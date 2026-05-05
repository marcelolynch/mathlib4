# Experiment plans — index

These are self-contained briefs for agents to execute. Each maps to one of the top-leverage opportunities identified in [`findings-report.md`](../findings-report.md) and [`mathlib-build-deep-dive.md`](../mathlib-build-deep-dive.md).

## Why these five

The findings converged on a single conclusion: **graph shape sets the clean-build floor; cache semantics set the incremental-build floor.** Sharding, federation, and hardware buys are decoration. The five experiments below are exactly the interventions the data supports — ordered by leverage.

| # | experiment | tier | expected payoff | effort |
|---|---|---|---|---|
| [01](01-private-import-audit.md) | `private import` audit on top-50 leverage modules | now | tens of seconds of rebuild CP today; multiplier when (02) lands | weeks of localized PRs |
| [02](02-api-hash-measurement.md) | API-diff tool over commit history | this quarter | the empirical number that justifies Lake signature-hash caching | 1–2 weeks |
| [03](03-pr-blast-predictor.md) | Deploy `pr_impact.py` as a GitHub Action | now | turns rebuild cost into a reviewable signal | 1 day |
| [04](04-analysis-cp-split.md) | Split top-5 Analysis CP modules | this quarter | ~85 s of clean-build CP (~11 % of floor) | 5 mathematical refactors |
| [05](05-weekly-clean-build-ci.md) | Weekly clean-build CI capture | now | longitudinal dataset that everything else needs | half a day |

## Things any agent should NOT attempt

These were ruled out by the data:

- **Phasing the build into foundation → downstream stages.** Two-phase pipelines were 15–35 % slower than monolithic across all three foundation cuts we tested. Don't propose pipeline architectures.
- **Naive namespace-level sharding under content hashing.** Median module blast jumps from 6 % → 98 %. Strictly worse than today's file-level cache.
- **Surgical fixes for the namespace cycles.** Removing the worst 500 wrong-direction importers shrinks the giant SCC by exactly one namespace. The full feedback arc set is ~1,957 edges.
- **Buying >128-core hardware** for clean-build throughput. The speedup curve is essentially flat past 96–112 cores.
- **Expanding the K=5 Analysis split to K=10+.** Returns plateau immediately; alternative chains take over.

## Shared context for every experiment

- Recorded build log: [`mathlib-clean.log`](../mathlib-clean.log) (mathlib4 @ `36a97460`, 2026-05-04, 18-core Apple Silicon, 32m46s, 8,393 jobs).
- lakeprof Python source lives at `/Users/chelo/lakeprof/`. Scripts here import via `sys.path.insert(0, "/Users/chelo/lakeprof")`.
- `mathlib-clean.log` is the input every CP / blast / leverage analysis reads. Don't re-record unless you need to refresh — the analyses are seconds; the recording is half an hour.
- Critical-path computations require populating edge weights:
  ```python
  for u, v, data in g.edges(data=True):
      data["time"] = g.nodes[u]["time"]
  ```
  Without this, `dag_longest_path_length(g, weight="time")` silently returns edge counts. Verify by checking the result matches `lakeprof report -p`'s reported floor (~750 s).
- Edge direction in lakeprof's graph is `importer → importee`. So "modules I invalidate when I edit m" = `networkx.ancestors(g, m)`, not `descendants`.
