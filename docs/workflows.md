# GitHub Workflows Summary

### Note

- The grouping below is done mainly by primary trigger (the main event that causes runs).
- _Importance_ is a rough evaluation of the importance of the workflow in our operations:
  - High: core CI logic, merge-flow, branch-health, or high-impact automation.
  - Medium: quality checks, reports, notifications, and operational helpers.
  - Low: cosmetic/status/bookkeeping helpers with limited blast radius.

### Trigger type glossary

- `pull_request`: runs on PR activity using the PR branch workflow file.
- `pull_request_target`: runs on PR activity using the base branch workflow file (safer access to repository secrets/write operations when guarded correctly).
- `merge_group`: runs for GitHub merge queue batches.
- `issue_comment`: runs when issue or PR comments are created/edited (depending on `types`).
- `pull_request_review`: runs on PR review submissions.
- `pull_request_review_comment`: runs on inline PR review comments.
- `push`: runs when commits are pushed to matching branches/tags.
- `schedule`: runs on a cron schedule in UTC.
- `workflow_dispatch`: manual run from the Actions UI or API.
- `workflow_run`: runs after another workflow run reaches specified activity types (for example `completed`).
- `issues`: runs on issue lifecycle events (for example `closed`, `reopened`).
- `workflow_call`: reusable workflow entrypoint, triggered only when called by another workflow.

# Summary
## Main CI

