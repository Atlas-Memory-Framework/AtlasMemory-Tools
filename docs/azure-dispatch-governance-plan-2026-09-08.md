# Azure dispatch, human handoffs, and authority implementation

Status: Approved for local implementation
Lifecycle: legacy-plan
BlockingDecision: none
UnresolvedBlockers: 0
PlanningReviewsComplete: Pass — independent implementation/security reviews

## Authority and decisions

DR-001: The user approved the complete design discussed in this session with
“This overall system update looks good. Lets document it & implement it”. This
authorizes local documentation, implementation, and tests. It overrides a
separate planning ceremony; independent review remains a build gate. It grants
no live model dispatch, installation, Azure write, publication, pipeline run,
approval, deployment, merge, permission change, or service-connection access.
The immediate staging blocker remains the user's responsibility.

DR-002: Preserve the existing Website configuration's four Astra/max settings.
Provide a separately selected, versioned routing policy: Terra/medium assessment,
Sol/high independent challenge and bounded reassessment; Luna/low clerical,
Terra/medium routine implementation with Sol/high review, and stronger bounded
profiles for sensitive or difficult work. Report every effective setting.
Points affect sizing/decomposition and budgets, never authority or risk alone.

DR-003: Human input, approval, testing, feedback and external pipeline/PR decisions
are explicit gates with owners, questions, exact artifacts/candidates and scoped
receipts. The Website forbids agent pipeline deployment/approval and PR
self-approval. Represent those steps as external/human work; never add an
execution bypass. Missing or stale evidence cannot complete work.

DR-004: A counterfactual challenger reasons independently from the primary
evidence before comparing assessments. It checks over- and under-escalation,
scope, missing evidence and human judgment. Policy enforces risk floors and
bounded resolution. Model agreement grants no authority.

DR-005: Replace trust in self-asserted local approval strings for Azure writes
and worker execution with verified signed grants from operator-configured
issuers. Trust lives at the fixed `authority/trust.json` under the explicit
runtime, outside all agent worktrees. Agents cannot bootstrap trust, issue
grants, or access signing secrets. Only public verification material is read.
Use the installed OpenSSL executable for bounded RSA/SHA-256 verification;
no Python dependency or system installation. Missing trust or verifier blocks.
No trust store or real keys are created during this implementation. Public test
fixtures and synthetic signatures carry no production authority.

DR-006: Keep the prepared model/provenance configuration immutable when a human
responds after preparation. Publication accepts separate human receipts whose
digest is part of the signed `draft_pr` grant. A deferred gate is instantiated
from its original template and the exact prepared candidate; signed bindings
retain the template hash, owner, question, action and reviewed artifact. A receipt
cannot replace the gate or apply to another candidate. Before-step answers
become hashed primary evidence in a new immutable intake while preserving the
original worker packet and gate. The new intake requires a matching assessment
grant and cannot reuse another answer's cached assessment. A separate assessment
grant permits assessment before approval of local execution.

DR-007: Waiting for a human may outlast the routing evidence freshness window.
Publication may reconstruct the already prepared route from its durable claim
and immutable configuration, packet, candidate and acceptance evidence. This is
historical preparation evidence only: publication still requires a new
currently valid exact grant, the current enrolled policy, fresh native Board
and dependency reads, and unchanged source/candidate evidence. Historical route
validation cannot authorize new worker execution or bypass freshness there.

## Contract and interfaces

Shared canonical hash: SHA-256 of UTF-8 JSON with sorted keys, compact
separators and `ensure_ascii=False`, rejecting nonfinite values and duplicate
JSON keys at input.

`atlas_authority.py` owns `AuthorityError`, `canonical_digest(value)`, and
`verify_grant(runtime_dir, envelope, action, bindings, *, now=None) -> dict`.
The envelope contains a signed payload and signature plus issuer identity.
Verification enforces authenticated issuer, permitted action, exact typed
bindings, time validity, revocation, runtime and policy scope. No fallback to a
nonempty approval string or caller-supplied trust registry is allowed.

`atlas_routing.py` owns policy/intake/assessment validation and pure
`decide_route(intake, policy, assessment=None, challenge=None, *, now=None)`.
Intake includes the immutable bounded worker packet, primary evidence with
hashes, current readiness, point estimate if present, step kind, human gates,
attempt history and budget. Output binds intake/policy/revision/evidence and
model settings, gives reasons and pending gates, and never asserts authority.
Missing assessment/challenge, stale inputs, unsupported operation, missing
dependencies, unresolved technical disagreement or human gates produce explicit
non-runnable states. Deterministic operations select no model. One bounded
reassessment/escalation is permitted by policy; retries are not unlimited.

