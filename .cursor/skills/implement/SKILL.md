---
# atlas-tools-generated: source=skills/implement/SKILL.md manifest=atlas-tools.v1 checksum=sha256:14e84c5f354f056eff8653aaaa2153875bb330a674afdb352474cda2169ed6c9
# atlas-tools-generated-end
name: build
description: Execute the current plan artifact with strict sub-agent orchestration, plan-execution discipline, and build-time gates. Use when the user runs /build, /implement, or requests implementation from an approved plan.
---

# /build and /implement Orchestrator

## Purpose
Implement the current plan artifact exactly, honoring phases, tasks, owners, and gates, while delegating execution to sub-agents by default.

## Artifact authority contract
- The markdown plan artifact is the planning write surface and amendment record.
- In `registry-first`, compiled registry YAML is the local planning SSOT for structure, joins, execution routing, and projection metadata.
- GitHub issues, PRs, and checks are the execution truth.
- GitHub Projects v2 is downstream execution UI/signal only.
- Rendered overlays and runtime-mirror outputs are read-only derived context.
- `/implement` must never treat markdown artifacts as execution-authoritative once compiled registry data is the active planning authority.

## Delegation policy (default required)
- Prefer sub-agents for all non-trivial implementation work.
- "Non-trivial" means any of:
  - touching more than 1 file
  - work estimated to take more than one direct tool call
  - running or fixing tests/lints
  - code review or test validation gates
  - parallel workstreams in the plan
- Direct orchestrator edits are allowed only for trivial single-file/single-hunk fixes or explicit merge/integration tasks.
- If sub-agents are available, do not perform medium/large implementation work directly in the orchestrator.
- If a task is not delegated, explicitly justify why in `Execution Status`.

## Preflight conformance checks
- Plan `Status` is Approved (or explicit override logged in Decision Log). If all gates pass but Status is not Approved, instruct the user to run `/plan` to finalize status.
- Plan is not blocked on planning decisions:
  - `BlockingDecision` is `none` AND `UnresolvedBlockers` is `0`
  - If not, stop and instruct the user to run `/plan` to resolve the blocker(s), or log an explicit override DR entry.
- Planning reviews are complete:
  - `PlanningReviewsComplete: Pass` and security/privacy review present.
  - If not, stop and instruct the user to run `/plan` or `/planning-reviews` to complete reviews.
- Identify current phase, tasks, owners, exit criteria, and gates.
- Identify dependencies, merge points, and allowed parallel workstreams.
- Resolve lifecycle mode (`legacy-plan`, `migration-bridge`, `registry-first`) before using planning metadata for execution.
- If `registry-first` is active, resolve execution repo, scope, joins, and story metadata from the compiled registry or validated rendered overlay derived from it; do not infer execution routing from markdown prose.
- Treat rendered overlays as read-only operator context, never as authoring input.
- Conformance for parallelism:
  - Each file delta has a single explicit owner (WS/agent) until an explicit merge point.
  - If multiple workstreams would touch the same file, require an integration task at a merge point and treat that file as owned by the integrator.
- If build discovers missing plan detail that changes intent (interfaces, invariants, scope, rollout, tests), stop and require a plan patch + DR entry (do not redesign silently during build).
- If ambiguity exists, stop and require a plan patch + DR entry.

## User experience rule (no "go read the plan")
- If build is blocked (ambiguity, missing decision, missing gate definition), paste the relevant excerpt(s) in the chat response:
  - the phase/tasks that are blocked
  - the exact missing decision or missing plan detail
  - the recommended minimal plan patch to unblock

## Execution model
- Phases are serial.
- Workstreams can be parallel only if the plan says so.
- Merge points are explicit steps that integrate parallel work.
- Delegate each independent workstream to a sub-agent.
- Launch sub-agents in parallel when workstreams are independent.
- Do not launch more than 4 sub-agents at once.

## Sub-agent selection rules
- `explore`: quick context gathering for broad codebase discovery.
- `generalPurpose`: implementation tasks (code edits, refactors, bug fixes).
- `test-engineer`: run and triage plan-defined tests; return failures with fix guidance.
- `code-reviewer`: review integrated changes for correctness/regressions/security.
- Prefer a faster model for straightforward implementation and test loops.

## Ownership and merge discipline
- Keep strict single-owner file policy until merge point.
- Every changed file must have one active owner at a time (WS/sub-agent/integrator).
- If two workstreams need the same file, schedule explicit merge-point integration owned by the integrator.
- Integrator is the only owner allowed to modify shared files at merge point.

## Required execution loop per phase
1. Build a delegation matrix from plan tasks:
   - `Task -> Owner -> Files -> Agent Type -> Done Criteria`
2. Start sub-agents for all eligible tasks (default).
3. Poll agent outputs; resolve blockers; resume agents as needed.
4. Integrate outputs at explicit merge points.
5. Run plan-defined gates (use `test-engineer` and `code-reviewer` sub-agents for non-trivial validation).
6. If a gate fails, delegate fixes back to the owning sub-agent, then re-run gates.
7. Mark phase complete only when all exit criteria and gates pass.

## Build-time gates
- Lint/format, unit tests, integration tests, smoke/manual steps, build artifacts, staging dry-run.
- Run only gates listed for the phase.

## Output format
Update the current plan artifact with this block:

```md
## Execution Status
Phase: <name>
Status: not started | in progress | blocked | complete

Workstreams:
- WS1: <status> - completed tasks / blockers
- WS2: ...

Delegation matrix:
- Task: <task id/name> | Owner: <WS/agent> | Files: <paths> | Agent: <type> | Status: <...>

Completed tasks:
- ...

Blocked:
- ... - reason - requires DR-xxx / plan patch

Build gates:
- Lint - pass/fail - notes
- Tests - pass/fail - notes

Sub-agent usage:
- Agents launched: <count>
- Parallel batches: <count>
- Direct orchestrator edits: <count> - justification

Next actions:
- ...
```
