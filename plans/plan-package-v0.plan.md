# Feature: Plan Package v0

## Plan State
PlanFormatVersion: 2
PlanId: plan-package-v0
PlanGroup: planning-runtime
PlanKind: architecture
ParentPlan: none
DependsOnPlans: none
BlocksPlans: future-plan-package-default
AtomicScope: Add optional deep issue spec sidecars and package-mode review support without replacing single-plan authoring authority.
CampaignMetadataAuthority: descriptive-only; explicit @path authoring artifact selection wins
Status: Draft
StructuralStatus: StructurallyComplete
SubstanceStatus: SubstantivelyReviewed
ProjectionApproval: Blocked
DispatchApproval: Blocked
CurrentStage: Implementation
PlanTier: Full
AutomationTarget: manifest-only
DeliveryMode: DevOnly
ContextMode: RepoInferred
LastUpdated: 2026-06-17T12:00:00
PrimaryOwner: mat
BaseBranch: main
BaseCommit: c707cc86ec4aad3d79b0026e6e62819006bd26e4
TargetBranch: feat/plan-package-v0
Related: late-night design session pasted in chat 2026-06-17
NextRequiredUserAction: none; PPV0-LEAF-001 can begin when implementation starts
BlockingDecision: none
UnresolvedBlockers: 0
RubberStampSignals: 0
LastGateRun: 2026-06-17
ArtifactAuthorityMode: migration-bridge

## Gate Results
IntentModelComplete: Pass
ProblemDefinitionComplete: Pass
FeatureClarity: Pass
TechnicalClarity: Pass
HumanReadabilityReview: Pass
PlanReadiness: Pass
AutomationReadiness: Pass
PlanningReviewsComplete: Pass

## Decision Log
### DR-001: Implement sidecar issue specs before package directories become default
- Stage: Technical
- Date: 2026-06-17
- ScopeAffected: skills/plan, skills/automation-decomposition, skills/plan-to-issues, skills/local-plan-agent-runtime
- Decision: Start with optional deep issue spec sidecars referenced from Automation Issue Manifest leaves, then add package-directory review support after sidecar validation is stable.
- Options considered:
  - A) Sidecar-first migration bridge
  - B) Immediate directory-first replacement
  - C) Keep large single-file plans and only tune prompts
- Why chosen: A delivers issue-level depth, reviewability, and projection metadata without breaking the current single selected markdown authoring artifact rule.
- Consequences / follow-ups: Package directories remain an explicit mode until validators, projection, and local agent review understand cross-file packages.
- Status: Accepted
- Revisit trigger (if not Accepted): none

### DR-002: Keep `$plan` as the user-facing orchestrator and keep local-plan-agent-runtime as an internal review layer
- Stage: Technical
- Date: 2026-06-17
- ScopeAffected: skills/plan/SKILL.md, skills/local-plan-agent-runtime/SKILL.md, skills/local-plan-agent-runtime/scripts/snapshot_plan.py
- Decision: Consolidate the public workflow into `$plan`, but do not physically merge all runtime scripts and references into the plan skill in v0.
- Options considered:
  - A) `$plan` public surface with local-plan-agent-runtime as internal package-aware review machinery
  - B) Move every local runtime script and reference into skills/plan immediately
  - C) Leave `/local-plan-agent-runtime` as a separate user-facing workflow
- Why chosen: A preserves the clean user entrypoint while keeping specialized snapshot, proposal validation, and reconciliation logic isolated and testable.
- Consequences / follow-ups: Documentation should describe local-plan-agent-runtime as implementation detail of `$plan` agentic review mode.
- Status: Accepted
- Revisit trigger (if not Accepted): none

### DR-003: Package directory default timing
- Stage: Implementation
- Date: 2026-06-17
- ScopeAffected: plan selection semantics, package.yaml, index.md, compiled package registry
- Decision: Keep v0 sidecar-first and make package directories opt-in until sidecar validation, projection links, and package-mode snapshots have been proven on one real planning campaign.
- Options considered:
  - A) Keep v0 sidecar-first and make package directories opt-in only
  - B) Make new `/plan` artifacts package directories immediately
  - C) Never promote package directories; keep sidecars as the permanent shape
- Why chosen: A avoids a broad semantic break while preserving a direct path to the stronger package model.
- Consequences / follow-ups: This is still a real migration path, but the first shipped change adds the missing executable issue-spec layer before changing the default `/plan` artifact shape.
- Status: Accepted
- Revisit trigger (if not Accepted): After one sidecar-backed plan has been projected to issues and reviewed by package-mode agentic review.

### DR-004: Keep spec metadata in local execution records and issue bodies for v0
- Stage: Implementation
- Date: 2026-06-17
- ScopeAffected: skills/plan-package, skills/plan-to-issues, project-queue-audit, local work-item export, GitHub Project fields
- Decision: Emit `SpecPath`, `SpecHash`, `PackageId`, `PackageHash`, and `SourceId` in local package/work-item records first, and in GitHub issue bodies only when exporting to GitHub. Do not require new GitHub Project fields in v0.
- Options considered:
  - A) Local execution metadata first, optional GitHub issue body export
  - B) Add new GitHub Project fields immediately
  - C) Do not expose spec metadata in projected issues
- Why chosen: A keeps the fast path local and deterministic while still allowing GitHub issues to carry enough source metadata when work is exported.
- Consequences / follow-ups: Project fields may mirror these values in a later pass if they prove useful, but v0 must not depend on Project-only state or Project API round trips.
- Status: Accepted
- Revisit trigger (if not Accepted): After projected package issues exist and operators need sortable/filterable Project columns for spec freshness.

### DR-005: Require sidecars for ambiguity, not boilerplate
- Stage: Implementation
- Date: 2026-06-17
- ScopeAffected: skills/automation-decomposition, skills/issue-spec, skills/plan-to-issues
- Decision: Require sidecar specs for complex, high-ambiguity, data/testing/coverage, cross-module, runtime/projection, or multi-file leaves. Allow tiny one-point leaves to stay inline only when the manifest is self-contained and declares `Spec: inline`.
- Options considered:
  - A) Sidecar for every leaf issue
  - B) Sidecar only when ambiguity or depth requires it, with strict inline fallback
  - C) Sidecars always optional
- Why chosen: B prevents the failure mode that started this work without creating empty boilerplate files for trivial changes.
- Consequences / follow-ups: Validators must fail `Spec: inline` leaves unless file scope, dependencies, validation, acceptance criteria, dispatch mode, and one-PR contract are complete in the manifest.
- Status: Accepted
- Revisit trigger (if not Accepted): If teams repeatedly skip sidecars for work that later gets flattened or misimplemented.

### DR-006: Enforce campaign parent and child plan scope budgets
- Stage: Implementation
- Date: 2026-06-17
- ScopeAffected: skills/plan, skills/automation-decomposition, skills/plan/scripts/validate_plan.py, skills/plan-package
- Decision: Add explicit campaign hierarchy rules so a parent plan governs child plans instead of containing every one-point issue. A child plan should own one bounded outcome and normally contain 3-8 executable leaves; more than 12 executable leaves requires a split into child plans or a DR-backed waiver.
- Options considered:
  - A) Parent plan indexes child plans, child plans own bounded executable leaves, validator enforces leaf budgets
  - B) Let one package index contain unlimited one-point leaves
  - C) Avoid hierarchy rules and rely on author judgment
- Why chosen: A prevents the same context dilution problem from reappearing as a directory full of tiny issues.
- Consequences / follow-ups: Parent/campaign plans may carry tracking-only child-plan entries and dependency graph summaries, but they should not carry dozens of `agent-ready` leaves directly.
- Status: Accepted
- Revisit trigger (if not Accepted): If a real campaign cannot fit a bounded child plan into roughly 12 executable leaves without harming implementation clarity.

### DR-007: Make local package/work-item state the fast execution path
- Stage: Implementation
- Date: 2026-06-17
- ScopeAffected: skills/plan-package, templates/local-automation-runtime, scripts/runtime_control.py, skills/plan-to-issues
- Decision: Plan Package v0 should run from local package registry and local work-item records by default. GitHub issues, PRs, and Projects are export/sync surfaces, not required for planning validation, package review, local queueing, or agent dispatch simulation.
- Options considered:
  - A) Local package/work-item execution first, optional GitHub export/sync
  - B) GitHub issues and Projects remain required for all executable work
  - C) Remove GitHub integration entirely
- Why chosen: A preserves the current GitHub integration when it is useful, but removes GitHub Projects from the hot path that slows planning and local automation.
- Consequences / follow-ups: `plan-to-issues` becomes one projection target, not the only execution bridge. Package-to-local-work-items export must carry the same SourceId, spec hash, dependencies, write scope, validation, and dispatch metadata.
- Status: Accepted
- Revisit trigger (if not Accepted): If local work-item execution cannot provide enough durable state for review, retry, and audit without GitHub.

### DR-008: Accept planning review remediations for build readiness
- Stage: Reviews
- Date: 2026-06-17
- ScopeAffected: Technical Plan, Implementation Plan, Automation Issue Manifest, Planning Reviews
- Decision: Accept the review findings by making hash canonicalization, registry schema, snapshot CLI, and review evidence explicit before build dispatch.
- Options considered:
  - A) Patch the plan now and record resolved review dispositions
  - B) Defer schema/hash details to PPV0-LEAF-003 implementation
  - C) Proceed to build with review findings open
- Why chosen: A removes the remaining zero-context implementation ambiguity without changing the local-first or sidecar-first decisions.
- Consequences / follow-ups: Build agents must implement the v0 hash, registry, snapshot CLI, and review-gate contracts exactly as written unless a later `$plan` decision changes them.
- Status: Accepted
- Revisit trigger (if not Accepted): none

## Risks / Assumptions / Tests
- R1 (High): Sidecars become duplicated prose instead of executable depth.
  - Mitigation: Add validator rules that require source id, file scope, acceptance criteria, validation evidence, one-PR contract, and a quantitative depth contract for testing/data/coverage leaves.
  - Owner: plan-package-architect
  - Status: Mitigated
  - Trigger (if deferred): none
- R2 (High): Cross-file package mode weakens the current authoring authority contract.
  - Mitigation: v0 keeps the selected markdown plan as authoring authority and treats sidecar hashes as governed attachments; package directories are opt-in until the sidecar-backed workflow is proven.
  - Owner: plan-orchestrator
  - Status: Mitigated
  - Trigger (if deferred): none
- R3 (Medium): Projection writes stale spec links or hashes into GitHub issues.
  - Mitigation: `plan_to_issues.py` should fail apply mode when a referenced spec path is missing or the computed hash disagrees with the manifest hash.
  - Owner: projection-engineer
  - Status: Mitigated
  - Trigger (if deferred): none
- R4 (Medium): Package snapshots accidentally read uncontrolled files or follow unsafe paths.
  - Mitigation: package snapshot code must stay root-confined, reject symlink escapes, sort files deterministically, and include only package-declared files.
  - Owner: runtime-engineer
  - Status: Mitigated
  - Trigger (if deferred): none
- R5 (High): Sidecar-first migration creates 100 one-point issue files under one plan and recreates the original giant-plan problem.
  - Mitigation: Add parent/child plan scope budgets. Parent plans govern, child plans execute, and large leaf sets must be split into child plans or captured as depth-contract axes inside fewer issue specs.
  - Owner: plan-package-architect
  - Status: Mitigated
  - Trigger (if deferred): none
