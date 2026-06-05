# Handoff: Atlas Core Project 5 Runtime Rollout

**Created:** 2026-05-25 21:45 UTC
**Project:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
**Runtime:** `/home/mat/distrobox-homes/atlas-agent/agent-runtime`
**Purpose for next session:** Operate the local automation runtime for GitHub Project #5 only and begin the Atlas Core rollout without sweeping old Azure registry work.
**Continues from:** `.codex/handoffs/2026-05-25-2051-atlas-core-runtime-first-shift.md`

## Current State

User wants Project #5 to become the active runtime lane: `https://github.com/orgs/Atlas-Memory-Framework/projects/5`.

Project #5 is the Atlas Core Local-First Workspace Operations MVP board, not the old Azure registry board. Current snapshot from `gh project item-list 5 --owner Atlas-Memory-Framework --limit 200 --format json`:

- Total items: `68`
- Execution repo: all `Atlas-Memory-Framework/atlas-memory`
- Target repo distribution: `atlas-memory` 56, `Atlas-Memory-UI` 11, cross-repo 1
- Automation state: `Blocked` 66, `Planned` 1, `PR Open` 1
- Issue readiness: `Blocked` 66, `Draft` 1, `Ready` 1
- The only ready/in-progress item is `#110` / PR `#161` (`TOOLS-PROJECTION-001`), still blocked by required-check/no-check policy.

## Decisions

- **Project #5 is the active lane**: Run Atlas Core Project #5 only. Do not resume old Azure registry work unless the user explicitly asks.
- **Default runtime repos narrowed**: `repos.txt` now contains only `Atlas-Memory-Framework/atlas-memory` and `Atlas-Memory-Framework/Atlas-Memory-UI`.
- **No broad repo-wide PR sweeps**: Do not run unattended/review/repair/finalize loops that scan all open `atlas-memory` PRs. Those picked up old Azure PRs (`#66`, `#67`, `#69`, `#70`, `#71`) and created noise.
- **Use Project/issue-aware targeting**: For build velocity, first make Project #5 queueable through audit/decomposition/promotion, then dispatch constrained one-point items. Runtime improvements are in scope when needed to support this.

## Changed or Important Files

- `/home/mat/distrobox-homes/atlas-agent/agent-runtime/repos.txt`: changed from Azure/Admin/Chainlit/default atlas lane to only current Project #5 repos:
  - `Atlas-Memory-Framework/atlas-memory`
  - `Atlas-Memory-Framework/Atlas-Memory-UI`
- `/home/mat/distrobox-homes/atlas-agent/agent-runtime/projects.txt`: already points at `Atlas-Memory-Framework/5`; no change needed.
- `/home/mat/distrobox-homes/atlas-agent/agent-runtime/CURRENT_PROJECT_LANE.md`: new runtime-local guardrail note documenting Project #5 as active and quarantining old Azure-era PRs.
- `/tmp/atlas-project-5-items.json`: latest Project #5 item-list snapshot from this session.
- `/tmp/atlas-core-reconcile-preview.json`: repo reconcile preview after reconfig.
- `/tmp/atlas-core-project-reconcile-preview.json`: Project reconcile dry-run showing stale metadata on `#162-#171`.
- `/tmp/atlas-core-project-reconcile-apply.json`: Project metadata hydration apply summary for `#162-#171`.

## Verification

- `gh repo view Atlas-Memory-Framework/atlas-memory`: passed; default branch is `fix/mime-resolution-pins-mainline`.
- `gh repo view Atlas-Memory-Framework/Atlas-Memory-UI`: passed; default branch is `main`.
- `./atlas-agent-reconcile --repos-file repos.txt --summary /tmp/atlas-core-reconcile-preview.json`: passed, no decisions.
- `./atlas-agent-project-reconcile --projects-file projects.txt --limit 200 --dry-run --summary /tmp/atlas-core-project-reconcile-preview.json`: passed; found only Project metadata hydration needed for `#162-#171`.
- `./atlas-agent-project-reconcile --projects-file projects.txt --limit 200 --hydrate-metadata --apply --summary /tmp/atlas-core-project-reconcile-apply.json`: passed; applied `Priority: P3` metadata for `#162-#171`.
- Removed stale `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/atlas-agent-shift.lock` after terminating the stopped shift PID.
- Verified no `agent-runtime/atlas-agent-shift`, `agent-runtime/atlas-agent-unattended`, or `agent-runtime/atlas-agent-pr-repair` processes remained.

