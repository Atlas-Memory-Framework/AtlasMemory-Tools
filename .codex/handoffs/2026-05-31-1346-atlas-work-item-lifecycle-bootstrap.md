# Handoff: Atlas Work Item Lifecycle Bootstrap

**Created:** 2026-05-31 13:46 UTC
**Project:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
**Branch:** `docs-runtime-update`
**Purpose for next session:** Continue the Atlas-owned local work-item lifecycle and workflow-template bootstrap from the new local provider/model.
**Continues from:** `.codex/handoffs/2026-05-31-0252-atlas-work-item-lifecycle-bootstrap.md` was requested but was not present in this checkout.

## Current State

The local Atlas work-item scheduler/worker bootstrap is implemented in the runtime template. `atlas-agent-orchestrator`
now has an opt-in `--atlas-work-items path/to/work-items.json` mode that bypasses GitHub issue dispatch entirely. It loads
ready local work items, projects them to operation states, lets `run_worker_daemon_once` claim work, runs an optional local
command, and records claim/result evidence back onto the same JSON work-item record.

The first explicit workflow-template model is also present. `TeamTemplate` is documented as a structured agent-role
workflow label, not a literal team or human org chart. `TeamRun` records role outputs and rolls them into one evidence
document with missing-output tracking. A default `planning-design-doc` JSON template now exists under
`templates/local-automation-runtime/team-templates/`, and the runtime can load/select templates by workflow kind,
explicit template id, and required outputs from work-item metadata. The default templates now cover planning and
work-item change execution. When a claimed local work item carries a workflow request, the worker now writes a
`team-run.json` and `team-rollup.md` skeleton into the job directory and links those artifacts from result evidence.
`atlas-agent-workflow-select` now reports the selected template plus all candidates, role phases, covered outputs, and
missing required outputs for a work item or direct workflow request. Use it before a run to decide whether an existing
template is sufficient or a task-specific template needs to be edited/created.
When multiple templates of the requested workflow kind cover the required outputs, selection now chooses the most
specific match by fewest extra outputs, then fewer roles, then template id; explicit `team_template` requests remain
authoritative when they satisfy the required outputs.
Template selection reports now also include an explicit `selection` decision block with `status`, `suggested_action`,
closest matching template, covered required outputs, and uncovered required outputs. This gives Atlas a stable local
signal for whether to use an existing workflow template, edit the closest matching template, or create a new
task-specific template before execution.
`atlas-agent-workflow-template-add` now closes the local scaffold loop: it writes a validated workflow template JSON file
from explicit role contracts, refuses to overwrite existing templates without `--force`, and by default requires a final
rollup role that consumes all prior roles.
Result evidence includes selected template id, workflow kind, role ids, missing outputs, and artifact paths. Template
selection evidence is also recorded compactly on the work item with candidate role phases, covered required outputs, and
missing required outputs, plus the same selection decision block, so later audit can see why a template matched or why a
template gap was identified without opening CLI output. Template
validation now rejects duplicate outputs, self-consuming roles, unknown `consumes` references, and dependency cycles.
Templates that set `rollup.missing_outputs_block_completion` or `rollup.require_coverage` now also require a final-phase
rollup role that consumes every prior role; workflow lint reports the derived rollup role for audit.
Templates now derive schedulable role phases from `consumes`: same-phase roles are dependency-independent fan-out
candidates, and later phases wait for earlier consumed outputs. Phase data appears in lint output, compact run summaries,
and each role task packet as `phase_index`.
Workflow-aware local commands can write role outputs to `ATLAS_TEAM_ROLE_RESULTS_FILE`; the worker then refreshes
`team-run.json`, rewrites `team-rollup.md`, and records `completed_roles` plus updated `missing_outputs` in lifecycle
result evidence.
The worker also writes `team-role-tasks.json` and exposes it as `ATLAS_TEAM_ROLE_TASKS_FILE`. Each task packet contains
the role id, selected `agent_ref`, skills, dependencies, required outputs, current missing outputs, status, acceptance
criteria, phase index, contract issues, dependency blockers, and completed dependency outputs under
`consumed_role_results`.
When `--agent-registry` and/or `--agent-root` are provided, task packets also include `agent_definition` metadata with
the resolved agent id, ref, description, skills, and local markdown source path when available. This makes the packets
self-contained enough for downstream role executors and audit tools without changing execution authority.
The default registry seed now includes `source` paths, and the repo now has canonical `agents/*.md` persona/rubric files
for the registry-backed workflow roles: architecture, auth, security, data-models, scaling, product-semantics,
rollup-editor, implementation, semantic-alignment, evidence-rollup, security-review, semantic-review, review-rollup,
local-validation, deployed-validation, and validation-rollup.
`atlas-agent-role-runner` now consumes those task packets with a JSON command map. It selects dependency-ready roles,
resolves commands by role id, resolved agent id, `agent_ref`, execution profile, skill, or default, hydrates consumed
dependency outputs into downstream task packets, runs the mapped local command, and appends role results for the work-item
worker to ingest. Role commands receive `ATLAS_AGENT_ID`, `ATLAS_AGENT_SOURCE`, and
`ATLAS_AGENT_EXECUTION_PROFILE` alongside the role task/result file paths.
Its `role-runner-summary.json` records attempted role phase indexes and an `incomplete_tasks` section with blocked roles,
missing outputs, dependency waits, contract issues, dependency blockers, and terminal task status.
`atlas-agent-role-runner` also treats command-authored `contract_issues` or `dependency_blockers` as incomplete
immediately, even when all required output names are present and the role command wrote `status: complete`; such roles are
excluded from `completed_roles` for dependency scheduling and cause a non-zero runner exit. Stale task-packet blockers are
cleared when a role command writes a fresh successful result without those issues, so resumed/downstream fake-execute
flows can complete.
`atlas-agent-orchestrator` can invoke it directly with `--atlas-role-command-config` and `--atlas-role-max`, and can pass
agent resolution inputs with `--agent-registry` and `--agent-root`.
Work-item result evidence now embeds a compact `team_run` summary with template id, workflow kind, status, per-role
status, role phases, completed output names, missing outputs, contract issues, and dependency blockers, so the JSON
work-item lifecycle is auditable without dereferencing job artifacts. The markdown rollup also prints role dependencies
and dependency blockers beside role output evidence.
`record_result` now also appends a durable `workflow_runs` entry onto the work item with artifact paths, the compact
`team_run` summary, and a rollup markdown snapshot. `config/role-commands.example.json` was added as a safe failing stub
for the role-runner command-map schema.
`atlas-agent-role-runner` now advances dependency-ready roles in sequence up to `--max-roles` and exits non-zero when
required outputs remain incomplete, preventing partial workflow evidence from being treated as complete.
When a bounded role-runner invocation completes at least one role but leaves required outputs missing, the local worker
records the partial evidence, moves the work item back to `ready`, preserves the active claim under `previous_claims`,
and resumes the same `TeamRun` on the next claim from the previous run artifact. Failures that do not complete any role
still fail closed.
Role result ingestion now enforces the template contract more clearly: a `complete` role result missing required
`must_produce` outputs is normalized to `incomplete`, unexpected output names are recorded as contract issues, and a
generic local command returning `0` cannot mark a workflow work item `done` while selected-template outputs remain
missing. Downstream roles with `consumes` are also normalized to `incomplete` until every consumed role has completed its
required outputs, so generic result files cannot bypass dependency ordering. Normalization now rechecks existing results
in dependency phase order; transitive dependency failures propagate downstream, and stale generated dependency issues
clear when a later claim completes the upstream role.
The local Atlas work-item path now honors `--dry-run`: it previews ready operations and does not claim work items, create
job directories, run workers, or mutate the JSON store.
`atlas-agent-work-item-add` now appends a new local `ready` work item with scheduler/workflow metadata and `create`
evidence, failing on duplicate ids. It is local-only and writes to the same JSON store consumed by the scheduler.
It can also validate the requested workflow against a local template catalog at enqueue time: `--select-team-template`
stamps the selected template id into scheduler metadata when the catalog has a match, and `--require-template-match`
fails before creating the store record when required outputs are uncovered.
`atlas-agent-work-item-inspect` now exposes the same scheduler projection for local stores, including ready, blocked,
active, and terminal items with blocker reasons in text or JSON output. JSON inspection also includes claim/result
summaries and latest workflow run state: selected template, missing outputs, completed roles, continuation markers,
resume markers, and artifact paths.
Ready local work items are now claimed in deterministic scheduler order: priority first (`p0` before `p1` before `p2`
before `p3`, including `priority:p*` labels), then lower `critical_path_rank`, then work-item id. Full inspection remains
in store order for auditability.
Ready local work items are also blocked while another local item is active on an overlapping execution repo, base branch,
and `write_scope`; missing scope metadata is treated conservatively as overlapping.
`atlas-agent-work-item-requeue-stale` previews stale `running` claims by default and requeues them only with `--apply`.
Applied requeues move the item back to `ready`, preserve previous claim data under `previous_claims`, and append
`requeue` evidence to the same work-item lifecycle.
`atlas-agent-role-codex` and `config/role-commands.codex.example.json` now provide a Codex-backed command-map starting
point. The wrapper prepares a role prompt/result contract and fails closed unless `--execute` is explicitly added.
Execution still requires a second gate, `--allow-execute` or `ATLAS_ROLE_CODEX_ALLOW_EXECUTE=true`, and uses
`AGENT_CODEX_WORKFLOW_ROLE_*` profile/model/extra-args/timeout settings. Tests cover profile arg selection, missing second
gate failure, runtime-relative command resolution, and fake allowed execution writing required role outputs.
`atlas-agent-role-fake-codex` and `config/role-commands.fake-execute.example.json` provide a deterministic local
completion harness that exercises the same wrapper/runner path without executing real Codex. It is lifecycle wiring
verification only, not trusted review or implementation evidence.
`examples/atlas-work-items.sample.json` now provides a local prepare-only review workflow smoke input for the orchestrator.
The prepare-only smoke was run against a temp copy of that sample: it processed one local work item, attempted the three
independent review roles, completed zero roles, kept all required outputs missing, wrote one `workflow_runs` record, and
failed the work item as intended (`returncode: 3` from role runner, process exit still `0` because orchestrator reports
processed count).
A fake-execute smoke was also run against a temp copy of the sample: it processed one local work item, completed
`code-review`, `security-review`, `semantic-review`, and `review-rollup`, wrote consumed dependency outputs into the
rollup task packet, appended one complete `workflow_runs` record, and marked the work item `done` with result returncode
`0`.
`AgentRegistry`, `AgentDefinition`, markdown frontmatter parsing, and `validate_template_agent_refs` are now in
`atlas_workflows.py`. `AgentDefinition` includes an `execution_profile` field used by role-runner profile command maps.
The runtime has an initial `config/agent-registry.example.json` seed for the default `agent-registry://...` references,
and `atlas-agent-workflow-lint` checks template shape plus optional registry/local markdown agent references and registry
source paths.