- R6 (High): The package model remains bottlenecked on GitHub Project APIs and loses the speed benefit of local planning.
  - Mitigation: Make local package registry and local work-item records the default execution substrate; GitHub issue/project sync is optional and outside the fast path.
  - Owner: runtime-engineer
  - Status: Mitigated
  - Trigger (if deferred): none
- A1: The current repo should not replace existing plan projection, queue, or Project audit behavior in the first pass.
  - Test: Existing `tests/test_plan_validator.py`, `tests/test_local_plan_snapshot.py`, and `skills/plan-to-issues/scripts/test_plan_to_issues.py` continue to pass after sidecar additions.
  - Pass/Fail criteria: All existing tests pass plus new sidecar/package tests.
  - Status: Accepted
- A2: Package registry output should be generated, not hand-authored.
  - Test: Compiler tests assert stable output ordering and hash mismatch failures.
  - Pass/Fail criteria: Running the compiler twice on the same package produces byte-identical JSON.
  - Status: Accepted

## Intent Model
<!-- owner: intent-reconciliation -->
Latent target:
- What the user appears to be trying to achieve: preserve rich intent and issue-level execution depth so future agents can execute large planning campaigns without flattening nuanced work into generic tasks.
- What the user is reacting against: one huge planning document that causes context dilution, review fatigue, and under-specified issue projection.
- Non-verbal / experiential target: future planning should feel navigable, inspectable, and durable at the same depth as the original thought process.
- Confidence: High

Anti-targets:
- Do not replace one giant plan with a directory full of duplicated mini-plans.
- Do not let GitHub issues become the full deep spec body.
- Do not make GitHub Projects required for planning, local review, queueing, or package validation.
- Do not make package directories the default until the current single-artifact workflow has a compatibility bridge.
- Do not allow agentic review workers to edit package files or flip planning gates directly.

Expression-state notes:
- User phrase: "move the whole planning runtime into the standard planning skill"
  - Interpreted meaning: make `$plan` the single public entrypoint for planning and agentic review, not necessarily collapse every specialized script into `skills/plan`.
  - Alternate plausible interpretations: physically move all local-plan-agent-runtime files under `skills/plan`; remove the standalone runtime skill entirely.
  - Confidence: Medium
  - Risk if wrong: implementation may over-consolidate and make runtime code harder to test or reuse.
- User phrase: "plan structure"
  - Interpreted meaning: define the future authoring model for index, shared context, deep issue specs, generated registry, and concise GitHub issue cards.
  - Alternate plausible interpretations: only update markdown templates without any script support.
  - Confidence: High
  - Risk if wrong: work may stop at documentation and fail to change the automation path.

Open Loop Ledger:
- OL-001:
  - Type: scope-gap
  - Source: user
  - Latent object: timing for making package directories the default authoring shape.
  - Why it matters: defaulting too early breaks current `/plan`, validator, projection, and local runtime assumptions.
  - Candidate interpretations:
    - A) Sidecar-first, package opt-in until proven
    - B) Directory-first immediately for new plans
    - C) Sidecars only, no package default
  - Status: Resolved
  - Resolution evidence: DR-003 selects sidecar-first package opt-in for v0.
  - Blocks: none

Intent checksum:
- Success means:
  - A plan leaf can point to a deep issue spec with local context, quantitative depth requirements, validation evidence, dependencies, and one-PR boundaries.
  - Local package/work-item records carry stable `SourceId`, `SpecPath`, `SpecHash`, execution-state fields, and runtime guardrails; GitHub issue projection remains optional and concise.
  - `$plan` remains the public orchestration surface, and local-plan-agent-runtime can review package members without becoming an independent authoring writer.
- Failure would look like:
  - Sidecars duplicate plan prose without adding enforceable execution detail.
  - Package mode bypasses `$plan` authority or lets workers mutate canonical intent.
  - GitHub Projects become required for normal planning or local execution.
  - GitHub issues contain full specs and drift from repo files.
- User confirmation needed:
  - none

## Problem Definition
Problem narrative:
Large efforts currently force too much execution detail into one long document. Future implementers can see the broad shape, but the dense leaf-level requirements that prevent underspecified work are easy to skim, compress, or lose.

The desired workflow gives each executable unit its own durable spec with measurable depth, local context, validation evidence, and stop rules. The global view stays small enough to browse while each leaf remains detailed enough for a zero-interaction implementer.

Current broken workflow:
- Large plans embed leaf work in a single `## Automation Issue Manifest`, so issue-level detail is hard to review as its own object.
- Local agentic review currently snapshots one markdown file and builds one section index, so it cannot hand one worker a bounded issue spec plus direct dependencies.
- GitHub projection already prefers leaf issues, but projected issue bodies do not yet link back to a deep spec path/hash.
- GitHub Projects are useful for external visibility, but making them part of the hot path slows local planning and automation.

Desired workflow:
- `$plan` remains the public planning command and the selected markdown plan remains the v0 authority surface.
- Automation manifest leaves may reference sidecar issue specs with stable path/hash metadata.
- Issue specs carry the executable depth contract: intent, anti-scope, file scope, dependencies, acceptance criteria, validation evidence, unresolved decisions, one-PR contract, and quantitative depth rules where relevant.
- Local agentic review can snapshot a package context and review a selected issue file without reading the entire campaign.
- Local package/work-item records become the default execution cards for fast local review and queueing.
- GitHub issues stay concise export cards when external tracking or PR workflow integration is needed.

Why this matters / why now:
- The newly added Intent Model preserves high-level latent intent, but large implementation campaigns still need a durable issue-level contract to prevent downstream flattening.
- The repo already has most of the machinery: planning skill, validators, manifest leaf projection, local work-item/runtime tools, Project audit, and agentic review snapshot scripts.
- Adding the bridge now is lower risk than waiting until another large plan hits the 50-issue / 6,000-line failure mode.

Current-state facts:
- Fact 1: `README.md` defines this repo as the canonical toolkit for planning, issue projection, GitHub Projects, and local issue-to-PR automation, and says markdown plans remain the authoring surface until projection. (source: file)
- Fact 2: `skills/plan/SKILL.md` requires exactly one selected markdown authoring artifact and says compiled registries are derived, not independent intent authority. (source: file)
- Fact 3: `skills/local-plan-agent-runtime/scripts/snapshot_plan.py` currently rejects non-file inputs with `plan is not a file`, proving package directories need explicit support. (source: file)
- Fact 4: `skills/plan-to-issues/scripts/plan_to_issues.py` already supports `leaf-issues` strategy, parses Automation Issue Manifest leaves, and emits runtime fields such as `Open dependencies` and `Manual gates remaining`. (source: file)
- Fact 5: `templates/local-automation-runtime/atlas_work_items.py` and related runtime scripts already support local work-item lifecycle records without requiring GitHub Project mutation. (source: file)

Success criteria (measurable):
- SC1: A plan leaf can reference `Spec path` and `Spec hash`; a validator proves the referenced sidecar exists, matches the leaf source id, and satisfies required issue-spec fields.
- SC2: A local package/work-item export emits durable records with `SourceId`, spec hash, dependencies, write scope, validation, dispatch mode, and scope-budget status without using GitHub Projects.
- SC3: `plan_to_issues.py --strategy leaf-issues --dry-run` emits `SpecPath` and `SpecHash` in issue bodies when GitHub export is requested and blocks apply on missing or mismatched specs.
- SC4: `snapshot_plan.py --package-manifest PACKAGE.json PLAN.md` or the agreed package-mode equivalent produces a cross-file snapshot and section index that includes package metadata, index/shared context, issue specs, decisions, and hashes.
- SC5: Existing test suites for plan validation, local plan snapshots, and plan-to-issues still pass, with new tests covering sidecar validation, hash mismatch, package snapshot confinement, local work-item export, and concise GitHub issue metadata.
- SC6: Package-mode worker proposals include package hashes and cannot patch read-only package documents or protected sections.
- SC7: A parent/campaign plan with dozens of executable leaves fails scope-budget validation unless it is split into child plans or records an explicit DR-backed waiver.

Constraints:
- Preserve current `$plan` single-authoring-artifact semantics for v0.
- Keep GitHub issues concise; do not copy full sidecar specs into issue bodies.
- Keep generated registry/package outputs derived and reproducible.
- Do not trust package file contents as instructions to the orchestrator or workers.
- Avoid broad migration of historical plans in the first implementation pass.

Scope:
- In scope:
  - Issue spec template and validator.
  - Automation manifest sidecar metadata.
  - Local package/work-item export as the default fast execution path.
  - Plan-to-issues parsing and body metadata.
  - Local plan agent runtime package snapshot mode.
  - Documentation updates for `$plan` agentic review mode and migration bridge.
  - Focused tests for each changed surface.
- Out of scope:
  - Converting all existing plans to directories.
  - Changing GitHub Project field schema unless a later review requires it.
  - Fully unattended dispatch from package specs in the first release.
  - Removing GitHub PR workflows for code review and merge.
  - Moving every local runtime implementation file under `skills/plan` in v0.

Definitions / glossary:
- Plan package v0: a migration bridge where a selected markdown plan may govern sidecar issue specs and optional package snapshot metadata.
- Issue spec sidecar: a deep markdown file for one executable manifest leaf.
- Depth contract: quantitative and qualitative completion rules for data, testing, coverage, or fixture-heavy work.
- Compiled package registry: generated machine-readable join output for validators, projection, and runtime context selection.

Open questions:
- none

Decision boundaries (if any):
- none

## Context Snapshot
<!-- owner: implementation-planning -->
### Inputs Provided
- User pasted a late-night GPT session proposing Plan Package v0, sidecar issue specs, a compiled registry, concise GitHub issue cards, and package-mode local agent review.
- User suggested using the new `$plan` skill and raised the question of whether the whole planning runtime should move into the standard planning skill.
- Repo inspection occurred on 2026-06-17 in `/home/mat/Desktop/AtlasMemory-Workspace/AtlasMemory-Tools`.

### System Understanding
- Summary: The repo has a mature single-plan workflow with separate scripts for validation, issue projection, local agentic review snapshots, and local issue-to-PR runtime. The missing layer is a first-class deep issue spec object between plan leaf and GitHub issue.
- Components:
  - `skills/plan/SKILL.md` and `skills/plan/reference.md`: public planning contract and template.
  - `skills/plan/scripts/validate_plan.py`: deterministic gate validator.
  - `skills/automation-decomposition/SKILL.md`: leaf issue decomposition contract.
  - `skills/plan-to-issues/scripts/plan_to_issues.py`: projection parser and GitHub issue body builder.
  - `skills/local-plan-agent-runtime/scripts/snapshot_plan.py`: local snapshot and section index generator.
  - `templates/local-automation-runtime/*`: runtime consumers of issue body execution-state fields and Project metadata.
- Data flow:
  - User intent enters `$plan`.
  - `$plan` writes one markdown plan artifact.
  - Automation manifest leaves feed `plan_to_issues.py`.
  - Project/issue audit and runtime queue consume issue body fields and Project mirrors.
  - Local agentic review snapshots the selected authoring artifact and validates worker proposals.
- Key abstractions:
  - Selected authoring artifact.
  - Automation Issue Manifest leaf.
  - Local package work-item record.
  - IssueDraft projection model.
  - Runtime execution-state fields.
  - Section index and proposal hashes.
  - Derived registry/package metadata.

### Known Unknowns (ranked)
1) Which concrete first campaign should be used to prove package-mode review and projection.
2) Whether package metadata should later be mirrored into GitHub Project fields for operator dashboards.
3) Whether repeated inline-spec misuse should force sidecars for every executable leaf in v1.

