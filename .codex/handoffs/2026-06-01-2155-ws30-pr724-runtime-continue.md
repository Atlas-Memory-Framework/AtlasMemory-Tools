# Handoff: WS30 Runtime Continue From PR #724

**Created:** 2026-06-01 21:55 UTC
**Project:** /run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory
**Runtime:** /home/mat/distrobox-homes/atlas-agent/agent-runtime
**Branch:** fix/mime-resolution-pins-mainline
**Purpose for next session:** continue after WS30 #716-#720 completion and find the next safe one-point runtime item.
**Continues from:** /run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.codex/handoffs/2026-06-01-1847-ws30-runtime-dispatch.md

## Current State

WS30 issues #716, #717, #718, #719, and #720 are merged and closed.

#719 `PROXY-CLI-SURFACE-001` completed via PR #724:

- PR: https://github.com/Atlas-Memory-Framework/atlas-memory/pull/724
- Issue: https://github.com/Atlas-Memory-Framework/atlas-memory/issues/719
- PR branch: `agent/issue-719/20260601T204303Z`
- PR worktree: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/checkouts/Atlas-Memory-Framework__atlas-memory/issue-719-20260601T204303Z`
- Latest pushed repair commit: `30c3bf1d0b362c16cbfad0a1bf70aa1ea05219a3`
- Merge commit: `f472b99f4d6e5f3035600d0c055df1081791a4be`
- PR merged at: `2026-06-01T21:57:10Z`
- Issue #719 closed at: `2026-06-01T21:57:11Z`

#724 originally failed semantic review because `atlas proxy attach` advertised session/work-item/run refs but non-run refs silently fell back to default workflow focus. I repaired this by failing closed for unsupported non-run refs and adding tests. The repaired head is pushed.

#720 `PROXY-ROLLBACK-REVIEW-001` completed via PR #725:

- Issue: https://github.com/Atlas-Memory-Framework/atlas-memory/issues/720
- PR: https://github.com/Atlas-Memory-Framework/atlas-memory/pull/725
- Branch: `agent/issue-720/20260602T014722Z`
- Merge commit: `02c1fffda4ae3a7f0bb20cf04750d3ee26c8ea76`
- PR merged at: `2026-06-02T02:08:54Z`
- Issue #720 closed at: `2026-06-02T02:08:55Z`
- Changed files:
  - `2 - implementations/2.1 - local/docs/atlas-proxy-tui.md`
  - `2 - implementations/2.1 - local/tests/test_atlas_proxy_command_allowlist.py`
  - `2 - implementations/2.1 - local/tests/test_atlas_proxy_no_external_mutation.py`
- PR #725 proved `/rollback` is outside the WS30 proxy command allowlist and receives deterministic non-mutation denial.

After #720 closed, `atlas-agent-orchestrator --dry-run` found no runnable one-point `status:ready`/`agent:ready` issues. It saw older ready-labeled issues such as #49/#44 and UI #1/#2, but they remain blocked by manual gates and/or multi-point decomposition requirements.

A broad `atlas-agent-dependency-promote --project-mode --dry-run` was started to find newly promotable work, but it scanned too broadly and was terminated manually. It was non-mutating (`--dry-run`), and no promotion decisions were reached before termination.

## Decisions

- **Fail closed for unsupported attach targets in #724**: first CLI slice should not pretend to attach to `proxy-session://...` or `work-item://...` until those refs are resolvable through the session/read-model path.
- **Keep main checkout untouched**: `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory` is behind and has unrelated local/untracked files, including `2 - implementations/2.1 - local/atlas_memory_local/operations/work_items.py`. Do not reset or overwrite it.
- **Use runtime PR worktrees for validation**: they track the PR branch and avoid the main checkout’s unrelated state.

## Changed or Important Files

