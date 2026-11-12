# Feature: Full workflow-harness MCP coverage

## Plan State
PlanFormatVersion: 2
PlanId: full-workflow-harness-mcp
PlanGroup: none
PlanKind: roadmap
ParentPlan: none
DependsOnPlans: none
BlocksPlans: none
AtomicScope: Daily-first MCP implementation and acceptance contract; all-lane coverage roadmap with later stages tracking-only
CampaignMetadataAuthority: descriptive-only; explicit @path authoring artifact selection wins
Status: Draft
StructuralStatus: Draft
SubstanceStatus: NeedsWork
ProjectionApproval: NotRequested
DispatchApproval: Blocked
CurrentStage: Implementation
PlanTier: Full
AutomationTarget: none
DeliveryMode: DevOnly
ContextMode: RepoInferred
LastUpdated: 2026-11-10
PrimaryOwner: user (scope acceptance); plan orchestrator (authoring)
BaseBranch: current checkout; no branch mutation authorized by this planning invocation
BaseCommit: 6edb37cdcabf2af2dfcf9626916aad9b1de27acf
TargetBranch: none selected
Related: docs/harness-interface.md; docs/daily-development.md
NextRequiredUserAction: Review repairs; fresh independent review/readback precede any authorization request
BlockingDecision: DR-006 (complex-work admission route)
UnresolvedBlockers: 5
RubberStampSignals: 0
LastGateRun: 2026-11-10
ArtifactAuthorityMode: legacy-plan
HarnessAdmissionReadiness: Blocked
RuntimeSelection: NoneSelected
ImplementationAuthorization: WithheldByUser
AdmittedWorkItems: 0 (none created by this planning session; no external queue inspection inferred)
EstimatedStoryPoints: 68
EstimateStatus: ProvisionalDeliveryOnly

## Gate Results
IntentModelComplete: Pass
ProblemDefinitionComplete: Pass
FeatureClarity: Pass
TechnicalClarity: Pass
HumanReadabilityReview: Fail
PlanReadiness: Fail
AutomationReadiness: N/A
PlanningReviewsComplete: Fail

## Decision Log

### DR-001: Coverage scope
- Stage: Problem
- Date: 2026-11-10
- ScopeAffected: MCP catalog, shared services, runtime adapters and upgrade requirements.
- Decision: B accepted by user: all maintained lanes, delivered in stages, supervised daily workflow first; existing authority checks remain in place.
- Options considered:
  - A) Daily lifecycle only.
  - B) All maintained lanes in stages, daily lifecycle first.
  - C) Add autonomous execution powers.
- Why chosen: User selected the recommended staged scope on 2026-11-10.
- Consequences / follow-ups: Inventory and technical decomposition depend on the selected boundary.
- Status: Accepted
- Revisit trigger: none.

### DR-002: Lost preparation response and recovery
- Stage: Technical
- Date: 2026-11-10
- ScopeAffected: Daily reservation/replay, MCP reconnect, adapter timeout and runtime cutover.
- Decision: Preserve the authoritative reservation; inspect the same work item and recover the same invocation instead of dispatching replacement work.
- Options considered:
  - A) Recover the existing reservation and known invocation.
  - B) Treat connection loss as failure and dispatch a replacement.
  - C) Reset ownership automatically after a timeout.
- Why chosen: User accepted the stated recovery behavior on 2026-11-10. B and C risk duplicate execution and lost custody.
- Consequences / follow-ups: Preparation reexport and import replay must survive reconnect. A reservation alone does not prove host dispatch occurred; inspect host records before concluding it did. Uncertain invocation remains fenced.
- Status: Accepted
- Revisit trigger: none.

### DR-003: Clarify native semantics and safe evidence access
- Stage: Technical
- Date: 2026-11-10
- ScopeAffected: Daily tool annotations, bridge protocol, snapshot cursors, selection admission, evidence paths and historical reservation availability.
- Decision: Apply bounded reviewer corrections preserving DR-001/DR-002: prepare is not globally idempotent; wire inputs carry exact base64 bytes with strict limits; paging hashes the exact parsed snapshot; selection freezes at admission; reservation view is pending-only; evidence traversal uses descriptor-relative no-follow opens and explicit refusal tests.
- Why chosen: Concrete API/data-integrity and security reviews exposed implementation ambiguities. These clarify existing chosen boundaries and do not grant new authority or change permitted data handling.
- Consequences / follow-ups: G-DAILY and G-INTEGRATION explicitly test these cases; refresh affected reviews after edits. Also require unambiguous artifact IDs for historical evidence views and uncertain-add reconciliation by observed intake projection; no original-intake-byte retention claim is invented. Resolve zero-context/implementer phase-order findings: Phase 2 proves isolated bridges, actual MCP alternation waits for Phase 3; G-GOAL source acceptance requires actual qualified queue/host custody, distinct from offline source checks. Free-text task evidence remains untrusted and not guaranteed secret-free.
- Status: Accepted
- Acceptance authority: Orchestrator auto-remediation of implementation/clarity findings under planning-reviews; no new user policy choice.
- Revisit trigger: any correction would require changing authority or data-handling boundaries.

### DR-004: First-stage completion and rollout readback
- Stage: Implementation
- Date: 2026-11-10
- ScopeAffected: MP5 source acceptance, MP6 installed qualification, G-LIVE and runtime cutover.
- Decision: Offline source checks and live workflow acceptance remain separate. The first daily milestone remains incomplete until an actual supervised item passes independent goal review. Recover pending work with its original runtime before selecting the upgrade; unreadable configuration blocks live qualification but not source development.
- Why chosen: User explicitly selected both recommended implementation readback answers on 2026-11-10.
- Consequences / follow-ups: Do not claim daily milestone complete from fixtures, source checks or imported role results. Source development does not waive actual role-admission or G-GOAL prerequisites. Preserve original custody/runtime and actual host evidence. No build, dispatch, upgrade, publication or merge authorization follows.
- Status: Accepted
- Revisit trigger: none.

### DR-005: Repair admission preparation and estimates
- Stage: Implementation
- Date: 2026-11-10
- Decision: Repair supported execution-preparation defects while retaining scope and authority. WS1–WS6 are ownership containers, not admitted assignments. D01–D12 describe delivery; complex work remains coding-blocked until an honest qualifying route exists. Replace the informal forty-point approximation with the independently proposed package estimates, arithmetically verified at 68 points, excluding D12 and admission/setup/decomposition overhead.
- Evidence: Current atlas_local_sizing.py requires at most4 files,3 criteria and1 changed interface for coding/validation; generic v2 model review does not waive complexity flags. atlas_local_dev.validate_task requires one independent goal gate. Source planning-design-doc has no such gate.
- Disposition authority: Author repairs of source-backed preparation gaps; no implementation, route qualification, budget approval or admission-policy change accepted.
- User correction: No runtime selection exists (explicit user answer); an absent default file is not a broken selected installation.
- Consequences: Current reviews/readbacks are stale after these material repairs. Existing accepted intent/scope/recovery decisions remain historical authority; new readback must cover admission boundaries.
- Status: Accepted

### DR-006: Complex-work admission route remains unresolved
- Stage: Implementation
- Date: 2026-11-10
- Decision: No route chosen or qualified for D03–D11. Do not clear genuine flags or reuse unrelated frozen supervisor packet IDs/hashes.
- Options considered:
  - A) Decompose and independently size children; admit only children the current policy truthfully qualifies. Any remaining flagged integration stays blocked.
  - B) Propose a bounded admission-policy/template extension with independent review and separate explicit user acceptance before changing the execution lane.
  - C) Keep complex implementation on hold while only genuinely qualified routine leaves proceed after authorization.
- Recommended next step: Source-backed admission design/discovery before proposing A/B; no coding route is assumed. A stronger model or completed contract alone does not authorize clearing a flag.
- Status: Revisit
- Owner: plan owner prepares evidence; user retains consequential policy/route acceptance.
- Revisit trigger: Fresh independent review identifies exact child contexts and a qualifying existing route, or a separately reviewed policy proposal is ready for user judgment.

### DR-007: Repair adapter settlement and inventory acceptance sequencing
- Stage: Technical / Implementation
- Date: 2026-11-10
- Decision: Apply F-401/F-402 as bounded contract repairs. Add caller-known adapter call identity, local transport receipts and an inherited lifetime lock for restart-safe settlement observation. Give D01 a data-only gate independent of D02; require full G-COVERAGE at D02 and MP1.
- Evidence: Reviewed artifact sha256:5f301965a939f81074d8dbff08f5484ece1408ed5f63fc8647c9f30a4b950e7b required adapter termination without exposing its observation; D01 required the checker assigned to its dependent D02.
- Disposition authority: Requested plan repair; technical corrections preserve DR-001/DR-002 and existing local evidence boundaries. No new lifecycle authority, scheduler, provider route, paid work or execution authorization.
- Consequences: D05/D06/D08/D09 contracts and their later exact-context sizing must include transport settlement. Existing 68-point delivery estimate remains provisional and does not size this added detail. Fresh independent review/readback must cover both repairs; no prior pass is refreshed by authorship.
- Status: Accepted (author repair; independent acceptance pending)
- Revisit trigger: A proposed implementation needs another authority, filesystem trust boundary or admission-policy change.

## Risks / Assumptions / Tests

- R1 (High): Daily prepare is mislabeled read-only because provider prepare is inert.
  - Mitigation: Separate operation contracts, mutation annotations and tests for persisted claims/reservations.
  - Owner: future API-contract reviewer.
  - Status: Untested
- R2 (High): Import reconstructs worker evidence or accepts caller-fabricated host identity as proof.
  - Mitigation: Preserve original bytes and existing receipt checks; disclose receipt authenticity limits.
  - Owner: future integrity reviewer.
  - Status: Untested
- R3 (High): Upgrade changes runtime while a reservation is pending.
  - Mitigation: Keep original snapshot and recover before cutover; exercise restart/replay across versions.
  - Owner: future upgrade reviewer.
  - Status: Untested
- A1: Full usage primarily means access to maintained capabilities rather than new execution authority.
  - Test: User selection of DR-001.
  - Pass/Fail criteria: B or A confirms existing-authority scope; C requires reframing.
  - Status: Accepted

## Intent Model

Latent target:
- Enable agents to use the workflow harness through MCP throughout a work item's lifecycle, with evidence and diagnostics explaining what happened and what comes next.
- Likely motivation: essential workflow operations still require CLI fallback.
- Non-verbal / experiential target: agents can stay within the workflow without the operator reconstructing missing steps.
- Confidence: High for scope; detailed operation inventory remains source investigation.

Anti-targets:
- A transport change or larger tool catalog that leaves essential workflow steps inaccessible.
- MCP-specific state or rules diverging from maintained runtime APIs.
- Treating imported results or process exit as independent goal acceptance.
- Inferring autonomous execution, installation, publication or merge authority from coverage.

Expression-state notes:
- User phrase: “extend the MCP capabilities to cover full usage of the workflow harness.”
  - Interpreted meaning: typed access to supported lifecycle operations, observations and recovery.
  - Alternate plausible interpretations: daily lane only; all maintained lanes; new autonomous execution.
  - Confidence: Medium.
  - Risk if wrong: underbuild coverage or introduce unrequested powers.

Open Loop Ledger:
- OL-001:
  - Type: scope-gap
  - Source: User phrase “full usage”.
  - Latent object: Required lanes and execution boundaries.
  - Why it matters: Determines coverage, sequence, integration evidence and authority requirements.
  - Candidate interpretations:
    - A) Daily lifecycle only.
    - B) All maintained lanes in stages, beginning with daily lifecycle.
    - C) Additional autonomous execution powers.
  - Status: Resolved
  - Resolution evidence: User selected all maintained lanes, delivered in stages; DR-001.
  - Blocks: none

Intent checksum:
- Success means: agents complete selected supported workflows through MCP while preserving identity, runtime selection, original evidence, independent acceptance and authority checks.
- Failure would look like: essential CLI fallback, silent lane switching, or a lifecycle bypass concealed by successful tool calls.
- User confirmation needed: none for scope or technical recovery; DR-001 and DR-002 record accepted boundaries.

## Problem Definition

Problem narrative:
The MCP interface exposes provider-run discovery, inspection, preparation, start, observation, cancellation and remote configuration. Supervised daily work separately requires CLI operations for intake, role reservation, result import and status. An agent cannot currently use MCP alone to carry a supervised work item from intake through independent acceptance.

The desired workflow gives agents typed MCP access to the supported operations of each selected harness lane, including evidence, blockers and recovery guidance. This matters now because broader MCP usage otherwise leaves agents dependent on shell commands and interpretation of separate interfaces.

Current broken workflow:
- Provider cycles use MCP while supervised daily work uses a separately selected runtime and CLI.
- Existing MCP registration does not select the daily installation or enable its execution.
- Import completion does not establish independent goal acceptance.

