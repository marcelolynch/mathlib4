import Lean
import ImportGraph.Lean.Environment

/-!
# DeclCensus — type-aware per-declaration usage census for mathlib4

## What this tool produces

Given an imported `Environment` (typically the full Mathlib environment), this
tool walks every declaration once and emits one JSON line per Mathlib decl
on `stdout`. Each line carries the data needed to answer:

  * Where is this declaration defined? (`fq_name`, `defining_module`)
  * What kind of declaration is it? (`kind`: def, theorem, instance, …)
  * Does the author treat it as public API? (`has_docstring`, `name_pattern`)
  * Who uses it, and how? Split by:
      - `n_external_users` — distinct *modules* that reference it
      - `n_external_users_sig` / `n_external_users_body`
            — split by whether the reference appears in the referrer's type
              (signature, blocks privatization mechanically) or its body
              (proof / def value, sometimes re-derivable via alternate API)
      - `n_intra_module_refs` — referrers in the SAME module
      - `signature_referenced_by_intra` — the cluster signal: intra-module
            siblings whose *type* references this. High count ⇒ this decl
            is a "hub" with siblings forming a hideability cluster.

Concretely, the output schema is documented in the JSON-emit code below
(both fast and slow paths). The pipeline that consumes it
(`rerank_lean.py`) ranks candidates for `private`-keyword application as
the PR-38702 ("encapsulate the real numbers") shape.

## Why a meta-program rather than a regex over `.lean` files

Surface-text scans cannot resolve:

  * **Root-namespace identifiers** (`not_subsingleton`) — no qualified form.
  * **Dot-method calls** (`f.nontrivial` for `f : Function.Surjective`)
        — resolve via Lean's elaborator to `Function.Surjective.nontrivial`.
  * **Name collisions** — `swap_fst` exists in both `Mathlib.Data.TwoPointing`
        and `Mathlib.CategoryTheory.Limits.Shapes.BinaryProducts.BinaryFan`.
  * **Theorem proof bodies** — references to lemmas used inside `by`-blocks
        and proof terms only show up in `info.value?`, which by default
        returns `none` for theorems unless `allowOpaque := true` is passed.

This tool resolves all four by walking the elaborated `Expr` graph.

## Algorithm — three passes, O(N + total-references)

A naïve "for each decl, check who else mentions it" approach is O(N²).
Instead:

  Pass 1 — `gatherForward`
    Walk `env.constants.map₁` once. For each constant, capture:
      sigRefs  := Expr.foldConsts info.type
      bodyRefs := Expr.foldConsts info.value? (allowOpaque := true)
    Plus kind, docstring presence, private-keyword status, internal-name
    flag, and module. Push into a flat array.

  Pass 2 — `buildReverse`
    Invert the (referrer ⟶ {targets}) edges into two maps keyed by target:
      sigRev  : NameMap NameSet  (target ↦ set of decls referencing it in their TYPE)
      bodyRev : NameMap NameSet  (target ↦ set of decls referencing it in their BODY)
    Performance-critical choice: NameSet (RBTree). NameMap (Array Name)
    would be O(K²) per high-fanin target on push (Lean's immutable arrays
    do RC-aware copy-on-multi-ref); RBTree insert is O(log K) and dedupes
    naturally. For targets like `Eq.refl` or `True` with thousands of
    referrers, this is the difference between "completes in 30 s" and
    "stalls past 100 K of 350 K decls."

  Pass 3 — `emitJson`
    For each non-internal forward record, look up referrers in both reverse
    maps, partition by `env.getModuleFor?` into intra-module vs cross-module
    sets, and stream a JSON line. Output goes directly to stdout — never
    accumulate into a String buffer (would be O(N²) on String concat).

## Why we keep INTERNAL decls in the forward array

Lean's `Name.isInternal` matches compiler-generated names: equation-compiler
artifacts (`._eq_*`, `.proof_*`, `.match_*`), structure projections, and
crucially, **the `_initFn_*` decls produced by `initialize { … }` blocks**.

