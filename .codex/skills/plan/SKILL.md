---
# atlas-tools-generated: source=skills/plan/SKILL.md manifest=atlas-tools.v1 checksum=sha256:76ae110a85dbad3a51f4cf46acf5155a69d5704d4e2babf00dc855e224d4cb92
# atlas-tools-generated-end
name: plan
description: Orchestrate the /plan workflow to create or update the current plan artifact (autonamed by the planning workflow) as the planning write surface and implementation plan. Use when the user runs /plan, asks to create a plan, or wants to progress planning stages with validation and reviews.
---

# /plan Orchestrator

## Purpose
Create or update the current markdown plan artifact and move it through Problem, Feature, Technical, Implementation, Automation, and Reviews with deterministic validators, decision logging, and substance-first human review. The plan must explain the real product/system work before it explains planning machinery, and it must contain enough detail for implementation agents that have zero prior context and no user interaction. The markdown artifact is the authoring write surface. Compiled registry YAML, when used, is a derived machine-readable package for joins, validator inputs, and projection metadata; it does not replace the selected markdown plan as authoring authority. Section-owner skills run as sub-agents and return drafts; the orchestrator is the only writer and runs the Q/A loop inline with the user.

## Agentic review mode
When the user says `Use $plan with agentic review mode`, asks for parallel plan review, asks to review an old plan before trusting it, or asks to run the local agentic planning workflow on a markdown plan, `$plan` remains the public workflow and canonical writer. Invoke `/local-plan-agent-runtime` as an internal review layer after the authoring artifact is selected and before preserving approval/readiness state.

Agentic review mode must run as dry-run review/proposal work unless the user explicitly approves `$plan`-routed edits. It snapshots the selected plan, runs independent reviewer personas, validates structured proposal packets, reconciles conflicts, and returns findings, decisions, and patch candidates. The runtime and its sub-agents must not write the canonical plan, flip gates, approve projection, approve dispatch, or encode human-agency decisions. `$plan` owns all accepted edits, Decision Log updates, gate updates, review freshness, and user Q/A.

Use this mode for new plans, old plans that are not in current shape, and previously reviewed or approved plans. For old or approved plans, treat existing `Pass`, `Approved`, projection, and dispatch claims as stale until the re-entry audit and agentic review findings are dispositioned. If implementation-critical intent is missing, interrogate the user with targeted questions and keep the plan blocked until the answer is recorded.

## Core rules
- The current markdown plan artifact is the planning write surface; do not assume a fixed filename.
- **Substance before mechanics**: Product/system sections (`Problem Definition`, `Challenge Artifacts`, `Technical Plan`) must describe the real workflow failure/opportunity, desired behavior, and engineering approach. Planning machinery, authority contracts, projection, and dispatch policy belong in `Plan State`, `Implementation Plan`, `Automation Issue Manifest`, and `Execution Mechanics / Automation Appendix`.
- **Zero-interaction implementer standard**: assume future build agents cannot ask the user questions and have no prior knowledge. If an implementation-critical fact is missing, ask now, record a decision boundary, or keep the gate failing. Do not fill gaps with vague defaults.
- **Interrogate before advancing**: for Problem, Technical, and Implementation stages, ask targeted questions until the plan names the current workflow, desired workflow, why the gap matters now, concrete repo/user facts, owners, file boundaries, verification entrypoints, rollout, and rollback. It is better to block than to pass a lazy plan.
- **Many atomic plans, one campaign**: when a large effort is intentionally split across multiple plan artifacts, each plan still owns exactly one selected authoring artifact. Use optional metadata such as `PlanGroup`, `ParentPlan`, `DependsOnPlans`, `BlocksPlans`, and `AtomicScope` only as descriptive links. These fields do not replace `@path` selection, do not create registry authority, and do not let one `/plan` invocation edit multiple plans.
- **Artifact authority contract (required)**:
  - the selected harness-local plan artifact is authoritative for authoring intent, rationale, and amendments.
  - compiled registry YAML is derived from the selected plan and may be used as a machine-readable package for local planning structure, joins, validator inputs, and projection metadata after successful compile. If it conflicts with the selected plan, patch the plan and recompile; do not treat the registry as independent intent authority.
  - GitHub issues and PRs are authoritative for execution state and mutation authority.
  - GitHub Projects v2 is downstream execution UI/signal only.
  - rendered overlays and runtime-mirror outputs are derived surfaces, never authoring input.