Desired workflow:
- Explicitly select a lane and runtime, perform supported lifecycle actions through MCP, and inspect acceptance and next actions.
- MCP and CLI share maintained lifecycle APIs and ownership, source, receipt, readiness and replay checks.
- Unsupported actions return concrete blockers rather than switching lanes or granting powers.

Why this matters / why now:
- The user requests full workflow-harness access; the daily lifecycle is a verified coverage gap.
- Vision → outcome → capability → contribution: usable harness through MCP → complete selected workflows → typed lifecycle access → first inventory and bounded daily-lifecycle slice. Broader coverage and live usefulness remain unproven.

Current-state facts:
- `scripts/harness_mcp.py` exposes nine tools; named operations include GitHub cycles and Azure operations. (source: file)
- `docs/harness-interface.md:37` separates daily selection from MCP registration; `harness_start` does not execute that lane. (source: file)
- `templates/local-automation-runtime/atlas_local_dev.py` implements add, status, prepare and import against the selected runtime modules. (source: file)
- `docs/daily-development.md` requires original worker bytes, observed host receipt and independent goal review. (source: file)
- `python3 -B scripts/atlas_daily.py status` exited 2: selected config or provenance file unreadable. This does not prove no installation exists. (source: command)

Success criteria (measurable):
- SC1: Every maintained operation in selected lanes maps to a typed MCP action or an explicit, user-accepted exclusion. No unclassified operations remain.
- SC2: One supervised item completes intake, role preparation, authentic host execution, import, independent reviews and acceptance inspection with no CLI fallback for harness operations. The host remains responsible for actual execution.
- SC3: Restart/reconnect, exact replay, stale/foreign reservation refusal, original-byte retention and uncertain-invocation blocking are demonstrated through MCP integration tests.
- SC4: Responses distinguish process termination, accepted import and independently accepted goal.
- SC5: An explicitly selected runtime upgrades without losing local state or changing outstanding handoff bindings; rollback preserves new evidence and permits recovery with the original snapshot.

Constraints:
- Preserve selection, ownership, source pins, sizing, route qualification, budgets, independent review and existing authority.
- Keep coordination and evidence local. Do not execute live jobs from templates.
- This invocation plans; it does not install runtimes, launch work, build, publish or merge.
- Recover pending handoffs with their original runtime before version changes.
- Fixtures and source inspection do not qualify a live host or prove model usefulness.

Scope:
- In scope: coverage inventory, typed lifecycle/diagnostic contracts, shared API behavior, evidence, recovery and upgrade compatibility.
- Out of scope: Atlas product capability claims, replacement scheduler, arbitrary command tools, implicit installation selection, new autonomy or merge authority.

Definitions / glossary:
- Lane: maintained workflow with its own selection, execution and authority rules.
- Full coverage: all agreed supported operations, including failures and recovery.
- Acceptance: independent goal judgment, separate from result import.

Open questions:
- Q1: Which lanes and execution boundaries define full usage?
  - Owner: user
  - Status: Resolved (DR-001)
  - Blocks: none

Decision boundaries (if any):
- DR-001:
  - A) Daily lifecycle only.
  - B) All maintained lanes in stages, daily lifecycle first.
  - C) Include new autonomous execution powers.
Recommended default: B; preserve the broader goal while bounding the first delivery. C requires separate requirements and authority.

## Context Snapshot

### Inputs Provided
- User invoked runtime-upgrade and plan skills for full workflow-harness MCP coverage.
- Source HEAD: `6edb37cdcabf2af2dfcf9626916aad9b1de27acf`.
- Existing dirty files preserved: canonical/generated local-automation-runtime-operate skills; untracked database-backed-agent-workspaces plan.

### Repair reconciliation (2026-11-10)
- Before snapshot outside repository: /tmp/atlas-mcp-plan-repair-wb8d3_1j/before.plan.md; prior reviewed plan hash: sha256:fc89e2dafd14c8b7a87c83531c76a15b476882fe6ae7d6a8e0f941aa84f3be5c.
| Finding / input | Validity and affected contract | Disposition / reason |
| --- | --- | --- |
| Re-entry F-301; prior assistant dispatch prerequisites | Valid: workstreams lack exact bounded/admitted packets | Accept → DR-005; delivery package map and packet assembly contract below; no fabricated intake/receipt |
| Re-entry F-302 | Valid: zero-blocker/readiness metadata obscured actual admission blockers | Accept → DR-005; explicit five blockers, current admission Blocked and stale readiness/reviews |
| Repair R-003: source qualifier limits | Valid: v2 review does not waive four-file/three-criterion/one-interface or complexity rules | Accept → DR-005/DR-006; complex packages coding-blocked, not renamed routine |
| Repair R-004: point estimate | Valid: about 40 was an unsupported approximation, not formal sizing | Accept → DR-005; package estimate 68; proposal's claimed total 73 rejected as arithmetic error (listed terms sum 68) |
| Repair R-005: runtime bootstrap | Valid: governing execution runtime differs from future bridge-enabled target | Accept → DR-005; use original selected CLI governance; never require unbuilt MCP bridge to govern its own implementation |
| Repair R-006: proposed budget versus actual authority | Valid: no reviewed per-item budget or route receipt exists | Accept → DR-005; proposals separated from admission evidence and user authorization |
| User: none selected | Confirmed fact, not absent-installation proof | Record NoneSelected; do not guess a runtime, owner or state path |
- Fresh zero-context re-entry audit answered what/why/repo/first change/must-not/validation/blockers before repair. It was a before-repair audit, not a fresh approval of repaired text.

### F-401/F-402 repair reconciliation (2026-11-10)
- Review input: preceding expert-technical review in this conversation, reviewed semantic hash sha256:5f301965a939f81074d8dbff08f5484ece1408ed5f63fc8647c9f30a4b950e7b.
- Before snapshot: /tmp/atlas-mcp-plan-repair-f401-f402-208uvmmc/before.plan.md; raw file SHA256:58a8084c34251f92b5554f4316789851b23a78a40d8b749babab1616eb6d833f.
| Finding | Validity / affected contract | Disposition / reason |
| --- | --- | --- |
| F-401: no restart-safe adapter termination observation | Valid: schemas, common envelope, lost-add recovery and subprocess lifecycle lacked a caller-known correlation key and settlement evidence | Fix under DR-007: adapter_call_id, private transport metadata, inherited lifetime lock and read-only status observation; no invented host invocation or queue transition |
| F-402: D01 needs its dependent D02 checker | Valid: first bounded packet required G-COVERAGE before its checker/test files exist | Fix under DR-007: executable G-COVERAGE-DATA for D01; D02 depends on accepted D01 and supplies full G-COVERAGE; MP1 still requires both |
- Gate development exposed four observed-only inventory rows absent from BaseCommit. G-COVERAGE-DATA preserves their metadata under observed_only_paths, verifies committed bytes only for Git-tracked rows and never reads/copies their local contents. The immutable original inventory remains unchanged.
- No finding rejected or deferred. Existing five admission blockers remain; these author corrections are not independently accepted findings closures or fresh review passes.

### System Understanding
| Capability | Current MCP coverage | Proposed discovery target |
| --- | --- | --- |
| Registration, discovery, inspection | Existing | Lane identity, selection diagnostics, freshness and pagination completeness |
| GitHub/Azure operations | Existing bounded lifecycle | Audit supported native actions versus exposed operations |
| Daily intake and status | Missing typed daily tools | Validated add and complete work-item status |
| Daily role preparation | Missing | Mutating claim/reservation with exact replay; distinct from inert provider preparation |
| Host execution | Separate supported host | Preserve packet/route and actual invocation receipt; no invented dispatcher |
| Result import and goal acceptance | Missing typed daily tools | Original-byte import, refused attempts, independent acceptance evidence |
| Recovery and upgrade | Partial observation; broader parity unverified | Inventory maintained APIs; explicit blockers where no supported action exists |

This table is an initial source-based map, not a complete operation inventory or final tool schema.

### Maintained lane families and staged discovery
| Family | Native source entrypoints | Required inventory emphasis |
| --- | --- | --- |
| Daily supervised lifecycle (first delivery) | atlas_local_dev.py; atlas_supervised_handoff.py; scripts/atlas_daily.py | add/status/prepare/import, selected runtime, authentic results, all review roles |
| Local work-item/team workflows | atlas-agent-work-item-add/inspect/rework/requeue-stale; atlas_workflows.py; workflow-select/template-add/lint; role-runner | Explicit recovery transitions, template validation, role execution qualification |
| GitHub issue-to-PR | plan-queue, issue-decompose, triage, orchestrator, worker, review, semantic-review, local/deployed-validate, finalize, project-sync/reconcile, dependency-promote, pr-repair | Aggregate github-cycle is not proof of operation parity; classify cloud effects |
| GitHub Actions | atlas-agent-workflow run/list/watch/view/download | Distinct from team workflows; ref identity, bounded observation and artifact output |
| Azure governed lifecycle | azure-intake/approval/dispatch/worker/supervise/inspect/reconcile and atlas_* modules | Signed grants, native approval, partial existing MCP coverage |
| Operator recovery/controls | admin, throttle-status, pause, cleanup, notify, cycle-summary | Actual side effects, evidence retention, uncertainty and repair authority |
| Installation/configuration/upgrade | setup_harness_interface.py; harness_remotes.py; runtime_control.py; verify_harness.py; setup/check/build scripts | Explicit preview/apply, backups, state preservation and version compatibility |

These are source families, not an exhaustive subcommand ledger or installed capability claim. `scripts/runtime_control.py` already provides named operations for status/configuration, model reporting, sync, plan-preview/queue, cycles, review/finalize and Azure lifecycle; reuse its maintained selection and effect checks rather than inventing a parallel control plane.

### Source inventory evidence
- Supporting ledger: [source-inventory.md](support/full-workflow-harness-mcp/source-inventory.md) and [source-inventory.json](support/full-workflow-harness-mcp/source-inventory.json).
- Snapshot: 93 observed files,61 supported entrypoints,139 listed subcommands/effect-bearing modes, with BaseCommit as the tracked-source reference. Every runtime-root regular file plus nine named interface/operator scripts has a SHA256 and disposition. Four rows are local observations absent from that commit: config.env, local-validation.json, projects.txt and repos.txt under the runtime template root. Their hashes do not establish committed or installed source identity; never copy their contents into a task checkout or published evidence.
- Scope is entrypoint inventory, not exhaustive dynamic flag semantics. Effects are conservative entrypoint-level upper bounds, not certified per-mode behavior. Imported aliases, libraries, configuration and test doubles have explicit dispositions.
- Deployment and external-notification families are included in later-stage tracking. They retain existing explicit effect authorization; plan scope is not permission to execute them.
- Source warning: run_dry_issue.sh changes labels; run_parallel_orchestrators.sh has publication/notification defaults; pause_github_agentic.sh changes hosted workflows. Names are not effect classifications.

### Known Unknowns (ranked)
1. Source entrypoint inventory is recorded below; per-flag effect/authority contracts for later lanes remain future stage inputs.
2. Later lane plans must refine operation-level contracts from source, not invent force/requeue/cancel transitions.
3. Installed runtime, state, owner and pending handoffs are unverified because none is selected (user-confirmed). Planning continues without substituting another installation.
4. Live configuration, route availability and actual pending custody must be resolved before installed-lane qualification; no source test resolves them.

### Dynamic Review Roster
- Source spot-checks: scripts/harness_mcp.py currently has nine tools; atlas_daily selection is independent; atlas_local_dev uses runtime imports and native queue locking; supervised_handoff preserves captured bytes. No execution selection exists; user confirmed NoneSelected after read-only diagnosis found the checkout default absent. These facts trigger first-stage boundary reviews rather than proving live behavior.
- Required core passes: zero-context, implementer readiness, expert technical, security/privacy and human readability.
- Triggered specialists:
  - API/contracts: five additive tools, bridge protocol, mutation annotations, conditional replay and refusal/version semantics; G-MCP/G-DAILY (CI/Local, named unittest commands below).
  - Data-integrity/concurrency and runtime recovery: shared service extraction, original bytes, claim races, lost responses and snapshot cutover; G-NATIVE/G-INTEGRATION/G-UPGRADE (CI/Local, named unittest commands below).
  - Operator workflow: readable status/recovery actions, missing history/config, distinction between reservation/invocation/import/goal acceptance; G-INTEGRATION and G-LIVE (CI/Local plus selected installed lane).
- Not triggered for this first stage:
  - Cloud/provider infrastructure, deployment and external messaging: later tracking-only stages, no new provider execution; G-BRIDGE/G-INTEGRATION include no-launch tripwires. Dedicated effect reviews become mandatory in those child plans.
  - Database/migrations: no database or persistent queue-schema migration proposed; file-state integrity is reviewed separately.
  - Additional cost specialist: no new spending/model route; transport/time budgets and disclosed native queue-memory behavior reviewed by API/runtime specialists.
  - Graphical UI/accessibility: no browser UI; operator comprehension receives its own workflow review.
