# Feature: Database-backed agent workspaces

## Plan State
PlanFormatVersion: 2
PlanId: database-backed-agent-workspaces
PlanGroup: none
PlanKind: architecture
ParentPlan: none
DependsOnPlans: none
BlocksPlans: none
AtomicScope: Implement an opt-in local managed-workspace lane from committed source import through reviewed Git candidate export, with storage/harness qualification before activation.
CampaignMetadataAuthority: descriptive-only; explicit @path authoring artifact selection wins
Status: SubstantivelyReviewed
StructuralStatus: StructurallyComplete
SubstanceStatus: SubstantivelyReviewed
ProjectionApproval: NotRequested
DispatchApproval: NotRequested
CurrentStage: Reviews
PlanTier: Full
AutomationTarget: none
DeliveryMode: DevOnly
ContextMode: RepoInferred
LastUpdated: 2026-11-09
PrimaryOwner: root planning orchestrator
BaseBranch: current checkout; no branch mutation requested
BaseCommit: 6edb37cdcabf2af2dfcf9626916aad9b1de27acf
TargetBranch: none; research and planning only
Related: docs/local-harness-operating-instruction.md; docs/daily-development.md
NextRequiredUserAction: None for plan repair. Implementation is a separate request beginning with WS1 qualification; no installation, dispatch, publication or merge is authorized by this planning status.
BlockingDecision: none
UnresolvedBlockers: 0
RubberStampSignals: 0
LastGateRun: 2026-11-09
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

### DR-001: Git-free tasks and Git-owned accepted history
- Stage: Problem
- Date: 2026-11-09
- ScopeAffected: Workspace representation, source import, review, Git export.
- Decision: Select B. The user explicitly chose Git-owned accepted source history while agents work without `.git`.
- Options considered:
  - A) Git repositories inside database-backed task mounts.
  - B) Git-free task mounts; a separate bridge imports/exports Git, which retains accepted source history.
  - C) Database-owned accepted revisions; Git is an export.
- Why chosen: Removes task checkout/worktree administration while retaining established source integration.
- Consequences / follow-ups: A candidate commit is not a merge or accepted-branch advance. B is the v1 contract; C is outside this scope.
- Status: Accepted

### DR-002: Primary outcome and object storage
- Stage: Problem
- Date: 2026-11-09
- ScopeAffected: First delivery and storage placement.
- Decision: Simplify isolated workspace creation/resume first. Multi-machine sharing is future work; the accidental SQL-only answer remains withdrawn.
- Options considered:
  - A) Task lifecycle/resume first.
  - B) Multi-machine sharing first.
  - C) Require SQL-only bytes and metadata.
- Why chosen: Explicit corrected user answer.
- Consequences / follow-ups: Object storage is permitted. First local qualification can use JuiceFS's PostgreSQL block backend without requiring a separate object-storage service.
- Status: Accepted

### DR-003: DBOS for the new local lifecycle
- Stage: Problem
- Date: 2026-11-09
- ScopeAffected: New-task state, orchestration, versioned handoff, recovery.
- Decision: Plan an additive opt-in DBOS/PostgreSQL/JuiceFS lane. Existing JSON tasks and pending v1 handoffs finish through their original runtime; no dual state authority or automatic migration.
- Options considered:
  - A) Keep JSON orchestration indefinitely and replace only storage.
  - B) Add a new DBOS-backed lane, qualify it, then explicitly select it for new tasks.
  - C) Convert active legacy tasks in place.
- Why chosen: User accepts the stack and requests implementation planning; B preserves existing live evidence while delivering the requested engine direction.
- Consequences / follow-ups: Source implementation is distinct from selecting an installed runtime or launching jobs. The current config/provenance error blocks live qualification, not plan authoring or offline source work.
- Status: Accepted

### DR-004: PostgreSQL-first local configuration
- Stage: Technical
- Date: 2026-11-09
- ScopeAffected: Dependencies, schema, filesystem metadata and blocks.
- Decision: Use one local PostgreSQL service with separate supported namespaces for application/DBOS records and JuiceFS metadata/data in the initial qualification. External object-storage backends remain a later configuration extension.
- Options considered:
  - A) PostgreSQL metadata/state plus PostgreSQL JuiceFS blocks for local v1.
  - B) PostgreSQL metadata/state plus external object storage immediately.
  - C) Worker-local SQLite as the primary backend.
- Why chosen: PostgreSQL preference and local-only delivery; A minimizes independently operated services for the first proof. This is an implementation choice to validate, not a reinstatement of SQL-only product requirements.
- Consequences / follow-ups: Qualification records exact versions, growth, flush, and recovery behavior. A failed capability stops dependent work; it does not authorize another backend silently.
- Status: Accepted

### DR-005: Committed-only, independent source import
- Stage: Problem
- Date: 2026-11-09
- ScopeAffected: Local/remote source admission and retained history.
- Decision: Import committed revisions only, as selected by the user. Copy a complete source tree into owned JuiceFS storage and retain a self-contained Git bundle for export-critical objects and parent history. The donor repository is an origin, not backing storage.
- Options considered:
  - A) Fixed committed tree copied independently.
  - B) Selected dirty/untracked overlays.
  - C) Read-through dependency on the original repository.
- Why chosen: Explicit committed-only answer and managed-resume objective. Report excluded local changes; do not silently import or modify them.
- Consequences / follow-ups: No source alternates or hardlinks; disposable bare caches rebuild from retained bundles. SHA-1 Git trees only in v1; submodules, LFS-dependent content, unsafe paths/escaping symlinks receive explicit unsupported-input diagnostics.
- Status: Accepted

### DR-006: Local delivery and existing provider reuse
- Stage: Problem
- Date: 2026-11-09
- ScopeAffected: Operator interface, credentials, GitHub/Azure adapters, rollout.
- Decision: Local service first, with adaptation of existing GitHub/Azure integrations. Cloud hosting is excluded, as explicitly clarified by the user.
- Options considered:
  - A) Local service, current provider reuse, no hosted deployment.
  - B) Local-only source support with provider adaptation later.
  - C) Hosted multi-user service now.
- Why chosen: Explicit user answer and subsequent request to reuse existing integrations.
- Consequences / follow-ups: Private same-UID local control boundary. Provider credentials remain server-side through existing routes. Branch/PR publication requires its existing exact-operation authority; no merge capability is added.
- Status: Accepted

### DR-007: Git functions and harness capability qualification
- Stage: Technical
- Date: 2026-11-09
- ScopeAffected: Agent context, Git-dependent build tools, host profiles.
- Decision: Preserve required Git information through read-only context functions and broker history mutations outside the task directory. The first bounded phase qualifies plain-file execution and, where needed, a read-only external metadata view. No blanket feature loss is recorded as user-approved.
- Options considered:
  - A) Treat Git-free as removal of all Git features.
  - B) Separate file execution, Git context, and broker operations; qualify required behavior before admitting a harness/project.
  - C) Restore a writable `.git` or native worktree per task.
- Why chosen: The user requested help identifying affected functions. B preserves the accepted Git-free direction while making compatibility an engineering acceptance requirement.
- Consequences / follow-ups: Qualification selects a capability profile from measured evidence. If no profile satisfies required behavior, retain failure and stop dependent work for a scoped amendment. Never silently create a hidden task repository or launch another route.
- Status: Accepted

### DR-008: Scope deferrals and stop gates
- Stage: Implementation
- Date: 2026-11-09
- ScopeAffected: Hosting, active-task migration, remote canaries, unsupported repository features.
- Decision: Defer cloud hosting, multi-user/HA operation, dirty-input support, generalized Git formats/LFS/submodule support, and active legacy-task migration.
- Options considered:
  - A) Implement all immediately.
  - B) Deliver the bounded local lane and defer these extensions.
  - C) Stop all development until production deployment is selected.
- Why chosen: User's local-first and committed-only scope; remaining extensions are not needed for the first complete workflow.
- Consequences / follow-ups: Actual-host and credentialed-provider canaries require exact selected runtime, route, target, and authority. Their absence blocks activation/live effects, not offline build tasks.
- Status: Deferred
- Revisit trigger: A separate request for the deferred capability, or failure evidence that the admitted workload requires it.

### DR-009: Review remediation authority
- Stage: Reviews
- Date: 2026-11-09
- ScopeAffected: Plan clarity and implementation contracts.
- Decision: The orchestrator may reconcile source facts, precise contracts, test coverage, file ownership, and wording within the accepted scope. Security/data-policy/cost/provider changes remain human decisions.
- Options considered:
  - A) Leave every clarity finding unresolved.
  - B) Repair scope-preserving findings and rerun fresh reviews.
  - C) Let review agents alter product decisions or approve execution.
- Why chosen: Existing plan workflow; makes independent reviews actionable without changing user choices.
- Consequences / follow-ups: Each finding gets an explicit disposition; material edits invalidate prior review hashes. Scope-preserving repairs specify taskless operation identity, canonical manifests, pre-seal node checks, redaction tests, earlier transport ownership, explicit canary production, qualified interpreter/bootstrap bindings including the full tracked runtime package, uncertain commit acknowledgement, and capacity accounting for the existing operator-configured limits. These clarify implementation and verification of the selected design; no runtime or dispatch authority follows.
- Status: Accepted

### DR-010: First usable milestone
- Stage: Implementation
- Date: 2026-11-09
- ScopeAffected: Completion and provider enablement gates.
- Decision: The user explicitly selected the complete local workflow ending in a reviewed Git commit/bundle; live remote publication is qualified separately per provider.
- Options considered:
  - A) Local completion first, provider canaries separately.
  - B) Require live draft PRs on both providers for initial completion.
  - C) Count storage/component tests alone as first usable delivery.
- Why chosen: Explicit implementation comprehension-check answer.
- Consequences / follow-ups: G-PROVIDER-LIVE controls only the corresponding provider path; it is not a prerequisite for local core completion.
- Status: Accepted

### DR-011: Re-entry contract repairs
- Stage: Reviews
- Date: 2026-11-09
- ScopeAffected: Original Git objects, same-task rework, provider-neutral readable approval, regression evidence.
- Decision: Repair the three re-entry findings with controlled Git reads and object verification, an explicit `task rework` operation that preserves the task while creating a successor generation, and a backward-compatible workspace approval request schema. Keep existing issuers, trust, signed envelopes, supported actions and effect restrictions.
- Options considered:
  - A) Retain implicit Git execution, an unspecified rework path and the Azure-only approval request.
  - B) Specify the missing contracts and their consumers/tests within the selected local lane.
  - C) Replace the approval platform, change provider policy, or rebuild the legacy task lifecycle.
- Why chosen: The user explicitly requested repair of the three findings after the re-entry review. B completes the accepted scope without changing authentication, billing, retention, dispatch or merge policy.
- Consequences / follow-ups: WS2 fixes the shared request/state contracts; WS3 verifies original Git objects; WS4/WS6 preserve rejected candidates and resume one successor generation; WS7 extends the reusable approval library and owns the workspace operator route. Old Azure request identities and cards remain compatible. Fresh reviews replace the superseded pass claims; no implementation or live operation is authorized.
- Status: Accepted

## Risks / Assumptions / Tests

- R1 (High), WS2/WS4: Partial cross-component import/freeze appears admitted. Stage and verify tree, bundle and manifest before CAS admission; test G-DB/G-SOURCE/G-STORAGE.
- R2 (High), WS5/WS6: A stale process writes after workflow ownership changes. One worker; no takeover/freeze before actual terminal/release observation; test G-HOST/G-RECOVERY.
- R3 (High), WS3/WS7: Export or publication differs from the reviewed candidate. Seal/digest/tree/parent checks and exact operation grants; test G-SOURCE/G-AUTH/G-PROVIDER.
- R4 (High), WS7: Reusing a raw client bypasses current authority. Adapt typed v2 bindings through existing grant/approval verification before effects; foreign/stale/revoked cases must fail before client access under G-AUTH.
- R5 (Medium), WS1/WS5: Missing Git metadata changes guidance or version-tool behavior. Qualify read context and external read-only metadata profiles under G-CAP/G-HOST; no user-approved blanket feature loss.
- R6 (Medium), WS6: A committed result loses its notification, or replayed notification repeats an effect. Application outbox plus stable message/request identity and original-byte replay; test G-RECOVERY.
- R7 (Medium), WS8: Backup restores inconsistent workflow/filesystem references. Quiesce all writers/transitions and verify a coordinated fresh-target restore under G-E2E.
- R8 (Medium), WS1/WS8: Small-file churn and retained bundles exceed local capacity. Explicit admission limits, measured fixture timings/bytes and visible blocked intake; no automatic deletion or unmeasured throughput claim.
- R9 (High), WS3: Replacement refs, ambient Git settings or lazy fetching alter pinned-source reads or mutate the donor. Use controlled execution, original-object hash checks and independent bundle/manifest comparison; test replacement/configuration/missing-object fixtures under G-SOURCE.
- R10 (Medium), WS2/WS4/WS6: A rejected candidate loses edits or a retry creates two successor generations. Explicit same-task rework binds the failed candidate, reserves one successor and preserves prior evidence; test G-DB/G-STORAGE/G-RECOVERY/G-E2E.
- R11 (High), WS7: A workspace request is forced through Azure issue fields or a new request format weakens existing approval. Extend the reusable approval library with a discriminated schema, preserve legacy identities and cryptographic verification, and test both full lifecycles under G-AUTH.
- Status of R1–R11: Unverified engineering risks with concrete mitigation/gates. They are not claims of current runtime failure or successful mitigation.
- A1: Required JuiceFS/PostgreSQL semantics exist in the pinned target build. Test G-CAP; failure stops dependent work rather than selecting a new backend silently. Status: Untested.
- A2: An admitted source is independent of donor and bare cache. Test G-SOURCE by removing controlled fixtures and restoring retained Git closure. Status: Untested.
- A3: One qualified harness/project profile can perform the complete Git-free workflow. Test G-HOST with actual original receipts and required context/guidance/version behavior. Status: Untested.
- A4: DBOS recovery preserves task/external-effect identity. Test G-RECOVERY with real PostgreSQL/process restarts and explicit stand-ins, then G-E2E with actual admitted host evidence. Status: Untested.

## Intent Model

Latent target:
- What the user appears to be trying to achieve: Replace durable per-task Git worktrees with managed, resumable workspaces using DBOS, PostgreSQL, and JuiceFS. Agents operate on ordinary mounted files without `.git`; Git retains accepted source history.
- What the user is reacting against: Local checkout directories carrying persistence, isolation, and recovery responsibilities, with unclear local/remote import behavior.
- Non-verbal / experiential target: Import once, create a task workspace by identity, resume it after interruption, inspect a frozen result, and export a normal Git commit without managing a task checkout.
- Confidence: High. Committed-only imports, local-first delivery, existing provider reuse, and Git-owned accepted history were explicitly selected.

Anti-targets:
- Depend on the donor repository for missing file contents or Git objects after reporting import success.
- Include dirty, untracked, or ignored working-directory files in the first version.
- Reintroduce `.git`, hidden per-task Git worktrees, or database-owned accepted source history.
- Replace normal file tools with an SDK-only interface or promise compatibility with every harness without testing it.
- Rebuild GitHub/Azure authentication or provider governance when existing paths can be adapted.
- Expand this work into cloud hosting, multi-user delivery, unattended operation, automatic merging, or in-place migration of pending work.
- Treat durable storage as a prohibition on transient mounts, caches, transport files, or local tool processes.

Expression-state notes:
- User phrase: "I'm fine with the git free workspace."
  - Interpreted meaning: Task file namespaces contain no `.git`; the Git bridge operates outside them.
  - Alternate plausible interpretations: None requiring a Git checkout inside a task.
  - Confidence: High.
  - Risk if wrong: Restore the original lifecycle burden under another name.
- User choice: "Committed revisions only for the first implementation."
  - Interpreted meaning: A commit tree supplies exact baseline bytes; local working changes are excluded and reported.
  - Alternate plausible interpretations: None authorizing dirty/untracked import.
  - Confidence: High.
  - Risk if wrong: Import unintended content or falsely reproduce the user's current working directory.
- User choice: Local service with GitHub/Azure DevOps connectors, followed by "we already have this to some degree" and no concern for cloud hosting now.
  - Interpreted meaning: Reuse existing provider infrastructure and implement the workspace boundary locally. Preserve clean interfaces without implementing a hosted deployment.
  - Alternate plausible interpretations: Connector availability itself proves the new workspace path is qualified.
  - Confidence: High.
  - Risk if wrong: Duplicate existing systems or skip integration evidence.
- User choice: "accepted source versions are Git commits; agents work without .git."
  - Interpreted meaning: Managed snapshots own drafts/checkpoints; the designated Git ref owns accepted source versions.
  - Alternate plausible interpretations: A candidate commit alone is already accepted or merged.
  - Confidence: High.
  - Risk if wrong: Confuse creating/exporting a commit with accepting or merging it.
