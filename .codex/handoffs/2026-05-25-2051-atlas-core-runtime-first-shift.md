# Handoff: Atlas Core Runtime First Shift

**Created:** 2026-05-25 20:51 UTC
**Project:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
**Runtime:** `/home/mat/distrobox-homes/atlas-agent/agent-runtime`
**Purpose for next session:** Continue bounded Atlas Core runtime operation after PR #161 repair/validation and explicit plan issue decomposition.

## Current State

The runtime first shift completed without direct worker dispatch. PR #161 was repaired in place and locally validated. Explicit decomposition was run only against the approved current-plan issue refs `#74-#110`, `#140-#159`, and `#162-#171`.

Queue preview after the shift reports:
- `dispatch_blocked=false`
- `queueable_count=1`
- `blocked_count=58`
- only queueable source: `TOOLS-PROJECTION-001`

Do not requeue #110 without resolving the existing PR #161 path.

## Decisions

- **No duplicate worker PR for #110**: PR #161 already exists and is the active route.
- **No broad dispatch**: decomposition was allowed, but worker execution remained blocked.
- **No finalization of PR #161**: runtime required-check policy still expects GitHub checks for `atlas-memory`; GitHub reports no checks.
- **Runtime hotfixes applied**: installed runtime was patched so worker/repair containers mount the cached git repo and Tools checkout paths.

## Changed or Important Files

- `templates/local-automation-runtime/atlas-agent-worker`: added hook-disable and container mounts for cached gitdir plus read-only Tools paths.
- `templates/local-automation-runtime/atlas-agent-pr-repair`: added equivalent repair-container mounts and hook-disable behavior.
- `templates/local-automation-runtime/tests/test_local_agent_autonomy.py`: focused tests for worker/repair mount helpers and hook-disable behavior.
- Installed runtime copies updated:
  - `/home/mat/distrobox-homes/atlas-agent/agent-runtime/atlas-agent-worker`
  - `/home/mat/distrobox-homes/atlas-agent/agent-runtime/atlas-agent-pr-repair`
  - `/home/mat/distrobox-homes/atlas-agent/agent-runtime/atlas_agent_common.py`

## Verification

- Focused unit tests passed:
  `PYTHONPATH=templates/local-automation-runtime python3 -m unittest ...test_pr_repair... ...test_worker...`
- Installed `atlas-agent-pr-repair` syntax check passed via `compile(...)`.
- PR #161 repair pushed commit `bac4f02bc128332fb261b5fe6f20f0a38f4e967d`.
- PR #161 final state checked:
  - open draft
  - mergeable `MERGEABLE`
  - merge state `CLEAN`
  - label `agent:local-validation-passed`
- Local validation artifact:
  `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/pr-161-validate-20260525T195350Z`
- Decomposition summary:
  `/tmp/atlas-core-decompose-20260525T2010.json`
- Queue preview after decomposition still shows one queueable item and 58 blocked.

## Runtime Results

Explicit decomposition counts:
- `already-decomposed`: 3
- `decompose`: 56
- `mark-one-point`: 8
- records processed: 67
- created blocked child issues: `#172` through `#443`

Accounting mismatches needing planning review before dependency promotion:
- `#92`
- `#153`
- `#159`
- `#167`

## Open Questions and Blockers

- PR #161 cannot be finalized under current `required-checks.json` because `atlas-memory` requires GitHub checks (`reliability-tests`, `processing-heavy-tests`) and GitHub reports no checks.
- Created children are blocked and not project-metadata-hydrated here; Project v2 operations may still require refreshed `read:project`/`project` auth.
- Multi-repo caveat remains: plan projection includes `Atlas-Memory-Framework/atlas-memory` and `Atlas-Memory-Framework/Atlas-Memory-UI`; verify token access and project membership before any cross-repo apply/dispatch.

## Next Steps

1. Decide PR #161 path: either add/trigger required GitHub checks, adjust no-check policy for plan-only PRs, or keep it draft/local-validation-passed for human review.
2. Review decomposition accounting mismatches on `#92`, `#153`, `#159`, and `#167`.
3. Hydrate Project #5 metadata for newly created child issues once Project auth is confirmed.
4. Only after review/promotion, dispatch constrained parser-clean one-point children with `--require-one-point --dispatch-max-per-repo 1`.

## Context Notes

The scoped repo file used was `/tmp/atlas-core-runtime-repos.txt` containing only `Atlas-Memory-Framework/atlas-memory`.

No default `repos.txt` operation and no direct broad parent dispatch were used.