## Open Questions and Blockers

- [ ] Project #5 is still mostly blocked. Most parent issues are `points:3+`, `tracking-only`, or `manual-review`, and require decomposition or explicit promotion before dispatch.
- [ ] PR `#161` for issue `#110` has repeated local-validation-passed comments but no GitHub checks; do not keep revalidating it in a loop. Decide whether to adjust no-check policy, trigger checks, or leave it for human review.
- [ ] Old Azure-era PRs in `atlas-memory` are still open and labeled for repair/validation. They are not the current lane. Do not close or merge them without user direction.
- [ ] Runtime may need an issue/project-aware targeter to avoid repo-wide PR scans. This is legitimate runtime work for the next session.

## Next Steps

1. Use `project-queue-audit` semantics on Project #5, not repo-wide PR state. Start from Project items with `planKey=ATLAS-CORE-LOCAL-FIRST-WORKSPACE-OPERATIONS-MVP`.
2. Build a safe target list of current Project #5 leaves: prefer already decomposed one-point child issues, no manual gates, no open dependencies, target repo in `repos.txt`, and no active PR.
3. If no queueable leaves exist, decompose or promote current Project #5 blocked items in small batches, then re-run Project reconcile.
4. Run only bounded targeted dispatch for approved one-point issues. Avoid `review,repair,finalize` sweeps over all repo PRs.
5. Log each cycle in a new handoff/status artifact before scaling concurrency.

## Context Notes

User wants fast rollout of ~300 points, aiming for at least the known peak pace of ~50 points/day in a fresh session. Speed is desired, but the controlling constraint is target hygiene: current Project #5 only, no old Azure registry work, no repeated #161 validation loops.

Use `local-automation-runtime-operate` for runtime operation and `handoff` for durable state. If runtime code needs improvement to support Project-aware targeting, make that change deliberately before dispatching more agents.

## 2026-05-26 Runtime Continuation Update

**Current phase:** Project #5 Atlas Core lane is active. CORE-SEM-001 children are complete, but parent promotion is waiting on a human Core authority gate. UI children are blocked by cross-repo runtime limitations.

**Merged / closed:**
- `atlas-memory` PR `#161` for issue `#110`: repaired validation evidence, semantic review passed, merged at `2026-05-26T01:05:21Z`, merge `b513eb3990f5befa6ea402e098fda341798776c9`; issue `#110` closed.
- `atlas-memory` PR `#444` for issue `#104`: implemented `protocols/semantic_workspace.py` plus semantic-kernel tests after correcting child scope; local validation and semantic review passed; merged at `2026-05-26T01:48:22Z`, merge `beeb4d888ba203cf083a6bf0e1629ff7870f4857`; issue `#104` closed.
- `atlas-memory` PR `#445` for issue `#103`: implemented `atlas_memory_core/semantic/**`, moved kernel source-of-truth there, left `protocols/semantic_workspace.py` as compatibility re-export, updated semantic tests; local validation and semantic review passed; merged at `2026-05-26T02:12:27Z`, merge `f64b3972ec982988736247eae22033a4edc7ad43`; issue `#103` closed.
- Issue `#105` closed as completed by the corrected CORE-SEM-001 merge group because its `tests/test_semantic_kernel/**` scope landed through `#444/#445`; completion comment includes docs-not-needed and GC rationale.

**Runtime/tooling changes made in `templates/local-automation-runtime/` and installed where relevant:**
- `atlas-agent-review`: fixed false superseded detection by no longer treating arbitrary PR/issue body code text containing `SUPERSEDED` as a stale/superseded signal.
- `atlas-agent-worker`: validation extraction now recognizes Markdown bold headings like `**Tests**` / `**Verification**`; future worker PRs should not publish without evidence under the updated policy.
- `atlas-agent-workstream-review`: `create_followup` now ensures required follow-up labels before `gh issue create`, avoiding failure on missing `agent:workstream-followup`.
- Active runtime `required-checks.json`: no-check path policy now includes `3 - interfaces/core/**`, still requiring `agent:no-checks-expected`; used for `#444/#445` because GitHub required workflows are path-filtered and do not trigger for core-interface paths.
- Active runtime `local-validation.json`: added `Atlas-Memory-Framework/Atlas-Memory-UI` commands: `npm ci`, targeted workflow intake test, typecheck, lint, build.

