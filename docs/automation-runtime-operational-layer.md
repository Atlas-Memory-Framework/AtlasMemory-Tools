# Automation Runtime Operational Layer

This document describes the current local issue-to-PR automation runtime. `AtlasMemory-Tools` remains the canonical source for skills, agents, scripts, Project helpers, and runtime templates. Installed runtime directories are local operational hosts and must preserve their config, auth, logs, jobs, and checkouts.

## Current Model

- Canonical template: `templates/local-automation-runtime/`
- Installed runtime host: any copied runtime directory with local `config.env`, `repos.txt`, `projects.txt`, `jobs/`, `logs/`, `repos/`, and `codex-home/`
- Runtime-managed repo checkouts: `AGENT_REPOS`, default `./repos`
- Disposable job checkouts: `AGENT_JOBS/checkouts`
- GitHub issues and PRs: execution truth
- GitHub Projects v2: portfolio and automation signal layer

One runtime can operate multiple target repositories. Add target repos to `repos.txt`; create another runtime only for separate secrets/auth, host isolation, or intentionally independent lanes.

## Runtime Inventory

The template includes these operational scripts:

- `atlas-agent-plan-queue`: project an approved plan into GitHub issues, queue eligible work, and optionally run a chain.
- `atlas-agent-unattended`: run bounded cycles across reconcile, project reconcile, decomposition, workstream review, dependency promotion, dispatch, review, semantic review, validation, repair, finalize, and summary.
- `atlas-agent-admin`: inspect and manage runtime state.
- `atlas-agent-cycle-summary`: produce end-of-cycle summaries.
- `atlas-agent-deploy`: run deployment-oriented helper flows.
- `atlas-agent-notify`: send configured operator notifications.
- `atlas-agent-orchestrator`: promote queue candidates, dispatch workers, apply direct Project state updates, triage blocked work, and enforce write-scope locks.
- `atlas-agent-reconcile`: reconcile issue and PR lifecycle labels.
- `atlas-agent-triage`: classify queue and PR state for operators.
- `atlas-agent-worker`: run Codex in an isolated per-job worktree, enforce file/diff/policy limits, commit, push, open draft PRs, and update Project lifecycle fields.
- `atlas-agent-issue-decompose`: mark one-point issues or create one-point child issues from oversized parents while preserving parent plan metadata.
- `atlas-agent-workstream-review`: review workstream-level issue readiness before dispatch.
- `atlas-agent-dependency-promote`: promote dependency-gated issues once upstream issues/PRs and manual gates are complete.
- `atlas-agent-project-reconcile`: hydrate Project fields, reconcile lifecycle state, backfill metadata, and keep child/parent status aligned.
- `atlas-agent-review`: classify PRs into approved, repair, validation, semantic review, overlap, or human action routes.
- `atlas-agent-local-validate`: run configured local validation commands for no-check PRs and record current-head evidence.
- `atlas-agent-deployed-validate`: run configured deployed/manual validation commands and collect workflow artifact evidence.
- `atlas-agent-semantic-review`: run semantic review and label current-head semantic review state.
- `atlas-agent-pr-repair`: repair PR branches using failed checks, logs, review comments, and semantic review evidence.
- `atlas-agent-finalize`: leave draft, merge, and close linked issues only after configured gates pass.
- `atlas-agent-workflow`: dispatch, watch, inspect, rerun, and download GitHub Actions runs and artifacts.

## Execution State

GitHub is the canonical execution state:

- Issues are executable work items, plan projection targets, dependency references, and closure records.
- Labels express type, status, risk, queue, policy, validation, and review state.
- PRs contain implementation evidence, CI state, review discussion, repair context, and finalization units.
- Projects show portfolio state and runtime lifecycle state; they do not replace issue bodies or PR evidence.

The runtime owns only ephemeral execution state: logs, job directories, lockfiles, local checkouts, Codex auth, and validation artifacts.

## Issue And Project Lifecycle

Recommended label families:

- Type: `type:epic`, `type:story`, `type:spike`, `type:tracker`
- Status: `status:draft`, `status:planned`, `status:ready`, `status:blocked`, `status:done`
- Priority: `priority:p0`, `priority:p1`, `priority:p2`, `priority:p3`
- Workstream and scope: `workstream:*`, `area:*`, `repo:*`, `tier:*`, `points:*`
- Agent queue: `agent:ready`, `agent:running`, `agent:pr-open`, `agent:failed`, `agent:done`, `agent:one-point`, `agent:decomposition-required`, `agent:decomposed`, `agent:checks-pending`, `agent:no-checks-expected`
- Agent policy: `agent:approved-dispatch`, `agent:allow-workflows`, `agent:allow-infra`, `agent:allow-large`
- Review and repair: `agent:review-approved`, `agent:needs-repair`, `agent:superseded`, `agent:overlap-queued`, `agent:human-action-required`
- Workstream review: `agent:workstream-review-required`, `agent:workstream-review-passed`, `agent:workstream-review-failed`, `agent:workstream-needs-human`, `agent:workstream-followup`
- Validation: `agent:local-validation-required`, `agent:local-validation-passed`, `agent:local-validation-failed`, `agent:manual-validation-required`, `agent:manual-validation-approved`, `agent:deployed-validation-passed`, `agent:deployed-validation-failed`, `agent:semantic-review-required`, `agent:semantic-review-passed`, `agent:semantic-review-failed`

Project `AutomationState` mirrors runtime lifecycle:

```text
Manual -> Draft -> Planned -> Ready -> Queued -> Running -> PR Open ->
Review -> Semantic Review -> Local Validation / Deployed Validation ->
Repair -> Waiting / Human Action / Blocked -> Done / Failed / Superseded
```

