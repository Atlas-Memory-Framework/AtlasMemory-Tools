# Handoff: Continue Atlas Memory Runtime To M1.5

**Created:** 2026-05-28 15:22 UTC
**Project:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
**Runtime repo checkout:** `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory`
**Branch:** `AtlasMemory-Tools` on `docs-runtime-update`; `atlas-memory` on `fix/mime-resolution-pins-mainline`
**Purpose for next session:** Continue running the Atlas Memory runtime toward `M1.5-AtlasOwnedExecutionCutover`, then verify completion and produce the switch-over packet. Do not claim v1/product readiness.
**Continues from:** Current session semantic/runtime audit on 2026-05-28.

## Current State

M1 is validated as an internal CLI/API proof milestone, not a product-complete release. Local `atlas-memory` is synced to `ac01c3ae99dd05aabeee65b260aee4dd1fb3833f`, the merge commit from PR #611.

M1 evidence:
- PR #611 merged: `Align empty context bundle test with trust contract`.
- Key M1 parent issues are closed, including:
  - `CORE-SEM-001` #74
  - `CORE-EVENTS-001` #75
  - `PG-SCHEMA-001` #76
  - `PG-REPOS-001` #77
  - `PG-LEDGER-001` #78
  - `STATE-ROOT-001` #98
  - `WORKSPACE-LEASE-001` #99
  - `INTAKE-API-001` #79
  - `CONTEXT-BUNDLE-001` #80
  - `TRUST-BUNDLE-001` #81
- `CANARY-INTAKE-001` #95 remains open/blocked. It is WS8/M2+ evidence, not M1 evidence.

Active execution Project is **Atlas-Memory-Framework Project #5**: `Atlas Core Local-First Workspace Operations MVP Execution`.
Do not confuse it with Project #2, which is the older Azure delivery board.

Post-cleanup repo queue labels:
- open `agent:ready`: 0
- open `agent:approved-dispatch`: 0
- open `agent:pr-open`: 3 (`#6`, `#9`, `#17`, each has a real open PR)
- open `agent:failed`: 1 (`#3`)

Project #5 final readback after reconciliation:
- total items: 115
- `AutomationState`: `Blocked=104`, `Done=10`, `Planned=1`
- Project board `Status`: `Done=22`, `Todo=93`

The 93 `Todo` rows are mostly blocked/manual/tracking Project rows. They are not an unattended queue. The runtime dispatch truth is issue body fields (`Open dependencies`, `Manual gates remaining`) plus labels/PR/check evidence, not Project board position alone.

## Decisions

- **M1 is accepted with scope limits**: It proves CLI/API/core local behavior and deterministic storage paths. It does not complete M1.5, M2, M3, v1, UI acceptance, old-system demotion, or product readiness.
- **Project #5 is a mirror/signal layer**: Issue bodies and PR/check evidence remain authoritative for dispatch. Project fields were hydrated to reduce misleading stale/manual state but are not planning truth.
- **No new work was dispatched**: Queue remains intentionally empty (`agent:ready=0`, `agent:approved-dispatch=0`).
- **M1.5 must stop for human switch-over approval**: Even after the packet is complete, do not demote GitHub Project #5 or AtlasMemory-Tools from the hot path without explicit human approval.
- **Duplicate SourceId Project rows are audit blockers, not deletion targets**: Parent/child mirror duplicates remain visible. The reconciler marked them blocked/human-action where appropriate rather than deleting Project rows.

## Changes Made This Session

GitHub issue label cleanup:
- Removed stale `agent:approved-dispatch` from open multi-point Atlas issues:
  - #3 `[WS1-B] Local workflow control-plane runtime and persistence`
  - #6 `[WS4-A] Backend operator contract freeze`
  - #9 `[WS3-B] Local drafting runtime and dual-artifact emission`
  - #12 `[WS3-C] Retrieval and verification integration`
  - #14 `[WS3-D] Drafting tests and merge blockers`
  - #17 `[WS2-G] SSOT documentation and launch gating`
- Preserved `agent:pr-open` on #6, #9, and #17 because PRs #71, #70, and #66 are still open.

GitHub Project reconciliation:
- Ran `atlas-agent-project-reconcile` against Project #5 with `--hydrate-metadata --apply --no-pr-lookup`.
- Hydrated stale Project #5 metadata, including many `AutomationState=Done` M1 rows and `AutomationState=Blocked` future/manual rows.
- Cleared parent rollup `Size` on decomposed rows where the reconciler considered child items authoritative.
- Marked duplicate SourceId/Project disagreement rows as blocked/human-action via Project fields rather than deleting rows.

Local checkout:
- Fast-forwarded `atlas-memory` to `origin/fix/mime-resolution-pins-mainline` at `ac01c3ae99dd05aabeee65b260aee4dd1fb3833f`.
- No tracked local changes remain in `atlas-memory`; only pre-existing untracked `.cursor/plan-runs/...`.
- `AtlasMemory-Tools` has no tracked changes apart from this handoff; `.codex/` is untracked.

## Verification

Run from `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory`.

M1 intake/API/CLI focused gate:
```bash
cd "2 - implementations/2.1 - local"
env PYTHONPATH='/tmp/atlas-pg-schema-testdeps:/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/3 - interfaces/core:/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/2 - implementations/2.0 - modules/atlas_memory_processing_modules/src' \
  python3 -m pytest tests/test_intake_context_bundle.py tests/test_context_bundle_trust.py tests/test_workflow_cli.py \
  -k 'intake or run_apply or replay or idempotency or trust' --maxfail=1 -q
```
Result: `59 passed, 173 deselected, 2 warnings`.

