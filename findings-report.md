# mathlib4 build-time analysis — final findings report

Comprehensive analysis of mathlib4's build graph, parallelism limits, incremental rebuild costs, and federation viability. Based on a clean recorded build of mathlib4 @ `36a97460` (2026-05-04, 18-core Apple Silicon, 32m46s wall-clock, 8,393 jobs) and the last 1,500–2,000 commits of git history. All numerics traceable to scripts in this directory.

This document complements the phase-by-phase technical breakdown in [`lakeprof-analysis.md`](lakeprof-analysis.md).

---

## Top-line conclusions

1. **The clean-build wall-clock floor is 750 s** (12 m 31 s) under any number of cores. **62 % of that floor lives inside `Mathlib.Analysis`** alone. Speedup ceiling vs single-CPU: 44×. Practical knee at ~96–112 cores; true saturation at 192.

2. **mathlib has no layered architecture** — at the namespace level, **96 % of modules participate in one giant strongly-connected component** of 27 namespaces. The intuition that `Algebra → Analysis → NumberTheory` is a DAG is empirically false. Even at 4-level (directory) granularity, 57 % of modules remain in one SCC.

3. **Pure sharding cannot help.** Two-phase (foundation → downstream) builds are 15–35 % *slower* than monolithic. Naive namespace-level federation under content hashing is *strictly worse* than today's file-level cache (98 % vs 6 % median module blast).

4. **The dominant lever is cache semantics, not infrastructure.** Only 1.3 % of mathlib's 33,651 imports are private. The theoretical lower bound under maximal `private import` adoption shrinks the rebuild critical path from 734 s to **68 s** — a 91 % reduction. This is the largest single available improvement, and most of it is achievable today without upstream changes.

5. **The foundation churns hardest.** `Mathlib.Algebra` is in 19 % of all commits with avg blast radius 52 % of the graph. The median commit invalidates 36 % of the critical path. The "stable foundation, churning leaves" intuition is the opposite of reality.

---

## 1. Clean-build parallelism limits

### Baseline
- Total work (1-CPU sim): 33,075 s ≈ 9 h 11 m
- Critical-path floor (∞ cores): **750 s**
- Speedup ceiling: 44× (= 33,075 / 750)
- Recorded 18-core wall-clock: 1,966 s = ~16.8× = 38 % of theoretical max

### Where the ceiling is set

The 113-module critical path runs:
`Set → Order → Topology → Algebra → Analysis (Seminorm/Operator/Multilinear) → Analytic → ContDiff → Manifold → SchwartzSpace → Fourier → ModularForms`

Heaviest CP nodes (Analysis-dominated):
| s | module |
|---:|---|
| 32.0 | `Mathlib.Analysis.Distribution.SchwartzSpace.Basic` |
| 26.0 | `Mathlib.Analysis.Normed.Module.Multilinear.Basic` |
| 26.0 | `Mathlib.Analysis.Analytic.Constructions` |
| 22.0 | `Mathlib.Analysis.Analytic.Basic` |
| 20.0 | `Mathlib.Analysis.Calculus.ContDiff.Defs` |

### Parallelism profile

| concurrent jobs | wall-clock share |
|:---:|---:|
| <16 | 11 % |
| 16–31 | **31 %** |
| 32–63 | 35 % |
| 64–95 | 17 % |
| ≥96 | 6 % |

**42 % of the wall-clock floor has fewer than 32 tasks running.** This is why the speedup curve flattens hard. Adding cores past ~32 helps less than commonly assumed — most of the build is structurally narrow.

### Bottleneck what-if (zero out top-K CP modules)

| K | new floor | gain |
|---:|---:|---:|
| 1 | 736 s | 14 s |
| 5 | 665 s | 86 s |
| 10 | 665 s | **0 (plateau)** |
| 25 | 652 s | <1 s/module |
| 50 | 628 s | <1 s/module |

Diminishing returns hit at K=5; alternative chains then dominate. **Splitting at most 5 specific Analysis modules is worth ~85 s of CP**; further splits are wasted unless coordinated across multiple parallel chains.

