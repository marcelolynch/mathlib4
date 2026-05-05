# Kickoff — Experiment 04: split top-5 Analysis CP modules

You're in a git worktree at `/Users/chelo/lakeprof-experiments/04-analysis-split` on branch `experiment/04-analysis-split`. The branch is based on `local/analysis` and contains the full lakeprof analysis artifacts.

**Read `experiments/04-analysis-cp-split.md` — that brief is the source of truth.** This file is just the kickoff.

## Environment

- `lakeprof` Python package: `/Users/chelo/lakeprof`.
- Recorded build log: `mathlib-clean.log` in this directory. Use it to predict the CP impact of any proposed split *before* editing source.
- Critical-path code must populate edge weights:
  ```python
  for u, v, data in g.edges(data=True):
      data["time"] = g.nodes[u]["time"]
  ```

## Run to completion

Work end-to-end through the brief's procedure on **`Mathlib.Analysis.Distribution.SchwartzSpace.Basic`** only (heaviest CP module, 32 s). The other four modules are for separate sessions.

1. **Step 1 — characterize.** Read the module. Count declarations by kind. Identify natural cleavage planes.
2. **Step 2 — propose a split.** Write `experiments/04/PROPOSAL-SchwartzSpace.md`: which declarations move where, predicted CP impact computed via lakeprof on a manually-edited graph, expected self-time of each new module.
3. **Apply the worth-doing-iff gates:**
   - Split drops the module's CP self-time by ≥ 60 %.
   - No new module on the new CP at > self_time/3 of original.
   - No cycles introduced.
   - Predicted `self_time(Defs) + self_time(Lemmas) ≤ 1.1 × self_time(original)`.
   If any gate fails, **do not execute the split.** Write a "do not proceed" recommendation in the report and stop. Marginal splits aren't worth the risk; the answer "this module shouldn't be split" is a valid result.
4. **Step 3 — execute the split.** Edit `.lean` source. Move declarations to new files. Update imports in the original module's downstream consumers (the brief's diff predicts which modules will need import updates).
5. **Step 4 — measure.** Build the affected modules (`lake build Mathlib.Analysis.Distribution.SchwartzSpace.Basic` and a few key downstream consumers). Compare actual CP impact against predicted.
6. Commit on `experiment/04-analysis-split` with a message like `refactor(Analysis): split SchwartzSpace.Basic (CP -X s)` including before/after CP and downstream-import changes in the body.

## When to stop

Stop and write the report when **any** of these is true:

- Split executed, builds clean, measured CP delta is within ±5 s of predicted.
- A worth-doing-iff gate fails — write a "do not proceed" report.
- Build fails after the split and the failure isn't a simple import fix-up (e.g. typeclass resolution loops, mutual-import cycles you didn't predict). Revert the source changes, write a "blocked" report.
- Permission prompt or missing tool you can't resolve.

## Write the report

Always, before stopping. Path:

```
/Users/chelo/lakeprof-experiments/reports/04-analysis-split.md
```

Use `experiments/REPORT_TEMPLATE.md`. Must include: declaration inventory, proposed split summary (link to PROPOSAL-SchwartzSpace.md), gate verdicts (each one pass/fail with numbers), predicted vs measured CP delta if executed, downstream import changes, recommendation to proceed-with-PR or not, and **explicit flag that mathematical review is still needed before any upstream PR** (the agent did not have domain expertise; an Analysis maintainer should confirm the split is mathematically reasonable, not just compilation-clean).

## Out of scope for this session

- Editing `.lean` source. That's the next session, after the proposal is reviewed.
- The other four modules.
- Re-recording `mathlib-clean.log` (only do that after splits actually land).
- This clone has no `origin` remote. Local commits only.
