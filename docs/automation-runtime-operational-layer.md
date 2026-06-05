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
- `atlas-agent-issue-decompose`: mark one-point issues, emit review-only one-point child drafts, or create one-point child issues from oversized parents while preserving parent plan metadata.
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

The established issue-to-PR lane uses GitHub as the canonical execution state:

- Issues are executable work items, plan projection targets, dependency references, and closure records.
- Labels express type, status, risk, queue, policy, validation, and review state.
- PRs contain implementation evidence, CI state, review discussion, repair context, and finalization units.
- Projects show portfolio state and runtime lifecycle state; they do not replace issue bodies or PR evidence.

The runtime owns only ephemeral execution state for that lane: logs, job directories, lockfiles, local checkouts, Codex auth, and validation artifacts.

The Atlas-owned bootstrap lane can now run from a local JSON work-item store instead of GitHub issues. In that mode,
`atlas-agent-orchestrator --atlas-work-items path/to/work-items.json` loads ready work items through
`AtlasWorkItemOperationProvider`, projects them into operation states, orders ready work by priority (`p0` before `p1`
before `p2` before `p3`) and then lower `critical_path_rank`, lets `run_worker_daemon_once` claim one or more items, and
appends claim/result evidence back onto the same work-item record. This path is local-only: it does not query GitHub
issues, mutate labels, publish PRs, or update Projects. With `--dry-run`, it only previews ready operations and does not
claim items, create worker jobs, or mutate the JSON store. Use `atlas-agent-work-item-inspect` to see the full
scheduler projection, including ready, blocked, active, and terminal work items with blocker reasons. Its JSON output also
includes compact lifecycle summaries for claims, results, latest workflow runs, selected templates, missing outputs,
completed roles, continuation markers, and resume markers. Use
`atlas-agent-work-item-requeue-stale` to preview or apply recovery for stale `running` claims; the apply form moves stale
items back to `ready`, preserves previous claim data, and appends `requeue` evidence. Ready items are blocked while an
active item has an overlapping execution repo, base branch, and write scope; missing scope metadata is treated as
overlapping. Use `atlas-agent-work-item-add` to append a new local `ready` work item with scheduler/workflow metadata and
`create` evidence; it fails on duplicate ids and remains local-only. The add command can also validate against the local
template catalog with `--team-templates`, stamp a selected template with `--select-team-template`, or fail early with
`--require-template-match` when no template covers the requested outputs. Operators can pass
`--atlas-work-item-command "..."` to
run a local command after claim; the command receives `ATLAS_WORK_ITEM_ID`, `ATLAS_OPERATION_FILE`, `ATLAS_JOB_DIR`, and
`ATLAS_WORK_ITEM_STORE`. When an item requests a workflow template through `workflow_kind` or `team_template`, the local
worker writes a `team-run.json` and `team-rollup.md` skeleton into the job directory and links those artifacts from the
result evidence alongside selected template id, workflow kind, role ids, missing outputs, and the compact template
selection decision for whether Atlas used an existing template or identified a template gap. Use
`--team-templates path/to/templates` to override the default `team-templates/` directory. Use
`atlas-agent-workflow-template-add` to write a validated local template when selection identifies a new task-specific
workflow gap. Workflow-aware local commands
receive `ATLAS_TEAM_RUN_FILE`, `ATLAS_TEAM_ROLLUP_FILE`, `ATLAS_TEAM_ROLE_RESULTS_FILE`, and `ATLAS_TEAM_TEMPLATE`. If
the command writes role results to `ATLAS_TEAM_ROLE_RESULTS_FILE`, the worker refreshes the run JSON, markdown rollup,
missing-output map, completed-role list, and lifecycle result evidence before marking the item done or failed.
The worker also writes `team-role-tasks.json` and exposes it as `ATLAS_TEAM_ROLE_TASKS_FILE`; each packet names the role,
selected agent reference, skills, dependencies, required outputs, current missing outputs, acceptance criteria, and
derived dependency phase, plus completed dependency outputs under `consumed_role_results`. Packets also include contract
issues and dependency blockers so role executors and inspectors can explain why a role is incomplete or waiting without
recomputing the template graph. When `--agent-registry` and/or `--agent-root` are provided, packets also include resolved
`agent_definition` metadata so later role executors can see the agent id, description, skills, and local source path used
for scheduling.
Result evidence also embeds a compact `team_run` summary so the work-item store itself records the selected template,
workflow kind, run status, role phases, role status, completed outputs, and missing outputs even without dereferencing job
artifacts. It also records compact workflow-selection evidence with the request, selected template, candidate role phases,
covered required outputs, and missing required outputs. The compact run summary and markdown rollup include contract
issues and dependency blockers for incomplete role evidence.
`atlas-agent-role-runner` is the local bridge from those packets to executable role work. It reads a JSON command map,
selects runnable roles whose `consumes` dependencies are complete, resolves commands by role id, resolved agent id,
`agent_ref`, execution profile, skill, then `default`, hydrates consumed dependency outputs into downstream task packets,
and appends role results for the worker to ingest. Role commands receive `ATLAS_AGENT_ID`, `ATLAS_AGENT_SOURCE`, and
`ATLAS_AGENT_EXECUTION_PROFILE` alongside the role task/result file paths. The runner advances dependency-ready roles in
sequence until `--max-roles` is reached or no runnable role remains, and exits non-zero if required outputs remain
incomplete.
`atlas-agent-orchestrator` can use this runner directly with
`--atlas-role-command-config path/to/role-commands.json --atlas-role-max N`.
When the runner records at least one completed role but required workflow outputs remain, the work-item worker records
the partial result, clears the active claim into `previous_claims`, and moves the item back to `ready` for a later local
claim. The next claim resumes the same `TeamRun` from the previous run artifact, so bounded role execution can advance
large workflows without rerunning completed roles or treating incomplete evidence as final success. A runner failure that
does not complete any required role still marks the work item `failed`. Role result ingestion normalizes contract
violations: `complete` results missing required outputs become `incomplete`, unexpected output names are recorded as
contract issues, downstream roles cannot complete before their `consumes` dependencies have completed required outputs,
transitive dependency failures propagate through downstream roles, stale generated dependency issues clear after upstream
roles complete, and a zero process exit code cannot mark a workflow work item `done` while template outputs remain
missing.
Use `atlas-agent-workflow-select --work-item path/to/work-items.json --json` before a run to inspect which template the
work item will select, which candidates cover the required outputs, and which outputs would require editing or creating a
template.
The template includes `config/role-commands.example.json` as a safe failing stub so operators can see the schema without
accidentally creating trusted evidence. Replace it with project-specific local agent or Codex commands before using role
outputs as lifecycle evidence. When workflow evidence exists, `record_result` also appends a durable `workflow_runs`
entry to the work item, including artifact paths, compact `team_run` summary, and a rollup markdown snapshot.
`config/role-commands.codex.example.json` maps the default workflow templates to `atlas-agent-role-codex`, a safe wrapper
that prepares a role-specific prompt and result-file contract. The wrapper fails closed unless the operator explicitly
adds `--execute` and a second execution gate: `--allow-execute` or `ATLAS_ROLE_CODEX_ALLOW_EXECUTE=true`. Executed role
commands use `AGENT_CODEX_WORKFLOW_ROLE_PROFILE`, `AGENT_CODEX_WORKFLOW_ROLE_MODEL`,
`AGENT_CODEX_WORKFLOW_ROLE_EXTRA_ARGS`, and `AGENT_CODEX_WORKFLOW_ROLE_TIMEOUT_SECONDS`, falling back to
`AGENT_CODEX_TIMEOUT_SECONDS` when the role timeout is unset. The wrapper invokes `codex exec` and requires Codex to
write the role result JSON.
Use `examples/atlas-work-items.sample.json` with the Codex example command map for a fully local prepare-only smoke run:
it creates workflow artifacts and prompt evidence under `jobs/` without touching GitHub or executing Codex.
Use `config/role-commands.fake-execute.example.json` only for a deterministic completion smoke. It runs the same wrapper
against `atlas-agent-role-fake-codex`, proving lifecycle wiring and rollup completion without producing trusted review or
implementation evidence.

