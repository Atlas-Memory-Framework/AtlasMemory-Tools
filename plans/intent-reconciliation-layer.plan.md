# Feature: Intent Reconciliation Layer

## Plan State
PlanFormatVersion: 2
PlanId: intent-reconciliation-layer
PlanGroup: planning-hardening
PlanKind: feature
ParentPlan: none
DependsOnPlans: none
BlocksPlans: future issue-projection and unattended-prs planning hardening
AtomicScope: Add an intent-preservation layer to AtlasMemory-Tools planning without replacing the existing /plan workflow.
CampaignMetadataAuthority: descriptive-only; explicit @path authoring artifact selection wins
Status: Draft
StructuralStatus: Draft
SubstanceStatus: NeedsWork
ProjectionApproval: NotRequested
DispatchApproval: NotRequested
CurrentStage: Implementation
PlanTier: Full
AutomationTarget: none
DeliveryMode: DevOnly
ContextMode: RepoInferred
LastUpdated: 2026-06-17
PrimaryOwner: mat
BaseBranch: main
BaseCommit: d2421bd36f39f931a5dc1895917d25e4232f3860
TargetBranch: feat/intent-reconciliation-layer
Related: current chat request
NextRequiredUserAction: none
BlockingDecision: none
UnresolvedBlockers: 0
RubberStampSignals: 0
LastGateRun: 2026-06-17

ArtifactAuthorityMode: legacy-plan

## Gate Results
IntentModelComplete: Pass
ProblemDefinitionComplete: Pass
FeatureClarity: Fail
TechnicalClarity: Fail
HumanReadabilityReview: N/A
PlanReadiness: Pass
AutomationReadiness: N/A
PlanningReviewsComplete: Fail

## Decision Log
### DR-001: Intent section enforcement mode
- Stage: Problem
- Date: 2026-06-17
- ScopeAffected: skills/plan/SKILL.md, skills/plan/reference.md, skills/plan/scripts/validate_plan.py, tests/test_plan_validator.py
- Decision: A) Add `## Intent Model` as a required warning-only validator result for all plans, blocking only for `PlanTier: Full` or `AutomationTarget: unattended-prs`.
- Options considered:
  - A) Add `## Intent Model` as a required warning-only validator result for all plans, blocking only for `PlanTier: Full` or `AutomationTarget: unattended-prs`.
  - B) Add `## Intent Model` as a hard requirement for every plan immediately.
  - C) Add `## Intent Model` as documentation-only in the first PR and defer mechanical validation.
- Why chosen: User confirmed this default on 2026-06-17; it protects high-risk zero-interaction work while avoiding unnecessary churn for lightweight plans.
- Consequences / follow-ups: A gives the best migration path because existing plans and tests can adapt gradually while high-risk plans stop pretending readiness when latent intent is unresolved.
- Status: Accepted
- Revisit trigger (if not Accepted): none

### DR-002: New skill versus expanding problem-definition
- Stage: Problem
- Date: 2026-06-17
- ScopeAffected: skills/intent-reconciliation/SKILL.md, skills/problem-definition/SKILL.md, skills/plan/SKILL.md
- Decision: A) Create a new `intent-reconciliation` skill and make `/plan` call it before or inside `ProblemDefinitionComplete`.
- Options considered:
  - A) Create a new `intent-reconciliation` skill and make `/plan` call it before or inside `ProblemDefinitionComplete`.
  - B) Fold all intent-model behavior into `problem-definition`.
  - C) Do only reviewer-side intent checks in `plan-execution-readiness` and avoid a new authoring skill.
- Why chosen: User confirmed this default on 2026-06-17; the boundary keeps expression-to-intent mapping distinct from problem framing.
- Consequences / follow-ups: A keeps problem framing separate from expression-to-intent mapping and makes the new section owner explicit.
- Status: Accepted
- Revisit trigger (if not Accepted): none

### DR-003: Generated adapter refresh timing
- Stage: Implementation
- Date: 2026-06-17
- ScopeAffected: .codex/skills, manifests/atlas-tools.v1.json, scripts/verify_harness.py
- Decision: A) Update source files first and regenerate checked-in Codex adapters in the same implementation PR.
- Options considered:
  - A) Update source files first and regenerate checked-in Codex adapters in the same implementation PR.
  - B) Update source files first and make adapter regeneration a follow-up PR.
  - C) Update source files only and leave generated adapters intentionally stale until a later harness release.
- Why chosen: User confirmed this default on 2026-06-17; checked-in adapters should match source behavior after the change.
- Consequences / follow-ups: A gives the cleanest repo verification result but increases PR size; B keeps the semantic change easier to review; C is fastest but risks local Codex behavior not matching source skills.
- Status: Accepted
- Revisit trigger (if not Accepted): none

### DR-004: Build before formal planning reviews
- Stage: Build
- Date: 2026-06-17
- ScopeAffected: plans/intent-reconciliation-layer.plan.md
- Decision: Proceed with implementation after explicit user approval, while keeping `PlanningReviewsComplete: Fail` until formal reviews are run.
- Options considered:
  - A) Proceed now with implementation and record the review gap.
  - B) Stop and run full planning reviews before editing source files.
  - C) Limit work to documentation only.
- Why chosen: User explicitly said "Lets build it" after accepting the blocking decisions. The change is local tooling, docs, and tests with no production data, auth, external effects, or deployment surface.
- Consequences / follow-ups: Final status must not claim `SubstantivelyReviewed` or `ApprovedForDispatch`; verification and review gaps remain visible.
- Status: Accepted
- Revisit trigger (if not Accepted): none

## Risks / Assumptions / Tests
- R1 (High): The new layer becomes planning ceremony instead of preserving user intent.
  - Mitigation: Keep the MVP to one section, one skill, one reviewer persona, and one validator check; require concrete open loops and wrong-but-plausible implementation examples.
  - Owner: plan
  - Status: Accepted
  - Trigger (if deferred): none
- R2 (High): Blocking every existing plan on `## Intent Model` causes immediate workflow churn.
  - Mitigation: Start warning-style or block only `PlanTier: Full` / `AutomationTarget: unattended-prs`, depending on DR-001.
  - Owner: plan
  - Status: Accepted
  - Trigger (if deferred): none
