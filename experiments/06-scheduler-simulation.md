# Experiment 06 — Stage 0: pure-simulation agent prompt

The cheap first pass. Pure simulation against the existing `mathlib-clean.log`. No CI workflows, no lean4 fork build, no runner access, no graph extraction. The agent extends lakeprof's scheduler with priority policies and applies the decision rule.

Kick off from `~/mathlib4-lakeprof`:

```bash
cd ~/mathlib4-lakeprof
claude "$(cat experiments/06-scheduler-simulation.md)"
```

If this stage's report says **drop**, the experiment ends here. If it says **proceed**, follow up with `06-scheduler-data-prep.md` then `06-scheduler-analysis.md` (Stage 1+).

---

## Your task

Quantify the *theoretical* wall-clock headroom from smarter task scheduling at p=12. Apply the committed decision rule against the 18-core trace. Recommend drop or proceed.

This stage uses Apple Silicon self-times from the existing 18-core trace. They aren't perfectly representative of Xeon Gold 6132 + KVM behavior, but the relative gap between scheduling policies is largely graph-shape-determined and should transfer. If this stage already says drop, no runner-time investment is needed.

Run end-to-end. Stop when the report is written.

## Inputs you should find on disk

| path | purpose |
|---|---|
| `/Users/chelo/lakeprof/` | lakeprof Python package source (~360 lines) |
| `/Users/chelo/mathlib4-lakeprof/mathlib-clean.log` | existing 18-core trace |

If `mathlib-clean.log` is missing, escalate — this stage can't run.

## Pointers — read before drafting

- `/Users/chelo/mathlib4-lakeprof/findings-report.md` — top-line conclusions (cite, don't re-derive). Avg parallelism 44, CP 750 s, simulator at p=8 → 4,158 s and p=16 → 2,128 s. p=12 should land near ~2,800 s under FIFO.
- `/Users/chelo/mathlib4-lakeprof/mathlib-build-deep-dive.md` — long-form writeup if you need more context. Already-ruled-out approaches (cross-runner sharding, phasing, naive federation) — don't propose them.
- `/Users/chelo/lakeprof/` — simulator currently uses recorded order as tie-break, effectively FIFO. Trace format: one `{ISO ts} Built {name} ({self_time_s}s)` per line. `lakeprof.parse(open(LOG))` returns the populated networkx graph.

## Decision rule (committed before measuring)

Compute `gap = (FIFO_wall − HLFET_wall) / FIFO_wall` at p=12 against `mathlib-clean.log`.

- **< 5 %** → recommend dropping. Effort goes to other levers (private import, API hash, Analysis split, weekly CI).
- **5–15 %** → recommend Stage 1 (capture runner trace and re-simulate against runner-realistic self-times before committing to the orchestrator).
- **> 15 %** → recommend Stage 1, urgent. The orchestrator path is justified.

Apply mechanically. Don't move the goalposts.

**Boundary caveat:** this stage uses Apple Silicon self-times. The runner is Xeon + KVM, so per-module compile times differ. The gap *direction* is graph-shape-determined and should transfer; the gap *magnitude* may shift by a few percent. If you compute 4–6 %, recommend proceeding to Stage 1 — runner self-times might push it over the threshold.

## Procedure

### Step 1 — Extend lakeprof's simulator

Add priority policies to the list-scheduler. Implement at minimum:

- **FIFO** — recorded-order tie-break (today's behavior). Should be a no-op refactor that preserves current results.
- **HLFET** — longest weighted path-to-sink. Precompute via single backward pass over a reverse topological order: `cp_to_sink[v] = self_time(v) + max(cp_to_sink[succ] for succ in successors(v))`, or `self_time(v)` if v is a sink.
- **LPT** — longest self-time first.
- **Random** — fixed seed (42) for reproducibility.

API surface: a `priority` keyword on the simulator entry point taking either a string ("fifo" / "hlfet" / "lpt" / "random") or a node-id → sortable-key callable. Output per call: simulated wall-clock at the requested p, per-task start/stop trace, and the list of intervals where two policies pick different ready tasks (useful diagnostic for Stage 2's W3 module selection).

Critical-path / longest-path code must populate edge weights before calling `dag_longest_path_length`:

```python
for u, v, data in g.edges(data=True):
    data["time"] = g.nodes[u]["time"]
```

Without this, `weight="time"` falls back to default 1 and you get edge counts, not seconds. Verify the FIFO simulation result matches the existing `lakeprof report -s` numbers before relying on the extension.

Save the extended simulator at `/Users/chelo/mathlib4-lakeprof/scheduler_sim.py`. Commit on the worktree branch (whatever you're on; this isn't tied to one of the existing experiment worktrees).

### Step 2 — Compute the gap

Run all four policies at p=12 against `mathlib-clean.log`. Record per-policy wall-clock + schedule trace.

Sanity checks before trusting any number:
- FIFO at p=12 should land near 2,800 s (between p=8 → 4,158 s and p=16 → 2,128 s). Materially off → simulator regression.
- Random ≥ FIFO and ≥ HLFET (or close to it). If Random is faster, the priority key isn't being respected.
- HLFET ≤ FIFO. LPT can go either way.

Compute `gap = (FIFO_wall − HLFET_wall) / FIFO_wall`. Apply the decision rule.

### Step 3 — Diagnose where policies diverge (only if proceeding)

If gap ≥ 5 %, walk the HLFET-vs-FIFO trace and list intervals where the two policies pick a different ready task. The modules involved are the candidates for Stage 2's W3 module selection (VM calibration on CP-heavy nodes that scheduling actually touches).

Save as `/Users/chelo/mathlib4-lakeprof/policy_divergence.json` or similar. Reference from the report.

### Step 4 — Write the report

Single file at:

```
/Users/chelo/lakeprof-experiments/reports/06-scheduler-stage0.md
```

Use `experiments/REPORT_TEMPLATE.md`. Sections:

1. Executive summary: simulated gap at p=12, the decision (drop / proceed-to-Stage-1), the Apple-Silicon-self-time caveat.
2. Per-policy simulator wall-clocks at p=12 (table).
3. Sanity-check verdicts (Step 2).
4. *(proceeding)* Policy divergence summary — how many intervals, top modules involved, link to the JSON.
5. *(proceeding)* Explicit handoff: pointer to `06-scheduler-data-prep.md` and what artifacts the next stage needs.
6. *(dropping)* Closing rationale: which other lever should get the freed effort, with a one-line link to its experiment.
7. Files produced this session: `scheduler_sim.py`, optionally `policy_divergence.json`, the report itself.

## What you do NOT do

- Run any CI workflows.
- Capture a runner trace.
- Build the lean4 fork or run `lake graph-extract`.
- Build the orchestrator.
- Apply the decision rule against any number other than the 18-core simulated gap from `mathlib-clean.log`.

## Out of scope

- Cross-runner build sharding (already ruled out).
- Phased / multi-stage builds (already ruled out).
- Patching Lake itself.
- Toolchain changes.
- Simulating at non-12-core counts as a substitute.

## When to escalate

- `mathlib-clean.log` is missing.
- Simulator extension regresses existing FIFO behavior (FIFO at p=12 not near 2,800 s, or doesn't match `lakeprof report -s` numbers).
- Gap lands on the decision-rule boundary (4–6 %) and the Apple-Silicon-self-time caveat creates ambiguity you can't resolve.
- A fundamental ambiguity in what "smart scheduling" should optimize for that wasn't specified (latency vs throughput, single-job vs queue, etc.).