M1 storage/ledger/state-root/lease focused gate:
```bash
cd "2 - implementations/2.1 - local"
env PYTHONPATH='/tmp/atlas-pg-schema-testdeps:/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/3 - interfaces/core:/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/2 - implementations/2.0 - modules/atlas_memory_processing_modules/src' \
  python3 -m pytest tests/test_workspace_ledger.py tests/test_semantic_events.py tests/test_state_root_layout.py tests/test_backup_export.py tests/test_workspace_leases.py tests/test_runtime_safety_reuse.py \
  --maxfail=1 -q
```
Result: `60 passed, 10 skipped, 3 warnings`.

Core semantic kernel:
```bash
cd "3 - interfaces/core"
env PYTHONPATH=/tmp/atlas-pg-schema-testdeps python3 -m pytest tests/test_semantic_kernel -q
```
Result: `25 passed, 1 warning`.

Notes:
- The first intake/API/CLI run inside the sandbox failed on localhost socket creation. It passed when rerun outside the sandbox.
- `/tmp/atlas-pg-schema-testdeps` existed from prior validation and contains pytest/test dependencies. If missing, install dependencies in a controlled venv or recreate the shim; do not assume global Python has pytest.

## Important Files And Artifacts

- `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.cursor/plans/atlas_core_local_first_workspace_operations_mvp_2026-05-21.plan.md`: current plan and M1.5 scope. Key sections include `M1.5 Atlas-Owned Execution Cutover Stop`, `TOOLS-EXIT-001`, and `G-M15-SwitchOverPacket`.
- `/run/host/var/home/mat/Desktop/AtlasMemory-Tools/templates/local-automation-runtime/`: canonical runtime template. Do not operate directly from this path as a live runtime.
- `/tmp/atlas-project5-reconcile-dry.json`: dry-run summary from Project #5 reconciliation.
- `/tmp/atlas-project5-reconcile-apply.json`: apply summary from Project #5 reconciliation.
- Project #5: `https://github.com/orgs/Atlas-Memory-Framework/projects/5`
- Active repo: `Atlas-Memory-Framework/atlas-memory`

## Open Questions And Blockers

- [ ] Locate or install the actual live local automation runtime directory for Atlas. I did not find an installed Atlas runtime on the Desktop alongside `AtlasMemory-Tools`; only the template is present in this repo. Do not run long-lived automation from `templates/local-automation-runtime/`.
- [ ] Resolve `agent:failed` on issue #3 or classify it as intentionally historical before any queue expansion.
- [ ] Inspect open PRs #66, #70, and #71 tied to #17, #9, and #6. They are stale Project/PR-open state and may need human close/supersede/repair decisions.
- [ ] Project #5 still has duplicate SourceId audit blockers for parent/child mirror rows, including `CORE-SEM-001`, `TOOLS-PROJECTION-001`, and `UI-CONTRACT-001`. Do not delete rows without confirming the intended mirror model.
- [ ] M1.5 requires a full verification packet and human switch-over decision. No automatic demotion of GitHub Project #5 or AtlasMemory-Tools is authorized.

## Next Steps

1. Find or create an installed Atlas runtime host from the `AtlasMemory-Tools` template. Preserve local `config.env`, `repos.txt`, `projects.txt`, `jobs/`, `logs/`, `repos/`, and `codex-home/` if one already exists.
2. In the runtime host, configure:
   - `repos.txt`: `Atlas-Memory-Framework/atlas-memory`
   - `projects.txt`: `Atlas-Memory-Framework/5`
   - required checks/local validation JSON for `atlas-memory`
   - `ATLAS_TOOLS_ROOT=/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
3. Start with read-only/dry-run runtime checks:
   ```bash
   ./check_runtime.sh
   ./atlas-agent-reconcile --repos-file repos.txt --limit 700
   ./atlas-agent-project-reconcile --projects-file projects.txt --limit 500 --hydrate-metadata --dry-run --no-pr-lookup
   ./atlas-agent-triage --repos-file repos.txt
   ```
4. Do not dispatch broad Project rows. Only promote parser-clean one-point children whose issue body markers are safe:
   - `Open dependencies: none`
   - `Manual gates remaining: none`
   - `points:1`
   - no active PR conflict
   - Project/body labels agree after reconciliation
5. Use `project-queue-audit` before adding `agent:approved-dispatch` or `agent:ready` to anything.
6. Work toward M1.5 roots named in the plan:
   - `TOOLS-EXIT-001`
   - `PLANNING-BOOTSTRAP-IMPORT-001`
   - `ATLASFS-CODEX-001`
   - `ATLASFS-TRIGGERS-001`
7. At the M1.5 stop, verify the `G-M15-SwitchOverPacket` evidence, including:
   - planning import parity
   - queue parity
   - lease/claim proof
   - AtlasFS workspace proof
   - trigger/timeline proof
   - async GitHub mirror proof
   - Tools exit parity
   - stuck-work repair proof
   - Atlas-on-Atlas candidate-workspace representability proof
   - explicit human switch-over approval
8. Only after that packet is complete, ask the human whether to demote GitHub Project #5 / AtlasMemory-Tools from hot path to mirror/adapter.

## Context Notes

- Use GitHub CLI outside the sandbox when Project v2 reads/writes are required. The keyring-backed `gh` auth worked when escalated; sandboxed `gh` saw an invalid token file.
- Keep GitHub API throttle behavior enabled. Project writes are slow by design.
- Do not interpret Project `Todo` as dispatchable. It is board flow only.
- Do not use `agent:ready` or `agent:approved-dispatch` on multi-point parents or tracking-only rows.
- Do not claim M1.5, M2, M3, v1, or UI-backed product readiness from M1 evidence.
