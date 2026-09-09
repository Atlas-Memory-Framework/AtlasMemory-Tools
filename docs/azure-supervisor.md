# Azure supervisor and approval operations

The supervisor connects evidence refresh, a local review inbox, and the existing
bounded Azure dispatcher, worker and reconciler. It coordinates work through
explicit commands and durable state; it does not install a daemon or grant its
children authority. The [implementation plan](azure-supervisor-plan-2026-09-09.md)
records the scope and the [routing contract](azure-dispatch-governance.md) defines
model selection, independent challenge and exact signed grants.

## Responsibility

| Condition | Supervisor/system action | Human responsibility |
| --- | --- | --- |
| Stale evidence | Refresh current native reads and declared source files; rebuild only when necessary | Resolve access or genuinely missing source information |
| Missing dependency links | Present the exact missing edges and a bounded reconciliation proposal when complete source proof is available | Approve the dependency contract and exact Board change |
| Unfinished prerequisite | Observe its evidence; select separately queued, authorized work if eligible | Perform human-owned prerequisites and acceptance |
| Missing scope or commands | Produce a truthful draft with concrete missing fields and questions | Decide unresolved scope or acceptance semantics |
| Missing/expired grant | Prepare or revise one review request with exact current bindings | Approve through the enrolled issuer |
| Human testing or taste | Preserve candidate/artifact-bound questions and verify the response | Test/review that candidate and record the decision |
| Uncertain child effect | Reconcile recorded state; stop if the effect cannot be established | Resolve the explicitly described uncertainty |

An unchanged timestamp, another model call or an exit code does not prove
progress. Adding dependency links never completes prerequisite work. The immediate
staging release blocker remains with the user. Website pipeline approvals,
deployments, protected branches, permission changes, merges and service connections
are external work; the supervisor has no execution path for them.

## Modes and state

Default previews evaluate supplied inputs and return a plan without creating
files, acquiring locks, starting processes, authenticating or making requests.
The command wrapper's dry-run prints the proposed child command without running it.
An explicit observe operation may refresh read-only Azure evidence and record
local status and review cards. An explicit run operation may consume independently
verified grants for existing bounded actions. A human-readable approval request
does not itself enable that action.

The explicit runtime must remain within this business identity. Execution/trust
state must be outside Git checkouts and agent worktrees, with owned, protected
ancestry. `.azure-supervisor/` contains durable controller state;
`approval-inbox/` contains request revisions, receipts and review artifacts.
Template sync, upgrades and source copying must preserve/exclude these operator
directories along with `authority/`, API throttle state and worker claims.

Cycles, items, time, child calls and attempts are bounded. Concurrent supervisors
coordinate through a fixed lock. Resume checks the same queue, policy, source,
configuration and operation identity. Two observations of the same blocker without
material new evidence stop the loop. Waiting for a human consumes no model calls.
The existing shared Azure throttling and write reconciliation rules still apply.

From the AtlasMemory-Tools source checkout, this preview uses the existing source
directory and starts no child or live operation:

```bash
python3 -B templates/local-automation-runtime/atlas-agent-azure-supervise \
  --config examples/instablinds/local-automation-runtime/config/azure-website.json \
  --runtime-dir templates/local-automation-runtime \
  --policy examples/instablinds/local-automation-runtime/config/azure-website-routing.json \
  --queue examples/instablinds/local-automation-runtime/supervisor-queue.example.json
```

Select a real definition and an existing protected state directory before adding
`--observe`. That mode refreshes Azure and records local evidence without model
calls or server writes. `--run` is a separate operation and still needs every
child's exact signed grant. `--max-cycles`, `--max-items` and `--max-seconds` may
only reduce the queue's explicit limits. The wrapper exposes the same modes as
`azure-supervise`; its global `--dry-run` does not launch the child.

Time enforcement checks admission and deadlines between operations. Each child
retains its own bounded transport timeout; a synchronous operation can finish
after the outer time limit. The controller does not detach it or claim a hard
process deadline. Worker admission includes the full possible role/repair and
acceptance sequence; a short observation budget cannot admit that worker.

## Review inbox and trusted issuer

The review inbox makes the decision concrete: who owns it, what action is
requested, the issue/revision and candidate/artifact, what evidence supports it,
and the exact operation bindings. Incidental timestamps do not create another
decision card. A changed material decision or exact binding is recorded as a new
request revision; old receipts cannot silently approve the replacement.

The local review interface and CLI confirmation are presentation mechanisms.
Authentication and consent belong to the enrolled approval issuer. A protected
`authority/issuer.json` profile identifies the operator-configured adapter. The
supervisor may create requests and consume verified responses; it never invokes
the signer. A separate explicit operator action submits a reviewed decision.
The adapter must perform real issuer authentication/consent outside model control
and return only the bounded signed public envelope expected by the runtime.

