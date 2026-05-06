# Experiment 06 — Stage 1+: empirical analysis (agent prompt)

This file is the Stage 1+ agent prompt. Kick it off from `~/mathlib4`:

```bash
cd ~/mathlib4
claude "$(cat /Users/chelo/mathlib4-lakeprof/experiments/06-scheduler-analysis.md)"
```

## Prerequisites

Before this session starts, both of these must be true:

- **Stage 0 ran and recommended "proceed."** Read `/Users/chelo/lakeprof-experiments/reports/06-scheduler-stage0.md`. If it said drop, this session should not run.
- **`06-scheduler-data-prep.md` Steps 1–4 are done.** The artifacts listed below should already be on disk.

If either is false, escalate at the very start.

---

## Your task

Re-validate the scheduling-headroom gap against the runner-realistic 12-core trace, then empirically validate it via an external orchestrator on the runner. Apply the committed decision rule. Produce a single report that recommends one of: drop the scheduling thread / deploy the orchestrator in mathlib's CI / escalate.

Run end-to-end. Stop only when the report is written or you're blocked on a prerequisite.

## Inputs you should find on disk

Verify each before starting any analysis. If any are missing, escalate immediately.

| path | purpose |
|---|---|
| `/Users/chelo/lakeprof-experiments/reports/06-scheduler-stage0.md` | Stage 0's report (must say "proceed") |
| `/Users/chelo/mathlib4-lakeprof/scheduler_sim.py` | extended simulator from Stage 0 |
| `/Users/chelo/mathlib4-lakeprof/mathlib-clean.log` | existing p=18 trace (Apple Silicon) |
| `/Users/chelo/mathlib4-lakeprof/mathlib-clean-12c.log` | p=12 baseline from runner (W1) |
| `/Users/chelo/mathlib4-lakeprof/mathlib-clean-12c-run{2,3}.log` | variance traces (W2; optional) |
| `/Users/chelo/mathlib4/manifest.json` + `/Users/chelo/mathlib4/sidecars/` | extracted graph |
| `/Users/chelo/mathlib4/lean4-src/` | lean4 fork with graph-extract patch |

The analysis cannot start without Stage 0's outputs, the W1 trace, and the manifest. Everything else is either reference (the existing 18-core trace) or quality-improving (W2 variance).

## Pointers — read before drafting

### Prior analysis (cite, don't re-derive)

- `/Users/chelo/mathlib4-lakeprof/findings-report.md` — top-line conclusions across the existing five experiments.
- `/Users/chelo/mathlib4-lakeprof/mathlib-build-deep-dive.md` — long-form technical writeup.
- Key facts already established: avg parallelism 44, critical path 750 s, simulator at p=8 → 4,158 s and p=16 → 2,128 s. Cross-runner sharding, phased builds, and naive namespace federation are all ruled out — don't re-litigate.

### lakeprof — the simulator and trace tool

- Source at `/Users/chelo/lakeprof/` (~360 lines of Python).
- Trace format: one `{ISO ts} Built {name} ({self_time_s}s)` line per module.
- `lakeprof report -i LOG -p -s -r` runs critical-path / list-scheduling-simulator / rebuild-aware analyses. The simulator currently uses recorded order as tie-breaker — effectively FIFO.
- Graph reconstruction calls `lake query --no-build --json +<module>:header` to populate import edges with their `isExported` / `isMeta` / `importAll` flags. You don't need to invoke `lake query` directly; `lakeprof.parse(open(LOG))` returns the populated networkx graph.
- Critical-path code must populate edge weights before calling `dag_longest_path_length`:
  ```python
  for u, v, data in g.edges(data=True):
      data["time"] = g.nodes[u]["time"]
  ```

### Graph extractor — the orchestrator's input

- `/Users/chelo/mathlib4/lean4-src/src/lake/Lake/Build/GraphExtract.lean` — header docstring describes schema v2.
- Each per-node sidecar (`<sanitized-id>.node.json`) carries `{command, env, outputs, importArts, setup_json}` — the exact `lean` argv + env Lake would emit per module. The orchestrator just shells out `node.command` with `node.env`; it does not reconstruct Lake's invocation logic.
- Verified byte-identical against a prior Python prototype on 175 sample nodes (Init / Algebra.Group.Defs / Aesop.BaseM / Cache.Hashing).

## Decision rule (committed before measuring)

Compute `gap = (FIFO_wall − HLFET_wall) / FIFO_wall` at p=12. Apply mechanically:

- **< 5 %** → recommend dropping the scheduling thread; effort goes to other levers (private import, API hash, Analysis split, weekly CI).
- **5–15 %** → recommend deploying the external orchestrator in mathlib's CI as a wrapper script. Optionally upstream a Lake patch later.
- **> 15 %** → escalate; orchestrator deployment becomes urgent and a Lake patch becomes justified upstream-engineering work.

Do not move the goalposts after seeing the number.

## Procedure

### Step 1 — Re-simulate against the runner trace

Use Stage 0's `scheduler_sim.py` (already at `/Users/chelo/mathlib4-lakeprof/scheduler_sim.py`). Run all four policies (FIFO / HLFET / LPT / Random) at p=12 against `mathlib-clean-12c.log` (W1). The runner's per-module self-times differ from Apple Silicon, so this gap is the runner-realistic one — Stage 0's gap was a graph-shape estimate built on Apple Silicon self-times.

Compute `runner_gap = (FIFO_wall − HLFET_wall) / FIFO_wall` against the W1 trace.