- User concern: Compatibility with Codex, Claude Code, or another harness.
  - Interpreted meaning: Qualify real tool behavior, guidance discovery, and Git-dependent project tooling rather than treating a mount as universal compatibility.
  - Alternate plausible interpretations: Recreate all native Git/worktree features immediately.
  - Confidence: High for the compatibility requirement; the exact supported profile is established by the bounded qualification phase.
  - Risk if wrong: Deliver a filesystem that the selected harness or build cannot actually use.

Open Loop Ledger:
- OL-001:
  - Type: scope-gap
  - Source: Local import question and committed-only answer.
  - Latent object: What bytes an import owns.
  - Why it matters: The baseline must be independent and reproducible.
  - Status: Resolved
  - Resolution evidence: Committed-only input; owned JuiceFS baseline plus retained export-critical Git object closure under DR-005.
  - Blocks: none
- OL-002:
  - Type: scope-gap
  - Source: Local/cloud delivery answer and later clarification.
  - Latent object: Deployment and provider scope.
  - Why it matters: Local connector adaptation must not become unrequested hosting infrastructure.
  - Status: Resolved
  - Resolution evidence: Local service, reuse GitHub/Azure paths, cloud hosting excluded under DR-006.
  - Blocks: none
- OL-003:
  - Type: concept-gap
  - Source: Accepted-history answer.
  - Latent object: Accepted next baseline.
  - Why it matters: Snapshots are drafts until the designated Git acceptance path advances.
  - Status: Resolved
  - Resolution evidence: DR-001 option B explicitly selected.
  - Blocks: none
- OL-004:
  - Type: acceptance-gap
  - Source: Harness compatibility concern and current structured question.
  - Latent object: Unsupported Git-native capabilities in the first version.
  - Why it matters: A fallback can reintroduce Git state or alter the supported execution boundary.
  - Status: Resolved
  - Resolution evidence: DR-007 requires read-only Git context plus measured harness/project profiles; no blanket feature loss or hidden checkout is assumed. An unmet required capability stops dependent implementation.
  - Blocks: none

Intent checksum:
- Success means:
  - An implementation can import a selected commit, survive loss of the donor, run an admitted harness in an isolated mount, seal and review the exact result, and export a correctly parented Git commit.
  - DBOS resumes the same task and external-operation identities; original result bytes and independent review survive.
  - Existing provider routes remain the integration boundary, with no new cloud hosting or implicit publication.
- Failure would look like:
  - Put queue JSON in PostgreSQL while continuing to create task worktrees.
  - Call an import durable while it still reads from the donor's directory or Git alternates.
  - Assume every harness, Git-native feature, or build works merely because ordinary file reads do.
- User confirmation needed: None for the recorded v1 intent. Host/package capabilities are explicit qualification work; live activation and publication need separately verified authority.

## Problem Definition

Problem narrative:

Agent work currently depends on local checkout paths and Git state. The user wants each task to receive an isolated, durable workspace that can be created, preserved, resumed, and reviewed without maintaining a Git worktree for every task. The selected direction uses DBOS to coordinate work, PostgreSQL for durable records, and JuiceFS to present ordinary files to agents.

Import must produce an independently retained copy of a selected committed revision. Local repositories, GitHub, and Azure DevOps supply source; they do not remain the workspace's backing directory. Agents work without `.git`. A separate Git bridge preserves the source objects needed to create reviewed candidate commits, while the designated Git acceptance path continues to define accepted source history.

Current broken workflow:
- The supervised daily lane binds work to an absolute checkout and exact Git HEAD; GitHub and Azure workers also rely on task Git worktrees.
- Source, workspace, candidate, and execution identities are currently coupled to checkout state.
- Existing provider clients and publication checks can be reused, but they do not already implement an independent baseline store or a Git-free task workspace.
- Runtime-template copying upgrades tool files; it is not project-source import.

Desired workflow:
- Register an explicit local or configured remote repository, resolve its selected revision to one commit, and capture its committed tree.
- Admit a managed baseline only after its manifest, JuiceFS contents, and export-critical Git objects are durably retained and verified.
- Clone isolated task namespaces from that immutable baseline; give the admitted harness a mounted root without `.git`.
- Preserve one task identity through prepare, authentic host-result admission, sealing, validation, independent review, export, and recovery.
- Create/export a candidate commit separately from any requested remote branch/PR publication or accepted-branch merge.
- Reuse current GitHub/Azure clients, authentication, capability checks, and publication restrictions.

Why this matters / why now:
- The user has selected the stack, committed-only input, local delivery, and Git-owned accepted history and now requests an executable implementation design.
- The primary benefit is simpler task lifecycle and resumability. Copying exact source into owned storage is the capability required to remove donor-path and per-task-worktree dependence.
- A complete end-to-end task must prove the benefit; independent storage or connector tests alone cannot.

Current-state facts:
- Fact 1: `docs/daily-development.md` freezes absolute `scheduler.execution_repo` and full Git `scheduler.base_branch`. (source: file)
- Fact 2: `templates/local-automation-runtime/atlas_supervised_handoff.py:_observe` checks checkout root and HEAD. (source: file)
- Fact 3: `templates/local-automation-runtime/atlas_work_items.py:AtlasWorkItemStore` owns JSON state, locking, and temporary-file replacement. (source: file)
- Fact 4: `templates/local-automation-runtime/atlas-agent-worker` clones/fetches a repository, adds a detached worktree, then commits/pushes from it. (source: file)
- Fact 5: `templates/local-automation-runtime/atlas_azure_worker.py` validates isolated worktree/source state; `create_only_push_command` already uses an absent-ref comparison for publication. (source: file)
- Fact 6: `templates/local-automation-runtime/atlas_azure_devops.py:AzureBoardsProvider.repository_evidence` and `AzureDevOpsClient` provide repository evidence and controlled provider operations to adapt. (source: file)
- Fact 7: `scripts/sync_runtime_template.py` preserves runtime-local config/state and copies managed template files; it is an installation mechanism. (source: file)
- Fact 8: `atlas-agent-role-codex` and the GitHub worker already pass `--skip-git-repo-check`, but other code still requires Git checkout identity. (source: file)
- Fact 9: The user selected committed-only import, local service with existing provider reuse, and Git-owned accepted history; cloud hosting is out of scope. (source: user)
- Fact 10: `atlas_approval.validate_request`, `request_identity`, `render_review` and the Azure-only `main` assume native Azure repository/issue fields. `atlas_authority.verify_grant` accepts exact typed inner bindings, but does not remove those outer request restrictions. (source: files and pure request-validation refusal)

Success criteria (measurable):
- SC1: Import a fixture commit, make its donor directory and `.git` unavailable, remove the disposable bare cache, then resume files and export a commit from managed storage alone; bytes, types, modes, and parent match.
- SC2: Local, GitHub, and Azure source adapters produce the same versioned baseline/provenance record and pin a commit before copying. A moving remote ref cannot alter an admitted baseline.
- SC3: Two task clones from one baseline contain no `.git`; writes, deletes, renames, and mode changes in either cannot alter the other or baseline. No task path invokes `git worktree add`.
- SC4: An exact harness/version/host qualification demonstrates guidance discovery, ordinary file tools, search, actual edits, validation, resume, and mount identity. Missing mounts or unsupported required features are refused before work.
- SC5: Tests and independent review bind to one sealed candidate. Later writes, stale receipts, or mismatched manifests cannot pass acceptance or export.
- SC6: Export preserves admitted binary/text bytes, executable modes, symlink targets, deletions, and rename endpoints, with the exact imported parent. Unsupported Git object formats, LFS-dependent trees, submodules, or unsafe paths receive explicit admission diagnostics.
- SC7: Failure injection around import admission, host dispatch/result capture, review waits, and publication recovers the same task and operation identities without a duplicate admitted invocation or overwrite of an existing remote branch.
- SC8: Dirty/untracked/ignored donor files are excluded and reported; donor bytes, index, refs, and config remain unchanged. Runtime/provider/storage credentials are not injected into source, prompts, or receipts; committed source is captured exactly under its admission policy.
- SC9: A local canary completes import → prepare → actual admitted host work → seal → validate/review → export. Offline fixtures are distinguished from actual-host and credentialed-provider evidence.
- SC10: Failed checks or a failed independent review can be corrected through explicit `task rework`: preserve the same task/source and failed candidate, create one isolated successor generation from that candidate, and require fresh checks/review before export. Restart/replay neither loses edits nor duplicates the successor.
- SC11: GitHub and Azure workspace publication can complete readable request → external signed response → verified import without a fabricated tracker issue. Existing schema-1 Azure request IDs, material digests, stored cards and authority checks remain compatible. Local import/rework/export keeps its private operator authority and gains no new signed-approval requirement.

Constraints:
- V1 input is committed SHA-1 Git trees; reject unsupported representations rather than silently changing bytes.
- Preserve authentic result bytes, observed host identity, independent goal review, and fail-closed recovery of uncertain invocations.
- Retain an owned baseline and self-contained Git object closure. Donor paths, object alternates, hardlinks, and remote availability are not resume dependencies after admission.
- Keep storage/provider credentials and supervisor acceptance records outside the agent's writable namespace.
- Existing pending tasks remain on their original runtime and protocol; no in-place state conversion or automatic cloud writes.

Scope:
- In scope:
  - An additive local DBOS/PostgreSQL/JuiceFS lane, committed source import, owned baselines, task mounts, sealed review, Git export, and adaptation of existing GitHub/Azure provider paths.
  - Explicit harness capability profiles and exact-host admission, recovery, inspection, installation, and rollback evidence.
- Out of scope:
  - Cloud hosting, multi-user identity, remote agents, distributed takeover, unattended execution, automatic merging, and migration of active legacy tasks.
  - Dirty/untracked input, Git-native task worktrees, bespoke filesystem/VCS, transparent support for every repository or harness, and new provider authentication platforms.

Definitions / glossary:
- Source: Selected local repository or configured remote repository and ref; resolved to one full commit OID.
- Baseline: Immutable imported tree and manifest, independently retained in JuiceFS.
- Git object closure: Self-contained retained bundle sufficient to reconstruct the baseline commit and its reachable parent history; separate from task files.
- Workspace: Isolated writable clone whose durable ID is independent of its mount path.
- Candidate: Sealed task output; its manifest binds validation/review/export.
- Publication: Requested create-only feature-branch and optional draft-PR operation; never automatic accepted-branch merge.
- Acceptance: Existing Git policy advances the designated accepted source ref. Creating a candidate commit alone is not acceptance.

Open questions:
- None for recorded import, delivery, stack, and accepted-history scope. Required package/host capabilities are resolved by the bounded qualification phase, with explicit stop conditions before dependent implementation.
- Compatibility is resolved by DR-007 and the stop-first qualification task; no package or actual-host behavior is claimed as already tested.

Decision boundaries:
- DR-001 option B is selected: Git-free workspaces, Git-owned accepted history.
- DR-005 selects committed-only independent import; DR-006 fixes local delivery and existing provider reuse.
- DR-007 preserves required Git functions through context/broker interfaces and qualification, without an implicit task checkout.

## Context Snapshot

### Inputs Provided
- Selected authoring artifact: `plans/database-backed-agent-workspaces.plan.md`.
- Source checkout: `/var/home/mat/Desktop/AtlasMemory-Tools`, baseline commit `6edb37cdcabf2af2dfcf9626916aad9b1de27acf`; the selected plan is the only observed untracked change.
- User decisions: committed-only imports; Git-free task paths; Git owns accepted history; local service; reuse existing GitHub/Azure integrations; cloud hosting excluded.
- First usable milestone: full local workflow produces a reviewed Git commit/bundle. Each live remote publication path is qualified separately.
- Compatibility concern: preserve required Git functions through declared profiles/context/broker interfaces. The user has not accepted blanket feature removal.

### System Understanding
- The daily supervised lane uses a JSON store and Git-root/HEAD-bound handoffs. General GitHub and Azure workers use task worktrees. The new lane is additive, with v2 identities; whole legacy worker loops are not its execution engine.
- Reuse current provider/auth/throttle/policy and exact grant/approval primitives. `gh_json` has default retries, so the mutation adapter must explicitly use one attempt and readback.
- Flat optional Python modules match the existing daily `*.py` snapshot convention. Template sync preserves local configuration/state; new private config/cache/evidence locations must also be preserved and excluded from publication.
- Current daily status returns selected-config/provenance input error. Installed runtime version, pending task state, account/model route, mounts and database configuration remain unobserved. No alternate installation was guessed.
- Observed host: Linux x86_64; default Python 3.14.8; Git 2.56.0. CI currently selects Python 3.12. The new service target is a separately qualified Python 3.12 environment, not the default interpreter by assumption.

### Agent roster
These are build-role bindings proposed by this plan, not claims of already installed workers or qualified model routes.
- qualification-worker: package/host capability and pin evidence; infra/runtime specialist review.
- foundation-worker: protocol, config, migrations and transactional records; data-contracts review.
- git-worker: committed import, self-contained history, deterministic export.
- workspace-worker: mounts, clone/isolation, sealing and restore; processing review.
- host-worker: harness profiles, scoped Git context, authentic handoffs.
- workflow-worker: DBOS sequencing, waits, restart and uncertain-effect reconciliation.
- integration-worker: local operator surface, existing provider/authority adaptation, installation and end-to-end evidence.
- code-reviewer: independent source review; goal-reviewer: independent complete-workflow acceptance.
- Root orchestrator: canonical plan, task sizing/admission, serial merge and evidence reconciliation.
- Existing persona references: `agents/data-contracts.md`, `agents/processing-engineer.md`, `agents/infra-engineer.md`, `agents/code-reviewer.md`, and build-phase `agents/test-engineer.md`. Persona availability is not execution-route qualification.

### Known Unknowns and Resolution Tasks
1. Exact package artifacts and storage semantics: WS1 produces locked versions and an actual-host storage capability receipt before dependent implementation.
2. Required plain/read-only-metadata behavior for a selected harness/project: WS1 prototypes deterministic capabilities; WS5 must obtain real host evidence before that profile is enabled.
3. Actual installed runtime/model/account route: B-HOST controls live model use. Current config selection error must be reconciled through its original invocation, not an alternate guessed installation.
4. Credentialed provider operation: B-PROVIDER is per provider and operation, controlling remote enablement rather than local completion.

### Dynamic Review Roster
- Triggered: zero-context, implementer readiness, expert technical, security/privacy, database/migrations, data integrity/concurrency, filesystem/harness API contracts, external-effects/governance, local cost/operations, and human readability.
- Evidence hooks: G-CAP/G-DB/G-STORAGE/G-HOST/G-RECOVERY/G-AUTH/G-PROVIDER/G-E2E/G-REPO.
- Cloud infrastructure deployment review is not triggered because hosting is excluded. Provider protocol and authority review is triggered because candidates and operations gain new v2 identities.
- UI/product-design review is not triggered: v1 is a private local service/CLI with no new web application.
- Source spot-check: current handoff `_observe`, GitHub worker clone/commit path, Azure source/create-only push, generic grant equality, approval request binding, template sync, and CI/test entrypoints were inspected. No source spot-check establishes a live mount or provider permission.
- Re-entry spot-check: a pure GitHub approval request fails the current Azure-only outer validator. An isolated Git fixture also shows replacement bytes returned by ordinary `cat-file` for an original blob OID; disabling replacement objects returns the committed bytes. These checks establish the contract gaps, not new-lane implementation. Review coverage includes the new request discriminator/legacy compatibility and failed-candidate generation transitions under G-AUTH/G-SOURCE/G-DB/G-RECOVERY/G-E2E.

## Challenge Artifacts

### Challenge Packet

#### 1) What is being built
- An owned, resumable workspace lifecycle using DBOS/PostgreSQL/JuiceFS, with Git-free agent mounts and Git-owned accepted history.
- Committed source enters through local or existing provider adapters; reviewed source leaves through a separate Git bridge.

#### 2) Concrete weaknesses
- W1: File contents can be independent while export still depends on the donor's Git objects. Admit both a verified tree and self-contained parent/object bundle; prove export after donor and disposable-cache removal.
- W2: A mount does not establish actual harness compatibility. The host may see another namespace, omit nested instructions, require Git context, or run a build that mutates sealed source. Qualify these separately and provide controlled build/cache locations.

#### 3) End-to-end failure mode
- FM1: The donor disappears; DBOS restarts while an agent still writes; another invocation starts; an incomplete tree is sealed; publication times out after creating a branch. Detect with durable operation/invocation IDs, observed writer termination, sealed manifests, and remote readback. Block uncertainty instead of treating a workflow retry as permission for another effect.

