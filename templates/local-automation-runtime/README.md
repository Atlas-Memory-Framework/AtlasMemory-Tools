# Local Automation Runtime Template

Use the [current local harness operating instruction](../../docs/local-harness-operating-instruction.md) for queue-first work, model-route qualification and visible exceptions. It does not enable standalone model execution.

This template contains separate GitHub and Azure providers. The Azure provider
supports read-only inspection, one bounded local task, separately authorized
draft PR publication and revision-safe Board reconciliation. Start with the
read-only [Website source example](../../examples/instablinds/local-automation-runtime/config/azure-website.json) and the
[Azure operating contract](../../docs/azure-devops-runtime.md). Website uses
Azure exclusively; the GitHub workflow below is for other repositories.

`scripts/runtime_control.py` requires an explicit provider and an existing owned
runtime within the current identity. Status and dry-run commands never install,
migrate or dispatch child commands. Effective model/reasoning/argv settings for
planning, implementation, review and repair are reported before Azure dispatch.
Capabilities never replace exact operation authorization.

The Azure dispatcher adds explicit routing policy, independent challenge,
candidate-bound human gates and signed issuer grants. Its offline preview is
inert; assessment and worker execution are separate authorized operations.
See [routing and authority](../../docs/azure-dispatch-governance.md). Protect
`authority/`, `.azure-dispatch/`, `.azure-api/`, `.azure-supervisor/`,
`approval-inbox/`, `azure-reconcile/` and
`worktrees/` as operator state; template synchronization preserves them.

The [Azure supervisor and review inbox](../../docs/azure-supervisor.md) add
bounded observation, intake refresh and authenticated decision handoffs.
`atlas-agent-azure-supervise`, `atlas-agent-azure-intake` and
`atlas-agent-azure-approval` default to local previews. The supervisor prepares
requests and consumes verified responses; a separately configured issuer handles
human authentication and consent. No supervisor command enrolls that issuer or
installs a background process.

The GitHub lane provides:

- issue queueing from `status:ready` to `agent:ready`
- local Codex worker execution in isolated per-job worktrees
- draft PR publishing
- unattended reconcile, dependency promotion, dispatch, review, local/deployed validation, repair, finalize, and merge supervision
- local Atlas work-item dispatch from a JSON store without GitHub issue or PR mutation
- workflow-template models and default planning template under `team-templates/`
- bounded shift supervision with a wall-clock budget, one supervisor lock, heartbeat/status files, and handoff notes
- dry-run/apply cleanup for stale per-job worktrees, copied Codex homes, old job artifacts, logs, and imported template backups
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

Run the local work-item bootstrap lane without touching GitHub:

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
Each role packet includes `work_item_context`: the work item's title, substantive task/goal text, acceptance criteria,
validation commands, scope, checkout/base identity, and plan/spec references when supplied. This explicit projection
excludes lifecycle, claim, result, evidence, and unrelated metadata. It is carried through role-result refresh and resume,
and the Codex wrapper includes it in the prompt. Reference paths are context for the worker; the runtime does not load
their contents or verify their hashes here. Supply an explicit local checkout path and substantive instructions before
real execution. Goal-reviewed resumes bind the complete context and template contract; changed inputs block reuse and
require explicit replanning or rework. Declared plan/spec identities are included; reference contents are not read here.

The `work-item-change-lifecycle` template runs implementation, then tests, then independent code and goal-alignment
reviews, then evidence rollup. Both reviewers consume implementation and test results. `work-item` and `review` workflows
require exactly one independent `goal_gate`, substantive source goals, and acceptance criteria. That role must return
`goal_review` separately from its outputs:

```json
{"verdict": "pass", "reason": "Observed behavior meets the supplied criteria.", "evidence": ["path/to/result.json"]}
```

The exact verdicts are `pass`, `fail`, and `inconclusive`; reason and evidence must be nonempty. Only a complete role with
valid `pass` evidence and no contract issues satisfies the gate. Missing/malformed/negative reviews, failed commands,
and incomplete attempted roles persist `blocked` state. Positive rollup prose cannot override the gate. Dependent work
requires a current structured pass, including the current goal and workflow request hash. The reviewer still owns the
semantic judgment: a synthetic fake pass verifies wiring only.