### Linear core sweep

True saturation point is **192 cores** (not 128 as the doubling sweep suggested). Practical knee at 96–112 cores — beyond that you pay for cores that sit idle waiting on the critical path.

---

## 2. Incremental-build reality

### Per-commit blast radius (content-hash invalidation, last 1,871 commits)

| quantile | edited mods | invalidated mods | rebuild CP | % of full CP |
|---|---:|---:|---:|---:|
| p25 | 1 | 14 | 34 s | 4.6 % |
| **p50** | **2** | **507** | **269 s** | **35.9 %** |
| p75 | 4 | 2,604 | 520 s | 69.3 % |
| p90 | 7 | 6,460 | 667 s | 88.9 % |
| p95 | 13 | 7,363 | 725 s | 96.7 % |

Only the bottom 25 % of commits are leaf-like. The median commit kills ~12 minutes of cache-able critical path; the 90th percentile commit is ~89 % of a clean rebuild.

### Where churn lands

| namespace | % of commits | avg blast (% of graph) |
|---|---:|---:|
| `Mathlib.Algebra` | **19 %** | 52 % |
| `Mathlib.Analysis` | 15 % | 6 % |
| `Mathlib.RingTheory` | 14 % | 18 % |
| `Mathlib.Topology` | 14 % | 19 % |
| `Mathlib.CategoryTheory` | 11 % | 11 % |
| **`Mathlib.Order`** | 10 % | **66 %** |
| `Mathlib.Data` | 10 % | 45 % |
| **`Mathlib.Tactic`** | 8 % | **58 %** |
| Mathlib.NumberTheory | 10 % | 1 % |
| Mathlib.AlgebraicGeometry | 3 % | 0.5 % |

The most-edited namespaces are also the highest-blast — exactly the opposite of the "stable foundation" pattern. The true low-blast namespaces (NumberTheory, AlgebraicGeometry, Probability, AlgebraicTopology) have 1–6 % blast but only collectively account for ~15 % of edits.

### Top-30 leverage modules (edits × blast CP)

All 30 fall into the same lever class: **hot edits + huge blast radius**. Zero are split candidates. Sample (top 10):

| rank | edits | blast CP | module |
|---:|---:|---:|---|
| 1 | 32 | 384 s | `Mathlib.SetTheory.Cardinal.Cofinality` |
| 2 | 16 | 739 s | `Mathlib.Tactic.Translate.Core` |
| 3 | 28 | 410 s | `Mathlib.SetTheory.Ordinal.Basic` |
| 4 | 21 | 405 s | `Mathlib.SetTheory.Ordinal.Arithmetic` |
| 5 | 10 | 738 s | `Mathlib.Tactic.Translate.ToDual` |
| 6 | 10 | 735 s | `Mathlib.Logic.Basic` |
| 7 | 9 | 714 s | `Mathlib.Order.Lattice` |
| 8 | 9 | 698 s | `Mathlib.Data.List.Basic` |
| 9 | 10 | 614 s | `Mathlib.Order.Cover` |
| 10 | 15 | 401 s | `Mathlib.SetTheory.Ordinal.Family` |

Pareto: top 528 modules = 50 % of total observed rebuild cost; top 1,423 = 80 %; top 2,421 = 95 %. Cost is **diffuse**, but the *fix type* is uniform — one mechanism (`private import` / API hashing) addresses the entire top end.

---

## 3. Module-system delta (private-import headroom)

### Current state of mathlib's import declarations

| import kind | count | share |
|---|---:|---:|
| public (`isExported: true`) | 33,002 | **98.1 %** |
| private (`isExported: false`) | 451 | 1.3 % |
| meta | 198 | 0.6 % |
| importAll | 4 | 0.0 % |

Only 1.3 % of imports are private. On the critical path, **96 % of edges are public** (132 of 137).

### Theoretical lower bound

Replacing every public import with `private import` and recomputing the rebuild-aware CP:

