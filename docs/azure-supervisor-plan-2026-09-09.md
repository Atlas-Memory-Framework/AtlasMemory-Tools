# Azure supervisor and operational handoffs

Status: Local implementation and live read-only pilot complete
Lifecycle: legacy-plan
BlockingDecision: none
UnresolvedBlockers: 0
PlanningReviewsComplete: yes; four implementation owners cross-reviewed the final slices

## Authorization and decisions

DR-001: The user approved fixing the operational gap and proceeding with the
previously proposed next steps. Scope is local implementation in AtlasMemory-Tools,
then a live read-only Website Azure inspection and one real intake. Preserve
all existing user work and the Website's Azure-only delivery authority. The
user still owns the immediate staging blocker. This approval does not supply
exact grants for model assessment, worker execution, publication or Board writes.
Merges, protected pushes, deployments, permissions and service connections stay
excluded. No service, scheduled job or unattended process is installed or enabled.

DR-002: The outer supervisor is deterministic. It refreshes evidence, classifies
blockers, prepares concrete decisions, consumes verified responses, budgets and
invokes existing bounded operations only when their exact grants exist. It must
never manufacture task commands, acceptance evidence, approvals or completion.
Missing prerequisites may be scheduled only if separately present and authorized
in the explicit queue; a dependency link does not prove completed work.

DR-003: Add a local review inbox with safe readable decision artifacts, exact
binding export and verified receipt import. Integrate a protected operator-
configured issuer adapter without reading, creating or persisting private keys
or credentials. The adapter must enforce real issuer identity/consent externally;
a local button, string, CLI confirmation or model message is not authentication.
An existing approval service may be selected if the user identifies one. Without
enrollment, requests remain actionable but unsigned and execution stays blocked.
No messages are sent to other people or external channels during this task.

DR-004: Default previews remain entirely inert. Explicit observe mode permits
read-only Azure operations and bounded local status/inbox evidence. Explicit run
mode may consume separately supplied operation grants; normal workspace-write
sandboxing, approvals and the previously tested action guards remain mandatory.
Keep model/reasoning settings and GitHub support unchanged.

DR-005: Preserve material identity across refreshes. Reuse unchanged still-fresh
intakes, avoid duplicate pending approval cards, and record request revisions
when current exact bindings change. Never replay an old grant against changed
bindings merely to avoid another approval. Repeated unchanged blockers stop
after two observations; uncertain writes/claims are reconciled before retries.

## Loop and evaluation contract

Implementation baseline: 349 source files, HEAD
`0a571a5b94dfa6ea53a7ea032b4d300b5002f8bf`, 702 runtime tests.
Queue: explicit bounded Azure item/intake definitions and native dependencies.
Repository: https://dev.azure.com/Instablinds/Instablinds/_git/Website.
Live pilot: max one cycle, one selected intake, concurrency one, no model calls,
no server mutation; full bounded dependency read closure remains necessary.
Offline trials: synthetic transports and issuers, bounded cycles/items/time,
with independent outcome and operator-burden assertions. Progress means fresh
material evidence, a verified handoff, or accepted child evidence; refreshing a
timestamp or returning exit zero does not count. Stop on missing authority,
incomplete/stale evidence, human decision, conflicts, exhausted budgets, uncertain
effects or two unchanged blocker observations. No unattended promotion follows
from offline tests or a successful read-only pilot.

## Workstreams and ownership

| Stream | Owner | Files/responsibility |
| --- | --- | --- |
| SUP | routing_policy | atlas_supervisor.py, atlas-agent-azure-supervise, supervisor tests; bounded durable controller and resume |
| APPROVAL | routing_authority | atlas_approval.py, atlas-agent-azure-approval, approval tests/example issuer profile; review/export/import/protected issuer integration |
| INTAKE | routing_dispatcher | atlas_intake.py, atlas-agent-azure-intake, intake tests; fresh evidence assembly and material identity without fabricating scope |
| CONFIG/EVAL | routing_enforcement | scripts/runtime_control.py, wrapper tests, supervisor queue examples and independent evaluation tests; explicit modes and boundaries |
| Integrate | root | plan/operating docs, README/SETUP, static/copy guards, interface decisions, reviewed delivery and live pilot |

Four agents at most, sharing /tmp/atlas-supervisor-20260909; preserve partner
edits. Owners coordinate exported helper contracts before dependent edits.
Existing runtime modules are frozen except narrowly reviewed integration fixes
assigned by root. Cross-review and full suites precede delivery and live reads.

## Interface direction

Intake assembly takes an explicit draft worker packet, declared source evidence,
fresh normalized inspection and runtime/policy configuration. Return either a
valid intake with snapshot and hashes, or a truthful draft listing missing scope,
commands, human owner or evidence. Native item revisions and graph completeness
come from inspection, never optimistic local annotations. Preserve approved
gate templates; changed revisions/answers require new bound requests.

Supervisor uses the existing Azure inspector, dispatcher, worker and reconciler;
no parallel implementation of their authority checks. Durable state and inbox
live outside agent worktrees under explicit protected runtime roots. Queue,
policy, code, source and model identities remain in resume evidence. Default
preview creates no directories, locks, subprocesses, authentication or network.

Approval requests bind repository, issue/revision, action, exact operation
bindings, owner/question/artifact and policy. Material request identity excludes
incidental creation timestamps but exact grants remain strict. Human review is
readable; accepted/rejected/feedback decisions and missing issuer readiness are
visible. Supervisor can prepare and consume requests; only the separately
configured trusted issuer can attest the authenticated approval.

## Acceptance

- Refresh/resume, incomplete/stale reads, dependency changes and fresh revisions.
- Repeated blockers, durable budgets, concurrent controllers, path conflicts,
  duplicate approval requests, changed scope/policy/code, uncertain child results.
- Real signed receipts, forged/revoked/expired/mismatched grants, unsafe issuer
  configuration and no signer/auth invocation from preview or supervisor waiting.
- Meaningful human-answer propagation and exact candidate/artifact binding.
- Complete observable fixture path from pending input through authorized child
  result ingestion; reject exit-zero false completion and external action claims.
- No hidden model selection or automated acceptance of subjective work.
- Runtime unittest discovery and scripts/verify_repo.py; no browser tests.
- Live read-only receipt and one real intake, with concrete human decisions and
  setup requirements if it remains blocked. No timestamp/authority flag edits to
  force synthetic examples green.

## Execution Status

Phase: completed local scope and read-only pilot
Status: implementation, cross-review, source delivery and read-only intake complete
Direct root edits are explicit integration responsibilities above.
848 runtime tests and 19 isolated independent outcome evaluations pass. The first full
repository run caught a placeholder convention mismatch in the disabled issuer
example; the example is corrected without weakening the test. Final gates are
recorded in [the validation receipt](azure-supervisor-validation-2026-09-09.md).
The first live read revealed project-GUID native URLs; inspection and revision-safe
reconciliation now share a verified alias parser, with bounded closure in both
directions. Repeated live observation confirms 37 items, 53 existing links and 18
missing edges. It prepares exactly those 18 additions as an unapproved proposal;
eligibility remains zero. Real intake #21 revision 4 remains a truthful draft.

The configured `develop` ref is absent; a complete read finds `main` among 73
heads. Remaining human/setup decisions are dependency approval, source authority,
task ownership and acceptance, issuer enrollment, and exact action grants. No
model, worker, publication, Board mutation, installation or release action ran.
The retained overlapping-evaluation verifier failure passed in isolation without
changing code or limits; its cause remains unverified and unattended promotion
is deferred. The immediate staging blocker remains owned by the user.
