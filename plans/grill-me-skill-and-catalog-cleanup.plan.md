# Feature: Materiality-Driven Grill Me and Skill Catalog Cleanup

## Plan State
PlanFormatVersion: 2
PlanId: grill-me-skill-and-catalog-cleanup
PlanGroup: skill-library-quality
PlanKind: feature
ParentPlan: none
DependsOnPlans: none
BlocksPlans: none
AtomicScope: Add one materiality-driven design interview skill and the minimum catalog checks needed to ship it safely.
CampaignMetadataAuthority: descriptive-only; explicit @path authoring artifact selection wins
Status: InBuild
StructuralStatus: StructurallyComplete
SubstanceStatus: SubstantivelyReviewed
ProjectionApproval: NotRequested
DispatchApproval: NotRequested
CurrentStage: Build
PlanTier: Lite
AutomationTarget: none
DeliveryMode: DevOnly
ContextMode: UserProvided
LastUpdated: 2026-08-19
PrimaryOwner: Atlas
BaseBranch: main
BaseCommit: 464660e
TargetBranch: main
Related: current conversation
NextRequiredUserAction: none
BlockingDecision: none
UnresolvedBlockers: 0
RubberStampSignals: 0
LastGateRun: 2026-08-19

ArtifactAuthorityMode: legacy-plan

## Gate Results
IntentModelComplete: Pass
ProblemDefinitionComplete: Pass
FeatureClarity: Pass
TechnicalClarity: Pass
HumanReadabilityReview: Pass
PlanReadiness: Pass
AutomationReadiness: N/A
PlanningReviewsComplete: Pass

## Decision Log
### DR-001: Start with one grilling skill
- Stage: Feature
- Date: 2026-08-19
- ScopeAffected: skills/grill-me, README.md, manifests/atlas-tools.v1.json
- Decision: Create `grill-me` as one self-contained skill; extract a reusable `grilling` primitive only after a second real workflow needs it.
- Options considered:
  - A) One `grill-me` skill now.
  - B) Add both `grill-me` and `grilling` immediately.
  - C) Add no skill and expand `/plan` only.
- Why chosen: The user wants the alignment primitive without cargo-culting Matt Pocock's catalog and explicitly questioned whether two skills are needed.
- Consequences / follow-ups: A future repo-writing interview or triage workflow may justify extraction, but duplication alone will not.
- Status: Accepted
- Revisit trigger (if not Accepted): none

### DR-002: Build before formal planning reviews
- Stage: Build
- Date: 2026-08-19
- ScopeAffected: this plan and the file deltas below
- Decision: Proceed after the user's explicit "lets proceed" approval while keeping `PlanningReviewsComplete: Fail` until post-implementation review is recorded.
- Options considered:
  - A) Implement the bounded Lite scope now and record verification evidence.
  - B) Stop for the full planning review workflow.
  - C) Add only documentation.
- Why chosen: The work is local Markdown, JSON, Python validation, and tests with no production, secret, identity, deployment, or external-effect surface.
- Consequences / follow-ups: The final diff still requires repository verification and an independent review pass.
- Status: Accepted
- Revisit trigger (if not Accepted): none

## Risks / Assumptions / Tests
- R1 (High): `grill-me` rewards question volume and creates an illusion of rigor.
  - Mitigation: Rank questions by materiality and stop when remaining answers cannot materially change the design.
  - Owner: grill-me skill
  - Status: Mitigated
- R2 (High): The skill asks the user for facts available in the repo or evidence.
  - Mitigation: Require context inspection before questions and route empirical uncertainty to research or a prototype.
  - Owner: grill-me skill
  - Status: Mitigated
- R3 (Medium): Catalog cleanup expands into an installer redesign.
  - Mitigation: Limit this tranche to manifest integrity, alias-backed identity drift, and validation tests; defer profiles/selective installation.
  - Owner: catalog workstream
  - Status: Mitigated
- A1: Existing `/plan` and review skills can formalize and validate the resulting decision record.
  - Test: README flow routes `grill-me` into `plan` and review rather than adding duplicate spec/review skills.
  - Pass/Fail criteria: One clear route exists and no new duplicate skill is added.
  - Status: Tested