If we filtered internal decls out at the forward pass, references *from*
their bodies (`initialize registerBuiltinAttribute { add := fun ... ↦ … }`
closures) would never enter the reverse map, and the public decls those
closures call would appear to have no external users.

So we KEEP internal decls in the forward array (they contribute their refs
to the reverse map), and SKIP them only at JSON emit time so they don't
appear as candidates themselves.

## Performance (full mathlib, Lean 4.30)

  forward  ~1m35s   reads 759K imported constants, keeps 350K Mathlib decls
  reverse  ~30s     350K records × ~30 refs each ≈ 10 M edges
  emit     ~22m     per-decl JSON serialization with fast-path for 0-referrers
  total    ~24m     output is ~175 MB JSONL

Emit is the slow phase; it could be 1-2 orders faster with `Lean.Json.compress`
+ direct file I/O instead of `IO.FS.Stream.putStrLn` per line, but that's
a future optimization. Functional correctness is unaffected.

## Output

JSON Lines (one decl per line) on stdout. Stderr carries progress reports
of the form `[census] forward pass: processed N consts ...`. The
intermediate buffering is line-by-line so the consumer can stream-process
without loading the whole file.
-/

open Lean

namespace DeclCensus

/-! ## Filtering primitives -/

/--
Internal-decl filter: matches compiler-generated names whose visibility is
not directly controllable by the user (`Decl._cstage1`, `_proof_1`,
`._eq_*`, `_initFn_…`, equation-compiler artifacts, etc.).

We keep these in the forward array so their references contribute to the
reverse map (essential for `initialize`-block bodies — see file-level doc),
but skip them in the emit phase since they aren't candidates themselves.
-/
def isInternalDecl (n : Name) : Bool :=
  n.isInternal

/--
Restrict the census output to declarations defined in modules under the
`Mathlib.*` namespace. Excludes Lean core, Batteries, Cli, Aesop,
`ImportGraph`, `proofwidgets`, `LeanSearchClient`, `plausible`, and `Qq`.
The candidate queue downstream targets only Mathlib, so anything outside
is noise.

Returns `false` for decls without a module of origin (rare — only synthetic
declarations created at runtime).
-/
def isMathlibDecl (env : Environment) (n : Name) : Bool :=
  match env.getModuleFor? n with
  | some m => m.toString.startsWith "Mathlib"
  | none   => false

/-! ## Name-pattern classification -/

/--
Substring containment, used by the small set of needles in `classifyNamePattern`.

`String` doesn't expose `containsSubstr` in the version of Lean we target,
and `String.splitOn` is the tersest equivalent: a string contains `needle`
iff splitting on it produces ≠1 piece. (1 piece means no match; >1 means
at least one match boundary was found.)
-/
def strContains (hay : String) (needle : String) : Bool :=
  (hay.splitOn needle).length != 1

/--
Classify a leaf-name + namespace into one of four `name_pattern` buckets.
Used downstream to apply the framework correction: defs/abbrevs hide freely;
theorems hide ONLY when the name pattern is non-`normal` AND there's no
docstring (i.e., the author has marked the decl as internal-by-naming).

  * `underscore_prefix` — leaf starts with `_`. Almost always elaborator-
        synthesized or hand-named-internal (`_root_`-style).
  * `aux` — leaf contains "aux" (case-insensitive). Authors use this
        suffix conventionally for auxiliary lemmas.
  * `internal_namespace` — namespace path contains "internal", "impl",
        or "private". Decl belongs to a deliberately-internal namespace.
  * `normal` — none of the above. Default; theorems with this pattern
        are treated as public API by the ranking layer.

The classification is deliberately coarse — it's a *gate*, not a
*classification*, so over-classifying as `normal` is the safe failure mode
(passes more theorems through the no-docstring filter, which is itself
strict).
-/
def classifyNamePattern (leaf : String) (ns : String) : String :=
  if leaf.startsWith "_" then "underscore_prefix"
  else if strContains leaf.toLower "aux" then "aux"
  else
    let ns_lower := ns.toLower
    if strContains ns_lower "internal"
       || strContains ns_lower "impl"
       || strContains ns_lower "private" then
      "internal_namespace"
    else "normal"