No runtime command creates private signing keys, reads key material or imports
trust automatically. Issuer enrollment, installation and channel configuration
remain explicit setup operations. Missing issuer configuration is reported as a
setup requirement. Operators should use the supported review/export/import flow;
they should not have to hand-author approval JSON or copy credential values.

Each prepared card includes text and safe static HTML plus exact operator command
arguments. `atlas-agent-azure-approval --request-id <id>` reads that stored card;
its default is an inert preview. The explicit operations are:

- `--export`: write an unsigned exact signing request to the local inbox.
- `--import-response <file>`: verify and retain the issuer's signed response.
- `--operator-issue`: invoke the enrolled adapter and verify its returned response.
- `--reopen`: explicitly advance the review revision after a verified response,
  allowing renewed or changed human decisions while retaining history.

These operations also require the explicit `--config` and `--runtime-dir` used
for the card. Human responses use `--decision accepted|rejected|feedback` and
plain `--response-text` or `--response-file`; binding JSON is generated by code.
Only accepted operation grants authorize execution. Rejections and feedback
remain authenticated decisions, never executable substitutes. Interrupted issuer
attempts require response reconciliation before another attempt. The disabled
[issuer example](../templates/local-automation-runtime/config/issuer.example.json)
documents the pinned executable and bounded stdio protocol; copying it is not
issuer enrollment.

The current exact-grant contract is retained. Refreshing current bindings does
not authorize an automatic replacement signature. Request deduplication reduces
duplicate decisions without weakening expiry, revocation or exact scope checks.

## Intake refresh

A definition supplies bounded scope, acceptance commands and declared source
evidence. Current revisions, native dependencies and source hashes come from
inspection. Missing task information produces a real-item draft with explicit
questions; the runtime does not invent a validation command to make it runnable.
Human answers enter hashed primary evidence and are separately authenticated.

Unchanged, still-fresh evidence may reuse an intake. Source changes, changed
native revision, stale evidence or changed human answers require a new exact
intake and corresponding grants. The unapproved synthetic Website examples stay
blocked. A live read must establish the current dependency graph; the historical
53-link receipt does not authorize the other 18 prerequisites.

Azure may return project GUIDs in native work-item URLs even when configuration
uses the project name. Inspection and reconciliation verify that alias against
the item's own canonical URL, ID and `System.TeamProject`, reject inconsistent
aliases, and retain the configured namespaced issue ID. The bounded native graph
read covers both dependency directions and rejects unresolved or nonreciprocal
links. See Microsoft's [work-item REST contract](https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/work-items/get-work-items-batch?view=azure-devops-rest-7.1),
which accepts a project ID or name. A parser failure is incomplete evidence; it
must never turn existing links into an executable missing-link proposal.

## Website read-only pilot

The September 9 observation uses the existing source checkout and protected local
evidence directory, with one selected item, one cycle and no queued write actions.
It prepares a real intake for `azdo:Instablinds:Instablinds:21`; missing ownership,
scope or acceptance stays visible as a draft. Read the
[validation and pilot receipt](azure-supervisor-validation-2026-09-09.md) before
using this evidence to prepare a later authorized canary.

To refresh the same read-only pilot from the AtlasMemory-Tools checkout:

```bash
python3 -B templates/local-automation-runtime/atlas-agent-azure-supervise \
  --config examples/instablinds/local-automation-runtime/config/azure-website.json \
  --runtime-dir /home/instablinds-admin/.local/state/atlas-azure-pilot-20260909 \
  --policy examples/instablinds/local-automation-runtime/config/azure-website-routing.json \
  --queue /home/instablinds-admin/.local/state/atlas-azure-pilot-20260909/queue.json \
  --observe --max-cycles 1 --max-items 1 --max-seconds 300
```

This command refreshes Board evidence and local intake/proposal state. Repository
branch and pipeline evidence has its own observation time and must also be fresh
before any worker qualification. The observed Azure repository has `main` and
no `develop` ref, while the current policy and runtime configuration specify
`develop`. Selecting a different base or establishing the intended integration
branch requires a reviewed source-authority decision; the supervisor does not
change that configuration or create a protected branch to clear the blocker.

## Qualification and rollout

The first operational pilot is one read-only cycle and one real intake, with
concurrency one and no model or external write capability. It establishes actual
readback and truthful blockers. It does not establish worker sandbox/model
availability, human issuer enrollment, published PRs or release acceptance.

Offline evaluation must cover a positive authorized child-result path as well as
stale inputs, forged authority, human waiting, duplicate requests, concurrency,
uncertain effects and exit-zero false completion. Qualify a real one-item worker
through validation, review and durable result ingestion before any unattended or
multi-hour promotion. Keep the four original Astra/max settings visible; selected
routing policies continue to report every effective model and reasoning setting.