- **Authoring artifact selection is a hard lock**:
  - **Selection precedence**:
    - If the user referenced any plan via `@path` in the last user message, **that wins** over thread context.
    - If multiple plans are referenced, you MUST ask the user to pick exactly one before proceeding (single-select).
  - Treat a plan as the selected authoring artifact only if:
    - the user explicitly provided it in this conversation (pasted content or referenced via `@path`), OR
    - `/plan` created it earlier in this same run.
  - Do NOT implicitly adopt a plan just because it exists in the workspace or happens to be open in the editor.
- **Authoring artifact echo (required)**: after the selection is made, print `AuthoringArtifact = <path>` in chat before doing any `/plan` work.
- **No-new-plan invariant**: if an authoring artifact is already selected, do NOT create a new plan artifact unless the user explicitly requests “new plan”.
- If no explicit in-conversation plan artifact is provided, create a new plan doc from `reference.md` and immediately echo it as the selected authoring artifact.
- **Reviews/Approved re-entry audit (hard rule)**: when updating an existing plan whose `CurrentStage: Reviews`, `Status: Approved`, `Status: SubstantivelyReviewed`, `Status: StructurallyComplete`, `SubstanceStatus: SubstantivelyReviewed`, `StructuralStatus: StructurallyComplete`, `ProjectionApproval: ApprovedForProjection`, or `DispatchApproval: ApprovedForDispatch`, ignore existing gate pass claims until a fresh zero-context re-entry audit has been performed for this invocation. The audit must answer:
  - what is being built,
  - why now,
  - what repo(s) are involved,
  - what changes first,
  - what must not happen,
  - how work is validated,
  - what remains blocked.
  If any answer is weak, patch the relevant Problem, Technical, Implementation, Automation, Decision Log, or Planning Reviews sections before preserving or setting any pass/approval state.
- Workflow order is fixed: Problem -> Feature -> Technical -> Human Readability -> Implementation -> Automation (when `AutomationTarget != none`) -> Reviews. Human Readability is a gate, not a separate `CurrentStage`.
- Hard rule: `/problem-definition` and `/critical-ideation` are Q/A gated before advancing; run the Q/A loop inline with the user and only when the checklist fails or `Questions` is non-empty.
- **No gate flips without evidence**: before changing any of `Status`, `CurrentStage`, quality/approval state fields, or any Gate Results, include a short checklist in chat stating:
  - which section(s) changed, and
  - why the validator now passes (what evidence/fields were added/clarified).
- Hard rule: plan artifact writes are done only by the orchestrator.
- Decision boundaries require A/B/C options and a Decision Log entry.
- Preserve user agency via decision boundaries + dispositions. Do not "auto-approve" ambiguous decisions.

## On each /plan invocation
1) Determine the selected authoring artifact using the selection precedence rules above.
2) If multiple plan artifacts were referenced, stop and ask the user to select exactly one (single-select) before doing any work.
3) If missing (no authoring artifact could be selected):
   - Ask for the feature idea / goal statement (1-2 sentences) and any hard constraints (optional).
   - Create a new plan doc using the template in `reference.md`.
4) Echo the selection in chat: `AuthoringArtifact = <path>`.
5) Determine `CurrentStage`. If the user requested agentic review mode, run `/local-plan-agent-runtime` in dry-run against the selected artifact before trusting readiness, review, projection, or dispatch state; use `/plan-execution-readiness` as the critical review persona/checklist when focused execution-readiness review is needed.
6) If the plan is in Reviews/Approved re-entry state, run `/review mode=zero-context` as a fresh re-entry audit before trusting existing `Pass` or approval values. Treat all existing pass claims as stale until the audit answers the seven required questions above with concrete, plan-cited answers. If the audit is weak, route remediation to the owner skill for the weak section(s), set affected gates to `Fail`, and do not preserve or set approval state.
7) Run validators in stage order up to the current stage.
   - When available, run `python3 skills/plan/scripts/validate_plan.py <authoring-artifact>` as the deterministic mechanical check for `ProblemDefinitionComplete`, `PlanReadiness`, `AutomationReadiness`, `PlanningReviewsComplete`, and `PlanStateSanity`. Use the script output as blocking evidence, not as a substitute for human-agency decisions.
   - If the plan is part of an atomic-plan campaign, verify that its descriptive metadata is coherent enough for human navigation (`PlanGroup`, `AtomicScope`, and known dependencies), but do not fail the gate solely because optional cross-plan metadata is absent unless the plan itself depends on it.