/--
Split a fully-qualified name into `(namespace, leaf)`.

  `Mathlib.Data.Real.Basic.cauchy_add`  ↦  ("Mathlib.Data.Real.Basic", "cauchy_add")
  `not_subsingleton`                    ↦  ("",                       "not_subsingleton")
  `Foo.bar.baz` (with leaf `baz`)       ↦  ("Foo.bar",                 "baz")

Used to feed `classifyNamePattern` and to populate the `namespace` and
`leaf` JSON fields. Note: for nested anonymous names the result is just
`n.toString`, but those don't appear in the Mathlib subset we emit.
-/
def splitName (n : Name) : String × String :=
  let leaf := match n with
    | .str _ s => s
    | _ => n.toString
  let ns := match n.getPrefix with
    | .anonymous => ""
    | p => p.toString
  (ns, leaf)

/-! ## Reference extraction -/

/--
Walk an `Expr` and collect all referenced constants into a `NameSet`.

`Expr.foldConsts` traverses the expression tree once, calling the supplied
function on every `Expr.const` node it encounters. The default RBTree-backed
`NameSet` deduplicates, so even an expression that mentions `Eq.refl` 50
times produces a singleton set. Used for both signature (`info.type`) and
body (`info.value?`) reference extraction.
-/
def referencedConsts (e : Expr) : NameSet :=
  e.foldConsts NameSet.empty fun n s => s.insert n

/--
Categorize a `ConstantInfo` into one of nine kind strings used by the
ranking pipeline. The kinds map 1:1 to Lean's `ConstantInfo` constructors:

  | constructor           | kind        | comment |
  |-----------------------|-------------|---------|
  | `thmInfo`             | `theorem`   | proof; body opaque by default |
  | `defnInfo`            | `def`       | computational definition |
  | `axiomInfo`           | `axiom`     | postulated truth |
  | `opaqueInfo`          | `opaque`    | sealed defn (no unfold) |
  | `inductInfo`          | `inductive` | type former |
  | `ctorInfo`            | `ctor`      | inductive constructor |
  | `recInfo`             | `rec`       | recursor / `casesOn` synthesized |
  | `quotInfo`            | `quot`      | `Quot.lift` & friends |

Note: `def`, `abbrev`, and `instance` all show up as `defnInfo` here.
`abbrev` is distinguishable via `defnInfo.hints = .abbrev`, but the
ranking layer treats them identically, so we don't bother. Instances
are distinguishable via `Lean.isInstance env n`, which the ranking layer
calls separately if needed.
-/
def kindOf (info : ConstantInfo) : String :=
  match info with
  | .thmInfo _       => "theorem"
  | .defnInfo _      => "def"
  | .axiomInfo _     => "axiom"
  | .opaqueInfo _    => "opaque"
  | .inductInfo _    => "inductive"
  | .ctorInfo _      => "ctor"
  | .recInfo _       => "rec"
  | .quotInfo _      => "quot"

/-! ## Per-decl forward record (the pass-1 output type) -/

/--
One row per Mathlib (or kept-internal) declaration, populated during the
forward pass. Used as input to both the reverse-map build and the JSON emit.