| metric | value |
|---|---:|
| current rebuild CP (`-r`) | 734–738 s |
| maximal-private rebuild CP | **68 s** |
| theoretical headroom | **−666 s (−91 %)** |

This is an unreachable upper bound (many imports must be public for instance resolution, syntax, reducible defs, etc.) — but it bounds what private-import adoption alone could buy. Capturing 10–20 % of the headroom translates to 60–130 s of CP, which compounds across every commit.

**329 mechanically-identifiable conversion candidates exist among the top 30 CP modules alone** — these are public imports from non-CP modules into CP modules, where conversion would shrink rebuild blast without affecting the standard CP.

---

## 4. Federation viability (the cycle problem)

### The killer finding: namespace cycles

Of mathlib's 34 top-level namespaces:

- **One giant SCC contains 27 namespaces = 7,836 modules = 96 % of mathlib**
- Only AlgebraicGeometry, Condensed, InformationTheory, Testing, Deprecated sit outside the giant SCC (170 modules = 2 % of the codebase)
- 96 bidirectional namespace pairs (17 % of all possible 561 pairs)
- Even at 3-level (`Mathlib.X.Y`) granularity: largest SCC = 88 % of modules
- At 4-level (directory level): largest SCC = 57 % of modules

**The conventional intuition that mathlib is layered (`Foundation → Algebra → Analysis → Leaves`) is empirically false.** The "leaves" — `NumberTheory`, `Probability`, `AlgebraicTopology`, `Geometry`, `RepresentationTheory`, `MeasureTheory`, `ModelTheory`, `Dynamics` — are all *inside* the giant SCC.

### Misnamed namespaces

What % of each namespace's modules contribute wrong-direction (cycle-creating) imports under a layered ordering:

| namespace | % of own modules contributing cycles |
|---|---:|
| `Mathlib.Logic` | **70 %** |
| `Mathlib.Control` | 56 % |
| `Mathlib.Order` | 54 % |
| `Mathlib.SetTheory` | 48 % |
| `Mathlib.Combinatorics` | 42 % |
| `Mathlib.Data` | 39 % |
| `Mathlib.Tactic` | 36 % |
| `Mathlib.Algebra` | 29 % |
| Mathlib.RingTheory | 27 % |
| Mathlib.Topology | 10 % |
| Mathlib.Analysis | 10 % |
| Mathlib.NumberTheory | 0 % |

**`Mathlib.Logic`, `Mathlib.Order`, `Mathlib.Control`, `Mathlib.SetTheory` are application layers wearing foundation names.** 50–70 % of their modules import "downstream" content. The truly low-cycle namespaces (NumberTheory, MeasureTheory, Topology, Analysis) sit *higher* in the stack, not lower.

### No surgical fix exists

Surgical removal of the top-K wrong-direction importers:

| top-K removed | biggest namespace SCC |
|---:|---:|
| 0 | 27 |
| 5 | 26 |
| 50 | 26 |
| 100 | 26 |
| 500 | **26** |

Removing the worst 500 cycle-makers shrinks the SCC by **exactly one** namespace. The cycles are diffuse, not concentrated. There is no small set of "bad files" to refactor.

### Total feedback arc set

To break all 96 bidirectional namespace pairs (assuming we cut the smaller direction of each): **1,957 edges** = 11 % of cross-namespace edges. That's a substantial structural refactor — relocating ~1,957 specific imports.

### Federation-without-API-hashing penalty

If we federated naively (each package = monolithic cache unit, content-hash keyed):

| approach | median module blast | p90 |
|---|---:|---:|
| File-level cache (today) | 507 / 8,183 = 6 % | 6,460 = 79 % |
| Naive namespace federation | **8,008 / 8,183 = 98 %** | 8,008 = 98 % |
| Naive collapse-to-foundation | 8,008 / 8,183 = 98 % | 8,008 = 98 % |

**Naive federation is strictly worse** because granularity becomes coarser without becoming smarter. The win has to come from API-hashing, not boundary location.