### Questions to Proceed (ranked)
1) none before implementation; revisit dashboard fields and package-directory defaults only after the first v0 campaign is proven.

### Dynamic Review Roster
<!-- owner: planning-reviews -->
- Refreshed: 2026-06-17
- Triggered specialist reviews:
  - Review: automation-runtime
    - Why triggered: The design changes how manifest leaves, projected issue bodies, and local runtime dispatch metadata relate.
    - Specialist/persona: automation-readiness-reviewer
    - Evidence hooks (named gates or source checks): G-CI-PlanPackage-Unit, G-CI-Projection-Sidecar, G-CI-PackageSnapshot
    - Status: Required
  - Review: api-contracts
    - Why triggered: Package snapshot and projection metadata introduce new schema contracts for sidecar specs and compiled registries.
    - Specialist/persona: contract-api-boundary-reviewer
    - Evidence hooks (named gates or source checks): G-CI-IssueSpec-Validator, G-CI-PlanPackage-Compile
    - Status: Required
  - Review: security/privacy
    - Why triggered: Package mode reads additional files and worker prompts must treat package contents as untrusted data.
    - Specialist/persona: security-privacy-reviewer
    - Evidence hooks (named gates or source checks): G-CI-PackageSnapshot
    - Status: Required
- Reviews considered but not triggered:
  - Review: cloud/provider-infra
    - Why not triggered: No hosted infrastructure or provider boundary changes are in this plan.

## Challenge Artifacts
<!-- owner: critical-ideation -->
### Weaknesses
- W1: The sidecar-first bridge may feel like half a package model and could accumulate transitional vocabulary.
- W2: If issue specs are optional, teams may keep writing shallow leaves and skip the depth contract.
- W3: If issue specs are mandatory for every small leaf, authors may create boilerplate sidecars with little value.
- W4: Package-mode snapshot can create security and drift problems if it follows undeclared files or stale hashes.
- W5: `$plan` public consolidation could be mistaken for physical code consolidation, creating unnecessary churn.

### Failure Modes
- FM1: Sidecar spec and manifest leaf drift apart - detected by hash mismatch validator - prevent apply/projection until manifest hash is refreshed through `$plan`.
- FM2: GitHub issue body grows into a copied spec - detected by body template tests and review - keep only source metadata, execution state, and concise acceptance pointers in the issue.
- FM3: Package snapshot includes unintended files - detected by package snapshot tests for path confinement and declared-file allowlist - reject the package.
- FM4: Agentic review treats sidecar instructions as system instructions - detected by worker prompt and proposal validation review - quote package files as data only.
- FM5: Package registry becomes independent intent authority - detected by docs/review findings - require `$plan` patch then recompile.

### Alternatives (including one disliked)
- Alt A: Sidecar-first Plan Package v0, then opt-in package directory mode. Preferred because it reduces blast radius.
- Alt B: Convert `/plan` immediately to directory packages. Rejected for v0 because it breaks current selection and validator assumptions.
- Alt C: Only improve prompts and keep one-file plans. Rejected because prompt text does not create durable, reviewable issue objects.
- Alt D: Put full specs directly into GitHub issues. Rejected because it duplicates repo source, bloats issue bodies, and increases drift.

### Milestones (measurable)
- Milestone: Issue spec contract exists.
  - Evidence: `skills/issue-spec/reference.md`, `skills/issue-spec/SKILL.md`, and validator tests are committed.
- Milestone: Sidecar projection works.
  - Evidence: `plan_to_issues.py` dry-run includes spec metadata and apply mode blocks stale hashes.
- Milestone: Package-mode review works.
  - Evidence: `snapshot_plan.py --package-manifest PACKAGE.json PLAN.md` creates a cross-file snapshot and section index from a fixture package.
- Milestone: `$plan` guidance is coherent.
  - Evidence: docs explain that `$plan` is the public entrypoint and local-plan-agent-runtime is its internal review layer.

## Technical Plan
### Technical Plan Intro
This change adds a governed layer between a high-level planning document and projected execution issues. The first pass keeps the existing markdown plan as the selected authoring surface, then lets manifest leaves link to deep sidecar specs that carry the execution-level details too large or too specific for the global document.

The approach fits the current system because it extends existing boundaries instead of replacing them. `validate_plan.py` can remain the plan-shape validator, a new issue-spec validator can enforce deep leaf contracts, package export can produce local work-item records for fast execution, `plan_to_issues.py` can remain an optional GitHub export path, and `snapshot_plan.py` can gain an explicit package mode for agentic review.

The implementation touches the planning skill/template, automation decomposition guidance, plan-to-issues parser/body generation, local plan agent snapshot runtime, tests, and README-style workflow docs. It does not alter GitHub issue/PR execution truth or Project v2 authority.

### Integration Points
- `$plan` authoring contract:
  - Add vocabulary for sidecar issue specs and package-mode agentic review while retaining the v0 selected markdown authoring artifact rule.
- Automation Issue Manifest:
  - Add optional leaf fields for `Spec path`, `Spec hash`, `Spec status`, and `Depth contract`.
- Issue spec validator:
  - Validate sidecar markdown structure, source id alignment, parent plan id, manifest leaf id, dispatch metadata, and depth contract.
  - Required v0 fields: `SpecId`, `SourceId`, `ParentPlanId`, `ManifestLeafId`, `Intent`, `Anti-scope`, `Files in scope`, `Files out of scope`, `Dependencies`, `Required gates`, `Validation`, `Acceptance criteria`, `Dispatch mode`, `One PR contract`, and `Open decisions`.
  - Conditional fields: `Depth contract` is required for testing, data, coverage, fixture-heavy, runtime/projection, cross-module, or multi-file leaves; `Spec: inline` is allowed only when the manifest itself contains the complete file scope, dependencies, validation, acceptance criteria, dispatch mode, and one-PR contract.
  - Sidecars may refine execution detail, but may not introduce or override leaves, files, gates, dependencies, dispatch readiness, approval state, or authority semantics that are absent from the markdown manifest.
  - Hash canonicalization: all v0 `SpecHash`, `PackageHash`, and source hashes use the `sha256:` prefix followed by a 64-character lowercase hexadecimal digest over UTF-8 bytes after normalizing line endings to `\n` and trimming only trailing whitespace at end of file. Hashes do not normalize markdown heading text, table spacing, frontmatter, or field ordering unless the input is generated JSON.
  - Generated JSON hash canonicalization: compiled registry/package JSON is serialized with sorted object keys, two-space indentation, `\n` line endings, and a trailing newline before hashing.
- Plan-to-issues projection:
  - Parse sidecar fields, verify hashes, include concise issue metadata, and fail apply mode when referenced specs are invalid when GitHub export is requested.
- Local work-item export:
  - Convert compiled package leaves into local work-item records with source id, spec hash, dependencies, write scope, validation, dispatch mode, and audit status.
  - Avoid GitHub Project API calls in the normal package validation, review, and local queueing path.
- Campaign scope enforcement:
  - Parent plans index child plans and dependency summaries; child plans own executable leaves and sidecar specs.
  - `$plan` and automation decomposition should warn at more than 8 executable leaves and fail above 12 executable leaves unless a DR-backed waiver explains why the plan cannot be split.
  - Executable leaf means any non-`tracking-only` manifest leaf intended to become work, including `manual-review`, `agent-ready`, and `blocked` leaves once their blockers are cleared.
  - Scope-budget waivers must cite a DR id, exact executable-leaf count, rationale for not splitting, validation risk, and revisit trigger.
- Local plan agent runtime:
  - Add package-aware snapshot mode with cross-file section index and root-confined file selection.
  - The v0 CLI contract is `python3 skills/local-plan-agent-runtime/scripts/snapshot_plan.py PLAN.md --package-manifest PACKAGE.json --out DIR`; package mode must reject a manifest that points outside the repo root or changes the selected `PLAN.md`.
- Compiled package registry:
  - Generate deterministic join metadata for package members, issue specs, dependencies, source hashes, projection hints, and local-export metadata.
  - Required registry fields: `schema_version`, `package_id`, `package_hash`, `source_plan.path`, `source_plan.hash`, `members[]` with `path`, `kind`, `hash`, and `patchable`, `leaves[]` with `source_id`, `manifest_leaf_id`, `spec_path`, `spec_hash`, `dependencies`, `required_gates`, `files_in_scope`, `files_out_of_scope`, `dispatch_mode`, `validation`, `acceptance_criteria`, `projection_hints`, and `local_export`.

### Proposed Architecture Changes
- Add `skills/issue-spec/`:
  - `SKILL.md`: authoring/review contract for deep executable issue specs.
  - `reference.md`: canonical issue spec template.
  - `scripts/validate_issue_spec.py`: deterministic sidecar validator.
- Add `skills/plan-package/`:
  - `reference.md`: package layout and authority model.
  - `scripts/compile_plan_package.py`: deterministic JSON compiler for package metadata.
  - `scripts/validate_plan_package.py`: package-level path, hash, dependency, and registry checks.
- Update `skills/plan/reference.md` and `skills/automation-decomposition/SKILL.md`:
  - Manifest leaves may include sidecar metadata.
  - Complex data/testing/coverage leaves should include a depth contract.
  - Parent/campaign plans should use tracking-only child-plan entries instead of enumerating large leaf sets.
- Update `skills/plan-to-issues/scripts/plan_to_issues.py`:
  - Extend `IssueDraft` with `spec_path`, `spec_hash`, `spec_status`, and possibly `depth_contract_required`.
  - Parse manifest fields from leaf blocks.
  - Compute spec hash from the referenced sidecar file using the v0 hash canonicalization rules and verify it when fields are present.
  - Emit body metadata under `## Source Plan` or `## Automation Manifest Metadata` only for GitHub export.
- Add local package work-item export:
  - `skills/plan-package/scripts/export_work_items.py` writes local JSON work-item records from compiled package metadata.
  - The local export format mirrors the runtime fields currently carried in GitHub issue bodies, but does not require issue creation or Project sync.
- Update `skills/local-plan-agent-runtime/scripts/snapshot_plan.py`:
  - Add explicit package input: `python3 skills/local-plan-agent-runtime/scripts/snapshot_plan.py PLAN.md --package-manifest PACKAGE.json --out DIR`.
  - Reject package manifests that point outside the repo root or silently change the selected positional `PLAN.md`.
  - Produce `package.snapshot/` and a `section-index.json` with file-level and section-level ids.
  - Preserve old file-mode behavior and tests.
- Update `skills/local-plan-agent-runtime/scripts/validate_proposal.py`:
  - Require `source_package_sha256` in package mode.
  - Reject drift in any canonical package document recorded in the snapshot.
  - Reject non-`no-patch` patches against read-only package documents.
- Update `skills/local-plan-agent-runtime/scripts/summarize_run.py` only if conflict grouping needs file-qualified package section ids.
- Add optional `PlanPackageConsistency` validation:
  - Trigger only when package metadata or a package manifest is present.
  - Preserve `AutomationReadiness` as markdown-authoritative; sidecars may fail package consistency but must not make the manifest pass.
  - Consider `ReviewedPackageHash` freshness once reviews are expected to cover sidecar/package files.
  - Validate every declared hash with the v0 canonicalization rules and fail on missing, malformed, mismatched, or duplicate source ids.
