# Plan Authoring Template (Slim)

Use this file to create a new plan doc when missing. Cursor will autoname it.
Keep sections but let owners fill only their sections.

Optional external tracking metadata can be added without changing plan semantics.
Keep it additive and optional so the markdown body remains the authoring write surface and does not get confused with execution or compiled-registry authority.

Example optional frontmatter:

```yaml
tracking:
  provider: github
  project: "OWNER workflow readiness"
  epic: ""
  mode: draft
```

```md
# Feature: <name>

## Plan State
PlanFormatVersion: 2
PlanId: <auto or short unique id>
Status: Draft | ProblemDefined | FeatureChallenged | TechnicalChallenged | Planned | StructurallyComplete | SubstantivelyReviewed | Approved | InBuild | Shipped
StructuralStatus: Draft | StructurallyComplete
SubstanceStatus: NotReviewed | NeedsWork | SubstantivelyReviewed
ProjectionApproval: NotRequested | Blocked | ApprovedForProjection
DispatchApproval: NotRequested | Blocked | ApprovedForDispatch
CurrentStage: Problem | Feature | Technical | Implementation | Automation | Reviews | Build
PlanTier: Lite | Full
AutomationTarget: none | manifest-only | issue-projection | unattended-prs
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
HumanReadabilityReview: Pass | Fail | N/A
PlanReadiness: Pass | Fail | N/A
AutomationReadiness: Pass | Fail | N/A
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
Problem narrative:
<1-2 paragraphs describing the real product/system failure or opportunity. The first two paragraphs must not use planning-meta terms such as plan, artifact, gate, issue manifest, registry, projection, or dispatch.>

Current broken workflow:
- ...

Desired workflow:
- ...

Why this matters / why now:
- ...

Current-state facts:
- Fact 1: ... (source: file|command|user|issue)
- Fact 2: ... (source: file|command|user|issue)
- Fact 3: ... (source: file|command|user|issue)

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
### Technical Plan Intro
<1-3 paragraphs explaining what will change in the system, why this approach fits the problem, and which existing components/data flows it touches. A new engineer should understand what is being built and why from this intro plus Problem Definition.>

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
- WS1: <name>
  - Owner:
  - Agent type: <generalPurpose | test-engineer | code-reviewer | explore>
  - Delegate: required | optional
  - Intended behavior change:
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

## Automation Issue Manifest
<!-- owner: automation-decomposition -->
Applies when `AutomationTarget` is not `none`.

### Dispatch policy
- Automation target: none | manifest-only | issue-projection | unattended-prs
- Dispatch strategy: sequential | parallel-bounded | fanout
- Max concurrent work items:
- Required labels:
- Default reviewer / reviewer pool:
- Branch policy:
- PR policy: draft | ready-for-review
- Merge policy: manual | auto-merge-after-gates
- Rebase/update policy:
- Failure policy:
- Human approval required before dispatch: yes | no

### Containers
- WS1:
  - Type: epic | workstream | phase | merge-point
  - Parent:
  - Dispatch: tracking-only
  - Source plan sections:
    - ...

### Leaf issues
- WS1-LEAF-ID: <title>
  - Type: spike | story | task | validation | integration | release
  - Parent: WS1
  - Owner:
  - Agent type: generalPurpose | test-engineer | code-reviewer | explore
  - Dispatch: agent-ready | manual-review | blocked | tracking-only
  - Depends on:
    - WS1-OTHER-LEAF
  - External blockers:
    - <owner/status/blocker or none>
  - Manual blockers:
    - <owner/status/blocker or none>
  - Files in scope:
    - path/to/file.ext
  - Files out of scope:
    - path/to/other.ext
  - Required gates:
    - G-...
  - Validation:
    - <command or evidence artifact>
  - Acceptance criteria:
    - ...
  - One PR contract: yes | no
  - Risk / dispatch notes:
  - Source plan sections:
    - Implementation Plan / WS...

### Manifest validation summary
- Dependency graph acyclic: Pass | Fail
- Dependencies resolvable: Pass | Fail
- Gate coverage complete: Pass | Fail
- File-scope conflicts resolved: Pass | Fail
- Acceptance criteria executable: Pass | Fail
- Required metadata complete: Pass | Fail
- Notes / waivers (must cite DR-xxx):
  - ...

## Planning Reviews
<!-- owner: planning-reviews -->
### Zero-Context Review (required)
- Reviewer: doc-reviewer-zero-context
- Refreshed: <YYYY-MM-DD>
- Re-entry audit answers (required when updating a plan at CurrentStage: Reviews or approved/complete status):
  - What is being built:
  - Why now:
  - Repos involved:
  - What changes first:
  - What must not happen:
  - How work is validated:
  - What remains blocked:
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

### Human Readability Review (required)
- Reviewer:
- Refreshed: <YYYY-MM-DD>
- Findings:
  - Product/system clarity:
  - Technical narrative clarity:
  - Execution-mechanics leakage:
  - Strongest remaining ambiguity:
- Pass/fail readability statement:
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

### Automation Readiness Review (required when AutomationTarget != none)
- Reviewer: automation-readiness
- Refreshed: <YYYY-MM-DD>
- Findings:
  - Manifest gaps:
  - Dependency/gate/file-scope risks:
  - Dispatch policy risks:
  - Pass/fail readiness statement:
- Disposition:
  - Accept: <finding-id> -> DR-xxx
  - Reject: <finding-id> -> rationale
  - Defer: <finding-id> -> DR-xxx + trigger

## Execution Mechanics / Automation Appendix
### Authority / source-of-truth contract
- Authoring write surface: selected harness-local plan artifact
- Local planning authority after compile: selected harness-local planning registry
- Execution truth: GitHub issues / PRs / checks
- Execution UI / signal layer: GitHub Projects v2
- Derived read models / views: runtime mirror, rendered overlays, forecasts

### Projection and dispatch approvals
- Structural completion evidence:
- Substance review evidence:
- Projection approval evidence:
- Dispatch approval evidence:
- Dispatch remains blocked until:

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