- R3 (Medium): Runtime reviewers produce noisy subjective findings.
  - Mitigation: Add one optional `intent_gap_type` enum and one persona first; require evidence tied to plan text and user expression.
  - Owner: local-plan-agent-runtime
  - Status: Accepted
  - Trigger (if deferred): none
- A1: `skills/` is the source implementation surface and `.codex/skills/` is generated adapter output.
  - Test: README states source skills live under `skills/` and generated harness files should not be edited directly.
  - Pass/Fail criteria: Changes target `skills/` first and generated-copy verification is run before publishing.
  - Status: Tested
- A2: Existing plan validation can absorb a new gate result without broad architectural rewrite.
  - Test: `skills/plan/scripts/validate_plan.py` already uses small `GateResult` functions and tests import it directly.
  - Pass/Fail criteria: New `IntentModelComplete` tests run with `python3 -m unittest tests.test_plan_validator`.
  - Status: Tested

## Intent Model
<!-- owner: intent-reconciliation -->
Latent target:
- Make the planning system preserve the thing the user actually means before it turns that idea into polished execution prose.
- Add a practical anti-loss layer to AtlasMemory-Tools planning, not an abstract Atlas ontology.
- Let future zero-context agents see what would satisfy the user's intended outcome and what plausible output would miss it.
- Confidence: High.

Anti-targets:
- Do not build this first in Atlas proper as a cognition layer.
- Do not replace `/plan` with a new workflow.
- Do not add a new formal `CurrentStage` until the additive layer proves useful.
- Do not overload the first MVP with multiple personas, a new registry schema, or broad historical migrations.

Expression-state notes:
- User phrase: "messy user intent -> plan artifact -> agentic review -> open-loop ledger -> intent checksum -> implementation-readiness gate"
  - Interpreted meaning: The workflow needs a closed loop that tracks unresolved expression-to-intent gaps before implementation.
  - Alternate interpretations: A full semantic memory system; a planning review checklist only; a new runtime pipeline.
  - Confidence: High.
  - Risk if wrong: The implementation either becomes too abstract or too shallow.
- User phrase: "not build this first as an Atlas cognition layer"
  - Interpreted meaning: Keep the work in AtlasMemory-Tools as a planning hardening layer.
  - Alternate interpretations: Never build Atlas cognition support; build only documentation.
  - Confidence: High.
  - Risk if wrong: Scope drifts into runtime memory architecture prematurely.
- User phrase: "unresolved latent intent"
  - Interpreted meaning: A typed planning object for meaning not captured by open questions, blockers, or decision boundaries.
  - Alternate interpretations: Another name for open questions; subjective review commentary.
  - Confidence: High.
  - Risk if wrong: The new section duplicates existing plan fields and adds noise.

Open Loop Ledger:
- OL-001:
  - Type: scope-gap
  - Source: user proposal and repo inspection
  - Latent object: Validator enforcement level for the new section.
  - Why it matters: Too strict breaks existing plans; too weak will not protect unattended execution.
  - Candidate interpretations:
    - A) Warning for ordinary plans, fail for Full/unattended risk.
    - B) Hard fail for every plan.
    - C) Documentation-only first.
  - Status: Resolved
  - Resolution evidence: DR-001 accepted by user on 2026-06-17.
  - Blocks: none
- OL-002:
  - Type: concept-gap
  - Source: user proposal
  - Latent object: Ownership boundary between problem framing and intent reconciliation.
  - Why it matters: Combining them may flatten the very distinction this feature is meant to preserve.
  - Candidate interpretations:
    - A) New section-owner skill.
    - B) Expand problem-definition.
    - C) Review-only layer.
  - Status: Resolved
  - Resolution evidence: DR-002 accepted by user on 2026-06-17.
  - Blocks: none
- OL-003:
  - Type: acceptance-gap
  - Source: plan authoring design
  - Latent object: What counts as a good Intent Model in practice.
  - Why it matters: The section must be specific enough to prevent wrong-but-plausible builds, not just repeat the problem statement.
  - Candidate interpretations:
    - A) Require at least one wrong-but-plausible implementation example and any open loops that block downstream stages.
    - B) Require only latent target and anti-targets.
    - C) Require open-loop ledger entries for every ambiguity.
  - Status: Deferred
  - Resolution evidence: First implementation PR review and validator tests.
  - Blocks: none

Intent checksum:
- Success means:
  - A future implementer can read `## Intent Model` and explain the latent target, anti-targets, unresolved open loops, and likely wrong-but-plausible implementation before touching files.
  - A readiness reviewer can fail a mechanically complete plan because it does not preserve the user's latent target.
  - A semantic-alignment reviewer can compare a PR against intent context, not just task completion.
- Failure would look like:
  - The repo gains another template section filled with generic text.
  - Validators pass because labels are present even though the target was flattened.
  - Runtime reviewers produce subjective comments that cannot be converted into decisions, plan patches, or tests.
- User confirmation needed:
  - Confirmed DR-001 enforcement mode.
  - Confirmed DR-002 ownership model.
  - Confirmed DR-003 adapter refresh timing.

## Problem Definition
Problem narrative:
Current authoring flow turns messy user expression into crisp execution text too quickly. That works when the user's target is already explicit, but it fails when the real target is experiential, negative, architectural, or partly unspoken: the document can sound accurate while preserving the wrong thing.

The desired workflow is that AtlasMemory-Tools captures the latent target, anti-targets, expression-state risks, open loops, and a short checksum before downstream sections convert the work into architecture, implementation tasks, tracker work, or unattended execution. Future agents should be able to see not only what to build, but what plausible wrong implementation would miss the user's actual intent.

Current broken workflow:
- `## Problem Definition` captures current workflow, desired workflow, success criteria, constraints, scope, open questions, and decision boundaries, but it does not model whether the user's words faithfully encode the latent target.
- `plan-execution-readiness` asks whether agents will build the intended product, but its checklist has no explicit intent-model section to verify.
- `local-plan-agent-runtime` can fan out reviewer personas, but its persona list and proposal schema do not classify latent intent gaps.
- Work-item semantic roles catch drift after planning or implementation, but the upstream plan does not provide a stable intent object for them to compare against.

