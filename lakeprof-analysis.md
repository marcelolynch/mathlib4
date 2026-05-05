# mathlib4 build-graph and critical-path analysis

Recorded clean build of mathlib4 @ commit `36a97460` on 18-core Apple Silicon, 2026-05-04. 8,393 jobs in 32m46s wall-clock. Log: `mathlib-clean.log`. All scripts referenced are in this directory.

## Executive summary

The build's structural floor is **750 s** under any amount of parallelism, set by a 113-module chain through `Order → Topology → Algebra → Analysis → Calculus → Manifold → Distribution → Fourier → ModularForms`. **62 % of that floor lives inside `Mathlib.Analysis`** alone.

**The build cannot be sharded out of this floor.** Two-phase "build foundation, then downstream" schemes are 15–35 % *slower* than monolithic. Naive namespace-level federation without API-aware caching is *strictly worse* than today's file-content cache.

The four levers, ranked by leverage:

1. **`private import` adoption is the highest-impact change available today.** Only 1.3 % of mathlib's 33,651 import edges are private; 96 % of edges on the critical path are public. A theoretical lower bound under maximal `private import` adoption shrinks the rebuild critical path from 734 s to **68 s — a 91 % reduction**. Even partial adoption (top-50 modules) is worth tens of seconds of CP and dramatically reduces rebuild blast.
2. **Lake cache keyed on signature hash, not file content.** Mathlib's foundation churns hard (median commit invalidates 36 % of CP under content hashing). API-hashing would make most of those invalidations free. This is upstream Lean/Lake work.
3. **Targeted CP refactor inside `Mathlib.Analysis`.** Five modules (`SchwartzSpace.Basic`, `Multilinear.Basic`, `Analytic.Constructions`, `Analytic.Basic`, `ContDiff.Defs`) carry ~10 % of the CP. Diminishing returns past K=5 — splitting 5 specific modules is worth ~85 s of floor; further splits move a different chain into critical position.
4. **Hardware spend past 32 cores has poor ROI.** True saturation point is ~192 cores (12.5 min wall-clock floor). Practical knee is ~96–112 cores. 32 cores buys ~20 min wall-clock — the sensible target.

The first lever requires no infrastructure work and is incrementally PR-mergeable. The second is a multi-month upstream project. The third is one-time refactoring with bounded payoff. The fourth is purchasing.

---

## Phase 2 — Baseline metrics

**Total work**: 33,075 s ≈ 9 h 11 m of single-CPU work.
**Critical path floor (∞ cores)**: 750.9 s.
**Speedup ceiling**: 33,075 / 751 ≈ **44×**.
**Recorded 18-core wall-clock**: 1,966 s ≈ 32 m 46 s = ~16.8× of the 1-CPU floor (38 % of theoretical).

### Doubling sweep (`lakeprof report -s`)

| #CPUs | sim time | CPU% |
|---:|---:|---:|
| 1 | 33,075 s | 100 % |
| 2 | 16,543 s | 200 % |
| 4 | 8,281 s | 399 % |
| 8 | 4,158 s | 795 % |
| 16 | 2,128 s | 1554 % |
| 32 | 1,189 s | 2781 % |
| 64 | 838 s | 3949 % |
| 128 | 752 s | 4398 % |
| 256 | 751 s | 4405 % |

### Finer linear sweep (`sweep.py`)

| cores | time | cores | time |
|---:|---:|---:|---:|
| 64 | 838 s | 120 | 752 s |
| 80 | 793 s | 128 | 752 s |
| 96 | 763 s | 160 | 752 s |
| 104 | 760 s | **192** | **751 s** ← exact floor |
| 112 | 753 s | 256 | 751 s |

Doubling sweep underestimates the saturation point. **True minimum cores to hit floor: 192.** Practical knee at 96–112; 16-cores-per-additional-second economics break down past 112.

### Rebuild-aware critical path (`-r`)

Standard CP: 750.9 s.
Rebuild-aware CP: **737.9 s** (1.7 % shorter).

The 13 s gap is the value of mathlib's *current* `private`/`meta` import discipline. As shown in Phase 7, this is leaving 90 %+ of the available headroom on the table.

---

## Phase 3 — Parallelism profile

How long the build runs with N tasks concurrently active under infinite cores:

