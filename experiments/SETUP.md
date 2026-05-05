# Running the experiments in parallel — worktree + multi-Claude setup

Each experiment runs in its own git worktree on its own branch. All worktrees share the same underlying `mathlib4-lakeprof` clone via `git worktree`, so disk and `.git` state are shared but working trees are independent.

The analysis artifacts (the `*.py` scripts, `mathlib-clean.log`, `figs/`, `findings-report.md`, `mathlib-build-deep-dive.md`, `experiments/`, etc.) are committed once to a local-only branch `local/analysis`, and every experiment worktree branches off that. This keeps the analysis context visible in every worktree without symlinks.

The `origin` remote has been removed from this clone, so `git push` errors out with no destination — there's no way to accidentally push to upstream mathlib. If you ever need to re-sync upstream: `git remote add origin https://github.com/leanprover-community/mathlib4.git && git fetch origin`.

## Layout

```
mathlib4-lakeprof/                   # main checkout, on master
└── (will commit analysis files to local/analysis branch)

lakeprof-experiments/
├── reports/                         # per-experiment final reports, survives worktree teardown
│   ├── 01-private-imports.md
│   ├── 02-api-hash.md
│   ├── 03-pr-predictor.md
│   ├── 04-analysis-split.md
│   └── 05-weekly-ci.md
├── 01-private-imports/              # worktree off local/analysis, branch experiment/01-private-imports
├── 02-api-hash/                     # worktree off local/analysis, branch experiment/02-api-hash
├── 03-pr-predictor/                 # worktree off local/analysis, branch experiment/03-pr-predictor
├── 04-analysis-split/               # worktree off local/analysis, branch experiment/04-analysis-split
└── 05-weekly-ci/                    # worktree off local/analysis, branch experiment/05-weekly-ci
```

Reports are the **discoverable result of each experiment**. They use the template at `experiments/REPORT_TEMPLATE.md` (status / what was done / files produced / measurements / blockers / what to do next / how to resume). The `reports/` directory lives outside every worktree on purpose — it's meant to survive worktree teardown so you can come back weeks later, run `ls /Users/chelo/lakeprof-experiments/reports/`, and pick up where things left off.

## Step 1 — commit the analysis artifacts to `local/analysis`

From the main checkout, on `master`:

```bash
cd /Users/chelo/mathlib4-lakeprof

# Make a local-only branch.
git switch -c local/analysis

# Stage every untracked artifact at the top level. Avoid `git add -A` so you
# don't accidentally pick up build outputs from .lake/ or test artifacts.
git add \
  experiments/ figs/ \
  *.py *.md *.txt *.log *.json *.npy *.html

# Verify nothing huge sneaks in.
git status --short
git diff --cached --stat | tail -5

# Commit.
git commit -m "Add lakeprof analysis artifacts (local-only)"
```

## Step 2 — create worktrees off `local/analysis`

```bash
mkdir -p /Users/chelo/lakeprof-experiments/reports

cd /Users/chelo/mathlib4-lakeprof

git worktree add /Users/chelo/lakeprof-experiments/01-private-imports \
  -b experiment/01-private-imports local/analysis

git worktree add /Users/chelo/lakeprof-experiments/02-api-hash \
  -b experiment/02-api-hash local/analysis

git worktree add /Users/chelo/lakeprof-experiments/03-pr-predictor \
  -b experiment/03-pr-predictor local/analysis

git worktree add /Users/chelo/lakeprof-experiments/04-analysis-split \
  -b experiment/04-analysis-split local/analysis

git worktree add /Users/chelo/lakeprof-experiments/05-weekly-ci \
  -b experiment/05-weekly-ci local/analysis
```

Every worktree now has the full mathlib source plus all the analysis files, no symlinks needed.

## Step 3 — verify

```bash
git -C /Users/chelo/mathlib4-lakeprof worktree list

for d in /Users/chelo/lakeprof-experiments/*/; do
  echo "=== $d ==="
  ls "$d/mathlib-clean.log" "$d/experiments/00-overview.md" 2>&1 | head
  git -C "$d" branch --show-current
done

# lakeprof importable from each worktree:
cd /Users/chelo/lakeprof-experiments/01-private-imports
python3 -c "import sys; sys.path.insert(0, '/Users/chelo/lakeprof'); import lakeprof; print(lakeprof.__file__)"
```

## Step 4 — launch one Claude per experiment

Open one terminal per experiment, `cd` into its worktree, run `claude`, and paste the contents of the matching kickoff file. Each kickoff file points the agent at its brief (the source of truth) and at a checkpoint to stop at before doing anything irreversible.

| terminal | worktree | kickoff prompt |
|---|---|---|
| 01 | `/Users/chelo/lakeprof-experiments/01-private-imports` | `experiments/kickoff-01.md` |
| 02 | `/Users/chelo/lakeprof-experiments/02-api-hash` | `experiments/kickoff-02.md` |
| 03 | `/Users/chelo/lakeprof-experiments/03-pr-predictor` | `experiments/kickoff-03.md` |
| 04 | `/Users/chelo/lakeprof-experiments/04-analysis-split` | `experiments/kickoff-04.md` |
| 05 | `/Users/chelo/lakeprof-experiments/05-weekly-ci` | `experiments/kickoff-05.md` |