## Decisions

- **Keep the Atlas work-item path local-only:** The new provider does not query GitHub issues, edit labels, publish PRs,
  or update Projects. This preserves the bootstrap boundary while Atlas-owned lifecycle state matures.
- **Use a JSON store first:** `AtlasWorkItemStore` is a small locked JSON file store, intentionally simple enough to
  replace with an Atlas-native backend later.
- **Claim against the locked current snapshot:** Claim rechecks readiness and dependencies while holding the store lock,
  preventing stale ready projections from claiming blocked work.
- **Use TeamTemplate as a model name only:** Docs clarify that "team" means an organized specialist-agent workflow.

## Changed or Important Files

- `templates/local-automation-runtime/atlas_work_items.py`: JSON-backed `AtlasWorkItemStore`, operation projection,
  claim/result evidence, local command worker, workflow artifact skeletons, role-result ingestion, and
  `run_worker_daemon_once`.
- `templates/local-automation-runtime/atlas-agent-orchestrator`: adds `--atlas-work-items` and
  `--atlas-work-item-command` dispatch path plus optional `--team-templates`, `--atlas-role-command-config`, and
  `--atlas-role-max`.
- `templates/local-automation-runtime/atlas-agent-role-runner`: local role-task runner that consumes
  `team-role-tasks.json` and writes role results through a command map.