- Full commands and green criteria are named in Implementation Plan. Specialist planning passes assess whether these requirements are specified; future test receipts establish implementation behavior.

## Challenge Artifacts

### Challenge Packet
#### What we are trying to achieve
Typed MCP access to all maintained lanes in stages, starting with daily work; measure usable workflows, interrupted cases and refusals rather than tool count.

#### Two concrete weaknesses
- W1: Provider preparation is inert; daily preparation claims work and persists a reservation. A generic prepare contract or read-only annotation can change ownership during inspection. Separate contracts and test actual persisted effects.
- W2: Daily coverage can omit supporting actions such as rework, template selection, Actions artifacts and operator recovery. Maintain an operation-level ledger; unclassified supported actions prevent a full-coverage claim.

#### End-to-end failure mode
- FM1: A daily reservation persists, its MCP response is lost, and a retry follows an upgrade. Treating response loss as no work can duplicate execution or import against a changed contract. Restart tests must compare reservation, invocation, runtime and result identities. Reexport the same reservation; preserve the original runtime and reconcile the same invocation.

#### Assumptions -> tests
- A1: Maintained entrypoints map to bounded typed contracts without arbitrary command execution.
  - Test: Inventory APIs, defaults, configuration reads, local writes and external effects.
  - Pass/Fail criteria: Every supported operation has an effect classification and typed contract, or a named discovery blocker; unknown behavior blocks that operation.
  - Status: Untested
- A2: Sharing maintained APIs preserves CLI behavior.
  - Test: Equivalent CLI and MCP requests against independent temporary copies of identical state.
  - Pass/Fail criteria: Equivalent transitions, refusals, bindings and original-byte retention; no MCP-only authority bypass.
  - Status: Untested
- A3: Native presence alone makes an operation safe to expose.
  - Test: Review implicit selection, waits, filesystem scope and effect authorization.
  - Pass/Fail criteria: Explicit selection, bounded output and maintained authority are preserved; presence alone fails.
  - Status: Untested

#### Ranked risks
- R1 (High): Generic tools erase lane-specific effects. Owner: API/security reviewers. Status: Untested. Mitigation: distinct contracts and unauthorized-effect tests.
- R2 (High): Retries/upgrades duplicate execution. Owner: integrity reviewer. Status: Untested. Mitigation: exact replay and original-runtime recovery.
- R3 (High): Artifact access exposes secrets or arbitrary files. Owner: privacy reviewer. Status: Untested. Mitigation: work-bound allowlisted artifacts, bounded output and visible truncation.
- R4 (Medium): All-lane delivery becomes oversized. Owner: orchestrator/goal reviewer. Status: Mitigated by DR-001 staging; executable decomposition remains untested.

#### Alternatives considered
- A: Dedicated typed operations using maintained lane APIs. Preferred: visible effects and direct semantic parity tests; requires maintaining shared contracts.
- B: Generic run-command tool (disliked). Fast apparent coverage but hidden defaults and arbitrary effects violate explicit contracts; reject.
- C: Declare daily-only coverage complete. Useful first delivery, rejected as final outcome under DR-001.
- D: Replace runtime with MCP-native scheduler. Uniform surface, rejected because it introduces a competing lifecycle.

#### Milestones (measurable)
- M0: Exhaustive source operation ledger: lane, entrypoint/subcommand, API, defaults, effects, authority, MCP disposition, stage and acceptance test. Zero unclassified maintained operations.
- M1: Daily item completes all roles and independent acceptance through MCP harness operations; real-host evidence distinct from fixtures. Reconnect/replay/refusal tests pass.
- M2: Each later lane closes its operation ledger with normal, interrupted and refused integration evidence; previous contracts remain compatible.
- M3: Explicit installation upgrade records source/runtime versions, preserved state, original-runtime recovery and rollback evidence. This does not grant unattended authority.

#### Decision boundary
None new at Feature stage. DR-001 fixes scope and sequence. Surface any necessary authority change rather than accepting it as an implementation detail.

## Technical Plan

### Technical Plan Intro
Extend the existing stdio MCP server with typed access to maintained harness operations. A coverage ledger identifies every supported native action, its effects, existing checks and delivery stage. The first delivery covers explicit daily installation selection, intake, status, role reservation, original-result import and acceptance inspection. Later stages cover remaining lanes; daily completion alone does not establish full harness coverage.

Keep lifecycle behavior in maintained runtime APIs. MCP validates requests, selects the explicit installation, invokes a fixed adapter and returns bounded results. CLI and MCP share service functions and equivalent queue transitions and retained evidence. Isolate installed imports from the long-lived MCP process so different source versions cannot reuse cached Python modules.

### Integration Points
- `scripts/harness_mcp.py`: additive typed tools, mutation annotations, strict request validation and bounded responses. Existing nine tools retain their meanings.
- `scripts/harness_service.py`: common envelope, diagnostics and provider conventions; daily selection remains distinct from provider registration.
- `scripts/atlas_daily.py`: extract reusable explicit selection/provenance logic rather than duplicating it.
- `templates/local-automation-runtime/atlas_local_dev.py`: extract shared daily service functions for add/status/prepare/import without changing behavior.
- Installed `atlas_work_items`, `atlas_supervised_handoff`, `atlas_local_sizing`, `atlas_workflows`: retained ownership, readiness, reservation, replay and acceptance rules.
- Local artifacts: full reservations, actual host receipts, original worker bytes, refusal evidence and accepted receipts.
- Other lanes: `scripts/runtime_control.py`, provider adapters and native entrypoints identified in the operation ledger.

### Proposed Architecture Changes
#### Operation coverage ledger
Each maintained entrypoint/subcommand needs a stable operation ID, lane, native API, maintenance status, actual defaults, effect classification, configuration inputs, authority prerequisites, evidence, retry/recovery rules, current MCP coverage, proposed delivery stage and acceptance test. Inventory includes GitHub Actions and local team workflows as separate families. Unknown behavior blocks that operation; no generic command escape hatch. The source ledger below establishes entrypoint coverage; per-mode effect/authority audits remain a required precondition of later lane contracts.

#### Daily MCP contract v1
Create `scripts/daily_selection.py` by extracting the current selection/provenance checks from `scripts/atlas_daily.py`; preserve the CLI's default selection behavior. Create `scripts/harness_daily.py` for MCP service validation/projection. Extract native operations into `templates/local-automation-runtime/atlas_daily_service.py` (already-read bytes to result objects); keep `atlas_local_dev.py` as a compatible CLI wrapper. Create `atlas_daily_bridge.py` as the fixed installed JSON entrypoint. Never load multiple installed runtime modules into the persistent MCP process.

All request objects reject extra properties, duplicate keys, nonfinite values and NULs. These are intended v1 engineering contracts, not claims about current implementation:

```text
Selection = {config_path: absolute path, 1..4096 characters}
FileRef = {path: absolute path, 1..4096 characters, sha256: lowercase hex64}
selection_digest = lowercase hex64
id = nonblank string, <=200 characters
cursor = string, <=2048 characters
limit = integer, default20, range1..100
adapter_call_id = caller-generated lowercase UUIDv4, retained before mutation submission

harness_daily_status(selection, work_item_id?, adapter_call_id?, cursor?, limit?)
harness_daily_add(selection, expected_selection_sha256, adapter_call_id, intake:FileRef)
harness_daily_prepare(selection, expected_selection_sha256, adapter_call_id,
                      work_item_id, expected_revision:lowercase Git SHA40|64)
harness_daily_import(selection, expected_selection_sha256, adapter_call_id,
                     reservation:FileRef, host_receipt:FileRef, result:FileRef)
harness_daily_evidence(selection, work_item_id, artifact_id?:string<=512,
                       view:index|reservation|receipt|goal-review|role-result,
                       cursor?, limit?)
```

`selection` is mandatory on every call. No provider-registry, working-directory or environment fallback selects a daily installation. Config supplies runtime/state/owner/source/lane/standalone; independent overrides are refused. Status remains available to diagnose an unavailable bridge, with native work status marked unknown rather than inventing values.

`status` and `evidence` are read-only. `add`, `prepare`, `import` mutate local state. Daily prepare never inherits inert provider preparation annotations. Use readOnlyHint=false for these three tools; idempotentHint=false for add and prepare, true for import only for its exact fixed-input replay contract; openWorldHint=false. Tool annotations are descriptive, not authority grants. Prepare replay is identical only while that owned reservation remains pending: after import, the same request can advance to the next role, so prepare is not globally idempotent.

Selection binding: hash a canonical JSON record containing the resolved config path, raw-config SHA256 and ordered provenance marker names+SHA256, plus resolved runtime/state/owner/source/lane/standalone. Use sorted keys, compact separators, ensure_ascii=true, allow_nan=false and UTF-8. This binds bytes and identity without returning private config bytes. Mutation requires `expected_selection_sha256` from prior status; recompute immediately before invocation and in the bridge, passing the original validated selection. Pre-admission drift returns `selection_changed` without mutation. The admission point is the bridge's final selection comparison immediately before calling the native service; freeze that validated runtime/state/owner tuple for the whole call. A detected later config change is reported as post-admission drift against the original identity, without rollback claims or switching targets. Do not claim filesystem-wide atomicity: native ownership/claim locks remain final state authority; include a concurrent config-change regression before qualification.

Input files: preserve native 1..65,536-byte limits. Open the exact caller-supplied file once, verify owned regular object, read at most65,537 bytes, calculate hash and forward the captured exact bytes. Compare fstat before/after and refuse observed change; hash match binds captured bytes, not a promise against later file edits. No parse/reserialize of role result bytes. Explicit files can originate in the assigned execution checkout or elsewhere readable under existing owner checks; do not impose a jobs-only import boundary. Input contents are not echoed. New ownership checks must be documented as adapter checks, not falsely described as existing CLI behavior.

Evidence browsing is narrower than input capture: artifact IDs come only from the selected item's native pending reservation or accepted receipt. Resolve retained artifact files under selected jobs, reject escapes and symlinks that leave that boundary, check known hashes, and use descriptor-relative traversal from an opened jobs directory: each component uses dir_fd/openat with O_NOFOLLOW (O_DIRECTORY for parents), reject dot/dot-dot and absolute artifact paths, verify final fstat regular/owner and recorded hashes. Do not resolve/check then reopen by string path. Deterministic parent-symlink-swap tests must prove refusal without reading an escape target. Do not offer private queue snapshots, config, credentials or unrestricted process logs. Expose only named native contract fields; free-text evidence remains untrusted task data, not instructions, and cannot be guaranteed secret-free by its field name.

Artifact selection rules: index forbids artifact_id and enumerates known opaque IDs with native handoff/role/kind metadata. receipt, goal-review and role-result require artifact_id; omission returns artifact_required, unknown or foreign IDs refuse without falling back to latest. Reservation may omit artifact_id to select the current pending reservation; if supplied, it must identify that same pending reservation. View/kind mismatch returns artifact_view_mismatch. Never choose an arbitrary historical handoff.

`view=reservation` returns only the current pending reservation, in full four-field shape without altering bindings/packet. Never reconstruct a historical reservation from accepted receipts or copied task artifacts that a later role may have overwritten. If no original pending reservation is retained, return reservation_unavailable with known historical receipt/result references; do not invent a dispatch packet. `receipt` exposes the six correlation fields. `goal-review` exposes verdict/reason/evidence. `role-result` projects the known result shape; display truncation does not modify retained bytes. Return hashes and sizes independently of displayed text. Known malformed artifacts return refusal, not a fabricated empty result.

Uncertain add recovery: status filtered by the submitted work_item_id must work before any handoff exists. In the MCP row expose intake_projection_sha256: SHA256 of canonical JSON selecting exactly the observed item's present TASK_FIELDS (the same native intake allowlist, excluding runtime-owned fields); sort keys, compact separators, ensure_ascii=true, allow_nan=false, UTF-8. Derive the expected projection from the captured submitted intake with the same function. Also expose task_context_sha256 from maintained work_item_context for source review. These are observed semantic projections, not a retained original intake-byte digest or a substitute for goal acceptance. Native CLI output stays compatible; these are MCP-only derived observations.

After lost add response: inspect the caller-retained adapter_call_id through status and the same work_item_id. While adapter settlement is active or unknown, do not repeat the mutation. After a terminal observation, reconcile the native item. If a row exists and its intake projection matches, continue inspection of that existing item without another creation. A different projection is intake_conflict and stays blocked; no inferred equivalence after source changes. Missing item alone does not prove an in-flight mutation failed. Only the terminal adapter observation below permits considering a new deliberate add, with a fresh adapter_call_id, unchanged intake and explicit work-item identity; native readiness and duplicate checks still apply. No automatic retry. Preserve native duplicate refusal; never fabricate a creation/host receipt. Test response loss, delayed original process, matching admission and conflicting preexisting ID.