Apply the decision rule:
- **< 5 %** → recommend dropping after runner re-validation. Skip Steps 3–4; write the "drop" report.
- **5–15 %** → recommend deploying orchestrator. Continue.
- **> 15 %** → escalate. Continue.

If `runner_gap` differs materially from Stage 0's `mathlib-clean.log` gap, note the divergence — it's evidence that runner self-times shift the priority calculus. Worth flagging in the report.

### Step 2 — Variance floor (only if W2 traces exist)

Compute mean / stdev / range across `mathlib-clean-12c.log` + `mathlib-clean-12c-run{2,3}.log`. Compare to the gap from Step 1.

If `runner_gap < 2× stdev`, the empirical claim is weak regardless of simulator math — note the caveat prominently in the report and recommend more variance baselining before any deployment.

If W2 traces are absent, skip this step but flag "variance floor not measured" as a caveat in the report.

### Step 3 — Orchestrator implementation + olean equivalence

Build the dispatcher (~150–250 lines of Python). Responsibilities:
- Read `manifest.json` plus per-node sidecars (lazy load — don't slurp 440 MB into memory).
- Maintain a ready-queue of modules whose `importArts` references have all completed, ordered by a pluggable priority function (the same four policies as Step 1).
- Spawn up to `p` concurrent `subprocess.Popen(node.command, env=merge(os.environ, node.env))`.
- On completion: mark dependents ready when all their `importArts` complete. On failure: stop new dispatches, drain in-flight, surface the failing module's stderr, exit non-zero.

Olean equivalence test (do this before claiming any orchestrator-driven wall-clock is meaningful): pick a non-trivial slice — `Mathlib.Algebra.Group.Defs`'s ~84-module closure plus a few hundred downstream modules. Build the slice with Lake (locally or on the runner; if you don't have local Lean, spec a CI workflow for the data-prep follow-up round). Build the same slice with the orchestrator. Diff the resulting oleans. They must match modulo known toolchain non-determinism. If they don't match, escalate before anything else — the orchestrator is bug-shaped and W4 wall-clocks would be meaningless.

### Step 4 — Spec the next data-prep round

If the Step 1 gap was ≥ 5 %, the report needs to recommend a follow-up round of data-prep that the user dispatches. Spec these workflows:

- **W3 — VM calibration.** Build one CP-heavy module (suggest `Mathlib.Analysis.Distribution.SchwartzSpace.Basic`) under three loads: alone, with 11 cheap modules co-resident, with 11 AVX-heavy modules co-resident. Use Stage 0's `policy_divergence.json` to pick CP-heavy modules where HLFET vs FIFO actually diverges — those are the ones whose calibrated self-time matters for any priority decision.
- **W4 — orchestrator-driven full-build runs.** Three runs at p=12 under FIFO / HLFET / LPT priorities. W4-FIFO is the parity check (should match W1 within ~5 %); larger gap = orchestrator overhead.

Workflow YAML outlines + expected runner-minute cost go into the report's "Next data-prep round" section. Don't dispatch them — that's the user's job in the next data-prep iteration.

### Step 5 — Write the report

Single file at:

```
/Users/chelo/lakeprof-experiments/reports/06-scheduler-analysis.md
```

Use `experiments/REPORT_TEMPLATE.md`. Sections:

1. Executive summary (5–10 lines): the runner-trace gap, the recommendation, link back to Stage 0's report.
2. Per-policy wall-clocks at p=12 against the W1 trace (table). Include the Stage-0 18-core numbers for comparison.
3. Variance floor (Step 2) — or "not measured" if W2 traces absent.
4. Orchestrator olean-equivalence verdict (Step 3) — only if reached.
5. Headline gap and the decision (drop / deploy / escalate) with the specific numbers.
6. *(deploy / escalate)* Next data-prep round spec — W3 + W4 workflow YAML outlines, expected runner-minute costs, what numbers each would produce.
7. Files produced this session (paths to `orchestrator.py`, slice oleans, etc.).
8. What to do next (concrete instructions for the next agent or human).

Commit the artifacts you produced (simulator extension, orchestrator, any helper scripts) on the worktree branch. Report lives outside the worktree — survives teardown.

## What you do NOT do

- Dispatch any CI workflows. You spec them; the user dispatches in the next data-prep round.
- Run extraction or build the lean4 fork. Those are data-prep prerequisites that should already be done.
- Execute W3 / W4. Spec them; the user dispatches.
- Apply the decision rule against W4 wall-clocks. The current decision rule applies to the simulator gap from Step 2. W4 numbers (when they exist) feed a *follow-up* analysis session.

## Out of scope

- Multi-runner orchestration / cross-runner build sharding (already ruled out).
- Phased / multi-stage builds (already ruled out).
- Patching Lake itself (only sketch as follow-up if the recommendation is "deploy" + the user wants Lake-side parity).
- Toolchain changes.
- Productionizing the orchestrator beyond the experiment (incremental rebuild, full `cache get` integration, error recovery, monorepo support).

## When to escalate

Surface immediately and stop:
- A required input from data-prep is missing (W1 trace, manifest, sidecars, lean4-src commits).
- Orchestrator can't reproduce Lake's oleans on the slice and the divergence isn't trivially-traceable to known toolchain non-determinism.
- Simulator gap lands on a decision-rule boundary (4–6 % or 14–16 %) — the user's risk tolerance decides.
- mathlib's target depends on `cc_compile` / `cc_link` / `package_extra_dep` nodes (out of v1 extractor scope) — manifest is incomplete.
- A fundamental ambiguity in what "smart scheduling" should optimize for that wasn't specified (e.g. p50 vs p95 wall-clock, latency vs throughput, single-job vs queue-of-jobs).
