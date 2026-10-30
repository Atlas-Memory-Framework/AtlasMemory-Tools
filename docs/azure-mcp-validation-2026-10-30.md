# Azure MCP and local communication validation

Result: source implementation and current-account instructions passed the gates
below. This is external AtlasMemory-Tools evidence, not qualification for
Atlas-native execution, unattended work, Azure writes or model/account routes.

## Implemented behavior

- MCP GitHub cycles select local comment policy. Worker results, reservations,
  status and handoffs stay local; PR/cloud operations remain explicit. Existing
  raw CLI installations retain their legacy compatibility default.
- Selected cloud review summaries skip unchanged successful publications.
- Six Azure operations share prepare/start/wait/cancel: inspection, worker
  preview/execution, draft publication, and Board preview/apply. Per-operation
  capabilities and original signed Azure grant checks remain controlling.
- Preparation makes no provider calls or worker launches. Results separate
  Boards and repository completeness and preserve bounded typed PR, policy,
  build, timeline and base-ref evidence. They exclude raw logs, credential
  values, unknown backend fields and task-acceptance claims.
- Discovery takes a caller-supplied project URL. Named configuration saves an
  explicit repository/branch selection only on apply. No organization, project,
  repository, branch or model is assumed.
- Profile updates require the reviewed current fingerprint. Retargeting needs a
  new profile name. Runtime state, checkouts, source pins and local overrides are
  preserved; receipts support rollback.
- Read-only and Board-only profiles need no model choice. Worker, routing and
  publication need explicit models; workers need an existing isolated checkout.

## Tests and review

`python3 scripts/verify_repo.py` passed:

| Suite | Result |
| --- | --- |
| Repository unittest | 327 passed |
| Selected pytest suites | 307 passed |
| Runtime unittest | 1,323 cases, one skipped |
| Total | 1,956 passed, one skipped |
| Static, generated adapter, copy and whitespace gates | Passed |

Independent final review reran 141 affected tests with 227 subtests and found no
remaining actionable issue. Earlier findings led to profile updates, explicit
worker checkout, and separate repository evidence projection.

Five real stdio MCP canaries use production service, adapter and lifecycle code
with owned isolated fixtures. They cover model-free Azure preparation, an actual
inspector dry-run, detached execution, reconnection, sanitized results, stale
input rejection, provider separation, missing grant refusal, configuration
preview and parameterized discovery. Fake auth/model/network executables reject
unintended calls. These fixtures do not establish authenticated Azure writes or
accepted development outcomes.

No original event log was supplied for the reported GitHub rate-limit incident.
Source evidence identifies avoidable comment reads/writes, not a measured cause
of that historical incident. The [communication audit](remote-communication-audit-2026-10-30.md)
records call sites, compatibility boundaries and remaining API use.

## Live read and installation

A standard MCP Python SDK client connected to the actual configured server,
listed nine tools, and called repository discovery with the project URL supplied
by the user at invocation. Azure returned three repository choices and observed
default branches. No repository was selected or saved. No returned target is
encoded in source, defaults or tests. No PR, Board mutation, model run or
production worker was started.

Account setup refreshed two managed instruction files and preserved 13 local
overrides. Receipt:
`/var/home/mat/.local/state/atlasmemory-tools/installations/20261030T170239Z-d5f489fc46/receipt.json`.
The existing GitHub registration is unchanged. Future agents configure their
selected Azure remote through the named tool. A new client session loads the
nine-tool catalog.

The supervised local JSON queue remains a separate maintained workflow. Its
unavailable explicit selection was recorded; no substitute installation, queue
claim or qualified daily execution was inferred.