#### 4) Assumptions and tests
- A1: Selected JuiceFS/PostgreSQL versions preserve required file representation and acknowledged writes. Test binary data, executable modes, symlinks, atomic editor replacement, deletes, renames, flush, remount and restore. Any lost/changed acknowledged source fails the qualification.
- A2: Committed-only admission is independent of working state and archive attributes. Compare direct Git objects with the owned baseline, including staged/unstaged/untracked/ignored fixtures and export-ignore/export-subst attributes; donor remains unchanged.
- A3: Cloning/sealing isolates baseline, sibling and reviewed candidate. Modify both task paths and attempt stale-writer access; any alteration of another namespace fails the gate.
- A4: Recovery preserves external operation identity. Interrupt around creation, dispatch, result import, review wait, Git export and simulated publication; duplicate admitted invocations or overwritten refs fail.
- A5: A qualified harness sees required instructions, context functions and actual source. Test root/nested guidance, declared Git-dependent commands, read-only metadata where needed, out-of-scope writes and a missing/wrong mount. Documentation is insufficient.
- Status of A1–A5: Untested; assigned to named build gates, not accepted as runtime facts.

#### 5) Ranked risks
- R1 (High), foundation/workspace owners: Admission spans application, DBOS, metadata and block transactions. Stage then verify before an atomic admitted-state transition; never expose a partial baseline.
- R2 (High), workflow/host owners: DB ownership changes do not stop FUSE writers. One local worker; no takeover before actual termination and mount release are observed.
- R3 (High), Git owner and independent reviewer: Exported/published source can differ from reviewed bytes. Manifest/tree equality and exact parent/operation bindings are mandatory.
- R4 (High), provider owner: Calling an existing low-level client can bypass higher authorization layers. Reuse exact typed grant/approval verification before every effect and reconcile uncertain writes.
- R5 (Medium), host owner: Committed hooks/config are source bytes, not automatically trusted executable configuration. Explicit host-profile qualification preserves existing restrictions.
- Risk status: Mitigations are designed; live proof is pending and controls rollout.

#### 6) Alternatives considered
- Ordinary Git repositories on JuiceFS: Fewer source-check changes, but retains the task checkout coupling the user rejected.
- AgentFS: Useful fallback evidence if JuiceFS fails qualification; changing the selected stack requires a scoped amendment.
- Bespoke SQL filesystem, disliked: Adds filesystem correctness and caching work before proving lifecycle value.
- Database-owned accepted history: Unnecessary in v1 because Git authority was explicitly selected.

#### 7) Milestones and evaluation criteria
- M0: Pin dependencies and qualify real storage/harness capabilities before dependent implementation; retain failure evidence and stop on missing capabilities.
- M1: Prove source independence, two isolated task generations, sealed validation/review, restart recovery and export through a rebuilt bare cache.
- M2: Prove create-only/retry-safe publication using controlled Git remotes and existing provider fixtures. Actual credentialed-provider canaries remain separately authorized activation gates.
- Evaluation: Required correctness and scope invariants are pass/fail. Record provision/traversal/edit/freeze/restore timings and retained bytes on a fixed fixture; no deployment throughput promise is inferred.

#### 8) Decision boundary
- No new product choice. DR-001 through DR-008 define the v1 scope and explicit stop-first qualification/deferred capabilities.

## Technical Plan

### Technical Plan Intro

Add an opt-in local service that imports committed source into independently retained storage, creates isolated task mounts, and recovers their lifecycle through DBOS. PostgreSQL stores application/workflow records and the first JuiceFS metadata/block configuration. Agents use ordinary files without `.git`. A separate Git bridge supplies source history and exports frozen, reviewed candidates as correctly parented commits.

Local repositories, GitHub, and Azure DevOps enter through one source contract. Existing provider clients, authentication, grants, and publication restrictions are adapted rather than rebuilt. The first qualification phase proves storage and harness behavior before the lane is activated. Existing JSON tasks and pending handoffs stay on their original runtime/protocol; cloud hosting and distributed takeover are excluded.

### Integration Points

All `atlas_workspace_*.py` modules below are new flat modules under `templates/local-automation-runtime/`. Optional dependencies load only when the new lane is selected, so legacy commands remain usable without DBOS, PostgreSQL, or JuiceFS.

| Boundary | Proposed module | Existing source reused | Change and required refusal |
|---|---|---|---|
| Local transport | `atlas_workspace_transport.py` | Strict framing/peer identity and capability concepts | Foundation-owned real administrative/context separation; later services register handlers without changing its authority boundary |
| Typed identities | `atlas_workspace_contracts.py` | Strict JSON/canonical digest concepts in `atlas_authority.py` | Protocol v2; reject malformed types, unknown versions, duplicate keys, nonfinite values, or mismatched digests |
| Durable records | `atlas_workspace_store.py`, `atlas_workspace_migrations.py` | DBOS SQLAlchemy datasource API | Transactional row versions and operation keys; refuse schema/version mismatch |
| Import | `atlas_workspace_source.py` | Git object commands and configured repository identities | Copy selected committed tree and retained history; refuse partial admission or unsupported tree representation |
| Filesystem | `atlas_workspace_storage.py` | JuiceFS clone/mount/flush behavior | Create task generation, observe mount identity, seal/restore; refuse wrong/missing mount and unresolved writers |
| Git context/export | `atlas_workspace_git.py`, `atlas_workspace_context.py` | Bare Git object operations | Read history/context and build deterministic commit; refuse stale parent, out-of-scope paths, or tree mismatch |
| Provider/authority | `atlas_workspace_providers.py`, `atlas_workspace_authority.py` | `atlas_agent_common.py`, `atlas_azure_devops.py`, `atlas_authority.verify_grant`, `atlas_approval`, pure `create_only_push_command` | Adapt exact v2 operation bindings; refuse foreign repository/candidate/ref/runtime, revoked/expired authority, and uncertain replay |
| Host handoff | `atlas_workspace_harness.py` | Supervised packet/original-result/host-receipt conventions | Bind actual mounted root/generation and reserved role/model; refuse substitute results or unqualified routes |
| Orchestration | `atlas_workspace_workflow.py` | DBOS workflows/steps/durable messages | Advance coarse transitions; retain uncertainty rather than blindly repeat effects |
| Local operator surface | `atlas_workspace_service.py`, `atlas_workspace_cli.py` | Explicit runtime/config/owner conventions | Same-UID private Unix socket, explicit configuration, versioned requests; no automatic model launch or lane migration |
| Qualification | `atlas_workspace_qualify.py` | Repository verifier and focused tests | Emit version/host/capability evidence; missing capability stops dependent work |

### Proposed Architecture Changes

#### Dependencies and an explicit stop-first phase

Target Python 3.12, PostgreSQL 17, DBOS 3.4.0 and JuiceFS 1.3.3 for the first qualification. These are proposed dependency pins, not tested installations. WS1 resolves the exact distribution/build, transitive hash lock, JuiceFS artifact checksum, and PostgreSQL image/binary fingerprint into a maintained qualification record before dependent implementation. It must verify that the targeted release actually supports PostgreSQL metadata, PostgreSQL blocks, clone preservation, flush and remount. Failure retains evidence and requires an explicit source amendment or successor; no silent release/backend substitution.

The config records an absolute resolved `python_executable`, Python major/minor, dependency-lock digest, installed managed-file manifest digest and expected source/package digest. `WS_PYTHON` is that exact interpreter. Bootstrap, CLI, service, recovery and qualification use it consistently; G-CAP and every service startup reject interpreter, lock or managed-byte mismatch before work. A version marker alone is source provenance, not installed-file integrity.