Memory-conscious: we store the two reference sets directly here. For full
mathlib (~350 K decls × ~30 refs each ≈ 10 M `Name`s in NameSet form), this
is ~hundreds of MB of RBTree nodes during the run — acceptable, since the
machine has GBs and the data is touched once per pass and discarded.
-/
structure ForwardRec where
  /-- Fully-qualified declaration name. -/
  name : Name
  /-- The Mathlib module where this decl is defined. -/
  module : Name
  /-- Stringified `ConstantInfo` constructor, see `kindOf`. -/
  kind : String
  /-- Whether the decl has a `/-- ... -/` docstring. (Mathlib's API gate
  is a docstring-presence linter, so this is the cleanest "author marked
  this as public API" signal we have.) -/
  hasDocstring : Bool
  /-- True if the decl was already declared with the `private` keyword
  (its name is mangled `_private.<module>.<n>.X`). -/
  isPrivate : Bool
  /-- True when the decl name is internal (e.g., `_initFn_*`, match-compiler
  artifacts). Internal decls are kept in the forward array so their outgoing
  references contribute to the reverse map (this is how we catch the
  `initialize { add := fun ... ↦ ... }` pattern), but they are skipped
  during JSON emission. -/
  isInternal : Bool
  /-- Constants referenced in `info.type` — i.e., the signature. -/
  sigRefs : NameSet
  /-- Constants referenced in `info.value? (allowOpaque := true)` — the
  proof body for theorems, the value for defs. -/
  bodyRefs : NameSet
deriving Inhabited

/-! ## JSON emission helpers (no library import; minimal hand-rolled) -/

/--
JSON-string escape for the limited set of characters that can occur in
declaration names and the small JSON values we emit. We do NOT handle
the full Unicode escape range — decl names won't contain control chars
and won't be parsed by anything that requires it. Keeps the hot loop
fast (no allocation in the common case where escape is unnecessary).
-/
def escapeJson (s : String) : String :=
  s.foldl (init := "") fun acc c =>
    match c with
    | '"'  => acc ++ "\\\""
    | '\\' => acc ++ "\\\\"
    | '\n' => acc ++ "\\n"
    | '\r' => acc ++ "\\r"
    | '\t' => acc ++ "\\t"
    | c    => acc.push c

/-- Wrap a string as a JSON string literal: `"value"`. -/
def jsonStr (s : String) : String := "\"" ++ escapeJson s ++ "\""

/-- Build a JSON list of strings: `["a","b","c"]`. -/
def jsonStrList (xs : List String) : String :=
  "[" ++ String.intercalate "," (xs.map jsonStr) ++ "]"

/-- Build a JSON list of names by stringifying each. -/
def jsonNameList (xs : List Name) : String :=
  jsonStrList (xs.map Name.toString)

end DeclCensus

namespace DeclCensus

/-! ## Pass 1 — Forward walk -/

/--
Walk every constant in `env.constants.map₁` once and produce one
`ForwardRec` per declaration we want to track.

Filter logic:
  * Decls outside `Mathlib.*` modules → skipped entirely (out of scope).
  * Decls with internal names (`_initFn_*`, `_proof_*`, etc.) → KEPT, with
    `isInternal := true`, so their outgoing references contribute to the
    reverse map. The emit phase will drop them.
  * Everything else → emitted as a regular forward record.

Reference extraction uses `info.value? (allowOpaque := true)`. This is
load-bearing: by default `value?` returns `none` for `thmInfo` (Lean's
proof-irrelevance optimization). Without `allowOpaque`, every theorem
appears to have an empty body and the body-reference graph is empty.

Diagnostic output: progress every 50 K decls; a final summary line with
total kept, internal-but-kept count, and skipped non-Mathlib count.
-/
def gatherForward (env : Environment) : IO (Array ForwardRec) := do
  let mut out : Array ForwardRec := #[]
  let constants := env.constants.map₁
  let mut i := 0
  let mut nSkippedInternal := 0
  let mut nSkippedNonMathlib := 0
  for info in constants.values do
    i := i + 1
    if i % 50000 == 0 then
      IO.eprintln s!"[census] forward pass: processed {i} consts ..."
    let n := info.name
    -- Internal-named Mathlib decls are KEPT in the forward array so their
    -- outgoing references populate the reverse map. (Critical:
    -- `initialize { add := fun ... }` creates `_initFn_*` decls whose
    -- bodies reference public decls — without these in the reverse map,
    -- we under-count external users of those public decls.) The internal
    -- decls themselves will be filtered out at emit time so they don't
    -- appear as candidates for privatization.
    let isInt := isInternalDecl n
    if !isMathlibDecl env n then
      nSkippedNonMathlib := nSkippedNonMathlib + 1
      continue
    if isInt then
      nSkippedInternal := nSkippedInternal + 1  -- counted but kept
    let module := (env.getModuleFor? n).getD `unknown
    -- `referencedConsts` walks the Expr tree and gathers `Expr.const` heads.
    let sigRefs := referencedConsts info.type
    -- `allowOpaque := true` is required for theorem bodies — otherwise
    -- `value?` returns `none` and theorem proof bodies contribute zero
    -- references to the reverse map.
    let bodyRefs :=
      match info.value? (allowOpaque := true) with
      | some v => referencedConsts v
      | none   => NameSet.empty
    let docOpt ← Lean.findDocString? env n
    out := out.push {
      name := n,
      module,
      kind := kindOf info,
      hasDocstring := docOpt.isSome,
      isPrivate := Lean.isPrivateName n,
      isInternal := isInt,
      sigRefs,
      bodyRefs,
    }
  IO.eprintln s!"[census] forward pass done: kept {out.size} \
                 (internal kept-for-reverse: {nSkippedInternal}), \
                 skipped non-Mathlib {nSkippedNonMathlib}"
  return out

/-! ## Pass 2 — Reverse-map construction -/

/--
Build two reverse maps from the forward records:

  * `sigRev  : NameMap NameSet`  — target ↦ {referrers whose TYPE mentions target}
  * `bodyRev : NameMap NameSet`  — target ↦ {referrers whose BODY mentions target}

Why a `NameSet` (RBTree) value rather than `Array Name`:
For decls with thousands of referrers (basic types like `Eq`, `True`,
`Nat`), each `Array.push` would copy the array (Lean's persistent arrays
RC-clone on multi-ref). For K referrers per target that's K² total work.
RBTree insert is O(log K), and the set semantics dedupe naturally. This
is the difference between "30 seconds" and "stalls past 100K decls".

The symmetric structure (sig vs body) is preserved end-to-end so the
emit phase can split `n_external_users` into `n_external_users_sig` and
`n_external_users_body` — a load-bearing distinction for the ranking
layer (signature uses block privatization mechanically; body-only uses
sometimes don't).

Diagnostic output: progress every 50 K input records; a final summary
line with the size of each reverse map (number of distinct targets
referenced).
-/
def buildReverse (recs : Array ForwardRec)
    : IO (NameMap NameSet × NameMap NameSet) := do
  let mut sigRev : NameMap NameSet := .empty
  let mut bodyRev : NameMap NameSet := .empty
  let mut i := 0
  for rec in recs do
    i := i + 1
    if i % 50000 == 0 then
      IO.eprintln s!"[census] reverse pass: processed {i} ..."
    -- For every (referrer, target) edge in the signature graph, add the
    -- referrer's NAME (not module) to sigRev[target]. We dedupe later
    -- by module at emit time; storing names here also lets us emit the
    -- `signature_referenced_by_intra` field without extra bookkeeping.
    for tgt in rec.sigRefs do
      let cur := sigRev.find? tgt |>.getD .empty
      sigRev := sigRev.insert tgt (cur.insert rec.name)
    for tgt in rec.bodyRefs do
      let cur := bodyRev.find? tgt |>.getD .empty
      bodyRev := bodyRev.insert tgt (cur.insert rec.name)
  IO.eprintln s!"[census] reverse pass done: sigRev size={sigRev.size}, bodyRev size={bodyRev.size}"
  return (sigRev, bodyRev)

/-! ## Pass 3 — JSON emission

Per-line JSON-Lines output to stdout. The schema below is fixed by the
downstream consumer (`rerank_lean.py`).

### Schema

  {
    "fq_name":                    string  — qualified name
    "defining_module":            string  — module where declared
    "kind":                       string  — see kindOf
    "namespace":                  string  — dotted prefix
    "leaf":                       string  — final segment
    "is_private":                 bool    — `private` keyword in source
    "has_docstring":              bool    — has /-- ... -/
    "name_pattern":               string  — see classifyNamePattern
    "n_external_users":           number  — distinct cross-module referrers (modules)
    "n_external_users_sig":       number  — signature-only count
    "n_external_users_body":      number  — body-only count
    "n_intra_module_refs":        number  — same-module referrers (decls, not modules)
    "signature_referenced_by_intra":  array of names  — intra-module refs via TYPE
    "n_signature_refs":           number  — len of the above array (cluster signal)
    "n_sig_refs_fwd":             number  — diagnostic: this decl's outgoing sig-refs
    "n_body_refs_fwd":            number  — diagnostic: this decl's outgoing body-refs
  }

The `_users_` counts are **module-level** (deduplicated by
`env.getModuleFor?`). The `_intra_` and `signature_referenced_by_intra`
fields carry decl names because intra-module clustering is the unit of
analysis for the encapsulation-hub tier.

### Optimization notes

* Fast path. The vast majority of decls have ZERO referrers (no
  cross-module use, no intra-module use). We detect this in O(1) via
  `sigReferrers.isEmpty && bodyReferrers.isEmpty` and emit a stripped
  JSON without the partition step. Cuts ~70% of emit time.

* Slow path. Partition referrers by module (intra vs cross). Two
  separate maps are maintained because we report sig-vs-body external
  splits but only sig refs for intra (the cluster signal — body refs
  inside a module are noise for clustering).

* Drop the full external-user lists. Earlier versions emitted
  `external_users_sig: [m1, m2, ...]` arrays; for high-fanin decls this
  was 100s of KB per row. We keep just the COUNTS plus the small
  `signature_referenced_by_intra` list, which is the cluster signal.
  Output went from ~1.5 GB to ~175 MB.

* Stream output. `IO.FS.Stream.putStrLn` per line, never accumulate
  into a String buffer (would be O(N²) on String concat).
-/
def emitJson (env : Environment) (recs : Array ForwardRec)
    (sigRev bodyRev : NameMap NameSet) : IO Unit := do
  let stdout ← IO.getStdout
  let mut i := 0
  let mut nSkippedEmit := 0
  for rec in recs do
    i := i + 1
    if i % 20000 == 0 then
      IO.eprintln s!"[census] emit: {i} of {recs.size} ..."
    -- Internal decls were kept in the forward array purely so their
    -- references populate the reverse map. They are not candidates
    -- themselves; skip emit. (The emit-phase counter `nSkippedEmit`
    -- should match `nSkippedInternal` from the forward pass.)
    if rec.isInternal then
      nSkippedEmit := nSkippedEmit + 1
      continue
    let (ns, leaf) := splitName rec.name
    let pattern := classifyNamePattern leaf ns
    let sigReferrers := sigRev.find? rec.name |>.getD .empty
    let bodyReferrers := bodyRev.find? rec.name |>.getD .empty

    -- Fast path: no referrers anywhere. Emit minimal JSON without
    -- doing the per-referrer module lookup. Most decls hit this path;
    -- it's the dominant cost saver.
    if sigReferrers.isEmpty && bodyReferrers.isEmpty then
      let json :=
        "{"
        ++ "\"fq_name\":" ++ jsonStr rec.name.toString
        ++ ",\"defining_module\":" ++ jsonStr rec.module.toString
        ++ ",\"kind\":" ++ jsonStr rec.kind
        ++ ",\"namespace\":" ++ jsonStr ns
        ++ ",\"leaf\":" ++ jsonStr leaf
        ++ ",\"is_private\":" ++ (if rec.isPrivate then "true" else "false")
        ++ ",\"has_docstring\":" ++ (if rec.hasDocstring then "true" else "false")
        ++ ",\"name_pattern\":" ++ jsonStr pattern
        ++ ",\"n_external_users\":0"
        ++ ",\"n_external_users_sig\":0"
        ++ ",\"n_external_users_body\":0"
        ++ ",\"n_intra_module_refs\":0"
        ++ ",\"signature_referenced_by_intra\":[]"
        ++ ",\"n_signature_refs\":0"
        ++ ",\"n_sig_refs_fwd\":" ++ toString rec.sigRefs.size
        ++ ",\"n_body_refs_fwd\":" ++ toString rec.bodyRefs.size
        ++ "}"
      stdout.putStrLn json
      continue

    -- Slow path: partition referrers into intra-module and cross-module.
    -- For cross-module we collect the *module set* (deduplicated) since
    -- the candidate ranking is module-level. For intra-module we keep
    -- the *decl names* so we can serialize `signature_referenced_by_intra`.
    let mut sigIntra  : NameSet := .empty
    let mut sigExt    : NameSet := .empty   -- module set, dedupe
    let mut sigExtN   : Nat := 0            -- alias for size at end
    for r in sigReferrers do
      let m := (env.getModuleFor? r).getD `unknown
      if m == rec.module then
        sigIntra := sigIntra.insert r
      else
        sigExt := sigExt.insert m
    let mut bodyIntra : NameSet := .empty
    let mut bodyExt   : NameSet := .empty
    for r in bodyReferrers do
      let m := (env.getModuleFor? r).getD `unknown
      if m == rec.module then
        bodyIntra := bodyIntra.insert r
      else
        bodyExt := bodyExt.insert m
    let _ := sigExtN -- suppress unused-variable warning
    -- `n_external_users` is the union of sig-external and body-external
    -- module sets. A module that uses the decl in both a signature and
    -- a body counts once, but we still report sig and body counts
    -- separately for the ranking layer's sig-vs-body refinement.
    let allExt := sigExt.union bodyExt
    let nIntra := (sigIntra.union bodyIntra).size
    let json :=
      "{"
      ++ "\"fq_name\":" ++ jsonStr rec.name.toString
      ++ ",\"defining_module\":" ++ jsonStr rec.module.toString
      ++ ",\"kind\":" ++ jsonStr rec.kind
      ++ ",\"namespace\":" ++ jsonStr ns
      ++ ",\"leaf\":" ++ jsonStr leaf
      ++ ",\"is_private\":" ++ (if rec.isPrivate then "true" else "false")
      ++ ",\"has_docstring\":" ++ (if rec.hasDocstring then "true" else "false")
      ++ ",\"name_pattern\":" ++ jsonStr pattern
      ++ ",\"n_external_users\":" ++ toString allExt.size
      ++ ",\"n_external_users_sig\":" ++ toString sigExt.size
      ++ ",\"n_external_users_body\":" ++ toString bodyExt.size
      ++ ",\"n_intra_module_refs\":" ++ toString nIntra
      ++ ",\"signature_referenced_by_intra\":" ++ jsonNameList sigIntra.toList
      ++ ",\"n_signature_refs\":" ++ toString sigIntra.size
      ++ ",\"n_sig_refs_fwd\":" ++ toString rec.sigRefs.size
      ++ ",\"n_body_refs_fwd\":" ++ toString rec.bodyRefs.size
      ++ "}"
    stdout.putStrLn json
  IO.eprintln s!"[census] emit done: {i} processed, {nSkippedEmit} internal decls skipped"

/-! ## Top-level orchestration -/

/--
Run the three-pass census against an already-imported `Environment`. Caller
is responsible for `initSearchPath` + `withImportModules` to produce `env`.
See `Main.lean` for the standard full-mathlib entry point.
-/
def run (env : Environment) : IO Unit := do
  IO.eprintln s!"[census] env loaded: {env.constants.map₁.size} imported constants"
  let recs ← gatherForward env
  let (sigRev, bodyRev) ← buildReverse recs
  emitJson env recs sigRev bodyRev
  IO.eprintln "[census] done."

end DeclCensus