- Add `PlanScopeBudget` validation:
  - Trigger for `PlanTier: Full` plans with `AutomationTarget` set to `manifest-only`, `issue-projection`, or `unattended-prs`.
  - Count executable leaves as all non-`tracking-only` manifest leaves intended to become work, including `manual-review`, `agent-ready`, and blocked work once the blocker is cleared.
  - Warn when executable leaves exceed 8.
  - Fail when executable leaves exceed 12 unless the plan is an explicitly tracking-only parent or cites an accepted DR waiver with leaf count, rationale, validation risk, and revisit trigger.
  - Fail parent/campaign plans that directly carry large executable leaf sets in any dispatch mode instead of child-plan tracking entries.

### Failure Modes (per integration point)
- `$plan` contract:
  - Failure: package files are treated as independent authoring authority.
  - Detection: planning reviews and docs tests identify language that bypasses selected authoring artifact.
  - Mitigation: v0 says sidecars are governed attachments and package directories remain opt-in.
- Issue spec validator:
  - Failure: validator accepts generic prose without executable criteria.
  - Detection: tests with missing files, missing acceptance criteria, missing validation, and missing depth contract fail.
  - Mitigation: required fields and domain-triggered depth contract.
- Plan-to-issues:
  - Failure: stale spec hash is projected to GitHub.
  - Detection: apply-mode preflight error.
  - Mitigation: dry-run warnings, apply hard failure.
- Local work-item export:
  - Failure: local work-item records diverge from package specs or omit dependency/write-scope metadata.
  - Detection: package work-item export tests compare exported records against compiled package source hashes and required runtime fields.
  - Mitigation: fail export until package validation passes.
- Package snapshot:
  - Failure: snapshot follows symlink outside package root.
  - Detection: path confinement test.
  - Mitigation: resolve paths, reject symlink escapes and undeclared package members.
- Proposal validation:
  - Failure: worker proposes patches against registry or sidecar files that `$plan` cannot authoritatively accept in v0.
  - Detection: package-mode proposal validator rejects patches to `patchable: false` documents and protected sections.
  - Mitigation: route all accepted intent changes through the selected markdown plan, then regenerate sidecars/registry.
- Compiled registry:
  - Failure: generated registry drifts from markdown/spec sources.
  - Detection: compiler hash mismatch and deterministic output tests.
  - Mitigation: registry is regenerated, not hand-edited.

### Invariants / Non-Changes
- `$plan` remains the public planning workflow.
- The selected markdown plan remains v0 authoring authority.
- Local package/work-item records are the fast execution truth before external export.
- GitHub issues and PRs remain optional external execution/review surfaces when a repo workflow needs them.
- GitHub Projects remain optional portfolio UI/signal only and are never required for local package validation or queueing.
- Worker agents propose findings/patches and do not write canonical plan/package files.
- Full issue specs stay in repo files, not GitHub issue bodies.
- Sidecars cannot introduce leaves, files, gates, dependencies, or dispatch readiness that are absent from the markdown manifest in v0.
- JSON is the v0 package metadata format to avoid adding a YAML dependency to plan/package validators.
- Parent plans govern and child plans execute. A plan package should improve focus, not hide an unbounded issue list across many files.

### NFRs alignment
- Determinism: package registry and hash validation must be stable across runs.
- Backward compatibility: existing single-file plans, validators, local work-item flows, and plan-to-issues dry-runs must continue to work.
- Reviewability: package-mode snapshots must let reviewers focus on one issue spec plus relevant shared context.
- Security: package reads must be root-confined and treated as untrusted content.
- Maintainability: script additions should be small, test-backed, and not collapse specialized runtime code into one monolithic skill.

## Implementation Plan
### Agent roster (required for PlanTier: Full)
- plan-package-architect: owns schema, authority wording, and migration boundaries.
- issue-spec-engineer: owns issue spec template and validator.
- projection-engineer: owns plan-to-issues parsing, issue body metadata, and preflight behavior.
- runtime-engineer: owns package-mode snapshot, section index, and local agent runtime docs.
- test-engineer: owns focused unit tests and regression coverage.
- planning-doc-reviewer: owns human readability and workflow documentation review.

### File Deltas (exhaustive) + rationale
- skills/issue-spec/SKILL.md - create - issue-spec-engineer - define how deep issue specs are authored and reviewed.
- skills/issue-spec/reference.md - create - issue-spec-engineer - provide the sidecar issue spec template.
- skills/issue-spec/scripts/validate_issue_spec.py - create - issue-spec-engineer - enforce required issue-spec fields and depth contracts.
- skills/plan-package/reference.md - create - plan-package-architect - document package layout, authority, and migration model.
- skills/plan-package/scripts/compile_plan_package.py - create - plan-package-architect - generate deterministic package registry metadata.
- skills/plan-package/scripts/validate_plan_package.py - create - plan-package-architect - validate package member paths, hashes, and dependency graph.
- skills/plan-package/scripts/export_work_items.py - create - runtime-engineer - emit local work-item records from the compiled package without GitHub Project calls.
- skills/plan/SKILL.md - modify - plan-package-architect - describe sidecar-governed v0 and package-mode agentic review without changing authoring selection rules.
- skills/plan/reference.md - modify - plan-package-architect - add optional sidecar metadata fields to Automation Issue Manifest leaves.
- skills/plan/scripts/validate_plan.py - modify - plan-package-architect - add optional package consistency checks and scope-budget checks when package metadata or large manifests are present.
- skills/plan/README.md - modify - planning-doc-reviewer - explain sidecar-first migration and `$plan` public entrypoint.
- skills/automation-decomposition/SKILL.md - modify - plan-package-architect - require sidecar specs for complex/data/testing leaves or explicit not-required rationale.
- skills/local-plan-agent-runtime/SKILL.md - modify - runtime-engineer - document package-aware review mode and package member authority constraints.
- skills/local-plan-agent-runtime/references/run-protocol.md - modify - runtime-engineer - add package snapshot layout and worker context rules.
- skills/local-plan-agent-runtime/references/proposal-schema.md - modify - runtime-engineer - allow file-qualified section ids while preserving old schema fields.
- skills/local-plan-agent-runtime/scripts/snapshot_plan.py - modify - runtime-engineer - add package-mode snapshot and cross-file section index.
- skills/local-plan-agent-runtime/scripts/validate_proposal.py - modify - runtime-engineer - add package hash, document drift, and patchability checks.
- skills/local-plan-agent-runtime/scripts/summarize_run.py - modify - runtime-engineer - preserve conflict grouping with file-qualified section ids if needed.
- skills/plan-to-issues/SKILL.md - modify - projection-engineer - document spec metadata in projected issue bodies.
- skills/plan-to-issues/reference.md - modify - projection-engineer - add example leaf sidecar fields and issue body output.
- skills/plan-to-issues/scripts/plan_to_issues.py - modify - projection-engineer - parse, validate, and emit spec metadata.
- tests/test_plan_validator.py - modify - test-engineer - add manifest sidecar metadata acceptance/regression tests if `validate_plan.py` gets lightweight checks.
- tests/test_local_plan_snapshot.py - modify - test-engineer - add package-mode snapshot fixture tests.
- skills/plan-to-issues/scripts/test_plan_to_issues.py - modify - test-engineer - add sidecar projection and stale hash tests.
- tests/test_issue_spec_validator.py - create - test-engineer - cover sidecar validator success/failure cases.
- tests/test_plan_package.py - create - test-engineer - cover package compile/validate behavior.
- tests/test_plan_package_work_items.py - create - test-engineer - cover package-to-local-work-items export and dependency metadata.
- tests/test_local_plan_agent_runtime.py - modify - test-engineer - cover package-mode proposal validation and read-only document patch rejection.
- README.md - modify - planning-doc-reviewer - update top-level workflow and source-of-truth description for sidecar/package mode.
- manifests/atlas-tools.v1.json - modify - plan-package-architect - register new skills/scripts after implementation and generation workflow.

### Workstreams + merge points
- WS1: Issue spec sidecar contract
  - Owner: issue-spec-engineer
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: authors can create one deep executable spec per manifest leaf with deterministic validation.
  - Tracking: none
  - Depends on: none
  - Review gates (named):
    - G-CI-IssueSpec-Validator
  - Owns files:
    - skills/issue-spec/SKILL.md
    - skills/issue-spec/reference.md
    - skills/issue-spec/scripts/validate_issue_spec.py
    - tests/test_issue_spec_validator.py
  - Merge point / integration step: MP1-sidecar-contract
- WS2: `$plan` and automation manifest integration
  - Owner: plan-package-architect
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: planning docs and manifest templates understand sidecar metadata and package v0 authority.
  - Tracking: none
  - Depends on: WS1
  - Review gates (named):
    - G-CI-Plan-Validator
    - G-DOCS-PlanPackage-Clarity
  - Owns files:
    - skills/plan/SKILL.md
    - skills/plan/reference.md
    - skills/plan/scripts/validate_plan.py
    - skills/plan/README.md
    - skills/automation-decomposition/SKILL.md
    - README.md
    - manifests/atlas-tools.v1.json
  - Merge point / integration step: MP2-plan-contract
- WS3: Compiled package registry
  - Owner: plan-package-architect
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: package metadata can be generated deterministically for joins, validation, local work-item export, and future projection.
  - Tracking: none
  - Depends on: WS1, WS2
  - Review gates (named):
    - G-CI-PlanPackage-Compile
  - Owns files:
    - skills/plan-package/reference.md
    - skills/plan-package/scripts/compile_plan_package.py
    - skills/plan-package/scripts/validate_plan_package.py
    - tests/test_plan_package.py
  - Merge point / integration step: MP3-package-registry
- WS4: Local package work-item export
  - Owner: runtime-engineer
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: compiled package leaves can become local work-item records without GitHub issue or Project mutation.
  - Tracking: none
  - Depends on: WS3
  - Review gates (named):
    - G-CI-LocalWorkItemExport
  - Owns files:
    - skills/plan-package/scripts/export_work_items.py
    - tests/test_plan_package_work_items.py
    - docs/automation-runtime-operational-layer.md
  - Merge point / integration step: MP4-local-work-items
- WS5: Optional plan-to-issues sidecar projection
  - Owner: projection-engineer
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: when GitHub export is requested, projected GitHub issues carry concise spec path/hash metadata and fail stale sidecars before apply.
  - Tracking: none
  - Depends on: WS1, WS3
  - Review gates (named):
    - G-CI-Projection-Sidecar
  - Owns files:
    - skills/plan-to-issues/SKILL.md
    - skills/plan-to-issues/reference.md
    - skills/plan-to-issues/scripts/plan_to_issues.py
    - skills/plan-to-issues/scripts/test_plan_to_issues.py
  - Merge point / integration step: MP5-github-export
- WS6: Package-mode local agent review
  - Owner: runtime-engineer
  - Agent type: generalPurpose
  - Delegate: required
  - Intended behavior change: agentic review can snapshot package context, target one issue spec without reading a giant plan, and reject unsafe package-mode proposals.
  - Tracking: none
  - Depends on: WS3
  - Review gates (named):
    - G-CI-PackageSnapshot
  - Owns files:
    - skills/local-plan-agent-runtime/SKILL.md
    - skills/local-plan-agent-runtime/references/run-protocol.md
    - skills/local-plan-agent-runtime/references/proposal-schema.md
    - skills/local-plan-agent-runtime/scripts/snapshot_plan.py
    - skills/local-plan-agent-runtime/scripts/validate_proposal.py
    - skills/local-plan-agent-runtime/scripts/summarize_run.py
    - tests/test_local_plan_snapshot.py
    - tests/test_local_plan_agent_runtime.py
  - Merge point / integration step: MP6-runtime-package