**Validation of runtime patches:**
- `.venv/bin/python -m pytest templates/local-automation-runtime/tests/test_review_agent.py templates/local-automation-runtime/tests/test_local_agent_autonomy.py -k "superseded or bold_tests"`: `5 passed`.
- `.venv/bin/python -m pytest templates/local-automation-runtime/tests/test_workstream_review.py`: `5 passed`.
- Full `test_local_agent_autonomy.py` was not rerun successfully because unrelated tests write runtime lock/cache files under a read-only `/var/home/.../local-automation-runtime-state` path in this sandbox.

**Workstream review:**
- Ran `./atlas-agent-workstream-review Atlas-Memory-Framework/atlas-memory#74 --apply`.
- Result: `needs-human`, not code failure. The review says merged work appears to satisfy CORE-SEM-001, but parent `#74` still carries `Core authority requires human review before dispatch`; downstream dependency promotion requires human approval.
- Artifact: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/issue-74-workstream-review-20260526T021935Z`.

**Remaining Project #5 blockers / next safe actions:**
1. Do not promote CORE-SEM-001 parent `#74` until human Core authority signs off.
2. UI children `#106-#109` are blocked. They are tracked as issues in `Atlas-Memory-Framework/atlas-memory` but target/write `Atlas-Memory-UI`; current worker assumes issue repo equals checkout/PR repo, so dispatch would operate in the wrong repository. Comments were added to `#106-#109` documenting this blocker.
3. Next runtime improvement should be cross-repo source-issue / target-repo support, or create mirrored UI-repo issues and add them to Project #5. Until then, do not dispatch `#106-#109`.
4. Before another broad runtime cycle, avoid `--auto-queue-label status:ready`; use explicit issue dispatch or a Project-scoped approved label.

**Important safety notes:**
- An unrelated Instablinds runtime process was observed under a parent `atlas-agent-shift`; do not touch it.
- `config.env` in the active runtime still contains stale Azure defaults. For explicit worker dispatch, set `AGENT_REPO`, `AGENT_BASE_BRANCH`, and runtime dirs explicitly, as was done for issue `#103`.
- There are repo-local uncommitted template/test changes in `AtlasMemory-Tools`; do not revert user changes.

## 2026-05-26 Shift Update: UI Contract Completed, gh Quota Blocked

**Current phase:** Project #5 remains the active lane. CORE-SEM-001 parent `#74` still needs human Core authority review. UI-CONTRACT-001 parent `#90` is now completed and closed through target-repo mirror PRs.

**GitHub CLI blocker:**
- `gh` is currently blocked by `GraphQL: API rate limit already exceeded for user ID 150743840`.
- Because runtime commands depend on `gh`, the following could not run after the quota was hit:
  - `./atlas-agent-project-reconcile --projects-file projects.txt --apply`
  - `./atlas-agent-workstream-review Atlas-Memory-Framework/atlas-memory#90 --apply`
- Connector-backed issue/PR work still functioned, and plain `git fetch/push` worked. Use connector or wait for `gh` quota reset before runtime loops.

**Runtime/tooling changes since the prior update:**
- `atlas-agent-worker`: refactored git author setup into `configure_worktree_identity(worktree_dir)` and installed the script into the active runtime. This preserves the fix for missing worker commit identity (`AGENT_GIT_USER_NAME` / `AGENT_GIT_USER_EMAIL`).
- `atlas-agent-project-reconcile`: stale Project item update failures containing `Could not resolve to a node` are skipped instead of aborting. Installed earlier in the active runtime.
- Added tests:
  - `templates/local-automation-runtime/tests/test_project_reconcile.py`: stale Project item skip and non-stale RuntimeError re-raise.
  - `templates/local-automation-runtime/tests/test_local_agent_autonomy.py`: worker worktree git identity setup.