Minimal local store shape:

```json
{
  "version": 1,
  "work_items": [
    {
      "id": "WI-1",
      "status": "ready",
      "title": "Bootstrap local lifecycle loop",
      "scheduler": {
        "depends_on": [],
        "execution_repo": "local/atlas",
        "write_scope": ["templates/local-automation-runtime"],
        "parallel_group": "bootstrap"
      },
      "evidence": []
    }
  ]
}
```

After a local run, the item status moves through `running` to `done` or `failed`, with `claim` and `result` evidence
entries preserved in the item lifecycle.

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

The scheduler contract is metadata-first. Decomposition should emit explicit leaf metadata for dependency graph and batching decisions: `Depends on`, `Blocks`, `Parallel group`, `Critical path rank`, `Merge group`, `Combine policy`, `Conflict class`, `Write Scope`, and `Validation tier`. The runtime may still infer conservative locks from issue bodies, but missing metadata should reduce parallelism instead of widening it.

Recommended dispatch policy:

- Start with `parallel-bounded`, not unbounded fanout.
- Dispatch independent leaves in the same `Parallel group` only when dependencies are closed and write scopes are disjoint.
- Treat `Conflict class: schema`, `migration`, `repo-wide`, or unknown scope as exclusive for the repo/base branch.
- Use `Critical path rank` to run long dependency chains first.
- Keep implementation PRs separate by default; use an explicit integration leaf or `Merge group` for rollup work.
- Set `Combine policy: never` for most one-point implementation leaves, `rollup-after-green` for generated/docs/test-only batches, and `integration-pr` only when a final combining PR is intentionally planned.