- WS7: Integration review and release gate
  - Owner: test-engineer
  - Agent type: code-reviewer
  - Delegate: required
  - Intended behavior change: verify backward compatibility and package v0 workflow coherence.
  - Tracking: none
  - Depends on: WS2, WS3, WS4, WS5, WS6
  - Review gates (named):
    - G-CI-Repo-Verify
    - G-Review-AgenticPackage
  - Owns files:
    - tests/test_plan_validator.py
    - plans/plan-package-v0.plan.md
  - Merge point / integration step: MP7-release-review

### Delegation Quality Gate (required for PlanTier: Full)
- DQ-1 Workstream delegation metadata complete: Pass
  - Rule: Every workstream has `Owner`, `Agent type`, and `Delegate`.
- DQ-2 File ownership conflict-free before merge points: Pass
  - Rule: No file is owned by more than one active workstream before an explicit merge point.
- DQ-3 Delegation coverage: Pass
  - Rule: All non-trivial workstreams are marked `Delegate: required`.
- DQ-4 Validation delegation path present: Pass
  - Rule: Test/review gates identify delegated execution path through test-engineer, projection-engineer, or runtime-engineer.
- Notes / waivers (must cite DR-xxx):
  - none

### Phases + tasks + exit criteria
#### Phase 1: Sidecar Contract
- Owner(s): issue-spec-engineer
- Depends on: none
- Tracking: none
- Tasks (by owner):
  - Owner: issue-spec-engineer
    - [ ] Create issue-spec skill and reference template.
    - [ ] Implement sidecar validator with required field checks.
    - [ ] Add depth contract trigger for testing/data/coverage leaves.
- Exit criteria (evidence): `python3 -m unittest tests.test_issue_spec_validator` passes and fixtures cover missing depth contract, bad source id, missing validation, and valid minimal spec.
- Gates (named):
  - G-CI-IssueSpec-Validator

#### Phase 2: Planning Contract Bridge
- Owner(s): plan-package-architect, planning-doc-reviewer
- Depends on: Phase 1
- Tracking: none
- Tasks (by owner):
  - Owner: plan-package-architect
    - [ ] Update `$plan` and automation decomposition guidance for sidecar metadata.
    - [ ] Add Plan Package v0 reference language and package authority constraints.
    - [ ] Add campaign parent/child plan budget guidance and validator checks.
  - Owner: planning-doc-reviewer
    - [ ] Update README and human workflow docs.
- Exit criteria (evidence): `python3 -m unittest tests.test_plan_validator` passes and docs describe sidecar-first v0 plus parent/child plan budgets without contradicting selected authoring artifact rules.
- Gates (named):
  - G-CI-Plan-Validator
  - G-DOCS-PlanPackage-Clarity

#### Phase 3: Package Registry
- Owner(s): plan-package-architect, runtime-engineer
- Depends on: Phase 1, Phase 2
- Tracking: none
- Tasks (by owner):
  - Owner: plan-package-architect
    - [ ] Implement deterministic package compiler and validator.
    - [ ] Emit issue specs, dependencies, source hashes, projection hints, and local-export metadata.
    - [ ] Serialize registry JSON with sorted keys, two-space indentation, `\n` line endings, and trailing newline before hashing.
- Exit criteria (evidence): `python3 -m unittest tests.test_plan_package` passes, compiler output is deterministic, and fixtures prove hash mismatch, duplicate source id, path escape, missing required registry field, and downstream local-export metadata failures.
- Gates (named):
  - G-CI-PlanPackage-Compile

#### Phase 4: Local Work-Item Export
- Owner(s): runtime-engineer
- Depends on: Phase 3
- Tracking: none
- Tasks (by owner):
  - Owner: runtime-engineer
    - [ ] Implement package-to-local-work-items export from compiled package metadata.
    - [ ] Preserve SourceId, spec hash, dependencies, write scope, validation, dispatch mode, and scope-budget status.
    - [ ] Document that GitHub Projects are optional mirrors, not required for local package execution.
- Exit criteria (evidence): `python3 -m unittest tests.test_plan_package_work_items` passes and exported records require no GitHub Project calls.
- Gates (named):
  - G-CI-LocalWorkItemExport

#### Phase 5: Optional GitHub Export
- Owner(s): projection-engineer
- Depends on: Phase 1, Phase 3
- Tracking: none
- Tasks (by owner):
  - Owner: projection-engineer
    - [ ] Extend manifest leaf parsing for `Spec path`, `Spec hash`, and `Depth contract`.
    - [ ] Emit concise GitHub issue body metadata including `Source kind`, `SourceId`, `Package id`, `Package hash`, `Spec id`, `Spec path`, `Spec hash`, and `Projection schema`.
    - [ ] Fail apply mode on missing spec or hash mismatch.
- Exit criteria (evidence): `python3 skills/plan-to-issues/scripts/test_plan_to_issues.py` or equivalent pytest target passes with new sidecar tests.
- Gates (named):
  - G-CI-Projection-Sidecar

#### Phase 6: Package Snapshot Mode
- Owner(s): runtime-engineer
- Depends on: Phase 3
- Tracking: none
- Tasks (by owner):
  - Owner: runtime-engineer
    - [ ] Add explicit package-mode CLI: `python3 skills/local-plan-agent-runtime/scripts/snapshot_plan.py PLAN.md --package-manifest PACKAGE.json --out DIR`.
    - [ ] Generate file-qualified section ids and package manifest metadata.
    - [ ] Extend proposal validation for `source_package_sha256`, package document drift, and read-only document patch rejection.
    - [ ] Add path confinement and symlink escape tests.
- Exit criteria (evidence): `python3 -m unittest tests.test_local_plan_snapshot` passes with both old single-file mode and package-mode fixtures, including rejection when the package manifest points outside the repo root or changes the selected positional `PLAN.md`.
- Gates (named):
  - G-CI-PackageSnapshot

#### Phase 7: Integration Review
- Owner(s): test-engineer, planning-doc-reviewer
- Depends on: Phase 2, Phase 3, Phase 4, Phase 5, Phase 6
- Tracking: none
- Tasks (by owner):
  - Owner: test-engineer
    - [ ] Run targeted test suites and repo verification.
    - [ ] Run one local work-item export from a fixture package using sidecar specs.
    - [ ] Run one optional GitHub dry-run projection from the same fixture package.
  - Owner: planning-doc-reviewer
    - [ ] Perform human readability and implementer readiness reviews.
- Exit criteria (evidence): Targeted tests pass, `python3 scripts/verify_repo.py` passes or failures are documented, and planning reviews are refreshed.
- Gates (named):
  - G-CI-Repo-Verify
  - G-Review-AgenticPackage

### Review gates (named + definitions)
- G-CI-IssueSpec-Validator:
  - Where it runs: Local
  - Entry point / command: python3 -m unittest tests.test_issue_spec_validator
  - Green means: sidecar validator accepts valid specs and rejects missing required fields, bad hashes, and missing depth contracts.
- G-CI-Plan-Validator:
  - Where it runs: Local
  - Entry point / command: python3 -m unittest tests.test_plan_validator
  - Green means: existing plan validator behavior remains compatible with sidecar metadata and large executable leaf sets fail without child-plan split or DR waiver.
- G-DOCS-PlanPackage-Clarity:
  - Where it runs: Local
  - Entry point / command: human review of README.md, skills/plan/README.md, and skills/plan-package/reference.md
  - Green means: a new engineer can explain sidecar-first v0 and why package directories are opt-in.
- G-CI-LocalWorkItemExport:
  - Where it runs: Local
  - Entry point / command: python3 -m unittest tests.test_plan_package_work_items
  - Green means: compiled package leaves export to local work-item records with source ids, spec hashes, dependencies, write scope, validation, dispatch mode, and no GitHub Project dependency.
- G-CI-Projection-Sidecar:
  - Where it runs: Local
  - Entry point / command: python3 skills/plan-to-issues/scripts/test_plan_to_issues.py
  - Green means: optional GitHub dry-run emits spec metadata and apply preflight rejects missing or stale spec hashes.
- G-CI-PackageSnapshot:
  - Where it runs: Local
  - Entry point / command: python3 -m unittest tests.test_local_plan_snapshot tests.test_local_plan_agent_runtime
  - Green means: single-file snapshots still work, package snapshots are root-confined with file-qualified section ids, and package-mode proposals cannot patch read-only documents.
- G-CI-PlanPackage-Compile:
  - Where it runs: Local
  - Entry point / command: python3 -m unittest tests.test_plan_package
  - Green means: package compiler output is deterministic and validator rejects mismatched paths, hashes, or dependencies.
- G-CI-Repo-Verify:
  - Where it runs: Local
  - Entry point / command: python3 scripts/verify_repo.py
  - Green means: repository release/copy gates pass after changes.
- G-Review-AgenticPackage:
  - Where it runs: Local
  - Entry point / command: Use `$plan` with agentic review mode against this plan after implementation.
  - Green means: review findings are dispositioned and no human-agency items remain unresolved.

### Merge points -> required gates
- MP1-sidecar-contract:
  - Blocks on:
    - G-CI-IssueSpec-Validator
- MP2-plan-contract:
  - Blocks on:
    - G-CI-Plan-Validator
    - G-DOCS-PlanPackage-Clarity
- MP3-package-registry:
  - Blocks on:
    - G-CI-PlanPackage-Compile
- MP4-local-work-items:
  - Blocks on:
    - G-CI-LocalWorkItemExport
- MP5-github-export:
  - Blocks on:
    - G-CI-Projection-Sidecar
- MP6-runtime-package:
  - Blocks on:
    - G-CI-PackageSnapshot
- MP7-release-review:
  - Blocks on:
    - G-CI-LocalWorkItemExport
    - G-CI-Repo-Verify
    - G-Review-AgenticPackage

### Test Matrix
- Issue spec validator - shallow or vague sidecars - unit tests - where it runs: Local
- Issue spec depth contract - testing/data/coverage leaves without quantitative completion rules - unit tests - where it runs: Local
- Plan validator compatibility - existing plans fail after optional metadata is added - unit tests - where it runs: Local
- Parent/child plan scope budget - one parent plan contains dozens of executable leaves - unit tests - where it runs: Local
- Local work-item export - package records require GitHub Project calls or omit runtime metadata - unit tests - where it runs: Local
- Optional plan-to-issues sidecar projection - stale/missing spec links reach GitHub apply - unit tests and dry-run preflight - where it runs: Local
- Package snapshot confinement - undeclared files or symlink escapes included in worker context - unit tests - where it runs: Local
- Package proposal validation - read-only package docs patched or stale package hash accepted - unit tests - where it runs: Local
- Package compiler determinism - generated registry drift - unit tests - where it runs: Local
- Repo release integrity - generated harness or manifest drift - verify script - where it runs: Local

### Test plan (CI vs deployed)
- CI:
  - python3 -m unittest tests.test_issue_spec_validator
  - python3 -m unittest tests.test_plan_validator
  - python3 -m unittest tests.test_local_plan_snapshot
  - python3 -m unittest tests.test_local_plan_agent_runtime
  - python3 -m unittest tests.test_plan_package
  - python3 -m unittest tests.test_plan_package_work_items
  - python3 skills/plan-to-issues/scripts/test_plan_to_issues.py
  - python3 scripts/verify_repo.py
- Deployed environment:
  - not applicable; this is a repository planning/runtime tooling change.

### Rollout / Rollback
- Rollout:
  - Land sidecar validator and template first.
  - Update `$plan` and automation decomposition docs after validator tests pass.
  - Update plan-to-issues and local plan snapshot package mode behind explicit metadata/CLI paths.
  - Run one sidecar-backed fixture through validation, dry-run projection, and package-mode snapshot.