| File | Name / status  |  Importance | Triggers | Description |
|---|---|---|---|---|
| [`build_fork.yml`](../.github/workflows/build_fork.yml) | [![continuous integration (mathlib forks)](https://github.com/leanprover-community/mathlib4/actions/workflows/build_fork.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/build_fork.yml) | High | `pull_request_target` | Runs CI for fork PRs via `pull_request_target`, using the reusable build template. |
| [`bors.yml`](../.github/workflows/bors.yml) | [![continuous integration (staging)](https://github.com/leanprover-community/mathlib4/actions/workflows/bors.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/bors.yml) | High | `push` | Runs staging/trying branch CI by calling the reusable build template. |
| [`build.yml`](../.github/workflows/build.yml) | [![continuous integration](https://github.com/leanprover-community/mathlib4/actions/workflows/build.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/build.yml) | High | `merge_group, push` | Main push/merge-group CI entrypoint that delegates to `build_template.yml`. |


### The main CI pipelines above all use this reusable workflow for the base logic:
| File  | Description |
|---|---|
| [`build_template.yml`](../.github/workflows/build_template.yml) | Reusable CI workflow (`workflow_call`) that performs Lean setup, build/test/lint steps, cache/artifact handling, and reporting. |

## PR / merge queue

Primary trigger for this section: PR/merge-queue events (`pull_request`, `pull_request_target`, `merge_group`).

| File | Name / status  |  Importance | Triggers | Description |
|---|---|---|---|---|
| [`actionlint.yml`](../.github/workflows/actionlint.yml) | [![Check workflows](https://github.com/leanprover-community/mathlib4/actions/workflows/actionlint.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/actionlint.yml) | Medium | `merge_group, pull_request` | Runs `actionlint` with reviewdog for workflow changes on PRs and merge queues. |
| [`commit_verification.yml`](../.github/workflows/commit_verification.yml) | [![Commit Verification](https://github.com/leanprover-community/mathlib4/actions/workflows/commit_verification.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/commit_verification.yml) | Medium | `pull_request` | Verifies `transient:` and `x:` commits in PRs and posts a verification summary comment. |
| [`pre-commit.yml`](../.github/workflows/pre-commit.yml) | [![Run pre-commit and in-place update PR on push](https://github.com/leanprover-community/mathlib4/actions/workflows/pre-commit.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/pre-commit.yml) | Medium | `pull_request, push` | Runs pre-commit hooks on pushes/PRs and uses pre-commit-ci lite for automatic fixes. |
| [`check_pr_titles.yaml`](../.github/workflows/check_pr_titles.yaml) | [![Check PR titles](https://github.com/leanprover-community/mathlib4/actions/workflows/check_pr_titles.yaml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/check_pr_titles.yaml) | Low | `pull_request_target` | Validates PR titles against project conventions and maintains a sticky guidance comment. |
| [`pr_suggestions.yml`](../.github/workflows/pr_suggestions.yml) | [![PR suggestions](https://github.com/leanprover-community/mathlib4/actions/workflows/pr_suggestions.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/pr_suggestions.yml) | Low | `pull_request_target` | Posts reminder comments for PRs based on changed files and other rules |
| [`lint_and_suggest_pr.yml`](../.github/workflows/lint_and_suggest_pr.yml) | [![lint and suggest](https://github.com/leanprover-community/mathlib4/actions/workflows/lint_and_suggest_pr.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/lint_and_suggest_pr.yml) | Low | `pull_request` | Runs style linting in suggest mode on pull requests. |
| [`PR_summary.yml`](../.github/workflows/PR_summary.yml) | [![Post PR summary comment](https://github.com/leanprover-community/mathlib4/actions/workflows/PR_summary.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/PR_summary.yml) | Low | `pull_request_target` | On `pull_request_target`, computes PR summary data (imports/declarations/tech debt), manages related labels, and updates PR comments. |
| [`add_label_from_diff.yaml`](../.github/workflows/add_label_from_diff.yaml) | [![Autolabel PRs](https://github.com/leanprover-community/mathlib4/actions/workflows/add_label_from_diff.yaml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/add_label_from_diff.yaml) | Low | `pull_request_target, push` | Runs `lake exe autolabel` and applies an inferred topic label to newly opened PRs. |
| [`label_new_contributor.yml`](../.github/workflows/label_new_contributor.yml) | [![Label New Contributors](https://github.com/leanprover-community/mathlib4/actions/workflows/label_new_contributor.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/label_new_contributor.yml) | Low | `pull_request_target` | Labels PRs from low-history contributors and records a neutral check-run summary. |
| [`zulip_emoji_closed_pr.yaml`](../.github/workflows/zulip_emoji_closed_pr.yaml) | [![Add "closed-pr" emoji in Zulip](https://github.com/leanprover-community/mathlib4/actions/workflows/zulip_emoji_closed_pr.yaml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/zulip_emoji_closed_pr.yaml) | Low | `pull_request_target` | Updates Zulip emoji reactions for PR close/reopen events. |
| [`zulip_emoji_labelling.yaml`](../.github/workflows/zulip_emoji_labelling.yaml) | [![zulip_emoji_labelling.yaml](https://github.com/leanprover-community/mathlib4/actions/workflows/zulip_emoji_labelling.yaml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/zulip_emoji_labelling.yaml) | Low | `pull_request_target` | Updates Zulip emoji reactions in response to PR label changes. |

## Maintainer commands

Primary trigger for this section: review/comment command events (`issue_comment`, `pull_request_review`, `pull_request_review_comment`).

| File | Name / status  |  Importance | Triggers | Description |
|---|---|---|---|---|
| [`maintainer_bors.yml`](../.github/workflows/maintainer_bors.yml) | [![Add "ready-to-merge" and "delegated" label](https://github.com/leanprover-community/mathlib4/actions/workflows/maintainer_bors.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/maintainer_bors.yml) | High | `issue_comment, pull_request_review, pull_request_review_comment` | Processes maintainer merge/delegate commands, updates labels, and emits artifact/context for follow-up workflows. |
| [`maintainer_merge.yml`](../.github/workflows/maintainer_merge.yml) | [![Maintainer merge](https://github.com/leanprover-community/mathlib4/actions/workflows/maintainer_merge.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/maintainer_merge.yml) | High | `issue_comment, pull_request_review, pull_request_review_comment` | Handles maintainer merge/delegate commands, performs permission checks, and posts Zulip/PR notifications. |
| [`labels_from_comment.yml`](../.github/workflows/labels_from_comment.yml) | [![Label PR based on Comment](https://github.com/leanprover-community/mathlib4/actions/workflows/labels_from_comment.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/labels_from_comment.yml) | Medium | `issue_comment, pull_request_review, pull_request_review_comment` | Adds/removes an allowlisted set of labels based on comment/review text commands. |
| [`bot_fix_style.yaml`](../.github/workflows/bot_fix_style.yaml) | [![bot fix style](https://github.com/leanprover-community/mathlib4/actions/workflows/bot_fix_style.yaml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/bot_fix_style.yaml) | Low | `issue_comment, pull_request_review, pull_request_review_comment` | Responds to review/comment events and runs `lint-style-action` in `fix` mode. |

## Push-triggered workflows

Primary trigger for this section: repository push events (`push`).

| File | Name / status  |  Importance | Triggers | Description |
|---|---|---|---|---|
| [`zulip_emoji_merge_delegate.yaml`](../.github/workflows/zulip_emoji_merge_delegate.yaml) | [![Zulip emoji merge update](https://github.com/leanprover-community/mathlib4/actions/workflows/zulip_emoji_merge_delegate.yaml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/zulip_emoji_merge_delegate.yaml) | Low | `push` | On push, detects merged/delegated PR context and updates Zulip emoji state. |

## Scheduled CI maintenance

Primary trigger for this section: scheduled automation (`schedule`, often with `workflow_dispatch`).

| File | Name / status  |  Importance | Triggers | Description |
|---|---|---|---|---|
| [`daily.yml`](../.github/workflows/daily.yml) | [![Daily CI Workflow](https://github.com/leanprover-community/mathlib4/actions/workflows/daily.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/daily.yml) | High | `schedule (daily at 00:00 UTC), workflow_dispatch` | Runs scheduled expensive checks (master + nightly variants) and posts status updates to Zulip. |
| [`nightly_bump_and_merge.yml`](../.github/workflows/nightly_bump_and_merge.yml) | [![Bump toolchain and merge pr-testing branches](https://github.com/leanprover-community/mathlib4/actions/workflows/nightly_bump_and_merge.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/nightly_bump_and_merge.yml) | High | `schedule (daily at 10:00, 13:00, 16:00, 19:00, 22:00 UTC), workflow_dispatch` | Automates nightly-testing toolchain bump and merges `lean-pr-testing-*` branches with status messaging. |
| [`nightly_merge_master.yml`](../.github/workflows/nightly_merge_master.yml) | [![Merge master to nightly](https://github.com/leanprover-community/mathlib4/actions/workflows/nightly_merge_master.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/nightly_merge_master.yml) | High | `schedule (daily at 00:30 UTC), workflow_dispatch` | Daily automation that merges `mathlib4/master` into `mathlib4-nightly-testing` and pushes updates. |
| [`update_dependencies.yml`](../.github/workflows/update_dependencies.yml) | [![Update Mathlib Dependencies](https://github.com/leanprover-community/mathlib4/actions/workflows/update_dependencies.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/update_dependencies.yml) | High | `schedule (hourly at minute 00 UTC), workflow_dispatch` | Hourly dependency update workflow that runs `lake update`, manages a bot PR, and alerts on failures. |
| [`docker_build.yml`](../.github/workflows/docker_build.yml) | [![docker](https://github.com/leanprover-community/mathlib4/actions/workflows/docker_build.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/docker_build.yml) | Medium | `schedule (daily at 00:00 UTC), workflow_dispatch` | Scheduled build-and-push of Docker images to GHCR with metadata and provenance attestations. |
| [`merge_conflicts.yml`](../.github/workflows/merge_conflicts.yml) | [![Merge conflicts](https://github.com/leanprover-community/mathlib4/actions/workflows/merge_conflicts.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/merge_conflicts.yml) | Medium | `schedule (every 15 minutes), workflow_dispatch` | Periodically detects conflicted PRs and labels/comments on them. |
| [`nightly-docgen.yml`](../.github/workflows/nightly-docgen.yml) | [![Docgen test on nightly-testing](https://github.com/leanprover-community/mathlib4/actions/workflows/nightly-docgen.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/nightly-docgen.yml) | Medium | `schedule (daily at 01:37 UTC), workflow_dispatch` | Runs nightly-testing docgen checks and sends Zulip success/failure messages. |
| [`nightly-regression-report.yml`](../.github/workflows/nightly-regression-report.yml) | [![nightly-testing regression report](https://github.com/leanprover-community/mathlib4/actions/workflows/nightly-regression-report.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/nightly-regression-report.yml) | Medium | `schedule (daily at 04:37 UTC), workflow_dispatch` | Produces nightly-testing regression/lint report output and posts summary to Zulip. |
| [`nolints.yml`](../.github/workflows/nolints.yml) | [![update nolints](https://github.com/leanprover-community/mathlib4/actions/workflows/nolints.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/nolints.yml) | Medium | `schedule (weekly on Sunday at 00:00 UTC), workflow_dispatch` | Regenerates `nolints.json` on a schedule and opens/updates a PR with the result. |
| [`remove_deprecated_decls.yml`](../.github/workflows/remove_deprecated_decls.yml) | [![Remove outdated deprecated declarations](https://github.com/leanprover-community/mathlib4/actions/workflows/remove_deprecated_decls.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/remove_deprecated_decls.yml) | Medium | `schedule (monthly on day 15 at 04:05 UTC), workflow_dispatch` | Monthly/manual cleanup of old deprecations with optional PR creation and Zulip notifications. |
| [`dependent-issues.yml`](../.github/workflows/dependent-issues.yml) | [![Dependent Issues](https://github.com/leanprover-community/mathlib4/actions/workflows/dependent-issues.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/dependent-issues.yml) | Low | `schedule (every 15 minutes), workflow_dispatch` | Periodically updates dependency-tracking labels from issue/PR dependency checkboxes. |
| [`latest_import.yml`](../.github/workflows/latest_import.yml) | [![Late importers report](https://github.com/leanprover-community/mathlib4/actions/workflows/latest_import.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/latest_import.yml) | Low | `schedule (weekly on Monday at 04:00 UTC), workflow_dispatch` | Runs weekly min-imports analysis/build and posts a late-importers report to Zulip. |
| [`long_file_report.yml`](../.github/workflows/long_file_report.yml) | [![Weekly Long File Report](https://github.com/leanprover-community/mathlib4/actions/workflows/long_file_report.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/long_file_report.yml) | Low | `schedule (weekly on Monday at 04:00 UTC), workflow_dispatch` | Runs a weekly long-file report script and posts the result to Zulip. |
| [`technical_debt_metrics.yml`](../.github/workflows/technical_debt_metrics.yml) | [![Weekly Technical Debt Counters](https://github.com/leanprover-community/mathlib4/actions/workflows/technical_debt_metrics.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/technical_debt_metrics.yml) | Low | `schedule (weekly on Monday at 04:00 UTC), workflow_dispatch` | Runs weekly technical-debt counter script and posts results to Zulip. |
| [`weekly-lints.yml`](../.github/workflows/weekly-lints.yml) | [![Weekly linting report](https://github.com/leanprover-community/mathlib4/actions/workflows/weekly-lints.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/weekly-lints.yml) | Low | `schedule (weekly on Monday at 05:00 UTC), workflow_dispatch` | Runs weekly lint-set build/report workflow and posts parsed output to Zulip. |

## Workflow chaining (`workflow_run`)

Primary trigger for this section: completion of other workflows (`workflow_run`).

| File | Name / status  |  Importance | Triggers | Description |
|---|---|---|---|---|
| [`nightly_detect_failure.yml`](../.github/workflows/nightly_detect_failure.yml) | [![Post to zulip if the nightly-testing branch is failing.](https://github.com/leanprover-community/mathlib4/actions/workflows/nightly_detect_failure.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/nightly_detect_failure.yml) | High | `workflow_run` | Reacts to nightly-testing CI outcomes; posts status updates and performs branch/tag maintenance on success. |
| [`update_dependencies_zulip.yml`](../.github/workflows/update_dependencies_zulip.yml) | [![Monitor Dependency Update Failures](https://github.com/leanprover-community/mathlib4/actions/workflows/update_dependencies_zulip.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/update_dependencies_zulip.yml) | High | `workflow_run` | Watches dependency-update CI runs and sends Zulip success/failure messages with PR/label handling. |
| [`maintainer_bors_wf_run.yml`](../.github/workflows/maintainer_bors_wf_run.yml) | [![Add "ready-to-merge" and "delegated" label (workflow_run)](https://github.com/leanprover-community/mathlib4/actions/workflows/maintainer_bors_wf_run.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/maintainer_bors_wf_run.yml) | Medium | `workflow_run` | Consumes artifacts from the maintainer-label workflow and applies/removes labels plus Zulip emoji updates. |
| [`maintainer_merge_wf_run.yml`](../.github/workflows/maintainer_merge_wf_run.yml) | [![Maintainer merge (workflow_run)](https://github.com/leanprover-community/mathlib4/actions/workflows/maintainer_merge_wf_run.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/maintainer_merge_wf_run.yml) | Medium | `workflow_run` | Workflow-run follow-up that reads maintainer-merge artifacts and posts notifications/comments. |
| [`export_telemetry.yaml`](../.github/workflows/export_telemetry.yaml) | [![Export workflow telemetry](https://github.com/leanprover-community/mathlib4/actions/workflows/export_telemetry.yaml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/export_telemetry.yaml) | Low | `workflow_run` | Exports CI run telemetry to OTLP when selected CI workflows complete. |

## Issue/PR lifecycle bookkeeping (1 workflow)

Primary trigger for this section: issue/PR state transitions (`issues`, `pull_request`).

| File | Name / status  |  Importance | Triggers | Description |
|---|---|---|---|---|
| [`sync_closed_tasks.yaml`](../.github/workflows/sync_closed_tasks.yaml) | [![Cross off linked issues](https://github.com/leanprover-community/mathlib4/actions/workflows/sync_closed_tasks.yaml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/sync_closed_tasks.yaml) | Low | `issues, pull_request` | Syncs task-list checkbox references when issues/PRs are closed or reopened. |

## Manual-only workflows (1 workflow)

Primary trigger for this section: explicit manual invocation (`workflow_dispatch`).

| File | Name / status  |  Importance | Triggers | Description |
|---|---|---|---|---|
| [`stale.yml`](../.github/workflows/stale.yml) | [![Close stale issues and PRs](https://github.com/leanprover-community/mathlib4/actions/workflows/stale.yml/badge.svg)](https://github.com/leanprover-community/mathlib4/actions/workflows/stale.yml) | Low | `workflow_dispatch` | Manual stale-bot workflow for inactive PRs/issues (currently configured in debug-only mode). |
