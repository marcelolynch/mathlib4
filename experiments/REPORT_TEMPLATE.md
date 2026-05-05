# Experiment 0X — <name>

> Template. Each experiment's final report lives at
> `/Users/chelo/lakeprof-experiments/reports/0X-<short-name>.md`.
> Reports outlive the worktree — discoverable later via `ls /Users/chelo/lakeprof-experiments/reports/`.

## Status

One of: **completed** / **partial** / **blocked** / **abandoned**. One sentence on what that means concretely (e.g., "partial — 2 of 5 modules audited; rebuild-CP delta validated").

## What was done

Bullet list of the work performed in this session. Specific enough that someone returning in a month can pick up where you left off without re-reading the brief.

## Files produced or modified

Absolute paths, with one-line purpose for each.

- `/path/to/file` — what it is
- `/path/to/file` — what it is

Distinguish files in the worktree (will be lost if worktree is removed without committing) from files committed to a branch (survive worktree removal) from files outside the worktree (survive regardless).

## Measurements / validation

Concrete numbers. Before/after where applicable. What you actually ran to verify, not what you intended to run.

| metric | before | after | delta |
|---|---:|---:|---:|
| ... | ... | ... | ... |

If validation was incomplete (e.g., "didn't recompile because Lean toolchain wasn't installed"), say so.

## Blockers / open questions

Anything that stopped progress or needs a human decision before the next step. Phrase as concrete questions.

## What to do next

The most important section. Concrete steps a future Claude (or human) can pick up:

1. Specific next action, with file path and command if relevant.
2. ...
3. ...

If the next step is "stop, this experiment isn't worth pursuing further," say so plainly with the reason.

## How to resume

One paragraph: which worktree to enter, which kickoff file to feed a new Claude session, any state in the worktree that matters (uncommitted changes, etc.).

```
cd /Users/chelo/lakeprof-experiments/0X-<name>
claude "$(cat experiments/kickoff-0X.md)"
# then mention: "previous report at reports/0X-<name>.md, resume from 'What to do next'"
```
