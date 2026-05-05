# Experiment 04 — Targeted refactor of the top-5 Analysis CP modules

## Goal

Split the five heaviest Analysis modules on the clean-build critical path into smaller, parallelizable pieces, recovering ~85 s of CP (≈11 % of the 750 s clean-build floor).

## Why this experiment

- 62 % of the clean-build CP lives inside `Mathlib.Analysis`. The top-5 CP modules account for 126 s of unavoidable wall-clock.
- The bottleneck what-if (zero-out top-K CP modules) shows:
  - K=1 → 14 s recovered
  - K=3 → 60 s
  - K=5 → 86 s
  - K=10 → still 86 s (plateau — alternative chains take over)
- So K=5 is **exactly the right depth.** Past that, returns are zero until parallel chains are also addressed; below it, you're leaving recoverable CP on the table.
- This is the only experiment in the set that targets *clean-build* CP (every other lever targets incremental rebuild). It's worth doing because clean rebuilds happen on every CI runner that misses the cache and on every contributor's first build.

## Inputs

The five modules, with their CP contribution:

| s on CP | module | self-time |
|---:|---|---:|
| 32.0 | `Mathlib.Analysis.Distribution.SchwartzSpace.Basic` | (look up in `mathlib-clean.log`) |
| 26.0 | `Mathlib.Analysis.Normed.Module.Multilinear.Basic` | |
| 26.0 | `Mathlib.Analysis.Analytic.Constructions` | |
| 22.0 | `Mathlib.Analysis.Analytic.Basic` | |
| 20.0 | `Mathlib.Analysis.Calculus.ContDiff.Defs` | |

## Procedure

For each of the five modules, in priority order:

### Step 1 — characterize the module's content

- Read the module. Count declarations by kind (defs, lemmas, instances, classes).
- Identify natural cleavage planes. Common patterns that split well:
  - **Defs separated from lemmas about them.** A def + 30 lemmas can become a Defs module + a Lemmas module, with Lemmas importing Defs. Downstream consumers that only need the def avoid the lemma elaboration cost.
  - **Multiple unrelated topics in one module.** Sometimes a module bundles two or three logically-distinct theories. Each can become its own module.
  - **Cap-stone theorems separated from the API.** A "main theorem" at the bottom of a module can sometimes move to a downstream module without disturbing the API.
- Identify what would **block** a split: anything that introduces a cycle (a lemma whose statement uses something defined later in the same file in a way that would require mutual import).

### Step 2 — propose a split

Write a 1-page sketch *before* editing: which declarations move where, what the new import graph looks like, and what the predicted CP impact is. Use `lakeprof report -p` to verify the predicted CP impact: simulate the split by manually editing the dependency graph and recomputing the CP.

The split is worth doing iff:
- The module's self-time on the CP drops by ≥ 60 %.
- No new module added to the split is itself on the new CP at > self_time / 3 of the original.
- The split doesn't introduce cycles or require relocating definitions across the wider Analysis hierarchy.

### Step 3 — execute the split as local commits

- One commit per module split. Don't bundle multiple modules into one commit.
- Commit message format: `refactor(Analysis): split Foo into Foo.Defs and Foo.Lemmas (CP -X s)`.
- Commit body includes before/after CP, the dependency-graph diff, and a list of any downstream modules whose imports needed updating.
- No PR is opened from this clone — it has no `origin` remote. When ready to upstream, cherry-pick these commits into a separate mathlib clone that has a fork remote.

### Step 4 — measure

After each merged split, re-record `lakeprof record lake build` (this is the only experiment in the set that requires a fresh build to validate; the graph genuinely changed). Compare the new CP to the predicted one.

## Success criteria

- **Minimum useful:** K=3 splits land, ≥ 50 s of CP recovered.
- **Strong:** all 5 land, 80–86 s recovered (matching the analytical prediction).
- **Validation:** re-recorded `lakeprof.log` confirms within ±5 s.

## Scope limits

- **Hard cap at K=5.** Do not propose splitting modules ranked 6+ on the CP. The data is unambiguous: returns plateau at K=5 until parallel chains are addressed too, which would require a much larger coordinated refactor.
- **Don't relocate declarations across the Analysis hierarchy.** A split that moves `Foo` into `Foo.Defs` + `Foo.Lemmas` is good; a split that moves declarations into `Mathlib.Topology` to "untangle" the graph is out of scope and likely to break things.
- **Don't merge modules.** Some of these modules might look like they want to absorb their neighbors. Resist; the goal is *more* parallelism, not less.
- **Don't try to fix the namespace SCC** while you're in there. Cycle untangling is a separate question and the data shows surgical fixes don't work anyway.

## Deliverables

- 5 local commits on `experiment/04-analysis-split`, one per module.
- One split-proposal markdown per module in the worktree at `experiments/04/PROPOSAL-<Module>.md`, written before any source edits.
- A final report at `/Users/chelo/lakeprof-experiments/reports/04-analysis-split.md` (using `experiments/REPORT_TEMPLATE.md`) with measured vs predicted CP delta per split and concrete next-step instructions. Lives outside any worktree.
- Updated `mathlib-clean.log` after all splits land, so subsequent leverage / blast / churn analyses reflect the new graph shape.

## Risk notes

- Domain expertise required. Splitting Analysis files badly can produce uglier downstream import lists. Consult mathlib's Analysis maintainers before merging.
- Lean's elaborator sometimes performs better with related declarations in the same file (shared elaboration state). Verify that `self_time(Defs) + self_time(Lemmas) ≤ 1.1 × self_time(original)`. If splitting *increases* total work by more than 10 %, the split costs more wall-clock than it saves.
