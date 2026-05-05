# Kickoff — Experiment 01: private-import audit

You're in a git worktree at `/Users/chelo/lakeprof-experiments/01-private-imports` on branch `experiment/01-private-imports`. The branch is based on `local/analysis`, which contains the full lakeprof analysis artifacts (`mathlib-clean.log`, the analysis Python scripts, the experiment briefs, `findings-report.md`, `mathlib-build-deep-dive.md`).

**Read `experiments/01-private-import-audit.md` — that brief is the source of truth.** This file is just the kickoff.

## Environment

- `lakeprof` Python package: `/Users/chelo/lakeprof`. Scripts import via `sys.path.insert(0, "/Users/chelo/lakeprof")`.
- Recorded build log to analyse: `mathlib-clean.log` in this directory (mathlib4 @ `36a97460`, 18-core run, 32m46s).
- Critical-path code must populate edge weights before calling `dag_longest_path_length`:
  ```python
  for u, v, data in g.edges(data=True):
      data["time"] = g.nodes[u]["time"]
  ```
  Without this, you'll get edge counts instead of seconds.
- Edge direction is `importer → importee`; "modules invalidated by editing m" = `networkx.ancestors(g, m)`.

## Run to completion

Work end-to-end through the brief. There is no planning checkpoint — proceed through the full procedure until you have something concrete to report.

1. Run `leverage_analysis.py` against `mathlib-clean.log` to regenerate the top-50 leverage list.
2. Work through modules in leverage order (top-N where N is what you can realistically validate; aim for at least the top 10 modules, more if Lean compiles are fast).
3. For each module: identify conversion candidates per the brief's §Procedure step 2; convert candidates in one go; build the module to check elaboration; revert conversions that fail. Don't validate one-conversion-at-a-time — that's hours of redundant builds.
4. After each module, commit the surviving conversions on `experiment/01-private-imports` with a message citing the imports flipped.
5. After all modules in your batch are done, measure: `lakeprof report -r -i mathlib-clean.log` before vs after the cumulative changes. Standard CP (`lakeprof report -p`) must not move; if it does, something other than imports changed.

## When to stop

Stop and write the report when **any** of these is true:

- You've validated conversions on the top 10+ modules from the leverage list and have a measurable rebuild-CP delta.
- You hit a permission prompt or missing tool you can't resolve — record it as a blocker and stop.
- A compile failure isn't the result of a candidate misclassification (i.e. the import really is public-required but the brief's heuristic said it wasn't) and is widespread enough that you need a human to refine the rules.
- You've spent enough time that further work risks introducing instability.

## Write the report

Always, before stopping. Path:

```
/Users/chelo/lakeprof-experiments/reports/01-private-imports.md
```

Use `experiments/REPORT_TEMPLATE.md`. Must include: imports flipped (list with module + count, link to commits), rebuild-CP before/after, standard-CP before/after (sanity), any conversions that failed and the rule they exposed, realized-vs-91 %-ceiling headroom captured, what module to target next session, branch name where work lives.

## Out of scope for this session

- Don't touch modules outside the top-50 leverage list.
- Don't restructure module contents (that's experiment 04's territory).
- This clone has no `origin` remote — `git push` and `gh pr create` will fail. That's intentional. Local commits only; upstream PR flow happens from a separate clone.