8) Route to the first failing gate and call the owner skill as a sub-agent to produce a draft section. Provide any known agent roster or `## Context Snapshot` so ownership can be assigned correctly.
9) Run the human Q/A loop inline with the user using the gate's mode (see map below) when:
   - the validator fails, OR
   - `Questions` is non-empty, OR
   - the Substance Gate requirements for `ProblemDefinitionComplete` are not all satisfied, OR
   - you are moving into/through **TechnicalClarity** and you have not yet run at least one `mode=comprehension` checkpoint in this /plan invocation, OR
   - you are moving into/through **PlanReadiness** and you have not yet run at least one `mode=comprehension` checkpoint in this /plan invocation.
   Keep these checkpoints targeted. Ask enough to remove ambiguity; do not accept "looks good" when current workflow, desired workflow, repo facts, owners, gates, or rollback remain vague.
10) Re-run the owner sub-agent as needed until the gate passes.
11) Orchestrator writes the accepted output into the plan section.
12) Re-run the affected validator.
13) Advance stage only when its gate passes.
14) Update `Status`, `CurrentStage`, quality/approval state fields, and any Gate Results only after providing the “no gate flips without evidence” checklist in chat.
    - Treat lifecycle status, structural completion, substance review, projection approval, and dispatch approval as separate states.
    - `StructuralStatus: StructurallyComplete` requires deterministic gates through `PlanReadiness`.
    - `SubstanceStatus: SubstantivelyReviewed` requires the Substance Gate and `HumanReadabilityReview: Pass`.
    - `ProjectionApproval: ApprovedForProjection` requires `AutomationReadiness: Pass` or `AutomationTarget: none` with rationale.
    - `DispatchApproval: ApprovedForDispatch` requires explicit human dispatch approval plus all projection/dispatch policy gates.
    - Legacy `Status: Approved` may be used only as a compatibility summary after `PlanStateSanity`, `StructuralStatus`, and `SubstanceStatus` pass. It never implies issue projection or dispatch approval.
15) If `AutomationTarget != none`, run `/automation-decomposition` after PlanReadiness passes and before Reviews; do not dispatch work here.
16) Reviews stage only: run planning reviews, then auto-remediate findings that are purely clarity/structure improvements and do not change decisions.
    - **No paper reviews**: after any remediation or other material plan edits, regenerate reviews (or re-run the same review agents) so `PlanningReviewsComplete` reflects the updated document.
    - If reviews are stale (plan changed since last review run), `PlanningReviewsComplete` MUST be `Fail` until re-run.
    - Each refreshed review block must record `ReviewedPlanHash: sha256:<hash>` for the current plan state, or timestamp-level `RefreshedAt` when hash capture is not available. Date-only freshness is stale for new reviews.
17) Repeat the review -> remediation loop until findings are resolved, deduped as ignorable/non-relevant, or no new findings appear.
18) Only surface findings to the user when they require human agency (policy/compliance/cost/trust boundaries, decision boundaries, external source approval, contradictions with explicit assumptions or authority contracts, or remediation target is `Unknown`). Ask for A/R/D only for this reduced set.
19) Hard rule: do not set `Status: Approved`, `SubstanceStatus: SubstantivelyReviewed`, `PlanningReviewsComplete: Pass`, `ProjectionApproval: ApprovedForProjection`, or `DispatchApproval: ApprovedForDispatch` if any human-agency items remain unresolved. Stop and request dispositions first.

## Validators (deterministic)
- ProblemDefinitionComplete: problem narrative, measurable success criteria, constraints, scope/anti-scope, decision boundaries, and the **Substance Gate**. Must be Q/A gated; inline loop is required whenever substance is missing.
  - **Substance Gate (required before pass)**:
    - The first paragraph describes the real product/system failure or opportunity, not the need to create a plan.
    - The first two paragraphs avoid planning-meta terms: `plan`, `artifact`, `gate`, `issue manifest`, `registry`, `projection`, `dispatch`.
    - It names the current broken workflow, the desired workflow, and why the gap matters.
    - It includes at least 3 concrete current-state facts from repo inspection and/or user-provided context, each with a source (`file`, `command`, `user`, or `issue`). If facts are unavailable, keep the gate failing and ask for them.
    - It explains why the work exists now.
    - Success criteria measure product/system outcomes and verification evidence, not document completeness.
    - Any unknown that would force an implementer to guess is an Open question with owner/status or a Decision boundary with A/B/C options.