## Intent Model
Latent target:
- Improve thinking before code generation by extracting consequential decisions, contradictions, and unnecessary scope from the user's half-formed design.
- Treat skills as inspectable decision procedures tied to recurring failure modes, not as a large prompt collection.
- Confidence: High

Anti-targets:
- Do not optimize for number of questions or "relentlessness."
- Do not create both `grill-me` and `grilling` without demonstrated reuse.
- Do not silently turn the interview into implementation.
- Do not expand this tranche into every attractive skill from another repository.

Expression-state notes:
- User phrase: "the 27th question made him realize what he actually wanted"
  - Interpreted meaning: Breakthrough value matters; question count does not.
  - Alternate plausible interpretations: Longer sessions are inherently better.
  - Confidence: High
  - Risk if wrong: The skill becomes exhausting and performative.
- User phrase: "grill -> formalize specification -> validate/review"
  - Interpreted meaning: Discovery, formalization, and verification are distinct phases with an approval boundary before implementation.
  - Alternate plausible interpretations: Three new skills must be created now.
  - Confidence: High
  - Risk if wrong: Atlas duplicates its existing plan and review machinery.

Open Loop Ledger:
- OL-001:
  - Type: scope-gap
  - Source: user feedback
  - Latent object: Whether `grilling` is a separate reusable primitive.
  - Why it matters: Premature extraction adds catalog and routing load.
  - Candidate interpretations:
    - A) One skill now.
    - B) Wrapper and primitive now.
    - C) No skill.
  - Status: Resolved
  - Resolution evidence: DR-001 and user's permission to choose the simpler structure.
  - Blocks: none

Intent checksum:
- Success means:
  - The skill discovers material decisions and deletes unjustified scope before planning.
  - It distinguishes decisions from facts and discussion from experiments.
  - It produces a compact record that existing planning/review workflows can consume.
- Failure would look like:
  - Endless plausible questions, passive agreement, or premature implementation.
- User confirmation needed:
  - None; the user explicitly approved proceeding with this direction.

## Problem Definition
Problem narrative:
The current skill library can turn user intent into governed implementation work, but it lacks a lightweight interactive procedure for discovering what the user actually wants before formalization. Existing challenge and Q/A skills validate defined sections and known criteria; they do not adaptively explore a dependency-ordered decision tree or actively remove scope.

The desired workflow inspects available evidence first, asks only high-value decisions, challenges contradictions and unnecessary scope, and stops when conversation no longer has enough expected value. It then hands a concise decision record to the existing formalization and review path without implementing anything.

Current broken workflow:
- A vague request can enter `/plan`, where formal structure may arrive before the hidden design decision is discovered.
- `human-qa-loop` validates target outputs but does not maintain a materiality-ranked decision frontier.
- `critical-ideation` emits a fixed challenge packet rather than conducting an adaptive interview.

Desired workflow:
- The user invokes `grill-me` for a plan, design, idea, or consequential decision.
- The agent resolves discoverable facts, ranks unresolved decisions by expected value, and asks in dependency order.
- Discussion stops for research/prototyping when evidence is the real missing input.
- The result is a decision record and proposed specification for user approval and later planning/review.

Why this matters / why now:
- The user supplied external validation that the highest-value outcome is major scope correction before code, and explicitly asked to implement the primitive now.

Current-state facts:
- Fact 1: The manifest currently inventories 26 skills with names and paths; see `manifests/atlas-tools.v1.json`. (source: file)
- Fact 2: `human-qa-loop` asks targeted questions to close explicit success criteria; see `skills/human-qa-loop/SKILL.md`. (source: file)
- Fact 3: `critical-ideation` requires a fixed challenge packet; see `skills/critical-ideation/SKILL.md`. (source: file)
- Fact 4: The manifest installs `skills/implement`, whose frontmatter declares `name: build`, without an explicit alias recording that difference. (source: file)

Success criteria (measurable):
- SC1: `grill-me` declares trigger, inputs, procedure, output, stop, escalation, and validation behavior.
- SC2: The procedure ranks material questions, researches facts first, tracks scope deletion, and blocks implementation until approval.
- SC3: Catalog validation fails an undeclared manifest/frontmatter mismatch and passes an explicitly aliased mismatch.
- SC4: Generated Codex copies and repository verification pass.

