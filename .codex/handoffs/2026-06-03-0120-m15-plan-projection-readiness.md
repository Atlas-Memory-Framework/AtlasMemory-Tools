# Handoff: M1.5 Plan Projection Readiness Review

**Created:** 2026-06-03 01:20 UTC
**Project:** `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory`
**Project branch:** `fix/mime-resolution-pins-mainline`
**Tools repo:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
**Tools branch:** `docs-runtime-update`
**Purpose for next session:** Thoroughly review the amended M1.5 plan, make it ready for safe issue projection, and keep dispatch blocked until projection/recount/review explicitly passes.
**Continues from:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools/.codex/handoffs/2026-06-02-2348-runtime-recovery-export-proof-271.md` for unrelated runtime recovery context only.

## Current State

The selected authoring artifact is:

`/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.codex/plans/atlas_core_local_first_workspace_operations_mvp_2026-05-21.plan.md`

It has uncommitted local edits. These edits were made after the user clarified that M1.5 cannot be satisfied by importing the old markdown plan. Atlas must build a native planning workflow/team that consumes a baseline evidence package, replans inside Atlas, exposes Workflow State, and produces a human-promoted candidate planning revision.

No GitHub issue, Project, PR, worker queue, runtime dispatch, or completed issue was mutated by these plan edits.

Fresh parser dry-run after the review-fix amendment:

- `preflight_ok=True`
- `children=123`
- `suggested_points=500`
- `dispatch_blocked=True`
- `unresolved_blockers=3`
- New/split leaves parse as `tracking-only`, `issue_ready=False`:
  - `PLANNING-REPLAN-WORKFLOW-001`
  - `PLANNING-REPLAN-TUI-001`
  - `WORKBENCH-FIVE-VIEW-READMODELS-001`
  - `FIVE-VIEW-LINEAGE-001`
  - `TOOLS-EXIT-001`

## Decisions

- **Import is evidence, not authority:** `PLANNING-BOOTSTRAP-IMPORT-001` creates a `BaselineEvidencePackage`; it does not by itself satisfy planning authority.
- **Native replanning is mandatory:** `PLANNING-REPLAN-WORKFLOW-001` runs the Atlas planning workflow/team and emits a candidate revision with open questions, alternatives, rejected alternatives, dependency/gate diffs, ready/blocked recompute, and trace envelopes.
- **Planning visibility is separate work:** `PLANNING-REPLAN-TUI-001` proves `atlas` / `atlas proxy` can inspect the planning workflow state without raw DB/JSON/GitHub Project lookup.
- **Five-view UI cannot be mock-only:** `WORKBENCH-FIVE-VIEW-READMODELS-001` adds backend read models before `FIVE-VIEW-LINEAGE-001` UI acceptance can pass.
- **Workflow State replaces the vague execution tab:** it must show agents/workers, workflow graph(s), runs, leases, failures, evidence/log refs, mirror backlog, and typed repair actions.
- **No dispatch:** queue gates now require `queueable_count=0` while closed/completed-issue filtering and M1.5 projection review remain unresolved.

## Changed or Important Files

- `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.codex/plans/atlas_core_local_first_workspace_operations_mvp_2026-05-21.plan.md`: amended M1.5 plan.
- `/run/host/var/home/mat/Desktop/AtlasMemory-Tools/.codex/handoffs/2026-06-02-2348-runtime-recovery-export-proof-271.md`: older runtime-recovery handoff for #271; keep separate from plan projection work.

## Verification

- `git diff --check -- .codex/plans/atlas_core_local_first_workspace_operations_mvp_2026-05-21.plan.md`: pass.
- `python3 skills/plan-to-issues/scripts/plan_to_issues.py --plan ... --repo Atlas-Memory-Framework/atlas-memory --strategy leaf-issues --dry-run`: pass, 123 children / 500 suggested points, dispatch blocked.
- Product tests were not run.
- No projection apply, issue mutation, Project mutation, queue apply, branch creation, PR creation, or dispatch was run.

## Open Questions and Blockers

- [ ] Projection dry-run/review must identify which existing open issues would update and which new issues would be created.
- [ ] Completed issues #110, #328, and WS30 #716-#720 must not be edited, reopened, queued, or used as current readiness evidence.
- [ ] New/split M1.5 leaves need projection review before they exist as GitHub issues.
- [ ] Dispatch remains blocked until runtime closed/completed issue filtering is repaired and a fresh reviewed child is explicitly promoted.
- [ ] Separate runtime recovery for #271 remains open and should not be mixed with this planning/projection review.

## Next Steps

1. Run a zero-context execution-readiness review of the amended plan, focused on projection readiness and dispatch safety.
2. Run `plan_to_issues.py --dry-run` and inspect issue mapping: existing issue updates versus new creates, completed issue touches, dependencies, gates, and dispatch metadata.
3. Patch the plan if the review finds stale approvals, unresolved dependencies, gate ids used as dependencies, UI mock loopholes, or any path that could queue completed work.
4. Only after review passes, prepare an explicit projection proposal: which existing open issues to update, which new tracking-only issues to create, and which completed issues are explicitly untouched.
5. Do not run apply-mode projection or dispatch without explicit user approval.

## Context Notes

- User is worried agents will do something lazy: importing markdown, drawing a fake graph, building mock UI, or treating GitHub Project fields as truth. Review against that failure mode.
- The desired M1.5 outcome is an Atlas-owned planning/workflow system, not a prettier report over the old plan.
- Planning may be an agent mode or attached workflow view; it does not have to be a separate tab.
- Workflow State is the operator monitoring surface for agents, workflow graph(s), leases, failures, evidence, mirror backlog, and repair actions.
- Browser UI is secondary to the local Atlas service/API/read models; TUI/proxy is the first visible proof.
- Static HTML, raw DTO dumps, GitHub Project rows, and backend-only hidden graph objects cannot satisfy M1.5.
