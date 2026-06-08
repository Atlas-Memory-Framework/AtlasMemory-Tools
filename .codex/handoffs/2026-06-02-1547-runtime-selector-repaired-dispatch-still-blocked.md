# Handoff: Runtime Selector Repaired, Dispatch Still Blocked

**Created:** 2026-06-02 15:47 UTC
**Project:** `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory`
**Runtime:** `/run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime`
**Tools repo:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
**Continues from:** `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.codex/handoffs/2026-06-02-1517-runtime-selection-repair-before-dispatch.md`
**Purpose for next session:** Continue M1.5 runtime operation only after creating or reviewing parser-clean one-point child work; do not queue stale closed issues or blocked parents.

## Current State

The runtime selector repair is implemented in the Tools source template and synced into the installed runtime. The repaired selector now uses sync-preview live issue metadata before queue classification and blocks would-be queueable children unless their matched live issue is `OPEN`.

No dispatch was started. Current live candidate audit found no open issues with both `status:ready` and `points:1`.

## Decisions

- **Live issue state is required for queueability**: A locally clean child is blocked when sync-preview has no live match, when the live match is not `OPEN`, or when existing live labels indicate completion.
- **Manifest `Issue ref` is a live-state anchor**: Manifest leaves now parse `Issue ref:` into `legacy_issue_repo` / `legacy_issue_number`, allowing sync-preview to match exact existing issues such as #716 even if plan path metadata changes.
- **Dispatch remains blocked**: The real plan still returns `queueable_count=0`; no queue apply, worker publish, branch creation, or PR creation is authorized.

## Changed or Important Files

- `/run/host/var/home/mat/Desktop/AtlasMemory-Tools/templates/local-automation-runtime/atlas-agent-plan-queue`: Adds live issue-state blocking and dry-run sync-preview use with fail-closed fallback.
- `/run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime/atlas-agent-plan-queue`: Synced installed runtime copy.
- `/run/host/var/home/mat/Desktop/AtlasMemory-Tools/skills/plan-to-issues/scripts/plan_to_issues.py`: Preserves `match.state` in sync-preview and parses manifest `Issue ref`.
- `/run/host/var/home/mat/Desktop/AtlasMemory-Tools/templates/local-automation-runtime/tests/test_runtime_template.py`: Adds selector regressions for closed ready child, completed closed child, blocked parent shape, and valid open one-point child.
- `/run/host/var/home/mat/Desktop/AtlasMemory-Tools/skills/plan-to-issues/scripts/test_plan_to_issues.py`: Adds sync-preview state and manifest `Issue ref` assertions.
- `/tmp/atlas-closed-issue-selector-proof.plan.md`: Temporary dry-run-only proof plan for stale #716.

## Verification

- `env PYTHONPATH=templates/local-automation-runtime python3 templates/local-automation-runtime/tests/test_runtime_template.py`: pass, 21 tests, 1 skipped.
- Installed runtime selector regression subset: pass, 4 tests.
- Installed full runtime template test: failed on pre-existing `atlas-agent-issue-decompose` template/runtime mismatch, unrelated to selector repair.
- Direct projection smoke: pass; sync-preview match summaries preserve `state`.
- Live `gh issue view 716`: #716 is `CLOSED` and still has stale ready/approved-dispatch labels.
- Proof dry-run against `/tmp/atlas-closed-issue-selector-proof.plan.md`: pass; `queueable_count=0`, blocked reason `live issue state CLOSED`, match `number=716`.
- Real plan dry-run with live access: pass fail-closed; `queueable_count=0`, `blocked_count=120`, `queueable=[]`, #716-#720 live matches are `CLOSED`.
- Narrow live candidate audit: `gh issue list --state open --label status:ready --label points:1` returned `[]`.

## Open Questions and Blockers

- [ ] No reviewed parser-clean one-point child is currently queueable.
- [ ] #726 remains a blocked `points:8` parent and must not be queued; decompose into reviewed one-point children first if SkillOpt work should proceed.
- [ ] The installed runtime still has unrelated template drift in `atlas-agent-issue-decompose`; resolve separately before treating the full installed template suite as clean.
- [ ] Broad Project reconcile with PR lookup remains unsafe/noisy; keep using issue-scoped audits and `--no-pr-lookup`.

## Next Steps

1. Decide the next M1.5 child lane to prepare, likely under planning import parity, AtlasFS workspace proof, trigger/timeline proof, async GitHub mirror proof, Tools exit parity, stuck-work repair proof, or Atlas-on-Atlas representability.
2. Create or identify a one-point child with `status:ready`, `points:1`, `Dispatch: agent-ready`, `Dispatch recommendation: auto-dispatch`, `Open dependencies: none`, `Manual gates remaining: none`, bounded write scope, validation command, and live `OPEN` issue state.
3. Run an issue-scoped project/body audit for that child before queue approval.
4. Only then run bounded runtime queue/apply; do not use #726 or any closed WS30 issue as a worker item.

## Context Notes

Use `python3`, not `python`. Use escalated `gh` or runtime commands for live GitHub reads because sandbox network failures are misleading. Do not run broad Project reconcile with PR lookup, queue apply, worker publish, branch creation, or PR automation until a specific reviewed one-point child is approved.