Constraints:
- Preserve the repo-first source/generated-copy model.
- Keep the new skill self-contained and small.
- Preserve current `/build` and `/implement` behavior through an explicit alias rather than a disruptive rename.
- Do not add selective install/profile support in this tranche.

Scope:
- In scope:
  - Add `skills/grill-me/SKILL.md`.
  - Register the skill and record the existing `implement`/`build` identity alias in the manifest.
  - Add catalog/frontmatter integrity validation and tests.
  - Document `grill-me -> plan -> review -> build` in the README.
  - Regenerate committed Codex adapters.
- Out of scope:
  - Separate `grilling`, prototype, domain-language, questionnaire, TDD, or router skills.
  - Installer profiles or harness-specific invocation-policy translation.
  - Runtime, issue, Project, or deployment changes.

Definitions / glossary:
- Material question: An unresolved decision whose answer has a meaningful chance of changing the design and a meaningful cost if guessed incorrectly.
- Decision frontier: Decisions whose prerequisites are already resolved.
- Evidence escalation: Stop interviewing when research, code inspection, measurement, or a prototype is needed.
- Scope deletion: Explicitly removing work that no longer contributes to the intended outcome.

Open questions:
- None. Status: Resolved (DR-001)

Decision boundaries:
- None; the only material structural choice is resolved in DR-001.

## Context Snapshot
### Inputs Provided
- User's detailed Theo/Matt analysis and proposed disciplined procedure.
- Current repository skills, manifest, harness generator, and tests.

### System Understanding
- Summary: Canonical skills under `skills/` are copied into harness-specific directories from the manifest.
- Components: skill Markdown, manifest JSON, harness library, repository verifier, unit tests, README.
- Data flow: canonical skill -> manifest inventory -> harness generator -> committed `.codex` copy -> verification.
- Key abstractions: canonical source, generated adapter, alias, decision procedure.

### Known Unknowns (ranked)
1) None that block the bounded implementation.

### Questions to Proceed (ranked)
1) None.

### Dynamic Review Roster
- Refreshed: 2026-08-19
- Triggered specialist reviews:
  - Review: security/privacy
    - Why triggered: Required planning review; no sensitive-data surface is introduced.
    - Specialist/persona: code reviewer
    - Evidence hooks: diff contains only local instructions, validation, tests, manifest, docs, and generated copies.
    - Status: Required
- Reviews considered but not triggered:
  - Review: automation-runtime
    - Why not triggered: Runtime templates and dispatch are out of scope.

## Challenge Artifacts
### Weaknesses
- W1: A scoring formula can become fake precision; the skill should use materiality as a ranking heuristic, not calculate invented probabilities.
- W2: Producing a proposed specification can accidentally duplicate `/plan`; keep it concise and route formalization onward.

### Failure Modes
- FM1: Interview keeps generating low-value questions -> detect repeated answers/no design changes -> stop and summarize.

### Alternatives (including one disliked)
- Add Matt's full catalog: rejected because it adds overlapping workflows without evidence of recurring Atlas failures.
- Add both wrapper and primitive: rejected for now because only one consumer exists.

### Milestones (measurable)
- Milestone: New skill, catalog checks, docs, generated copy, and tests all pass repository verification.
  - Evidence: `python3 scripts/verify_repo.py` exits zero.

## Technical Plan
### Technical Plan Intro
Add one canonical self-contained skill containing the materiality-driven interview algorithm. Register it through the existing manifest so harness generation remains unchanged. Extend catalog tests with a YAML-backed frontmatter reader that checks syntax and required string fields, and requires name mismatches to be represented by aliases; this makes the current `implement`/`build` distinction explicit without renaming installed paths.

### Integration Points
- `skills/grill-me/SKILL.md` -> canonical behavior.
- `manifests/atlas-tools.v1.json` -> inventory and the explicit `implement`/`build` identity alias.
- `tests/test_manifest_and_harness.py` -> catalog integrity.
- `README.md` -> public workflow routing.
- `.codex/skills/grill-me/SKILL.md` -> generated adapter copy.

### Proposed Architecture Changes
- No new framework layer; one skill plus stronger inventory validation.

### Failure Modes (per integration point)
- Invalid YAML/frontmatter -> test failure.
- Undeclared name drift -> test failure.
- Generated-copy drift -> existing verification failure.