The target DBOS release supports current SQLAlchemy datasource and registered-queue APIs. [Its package metadata](https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/3.4.0/pyproject.toml) supports Python 3.12; avoid removed `@DBOS.transaction` examples. [DBOS production guidance](https://docs.dbos.dev/production/checklist) requires direct or session-pooled PostgreSQL connections rather than transaction pooling.

Use one PostgreSQL service with four explicit logical databases: application records, DBOS system state, JuiceFS metadata, and JuiceFS blocks. Separate migration/runtime roles and supported namespaces prevent component collisions; no cross-database atomicity is assumed. Operator-supplied URLs select exact databases. Migrations are an explicit installation command; normal startup verifies the expected schema and fails if missing or incompatible. DBOS and datasource schema migration use the pinned package APIs. Application migrations are numbered and transactional with a schema-version table and migration lock; v1 supplies no destructive down migration.

JuiceFS documents [PostgreSQL metadata](https://juicefs.com/docs/community/databases_for_metadata/#postgresql) and [PostgreSQL block storage](https://juicefs.com/docs/community/reference/how_to_set_up_object_storage/#postgresql), including a `jfs_blob` table. External object storage is allowed but outside the first configuration. A different data backend requires a separately tested migration, not changing a URL under an existing volume.

#### Protocol v2 and durable model

Requests use strict JSON, `protocol_version: 2`, stable IDs, canonical SHA-256 digests for content/records, and explicit SHA-1 Git OID fields. Never treat a Git OID as the manifest digest. Record timestamps in UTC and persist generated identifiers/commit metadata before an external operation. V1 request limit is 65,536 bytes; raw role results are bounded at 2,000,000 bytes; large manifests/content use retained references rather than inline queue payloads. The example config declares admission byte/path limits; exceeding them refuses intake with observed counts.

Persist these application-owned records:

| Record | Required identity and state |
|---|---|
| Repository/source | Repository ID, kind `local|github|azure`, configured connection ID without secrets, accepted ref, resolved commit/tree OIDs, object format, source manifest digest, retained bundle digest, admission state |
| Task | Task ID, goal/acceptance criteria/write scope, source ID, runtime source/version, workflow ID, state, generation, CAS row version |
| Workspace | Workspace ID, task/generation, volume ID, storage namespace, baseline digest, mount observation, writer/invocation state |
| Invocation | Reserved role, packet digest, workspace/generation, host route/model/reasoning, observed invocation ID, terminal observation, untouched result bytes/digest and receipt |
| Candidate | Candidate ID, source/workspace generation, immutable manifest, change inventory, freeze receipt, check/review references, exported commit OID |
| Check/review | Candidate manifest digest, command/criterion, independent actor, terminal result, original evidence references |
| Operation/publication | Unique operation key, request digest, prior row version, phase/uncertainty, repository/base/candidate/target ref, exact authority digest, observed receipts |

Every mutating operation uses non-null `runtime_id`, `resource_kind`, `resource_id`, and `operation_key`, with a unique constraint on that complete tuple and a retained request digest. Kinds include service/repository/source/task/backup/restore. Before a task exists, registration uses the service/repository scope, import uses its repository scope, and backup/restore uses an explicit client-provided artifact/restore ID. A task foreign key is optional metadata, never a nullable uniqueness key. Identical retry returns the retained operation/result; changed inputs under that identity are refused. Check accepted replay before checking current row drift; a new transition separately requires the expected row version/generation. DBOS checkpoints contain IDs/digests/receipts, not source trees. Datasource transactions atomically update application rows and their tracked transaction outcome; filesystem and remote effects use staged admission/reconciliation.

Normal task states are `ADMITTED → WORKSPACE_READY → HANDOFF_PREPARED → RUNNING → WRITER_STOPPED → FROZEN → VALIDATING → REVIEW_REQUIRED → ACCEPTED_CANDIDATE → COMMIT_READY`. `ACCEPTED_CANDIDATE` means required local checks and independent review passed; it does not advance accepted Git history. A terminal failing check or independent review verdict of `fail` records its evidence and enters `REWORK_REQUIRED`. Explicit `task rework` creates a successor writable generation as specified below. `BLOCKED`, `RUNNING_UNCERTAIN`, `FAILED`, `CANCELLED`, and `PUBLICATION_UNCERTAIN` preserve attempts/evidence. Publication has its own prepared/attempted/observed lifecycle.

#### Failed checks, rejected review and explicit rework

Failed check/review imports retain the sealed candidate and original evidence. They never create another generation or dispatch a role automatically. Missing, pending or inconclusive evidence blocks acceptance; it is not a definitive failure or permission to edit a seal.

The operator invokes `task rework` with `task_id`, `expected_row_version`, `expected_generation`, `candidate_id`, `candidate_manifest_digest`, a retained `failure_evidence_id`, a bounded nonblank `reason`, and the normal stable operation identity. The service requires `REWORK_REQUIRED` and verifies that the candidate and failure belong to the current task/generation. All implementation, validation and review invocations must be terminal with writer/view release observed. Pending or uncertain invocations, writers, checks or publication block rework. Rework cannot change goal, criteria, source, write scope, independent reviewer, qualified host profile, or the remaining task budget; a required change to those needs separately authorized task intake.

Before cloning, reserve generation `n+1` and its staging namespace under the rework operation using the WS2 uniqueness/CAS contract. Clone the exact failed sealed candidate, preserving its edits, rather than resetting to the original baseline. After flush/readback verification, one CAS transaction makes the successor active, records its predecessor candidate/reason, clears active candidate/check/review/export eligibility and enters `WORKSPACE_READY`. The old candidate and every original result/receipt remain immutable historical evidence. Rework uses the same task ID and original source ID; cumulative scope validation and the next export still use the original imported baseline/parent.

Exact replay returns the retained successor even after the task advances; changed inputs under that operation are refused. Another request with stale generation/row/candidate bindings cannot reserve a second active successor. Crashes before/after clone, admission or acknowledgement reconcile the same reserved namespace/generation. The next generation requires a fresh handoff reservation, actual host observation, seal, checks and independent review. Earlier evidence remains inspectable but cannot authorize the successor.

#### Shared manifest and retained-history contract

WS2 owns a shared `ManifestV1` contract before MP2. It contains `schema_version: 1` and a list of file/symlink entries, sorted by exact UTF-8 relative path bytes. Every entry binds `path`, `kind`, `git_mode`, `size_bytes`, and raw-content SHA-256. A symlink additionally binds its exact admitted UTF-8 target and hashes that target's bytes; modes are `100644`, `100755`, or `120000` as appropriate. Encode canonical UTF-8 JSON with sorted object keys, fixed compact separators, finite integer sizes, and no incidental whitespace. Hash with the fixed domain prefix `atlas.workspace.manifest.v1` plus a newline and those canonical bytes. Preserve path case/Unicode bytes; never normalize them into another Git path.

Do not include mount path, device/inode, UID, timestamps, cache state or other non-Git attributes. Directories are structural parents; empty directories are inventoried separately in the freeze receipt as non-exported namespace metadata, not silently treated as Git source entries. A mode-only, type-only, byte, path or link-target change alters the logical source identity. An unchanged clone/remount preserves it.

A separate retained-history receipt binds repository/commit/tree OIDs, required parent closure, admitted profile-required refs/tags, object format and bundle artifact digest. Bundle pack bytes may differ without changing a tree manifest; artifact integrity and logical tree identity remain distinct. Verify the receipt by independent restore. Bind both receipts into source admission so changed or incomplete history cannot be reused as the same admitted source accidentally.

#### Committed import and source independence

Resolve the selected ref once to a complete 40-hex commit, verify its object format, then capture that commit's tree. A local repository may contain working changes; report that they are excluded, while importing the committed tree unchanged. Do not write its index, refs, config, files, or hooks.

`atlas_workspace_git.py` owns one controlled Git execution wrapper for resolution, object/tree reads, history retention, context and export. Select the intended repository explicitly, remove inherited Git routing/configuration variables, disable system/global Git configuration and use only adapter-owned transport settings. Disable replacement objects with `git --no-replace-objects`; donor inspection also disables optional index writes, filesystem-monitor helpers and lazy fetching. No command may fetch missing objects into the donor or invoke its configured executable helpers. Missing donor objects or graft files produce explicit refusal; shallow/incomplete history is refused when it cannot meet the retained parent-closure contract. Do not repair, convert or delete these donor structures. Donor replacement refs may exist but are ignored and never become authoritative imported history.

Import through `git ls-tree -rz --full-tree` and raw `git cat-file` object reads. Preserve exact admitted UTF-8 path bytes, file contents, Git executable modes and symlink targets; do not apply Unicode normalization, checkout/smudge filters, archive export-ignore/export-subst attributes, hooks, or arbitrary repository commands. Reject absolute/escaping/reserved paths, invalid UTF-8, `.git` components, unsupported Git object formats, gitlinks/submodules, required LFS content, and symlink targets escaping the admitted tree. Diagnostics name the rejected representation. These are scoped v1 admission limits, not silent data conversion.

For each captured commit/tree/blob, recompute its Git SHA-1 from object type, byte length and untouched bytes and require equality with the referenced OID. Verify the selected commit's actual tree OID and reconstruct its tree from the captured entries before admission. Dirty/untracked exclusion reporting uses the same controlled wrapper and preserves donor index, refs, config, objects and files. Independent bundle restore repeats original-object verification and recomputes the manifest from the restored tree; that manifest and tree must equal the staged baseline. A matching OID printed by a replacement-aware command is insufficient evidence. Git object identity and the manifest's SHA-256 remain distinct.

Copy source files into a private staging namespace. In a separate service-owned bare store, fetch/copy the selected commit and required reachable object/parent closure using ordinary transport with no source alternates or hardlinks. Retain any admitted reachable tags/refs required by the qualified version-tool profile. Save a self-contained Git bundle under managed storage. Restore it into an empty independent bare repository and verify the selected commit, parent closure, and tree. This cache is disposable; its retained bundle is the recovery dependency.

Only after tree/manifest/bundle storage and readback verification succeed does a transaction mark the source `ADMITTED`. Partial staging stays unadmitted and can be inspected/reconciled by the same operation key. An import receipt records source binding, resolved OIDs, content/bundle hashes, excluded-working-change summary, and version evidence. Donor deletion and cache deletion must not prevent later task creation or export.

Remote import uses the same object path after existing provider identity/auth/capability checks. A configured repository connection supplies the remote; arbitrary URLs, embedded credentials, Git URL rewrites, extension protocols, or repository-controlled credential helpers are not accepted. Credentials stay in the current server-side provider route and are redacted from errors/receipts. No issue/PR comment is used as a workflow transport.

#### Workspace creation, sealing and visibility

Use a service-owned JuiceFS volume layout with separate `sources`, `workspaces`, `candidates`, `results`, and Git-bundle namespaces. Only the assigned task generation is writable by an agent; baseline, sibling workspaces, receipts, and service controls are outside its grants. The actual host/sandbox configuration enforces the scope. Same-UID local service operation is not a hostile multi-tenant isolation claim.

For initial task creation, clone only an admitted immutable baseline. Rework clones only its explicitly bound failed sealed candidate under the rework preconditions above. Qualify the selected clone command/options for modes, links and data; a metadata-only clone of a live changing tree is not a consistent snapshot. Observe volume ID, namespace and generation from each real execution path before prepare/dispatch; a directory's existence is insufficient.

The first implementation has one workflow worker and no automatic takeover. A DB lease expiring does not stop an existing FUSE writer. Reconcile the same host invocation; replacement, freeze, and cleanup are prohibited until actual writer termination and writable-view release are observed. Uncertain terminal state becomes `RUNNING_UNCERTAIN`, not a new launch.

Before reading/hash traversal or sealing, perform an `lstat`/no-follow inventory using an explicit whitelist: structural directories, regular files with admitted executable modes, and admitted symlinks. Apply the import path/link rules to newly created outputs too. Reject FIFOs, sockets, devices, reserved `.git` paths, escaping links, hardlink aliases, and other unsupported nodes before content reads; never block on a FIFO or silently omit/reinterpret it. Refusal preserves the writable generation and diagnostics and creates no admitted candidate.

After all source writers terminate and flushing completes, clone into a service-owned candidate namespace outside every writer grant, hash/read back the manifest, and seal its record. Review uses read-only access. Validation uses a controlled execution view of the sealed source with separately declared build/cache space; source changes invalidate validation rather than silently updating the candidate. Inventory every source-tree output; `.gitignore` is not an output authorization rule. Rename checks cover old and new paths, and path scope validation uses no-follow containment rules.

#### Harness modes and Git-dependent functions

Provide five read-only context operations: `workspace.status`, `workspace.diff`, `source.log`, `source.show`, and `source.blame`. Source history is anchored to the retained source commit; workspace context names its generation and observation/candidate digest. A read of an active tree reports instability or incomplete observation when concurrent writes prevent a coherent result. Blame describes committed source, not attribution of uncommitted agent edits.

Expose context through the selected host's supported tool/CLI transport with invocation-scoped read permissions. The host adapter validates task/source/generation and operation. It never exposes raw PostgreSQL, JuiceFS or provider credentials. Context output is bounded; large/binary changes use retained digest-bound references. Commit/branch/publication are separate broker operations against frozen candidates.

Qualification covers two profiles:
- Plain-file execution: Start at the mounted source root in the harness's supported non-repository mode, with context functions and preserved project instructions. Verify required root/nested instructions, hooks/trust settings, ordinary reads/search/edits, validation, session identity, and negative probes for service config/credentials and the administrative endpoint.
- Read-only metadata compatibility, where a required project tool needs ordinary Git reads: Build a disposable metadata view outside the task root, set explicit `GIT_DIR`/`GIT_WORK_TREE`, and retain admitted history/tags. Verify required reads without writable index/config, hidden task `.git`, remote credentials, native worktree creation, or history mutation. Command-line support does not prove a harness's internal discovery uses these variables.

[Codex documents `--skip-git-repo-check`](https://learn.chatgpt.com/docs/non-interactive-mode); the existing role launcher already uses it. [Codex guidance discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md) checks only the current directory when it cannot find a project root, so root and nested guidance behavior must be qualified rather than presumed. [Claude Code documents outside-Git settings behavior](https://code.claude.com/docs/en/settings), while [native worktree mode](https://code.claude.com/docs/en/cli-reference) is a separate feature. Record the exact supported harness/version/host/project profile. No universal compatibility or user-approved feature loss is claimed.

If neither profile meets required behavior, the qualification stops and retains a scoped amendment request. It must not silently create a task checkout, replace the harness, or change model/provider route. This is a first-phase discovery outcome with an explicit stop, not an assumption left to a later coding agent.

#### Capacity admission and persistence failure

Configuration requires operator-supplied aggregate retained-byte limit, active-staging limit, and minimum free headroom for the PostgreSQL and cache/backup storage volumes; these are capacity settings, not a promised cost budget or retention period. G-CAP must validate the configured read-only accounting/headroom probes. Account for all four PostgreSQL databases plus owned local cache/backup storage; source blocks, bundles, results and staging already inside those stores must not be double-counted. Keep staging logical-byte and per-source limits separate from aggregate physical usage, and account for PostgreSQL storage/WAL headroom through the configured volume probe.

If capacity cannot be measured or headroom/limits are exceeded, stop new source/task/clone/publication admissions and show the measured scope/reason. Preserve existing work and evidence; never clear space by automatic deletion. Recheck before durable state transitions. A persistence failure must not acknowledge successful import/result/seal without durable proof. A confirmed rollback preserves the prior committed state. If commit or flush acknowledgement is lost, retain the same operation identity and staging/original-result evidence, report an uncertain outcome, and reconcile through authoritative readback after recovery before classifying it or repeating any effect. Exact replay returns an already committed outcome without another transition; a proven uncommitted operation may resume under the same identity using the caller-retained original bytes. Tests inject low-space and failed writes; no candidate/source becomes admitted and no evidence is deleted. Coordinated backup also reserves/validates its target capacity before writing.

#### Local control operations and transport

WS2 implements `atlas_workspace_transport.py` as the production framing/peer/capability boundary before MP2. WS5 registers read-only context handlers and a protected administrative probe on that same transport for its real host fixture. WS7 later registers lifecycle/provider handlers; it does not introduce a new authentication boundary. G-HOST is rerun against the complete assembled service at MP7. Testing an absent endpoint or a different mock transport never satisfies an administrative-denial probe.

The private service uses framed JSON control messages over a same-UID Unix socket under an operator-owned mode-0700 runtime directory, with socket mode 0600 and Linux peer-UID verification. Use separate administrative and context endpoints/capabilities. Agent context requests carry invocation-scoped read capability; administrative methods reject that capability even for the same UID. The agent sandbox cannot access the administrative socket/capability or service credential/config files. Do not infer administrative authority from peer UID alone; the operator-only capability/endpoint is outside the worker namespace and inherited descriptors are closed. This is an ordinary same-user boundary backed by the qualified agent sandbox, not a hostile cross-tenant security claim.

CLI methods map to fixed versioned operations: `repository register`, `source import`, `task add`, `task status`, `task rework`, `handoff prepare`, `result import`, `candidate freeze`, `check record`, `review import`, `candidate export`, `publication prepare|apply|reconcile`, `approval preview|prepare|status|export|import-response|operator-issue|reopen`, `context`, `cancel request|observe`, `backup`, and `restore`. `serve` starts an explicitly selected local worker; `migrate` performs explicit schema setup. No status/preflight command initializes a store, migrates schema, starts a model, or claims a task. Only explicit operator invocation of `approval operator-issue` may call the existing issuer bridge; service/workflow execution, preview and status never invoke it.

Every control request contains protocol version, request/operation ID, method, typed arguments and any expected row/generation/candidate version. Mutating retry with changed arguments is refused. The 65,536-byte control-frame limit excludes a separately framed original-result body: its header binds exact length and SHA-256; the server reads at most 2,000,000 untouched bytes and stores those bytes before parsing. Client file reads use bounded owned regular files without following symlinks; server-side arbitrary file paths are not a result transport. Logs omit capability values, signed envelopes, tokens, DSNs and raw provider exceptions.

`repository register` references an existing configured local/provider connection and explicit accepted ref. `source import` captures one selected commit. `task add` must name an admitted source ID, bounded goal/criteria/scope, qualified host profile and independent review role. `handoff prepare` returns a reservation, never a launch. `result import` and `review import` verify actual observations and original bytes. `candidate export` writes only a managed Git commit/bundle. `publication apply` requires the exact prepared operation and existing authority. `backup/restore` enforce quiescence and fresh targets.

`task rework` admits only the successor defined above and returns its original operation receipt on replay. Workspace `approval` commands use the same explicit runtime/config and protected administrative boundary; they load the retained exact publication request by operation ID and cannot substitute a different task, candidate or target. The operator CLI calls the shared inbox/issuer library, not the legacy Azure command entrypoint, and emits workspace commands in its previews.

A new task may explicitly select an older admitted source ID. If origin refresh is requested and unavailable, refuse refresh; never silently substitute the last retained baseline while describing it as latest.

#### Authentic supervised handoff and DBOS orchestration

The service prepares a versioned packet and waits for the supervisor's supported host to dispatch the reserved role at the actual mounted root. Preserve packet digest, task/generation, exact role/model/reasoning, actual invocation identity, terminal host observation, and original result bytes. Import validates all bindings and atomically admits exact replay; changed bytes or IDs under an accepted key are refused. Implementation and goal review remain independent.

DBOS coordinates `import → create/mount → prepare → wait for host/result → seal → validate → wait for review → export → retain/release`. Database-backed waits resume with the same task and deadline. A durable message is transport; the application still verifies actor, candidate, authority and freshness before accepting a decision. Direct model launching and new billing/auth routes are excluded. Existing standalone restrictions remain in force.

[DBOS ordinary steps have at-least-once semantics](https://docs.dbos.dev/explanations/concurrent-executions). Persist operation identity before each external effect; reconcile a previously attempted create, invocation, import, export or publication before another effect. Record actual effect before acknowledging completion. Never catch an ownership conflict and continue making effects. Single-worker restart must recover through compatible pinned workflow code; blue/green incompatible migrations are outside v1.

Result admission and DBOS notification span separate databases. Commit the authenticated result and a durable notification outbox entry together in the application transaction. Deliver a stable event/operation key through the pinned DBOS messaging API; retry delivery by identity and deduplicate consumption against the retained request digest. A crash between result commit and notification must not strand a task, and duplicate delivery must not re-admit changed bytes.

Correctable failed checks/reviews leave the same DBOS task workflow waiting for explicit rework or cancellation. Commit successor-generation admission and its stable outbox event together. Delivery/restart resumes that workflow with the reserved successor; it does not start an unrelated task, reset the deadline/budget, replay the predecessor's host invocation or dispatch another role automatically.

Cancellation enters `CANCEL_REQUESTED` first. It produces a supervisor action for the same actual invocation; terminal cancellation requires observed host termination and mount/writer release. DBOS cancellation alone does not prove a subprocess stopped. Keep reconciliation available when workflow execution is cancelled; unresolved effects retain uncertainty instead of being marked safely cancelled.

#### Git export and existing provider authority

Rebuild the disposable bare repository from retained bundles as needed. From the sealed candidate create raw Git blobs/trees and a commit with the exact imported parent. Persist author/committer, message, timestamp and tree inputs before creation so identical export replay yields the same OID. Verify resulting tree equality with the admitted candidate representation. Export to a managed bundle/commit receipt does not alter the donor or a remote.

A requested local return produces a bundle/patch for review; applying it to the donor is a separate explicit action. Remote publication creates a selected new feature branch and optionally a draft PR; it never overwrites an unrelated branch or merges into the accepted ref. Git acceptance remains the existing repository policy. A later task resolves the configured accepted ref anew instead of treating a database candidate as accepted source.

Reuse `atlas_agent_common` for GitHub auth/throttle/policy, and `AzureDevOpsClient` plus qualified pure helpers for Azure. Do not call their checkout-based worker lifecycle or inherit generic mutation retries. Mutations use one transport attempt followed by ref/PR readback. Existing matching state counts as replay only when repository, branch, operation identity and exact candidate match; a conflicting existing state blocks publication.

The new authority adapter builds typed v2 operation bindings: runtime/config/policy identity, task/source/generation, base OID, candidate manifest/commit, checks/review evidence digest, repository identity, action, target ref and expected absence, and stable operation ID. Existing `atlas_approval` request schema 1 requires a native Azure issue; generic inner grant equality does not make that outer schema provider-neutral. WS7 therefore extends the reusable library as specified below, while `atlas_authority.verify_grant` retains its existing signed envelope/actions. Verify capabilities, expiry/revocation, actor and current bindings immediately before every effect. The adapter must not fabricate an Azure issue or v1 checkout packet, or bypass higher approval layers by calling a raw client. Foreign or stale grants fail before network mutation.

#### Backward-compatible workspace approval requests

Extend `atlas_approval.validate_request`, `request_identity`, `render_review` and the common `ApprovalInbox` paths with an explicit workspace request variant. Schema-1 Azure validation, canonical request/material digests, request IDs, rendering, stored cards and pending responses retain their existing behavior. The existing Azure-only `main` explicitly rejects schema 2 before indexing Azure fields and continues emitting its existing commands; workspace requests use `atlas_workspace_cli.py` instead.

A workspace readable request has `schema_version: 2` and exactly these required fields: `schema_version`, `subject`, `action`, `owner`, `question`, `artifact_sha256`, `policy_sha256`, `bindings`. Optional fields are `step_id`, `details`, `artifact_path`, with the existing bounded text/digest rules and logical-step default. Its `subject` contains exactly `kind: "workspace_operation"`, `runtime_id`, `task_id`, `repository_id`, `repository_kind` (`github|azure`) and `operation_id`. IDs are nonblank bounded identifiers. Reject unknown/mixed schema fields, including schema-1 `issue_id`, `issue_revision` or `repository_url` fields on a schema-2 request. `bindings.approval_subject` must exactly equal `subject`; all other typed operation bindings must match the currently registered runtime/repository/task/source/generation/candidate and prepared publication. No fabricated tracker identity is used.

Schema-2 requests in this lane support the existing `draft_pr` signed action for the exact branch-create or draft-PR-create operation distinguished in the bindings. Other request-action mappings are refused. This adds no merge, Board-write, model-dispatch or local import/rework/export approval requirement. Local operations retain their existing private operator boundary. A local repository is not a remote publication target; refuse a local target rather than inventing a remote provider identity.

For schema 2, request identity hashes a canonical object containing `schema_version`, the complete `subject`, `action` and logical `step_id`; material digest covers the complete validated request. Different provider/repository/task/operation subjects cannot collide with each other or schema-1 identity. A changed candidate, target, owner or other material input requires a new publication operation ID and readable request, regardless of the previous operation's phase. Never change the retained request under an existing operation identity. Explicit `reopen` applies only to unchanged material after issuer-attempt/response reconciliation and retains the existing renewal/signature checks; it is not a material-edit route. Prior responses cannot authorize the new operation. Rendering identifies the actual provider/repository, task, candidate and requested effect, without an invented Azure issue.

Common card/export/response, signed-grant and trust-registry envelopes keep their existing versions; their embedded readable request may be schema 2. Reuse existing prepare/export/import/reopen/response lookup and protected issuer invocation, including signed rejection/feedback through the existing `human_gate` response action. Signature, issuer/owner, runtime, policy, action, validity/revocation and complete typed binding verification remain unchanged. No issuer enrollment, key, cryptographic format or authority is introduced. A real issuer that cannot display and approve the complete schema-2 subject leaves that provider path unqualified; it is not a reason to downgrade the request or bypass readable approval. G-PROVIDER-LIVE includes this issuer compatibility, separately from local completion.

### Failure Modes (per integration point)

- Wrong/missing mount or changed source: Refuse prepare/dispatch; retain diagnostics.
- Partial import/clone/freeze: Preserve staging and operation record; never mark it admitted/sealed until durable readback succeeds.
- Uncertain writer or dispatch: Keep reservation/generation; no takeover, freeze, or cleanup until terminal observation.
- Stale evidence or review: Reject candidate/generation/digest mismatch; require a new freeze/check/review for changed source.
- Failed check or rejected review: Retain the candidate/failure in REWORK_REQUIRED; only explicit replay-safe rework creates a successor generation. Pending/inconclusive evidence remains blocked.
- Stale or competing rework: Refuse wrong candidate/generation/CAS inputs; reconcile the reserved successor and preserve all predecessor evidence.
- Source-object/export mismatch: Block commit readiness; retain object/manifest comparison.
- Replacement/configuration-dependent source: Ignore replacements through controlled reads; refuse inconsistent object bytes, grafts or incomplete history without changing the donor.
- Remote timeout: Enter publication uncertainty; inspect the existing ref/PR without blanket mutation replay.
- Revoked/foreign authority or unavailable provider: Refuse effect; local workspace remains recoverable.
- Unsupported readable request or issuer: Refuse mixed schemas, subject/binding mismatch or unqualified schema-2 issuer behavior before provider mutation; retain legacy Azure request handling.
- Migration/version mismatch: Stop the new service; do not alter legacy task state or downgrade schema in place.
- Unsupported harness/project: Stop at capability admission with the exact failed behavior and profile; no hidden Git checkout.

### Invariants / Non-Changes

- No per-task `.git` or worktree is created. Transient mounts, context transport files, and disposable bare caches are allowed outside the task namespace.
- Legacy queues, active tasks, v1 packets, operator configuration, trust material, credentials and existing runtime snapshots are preserved.
- Rework preserves the task, source parent and remaining authority/budget. It never edits an old seal or treats predecessor evidence as successor acceptance.
- Workspace approval requests preserve schema-1 identities/cards/responses and existing signed-envelope/trust verification; a new readable request grants no authority by itself.
- No automatic model dispatch, accepted-branch merge, cloud hosting, multi-user delivery or distributed takeover.
- A shared PostgreSQL service is not a transaction across all filesystem/remote effects.
- This document specifies future source implementation and checks; no service, mount, migration, host invocation, or publication was run during planning.

### NFRs alignment

- Integrity: Independent source/tree/history retention, staged admission, sealed manifests, CAS state, exact typed authority and original-byte retention.
- Performance: Record creation/traversal/edit/freeze/export/restore time and retained bytes for fixed fixtures; expose admission limits and stop on exceeded bounds. No unmeasured deployment throughput promise.
- Security: Private same-UID socket/config; qualified sandbox write roots; restricted context operations; credentials and control state outside task grants; import copies source without automatically trusting hooks/config.
- Operability: Status reports source/task/generation, lifecycle, mount, pending role/invocation, candidate and next action. Uncertainty is visible and never automatically cleared by age.
- Recovery: Coordinated backup/restore of application/workflow/metadata/block databases and retained Git bundles; cache absence is harmless after restore. Preserve old runtime for rollback and require explicit new-task lane selection.

## Implementation Plan

Implement an additive local lane for new tasks. PostgreSQL/DBOS is its task-state authority; retained transport files are derived. Existing JSON tasks and v1 handoffs stay on their original runtime. The first usable milestone is a reviewed local Git commit/bundle; each live provider and harness profile is enabled only after its own qualification.

### Agent roster
Use the explicit role bindings in Context Snapshot. Root merges serially; an implementation owner cannot accept its own code or goal result. No concurrent editing is required. Existing specialist personas provide review capabilities, not automatic deployed staffing.

Model sizing is task-bound: Luna is the default for clear bounded adapters/docs. Coupled contract/migration, Git fidelity, storage recovery, and DBOS work justify Sol or Terra only through an independent sizing review of that item's exact source/spec/complexity. Every admitted item records actual model/reasoning policy and budget; unavailable routing blocks dispatch. Do not infer that a stronger model resolves a missing objective or expands scope.

### File Deltas (exhaustive) + rationale
Each row names exactly one owner until its merge point. New module interfaces are the contracts in Technical Plan, not existing functions. The selected plan remains the orchestrator's authoring surface rather than a build-owned file.

- `templates/local-automation-runtime/atlas_workspace_qualify.py` - create - WS1 - bootstrap capability runner and later gate dispatcher with explicit pending/fail/pass outcomes.
- `scripts/install_workspace_runtime.py` - create - WS1 - stdlib bootstrap installer reading the exact committed source package into an absent runtime target.
- `tests/test_workspace_runtime_bootstrap.py` - create - WS1 - complete tracked runtime-package copy, source/interpreter binding, and missing/stale reused-helper, live-suite, fixture and lock refusals.
- `templates/local-automation-runtime/requirements-workspace.in` - create - WS1 - optional direct dependency targets.
- `templates/local-automation-runtime/requirements-workspace.lock` - create - WS1 - exact hashed Python dependency artifacts for the qualified environment.
- `templates/local-automation-runtime/config/workspace-artifacts.lock.json` - create - WS1 - JuiceFS/PostgreSQL artifact fingerprints and checksums.
- `templates/local-automation-runtime/config/workspace.example.json` - create - WS1 - non-secret explicit runtime/URL references and bounded admission defaults.
- `docs/workspace-source-pins.md` - create - WS1 - qualified versions, provenance, failed capabilities and supported host limits.
- `templates/local-automation-runtime/atlas_workspace_contracts.py` - create - WS2 - strict versioned records, rework request/state/predecessor identities and workspace approval-subject bindings.
- `templates/local-automation-runtime/atlas_workspace_config.py` - create - WS2 - explicit config/runtime/owner selection and lazy optional dependencies.
- `templates/local-automation-runtime/atlas_workspace_transport.py` - create - WS2 - real framing, UID and admin/context capability boundary needed before WS5 host qualification.
- `templates/local-automation-runtime/tests/test_atlas_workspace_transport.py` - create - WS2 - frame bounds, exact replay and admin/context separation before later handler assembly.
- `templates/local-automation-runtime/atlas_workspace_migrations.py` - create - WS2 - numbered application migrations and compatibility refusal.
- `templates/local-automation-runtime/atlas_workspace_store.py` - create - WS2 - transactional state, operation replay, CAS versions and one reserved successor generation per rework operation.
- `templates/local-automation-runtime/tests/test_atlas_workspace_contracts.py` - create - WS2 - parsing, identity, limits and compatibility refusals.
- `templates/local-automation-runtime/tests/test_atlas_workspace_store.py` - create - WS2 - transaction/replay/conflict cases, competing rework and lost successor-admission acknowledgement.
- `templates/local-automation-runtime/atlas_workspace_source.py` - create - WS3 - original committed object admission using controlled Git execution without donor writes or lazy fetching.
- `templates/local-automation-runtime/atlas_workspace_git.py` - create - WS3 - shared controlled object reads and type/size/OID verification, retained Git closure, context primitives and deterministic export.
- `templates/local-automation-runtime/tests/test_atlas_workspace_source.py` - create - WS3 - replacement refs, ambient Git configuration, missing objects, dirty-source exclusion and donor preservation.
- `templates/local-automation-runtime/tests/test_atlas_workspace_git.py` - create - WS3 - original-object hash checks, independent bundle/manifest comparison, exact parent and deterministic candidate tree.
- `templates/local-automation-runtime/atlas_workspace_storage.py` - create - WS4 - mount identity, clone, flush, seal/release and isolated rework cloning from the bound failed candidate.
- `templates/local-automation-runtime/tests/test_atlas_workspace_storage.py` - create - WS4 - adapter refusals, rework clone isolation and incomplete operation recovery.
- `templates/local-automation-runtime/tests/workspace_live/test_workspace_storage.py` - create - WS4 - actual PostgreSQL/JuiceFS isolation and remount tests.
- `templates/local-automation-runtime/atlas_workspace_harness.py` - create - WS5 - qualified host profiles, scoped context transport and authentic result admission.
- `templates/local-automation-runtime/atlas_workspace_context.py` - create - WS5 - invocation-scoped status/diff/log/show/blame functions.
- `templates/local-automation-runtime/config/workspace-harnesses.example.json` - create - WS5 - versioned explicit capabilities and host profile records.
- `templates/local-automation-runtime/tests/test_atlas_workspace_harness.py` - create - WS5 - receipt/generation/route/guidance/profile refusal.
- `templates/local-automation-runtime/tests/test_atlas_workspace_context.py` - create - WS5 - read-only operation scope, stable observations and credential exclusion.
- `templates/local-automation-runtime/atlas_workspace_workflow.py` - create - WS6 - DBOS lifecycle, explicit failed-candidate rework, waits, notification recovery and cancellation observation.
- `templates/local-automation-runtime/tests/test_atlas_workspace_workflow.py` - create - WS6 - failed-check/review rework, retained predecessor evidence, fresh reservations, replay and uncertainty cases.
- `templates/local-automation-runtime/tests/workspace_live/test_workspace_recovery.py` - create - WS6 - real DBOS/PostgreSQL restart, effect/checkpoint failures and one rework successor across reservation/clone/admission crashes.
- `templates/local-automation-runtime/atlas_workspace_authority.py` - create - WS7 - construct schema-2 workspace approval requests from exact v2 operation bindings and use existing grant verification.
- `templates/local-automation-runtime/atlas_approval.py` - modify - WS7 - extend reusable validation/identity/rendering/inbox paths for workspace request schema 2 while preserving schema-1 Azure bytes/identities/cards and explicitly keeping the existing Azure CLI schema-1-only.
- `templates/local-automation-runtime/tests/test_atlas_approval.py` - modify - WS7 - full workspace request/response lifecycle, request discrimination, signed replay/supersession and unchanged legacy Azure request/CLI behavior.
- `templates/local-automation-runtime/atlas_workspace_providers.py` - create - WS7 - adapters around existing provider identity/auth/client paths.
- `templates/local-automation-runtime/atlas_workspace_service.py` - create - WS7 - private local service, explicit rework preconditions and workspace approval operations over the administrative transport.
- `templates/local-automation-runtime/atlas_workspace_cli.py` - create - WS7 - explicit rework/approval commands and reviewable operation previews without the Azure-only CLI route.
- `templates/local-automation-runtime/tests/test_atlas_workspace_authority.py` - create - WS7 - real signed GitHub/Azure workspace subjects without fabricated issue IDs, local-target refusal, expiry/revocation and foreign-subject refusal.
- `templates/local-automation-runtime/tests/test_atlas_workspace_providers.py` - create - WS7 - create-only publication, one-attempt/readback and uncertain outcomes.
- `templates/local-automation-runtime/tests/test_atlas_workspace_service.py` - create - WS7 - private transport, rework/approval bounds and replay, operator-only issuer entry and invocation-scoped context.
- `templates/local-automation-runtime/atlas_workspace_canary.py` - create - WS8 - resumable canary preparation and retained original-evidence verification.
- `templates/local-automation-runtime/tests/workspace_live/test_workspace_canary.py` - create - WS8 - integrated source/storage, failed-candidate rework with fresh review/export, and backup/restore cases.
- `tests/test_workspace_runtime_copy_boundaries.py` - create - WS8 - installed copy, disabled default and preservation regression.
- `scripts/verify_repo.py` - modify - WS8 - include new static and deterministic checks while preserving generated-adapter checks.
- `scripts/sync_runtime_template.py` - modify - WS8 - preserve new private config/cache/evidence locations during sync.
- `.github/workflows/verify.yml` - modify - WS8 - install qualified optional dependencies and run deterministic checks without live credentials/mounts.
- `templates/local-automation-runtime/check_runtime.sh` - modify - WS8 - read-only workspace readiness only when explicitly configured.
- `templates/local-automation-runtime/config.env.example` - modify - WS8 - disabled-by-default workspace config reference.
- `templates/local-automation-runtime/README.md` - modify - WS8 - new lane/protocol boundary and optional dependency setup.
- `docs/daily-development.md` - modify - WS8 - distinguish legacy pending work from explicitly selected new-lane tasks.
- `docs/database-workspace-runtime.md` - create - WS8 - installation, explicit rework/approval operations, evidence, unchanged legacy Azure route, coordinated backup/restore and rollback.
- `AGENTS.md` - modify - WS8 - document the qualified opt-in v2 lane and preserve legacy pending-work rules.
- `docs/local-harness-operating-instruction.md` - modify - WS8 - distinguish new-task lane selection from original runtime recovery and authority.
- `templates/local-automation-runtime/AGENTS.md` - modify - WS8 - describe installed workspace operation boundaries without widening dispatch or merge authority.

### Workstreams + merge points

- WS1: Dependency and capability qualification
  - Owner: qualification-worker.
  - Agent type: explore.
  - Delegate: required.
  - Depends on: none.
  - Intended behavior change: replace storage/profile assumptions with pinned artifacts and actual-host capability evidence before larger integration.
  - Owns files: all WS1 File Deltas; keep `atlas_workspace_qualify.py` as a thin dispatcher, with gate case implementations owned by the downstream modules/tests that supply them.
  - Review gates: G-CAP.
  - Bootstrap contract: WS1 uses its installer on a committed candidate source pin, reading every tracked file under `templates/local-automation-runtime/` at that pin and preserving its relative path. This complete managed package includes reused core/helper modules (`atlas_agent_common`, `atlas_azure_devops`, `atlas_authority`, `atlas_approval` and their runtime dependencies), workspace modules, all test/live-suite files and fixtures, dependency locks, scripts and examples present at that phase. Exclude untracked files and private operator state; the installed runtime must not import modules or read tests from the source checkout. Install to an absent private directory, record actual managed-file hashes and exact source/interpreter/lock identity, then run capabilities there. Later source phases install fresh directories from their updated committed pins. WS8 extends preservation/upgrade coverage; it does not supply the bootstrap needed by WS1.
  - Merge point: MP1; locks and substrate receipt. The bootstrap `capabilities` case must be self-contained, not depend on unimplemented WS2–WS7 modules. Harness mode prototypes are deterministic tool/profile checks here; actual host admission is G-HOST at WS5.
- WS2: Contracts and transactional state
  - Owner: foundation-worker.
  - Agent type: generalPurpose.
  - Delegate: required.
  - Depends on: WS1.
  - Intended behavior change: strict config/schema, production local capability transport, and source/task/workspace/invocation/candidate/check/review/publication records with non-null resource-scoped operations, original result storage and CAS. Freeze the rework request/state, predecessor bindings and successor reservation contract before consumers.
  - Owns files: all WS2 File Deltas.
  - Review gates: G-UNIT, G-DB.
  - Merge point: MP2; freeze public record/adapter interfaces before consumer merges.
- WS3: Committed source and Git bridge
  - Owner: git-worker.
  - Agent type: generalPurpose.
  - Delegate: required.
  - Depends on: WS2.
  - Intended behavior change: original-object source admission and deterministic candidate export independent of donor/cache/task Git state. Controlled Git execution and per-object OID checks prevent replacement refs or ambient settings from changing captured content.
  - Owns files: all WS3 File Deltas.
  - Review gates: G-UNIT, G-SOURCE.
  - Merge point: MP3 with WS4; restore history from managed bundle and compare candidate tree/parent.
- WS4: Mounted storage and sealing
  - Owner: workspace-worker.
  - Agent type: generalPurpose.
  - Delegate: required.
  - Depends on: WS2.
  - Intended behavior change: mounted task generations, sibling/baseline isolation, durable flush and immutable candidate handling. Supply a rework clone primitive from the exact failed sealed candidate before WS6 consumes it.
  - Owns files: all WS4 File Deltas.
  - Review gates: G-UNIT, G-STORAGE.
  - Merge point: MP3 with WS3; qualify the PostgreSQL metadata/block configuration and release-without-deletion.
- WS5: Harness profiles and Git context
  - Owner: host-worker.
  - Agent type: generalPurpose.
  - Delegate: required.
  - Depends on: WS3, WS4.
  - Intended behavior change: invocation-scoped Git context plus authentic host/result binding for qualified Git-free execution; implement read-only external metadata only where measured requirements justify it.
  - Owns files: all WS5 File Deltas.
  - Review gates: G-UNIT, G-HOST.
  - Merge point: MP4; one actual qualified profile must meet the WS5 feature fixture using the real WS2 transport and WS5 context/protected-admin handlers before lifecycle work is enabled. WS7 depends on this existing boundary rather than supplying it; MP7 reruns the same gate against its fully assembled service. Other profiles remain explicitly unqualified, not silently substituted.
- WS6: DBOS lifecycle and recovery
  - Owner: workflow-worker.
  - Agent type: generalPurpose.
  - Delegate: required.
  - Depends on: WS3, WS4, WS5.
  - Intended behavior change: new-task durable transitions/waits with unchanged-input replay, explicit same-task rework, operation reconciliation and observed cancellation. Failed checks/reviews wait in REWORK_REQUIRED; an explicit rework request creates one successor generation and fresh reservations without launching a role.
  - Owns files: all WS6 File Deltas.
  - Review gates: G-UNIT, G-RECOVERY.
  - Merge point: MP5; recover the same task/role/invocation. No second writer after a lease timeout.
- WS7: Local service, providers and exact authority
  - Owner: integration-worker.
  - Agent type: generalPurpose.
  - Delegate: required.
  - Depends on: WS6.
  - Intended behavior change: expose explicit local/rework operations and adapt existing provider routes to v2 source/candidate/ref identities with existing grant verification. Extend the shared approval library for schema-2 workspace subjects and expose their complete operator route while preserving the legacy Azure CLI.
  - Owns files: all WS7 File Deltas.
  - Review gates: G-UNIT, G-AUTH, G-PROVIDER.
  - Merge point: MP6; complete request/preview/export/signed-response/import verification for workspace subjects and unchanged schema-1 Azure behavior. No raw-client bypass, fabricated Azure issue or legacy checkout packet. Live provider use remains gated per operation.
- WS8: Installation and complete local evidence
  - Owner: integration-worker.
  - Agent type: generalPurpose.
  - Delegate: required.
  - Depends on: WS7.
  - Intended behavior change: install a disabled-by-default version alongside legacy state and complete one local import-to-export task including a failed candidate, explicit rework, fresh independent acceptance, backup/restore and rollback.
  - Owns files: all WS8 File Deltas.
  - Review gates: G-REPO, G-E2E, G-HOST; G-PROVIDER-LIVE only for each separately enabled provider.
  - Merge point: MP7; independent code/goal review accepts local evidence. An unqualified remote path does not block local completion and cannot be enabled by it.

### Delegation Quality Gate
- DQ-1: Pass — eight bounded streams map intended behavior to disjoint file rows, dependencies and serial merge points.
- DQ-2: Pass — unknown storage/artifact behavior is assigned to WS1; actual host admission to WS5. Failure has a named stop rather than an implicit backend/harness replacement.
- DQ-3: Pass — implementation, code review and goal acceptance are independent; shared files stay with their single owner until the declared merge.
- DQ-4: Pass — commands, original evidence, operational blockers, activation and rollback distinguish build completion from installed/live qualification.
These are authoring-quality checks, not assertions that build/runtime checks have run.

### Phases + tasks + exit criteria

#### Phase 1: Qualify a local substrate
- Owner(s): qualification-worker; independent infra/runtime reviewer.
- Depends on: none.
- Tasks (by owner): qualification-worker creates isolated locks/config and bootstrap capability runner. Run `"$WS_PYTHON" -B scripts/install_workspace_runtime.py --source-revision "$WORKSPACE_SOURCE_SHA" --target "$RUNTIME" --python "$WS_PYTHON"` against a committed candidate that contains WS1 files; then verify PostgreSQL/JuiceFS, file semantics and deterministic Git-context/metadata prototypes.
- Exit criteria (evidence): pinned artifact/host receipt and concrete supported behavior. A missing substrate capability stops later phases; no silent version or backend substitution.
- Gates (named): G-CAP.

#### Phase 2: Retain source and isolate tasks
- Owner(s): foundation-worker, git-worker, workspace-worker.
- Depends on: Phase 1.
- Tasks (by owner): WS2 defines state/interfaces; WS3 captures source/history and export; WS4 mounts/clones/seals; root integrates serially.
- Exit criteria (evidence): donor/cache removal does not break source or export; replacement refs and ambient Git settings do not change original object capture; donor index/refs/config/files remain unchanged. Two task trees and sealed candidate remain independent; rework clone isolation and database replay/conflict behavior are correct.
- Gates (named): G-UNIT, G-DB, G-SOURCE, G-STORAGE.

#### Phase 3: Bind a real harness and recover work
- Owner(s): host-worker, workflow-worker.
- Depends on: Phase 2.
- Tasks (by owner): WS5 qualifies the actual host/project profile after B-HOST clears; WS6 integrates DBOS recovery and durable review waits.
- Exit criteria (evidence): actual tool/guidance/context results and original receipts match the mounted generation; restart/cancel/notification failures preserve one task and external effect identity. Definitive failed checks and failed reviews each reach REWORK_REQUIRED, and explicit rework/restart yields one successor preserving edits while refusing predecessor evidence.
- Gates (named): G-HOST, G-RECOVERY.

#### Phase 4: Adapt operator/provider boundaries
- Owner(s): integration-worker; independent security/contracts reviewer.
- Depends on: Phase 3.
- Tasks (by owner): WS7 supplies local CLI/service and existing provider/authority adapters; test crypto refusals and simulated uncertainty before remote use.
- Exit criteria (evidence): GitHub/Azure workspace subjects complete readable request/export/signed-response/import without tracker-issue fabrication; local operations gain no approval requirement, and schema-1 Azure identities/cards and supervisor behavior remain compatible. Foreign/stale/revoked grants fail before network mutation; one-attempt/readback resolves exact replay or reports a conflict.
- Gates (named): G-UNIT, G-AUTH, G-PROVIDER.

#### Phase 5: Complete the local workflow
- Owner(s): integration-worker, code-reviewer, goal-reviewer, root.
- Depends on: Phase 4.
- Tasks (by owner): WS8 installs a new pinned version, preserves old state, completes an actual local canary, performs coordinated backup/restore and demonstrates rollback. Provider enablement is separate.
- Exit criteria (evidence): one persistent task retains a failed candidate, explicitly reworks its edits in a successor generation through actual host work, and reaches a reviewed local Git commit/bundle using fresh checks/review. Source/tree/lineage/export/restore receipts agree; no donor or old-lane mutation. This exercises the first usable milestone selected by the user.
- Gates (named): G-REPO, G-E2E, G-HOST.

### Review gates (named + definitions)

`WS_PYTHON`, `RUNTIME`, `WORKSPACE_CONFIG`, and `EVIDENCE` are explicit absolute operator/test-fixture values, never guessed installations. `WORKSPACE_SOURCE_SHA` is the complete committed candidate source SHA that contains the files being installed. `WS_PYTHON` is the resolved qualified interpreter, not whichever `python3` happens to be on PATH. In CI it is the Python 3.12 interpreter selected by setup; local service commands must match the configured interpreter/lock/installed-byte manifest. `HARNESS_PROFILE` names an admitted version/host profile; `PROVIDER` names a configured connection; `OPERATION_RECEIPT` is actual authorized provider evidence; `CANARY_TASK` is the persistent canary ID. Live commands run only from an installed temporary or selected runtime, never the source template. Test-only fixtures may construct isolated copies. Gate tools return 0 only for terminal pass, 1 for failed checks, 2 for invalid/missing prerequisites, and 3 for pending supervised evidence; pending/skipped is not green.

- G-CAP:
  - Where it runs: Local.
  - Entry point / command: `"$WS_PYTHON" -B "$RUNTIME/atlas_workspace_qualify.py" --config "$WORKSPACE_CONFIG" capabilities --output "$EVIDENCE/capabilities.json"`.
  - Green means: exact Python/DBOS/PostgreSQL/JuiceFS artifacts, pooling/migration compatibility, actual mount, byte/mode/link/editor-replacement/clone/flush/remount cases and deterministic Git-context prototype pass. Configured aggregate/staging accounting and storage-headroom probes, exact interpreter/lock/managed-file binding, and low-space admission refusal must also pass. No model launch is implicit; actual harness admission is G-HOST.
- G-UNIT:
  - Where it runs: CI and Local.
  - Entry point / command: `"$WS_PYTHON" -B -m unittest discover -s templates/local-automation-runtime/tests -p 'test_atlas_workspace_*.py'` after installing the qualified optional lock.
  - Green means: meaningful schema/replay/scope/receipt/provider/authority refusal tests pass without live credentials, mounts or model calls, including strict rework/predecessor bindings and failed-check/failed-review transitions. Inject canary tokens, capabilities, signed envelopes, DSNs and provider exceptions into successful/failing operations; captured logs/errors/context/receipts must omit those secret values. Preserve original private role-result bytes unchanged rather than redacting them. CI treats required skipped workspace tests as failure. Legacy import/commands also work without the optional dependencies.
- G-DB:
  - Where it runs: Local.
  - Entry point / command: `"$WS_PYTHON" -B "$RUNTIME/atlas_workspace_qualify.py" --config "$WORKSPACE_CONFIG" database --output "$EVIDENCE/database.json"`.
  - Green means: fresh and repeated migrations, incompatible-schema refusal, concurrent CAS conflicts, non-null resource-scoped replay for both task and taskless register/import/backup/restore, changed-input refusal, interrupted staging convergence, confirmed transaction rollback and connection loss after server commit but before acknowledgement pass on actual PostgreSQL. Competing rework requests and lost successor-admission acknowledgement converge on one reserved active successor. Authoritative reconciliation must classify the same operation correctly, retain one result with unchanged original bytes, and prevent duplicate admission or notification effects.
- G-SOURCE:
  - Where it runs: Local; deterministic object cases also run in CI through G-UNIT.
  - Entry point / command: `"$WS_PYTHON" -B "$RUNTIME/atlas_workspace_qualify.py" --config "$WORKSPACE_CONFIG" source-independence --output "$EVIDENCE/source.json"`.
  - Green means: committed-tree and archive-attribute fixtures, dirty exclusion, donor immutability, donor/cache absence, restored self-contained bundle, exact parent/tree and deterministic export all pass. Replacement blob/tree/commit refs cannot change original captured bytes; inherited Git routing/configuration and donor helper sentinels cannot redirect reads or execute helpers. Graft and missing-promisor-object fixtures fail without repairing or lazy-fetching into the donor. Every captured object's type/size/bytes reproduce its OID; the independently restored tree reproduces the staged manifest. Donor index/refs/config/objects/files are unchanged. Mode-only, type-only, link-target, path and retained-closure changes alter the appropriate identities or are refused; unchanged clone/remount identity is stable.
- G-STORAGE:
  - Where it runs: Local.
  - Entry point / command: `ATLAS_WORKSPACE_TEST_CONFIG="$WORKSPACE_CONFIG" "$WS_PYTHON" -B -m unittest discover -s "$RUNTIME/tests/workspace_live" -p test_workspace_storage.py`.
  - Green means: actual mount identity, clone fidelity, baseline/sibling/seal exclusion, acknowledged-write recovery, incomplete freeze and missing-mount refusals pass. Rework clones the exact failed sealed candidate with its edits, leaves its bytes/receipts unchanged and isolates the successor; interrupted clones or unresolved writers admit no successor. New FIFO/socket/device/reserved-path/escaping-link/hardlink-alias fixtures are refused before content reads/sealing, with diagnostics and writable generation retained; no hung reads or silent exclusion.
- G-HOST:
  - Where it runs: Local, per exact profile.
  - Entry point / command: `"$WS_PYTHON" -B "$RUNTIME/atlas_workspace_qualify.py" --config "$WORKSPACE_CONFIG" harness --profile "$HARNESS_PROFILE" --output "$EVIDENCE/harness.json"`.
  - Green means: supervisor supplies actual dispatch/terminal/result observations for the same mount; real editing/search/shell, root/nested guidance, required Git context/version tooling, write-scope probes, and denied reads/access to service secrets/admin capability pass. The command prepares/validates evidence and may return pending; it never silently launches a model. Synthetic results cannot satisfy this gate.
- G-RECOVERY:
  - Where it runs: Local.
  - Entry point / command: `ATLAS_WORKSPACE_TEST_CONFIG="$WORKSPACE_CONFIG" "$WS_PYTHON" -B -m unittest discover -s "$RUNTIME/tests/workspace_live" -p test_workspace_recovery.py`.
  - Green means: real DBOS/PostgreSQL process restarts preserve task/generation, review waits/deadlines, consumed-message/import replay, cancellation observation and operation identity across effect/checkpoint failures, including committed transactions whose acknowledgement is lost. Failed-check and failed-review rework cases restart before/after successor reservation, clone completion, admission and outbox delivery; exact replay returns one successor under the same task/workflow and changed-input/predecessor-evidence reuse is refused. Budget/deadline and original failure bytes remain unchanged; no automatic dispatch follows recovery. Deterministic worker stand-ins test failure paths; actual host proof remains G-HOST.
- G-AUTH:
  - Where it runs: CI and Local.
  - Entry point / command: run `"$WS_PYTHON" -B -m unittest discover -s templates/local-automation-runtime/tests -p test_atlas_workspace_authority.py`, `"$WS_PYTHON" -B -m unittest discover -s templates/local-automation-runtime/tests -p test_atlas_approval.py`, and `"$WS_PYTHON" -B -m unittest discover -s templates/local-automation-runtime/tests -p 'test_azure_supervisor*.py'`.
  - Green means: schema-2 GitHub/Azure task subjects complete preview/prepare/export/existing signed-response import and exact effect-binding checks without fabricated tracker IDs. Unknown/mixed schemas, local publication targets, subject/binding/provider/task/operation mismatches, foreign runtime/repository/ref/candidate, changed bytes, expiry and revocation fail before provider access. Schema-1 Azure IDs, canonical material digests, cards, pending responses, renderer and CLI/supervisor behavior remain compatible; Azure CLI refuses schema 2 before indexing legacy fields or contacting an issuer. Existing signed rejection/feedback, supersession, replay, protected issuer and signature/trust verification remain enforced. No new cryptographic format/key flow or local-export approval is introduced; an unsupported real issuer blocks its provider path rather than downgrading the request.
- G-PROVIDER:
  - Where it runs: CI and Local.
  - Entry point / command: `"$WS_PYTHON" -B -m unittest discover -s templates/local-automation-runtime/tests -p test_atlas_workspace_providers.py`.
  - Green means: adapters use existing identity/auth/capability clients; controlled Git remotes and provider fixtures prove create-only ref, candidate readback, single-attempt mutation, existing/conflicting branch and ambiguous PR behavior. Capture success/failure logs, errors and receipts under canary credentials/DSNs/approval envelopes and assert redaction without changing privately retained original result bytes. No fixture result proves live permission.
- G-PROVIDER-LIVE:
  - Where it runs: Local, separately for each enabled provider and authorized operation.
  - Entry point / command: `"$WS_PYTHON" -B "$RUNTIME/atlas_workspace_qualify.py" --config "$WORKSPACE_CONFIG" provider --provider "$PROVIDER" --operation-receipt "$OPERATION_RECEIPT" --output "$EVIDENCE/provider.json"`.
  - Green means: actual authorized target/source/ref/candidate and observed outcomes match the retained operation, including the existing issuer's ability to display/approve the complete schema-2 readable subject and return its matching signed response. The checker does not create a replacement invocation/effect. No automatic merge or remote cleanup. This gate enables only that provider path, not local core completion.
- G-E2E:
  - Where it runs: Local.
  - Entry point / command: prepare with `"$WS_PYTHON" -B "$RUNTIME/atlas_workspace_canary.py" --config "$WORKSPACE_CONFIG" prepare --task-id "$CANARY_TASK"`; run the installed live suite with `ATLAS_WORKSPACE_TEST_CONFIG="$WORKSPACE_CONFIG" "$WS_PYTHON" -B -m unittest discover -s "$RUNTIME/tests/workspace_live" -p test_workspace_canary.py`; collect supervised dispatch/terminal/original-result/check/review receipts through the normal CLI; then run `"$WS_PYTHON" -B "$RUNTIME/atlas_workspace_canary.py" --config "$WORKSPACE_CONFIG" verify --task-id "$CANARY_TASK"`.
  - Green means: complete independent source, two tasks, actual admitted host work, sealed checks/independent review, restored-cache export, failure/low-space recovery and coordinated backup/restore evidence agree on the persistent task/candidate. One persistent canary task retains a genuinely failing deterministic check on its sealed candidate, explicitly reworks that candidate's edits in a successor generation through actual host work, and exports only after fresh passing checks and independent review. The failure fixture and its criterion are declared by canary preparation; no worker/reviewer result is fabricated. The verifier rejects predecessor evidence reused for successor acceptance. Both failure routes have deterministic/restart coverage under G-UNIT/G-RECOVERY. `verify` inspects retained receipts; it neither reruns tests nor fabricates outputs.
- G-REPO:
  - Where it runs: CI and Local.
  - Entry point / command: `"$WS_PYTHON" -B scripts/verify_repo.py`.
  - Green means: repository verification, generated-adapter freshness, new deterministic checks and affected legacy regressions pass. Workspace live suites are explicit, not accidentally invoked by offline discovery.

### Merge points -> required gates
- MP1: Dependency/capability boundary — G-CAP.
- MP2: Public contracts and storage records — G-UNIT, G-DB.
- MP3: Independent source and mounted task integration — G-SOURCE, G-STORAGE.
- MP4: Actual harness/context boundary — G-HOST.
- MP5: Durable lifecycle — G-RECOVERY.
- MP6: Local/provider control — G-AUTH, G-PROVIDER.
- MP7: Complete local release candidate — G-REPO, G-E2E, G-HOST. Enabling a remote path additionally requires its G-PROVIDER-LIVE.

### Test Matrix
| Area/component | Risk | Test type | Where it runs |
|---|---|---|---|
| Contracts/store | Changed identity or duplicate operation | Strict unit refusal and real transaction | CI / Local |
| Source/Git | Donor dependency, transformed bytes, wrong parent | Object/tree comparison and fixture donor/cache removal | CI / Local |
| Mounted storage | Lost writes or mutable seal | Actual mount, clone, restart and write-scope probes | Local |
| Harness/context | Missing guidance or unsafe metadata behavior | Actual exact-profile canary and read-operation refusal | Local |
| DBOS | Repeated external effects or lost human wait | Real process restart with recorded failure injection | Local |
| Provider/authority | Wrong target or repeated write | Signed-crypto refusal, controlled remotes and provider fixtures | CI / Local |
| Installation | Lost operator state or implicit activation | Temporary installed-copy regression and rollback | CI / Local |
| Complete task | Component success without usable integration | Independent original-evidence acceptance | Local |
| Controlled Git | Replacement bytes, donor mutation or executable helpers | Replacement/configuration fixtures, object hash checks, donor snapshots | CI / Local |
| Same-task rework | Lost edits, duplicate successor or stale acceptance | Failed-check/review transitions, transactional replay, real restart and clone isolation | CI / Local |
| Approval compatibility | Task requests blocked or legacy Azure authority weakened | Full versioned request lifecycle, signed fixture responses and Azure supervisor regressions | CI / Local |

### Test plan (CI vs deployed)
- CI: Install the locked optional dependencies, run deterministic workspace tests and the repository verifier; no provider secrets, model calls or mandatory FUSE service. Separate regression proves legacy imports without optional dependencies.
- Local installed environment: Explicit live suites use the selected PostgreSQL/JuiceFS config and fail on missing prerequisites. Actual host and provider evidence remains distinct from stand-ins.
- Deployed cloud environment: N/A; cloud hosting is excluded. Local activation is controlled by the exact profile/live gates above.

### Manual blockers
- B-ENV: Operator/root, before G-CAP. Select explicit local runtime/private config and approved isolated PostgreSQL/JuiceFS prerequisites. The existing daily selection error must be resolved through its original path before touching old work. No guessed installation or automatic system-level change.
- B-HOST: Supervisor, before any actual model dispatch. Verify exact host/model/reasoning/account route, task-bound sizing and budget, mounted cwd/scope, original-result capture and terminal observation. Binary/login/profile names alone do not clear it.
- B-PROVIDER: Supervisor, before remote mutation, per target. Existing capability and signed exact operation authority must bind repository/source/candidate/ref. Missing authority blocks only that remote effect; it does not invalidate local source or enable another path.

### Rollout / Rollback
- Rollout: Merge behind a disabled default. Install a new pinned runtime directory/private config, preserving old snapshots and pending handoffs. Start one new canary ID; migrate no legacy task. Enable only the local lane/profile after G-REPO/G-E2E/G-HOST and independent code/goal acceptance. Remote paths remain off until individually qualified.
- Backup/restore: Quiesce intake, DBOS transitions and all external writers; observe terminal/release state before dumping the four databases. The backup manifest binds code/schema/volume versions and retained source/candidate/Git-bundle hashes. Restore into fresh private databases/namespaces with compatible code, then recheck those identities before resume. A sequential dump of still-changing databases is not a coordinated backup.
- Rollback trigger: Manifest/tree mismatch, lost acknowledged state, duplicate admitted invocation, stale grant accepted, unresolved writer/publication, preservation failure or incompatible schema/version.
- Rollback steps: Stop intake/publication; reconcile or retain uncertain operations; stop writers and observe release; preserve PostgreSQL/JuiceFS data, bundles, raw results and receipts. Disable new intake selection and finish legacy work on its original runtime. Restore the new lane only from a verified coordinated backup and compatible version. Do not delete evidence, blindly undo remote effects, or downgrade schema in place.

## Automation Issue Manifest
Not applicable: AutomationTarget is none. No issue projection or dispatch is requested.

## Planning Reviews

Eight fresh independent plan-only passes reviewed the repaired substantive plan and checked the final metadata/DR-011 snapshot at `sha256:79340497f9bb8388afac6d8ca0a3b4ec767b850cc3ae9715c29bacd05b0673d5`. The zero-context, implementer and expert passes found two remaining wording conflicts; the clone-source rule and immutable approval-operation inputs were corrected and actually reread before pass. All eight final checks report no unresolved planning finding or human decision. Earlier reviews remain below as historical evidence only.

These reviews establish planning adequacy, not installed integrity, storage/harness behavior, issuer compatibility or provider permission. `validate_plan.py --json` and `python3 -B scripts/verify_repo.py --skip-tests` are the planning verification entrypoints. The new build/live gates remain unrun. Only this plan is changed; no installation, model dispatch, publication or merge is authorized.

### Re-entry Repair Findings
- Reviewer: `/root` in the preceding review and current repair invocation.
- F-001: (Resolved) Original-object import previously relied on replacement-aware Git reads. Controlled execution, original object OID checks and independent restored-tree/manifest comparison are specified in Committed import, WS3 and G-SOURCE. Remediation target: Technical.
- F-002: (Resolved) Rework lacked an explicit operation. The same-task request, failure preconditions, predecessor/one-successor contract, DBOS wait/outbox and fresh acceptance requirements are specified in Protocol v2, Local control operations, WS2/WS4/WS6/WS7 and G-DB/G-STORAGE/G-RECOVERY/G-E2E. Remediation target: Technical.
- F-003: (Resolved) The reusable approval API required native Azure issue fields. Its schema-2 workspace request branch, all affected library consumers, a workspace operator route and schema-1 compatibility tests are specified in Provider authority, WS7 and G-AUTH. Existing signed envelopes, trust, issuers and actions remain unchanged. Remediation target: Technical.
- F-004: (Resolved) File ownership, phase exits and named gates now cover all three contracts. Local completion and provider-specific issuer/live qualification remain separate. Remediation target: Implementation.
- F-005: (Resolved) The baseline-only clone rule is now scoped to initial task creation; rework explicitly admits only its bound failed seal. Remediation target: Technical.
- F-006: (Resolved) Any changed schema-2 approval material requires a new publication operation/request, regardless of phase. Reopen is limited to unchanged material after reconciliation, preserving immutable operation inputs. Remediation target: Technical.
- Disposition:
  - Accept: F-001 -> DR-011
  - Accept: F-002 -> DR-011
  - Accept: F-003 -> DR-011
  - Accept: F-004 -> DR-011
  - Accept: F-005 -> DR-011
  - Accept: F-006 -> DR-011

### Zero-Context Review
- Reviewer: `/root/refresh_zero`.
- RefreshedAt: 2026-11-09T22:30:47Z
- ReviewedPlanHash: sha256:79340497f9bb8388afac6d8ca0a3b4ec767b850cc3ae9715c29bacd05b0673d5
- Re-entry audit answers:
  - What is being built: An opt-in local DBOS/PostgreSQL/JuiceFS tooling lane for independent committed source, Git-free task generations, recoverable work, sealed acceptance and Git export.
  - Why now: Remove checkout-dependent persistence and prove the complete task lifecycle.
  - Repos involved: AtlasMemory-Tools implements the lane; explicitly selected local/GitHub/Azure repositories supply source.
  - What changes first: WS1 installs and qualifies a complete pinned runtime package in an absent private target.
  - What must not happen: Dirty import, donor-backed resume, hidden task repositories, legacy-task migration, implicit dispatch/publication or accepted-branch merge.
  - How work is validated: Original-object/restored-manifest comparison, transactional replay, mount isolation, actual-host qualification, recovery injection, signed-authority refusals and same-task rework/export evidence.
  - What remains blocked: B-ENV selects prerequisites/runtime, B-HOST qualifies actual dispatch, and B-PROVIDER/issuer compatibility control remote effects separately. Failed qualification stops dependent work.
- Missing context: None found for the selected scope.
- Contradictions:
  - F-001: (Resolved) Initial baseline cloning and rework cloning from the explicitly bound failed sealed candidate are distinct and consistent. Remediation target: Technical.
  - F-002: (Resolved) Every material approval change requires a new publication operation, regardless of phase; reopen accepts unchanged material only after reconciliation. Remediation target: Technical.
- Unclear decisions: None requiring user policy or an implementer's guess.
- Risks and edge cases:
  - F-003: Non-blocker: Storage/dependency/host capabilities remain future qualification work with explicit stop conditions. Remediation target: Implementation.
- What I would screw up implementing tomorrow: No additional material ambiguity; original-object reads, same-task rework, fresh acceptance and versioned approval consumers are explicit.
- Pass/fail readiness statement: Pass for planning readiness and beginning WS1 qualification; no live behavior or provider permission is established.
- Disposition:
  - Accept: F-001 -> DR-011
  - Accept: F-002 -> DR-011
  - Reject: F-003 -> No amendment required; existing qualification gates preserve the uncertainty.

### Implementer Readiness Review
- Reviewer: `/root/refresh_implementer`.
- RefreshedAt: 2026-11-09T22:31:16Z
- ReviewedPlanHash: sha256:79340497f9bb8388afac6d8ca0a3b4ec767b850cc3ae9715c29bacd05b0673d5
- Top 5 gotchas:
  - F-001: (Resolved) The initial-clone and rework-clone rules now agree; DR-011 preserves the task while creating a successor generation. Remediation target: Technical.
- Evidence needed to prevent each gotcha:
  - F-002: Non-blocker: G-SOURCE covers original-object reads/donor preservation, G-DB/G-STORAGE/G-RECOVERY cover one successor and retained edits, and G-AUTH covers full workspace approval and legacy Azure compatibility. Material approval changes require a new operation; unchanged renewal requires reconciliation. Remediation target: Implementation.
- Pass/fail readiness statement:
  - F-003: Non-blocker: Pass for implementation-plan readiness beginning with WS1. No implementation-critical questions remain; actual capabilities and activation are still gated. Remediation target: Implementation.
- Disposition:
  - Accept: F-001 -> DR-011
  - Reject: F-002 -> No amendment required; the named tests and ownership already cover the contracts.
  - Reject: F-003 -> No amendment required; records the current readiness result without execution authority.

### Expert Technical Review
- Reviewer: `/root/refresh_expert`.
- RefreshedAt: 2026-11-09T22:30:53Z
- ReviewedPlanHash: sha256:79340497f9bb8388afac6d8ca0a3b4ec767b850cc3ae9715c29bacd05b0673d5
- Technical risks and integration gaps: No additional material gap. Original-object verification/restored-manifest comparison, predecessor-preserving rework and schema-2 approval keep their explicit boundaries.
- Missing validations or operational steps: None additional; G-SOURCE/G-DB/G-STORAGE/G-RECOVERY/G-AUTH name the relevant fixtures and evidence.
- Contradictions with stated invariants or authority boundaries:
  - F-001: (Resolved) Workspace creation explicitly separates initial baseline cloning from failed-seal rework, agreeing with the generation transition. Remediation target: Technical.
- Patch suggestions (point to plan sections):
  - F-002: (Resolved) Clone policy permits the rework input, and approval material changes always require new operations while reopen retains unchanged material. DR-011 states same task/new generation accurately. Remediation target: Technical.
- Pass/fail readiness statement: Pass for technical plan adequacy and beginning WS1; no runtime qualification is established.
- Disposition:
  - Accept: F-001 -> DR-011
  - Accept: F-002 -> DR-011

### Security/Privacy Review
- Reviewer: `/root/refresh_security`.
- RefreshedAt: 2026-11-09T22:31:22Z
- ReviewedPlanHash: sha256:79340497f9bb8388afac6d8ca0a3b4ec767b850cc3ae9715c29bacd05b0673d5
- Security/privacy risks:
  - F-001: Non-blocker: Complete schema-2 subject/effect bindings preserve existing issuer/owner/signature/trust verification and schema-1 Azure handling. Mixed schemas, substitutions and unsupported issuers fail closed under G-AUTH/G-PROVIDER-LIVE. Final metadata grants no installation, dispatch, publication or merge authority. Remediation target: Technical.
- Missing validations or mitigations:
  - F-002: Non-blocker: G-HOST requires actual administrative/secret exclusion; G-UNIT/G-PROVIDER cover secret handling; G-SOURCE covers controlled reads/donor preservation; G-AUTH/G-PROVIDER-LIVE cover approval/issuer behavior. These are future evidence requirements. Remediation target: Implementation.
- Patch suggestions (point to sections): None required; rework preserves scope, budget, predecessor evidence and fresh acceptance.
- Pass/fail readiness statement: Pass for security/privacy planning adequacy; no human-agency security decision remains. Runtime enforcement and provider permission remain unproven.
- Disposition:
  - Reject: F-001 -> No amendment required; confirms specified authority preservation and live gates.
  - Reject: F-002 -> No amendment required; evidence hooks already cover the claims.

### Database and Data Integrity Review
- Reviewer: `/root/refresh_database`.
- RefreshedAt: 2026-11-09T22:31:25Z
- ReviewedPlanHash: sha256:79340497f9bb8388afac6d8ca0a3b4ec767b850cc3ae9715c29bacd05b0673d5
- Domain risks and integration gaps:
  - F-001: Non-blocker: Four separate databases do not imply a shared transaction. Staged admission, non-null operation uniqueness, CAS and readback cover the boundaries. Rework reserves one successor before cloning and admits it with an outbox event while preserving task/source/predecessor evidence. Remediation target: Technical.
- Missing validations or operational steps:
  - F-002: Non-blocker: G-DB/G-RECOVERY cover competing requests, reservation/clone/admission crashes, lost acknowledgement and notification replay. G-SOURCE verifies original objects against independently restored tree/manifest; G-STORAGE checks isolation and G-E2E coordinated restore. Remediation target: Implementation.
- Contradictions with stated invariants or authority boundaries: None found. Historical replay cannot advance the active generation or authorize its successor; changed publication material requires a new operation.
- Patch suggestions (point to plan sections): None required.
- Pass/fail readiness statement: Pass for planning adequacy and WS1 qualification; no database/storage/recovery runtime behavior is established.
- Disposition:
  - Reject: F-001 -> No amendment required; confirms the specified transaction boundaries.
  - Reject: F-002 -> No amendment required; the existing gates cover the failure cases.

### Local Operations Review
- Reviewer: `/root/refresh_operations`.
- RefreshedAt: 2026-11-09T22:31:51Z
- ReviewedPlanHash: sha256:79340497f9bb8388afac6d8ca0a3b4ec767b850cc3ae9715c29bacd05b0673d5
- Domain risks and integration gaps:
  - F-001: Non-blocker: Interpreter, lock and managed-byte identity are consistently bound. WS1 installs all tracked runtime helpers/tests/fixtures/locks without source-checkout dependence; G-CAP/bootstrap regressions require actual evidence. Remediation target: Implementation.
- Missing validations or operational steps:
  - F-002: Non-blocker: Capacity includes all four databases, owned cache/backup, staging and WAL headroom. Low/unmeasurable capacity stops admission without deletion; backup validates target capacity. G-CAP/G-DB/G-RECOVERY/G-E2E cover failures. Remediation target: Implementation.
- Contradictions with stated invariants or authority boundaries:
  - F-003: Non-blocker: Rework preserves authority and remaining deadline/budget; recovery never dispatches automatically. Workspace approval owns schema 2, legacy Azure CLI remains schema-1-only and issuer invocation is explicit. Remediation target: Technical.
- Patch suggestions (point to plan sections):
  - F-004: Non-blocker: No further patch required. Disabled-default rollout, quiesced version/hash-bound backup, fresh private restore and evidence-preserving rollback remain explicit. G-E2E must provide actual restore evidence. Remediation target: Implementation.
- Pass/fail readiness statement: Pass for local operations planning adequacy and WS1 qualification; no questions remain. Actual storage/host/issuer/restore behavior remains unproven.
- Disposition:
  - Reject: F-001 -> No amendment required; confirms installation/version contracts.
  - Reject: F-002 -> No amendment required; capacity checks and failure behavior are already specified.
  - Reject: F-003 -> No amendment required; confirms preserved authority/budget and command boundaries.
  - Reject: F-004 -> No amendment required; rollout/restore/rollback evidence remains gated.

### Dynamic Specialist Review Roster
- Reviewer: `/root/refresh_roster`.
- RefreshedAt: 2026-11-09T22:31:54Z
- ReviewedPlanHash: sha256:79340497f9bb8388afac6d8ca0a3b4ec767b850cc3ae9715c29bacd05b0673d5
- Triggered specialist review rationale:
  - F-001: Non-blocker: Expert review covers Git/filesystem/harness/provider interfaces, database review covers CAS/rework/outbox, security covers approval/issuer/sandbox/secrets, and operations covers installation/capacity/restore/budgets. Implementer and readability reviews cover the private operator workflow. Named gates specify where, command and green evidence. Remediation target: Context Snapshot.
- Skipped specialist review rationale:
  - F-002: Non-blocker: Cloud hosting, multi-user operation, browser UI, new authentication infrastructure and unattended automation remain excluded. Provider protocol/approval stays in expert/security scope. Automation readiness is N/A; projection/dispatch approval remains NotRequested. Remediation target: Context Snapshot.
- Missing or deferred specialist coverage:
  - F-003: Non-blocker: No additional review domain is missing. Actual storage/sandbox/host/issuer/provider behavior remains future qualification. Revisit for hosting, multi-user operation, unattended dispatch, destructive migration, backend substitution or new provider authentication. Remediation target: Context Snapshot.
- Pass/fail roster statement: Pass; coverage does not certify another reviewer's judgment or live behavior.
- Disposition:
  - Reject: F-001 -> No amendment required; actual independent passes cover these domains.
  - Reject: F-002 -> No amendment required; the skipped domains remain explicitly excluded.
  - Reject: F-003 -> No amendment required; qualification and scope-change triggers are already explicit.

### Human Readability Review
- Reviewer: `/root/refresh_readability`.
- RefreshedAt: 2026-11-09T22:30:31Z
- ReviewedPlanHash: sha256:79340497f9bb8388afac6d8ca0a3b4ec767b850cc3ae9715c29bacd05b0673d5
- Product/system clarity:
  - F-001: Non-blocker: The opening explains checkout-dependent task persistence, independently retained source and resumable Git-free workspaces. Current workflow, why-now and measurable outcomes are explicit. Remediation target: Problem.
- Technical narrative clarity:
  - F-002: Non-blocker: Actors, conditions and reasons are clear: the Git adapter verifies original bytes, explicit rework creates a successor from the failed seal while preserving the task, and workspace approvals use their versioned route while preserving Azure requests. Old evidence cannot authorize a successor; changed approval material requires a new operation. Remediation target: Technical.
- Execution-mechanics leakage:
  - F-003: Non-blocker: Introductions explain the work before execution mechanics. Detailed authority/recovery rules describe the runtime being changed; planning authority remains in the appendix and older reviews are marked historical. Remediation target: Implementation.
- Strongest remaining ambiguity:
  - F-004: Non-blocker: Storage, exact harness and real issuer behavior remain unproven engineering results with named qualification/stop tasks, distinguishable from missing user intent. Remediation target: Implementation.
- Pass/fail readability statement: Pass
  - F-005: Non-blocker: All seven meaning criteria pass: answer-first, actors-actions, conditions-reasons, terms-referents, reasoning-uncertainty, economy-clarity and faithfulness. Final metadata separates reviewed planning, implementation authorization and future live qualification.
- Rendered view: Complete Markdown reviewed; HTML was not generated or run.
- Disposition:
  - Reject: F-001 -> No amendment required; the problem/outcome narrative is explicit.
  - Reject: F-002 -> No amendment required; the repaired contracts explain behavior and conditions.
  - Reject: F-003 -> No amendment required; execution detail is placed according to its meaning.
  - Reject: F-004 -> No amendment required; uncertainty has named qualification owners and stops.
  - Reject: F-005 -> No amendment required; records the semantic readability result without live proof.

### Historical review record (superseded)
The following records preserve the earlier review findings, dispositions and reported checks. Their hashes and pass statements describe the earlier snapshots only; they do not establish freshness or readiness of the repaired plan. Current reviews above establish freshness for the repaired plan.

Eight independent plan-only passes reviewed the complete substantive document at the hash below. The first review round (`sha256:7c1238ac4cfd8998d8919d2f5f914707ab93a090b422d7411f40ba516883f7a1`) found the contract gaps retained under their stable IDs. Subsequent rereads verified the actual repairs; the final substantive snapshot is `sha256:8e7726ba233526105c881a3d113719a07cf23167b2ca83c415f9c8ff19b249d3`. These reviews establish planning adequacy, not implementation, dependency support, installed integrity or live qualification. Accept dispositions below refer to scope-preserving documentation/contracts/test requirements under DR-009. No human-agency finding remains.

Final planning verification: `validate_plan.py --json` passes IntentModelComplete, ProblemDefinitionComplete, PlanReadiness, PlanningReviewsComplete and PlanStateSanity; AutomationReadiness is N/A. `python3 -B scripts/verify_repo.py --skip-tests` exits 0. All eight reviewers checked the final metadata and their packaged findings against the current canonical hash. Only this plan is changed; future build/live gates remain unrun.

#### Zero-Context Review
- Reviewer: `/root/review_zero`.
- RefreshedAt: 2026-11-09T21:14:28Z
- ReviewedPlanHash: sha256:f269c92adc037284183600233bd18c86afc177350e85d712229d9dd746a9f279
- Re-entry audit answers:
  - What is being built: An opt-in local DBOS/PostgreSQL/JuiceFS lane for committed import, independent storage, Git-free work, recoverable lifecycle, sealed review and Git candidate export.
  - Why now: Replace checkout-dependent task persistence and prove a complete useful workflow rather than counting component tests alone.
  - Repos involved: AtlasMemory-Tools owns the implementation; explicitly selected local/GitHub/Azure repositories supply committed source. Owned storage retains admitted bytes/history independently.
  - What changes first: WS1 locks artifacts and installs the complete tracked runtime package into an absent private target for bound-interpreter capability checks.
  - What must not happen: Dirty input, donor-backed resume, hidden task Git repositories, silent Git-feature loss, legacy-task migration, automatic dispatch/merge or provider activation inferred from local completion.
  - How work is validated: Shared manifest/history bindings, deterministic refusals, actual database/storage/host/recovery evidence and an independently reviewed local import-to-export canary. Provider live gates remain separate.
  - What remains blocked: B-ENV selects prerequisites/runtime, B-HOST controls actual dispatch, B-PROVIDER controls only its exact remote effect. Failed substrate/profile qualification stops dependent work.
- Missing context: None found.
- Contradictions: None found; WS2 supplies the production transport before WS5, and MP7 repeats qualification.
- Unclear decisions: None requiring further user policy.
- Risks and edge cases:
  - F-001: Non-blocker: Donor ownership, independent tree/history admission and local return are explicit; exporting a candidate grants no right to modify the donor. Remediation target: Technical.
- What I would screw up implementing tomorrow: No additional material ambiguity; pre-seal node refusals, uncertain acknowledgement reconciliation and separate provider gates are explicit.
- Pass/fail readiness statement: Pass for beginning implementation with WS1.
- Disposition:
  - Reject: F-001 -> No change required; confirms DR-005 and the existing import/export boundary.

#### Implementer Readiness Review
- Reviewer: `/root/review_implementer`.
- RefreshedAt: 2026-11-09T21:13:34Z
- ReviewedPlanHash: sha256:f269c92adc037284183600233bd18c86afc177350e85d712229d9dd746a9f279
- Top 5 gotchas:
  - F-001: (Resolved) The WS5/WS7 dependency cycle is removed: WS2 owns the real transport before MP2, WS5 registers actual handlers, and MP7 reruns G-HOST. Remediation target: Implementation.
  - F-002: (Resolved) G-E2E now names canary preparation, live-suite production, supervised receipt collection and verification. Remediation target: Implementation.
  - F-006: (Resolved) Bootstrap now includes every tracked runtime-template file, helpers/dependencies, live suites/fixtures, scripts/locks/examples, with no source-checkout dependency. Remediation target: Implementation.
- Evidence needed to prevent each gotcha:
  - F-003: (Resolved) Early transport tests, real WS5 handlers and assembled-service requalification supply the required evidence order. Remediation target: Implementation.
  - F-004: (Resolved) The canary producer/collector/verifier sequence distinguishes actual host receipts from deterministic fixtures. Remediation target: Implementation.
  - F-007: (Resolved) Bootstrap tests explicitly detect missing/stale helpers, live suites, fixtures and locks and prove installed-copy independence. Remediation target: Implementation.
- Pass/fail readiness statement:
  - F-005: (Resolved) Pass for implementation-plan readiness; B-ENV/B-HOST and future qualification gates still control live work. Remediation target: Implementation.
- Disposition:
  - Accept: F-001 -> DR-009
  - Accept: F-002 -> DR-009
  - Accept: F-003 -> DR-009
  - Accept: F-004 -> DR-009
  - Accept: F-005 -> DR-009
  - Accept: F-006 -> DR-009
  - Accept: F-007 -> DR-009

#### Expert Technical Review
- Reviewer: `/root/review_expert`.
- RefreshedAt: 2026-11-09T21:14:11Z
- ReviewedPlanHash: sha256:f269c92adc037284183600233bd18c86afc177350e85d712229d9dd746a9f279
- Technical risks and integration gaps:
  - F-001: (Resolved) Pre-seal no-follow inventory rejects unsupported new nodes before reading/hashing/sealing while retaining diagnostics and the generation. Remediation target: Technical.
  - F-004: Non-blocker: Package, clone/flush and exact harness compatibility remain unverified engineering capabilities with explicit stop-first qualification. Remediation target: Implementation.
- Missing validations or operational steps:
  - F-002: (Resolved) G-STORAGE names special-node/path/link/hardlink refusal fixtures, no hung reads or silent omission, and retained diagnostics. Remediation target: Implementation.
- Contradictions with stated invariants or authority boundaries: None material; tree and bundle identities, real transport order, writer release and uncertain persistence remain distinct.
- Patch suggestions (point to plan sections):
  - F-003: (Resolved) Workspace creation/sealing and G-STORAGE include the requested policy and coverage. Remediation target: Technical.
- Pass/fail readiness statement: Pass within the technical scope.
- Disposition:
  - Accept: F-001 -> DR-009
  - Accept: F-002 -> DR-009
  - Accept: F-003 -> DR-009
  - Reject: F-004 -> No change required; existing WS1/WS5 qualification explicitly preserves the uncertainty.

#### Security/Privacy Review
- Reviewer: `/root/review_security`.
- RefreshedAt: 2026-11-09T21:14:13Z
- ReviewedPlanHash: sha256:f269c92adc037284183600233bd18c86afc177350e85d712229d9dd746a9f279
- Security/privacy risks: No new material finding; real administrative/context separation, actual sandbox probes, authentic results, exact grants and uncertain-effect reconciliation remain enforced requirements.
- Missing validations or mitigations:
  - F-001: (Resolved) G-UNIT/G-PROVIDER inject canary secrets into successful/failing operations and assert their exclusion from logs/errors/context/receipts while preserving privately retained original role-result bytes unchanged. Remediation target: Implementation.
- Patch suggestions (point to sections): None further. Actual G-HOST sandbox evidence cannot be replaced by deterministic fixtures; failed qualification prevents activation.
- Pass/fail readiness statement: Pass for plan adequacy; no additional human-agency security decision.
- Disposition:
  - Accept: F-001 -> DR-009

#### Database and Data Integrity Review
- Reviewer: `/root/review_database`.
- RefreshedAt: 2026-11-09T21:13:42Z
- ReviewedPlanHash: sha256:f269c92adc037284183600233bd18c86afc177350e85d712229d9dd746a9f279
- Domain risks and integration gaps:
  - F-001: (Resolved) Non-null resource-scoped operation uniqueness covers taskless requests; exact replay precedes drift checks and new transitions require separate CAS. Remediation target: Technical.
- Missing validations or operational steps:
  - F-002: (Resolved) Shared manifest/history contracts define canonical bytes and logical identity, separate bundle integrity/closure, independent restore and distinguishing fixtures. Remediation target: Technical.
- Contradictions with stated invariants or authority boundaries:
  - F-003: (Resolved) Confirmed rollback and lost commit/flush acknowledgement have distinct outcomes. Uncertainty retains operation identity/original evidence until authoritative reconciliation; replay returns committed outcomes without another transition. G-DB/G-RECOVERY inject the acknowledgement-loss case and require one result with unchanged bytes and no duplicate admission/notification. Remediation target: Technical.
- Patch suggestions (point to plan sections): None further; complete tracked-runtime bootstrap introduces no database/concurrency regression.
- Pass/fail readiness statement: Pass.
- Disposition:
  - Accept: F-001 -> DR-009
  - Accept: F-002 -> DR-009
  - Accept: F-003 -> DR-009

#### Local Operations Review
- Reviewer: `/root/review_operations`.
- RefreshedAt: 2026-11-09T21:13:45Z
- ReviewedPlanHash: sha256:f269c92adc037284183600233bd18c86afc177350e85d712229d9dd746a9f279
- Domain risks and integration gaps:
  - F-001: (Resolved) Absolute qualified interpreter, dependency-lock and installed-byte identity are bound consistently across commands. Remediation target: Implementation.
- Missing validations or operational steps:
  - F-002: (Resolved) WS1 bootstrap owns complete committed runtime-package installation before downstream gates, including helpers/live suites/fixtures and missing/stale-byte refusal checks. Remediation target: Implementation.
- Contradictions with stated invariants or authority boundaries:
  - F-003: Non-blocker: Disabled-default rollout, original-runtime legacy recovery, separate provider enablement, coordinated backup and fresh-target restore remain explicit; no deletion/retention/cost/hosting permission is invented. Remediation target: Implementation.
- Patch suggestions (point to plan sections):
  - F-004: (Resolved) Capacity accounting includes four databases, cache/backup, staging and WAL/headroom. Low/unmeasurable capacity stops admission without deletion; uncertain acknowledgement requires readback rather than invented rollback. G-CAP/G-DB/G-RECOVERY/G-E2E name these checks. Remediation target: Implementation.
- Pass/fail readiness statement: Pass within the operational scope.
- Disposition:
  - Accept: F-001 -> DR-009
  - Accept: F-002 -> DR-009
  - Reject: F-003 -> No change required; confirms existing rollout, legacy and provider boundaries.
  - Accept: F-004 -> DR-009

#### Dynamic Specialist Review Roster
- Reviewer: `/root/review_roster`.
- RefreshedAt: 2026-11-09T21:15:04Z
- ReviewedPlanHash: sha256:f269c92adc037284183600233bd18c86afc177350e85d712229d9dd746a9f279
- Triggered specialist review rationale:
  - F-001: Non-blocker: Separate database/concurrency, expert filesystem/harness/API/provider, security/privacy/authority, and local operations/capacity/installation passes cover the actual contracts. Their executable hooks are G-DB/G-RECOVERY, G-SOURCE/G-STORAGE/G-HOST, G-UNIT/G-AUTH/G-PROVIDER and G-CAP/G-E2E/G-REPO respectively. Remediation target: Context Snapshot.
- Skipped specialist review rationale:
  - F-002: Non-blocker: Cloud hosting, multi-user isolation, browser UI and a new authentication platform remain excluded. Existing provider authority stays in expert/security scope; private-CLI operator flow stays in operations/implementer/readability scope. Automation readiness is N/A because AutomationTarget is none. Remediation target: Context Snapshot.
- Missing or deferred specialist coverage:
  - F-003: Non-blocker: No additional domain is missing. Revisit if hosting, multi-user operation, unattended dispatch, destructive migrations, backend substitution or new provider authentication enters scope. Remediation target: Context Snapshot.
- Pass/fail roster statement: Pass; roster coverage does not certify another reviewer's result or live behavior.
- Disposition:
  - Reject: F-001 -> No change required; confirms existing specialist routing and evidence hooks.
  - Reject: F-002 -> No change required; confirms explicitly excluded domains and covered operator flow.
  - Reject: F-003 -> No change required; records the existing scope and revisit triggers.

#### Human Readability Review
- Reviewer: `/root/readability_review`.
- RefreshedAt: 2026-11-09T21:14:54Z
- ReviewedPlanHash: sha256:f269c92adc037284183600233bd18c86afc177350e85d712229d9dd746a9f279
- Product/system clarity: Pass. The result is understandable without the conversation: owned committed source, isolated resumable Git-free workspaces and a separately reviewed Git candidate. Actors and their responsibilities are named.
- Technical narrative clarity: Pass. Conditions and reasons explain import admission, writer termination, outbox recovery, cancellation and uncertain acknowledgement. Source/baseline/workspace/candidate/publication/acceptance and tree/bundle identity remain distinct. All seven plain-technical-English criteria pass: answer-first, actors/actions, conditions/reasons, terms/referents, reasoning/uncertainty, economy/clarity and faithfulness.
- Execution-mechanics leakage:
  - F-001: (Resolved) Stale review bookkeeping is replaced by actual final review records and exhaustive dispositions. Runtime authority remains where it explains this system; planning authority stays in the appendix. Remediation target: Implementation.
- Strongest remaining ambiguity:
  - F-002: Non-blocker: Exact storage artifacts and harness/project behavior remain unproven engineering work assigned to WS1/WS5, with a stop if required behavior fails. This is explicit uncertainty, not missing user intent. Remediation target: Implementation.
- Pass/fail readability statement: Pass
- Rendered view: Complete Markdown reviewed; HTML rendering was not generated or run.
- Disposition:
  - Accept: F-001 -> DR-009
  - Reject: F-002 -> No prose change required; existing qualification tasks and stop conditions preserve the uncertainty.

## Execution Mechanics / Automation Appendix

The selected harness-local Markdown document owns authoring intent, rationale and amendments. Compiled registry data and rendered views are derived. For issue/PR-backed execution, GitHub issues and PRs retain their existing execution-state and mutation-authority role; Projects remain a downstream UI. The explicitly selected new local lane stores its own task/operation lifecycle in PostgreSQL/DBOS. An imported issue or local task grants no remote write authority, and no cloud tracker/comment acts as its message bus.

AutomationTarget is none: this invocation creates no tracker issues, PRs, board state, schedule, runtime jobs, or unattended dispatch. Existing sizing/route/authority rules still apply when an item is actually admitted for implementation.

Planning validation is recorded separately from future build gates. Repository static verification and the plan validator are rerun after drafting. None of G-CAP/G-DB/G-STORAGE/G-HOST/G-RECOVERY/G-PROVIDER-LIVE/G-E2E is claimed to have run during planning. No service, dependency installation, mount, schema migration, account qualification or provider effect has occurred. The existing daily status still reports a selected-config/provenance input error; no installed runtime version or queue state has been inferred from this source plan.