- FeatureClarity: evaluation criteria, assumptions/tests, ranked risks with status, alternatives rejected, >=1 failure mode. Must be Q/A gated after critical-ideation; inline loop only when needed.
- TechnicalClarity: integration points named, failure modes per integration point, risks/assumptions updated, invariants respected, and a human-readable technical intro.
  - The Technical Plan intro must state what will change in the system, why that approach fits the problem, and which existing components/data flows it touches.
  - It must avoid authority/projection/dispatch language unless the technical work itself is authority/projection/dispatch.
  - It must leave no implementation-critical TBDs outside Decision Log/Open questions.
- HumanReadabilityReview:
  - A new engineer can explain what is being built and why after reading only `Problem Definition` and the `Technical Plan` intro.
  - Rendered HTML, if generated, reads like a product/engineering plan rather than a validator report.
  - Automation, authority-contract, projection, and dispatch details are confined to execution sections/appendices unless directly part of the product problem.
  - The review names the strongest remaining ambiguity or explicitly says none.
- ReviewsApprovedReentryAudit (required before preserving pass state on Reviews/Approved re-entry):
  - A fresh zero-context audit was run in the current invocation.
  - The audit gives concrete answers for what is being built, why now, repos involved, first changes, must-not-happen constraints, validation, and remaining blockers.
  - Any weak answer has been patched in the relevant section before pass/approval state is preserved or set.
- PlanReadiness (presence + structure + evidence; not “looks complete”):
  - **PlanTier: Lite (minimum)**:
    - file deltas exist and include explicit owner and rationale
    - workstreams include dependencies, merge points, and owned files
    - phases include evidence-based exit criteria and at least minimal build-time gates
    - test matrix includes “where it runs” (CI vs local vs deployed)
    - rollout includes rollback trigger + rollback steps
  - **PlanTier: Full (execution-grade, deterministic)**:
    - **agent roster exists** (owner -> responsibilities mapping) in `## Implementation Plan`
    - every workstream has explicit fields: `Owner`, `Agent type`, `Depends on`, `Review gates`, `Merge point`
    - each workstream declares file ownership boundaries for build parallelism (single owner per file until merge point)
    - each workstream includes delegation guidance (`delegate: required|optional`) so `/build` can enforce sub-agent-first execution
    - `### Delegation Quality Gate` exists and DQ-1..DQ-4 are all `Pass` (or explicit DR-backed waiver for any `Fail`)
    - every phase has explicit fields: `Owner(s)`, `Depends on`, `Exit criteria (evidence)`, `Gates (named)`
    - **gate definitions exist** (named gates like `G-CI-Unit`, `G-DEPLOY-Smoke`) and each includes:
      - where it runs (CI | Local | Deployed)
      - entrypoint/command (or named test runner target)
      - what “green” means
    - each merge point/phase references gate names (or includes concrete commands/entrypoints)
    - test plan includes “where it runs” (CI vs deployed) explicitly, not implied
    - dependency sanity: if any workstream/phase declares `Depends on`, the phase ordering does not contradict it (no backwards dependency)
    - no placeholder language in gates (e.g., “run smoke tests”) without naming the gate(s) and where/how they run
    - no task requires future user interaction unless it is explicitly a manual blocker with owner, trigger, and dispatch effect
    - every future agent-owned task has enough local context, file scope, acceptance criteria, and validation evidence to execute without asking the user what was intended
    - domain-specific hard questions that materially affect implementation MUST be decided or DR-deferred with trigger. Examples include migration tooling when schemas change, cutover/fallback criteria when replacing behavior, cache staleness when caches are introduced, provisioning/readiness semantics when activation state exists, provider/IAM/network boundaries when cloud infrastructure is in scope, and external-effect rollback/compensation when work can affect real systems.