### Invariants / Non-Changes
- Existing installer copies all manifest entries.
- Existing canonical/generated authority remains unchanged.
- `build` remains the public frontmatter name for the existing implementation skill.

### NFRs alignment
- Low context load, no network/runtime side effects, deterministic catalog checks.

## Implementation Plan
### File Deltas (exhaustive) + rationale
- `skills/grill-me/SKILL.md` - create - WS1 - canonical interview procedure.
- `skills/grill-me/agents/openai.yaml` - create - WS1 - explicit user-invocation policy and UI metadata.
- `skills/grill-me/references/eval-cases.md` - create - WS1 - permanent behavioral regression fixtures for future skill evaluations.
- `skills/local-plan-agent-runtime/agents/openai.yaml` - modify - WS2 - quote a colon-bearing prompt so canonical metadata is valid YAML.
- `skills/plan-execution-readiness/agents/openai.yaml` - modify - WS2 - quote a colon-bearing prompt so canonical metadata is valid YAML.
- `manifests/atlas-tools.v1.json` - modify - WS2 - register the skill and make the existing `implement`/`build` identity mismatch explicit.
- `scripts/harnesslib.py` - modify - WS2 - render product metadata with valid YAML comments.
- `tests/test_manifest_and_harness.py` - modify - WS2 - validate frontmatter/catalog identity.
- `requirements-dev.txt` - modify - WS2 - declare the pinned YAML parser used by catalog validation.
- `README.md` - modify - WS2 - document the workflow.
- `.codex/skills/grill-me/**` - generated - integrator - add the checked-in Codex adapter.
- `.codex/skills/*/agents/openai.yaml` - generated - integrator - replace invalid HTML generated headers with YAML comments.
- `plans/grill-me-skill-and-catalog-cleanup.plan.md` - create/modify - integrator - authoring and execution evidence.

### Workstreams + merge points
- WS1: Grill-me skill
  - Owner: skill author agent
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: Add materiality-driven pre-implementation discovery.
  - Depends on: none
  - Review gates: G-Skill-Behavior, G-Repo-Verify
  - Owns files: `skills/grill-me/SKILL.md`, `skills/grill-me/agents/openai.yaml`, `skills/grill-me/references/eval-cases.md`
  - Merge point / integration step: MP1 after WS2 catalog changes.
- WS2: Catalog integrity and docs
  - Owner: catalog agent
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: Register the skill and fail silent identity drift.
  - Depends on: none
  - Review gates: G-Catalog-Unit, G-Repo-Verify
  - Owns files: `manifests/atlas-tools.v1.json`, `scripts/harnesslib.py`, `tests/test_manifest_and_harness.py`, `requirements-dev.txt`, `README.md`
  - Merge point / integration step: MP1 regenerate adapters and verify.

### Phases + tasks + exit criteria
#### Phase 1: Canonical changes
- Owner(s): WS1, WS2
- Depends on: none
- Tasks: Create skill; update catalog, tests, and docs.
- Exit criteria (evidence): focused catalog tests pass.
- Gates (named): G-Skill-Behavior, G-Catalog-Unit

#### Phase 2: Integration
- Owner(s): integrator
- Depends on: Phase 1
- Tasks: Regenerate Codex adapters, run repository verification, review diff.
- Exit criteria (evidence): generated copies are fresh and repository verifier exits zero.
- Gates (named): G-Repo-Verify

### Review gates (named + definitions)
- G-Skill-Behavior:
  - Where it runs: Local
  - Entry point / command: semantic review of SKILL.md against SC1-SC2 and behavioral fixtures.
  - Green means: materiality, fact discovery, dependency ordering, scope deletion, escalation, stop, output, and approval boundary are all explicit.
- G-Catalog-Unit:
  - Where it runs: Local
  - Entry point / command: `python3 -m unittest tests.test_manifest_and_harness`
  - Green means: all catalog and harness tests pass.
- G-Repo-Verify:
  - Where it runs: Local
  - Entry point / command: `python3 scripts/verify_repo.py`
  - Green means: full repository verification passes.

### Merge points -> required gates
- MP1: Canonical skill and catalog/docs changes integrated, then adapters regenerated.
  - Blocks on: G-Skill-Behavior, G-Catalog-Unit, G-Repo-Verify

