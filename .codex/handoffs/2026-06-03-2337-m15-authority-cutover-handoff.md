# Handoff: M1.5 Atlas-Native Planning Authority Cutover

**Created:** 2026-06-03 23:37 UTC
**Project:** /run/host/var/home/mat/Desktop/AtlasMemory-Tools
**Runtime:** /run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime
**Runtime repo clone:** /run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime/repos/Atlas-Memory-Framework__atlas-memory
**Base branch:** `fix/mime-resolution-pins-mainline`
**Purpose for next session:** Keep the M1.5 cutover lane moving, with multiple safe parallel preparation lanes, after correcting the false "import old plan as authority" framing.
**Continues from:** /run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.codex/handoffs/2026-06-03-1429-m15-semantic-completion-agent.md

## Runtime Selection

Use `/run/host/var/home/mat/distrobox-homes/atlas-agent/agent-runtime` as the active runtime.

There is also a Desktop runtime at `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime` and old Tools-local state at `/run/host/var/home/mat/Desktop/AtlasMemory-Tools/local-automation-runtime-state`. Do not use either for current M1.5 work unless the operator explicitly switches runtimes. The Desktop runtime appears to be an older install/state directory: it has matching repo/project config, but its latest visible jobs are from `2026-06-03T13:16Z`, while the active distrobox runtime contains the current #773/#774 validation and semantic-review artifacts from `2026-06-03T22:xxZ` and `23:xxZ`.

## Current State

The operator corrected the core decision: Atlas must not import the old markdown plan as planning authority. Old/external plans, GitHub issues, GitHub Project fields, and AtlasMemory-Tools state are source evidence only. The target is Atlas-native planning authority that intakes evidence and replans it into Atlas-owned planning/work records and candidate revisions.

This decision has been recorded in live GitHub issue bodies:

- #751 `[PLANNING-BOOTSTRAP-IMPORT-001] Capture baseline evidence for Atlas-native replanning authority`
- #158 `[PLANNING-BOOTSTRAP-IMPORT-001] Reframe legacy plan evidence for Atlas-native planning authority`

Both #751 and #158 remain open, blocked, and tracking-only. Do not close them and do not clear their parent/manual gates without a fresh explicit human approval.

No open PRs remain in `Atlas-Memory-Framework/atlas-memory` or `Atlas-Memory-Framework/Atlas-Memory-UI` as of this handoff.

## Decisions

- **No direct plan import:** The old markdown plan is evidence, not authority. This replaces the misleading legacy interpretation of `PLANNING-BOOTSTRAP-IMPORT-001`.
- **#392-#396 are support evidence only:** They delivered parser/projection/dry-run/docs support. They do not complete #751/#158, do not approve markdown exit, do not persist authoritative planning graph records, and do not approve M1.5 switch-over.
- **Parent gates stay blocked:** #751/#158 must remain blocked until Atlas-native planning authority semantics and replanning workflow proof are explicit.
- **Issue body markers are dispatch authority:** Treat `Open dependencies` and `Manual gates remaining` as source of truth before dispatch. Avoid Project GraphQL except for minimal row repair when body/project agreement must be verified.
- **Conservative PR-producing dispatch:** Do not start multiple mutating runtime workers at once. The runtime shared worktree supports one `run_issue_publish.sh` mutating worker at a time.

## Completed This Session

- #396 was finished through PR #773.
  - PR #773 merged at `2026-06-03T22:24:26Z`.
  - Merge commit: `9fd3632bd4c48f020f266ba407efa220b15e3a97`.
  - #396 closed at `2026-06-03T22:24:27Z`.
  - Gates passed: focused pytest, dry-run projection, local validation, deployed validation, semantic review, `processing-heavy-tests`, `reliability-tests`.
