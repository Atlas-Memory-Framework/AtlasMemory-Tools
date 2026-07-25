<!-- atlas-tools-generated: source=skills/agent-harness-evals/references/eval-contract.md manifest=atlas-tools.v1 checksum=sha256:29149700b2546bb520ddb3176e8e10f208c13651948f669029b9148051d68adb -->
<!-- atlas-tools-generated-end -->
# Agent Harness Evaluation Contract

Use this contract to make harness comparisons reproducible and decision-relevant.

## Evaluation Packet

Record equivalent fields even when another format is used:

```yaml
eval_id: stable-id
decision: diagnose | qualify | compare | promote | defer | revert
system:
  code_ref: git-sha
  harness_ref: version-or-hash
  prompt_ref: hash
  skill_refs: [name-and-hash]
  model: provider/model/config
  tools: versions
  authority_policy: version-or-hash
baseline: exact-system-ref
variant: one-declared-change
budgets:
  trials: 3
  cycles_per_trial: 3
  minutes_per_trial: 60
  repairs_per_trial: 1
  approvals_per_trial: 1
progress:
  unit: accepted-work-item | passing-criterion | integrated-leaf
  minimum_per_trial: 1
tasks:
  - id: task-id
    initial_state_ref: immutable-fixture
    request: bounded-task
    success: deterministic-outcome
    forbidden_effects: []
    reference_solution_ref: known-solvable-path
graders:
  outcome: deterministic-command-or-query
  trace: contract-and-safety-rules
  semantic: rubric-or-null
```

For every trial, preserve the terminal environment state, trace, artifacts, commands, costs, timing, approval interactions, and reason for termination.

## Core Metrics

Use raw counts alongside ratios; do not hide small samples behind percentages.

| Metric | Definition |
|---|---|
| Accepted progress | Count of declared progress units that reached required validation/review |
| Terminal yield | Trials ending truthfully in `complete`, `blocked`, or `failed` divided by trials started |
| Stale-state count | Trials whose durable projection disagrees with actual worker/process state |
| Repair churn | Repair cycles divided by `max(accepted progress, 1)` |
| Blocker recurrence | Repeated identical blocker fingerprints without new evidence |
| Approval amplification | Approval prompts divided by `max(unique material decisions, 1)` |
| Operator attention | Human minutes plus number of required interventions |
| Recovery success | Interrupted or failed trials resumed to a truthful terminal state within budget |
| Evidence completeness | Required outcome, trace, version, and artifact fields present |
| Unsafe-action denial | Forbidden or unauthorized effects attempted or correctly denied |

Add task-specific quality measures, but do not replace accepted progress and terminal truth with proxy activity such as tool calls, commits, prompts generated, workers launched, or tokens consumed.

## Grader Precedence

1. Environment and repository outcomes.
2. Deterministic contract, policy, and trace assertions.
3. Human-approved acceptance criteria.
4. Calibrated model graders for semantic quality.
5. Worker or supervisor narrative as supporting evidence only.

If graders conflict, preserve the conflict and route it to review. Never let a model grader override a deterministic safety or authority failure.

## Trial Validity

Mark a trial invalid rather than failed when the task is unsolvable as specified, the reference solution cannot pass, required infrastructure is unavailable for every variant, or shared state contaminates the comparison. Record invalidation reasons and repair the evaluation before drawing performance conclusions.

## Decision Rule

Declare the minimum improvement and maximum regressions before running trials. Prefer a small Pareto scorecard over one composite score: task success, safety, operator burden, cost, and latency often represent real tradeoffs that should remain visible.