Adapter settlement (transport evidence, not work-item state): the caller records adapter_call_id before submitting add/prepare/import. The adapter retains a bounded record in a directory named by adapter_call_id under selected state_dir/daily-adapter-calls/ containing only protocol, call ID, selection digest, selected owner/runtime/state/source identity, operation, work-item ID, request SHA256, timestamps and terminal code/result digest if available. The request digest binds the operation, validated selection and captured input hashes or named prepare arguments; exclude the call ID itself. Do not retain raw config, request bodies, role results or stderr here. Use owned private directories/files, descriptor-relative no-follow access and atomic metadata publication; metadata objects are strict JSON <=65,536 bytes. This local diagnostic namespace is outside the native queue and jobs evidence index. It neither queues work nor changes claims, reservations, host receipts or goal acceptance. Preserve it during upgrade/rollback; no automatic deletion is added.

Before spawning a mutation bridge, the parent creates a private staging directory, opens its lifetime file and takes a Linux flock exclusive lock tied to the inherited open file description (not a process-scoped lockf lock), writes/fsyncs the initial record and atomically publishes the directory under the caller's ID. Publication must not overwrite an existing ID; competing submissions have one winner. The lock is already held when the record becomes visible. Pass that same open locked descriptor to the fixed bridge using pass_fds; the child verifies it against the published directory before native mutation. There must be no release/reacquire gap between parent publication, spawn and child ownership. The parent closes its copy after successful spawn; the bridge retains its copy through all possible native writes and terminal receipt publication. Any descendant capable of continuing mutation must retain the descriptor too; otherwise such delegation is forbidden. Parent death before spawn leaves no child; parent death after spawn leaves the child's lock held. Spawn failure records its actual refusal where possible and releases the lock. Never infer termination from elapsed time, a stored PID or a missing response. Unknown or unsupported lock/filesystem semantics refuse mutation before admission; the exact local lane must pass the real-process lock tests before qualification.

A repeated adapter_call_id never launches a second bridge: changed request digest returns adapter_call_conflict; matching digest returns adapter_call_exists with status recovery guidance. This fence is not native add/prepare idempotence. A deliberate native prepare reexport or exact import replay after settlement uses a fresh adapter_call_id and the same original native inputs; native replay/advancement rules remain authoritative. Records are diagnostic, not a cache that fabricates native success.

Status with adapter_call_id does not create directories, files or receipts. Return one bounded adapter_call observation outside queue pagination; cursor is forbidden with this selector. Validate recorded selection/owner, and cross-check work_item_id when supplied. Probe the existing lifetime lock nonblockingly: busy means active (outcome remains uncertain); acquired means terminal, even if the child exited without writing a terminal receipt. Keep that descriptor open for the observation and release it afterward. A terminal lock observation proves no process in that published call can still write native state, not that its mutation succeeded or rolled back; reconcile queue/reservation/accepted receipt separately. Missing, foreign, malformed or changed records and unverifiable locks report unknown/refusal without claiming termination. Unknown stays fenced for explicit operator reconciliation; there is no force, timeout-clear or automatic relaunch operation. Expose call ID, operation, recorded selection digest, work-item ID, adapter_state=active|terminal|unknown, terminal_receipt_present and safe terminal code/digest only. The model-host invocation ID remains the independently observed host receipt and must never be populated from adapter_call_id. Status can observe transport settlement without a working bridge; config selection must still validate. Prepublication refusal cannot have launched a child; if its response was lost, an absent record alone is still unknown.

Common envelope: schema_version=`atlas-tools.daily.v1`, observed_at, read_only, identity, status, optional work_item_id/adapter_call/native_result/items/next_cursor, truncated:boolean, outcome_uncertain:boolean, optional error={code,message,recovery}. Identity includes selection_sha256, adapter_protocol, adapter_source_sha256 and selected identity already exposed by the current status wrapper. Preserve native statuses/refusal codes, including exact duplicate versus accepted import; keep process state, import state and independent goal acceptance separate.

Pagination cursor is a base64url canonical JSON descriptor with protocol, selection digest, queue-file SHA256, view, work-item identity, offset and checksum of those fields. It conveys position, never authority; every page revalidates selection and native access. Verify checksum/bounds. Changed queue/selection returns `cursor_stale`; no mixed observations. Index/status use item limits; individual string projections use transport byte budget with explicit truncation. Native queue loading is currently unbounded: pagination bounds response size, not native memory; do not claim otherwise.

Keep existing transport maxima:1,048,576-byte MCP request and2,097,152-byte result. Never truncate a dispatchable reservation. If a complete reservation exceeds response size, return `reservation_too_large`, retain state and expose the original recovery route. This case blocks a claim of MCP-only coverage for that input. Native daily import itself limits reservation files to65,536 bytes; an oversized non-importable native reservation is a retained contract failure, not permission for a different MCP lifecycle. First-stage acceptance must prove admitted supported task packets round-trip within native reservation limits, or retain a failing task and repair the native contract separately before claiming success.

Fixed bridge invocation: `[approved_python, '-I', '-B', selected_runtime/'atlas_daily_bridge.py']`, bounded structured stdin, no caller executable/command flags. Child inserts only its own runtime path and validates imported module origins. The lifetime descriptor is an internal inherited capability, never a caller-supplied executable, arbitrary path or command flag. `describe` is read-only and reports protocol/actions/source digest/native limits. Missing bridge=`adapter_unavailable`; incompatible protocol=`adapter_incompatible`; no current-source-template or alternate-runtime fallback. The bridge/service digest hashes ordered relative filenames and raw bytes for bridge/service/CLI and their native daily dependency modules; expose the explicit inventory alongside its digest. Markers describe source provenance, not installed integrity or host qualification.

Use30-second process deadlines, bounded stdout at transport result ceiling, safe error codes instead of raw stderr. Drain/stop over-budget child output without buffering indefinitely. On timeout or output overflow, stop and reap the owned bridge where possible; retain the lifetime lock until no mutating descendant remains. If cleanup is uncertain, report the call active/unknown instead of claiming cancellation. Timeout, broken pipe, signal or missing/malformed result after mutation invocation reports outcome_uncertain=true with adapter_call_id; it proves no rollback. Reconnecting status observes the published lifetime lock even if the original MCP server was killed. Preserve same reservation/owner; recover through status/reexport or exact accepted import replay. Under DR-002 a host invocation exists only after actual dispatch; recover that actual invocation if dispatched, otherwise do not invent one. Keep worker.command=None and native route/budget/independent review checks.

Bridge wire protocol: one strict JSON object on stdin, at most1,048,576 bytes; fields are protocol, operation (describe/status/add/prepare/import/evidence), validated selection identity and digest, and that operation's named arguments; mutations also carry adapter_call_id and the published transport record identity validated against the inherited descriptor. File inputs are input objects with explicit encoding=base64, decoded_size integer1..65536, sha256 hex64 and data string. Decode with strict alphabet/padding, enforce encoded/decoded bounds before allocation, verify declared size/hash, and pass the captured decoded bytes to the native service. Maximum three inputs per import, one per add, zero otherwise; aggregate decoded input <=196,608 bytes. No caller command or alternate module path. Selection/provenance are reread for validation; service operates only the validated immutable runtime/state/owner snapshot carried in the request, never reselecting mid-operation. Define the complete per-operation wire JSON schema in the same shared service contract consumed by tests.

Snapshot consistency: status loads queue bytes once, hashes and parses those exact bytes and projects that observation; it must not hash a separate read after store.load. For evidence, read retained artifact bytes once and bind their digest plus the queue observation into the cursor; independently mutable projection inputs must be included in the observation digest or produce cursor_stale. This is an observation snapshot, not a transactional snapshot of the entire host.

Protocol checks before mutation must not launch models. Installed bridge source is trusted operator-selected code, like the maintained native CLI; source hashes report observed integrity, not a sandbox against malicious installed code.

### Failure Modes (per integration point)
- Selection: unreadable/contradictory config produces a concrete blocker; no installation search or inferred fallback.
- Runtime modules: cached imports cross versions; isolate subprocesses and alternate requests across two deliberately distinct runtime fixtures.
- Adapter process: parent death leaves a mutating bridge running; retain published call identity/lifetime lock, expose active versus terminal through read-only status, and reconcile native state without automatic relaunch.
- Reservation: persisted response loss duplicates work; retry reexports the identical owned reservation and uncertain host execution remains fenced.
- Import: normalized bytes or foreign receipt substitutions; enforce exact-byte retention, ownership and replay refusals.
- Evidence: stale/truncated data appears complete; expose freshness, cursors and explicit truncation without implying acceptance.
- Upgrade: pending bindings drift; block cutover until original-runtime recovery.
- Provider integration: typed wrappers bypass grants or wait indefinitely; retain native authority and bounded observation.

### Invariants / Non-Changes
No replacement scheduler, arbitrary-command tool, new execution authority, fabricated evidence, inferred acceptance, implicit installation selection or automatic upgrade. Coordination stays local and reviewers remain independent.

### NFRs alignment
- Security/privacy: allowlisted fields and work-bound artifacts; omit configuration/credential stores and unrestricted logs. Invalid input/error tests use secret sentinels and prove contents are not echoed. Free-text task evidence is untrusted and not guaranteed secret-free.
- Integrity: CLI/MCP semantic parity, concurrent reservation refusal, original-byte retention and exact replay.
- Operability: lane/version identity, selection diagnostics, actionable blockers and freshness.
- Performance: bounded messages, pagination and waits; v1 numeric limits and native queue-memory limitation are explicit above.
- Cost: no model launch from inspection or preparation; preserve route qualification and task budgets.

## Implementation Plan

### Agent roster (required for PlanTier: Full)
- implementation (`agents/implementation.md`): implement one admitted bounded work item in an isolated pinned checkout.
- validation (`agents/test-engineer.md`): independently execute objective checks and retain actual receipts.
- code-review (`agents/code-reviewer.md`): independently inspect source/API behavior and authority preservation.
- semantic-alignment (`agents/semantic-alignment.md`): independently judge the item and staged outcome against the accepted scope.
- evidence-rollup (`agents/evidence-rollup.md`): connect retained implementation, validation and review evidence to the same work-item identity.
- plan orchestrator: maintain this plan and reconcile proposals; does not fabricate role results or approve its own independent reviews.
- supervisor: verify host/account/route and model/reasoning against the reserved assignment before dispatch. Task-bound sizing selects the actual permitted route; this roster is not a reservation or model approval.

### File Deltas (exhaustive) + rationale
Delivery implementation targets only; these are not current admitted write scopes. D03–D11 decomposition outputs use the one-file support-spec scope above, and the listed code targets stay blocked until qualified child assignments exist. Later lane files remain outside this delivery's write scope. Planning evidence already exists in plans/support/full-workflow-harness-mcp/source-inventory.{json,md}; WS1 derives the maintained docs ledger from that pinned snapshot, preserving provenance. Never mutate the original snapshot to disguise drift.
- `docs/workflow-mcp-coverage.json` - create - WS1 - source-pinned operation ledger with native command/subcommand, effects, stage and acceptance mapping.
- `docs/workflow-mcp-coverage.md` - create - WS1 - readable coverage and stage summary, with incomplete stages visible.
- `scripts/check_workflow_mcp_coverage.py` - create - WS1 - refuse omitted/unclassified maintained entrypoints or missing evidence metadata.
- `tests/test_workflow_mcp_coverage.py` - create - WS1 - prove new native entrypoints/subcommands cannot silently escape inventory.
- `scripts/daily_selection.py` - create - WS2 - reusable explicit selection/provenance and source identity logic.
- `scripts/atlas_daily.py` - modify - WS2 - preserve current read-only CLI behavior using shared selection functions.
- `tests/test_atlas_daily.py` - modify - WS2 - retain CLI/symlink/config/source-drift behavior and prove no mutation from diagnosis.
- `templates/local-automation-runtime/atlas_local_dev.py` - modify - WS3 - extract service return values without changing CLI transitions, refusal semantics or original bytes.
- `templates/local-automation-runtime/atlas_daily_service.py` - create - WS3 - callable daily lifecycle operations with original input bytes and structured outputs shared by CLI and bridge.
- `templates/local-automation-runtime/atlas_daily_bridge.py` - create - WS3 - versioned fixed-entrypoint subprocess bridge using only selected installed runtime APIs, retaining the inherited lifetime lock through mutation and terminal observation.
- `templates/local-automation-runtime/tests/test_atlas_local_dev.py` - modify - WS3 - retained daily CLI lifecycle, concurrency and replay behavior after extraction.
- `templates/local-automation-runtime/tests/test_atlas_daily_bridge.py` - create - WS3 - bridge version/validation, original-byte handling and no model-launch behavior.
- `scripts/harness_daily.py` - create - WS4 - typed daily service, bounded subprocess execution, call-ID/transport-record publication and read-only settlement inspection, request binding and safe evidence projection.
- `scripts/harness_mcp.py` - modify - WS4 - additive daily tool schemas/annotations and strict request dispatch.
- `scripts/harness_service.py` - modify - WS4 - include new server components in source fingerprint and expose common response metadata without changing provider registration authority.
- `tests/test_harness_daily.py` - create - WS4 - request/ref boundary, pagination, compatibility and uncertainty behavior.
- `tests/test_harness_mcp.py` - modify - WS4 - new typed tools, mutation hints, invalid-input refusal and nine-tool regression behavior.
- `tests/test_harness_daily_integration.py` - create - WS6 - independent real-process MCP reconnect/lifecycle/parity tests using temporary runtimes and synthetic role results.
- `tests/test_sync_runtime_template.py` - create - WS5 - preserve installed local state and include the new managed bridge in runtime copy inventory.
- `scripts/verify_repo.py` - modify - WS5 - include operation-coverage check in repository verifier.
- `docs/daily-development.md` - modify - WS5 - MCP operation usage, caller-retained adapter IDs, settlement/retry recovery and explicitly separate actual host execution.
- `docs/harness-interface.md` - modify - WS5 - lane distinction, compatibility and bounded artifact/acceptance semantics.
- `skills/automation-harness/SKILL.md` - modify - WS5 - teach daily MCP path with explicit selection and preserved authority.
- `.codex/skills/automation-harness/SKILL.md` - regenerate - WS5 - generated adapter freshness from the canonical skill, never hand-edit.
No changes to runtime-local config, credentials, queues, jobs, reservations, repositories or unrelated dirty source are part of these file deltas. No new config key is required for the daily lane; the existing explicit daily selection remains authoritative.