- Rollback trigger:
  - Existing single-file planning, plan-to-issues, or local snapshot tests fail in a way that cannot be fixed without changing public semantics.
  - Package-mode snapshot creates ambiguous authority or unsafe file reads.
  - Projection produces bloated issue bodies or stale spec hashes.
- Rollback steps:
  - Disable package-mode CLI and sidecar projection apply behavior while leaving docs marked experimental.
  - Keep issue-spec validator as a standalone advisory tool if it does not break existing flows.
  - Revert `$plan` docs to sidecar-optional wording until DR-003 is revisited.

## Automation Issue Manifest
<!-- owner: automation-decomposition -->
Applies when `AutomationTarget` is not `none`.

### Dispatch policy
- Automation target: manifest-only
- Dispatch strategy: sequential
- Max concurrent work items: 1
- Required labels: plan-package-v0, planning-runtime
- Default reviewer / reviewer pool: mat
- Branch policy: one feature branch from main, no unattended dispatch
- PR policy: draft
- Merge policy: manual
- Rebase/update policy: rebase before review if main moves
- Failure policy: stop and patch the plan before continuing
- Human approval required before dispatch: yes

### Containers
- WS1:
  - Type: workstream
  - Parent: plan-package-v0
  - Dispatch: tracking-only
  - Source plan sections:
    - Implementation Plan / WS1
- WS2:
  - Type: workstream
  - Parent: plan-package-v0
  - Dispatch: tracking-only
  - Source plan sections:
    - Implementation Plan / WS2
- WS3:
  - Type: workstream
  - Parent: plan-package-v0
  - Dispatch: tracking-only
  - Source plan sections:
    - Implementation Plan / WS3
- WS4:
  - Type: workstream
  - Parent: plan-package-v0
  - Dispatch: tracking-only
  - Source plan sections:
    - Implementation Plan / WS4
- WS5:
  - Type: workstream
  - Parent: plan-package-v0
  - Dispatch: tracking-only
  - Source plan sections:
    - Implementation Plan / WS5
- WS6:
  - Type: workstream
  - Parent: plan-package-v0
  - Dispatch: tracking-only
  - Source plan sections:
    - Implementation Plan / WS6
- WS7:
  - Type: workstream
  - Parent: plan-package-v0
  - Dispatch: tracking-only
  - Source plan sections:
    - Implementation Plan / WS7

### Leaf issues
- PPV0-LEAF-001: Add issue spec template and validator
  - Type: story
  - Parent: WS1
  - Owner: issue-spec-engineer
  - Agent type: generalPurpose
  - Dispatch: manual-review
  - Depends on:
    - none
  - Parallel group: sidecar-contract
  - Blocks:
    - PPV0-LEAF-002
    - PPV0-LEAF-003
    - PPV0-LEAF-004
  - Critical path rank: 1
  - Merge group: plan-package-v0
  - Combine policy: solo
  - Conflict class: issue-spec
  - Validation tier: T1
  - External blockers:
    - none
  - Manual blockers:
    - none
  - Files in scope:
    - skills/issue-spec/SKILL.md
    - skills/issue-spec/reference.md
    - skills/issue-spec/scripts/validate_issue_spec.py
    - tests/test_issue_spec_validator.py
  - Files out of scope:
    - skills/plan-to-issues/scripts/plan_to_issues.py
    - skills/local-plan-agent-runtime/scripts/snapshot_plan.py
  - Required gates:
    - G-CI-IssueSpec-Validator
  - Validation:
    - python3 -m unittest tests.test_issue_spec_validator
  - Acceptance criteria:
    - Valid issue specs with required fields pass.
    - Missing required fields fail with specific messages for `SpecId`, `SourceId`, `ParentPlanId`, `ManifestLeafId`, `Intent`, `Anti-scope`, `Files in scope`, `Files out of scope`, `Dependencies`, `Required gates`, `Validation`, `Acceptance criteria`, `Dispatch mode`, `One PR contract`, and `Open decisions`.
    - Testing/data/coverage/fixture-heavy/runtime/projection/cross-module/multi-file leaves require a `Depth contract`.
    - `Spec: inline` is accepted only when the manifest leaf is self-contained with file scope, dependencies, validation, acceptance criteria, dispatch mode, and one-PR contract.
    - Sidecars cannot introduce or override leaves, files, gates, dependencies, dispatch readiness, approval state, or authority semantics absent from the markdown manifest.
  - One PR contract: yes
  - Risk / dispatch notes: Keep manual-review because this introduces a new authored contract.
  - Source plan sections:
    - Implementation Plan / WS1

- PPV0-LEAF-002: Update `$plan` and automation decomposition guidance
  - Type: story
  - Parent: WS2
  - Owner: plan-package-architect
  - Agent type: generalPurpose
  - Dispatch: manual-review
  - Depends on:
    - PPV0-LEAF-001
  - Parallel group: plan-docs
  - Blocks:
    - PPV0-LEAF-003
  - Critical path rank: 2
  - Merge group: plan-package-v0
  - Combine policy: solo
  - Conflict class: plan-skill-docs
  - Validation tier: T1
  - External blockers:
    - none
  - Manual blockers:
    - none
  - Files in scope:
    - skills/plan/SKILL.md
    - skills/plan/reference.md
    - skills/plan/scripts/validate_plan.py
    - skills/plan/README.md
    - skills/automation-decomposition/SKILL.md
    - README.md
    - manifests/atlas-tools.v1.json
  - Files out of scope:
    - skills/plan-to-issues/scripts/plan_to_issues.py
    - skills/local-plan-agent-runtime/scripts/snapshot_plan.py
  - Required gates:
    - G-CI-Plan-Validator
    - G-DOCS-PlanPackage-Clarity
  - Validation:
    - python3 -m unittest tests.test_plan_validator
  - Acceptance criteria:
    - Docs distinguish `$plan` public entrypoint from local-plan-agent-runtime implementation detail.
    - Manifest template includes sidecar metadata fields without requiring package directories.
    - Validator counts executable leaves as all non-`tracking-only` work leaves, including `manual-review`, `agent-ready`, and blocked leaves once blockers clear.
    - Validator warns above 8 executable leaves and fails above 12 without child-plan split or DR waiver.
    - DR-backed scope waivers must include DR id, exact executable-leaf count, rationale for not splitting, validation risk, and revisit trigger.
    - Parent plans cannot directly carry unbounded executable issue lists in any dispatch mode.
  - One PR contract: yes
  - Risk / dispatch notes: Manual-review because wording affects authority semantics.
  - Source plan sections:
    - Implementation Plan / WS2

- PPV0-LEAF-003: Add compiled package registry
  - Type: story
  - Parent: WS3
  - Owner: plan-package-architect
  - Agent type: generalPurpose
  - Dispatch: manual-review
  - Depends on:
    - PPV0-LEAF-001
    - PPV0-LEAF-002
  - Parallel group: package-registry
  - Blocks:
    - PPV0-LEAF-004
    - PPV0-LEAF-005
    - PPV0-LEAF-006
  - Critical path rank: 2
  - Merge group: plan-package-v0
  - Combine policy: solo
  - Conflict class: package-registry
  - Validation tier: T1
  - External blockers:
    - none
  - Manual blockers:
    - none
  - Files in scope:
    - skills/plan-package/reference.md
    - skills/plan-package/scripts/compile_plan_package.py
    - skills/plan-package/scripts/validate_plan_package.py
    - tests/test_plan_package.py
  - Files out of scope:
    - GitHub issue mutation code
  - Required gates:
    - G-CI-PlanPackage-Compile
  - Validation:
    - python3 -m unittest tests.test_plan_package
  - Acceptance criteria:
    - Registry compile output is deterministic.
    - Registry records required fields: `schema_version`, `package_id`, `package_hash`, `source_plan.path`, `source_plan.hash`, `members[]` with `path`, `kind`, `hash`, and `patchable`, and `leaves[]` with `source_id`, `manifest_leaf_id`, `spec_path`, `spec_hash`, `dependencies`, `required_gates`, `files_in_scope`, `files_out_of_scope`, `dispatch_mode`, `validation`, `acceptance_criteria`, `projection_hints`, and `local_export`.
    - Validator rejects missing package members, malformed hashes, hash mismatches, path escapes, duplicate source ids, missing required registry fields, and dependency mismatches.
    - Registry and generated JSON hashes use sorted keys, two-space indentation, `\n` line endings, and trailing newline before hashing.
  - One PR contract: yes
  - Risk / dispatch notes: Manual-review because registry authority must stay derived.
  - Source plan sections:
    - Implementation Plan / WS3

- PPV0-LEAF-004: Export local package work-item records
  - Type: story
  - Parent: WS4
  - Owner: runtime-engineer
  - Agent type: generalPurpose
  - Dispatch: manual-review
  - Depends on:
    - PPV0-LEAF-003
  - Parallel group: local-work-items
  - Blocks:
    - PPV0-LEAF-007
  - Critical path rank: 3
  - Merge group: plan-package-v0
  - Combine policy: solo
  - Conflict class: local-work-items
  - Validation tier: T1
  - External blockers:
    - none
  - Manual blockers:
    - none
  - Files in scope:
    - skills/plan-package/scripts/export_work_items.py
    - tests/test_plan_package_work_items.py
    - docs/automation-runtime-operational-layer.md
  - Files out of scope:
    - GitHub issue mutation code
    - GitHub Project mutation code
  - Required gates:
    - G-CI-LocalWorkItemExport
  - Validation:
    - python3 -m unittest tests.test_plan_package_work_items
  - Acceptance criteria:
    - Export reads compiled package metadata instead of reparsing sidecars independently.
    - Local work-item records include SourceId, spec hash, dependencies, write scope, validation, dispatch mode, and scope-budget status.
    - Export requires no GitHub issue creation, GitHub Project fields, or Project API calls.
  - One PR contract: yes
  - Risk / dispatch notes: Manual-review because local records become the fast execution path.
  - Source plan sections:
    - Implementation Plan / WS4

- PPV0-LEAF-005: Project sidecar metadata into concise GitHub issue bodies
  - Type: story
  - Parent: WS5
  - Owner: projection-engineer
  - Agent type: generalPurpose
  - Dispatch: manual-review
  - Depends on:
    - PPV0-LEAF-001
    - PPV0-LEAF-003
  - Parallel group: projection
  - Blocks:
    - PPV0-LEAF-007
  - Critical path rank: 3
  - Merge group: plan-package-v0
  - Combine policy: solo
  - Conflict class: plan-to-issues
  - Validation tier: T1
  - External blockers:
    - none
  - Manual blockers:
    - none
  - Files in scope:
    - skills/plan-to-issues/SKILL.md
    - skills/plan-to-issues/reference.md
    - skills/plan-to-issues/scripts/plan_to_issues.py
    - skills/plan-to-issues/scripts/test_plan_to_issues.py
  - Files out of scope:
    - templates/local-automation-runtime
  - Required gates:
    - G-CI-Projection-Sidecar
  - Validation:
    - python3 skills/plan-to-issues/scripts/test_plan_to_issues.py
  - Acceptance criteria:
    - Dry-run output includes spec path/hash metadata.
    - Apply mode blocks missing or mismatched specs.
    - Issue bodies link to specs without copying full spec content.
    - GitHub export remains optional and does not become the local execution path.
  - One PR contract: yes
  - Risk / dispatch notes: Manual-review because GitHub issue body metadata is runtime-facing.
  - Source plan sections:
    - Implementation Plan / WS5

