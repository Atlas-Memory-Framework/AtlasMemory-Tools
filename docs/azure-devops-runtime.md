# Azure Boards and Azure Repos runtime

The Azure adapter provides local, reviewable implementations of RUNTIME-A–D for
`https://dev.azure.com/Instablinds/Instablinds/_git/Website`. It does not establish
an installed runtime, an authorized worker, a published PR, or release readiness.
The user owns the immediate staging blocker.

The [dispatch and authority update](azure-dispatch-governance.md) adds an
explicit model policy, independent challenge, human handoffs and verified signed
grants. Its default preview remains inert. Existing local approval strings are
not sufficient authorization for worker execution, publication or Board writes.

Azure Repos is the Website delivery authority. The GitHub provider remains
available for other repositories. The wrapper rejects Azure targets and the
`Instablinds/Website` GitHub recovery archive when a GitHub operation is selected.

## Review slices

| Slice | Implementation | Acceptance boundary |
| --- | --- | --- |
| RUNTIME-A | `atlas_azure_devops.py`, `atlas-agent-azure-inspect` | Batched, paginated, cached reads; revisions and native dependency closure; complete, fresh evidence required before eligibility |
| RUNTIME-B | `atlas_azure_worker.py`, `atlas-agent-azure-worker` | One exact issue/revision/base/worktree/scope; bounded Codex roles and acceptance commands; local preparation and draft publication authorized separately |
| RUNTIME-C | `atlas_azure_reconcile.py`, `atlas-agent-azure-reconcile` | Exact proposal, fresh serial revision checks, owned-field preservation, uncertain-write readback, durable idempotency |
| RUNTIME-D | `atlas_runtime_config.py`, `scripts/runtime_control.py` | Explicit provider, capabilities, same-identity runtime, effective model settings, inert previews, operating contract |

These slices contain no Website merge, protected-branch push, branch cleanup,
workflow dispatch, deployment, permission, approval, or service-connection lane.
The Website's `docs/ai/agent-policy.md` remains the external-change authority
contract. A capability in a JSON file is not human authorization.

## Configuration and identity

The non-secret example is
[Website configuration](../examples/instablinds/local-automation-runtime/config/azure-website.json).
It explicitly chooses `azure-devops`, the canonical repository and `develop`
base, `read` capability, `workspace-write`, and `on-request` approvals. It contains
no credential, runtime-location default, execution authorization, or dependency
approval. Do not put tokens or auth material in this file.

The reusable template's `config/azure.example.json` uses organization/project/
repository placeholders. Product-specific settings live under the source
repository's `examples/instablinds/` directory and are selected explicitly.

Pass an existing runtime directory through `--runtime-dir`, `ATLAS_RUNTIME_DIR`
for the wrapper, or the configuration's `runtime_dir` field. The directory must
be an owned subdirectory of the current account's passwd home. The runtime does
not use `$HOME` to decide identity, create a missing directory, or follow a
symlink outside that identity. Configuration is restricted to the same home or
owned temporary work files. No command obtains another identity's credentials,
copies browser state, or reads `config.env` as Azure configuration.

For a worker, `repository.checkout` must name an existing isolated feature
worktree under `<runtime-dir>/worktrees/<task>`. The example identifies the
canonical source checkout for inspection; it deliberately cannot dispatch a
worker from that source directory. Creating or installing a runtime and creating
its worktree require their own authorized local preparation.

| Capability | What it enables | Additional gate |
| --- | --- | --- |
| `read` | Azure REST inspection | Explicit live-read mode and current-identity read access |
| `assess` | Bounded routing assessment and independent challenge | Verified signed grant for the exact intake, policy, configuration and budget |
| `local_execute` | One bounded local task | Exact worker authorization packet, fresh eligible issue revision, complete dependency contract, owned worktree, required commands and evidence |
| `draft_pr` | Create-only feature ref and draft Azure PR | Separate publication authorization for the exact packet, unchanged candidate and durable passing acceptance evidence |
| `board_write` | Exact Board JSON Patch proposal | Separately approved proposal digest, current revisions, owned fields and evidence |