Desired workflow:
- `/plan` creates or updates a plan with an explicit `## Intent Model` before problem framing, context snapshot, and technical conversion steps.
- A new `intent-reconciliation` skill drafts the section without writing the plan directly.
- `problem-definition`, `plan-execution-readiness`, and planning reviewers preserve the latent target and anti-targets instead of flattening them into generic implementation prose.
- The local plan-agent runtime can run one focused intent reviewer persona and classify intent findings without changing worker authority.
- Validator support starts conservatively and becomes blocking only where zero-interaction execution risk justifies it.

Why this matters / why now:
- The repo already has the control points for planning, review, issue projection, local agent execution, and semantic review. Adding intent preservation here gives an immediate test loop before building any Atlas cognition-layer abstraction.
- The highest-risk failure is not a missing task; it is a polished plan that allows agents to build something plausible but semantically wrong.
- The system is already moving toward zero-interaction implementers and unattended PR execution, so latent-intent gaps must become visible before dispatch.

Current-state facts:
- Fact 1: README names `skills/`, `agents/`, `templates/local-automation-runtime/`, and `manifests/atlas-tools.v1.json` as the repo-owned planning and automation surfaces. (source: file)
- Fact 2: `skills/plan/SKILL.md` requires zero-interaction implementer readiness and says missing implementation-critical intent should block or be captured before advancement. (source: file)
- Fact 3: `skills/plan/reference.md` currently starts product substance at `## Problem Definition`; there is no preceding `## Intent Model` section. (source: file)
- Fact 4: `skills/local-plan-agent-runtime/references/personas.md` includes product-spine and human-readability reviewers but no intent-reconciliation reviewer. (source: file)
- Fact 5: `skills/local-plan-agent-runtime/references/proposal-schema.md` has finding fields for issue/remediation/decision options but no intent-gap classification. (source: file)
- Fact 6: `skills/plan/scripts/validate_plan.py` has gate checks for problem, implementation, automation, reviews, and plan state sanity but no intent-model gate. (source: file)

Success criteria (measurable):
- SC1: New plans created from `skills/plan/reference.md` include `## Intent Model` before `## Problem Definition`.
- SC2: A new `skills/intent-reconciliation/SKILL.md` defines a draft-section contract with latent target, anti-targets, expression-state notes, open-loop ledger, checksum, checklist, questions, and notes.
- SC3: `plan-execution-readiness` explicitly reviews whether the problem, technical plan, implementation plan, and tests preserve the latent target and anti-targets.
- SC4: `local-plan-agent-runtime` can validate proposals that include optional `intent_gap_type` without breaking existing proposal packets.
- SC5: The validator has tests showing missing or blocking intent model content is surfaced according to the selected enforcement mode from DR-001.
- SC6: Team templates and semantic agents consume `## Intent Model` as an alignment input for planning and work-item review.

Constraints:
- Preserve `/plan` as the public workflow and canonical writer.
- Do not add a new persisted `CurrentStage` value for Intent in the first implementation.
- Do not let runtime workers write canonical plans, flip gates, approve projection, or encode human-agency decisions.
- Update repo-native `skills/`, `agents/`, `templates/`, `docs/`, and `tests/` first; generated `.codex/` copies are adapter outputs.
- Keep the first release additive and boring: one section, one skill, one persona, one optional schema field, one validator check.

Scope:
- In scope:
  - Add `## Intent Model` before `## Problem Definition` in the plan template.
  - Add `intent-reconciliation` as a section-owner skill.
  - Update `/plan` instructions and problem-definition guidance.
  - Update plan-execution-readiness checklist and finding schema.
  - Add one local-plan-agent-runtime persona and optional intent-gap field.
  - Add conservative validator support and focused tests.
  - Update workflow templates and semantic agents to consume intent context.
- Out of scope:
  - Building an Atlas cognition or memory runtime abstraction.
  - Replacing markdown plans with a registry-first intent store.
  - Adding multiple new personas at once.
  - Dispatching GitHub issues or unattended PR automation from this plan.
  - Retrofitting every historical plan in this repo in the first pass.

Definitions / glossary:
- Latent target: The result the user appears to be trying to achieve, including non-verbal or experiential aims not fully expressed as implementation requirements.
- Anti-target: A result the user is reacting against or explicitly does not want, including genericization, over-literalization, or wrong-feeling solutions.
- Expression-state note: A mapping from a user phrase to interpreted meaning, plausible alternatives, confidence, and risk if misread.
- Open loop: An unresolved expression-to-intent gap that could cause downstream agents to build the wrong thing.
- Intent checksum: A short alignment test describing success, likely wrong-but-plausible output, and any confirmation prompt needed.

Open questions:
- Q1: Should the first validator version block only high-risk plans or all plans?
  - Status: Resolved (DR-001)
  - Trigger (if Deferred): Before validator implementation.
- Q2: Should intent reconciliation be a new skill or part of problem-definition?
  - Status: Resolved (DR-002)
  - Trigger (if Deferred): Before skill implementation.

Decision boundaries (if any):
- Decision needed: Intent section enforcement mode.
  - A) Add warning-style validator behavior and block only `PlanTier: Full` or `AutomationTarget: unattended-prs`.
  - B) Hard-block every plan missing `## Intent Model`.
  - C) Documentation-only first release.
Recommended default: A (preserves safety for zero-interaction work without breaking every existing lightweight plan).
- Decision needed: Section ownership model.
  - A) New `intent-reconciliation` skill owns `## Intent Model`.
  - B) `problem-definition` owns `## Intent Model`.
  - C) Review-only checks with no new owner skill.
Recommended default: A (keeps expression-to-intent mapping distinct from problem framing).

## Context Snapshot
<!-- owner: implementation-planning -->
### Inputs Provided
- User supplied a detailed implementation thesis favoring AtlasMemory-Tools over Atlas proper.
- User identified target surfaces: `/plan`, `skills/plan/reference.md`, `skills/problem-definition`, `skills/plan-execution-readiness`, `skills/local-plan-agent-runtime`, and proposal validation/reconciliation scripts.
- Local repo inspection confirmed these files and adjacent runtime/team-template surfaces exist.

