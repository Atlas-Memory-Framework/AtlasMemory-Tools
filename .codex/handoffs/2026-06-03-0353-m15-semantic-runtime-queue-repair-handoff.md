# Handoff: M1.5 Semantic Runtime Review + Queue Repair

**Created:** 2026-06-03 03:53 UTC
**Project:** `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory`
**Project branch:** `fix/mime-resolution-pins-mainline`
**Tools repo:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
**Tools branch:** `docs-runtime-update`
**Runtime host:** `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime`
**Purpose for next session:** Continue M1.5 semantic fulfillment without dispatching tracking-only issues. Use the repaired runtime queue bridge, review/report the semantic findings, and route any canonical plan wording changes through `$plan` or explicit user approval.
**Continues from:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools/.codex/handoffs/2026-06-03-0332-m15-post-projection-local-agent-runtime.md`

## Current State

The local plan-agent runtime dry-run was started for:

`/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.cursor/plans/atlas_core_local_first_workspace_operations_mvp_2026-05-21.plan.md`

Run directory:

`/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.cursor/plan-runs/m15-post-projection-semantic-runtime-2026-06-03T033943Z`

Snapshot SHA:

`e0350b84ae7696172999453d03ac0e8cea77ddba176e364773448b674f80663a`

Manager report:

`/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.cursor/plan-runs/m15-post-projection-semantic-runtime-2026-06-03T033943Z/run-report.md`

The semantic dispatch decision is stable: **none** of the named candidates is dispatchable next. `PLANNING-BOOTSTRAP-IMPORT-001` is first in semantic sequence, but it is still a blocked, 5-point, manual-review/decomposition-required item.

Live issue mapping verified:

- `PLANNING-BOOTSTRAP-IMPORT-001` -> `Atlas-Memory-Framework/atlas-memory#751`, open, `status:blocked`, `points:5`, `decomposition:required`.
- `PLANNING-REPLAN-WORKFLOW-001` -> `#752`, open, `status:blocked`, `points:3`, `decomposition:required`.
- `PLANNING-REPLAN-TUI-001` -> `#753`, open, `status:blocked`, `points:2`, `decomposition:required`.
- `WORKBENCH-FIVE-VIEW-READMODELS-001` -> `#754`, open, `status:blocked`, `points:3`, `decomposition:required`.

## Decisions

- **No dispatch:** Queue apply, worker publish, shift apply/publish, and PR creation remain blocked for #751-#754.
- **Runtime bridge repair was appropriate and completed:** The installed runtime script now uses live issue state from sync-preview and fails closed on closed/completed issue matches.
- **Dry-run plan runtime remains non-authoritative:** Sub-agents proposed/reviewed only. No canonical plan edits were made.
- **Semantic next work is decomposition/design, not parent execution:** The useful future slice is a one-point `BaselineEvidencePackage v0` contract/fixture canary with read-only source evidence, quarantine, checksums, idempotency, and generated fixture expectations.

## Changed or Important Files

- `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime/atlas-agent-plan-queue`: updated from the repaired Tools template to include live issue state queue blockers.
- `/tmp/atlas-agent-plan-queue.before-m15-live-state-repair`: backup of the previous installed runtime bridge.
- `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.cursor/plan-runs/m15-post-projection-semantic-runtime-2026-06-03T033943Z/run-report.md`: manager reconciliation report.
- `/run/host/var/home/mat/Desktop/AtlasMemory-Tools/templates/local-automation-runtime/atlas-agent-plan-queue`: source template used for runtime repair; already had the repaired live-state logic before this session.

## Verification

- `./atlas-agent-plan-queue --plan ... --repo Atlas-Memory-Framework/atlas-memory --dry-run`: pass; `queueable_count=0`, `blocked_count=123`.
- `./check_runtime.sh` with network/keyring access: pass for GitHub auth, Podman, and Codex home isolation.
- `gh issue view 751..754 --repo Atlas-Memory-Framework/atlas-memory --json number,state,title,labels`: pass; all four are open but blocked/decomposition-required.
- Runtime bridge SHA check: installed runtime script matches Tools template SHA `b4d126f6e5ad5ba59da9449eb0f6ea1b07b692ee9e7f325da0bfe73abdbfec5f`; previous backup SHA `3a0f761adf82b37efc2c514681328459b1de827a0f24bd3f1df5c3df3fcf878b`.
- `PYTHONPYCACHEPREFIX=/tmp/atlas-pycache-m15 python3 -m py_compile ...`: pass.
- Synthetic terminal issue tests: pass for closed issue rejection and terminal-label rejection.

## Open Questions and Blockers

- [ ] Canonical plan still needs `$plan`-routed clarification: stale current-status prose, #751-#754 mapping table, and bootstrap plan path marked read-only evidence.
- [ ] User decisions remain for future plan intent: trace/export eligibility deny-by-default, switch-over evidence manifest requirement, M1.5 local contract epoch, trace split, early planning/workflow read-model canary, and bootstrap import sequencing.
- [ ] No one-point child is approved or queueable.
- [ ] The sub-agent JSON outputs were returned via chat notifications but not persisted as validated proposal JSON files in `proposals/`; the run report is the durable manager summary.

## Next Steps

1. Route a narrow `$plan` edit or request explicit approval to update non-protected prose:
   - mark #751-#754 as current tracking-only projections,
   - add the live leaf-id/issue mapping table,
   - clarify that the canonical markdown plan is read-only baseline evidence for bootstrap import.
2. Rerun read-only queue preview after any plan wording reconciliation:
   - `cd /run/host/var/home/mat/Desktop/Atlas-Automation-Runtime`
   - `./atlas-agent-plan-queue --plan /run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.cursor/plans/atlas_core_local_first_workspace_operations_mvp_2026-05-21.plan.md --repo Atlas-Memory-Framework/atlas-memory --dry-run`
3. Do not run `--apply`, `--queue`, `--publish`, `atlas-agent-shift --apply`, `atlas-agent-shift --publish`, or worker PR creation for #751-#754.
4. If the user approves future decomposition, create/review a one-point `BaselineEvidencePackage v0 contract/fixture` child before any importer persistence or native replan work.

## Context Notes

User preference remains semantic fulfillment over issue checkbox completion. Bad work here would be dispatching broad parents, importing markdown as authority, using UI mocks/static reports/raw DTOs as proof, or treating Project fields as truth. Good work moves Atlas toward native planning authority, observable Workflow State, explicit evidence manifests, and human switch-over control.