### Delivery packages, points and admission status
WS1–WS6 below retain file ownership but are tracking containers. They are not six admissible coding items. The following packages are a source-grounded delivery breakdown; their estimates describe eventual work, not permission to dispatch.

| ID / owner | Delivery target | Depends on | Provisional points | Current admission disposition |
| --- | --- | --- | ---: | --- |
| D01 / WS1 | Coverage data; G-COVERAGE-DATA acceptance | none | 3 | Routine candidate only; exact sizing/pins/route still missing |
| D02 / WS1 | Coverage checker; full G-COVERAGE acceptance | D01 | 5 | Routine candidate only; exact sizing/pins/route still missing |
| D03 / WS2 | Shared selection | D01 | 5 | Coding blocked: security_or_authority |
| D04 / WS3 | Native service extraction | D01 | 8 | Coding blocked: cross_component_protocol |
| D05 / WS3 | Installed bridge and inherited lifetime lock | D03,D04 | 8 | Coding blocked: cross_component_protocol, security_or_authority |
| D06 / WS4 | MCP service, byte capture and transport settlement records | D03,D05 | 8 | Coding blocked: cross_component_protocol, security_or_authority |
| D07 / WS4 | Evidence and pagination | D06 | 8 | Coding blocked: security_or_authority |
| D08 / WS4 | Five-tool MCP registration | D06,D07 | 5 | Coding blocked: cross_component_protocol, security_or_authority |
| D09 / WS6 | Independent integration evidence | D05,D06,D07,D08 | 8 | Coding blocked: cross_component_protocol |
| D10 / WS5 | Upgrade integrity tests | D05,D08 | 5 | Coding blocked: security_or_authority |
| D11 / WS5 | Verifier and release guidance | D02,D08,D09,D10 | 5 | Five files and multiple interfaces; split before coding |
| D12 / WS6 | Actual goal acceptance and installed qualification | D01,D02,D03,D04,D05,D06,D07,D08,D09,D10,D11 | Unestimated | Actual custody, source acceptance and live route unqualified |

- Delivery estimate: 68 points, excluding D12, discovery/decomposition, admission-policy work and any runtime installation/setup. Fibonacci estimates are provisional; no conversion to elapsed time, money or model limits is claimed. This is not a signed or task-bound sizing result.
- Scope budget:12 delivery packages; warning above8, within12 maximum. D03–D11 are blocked delivery groups whose next possible authorized activity is bounded decomposition, not their implementation. Expanded executable children require separately selected child plans before this parent exceeds12 leaves; no child plan is silently created or selected.
- D01/D02 have respectively two and two target files, at most three criteria and one interface; still require independent exact-context sizing. D03–D10 preserve their genuine listed flags even when scopes are small. D11 must split its five-file target. D06 then D07 serialize shared file ownership. D09 owns independent tests after D08; release/qualification waits for D10/D11.

### Admission contract and first bounded next action
1. **No selection means no admission.** B-SEL is a manual operator prerequisite: supply an explicit existing selection, or separately request/review new-installation preparation. Never infer runtime/state/owner from a GitHub registry, memory, cwd or an unrelated runtime. User has selected neither installation nor owner/state. Capture only allowlisted identity/readiness, not local configuration bytes, in repository evidence.
2. **Separate governing and target runtimes.** The governing installed runtime must support the existing daily CLI/handoff APIs. The future target snapshot will contain the new bridge. Use the former to govern implementation/reviews; the target need not exist yet. Recover original pending custody before any version switch.
3. **Current policy is a real blocker.** Coding/validation requires ≤4 explicit files,≤3 substantive criteria,≤1 changed interface, resolved questions and truthful complexity flags. Both generic v1/v2 refuse unresolved protocol/security/migration/new-service complexity; v2 independent model review does not override it. Known frozen supervisor exceptions are exact unrelated package contexts, not reusable escape hatches.
4. **Planning template bootstrap is not assumed.** Source planning-design-doc has10 roles and no independent goal gate; current daily add requires exactly one independent evidence-consuming goal gate. Do not dispatch that template as-is or relabel implementation/test-runner as decomposition. A genuinely noncoding decomposition context may qualify at the sizing layer, but template/route/goal-gate checks still apply. A compatible installed planning route must be independently demonstrated; otherwise keep decomposition admission blocked and prepare a separate reviewed route/template proposal under DR-006. This repair does not install or modify templates.
5. **Next source preparation is not execution.** Before any implementation request, freeze a reviewed D01 specification from this plan: exact two files, criteria preserving all source dispositions/stable IDs/later-stage gaps, G-COVERAGE-DATA and G-GOAL (not the unbuilt D02 checker), owned isolated checkout and full source SHA. D01 has three criteria: source-pinned inventory/disposition parity; stable unique operation IDs with explicit planned/later status and named acceptance targets; readable Markdown covering those same paths/IDs and incomplete-stage limits. D02 follows independently accepted D01 with checker/test scope, full G-COVERAGE plus G-GOAL, and three criteria: detects missing operations; detects missing evidence/dispositions; accepts valid complete ledger. Independent sizing decides eligibility and model route. No actual packet can be completed while selection, checkout identity and route remain unknown.
6. **Complex delivery follows evidence, not guesses.** For each D03–D11, a future authorized decomposition task may write only `plans/support/full-workflow-harness-mcp/specs/Dxx-admission.spec.md` (one explicit output), not implementation/config/queue files. Its three outputs are exact child scope/dependencies/criteria; real complexity and current qualifier outcome; integrated evidence/next blocker. These support specs are subordinate drafts, never permission to edit the canonical plan or a replacement authoring surface. If children retain flags, they remain blocked; do not claim contract discovery removed genuine coupling.

### Exact packet assembly, routing and proposed resource bounds
- Stable candidate IDs: MCP-DAILY-D01 through MCP-DAILY-D12, with explicit child suffixes only after decomposition. A stable candidate ID is not a queued/admitted work item. Preserve one actual work-item identity through implementation, test-runner, code-review, semantic-alignment and evidence-rollup; retain blocked attempts and reviewed successors.
- Every future clean intake must carry substantive goal and ≤3 criteria, full source SHA, absolute owned isolated execution checkout, exact approved write_scope, workflow_kind/team_template, source spec absolute path/hash, dependencies and local_execution_v1. Use docs/daily-development.md; omit all runtime-owned state/claim/result/receipt fields. Never use this working checkout's uncommitted plan as proof that an execution checkout includes it.
- Proposed route for routine D01: Luna/medium implementation+validation, Sol/high independent review. D02 may warrant Sol/high implementation+validation and Terra/high review under v2; this is a proposal requiring actual independent sizing of the frozen intake. Coherent complex design may warrant Sol or Terra, but model strength grants no admission. Current noncoding v2 roles use review_model, not implementation_model; do not promise incompatible per-role overrides. Distinct author/reviewer invocations remain independent even where the same permitted model is used.
- Actual v2 review must contain exactly reviewer/rationale/subject_sha256 from the independent reviewer against maintained sizing_subject_sha256(work_item_context(intake)); the hash is not a signature. Retain the authentic review and qualifier output; do not synthesize a passing review or use another package's hash.
- Proposed bounds for D01 or D02 only: at most5 initial role invocations and60 minutes per item, matching the existing five-role lifecycle. No automatic repair/redispatch loop. At a failed or inconclusive gate, stop and retain evidence; any continuation/revised bounds require a reviewed decision under the same custody. These are unapproved supervision stop gates, not demonstrated hard host cancellation or a monetary/token cap. Capture original start/deadline/counters and preserve them on reconnect/resume; never reset budgets because a new agent wakes.
- No budget has been selected or approved for D03–D12. Their actual template roles, call/time/token/cost bounds and host enforcement limitations must be frozen before admission. No new paid/provider route is permitted by this plan repair.
- Pre-admission evidence must bind selection identity, installed source/version/integrity observations, checkout HEAD and dirty policy, spec hash, real role/template references, independent sizing, qualified host/account/route/model/reasoning, budgets and any original pending custody. Missing evidence is a blocker, not a placeholder allowed into the queue.
- User authorization remains withheld. After fresh independent review and readback, present the exact plan/spec hash, proposed scope/routes/bounds, retained blockers and effects for user judgment. Do not add, prepare, dispatch, import, install, publish or merge merely to demonstrate readiness during repair.

### Manual admission blockers (current state)
| ID | Owner / status | Resolution evidence / dispatch consequence |
| --- | --- | --- |
| B-SEL | Operator/user; NoneSelected | Explicit selected config and read-only identity/provenance receipt. Until then no queue/config target is known. |
| B-ROUTE | Supervisor; Unverified | Actual host/account/route/model availability and original custody reconciled; no inference from installed binary or source fixtures. |
| B-SIZ | Independent sizing reviewer/supervisor; Missing | Exact isolated source/spec/intake, genuine review, qualifier result and selected bounds for the first task. |
| B-CPL | Plan/admission owner; Unresolved (DR-006) | Truthfully qualified children or separately accepted bounded policy/template route. Do not clear flags or borrow frozen packet exceptions. |
| B-REV | Independent reviewers and user; Stale after repair | Fresh execution-readiness review plus readback of repaired admission contract before any readiness/approval claim. |
Implementation authorization is separately withheld by the user; it is not evidence that these five prerequisites have been resolved.

### Workstreams + merge points
- WS1: All-lane operation inventory and delivery ledger
  - Owner: implementation; independent acceptance by semantic-alignment.
  - Agent type: explore
  - Delegate: required
  - Intended behavior change: every maintained operator operation is classified; daily-first delivery and remaining gaps are explicit.
  - Depends on: none.
  - Review gates (named): D01 G-COVERAGE-DATA/G-GOAL; D02 and MP1 G-COVERAGE/G-GOAL.
  - Owns files: coverage JSON/Markdown, checker and checker tests listed above.
  - Merge point / integration step: MP1, freeze operation IDs and daily effect classifications before exposing tools; later family upper bounds remain discovery inputs, not reviewed per-mode contracts.
- WS2: Shared daily selection
  - Owner: implementation; independent validation/code-review.
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: CLI and MCP use identical explicit installation/provenance checks, including symlink resolution and contradictory-source refusal.
  - Depends on: WS1.
  - Review gates (named): G-SELECTION, G-GOAL.
  - Owns files: daily_selection.py, atlas_daily.py and test_atlas_daily.py.
  - Merge point / integration step: MP2.
- WS3: Installed daily service and bridge
  - Owner: implementation; independent validation/code-review.
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: CLI and versioned bridge call maintained lifecycle functions; process isolation prevents runtime import contamination.
  - Depends on: WS1.
  - Review gates (named): G-NATIVE, G-BRIDGE, G-GOAL.
  - Owns files: atlas_local_dev.py, atlas_daily_service.py, atlas_daily_bridge.py and their runtime tests.
  - Merge point / integration step: MP2.
- WS4: Typed MCP daily operations
  - Owner: implementation; independent validation/code-review.
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: daily status/add/prepare/import/evidence use concrete schemas, bounded output, preserved original bytes and conservative uncertain-outcome reporting.
  - Depends on: WS2, WS3.
  - Review gates (named): G-MCP, G-DAILY, G-GOAL.
  - Owns files: harness_daily.py, harness_mcp.py, harness_service.py, test_harness_daily.py and test_harness_mcp.py.
  - Merge point / integration step: MP3.