| concurrent | wall-clock | share |
|---:|---:|---:|
| 0–7 | 24 s | 3.2 % |
| 8–15 | 58 s | 7.7 % |
| 16–31 | 236 s | **31.4 %** |
| 32–47 | 156 s | 20.8 % |
| 48–63 | 106 s | 14.1 % |
| 64–95 | 126 s | 16.8 % |
| 96–127 | 42 s | 5.5 % |
| 128–191 | 4 s | 0.5 % |

**42 % of the wall-clock floor has fewer than 32 tasks running.** The wide zone (≥96 concurrent) is only 6 %. This is why the speedup curve flattens hard — most of the build is structurally narrow, not throughput-limited.

Implication: adding cores past ~32 helps less than commonly assumed. Further reduction requires either shortening the critical path (refactor) or breaking dependency chains (`private import`).

---

## Phase 4 — Bottleneck what-if

Zero out the time of the top-K modules on the standard critical path; recompute the floor.

| K | new floor | gain | marginal |
|---:|---:|---:|---:|
| 0 | 751 s | — | — |
| 1 | 736 s | 14 s | 14 s |
| 3 | 691 s | 60 s | 22 s |
| 5 | 665 s | 86 s | 13 s |
| 10 | 665 s | 86 s | **0** |
| 25 | 652 s | 99 s | <1 s |
| 50 | 628 s | 123 s | <1 s |

**Diminishing returns hit at K=5.** From K=5 to K=10, removing more modules from the current critical path produces zero gain — alternative chains take over. This is a hard ceiling on "split the heaviest CP modules" as a strategy. Five splits get you ~85 s; more is wasted unless you also shorten the alternative chains, which requires data we don't have without rerunning what-ifs on the alternative paths.

The five highest-leverage CP modules to split:

| s | module |
|---:|---|
| 32.0 | `Mathlib.Analysis.Distribution.SchwartzSpace.Basic` |
| 26.0 | `Mathlib.Analysis.Normed.Module.Multilinear.Basic` |
| 26.0 | `Mathlib.Analysis.Analytic.Constructions` |
| 22.0 | `Mathlib.Analysis.Analytic.Basic` |
| 20.0 | `Mathlib.Analysis.Calculus.ContDiff.Defs` |

All in `Mathlib.Analysis`, all >20 s of self-time on the CP.

---

## Phase 5 — Churn × blast-radius leverage

Across the last 1,871 commits with mathlib edits:

### Per-commit blast distribution (content-hash invalidation)

| quantile | edited mods | invalidated mods | rebuild work | rebuild CP | % of full CP |
|---|---:|---:|---:|---:|---:|
| p25 | 1 | 14 | 69 s | 34 s | 4.6 % |
| p50 | 2 | 507 | 2,778 s | 269 s | **35.9 %** |
| p75 | 4 | 2,604 | 13,436 s | 520 s | 69.3 % |
| p90 | 7 | 6,460 | 29,020 s | 667 s | 88.9 % |
| p95 | 13 | 7,363 | 31,832 s | 725 s | 96.7 % |
| p99 | 133 | 7,972 | 32,891 s | 746 s | 99.5 % |

**Median commit invalidates 36 % of the critical path.** Only the bottom 25 % of commits are leaf-like (under 5 % of CP). The "stable foundation, churning leaves" intuition is wrong: foundation namespaces (Algebra, Order, Data, Tactic) are the *most-edited*, not the least, and their edits invalidate the most.

### Top-30 leverage modules (sorted by edits × blast_CP)

