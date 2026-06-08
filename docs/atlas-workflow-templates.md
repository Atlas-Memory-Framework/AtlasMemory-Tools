# Atlas Workflow Templates

Atlas workflow templates describe structured agent-role workflows. The model name `TeamTemplate` is a shorthand for a
coordinated set of specialist agent roles, not a literal team, physical group, or human org chart.

## Model

- `TeamTemplate`: reusable workflow definition for a task family such as planning, work-item implementation, review, or validation.
- `TeamRole`: one specialist role in the workflow. A role names the agent/profile reference, optional skills, inputs it consumes, and the outputs it must produce.
- `TeamRun`: one execution of a template for a work item, plan, or review target.
- `TeamRunRoleResult`: one role's outputs, status, notes, and evidence links.

Templates should make the expected outputs explicit. For planning, roles might cover architecture, auth, security, data
models, data contracts, scaling, runtime operations, product semantics, and validation. For work items, roles might cover
implementation, test execution, code review, semantic alignment, and final evidence rollup.

## Rollup Contract

Every run should produce one rollup document that can be attached to the work-item lifecycle or plan evidence. The rollup
must show:

- template id and run id
- target work item or plan
- each role's agent reference
- required outputs and whether each output exists
- evidence paths or links
- missing outputs that keep the run incomplete

Templates must have unique role ids, role dependencies in `consumes` must refer to real roles in the same template,
dependency graphs must not contain cycles, and required output names must not be duplicated across roles. Those checks
keep rollups deterministic: one output name maps to one role, and missing-output evidence can point at the responsible
role without guessing.
When `rollup.missing_outputs_block_completion` or `rollup.require_coverage` is enabled, the template must also contain a
real aggregation phase: at least one final-phase role must consume every prior role. `atlas-agent-workflow-lint` reports
the derived rollup role so operators can verify that specialist outputs have an explicit consolidation point.
The template model also derives role phases from `consumes`: roles in the same phase have no outstanding dependencies on
each other and can be considered parallel candidates, while later phases wait for earlier role outputs. Phase data is
included in lint output, compact run summaries, and each role task packet as `phase_index`.

The bootstrap implementation lives in `templates/local-automation-runtime/atlas_workflows.py`. Default JSON templates
live under `templates/local-automation-runtime/team-templates/`:

- `planning-design-doc`: architecture, auth, security, data models, data contracts, scaling, runtime operations,
  validation, product semantics, and rollup editing.
- `work-item-change-lifecycle`: implementation, test execution, code review, semantic alignment, and evidence rollup for
  one work item.
- `review-evidence-gate`: code review, security review, semantic review, and review decision rollup.
- `validation-evidence-gate`: test planning, local validation, deployed/manual validation, and validation rollup.

The current code can load a template file or directory and select a template by `workflow_kind` plus required output
names. A work item can request a workflow through top-level, `metadata`, or `scheduler` fields:

```json
{
  "id": "WI-1",
  "status": "ready",
  "scheduler": {
    "workflow_kind": "planning",
    "team_template": "planning-design-doc",
    "required_outputs": ["threat_model", "validation_commands"]
  }
}
```

Before running a workflow, use `atlas-agent-workflow-select` to inspect the current template catalog against a work item
or a proposed request. It reports the selected template, role phases, outputs covered by each candidate, and any required
outputs that no candidate covers. This is the local audit path for deciding whether to use an existing template, edit one,
or create a new task-specific template.
The JSON report includes a `selection` block with a stable `status`, `suggested_action`, closest matching template when
there is one, covered required outputs, and uncovered required outputs. The compact lifecycle evidence stores the same
decision block so later audit can see whether Atlas used an existing workflow template or identified a template gap.
When more than one template of the requested `workflow_kind` covers the required outputs, selection prefers the most
specific template: fewest extra outputs beyond the request, then fewer roles, then template id as a stable tie-breaker.
An explicit `team_template` request still wins when that template covers the required outputs.

```bash
templates/local-automation-runtime/atlas-agent-workflow-select \
  --team-templates templates/local-automation-runtime/team-templates \
  --work-item templates/local-automation-runtime/examples/atlas-work-items.sample.json \
  --json
```

When the selector recommends a new template, use `atlas-agent-workflow-template-add` to write a validated local JSON
template from explicit role contracts. The command fails closed on invalid dependency or rollup coverage and refuses to
overwrite existing templates unless `--force` is provided.

`templates/local-automation-runtime/config/agent-registry.example.json` is the first local registry seed for
`agent-registry://...` references used by the default templates. It names the expected specialist roles and their skills
without binding them to one execution command. Registry entries may include a `source` such as
`agents/security-review.md` and an `execution_profile` such as `review` or `planning`; the checked-in default registry
points at local persona/rubric files for the default workflow roles. `atlas_workflows.py` can validate both registry
source paths and local markdown agent references such as `agents/test-engineer.md` against an agent root. Dispatch policy,
live registry selection, and template mutation remain future work.
Use `templates/local-automation-runtime/atlas-agent-workflow-lint --agent-registry ... --agent-root ...` to check template
shape and agent references before running a workflow lane.
When the worker receives an agent registry and/or agent root, each role task packet also includes `agent_definition` with
the resolved agent id, ref, description, skills, and source path when available. This keeps downstream role executors from
having to rediscover the agent metadata that was used to schedule the workflow.
The local work-item worker already creates a run skeleton and markdown rollup when a claimed operation carries a workflow
request, so the lifecycle can point at missing role outputs before role-specific agent execution exists. Result evidence
records the selected template id, workflow kind, role ids, missing outputs, `team-run.json`, and `team-rollup.md`. It also
stores compact workflow-selection evidence, so the work-item lifecycle can show the request, selected template, candidate
role phases, covered required outputs, and missing required outputs without opening CLI output.