Quickest launch pattern:

```bash
cd /Users/chelo/lakeprof-experiments/01-private-imports
claude "$(cat experiments/kickoff-01.md)"
```

…or just `claude`, then paste the kickoff file's contents.

## Concurrency caveats

The kickoffs are configured to **run to completion** — each agent works through its full procedure and only stops when the report is ready (or when blocked). That has implications for parallel execution:

- **RAM contention between 01 and 04 is now real.** Both will compile Lean to validate their work. A full mathlib elaboration peaks at ~16+ GB. Running both simultaneously on a 32 GB box **will swap and may OOM-kill the agent's shell.** Options:
  - On ≤ 32 GB: launch 01 and 04 sequentially. Run 02, 03, 05 in parallel with whichever is active.
  - On 64+ GB: launch all five together.
  - Either way, run `lake exe cache get` once per worktree before launching to skip clean builds — incremental builds after a `cache get` are minutes, not the 30-minute clean rebuild.
- **Permission prompts will silently stall agents.** With nobody watching the terminal, an agent paused on `Bash` permission for `git commit` does nothing until you approve. Pre-approve common tools per worktree — at minimum `Bash`, `Edit`, `Write`, and any `git`/`lake`/`lean`/`python` invocations the agents will use. Check `.claude/settings.json` in each worktree (or set globally).
- **Disk usage adds up.** Each worktree that compiles produces its own `.lake/build/` (~5–10 GB). 01 and 04 together = up to 20 GB beyond the existing checkout. Monitor with `du -sh /Users/chelo/lakeprof-experiments/*/.lake/`.
- **Don't share branch names.** Each worktree has its own pre-created branch. If you re-run a setup step, `git worktree add -b` will fail loudly rather than silently colliding — that's intentional.
- **`.lake/` in each worktree is independent.** Experiment 04's split builds don't pollute experiment 01's elaborator state, but each worktree pays its own build cost. `lake exe cache get` is the mitigation.

### Recommended launch sequence on a 32 GB box

```bash
# Terminal 1: experiment 02 (no Lean compile, fast)
# Terminal 2: experiment 03 (no Lean compile, fast)
# Terminal 3: experiment 05 (no Lean compile, fast)
# Terminal 4: experiment 01 (Lean compile)
# Wait until 01 has written its report, then:
# Terminal 5: experiment 04 (Lean compile)
```

On 64+ GB, just launch all five.

## Local-only by design

This clone has no `origin` remote. Experiments produce **local commits only**. There is no PR-opening flow from this checkout.

When experiment 01 or 04 produces work that's worth sending upstream:

1. Spin up a separate mathlib4 clone with a fork remote configured.
2. Either cherry-pick the relevant commits, or produce a patch series with `git format-patch master..experiment/01-private-imports` and `git am` it in the other clone.
3. Open the PR from there.

Keeping this clone read-only (push-wise) means none of the experiment Claudes can accidentally invoke `gh pr create` or `git push origin` and reach upstream.

## Discovering results later

Each experiment writes a final report to `/Users/chelo/lakeprof-experiments/reports/0X-<name>.md` before stopping. To check progress across all experiments:

```bash
ls /Users/chelo/lakeprof-experiments/reports/

# Quick status across all reports — first non-empty line of the Status section:
for r in /Users/chelo/lakeprof-experiments/reports/*.md; do
  echo "=== $(basename "$r") ==="
  awk '/^## Status/{flag=1; next} flag && NF{print; exit}' "$r"
done
```

Reports follow `experiments/REPORT_TEMPLATE.md`. The "What to do next" and "How to resume" sections are designed so a future Claude session (or a future you) can pick up the experiment without re-reading the brief.

To resume an experiment, re-enter its worktree (it should still be there unless you ran `git worktree remove`) and feed the matching kickoff file to a new Claude, plus a hint to read the existing report:

```bash
cd /Users/chelo/lakeprof-experiments/01-private-imports
claude "$(cat experiments/kickoff-01.md)
The previous session's report is at /Users/chelo/lakeprof-experiments/reports/01-private-imports.md — read it and resume from its 'What to do next' section."
```

If a worktree was torn down before its experiment finished, the report still tells you what state it was in, but you'll need to recreate the worktree (`git worktree add ...`) before resuming code work. The branch (`experiment/0X-...`) was preserved by `git worktree remove` and still has all the committed work.

## Tearing down

```bash
cd /Users/chelo/mathlib4-lakeprof

# Refuses if the worktree has uncommitted changes — that's the safety.
git worktree remove /Users/chelo/lakeprof-experiments/01-private-imports

# Branches stick around. Delete experiment branches you don't need:
git branch -d experiment/01-private-imports

# local/analysis stays — it's reusable for future experiments.
# /Users/chelo/lakeprof-experiments/reports/ stays untouched — those reports outlive the worktrees.
```