### Test Matrix
- Skill contract - semantic omission/misrouting risk - invariant review - Local
- Manifest/frontmatter identity - silent drift risk - unit tests - Local
- Adapter freshness - generated-copy drift - repository verification - Local

### Test plan (CI vs deployed)
- CI/local: focused unit test and full `verify_repo.py`.
- Deployed environment: N/A; no deployed behavior.

### Rollout / Rollback
- Rollout: Merge canonical files and regenerated adapters together.
- Rollback trigger: Catalog verification regresses or skill routes ordinary planning requests into unwanted interviews.
- Rollback steps: Revert this bounded change set and remove the generated adapter entry.

## Automation Issue Manifest
Not applicable: `AutomationTarget: none`.

## Planning Reviews
### Zero-Context Review
- Reviewer: independent final-scope reviewer
- Refreshed: 2026-08-19
- RefreshedAt: 2026-08-19T06:07:04-04:00
- ReviewedPlanHash: sha256:20639c41d2069b2b77acbf3a4597d456ce3fa31797d2935245ff8dffd5eb3a46
- Re-entry audit answers:
  - What is being built: One explicit-only materiality-driven design interview skill plus bounded catalog and YAML integrity cleanup.
  - Why now: The user validated pre-code alignment and scope deletion as the useful primitive and approved implementation.
  - Repos involved: AtlasMemory-Tools only.
  - What changes first: Canonical skill and metadata, then manifest/tests/docs, then generated copies.
  - What must not happen: No separate abstraction without reuse, no implicit grilling, and no implementation from interview approval.
  - How work is validated: Behavioral fixture review, focused unit tests, skill validation, full repository verification, and independent diff review.
  - What remains blocked: Nothing.
- Findings:
  - F-001: The integrated diff is self-contained and understandable without conversation context; no missing decisions or contradictions remain.
- Disposition:
  - Accept: F-001 -> retain the bounded implementation and validation evidence.

### Implementer Readiness Review
- Reviewer: independent final-scope reviewer
- Refreshed: 2026-08-19
- RefreshedAt: 2026-08-19T06:07:04-04:00
- ReviewedPlanHash: sha256:20639c41d2069b2b77acbf3a4597d456ce3fa31797d2935245ff8dffd5eb3a46
- Findings:
  - F-001: The materiality loop, re-ranking step, scope deletion, escalation paths, stop conditions, output contract, and effect boundary are explicit.
  - F-002: Catalog identity and metadata syntax have executable regression coverage; generated copies are current.
  - Pass/fail readiness statement: Pass.
- Disposition:
  - Accept: F-001 -> skill contract and behavioral fixtures.
  - Accept: F-002 -> catalog/harness tests and full repository verifier.

### Expert Technical Review
- Trigger: Skill routing, generated metadata, and catalog integrity changed.
- Reviewer: independent final-scope reviewer
- Refreshed: 2026-08-19
- RefreshedAt: 2026-08-19T06:07:04-04:00
- ReviewedPlanHash: sha256:20639c41d2069b2b77acbf3a4597d456ce3fa31797d2935245ff8dffd5eb3a46
- Findings:
  - F-001: The review found invalid HTML comments in generated YAML; rendering now uses YAML comments and all affected adapters were regenerated.
  - F-002: The review found two invalid colon-bearing canonical prompts and a non-semantic frontmatter parser; prompts are quoted and PyYAML-backed validation now rejects syntax and type errors.
  - F-003: Re-review found no remaining P0/P1 technical issues.
- Disposition:
  - Accept: F-001 -> harness renderer fix and all-metadata parsing test.
  - Accept: F-002 -> canonical metadata repairs and semantic catalog validation.
  - Accept: F-003 -> close technical review.

### Security/Privacy Review
- Reviewer: independent final-scope reviewer
- Refreshed: 2026-08-19
- RefreshedAt: 2026-08-19T06:07:04-04:00
- ReviewedPlanHash: sha256:20639c41d2069b2b77acbf3a4597d456ce3fa31797d2935245ff8dffd5eb3a46
- Findings:
  - F-001: Changes are local instructions, metadata, deterministic validation, tests, docs, and generated copies; no secrets, network effects, persistence, deployment, or expanded authority are introduced.