- AutomationReadiness (required when `AutomationTarget != none`; otherwise N/A):
  - `AutomationTarget` is one of:
    - `none`: no automation manifest required.
    - `manifest-only`: plan includes a valid manifest for human review, but projection/dispatch can remain blocked.
    - `issue-projection`: manifest can be projected into tracker issues without additional decomposition.
    - `unattended-prs`: `agent-ready` leaf issues can be consumed by local issue-to-PR automation after human dispatch approval.
  - `## Automation Issue Manifest` exists and includes:
    - dispatch policy with strategy, concurrency, labels, branch/PR/merge/update/failure policies, and human-approval setting
    - containers for epics/workstreams/phases/merge points marked `tracking-only`
    - leaf issues with stable id, title, type, parent, owner, agent type, dispatch mode, dependencies, file scope, required gates, validation, acceptance criteria, source sections, and one-PR contract
    - dependency graph is acyclic and does not contradict workstream/phase dependencies
    - every dependency resolves to a leaf issue id, a structured external blocker, or a structured manual blocker
    - no gate, merge point, risk, assumption, or decision token is used as a dependency
    - every required gate is defined in `## Implementation Plan` with where/entrypoint/green means and attached to at least one leaf issue
    - file scopes do not conflict across simultaneously dispatchable items unless an explicit merge/dependency boundary serializes them
    - acceptance criteria are executable and map to named gates or concrete evidence
    - `issue-projection` and `unattended-prs` have no open dispatch-policy placeholders
    - `unattended-prs` has bounded concurrency, failure policy, branch policy, PR policy, and human approval before dispatch
    - risky work (secrets/auth/payments/live commerce/webhooks/migrations/infra/deploy/public API/data deletion/compliance) is converted into `manual-review`, `blocked`, or spike-first dispatch policy unless waived by DR
- PlanStateSanity (blocks false “Approved/Execution”):
  - Do NOT allow `Status: Approved`, `StructuralStatus: StructurallyComplete`, `SubstanceStatus: SubstantivelyReviewed`, `ProjectionApproval: ApprovedForProjection`, `DispatchApproval: ApprovedForDispatch`, or `CurrentStage: Build/Execution` if:
    - any required gate is not `Pass`, OR
    - the plan is in Reviews/Approved re-entry state and the fresh zero-context re-entry audit is missing, stale, or weak, OR
    - `Open questions` contains any item with `Status: Open` (or missing Status), OR
    - ambiguity markers remain in critical areas (Problem/Technical/Implementation/Decision Log), including: `TBD`, `to be decided`, `choose later`, `or decide later`
      - unless the ambiguity is explicitly captured as a Decision boundary (A/B/C) or a DR-backed Defer with a trigger.
- PlanningReviewsComplete: required reviews done with dispositions logged; required blocks include zero-context, implementer readiness, security/privacy, human readability, expert-tech findings or N/A rationale, dynamic specialist review roster, and automation readiness when `AutomationTarget != none`; Human Readability is Pass.
  - Specialist reviews are selected from plan content, not hard-coded provider assumptions. Trigger dedicated review passes for domains such as cloud/provider infrastructure, database/migrations, data integrity/concurrency, API contracts, external effects/governance, cost/operations, UI/operator workflow, or domain expertise when the plan touches those boundaries. Record why each triggered review was selected and why obvious-but-untriggered reviews were skipped.
  - **Stale review detection (mechanical)**:
    - Each required review block MUST include one of these canonical freshness markers:
      - `ReviewedPlanHash: sha256:<64 hex chars>` matching the current plan content excluding `## Planning Reviews`, OR
      - `RefreshedAt: YYYY-MM-DDTHH:MM:SS` at timestamp granularity.
    - Date-only `Refreshed: YYYY-MM-DD` is legacy context only and MUST NOT pass new review freshness.
    - If no hash or timestamp-level refreshed stamp is present for any required review, treat reviews as stale -> gate fails.
    - If plan `LastUpdated` is later than any required review’s `RefreshedAt`, treat reviews as stale -> gate fails.
    - Only pass when required reviews are refreshed for the current plan state.

## Gate -> owner skill map (sub-agents)
- ProblemDefinitionComplete -> `/problem-definition`
- FeatureClarity -> `/critical-ideation`
- TechnicalClarity -> `/technical-planning`
- HumanReadabilityReview -> `/planning-reviews` using `/review mode=human-readability`
- PlanReadiness -> `/implementation-planning`
- AutomationReadiness -> `/automation-decomposition` when `AutomationTarget != none`
- PlanningReviewsComplete -> `/planning-reviews`

