# Local Automation Runtime Template

This template is the host-side local Codex automation lane for GitHub issue-to-PR automation.

It provides:

- issue queueing from `status:ready` to `agent:ready`
- local Codex worker execution in isolated per-job worktrees
- draft PR publishing
- unattended reconcile, dependency promotion, dispatch, review, local/deployed validation, repair, finalize, and merge supervision
- local Atlas work-item dispatch from a JSON store without GitHub issue or PR mutation
- workflow-template models and default planning template under `team-templates/`
- bounded shift supervision with a wall-clock budget, one supervisor lock, heartbeat/status files, and handoff notes
- finalizer gates for required checks, duplicate PRs, mergeability, and issue dependencies
- one-command plan projection and queueing via `atlas-agent-plan-queue`
- one end-of-cycle summary from `run_e2e_chain.sh`

## Quick Start

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m playwright install chromium
cp config.env.example config.env
cp repos.example.txt repos.txt
cp config/required-checks.example.json required-checks.json
cp config/local-validation.example.json local-validation.json
cp projects.example.txt projects.txt
./check_runtime.sh
./build_codex_image.sh
python3 -m unittest tests.test_local_agent_autonomy
```

Edit `repos.txt` with one `OWNER/REPO` target per line. The runtime clones or fetches those repos under
`AGENT_REPOS`, defaulting to `./repos`.
Set `ATLAS_TOOLS_ROOT` in `config.env` when using `atlas-agent-plan-queue`; it must point at the
AtlasMemory-Tools checkout that contains `skills/plan-to-issues/scripts/plan_to_issues.py`.

Add another target repo to `repos.txt`; create another runtime only when you need separate secrets/auth, host
isolation, or intentional concurrent lanes.

Project an approved plan into one-point manifest leaf issues and preview queue eligibility:

```bash
./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --strategy leaf-issues --dry-run
```

Apply issues and queue eligible work:

```bash
./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --strategy leaf-issues --apply --queue --publish
```

Run the bounded local lane:

```bash
./run_e2e_chain.sh --apply --review --review-apply --require-review-approval --merge --close-issues --cycles 3
```

Without the review flags, the bounded script is useful for supervised local progression but does not enforce
the same review-approval gate as the unattended finalizer path.

Run the full unattended loop:

```bash
./atlas-agent-unattended --publish --apply --merge --close-issues --review-apply --cycles 3 --dispatch-max-per-repo 2 --post-cycle-summary
```

The unattended loop first reconciles stale lifecycle labels and Project epic status, promotes dependency-gated one-point stories whose upstream issues/PRs and manual gates are complete, then dispatches issue workers, reviews local-agent PRs, runs local/deployed validation where configured, repairs PRs labeled `agent:needs-repair`, and finalizes only PRs with `agent:review-approved`.

Run the Atlas-owned local work-item bootstrap lane without touching GitHub:

```bash
./atlas-agent-orchestrator --once --atlas-work-items ./work-items.json
```

The local work-item path reads ready items from `work-items.json`, projects each item to an operation state, claims work
through `run_worker_daemon_once`, and records claim/result evidence back onto the same item. Add
`--atlas-work-item-command "your-local-command"` to execute a local worker command after claim; the command receives
`ATLAS_WORK_ITEM_ID`, `ATLAS_OPERATION_FILE`, `ATLAS_JOB_DIR`, and `ATLAS_WORK_ITEM_STORE`. This mode intentionally does
not query GitHub issues, edit labels, publish PRs, or update Projects. If the work item requests `workflow_kind` or
`team_template`, the worker also writes `team-run.json` and `team-rollup.md` artifacts into the job directory using
templates from `team-templates/` or `--team-templates`. Result evidence records the selected template id, workflow kind,
role ids, missing outputs, and artifact paths, so operators can see exactly which structured workflow still has incomplete
role outputs. A local worker command can complete role outputs by writing JSON to `ATLAS_TEAM_ROLE_RESULTS_FILE`; after
the command exits, the runtime refreshes `team-run.json`, `team-rollup.md`, `missing_outputs`, `completed_roles`, and
result evidence. During command execution, workflow-aware commands receive `ATLAS_TEAM_RUN_FILE`,
`ATLAS_TEAM_ROLLUP_FILE`, `ATLAS_TEAM_ROLE_TASKS_FILE`, `ATLAS_TEAM_ROLE_RESULTS_FILE`, and `ATLAS_TEAM_TEMPLATE`.
`team-role-tasks.json` contains one task packet per role with the selected `agent_ref`, skills, dependencies, required
outputs, missing outputs, phase index, acceptance criteria, and any completed `consumed_role_results` for roles listed in
`consumes`. Phase indexes come from the template dependency graph: roles in the same phase are dependency-independent,
and later phases wait for earlier consumed outputs.
`config/agent-registry.example.json` seeds the registry-style references used by the checked-in workflow templates. It is
not an executor by itself; it lets operators validate that template roles point at named specialist agent profiles before
they bind those roles to concrete local commands or Codex profiles.
Pass `--agent-registry ./config/agent-registry.example.json --agent-root ../..` to enrich role task packets with resolved
`agent_definition` metadata from the registry and local markdown agents.
The default registry entries include `source` paths to canonical `agents/*.md` persona/rubric files; lint validates those
source paths when `--agent-root` is provided.

Validate the checked-in templates and local agent references with:

```bash
./atlas-agent-workflow-lint \
  --agent-registry ./config/agent-registry.example.json \
  --agent-root ../..
```

The lint output prints derived role phases so operators can see the intended specialist fan-out and rollup order before a
workflow runs. Templates with `rollup.missing_outputs_block_completion` or `rollup.require_coverage` must have a
final-phase role that consumes every prior role; lint prints that derived rollup role.

To execute one or more runnable role packets with a local command map, pass `--atlas-role-command-config` instead of a
raw work-item command:

```bash
cp config/role-commands.example.json role-commands.json
./atlas-agent-orchestrator \
  --once \
  --atlas-work-items ./work-items.json \
  --atlas-role-command-config ./role-commands.json \
  --agent-registry ./config/agent-registry.example.json \
  --agent-root ../.. \
  --atlas-role-max 1
```

Add `--dry-run` to preview ready local Atlas work items without claiming them, creating job directories, or mutating the
JSON store.
Ready local work items are claimed in scheduler order: priority first (`p0`, `p1`, `p2`, `p3`, including
`priority:p*` labels), then lower `critical_path_rank`, then work-item id for a stable tie-breaker.
Ready items are also blocked while another local item is active on an overlapping execution repo, base branch, and
`write_scope`. Missing scope metadata is treated conservatively as overlapping.

Add a ready local work item without GitHub dispatch with:

```bash
./atlas-agent-work-item-add ./work-items.json \
  --id LOCAL-WI-002 \
  --title "Review local evidence" \
  --workflow-kind review \
  --required-output review_decision \
  --write-scope templates/local-automation-runtime
```

The add command fails on duplicate ids, writes `ready` lifecycle state, and appends `create` evidence to the same JSON
store that the local scheduler consumes. Add `--team-templates ./team-templates --select-team-template` to stamp the
selected template id onto the work item when the catalog has a match, or `--require-template-match` to fail before
enqueueing a work item whose required outputs are not covered by the local template catalog.

Inspect workflow template selection before a run with:

```bash
./atlas-agent-workflow-select --work-item ./work-items.json --json
./atlas-agent-workflow-select --workflow-kind review --required-output review_decision
```

The selector reports the selected template, all candidate templates, role phases, covered outputs, and missing required
outputs so operators or agents can decide whether to use, edit, or create a template before executing role work. Its JSON
also includes `selection.status`, `selection.suggested_action`, the closest matching template when no template covers the
request, and uncovered required outputs. When multiple templates cover the requested outputs, selection prefers the one
with the fewest extra outputs, then fewer roles, then template id as a stable tie-breaker; an explicit `team_template`
still wins when it satisfies the request.

Create a new local workflow template from explicit role contracts with:

```bash
./atlas-agent-workflow-template-add ./team-templates \
  --id migration-plan \
  --workflow-kind migration \
  --role-json '{"id":"analysis","agent_ref":"agent-registry://architecture","must_produce":["migration_risks"]}' \
  --role-json '{"id":"rollup","agent_ref":"agent-registry://rollup-editor","must_produce":["migration_plan"],"consumes":["analysis"]}'
```

The add command validates the template before writing it and, by default, requires a final rollup role that consumes all
prior roles. It fails rather than overwriting an existing template unless `--force` is provided.

Inspect the full local scheduler projection, including blocked, active, and terminal items, with:

```bash
./atlas-agent-work-item-inspect ./work-items.json
./atlas-agent-work-item-inspect ./work-items.json --json
```

The JSON form includes claim/result summaries and the latest workflow run state, including selected template, missing
outputs, completed roles, continuation markers, resume markers, and artifact paths.

Preview and recover stale local `running` claims with:

```bash
./atlas-agent-work-item-requeue-stale ./work-items.json --stale-seconds 21600
./atlas-agent-work-item-requeue-stale ./work-items.json --stale-seconds 21600 --apply
```

The apply form moves stale active items back to `ready`, preserves the previous claim under `previous_claims`, and appends
`requeue` evidence to the work-item lifecycle.

The role command config can map commands by role id, resolved agent id, `agent_ref`, execution profile, skill, or
`default`. `atlas-agent-role-runner` advances roles whose `consumes` dependencies are already complete, runs the mapped
command with `ATLAS_ROLE_TASK_FILE`, `ATLAS_ROLE_RESULT_FILE`, `ATLAS_AGENT_ID`, `ATLAS_AGENT_SOURCE`, and
`ATLAS_AGENT_EXECUTION_PROFILE`, hydrates consumed dependency outputs into downstream task packets, then repeats until
`--atlas-role-max` is reached or no dependency-ready role remains. It exits
non-zero when required outputs remain incomplete, so unmapped or partial role work fails closed instead of marking a
workflow complete. It also writes `role-runner-summary.json` with attempted role phases, contract issues, dependency
blockers, and incomplete-role blockers. A role command that writes `contract_issues` is treated as incomplete immediately,
even if it marks the role `complete`. The
worker appends role results for the work-item worker to ingest. When at least one role completed but required outputs
remain missing, the item returns to `ready` and the next claim resumes the same `TeamRun` instead of rerunning completed
roles. Role result ingestion treats `must_produce` as the contract: a `complete` role missing required outputs is recorded
as `incomplete`, unexpected output names are kept as contract issues, downstream roles cannot complete before their
`consumes` dependencies have completed required outputs, transitive dependency failures propagate through downstream
roles, stale generated dependency issues clear when upstream roles complete, and a zero process exit code does not close a
workflow work item while required outputs remain missing. Result evidence embeds a compact
`team_run` summary so the work-item JSON records workflow status and missing outputs even when operators do not open the
job artifact files. The summary and markdown rollup include contract issues and dependency blockers for incomplete role
evidence. It also embeds compact workflow-selection evidence with candidate template coverage and missing required
outputs. The checked-in example config is a safe failing stub; replace it with project-specific Codex or local
agent commands before treating role output as evidence. Completed workflow runs are also copied into the work item under
`workflow_runs`, including a compact run summary and rollup markdown snapshot.

For a Codex-backed starting point, copy `config/role-commands.codex.example.json` instead. That map routes default
template roles to `./atlas-agent-role-codex`, which prepares a role-specific prompt and result-file contract but fails
closed unless the command is changed to include `--execute`. This makes the Codex invocation boundary explicit before
role output becomes lifecycle evidence. Actual execution also requires `--allow-execute` on the wrapper command or
`ATLAS_ROLE_CODEX_ALLOW_EXECUTE=true`, and uses `AGENT_CODEX_WORKFLOW_ROLE_*` profile/model/extra-args/timeout settings.

Try the local bootstrap path without GitHub or Codex execution:

```bash
cp examples/atlas-work-items.sample.json work-items.json
./atlas-agent-orchestrator \
  --once \
  --atlas-work-items ./work-items.json \
  --atlas-role-command-config ./config/role-commands.codex.example.json
```

This uses the review workflow template, writes role prompts and workflow artifacts under `jobs/`, and fails closed because
`atlas-agent-role-codex` is in prepare-only mode. Add `--execute` to the mapped Codex command only after choosing the
runtime Codex profile and sandbox policy, and add `--allow-execute` or set `ATLAS_ROLE_CODEX_ALLOW_EXECUTE=true` only for
the supervised execution window.

For a deterministic local completion smoke that still avoids real Codex execution, use
`config/role-commands.fake-execute.example.json`. It runs the same Codex wrapper with a checked-in fake command that writes
non-empty outputs for every required role output. Treat that as lifecycle wiring verification only, not as review or
implementation evidence.

Run a longer but still bounded shift by wrapping one-cycle unattended runs:

```bash
./atlas-agent-shift --cycles 12 --max-minutes 480 --sleep-seconds 300 --publish --apply --review-apply --post-cycle-summary
```

`atlas-agent-shift` holds one runtime-wide supervisor lock, runs `atlas-agent-unattended --cycles 1` repeatedly, updates `jobs/atlas-agent-shift-heartbeat.json`, writes a per-shift status JSON under `jobs/`, and writes a markdown handoff under `jobs/` on exit. Use it when the lane is already stable and the operator needs durable resume state across a long window. The unattended cycle performs GitHub issue reconciliation every cycle and keeps GitHub Project reconciliation out of the default hot path; use `--project-reconcile-every N` for checkpoint Project syncs. On `atlas-agent-shift`, that interval is counted across shift cycles. The shift wrapper adds wall-clock limits and restartable evidence, not broader mutation authority.

`agent:done` is reserved for resolved/closed work. A published draft PR leaves the linked issue marked `agent:pr-open` until the finalizer merges and closes it.

The default stage order is `reconcile -> decompose -> workstream-review -> dependency-promote -> dispatch -> review -> semantic-review -> review -> local-validate -> review -> semantic-review -> review -> deployed-validate -> review -> semantic-review -> review -> repair -> review -> semantic-review -> review -> finalize -> summary`. The default is local-first: GitHub Project sync is advisory and runs only when `project-reconcile` is explicitly included in `--stages` or `--project-reconcile-every N` is set. The decompose stage marks one-point issues with `agent:one-point` and prevents larger point estimates from reaching dispatch until they are split. The dependency promotion stage is dry-run by default and applies body, label, and Project field updates when `--apply`, `--review-apply`, or `--dependency-promote-apply` is used. Use `atlas-agent-issue-decompose --child-drafts-file /tmp/children.json --dry-run --issue OWNER/REPO#N` to emit reviewable one-point child issue drafts without creating GitHub issues. Use `--decompose-create-subissues` when you want the planning Codex profile to create one-point child issues for oversized parents.

Parallelism is stage-specific. `--dispatch-max-per-repo` replaces the older broad `--max-per-repo` lane count while keeping `--max-per-repo` as a compatibility default. Semantic review, repair, and local validation run independent targets in parallel by default up to their `--*-max` target count; use `--semantic-review-concurrency`, `--repair-concurrency`, and `--local-validate-concurrency` to cap active processes lower than the target count. Deployed validation remains conservative with `--deployed-validate-concurrency 1` unless the configured target environments are safe to share.

Dispatch workers use runtime-global write-scope locks by default. Issues with disjoint `## Write Scope` paths can run concurrently on the same repo/base branch; overlapping paths, schema/migration siblings, and unknown or repo-wide scopes wait for a later cycle. Use `--no-write-scope-locks` only for a manually supervised run.

Automation-ready decomposition should make parallelism explicit instead of relying only on inferred locks. Leaf issues should carry dependency and scheduling metadata such as `Depends on`, `Blocks`, `Parallel group`, `Critical path rank`, `Merge group`, `Combine policy`, `Conflict class`, `Write Scope`, and `Validation tier`. Treat missing or unknown metadata as a reason to narrow dispatch, not a reason to widen it.

Keep PRs separate by default. A one-point issue should normally produce one draft PR; use an explicit integration issue or `Merge group` when several green PRs need a planned rollup. Combining unrelated implementation PRs early makes repair routing and finalization less reliable.

GitHub CLI calls are paced through a runtime-wide throttle file under `jobs/github-api-throttle/`. Keep `AGENT_GITHUB_THROTTLE=true` when running multiple lanes so Project v2 GraphQL scans, `--json` issue/PR reads, and label/comment mutations do not stampede one token. The default pacing is conservative, and `AGENT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS` stops later stages from hammering GitHub after a rate-limit response. Use `./atlas-agent-throttle-status` to inspect cooldown and stale-lock state without calling GitHub.

Workstream review runs before dependency promotion in the default unattended loop. It reads items labeled
`agent:workstream-review-required`, can write feedback files/summaries, and applies
`agent:workstream-review-passed`, `agent:workstream-review-failed`, `agent:workstream-needs-human`, or
`agent:workstream-followup` according to the operator flags and review outcome.

Workstream completion requires a review bundle, not just merged PRs. Before marking a workstream done, record
semantic review status, garbage collection results, documentation changes or a docs-not-needed rationale,
validation evidence, and downstream readiness. Garbage collection includes stale followups, obsolete config,
generated junk, duplicate source-of-truth, and abandoned automation artifacts or branches when they are safe to
remove. Documentation updates are mandatory unless the closure record explains why no docs are affected.

PRs with no GitHub checks and no configured required checks are labeled `agent:local-validation-required`; `atlas-agent-local-validate --apply` runs the configured local commands and swaps that label to `agent:local-validation-passed` or `agent:local-validation-failed`. `local-validation.json` may use the legacy `repo -> [commands]` form or a structured object with `install_commands`/`setup_commands` followed by targeted `commands`. If a repository has required checks configured, local or deployed validation does not replace missing GitHub check reports.

Worker publication also has a pre-PR evidence gate. The implementation agent must leave a `Tests` or `Verification` section with exact commands and results before the worker publishes a draft PR. If tests are intentionally not run, the issue must carry an explicit validation waiver reason or controlled waiver label. Configure `pre-commit run --all-files`, targeted test commands, and build commands in `local-validation.json`; repository hooks may be disabled in worker worktrees, so important checks must be commands, not only hooks.

To reconcile more than one GitHub Project, put targets in `projects.txt` as `OWNER/NUMBER`, one per line, then run `atlas-agent-unattended --projects-file projects.txt --project-reconcile-every 3 ...` or run `atlas-agent-project-reconcile --projects-file projects.txt --apply` as a separate checkpoint. The Project board must use a `Status` field with `Todo`, `In Progress`, and `Done`. Project lifecycle scans read up to `AGENT_PROJECT_ITEM_LIMIT` cards, default `500`; raise that value if the reconcile log says the scanned item limit was reached or new cards are not moving.
Runtime stages do not update Project fields by default. Set `AGENT_PROJECT_STATE_UPDATES=true` only for supervised direct Project writes, or set `AGENT_PROJECT_STATE_UPDATE_MODE=queue` to append desired field updates under `jobs/project-sync/*.jsonl`. Use `./atlas-agent-project-sync status` offline and `./atlas-agent-project-sync flush` when you want to apply queued Project updates. Priority is inherited from the plan/parent issue during decomposition and can be backfilled by reconcile tooling.

Local validation is a fallback for repositories that do not publish PR checks. It can allow review approval and can move a draft PR to ready, but unattended merge still requires GitHub checks unless `required-checks.json` explicitly marks a path-scoped no-checks policy such as docs-only changes with a required `agent:no-checks-expected` label.
Validation labels alone are not sufficient for review approval. The review/finalizer path expects current-head
evidence comments with a recognized validation marker, `Head: <sha>`, and passing `Result:` for local,
deployed, and semantic validation gates.

Playwright is part of the shared dev dependency set so runtime validation can later add browser-backed checks without each target repo inventing its own install path.

Optional deployed/manual validation:

```bash
cp config/deployed-validation.example.json deployed-validation.json
```

Use this only after the target repo has chosen hosted/deployed validation. Configure an object with `workflows`, `commands`, and optional `env`; `atlas-agent-deployed-validate --apply` dispatches workflows, runs commands, records artifact names, applies `agent:manual-validation-approved` and `agent:deployed-validation-passed` when they pass, and removes failed/required validation labels. Review will then allow `agent:review-approved` when all other blockers are clear.

Repo-specific environment overlays live under `repo-env/<OWNER__REPO>/`. Files in that directory are copied
into worker and validation worktrees with mode `0600`; use it for local secrets or environment fragments that
must never be committed to a product repo.

Use `--post-cycle-summary` to send one Teams notification per cycle. Per-repo triage Teams posts are off by default; use `--post-triage-teams-per-repo` only for debugging.

## Safety

Do not use `--allow-no-checks` broadly. The default finalizer blocks no-check PRs unless an explicit
`required-checks.json` path policy and the `agent:no-checks-expected` label allow that PR shape.

Do not commit `config.env`, `codex-home/`, `repo-env/`, `jobs/`, `logs/`, `repos/`, or `state/`.