- Disposition:
  - Accept: F-001 -> no additional security/privacy mitigation required.

### Dynamic Specialist Review Roster
- Reviewer: planning/build orchestrator
- Refreshed: 2026-08-19
- RefreshedAt: 2026-08-19T06:07:04-04:00
- ReviewedPlanHash: sha256:20639c41d2069b2b77acbf3a4597d456ce3fa31797d2935245ff8dffd5eb3a46
- Findings:
  - F-001: Skill-procedure and catalog/harness review were triggered because behavior, routing metadata, generation, and identity validation changed.
  - F-002: Automation-runtime, database/migration, deployment, and external-integration reviews were not triggered because those surfaces are unchanged.
  - F-003: No specialist coverage remains missing or deferred.
- Triggered specialist reviews:
  - Review: skill procedure and catalog/harness integrity
    - Why triggered: The change introduces a decision procedure and strengthens adapter/catalog contracts.
    - Persona/sub-agent: independent final-scope reviewer
    - Required evidence hooks: G-Skill-Behavior, G-Catalog-Unit, G-Repo-Verify
    - Status: Complete
- Reviews considered but not triggered:
  - Review: automation runtime and deployment
    - Why not triggered: No runtime, dispatch, service, or deployment behavior changed.
- Disposition:
  - Accept: F-001 -> completed independent review and repairs.
  - Reject: F-002 -> broader specialist review would not cover an affected surface.
  - Accept: F-003 -> roster is complete.

### Human Readability Review
- Reviewer: build orchestrator
- Refreshed: 2026-08-19
- RefreshedAt: 2026-08-19T06:07:04-04:00
- ReviewedPlanHash: sha256:20639c41d2069b2b77acbf3a4597d456ce3fa31797d2935245ff8dffd5eb3a46
- Findings:
  - F-001: The plan separates discovery, formal planning, review, and build, and explains why one skill is added instead of a broader catalog.
  - Product/system clarity: Pass; the user-visible workflow and explicit invocation boundary are clear.
  - Technical narrative clarity: Pass; canonical-to-generated flow and validation changes are connected.
  - Execution-mechanics leakage: Proportionate to this repository-owned plan.
  - Strongest remaining ambiguity: None material.
- Pass/fail readability statement: Pass.
- Disposition:
  - Accept: F-001 -> close readability review.

## Execution Status
Phase: Integration
Status: complete

Workstreams:
- WS1: complete - materiality-driven skill, explicit invocation policy, and behavioral fixtures added.
- WS2: complete - catalog integrity, YAML semantics, docs, and generated-header cleanup integrated.

Delegation matrix:
- Task: grill-me skill design | Owner: WS1 | Files: `skills/grill-me/**` | Agent: generalPurpose | Status: complete
- Task: catalog/docs/test assessment | Owner: WS2 | Files: manifest, tests, README | Agent: generalPurpose | Status: complete
- Task: integrated scope review | Owner: integrator | Files: complete diff | Agent: generalPurpose | Status: complete - no remaining P0/P1 findings

Completed tasks:
- Added one explicit-only `grill-me` skill; no separate `grilling` abstraction.
- Added decision-ledger, materiality ranking, dependency ordering, scope deletion, evidence/prototype escalation, and re-ranking behavior.
- Added behavioral regression fixtures and generated Codex adapter files.
- Added catalog identity/frontmatter checks, including malformed YAML and non-string required-field cases.
- Fixed invalid generated YAML comment syntax and two pre-existing unquoted colon-bearing metadata prompts.
- Regenerated all affected Codex metadata and verified Codex, Gemini, and Claude generation.

Blocked:
- none

Build gates:
- G-Skill-Behavior - pass - quick validator and independent semantic review.
- G-Catalog-Unit - pass - 13 focused tests.
- G-Repo-Verify - pass - 107 repository tests, 55 plan-to-issues tests, 376 runtime tests, adapter verification, and diff checks.

Sub-agent usage:
- Agents launched: 3
- Parallel batches: 1
- Direct orchestrator edits: integration, repairs from review findings, generated-copy refresh, and plan closure.

Next actions:
- User review and optional commit/publish workflow.