| rank | edits | blast CP | module | lever |
|---:|---:|---:|---|---|
| 1 | 32 | 384 s | `Mathlib.SetTheory.Cardinal.Cofinality` | API stability |
| 2 | 16 | 739 s | `Mathlib.Tactic.Translate.Core` | API stability |
| 3 | 28 | 410 s | `Mathlib.SetTheory.Ordinal.Basic` | API stability |
| 4 | 21 | 405 s | `Mathlib.SetTheory.Ordinal.Arithmetic` | API stability |
| 5 | 10 | 738 s | `Mathlib.Tactic.Translate.ToDual` | API stability |
| 6 | 10 | 735 s | `Mathlib.Logic.Basic` | API stability |
| 7 | 9 | 714 s | `Mathlib.Order.Lattice` | API stability |
| 8 | 9 | 698 s | `Mathlib.Data.List.Basic` | API stability |
| 9 | 10 | 614 s | `Mathlib.Order.Cover` | API stability |
| 10 | 15 | 401 s | `Mathlib.SetTheory.Ordinal.Family` | API stability |
| 11 | 9 | 617 s | `Mathlib.Topology.Order` | API stability |
| 12 | 9 | 609 s | `Mathlib.Algebra.Group.Subgroup.Defs` | API stability |
| 13 | 10 | 540 s | `Mathlib.Data.NNReal.Defs` | API stability |
| 14 | 8 | 667 s | `Mathlib.Order.CompleteLattice.Basic` | API stability |
| 15 | 8 | 659 s | `Mathlib.Order.CompleteBooleanAlgebra` | API stability |
| 16 | 7 | 750 s | `Mathlib.Tactic.Linter.DirectoryDependency` | API stability |
| 17 | 7 | 733 s | `Mathlib.Tactic.Simps.Basic` | API stability |
| 18 | 8 | 636 s | `Mathlib.Order.ConditionallyCompleteLattice.Basic` | API stability |
| 19 | 7 | 725 s | `Mathlib.Order.OrderDual` | API stability |
| 20 | 9 | 558 s | `Mathlib.Algebra.Ring.Subring.Basic` | API stability |
| 21 | 7 | 696 s | `Mathlib.Order.BooleanAlgebra.Basic` | API stability |
| 22 | 7 | 681 s | `Mathlib.Order.Hom.Basic` | API stability |
| 23 | 9 | 524 s | `Mathlib.Order.SuccPred.Limit` | API stability |
| 24 | 7 | 643 s | `Mathlib.Order.Filter.Map` | API stability |
| 25 | 6 | 735 s | `Mathlib.Logic.Function.Defs` | API stability |
| 26 | 6 | 731 s | `Mathlib.Order.Defs.LinearOrder` | API stability |
| 27 | 9 | 485 s | `Mathlib.SetTheory.Cardinal.Basic` | API stability |
| 28 | 6 | 724 s | `Mathlib.Tactic.Push` | API stability |
| 29 | 7 | 609 s | `Mathlib.Order.ConditionallyCompleteLattice.Indexed` | API stability |
| 30 | 6 | 679 s | `Mathlib.Data.Set.Function` | API stability |

**All 30 top entries fall in the same lever class: hot edits + huge blast radius**, which is exactly the pattern `private import` and API-hashed caching exist to break. Zero entries are "rare-but-heavy" (split candidates).

### Pareto

- Top **528** modules = 50 % of total observed rebuild cost
- Top **1,423** = 80 %
- Top **2,421** = 95 %
- (out of 5,283 modules edited at least once in the window)

Cost is **diffuse** — no 90/10. But the *fix type* is uniform across the diffusion, which makes it tractable: one mechanism (private import / API hashing) addresses the entire top end.

### Per-namespace observed cost

Five foundation namespaces account for 60 % of all observed rebuild cost:

| namespace | total cost | share |
|---|---:|---:|
| Mathlib.Algebra | 431,528 s | 18.5 % |
| Mathlib.Data | 271,648 s | 11.6 % |
| Mathlib.Topology | 252,796 s | 10.8 % |
| Mathlib.Order | 241,324 s | 10.3 % |
| Mathlib.CategoryTheory | 200,990 s | 8.6 % |
| Mathlib.RingTheory | 165,677 s | 7.1 % |
| Mathlib.Tactic | 163,961 s | 7.0 % |
| Mathlib.Analysis | 137,416 s | 5.9 % |

---

## Phase 6 — Coupling and federation viability

### Cross-namespace coupling

- **52.7 % of all 33,651 import edges cross namespace boundaries** (intra: 47.3 %).
- Top-level namespace co-edit Jaccard, last 1,871 commits, most-coupled pairs:
  - `Algebra ↔ RingTheory` 0.19
  - `RingTheory ↔ LinearAlgebra` 0.18
  - `Data ↔ Order` 0.17
  - `Algebra ↔ Data` 0.16
  - `Analysis ↔ Topology` 0.16

Existing `Mathlib.<Top>` namespaces are **not** cohesive units. They have high cross-import density and material co-edit rates. They would not work as federation boundaries without further consolidation.

### Federation-without-API-hashing penalty

If we naively federated at namespace level (every package edit invalidates downstream packages whole):

| approach | median module-level blast | p90 |
|---|---:|---:|
| File-level cache (today) | 507 / 8,183 = 6 % | 6,460 = 79 % |
| Naive namespace federation | **8,008 / 8,183 = 98 %** | 8,008 = 98 % |

**Naive federation is strictly worse** because it coarsens the cache without making it smarter. The blast-radius win has to come from API-hashing, not boundary location. **Any reasonable boundary works once API-hashing exists; no boundary helps without it.**

### Defensible coarse partition