Budget pauses return to `ready` only after newly completed roles; prior progress alone cannot cause repeated dispatch.
To prepare one bounded rework after diagnosis, use:

```bash
./atlas-agent-work-item-rework ./work-items.json --id LOCAL-WI-001 \
  --reason "Address the evidenced goal-review finding" --evidence ./review-finding.json
```

Only blocked items qualify. The fixed budget permits one explicit rework, archives prior run/result evidence, carries
the rationale and prior goal verdict into fresh role packets, and starts a fresh run. A second rework request is rejected;
the scheduler never starts a model repair loop automatically. Generic evidence-only workflow kinds remain available, but
cannot substitute for the goal-reviewed `work-item`/`review` contracts.

This is external bootstrap tooling, separate from Atlas-native runtime capability. Queue state, scheduling, packets, and
results stay local in this lane. A source checkout may use Azure Repos while local task identity remains local; this lane
does not fetch or publish source changes. Existing Azure Board records and Azure-origin operation identities are rejected
by the generic provider because they require the Azure worker's authority checks. The Azure adapter still reads Boards;
API pacing/caching there does not remove that dependency. Do not relabel remote work items to bypass its guards.

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

### Supervised in-app role handoffs

The supervised handoff adapter is a local Python library, not a dispatcher. Use
one persistent `claimed_by` identity, an explicitly configured checkout, the
existing provider/store, and a worker with `command=None`. For example, set the
paths and work-item ID for your installation, then run this in the runtime
environment:

```python
from pathlib import Path
import hashlib
import json
import subprocess
import sys

runtime = Path("/path/to/local-automation-runtime").resolve()
sys.path.insert(0, str(runtime))
import atlas_supervised_handoff as handoff
import atlas_work_items

store_path = Path("/path/to/work-items.json")
jobs_dir = Path("/path/to/local-jobs")
checkout = Path("/path/to/execution-checkout").resolve()
source_id = "WI-123"
supervisor_id = "operator:atlas-local-handoff"  # Keep this identity across restarts.

store = atlas_work_items.AtlasWorkItemStore(store_path)
provider = atlas_work_items.AtlasWorkItemOperationProvider(store, claimed_by=supervisor_id)
worker = atlas_work_items.LocalCommandOperationWorker(
    command=None,
    jobs_dir=jobs_dir,
    templates_dir=runtime / "team-templates",
    # Set these only when the selected roles use your local registry/agent files.
    agent_registry_path=runtime / "config" / "agent-registry.json",
    agent_root=runtime,
)

# The queue's configured execution_repo must explicitly identify this checkout.
# The wrapper independently verifies repository root and full HEAD before use.
head = subprocess.run(
    ["git", "--no-optional-locks", "-C", str(checkout), "rev-parse", "--verify", "HEAD"],
    check=True, capture_output=True, text=True, timeout=5,
).stdout.strip()
payload = store.load()
item = next(item for item in payload["work_items"] if atlas_work_items.item_id(item) == source_id)
state = atlas_work_items.item_state(item)
if state == "ready":
    operation = next(op for op in provider.operation_states() if op.source_id == source_id)
    if not operation.ready:
        raise RuntimeError(f"work item is not claimable: {operation.blockers}")
    if provider.claim(operation) is None:  # One explicit claim, before reservation.
        raise RuntimeError("claim lost a concurrent readiness race; inspect the queue")
elif state == "running":
    claim = item.get("claim") if isinstance(item.get("claim"), dict) else {}
    if claim.get("claimed_by") != supervisor_id:
        raise RuntimeError("active claim belongs to another supervisor; stop")
else:
    raise RuntimeError(f"expected ready or this supervisor's running item, got {state!r}")

prepared = handoff.prepare_handoff(
    provider, worker, source_id=source_id, expected_revision=head,
)
binding = prepared["binding"]
packet = prepared["packet"]
print(json.dumps({"binding": binding, "packet": packet}, indent=2))
```

Only after `prepare_handoff` returns should the supervisor dispatch that exact
packet with the existing in-app tool, using the packet's fixed model and
reasoning assignment. Do not call `worker.run()` or launch an inference command.
Retain the actual task/invocation ID returned by the app. If dispatch outcome is
uncertain, recover that same invocation from app history; do not dispatch again
or guess at a result. A repeated prepare for a still-valid pending handoff
returns the same reservation. A stale or refused reservation requires operator
inspection; it is not cleared or silently replaced.