- Validation run:
  - `PYTHONPATH=templates/local-automation-runtime .venv/bin/python -m pytest templates/local-automation-runtime/tests/test_project_reconcile.py templates/local-automation-runtime/tests/test_review_agent.py templates/local-automation-runtime/tests/test_workstream_review.py templates/local-automation-runtime/tests/test_local_agent_autonomy.py -k 'project_field or git_identity or bold_tests or superseded or workstream'`: `18 passed, 120 deselected`.

**UI-CONTRACT-001 completion:**
- Source issue `atlas-memory#106` completed through UI mirror `Atlas-Memory-UI#6` / PR `Atlas-Memory-UI#7`; merge `9227a3c184233396651009587d42bf7741007d61`; source `#106` closed.
- Source issue `atlas-memory#107` completed through UI mirror `Atlas-Memory-UI#8` / PR `Atlas-Memory-UI#9`; merge `67abc6bb980719c2f5cce7c957d83dd83c0e48f3`; source `#107` closed.
- Source issue `atlas-memory#108` completed through UI mirror `Atlas-Memory-UI#10` / PR `Atlas-Memory-UI#11`; merge `baec29c9623a2da59e816482275fa0b4e026215a`; source `#108` closed.
- Source issue `atlas-memory#109` completed through UI mirror `Atlas-Memory-UI#12` / PR `Atlas-Memory-UI#13`; merge `d22e06abcac3957a86eb1e9c38aef0ef26b1d3f3`; source `#109` closed.
- Parent `atlas-memory#90` received a connector-backed `completion_review` bundle and was closed. The bundle covers semantic correctness, validation evidence, docs-not-needed rationale, garbage collection, and downstream readiness.

**Validation evidence for connector-backed UI PRs:**
- PR `#11` (`src/api/mockServer.ts`):
  - `npm ci`: passed, with pre-existing npm audit findings reported.
  - `npm run test -- workflow-intake-contract.test.ts`: failed as explicitly waived for this child because `#109` owned the test file and it was not on `main` yet.
  - `npm run test`: passed, `4 files / 25 tests`.
  - `npm run typecheck`: passed.
  - `npm run lint`: passed.
  - `npm run build`: passed with existing Vite chunk-size warning.
  - Connector-backed semantic review found and repaired missing `workspace_id` / `project_id` on context bundle mock records before merge.
- PR `#13` (`tests/workflow-intake-contract.test.ts`):
  - `npm run test -- workflow-intake-contract.test.ts`: passed, `1 file / 2 tests`.
  - `npm run test`: passed, `5 files / 27 tests`.
  - `npm run typecheck`: passed.
  - `npm run lint`: passed.
  - `npm run build`: passed with existing Vite chunk-size warning.
  - Validation waiver: none.

**Project/runtime state:**
- No active local runtime process was found except the current sandbox command itself.
- Project v2 fields are likely stale because Project reconcile is blocked by `gh` quota. Rerun reconcile after quota reset.
- Temporary UI checkout used for connector-backed work: `/tmp/atlas-ui-issue-10`.

**Next safe actions:**
1. After `gh` quota resets, run:
   - `./atlas-agent-project-reconcile --projects-file projects.txt --apply`
   - `./atlas-agent-workstream-review Atlas-Memory-Framework/atlas-memory#90 --apply --summary /tmp/ws90-review.json` if a runtime-native artifact is still desired, despite the connector-backed completion already being posted.
2. Do not promote `#74` until human Core authority signs off.
3. Continue Project #5 by selecting the next decomposed one-point leaves; avoid repo-wide PR sweeps and old Azure lane items.
4. If continuing cross-repo source issues, prefer target-repo mirror issues or add first-class source-issue/target-repo support to `atlas-agent-worker`.

## 2026-05-26 Runtime Audit Update: Ready Queue Is Not Dispatchable Yet

**Current phase:** Runtime work continued after a pause. No `atlas-agent-shift`, `atlas-agent-unattended`, `atlas-agent-project-reconcile`, `atlas-agent-workstream-review`, or worker process is currently running. Project #5 still has visible `status:ready` items, but the runtime dry-runs show they are not dispatchable worker lanes yet.

