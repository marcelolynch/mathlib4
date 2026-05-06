# Experiment 06 — Stage 1+: data-prep checklist (manual)

This is the data prep for the **empirical** half of the scheduling-headroom experiment. It is gated behind Stage 0 (`06-scheduler-simulation.md`).

## Prerequisite: Stage 0 must have recommended "proceed"

Before working through this checklist, run Stage 0 and read its report:

```
/Users/chelo/lakeprof-experiments/reports/06-scheduler-stage0.md
```

If Stage 0 said **drop**, do not run any of the steps below — the experiment is over and effort goes to other levers. If Stage 0 said **proceed**, continue.

## What this checklist is for

This is a checklist *for you* (or an infra collaborator). The Stage 1+ analysis agent (`06-scheduler-analysis.md`) doesn't have CI access or runner authorization; it needs the artifacts below dropped on disk before kickoff.

Don't kick off the analysis agent until at least Steps 1–4 of this document are done. Step 5 is optional but strongly recommended.

## What you'll produce

By the end of this checklist:
- A built `lake` binary from the user's lean4 fork — the one with `graph-extract` enabled.
- `~/mathlib4/manifest.json` + `~/mathlib4/sidecars/` — extracted static graph (~10 MB index + ~440 MB sidecars).
- `~/mathlib4-lakeprof/mathlib-clean-12c.log` — clean p=12 build trace from a self-hosted runner (W1).
- *(optional)* `~/mathlib4-lakeprof/mathlib-clean-12c-run{2,3}.log` — variance traces (W2).

These plus the existing `~/mathlib4-lakeprof/mathlib-clean.log` (p=18 baseline) are the analysis agent's inputs.

## Step 1 — Verify the graph-extract patch is in place

```bash
cd ~/mathlib4/lean4-src
git log --oneline -5
```

You should see commits `0b814ce7` (`feat: add Lake/Build/GraphExtract.lean`), `64d36c68` (`feat: add lake graph-extract CLI subcommand`), and `49b60ec9` (`feat: add per-node sidecar emission to graph-extract`) at or near the tip. If they're not there, fetch / rebase before continuing — the analysis agent cannot proceed without them.

## Step 2 — Build the lean4 fork

You need a `lake` binary that includes the `graph-extract` subcommand. Two options:

- **Local build.** Follow `~/mathlib4/lean4-src/doc/dev/bootstrap.md`. Output is `~/mathlib4/lean4-src/build/release/stage1/bin/lake`. ~30–60 minutes on a decent box.
- **CI build.** Dispatch a one-shot workflow that builds the fork and uploads the `lake` binary as an artifact. Faster turnaround if your local hardware is slow, but adds a runner round-trip.

Validate either way:

```bash
<built-lake-path> graph-extract --help
```

The subcommand should appear. If `--help` doesn't list it, the build didn't pick up the patch.

## Step 3 — Run extraction on mathlib4

```bash
cd ~/mathlib4-lakeprof   # this is the mathlib4 working tree
<built-lake-path> graph-extract Mathlib ~/mathlib4/manifest.json ~/mathlib4/sidecars/
```

Expected: ~42 s wall-clock, no `Built` lines (extraction does not trigger any builds).

Validate:
- `~/mathlib4/manifest.json` is ~10 MB (sidecar-mode index, not the 372 MB inline form).
- `~/mathlib4/sidecars/` contains ~8,300 `*.node.json` files totalling ~440 MB.
- Preflight passed: no warnings about `precompileModules == true` or unallowlisted `extraDepTargets`.

If preflight failed: stop. The extractor's regime-1 assumption is violated and the analysis can't proceed without resolving it. Surface to the extractor author (you).

## Step 4 — Capture a p=12 trace on the runner (W1)

You need from your CI infra owner before drafting the workflow:
- Fork URL or branch where experimental workflows can live.
- The `runs-on:` label that targets the 12-core self-hosted runners.
- Time-of-day / duration constraints (each capture is ~30–50 minutes).

Workflow sketch (finalize for your CI; this is illustrative, not copy-paste-ready):

```yaml
name: lakeprof-12c-baseline
on: { workflow_dispatch: {} }
jobs:
  capture:
    runs-on: [self-hosted, "<12-core-runner-label>"]
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v4
      - run: elan toolchain install $(cat lean-toolchain)
      - run: pip install lakeprof
      - run: rm -rf .lake
      - run: lakeprof record -o mathlib-clean-12c.log lake build
      - uses: actions/upload-artifact@v4
        with:
          name: lakeprof-12c-baseline
          path: mathlib-clean-12c.log
          retention-days: 90
```

Dispatch via `gh workflow run` or the Actions UI. Wait. Download the artifact.

Validate:
- ~8,000+ `Built X (Ys)` lines.
- **No `(0.00s)` lines** — those mean the cache leaked through and the build wasn't actually clean. If you see them, `rm -rf .lake` wasn't sufficient (check for `~/.cache/mathlib`, `~/.elan`, or other persistent caches the runner re-uses).
- Wall-clock from the first to the last `Built` line is in the **2,500–3,200 s** range. Outside that range = something's off; flag it for the analysis agent.

Drop the file at `~/mathlib4-lakeprof/mathlib-clean-12c.log`.

## Step 5 — Variance baseline (W2; optional, recommended)

Same workflow as Step 4 but **three captures** in a single workflow with `lake clean` (or `rm -rf .lake`) between runs. Sets the empirical noise floor for any scheduling claim — if W1's runs vary by ±8 %, the analysis can't empirically demonstrate a 5 % scheduling win.

Drop the resulting logs at `~/mathlib4-lakeprof/mathlib-clean-12c-run{2,3}.log`.

If runner time is constrained, you can skip this and let the analysis agent flag the missing variance floor as a caveat in its report.

## What you do NOT do here

- Build the orchestrator (analysis agent's job).
- Extend lakeprof's simulator (analysis agent's job).
- Run W3 (VM calibration) or W4 (orchestrator-driven runs). Both depend on the analysis agent's output — W3 picks specific modules from the leverage analysis, W4 needs the orchestrator to exist. They are **post-analysis** data-prep, spec'd in the analysis report and dispatched in a follow-up.

## Handoff

Once Steps 1–4 are done (and ideally Step 5):

```bash
cd ~/mathlib4
claude "$(cat /Users/chelo/mathlib4-lakeprof/experiments/06-scheduler-analysis.md)"
```

The analysis agent will run end-to-end, consume the artifacts above, and produce its report at `/Users/chelo/lakeprof-experiments/reports/06-scheduler-analysis.md`. If the report says "deploy orchestrator" or "escalate," it will include a follow-up data-prep spec (W3, W4) for you to dispatch.