Build the role result from the authentic single-role response. Keep the original
JSON bytes as received; the required root object is `{"role_results": [...]}`
with exactly one record for the reserved `role_id`. The record's `status` must
be terminal (`complete`, `failed`, `blocked`, or `incomplete`), `outputs` must
map output names to strings, and `evidence`, `contract_issues`, and `notes` must
use the fields and types shown below. For a goal-gate role, preserve its actual
structured review with `verdict`, nonblank `reason`, and nonempty `evidence`.
The example variables below must come from the real in-app response and receipt;
do not use placeholder values as evidence.

```python
# Supply these from the actual app response. Preserve its original bytes;
# do not parse and re-serialize the child's JSON before hashing/importing it.
actual_invocation_id = actual_task_id_returned_by_app
original_result_bytes = actual_role_result_bytes
decoded = json.loads(original_result_bytes)
records = decoded.get("role_results") if isinstance(decoded, dict) else None
if not isinstance(records, list) or len(records) != 1:
    raise RuntimeError("expected exactly one authentic role result; stop")
role_record = records[0]
if role_record.get("role_id") != binding["role_id"]:
    raise RuntimeError("result role does not match reservation; stop")
if not isinstance(role_record.get("outputs", {}), dict) or any(
    not isinstance(name, str) or not isinstance(value, str)
    for name, value in role_record.get("outputs", {}).items()
):
    raise RuntimeError("role outputs must map names to strings; stop")
# For packet["goal_gate"] == True, the original result must also contain its
# authentic structured goal_review; do not invent one to make acceptance pass.
assignment = binding["role_assignment"]
envelope = {
    "binding": binding,
    "host_receipt": {
        "invocation_id": actual_invocation_id,
        "transport": "supervised_in_app",
        "checkout": binding["checkout"],
        "revision": binding["revision"],
        "model": assignment["model"],
        "reasoning": assignment["reasoning"],
    },
    "result_sha256": hashlib.sha256(original_result_bytes).hexdigest(),
}
receipt = handoff.ingest_handoff(
    provider, worker, envelope=envelope, result_bytes=original_result_bytes,
)
print(json.dumps(receipt, indent=2))
```

If the process stops after reservation or dispatch, recover the same pending
packet and task; stop for human reconciliation when the invocation or its result
cannot be established. Replaying the exact accepted binding, host receipt, and
result bytes returns the prior acknowledgement without another queue event; a
different owner or conflicting replay is refused. `receipt["status"] ==
"accepted"` means the attempted role result was imported, not that the goal
passed. A failed or malformed goal review can be recorded and leave the item
blocked. Maintained `done` still requires every required role output and a
structured goal-review pass. There is one unresolved handoff across the store:
claim and prepare one role, import it, then explicitly claim the next role if
the item returns to ready. This opt-in adapter does not provide unattended
execution, automatic recovery/redispatch, or standalone startup qualification.

For a Codex-backed starting point, copy `config/role-commands.codex.example.json` instead. That map routes default
template roles to `./atlas-agent-role-codex`, which prepares a role-specific prompt and result-file contract but fails
closed unless the command is changed to include `--execute`. This makes the Codex invocation boundary explicit before
role output becomes lifecycle evidence. Actual execution also requires `--allow-execute` on the wrapper command or
`ATLAS_ROLE_CODEX_ALLOW_EXECUTE=true`, and uses `AGENT_CODEX_WORKFLOW_ROLE_*` profile/model/extra-args/timeout settings.

For explicit per-role model sizing, map each role to the wrapper with a distinct `--profile-kind`, such as
`["./atlas-agent-role-codex", "--profile-kind", "implementation"]`. Existing configuration keys then select
`AGENT_CODEX_IMPLEMENTATION_MODEL`, `AGENT_CODEX_IMPLEMENTATION_PROFILE`, and `AGENT_CODEX_IMPLEMENTATION_EXTRA_ARGS`.
Use separate kinds for decomposition and goal review. Verify the model identifier, effective argv, account and billing
route before enabling execution; an example model name or an available CLI does not establish that route. The local
lane does not classify task difficulty or choose a cheaper model automatically. Size the task packet to the selected
model and retain independent evaluation of the original goals. Neither a routing change nor a completed workflow
qualifies an unattended lane without a representative evaluated canary.