## Pre-PR Validation Evidence

Workers must produce validation evidence before publishing a draft PR. The worker prompt asks for a `Tests` or `Verification` section with exact commands and results, but prompt compliance is not enough; publication should fail closed when that section is missing or only says tests were skipped.

Expected policy:

- Code changes require an explicit `Tests` or `Verification` section.
- Existing targeted tests should run whenever the repo exposes a relevant command.
- New tests are expected for changed behavior, shared runtime logic, dependency resolution, review/finalize gates, and repair routing.
- Docs/config/generated-only changes may use an explicit validation waiver when the issue body contains `Validation waiver:` / `ValidationWaiver:` with a non-empty reason, or the issue has a controlled waiver label.
- A waiver is evidence, not approval. Review and finalization still require current-head checks, local validation, deployed/manual validation, or semantic review when those gates apply.
- `pre-commit` should be configured as a local validation command when a target repo depends on it; do not rely on repository hooks firing inside worker worktrees.

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

Project fields are not planning truth. Before dispatch, reconcile must make issue body markers,
labels, and Project fields agree; Project-only rows or Project-only runtime markers are not safe queue
items.

After plan-to-issues sync or Project reconciliation, audit affected rows as hard failures for missing
`Priority`, duplicate `SourceId`, ready/agent-ready state on issues larger than one point, Project-only
rows, and `Size` mismatches against issue body `Points` or `points:*` labels.

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

## Workstream Completion Bundle

A workstream is not complete when its last implementation PR merges. Completion requires an operator review bundle:

- semantic review outcome for the workstream, including any remaining product, data, runtime, or docs risk
- garbage collection pass for stale followups, obsolete config, generated junk, duplicate source-of-truth, and abandoned automation artifacts or branches when they are safe to remove
- documentation update, or an explicit `docs-not-needed` rationale in the closure record
- validation evidence with current-head commands, checks, artifacts, or manual/deployed evidence
- downstream readiness statement covering dependent issues, Projects, runtime lanes, release/deploy expectations, and followup ownership

Documentation updates are not optional. Every workstream either changes the relevant docs as part of the bundle or records why no doc surface is affected.

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
