---
name: local-automation-runtime-operate
description: "Operate the local automation runtime: queue issues, run bounded or unattended cycles, long shift supervision, review/validate/repair/finalize PRs, and summarize outcomes. Use when running issue-to-PR automation after setup."
---

# Local Automation Runtime Operate

## Purpose

Run the local GitHub issue-to-PR lane with explicit bounds, review gates, validation, repair, finalization, and summaries.
This skill owns operation of the `atlas-agent-shift` terminal program; there is no separate shift skill. The program is the durable supervisor wrapper, while this skill defines when and how an operator may use it.
Use `repos.txt` to add target repos; use another runtime only for isolation, secrets separation, or intentional concurrent lanes.
Run these commands from an installed runtime directory. Do not operate from `templates/local-automation-runtime/`
inside the tools repository; that path is source material and direct execution will create runtime state in the
template tree.

## Operator Roles

- Codex operator owns runtime host, secrets, worker execution, validation, repairs, finalization, and merges.
- Gemini operator may own planning, issue quality, semantic review notes, and readiness labels.
- Only one operator may run mutating flags at a time: `--apply`, `--publish`, `--merge`, or `--close-issues`.

## Operating Flow

1. Refresh repo/project state:
   - `./atlas-agent-reconcile --repos-file repos.txt --apply`
   - `./atlas-agent-project-reconcile --projects-file projects.txt --apply`
2. Preview queue eligibility:
   - `./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --dry-run`
3. Audit manual/dependency-gated items before queue approval:
   - Use `project-queue-audit` for items with `Manual`, `review-before-dispatch`, dependency, or blocker state.
   - Do not approve dispatch if issue body runtime fields and Project fields disagree.
4. Queue approved work:
   - `./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --apply --queue`
   - Add `--publish` only when eligible queued issues should immediately open draft PRs.
5. Run a bounded cycle:
   - `./run_e2e_chain.sh --cycles 1`
   - Add mutating flags only after preview looks correct.
6. Qualify the exact lane before unattended or long-shift operation:
   - Use `agent-harness-evals`.
   - Run one representative work item through dispatch, result ingestion, validation, independent review, truthful terminal state, and resumable evidence.
   - Compare accepted progress and operator attention with a direct supervised execution estimate.
   - Declare no-progress, repeated-blocker, repair, approval, time, and cycle stop thresholds before launch.
7. Run unattended cycles only after the canary passes:
   - `./atlas-agent-unattended --cycles 3 --dispatch-max-per-repo 2 --review-apply --post-cycle-summary`
8. Run a long bounded shift only after the lane earns long-shift readiness:
   - `./atlas-agent-shift --cycles 12 --max-minutes 480 --sleep-seconds 300 --publish --apply --review-apply --post-cycle-summary`
   - Use the shift wrapper for wall-clock limits, a supervisor lock, heartbeat/status JSON, and an exit handoff.
9. Review blockers:
   - `./atlas-agent-review --summary review.json`
   - `./atlas-agent-semantic-review OWNER/REPO#PR --apply`
10. Validate and repair:
   - `./atlas-agent-local-validate OWNER/REPO#PR --apply`
   - `./atlas-agent-deployed-validate OWNER/REPO#PR --apply`
   - `./atlas-agent-pr-repair OWNER/REPO#PR`
11. Finalize only when review approves:
   - `./atlas-agent-finalize --required-checks-file required-checks.json --merge --close-issues`

## Guardrails

- Keep cycles bounded with `--cycles`, `--dispatch-max-per-repo`, and per-stage repair/review/validation max and concurrency flags.
- For multi-hour operation, use `atlas-agent-shift` instead of treating a Codex chat or subagent as the durable supervisor.
- Do not start a long shift until one real item has passed the full canary. Stop after two consecutive no-progress cycles, the same blocker twice without new evidence, more than one repair of the same item, or any stale/nonterminal supervisor state after reconciliation.
- Stop when harness repair consumes more effort than the remaining direct task path. Preserve the candidate and route a direct supervised takeover instead of automatically refreezing and relaunching.
- Preserve exact-subject approvals where authority requires them. Do not ask again for an unchanged material decision merely because a wrapper, serialization, or internal hash changed without changing the effect envelope.
- Treat `Open dependencies:` and `Manual gates remaining:` as the runtime dispatch contract; Project fields are advisory unless they match the issue body.
- Keep unattended dispatch one-point only. Larger `points:N` issues must be decomposed or explicitly handled outside unattended dispatch.
- Treat no-check PRs as blocked unless local validation and required-check policy explicitly allow them.
- Do not repair failed workflows until `atlas-agent-review --apply` has classified the failure.
- For human-action, secret/config, infra/env, or dependency-blocked workflow classes, stop worker repair and hand the issue to the responsible operator.

## Subagents

- Delegate bounded side tasks only: inspect one PR, classify one log set, draft one repair plan, or review one handoff/status file.
- Do not delegate the runtime control loop. `atlas-agent-shift` owns the long-running loop, lock, heartbeat, and handoff.
- Require subagents to return changed files, commands run, validation results, blockers, and the next safe command.
- If a subagent works across more than one runtime cycle, require a handoff note before using its result.

## Output

Summarize:

- queued issues
- PRs opened
- review labels/routes
- validation results
- repairs attempted
- accepted progress units and terminal yield
- no-progress cycles, repeated blockers, and stale-state incidents
- approval prompts versus unique material decisions
- operator interventions and direct-execution comparison
- merged/closed items
- remaining blockers and owner actions