### System Understanding
- Summary: AtlasMemory-Tools is already the canonical planning, review, issue projection, runtime, skill, agent, and template repo. The new feature should add a thin intent-preservation layer to the existing plan artifact flow.
- Components:
  - `skills/plan/SKILL.md`: orchestrator contract and gate flow.
  - `skills/plan/reference.md`: plan template.
  - `skills/problem-definition/SKILL.md`: problem framing owner skill.
  - `skills/plan-execution-readiness/*`: critical plan review skill and checklist.
  - `skills/local-plan-agent-runtime/*`: local agentic review runtime, personas, proposal schema, and validation scripts.
  - `skills/plan/scripts/validate_plan.py`: deterministic gate checks.
  - `tests/test_plan_validator.py`: validator coverage.
  - `templates/local-automation-runtime/team-templates/*.json`: planning and work-item role flows.
  - `agents/product-semantics.md`, `agents/semantic-alignment.md`, `agents/semantic-review.md`: downstream semantic review rubrics.
- Data flow:
  - User expression enters `/plan`.
  - `intent-reconciliation` drafts `## Intent Model`.
  - `problem-definition` and downstream plan sections preserve the model.
  - `local-plan-agent-runtime` reviewers classify gaps and propose section patches.
  - `plan-execution-readiness` checks intent alignment before approval/projection/build.
  - Work-item semantic roles use the model to detect implementation drift.
- Key abstractions:
  - One selected markdown plan remains authoring authority.
  - Section-owner skills draft; `/plan` writes.
  - Runtime workers propose only; manager reconciles; user decides intent.
  - Validators provide mechanical evidence but cannot replace human-agency decisions.

### Known Unknowns (ranked)
1) Whether this initial plan should later be projected into GitHub issues after implementation planning is approved.
2) Whether formal planning reviews should be run after implementation to close `PlanningReviewsComplete`.

### Questions to Proceed (ranked)
1) Should this plan later be projected into GitHub issues after source implementation lands?
2) Should formal planning reviews be run after implementation or before PR creation?

### Dynamic Review Roster
<!-- owner: planning-reviews -->
- Refreshed: 2026-06-17
- Triggered specialist reviews:
  - Review: automation-runtime
    - Why triggered: The plan changes local-plan-agent-runtime proposal contracts and personas.
    - Specialist/persona: automation-readiness-reviewer
    - Evidence hooks (named gates or source checks): G-UNIT-PlanValidator, G-UNIT-ProposalValidation, G-VERIFY-Harness
    - Status: Required
  - Review: domain-expert
    - Why triggered: Intent reconciliation changes planning semantics and user-intent handling.
    - Specialist/persona: product-semantics
    - Evidence hooks (named gates or source checks): G-REVIEW-IntentReadiness
    - Status: Required
  - Review: ui/operator-workflow
    - Why triggered: The work affects operator-facing planning prompts and review output.
    - Specialist/persona: ux-operator-workflow-reviewer
    - Evidence hooks (named gates or source checks): G-READABILITY-Plan
    - Status: Optional
- Reviews considered but not triggered:
  - Review: security/privacy
    - Why not triggered: No new secrets, auth, privacy, data-retention, or external-effect boundary is introduced by the MVP.
  - Review: database/migrations
    - Why not triggered: No database or durable data migration is in scope.

## Challenge Artifacts
<!-- owner: critical-ideation -->
### Weaknesses
- W1: Intent modeling is inherently subjective; if the repo only checks labels, agents can still fill the section with generic text.
- W2: The existing planning flow is already heavy; adding a section and skill may increase friction unless enforcement is risk-tiered.
- W3: The first version could duplicate `Open questions`, `Decision boundaries`, and semantic-review agents if boundaries are not clear.
- W4: Updating source skills without regenerating adapter copies may leave local Codex behavior stale.

### Failure Modes
- FM1: Template-only implementation - detection: validator tests pass on label presence but review examples expose generic content - prevention/mitigation: require wrong-but-plausible implementation and blocking open-loop checks in readiness review.
- FM2: Over-blocking lightweight plans - detection: existing validator fixtures and examples fail unexpectedly - prevention/mitigation: DR-001 default A and explicit PlanTier/AutomationTarget behavior.
- FM3: Runtime proposal schema breakage - detection: existing proposal validation tests fail - prevention/mitigation: optional `intent_gap_type` with `none` default and backward-compatible validation.
- FM4: New skill writes plans directly - detection: skill text violates `/plan` authority rules - prevention/mitigation: copy the section-owner draft contract used by existing skills.
- FM5: Semantic downstream roles ignore the new section - detection: team templates still request only old outputs - prevention/mitigation: update `must_produce` and acceptance criteria to consume `Intent Model`.

### Alternatives (including one disliked)
- Alt A: Add `## Intent Model`, new skill, reviewer hooks, and conservative validation. This is the recommended MVP.
- Alt B: Expand only `problem-definition`. Rejected because it hides the distinction between problem framing and expression-to-intent mapping.
- Alt C: Add only readiness-review questions. Rejected because there would be no canonical section for downstream agents to preserve.
- Alt D: Build an Atlas cognition-layer ontology first. Rejected for this phase because it lacks the immediate test loop that this repo already provides.

### Milestones (measurable)
- Milestone: Source plan workflow understands Intent Model.
  - Evidence: `skills/plan/SKILL.md`, `skills/plan/reference.md`, `skills/problem-definition/SKILL.md`, and `skills/intent-reconciliation/SKILL.md` updated.
- Milestone: Review and runtime proposal layers classify intent gaps.
  - Evidence: readiness checklist, finding schema, personas, proposal schema, and proposal validation tests updated.
- Milestone: Mechanical validation surfaces missing/blocking intent.
  - Evidence: validator tests cover missing section, missing labels, blocking open loops, and risk-tier enforcement.
- Milestone: Downstream semantic roles use the model.
  - Evidence: team templates and semantic agents mention `Intent Model` inputs and outputs.

## Technical Plan
### Technical Plan Intro
This feature adds an additive intent-preservation layer to the existing markdown planning workflow. The core change is a new `## Intent Model` section in the plan template, owned by a new `intent-reconciliation` skill and consumed by problem definition, plan readiness review, local agentic review, and downstream semantic-alignment roles.

The approach fits this repo because AtlasMemory-Tools already owns the planning skill contracts, plan template, local agentic review runtime, deterministic validators, workflow templates, and generated harness adapters. The implementation should not introduce a new runtime or authority model; it should strengthen the existing one by making latent intent explicit before technical scope is finalized.