Unknown providers or capabilities fail closed. `azure_devops` is accepted as an
alias and reported as `azure-devops`. Azure commands never fall back to `gh` or
the legacy unattended/finalizer scripts. Generic GitHub operators must select
`--provider github` explicitly; their runtime is also required to remain inside
their own identity.

## Model and command contract

The observed local CLI was Codex `0.153.4`, with `gpt-6-astra` and reasoning
`max`, `workspace-write`, `on-request`, and no profile. The example pins that
model/reasoning pair separately for planning, implementation, review and repair.
It does not silently inherit a future local default. A shared explicit
`models.default` is also supported; the report identifies whether each role
came from that entry or its own override.

The `models` and `status` wrapper commands, direct inspector reports and worker
previews expose every role's model, reasoning, configuration source and effective
argv. The worker uses those resolved settings to build the actual command:

```text
codex exec --ignore-user-config --sandbox workspace-write
  -c approval_policy="on-request" -m gpt-6-astra
  -c model_reasoning_effort="max"
  -c sandbox_workspace_write.network_access=false --ephemeral --json
  -C <owned-isolated-worktree>
```

The worker appends its own bounded output-file location and sends the reviewed
packet on stdin. Arbitrary command flags, profiles, `--add-dir`, user-config
overrides and approval/sandbox bypasses are not configuration options. The
worker sanitizes its process environment and rejects a different identity's
Codex home. Acceptance commands run through `codex sandbox --permission-profile
:workspace` with workspace-write semantics and shell networking disabled. The
explicit built-in permission profile keeps current Codex CLI releases from
silently selecting a different profile or rejecting the command before the
validator starts. Do not substitute a model if the configured one
is unavailable; report the blocker and obtain a reviewed configuration change.
Previewing argv is not evidence that a live model call or sandbox canary passed.

## Dependency intake remains blocked

Keep identifiers namespaced, for example `azdo:Instablinds:Instablinds:17`.
The September 8 Board receipt verified 53 native predecessor links and their
reciprocal successors on 21 rollout issues, affecting 27 endpoints. The full
planning closure has 37 items and 71 expected edges. Its other 18 prerequisite
edges were outside that authorization. None is added by inspection or inferred
from an empty dependencies array.

Inspection requires a versioned full expected graph to establish completeness:

```json
{
  "schema_version": 1,
  "organization": "Instablinds",
  "project": "Instablinds",
  "dependencies": {
    "azdo:Instablinds:Instablinds:17": ["azdo:Instablinds:Instablinds:16"],
    "azdo:Instablinds:Instablinds:16": []
  }
}
```

This small example describes a shape, not the campaign's complete graph or an
approved dependency set. The authority packet binds the canonical JSON digest
as `dependency_contract_sha256` and records an `approval_record`. A separately
approved versioned supplement must have the same graph shape and an exact
`dependency_supplement_sha256` plus `supplement_approval_record`; it may supply
only the missing expected edges. Native projection of the 18 edges instead
requires its own exact Board approval. Neither route is authorized by the
earlier 53-edge receipt.

Missing pages, incomplete batch reads, unresolved references, missing reciprocal
links, unknown states, cycles, revision drift, stale observations, absent graph
approval or absent execution authority keep eligibility blocked. A read command
can succeed while reporting zero eligible issues. A Board update or draft PR
never establishes release acceptance.

## Inspection and previews

The next source-template pilot needs no installation and makes no API or auth
call. From the AtlasMemory-Tools checkout, explicitly use its existing template
directory as the location for this inert preview:

```bash
python3 -B templates/local-automation-runtime/atlas-agent-azure-inspect \
  --config examples/instablinds/local-automation-runtime/config/azure-website.json \
  --runtime-dir /home/instablinds-admin/code/AtlasMemory-Tools/templates/local-automation-runtime \
  --expected-manifest templates/local-automation-runtime/tests/fixtures/azure-website-dependencies.expected.json \
  --dry-run
```

