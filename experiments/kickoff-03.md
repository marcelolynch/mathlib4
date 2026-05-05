# Kickoff — Experiment 03: PR blast predictor as a GitHub Action

You're in a git worktree at `/Users/chelo/lakeprof-experiments/03-pr-predictor` on branch `experiment/03-pr-predictor`. The branch is based on `local/analysis` and contains the full lakeprof analysis artifacts, including the existing `pr_impact.py`.

**Read `experiments/03-pr-blast-predictor.md` — that brief is the source of truth.** This file is just the kickoff.

## Environment

- `lakeprof` Python package: `/Users/chelo/lakeprof`. Existing `pr_impact.py` imports it via a hardcoded `sys.path.insert`. Your productionized version should depend on lakeprof as a normal `pip install`.
- Recorded build log: `mathlib-clean.log` in this directory.

## Run to completion

Work end-to-end through Phases 3a and 3b. Phase 3c (post-launch calibration) requires real PR runs and is out of scope for this session.

1. **Phase 3a — productionize.** Modify a *copy* (e.g. `pr_impact_v2.py`); leave the original. Take paths from CLI/env, drop the hardcoded `sys.path` insert, depend on lakeprof as a normal package. Output a markdown comment matching the brief's spec. Cache the parsed graph between invocations (pickle keyed on the log file's hash) so repeat runs are fast.
2. **Phase 3b — workflow YAML.** Write `.github/workflows/build-impact.yml` per the brief's sketch. Use a sticky-comment action so subsequent pushes update one comment.
3. **README.** Add `experiments/03/README.md` covering deployment: where to host `mathlib-clean.log`, secret/permission needs, sticky-comment behaviour, expected runtime per PR, how to interpret the comment.
4. **Test locally.** Run `pr_impact_v2.py HEAD~5 HEAD` against this worktree's git history. Confirm the markdown output matches the spec. Run twice to confirm the graph cache works.

Commit the productionized script, workflow YAML, and README on `experiment/03-pr-predictor`.

## When to stop

Stop and write the report when **any** of these is true:

- All four steps above complete and the local test produces correct markdown.
- The local test reveals a bug in the productionized script you can't resolve.
- Permission prompt or missing tool you can't resolve.

## Write the report

Always, before stopping. Path:

```
/Users/chelo/lakeprof-experiments/reports/03-pr-predictor.md
```

Use `experiments/REPORT_TEMPLATE.md`. Must include: files produced (absolute paths), local test output (paste the markdown the script produced for `HEAD~5..HEAD`), known caveats (graph staleness, missing API-hash blast pending experiment 02), and concrete deployment steps an upstream maintainer would run.

## Out of scope for this session

- Phase 3c (post-launch calibration on real PRs) — requires the workflow to actually run on mathlib's CI.
- This clone has no `origin` remote. The workflow YAML is a *deliverable* that mathlib maintainers can adopt; it's not for us to merge from here.
