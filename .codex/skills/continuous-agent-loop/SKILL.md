---
# atlas-tools-generated: source=skills/continuous-agent-loop/SKILL.md manifest=atlas-tools.v1 checksum=sha256:6e8a974b470cd42ae3b327d4bbc89f4d37f8acbf366fb19f69f38adfc5596312
# atlas-tools-generated-end
name: continuous-agent-loop
description: Design and run bounded continuous agent work loops, including nested inner/outer loops, with explicit queue intake, authority, budgets, progress signals, work isolation, validation, evidence, review, resume state, and stop gates. Use when the user asks for loop engineering, unattended or semi-attended Codex work, recurring repo maintenance, multi-agent work queues, local JSON work-item loops, issue-to-PR automation, long-running development, or faster continuous development across one or more repos.
---

# Continuous Agent Loop

## Overview

Use this skill to turn vague "keep working" intent into a bounded operator loop. The loop may run once, run as a short supervised shift, or prepare an unattended lane, but it must keep authority, validation, and stop conditions explicit.

## Loop Contract

Before acting, state:

- The repo or repos in scope.
- The queue source: local work-item JSON, GitHub issues, a plan artifact, PR feedback, CI failures, or a single user goal.
- The authority level: dry-run, prepare-only, workspace edits, PR publishing, merge/finalize, or external effects.
- The budget: max cycles, max items, max minutes, sleep interval, and concurrency.
- The progress signal: what observable state must change for an iteration to count as progress.
- The stop gates: blocked dependency, failed validation, dirty/unknown worktree, missing authority, exhausted budget, or user decision required.

Do not treat a chat thread as a durable daemon. Prefer an installed runtime, scheduled automation, or explicit `codex exec` wrapper for long loops.

## Control Hierarchy

Keep loop responsibilities separate:

- The human/governance layer owns objectives, authority, policy, acceptance, and irreversible decisions.
- The outer supervisor loop refreshes state, selects bounded work, allocates child budgets, integrates evidence, and decides whether to repeat, replan, pause, or stop.
- The inner work-item loop orients, acts, tests, and reports one bounded result.
- A repair loop addresses a specific externally observed defect; it does not redefine success.
- An independent evaluator judges outcomes and evidence when risk or ambiguity justifies it.
- An offline improvement loop may propose changes to skills, prompts, tools, models, or scheduling policy only after replay/evaluation. It must not silently rewrite a live loop's controller.

A child loop may narrow inherited scope, authority, or budget but must never widen them. A successful process exit or worker self-report is evidence, not acceptance.

## Standard Loop

1. Orient from source of truth.
   - In Atlas, run `.venv/bin/python atlas/cli/atlas brief` before asking the user what to do next.
   - In other repos, read `AGENTS.md`, repo usage docs, current plan/handoff artifacts, and `git status --short`.
2. Build or inspect the queue.
   - Use an existing queue before inventing a new one.
   - Prefer one-point or file-scoped work items with explicit validation commands.
3. Select one safe item or one bounded batch.
   - Require disjoint write scopes for parallel workers.
   - Use worktrees or runtime job checkouts for independent implementation.
4. Execute with least authority.
   - Start with dry-run or prepare-only when the lane is new.
   - Do not publish PRs, merge, close issues, apply database mutations, or use external effects unless the queue item and current user instruction authorize that effect.
5. Validate.
   - Run the repo's targeted checks.
   - Capture exact commands and results.
   - Treat missing validation as a blocker unless a waiver is explicit.
6. Review independently where risk justifies it.
   - Use a reviewer/subagent for correctness, tests, security, or semantic alignment.
   - Do not let the same worker silently grade its own risky change.
7. Record evidence and route next state.
   - Write handoff/status artifacts where the repo expects them.
   - Classify the iteration as `advanced`, `no_change`, `regressed`, `blocked`, or `complete`.
   - Summarize changed files, commands run, evidence, blockers, and next safe command.
8. Repeat only if the loop budget remains, progress is observable, and no stop gate fired.

## Retry, Stagnation, and Resume