The expected result is `inspection_mode: dry-run`, no effects, dependency
completeness false and execution authority blocked. A direct inspector with
`--snapshot <expanded-snapshot.json>` projects an existing offline snapshot
without creating files, calling auth, or making network requests. Optional
`--expected-manifest`, `--supplement` and `--authority` are read-only inputs;
unapproved or incomplete inputs cannot grant eligibility.

The checked-in expected manifest contains the 37-node, 71-edge planning graph
and receipt provenance. It is an unapproved comparison fixture, not permission
to project its remaining dependencies or execute any issue. IDs can be omitted
when this manifest is supplied.

For the next *live read-only* pilot, review the explicit existing runtime
location and the returned effective configuration, then replace `--dry-run`
with `--live-read`. Use the complete expected manifest when it has been reviewed;
omitting it remains safely blocked. Do not add any write capability. Live read
auth uses the current identity's already-configured Azure CLI token in memory;
it does not print or persist the token and does not perform login or recover
credentials. An unavailable approved auth path blocks the read.

Live inspection has no Board/Repo mutation or worker dispatch. It maintains
only local shared throttle state needed to coordinate REST calls; choosing a
runtime directory does not install a service or migrate its configuration.
Repository evidence includes repository/base, PRs, policy/build evidence and
optional `--build-ids` timelines. Inspect the report's completeness and blockers,
not only the process exit code.

The wrapper requires `--config` and an explicit runtime for Azure commands.
`status`, `models`, `plan-preview`, `dry-cycle`, default worker/reconcile previews
and `--dry-run` do not execute a child runtime command. In particular, a dry-cycle
does not run a legacy loop that could update labels or dispatch workflows. The
wrapper prints a command plan; invoke the direct Azure inspector/reconciler to
validate an offline snapshot or proposal. Missing runtime scripts fail instead
of reporting a completed preview.

## Bounded execution and publication

Prepare one reviewed worker packet with: schema version; namespaced `id` and
current `revision`; exact `repository_url`, `base_branch`, `base_commit` and
`feature/*` or `develop-*` task branch; reviewed `write_scope`; bounded task; role timeout; nonempty
acceptance `commands` with IDs, argv and per-command timeout; and acceptance
IDs mapped to command IDs and distinct JSON evidence filenames. Include the
expected dependency manifest and its separate inspection authority.