Queue and worker paths now update Project state directly for `Queued`, `Running`, `PR Open`, `Failed`, and `Done`. `atlas-agent-project-reconcile` remains the backstop for stale or missing state.

## Default Unattended Loop

The default unattended stage order is:

```text
reconcile -> decompose -> workstream-review -> dependency-promote -> dispatch -> review ->
semantic-review -> review -> local-validate -> review -> semantic-review ->
review -> deployed-validate -> review -> semantic-review -> review ->
repair -> review -> semantic-review -> review -> finalize -> summary
```

The loop is intentionally redundant around review and semantic-review gates so state changes from one stage are classified before later stages act.
GitHub Project reconciliation is intentionally omitted from the hot path. Use `--project-reconcile-every N` for
end-of-cycle checkpoint syncs, or add `project-reconcile` to `--stages` for a supervised inline sync when Project
fields must be repaired immediately.

## Parallelism And Locks

Use explicit per-stage limits:

- `--dispatch-max-per-repo`
- `--semantic-review-concurrency`
- `--local-validate-concurrency`
- `--repair-concurrency`
- `--deployed-validate-concurrency`

Dispatch uses repo/base/write-scope locks by default. Disjoint `## Write Scope` paths can run concurrently; overlapping paths, schema/migration siblings, unknown scope, and repo-wide scope wait for another cycle. Use `--no-write-scope-locks` only for manually supervised runs.

## GitHub API Throttle

All runtime processes coordinate GitHub CLI pacing through `jobs/github-api-throttle/state.json`.

Keep these defaults enabled for parallel lanes:

- `AGENT_GITHUB_THROTTLE=true`
- `AGENT_GITHUB_MIN_INTERVAL_SECONDS=0.75`
- `AGENT_GITHUB_GRAPHQL_INTERVAL_SECONDS=2.0`
- `AGENT_GITHUB_PROJECT_INTERVAL_SECONDS=5.0`
- `AGENT_GITHUB_MUTATION_INTERVAL_SECONDS=2.0`
- `AGENT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS=900`

When GitHub returns a rate-limit response, later runtime calls pause instead of hammering the token.
Use `atlas-agent-throttle-status` to inspect the local throttle state and stale lock age without making a GitHub request.

## Project Sync Queue

The hot path keeps GitHub Project writes disabled by default with `AGENT_PROJECT_STATE_UPDATES=false`.
For supervised direct updates, set `AGENT_PROJECT_STATE_UPDATES=true`. For eventual sync, set
`AGENT_PROJECT_STATE_UPDATE_MODE=queue`; runtime stages append desired Project field updates under
`jobs/project-sync/*.jsonl` instead of calling `gh project`. Use `atlas-agent-project-sync status` offline
and `atlas-agent-project-sync flush` when the lane is idle or the GitHub token has recovered.

## Project Metadata Hydration

`atlas-agent-project-reconcile` hydrates issue rows from issue bodies, labels, parent Project rows, and safe defaults:

- Plan and hierarchy: `PlanKey`, `SourceId`, `ParentEpic`, `Workstream`
- Dispatch: `DispatchMode`, `DispatchRecommendation`, `IssueReady`, `AutomationState`
- Scope: `TargetRepo`, `ExecutionRepo`, `BaseBranch`, `WriteScope`, `Validation`
- Risk and gates: `ReviewGates`, `GateTier`, `Risk`, `RiskTags`, `ValidationScope`
- Sizing and priority: `Size`, `OnePRContract`, `Priority`
- PR state: `ActivePR`, `ReviewVerdict`, `Status`

Project scans read up to `AGENT_PROJECT_ITEM_LIMIT`, default `500`. Raise it if a Project has more active cards or logs report that the scanned item limit was reached.

Priority rules are conservative: explicit `priority:*` labels or body fields win; unambiguous same-workstream priority can be inherited; otherwise `GateTier` maps to priority (`T0/T1 -> P1`, `T2/T3 -> P2`, `T4+ -> P3`). `P0` remains explicit-only.

## Secrets And Config

Local `config.env` should contain only local runtime settings:

- agent labels and policy labels
- runtime paths
- Codex image, Codex home, timeout, and Podman command
- trusted GitHub authors and local commit identity
- local notification webhook URLs when used

GitHub Actions secrets and vars remain in GitHub. The runtime should not copy CI/deploy/cloud secrets locally.

## Review And Finalization Gates

Finalization requires:

- configured required checks pass
- local/deployed/manual validation evidence exists when labels require it
- semantic review passes when requested
- no unresolved requested changes
- no duplicate active PR for the same issue
- no overlapping approved PRs
- human approval for high-risk workflow, infra, auth/secrets, migration, large diff, or ambiguous product changes

Repair loops are bounded with `--repair-max` and `--repair-cooldown-hours`. Escalate to human action for secrets/config failures, non-reproducible environment failures, missing permissions, unsafe scope expansion, or repeated repair failure.

## Operational Runbook

Start with dry runs. Then use a bounded lane:

```bash
./atlas-agent-unattended \
  --publish --review-apply --apply \
  --cycles 1 \
  --dispatch-max-per-repo 1 \
  --post-cycle-summary
```

Increase concurrency only after locks, stale cleanup, repair limits, and queue fairness are stable.

Before upgrading an installed runtime, preserve `config.env`, `repos.txt`, `projects.txt`,
`required-checks.json`, `local-validation.json`, `deployed-validation.json`, `repo-env/`, `jobs/`,
`logs/`, `repos/`, `state/`, and `codex-home/`. Use `skills/local-automation-runtime-upgrade/SKILL.md`
and `scripts/sync_runtime_template.py`.