- WS5: Upgrade, documentation and release integration
  - Owner: implementation; independent validation/code-review.
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: verifier rejects coverage drift; installation guidance preserves old snapshots, local state and outstanding handoff bindings; canonical/generated skill guidance stays current.
  - Depends on: WS4.
  - Review gates (named): G-UPGRADE, G-REPO, G-GOAL.
  - Owns files: upgrade test, verify_repo.py, daily/harness docs and canonical/generated automation-harness skill.
  - Merge point / integration step: MP4.
- WS6: Independent integrated evidence and qualification
  - Owner: validation; code-review and semantic-alignment remain independent of the implementation author.
  - Agent type: test-engineer
  - Delegate: required
  - Intended behavior change: integrated lifecycle/reconnect and parity evidence rejects plausible wrong implementations; live qualification stays distinct from fixture success.
  - Depends on: WS4 for source integration tests; WS5 for release/installed qualification. Source test authoring must finish in Phase 3 before its G-INTEGRATION exit; qualification follows Phase 4.
  - Review gates (named): G-INTEGRATION, G-REPO, G-GOAL, G-LIVE.
  - Owns files: test_harness_daily_integration.py; actual receipts remain in selected local runtime artifacts, not repository source.
  - Merge point / integration step: MP5 (source acceptance) and MP6 (installed-lane qualification).

### Delegation Quality Gate (required for PlanTier: Full)
- DQ-1 Workstream delegation metadata complete: Pass
- DQ-2 File ownership conflict-free before merge points: Pass
- DQ-3 Delegation coverage: Pass
- DQ-4 Validation delegation path present: Pass
- One persistent work-item identity per admitted bounded leaf. Prepare/import each reserved role using the maintained queue APIs; do not use these workstream names as invented passing assignments. Retain failed attempts and explicit successors.

### Phases + tasks + exit criteria
#### Phase 0: Admission preparation (no implementation authorized)
- Owner(s): supervisor, independent sizing/route reviewers and plan owner; user retains policy and execution authority.
- Depends on: none.
- Tasks (by owner): resolve B-SEL/B-ROUTE/B-SIZ for D01; preserve B-CPL for flagged packages until DR-006 is resolved; obtain B-REV evidence on repaired text. Prepare no live queue reservation in this repair.
- Exit criteria (evidence): exact frozen D01 context is independently qualified; actual target/route/custody/budgets known; user authorization explicitly recorded for its reviewed effects. No flags removed to force eligibility.
- Gates (named): G-ADMISSION. Planning and deterministic source inspection can continue while this gate is blocked; actual implementation-role admission cannot.
#### Phase 1: Inventory and freeze daily contracts
- Owner(s): WS1 implementation; semantic-alignment reviewer.
- Depends on: Phase 0 for role admission.
- Tasks (by owner): WS1 first completes D01 data with G-COVERAGE-DATA and independent G-GOAL; after D01 acceptance, D02 adds the checker/tests and passes full G-COVERAGE/G-GOAL. Inventory every maintained entrypoint/subcommand, separate helpers/fixtures explicitly, record existing authority and freeze concrete daily contract schemas from Technical Plan. D01 acceptance alone does not close Phase 1 or MP1.
- Exit criteria (evidence): no unclassified native operations; all later-stage gaps visible; conservative family effects explicitly distinct from later per-flag effect audits; daily operation mappings testable; no generic shell escape.
- Gates (named): G-COVERAGE, G-GOAL.
#### Phase 2: Preserve CLI semantics and add isolated bridge
- Owner(s): WS2, WS3 implementation; independent validation and code-review.
- Depends on: Phase 1.
- Tasks (by owner): first resolve D03–D05 coding admission under DR-006 without weakening flags; only then WS2 extracts selection and WS3 extracts daily functions/bridge in independently qualified child scopes. The bridge does not launch models; it validates and holds the inherited adapter lifetime lock through terminal handling.
- Exit criteria (evidence): old CLI behavior/refusals unchanged; two distinct runtime versions alternate through isolated bridge subprocesses launched by one persistent test parent without cached-module leakage; unsupported bridge version refuses before mutation. Actual single-MCP-session alternation belongs to Phase 3 G-INTEGRATION, after WS4 exists.
- Gates (named): G-SELECTION, G-NATIVE, G-BRIDGE, G-GOAL.
#### Phase 3: Expose typed MCP daily lifecycle
- Owner(s): WS4 implementation; WS6 validation for integration test authoring; independent code-review.
- Depends on: Phase 2.
- Tasks (by owner): only after D06–D09 child admission is resolved, WS4 implements exact daily schemas, file digest checks and original-byte import, response bounds, artifact projections and published call records/status settlement. D05/D06/D08/D09 admission specs must include the lifetime-descriptor, wire, metadata and reconnect interfaces without weakening their complexity flags. WS6 writes and runs integration tests in this phase; later release qualification waits for WS5. Preserve old provider tool behavior.
- Exit criteria (evidence): CLI/MCP produce equivalent transitions/refusals; mutating prepare is labeled correctly; dropped-response prepare reexports the same reservation; uncertain host invocation remains blocked.
- Gates (named): G-MCP, G-DAILY, G-INTEGRATION, G-GOAL.
#### Phase 4: Release readiness and state-preserving qualification
- Owner(s): WS5 implementation; WS6 validation; independent code-review/semantic-alignment/evidence-rollup.
- Depends on: Phase 3.
- Tasks (by owner): resolve D10/D11 qualification and split limits first; WS5 then refreshes guidance, verifier and generated adapter; WS6 completes objective integration evidence and, only after live prerequisites are met, observes a supervised item and upgrade/recovery.
- Exit criteria (evidence): source gates pass before source release; installed qualification separately records actual host and queue evidence. No fixture-only claim of live acceptance.
- Gates (named): G-UPGRADE, G-REPO, G-INTEGRATION, G-GOAL; G-LIVE required for installed-lane qualification.

### Review gates (named + definitions)
- G-ADMISSION:
  - Where it runs: Local, explicitly selected governing runtime and qualified host; currently blocked.
  - Entry point / command: read-only `python3 -B scripts/atlas_daily.py --config /absolute/explicit-selection.json status`; then the selected installed runtime's maintained sizing_subject_sha256/qualify APIs on the exact frozen intake as documented in docs/daily-development.md. Role/queue mutations occur only after separate authorization.
  - Green means: explicit installation/owner/state, verified host/route/custody, isolated source/spec pins, authentic independent sizing and qualified assignment, concrete approved bounds and user authorization are all retained. Unknown paths, missing approvals, unrelated frozen exceptions and stale reviews never pass.
- G-COVERAGE-DATA:
  - Where it runs: Local, D01's pinned execution checkout; Python standard library only. No D02 files or runtime admission beyond the separately governed D01 item are needed for this deterministic check.
  - Entry point / command: run the following read-only command from the checkout root and retain stdout/exit status in the D01 validation role evidence. It validates the two data files against the preserved source snapshot; full discovery/checker regression belongs to D02.

```sh
python3 -B - <<'PYDATA'
import hashlib, json, subprocess
from pathlib import Path
snapshot = json.loads(Path('plans/support/full-workflow-harness-mcp/source-inventory.json').read_text())
ledger = json.loads(Path('docs/workflow-mcp-coverage.json').read_text())
summary = Path('docs/workflow-mcp-coverage.md').read_text()
assert ledger['source_commit'] == snapshot['source_commit']
assert ledger['scope'] == snapshot['scope']
assert ledger['completeness'] == snapshot['completeness']
assert ledger['source_files'] == snapshot['source_files']
assert ledger['counts'] == snapshot['counts']
tracked = set(subprocess.check_output(
    ['git', 'ls-tree', '-r', '--name-only', snapshot['source_commit']], text=True).splitlines())
observed_only = {row['path'] for row in snapshot['source_files'] if row['path'] not in tracked}
assert observed_only == {
    'templates/local-automation-runtime/config.env',
    'templates/local-automation-runtime/local-validation.json',
    'templates/local-automation-runtime/projects.txt',
    'templates/local-automation-runtime/repos.txt',
}
assert ledger['observed_only_paths'] == sorted(observed_only)
for row in snapshot['source_files']:
    if row['path'] in tracked:
        raw = subprocess.check_output(['git', 'show', snapshot['source_commit'] + ':' + row['path']])
        assert hashlib.sha256(raw).hexdigest() == row['sha256'], row['path']
    assert row['path'] in summary, row['path']
assert len(ledger['entrypoints']) == len(snapshot['entrypoints'])
ids = set()
for old, new in zip(snapshot['entrypoints'], ledger['entrypoints']):
    for key, value in old.items():
        if key != 'operations':
            assert new[key] == value, (old['path'], key)
    assert len(new['operations']) == len(old['operations'])
    for previous, current in zip(old['operations'], new['operations']):
        assert all(current[k] == v for k, v in previous.items())
        assert current['id'] not in ids
        ids.add(current['id'])
        assert current['delivery_status'] in {'planned-daily', 'later-pending'}
        assert isinstance(current['acceptance_test'], str) and current['acceptance_test'].strip()
        assert current['id'] in summary, current['id']
assert 'NOT IMPLEMENTED' in summary and 'LATER LANES INCOMPLETE' in summary
print('G-COVERAGE-DATA pass:', len(snapshot['source_files']), 'source files;', len(ids), 'operation IDs')
PYDATA
```

  - Green means: D01 preserves snapshot hashes/dispositions/entrypoint metadata, verifies tracked-source bytes at the pin, explicitly labels the four local-observation-only rows via observed_only_paths, and preserves unique stable operation IDs, adds explicit planned/later delivery status plus named future acceptance targets, and renders every path/ID with incomplete-stage warnings. Its independent reviewer additionally checks that the stage and acceptance mappings are meaningful, not merely nonempty. A future acceptance_test value names required evidence, not a claim that an unbuilt test ran. The snapshot/spec pins must be present and hash-verified in the isolated checkout before admission; no copied snapshot is silently inferred. This gate is intentionally not the new-operation discovery/regression gate supplied by D02.
- G-COVERAGE:
  - Where it runs: CI and Local.
  - Entry point / command: `python3 scripts/check_workflow_mcp_coverage.py`; `python3 -m unittest discover -s tests -p test_workflow_mcp_coverage.py`.
  - Green means: every maintained operator entrypoint/subcommand has a source disposition and delivery status; newly introduced native operations cannot evade inventory; later lanes remain explicitly incomplete. The future docs ledger supersedes the immutable planning snapshot under plans/support; source hashes are refreshed by WS1 after implementation integration, rather than requiring changed source to match its preimplementation hash. Per-mode effects must be audited before that mode becomes executable.
- G-SELECTION:
  - Where it runs: CI and Local.
  - Entry point / command: `python3 -B -m unittest discover -s tests -p test_atlas_daily.py`.
  - Green means: default config follows resolved script checkout; explicit selection and source pin checks are shared; missing/contradictory config refuses without alternate installation or filesystem mutation.
- G-NATIVE:
  - Where it runs: CI and Local.
  - Entry point / command: `python3 -B -m unittest discover -s templates/local-automation-runtime/tests -p test_atlas_local_dev.py`.
  - Green means: existing daily lifecycle, pending-conflict concurrency, replay, original-byte import and goal-gate behavior remain correct after extraction.
- G-BRIDGE:
  - Where it runs: CI and Local.
  - Entry point / command: `python3 -B -m unittest discover -s templates/local-automation-runtime/tests -p test_atlas_daily_bridge.py`.
  - Green means: bridge rejects unsupported schemas and performs only named native operations; bounded original bytes and refusal codes preserved; no model/provider launch.
- G-MCP:
  - Where it runs: CI and Local.
  - Entry point / command: `python3 -B -m unittest discover -s tests -p test_harness_mcp.py`.
  - Green means: additive schemas/annotations agree with actual effects; prior tools preserve behavior; invalid arguments cannot reach native mutation.
- G-DAILY:
  - Where it runs: CI and Local.
  - Entry point / command: `python3 -B -m unittest discover -s tests -p test_harness_daily.py`.
  - Green means: explicit selection, hash-bound regular inputs, original-byte retention, descriptor-relative no-follow evidence traversal (including parent-symlink swaps), secret-sentinel no-echo errors (malformed input/hash mismatch/bridge stderr/unexpected exceptions), artifact-ID substitution, unrelated-work-item and private queue/config refusal, strict bridge base64 bounds, version isolation, caller ID conflicts/duplicate-call refusal, foreign/malformed/missing transport records, nonmutating adapter-status inspection, gap-free lifetime-lock publication/inheritance, single-read snapshot cursors, uncertain-add same-ID intake-projection reconciliation and conflict refusal, pre/post-admission selection drift, pending-only reservation views, multi-handoff artifact_required/unknown ID/view-kind mismatch cases, prepare repetition before/after accepted import, cursor drift and time/output bounds pass refusal and normal cases.