**Runtime fixes installed in active runtime:**
- `atlas-agent-workstream-review`: now handles cross-repo source issues by reading target-repo file evidence, collecting explicit linked PR URLs from child issue comments, excluding `agent:workstream-followup` issues from child collection, and preventing auto-ready follow-ups when a source issue points at a different target/execution repo.
- `atlas-agent-issue-decompose`: dry-run records now include `dispatch_blockers` and `dispatchable_after_decomposition`; planner prompt now asks for `status:blocked` children when parent dependencies/manual gates remain.
- `atlas_agent_common.py`: `AGENT_REPOS`, `AGENT_JOBS`, and `AGENT_LOGS` environment variables now override `config.env`, allowing safe temp-state tests and operator-directed runtime state.

**Invalid artifact cleanup:**
- A pre-patch runtime-native review of `atlas-memory#90` incorrectly looked for UI files/PRs in `atlas-memory`, created follow-ups `#536-#539`, and reopened/failed the parent.
- Follow-ups `#536`, `#537`, `#538`, `#539` were commented and closed as `not_planned` because they were invalid runtime artifacts from the pre-patch reviewer.
- A corrected non-mutating preview for `#90` showed semantic correctness, docs, and validation evidence now pass, but the interrupted preview should be rerun cleanly after Project updates settle before reapplying parent labels.

**Validation evidence:**
- `env AGENT_JOBS=/tmp/atlas-runtime-test-jobs PYTHONPATH=templates/local-automation-runtime .venv/bin/python -m pytest templates/local-automation-runtime/tests/test_workstream_review.py templates/local-automation-runtime/tests/test_issue_decompose.py templates/local-automation-runtime/tests/test_project_reconcile.py templates/local-automation-runtime/tests/test_review_agent.py templates/local-automation-runtime/tests/test_finalizer_review_gate.py templates/local-automation-runtime/tests/test_local_agent_autonomy.py`: `170 passed in 0.28s`.
- After the decomposition audit patch: `env AGENT_JOBS=/tmp/atlas-runtime-test-jobs PYTHONPATH=templates/local-automation-runtime .venv/bin/python -m pytest templates/local-automation-runtime/tests/test_issue_decompose.py templates/local-automation-runtime/tests/test_workstream_review.py templates/local-automation-runtime/tests/test_local_agent_autonomy.py`: `117 passed in 0.19s`.

**Queue dry-run evidence:**
- `./atlas-agent-orchestrator --once --dry-run --repos-file repos.txt --limit 80 --max-items 80 --max-per-repo 30 --require-one-point`: processed `0` issues; there are no open `agent:ready` issues in the configured repos.
- `./atlas-agent-orchestrator --once --dry-run --repos-file repos.txt --limit 120 --max-items 120 --max-per-repo 30 --require-one-point --auto-queue-label status:ready --auto-queue-max 80`: processed `0` issues. The visible `status:ready` items were rejected as tracking-only, dependency/manual gated, or multi-point.
- `./atlas-agent-issue-decompose --repos-file repos.txt --candidate-label status:ready --max 20 --summary /tmp/issue-decompose-ready-preview-2.json --dry-run --no-create-subissues`: first 20 `status:ready` issues were all `action: decompose`, but each had `dispatch_blockers: ["open-dependencies", "dispatch-recommendation:tracking-only"]` and `dispatchable_after_decomposition: false`.

**Important operator note:**
- Do not launch full unattended dispatch merely because Project rows say Ready. In current state, `agent:ready` is empty and `status:ready` is mostly parent/tracking readiness, not worker readiness.
- A broad `--apply --create-subissues` run for the first 20 parents was rejected by approval policy because another agent is also updating shared Project issues. Continue with non-mutating audits or request explicit user approval before large shared GitHub mutations.

**Next safe actions:**
1. Let the other Project-updating agent settle, then rerun `atlas-agent-issue-decompose` dry-run and count records where `dispatchable_after_decomposition: true`.
2. If there are true dispatchable decomposition candidates, create child issues in a small approved batch, not a broad 20-parent mutation.
3. Rerun `atlas-agent-orchestrator --dry-run --auto-queue-label status:ready --require-one-point`; only run unattended with `--publish --apply` after it previews actual one-point `agent:ready` issues.
4. Rerun clean runtime-native `atlas-agent-workstream-review Atlas-Memory-Framework/atlas-memory#90` after stale labels/project rows settle, then apply only if the corrected review passes.

## 2026-05-26 Project Update Audit: Queue Semantics Repaired, No Ready Dispatch