- `templates/local-automation-runtime/atlas-agent-role-codex`: safe Codex role wrapper; prepares prompts by default and
  requires explicit `--execute` to invoke `codex exec`.
- `templates/local-automation-runtime/atlas-agent-role-fake-codex`: local fake Codex command used only for deterministic
  lifecycle wiring smoke tests.
- `templates/local-automation-runtime/atlas-agent-workflow-lint`: local lint command for workflow templates and optional
  agent reference validation.
- `templates/local-automation-runtime/atlas-agent-workflow-select`: local template-selection inspector for work items or
  direct workflow requests.
- `templates/local-automation-runtime/atlas-agent-workflow-template-add`: local command to create a validated workflow
  template JSON file from explicit role contracts.
- `templates/local-automation-runtime/atlas-agent-work-item-add`: local-only command to append ready work items with
  scheduler/workflow metadata.
- `templates/local-automation-runtime/config/agent-registry.example.json`: local registry seed for the checked-in
  `agent-registry://...` workflow roles.
- `templates/local-automation-runtime/config/role-commands.example.json`: safe stub command-map example for role runner
  configuration.
- `templates/local-automation-runtime/config/role-commands.codex.example.json`: maps default workflow template roles to
  the Codex wrapper.
- `templates/local-automation-runtime/config/role-commands.fake-execute.example.json`: fake-execute command map for local
  completion smoke tests.
