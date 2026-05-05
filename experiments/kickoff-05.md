# Kickoff — Experiment 05: weekly clean-build CI

You're in a git worktree at `/Users/chelo/lakeprof-experiments/05-weekly-ci` on branch `experiment/05-weekly-ci`. The branch is based on `local/analysis` and contains the full lakeprof analysis artifacts.

**Read `experiments/05-weekly-clean-build-ci.md` — that brief is the source of truth.** This file is just the kickoff.

## Environment

- `lakeprof` Python package: `/Users/chelo/lakeprof` (locally; the workflow you produce should `pip install lakeprof` like a normal dependency).
- Existing recorded log for reference shape: `mathlib-clean.log` in this directory.

## Run to completion

Work end-to-end through all three deliverables. There is no planning checkpoint.

1. Write `.github/workflows/weekly-lakeprof.yml` per the brief's sketch. Verify the YAML parses: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/weekly-lakeprof.yml'))"`.
2. Write `fetch_latest_log.sh` that pulls the most recent successful run's artifact via `gh run list / gh run download`. Make it idempotent. Sanity-check the script syntax: `bash -n fetch_latest_log.sh`.
3. Write `experiments/05/README.md` covering: how to interpret a run, expected CP range (~700–800 s), what to do when a run produces `(0.00s)` Built lines (cache wasn't actually clean), how downstream consumers should fetch the artifact, retention policy, runner-size requirements (≥ 16 cores), failure-mode recovery.

Commit all three files on `experiment/05-weekly-ci`.

## When to stop

Stop and write the report when **any** of these is true:

- All three files produced and syntax-validated.
- A YAML or shell syntax error you can't resolve.
- Permission prompt or missing tool you can't resolve.

## Write the report

Always, before stopping. Path:

```
/Users/chelo/lakeprof-experiments/reports/05-weekly-ci.md
```

Use `experiments/REPORT_TEMPLATE.md`. Must include: files produced (absolute paths), validation steps performed, what couldn't be validated without actually running the workflow (and what would validate it), open questions about retention / runner choice / scheduling, and concrete deployment instructions for an upstream maintainer.

## Out of scope for this session

- Actually running the workflow — requires mathlib's CI infra.
- Trend-dashboard scripts that consume the longitudinal data — separate concern, only useful once weeks of artifacts exist.
- This clone has no `origin` remote. The workflow YAML is a deliverable for mathlib maintainers to adopt.