## Gate -> Q/A loop mode map (inline)
- ProblemDefinitionComplete -> `qa-loop mode=default`
- FeatureClarity -> `qa-loop mode=default`
- TechnicalClarity -> `qa-loop mode=comprehension` (must run at least once per /plan invocation when moving into/through this gate)
- HumanReadabilityReview -> `qa-loop mode=comprehension` when the reviewer cannot explain the work or finds authority/projection leakage
- PlanReadiness -> `qa-loop mode=comprehension` (must run at least once per /plan invocation when moving into/through this gate)
- AutomationReadiness -> `qa-loop mode=comprehension` when dispatch policy or automation scope needs user confirmation
- PlanningReviewsComplete -> `qa-loop mode=disposition`

## Review auto-remediation routing
- Problem -> `/problem-definition`
- Feature -> `/critical-ideation`
- Technical -> `/technical-planning`
- Human Readability -> route to `/problem-definition`, `/technical-planning`, or `/implementation-planning` based on the finding target
- Implementation -> `/implementation-planning`
- Automation Issue Manifest -> `/automation-decomposition`
- Context Snapshot -> `/implementation-planning`
- Decision Log -> orchestrator updates decision boundary options; if unclear, ask the user.

## Human-agency definition (operational)
Human-agency items MUST be explicitly decided by the user (use structured questions when possible) and recorded as a Decision Log entry or an explicit “user decision: …” note. Human-agency includes:
- Cost targets that require SKU/region assumptions
- Retention/compliance commitments (e.g., multi-year audit retention)
- Routing boundary decisions (deny-by-default vs fallback behavior)
- Any change that alters the trust boundary or data-handling policy
- Security/privacy posture changes, data residency commitments, or auth boundary changes

## Patch strategy (required)
- Only replace the owned section between its header and the next header.
- Do not modify other sections.
- If the section is missing, insert it under the expected header in the template order.

## Malformed output definition (flexible mapping)
- Acceptable: content is semantically mappable to the owned section even if formatting differs from the template.
- Malformed: introduces new top-level sections, omits required fields for the gate, or conflicts with an existing section header.
- If malformed, do not write to the plan. Ask the user whether to (a) drop the extra content, (b) map it into the closest section, or (c) re-run the sub-agent with clarifications.
## Mapping heuristics (brief)
- Map extra bullets into the closest subsection by label match (e.g., "Risks" -> Risks/Assumptions/Tests).
- If no clear match, hold in `Questions` and ask the user.

## Failure behavior
- If a sub-agent output fails validation, ask the user for clarifications and re-run the sub-agent.
- If the Q/A loop cannot close the gap, set `NextRequiredUserAction`, keep the gate at `N/A`, and stop.

## Minimal plan policy (anti-overwrite)
- Keep prose tight, but never omit detail that a zero-interaction implementer needs.
- Prefer concrete nouns, file paths, commands, owners, and pass/fail evidence over framework language.
- Use paragraphs where narrative clarity matters (`Problem Definition`, `Technical Plan` intro); use bullets/tables for execution details.
- Do not compress away current-state facts, decision rationale, validation entrypoints, rollout, rollback, or dispatch blockers.

## Context handling
- Each sub-agent is responsible for collecting minimal necessary context for its section.
- The Implementation Planning sub-agent owns the `## Context Snapshot` section and should fill any missing context required for execution, including the agent roster and a delegation-ready workstream matrix if not already captured.
- The Automation Decomposition sub-agent owns only `## Automation Issue Manifest`; it derives items from the accepted implementation plan and must not mutate issues, projects, branches, or runtime state.
- Hard-block when missing context would force future implementers to infer user intent, invent product behavior, choose unapproved ownership, or validate without named evidence.

## Sub-skills used (run as sub-agents unless noted)
- `/problem-definition` -> sub-agent, Q/A gated (inline loop when needed)
- `/critical-ideation` -> sub-agent, Q/A gated (inline loop when needed)
- `/technical-planning` -> sub-agent, Q/A gated (inline loop when needed)
- `/implementation-planning` -> sub-agent, Q/A gated (inline loop when needed)
- `/automation-decomposition` -> sub-agent when `AutomationTarget != none`, Q/A gated when dispatch policy or scope is ambiguous
- `/planning-reviews` -> inline or sub-agent, Q/A gated (inline loop when needed)
- `/local-plan-agent-runtime` -> optional internal review layer when the user requests agentic review mode; returns validated findings/proposals only
- `/plan-execution-readiness` -> standalone or runtime persona/checklist for critical plan execution-readiness review

## Output
- Patch the current plan artifact only.
- Reply with a short summary of changes, gate status, and any required user decision.

## Additional resources
- Plan template: [reference.md](reference.md)