Workflow-aware local commands can write role results to the path in `ATLAS_TEAM_ROLE_RESULTS_FILE`:

```json
[
  {
    "role_id": "code-review",
    "status": "complete",
    "outputs": {
      "correctness_findings": "none",
      "regression_risks": "none",
      "test_gaps": "targeted tests only"
    },
    "evidence": ["jobs/review.md"]
  }
]
```

The worker validates role ids against the selected template, updates `team-run.json`, rewrites `team-rollup.md`, and
records `completed_roles` plus the updated `missing_outputs` in result evidence. A role result marked `complete` is
normalized back to `incomplete` if any declared `must_produce` output is missing. Extra output names are preserved but
recorded as contract issues. Contract issues and dependency blockers appear in `team-run.json`, the rollup markdown, and
compact lifecycle summaries so audit can distinguish "the command exited" from "the role satisfied its template
contract."

The worker also writes `team-role-tasks.json`. Each task packet includes the role id, label, selected `agent_ref`, skills,
dependencies from `consumes`, required outputs, current missing outputs, current role status, phase index, contract
issues, dependency blockers, and acceptance criteria. When agent resolution inputs are configured, the packet also
includes the resolved `agent_definition`.
This is the handoff point for a later role-agent runner: it can consume task packets without reparsing the template or
guessing which outputs each specialist role owns.

`atlas-agent-role-runner` consumes those packets today. A command map can resolve role execution by role id, resolved
agent id, `agent_ref`, execution profile, skill, or a `default` command:

```json
{
  "agent_ids": {
    "security-review": ["python3", "run_security_review.py"]
  },
  "agents": {
    "agent-registry://semantic-review": ["python3", "run_semantic_review.py"]
  },
  "profiles": {
    "validation": ["python3", "run_validation_role.py"]
  },
  "roles": {
    "code-review": ["python3", "run_code_review.py"]
  },
  "skills": {
    "handoff": ["python3", "write_rollup.py"]
  }
}
```

Each mapped command receives `ATLAS_ROLE_TASK_FILE` and `ATLAS_ROLE_RESULT_FILE`. It should write one role result object to
`ATLAS_ROLE_RESULT_FILE`; the runner appends that result to `ATLAS_TEAM_ROLE_RESULTS_FILE`, and the work-item worker then
refreshes the `TeamRun` artifacts. The runner advances dependency-ready roles in sequence and exits non-zero when any
required role outputs remain incomplete, so partial workflow evidence does not accidentally close a work item as complete.
The runner writes `role-runner-summary.json` beside per-role results with each attempted role's phase index and an
`incomplete_tasks` list showing blocked roles, missing outputs, dependency wait reasons, contract issues, and dependency
blockers. Contract issues written by a role command make that task incomplete immediately, even if the command also wrote
all required output names and marked the role `complete`.
When a bounded runner invocation completes at least one role but leaves required outputs missing, the local work-item
worker stores the partial run evidence and returns the item to `ready`. A later claim resumes the same `TeamRun` from the
previous artifact and writes fresh task packets with completed roles already marked complete. This lets large
agent-role workflows progress over multiple scheduler ticks while still failing closed when no role output was
successfully produced.
The worker also checks workflow completeness after any generic local command returns. A zero process exit code does not
mark the work item `done` if the selected template still has missing outputs.
For roles with `consumes`, the task packet includes `consumed_role_results` keyed by dependency role id. Rollup and gate
roles should use those consumed outputs as their source material instead of reparsing the markdown rollup or guessing from
the global result file. The same dependency rule is enforced during result ingestion: a role with `consumes` cannot be
accepted as complete until every consumed role has completed its required outputs. Ingestion rechecks existing role
results in dependency phase order, so transitive dependency failures propagate to downstream roles and stale generated
dependency issues clear when a later claim completes the upstream role.

Use `templates/local-automation-runtime/config/role-commands.example.json` only as a schema example. Its default command
intentionally writes a failed role result so an unmapped role cannot masquerade as validated specialist output.
Use `templates/local-automation-runtime/config/role-commands.codex.example.json` when the intended executor is Codex. It
maps the default template roles to `atlas-agent-role-codex`, which writes a role-specific prompt and fails closed by
default. Add `--execute` to the mapped command only after the runtime operator has chosen the Codex profile, auth boundary,
and sandbox policy for role execution. Even then, the wrapper still requires `--allow-execute` or
`ATLAS_ROLE_CODEX_ALLOW_EXECUTE=true`; this second gate is meant to keep command-map edits from silently enabling Codex
execution. Workflow-role execution uses the `AGENT_CODEX_WORKFLOW_ROLE_*` profile/model/extra-args/timeout settings.
The sample store `templates/local-automation-runtime/examples/atlas-work-items.sample.json` requests the review template.
Running it through `atlas-agent-orchestrator --atlas-role-command-config ./config/role-commands.codex.example.json`
creates prompt and workflow artifacts locally while intentionally leaving the work item failed until real role execution is
enabled.
For an end-to-end local completion smoke, use `config/role-commands.fake-execute.example.json`. It routes every role
through `atlas-agent-role-codex --execute --allow-execute --codex-command ./atlas-agent-role-fake-codex`; the fake command
writes deterministic non-empty outputs for each required output. This is only a harness for proving lifecycle wiring,
dependency hydration, and evidence rollup. It is not review or implementation evidence.

For durability, work-item result evidence embeds a compact `team_run` summary with the selected template, workflow kind,
run status, per-role status, completed output names, and missing outputs. The file artifacts remain the richer evidence,
but the work-item lifecycle can still be audited directly from the JSON store. `record_result` also appends a
`workflow_runs` entry to the work item with the compact run summary, artifact paths, and a rollup markdown snapshot.