**Current phase:** User updated Project #5 and wants a new session to start from a clean audit. No dispatch, label mutation, merge, or Project mutation was performed in this audit.

**Local runtime/process state:**
- `pgrep -af '[a]tlas-agent-(shift|unattended|worker|project-reconcile|workstream-review|orchestrator|issue-decompose)'`: no runtime processes found.
- Worktree remains on branch `docs-runtime-update` with the existing runtime hardening changes in `templates/local-automation-runtime/` and `.codex/` handoff files.

**Project #5 snapshot:**
- Snapshot command: `gh project item-list 5 --owner Atlas-Memory-Framework --limit 300 --format json > /tmp/project5-items-20260526.json`.
- Total items: `115`.
- `AutomationState`: `Blocked` 103, `Done` 11, `Planned` 1.
- `IssueReady`: `Blocked` 111, `Ready` 3, `Draft` 1.
- `DispatchMode`: `manual-review` 104, `blocked` 7, `agent-ready` 3, unset 1.
- `DispatchRecommendation`: `tracking-only` 105, `review-before-dispatch` 7, `auto-dispatch` 3.
- `OnePRContract`: `No` 104, `Yes` 10, `N/A` 1.
- The only `IssueReady=Ready` rows are already completed items:
  - `atlas-memory#110` (`AutomationState=Done`)
  - `Atlas-Memory-UI#6` (`AutomationState=Done`)
  - `Atlas-Memory-UI#8` (`AutomationState=Done`)
- Several completed rows still carry `status:ready` labels (`atlas-memory#103`, `#104`, `#110`, `Atlas-Memory-UI#6`, `#8`), but they are not open dispatch candidates.

**Issue #74 status:**
- Project row for `Atlas-Memory-Framework/atlas-memory#74` is correctly non-dispatchable:
  - `AutomationState=Blocked`
  - `IssueReady=Blocked`
  - `DispatchMode=manual-review`
  - `DispatchRecommendation=tracking-only`
  - `BlockerType=manual+automation`
  - `BlockerReason=Core authority requires human review before dispatch` plus decomposition requirement
  - labels include `status:blocked`, `agent:decomposed`, and `agent:workstream-needs-human`
- Do not promote or dispatch #74 until the human Core authority gate is explicitly cleared.

**Runtime dry-run evidence after Project update:**
- `./atlas-agent-orchestrator --once --dry-run --repos-file repos.txt --limit 120 --max-items 120 --max-per-repo 30 --require-one-point`: processed `0` issues. No open `agent:ready` work exists in the configured repos.
- `./atlas-agent-orchestrator --once --dry-run --repos-file repos.txt --limit 120 --max-items 120 --max-per-repo 30 --require-one-point --auto-queue-label status:ready --auto-queue-max 80`: processed `0` issues.
  - Rejected atlas-memory `status:ready` rows `#49`, `#44`, `#17`, `#14`, `#12`, `#9`, `#6`, `#3` as manual-gated, tracking-only/review-before-dispatch, or multi-point.
  - Rejected UI `status:ready` rows `Atlas-Memory-UI#2` and `#1` because both are `points:5` and require decomposition.
- `./atlas-agent-issue-decompose --repos-file repos.txt --candidate-label status:ready --max 40 --summary /tmp/issue-decompose-ready-preview-latest.json --dry-run --no-create-subissues`: found 10 decomposition candidates.
  - 8 atlas-memory candidates are not dispatchable after decomposition because of manual/review/tracking blockers.
  - 2 UI candidates are clean decomposition candidates: `Atlas-Memory-UI#2` and `Atlas-Memory-UI#1`; both have `dispatchable_after_decomposition: true` in the dry-run summary.

**GitHub quota note:**
- Follow-up `atlas-agent-project-reconcile --dry-run` attempts hit `GraphQL: API rate limit exceeded for user ID 150743840` and did not produce reconcile summaries.
- Avoid more `gh project` calls until quota resets. The saved snapshot and runtime dry-runs above are the current evidence for the next session.