- Corrected the authority wording after the operator clarified the intent.
  - Updated #751 and #158 issue bodies and comments with the operator authority correction.
  - Created #775 as a one-point docs correction issue.
  - PR #774 merged at `2026-06-03T23:32:19Z`.
  - Merge commit: `23364d24b5317378ff926845aa7590a4b1dc1fad`.
  - #775 closed at `2026-06-03T23:32:20Z`.
  - Gates passed: focused pytest, dry-run projection, local validation, deployed validation, semantic review, `processing-heavy-tests`, `reliability-tests`.

## Changed or Important Files

- `Atlas-Memory-Framework/atlas-memory:2 - implementations/2.1 - local/docs/planning-graph-filetree.md`
  - Now says bootstrap is evidence intake plus Atlas-native replanning preparation.
  - Explicitly says old plans/GitHub/Project/Tools state are evidence only.
  - Explicitly says parsing/projection/dry-run/docs do not approve authority, markdown exit, GitHub/Project mutation, or M1.5 switch-over.

Local runtime clone note:

- The runtime repo may still be on local branch `operator/m15-planning-authority-wording-20260603T2319Z` at commit `d35ab0c8`.
- PR #774 has been squash-merged remotely into `fix/mime-resolution-pins-mainline` as `23364d24`.
- First repo-edit step should be:
  - `git fetch origin fix/mime-resolution-pins-mainline`
  - `git switch fix/mime-resolution-pins-mainline`
  - `git pull --ff-only origin fix/mime-resolution-pins-mainline`

## Verification

- `gh pr list --repo Atlas-Memory-Framework/atlas-memory --state open`: no open PRs.
- `gh pr list --repo Atlas-Memory-Framework/Atlas-Memory-UI --state open`: no open PRs.
- #751: open, blocked, corrected authority wording.
- #158: open, blocked, corrected legacy authority wording.
- `tests/test_planning_bootstrap_import.py`: `11 passed` for both #773 and #774 validation.
- Plan-to-issues dry-run: `preflight.ok=true`, `children=124`.
- Runtime deployed validation for #774: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-774-deployed-validate-20260603T232749Z`.
- Runtime semantic review for #774: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-774-semantic-review-20260603T233048Z`.

