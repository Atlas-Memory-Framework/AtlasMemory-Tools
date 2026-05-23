# Repo Duplicate Audit - 2026-05-11

Historical snapshot: this document records the local repo/runtime state as observed on 2026-05-11.
It is not the current runtime inventory. Use it for audit history only, then re-run local status checks
before making cleanup, normalization, or publication decisions.

No repositories were deleted or reset during this audit. No network fetch was performed; upstream status reflects the local tracking refs already present.

## Classification

| Path | Role | Remote | Branch / State | Dirty State | Recommendation |
| --- | --- | --- | --- | --- | --- |
| `/var/home/mat/Desktop/AtlasMemory-Tools` | Canonical tooling source | GitHub Atlas org, `AtlasMemory-Tools` | `main`, tracking `origin/main`, ahead 0 / behind 0 | Canonical skill source change, generated Cursor mirror change, new operational docs | Keep as canonical source; commit source + generated mirror + docs together when ready. |
| `/home/mat/distrobox-homes/atlas-agent/agent-runtime` | Local runtime host | Not a Git repo | Local runtime directory | Local config/state only | Keep as runtime host; do not treat as source repo. |
| Runtime `repos/<atlas-org>__Atlas-Memory-Azure` | Runtime-managed checkout | GitHub Atlas org, `Atlas-Memory-Azure` | `agent/issue-30/20260506T041042Z`, tracking origin, ahead 0 / behind 0 | 27 generated `.cursor` SSOT harness files; no other changes | Keep active runtime-managed. Decide whether Atlas repos vendor generated harness files; if yes, commit harness refresh in repo. |
| Runtime `repos/<atlas-org>__atlas-memory` | Runtime-managed checkout | GitHub Atlas org, `atlas-memory` | `agent/issue-17/20260505T232732Z`, ahead 1 / behind 1 | 27 generated `.cursor` SSOT harness files; branch divergence has one local-only commit and one remote-only commit | Promote/reconcile before automation cycles: inspect local commit `197a4871` vs remote `592b9efc`, then push/rebase/replace intentionally. |
| Runtime `repos/<atlas-org>__Atlas-Memory-Chainlit` | Runtime-managed checkout | GitHub Atlas org, `Atlas-Memory-Chainlit` | `codex/atlas-memory-forwarder-default-branch`, upstream gone, HEAD contained by `origin/main` | 27 generated `.cursor` SSOT harness files; no other changes | Keep checkout, archive/retire stale branch later. Normalize to default branch before next runtime use if no active PR depends on it. |
| Runtime `repos/<atlas-org>__Atlas-Memory-Admin-UI` | Runtime-managed checkout | GitHub Atlas org, `Atlas-Memory-Admin-UI` | `agent/issue-1/20260505T200905Z`, no upstream, HEAD contained by `origin/main` | 27 generated `.cursor` SSOT harness files; no other changes | Keep checkout, archive/retire stale branch later. Normalize to default branch before next runtime use if no active PR depends on it. |
| `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/checkouts/*` | Disposable job worktrees/checkouts | Inherited from parent runtime-managed repos | 26 registered worktrees | Dirty entries are `.validation-venv/` and Python bytecode in validation worktrees; issue worktrees checked were clean | Ignore for source decisions. Later prune with `git worktree remove` only after confirming no active logs/jobs need them. |
| `/var/home/mat/Desktop/foil boat/atlas-memory` | Removed test clone | GitHub Atlas org, `atlas-memory` | Removed after preservation | Useful engineering bridge work preserved elsewhere | Removed from `foil boat`; do not recreate repo clones there. |
| `/var/home/mat/Desktop/instablinds` | Non-Atlas target repo | `git@github.com:cemplex2/instablinds.git` | `main`, tracking origin, ahead 0 / behind 0 | Mixed project changes, deleted `package-lock.json`, generated `.codex/.claude` harnesses, many scaffold docs | Keep as non-Atlas target. Do not revert. Resolve `package-lock.json` deletion before product automation. |

## Disposable Worktree Details

Registered job checkouts:

- Admin UI: 2 issue worktrees, clean.
- Azure: 9 validation worktrees; dirty entries are `.validation-venv/` in several detached validation checkouts.
- Chainlit: 12 issue/validation/deployed-validation worktrees; dirty entries are `.validation-venv/` and Python `__pycache__` files.
- atlas-memory: 2 issue worktrees, clean.

These should not drive source-of-truth decisions. They can be pruned later, but not before confirming no active runtime job, log, or PR repair still references them.

## Recommended Next Actions

## Cleanup Applied

- Promoted the legacy/manual engineering bridge work into local branch `promote/engineering-bridge-20260511` in `/var/home/mat/Desktop/foil boat/atlas-memory`.
- Created local commit `47f7eaa5 feat: add local engineering bridge bootstrap`.
- Rebased the promotion onto default-branch SHA `142a028b` and preserved it as local branch `promote/engineering-bridge-20260511` at `f5e0c4e1` in the runtime-managed `atlas-memory` checkout.
- Created local backups under `.local-backups/atlas-memory-promotion-20260512/`:
  - `atlas-memory-engineering-bridge.bundle`
  - `0001-feat-add-local-engineering-bridge-bootstrap.patch`
- Removed the mistaken test clone at `/var/home/mat/Desktop/foil boat/atlas-memory`.
- Validated the promotion candidate outside the sandbox with `timeout 120s .venv/bin/python -m pytest tests/test_engineering_*.py`: 27 passed.
- Preserved the divergent runtime `atlas-memory` local-only head as `preserve/agent-issue-17-local-197a4871-20260511`.
- Normalized runtime `atlas-memory` back to its tracked base branch and fast-forwarded to the already-fetched origin ref.
- Normalized runtime Chainlit back to `main` and fast-forwarded to the already-fetched `origin/main`.
- Normalized runtime Admin UI back to `main`.
- Left runtime Azure on `agent/issue-30/20260506T041042Z` because that branch is active/tracked and not contained by another inspected local branch.
- GitHub push/PR publication was not performed; the approval guard requires explicit user approval before publishing this local branch to the external remote.

## Remaining Next Actions

1. Decide harness vendoring policy for Atlas runtime-managed repos.
   - If yes: commit the 27 generated `.cursor` harness files in each Atlas repo intentionally.
   - If no: leave them local or remove generated harness roots later through a deliberate cleanup, not ad hoc deletion.
2. Publish the promoted engineering bridge branch when explicitly approved.
   - Push `promote/engineering-bridge-20260511` from the runtime-managed `atlas-memory` checkout, or restore from the local bundle.
   - Open a PR against the intended `atlas-memory` base branch.
3. Resolve runtime Azure branch ownership.
   - Confirm whether `agent/issue-30/20260506T041042Z` still maps to an open PR or active issue before normalizing that checkout.
4. Prune disposable validation worktrees later.
   - Use `git worktree remove` from the parent checkout only after logs/artifacts are no longer needed.