- `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/checkouts/Atlas-Memory-Framework__atlas-memory/issue-719-20260601T204303Z/2 - implementations/2.1 - local/atlas_memory_local/__main__.py`: repaired `_atlas_proxy_attach_impl` to reject unsupported target refs; updated attach command docstrings to workflow/run refs.
- `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/checkouts/Atlas-Memory-Framework__atlas-memory/issue-719-20260601T204303Z/2 - implementations/2.1 - local/tests/test_atlas_proxy_tui.py`: added regression coverage for `session-1` and `work-item-1` attach rejection with no workflow client call.
- `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.codex/plans/atlas_core_local_first_workspace_operations_mvp_2026-05-21.plan.md`: canonical WS30 plan.

## Verification

- `.venv/bin/python -m pytest tests/test_atlas_proxy_tui.py tests/test_atlas_proxy_command_allowlist.py tests/test_atlas_proxy_no_external_mutation.py tests/test_proxy_session_attachment.py`: passed, `17 passed, 1 warning in 0.69s`.
- `env PYTHONPYCACHEPREFIX=/tmp/atlas-pr724-pyc python3 -m compileall -q .`: passed; only existing financeBench syntax warning.
- `./atlas-agent-local-validate Atlas-Memory-Framework/atlas-memory#724 --apply`: passed on head `30c3bf1d0b362c16cbfad0a1bf70aa1ea05219a3`.
- `./atlas-agent-semantic-review Atlas-Memory-Framework/atlas-memory#724 --apply`: failed only because `reliability-tests` was still `IN_PROGRESS`; no remaining implementation mismatch was reported.

## Open Questions and Blockers

- [ ] Find the next safe one-point item without relying on the stale markdown plan parser.
- [ ] Consider a narrower dependency-promotion query/script; the current `atlas-agent-dependency-promote --project-mode` pass is too broad for interactive operation.
- [ ] Carry user CLI feedback forward: `open`, `attach`, and `status` are acceptable. `next`, `work`, and `telemetry warnings` feel too bare/unclear and need clearer operator wording in a later UI/CLI refinement.

## Next Steps

1. Verify completed WS30 state if needed:
   ```bash
   cd /home/mat/distrobox-homes/atlas-agent/agent-runtime
   gh pr view 725 --repo Atlas-Memory-Framework/atlas-memory --json number,state,mergedAt,mergeCommit,url
   gh issue view 720 --repo Atlas-Memory-Framework/atlas-memory --json number,state,closedAt,title,url
   ```
2. Run a narrow next-item search. Avoid the stale plan parser for already-promoted WS30 items; issue body is the runtime contract.
3. If using dependency promotion, prefer a bounded/narrow query around candidate blocked issues rather than full Project mode, or run it as a long shift instead of an interactive step.

## User Testing Notes

Do not test from the main atlas-memory checkout right now. Test from the PR worktree:

```bash
cd /home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/checkouts/Atlas-Memory-Framework__atlas-memory/issue-719-20260601T204303Z
cd "2 - implementations/2.1 - local"
.venv/bin/python -m pytest tests/test_atlas_proxy_tui.py tests/test_atlas_proxy_command_allowlist.py tests/test_atlas_proxy_no_external_mutation.py tests/test_proxy_session_attachment.py
```

To inspect the current CLI contract without a live server:

```bash
sed -n '145,230p' tests/test_atlas_proxy_tui.py
sed -n '2125,2178p' atlas_memory_local/__main__.py
```

The TUI/CLI feedback checkpoint is now, before #720:

- Should top-level verbs be `open`, `attach`, `status`?
- Should bare `atlas` open the proxy shell, or should it require `atlas open`?
- Is `next` the right label for next safe action?
- Should `work` be `work`, `item`, `current`, or `focus`?
- Is `telemetry warnings` too technical for the operator surface?
- Is rejecting session/work-item attach targets acceptable for the first CLI slice, or should #720 prioritize resolving them?

## Context Notes

- The main local checkout is one commit behind and cannot fast-forward cleanly because of unrelated untracked `operations/work_items.py`. Leave it alone.
- GitHub API throttling happened earlier but later commands succeeded with normal runtime throttling delays.
- Use `python3`, not `python`, on this host.
- Runtime local validation currently uses `compileall`, so focused pytest evidence should be cited separately when relevant.