For enforced local sizing and fixed bindings, add this opt-in object to a work item's `metadata`:

```json
{
  "local_execution_v1": {
    "policy_id": "local-luna-unit-v1",
    "role_purposes": {
      "implementation": "implementation",
      "test-runner": "validation",
      "code-review": "review",
      "semantic-alignment": "goal-review",
      "evidence-rollup": "review"
    },
    "changed_interfaces": [],
    "unresolved_questions": [],
    "complexity_flags": []
  }
}
```

The qualifier derives counts from existing `write_scope` and `acceptance_criteria`; supplied point estimates cannot
override them. Coding/validation packets require 1–4 exact repository-relative file paths, 1–3 substantive acceptance
criteria, and at most one named changed interface. Directories, globs, and unknown scope block. The pure path qualifier
conservatively requires a file extension or `Makefile`, `LICENSE`, or `Dockerfile`; the provider also rejects existing
directories. More scope requires splitting. Unresolved questions or `security_or_authority`, `migration`,
`new_dependency_or_service`, or `cross_component_protocol` flags require decomposition before coding. Decomposition-only
work may inspect oversized input and produce smaller leaves; it cannot relabel an implementation role to evade limits.
These are conservative pilot bounds, not measured cost-optimal thresholds.

Every selected template role needs an explicit purpose; known implementation, validation, and review roles retain their
purposes. `implementation` and `validation` bind to `gpt-6-luna` with `medium` reasoning; `decomposition`, `review`, and
`goal-review` bind to `gpt-6.1-sol` with `high` reasoning. Unknown policies, purposes, model/provider overrides, and incomplete
role maps fail qualification. The local provider requires an independent goal gate and includes resolved routing in its
resume fingerprint. Scheduling and state remain in the local JSON store.

For an independently reviewed sizing decision, opt in with `policy_id: "local-reviewed-unit-v2"` in the same
`local_execution_v1` object. Add the required fields `implementation_model`, `review_model`, and `sizing_review`.
Choose `gpt-6-luna` for ordinary implementation (and validation); it runs at medium reasoning. For a coherent,
bounded task that needs stronger reasoning, the operator may select `gpt-6.1-sol` or `gpt-6.1-terra` at high reasoning
for implementation and validation. Choose either `gpt-6.1-sol` or `gpt-6.1-terra` at high reasoning for decomposition
and review, including goal review. The model choices are explicit; there is no automatic difficulty classifier.

`sizing_review` must contain exactly `reviewer`, `rationale`, and `subject_sha256`: a nonblank reviewer identity,
a specific rationale for this task and its selected models, and the digest of the complete work-item context. Compute
the digest with `atlas_local_sizing.sizing_subject_sha256(work_item_context)` after setting the models and all other
context fields; the helper omits only `local_execution_v1.sizing_review`. Any subsequent context change requires a
fresh sizing review and digest. These fields provide structural evidence and freshness binding only: strings and a hash
do not authenticate the reviewer or grant authority. The operator must retain actual independent host review and the
independent goal gate. The same file, criterion, and interface budgets apply, and a stronger model does not resolve
open questions or complexity flags; split or decompose those packets first. Existing execution, authority, billing,
and canonical-runner gates remain in force.

