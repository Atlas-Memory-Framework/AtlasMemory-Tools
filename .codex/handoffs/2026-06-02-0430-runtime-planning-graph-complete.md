# Handoff: Runtime Shift After PLANNING-GRAPH Chain

**Created:** 2026-06-02 04:30 UTC
**Project:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
**Runtime:** `/home/mat/distrobox-homes/atlas-agent/agent-runtime`
**Atlas repo:** `Atlas-Memory-Framework/atlas-memory`
**Base branch:** `fix/mime-resolution-pins-mainline`
**Continues from:** `.codex/handoffs/2026-06-01-2155-ws30-pr724-runtime-continue.md`

## Current State

The local automation runtime was operated serially against Project 5. The previously blocked PLANNING-GRAPH-001 chain was safely promoted one child at a time after dependency review, dispatched, locally validated, semantically reviewed, CI-gated, finalized, merged, and closed.

Completed issues and PRs:

- #379 -> PR #727, merged `2026-06-02T03:05:11Z`, merge commit `f26585c43290a69d1d75c4d8676e49b08b2037b3`.
- #380 -> PR #728, merged `2026-06-02T03:26:10Z`, merge commit `a79c8042efa36f0f3b9d1fdaa6ea403dffcf822a`.
- #381 -> PR #729, merged `2026-06-02T03:46:27Z`, merge commit `ee6a118818a649afa621e77ebc0502aa9bd90284`.
- #382 -> PR #730, merged `2026-06-02T04:07:43Z`, merge commit `a90f7ba00b5fbb2c81bd102281583be5ce85c12c`.
- #383 -> PR #731, merged `2026-06-02T04:27:04Z`, merge commit `8971f33d1d09a52d3948be69ff3c7c0d7f7420ec`.

The queue dry-run after #383 initially showed no runnable items. Parent #155 remains open as a decomposed parent; a scoped Project metadata repair was applied, but it was not closed or converted into an execution issue.

## Decisions

- **Promoted PLANNING-GRAPH children #379-#383 one at a time**: This preserved one-PR discipline and avoided concurrent worktree/test collisions.
- **Passed the manual planning graph authority gate per child only**: The upstream `PG-REPOS-001` and `PG-LEDGER-001` gates were already closed; each audit comment scopes the pass to that child only.
- **Added `agent:allow-infra` on promoted children**: Runtime policy required it because inherited metadata contains `auth`; this was not approval for broader infra/auth/UI/migration work.
- **Did not promote #384**: #384 is blocked by `ATLASFS-SUBSTRATE-001`, `ARTIFACT-PATH-001`, and `filetree projection conflict-policy review required`.
- **TUI product stance**: First `atlas` / `atlas proxy` operator surface should be read/status/navigation with safe service controls only. Browser Workbench and five-view visualizer are important, but should stay outside the hard M1.5 gate unless the user explicitly changes the gate.

## Verification

- Runtime finalizer was used for all merged PRs with:
  - `--issue <issue>`
  - `--required-checks-file required-checks.json`
  - `--require-review-label agent:semantic-review-passed`
  - `--check-dependencies`
  - `--merge --close-issues`
- Required GitHub checks passed before each merge:
  - `processing-heavy-tests`
  - `reliability-tests`
- Local validation artifacts:
  - PR #727: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-727-validate-20260602T025407Z`
  - PR #728: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-728-validate-20260602T031346Z`
  - PR #729: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-729-validate-20260602T033313Z`
  - PR #730: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-730-validate-20260602T035411Z`
  - PR #731: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-731-validate-20260602T041913Z`
- Semantic review artifacts:
  - PR #727: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-727-semantic-review-20260602T030121Z`
  - PR #728: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-728-semantic-review-20260602T031411Z`
  - PR #729: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-729-semantic-review-20260602T034434Z`
  - PR #730: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-730-semantic-review-20260602T040525Z`
  - PR #731: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-731-semantic-review-20260602T042505Z`
- Focused local tests run manually as needed in a temp venv:
  - #728: `tests/test_planning_graph.py` -> `10 passed`
  - #729: `tests/test_planning_graph.py` -> `14 passed`
  - #730: `tests/test_planning_graph.py` -> `19 passed`
  - #731: `tests/test_planning_graph.py` -> `24 passed`
- `compileall` passed for PR worktrees; only a pre-existing examples syntax warning appeared.

## Open Questions and Blockers

- [ ] #384 is the next nearby child but remains blocked by `ATLASFS-SUBSTRATE-001`, `ARTIFACT-PATH-001`, and a filetree projection conflict-policy manual gate.
- [ ] Parent #155 remains open/decomposed even though #379-#383 are closed. Decide whether parent closure/status is a manual planning action or should be handled by a parent-summary/project reconcile workflow.
- [ ] User-facing TUI decision still needs explicit confirmation if the user wants to override the recommended read-mostly first TUI.
- [ ] Hard M1.5 gate should remain the mandatory 136-point packet unless the user explicitly adds Workbench/browser comfort views to the hard gate.

## Next Steps

1. Do not dispatch #384 until its AtlasFS/artifact path dependencies and conflict-policy gate are verified closed.
2. Find the next M1.5 one-point child whose dependencies are actually closed, likely in AtlasFS/artifact path prerequisite lanes rather than PLANNING-FILETREE.
3. Run scoped issue inspection and Project reconcile only; avoid broad dependency-promotion sweeps.
4. If no safe one-point child exists, prepare a queue audit that names the exact blocking dependency chain toward #384 / planning bootstrap import.

## Context Notes

- Work from runtime path `/home/mat/distrobox-homes/atlas-agent/agent-runtime`, not the template directory.
- Use escalated `gh` commands; sandbox auth/network checks are misleading.
- Keep dispatch serialized with `--require-one-point --max-per-repo 1`.
- Do not start a broad unattended shift until the next lane is clearly stable.
- The Tools repo worktree is dirty from unrelated existing work on branch `docs-runtime-update`; do not revert those changes.
- Temp venv `/tmp/atlas-pr727-venv` was augmented with `fastapi` and `uvicorn` for PR #731 focused tests.