- G-INTEGRATION:
  - Where it runs: CI and Local.
  - Entry point / command: `python3 -B -m unittest discover -s tests -p test_harness_daily_integration.py`.
  - Green means: real MCP subprocesses and temporary installed runtime copies demonstrate full synthetic item lifecycle, independent goal gating, CLI/MCP parity, reconnect, dropped add response with same-intake reconciliation/conflicting ID/delayed original adapter, MCP-parent SIGKILL while the bridge remains live, parent death before spawn, child death before terminal receipt, concurrent same-call submission, spawn failure, timeout/overflow cleanup and failed cleanup, response loss, uncertain outcomes, alternating versions and exact replay. A new MCP process must report the delayed call active despite an absent work item; after controlled child exit it must report terminal without inventing success, then reconcile matching/conflicting/missing native items. Prepublication/missing-record uncertainty stays blocked. Probes must use actual subprocesses and advisory locks, not only mocked PIDs or timers. Network/model-launch tripwires remain quiet. Synthetic results are labeled fixtures.
- G-UPGRADE:
  - Where it runs: CI and Local.
  - Entry point / command: `python3 -B -m unittest discover -s tests -p test_sync_runtime_template.py`.
  - Green means: managed bridge copied appropriately, private config/state/repos/jobs preserved byte-for-byte, pending-bound snapshots and daily-adapter-calls transport evidence retained, rollback never overwrites newer receipts. Transport status remains inspectable after source cutover without converting diagnostic records into native lifecycle authority.
- G-REPO:
  - Where it runs: CI and Local.
  - Entry point / command: `python3 scripts/verify_repo.py` (existing Verify CI entrypoint).
  - Green means: affected and complete repository tests plus required source checks, generated adapter installation checks and whitespace verification pass. Do not repair unrelated dirty source to force green; report it distinctly.
- G-GOAL:
  - Where it runs: Local maintained queue review lifecycle.
  - Entry point / command: prepare/dispatch/import the separately reserved code-review, semantic-alignment and evidence-rollup roles under `docs/daily-development.md`; inspect the same item's final `daily status` and retained accepted receipts.
  - Green means: actual independent reviewers supply complete passing results tied to the frozen scope/source/results; imported implementation alone is insufficient. This gate is not replaced by a fabricated JSON review or root self-approval. Its explicit runtime/state/owner and qualified host route are prerequisites even for source acceptance; offline checks alone do not pass it. The user-confirmed NoneSelected state therefore blocks actual model-role admission and G-GOAL source acceptance while source-level deterministic preparation can proceed.
- G-LIVE:
  - Where it runs: Deployed (explicitly selected supervised local installation).
  - Entry point / command: MCP daily status/add/prepare/import/evidence for one admitted bounded item, actual qualified host dispatch of each exact packet, then original-runtime recovery and newly selected snapshot status as specified in Rollout / Rollback.
  - Green means: retained actual invocation IDs, reserved model/reasoning matches, original-byte hashes, all independent review roles and accepted goal survive reconnect and version cutover. Record source version, installed version, queue terminal state and next action.
  - Manual blocker: no execution installation is selected; the checkout default file is absent. Supervisor must obtain an explicitly selected existing installation (or a separately authorized setup proposal), verify route/account and bounded budget, and reconcile pending work before live qualification. This does not block source-level analysis, deterministic fixture/check preparation or offline checks; admitted model implementation/review roles and source acceptance requiring G-GOAL also require their explicit runtime/qualified route. It does not authorize bypassing the maintained lane. This plan grants no live execution, unattended, merge or publication authority.

### Merge points -> required gates
- MP0: first actual role admission - G-ADMISSION. Every later admitted child repeats this gate with its own exact context.
- MP1: source inventory and daily contract freeze - accepted D01 G-COVERAGE-DATA/G-GOAL followed by D02 G-COVERAGE/G-GOAL; neither item requires its dependent item to pass first.
- MP2: selection plus bridge integration - G-SELECTION, G-NATIVE, G-BRIDGE, G-GOAL.
- MP3: daily MCP source integration - G-MCP, G-DAILY, G-INTEGRATION, G-GOAL.
- MP4: guidance/upgrade/release integration - G-UPGRADE, G-REPO, G-GOAL.
- MP5: first-stage source acceptance - G-COVERAGE, G-INTEGRATION, G-REPO, G-GOAL.
- MP6: installed daily-lane qualification - MP5 evidence plus G-LIVE. Neither MP5 nor MP6 establishes all-lane completion.

### Test Matrix
| Area/component | Risk | Test type | Where it runs |
| --- | --- | --- | --- |
| Operation inventory | Missing supporting lanes or subcommands | Static discovery plus omission regression | CI/Local |
| Selection | Wrong installation, source drift, symlink default | Unit and real-process CLI | CI/Local |
| Native service/bridge | Semantic drift, cached runtime imports | CLI parity, two-version subprocess integration | CI/Local |
| Reservation/import | Duplicates, foreign ownership, changed bytes | Concurrency, response-loss and refusal integration | CI/Local |
| Evidence/transport | Secret leakage, arbitrary reads, truncation | Allowlist/refusal, bounded-output and pagination tests | CI/Local |
| Upgrade | Lost private state or invalid pending bindings | Temporary-install copy/recovery/rollback tests | CI/Local |
| Useful supervised execution | Fixtures mistaken for actual goal acceptance | Actual host receipts and independent review lifecycle | Deployed selected lane |

### Test plan (CI vs deployed)
- CI: existing `.github/workflows/verify.yml` runs `python3 scripts/verify_repo.py`; add coverage checking to that maintained verifier and keep all new tests discoverable. No provider/model account is required for fixtures.
- Local: run affected named gates before full G-REPO. Use temporary installed snapshots rather than executing source templates. Keep synthetic evidence distinct from actual role results.
- Deployed environment: G-LIVE only with explicit valid selection, qualified host route, admitted scope and budget. Retain actual errors and blocked attempts. A failed live qualification cannot erase source test results or grant additional authority.

### Rollout / Rollback
- Rollout: first finish source review/tests. Freeze accepted source SHA and install a new managed snapshot; do not overwrite an active daily installation. Before selecting it, inspect existing queue/pending handoffs with the original runtime and finish or explicitly reconcile the same invocations. Preserve old snapshots, private configuration/state and adapter-call receipts/lock files; do not cut over while a bound adapter call is active or its settlement remains unknown. Select the new snapshot explicitly and run read-only diagnosis before any separately authorized task. Record version, source fingerprint, validation, reviews, queue state and next action.
- General-runtime upgrade: if a later lane requires changing a general installed runtime, first run repository verification and compare managed files; back up before overwrite, preserve config.env/codex-home/jobs/logs/repos/state/local validation, compare example keys without printing secrets, and run its `./check_runtime.sh` plus bounded non-mutating verification. Container rebuild is required only if reviewed container source changes.
- Rollback trigger: incompatible bridge, source/provenance mismatch, selection ambiguity, lost evidence, unexpected mutation, failed replay/acceptance or leaked sensitive content.
- Rollback steps: stop new intake/prepare and preserve uncertainty; inspect/recover outstanding work with its bound original snapshot, adapter-call settlement and observed host invocation. Preserve adapter-call directories and never replace/delete lifetime lock files as a recovery shortcut. Select the previous compatible snapshot explicitly after reconciliation; do not restore old queue or jobs over newer receipts, alter reservations, normalize worker files or delete attempts. Retain refusal evidence and create an explicit reviewed repair/successor if required.

### Remaining lane stages (tracking-only roadmap)
After daily-first acceptance, select bounded child plans from the coverage ledger for local team/work-item recovery; GitHub issue/PR lifecycle; GitHub Actions; Azure governed lifecycle; operator repair/throttle/cleanup; registration/setup/general upgrades; deployment wrappers and notification/summary integrations. Each child must name exact native actions, current authority, schemas, affected files and acceptance checks before becoming executable. This plan does not silently exclude deploy wrappers or cloud-changing “dry-run”/pause commands. No child plan file is created or implicitly selected here. Full campaign completion requires the operation ledger to show implemented, independently accepted MCP paths for all maintained supported operations, or explicit user-accepted exclusions; daily-first acceptance is only the first stage.

## Automation Issue Manifest

AutomationTarget: none. No issue projection, dispatch manifest or unattended execution requested. The six ownership containers and twelve delivery packages are not runtime queue intake or dispatch authorization. AutomationTarget:none excludes issue projection/unattended issue automation; it does not waive the local daily G-ADMISSION contract. Complex coding packages stay blocked under DR-006. Later lane stages are tracking-only.

## Planning Reviews

### Repair freshness and prior evidence
- Current status: Stale after DR-005 and material F-401/F-402 repairs under DR-007. No fresh independent review/readback was performed by the repair author.
- Prior reviewed hash: sha256:fc89e2dafd14c8b7a87c83531c76a15b476882fe6ae7d6a8e0f941aa84f3be5c. The nine records below remain preserved as historical design reviews, not current passes. Their hashes must not be updated merely to carry the old verdicts forward.
- Freshness scope: re-entry audit before repair identified F-301/F-302; it did not review the repaired artifact. Source-based sizing proposal supplied package estimates and constraints; it is not an authentic task-bound runtime sizing receipt.
- Next independent step: fresh execution-readiness/admission review of the repaired selected plan, including G-ADMISSION, package scopes/flags, points arithmetic and execution/target bootstrap; then a separate user readback. No reviewer is run or claimed fresh as a consequence of these author edits.
- Current readbacks: DR-001/DR-002/DR-004 decisions remain accepted history. The repaired admission contract has not received fresh readback or implementation authorization.
- F-401/F-402 author repairs: dispositioned in Context Snapshot/DR-007, not independently re-reviewed. Fresh API/runtime/operator review must check call-ID fencing, lock lifetime/publication, MCP-parent death and D01/D02 acceptance order. Historical reviewed hashes below are unchanged.
- Original finding aliases and dispositions below are retained without claiming they cover new text.

### Zero-Context Review
- Reviewer: zero_context_review
- RefreshedAt: 2026-11-10T23:00:50Z
- ReviewedPlanHash: sha256:fc89e2dafd14c8b7a87c83531c76a15b476882fe6ae7d6a8e0f941aa84f3be5c
- Re-entry audit answers:
  - What is being built: Five daily MCP tools, shared selection/native services, isolated installed bridge and bounded evidence access.
  - Why now: Essential supervised lifecycle operations currently require CLI fallback.
  - Repos involved: AtlasMemory-Tools; installed snapshots and state remain separate operator records.
  - What changes first: Coverage ledger/checker, shared selection and native service/bridge extraction.
  - What must not happen: Duplicate dispatch, fabricated evidence, implicit installation selection, lifecycle bypass or daily-only full-harness claims.
  - How work is validated: Named source/parity/integrity/reconnect/upgrade/repository/independent-goal checks; actual live acceptance separate from fixtures.
  - What remains blocked: Actual role admission and G-GOAL need qualified explicit custody/host route; G-LIVE needs real supervised independent acceptance; later lanes need child contracts.
- Missing context: None blocking for the daily-first design.
- Contradictions:
  - F-001: (Resolved) Phase 2 now proves bridge isolation before Phase 3 actual MCP integration.
  - F-002: (Resolved) G-GOAL explicitly requires actual custody/qualified route for source acceptance; offline checks are insufficient.
- Unclear decisions: None blocking.
- Risks and edge cases: Oversized reservations and later per-mode contracts remain explicit acceptance limitations.
- What I would screw up implementing tomorrow: Corrected phase order and prerequisite statements prevent the two identified mistakes.
- Disposition:
  - Accept: F-001 -> DR-003.
  - Accept: F-002 -> DR-003, consistent with DR-004.
- Pass/fail statement: Pass for the daily-first design and all-lane roadmap boundary.

### Implementer Readiness Review
- Reviewer: implementer_review
- RefreshedAt: 2026-11-10T23:00:52Z
- ReviewedPlanHash: sha256:fc89e2dafd14c8b7a87c83531c76a15b476882fe6ae7d6a8e0f941aa84f3be5c
- Top 5 gotchas:
  - F-001: (Resolved) Phase 2 bridge tests precede Phase 3 MCP-session tests.
  - F-002: (Resolved) G-GOAL requires explicit execution selection, qualified route and real custody even for source acceptance.
  - F-003: Non-blocker: prepare replay is pending-only; global idempotence is not advertised.
  - F-004: Non-blocker: original bytes cross bounded hash-verified base64 transport without reserialization.
  - F-005: Non-blocker: source checks, live daily acceptance and full-harness completion remain separate.
- Evidence needed to prevent each gotcha: G-BRIDGE/G-INTEGRATION phase order; actual G-GOAL role receipts; G-DAILY before/after-import prepare tests; native/bridge/MCP byte parity; DR-004 live milestone and later-lane tracking.
- Pass/fail readiness statement: Pass for the bounded first-stage design. Execution still needs a separate instruction, sizing, selection, qualified route and reconciled custody.
- Disposition:
  - Accept: F-001 -> DR-003.
  - Accept: F-002 -> DR-003.
  - Reject: F-003 as a blocker; contract and tests are explicit.
  - Reject: F-004 as a blocker; original-byte requirements are explicit.
  - Reject: F-005 as a blocker; staged acceptance boundaries are explicit.