The verified grant's operation bindings include the canonical packet SHA-256 as
`packet_sha256` and the canonical digest of `config.report()` as
`effective_config_sha256`, alongside repository URL, base branch and resolved
runtime directory. A changed model/reasoning or capability configuration
invalidates the earlier execution authorization. The authority verifier checks
the enrolled issuer's signature, exact action, policy, validity and revocation;
a nonempty approval reference is insufficient. Invoke
`--execute --authorization <local-execution-approval.json>` only after local
execution approval. Publication is a later separate invocation with
`--publish --authorization <draft-publication-approval.json>` and `draft_pr`
authority bound to the exact candidate and acceptance evidence. The wrapper
never chains these actions. See the [trusted approval contract](azure-dispatch-governance.md#trusted-approval-boundary)
for grant provisioning and the migration from unverified local records.

For a routed preparation, retain its exact `--routing` provenance for later
publication. Supply post-preparation answers with `--human-receipts`, containing
exactly a `receipts` list. The publication grant additionally binds
`publication_human_receipts_sha256` and `publication_gate_templates_sha256`.
Each candidate-specific human signature binds its original gate template and
review artifact; changing the owner, question or candidate invalidates reuse.

Claims are process-coordinated and reserve conservative path-prefix/glob scopes.
A missing worker/acceptance command, nonzero exit, stale revision, overlapping
scope, missing or mismatched candidate-bound evidence, failed review or uncertain
publication blocks progression. A process exit of zero is insufficient.
Interrupted claims and ambiguous writes require reconciliation; restarting does
not silently reclaim another worker's scope or create another PR. A passing
local preparation receipt does not close the Azure work item.

## Board reconciliation

Use the direct reconciler's `--snapshot <complete-expanded-read.json> --changes
<exact-changes.json>` to emit a local proposal and its digest. Save the returned
`proposal` member as the reviewed packet; `--packet` consumes that member, not
the surrounding preview report. Previewing requires no client or auth. Applying
requires `--apply --authorize-packet-sha256 <exact-approved-digest>` together with
`--authorization <signed-board-grant.json>` and configured `read` plus
`board_write` capabilities. The digest is a match check, not an approval source.
There is no approval inferred from tags,
issue descriptions, successful worker execution or the supplied config.

Every serial write re-reads current state and tests `/rev`. Proposed tag changes
are restricted to the declared operator-owned set, native dependency changes to
the exact approved endpoints, and state closure to the issue's explicit human
acceptance with immutable local evidence. Other fields and existing relations
are preserved. Revision conflicts require a fresh proposal and approval; an
uncertain write is reconciled against the target and reciprocal dependencies
before any retry. Reconciler receipts always keep execution eligibility blocked.

State closure supports the issue's release acceptance only. The acceptance
packet identifies `Dev`, `Staging` or `Production`, pipeline definition/run,
source candidate, artifact/package/assets SHA-256 digests, and database revision.
Each locally hashed evidence artifact must match that exact release and the
required check, assert successful acceptance, and contain nonempty already-run
commands with explicit successful results. The reconciler executes none of those
commands and rejects generic implementation completion as release acceptance.
The API's revision operation is documented in
[Azure Work Items Update](https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/work-items/update?view=azure-devops-rest-7.1).

## API pacing and retry evidence

All Azure REST operations share one process-coordinated
`.azure-api/throttle.lock` inside the explicit runtime, including requests to
different organizations. Work-item reads batch IDs; repeated
reads use bounded caching while eligibility and mutation checks require fresh
reads. Continuation pages are consumed explicitly, and missing/ambiguous pages
are not accepted as complete evidence.

`Retry-After` delays subsequent requests even when the response is HTTP 200; the
successful request is not replayed. Throttled or transient read failures use
bounded backoff. Ambiguous writes are never replayed automatically: callers
must read back their exact correlated result first. See
[Azure DevOps rate limits](https://learn.microsoft.com/en-us/azure/devops/integrate/concepts/rate-limits?view=azure-devops).
Draft PR creation sets the native `isDraft` field and reconciles its stable
publication marker and source/target branch before attempting creation again;
see [Azure Pull Requests Create](https://learn.microsoft.com/en-us/rest/api/azure/devops/git/pull-requests/create?view=azure-devops-rest-7.1).

## Validation, installation and rollback

Review the local fixtures and run from this checkout:

```bash
python3 -B -m unittest discover -s templates/local-automation-runtime/tests
python3 -B scripts/verify_repo.py
```

Tests cover throttling, batching/pagination, stale/incomplete reads, dependencies,
claims and path conflicts, command policy, duplicate publication, revision
conflicts, acceptance failures, provider routing, identity boundaries and inert
previews. They do not prove live Azure permissions, an installed worker sandbox,
deployment readiness, or a successful live PR/Board canary. No browser suite is
part of this adapter qualification.

Installation is a separate operation: choose an owned location, inventory the
existing runtime and state without reading secret values, review the exact
versioned managed-file delta, validate the source version, obtain installation
authorization, retain recoverable prior managed files, then explicitly sync and
verify. `runtime_control.py sync` only prints a command preview; applying requires
`sync --apply --yes`. Config migration additionally requires its explicit flag.
No other wrapper command syncs or migrates anything. Do not enable a service or
dispatch a worker as an installation check.

Rollback restores only that separately reviewed managed-file version while
preserving `config.env`, auth, repositories, worktrees, claims, journals, jobs and
evidence. Removing Board links/tags or a published branch/PR requires a new exact
external authorization and current readback; reverting local code cannot undo
those effects. The generic Atlas local work-item lane also requires configured
workflow acceptance outputs and a real command before completion, and rejects
Azure work-item metadata so it cannot bypass the Azure worker boundary.
