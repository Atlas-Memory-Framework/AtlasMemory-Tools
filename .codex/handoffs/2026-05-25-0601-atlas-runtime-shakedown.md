# Handoff: Atlas runtime shakedown from AtlasMemory-Tools

**Created:** 2026-05-25 06:01 UTC
**Project:** /var/home/mat/Desktop/AtlasMemory-Tools
**Branch:** docs-runtime-update
**Purpose for next session:** Run the Atlas local automation runtime from the `atlas-agent` distrobox, starting with the bounded #110 shakedown after pulling latest and fixing auth/Project metadata.
**Continues from:** current Codex session in /var/home/mat/Desktop/AtlasMemory-Workspace

## Current State
The runtime is close, but not ready for broad product-code dispatch. `AtlasMemory-Tools` is clean and aligned with `origin/docs-runtime-update` at `052fcd4`. The plan repo `atlas-memory` was committed and pushed on branch `fix/mime-resolution-pins-mainline` at `78ec98c8` with the latest shakedown state.

The intended runtime host is `/var/home/mat/distrobox-homes/atlas-agent/agent-runtime` inside the `atlas-agent` distrobox. `projects.txt` there was changed to Project 5 (`Atlas-Memory-Framework/5`) with backup `projects.txt.bak-20260525T0525Z`.

Issue #110 is the only chosen first-run candidate. It is a meta/runtime-plan shakedown, not product implementation. It currently has `status:ready`, `agent:approved-dispatch`, and `agent:failed`; the runtime removed `agent:ready` after the failed run. Do not re-add `agent:ready` until Codex auth smoke passes.

## Decisions
- **Use #110 for first run:** It is bounded to the plan artifact and avoids dispatching product-code slices before decomposition quality is fixed.
- **Do not run a broad queue:** Old issues still have unsafe dispatch labels, and #103-#109 are not ready for autonomous work.
- **Use direct orchestrator for shakedown:** Prefer a one-issue `atlas-agent-orchestrator --once --publish` command over `run_e2e_chain.sh` until the queue is proven safe.
- **GitHub is projection only:** Atlas local runtime/state remains the intended authority; GitHub Project fields are operator metadata and must match issue body runtime fields before dispatch.

## Changed or Important Files
- `/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.codex/plans/atlas_core_local_first_workspace_operations_mvp_2026-05-21.plan.md`: updated and pushed with the latest Project metadata/rate-limit/auth state.
- `/var/home/mat/Desktop/AtlasMemory-Tools/templates/local-automation-runtime/atlas-agent-issue-decompose`: runtime template supports exact `--issue` decomposition targeting.
- `/var/home/mat/Desktop/AtlasMemory-Tools/templates/local-automation-runtime/atlas-agent-unattended`: runtime template supports `--decompose-issue` pass-through.
- `/var/home/mat/Desktop/AtlasMemory-Tools/templates/local-automation-runtime/atlas_agent_common.py`: runtime template has RFC3339/duration helpers and Project update support.
- `/var/home/mat/distrobox-homes/atlas-agent/agent-runtime`: installed runtime was patched to match the template for the above changes.
- `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/issue-110-20260525T052011Z/codex.log`: failed worker Codex auth log.

## Verification
- `atlas-memory`: `git diff --check` passed before commit; commit `78ec98c8` pushed.
- `AtlasMemory-Tools`: focused runtime template tests had passed earlier; repo is clean at `origin/docs-runtime-update`.
- Runtime dry-run confirmed only `Atlas-Memory-Framework/atlas-memory#110` would be processed.
- Runtime publish run reached the worker and created the isolated worktree, but no PR opened because Codex auth failed.
- Codex smoke test in runtime failed with `token_expired` / `refresh_token_reused` even though `codex login status` said logged in.

## Open Questions and Blockers
- [ ] Codex auth in `CODEX_HOME=~/agent-runtime/codex-home` must be refreshed interactively from inside `atlas-agent`.
- [ ] Pull latest before running the runtime, per user instruction.
- [ ] GitHub Project 5 field metadata is only partially repaired for the new children:
  - #103 and #104 received the full extended field hydrate.
  - #105-#110 received core safety fields (`Size`, `TargetRepo`, `ExecutionRepo`, `BaseBranch`, `AutomationState`, `IssueReady`, `DispatchMode`, `DispatchRecommendation`, `Workstream`, `OnePRContract`) but still need extended fields (`ItemType`, `ExecutionState`, `GateTier`, `ParentEpic`, `PlanKey`, `Priority`, `ReviewGates`, `Risk`, `RiskTags`, `SourceId`, `Validation`, `ValidationScope`, `WriteScope`).
  - The extended hydrate was stopped after GitHub GraphQL rate limit hit and the process started a 900s wait.
- [ ] #106-#109 intentionally expose a mismatch: `TargetRepo=Atlas-Memory-Framework/Atlas-Memory-UI`, `ExecutionRepo=Atlas-Memory-Framework/atlas-memory`. Keep them blocked until resliced or coordinated cross-repo mode is explicitly chosen.

## Next Steps
1. In the `atlas-agent` distrobox, from `AtlasMemory-Tools`, pull latest: `git pull --ff-only origin docs-runtime-update`. Also pull `atlas-memory` branch `fix/mime-resolution-pins-mainline` before runtime work.
2. Reauth Codex in the installed runtime:
   ```bash
   cd ~/agent-runtime
   CODEX_HOME="$PWD/codex-home" codex logout
   CODEX_HOME="$PWD/codex-home" codex login --device-auth
   CODEX_HOME="$PWD/codex-home" codex exec --ephemeral --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox "Reply with the single word ok."
   ```
3. After GitHub Project rate limit clears, finish Project 5 extended metadata for #105-#110. Regenerate summary if needed:
   ```bash
   cd ~/agent-runtime
   ./atlas-agent-project-reconcile --dry-run --projects-file projects.txt --limit 500 --summary /tmp/atlas-project5-reconcile-summary.json
   ```
   Then apply only #105-#110 extended metadata, or run a deliberate reconcile apply if broad Project row hydration is intended.
4. Requeue #110 only after Codex smoke and Project audit pass:
   ```bash
   cd ~/agent-runtime
   gh issue edit 110 --repo Atlas-Memory-Framework/atlas-memory --remove-label agent:failed --add-label agent:ready
   printf "%s\n" Atlas-Memory-Framework/atlas-memory > /tmp/atlas-memory-only-repos.txt
   ./atlas-agent-orchestrator --once --publish --repos-file /tmp/atlas-memory-only-repos.txt --require-one-point --max-items 1 --max-per-repo 1 --limit 50
   ```
5. If a PR opens, continue with `local-automation-runtime-operate`: review, validate, repair if needed, finalize. Do not dispatch #103-#109 yet.

## Context Notes
Use the `local-automation-runtime-operate` skill in the next session. Treat issue bodies as the runtime contract and Project fields as the operator view; dispatch requires agreement between both. Avoid `agent:approved-dispatch` scans because older issues have that label. For the first shakedown, scan only `agent:ready` and only with the one-repo repos file.