### Expert Technical Review
- Reviewer: contract_integrity_review
- RefreshedAt: 2026-11-10T23:00:15Z
- ReviewedPlanHash: sha256:fc89e2dafd14c8b7a87c83531c76a15b476882fe6ae7d6a8e0f941aa84f3be5c
- Technical risks and integration gaps:
  - F-201 (original F-API-001): (Resolved) Prepare is non-idempotent; exact replay is conditional on the existing owned pending reservation.
  - F-202 (original F-API-002): (Resolved) Wire schema carries exact base64 bytes with strict hash/size/aggregate validation.
- Missing validations or operational steps:
  - F-203 (original F-API-003): (Resolved) Queue rows and cursor hashes use the same snapshot; artifact cursors bind independently mutable inputs.
  - F-204 (original F-API-004): (Resolved) Selection freezes at admission; later drift neither changes target nor claims rollback.
- Contradictions with stated invariants or authority boundaries:
  - F-205 (original F-API-005): (Resolved) Reservation export is pending-only; historical views require known artifact IDs and cannot reconstruct old packets.
- Patch suggestions: None blocking. Uncertain-add projection recovery and named refusal/recovery tests preserve native semantics.
- Disposition:
  - Accept: F-201 -> DR-003.
  - Accept: F-202 -> DR-003.
  - Accept: F-203 -> DR-003.
  - Accept: F-204 -> DR-003.
  - Accept: F-205 -> DR-003.
- TechnicalClarity: Pass for the bounded daily stage and campaign structure.

### Security/Privacy Review
- Reviewer: security_review
- RefreshedAt: 2026-11-10T23:00:21Z
- ReviewedPlanHash: sha256:fc89e2dafd14c8b7a87c83531c76a15b476882fe6ae7d6a8e0f941aa84f3be5c
- Security/privacy risks:
  - F-101 (original SP-F001): (Resolved) Descriptor-relative no-follow traversal and final ownership/type/hash checks preserve the artifact boundary.
  - F-102 (original SP-F002): (Resolved) Confidentiality wording excludes private stores/logs without promising free-text evidence is secret-free.
- Missing validations or mitigations:
  - F-103 (original SP-F003): (Resolved) G-DAILY covers symlink swaps, substitution, foreign/private artifacts and secret-sentinel no-echo failures.
- Patch suggestions: None blocking; opaque artifact/view checks and semantic uncertain-add reconciliation preserve the chosen boundaries.
- Disposition:
  - Accept: F-101 -> DR-003.
  - Accept: F-102 -> DR-003.
  - Accept: F-103 -> DR-003.
- Pass/fail security statement: Pass for specified requirements; implementation and installed qualification remain unproven.

### Human Readability Review
- Reviewer: readability_review
- RefreshedAt: 2026-11-10T23:00:32Z
- ReviewedPlanHash: sha256:fc89e2dafd14c8b7a87c83531c76a15b476882fe6ae7d6a8e0f941aa84f3be5c
- Product/system clarity: Daily-first implementation is distinct from tracking-only later lanes and full-harness completion.
- Technical narrative clarity: MCP validates/projects, native services change lifecycle state, the supervisor dispatches agents and independent reviewers judge goals.
- Execution-mechanics leakage: Necessary reservation/byte/artifact/recovery behavior is explained; file ownership/checks/rollout remain in Implementation Plan.
- Strongest remaining ambiguity:
  - F-001: Non-blocker: unreadable execution selection and unverified route/custody are explicit operational blockers, not hidden design decisions. Later lanes require bounded contracts.
- Pass/fail readability statement: Pass. All seven plain-technical-English meaning criteria pass; no additional human decision.
- Disposition:
  - Reject: F-001 as a readability blocker; actor, prerequisites, evidence and consequences are explicit.

### Dynamic Specialist Review Roster
- Reviewer: review_roster
- RefreshedAt: 2026-11-10T23:01:09Z
- ReviewedPlanHash: sha256:fc89e2dafd14c8b7a87c83531c76a15b476882fe6ae7d6a8e0f941aa84f3be5c
- Triggered specialist review rationale:
  - F-001: API/contracts; additive tools, versioned encoding, mutation/replay/refusal semantics. Hooks: G-MCP/G-DAILY, CI/Local, exact commands below; green means contracts and actual effects agree.
  - F-002: Data integrity/concurrency and runtime recovery; bytes, claims, response loss, snapshots and cutover. Hooks: G-NATIVE/G-INTEGRATION/G-UPGRADE, CI/Local; green means custody/bytes/newer evidence survive.
  - F-003: Operator workflow; uncertain add/prepare/import, missing packets/configuration and independent acceptance. Hooks: G-INTEGRATION plus G-GOAL/G-LIVE, selected qualified lane; green means explicit next actions without duplicate work.
  - F-004: Security/privacy; input capture, work-bound evidence, ownership/no-follow/no-echo. Hooks: G-DAILY/G-BRIDGE, CI/Local; green means refusal without private-content echo or arbitrary launch.
- Skipped specialist review rationale:
  - F-005: Cloud/provider infrastructure/deployment/messaging are later tracking-only; no new first-stage provider effect. Later child plans must review them; no-launch tripwires remain.
  - F-006: No database or persistent queue-schema migration proposed; file-state integrity is covered separately.
  - F-007: No new spending/model route; API/runtime reviews cover process/output budgets and disclosed native queue-memory limitation.
  - F-008: No graphical UI; operator workflow has its own pass.
- Missing or deferred specialist coverage:
  - F-009: No additional domain missing. Overall completion is conditional on actual final passing records for API, runtime, operator and security; those records are attached below/above for this exact hash.
- Triggered specialist reviews: API/contracts; Data integrity and runtime recovery; Operator workflow; dedicated Security/Privacy. Status: Complete for plan review only.
- Reviews considered but not triggered: cloud/provider infra, database/migrations, additional cost specialist, graphical UI; rationale above.
- Disposition:
  - Accept: F-001 -> DR-003; actual dedicated pass attached.
  - Accept: F-002 -> DR-003; actual dedicated pass attached.
  - Accept: F-003 -> DR-003; actual dedicated pass attached.
  - Accept: F-004 -> DR-003; actual dedicated pass attached.
  - Reject: F-005 as an additional first-stage review requirement; later scope only.
  - Reject: F-006 as an additional requirement; no proposed database/schema migration.
  - Reject: F-007 as an additional requirement; no new spending route.
  - Reject: F-008 as an additional requirement; no graphical UI.
  - Accept: F-009 -> DR-003; require the attached actual verdicts, not roster assertions.

### Specialist Review: API/contracts
- Reviewer: api_specialist
- RefreshedAt: 2026-11-10T23:01:22Z
- ReviewedPlanHash: sha256:fc89e2dafd14c8b7a87c83531c76a15b476882fe6ae7d6a8e0f941aa84f3be5c
- Domain risks and integration gaps:
  - F-001: (Resolved) Historical views require explicit known artifact IDs; index and current pending reservation have deterministic rules; foreign/mismatched IDs refuse.
- Missing validations or operational steps:
  - F-002: (Resolved) G-DAILY covers multiple handoffs, missing/unknown IDs and view-kind mismatch.
- Contradictions with stated invariants or authority boundaries: None blocking.
- Patch suggestions: None required.
- Disposition:
  - Accept: F-001 -> DR-003.
  - Accept: F-002 -> DR-003.
- Pass/fail statement: Pass for daily-first API design; not implementation/live/full coverage evidence.

### Specialist Review: Data integrity and runtime recovery
- Reviewer: runtime_specialist
- RefreshedAt: 2026-11-10T23:01:25Z
- ReviewedPlanHash: sha256:fc89e2dafd14c8b7a87c83531c76a15b476882fe6ae7d6a8e0f941aa84f3be5c
- Domain risks and integration gaps: No blocking gaps. Original bytes, native parity, replay, snapshots, selection admission, isolation and state-preserving rollback are explicit. Lost-add recovery does not invent intake-byte retention or infer a failed mutation from missing state.
- Missing validations or operational steps:
  - F-001: Non-blocker: native queue loading is unbounded; pagination's claim is explicitly limited to response size. Named G-DAILY/G-INTEGRATION cases cover matching/conflicting intake, delayed adapters and historical artifact selection.
- Contradictions with stated invariants or authority boundaries: None found; planning bookkeeping establishes no implementation or launch authority.
- Patch suggestions: None required.
- Disposition:
  - Reject: F-001 as an additional first-stage blocker; limitation is disclosed.
- Pass/fail statement: Pass for the frozen daily-first candidate.

### Specialist Review: Operator workflow
- Reviewer: operator_specialist
- RefreshedAt: 2026-11-10T23:01:45Z
- ReviewedPlanHash: sha256:fc89e2dafd14c8b7a87c83531c76a15b476882fe6ae7d6a8e0f941aa84f3be5c
- Domain risks and integration gaps:
  - F-001: (Resolved) Same-ID observed intake projection distinguishes matching admission from conflict after lost add response. Missing state does not prove an unsettled adapter failed.
- Missing validations or operational steps:
  - F-002: (Resolved) G-DAILY/G-INTEGRATION cover response loss, matching/conflicting identity and delayed adapter; native duplicate refusal remains.
- Contradictions with stated invariants or authority boundaries: None blocking; reservation/invocation/import/goal acceptance remain distinct, original custody and newer evidence survive upgrades.
- Patch suggestions: None blocking.
- Disposition:
  - Accept: F-001 -> DR-003.
  - Accept: F-002 -> DR-003.
- Pass/fail statement: Pass for the daily-first operator design; not live or implementation evidence.

### Automation Readiness Review
- Status: N/A; rationale: AutomationTarget is none. No issue projection or unattended dispatch requested, and no manifest has been admitted.

## Execution Mechanics / Automation Appendix

### Authority / source-of-truth contract
- Authoring intent: this selected Markdown document.
- Supervised execution truth: local queue, reservations, original role bytes and observed receipts.
- Provider execution truth: existing native provider records and local run evidence; no remote comment message bus.
- No issue projection or dispatch requested; AutomationTarget is none for this planning invocation.

### Upgrade requirements carried from the invoked skill
- Select the installation explicitly; record source/runtime versions, checksums and configuration key names without values containing secrets.
- Run `python3 scripts/verify_repo.py` before copying template-managed files.
- Preserve config.env, codex-home, jobs, logs, repos, state, validation evidence and secrets; back up before overwriting managed content.
- Daily upgrades use a new pinned snapshot after old handoffs are recovered; keep the old snapshot.
- Validate affected tests, `./check_runtime.sh` for the applicable general runtime, and a bounded non-mutating check. Verify generated harness copies where installed.
- Rollback must not restore old queue bytes over newer receipts or evidence.
- No installation or configuration changes have occurred in this invocation.

## Execution Status

Phase: Plan repair complete; admission preparation and fresh review pending
Status: blocked

Completed tasks:
- Preserved before snapshot outside Git and performed zero-context re-entry audit.
- Reconciled F-301/F-302 and source-backed policy/template/bootstrap/budget/estimate findings under DR-005.
- Added twelve delivery packages totaling 68 provisional points, exact blockers and admission evidence requirements; did not construct passing runtime packets.
- User confirmed no execution installation is selected. No private config or runtime state changed.
- Reconciled F-401/F-402 under DR-007: specified restart-safe adapter-call settlement and independent D01 data acceptance before D02; dependent schemas, package targets, gates and rollout were updated. These are author repairs only.

Blocked:
- B-SEL/B-ROUTE/B-SIZ/B-CPL/B-REV remain open as listed above.
- User explicitly withholds execution authorization pending readiness judgment.
- D03–D11 coding admission is not resolved by stronger models, smaller labels or previous design review passes.
- Actual first daily milestone and installed qualification require G-GOAL/G-LIVE; later lanes remain tracking-only.

Checks:
- Plan validator rerun after repair: IntentModelComplete, ProblemDefinitionComplete, mechanical PlanReadiness and PlanStateSanity pass; AutomationReadiness is N/A; PlanningReviewsComplete fails on stale review hashes. Semantic admission remains blocked and the authoring PlanReadiness gate remains Fail. Stale review hashes are not a waiver. G-COVERAGE-DATA is a future D01 validation command: the two deliverable files do not exist yet, so this repair must not claim it passed against delivered data.
- The embedded D01 command was exercised only against temporary synthetic data, including omission/disposition/warning refusals; this verifies the validation recipe, not D01 delivery or source implementation.
- No implementation tests, live jobs, queue mutations, installations, publication or merge were performed in this repair.

Next actions:
- Fresh independent execution-readiness/admission review, followed by user readback of repaired boundaries.
- Resolve the exact first packet and runtime/route prerequisites before requesting execution authorization. Do not infer authorization from a plan-repair instruction.