- PPV0-LEAF-006: Add package-mode snapshot support
  - Type: story
  - Parent: WS6
  - Owner: runtime-engineer
  - Agent type: generalPurpose
  - Dispatch: manual-review
  - Depends on:
    - PPV0-LEAF-003
  - Parallel group: runtime
  - Blocks:
    - PPV0-LEAF-007
  - Critical path rank: 3
  - Merge group: plan-package-v0
  - Combine policy: solo
  - Conflict class: local-plan-agent-runtime
  - Validation tier: T1
  - External blockers:
    - none
  - Manual blockers:
    - none
  - Files in scope:
    - skills/local-plan-agent-runtime/SKILL.md
    - skills/local-plan-agent-runtime/references/run-protocol.md
    - skills/local-plan-agent-runtime/references/proposal-schema.md
    - skills/local-plan-agent-runtime/scripts/snapshot_plan.py
    - skills/local-plan-agent-runtime/scripts/validate_proposal.py
    - skills/local-plan-agent-runtime/scripts/summarize_run.py
    - tests/test_local_plan_snapshot.py
    - tests/test_local_plan_agent_runtime.py
  - Files out of scope:
    - skills/plan-to-issues/scripts/plan_to_issues.py
  - Required gates:
    - G-CI-PackageSnapshot
  - Validation:
    - python3 -m unittest tests.test_local_plan_snapshot tests.test_local_plan_agent_runtime
  - Acceptance criteria:
    - Existing single-file snapshot behavior is unchanged.
    - Package mode CLI is `python3 skills/local-plan-agent-runtime/scripts/snapshot_plan.py PLAN.md --package-manifest PACKAGE.json --out DIR`.
    - Package snapshot records package files with file hashes and section hashes.
    - Package-mode proposals cannot patch read-only documents or stale package snapshots.
    - Path traversal, symlink escape, outside-root manifest, and selected-plan mismatch fixtures fail.
  - One PR contract: yes
  - Risk / dispatch notes: Manual-review because package snapshot expands file read scope.
  - Source plan sections:
    - Implementation Plan / WS6

- PPV0-LEAF-007: Integrate and review Plan Package v0
  - Type: validation
  - Parent: WS7
  - Owner: test-engineer
  - Agent type: code-reviewer
  - Dispatch: blocked
  - Depends on:
    - PPV0-LEAF-002
    - PPV0-LEAF-003
    - PPV0-LEAF-004
    - PPV0-LEAF-005
    - PPV0-LEAF-006
  - Parallel group: integration
  - Blocks:
    - none
  - Critical path rank: 4
  - Merge group: plan-package-v0
  - Combine policy: solo
  - Conflict class: integration-review
  - Validation tier: T1
  - External blockers:
    - none
  - Manual blockers:
    - human approval required before projection or dispatch
  - Files in scope:
    - plans/plan-package-v0.plan.md
    - tests/test_plan_validator.py
  - Files out of scope:
    - product repositories outside AtlasMemory-Tools
    - README.md
  - Required gates:
    - G-CI-Repo-Verify
    - G-Review-AgenticPackage
  - Validation:
    - python3 scripts/verify_repo.py
  - Acceptance criteria:
    - Existing repo verification passes or failures are explicitly dispositioned.
    - One local work-item export runs from the package fixture without GitHub Project calls.
    - One optional GitHub dry-run projection runs from the same fixture without copying full specs into issue bodies.
    - `$plan` agentic review mode can review the package v0 plan and package fixture.
    - Planning reviews are refreshed before approval or projection.
  - One PR contract: yes
  - Risk / dispatch notes: Blocked until upstream leaves are complete and user approves final review.
  - Source plan sections:
    - Implementation Plan / WS7

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
RefreshedAt: 2026-06-17T12:30:00
ReviewedPlanHash: sha256:02c5f8e822a016c4578b34debbc5ad0b72bfee89e3fcf2143a82499497b9edd6
- Re-entry audit answers:
  - What is being built: Plan Package v0 adds sidecar issue specs, a derived package registry, local package/work-item export, optional GitHub issue metadata export, package-mode local agent snapshots, and scope-budget validation.
  - Why now: Large plans currently flatten issue-level detail; the repo already has plan validation, issue projection, local work-item/runtime tooling, and local agent snapshot machinery ready for a sidecar/package bridge.
  - Repos involved: AtlasMemory-Tools only.
  - What changes first: PPV0-LEAF-001 creates `skills/issue-spec/` and its validator/template before plan/package/export consumers build on it.
  - What must not happen: GitHub Projects must not become required for local planning or execution; package directories must not become default in v0; sidecars must not override markdown manifest authority; issue bodies must not copy full specs.
  - How work is validated: Named local gates cover issue spec validation, plan validation, package compile, local work-item export, optional projection, package snapshot, and repo verification.
  - What remains blocked: Projection and dispatch approvals remain blocked until explicit user approval after implementation tests; no planning-decision blocker remains.

- Missing context:
  - F-001: (Resolved) Hash semantics were under-specified for `SpecHash`, `PackageHash`, and source hashes. Technical Plan now defines v0 text and generated JSON canonicalization rules.
- Contradictions:
  - F-002: No contradiction remains between sidecar-first migration, local-first execution, optional GitHub export, and package opt-in decisions.
- Unclear decisions:
  - F-003: (Resolved) Snapshot CLI was previously a preference. Technical Plan and Phase 6 now define `python3 skills/local-plan-agent-runtime/scripts/snapshot_plan.py PLAN.md --package-manifest PACKAGE.json --out DIR`.
- Risks and edge cases:
  - F-004: (Resolved) Package registry schema was conceptual. Technical Plan and PPV0-LEAF-003 now list required registry fields and validation failures.
- What I would screw up implementing tomorrow:
  - F-005: (Resolved) A build agent might create an incompatible registry shape. PPV0-LEAF-003 now requires fields consumed by local export, projection, and snapshots.
- Disposition:
  - Accept: F-001 -> DR-008
  - Reject: F-002 -> No contradiction found after review; no patch needed.
  - Accept: F-003 -> DR-008
  - Accept: F-004 -> DR-008
  - Accept: F-005 -> DR-008

### Implementer Readiness Review
RefreshedAt: 2026-06-17T12:30:00
ReviewedPlanHash: sha256:02c5f8e822a016c4578b34debbc5ad0b72bfee89e3fcf2143a82499497b9edd6
- Top 5 gotchas:
  - F-001: (Resolved) Hash canonicalization could diverge across validators, compiler, projection, and snapshots.
  - F-002: (Resolved) Package registry schema could be invented differently by separate implementers.
  - F-003: (Resolved) Snapshot package-mode CLI could diverge between docs, tests, and runtime.
  - F-004: (Resolved) Inline-spec fallback could become a loophole for shallow leaves.
  - F-005: (Resolved) Review freshness blocks were missing and would keep PlanningReviewsComplete failing.
- Evidence needed to prevent each gotcha:
  - F-002: Technical Plan and PPV0-LEAF-003 now define hash canonicalization, registry required fields, exact snapshot CLI, inline-spec constraints, and refreshed review blocks with `ReviewedPlanHash`.
- Pass/fail readiness statement:
  - F-003: Pass for build readiness. PPV0-LEAF-001 is ready to implement first; projection and dispatch remain blocked pending explicit human approval.
- Disposition:
  - Accept: F-001 -> DR-008
  - Accept: F-002 -> DR-008
  - Accept: F-003 -> DR-008
  - Accept: F-004 -> DR-008
  - Accept: F-005 -> DR-008

### Expert Technical Review
RefreshedAt: 2026-06-17T12:30:00
ReviewedPlanHash: sha256:02c5f8e822a016c4578b34debbc5ad0b72bfee89e3fcf2143a82499497b9edd6
- Technical risks and integration gaps:
  - F-001: (Resolved) Shared schema/hash contract spans issue spec validation, package compile, local work-item export, optional GitHub projection, and package snapshot. The plan now defines canonical hash inputs and registry fields.
- Missing validations or operational steps:
  - F-002: (Resolved) The plan now requires tests for malformed hashes, hash mismatches, duplicate source ids, path escapes, missing registry fields, dependency mismatches, outside-root package manifests, and selected-plan mismatch.
- Contradictions with stated invariants or authority boundaries:
  - F-003: No contradiction found. Sidecars remain governed attachments; registry is derived; local work-item records are primary only before optional external export; GitHub Projects remain optional UI/signal.
- Patch suggestions (point to plan sections):
  - F-004: (Resolved) Patched `Technical Plan / Integration Points`, `Proposed Architecture Changes`, `Phase 3`, `Phase 6`, `PPV0-LEAF-003`, and `PPV0-LEAF-006`.
- Disposition:
  - Accept: F-001 -> DR-008
  - Accept: F-002 -> DR-008
  - Reject: F-003 -> No contradiction found after review; no patch needed.
  - Accept: F-004 -> DR-008

### Security/Privacy Review
RefreshedAt: 2026-06-17T12:30:00
ReviewedPlanHash: sha256:02c5f8e822a016c4578b34debbc5ad0b72bfee89e3fcf2143a82499497b9edd6
- Domain risks and integration gaps:
  - F-001: Package-mode snapshot expands file read scope and could include unintended files or prompt-injection-like sidecar content if not treated as data.
- Missing validations or operational steps:
  - F-002: Required validations are present: path confinement, symlink escape, outside-root manifest rejection, selected-plan mismatch rejection, package hash drift rejection, and read-only document patch rejection.
- Contradictions with stated invariants or authority boundaries:
  - F-003: No contradiction found. The plan states package files are untrusted content, sidecars are governed attachments, and workers cannot write canonical package files directly.
- Patch suggestions (point to plan sections):
  - F-004: No additional patch required beyond the hash/schema/CLI review remediation already recorded in DR-008.
- Disposition:
  - Reject: F-001 -> Risk is already covered by `G-CI-PackageSnapshot`, path confinement tests, and read-only proposal validation.
  - Reject: F-002 -> Validation coverage already present in Phase 6 and PPV0-LEAF-006.
  - Reject: F-003 -> No contradiction found.
  - Reject: F-004 -> No additional patch required.

### Dynamic Specialist Review Roster
RefreshedAt: 2026-06-17T12:30:00
ReviewedPlanHash: sha256:02c5f8e822a016c4578b34debbc5ad0b72bfee89e3fcf2143a82499497b9edd6
- Triggered specialist review rationale:
  - F-001: Automation/runtime dispatch review is triggered because the plan changes manifest leaves, local work-item records, optional GitHub projection metadata, and package snapshot inputs.
  - F-002: API/contracts review is triggered because v0 adds sidecar, registry, work-item, projection, and snapshot schema contracts.
  - F-003: Security/privacy review is triggered because package mode reads additional files and worker prompts must treat sidecar/package content as untrusted data.
- Skipped specialist review rationale:
  - F-004: Cloud/provider infrastructure review is not triggered because the plan changes local repository tooling only and does not add hosted infrastructure.
  - F-005: Database/migration review is not triggered because the plan does not alter persistent database schemas or data migrations.
  - F-006: UI/operator workflow review is not triggered because there is no user interface surface beyond docs and CLI/runtime commands.
- Missing or deferred specialist coverage:
  - F-007: No specialist coverage remains missing for Plan Package v0.
- Disposition:
  - Accept: F-001 -> DR-008
  - Accept: F-002 -> DR-008
  - Accept: F-003 -> DR-008
  - Reject: F-004 -> Not in scope for this local tooling plan.
  - Reject: F-005 -> Not in scope for this local tooling plan.
  - Reject: F-006 -> Not in scope for this local tooling plan.
  - Reject: F-007 -> No missing coverage remains.

