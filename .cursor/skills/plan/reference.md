# Plan Authoring Template (Slim)

Use this file to create a new plan doc when missing. Cursor will autoname it.
Keep sections but let owners fill only their sections.

Optional external tracking metadata can be added without changing plan semantics.
Keep it additive and optional so the markdown body remains the authoring write surface and does not get confused with execution or compiled-registry authority.

Example optional frontmatter:

```yaml
tracking:
  provider: github
  project: "MateuszKordasiewicz's Workflow readiness"
  epic: ""
  mode: draft
```

```md
# Feature: <name>

## Plan State
PlanFormatVersion: 2
PlanId: <auto or short unique id>
Status: Draft | ProblemDefined | FeatureChallenged | TechnicalChallenged | Planned | Approved | InBuild | Shipped
CurrentStage: Problem | Feature | Technical | Implementation | Reviews | Build
PlanTier: Lite | Full
DeliveryMode: DevOnly | SharedDev | Staging | Prod
ContextMode: UserProvided | RepoInferred | Greenfield
LastUpdated: <YYYY-MM-DD>
PrimaryOwner: <name/handle>
BaseBranch: <e.g. main>
BaseCommit: <git sha>
TargetBranch: <e.g. feat/my-feature>
Related: <issue/pr/link if any>
NextRequiredUserAction: <none | pick option A/B/C for DR-xxx | provide input for Qn | run /plan again>
BlockingDecision: <none | DR-xxx>
UnresolvedBlockers: <0 | N>
RubberStampSignals: <0 | N>
LastGateRun: <YYYY-MM-DD>

ArtifactAuthorityMode: legacy-plan | migration-bridge | registry-first

## Gate Results
ProblemDefinitionComplete: Pass | Fail | N/A
FeatureClarity: Pass | Fail | N/A
TechnicalClarity: Pass | Fail | N/A
PlanReadiness: Pass | Fail | N/A
PlanningReviewsComplete: Pass | Fail | N/A

## Decision Log
### DR-001: <Decision topic>
- Stage: Problem | Feature | Technical | Implementation | Reviews | Build
- Date:
- ScopeAffected: <files/components/systems>
- Decision:
- Options considered:
  - A) ...
  - B) ...
  - C) ...
- Why chosen:
- Consequences / follow-ups:
- Status: Accepted | Revisit | Deferred
- Revisit trigger (if not Accepted):

## Risks / Assumptions / Tests
- R1 (High): <risk>
  - Mitigation:
  - Owner:
  - Status: Mitigated | Tested | Accepted | Deferred (DR-xxx)
  - Trigger (if deferred):
- A1: <assumption>
  - Test:
  - Pass/Fail criteria:
  - Status: Untested | Tested | Accepted | Deferred (DR-xxx)

## Problem Definition
<!-- owner: problem-definition -->
Problem statement:
- ...

Success criteria (measurable):
- SC1:
- SC2:

Constraints:
- ...

Scope:
- In scope:
  - ...
- Out of scope:
  - ...

Definitions / glossary:
- Term: ...

Open questions:
- Q1: <question>
  - Status: Open | Resolved (DR-xxx) | Deferred (DR-xxx)
  - Trigger (if Deferred):

Decision boundaries (if any):
- Decision needed:
  - A) ...
  - B) ...
  - C) ...
Recommended default: <A/B/C> (why)

## Context Snapshot
<!-- owner: implementation-planning -->
### Inputs Provided
- ...

### System Understanding
- Summary:
- Components:
- Data flow:
- Key abstractions:

### Known Unknowns (ranked)
1) ...

### Questions to Proceed (ranked)
1) ...

### Repo Security Reality Check (optional but recommended)
<!-- owner: planning-reviews -->
<!-- Keep this short and evidence-driven. Do not include secrets. -->
- Refreshed: <YYYY-MM-DD>
- Backend JWT proof:
  - Observed default behavior:
  - Deployed env fail-closed mechanism:
  - Evidence hook (named gate):
- Internal endpoints:
  - Observed auth enforcement points:
  - Observed sensitive logging risks (if any):
  - Evidence hook (named gate):
- APIM header projection / bypass paths:
  - Observed projection/overrides:
  - Bypass risk summary:
  - Evidence hook (named gate):

### Artifact authority snapshot
- Authoring write surface: `.cursor/plans/<plan>.plan.md`
- Local planning authority after compile: `.cursor/planning-registry/**`
- Execution truth: GitHub issues / PRs / checks
- Execution UI / signal layer: GitHub Projects v2
- Derived read models / views: runtime mirror, rendered overlays, forecasts

## Challenge Artifacts
<!-- owner: critical-ideation -->
### Weaknesses
- W1:
- W2:

### Failure Modes
- FM1: <failure> - detection - prevention/mitigation

### Alternatives (including one disliked)
- Alt A:

### Milestones (measurable)
- Milestone:
  - Evidence:

## Technical Plan
<!-- owner: technical-planning -->
### Integration Points
- ...

### Proposed Architecture Changes
- ...

### Failure Modes (per integration point)
- ...

### Invariants / Non-Changes
- ...

### NFRs alignment
- ...

## Implementation Plan
<!-- owner: implementation-planning -->
### Agent roster (required for PlanTier: Full)
- <agent/owner>: <responsibilities>

### File Deltas (exhaustive) + rationale
- path/to/file.ext - change type (create/modify/delete) - owner (WSx / agent) - rationale

### Workstreams + merge points
- WS1: <name> (Owner: <agent>)
  - Agent type: <generalPurpose | test-engineer | code-reviewer | explore>
  - Delegate: required | optional
  - Tracking: <optional org/repo#123 or URL>
  - Depends on:
  - Review gates (named):
    - G-...
  - Owns files:
    - path/to/file.ext
  - Merge point / integration step:

### Delegation Quality Gate (required for PlanTier: Full)
- DQ-1 Workstream delegation metadata complete: Pass | Fail
  - Rule: Every workstream has `Owner`, `Agent type`, and `Delegate`.
- DQ-2 File ownership conflict-free before merge points: Pass | Fail
  - Rule: No file is owned by more than one active workstream before an explicit merge point.
- DQ-3 Delegation coverage: Pass | Fail
  - Rule: All non-trivial workstreams are marked `Delegate: required`.
- DQ-4 Validation delegation path present: Pass | Fail
  - Rule: Test/review gates identify delegated execution path (agent type or owner).
- Notes / waivers (must cite DR-xxx):
  - ...

### Phases + tasks + exit criteria
#### Phase 1: <name>
- Owner(s):
- Depends on:
- Tracking: <optional org/repo#123 or URL>
- Tasks (by owner):
  - Owner: <agent>
    - [ ] Task
- Exit criteria (evidence):
- Gates (named):
  - G-...

### Review gates (named + definitions)
- G-CI-Lint:
  - Where it runs: CI | Local | Deployed
  - Entry point / command:
  - Green means:
- G-CI-Unit:
  - Where it runs: CI | Local | Deployed
  - Entry point / command:
  - Green means:

### Merge points -> required gates
- MP1: <merge point / integration step>
  - Blocks on:
    - G-...

### Test Matrix
- Area/component - risk - test type - where it runs

### Test plan (CI vs deployed)
- CI:
  - ...
- Deployed environment:
  - ...

### Rollout / Rollback
- Rollout:
- Rollback trigger:
- Rollback steps:

## Planning Reviews
<!-- owner: planning-reviews -->
### Zero-Context Review (required)
- Reviewer: doc-reviewer-zero-context
- Refreshed: <YYYY-MM-DD>
- Findings (schema):
  - Missing context:
  - Contradictions:
  - Unclear decisions:
  - Risks and edge cases:
  - What I would screw up implementing tomorrow:
- Disposition:
  - Accept: <finding-id> -> DR-xxx
  - Reject: <finding-id> -> rationale
  - Defer: <finding-id> -> DR-xxx + trigger

### Expert Technical Review (conditional)
- Trigger:
- Reviewer:
- Refreshed: <YYYY-MM-DD>
- Findings (schema):
  - Technical risks and integration gaps:
  - Missing validations or operational steps:
  - Contradictions with stated invariants or authority boundaries:
  - Patch suggestions (point to sections):
- Disposition:
  - Accept: <finding-id> -> DR-xxx
  - Reject: <finding-id> -> rationale
  - Defer: <finding-id> -> DR-xxx + trigger

### Security/Privacy Review (required)
- Reviewer:
- Refreshed: <YYYY-MM-DD>
- Findings (schema):
  - Security/privacy risks:
  - Missing validations or mitigations:
  - Patch suggestions (point to sections):
- Disposition:
  - Accept: <finding-id> -> DR-xxx
  - Reject: <finding-id> -> rationale
  - Defer: <finding-id> -> DR-xxx + trigger

### Implementer Readiness Review (required)
- Reviewer:
- Refreshed: <YYYY-MM-DD>
- Findings:
  - Top 5 gotchas:
  - Evidence needed to prevent each gotcha:
  - Pass/fail readiness statement:
- Disposition:
  - Accept: <finding-id> -> DR-xxx
  - Reject: <finding-id> -> rationale
  - Defer: <finding-id> -> DR-xxx + trigger

## Execution Status
Phase: <name>
Status: not started | in progress | blocked | complete

Workstreams:
- WS1: <status> - completed tasks / blockers
- WS2: ...

Completed tasks:
- ...

Blocked:
- ... - reason - requires DR-xxx / plan patch

Build gates:
- Lint - pass/fail - notes
- Tests - pass/fail - notes

Next actions:
- ...
```