Useful focused commands:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=".:../../3 - interfaces/core" /tmp/m15-755-pytest-venv/bin/python -m pytest --noconftest -p no:cacheprovider tests/test_planning_bootstrap_import.py
```

```bash
python3 /run/host/var/home/mat/Desktop/AtlasMemory-Tools/skills/plan-to-issues/scripts/plan_to_issues.py --plan "atlas-memory/.cursor/plans/atlas_core_local_first_workspace_operations_mvp_2026-05-21.plan.md" --repo "Atlas-Memory-Framework/atlas-memory" --strategy leaf-issues --dry-run
```

Temporary deployed validation config can be recreated as:

```json
{
  "Atlas-Memory-Framework/atlas-memory": [
    "gh pr checks \"$PR_NUMBER\" --repo \"$REPO\""
  ]
}
```

## Open Questions and Blockers

- [ ] #751 still has stale-looking closed dependencies in `Open dependencies`, but it is intentionally blocked by the new Atlas-native authority/manual gate. Audit before editing; do not accidentally mark ready.
- [ ] #158 is legacy authority and should eventually be reconciled with #751. Do not dispatch it directly.
- [ ] The canonical markdown plan likely still contains old `BootstrapImporter` language. Treat it as historical evidence until a deliberate plan amendment/replanning lane updates it.
- [ ] No dependency-clean PR-producing one-point child was available after #396/#775. Another queue review is needed before feeding the runtime again.

## Parallel Lanes For Next Agent

Run these in parallel as read-only or issue-only preparation lanes. Start PR-producing worker dispatch only after a fresh body-authority audit shows dependency-clean, non-overlapping one-point children.

1. **Queue/dependency audit lane**
   - Scope: M1.5 roots only.
   - Inputs: issue bodies, not Project GraphQL.
   - Roots to scan: #751/#158, OPS-WORKER-001, OPS-GITHUB-MIRROR-001, TRACE-MIN-ENVELOPE-001/provider-binding chain, WORKITEM-METADATA-001, WORKFLOW-DEFINITIONS-001, ATLASFS-PROMOTION-RECORDS-001, ATLASFS-CODEX-001/ATLASFS-TRIGGERS-001, WORKBENCH-FIVE-VIEW-READMODELS-001, PLANNING-REPLAN-WORKFLOW-001.
   - Output: dependency-clean one-point candidates with file scopes and overlap assessment.

2. **#751 authority decomposition lane**
   - Goal: draft one-point children that match the corrected decision, without clearing parent gates.
   - Candidate child themes:
     - Baseline evidence intake record shape for old/external plans as evidence, not authority.
     - Source provenance/checksum fixture expectations for old plan/GitHub/Tools evidence.
     - Atlas-native replanning handoff contract: evidence in, candidate planning/work records out, human promotion required.
     - Validation evidence cleanup for #392-#396 issue completion notes.
   - Do not create broad parent PRs. Prefer issue drafts first, then promote only one-point children.

3. **Stale authority cleanup lane**
   - Goal: reconcile #158 as legacy decomposition authority and #751 as the active parent.
   - Safe actions: issue comments/body clarifications, exact validation evidence rollups, workstream-review notes.
   - Unsafe without approval: closing #158, closing #751, removing blockers, marking `status:ready`.

4. **Downstream unblock map lane**
   - Goal: find which M1.5 chains are blocked only by stale markers versus real missing semantics.
   - Known body-blocked chains from this session:
     - TRACE-MIN-ENVELOPE #687-#689 blocked by `SEMANTIC-RESOLUTION-001; RUNTIME-PROVIDER-BINDING-001` plus trace/redaction gate.
     - Provider chain #699-#709 blocked by provider/account dependencies and redaction gate.
     - WORKITEM-METADATA #690-#692 blocked by `PLANNING-GRAPH-001; OPS-CONTROL-001; TRACE-MIN-ENVELOPE-001` plus authority gate.
     - WORKFLOW-DEFINITIONS #693-#695 blocked by WORKITEM-METADATA/OPS-WORKER plus workflow authority gate.
     - ATLASFS-PROMOTION-RECORDS #696-#698 blocked by ATLASFS-JOURNAL/TRACE-MIN plus trust-boundary gate.
     - WORKBENCH-FIVE-VIEW-READMODELS #754 blocked by workitem/workflow/trace/derived/replan dependencies plus read-model gate.
     - PLANNING-REPLAN-WORKFLOW #752 blocked by bootstrap/workflow/workitem/trace plus authority-promotion gate.

## Next Steps

1. Sync the runtime repo clone back to `fix/mime-resolution-pins-mainline` and verify no local changes.
2. Run a fresh M1.5-only issue body audit; do not use broad Project scans.
3. If no dependency-clean one-point PR lane exists, create issue drafts for #751 authority decomposition and exact validation evidence cleanup.
4. Report candidate lanes and file scopes before increasing concurrency.
5. Dispatch at most one PR-producing worker at a time until a clean cycle summary proves no overlapping write scopes, stale PR conflicts, or body/Project disagreement.

## Context Notes

- Do not drift into #271 or non-M1.5 export-proof work.
- Do not dispatch oversized parent issues directly.
- Do not revive "import the plan into planning graph" as the goal.
- Do not treat completed issue labels, merged PRs, static reports, raw DTO snapshots, UI-local mocks, GitHub Project fields, or filesystem-only proxy records as M1.5 readiness by themselves.
- GitHub and network commands usually need `sandbox_permissions: require_escalated`.
- Runtime global `deployed-validation.json` still lacks `atlas-memory`; use the temporary `gh pr checks` deployed-validation command file for atlas-memory PRs.
- Required checks for `Atlas-Memory-Framework/atlas-memory`: `processing-heavy-tests`, `reliability-tests`.