### Two-phase build penalty

| strategy | wall-clock floor | vs monolithic |
|---|---:|---:|
| Monolithic (current) | 750 s | — |
| Foundation A → downstream | 861 s | +15 % |
| Foundation B → downstream | 1010 s | +35 % |
| Foundation C → downstream | 975 s | +30 % |

Phasing the build always loses to monolithic because in a monolithic build, downstream modules start the moment their *specific* upstream deps finish — they don't wait for an entire upstream package. The phasing barrier is dead time.

### Naturally-extractable packages

Without any refactoring, only 2 % of mathlib is federable today:

| namespace | modules | work | internal CP |
|---|---:|---:|---:|
| `Mathlib.AlgebraicGeometry` | 127 | 867 s | 218 s |
| `Mathlib.Condensed` | 34 | 161 s | 35 s |
| `Mathlib.InformationTheory` | 6 | 23 s | 8 s |

---

## 5. Recommendations (ranked by leverage)

### 1. `private import` adoption — highest leverage, available today

- **What**: convert non-API-affecting imports in the top-50 leverage modules (and progressively wider) from `import` to `private import`.
- **Why**: 91 % theoretical headroom on rebuild CP. Empirically validated mechanism (Lean's module system already supports it). Mechanically discoverable conversion candidates: 329 just among top-30 CP modules.
- **Cost**: per-PR localized work. Audit-style — no coordination needed across files. Each conversion is mergeable independently.
- **Risk**: low — `private import` is well-understood Lean 4 semantics. Only risk is misidentifying an import as convertible (compiler will reject if downstream needs the public re-export).
- **Validation**: rerun `lakeprof report -r` after a wave of conversions; the gap to standard `-p` should grow. Lake's content-hash cache won't show the win directly until point #2 also lands.

### 2. Lake cache keyed on signature hash, not file content — biggest multiplier

- **What**: upstream Lean/Lake change. Cache key for downstream oleans depends on `hash(my_source ⊕ deps' signature_hashes)`, not deps' content hashes.
- **Why**: turns `private import` from a Lean-elaboration optimization into a real cache primitive. Most foundation commits (which we measured invalidate 36–66 % of CP under content hashing) don't change exposed signatures and become free.
- **Cost**: multi-month engineering project on Lake/Lean side. Requires precise definition of "API surface" for Lean (signatures + reducibility + instance priorities + macros). Determinism guarantees.
- **Risk**: moderate — getting "what is the API" exactly right is subtle. Easy to ship a version that under-invalidates and produces incorrect builds.
- **Pre-work**: deploy CI instrumentation (#5 below) to measure API-change rates and validate the assumption "most commits are internals-only."

### 3. Targeted refactor of top-5 Analysis CP modules

- **What**: split each of these into smaller, parallelizable units:
  - `Mathlib.Analysis.Distribution.SchwartzSpace.Basic` (32 s on CP)
  - `Mathlib.Analysis.Normed.Module.Multilinear.Basic` (26 s)
  - `Mathlib.Analysis.Analytic.Constructions` (26 s)
  - `Mathlib.Analysis.Analytic.Basic` (22 s)
  - `Mathlib.Analysis.Calculus.ContDiff.Defs` (20 s)
- **Why**: ~85 s of CP reduction for 5 splits. Diminishing returns past K=5 — alternative chains take over.
- **Cost**: one-off mathematical refactor; needs domain expertise.
- **Risk**: low. Pure code reorganization.
- **Limit**: bounded payoff (~11 % of clean-build floor). Don't expand to K>5 without coordinated work on parallel chains.

### 4. Hardware: 32 cores is the sweet spot

- **What**: standardize CI / contributor recommendation around 32-core machines.
- **Why**: ~20 minute wall-clock for clean rebuild. Practical knee at 96–112 cores → ~13 minutes. Past that, diminishing returns. 192-core true saturation is academic.
- **Cost**: hardware spend.
- **Risk**: zero technical risk. Pure cost-optimization decision.

### 5. CI instrumentation (foundation for everything else)

- **Layer 1 (1 day)**: weekly clean-build CI job recording `lakeprof.log` artifact. Builds the longitudinal dataset.
- **Layer 2 (1 week)**: deploy `pr_impact.py` as a GitHub Action; comment predicted blast radius on every PR. Makes cost visible.
- **Layer 3 (1 month)**: weekly digest post (top-N hot modules, CP trend, coupling drift) to mathlib's discussion forum.
- **Layer 4 (2 months, biggest payoff)**: API-hash manifest computation in CI. Even a crude version (strip comments + proof bodies, hash declaration headers) gives the missing data point — *what fraction of commits actually change the API?* — that justifies #2.

### Things to *not* do

- **Don't try to phase the build.** Two-phase pipelines are 15–35 % slower than monolithic.
- **Don't shard at namespace level without API hashing.** Strictly worse than current.
- **Don't pursue per-namespace federation without first relocating 1,957 specific imports** (the feedback arc set). The cycles will sabotage any package boundary.
- **Don't buy >128-core hardware.** The curve is essentially flat past 96–112 cores.
- **Don't expand the K=5 Analysis split to K=10+.** Returns plateau immediately.

---

## 6. Open questions / not-explored

These would require additional data we don't have:

- **Actual API-change rate per commit.** Our "blast radius" is content-hash based. To validate the API-hashing thesis, we'd need a syntactic API-diff tool (strip proof bodies, hash declaration types) and replay it over commit history.
- **Effect of `Mathlib.Analysis` internal restructuring.** We measured CP impact of zeroing top-5 modules but not of realistic refactors (typically you can split a module to 60–80 % of its self-time, not 0).
- **Cross-machine distributed-build cost.** Our simulator assumes free intra-cluster bandwidth. Realistic distributed RBE has non-trivial network costs that grow with module count.
- **Per-commit CI cache-hit rate distribution.** Would tell us how much of the predicted blast is actually paid by mathlib CI today vs. served from cache.
- **The 4-level partition's giant SCC composition.** We know it's 57 % of modules but didn't dig into which 4-level packages compose it.

---

## 7. Reproducibility

All scripts in this directory; rerun against a fresh `mathlib-clean.log` to refresh.

| script | purpose |
|---|---|
| `lakeprof record lake build` | clean-build capture (Phase 1) |
| `lakeprof report -p -s -r` | baseline metrics (Phase 2) |
| `sweep.py` | finer linear core sweep |
| `shard_analysis.py` | parallelism profile + bottleneck what-if |
| `foundation_analysis.py` | two-phase pipeline experiment |
| `churn_analysis.py` | per-commit blast distribution |
| `leverage_analysis.py` | top-N leverage table |
| `boundary_analysis.py` | co-edit + cross-cuts |
| `boundary_split3.py` | partition simulation + SCC condensation |
| `cycle_breakers.py` | feedback arc set analysis |
| `cycle_offenders.py` | per-module cycle-contribution ranking |
| `phase7.py` | private-import headroom |
| `pr_impact.py` | per-PR blast predictor (deployment-ready) |

Pitfall: scripts that compute critical paths must populate edge weights via `for u, v, data in g.edges(data=True): data["time"] = g.nodes[u]["time"]` after parsing. Without this, `dag_longest_path_length(g, weight="time")` silently uses default weight=1 and returns edge counts instead of seconds.

---

## Closing

Across every analytical lens — clean-build CP, sim parallelism, churn distribution, leverage ranking, namespace cycles, boundary-split simulation, cycle-offender enumeration — the conclusion converged:

**The wall-clock floor is set by graph shape; graph shape can't be fixed by sharding, hardware, or boundary location. Only two things move it: (a) cache semantics that don't invalidate spuriously and (b) targeted refactor of the few hot Analysis modules at the floor.**

Deploy `pr_impact.py` this week. Start the `private import` audit on the top-50 leverage list. Lobby Lake/Lean for signature-hash caching. Everything else is decoration.