**Recommended next session startup:**
1. Wait for GitHub GraphQL quota to recover, then rerun only non-mutating checks first:
   - `./atlas-agent-orchestrator --once --dry-run --repos-file repos.txt --limit 120 --max-items 120 --max-per-repo 30 --require-one-point`
   - `./atlas-agent-orchestrator --once --dry-run --repos-file repos.txt --limit 120 --max-items 120 --max-per-repo 30 --require-one-point --auto-queue-label status:ready --auto-queue-max 80`
   - `./atlas-agent-issue-decompose --repos-file repos.txt --candidate-label status:ready --max 40 --summary /tmp/issue-decompose-ready-preview-latest.json --dry-run --no-create-subissues`
2. Treat Project queue semantics as repaired enough to trust: Project no longer advertises open dispatch-ready items. Do not add `agent:ready` broadly.
3. If the user wants to create work, start with a small approved decomposition batch for `Atlas-Memory-UI#1` and `Atlas-Memory-UI#2`, because they are the only current dry-run candidates marked `dispatchable_after_decomposition: true`.
4. Keep `atlas-memory#74` in human-review/blocked state until Core authority approval is explicit.
5. After any Project mutation, rerun Project reconcile and the dry-run queue checks before starting unattended operation.

## 2026-05-26 Rate-Limit Reduction Runtime Update

**Purpose:** Reduce GitHub Project v2 GraphQL usage and avoid expensive PR inference when Project evidence is already available locally.

**Implemented in template and installed active runtime:**
- Added reusable Project snapshot helpers in `templates/local-automation-runtime/atlas_agent_common.py`.
- Added `--project-snapshot` to:
  - `atlas-agent-project-reconcile`
  - `atlas-agent-issue-decompose`
  - `atlas-agent-review`
  - `atlas-agent-finalize`
  - `atlas-agent-unattended`
- `atlas-agent-unattended` now forwards `--project-snapshot` into project reconcile, decompose, review, and finalize stages.
- `atlas-agent-project-reconcile` can use a saved `gh project item-list` JSON snapshot for dry-run reads without calling Project v2 `field-list` or `item-list`.
- Snapshot dry-runs now default to no PR search (`--no-pr-lookup` behavior) so closed rows without explicit evidence do not trigger repeated `gh pr list --search` calls. Live/non-snapshot reconcile keeps PR lookup enabled by default.
- Added explicit completion evidence support in `atlas-agent-project-reconcile`:
  - Parses `Completion mode: direct-pr|mirror-pr|merge-group`.
  - Parses `Completed by:` PR URLs and `OWNER/REPO#N` refs.
  - Hydrates supported Project fields `CompletionMode`, `CompletedBy`, `ActivePR`, and `ReviewVerdict` from issue body evidence without searching linked PRs.
- `atlas-agent-workstream-review` now honors explicit `Completed by:` PR refs before broad PR search:
  - If child issue body has `Completed by:`, it fetches exactly those PRs with `gh pr view`.
  - It skips same-repo `gh pr list --search #issue` for those issues.
  - The workstream review prompt now includes `completion_mode` and `completed_by` per child.

**Validation:**
- `env AGENT_JOBS=/tmp/atlas-runtime-test-jobs PYTHONPATH=templates/local-automation-runtime .venv/bin/python -m pytest templates/local-automation-runtime/tests/test_project_reconcile.py templates/local-automation-runtime/tests/test_issue_decompose.py templates/local-automation-runtime/tests/test_unattended_loop.py templates/local-automation-runtime/tests/test_review_agent.py templates/local-automation-runtime/tests/test_finalizer_review_gate.py templates/local-automation-runtime/tests/test_workstream_review.py`: `141 passed in 0.18s`.
- Active runtime help verifies new flags:
  - `./atlas-agent-project-reconcile --help` shows `--project-snapshot` and `--pr-lookup | --no-pr-lookup`.
  - `./atlas-agent-issue-decompose --help` shows `--project-snapshot`.
  - `./atlas-agent-unattended --help` shows `--project-snapshot`.
- `./atlas-agent-issue-decompose --repos-file repos.txt --candidate-label status:ready --max 40 --summary /tmp/issue-decompose-ready-preview-snapshot-20260526.json --dry-run --no-create-subissues --project-snapshot /tmp/project5-items-20260526.json`: ran without Project v2 calls and returned no records for the saved snapshot.

