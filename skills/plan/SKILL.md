---
name: plan
description: Orchestrate the /plan workflow to create or update the current plan artifact (autonamed by Cursor) as the planning write surface and implementation plan. Use when the user runs /plan, asks to create a plan, or wants to progress planning stages with validation and reviews.
---

# /plan Orchestrator

## Purpose
Create or update the current markdown plan artifact and move it through Problem, Feature, Technical, Implementation, and Reviews with deterministic validators and decision logging. The markdown artifact is the authoring write surface; in `registry-first`, a successful compile later hands planning authority to compiled registry YAML. Section-owner skills run as sub-agents and return drafts; the orchestrator is the only writer and runs the Q/A loop inline with the user.

## Core rules
- The current markdown plan artifact is the planning write surface; do not assume a fixed filename.
- **Artifact authority contract (required)**:
  - the selected harness-local plan artifact is authoritative for authoring intent, rationale, and amendments.
  - compiled registry YAML is authoritative for local planning structure, joins, validator inputs, and projection metadata after successful compile in `registry-first`.
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
- Workflow order is fixed: Problem -> Feature -> Technical -> Implementation -> Reviews.
- Hard rule: `/problem-definition` and `/critical-ideation` are Q/A gated before advancing; run the Q/A loop inline with the user and only when the checklist fails or `Questions` is non-empty.
- **No gate flips without evidence**: before changing any of `Status`, `CurrentStage`, or any Gate Results, include a short checklist in chat stating:
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
5) Determine `CurrentStage`.
6) Run validators in stage order up to the current stage.
7) Route to the first failing gate and call the owner skill as a sub-agent to produce a draft section. Provide any known agent roster or `## Context Snapshot` so ownership can be assigned correctly.
8) Run the human Q/A loop inline with the user using the gate's mode (see map below) when:
   - the validator fails, OR
   - `Questions` is non-empty, OR
   - you are moving into/through **TechnicalClarity** and you have not yet run at least one `mode=comprehension` checkpoint in this /plan invocation, OR
   - you are moving into/through **PlanReadiness** and you have not yet run at least one `mode=comprehension` checkpoint in this /plan invocation.
   Keep these checkpoints lightweight (2–3 targeted questions + one scope/ownership confirmation).
9) Re-run the owner sub-agent as needed until the gate passes.
10) Orchestrator writes the accepted output into the plan section.
11) Re-run the affected validator.
12) Advance stage only when its gate passes.
13) Update `Status`, `CurrentStage`, and any Gate Results only after providing the “no gate flips without evidence” checklist in chat.
    - Do not set `Status: Approved` unless `PlanStateSanity` passes.
14) Reviews stage only: run planning reviews, then auto-remediate findings that are purely clarity/structure improvements and do not change decisions.
    - **No paper reviews**: after any remediation or other material plan edits, regenerate reviews (or re-run the same review agents) so `PlanningReviewsComplete` reflects the updated document.
    - If reviews are stale (plan changed since last review run), `PlanningReviewsComplete` MUST be `Fail` until re-run.
15) Repeat the review -> remediation loop until findings are resolved, deduped as ignorable/non-relevant, or no new findings appear.
16) Only surface findings to the user when they require human agency (policy/compliance/cost/trust boundaries, decision boundaries, external source approval, contradictions with explicit assumptions or authority contracts, or remediation target is `Unknown`). Ask for A/R/D only for this reduced set.
17) Hard rule: do not set `Status: Approved` or `PlanningReviewsComplete: Pass` if any human-agency items remain unresolved. Stop and request dispositions first.

## Validators (deterministic)
- ProblemDefinitionComplete: problem statement, measurable success criteria, constraints, scope/anti-scope, decision boundaries. Must be Q/A gated; inline loop only when needed.
- FeatureClarity: evaluation criteria, assumptions/tests, ranked risks with status, alternatives rejected, >=1 failure mode. Must be Q/A gated after critical-ideation; inline loop only when needed.
- TechnicalClarity: integration points named, failure modes per integration point, risks/assumptions updated, invariants respected.
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
    - the following “hard questions” MUST be decided or DR-deferred with trigger (PlanTier: Full):
      - migration tooling (Alembic vs raw SQL)
      - cutover criteria (when fallback is removed)
      - cache staleness policy (TTL default/max; invalidation yes/no)
      - Tier C onboarding readiness (provisioning/active status & 503 behavior)
- PlanStateSanity (blocks false “Approved/Execution”):
  - Do NOT allow `Status: Approved` or `CurrentStage: Build/Execution` if:
    - any gate is not `Pass`, OR
    - `Open questions` contains any item with `Status: Open` (or missing Status), OR
    - ambiguity markers remain in critical areas (Problem/Technical/Implementation/Decision Log), including: `TBD`, `to be decided`, `choose later`, `or decide later`
      - unless the ambiguity is explicitly captured as a Decision boundary (A/B/C) or a DR-backed Defer with a trigger.
- PlanningReviewsComplete: required reviews done with dispositions logged; expert-tech either done or N/A with rationale.
  - **Stale review detection (mechanical)**:
    - Each required review block MUST include a refreshed stamp in one of these canonical forms:
      - `Refreshed: YYYY-MM-DD` (preferred), OR
      - `(refreshed YYYY-MM-DD)` (legacy, allowed for backward compatibility)
    - If no refreshed stamp is present for any required review, treat reviews as stale -> gate fails.
    - If plan `LastUpdated` is later than any required review’s refreshed stamp, treat reviews as stale -> gate fails.
    - Only pass when required reviews are refreshed for the current plan state.

## Gate -> owner skill map (sub-agents)
- ProblemDefinitionComplete -> `/problem-definition`
- FeatureClarity -> `/critical-ideation`
- TechnicalClarity -> `/technical-planning`
- PlanReadiness -> `/implementation-planning`
- PlanningReviewsComplete -> `/planning-reviews`

## Gate -> Q/A loop mode map (inline)
- ProblemDefinitionComplete -> `qa-loop mode=default`
- FeatureClarity -> `qa-loop mode=default`
- TechnicalClarity -> `qa-loop mode=comprehension` (must run at least once per /plan invocation when moving into/through this gate)
- PlanReadiness -> `qa-loop mode=comprehension` (must run at least once per /plan invocation when moving into/through this gate)
- PlanningReviewsComplete -> `qa-loop mode=disposition`

## Review auto-remediation routing
- Problem -> `/problem-definition`
- Feature -> `/critical-ideation`
- Technical -> `/technical-planning`
- Implementation -> `/implementation-planning`
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
- Keep sections as short as possible while still passing the gate.
- Prefer bullets over prose.
- If a section can be satisfied in 3-5 bullets, do not expand it.

## Context handling
- Each sub-agent is responsible for collecting minimal necessary context for its section.
- The Implementation Planning sub-agent owns the `## Context Snapshot` section and should fill any missing context required for execution, including the agent roster and a delegation-ready workstream matrix if not already captured.
- Only hard-block when missing context makes a gate unsafe to pass.

## Sub-skills used (run as sub-agents unless noted)
- `/problem-definition` -> sub-agent, Q/A gated (inline loop when needed)
- `/critical-ideation` -> sub-agent, Q/A gated (inline loop when needed)
- `/technical-planning` -> sub-agent, Q/A gated (inline loop when needed)
- `/implementation-planning` -> sub-agent, Q/A gated (inline loop when needed)
- `/planning-reviews` -> inline or sub-agent, Q/A gated (inline loop when needed)

## Output
- Patch the current plan artifact only.
- Reply with a short summary of changes, gate status, and any required user decision.

## Additional resources
- Plan template: [reference.md](reference.md)
