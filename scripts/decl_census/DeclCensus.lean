import Lean
import ImportGraph.Lean.Environment

/-!
# DeclCensus — type-aware per-declaration usage census for mathlib

Single-pass design (O(N + total-references), not O(N²)):

  Pass 1: walk env.constants.map₁ once. Per declaration:
    - module = env.getModuleFor? name
    - sig_refs = info.type.foldConsts ...
    - body_refs = info.value?.foldConsts ... (if present)
    Record these in a flat array.

  Pass 2: invert. For each (referrer, ref) edge in the sig/body sets,
    update sig_rev_modules[ref].insert referrer.module
    and intra_referrers[ref].insert referrer.name when same module.

  Pass 3: emit one JSON line per Mathlib declaration with:
    - external_users_sig, external_users_body  (cross-module module sets)
    - intra_module_referrers                   (same-module decl names)
    - has_docstring, name_pattern              (intent signals)
    - signature_referenced_by_intra            (precondition for encap clusters)

Output: one JSON per line on stdout. Stream — never accumulate output.
-/

open Lean

namespace DeclCensus

/-- Internal-decl filter: drop compiler-generated names (`Decl._cstage1`, etc.). -/
def isInternalDecl (n : Name) : Bool :=
  n.isInternal

/-- Decide if a name should be in the census output (Mathlib decls only). -/
def isMathlibDecl (env : Environment) (n : Name) : Bool :=
  match env.getModuleFor? n with
  | some m => m.toString.startsWith "Mathlib"
  | none   => false

/-- Cheap substring-contains for the small needles we care about. -/
def strContains (hay : String) (needle : String) : Bool :=
  (hay.splitOn needle).length != 1

/-- Classify a leaf-name + namespace into one of four name-pattern buckets. -/
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

/-- Given a fully-qualified name, return (namespace, leaf). -/
def splitName (n : Name) : String × String :=
  let leaf := match n with
    | .str _ s => s
    | _ => n.toString
  let ns := match n.getPrefix with
    | .anonymous => ""
    | p => p.toString
  (ns, leaf)

/-- Walk an Expr and collect referenced constants into a NameSet. -/
def referencedConsts (e : Expr) : NameSet :=
  e.foldConsts NameSet.empty fun n s => s.insert n

/-- Constant-kind classifier. -/
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

/-- Per-decl forward record. -/
structure ForwardRec where
  name : Name
  module : Name
  kind : String
  hasDocstring : Bool
  isPrivate : Bool
  sigRefs : NameSet
  bodyRefs : NameSet
deriving Inhabited

/-- JSON-string escape. Decl names won't contain control chars, so we cover
the common cases only. -/
def escapeJson (s : String) : String :=
  s.foldl (init := "") fun acc c =>
    match c with
    | '"'  => acc ++ "\\\""
    | '\\' => acc ++ "\\\\"
    | '\n' => acc ++ "\\n"
    | '\r' => acc ++ "\\r"
    | '\t' => acc ++ "\\t"
    | c    => acc.push c

def jsonStr (s : String) : String := "\"" ++ escapeJson s ++ "\""

/-- Build a JSON list of strings. -/
def jsonStrList (xs : List String) : String :=
  "[" ++ String.intercalate "," (xs.map jsonStr) ++ "]"

def jsonNameList (xs : List Name) : String :=
  jsonStrList (xs.map Name.toString)

end DeclCensus

namespace DeclCensus

/-- Phase 1 — walk all imported constants once, building per-decl records. -/
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
    if isInternalDecl n then
      nSkippedInternal := nSkippedInternal + 1
      continue
    if !isMathlibDecl env n then
      nSkippedNonMathlib := nSkippedNonMathlib + 1
      continue
    let module := (env.getModuleFor? n).getD `unknown
    let sigRefs := referencedConsts info.type
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
      sigRefs,
      bodyRefs,
    }
  IO.eprintln s!"[census] forward pass done: kept {out.size}, skipped internal {nSkippedInternal}, skipped non-Mathlib {nSkippedNonMathlib}"
  return out

/-- Phase 2 — build reverse maps: for each target, set of referrers (sig/body).

    Uses NameSet (RBTree) for the inner value, so each insert is O(log n)
    instead of array-copy O(n). For decls referenced by thousands of others
    (basic types like Eq, And, True), the array version was quadratic. -/
def buildReverse (recs : Array ForwardRec)
    : IO (NameMap NameSet × NameMap NameSet) := do
  let mut sigRev : NameMap NameSet := .empty
  let mut bodyRev : NameMap NameSet := .empty
  let mut i := 0
  for rec in recs do
    i := i + 1
    if i % 50000 == 0 then
      IO.eprintln s!"[census] reverse pass: processed {i} ..."
    for tgt in rec.sigRefs do
      let cur := sigRev.find? tgt |>.getD .empty
      sigRev := sigRev.insert tgt (cur.insert rec.name)
    for tgt in rec.bodyRefs do
      let cur := bodyRev.find? tgt |>.getD .empty
      bodyRev := bodyRev.insert tgt (cur.insert rec.name)
  IO.eprintln s!"[census] reverse pass done: sigRev size={sigRev.size}, bodyRev size={bodyRev.size}"
  return (sigRev, bodyRev)

/-- Phase 3 — emit JSONL with per-decl combined data.

Optimization notes:
  - For decls with no referrers in either map, skip the partition step and
    emit a minimal "no-users" JSON. Most decls have 0 external users.
  - We DROP the large `external_users_sig` and `external_users_body` lists.
    Keeping just the COUNTS plus the small `signature_referenced_by_intra`
    list (cluster-detection signal). Reduces output size ~10x and skips the
    expensive `Name.toString`-on-every-module work.
  - `intra_module_referrers` is also dropped — we keep `signature_referenced_by_intra`
    which is the cluster-relevant subset.
-/
def emitJson (env : Environment) (recs : Array ForwardRec)
    (sigRev bodyRev : NameMap NameSet) : IO Unit := do
  let stdout ← IO.getStdout
  let mut i := 0
  for rec in recs do
    i := i + 1
    if i % 20000 == 0 then
      IO.eprintln s!"[census] emit: {i} of {recs.size} ..."
    let (ns, leaf) := splitName rec.name
    let pattern := classifyNamePattern leaf ns
    let sigReferrers := sigRev.find? rec.name |>.getD .empty
    let bodyReferrers := bodyRev.find? rec.name |>.getD .empty

    -- Fast path: no referrers anywhere. Emit minimal JSON.
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

    -- Slow path: partition into intra-module vs cross-module module set.
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
    let _ := sigExtN -- suppress unused-warning
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

/-- Top-level orchestration. -/
def run (env : Environment) : IO Unit := do
  IO.eprintln s!"[census] env loaded: {env.constants.map₁.size} imported constants"
  let recs ← gatherForward env
  let (sigRev, bodyRev) ← buildReverse recs
  emitJson env recs sigRev bodyRev
  IO.eprintln "[census] done."

end DeclCensus
