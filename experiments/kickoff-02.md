# Kickoff — Experiment 02: API-hash measurement tool

You're in a git worktree at `/Users/chelo/lakeprof-experiments/02-api-hash` on branch `experiment/02-api-hash`. The branch is based on `local/analysis` and contains the full lakeprof analysis artifacts.

**Read `experiments/02-api-hash-measurement.md` — that brief is the source of truth.** This file is just the kickoff.

## Environment

- `lakeprof` Python package: `/Users/chelo/lakeprof`.
- Recorded build log: `mathlib-clean.log` in this directory.
- mathlib's git history is in this worktree's `.git` (shared via `git worktree`). Use `git log`, `git show`, `git diff` directly — no symlink dance.

## Run to completion

Work end-to-end through Phases 2a, 2b, and 2c of the brief. The headline deliverable is the empirical answer to "what fraction of mathlib commits actually change the API?" — don't stop until you have a number.

1. **Phase 2a — build `api_hash.py`.** Validate on 4–6 hand-picked commits where you know the expected verdict (proof-body edit → unchanged; public-lemma rename → changed; comment-only → unchanged). Reject the implementation and iterate if validation fails.
2. **Phase 2b — replay over commit history.** Use `git show <sha>:<path>` to read file contents at each commit — **do NOT do `git checkout` per commit**, that'll be hours and may fight with the worktree state. Read-only access via `git show` is fast (target ≤ 15 min for ~2,000 commits). Output: `api_blast_history.{csv,jsonl}` with one row per commit and both content-blast and API-blast columns.
3. **Phase 2c — analyze.** Compute the distribution of `api_blast_CP / content_blast_CP`, the fraction of commits with `api_blast_modules == 0`, per-namespace breakdowns. Generate the figure `figs/11-api-vs-content-blast.svg`. Write `api_diff_report.md` with the headline finding.

Commit `api_hash.py`, the JSONL/CSV, the figure, and `api_diff_report.md` on `experiment/02-api-hash`.

## When to stop

Stop and write the report when **any** of these is true:

- All three phases done, headline number computed.
- Hasher fails validation on simple cases and the parsing fix isn't obvious — record what's broken.
- Phase 2b errors out on a substantial fraction of commits (parsing failures, encoding issues, etc.) and the failure mode isn't fixable in the session.
- Permission prompt or missing tool you can't resolve.

## Write the report

Always, before stopping. Path:

```
/Users/chelo/lakeprof-experiments/reports/02-api-hash.md
```

Use `experiments/REPORT_TEMPLATE.md`. Must include: file inventory (absolute paths), validation cases with verdicts, **the headline number** (what fraction of commits change the API), per-namespace breakdown if computed, parsing-coverage caveats, and concrete next steps (typically: present this number to Lean/Lake maintainers as evidence for signature-hash caching).

## Out of scope for this session

- The full commit-history replay (Phase 2b).
- Any plot generation (Phase 2c).
- Hooking this into Lake — it's a measurement tool, not a cache patch.
- This clone has no `origin` remote. Local commits only.