### Integration Points
- `skills/plan/reference.md`: insert `## Intent Model` before `## Problem Definition`.
- `skills/plan/SKILL.md`: add routing and gate language for intent reconciliation inside ProblemDefinitionComplete without adding a new `CurrentStage`.
- `skills/problem-definition/SKILL.md`: instruct problem framing to preserve and reference intent-model content instead of flattening it.
- `skills/intent-reconciliation/SKILL.md`: new section-owner skill.
- `skills/plan-execution-readiness/SKILL.md` and references: add intent-alignment review dimensions and finding metadata.
- `skills/local-plan-agent-runtime/references/personas.md`: add one `intent-reconciliation-reviewer` persona.
- `skills/local-plan-agent-runtime/references/proposal-schema.md`: add optional `intent_gap_type` to findings.
- `skills/local-plan-agent-runtime/scripts/validate_proposal.py`: allow and validate the optional enum if present.
- `skills/plan/scripts/validate_plan.py`: add `check_intent_model` and include `IntentModelComplete` in output.
- `tests/test_plan_validator.py`: add coverage for new validator behavior.
- `templates/local-automation-runtime/team-templates/planning-design-doc.json`: require product-semantics to produce intent alignment risks.
- `templates/local-automation-runtime/team-templates/work-item-change-lifecycle.json`: require semantic-alignment to compare against `Intent Model`.
- `agents/product-semantics.md`, `agents/semantic-alignment.md`, `agents/semantic-review.md`: update role rubrics to consume intent model.
- `docs/atlas-workflow-templates.md` and README or `skills/plan/README.md`: document the workflow.

### Proposed Architecture Changes
- Add `## Intent Model` before `## Problem Definition` as an authoring section, not a separate lifecycle stage.
- Add `IntentModelComplete` as a validator result, initially configured by DR-001.
- Treat open loops marked open and blocking `Problem`, `Technical`, `Implementation`, or `Automation` as blocking for the selected enforcement tier.
- Preserve proposal schema compatibility by making `intent_gap_type` optional.
- Keep local agentic review read-only/proposal-only; accepted changes still route through `$plan`.

### Failure Modes (per integration point)
- Plan template: existing examples become stale - detected by tests/docs review - mitigated by updating source docs and generated adapters if selected.
- Validator: regex matches too broadly across open-loop entries - detected by focused tests - mitigated by small helper functions and explicit line-window checks.
- Proposal schema: old proposals are rejected - detected by validation tests - mitigated by optional enum.
- Runtime persona: findings become subjective - detected by required evidence fields - mitigated by tying each finding to `section_id`, user phrase, and concrete risk.
- Workflow templates: semantic roles duplicate review work - detected by role output overlap - mitigated by having them consume `Intent Model` and report drift only.

### Invariants / Non-Changes
- `/plan` remains the public workflow and canonical writer.
- One selected markdown artifact remains the authoring surface.
- Runtime workers do not mutate canonical plans or approval state.
- Decision boundaries still require A/B/C options and Decision Log entries.
- `CurrentStage` enum remains unchanged for the first release.
- GitHub issues, Projects, and PRs remain downstream execution surfaces.

### NFRs alignment
- Backward compatibility: existing proposal JSON remains valid.
- Reviewability: each change is small enough for focused PR review.
- Determinism: validator behavior is unit-tested and does not depend on model judgment.
- Operator ergonomics: new prompts ask only decision-bearing questions when open loops block execution.

## Implementation Plan
### Agent roster (required for PlanTier: Full)
- plan-orchestrator: owns source skill/template changes and final integration.
- validator-engineer: owns validator and tests.
- runtime-proposal-engineer: owns local-plan-agent-runtime persona/schema/proposal validation changes.
- semantic-workflow-engineer: owns team-template and semantic-agent updates.
- docs-reviewer: owns README/plan README/docs updates and readability pass.

