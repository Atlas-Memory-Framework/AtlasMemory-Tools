# /plan skill — how we use it

This directory contains the `/plan` **orchestrator** skill (`SKILL.md`) and the plan template it uses to create new plan artifacts (`reference.md`).

This README explains the *human workflow* for using `/plan` day-to-day.

## What `/plan` does

`/plan` creates or updates a **single plan artifact** (a markdown file in the active harness planning directory) and moves it through:

- **Problem → Feature → Technical → Human Readability → Implementation → Automation (when targeted) → Reviews**

It uses deterministic “gate” checks to decide what to do next, and it logs decisions in the plan’s **Decision Log**.
Human Readability is enforced as a gate between Technical and Implementation, even though the persisted
`CurrentStage` remains one of the plan state stages.
When available, `skills/plan/scripts/validate_plan.py` provides the mechanical gate check for plan
structure, automation manifest readiness, false approval states, and stale planning reviews.

Authority model:

- the markdown plan is the authoring write surface
- compiled registry YAML, when used, is a derived machine-readable package for joins, validator inputs, and projection metadata; it is not independent authoring authority
- GitHub issues and PRs remain the execution truth
- rendered overlays and project boards are derived views, not authoring inputs

## The most important rule: authoring artifact selection

`/plan` always operates on exactly one markdown plan document: the selected **authoring artifact**.

- If your last message references a plan via `@path`, that plan **must** be used as the authoring artifact.
- If multiple plans are referenced, you must pick one (single-select) before `/plan` continues.
- The assistant must echo the selection:
  - `AuthoringArtifact = <path>`

### How to pick the authoring artifact explicitly

In chat, reference the plan file:

```text
@project/plans/my-plan.plan.md /plan continue
```

## Many atomic plans in one campaign

Large efforts should be split into multiple small plan artifacts, but `/plan` still operates on exactly one selected authoring artifact per invocation.

Recommended pattern:

- one plan owns one primary outcome
- give each plan a stable `PlanId`
- group related plans with optional `PlanGroup`
- connect shards with optional `ParentPlan`, `DependsOnPlans`, `BlocksPlans`, and `AtomicScope`
- keep cross-plan metadata descriptive; it is not a registry and does not replace explicit `@path` selection
- use `/local-plan-agent-runtime` for agentic review of one selected plan at a time
- project issues only after that plan's implementation and automation sections are explicit enough for zero-interaction agents

## Typical ways to use `/plan`

### 1) Start a new plan

Use this when you don’t have a plan artifact yet.

```text
/plan
Goal: <1–2 sentences>
Constraints: <optional bullets>
```

If no plan is referenced, `/plan` will create a new plan doc from `reference.md` and echo it as the selected authoring artifact.

### 2) Continue an existing plan

```text
@project/plans/<plan>.plan.md /plan continue
```

`/plan` will:

- run gates in order
- route to the first failing gate
- draft missing sections via section-owner subskills
- ask targeted questions only when required to pass a gate

### 3) Ask for a focused review (e.g., Security/Privacy only)

```text
@.../my-plan.plan.md Use /plan to review. Focus on security/privacy. Do we need more work here?
```

Notes:

- The assistant should still respect the gating model and update the plan artifact, but keep the scope to the requested review area.
- If edits are made, reviews must be refreshed (see “No paper reviews”).

### 4) Update the plan with new constraints or authoritative inputs (deployment, cost, policy)

This is the most common “mid-plan” workflow: you learn something real (e.g., how CI deploys) and want the plan to match reality.

```text
@.../my-plan.plan.md /plan
New info: our authoritative deployment workflow is .github/workflows/deploy-dev.yml and it works today.
Update the implementation plan to align to that and include any required provisioning, activation, rollout, or rollback steps.
```

## How `/plan` progresses stages (gates)

`/plan` progresses only when the deterministic gates pass:

- **ProblemDefinitionComplete**
- **FeatureClarity**
- **TechnicalClarity**
- **HumanReadabilityReview**
- **PlanReadiness**
- **AutomationReadiness**
- **PlanStateSanity**
- **PlanningReviewsComplete**
- **ReviewsApprovedReentryAudit**

If a gate fails, `/plan` will:

- draft missing content in the correct section (via section-owner subskills)
- run a lightweight Q/A loop when required (especially for Technical/Implementation comprehension checkpoints)
- re-run the gate

## “No paper reviews” (critical)

If the plan changes in a material way after a review was written, that review is **stale**.

Expectation when using `/plan`:

- after material edits, **re-run** the required reviews (zero-context, implementer readiness, security/privacy; expert-tech when required)
- do not leave `PlanningReviewsComplete: Pass` based on stale review text
- new review blocks should record `ReviewedPlanHash: sha256:<hash>` or timestamp-level `RefreshedAt`
  so same-day material edits cannot look fresh

## What you should provide to get the best results

- **Authoring artifact reference** via `@path`
- **Goal + hard constraints**
- **Anything that is authoritative in the repo for the concern being planned** (examples):
  - deployment workflow(s) that actually run
  - the real auth boundary implementation
  - existing infrastructure modules/scripts
- **Your desired focus**: cost, correctness, security/privacy, rollout, etc.

## Common outputs you should expect in the plan

- **Decision Log** entries (`DR-xxx`) whenever there is a decision boundary
- **Workstreams** with explicit owners and merge points
- **Named gates** (CI vs deployed) with clear “green means” definitions
- **Runbooks** for migrations, provisioning, rollout, rollback, or external effects when those domains are in scope
- **Planning Reviews** with findings + dispositions (Accept/Reject/Defer)
- **Dynamic specialist review roster** when the plan touches high-risk or domain-specific boundaries

## Related files

- **Orchestrator rules**: `SKILL.md`
- **Plan template**: `reference.md`
- **Issue/project projection**: `../plan-to-issues/SKILL.md`
- **Automation decomposition**: `../automation-decomposition/SKILL.md`
- **HTML review artifacts**: `../plan-to-html/SKILL.md`
- **Session handoffs**: `../handoff/SKILL.md`

## Optional external tracking

Plans can carry optional tracking metadata for GitHub issues or projects, but that metadata does not replace the markdown plan as the authoring surface. Compiled registries and tracking systems are derived packages or downstream execution surfaces, not independent authoring authority.

Plans can also carry optional campaign metadata for multi-plan efforts:

- `PlanGroup`: campaign or roadmap grouping
- `ParentPlan`: parent/index plan id or path
- `DependsOnPlans`: upstream plan ids or paths
- `BlocksPlans`: downstream plan ids or paths
- `AtomicScope`: the single outcome this plan owns

This metadata is for navigation, review, and later issue projection. It is not a source of truth for selecting the authoring artifact.

Recommended pattern:

- keep tracking metadata additive and optional
- use the new `plan-to-issues` skill to preview or apply issue projections
- avoid patching unstable plan drafts with issue links until the tracking objects actually exist
