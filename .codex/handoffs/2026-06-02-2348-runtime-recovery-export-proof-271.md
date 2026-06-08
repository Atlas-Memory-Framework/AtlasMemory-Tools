# Handoff: Runtime Recovery After Compact Failure, EXPORT-PROOF #271

**Created:** 2026-06-02 23:48 UTC
**Project:** `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory`
**Runtime:** `/run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime`
**Tools repo:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
**Project branch:** `fix/mime-resolution-pins-mainline`
**Tools branch:** `docs-runtime-update`
**Purpose for next session:** Resume runtime operation from the real stopping point after the prior interactive agent failed during remote compact/image tooling. The immediate recovery target is issue #271 / EXPORT-PROOF-001.3.
**Continues from:** `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.codex/handoffs/2026-06-02-2043-skillopt-children-complete-handoff.md`

## Current State

The newest durable project handoff in `atlas-memory` is stale. It stops at 2026-06-02 20:43 UTC after SkillOpt children #735-#741 completed. Runtime work continued after that:

- Fresh queue audit was written at `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.codex/queue-audits/2026-06-02-2046-fresh-m15-queue-audit.md`.
- #269 / PR #749 completed:
  - PR #749 merged at `2026-06-02T22:19:53Z`.
  - Issue #269 closed at `2026-06-02T22:19:54Z`.
  - Live issue labels include `agent:done`; Project status is `Done`.
- #270 / PR #750 completed:
  - PR #750 merged at `2026-06-02T23:20:20Z`.
  - Issue #270 closed at `2026-06-02T23:20:22Z`.
  - Live issue labels include `agent:done`; Project status is `Done`.
- #271 has only a non-publish worker dry-run:
  - Job: `/run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/issue-271-20260602T233304Z`
  - Checkout: `/run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/checkouts/Atlas-Memory-Framework__atlas-memory/issue-271-20260602T233304Z`
  - Branch: `agent/issue-271/20260602T233304Z`
  - Base: `ab6b845e` (`agent: address issue #270 (#750)`)
  - Patch is staged in that checkout and touches only:
    - `2 - implementations/2.1 - local/atlas_memory_local/backup_export.py`
    - `2 - implementations/2.1 - local/docs/backup-export.md`
    - `2 - implementations/2.1 - local/tests/test_backup_export.py`
  - Worker final response says validation passed with temporary `/tmp` deps: `12 passed in 0.04s`.
  - `git diff --cached --check` in the #271 checkout passes.

Live GitHub state for #271 at this handoff:

- Issue #271 is `OPEN`.
- Project status is `Todo`.
- Labels include `status:ready`, `agent:approved-dispatch`, `agent:failed`, `points:1`, and `agent:one-point`.
- No live PR was found or recorded for #271 during this investigation.

The user reported repeated remote compact failures:

```text
The model 'gpt-image-2' does not exist.
type: image_generation_user_error
param: tools
code: invalid_value
```

I did not find this exact error string in local project/runtime logs with fixed-string searches. Based on durable state, the error appears to have interrupted the interactive agent/session compaction after the #271 dry-run, not the runtime worker's implementation of #271.

## Decisions

- **Treat #271 as the recovery point, not #269/#270:** #269 and #270 are live-verified merged/closed/done.
- **Do not broad-dispatch:** #271 has mixed live labels (`agent:failed` plus ready/approved labels). Clean and audit that one issue before any publish.
- **Do not use image generation:** no project task here requires image generation; the `gpt-image-2` failure is a tooling/session failure to avoid, not a project requirement.
- **Preserve existing dirty worktrees:** both repos contain untracked or modified runtime artifacts. Do not run `git reset`, broad cleanups, or destructive checkout commands.

## Changed or Important Files

- `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.codex/queue-audits/2026-06-02-2046-fresh-m15-queue-audit.md`: authoritative post-20:43 audit through #270 completion.
- `/run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/issue-269-20260602T215018Z`: published worker job for PR #749.
- `/run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/issue-270-20260602T223659Z`: published worker job for PR #750.
- `/run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/issue-271-20260602T233304Z`: non-publish dry-run for #271, including `comment.md`, `diff.patch`, and staged checkout.
- `/run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/checkouts/Atlas-Memory-Framework__atlas-memory/issue-271-20260602T233304Z`: staged #271 patch ready for review/reuse.
- `/run/host/var/home/mat/Desktop/AtlasMemory-Tools/.codex/handoffs/2026-06-02-2348-runtime-recovery-export-proof-271.md`: this handoff.

## Verification

- `gh pr view 749 ...`: live PR #749 is merged; required checks succeeded.
- `gh pr view 750 ...`: live PR #750 is merged; required checks succeeded.
- `gh issue view 269 ...`: #269 is closed/done; Project status `Done`.
- `gh issue view 270 ...`: #270 is closed/done; Project status `Done`.
- `gh issue view 271 ...`: #271 is open with `agent:failed`, `status:ready`, and `agent:approved-dispatch`; Project status `Todo`.
- `find .../jobs/leases ...`: no active issue leases found.
- `find .../jobs/write-scope-locks ...`: no active write-scope locks found.
- `git diff --cached --check` in the #271 checkout: pass.
- Fixed-string searches for `gpt-image-2`, `image_generation_user_error`, and `remote compact task`: no local matches in checked project/runtime paths.
- `sqlite3` is not installed, so I did not inspect `goals_1.sqlite`.

## Open Questions and Blockers

- [ ] Why #271 has `agent:failed` despite a successful non-publish dry-run is not resolved. Treat it as a runtime state artifact until audited.
- [ ] Decide whether to reuse the staged #271 patch directly or rerun a clean worker publish after resetting issue labels/body/Project fields.
- [ ] Confirm no open PR exists for #271 immediately before publishing; live state can change.
- [ ] The reported `gpt-image-2` compact failure is not locally reproducible from logs. Avoid image-generation tools in the continuation.

## Next Steps

1. Work from the installed runtime:
   ```bash
   cd /run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime
   ```
2. Re-read live #271 and PR state with `gh issue view 271` and `gh pr list/search`; do not rely only on this handoff.
3. Clean/reconcile #271 before publish:
   - remove or account for `agent:failed`;
   - keep only one intended ready/approved item;
   - ensure body says `Open dependencies: none`, `Manual gates remaining: none`, and `Active PR: none`;
   - run issue-scoped Project reconcile dry-run and require `decisions: []`.
4. Review the existing #271 staged patch in:
   ```bash
   /run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/checkouts/Atlas-Memory-Framework__atlas-memory/issue-271-20260602T233304Z
   ```
5. If accepted, either publish through the runtime using the established one-issue flow or manually commit/open a PR only after recording why the runtime path is unsafe. The preferred path is the runtime flow.
6. After #271 PR exists, run the usual gates: scoped Project reconcile to PR Open, required checks, semantic review, runtime review, finalizer dry-run, finalizer apply, issue label cleanup, and post-merge queue dry-run.

## Context Notes

- Use `python3`, not `python`, on this host unless a temporary shim is deliberately prepared.
- GitHub and Project reads are live/networked; sandbox failures can be misleading.
- Do not dispatch closed/completed issues, blocked parents, parent/tracker issues, or stale ready labels.
- Do not run broad Project reconcile with PR lookup. Prefer issue-scoped reconcile/audit commands.
- Do not clear GitHub throttle state manually.
- The Tools repo has many existing modified/untracked runtime-template files from prior work; do not treat them as created by this handoff.