Choose the next route from evidence:

- Retry only transient failures, using bounded backoff and idempotent operations.
- Repair reproducible implementation defects against unchanged acceptance criteria.
- Replan when the current decomposition or assumptions no longer fit observed reality.
- Escalate when intent, authority, credentials, or a human judgment is required.
- Stop on dirty overlap, unsafe scope expansion, exhausted budget, or repeated no-progress evidence.

Do not repeat the same action with the same inputs after it produced the same blocker. Permit one bounded retry only when there is a new hypothesis, changed input, or credible transient cause. If two consecutive attempts produce the same blocker fingerprint without new evidence, stop the child loop and route it to replan, pause, or human action.

For work that may cross a context, process, or model-version boundary, persist a resumable record with stable loop and parent ids, source/objective hashes, authority, budgets, attempt count, progress classification, blocker or stop reason, artifact references, and relevant code/prompt/model/tool versions. Treat pre-interrupt side effects as replayable only when they are idempotent.

## Improvement Boundary

Improve the harness offline from recorded outcomes and traces. Start with deterministic outcome graders, add trace or model graders only where needed, calibrate subjective graders with humans, and compare one harness change at a time against a stable task set. Track task success, validation and review outcomes, stalls, repairs, human interventions, cost, latency, and unsafe-action denials.

Use `agent-harness-evals` to diagnose harness failures and qualify any unattended or multi-hour lane before promotion. A new or materially changed lane must pass a representative one-item canary through result ingestion, validation, review, truthful terminal state, and resumable evidence.

Use search or alternative branches mainly for reversible diagnosis, research, and planning. Select one bounded path before repository mutation unless isolated branches have explicit merge and evaluation contracts.

## Atlas Posture

Atlas is not a task app or Codex wrapper. For Atlas work, name the layer in scope and what the loop proves and does not prove.

Useful current loop attach points:

- `atlas brief`: projection-only operating picture.
- `atlas loop1 dogfood-workpacket`: DB-backed proof candidate when Postgres is available.
- Runtime ledger and WorkPacket evidence: proof/evidence surfaces, not scheduler authority.
- AtlasMemory-Tools local JSON work items: practical supervisor loop before Atlas owns the full scheduler.

Stop before claiming unattended Atlas autonomy unless the loop has explicit scheduler, authority, persistence, and validation evidence.

## Runtime Choices

Use the smallest runtime that fits:

- One-off local task: normal Codex turn, then final evidence.
- Scriptable one-shot: `codex exec --json` with explicit sandbox and output schema.
- Recurring Codex app follow-up: thread or project automation.
- Repo-isolated parallel work: worktrees or runtime job checkouts.
- Local queue without GitHub mutation: AtlasMemory-Tools `atlas-agent-orchestrator --atlas-work-items`.
- GitHub issue-to-PR lane: AtlasMemory-Tools `atlas-agent-unattended` or `atlas-agent-shift`.

Before using `atlas-agent-unattended` or `atlas-agent-shift`, obtain an `agent-harness-evals` readiness disposition for the exact lane version. Do not infer readiness from dry-run, prompt construction, successful dispatch, or worker exit alone.

For multiple Codex accounts or subscriptions, use separate installed runtime directories and separate runtime-local `codex-home/` directories. Do not point unattended workers at a shared personal Codex home unless the user explicitly accepts the billing/data coupling.

## Cross-Repo Rules

When looping across repos:

- Preflight each repo separately.
- Preserve dirty or untracked user work.
- Assign file scopes per repo.
- Validate in the source repo before importing or adapting behavior elsewhere.
- Move evidence through explicit handoff packets, proposed deltas, or source records; do not silently copy runtime state into canonical state.

## References

- Read `references/loop-architecture.md` when designing nested loops, drawing a graph of loops, defining progress/stagnation behavior, making a loop resumable, or improving a harness from evaluations.
- Read `references/runtime-notes.md` when setting up or operating an Atlas/AtlasMemory-Tools loop, or when comparing Event Analysis Engine worker spawning to Atlas loop design.
