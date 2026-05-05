# Experiment 03 — Deploy `pr_impact.py` as a GitHub Action

## Goal

Wire the existing [`pr_impact.py`](../pr_impact.py) blast-radius predictor as a GitHub Action that comments on every mathlib4 PR with predicted modules invalidated, rebuild CP, and a flag if any top-50 hot-list module is touched.

## Why this experiment

- `pr_impact.py` is already written and works end-to-end against `mathlib-clean.log`.
- The cost of incremental rebuilds is currently a **hidden externality**: a PR author touching `Mathlib.Order.Lattice` (blast CP 714 s) and a PR author touching a leaf module (blast CP 5 s) look identical in the review UI. Reviewers can't price the difference.
- Making the cost visible doesn't reduce it directly, but it changes incentives. Authors who learn their seemingly-trivial PR will rebuild 60 % of the graph have a reason to look for a smaller-blast formulation. Reviewers gain a signal for when extra scrutiny is warranted.
- It's also the channel through which experiments 01 and 04 prove their value — every time a top-leverage module gets a `private import` conversion, subsequent PRs touching adjacent files should see their predicted blast drop.

## Inputs

- `pr_impact.py` (current implementation reads `mathlib-clean.log` from a hardcoded path; will need to be adjusted for CI).
- `mathlib-clean.log` from the most recent weekly clean-build CI run (experiment 05).
- A GitHub Actions workflow file in mathlib4's `.github/workflows/`.

## Procedure

### Phase 3a — productionize the script (1 day)

1. Take input paths from environment / CLI rather than hardcoded `/Users/chelo/lakeprof`.
2. Vendor or `pip install` lakeprof as a regular dependency. Don't rely on a sibling-directory checkout.
3. Output a markdown table suitable for posting as a PR comment:

   ```
   ## Build impact prediction

   - Modules edited: 3
   - Modules invalidated (transitive): 412
   - Predicted rebuild CP: 287 s (38 % of clean-build floor)
   - Top-50 hot-list modules touched: **2** (`Mathlib.Order.Lattice`, `Mathlib.Data.List.Basic`)

   <details>
   <summary>Top 10 invalidated modules by their own work time</summary>
   ...
   </details>
   ```

4. Cache the parsed graph between invocations (the `lakeprof.parse` call is the slow part). A pickle of the `networkx.DiGraph` keyed on the log file's hash should drop wall-clock from ~30 s to ~3 s.

### Phase 3b — wire as GitHub Action (half a day)

A workflow file roughly like:

```yaml
name: build-impact
on: [pull_request]
jobs:
  predict:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - run: pip install lakeprof networkx
      - run: |
          curl -L -o mathlib-clean.log "$LAKEPROF_LOG_URL"
        env:
          LAKEPROF_LOG_URL: ${{ secrets.LAKEPROF_LOG_URL }}
      - run: python pr_impact.py "$BASE" "$HEAD" > comment.md
        env:
          BASE: ${{ github.event.pull_request.base.sha }}
          HEAD: ${{ github.event.pull_request.head.sha }}
      - uses: marocchino/sticky-pull-request-comment@v2
        with:
          path: comment.md
```

Use a sticky-comment action so subsequent pushes update the same comment instead of stacking new ones.

### Phase 3c — calibrate (3–5 days, post-launch)

Once it's running on real PRs:

1. Spot-check predictions against actual cache-miss counts on a handful of merged PRs. The predictor uses `mathlib-clean.log` from a single point in time; if the graph shifts substantially, predictions will drift.
2. Tune the "hot-list" threshold. Top-50 by leverage is the obvious starting point but may be too noisy or too quiet in practice.
3. Consider adding a "predicted clean-build wall-clock at 18 cores" estimate alongside the CP, since reviewers are more familiar with wall-clock than CP seconds.

## Success criteria

- A comment appears on every new PR within ~2 minutes of opening.
- The comment is accurate to within ±10 % of actual rebuild cost on a calibration sample of 20 merged PRs.
- A measurable behavioural change: PR authors begin referencing the prediction in their PR descriptions, or breaking down large PRs to reduce predicted blast. (This is a soft success signal but the real one.)

## Scope limits

- **Don't block PRs based on the prediction.** This is informational. Hard gates would require much more validation — the prediction is approximate.
- **Don't chase precision.** The point is order-of-magnitude price visibility, not benchmark accuracy. A 50 % off prediction is still vastly more informative than no prediction.
- **Don't post comments on automated bot PRs** (Mathport, version bumps, etc.) — they'll spam the queue.
- **Don't use a stale `mathlib-clean.log`.** If the log is more than ~6 weeks old, predictions may be substantially wrong because the graph has shifted. Tie this to experiment 05's weekly capture so the log is always fresh.

## Deliverables

- `pr_impact.py` made CI-portable (no hardcoded paths). Modify a copy (e.g. `pr_impact_v2.py`); leave the original.
- `.github/workflows/build-impact.yml` produced locally in this worktree. Not pushed — this clone has no `origin`. Mathlib maintainers can adopt it from a separate fork-clone.
- A short README in `experiments/03/` (in the worktree) describing how to interpret the comment.
- A final report at `/Users/chelo/lakeprof-experiments/reports/03-pr-predictor.md` using `experiments/REPORT_TEMPLATE.md`, with deployment instructions for an upstream maintainer. Lives outside any worktree.

## Dependency on other experiments

- **Hard dependency on experiment 05.** Without weekly fresh `mathlib-clean.log`, predictions drift. Land 05 first or in parallel.
- **Soft synergy with experiment 02.** If the API-hash measurement tool exists, the predictor can show *both* content-hash blast (today's reality) and API-hash blast (what the cache could be doing), making the case for the upstream Lake change visible per-PR.
