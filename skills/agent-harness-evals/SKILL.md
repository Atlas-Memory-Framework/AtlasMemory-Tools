---
name: agent-harness-evals
description: Design, run, and interpret evaluations for agent harnesses, orchestration runtimes, prompts, skills, tools, model routing, and long-running operator lanes. Use when comparing harness variants, deciding whether a runtime is ready for unattended or multi-hour work, diagnosing stalls, repair churn, approval fatigue, repeated blockers, or stale state, converting traces into replay fixtures, defining progress and operator-burden metrics, or gating promotion and rollback.
---

# Agent Harness Evals

## Overview

Evaluate the model, harness, tools, environment, authority policy, and operator interaction as one system. Measure accepted task progress and recoverability, not activity, worker self-reports, or process exit alone.

## Evaluation Contract

Before running trials, state:

- The decision: diagnose, compare, qualify for a long shift, promote, defer, or revert.
- The system under test: exact code, prompt, skill, model, tool, runtime, and policy versions.
- The baseline and the single intended variant.
- The task set, initial-state fixtures, reference solutions, and counter-cases.
- The allowed authority and effects, plus time, cycle, token, cost, repair, and approval budgets.
- The primary progress unit and the minimum useful progress expected per trial.
- The outcome, trace, safety, and operator-burden graders.
- The conditions that invalidate a trial because of task or environment defects.

Use [references/eval-contract.md](references/eval-contract.md) for the task/trial schema and scorecard.

## Standard Workflow

1. Collect representative evidence.
   - Sample successes, failures, stalls, repairs, resumptions, and human escalations.
   - Preserve the original task, environment state, trace, artifacts, and final outcome.
2. Classify the failure surface.
   - Separate task/specification, model, prompt/skill, tool/interface, harness/orchestrator, environment, authority/policy, grader, and operator-interface failures.
   - Do not blame the model for an empty task packet, broken worktree, incompatible parser, or impossible grader.
3. Build a balanced task set.
   - Include cases where the behavior should and should not trigger.
   - Provide a known-solvable reference path for each blocking task.
   - Isolate trials so state, history, caches, or previous attempts cannot leak across them.
4. Run comparable trials.
   - Hold all but one harness variable constant.
   - Use multiple trials when model variance can change the decision.
   - Capture terminal environment state plus the complete available trace.
5. Grade in evidence order.
   - Grade deterministic environment outcomes first.
   - Grade contract and safety invariants from traces second.
   - Use model graders only for semantic dimensions that deterministic checks cannot cover.
   - Calibrate subjective graders against periodic human judgments.
6. Measure net operational value.
   - Score accepted progress, terminal yield, recovery, repair churn, repeated blockers, approval amplification, operator attention, cost, and latency.
   - Compare the runtime with direct supervised execution, not only with its previous version.
7. Route the decision.
   - Promote only when the variant improves the declared objective without unacceptable regressions.
   - Defer when evidence is insufficient or the task/environment is invalid.
   - Revert when safety, reliability, or operator burden worsens materially.
   - Convert material failures into permanent regression fixtures.

## Long-Shift Qualification

Do not start `atlas-agent-shift` or another multi-hour lane merely because dry-run, dispatch, or worker launch succeeds. Require a one-item canary to reach a truthful terminal state through implementation, validation, review, and handoff within its budget.

Stop or reject long-shift readiness when any of these occur:

- Two consecutive cycles produce no accepted progress.
- The same blocker fingerprint appears on two consecutive attempts without new evidence.
- Harness repair consumes more cycles than task implementation or validation.
- A worker succeeds but the supervisor remains nonterminal or cannot ingest its result.
- Task packets lack substantive instructions, the execution environment cannot run required validation, or resume state is untruthful.
- The user is repeatedly asked to approve unchanged semantics because internal hashes, wrappers, or serialized artifacts were regenerated.
- The direct supervised path is demonstrably faster and no safety or scale benefit offsets the harness burden.

Exact-subject or exact-hash approval can be a valid safety control. Count it as approval amplification only when it repeats an already-bound material decision or was caused solely by harness-internal churn with no change to the effect envelope, target, authority, or acceptance semantics.

Read [references/long-shift-readiness.md](references/long-shift-readiness.md) when evaluating `atlas-agent-shift`, issue-to-PR automation, local work-item orchestration, or a runtime that is spending most cycles repairing itself.

## Boundaries

- Keep evaluation read-only unless the user separately authorizes fixture creation or harness changes.
- Do not use the harness under test as its only grader.
- Do not promote from a single lucky trial when outputs are nondeterministic.
- Do not optimize away required authority or safety gates; instead reduce how often unchanged decisions are re-requested.
- Keep external bootstrap runtime success separate from Atlas-native capability proof.

## Output

Return:

- Decision and confidence.
- System, baseline, variant, task set, and trial count.
- Outcome and operational scorecard.
- Failure attribution with supporting evidence.
- Invalid or ambiguous trials.
- Promotion, defer, revert, or stop disposition.
- Smallest next experiment and permanent regression fixtures to add.
