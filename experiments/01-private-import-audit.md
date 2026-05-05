# Experiment 01 — `private import` audit on the top-50 leverage modules

## Goal

Convert non-API-affecting `import` statements to `private import` in the top-50 leverage modules. Each conversion shrinks the rebuild-aware critical path (`lakeprof report -r`) without touching the standard CP. Together they capture some fraction of the **91 % theoretical headroom** between today's rebuild CP (734–738 s) and the maximal-private floor (68 s).

## Why this experiment

- Only **1.3 % of mathlib's 33,002 imports are private today.** On the standard critical path itself, 96 % of edges are public.
- Maximal-private rebuild CP = **68 s** vs current 734 s — **−91 %** ceiling. Capturing 10–20 % of that ceiling = 60–130 s of CP, more than the entire payoff of splitting the top-5 Analysis modules.
- Mechanically: among incoming public imports into the top-30 CP modules, **329 are conversion candidates** (public imports from non-CP modules into CP modules — converting them shrinks rebuild blast without affecting standard CP).
- Per-PR localized work. No cross-file coordination. Each conversion is independently mergeable and reversible.

The catch: **`private import` only buys you anything against the rebuild-aware CP today.** Lake's actual cache still uses content hashing, so cache-hit rate won't move until experiment 02 + the eventual upstream Lake signature-hash work land. This experiment is the prep work that makes the eventual cache change effective.

## Inputs

- `mathlib-clean.log`
- [`leverage_analysis.py`](../leverage_analysis.py) — produces the leverage table; top-30 listed in §10 of [mathlib-build-deep-dive.md](../mathlib-build-deep-dive.md).
- [`phase7.py`](../phase7.py) — computes the headroom; cite as your before/after instrument.

## Procedure

1. Generate the top-50 leverage list. Run `leverage_analysis.py` against `mathlib-clean.log`. Output is sorted by `edits × blast_CP_seconds`. Top 10 entries from the most recent run, for sanity:
   - `Mathlib.SetTheory.Cardinal.Cofinality`
   - `Mathlib.Tactic.Translate.Core`
   - `Mathlib.SetTheory.Ordinal.Basic`
   - `Mathlib.SetTheory.Ordinal.Arithmetic`
   - `Mathlib.Tactic.Translate.ToDual`
   - `Mathlib.Logic.Basic`
   - `Mathlib.Order.Lattice`
   - `Mathlib.Data.List.Basic`
   - `Mathlib.Order.Cover`
   - `Mathlib.SetTheory.Ordinal.Family`

2. For each module on the list, classify each `import X` declaration. An import is a **conversion candidate** if `X`'s exposed names are referenced *only* in:
   - proof bodies (anything inside `:= by …` or `:= …` for theorems)
   - `private` declarations
   - `meta` blocks / macro implementations
   - internal helper definitions that are themselves not re-exported

   It is **not** a candidate if `X`'s names appear in:
   - any public theorem/def signature, structure field, instance type, class type
   - any `@[simp]` / `@[reducible]` def (because reducibility participates in elaboration of downstream signatures)
   - any notation or syntax declaration that is itself public
   - any `open X` at the top of the file (typically signals broad public reliance)

3. Convert candidates to `private import X`. Compile the module. The Lean compiler is the source of truth: if the module fails to elaborate, the import was load-bearing — revert.

4. Measure delta. Re-run `lakeprof report -r -i mathlib-clean.log` after each batch (20–30 conversions per batch is a reasonable PR size). Record the delta in rebuild-aware CP. The standard CP should not move.

5. Commit conversions in small batches on the worktree branch (`experiment/01-private-imports`). Don't bundle into one mega-commit — the changes are independent and small batches make later cherry-picking into an upstream-fork clone trivial. Commit message should cite the rebuild-CP delta. (No PR is opened from this clone — it has no `origin` remote.)

## Success criteria

- **Minimum useful:** ≥ 30 s of rebuild-aware CP recovered across the top-50 modules.
- **Strong:** ≥ 60 s recovered (≈ matching the K=5 Analysis-split payoff).
- **Stretch:** measurable per-commit blast-radius reduction once experiment 02's API-hash tool exists to validate it.

## Validation

- `lakeprof report -r -i mathlib-clean.log` before/after — the canonical metric.
- `phase7.py` to recompute the headroom delta.
- Sanity: standard CP (`lakeprof report -p`) must not move; if it does, you've changed something other than imports.

## Scope limits

- Don't touch modules outside the top-50 leverage list in this pass — diffuse effort gets diffuse results, and the per-module CP impact drops sharply past rank 50.
- Don't refactor module structure; only flip `import` → `private import` where it compiles. Restructuring is experiment 04's territory.
- If a conversion fails to compile, do not work around it by changing downstream modules. The right answer in that case is "this import is genuinely public" — leave it.

## Deliverables

- Local commits on `experiment/01-private-imports`, one batch per commit (~20–30 conversions per batch).
- A running tally (a markdown file at `experiments/01/AUDIT-LOG.md` in the worktree) of: module, imports flipped, rebuild-CP delta, commit SHA, status.
- A final report at `/Users/chelo/lakeprof-experiments/reports/01-private-imports.md` (using `experiments/REPORT_TEMPLATE.md`) with realized vs ceiling headroom captured and concrete next-step instructions. The report lives outside any worktree so it's discoverable after teardown.