**Important incident during validation:**
- A snapshot-backed `atlas-agent-project-reconcile` preview was started before `--no-pr-lookup` was added. It avoided Project v2 reads but still attempted REST-backed `gh pr list --search` for closed rows and hit the existing GraphQL throttle through `gh pr list`.
- The stuck sleeping process was killed. Final check found no `atlas-agent-*` runtime processes.
- Do not run old snapshot reconcile commands without `--no-pr-lookup` while GraphQL quota is tight.

**Next-session low-quota pattern:**
1. Take at most one Project snapshot per operator cycle after quota recovers:
   - `gh project item-list 5 --owner Atlas-Memory-Framework --limit 300 --format json > /tmp/project5-items-$(date -u +%Y%m%dT%H%M%SZ).json`
2. Reuse that snapshot for read-heavy stages:
   - `./atlas-agent-project-reconcile --projects-file projects.txt --dry-run --project-snapshot SNAPSHOT --no-pr-lookup --summary /tmp/project5-reconcile-snapshot.json`
   - `./atlas-agent-issue-decompose --repos-file repos.txt --candidate-label status:ready --max 40 --dry-run --no-create-subissues --project-snapshot SNAPSHOT --summary /tmp/issue-decompose-ready-preview.json`
   - `./atlas-agent-unattended --dry-run --repos-file repos.txt --projects-file projects.txt --project-snapshot SNAPSHOT --stages decompose,review,finalize,summary`
3. Add explicit completion evidence to source/tracking issues that are completed through mirror PRs or merge groups before relying on Project metadata:
   - `- Completion mode: \`mirror-pr\``
   - `- Completed by: https://github.com/OWNER/REPO/pull/NUMBER`
4. Keep full Project reconcile with live field metadata and PR lookup as a less frequent checkpoint, not the hot path.

## 2026-05-26 17:34 UTC Recheck After Rate-Limit Reset

**Quota / runtime state:**
- `gh api rate_limit` at `2026-05-26 17:33:12 UTC`: GraphQL `5000/5000`, REST core `5000/5000`.
- After one fresh Project snapshot and read-only dry-runs, GraphQL was `4785/5000`; REST core still `5000/5000`.
- No `atlas-agent-*` runtime processes were running before or after the check.

**Fresh Project snapshot:**
- Snapshot: `/tmp/project5-items-20260526T1733Z.json`.
- Project #5 remains `115` items.
- `AutomationState`: `Blocked` 103, `Done` 11, `Planned` 1.
- `IssueReady`: `Blocked` 111, `Ready` 3, `Draft` 1.
- Only `IssueReady=Ready` rows are already `Done`: `atlas-memory#110`, `Atlas-Memory-UI#6`, `Atlas-Memory-UI#8`.
- `atlas-memory#74` remains correctly blocked/manual-review/tracking-only with `agent:workstream-needs-human`.

**Read-only runtime checks:**
- `./atlas-agent-orchestrator --once --dry-run --repos-file repos.txt --limit 120 --max-items 120 --max-per-repo 30 --require-one-point`: processed `0`.
- `./atlas-agent-orchestrator --once --dry-run --repos-file repos.txt --limit 120 --max-items 120 --max-per-repo 30 --require-one-point --auto-queue-label status:ready --auto-queue-max 80`: processed `0`.
  - atlas-memory `status:ready` items remained rejected as manual-gated, review/tracking-only, or multi-point.
  - UI `status:ready` items `#1` and `#2` remained rejected as `points:5 requires decomposition before dispatch`.
- `./atlas-agent-issue-decompose --repos-file repos.txt --candidate-label status:ready --max 40 --summary /tmp/issue-decompose-ready-preview-20260526T1733Z.json --dry-run --no-create-subissues --project-snapshot /tmp/project5-items-20260526T1733Z.json`: returned no records for the saved Project snapshot.

**Snapshot reconcile preview:**
- `./atlas-agent-project-reconcile --projects-file projects.txt --limit 300 --dry-run --project-snapshot /tmp/project5-items-20260526T1733Z.json --no-pr-lookup --summary /tmp/project5-reconcile-snapshot-20260526T1733Z.json`: completed without Project v2 reads or PR lookup.
- It produced 44 dry-run decisions: 24 metadata hydration, 13 duplicate-source audit, 5 parent-size rollup, 2 blocked-audit decisions.
- Treat this as a cheap drift report, not an apply plan, because item-list snapshots do not include Project field metadata. Use a live reconcile with field metadata before applying Project mutations.