### Automation Readiness Review
RefreshedAt: 2026-06-17T12:30:00
ReviewedPlanHash: sha256:02c5f8e822a016c4578b34debbc5ad0b72bfee89e3fcf2143a82499497b9edd6
- Manifest gaps:
  - F-001: No manifest gap found. The plan has tracking containers and explicit leaf issues with owners, dispatch modes, dependencies, file scopes, gates, validation, acceptance criteria, and one-PR contracts.
- Dependency/gate/file-scope risks:
  - F-002: (Resolved) Registry fields shared across leaves were implicit. PPV0-LEAF-003 now lists required registry fields and validation failures.
- Dispatch policy risks:
  - F-003: No dispatch policy risk found for `manifest-only`: dispatch is sequential, max concurrency is 1, all executable leaves are `manual-review` or `blocked`, and human approval is required before dispatch.
- Pass/fail readiness statement:
  - F-004: Pass for manifest-only automation readiness. Projection and dispatch approval remain blocked until explicit human approval after implementation tests.
- Disposition:
  - Reject: F-001 -> No manifest gap found.
  - Accept: F-002 -> DR-008
  - Reject: F-003 -> No dispatch policy risk found.
  - Reject: F-004 -> Pass statement; no patch required.

### Human Readability Review
RefreshedAt: 2026-06-17T12:30:00
ReviewedPlanHash: sha256:02c5f8e822a016c4578b34debbc5ad0b72bfee89e3fcf2143a82499497b9edd6
- Product/system clarity:
  - F-001: Pass. The Problem Definition explains the product/system failure: large plans force too much execution detail into one document and lose leaf-level requirements.
- Technical narrative clarity:
  - F-002: Pass. The Technical Plan Intro explains the sidecar bridge, validator, local work-item export, optional projection, and package snapshot changes.
- Execution-mechanics leakage:
  - F-003: Pass. Planning/projection mechanics are the system being changed, and authority/dispatch details are mostly confined to execution sections and appendices.
- Strongest remaining ambiguity:
  - F-004: None after review remediation. Hash, registry, snapshot CLI, and sidecar override contracts are now explicit.
- Pass/fail readability statement: Pass
- Disposition:
  - Reject: F-001 -> Pass finding; no patch required.
  - Reject: F-002 -> Pass finding; no patch required.
  - Reject: F-003 -> Pass finding; no patch required.
  - Reject: F-004 -> No remaining ambiguity found.

## Execution Mechanics / Automation Appendix
### Authority / source-of-truth contract
- Authoring write surface: selected harness-local markdown plan artifact for v0.
- Issue spec sidecars: governed attachments referenced by the selected plan through path/hash metadata; they are not independent gate or approval authority in v0.
- Local planning package after compile: generated package registry, derived from selected plan plus declared package files and not independent intent authority.
- Local execution truth before external export: local package/work-item records for validation, queueing, retry, audit, and dispatch simulation.
- GitHub-backed execution truth after optional export: GitHub issues / PRs / checks for repositories that choose external tracking and PR workflow integration.
- Execution UI / signal layer: GitHub Projects v2 only after optional sync/export; Projects are not required for local package validation, local queueing, or local work-item execution.
- Derived read models / views: runtime mirror, rendered overlays, forecasts, compiled package registry.

### Projection and dispatch approvals
- Structural completion evidence: Drafted in this plan; requires validator run and agentic review before state changes.
- Substance review evidence: Not complete; reviews are pending.
- Local execution readiness evidence: Blocked until package compile, local work-item export, scope-budget validation, and refreshed reviews pass.
- Projection approval evidence: Blocked until optional plan-to-issues sidecar behavior exists and reviews are refreshed.
- Dispatch approval evidence: Blocked; all manifest leaves are manual-review or blocked.
- Dispatch remains blocked until: user approves local dispatch and, separately, optional GitHub projection/dispatch after refreshed reviews and implementation tests pass.

## Execution Status
Phase: Phase 7 - Integration Review
Status: complete with documented release-gate blockers

Workstreams:
- WS1: complete - PPV0-LEAF-001 implemented and G-CI-IssueSpec-Validator passed locally.
- WS2: complete - PPV0-LEAF-002 updated `$plan` docs, automation decomposition guidance, sidecar metadata template fields, and scope-budget validator/tests.
- WS3: complete - PPV0-LEAF-003 added deterministic plan-package compiler/validator and registry tests.
- WS4: complete - PPV0-LEAF-004 added local work-item export from compiled registry metadata and docs/tests.
- WS5: complete - PPV0-LEAF-005 added optional plan-to-issues sidecar projection metadata and apply-mode preflight tests.
- WS6: complete - PPV0-LEAF-006 added package-mode snapshot/proposal validation and tests.
- WS7: complete with blockers - integrated review findings were fixed; repo verification remains blocked by unrelated pre-existing `.codex/skills` required-copy deletions.

Delegation matrix:
- Task: PPV0-LEAF-001 Add issue spec template and validator | Owner: issue-spec-engineer / worker 019ed6e4-1b3e-7463-b859-c9bded0e6d3c | Files: skills/issue-spec/SKILL.md, skills/issue-spec/reference.md, skills/issue-spec/scripts/validate_issue_spec.py, tests/test_issue_spec_validator.py | Agent: worker | Status: complete
- Task: PPV0-LEAF-002 Update `$plan` and automation decomposition guidance | Owner: plan-package-architect / worker 019ed6ee-f070-70f1-b1ff-88114e37d02f | Files: skills/plan/SKILL.md, skills/plan/reference.md, skills/plan/scripts/validate_plan.py, skills/plan/README.md, skills/automation-decomposition/SKILL.md, README.md, manifests/atlas-tools.v1.json, tests/test_plan_validator.py | Agent: worker | Status: complete
- Task: PPV0-LEAF-003 Add compiled package registry | Owner: plan-package-architect / worker 019ed6f4-71a6-71c3-bc41-ff80aea03291 | Files: skills/plan-package/reference.md, skills/plan-package/scripts/compile_plan_package.py, skills/plan-package/scripts/validate_plan_package.py, tests/test_plan_package.py | Agent: worker | Status: complete
- Task: PPV0-LEAF-004 Export local package work-item records | Owner: runtime-engineer / worker 019ed6f9-02d7-79b1-a3f9-f46ed504f834 | Files: skills/plan-package/scripts/export_work_items.py, tests/test_plan_package_work_items.py, docs/automation-runtime-operational-layer.md | Agent: worker | Status: complete
- Task: PPV0-LEAF-005 Project sidecar metadata into concise GitHub issue bodies | Owner: projection-engineer / worker 019ed6f9-2270-7a60-87be-4317dbd88907 | Files: skills/plan-to-issues/SKILL.md, skills/plan-to-issues/reference.md, skills/plan-to-issues/scripts/plan_to_issues.py, skills/plan-to-issues/scripts/test_plan_to_issues.py | Agent: worker | Status: complete
- Task: PPV0-LEAF-006 Add package-mode snapshot support | Owner: runtime-engineer / worker 019ed6f9-4ac4-7e62-b34f-11883ab2e137 | Files: skills/local-plan-agent-runtime/SKILL.md, skills/local-plan-agent-runtime/references/run-protocol.md, skills/local-plan-agent-runtime/references/proposal-schema.md, skills/local-plan-agent-runtime/scripts/snapshot_plan.py, skills/local-plan-agent-runtime/scripts/validate_proposal.py, tests/test_local_plan_snapshot.py, tests/test_local_plan_agent_runtime.py | Agent: worker | Status: complete
- Task: PPV0-LEAF-007 Integrate and review Plan Package v0 | Owner: test-engineer / reviewer 019ed6fe-3c68-7850-a019-26d7f9eab1e6 plus orchestrator | Files: plans/plan-package-v0.plan.md and integrated touched files | Agent: worker/code-reviewer | Status: complete with repo-verify blocker

Completed tasks:
- Added issue-spec sidecar skill/template/validator and tests.
- Added sidecar metadata, parent/child scope-budget guidance, and scope-budget validation/tests to planning and automation decomposition docs.
- Added `skills/plan-package/` compiler, validator, reference, and package registry tests.
- Added compiled-registry-to-local-work-items export, including local-only metadata and tracking-only exclusion.
- Added optional plan-to-issues sidecar metadata projection, `Spec source id` parsing, and apply-mode preflight failures for missing/stale/mismatched sidecars.
- Added package-mode local agent snapshot/proposal validation, root confinement, read-only document patch rejection, and v0 `sha256:` package hash behavior.
- Fixed integration review findings: tracking-only package leaves no longer export as ready local work items, manifest `Spec source id` is enforced, and package-mode snapshot hashes use the v0 normalized `sha256:` contract.

Blocked:
- `scripts/verify_repo.py` fails because required `.codex/skills/local-automation-runtime-setup`, `local-automation-runtime-operate`, and `local-automation-runtime-upgrade` copy paths are missing. These `.codex/skills/...` deletions were present before this build and were not modified or reverted.
- `PlanningReviewsComplete` fails mechanically because this build updated `## Execution Status`, changing the reviewed plan hash. Reviews were not refreshed, and no projection/dispatch approval was granted.
- ProjectionApproval remains Blocked by plan state; no GitHub issues, PRs, projects, projection approval, or automation dispatch occurred.
- DispatchApproval remains Blocked by plan state; no automation dispatch occurred.

Build gates:
- G-CI-IssueSpec-Validator - pass - included in `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_issue_spec_validator tests.test_plan_validator tests.test_plan_package tests.test_plan_package_work_items tests.test_local_plan_snapshot tests.test_local_plan_agent_runtime`; combined run passed 64 tests.
- G-CI-Plan-Validator - pass for unit gate - same combined unittest run passed `tests.test_plan_validator`; `validate_plan.py plans/plan-package-v0.plan.md` passes IntentModelComplete, ProblemDefinitionComplete, PlanReadiness, AutomationReadiness, and PlanStateSanity but fails PlanningReviewsComplete on stale review hashes.
- G-CI-PlanPackage-Compile - pass - same combined unittest run passed `tests.test_plan_package`.
- G-CI-LocalWorkItemExport - pass - same combined unittest run passed `tests.test_plan_package_work_items`.
- G-CI-Projection-Sidecar - pass - `PYTHONDONTWRITEBYTECODE=1 python3 skills/plan-to-issues/scripts/test_plan_to_issues.py` passed 55 tests.
- G-CI-PackageSnapshot - pass - same combined unittest run passed `tests.test_local_plan_snapshot` and `tests.test_local_plan_agent_runtime`.
- G-CI-Repo-Verify - fail - `PYTHONDONTWRITEBYTECODE=1 python3 scripts/verify_repo.py` reports missing required copy paths under `.codex/skills/local-automation-runtime-*`.
- G-Review-AgenticPackage - pass with findings fixed - integration review found tracking-only export, `Spec source id`, and package hash contract gaps; all were patched and covered by regression tests.

Sub-agent usage:
- Agents launched: 7
- Parallel batches: 2
- Direct orchestrator edits: 2 - integration corrections for PPV0-LEAF-001 and PPV0-LEAF-007 findings, then execution-status update.

Next actions:
- Restore or regenerate the unrelated missing `.codex/skills/local-automation-runtime-*` required copy paths before treating `G-CI-Repo-Verify` as green.
- Refresh planning reviews if this plan needs to return to `PlanningReviewsComplete: Pass`.
- Keep projection and dispatch approvals blocked until explicit user approval after implementation tests.