Contracted work must pass through the canonical role runner and Codex wrapper. Raw worker commands and custom role
executables cannot bypass the binding. The outer runner accepts only the generated command-config and bounded role-count
arguments; contracted role maps contain only the canonical wrapper executable, with no packet-substitution arguments.
The wrapper records `<result>.invocation.json` with the exact intended model,
reasoning, and argv before execution. Ambient profile/model/extra-argument or provider overrides are rejected. Contracted
`--execute` remains blocked by default with `standalone provider/billing/startup not qualified`. The contracted route can
launch only when the supervisor-owned runtime `config.env` contains
`ATLAS_ROLE_CODEX_STANDALONE_ROUTE_QUALIFICATION="chatgpt_subscription"` and the existing execute gate is enabled. The
qualification value must be set only after the execution owner independently verifies account identity, subscription
billing, assigned-model availability, and the applicable spending allowance; task JSON and `--allow-execute` alone cannot
qualify the route. The canonical runner can request execution mode only when its operator-owned command config contains
`"supervisor_codex_execution_mode": "contracted-chatgpt-subscription-v1"`; the field is absent by default, is never read
from task JSON, and does not replace route qualification or the existing execute gate. Contracted launches use bounded
wall time and combined output. The Codex child inherits the canonical
role runner's process group so the outer work-item supervisor retains group cleanup custody; the wrapper reports only
direct-child and pipe state, and rebuilds its diagnostic report from parent-held metadata after the child exits. It reads
the child result only as a no-follow regular file, limited to 64 KiB, and atomically replaces the result, invocation
report, and log paths using a directory descriptor held across execution. The wrapper sends its validated result to the
canonical role runner through a bounded private file-descriptor handoff; the nested Codex process does not inherit that
descriptor. The runner consumes that handoff rather than reopening a child-writable result pathname, and anchors its
contracted result and output publication to its own held results-directory descriptor. It checks that the configured
directory path still identifies that directory immediately
after publication; a changed path fails closed. This prevents a same-group descendant from redirecting the consumer's
result read or parent writes through a swapped directory path.
Group uncertainty keeps the work item blocked. This does not prove cleanup of descendants that deliberately detach into
another session. This source change does not verify billing or enable an active role map. Preparation
verifies binding only, and cannot count as accepted implementation. Existing uncontracted packets retain their prior behavior.

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

`atlas-agent-shift` holds one runtime-wide supervisor lock, runs `atlas-agent-unattended --cycles 1` repeatedly, updates `jobs/atlas-agent-shift-heartbeat.json`, writes a per-shift status JSON under `jobs/`, and writes a markdown handoff under `jobs/` on exit. Use it when the lane is already stable and the operator needs durable resume state across a long window. The unattended cycle performs GitHub issue reconciliation every cycle, runs runtime cleanup in the configured dry-run/apply mode, and keeps GitHub Project reconciliation out of the default hot path; use `--project-reconcile-every N` for checkpoint Project syncs. On `atlas-agent-shift`, that interval is counted across shift cycles. The shift wrapper adds wall-clock limits and restartable evidence, not broader mutation authority.

`agent:done` is reserved for resolved/closed work. A published draft PR leaves the linked issue marked `agent:pr-open` until the finalizer merges and closes it.

The default stage order is `reconcile -> decompose -> workstream-review -> dependency-promote -> dispatch -> review -> semantic-review -> review -> local-validate -> review -> semantic-review -> review -> deployed-validate -> review -> semantic-review -> review -> repair -> review -> semantic-review -> review -> finalize -> summary -> cleanup`. The default is local-first: GitHub Project sync is advisory and runs only when `project-reconcile` is explicitly included in `--stages` or `--project-reconcile-every N` is set. The decompose stage marks one-point issues with `agent:one-point` and prevents larger point estimates from reaching dispatch until they are split. The dependency promotion stage is dry-run by default and applies body, label, and Project field updates when `--apply`, `--review-apply`, or `--dependency-promote-apply` is used. Use `atlas-agent-issue-decompose --child-drafts-file /tmp/children.json --dry-run --issue OWNER/REPO#N` to emit reviewable one-point child issue drafts without creating GitHub issues. Use `--decompose-create-subissues` when you want the planning Codex profile to create one-point child issues for oversized parents.

Runtime cleanup is a garbage-collection pass over local artifacts, not GitHub state. `atlas-agent-cleanup` defaults to dry-run and reports stale checkout, copied Codex home, job artifact, log, and imported-template backup candidates. It uses a runtime cleanup lock, protects recent job `worktree.txt` markers, skips dirty worktrees and worktrees with active git lock files, and prunes stale git worktree registrations from cached repos. Run it manually before enabling deletion:

```bash
./atlas-agent-cleanup --measure-size --summary jobs/cleanup-preview.json
```

To delete after review, pass `--apply`; to use it live, set `AGENT_CLEANUP_MODE=apply` or run unattended with `--cleanup-mode apply`. For very large runtimes, keep the first apply bounded with `--max-delete N` and repeat until the summary is clean. The highest-impact target is normally `jobs/checkouts/<OWNER__REPO>/`, because every retained per-job worktree can duplicate large repository assets. Dirty checkouts are preserved unless `--include-dirty-checkouts` is explicitly supplied.

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