### File Deltas (exhaustive) + rationale
- skills/plan/reference.md - modify - plan-orchestrator - add `## Intent Model` in the canonical template.
- skills/plan/SKILL.md - modify - plan-orchestrator - route intent reconciliation before ProblemDefinitionComplete can pass in triggered contexts.
- skills/problem-definition/SKILL.md - modify - plan-orchestrator - preserve intent model and avoid flattening expression-state gaps.
- skills/intent-reconciliation/SKILL.md - create - plan-orchestrator - define new section-owner skill and draft output contract.
- skills/plan-execution-readiness/SKILL.md - modify - docs-reviewer - add intent alignment review posture and output expectations.
- skills/plan-execution-readiness/references/execution-readiness-checklist.md - modify - docs-reviewer - add intent alignment checklist.
- skills/plan-execution-readiness/references/finding-schema.md - modify - docs-reviewer - add optional intent-gap type field for structured findings.
- skills/local-plan-agent-runtime/references/personas.md - modify - runtime-proposal-engineer - add `intent-reconciliation-reviewer`.
- skills/local-plan-agent-runtime/references/proposal-schema.md - modify - runtime-proposal-engineer - document optional `intent_gap_type`.
- skills/local-plan-agent-runtime/scripts/validate_proposal.py - modify - runtime-proposal-engineer - validate optional intent-gap enum.
- skills/plan/scripts/validate_plan.py - modify - validator-engineer - add `IntentModelComplete` check.
- tests/test_plan_validator.py - modify - validator-engineer - add plan validator tests for intent model.
- tests/test_local_plan_agent_runtime.py or relevant proposal validator test file - modify/create - runtime-proposal-engineer - add optional enum validation coverage.
- templates/local-automation-runtime/team-templates/planning-design-doc.json - modify - semantic-workflow-engineer - require product-semantics intent alignment output.
- templates/local-automation-runtime/team-templates/work-item-change-lifecycle.json - modify - semantic-workflow-engineer - require semantic-alignment comparison to Intent Model.
- templates/local-automation-runtime/config/agent-registry.example.json - modify - semantic-workflow-engineer - update role descriptions if needed.
- agents/product-semantics.md - modify - semantic-workflow-engineer - consume Intent Model.
- agents/semantic-alignment.md - modify - semantic-workflow-engineer - compare implementation against Intent Model.
- agents/semantic-review.md - modify - semantic-workflow-engineer - classify user-intent questions using open loops.
- skills/plan/README.md - modify - docs-reviewer - explain when Intent Model is created and how it affects readiness.
- README.md - modify - docs-reviewer - update planning with agentic review mode summary.
- docs/atlas-workflow-templates.md - modify - docs-reviewer - document workflow role outputs that consume Intent Model.
- manifests/atlas-tools.v1.json - modify - plan-orchestrator - add new skill and generated-copy inventory if required by harness generation.
- .codex/skills/* - modify/generated - plan-orchestrator - update only through harness generation if DR-003 selects same-PR adapter refresh.

### Workstreams + merge points
- WS1: Intent authoring surface
  - Owner: plan-orchestrator
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: Plans gain an explicit intent-preservation section and owner skill.
  - Tracking: none
  - Depends on: DR-001, DR-002
  - Review gates (named):
    - G-READABILITY-Plan
    - G-VERIFY-Harness
  - Owns files:
    - skills/plan/reference.md
    - skills/plan/SKILL.md
    - skills/problem-definition/SKILL.md
    - skills/intent-reconciliation/SKILL.md
    - manifests/atlas-tools.v1.json
  - Merge point / integration step: MP1
- WS2: Readiness and runtime review contracts
  - Owner: runtime-proposal-engineer
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: Reviewers can identify and classify latent intent gaps without changing plan authority.
  - Tracking: none
  - Depends on: WS1 section names
  - Review gates (named):
    - G-UNIT-ProposalValidation
    - G-READABILITY-Plan
  - Owns files:
    - skills/plan-execution-readiness/SKILL.md
    - skills/plan-execution-readiness/references/execution-readiness-checklist.md
    - skills/plan-execution-readiness/references/finding-schema.md
    - skills/local-plan-agent-runtime/references/personas.md
    - skills/local-plan-agent-runtime/references/proposal-schema.md
    - skills/local-plan-agent-runtime/scripts/validate_proposal.py
  - Merge point / integration step: MP1
- WS3: Deterministic validation
  - Owner: validator-engineer
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: Validator reports IntentModelComplete and tests cover enforcement rules.
  - Tracking: none
  - Depends on: DR-001, WS1 template shape
  - Review gates (named):
    - G-UNIT-PlanValidator
  - Owns files:
    - skills/plan/scripts/validate_plan.py
    - tests/test_plan_validator.py
  - Merge point / integration step: MP1
- WS4: Semantic workflow consumption
  - Owner: semantic-workflow-engineer
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: Planning and work-item roles consume Intent Model as semantic alignment input.
  - Tracking: none
  - Depends on: WS1
  - Review gates (named):
    - G-JSON-TeamTemplates
    - G-READABILITY-Plan
  - Owns files:
    - templates/local-automation-runtime/team-templates/planning-design-doc.json
    - templates/local-automation-runtime/team-templates/work-item-change-lifecycle.json
    - templates/local-automation-runtime/config/agent-registry.example.json
    - agents/product-semantics.md
    - agents/semantic-alignment.md
    - agents/semantic-review.md
    - docs/atlas-workflow-templates.md
  - Merge point / integration step: MP1
- WS5: Documentation and generated adapter verification
  - Owner: docs-reviewer
  - Agent type: generalPurpose
  - Delegate: optional
  - Intended behavior change: Human docs explain the new workflow and verification confirms generated copies are fresh.
  - Tracking: none
  - Depends on: WS1, WS2, WS3, WS4
  - Review gates (named):
    - G-VERIFY-Repo
    - G-VERIFY-Harness
  - Owns files:
    - README.md
    - skills/plan/README.md
    - generated adapter outputs if selected
  - Merge point / integration step: MP2

### Delegation Quality Gate (required for PlanTier: Full)
- DQ-1 Workstream delegation metadata complete: Pass
  - Rule: Every workstream has `Owner`, `Agent type`, and `Delegate`.
- DQ-2 File ownership conflict-free before merge points: Pass
  - Rule: No file is owned by more than one active workstream before an explicit merge point.
- DQ-3 Delegation coverage: Pass
  - Rule: All non-trivial workstreams are marked `Delegate: required`.
- DQ-4 Validation delegation path present: Pass
  - Rule: Test/review gates identify delegated execution path (agent type or owner).
- Notes / waivers (must cite DR-xxx):
  - WS5 is optional delegation because documentation integration depends on final wording from other workstreams.

### Phases + tasks + exit criteria
#### Phase 1: Intent surface MVP
- Owner(s): plan-orchestrator
- Depends on: DR-001, DR-002
- Tasks (by owner):
  - Owner: plan-orchestrator
    - [ ] Add `## Intent Model` before `## Problem Definition` in `skills/plan/reference.md`.
    - [ ] Create `skills/intent-reconciliation/SKILL.md`.
    - [ ] Update `/plan` to call intent reconciliation in the Problem stage when trigger conditions apply.
    - [ ] Update `problem-definition` to preserve latent target and anti-targets.
- Exit criteria (evidence): A new plan template shows the Intent Model section in the expected order and the new skill has a complete draft-section contract.
- Gates (named):
  - G-READABILITY-Plan
  - G-VERIFY-Harness

#### Phase 2: Review/runtime contracts
- Owner(s): runtime-proposal-engineer, docs-reviewer
- Depends on: Phase 1
- Tasks (by owner):
  - Owner: runtime-proposal-engineer
    - [ ] Add `intent-reconciliation-reviewer` persona.
    - [ ] Add optional `intent_gap_type` to proposal schema and validator.
  - Owner: docs-reviewer
    - [ ] Extend plan-execution-readiness with intent alignment checks.
    - [ ] Extend finding schema with optional intent-gap metadata.
- Exit criteria (evidence): Existing proposal packets remain valid; new packets with valid intent-gap enum pass; invalid enum fails.
- Gates (named):
  - G-UNIT-ProposalValidation

#### Phase 3: Deterministic validation
- Owner(s): validator-engineer
- Depends on: Phase 1 and DR-001
- Tasks (by owner):
  - Owner: validator-engineer
    - [ ] Add `check_intent_model`.
    - [ ] Add `IntentModelComplete` to validator output.
    - [ ] Add tests for missing section, missing labels, blocking open loop, and selected enforcement behavior.
- Exit criteria (evidence): Validator unit tests pass and failure messages are specific enough for `/plan` remediation.
- Gates (named):
  - G-UNIT-PlanValidator

#### Phase 4: Downstream semantic consumption
- Owner(s): semantic-workflow-engineer
- Depends on: Phase 1
- Tasks (by owner):
  - Owner: semantic-workflow-engineer
    - [ ] Update product-semantics and semantic-alignment role outputs.
    - [ ] Update planning and work-item team templates.
    - [ ] Update workflow docs.
- Exit criteria (evidence): Team templates are valid JSON and semantic role docs tell reviewers to compare against Intent Model.
- Gates (named):
  - G-JSON-TeamTemplates
  - G-READABILITY-Plan

#### Phase 5: Repo verification and adapter policy
- Owner(s): docs-reviewer, plan-orchestrator
- Depends on: Phase 1, Phase 2, Phase 3, Phase 4
- Tasks (by owner):
  - Owner: docs-reviewer
    - [ ] Update README and `skills/plan/README.md`.
  - Owner: plan-orchestrator
    - [ ] Update manifest if adding the skill requires it.
    - [ ] Run repository verification.
    - [ ] Regenerate/check harness adapter files if selected.
- Exit criteria (evidence): Repository verification passes or failures are documented with exact cause and next fix.
- Gates (named):
  - G-VERIFY-Repo
  - G-VERIFY-Harness

### Review gates (named + definitions)
- G-UNIT-PlanValidator:
  - Where it runs: Local
  - Entry point / command: python3 -m unittest tests.test_plan_validator
  - Green means: all validator tests pass, including intent model coverage.
- G-UNIT-ProposalValidation:
  - Where it runs: Local
  - Entry point / command: run the relevant local-plan-agent-runtime proposal validator tests or add `python3 -m unittest` coverage if no test file exists.
  - Green means: existing proposals remain valid and invalid intent-gap enum values fail.
- G-JSON-TeamTemplates:
  - Where it runs: Local
  - Entry point / command: python3 -m json.tool templates/local-automation-runtime/team-templates/planning-design-doc.json and python3 -m json.tool templates/local-automation-runtime/team-templates/work-item-change-lifecycle.json
  - Green means: JSON is valid and role outputs mention intent alignment.
- G-READABILITY-Plan:
  - Where it runs: Local
  - Entry point / command: manual review using `skills/plan-execution-readiness/references/execution-readiness-checklist.md`
  - Green means: a new engineer can explain the target, anti-targets, open loops, enforcement mode, and rollout sequence.
- G-VERIFY-Harness:
  - Where it runs: Local
  - Entry point / command: python3 scripts/verify_harness.py --target .
  - Green means: generated Codex harness copies are fresh or intentionally deferred with a documented reason.
- G-VERIFY-Repo:
  - Where it runs: Local
  - Entry point / command: python3 scripts/verify_repo.py
  - Green means: repository verification passes.

### Merge points -> required gates
- MP1: Source contract integration
  - Blocks on:
    - G-UNIT-PlanValidator
    - G-UNIT-ProposalValidation
    - G-JSON-TeamTemplates
    - G-READABILITY-Plan
- MP2: Final verification
  - Blocks on:
    - G-VERIFY-Repo
    - G-VERIFY-Harness

### Test Matrix
- plan template - missing section/order risk - manual/source check - where it runs: Local
- plan validator - false pass/fail risk - unit test - where it runs: Local
- proposal schema - backward compatibility risk - unit test or script fixture - where it runs: Local
- team templates - invalid JSON risk - JSON syntax check - where it runs: Local
- harness adapters - generated-copy drift risk - harness verification - where it runs: Local
- repo verification - integration drift risk - repository verifier - where it runs: Local

### Test plan (CI vs deployed)
- CI:
  - python3 -m unittest tests.test_plan_validator
  - python3 scripts/verify_repo.py if CI has the same prerequisites as local verification
- Deployed environment:
  - not applicable; this is repo-local planning/tooling work.

### Rollout / Rollback
- Rollout: Merge source-skill/template/schema/validator changes behind conservative enforcement, then use the new section on this plan and one future planning session before projecting work into issues.
- Rollback trigger: Existing plans or proposal validation break unexpectedly, or reviewers find the new section creates noise without actionable decisions.
- Rollback steps: Revert validator enforcement first while keeping documentation; if still noisy, remove the runtime persona/schema extension; leave semantic role docs only if they remain useful.

## Automation Issue Manifest
<!-- owner: automation-decomposition -->
Applies when `AutomationTarget` is not `none`.

### Dispatch policy
- Automation target: none
- Dispatch strategy: manual planning only
- Max concurrent work items: 0
- Required labels: none
- Default reviewer / reviewer pool: maintainer
- Branch policy: feature branch when implementation starts
- PR policy: draft
- Merge policy: manual
- Rebase/update policy: update before merge
- Failure policy: stop and report
- Human approval required before dispatch: yes

### Containers
- none:
  - Type: workstream
  - Parent: none
  - Dispatch: tracking-only
  - Source plan sections:
    - Implementation Plan

### Leaf issues
- none: No automation leaf issues are defined because `AutomationTarget: none`.

### Manifest validation summary
- Dependency graph acyclic: Pass
- Dependencies resolvable: Pass
- Gate coverage complete: Pass
- File-scope conflicts resolved: Pass
- Acceptance criteria executable: Pass
- Required metadata complete: Pass
- Notes / waivers (must cite DR-xxx):
  - none

## Planning Reviews
<!-- owner: planning-reviews -->
### Zero-Context Review
- Reviewer: not run
- Refreshed: not run
- RefreshedAt: not run
- ReviewedPlanHash: not run
- Re-entry audit answers (required when updating a plan at CurrentStage: Reviews or approved/complete status):
  - What is being built: not run
  - Why now: not run
  - Repos involved: not run
  - What changes first: not run
  - What must not happen: not run
  - How work is validated: not run
  - What remains blocked: not run
- Findings (schema):
  - Missing context:
  - Contradictions:
  - Unclear decisions:
  - Risks and edge cases:
  - What I would screw up implementing tomorrow:
- Disposition:
  - none

### Expert Technical Review
- Trigger: required before implementation
- Reviewer: not run
- Refreshed: not run
- RefreshedAt: not run
- ReviewedPlanHash: not run
- Findings (schema):
  - Technical risks and integration gaps:
  - Missing validations or operational steps:
  - Contradictions with stated invariants or authority boundaries:
  - Patch suggestions (point to sections):
- Disposition:
  - none

### Security/Privacy Review
- Reviewer: not run
- Refreshed: not run
- RefreshedAt: not run
- ReviewedPlanHash: not run
- Findings (schema):
  - Security/privacy risks:
  - Missing validations or mitigations:
  - Patch suggestions (point to sections):
- Disposition:
  - none

### Dynamic Specialist Review Roster
- Reviewer: planning-reviews-orchestrator
- Refreshed: 2026-06-17
- RefreshedAt: not run
- ReviewedPlanHash: not run
- Findings (schema):
  - Triggered specialist review rationale:
    - F-001: automation-runtime and product-semantics review are required because the plan changes local agentic review and planning semantics.
  - Skipped specialist review rationale:
    - F-002: security/privacy and database/migrations are not triggered by the current scope.
  - Missing or deferred specialist coverage:
    - F-003: full review not run yet.
- Triggered specialist reviews:
  - Review: automation-runtime
    - Why triggered: local-plan-agent-runtime proposal contracts and personas change.
    - Persona/sub-agent: automation-readiness-reviewer
    - Required evidence hooks: G-UNIT-ProposalValidation
    - Status: Required
  - Review: domain-expert
    - Why triggered: planning semantics and user-intent handling change.
    - Persona/sub-agent: product-semantics
    - Required evidence hooks: G-REVIEW-IntentReadiness
    - Status: Required
- Reviews considered but not triggered:
  - Review: database/migrations
    - Why not triggered: no data migration in scope.
- Disposition:
  - none

### Human Readability Review
- Reviewer: not run
- Refreshed: not run
- RefreshedAt: not run
- ReviewedPlanHash: not run
- Findings:
  - Product/system clarity:
- Pass/fail readability statement: Fail
- Disposition:
  - none

### Implementer Readiness Review
- Reviewer: not run
- Refreshed: not run
- RefreshedAt: not run
- ReviewedPlanHash: not run
- Findings:
  - Top 5 gotchas:
- Disposition:
  - none

## Execution Status
Phase: Intent reconciliation layer MVP
Status: complete

Workstreams:
- WS1 Intent authoring surface: complete - template, `/plan`, `problem-definition`, manifest, and new skill updated.
- WS2 Readiness and runtime review contracts: complete - readiness references, persona, proposal schema, and proposal validator updated.
- WS3 Deterministic validation: complete - `IntentModelComplete` implemented and tested.
- WS4 Semantic workflow consumption: complete - semantic agents and workflow templates now consume `Intent Model`.
- WS5 Documentation and generated adapter verification: complete - README/docs updated and Codex adapters regenerated.

Delegation matrix:
- Task: Add Intent Model before Problem Definition | Owner: plan-orchestrator | Files: skills/plan/reference.md, skills/plan/SKILL.md, skills/problem-definition/SKILL.md, skills/intent-reconciliation/SKILL.md | Agent: direct orchestrator | Status: complete
- Task: Add intent proposal/runtime support | Owner: runtime-proposal-engineer | Files: skills/local-plan-agent-runtime/references/personas.md, skills/local-plan-agent-runtime/references/proposal-schema.md, skills/local-plan-agent-runtime/scripts/validate_proposal.py, tests/test_local_plan_agent_runtime.py | Agent: direct orchestrator | Status: complete
- Task: Add IntentModelComplete validator | Owner: validator-engineer | Files: skills/plan/scripts/validate_plan.py, tests/test_plan_validator.py | Agent: direct orchestrator | Status: complete
- Task: Update semantic workflow consumers | Owner: semantic-workflow-engineer | Files: agents/product-semantics.md, agents/semantic-alignment.md, agents/semantic-review.md, templates/local-automation-runtime/team-templates/*.json, templates/local-automation-runtime/config/agent-registry.example.json, docs/atlas-workflow-templates.md | Agent: direct orchestrator | Status: complete
- Task: Refresh docs and generated adapters | Owner: docs-reviewer | Files: README.md, skills/plan/README.md, .codex/skills/** | Agent: direct orchestrator | Status: complete

Completed tasks:
- Created `skills/intent-reconciliation/SKILL.md`.
- Added `## Intent Model` before `## Problem Definition` in the plan template.
- Added `IntentModelComplete` validator behavior with risk-tier enforcement.
- Added optional `intent_gap_type` proposal validation.
- Added runtime persona `intent-reconciliation-reviewer`.
- Updated semantic agents/team templates to consume `Intent Model`.
- Updated source docs and regenerated Codex adapter copies.

Blocked:
- Formal planning reviews remain incomplete - `PlanningReviewsComplete: Fail` until review blocks are refreshed and dispositioned.

Build gates:
- G-UNIT-PlanValidator - pass - `python3 -m unittest tests.test_plan_validator tests.test_local_plan_agent_runtime`
- G-UNIT-ProposalValidation - pass - covered by `tests.test_local_plan_agent_runtime`
- G-JSON-TeamTemplates - pass - `python3 -m json.tool` on planning and work-item team templates
- G-VERIFY-Harness - pass - `python3 scripts/verify_harness.py --target .`
- G-VERIFY-Repo - pass - `python3 scripts/verify_repo.py`
- Plan validator on this plan - expected partial pass - `IntentModelComplete`, `ProblemDefinitionComplete`, `PlanReadiness`, `AutomationReadiness: N/A`, and `PlanStateSanity` pass; `PlanningReviewsComplete` fails because reviews were intentionally not run.

Sub-agent usage:
- Agents launched: 0
- Parallel batches: 0
- Direct orchestrator edits: 1 implementation batch - direct edits were used to keep source, tests, manifest, generated adapters, and plan status synchronized in one workspace after the user explicitly approved the small MVP decisions.

Next actions:
- Run formal planning reviews if this plan needs `PlanningReviewsComplete: Pass`.
- Review the diff and decide whether to project follow-up issue work.