- `templates/local-automation-runtime/examples/atlas-work-items.sample.json`: local sample work-item store that requests
  the review workflow template.
- `templates/local-automation-runtime/atlas_workflows.py`: `TeamTemplate`, `TeamRole`, `TeamRun`, role result, validation,
  missing-output, markdown rollup model, template loading, and work-item-aware selection.
- `templates/local-automation-runtime/team-templates/planning-design-doc.json`: first structured planning workflow template
  with specialist roles for architecture, auth, security, data models, data contracts, scaling, runtime operations,
  validation, product semantics, and rollup editing.
- `templates/local-automation-runtime/team-templates/work-item-change-lifecycle.json`: first work-item workflow template
  with implementation, test-runner, code-review, semantic-alignment, and evidence-rollup roles.
- `templates/local-automation-runtime/team-templates/review-evidence-gate.json`: review-only workflow with code review,
  security review, semantic review, and review rollup.
- `templates/local-automation-runtime/team-templates/validation-evidence-gate.json`: validation-only workflow with test
  planning, local validation, deployed/manual validation, and validation rollup.
- `templates/local-automation-runtime/tests/test_atlas_work_items.py`: focused lifecycle/provider/orchestrator tests.
- `templates/local-automation-runtime/tests/test_atlas_workflows.py`: workflow-template/run/rollup tests.
- `docs/automation-runtime-operational-layer.md`: documents the local work-item bootstrap lane.
- `docs/atlas-workflow-templates.md`: documents TeamTemplate/TeamRun terminology and rollup contract.
- `README.md` and `templates/local-automation-runtime/README.md`: discovery docs.

## Verification

- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_work_items templates.local-automation-runtime.tests.test_runtime_template`: pass, 39 tests, 1 skipped.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_role_codex templates.local-automation-runtime.tests.test_atlas_role_runner templates.local-automation-runtime.tests.test_atlas_workflows templates.local-automation-runtime.tests.test_atlas_work_items templates.local-automation-runtime.tests.test_runtime_template`: pass, 96 tests, 1 skipped.
- `AGENT_JOBS=/tmp/atlasmemory-tools-test-jobs AGENT_LOGS=/tmp/atlasmemory-tools-test-logs python3 -m unittest discover -s templates/local-automation-runtime/tests`: pass, 360 tests, 1 skipped.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_workflows`: pass, 39 tests.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_workflows templates.local-automation-runtime.tests.test_atlas_work_items`: pass, 63 tests.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_work_items templates.local-automation-runtime.tests.test_atlas_workflows templates.local-automation-runtime.tests.test_runtime_template`: pass, 80 tests, 1 skipped.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_workflows templates.local-automation-runtime.tests.test_runtime_template`: pass, 56 tests, 1 skipped.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_work_items`: pass, 20 tests.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_workflows templates.local-automation-runtime.tests.test_atlas_role_runner`: pass, 45 tests.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_role_runner`: pass, 12 tests.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_workflows`: pass, 36 tests.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_work_items templates.local-automation-runtime.tests.test_atlas_role_runner`: pass, 29 tests.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_workflows templates.local-automation-runtime.tests.test_atlas_work_items`: pass, 49 tests.
- `python3 -m unittest templates.local-automation-runtime.tests.test_atlas_workflows templates.local-automation-runtime.tests.test_atlas_work_items templates.local-automation-runtime.tests.test_atlas_role_runner templates.local-automation-runtime.tests.test_runtime_template`: pass, 79 tests, 1 skipped.
- Local prepare-only smoke with `examples/atlas-work-items.sample.json` and `config/role-commands.codex.example.json`: pass for expected fail-closed behavior; work item status `failed`, result returncode `3`, `workflow_runs=1`, attempted roles `code-review`, `security-review`, `semantic-review`, completed roles `[]`.
- Local fake-execute smoke with `examples/atlas-work-items.sample.json` and `config/role-commands.fake-execute.example.json`: pass; work item status `done`, result returncode `0`, `workflow_runs[0].status` `complete`, completed roles `code-review`, `security-review`, `semantic-review`, `review-rollup`.
- `templates/local-automation-runtime/atlas-agent-workflow-lint --team-templates templates/local-automation-runtime/team-templates --agent-registry templates/local-automation-runtime/config/agent-registry.example.json --agent-root .`: pass, checked 4 templates and printed derived role phases.
- `templates/local-automation-runtime/atlas-agent-workflow-select --team-templates templates/local-automation-runtime/team-templates --work-item templates/local-automation-runtime/examples/atlas-work-items.sample.json --json`: pass; selects `review-evidence-gate` and reports all candidate template coverage.
- `templates/local-automation-runtime/atlas-agent-workflow-select --team-templates templates/local-automation-runtime/team-templates --workflow-kind review --required-output correctness_findings --required-output unknown_output --json`: pass with expected exit code `1`; reports `selection.status=no_covering_template`, `selection.suggested_action=edit_closest_template_or_create_new`, `closest_template=review-evidence-gate`, and `uncovered_required_outputs=["unknown_output"]`.
- `templates/local-automation-runtime/atlas-agent-workflow-template-add <temp-dir> --id migration-plan --workflow-kind migration --role-json ... --json` followed by `atlas-agent-workflow-lint --team-templates <temp-dir> --json`: pass; writes a two-phase migration template and lint reports `rollup_roles=["rollup"]`.
- `templates/local-automation-runtime/atlas-agent-work-item-add <temp-store> --id WI-SMOKE --workflow-kind review --required-output review_decision --write-scope templates/local-automation-runtime --json` followed by `atlas-agent-work-item-inspect <temp-store> --json`: pass; adds 1 ready local item with create evidence and scheduler metadata.
- `templates/local-automation-runtime/atlas-agent-work-item-add <temp-store> --id WI-SELECT --workflow-kind review --required-output review_decision --team-templates templates/local-automation-runtime/team-templates --select-team-template --json` followed by `atlas-agent-work-item-inspect <temp-store> --json`: pass; stamps `team_template=review-evidence-gate` and stores `selection.status=use_existing_template` on create evidence.
- `templates/local-automation-runtime/atlas-agent-work-item-inspect templates/local-automation-runtime/examples/atlas-work-items.sample.json --json`: pass; reports 1 ready local work item.
- `templates/local-automation-runtime/atlas-agent-work-item-requeue-stale <temp-sample-store> --stale-seconds 0 --json`: pass; preview reports no records for a ready-only sample store.
- `python3 -m py_compile templates/local-automation-runtime/atlas_work_items.py templates/local-automation-runtime/atlas_workflows.py templates/local-automation-runtime/atlas-agent-orchestrator templates/local-automation-runtime/atlas-agent-role-runner templates/local-automation-runtime/atlas-agent-role-codex templates/local-automation-runtime/atlas-agent-role-fake-codex templates/local-automation-runtime/atlas-agent-workflow-lint templates/local-automation-runtime/atlas-agent-workflow-select templates/local-automation-runtime/atlas-agent-workflow-template-add templates/local-automation-runtime/atlas-agent-work-item-add templates/local-automation-runtime/atlas-agent-work-item-inspect templates/local-automation-runtime/atlas-agent-work-item-requeue-stale`: pass.
- Initial full unittest discovery without overriding `AGENT_JOBS` failed because configured runtime paths pointed at a read-only installed agent home in this sandbox; rerun with `/tmp` job/log paths passed.

## Open Questions and Blockers

- [ ] Decide the durable Atlas-native backing store that will replace or wrap the JSON bootstrap store.
- [ ] Decide the durable Atlas template registry and mutation flow for promoting edited/new task-specific templates.
- [ ] Decide when a `TeamRun` should be appended directly to work-item lifecycle evidence versus stored as a separate artifact linked from the work item.

## Next Steps

1. Decide the real production Codex role profile and sandbox policy before enabling `ATLAS_ROLE_CODEX_ALLOW_EXECUTE=true`
   in any long-running runtime.
2. Evolve the registry seed into the durable Atlas agent registry, including concrete execution profiles and policy per
   role instead of only identity/skill validation.

## Context Notes

The user explicitly clarified that "teams" is an organizational shorthand for structured workflows and specialist agent
roles. Keep product wording careful: use "workflow template", "agent-role workflow", or `TeamTemplate` as a model name
with clarification. Avoid implying literal people, physical teams, or a human org chart.
