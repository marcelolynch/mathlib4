# Experiment 05 — Weekly clean-build CI capture

## Goal

Add a scheduled CI job that runs `lakeprof record lake build` on a clean tree once a week, uploads the resulting `mathlib-clean.log` as a build artifact, and retains it for ≥ 12 months. This produces the longitudinal dataset every other experiment depends on.

## Why this experiment

- All current analyses run against a single recorded build (`36a97460`, 2026-05-04). That snapshot ages.
- The PR blast predictor (experiment 03) drifts when its underlying graph is stale.
- Trends (CP creep, hot-list shift, namespace coupling drift) are invisible without longitudinal data.
- Foundational, cheap, and unblocks everything else. Should land first.

## Inputs

- mathlib4 CI infrastructure.
- `lakeprof` (Python; ~1 minute install).

## Procedure

### Step 1 — workflow

A scheduled GitHub Actions workflow:

```yaml
name: weekly-lakeprof
on:
  schedule:
    - cron: '17 6 * * 1'   # Mondays 06:17 UTC
  workflow_dispatch:        # also allow manual trigger
jobs:
  record:
    runs-on: <large-runner>   # at least 16 cores; clean build is ~30 m on 18-core
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v4
      - run: elan toolchain install $(cat lean-toolchain)
      - run: pip install lakeprof
      - run: rm -rf .lake   # ensure no cache hits
      - run: lakeprof record -o mathlib-clean.log lake build
      - run: lakeprof report -i mathlib-clean.log -p -s -r > lakeprof-report.txt
      - uses: actions/upload-artifact@v4
        with:
          name: lakeprof-${{ github.sha }}-${{ github.run_id }}
          path: |
            mathlib-clean.log
            lakeprof-report.txt
          retention-days: 365
```

### Step 2 — surface the artifact

Two consumers:

1. **Experiment 03's PR predictor** needs the *latest* log. Either:
   - Fetch by the workflow's "latest successful run" via `gh run list --workflow=weekly-lakeprof --limit 1 --json databaseId`, then download the artifact, or
   - Mirror the latest log to a stable URL (S3, GitHub release asset) at the end of each weekly run.
2. **Trend dashboards** consume the historical sequence. The artifacts named `lakeprof-<sha>-<runid>` form a time series; a small dashboard script can pull the last N and produce CP-over-time, hot-list-shift-over-time figures.

### Step 3 — sanity check

For the first 2–3 weekly runs, manually verify:

- `mathlib-clean.log` has ~8,000 `Built X (Ys)` lines, none with `(0.00s)`. A `(0.00s)` line means the cache wasn't actually clean — `rm -rf .lake` failed or there's a separate cache directory the workflow missed.
- `lakeprof-report.txt`'s reported CP is in the 700–800 s range. Sudden 100s+ shifts are either a real graph change worth investigating or a measurement bug.

## Success criteria

- Workflow runs on schedule for 4 consecutive weeks without manual intervention.
- Artifacts are downloadable by other workflows (test by having experiment 03's predictor fetch them).
- The CP series shows the expected ~750 s with realistic week-to-week variance (< ±5 % typically).

## Scope limits

- **Don't run on every PR.** It's a 30-minute build; weekly is the right cadence. Per-PR builds are experiment 03's territory and use the cached log, not a fresh recording.
- **Don't try to also produce all the figures inline.** Generating the full set of `figs/*.svg` is a separate concern (`make_plots.py`) and adds wall-clock for no CI-time benefit. Capture the log; figures can be generated on demand.
- **Don't deduplicate runs.** Even if the SHA hasn't moved (unlikely on mathlib's main branch), running again and noting that runs match is a useful sanity check on measurement noise.

## Deliverables

- `.github/workflows/weekly-lakeprof.yml` produced locally in this worktree. Not pushed — this clone has no `origin`. Mathlib maintainers can adopt it from a separate fork-clone.
- A short doc at `experiments/05/README.md` (in the worktree) describing how to fetch the latest artifact, what to do when a run fails, and the expected CP range.
- One follow-up artifact-consumer script (`fetch_latest_log.sh`) that experiment 03 imports.
- A final report at `/Users/chelo/lakeprof-experiments/reports/05-weekly-ci.md` using `experiments/REPORT_TEMPLATE.md`, with deployment instructions for an upstream maintainer. Lives outside any worktree.

## Why this is the foundation

Every other experiment in this set assumes "we have a recent `mathlib-clean.log`":

- 01 (private import audit) — measures rebuild-CP delta against the log.
- 02 (API hash measurement) — uses the log's graph for blast propagation.
- 03 (PR predictor) — the log *is* its model.
- 04 (Analysis split) — needs a fresh log post-split to validate.

Without 05, all of those are anchored to a single point in time. With 05, they become continuous instruments.
