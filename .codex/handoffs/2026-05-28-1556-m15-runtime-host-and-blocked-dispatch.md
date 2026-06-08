# Handoff: M1.5 Runtime Host Installed, Dispatch Blocked

**Created:** 2026-05-28 15:56 UTC
**Project:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
**Runtime host:** `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime`
**Runtime repo checkout:** `/run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory`
**Branch:** `AtlasMemory-Tools` on `docs-runtime-update`; `atlas-memory` on `fix/mime-resolution-pins-mainline`
**Purpose for next session:** Continue M1.5 only after explicit blocker resolution. Do not dispatch workers or claim switch-over readiness from the current state.
**Continues from:** `.codex/handoffs/2026-05-28-1522-m15-runtime-continuation.md`

## Current State

Installed a dedicated Atlas local automation runtime host at `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime` from tracked `templates/local-automation-runtime` files only. The template itself was not used as live runtime state.

M1.5 has not been reached. The runtime is operational for dry-run/read-only checks, but the queue remains intentionally empty and all M1.5 root workstreams remain blocked by issue-body dispatch contracts.

Verified current queue labels after dry-run work:
- open `agent:ready`: 0
- open `agent:approved-dispatch`: 0

## Decisions

- **No dispatch labels applied**: Project/issue bodies still say `Issue ready: false`, `Dispatch mode: blocked`, non-empty `Open dependencies`, and non-empty `Manual gates remaining`.
- **No broad dependency promotion applied**: A full Project dependency-promotion preview expanded into hundreds of per-issue PR checks. It was stopped as unbounded for the current decision. Use targeted audits before any promotion.
- **M1.5 remains a hard stop, not a claim**: Current state is runtime-host-ready plus dispatch-blocked, not Atlas-owned execution cutover.

## Changed or Important Files

- `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime/config.env`: Atlas-only local runtime config. Repo is `Atlas-Memory-Framework/atlas-memory`; Project is `Atlas-Memory-Framework/5`; base branch is `fix/mime-resolution-pins-mainline`; `ATLAS_TOOLS_ROOT` points to this tools repo.
- `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime/repos.txt`: contains `Atlas-Memory-Framework/atlas-memory`.
- `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime/projects.txt`: contains `Atlas-Memory-Framework/5`.
- `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime/required-checks.json`: local policy has no required named checks and does not allow no-check merge.
- `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime/local-validation.json`: focused validation commands for Atlas core smoke gates.
- `/tmp/atlas-m15-decompose-dry.json`: bounded dry-run summary for the four M1.5 root issues.

## Verification

- `gh auth status` outside sandbox: passed for `AtlasMemory-Dev` with `repo`, `workflow`, and `project` scopes.
- `gh repo view Atlas-Memory-Framework/atlas-memory --json defaultBranchRef`: default branch is `fix/mime-resolution-pins-mainline`.
- `./check_runtime.sh` in runtime host: passed core prerequisites. Direct `playwright` and direct `podman` were reported missing, but `distrobox-host-exec` exposes host podman and the script printed `podman version 5.8.2`.
- `python3 -m unittest discover tests` in runtime host: `267 tests`, `OK`, `1 skipped`.
- `./atlas-agent-reconcile --repos-file repos.txt --limit 700`: read-only run completed.
- `./atlas-agent-project-reconcile --projects-file projects.txt --limit 700 --hydrate-metadata --dry-run --no-pr-lookup`: completed and found only stale metadata / duplicate SourceId / Project-body disagreements already known from the previous handoff.
- `./atlas-agent-triage --repos-file repos.txt`: no dispatchable issues; older open issues remain blocked by review/human/untrusted-author gates.
- `./atlas-agent-plan-queue --plan /run/host/var/home/mat/Desktop/AtlasMemory-Workspace/atlas-memory/.cursor/plans/atlas_core_local_first_workspace_operations_mvp_2026-05-21.plan.md --repo Atlas-Memory-Framework/atlas-memory --dry-run`: `queueable_count=0`, `blocked_count=104`.
- `./atlas-agent-issue-decompose --issue #145 --issue #158 --issue #148 --issue #149 --dry-run --no-create-subissues`: all four M1.5 roots are already decomposed and `dispatchable_after_decomposition=false`.

## M1.5 Root Audit

Bounded issue-list audit:
- `TOOLS-EXIT-001` #145: already decomposed; children #336, #337, #338 are one-point but blocked.
- `PLANNING-BOOTSTRAP-IMPORT-001` #158: already decomposed; children #392, #393, #394, #395, #396 are one-point but blocked.
- `ATLASFS-TRIGGERS-001` #148: already decomposed; children #349, #350, #351 are one-point but blocked.
- `ATLASFS-CODEX-001` #149: already decomposed; children #352, #353, #354, #355, #356 are one-point but blocked.

Sample body-contract blockers:
- #392: `Open dependencies: PLANNING-GRAPH-001; PLANNING-FILETREE-001; PLANNING-TEMPLATES-001`; `Manual gates remaining: bootstrap import review required before markdown exit`.
- #337: `Open dependencies: OPS-WORKER-001; OPS-GITHUB-MIRROR-001; OPS-VISUALIZER-001`; `Manual gates remaining: human review of Tools exit evidence required`.
- #350: `Open dependencies: ATLASFS-JOURNAL-001; OPS-CONTROL-001`; `Manual gates remaining: trigger dedupe/review policy approval required`.
- #352: `Open dependencies: ATLASFS-JOURNAL-001; HARNESS-SUPERVISOR-001; OPS-WORKER-001`; `Manual gates remaining: Codex runtime auth/smoke test required before live worker retry`.

## Open Questions and Blockers

- [ ] Decide whether the PM/human-in-loop role is allowed to clear specific manual gates in issue bodies, and under what recorded evidence standard. Do not infer this from the runtime config.
- [ ] Resolve or close the upstream dependencies named in the M1.5 child bodies before promotion/dispatch.
- [ ] Run `project-queue-audit` on any exact child before adding `agent:approved-dispatch` or `agent:ready`.
- [ ] Avoid full-project dependency promotion until it has a narrower candidate filter or operator accepts a long throttled scan.

## Next Steps

1. Pick one M1.5 child and run a full targeted queue audit against its issue body, Project fields, and dependency refs.
2. If the audit classifies it as `Ready`, apply `agent:approved-dispatch` and `agent:ready`, then run a bounded cycle.
3. If the audit remains `Blocked` or `Dependency-gated`, resolve the named upstream issue or manual gate first; do not bypass the issue-body contract.
4. Once a child PR exists, use review, local validation, repair, and finalize gates before considering the next child.

## Context Notes

- The runtime writes local state under `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime/jobs`, `logs`, `repos`, and `codex-home`; keep these out of the tools repo.
- The previous handoff's M1 validation remains valid. This handoff only adds runtime-host setup and M1.5 blocked-dispatch evidence.
- No tracked source changes were made in `atlas-memory`.