`atlas_human_gates.py` owns candidate-bound gate/receipt evaluation; authenticated
receipts use the authority verifier. Required input before a step blocks it;
later visual acceptance must not prevent already authorized preparation.
Receipt replay across candidates, revisions, artifacts or gates is rejected.

`atlas_dispatch.py` plus `atlas-agent-azure-dispatch` own bounded context
collection, CLI orchestration, durable routing/assessment receipts and inert
previews. Default preview reads supplied inputs and emits JSON without state,
authentication, network, subprocess, installation or execution. Explicit
assessment requires a signed `assess` grant and normal sandbox/approvals. It
uses isolated scratch context and fixed role argv; no issue-supplied commands.
Repeated unchanged work reuses bound evidence; concurrent claims and exhausted
budgets block duplicate calls. Actual worker dispatch remains separately
authorized for the resolved exact configuration and packet.

Interfaces may be refined during integration without widening authority. Record
material refinements here and in operating documentation.

## Workstreams and ownership

| Stream | Owner | Files and responsibility |
| --- | --- | --- |
| AUTH | authority agent | `atlas_authority.py`, authority tests/public fixtures; strict verification contract |
| ROUTE | routing agent | `atlas_routing.py`, `atlas_human_gates.py`, their tests, neutral policy example and Website policy/intake examples |
| ENFORCE | enforcement agent | `atlas_azure_worker.py`, `atlas_azure_reconcile.py`, their tests; enforce signed grants in direct APIs/CLIs and bind routed models |
| DISPATCH | dispatcher agent | `atlas_dispatch.py`, dispatcher entrypoint/tests, `atlas_runtime_config.py`, `scripts/runtime_control.py`, wrapper/config tests |
| Integrate | root | Plan, operating docs, README/SETUP/static verification, interface reconciliation and delivery |

Agents share the staging checkout and must preserve each other's edits. At most
four implementation agents run concurrently. Independent cross-review follows
implementation before local delivery. Root owns shared-file integration only.

## Validation and acceptance

- Routing: points versus risk, sensitive paths, absent/stale/incomplete evidence,
  unknown fields and type confusion, independent challenge, disagreement,
  explicit budgets, repeated failures, model/config drift and no fallback.
- Authority: forged/altered/expired/revoked grants, unknown issuer, scope and
  exact action mismatch, changed packet/config/candidate/policy, unsafe trust
  paths, direct worker/reconciler bypass and missing verifier.
- Handoffs: owner and question required, per-step gates, signed decisions,
  rejected/stale/replayed feedback, no inferred human acceptance/completion.
- Execution: inert previews (including no bytecode), bounded model argv and
  sandbox, concurrent claims, cached evidence identity, failure classification,
  deterministic operations with zero model calls and forbidden live actions.
- Regression: runtime unittest discovery and `python3 -B scripts/verify_repo.py`.
  No browser suite, live model canary or external mutation is authorized.
- Document operating commands, trust provisioning boundary, migration from
  plain approvals, policy selection, rollback, and unqualified live behavior.

## Execution Status

Phase: local implementation and delivery
Status: complete

Workstreams: AUTH, ROUTE, ENFORCE and DISPATCH complete and independently
cross-reviewed. The ownership table above is the delegation matrix; all four
owners have frozen their files. No unresolved implementation blocker remains.

Completed tasks: deterministic model routing; independent challenge; verified
authority; direct worker/reconciler enforcement; human input and publication
resume; shared durable budgets; inert CLI/wrapper previews; blocked Website
examples; operating documentation and migration/rollback boundaries.

Build gates: 702 runtime tests passed (baseline 507); `scripts/verify_repo.py`
passed with 109 repository tests, 55 plan-to-issues checks, the full runtime
suite, static/copy/harness and whitespace checks. Offline routing/inspection
pilots returned no effects and remained blocked. See the
[validation receipt](azure-dispatch-governance-validation-2026-09-08.md).

Sub-agent usage: four implementation owners in one parallel batch, followed by
independent cross-review and integration validation. Direct root edits are the
explicit integration responsibility: plan/docs, source-copy/upgrade exclusions,
static verification inventory, and authorization timing after REST throttle waits.
The copy and write-timing regressions failed before their corresponding guards;
independent mutation checks confirmed those tests detect guard removal.

Delivery: 37 reviewed source, test and documentation files applied to the
requested AtlasMemory-Tools checkout with exact before/after hash checks.
Unrelated baseline files and HEAD were preserved. Target checkout verification
also passed all 702 runtime tests, `scripts/verify_repo.py`, and both inert
pilots. No required local implementation work remains.

Next action: the documented read-only pilot. Installation, issuer enrollment,
live canaries and external operations remain separately authorized work.

Rollback: revert only this update's reviewed source deltas; preserve prior Azure
implementation and all operator state. Installation remains separately approved.
