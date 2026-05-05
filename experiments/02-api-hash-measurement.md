# Experiment 02 — API-diff measurement over commit history

## Goal

Build a syntactic API-diff tool for Lean 4 modules and run it across mathlib's last 1,500–2,000 commits. Produce the empirical answer to the load-bearing question: **what fraction of mathlib commits actually change a module's public API surface, vs only its internals?**

Without this number, the case for the upstream Lake signature-hash caching project (the biggest single multiplier in the analysis) is speculative. With it, the case becomes data-driven.

## Why this experiment

- Today's blast-radius numbers are all **content-hash based**. They assume any byte change in a module invalidates downstream caches.
- The thesis behind every API-hashing recommendation is: most commits change only proof bodies and internals, so an API-hash cache would skip the bulk of today's spurious invalidations.
- That thesis is currently **a guess**. We measured the *theoretical* headroom (91 %), not the *realized* fraction. This experiment closes that gap.

If, say, 75 % of commits leave the API hash unchanged for every module they touch, then API-hashed caching would skip 75 % of downstream invalidations and the upstream Lake project is justified on impact alone. If only 20 %, the value proposition is weaker and effort should redirect.

## Inputs

- mathlib4 git history (`git log` over the last ~2,000 commits).
- `mathlib-clean.log` for the dependency graph used to compute API-hash blast.
- Lean parser. Options: (a) parse via Lean itself by hooking into the elaborator (correct but slow and Lean-version-coupled); (b) a textual approximation that strips proof bodies and comments and hashes declaration headers (crude but fast). Start with (b); it matches the recommendation in §20 of the deep-dive.

## Procedure

### Phase 2a — build the API hasher (1 week)

For each `.lean` file, extract a normalized "API surface" string:

- Each `theorem` / `lemma` / `def` / `instance` / `class` / `structure` / `inductive` / `abbrev`: name, universe params, type signature, attributes. **Strip the body** — for `theorem`/`lemma`, drop everything after `:=` or `where`. For `def`, drop the body **unless** the def is `@[reducible]` or `abbrev` (those participate in downstream elaboration through their bodies; treat the body as part of the API).
- Each `instance`: full signature including priority annotations and any `@[default_instance]` attributes.
- Each `notation` / `syntax` / `macro` / `elab` / `infix` / `prefix` / `postfix`: full declaration (these expand at compile time and downstream consumers see the expansion).
- Each `open` / `export` / `import` / `private import` declaration: verbatim.
- All `@[…]` attributes attached to public declarations.

Strip from the API surface:
- Comments (`--`, `/-`, `/--` doc comments) — these don't affect compilation. (Open question: do `/--` doc-gen comments affect anything cache-relevant? Probably not, but verify.)
- Whitespace beyond what's needed to disambiguate tokens.
- Proof bodies as noted above.
- Anything inside a `private` declaration.
- `#check` / `#eval` / `example` blocks.

Hash the resulting normalized string. That's the module's API hash.

Validate against a handful of hand-picked commits where you know whether the API changed (e.g. a commit that adds a new lemma should change the API hash; a commit that only edits a proof body should not).

### Phase 2b — run over commit history (1–2 days)

For each of the last ~2,000 commits:

1. Identify the modules touched (from `git diff --name-only`).
2. For each touched module, compute the API hash at the parent commit and at the commit. Record whether they differ.
3. Compute the **API-hash blast radius**: invalidate only modules whose API changed (under content hashing the touched module is always invalidated; under API hashing it's invalidated iff its API changed). Propagate downstream the same way the existing blast computation does.
4. Record `(commit, content_blast_modules, content_blast_CP, api_blast_modules, api_blast_CP)`.

### Phase 2c — analysis (2–3 days)

Produce:
- Distribution of `api_blast_CP / content_blast_CP` over the commit window. Mean, median, p25/p50/p75/p90.
- The fraction of commits with `api_blast_modules == 0` (purely internal changes — these would be free under API hashing).
- Per-namespace breakdown: which namespaces have the highest internals-only commit fraction?
- Compare the API-hash blast distribution against the existing content-hash blast distribution from `churn_analysis.py`.

## Success criteria

- A working `api_hash.py` script that produces a stable hash for any `.lean` file.
- A CSV or JSONL artifact: one row per commit, both blast metrics.
- A short report (≤ 1,500 words) that answers: *"If Lake used API-hash caching, what fraction of mathlib commits would have zero downstream invalidations? What fraction would have <10 %?"*

## Scope limits

- **Don't try to be perfectly correct.** A textual approximation that under-counts API changes (says "API changed" when it didn't) is fine — it gives a conservative bound. Over-counting (saying "API unchanged" when it did) is the problem to avoid; bias toward false positives if unsure.
- **Don't try to handle Lean's full surface syntax.** Macros and tactic syntax can be hairy. If a file uses exotic syntax that the parser can't handle, log and skip — note it as a coverage gap.
- **Don't extend to multi-toolchain history.** mathlib bumps Lean toolchain occasionally; the API surface format may shift across bumps. Run within a single-toolchain window or note toolchain changes as discontinuities.
- **Don't ship this as production cache logic.** This is a measurement tool, not a Lake patch. The eventual upstream Lake change is a separate engineering project that consumes this experiment's output as evidence.

## Deliverables

- `api_hash.py` — single-file API hasher (in the worktree, committed on `experiment/02-api-hash`).
- `api_blast_history.{csv,jsonl}` — per-commit blast under both metrics (Phase 2b output).
- `api_diff_report.md` — analysis with the headline number (Phase 2c output, in the worktree).
- A figure `figs/11-api-vs-content-blast.svg` plotting the two distributions (Phase 2c output).
- A final report at `/Users/chelo/lakeprof-experiments/reports/02-api-hash.md` using `experiments/REPORT_TEMPLATE.md`, summarizing the headline finding and what to do next. Lives outside any worktree.

## Open questions to flag in the report

- How does the answer change if you treat `@[reducible]` defs' bodies as opaque vs included? (This is a real ambiguity in Lean's semantics.)
- Are there mathlib subdirectories where the internals-only fraction is dramatically higher or lower? (Hypothesis: `Tactic` may have a high API-change rate because many edits add new tactics; `Analysis` proofs may have a high internals-only rate.)
- Does the API-hash blast distribution correlate with the leverage table from experiment 01? If the top leverage modules are also the ones with high internals-only edit rates, that reinforces the joint case for (01) + (02) + upstream Lake.
