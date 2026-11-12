---
name: local-automation-runtime-operate
description: "Operate an installed local automation runtime for local work queues or issue-to-PR campaigns: bounded cycles, continuous outer supervision, recovery, validation, independent review and handoff. Use after runtime selection and setup; unattended operation requires qualification of that exact lane."
---

# Local Automation Runtime Operate

## Supervised daily lane first

For a Tools checkout using `.atlas-dev.local.json`, start with
`python3 -B scripts/atlas_daily.py status` and follow `docs/daily-development.md`
before queueing work. The read-only entry selects config relative to its resolved
script checkout, including through a symlink, regardless of the current directory.
Use `python3 -B scripts/atlas_daily.py --config /absolute/path/.atlas-dev.local.json status`
for another explicit config. Missing or contradictory selection fails; never guess
another installation or run from the source template. Keep local config private.

This entry supports status only. For mutations, use the guide's existing `daily`
helper with runtime/state/owner taken from the same explicit config. Preserve the
stable owner and recover pending handoffs through the same invocation before other
work. Read native status and recovery guidance alongside the distinct checkout
HEAD, candidate drift and runtime source pin. Source markers record provenance,
not installed-file integrity or host/account/model qualification. The supervisor
must verify the exact host and route before dispatch. This supervised lane grants
no unattended or merge authority. Do not continue into the general issue-to-PR
flow below automatically; it applies only to a separately selected, qualified lane.

## Continuous campaign operating mode

When the user asks to keep operating a campaign, use the selected runtime as the
outer supervisor: reconcile -> select eligible work -> reserve -> dispatch ->
observe -> ingest original evidence -> validate/review -> accept or route -> repeat.
Task or milestone completion returns to work selection within the admitted window;
it is not by itself a reason to end the campaign turn or request acknowledgment.
For loop design and qualification, use `continuous-agent-loop` and
`agent-harness-evals` where available.

Name the actual execution mode: supervised in-app, scheduled bounded runs, or a
qualified durable supervisor. A chat, subagent, accounting lease or recurring
schedule alone does not prove continuous runtime operation. Verify the selected
queue/runtime/owner, installed integrity, exact execution route, recovery,
nonoverlap and resource enforcement before promoting to a longer or unattended
mode. A GitHub shift command is not a substitute for an unrelated local lane.

- Recover an owned pending invocation through its original identity before new
  dispatch. Another controller's lease prevents competing mutation; age alone
  does not authorize takeover. Observe an already running supervisor rather than
  starting a duplicate on each scheduled wake.
- Use the existing qualified launcher and its bounded continuous mode only when
  the selected lane actually supports them. Preserve original parent deadlines,
  consumed reservations, phase and wake/shift caps, stable owner and stop gates.
  Repeated leases, child budgets, waits and restarts must not renew the envelope
  or bypass a shorter supervision limit. Change cadence or execution mode only
  through supported controls under applicable authority, with readback.
- After each accepted item, continue immediately to eligible authorized work
  while the full next allowance and custody/cleanup fit. Preserve independent
  review and all complexity/authority flags. A dependent lane failure blocks that
  action; continue independent useful work. Do not treat an unchanged scope/hash
  as requiring a new human approval.
- When continuity is not qualified, identify the exact missing gate and resume
  condition. Prepare a separately bounded qualification task only within the
  existing repair authority and limits; do not repeat a closed failed wrapper
  tranche. Continue permitted direct work and describe it honestly as supervised.
  If the selected limits cannot support the requested continuous interval,
  disclose that conflict rather than silently extending them.
- Measure progress against connected parent acceptance demonstrations. Reuse
  valid pinned evidence; avoid repeatedly re-admitting unchanged contracts or
  producing further scaffolding without advancing a dependency. Replan when
  setup/review/repair overhead consumes the useful execution allowance.
- End intake for a genuine applicable blocker, unknown invocation outcome,
  missing authority, exhausted admitted window/envelope, user stop or accepted
  campaign completion. Distinguish a task stop from a campaign stop. An empty
  eligible queue needs a concrete dependency/decision, not a generic report.

At exit record the actual supervisor/invocation identity and running/terminal state,
accepted progress toward the parent outcome, remaining original limits, precise
stop reason and supported resume route. Report accepted milestones as requested
without turning them into acknowledgment gates. Notification policy follows the
user's intent; routine unchanged heartbeats need not create inbox noise.

## Purpose

When the `atlasmemory_tools` MCP server is available, use `harness_discover` to
compare registered capabilities with the existing explicit runtime selection.
Inspect a matching selected registered runtime with `harness_inspect`. An
unrelated registered default must not replace a selected local lane; when that
lane is not registered, retain its explicit selection and use its supported local
status route. The commands below remain provider-level operations; do not
reconstruct runtime location from memory.

Keep agent coordination in local queues and artifacts. The MCP GitHub cycle
uses `--remote-comments local`. Direct legacy commands retain their old default;
select local policy explicitly for new automation. Use `cloud-review` only for
deliberately selected PR-facing summaries, never as worker-to-worker messaging.

Run the local GitHub issue-to-PR lane with explicit bounds, review gates, validation, repair, finalization, and summaries.
For the qualified GitHub lane below, this skill owns operation of `atlas-agent-shift`; there is no separate shift skill. Other selected lanes must use their own actually supported supervisor route.
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
- For qualified multi-hour GitHub operation, use `atlas-agent-shift`. Other lanes require their selected supported supervisor; a Codex chat or subagent is not a durable substitute.
- Do not start a long shift until one real item has passed the full canary. Stop new dispatch after two consecutive no-progress cycles, the same blocker twice without new evidence, more than one repair of the same item, or stale, unknown or unreconciled supervisor custody after reconciliation. A healthy known running supervisor is expected: observe it without a competing launch.
- Stop when harness repair consumes more effort than the remaining direct task path. Preserve the candidate and route a direct supervised takeover instead of automatically refreezing and relaunching.
- Preserve exact-subject approvals where authority requires them. Do not ask again for an unchanged material decision merely because a wrapper, serialization, or internal hash changed without changing the effect envelope.
- Treat `Open dependencies:` and `Manual gates remaining:` as the runtime dispatch contract; Project fields are advisory unless they match the issue body.
- Keep unattended dispatch one-point only. Larger `points:N` issues must be decomposed or explicitly handled outside unattended dispatch.
- Treat no-check PRs as blocked unless local validation and required-check policy explicitly allow them.
- Do not repair failed workflows until `atlas-agent-review --apply` has classified the failure.
- For human-action, secret/config, infra/env, or dependency-blocked workflow classes, stop worker repair and hand the issue to the responsible operator.

## Subagents

- Delegate bounded side tasks only: inspect one PR, classify one log set, draft one repair plan, or review one handoff/status file.
- Do not delegate the runtime control loop. The selected qualified supervisor owns its long-running loop, lock, heartbeat and handoff; `atlas-agent-shift` supplies these for the GitHub lane.
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