Reading from co-edit cohesion + topology, four macro-packages dominate:

| package | scope |
|---|---|
| **mathlib-foundations** | Init, Logic, Util, Lean, Tactic, Order, Data, SetTheory |
| **mathlib-algebra** | Algebra, RingTheory, LinearAlgebra, GroupTheory, FieldTheory, CategoryTheory, Combinatorics |
| **mathlib-analysis** | Analysis, Topology, MeasureTheory |
| **mathlib-leaves** | NumberTheory, AlgebraicGeometry, Geometry, Probability, AlgebraicTopology, RepresentationTheory, Dynamics, Condensed |

Four packages, not 30. But the data already says: this is moot until cache semantics change.

---

## Phase 7 — Module-system delta (private-import headroom)

### Current edge composition (33,651 total imports)

| kind | count | % |
|---|---:|---:|
| public (`isExported: true`) | 33,002 | **98.1 %** |
| private (`isExported: false`) | 451 | 1.3 % |
| meta | 198 | 0.6 % |
| importAll | 4 | 0.0 % |

### Critical path edge composition

Standard CP has 138 nodes / 137 edges. Of those edges: **132 (96 %) are public**, 2 private, 3 meta.

### Theoretical lower bound under maximal private adoption

Replacing every `isExported: true` with `isExported: false` (every import becomes `private import`) and re-running the rebuild-aware critical path:

| metric | value |
|---|---:|
| current rebuild CP | 734 s |
| maximal-private rebuild CP | **68 s** |
| theoretical headroom | −666 s (−91 %) |

This is an upper bound on what `private import` adoption alone could achieve at the CP level. Real adoption can't reach it — many imports must remain public because consumers genuinely need the imported types/instances. But even capturing 10–20 % of the headroom translates to 60–130 s of CP, which compounds across every commit.

### Conversion candidates among top-30 CP modules

For each module on the standard CP, count incoming public imports from non-CP modules — these are mechanically-identifiable conversion candidates whose privatization would shrink rebuild blast for non-CP edits without affecting the standard CP. Notable:

| rank | candidates | module |
|---:|---:|---|
| 6 | 186 | `Mathlib.Init` |
| 20 | 26 | `Mathlib.Logic.Equiv.Defs` |
| 15 | 17 | `Mathlib.Logic.Function.Basic` |
| 24 | 16 | `Mathlib.Order.Lattice` |
| 12 | 9 | `Mathlib.Tactic.ToDual` |
| 2 | 9 | `Mathlib.Tactic.Linter.Header` |
| ... | ... | ... |

**329 conversion candidates among the top 30 CP modules alone**, all mechanically discoverable. Whether each is *semantically* convertible (i.e. the importer doesn't actually re-export the import) requires Lean-level audit — but this gives a starting list for the audit.

---

## Pitfalls / caveats

- All blast-radius numbers are **content-hash** based (ancestor invalidation). API-hash blast would be smaller; we have no data on it.
- The ∞-core simulation assumes single-threaded modules; real builds have intra-module Lean parallelism baked into `time`.
- The simulator uses recorded order as tie-breaker, not optimal scheduling — produces a 2-approximation in the worst case (Graham bound).
- "Maximal-private rebuild CP = 68 s" is a structural lower bound, not a practical target. Many imports must remain public for typeclass instance resolution, syntax/notation, `@[reducible]` defs, etc.
- The Phase 7 rebuild-CP simulator in `phase7.py` mildly differs from `lakeprof report -r` (734 s vs 738 s) — likely a meta-edge-handling difference. Use lakeprof's `-r` for canonical numbers.

---

## Reproducibility

Every figure traces back to one of:

| script | purpose |
|---|---|
| `lakeprof record lake build` | Phase 1 capture |
| `lakeprof report -p -s -r` | Phase 2 baseline |
| `sweep.py` | Phase 2 finer linear sweep |
| `shard_analysis.py` | Phase 3, 4 |
| `foundation_analysis.py` | "Two-phase build" experiment |
| `churn_analysis.py` | Phase 5 distribution |
| `leverage_analysis.py` | Phase 5 top-N leverage table |
| `boundary_analysis.py` | Phase 6 coupling + federation |
| `phase7.py` | Phase 7 module-system delta |
| `pr_impact.py` | per-PR blast predictor (deployment-ready) |

All scripts are in this directory. To rerun, ensure `mathlib-clean.log` is current and the working directory is the mathlib4 checkout (lakeprof's `parse()` calls `lake query --no-build` against it).
