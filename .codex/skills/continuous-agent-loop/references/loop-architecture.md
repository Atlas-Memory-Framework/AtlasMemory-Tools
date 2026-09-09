<!-- atlas-tools-generated: source=skills/continuous-agent-loop/references/loop-architecture.md manifest=atlas-tools.v1 checksum=sha256:95853476f583d312bf3cbfde5289e10a52a9abe1a99ce058a055e7e0081f5cf6 -->
<!-- atlas-tools-generated-end -->
# Loop Architecture

Use this reference to design a graph of bounded agent loops without confusing work dependencies, execution order, and control authority.

## Contents

- Separate the three graphs
- Recommended topology and control invariants
- Progress, stagnation, and retry classification
- Minimal resumable record
- Offline harness-improvement loop

## Separate the Three Graphs

| Graph | Question | Typical nodes and edges |
|---|---|---|
| Dependency graph | What work must precede other work? | Work items connected by `depends_on` or `blocks` |
| Execution graph | Which actor or stage runs next? | Worker, reviewer, validator, repair, and approval stages connected by conditional transitions |
| Control graph | Who may change objectives, authority, budgets, or policy? | Governance, outer supervisor, child loops, evaluator, and offline improvement loop |

Do not infer control authority from execution order. A downstream worker may consume an upstream result without gaining permission to accept it, publish it, or change the parent objective.

## Recommended Topology

```text
Human governance
  sets objective, authority, policy, acceptance, and irreversible gates
        |
        v
Outer supervisor
  observe -> select and budget -> invoke child -> integrate evidence -> replan or stop
        |
        +--> Inner work-item loop
        |      orient -> act -> test -> assess
        |                         |
        |                         +--> bounded repair from external failure evidence
        |
        +<-- Independent evaluator
               outcome and trace -> pass, repair, block, or escalate

Offline improvement loop
  sample traces and outcomes -> classify failure -> add eval -> change one variable
  -> compare with baseline -> promote or revert through governance
```

Run the layers at different rates. Inner loops respond to immediate tool and test feedback. Outer loops reconsider work selection after each bounded child result. Governance changes objectives or authority only at explicit gates. The improvement loop changes the harness only after offline evidence.

## Control Invariants

- Child scope, authority, budget, and side effects must be equal to or narrower than the parent contract.
- The outer loop owns queue selection and budget allocation; the inner loop owns only task-local action selection.
- The evaluator judges evidence but does not mutate the candidate it is grading.
- A repair loop preserves the objective and acceptance criteria. Changed requirements require replan or governance.
- Environment outcomes outrank worker claims. Exit code zero, a commit, or a plausible summary cannot establish acceptance alone.
- Every cycle and graph cycle needs a deterministic exit route plus a hard budget.
- External effects need idempotency keys or an equivalent duplicate-effect guard when retry or resume is possible.
- Live loops may record improvement proposals but must not rewrite their own skills, prompts, authority, or acceptance policy.

## Progress and Stagnation

Record one progress classification per iteration:

| State | Meaning | Default route |
|---|---|---|
| `advanced` | A named observable moved toward acceptance | Continue if budget remains |
| `no_change` | No relevant observable changed | Change hypothesis once or stop |
| `regressed` | A previously passing observable worsened | Restore or repair, then reassess |
| `blocked` | Progress requires unavailable dependency, authority, or human input | Pause or escalate |
| `complete` | Acceptance evidence is present and required review passed | Return to the outer loop |

Derive a stable blocker fingerprint from the failing gate, relevant command or operation, normalized error class, and unchanged input/source refs. Do not rerun an identical action against an identical fingerprint. If two consecutive attempts produce the same fingerprint without new evidence, stop the child loop and route to replan, pause, or human action.

## Retry Classification

| Evidence class | Route |
|---|---|
| Transient network, rate limit, lease, or service availability failure | Bounded retry with backoff and idempotency |
| Reproducible code, test, or review defect | Bounded repair against the same acceptance contract |
| Invalid decomposition, stale premise, or changed source of truth | Replan in the outer loop |
| Missing intent, authority, credential, approval, or value judgment | Escalate to the owner |
| Dirty overlap, unsafe scope expansion, or unbounded side effect | Stop |
| Exhausted time, token, cost, cycle, or repair budget | Stop and hand off evidence |

## Minimal Resumable Record

Persist equivalent fields even when the runtime uses a different schema:

```json
{
  "loop_id": "stable-id",
  "parent_loop_id": "stable-parent-id-or-null",
  "kind": "outer|inner|repair|evaluation|improvement",
  "objective_ref": "source-id-and-hash",
  "authority": ["workspace-edit"],
  "budget": {"cycles": 3, "minutes": 60, "cost": null},
  "attempt": 1,
  "progress": "advanced",
  "blocker_fingerprint": null,
  "stop_reason": null,
  "artifact_refs": [],
  "versions": {"code": "git-sha", "prompt": "hash", "model": "id", "tools": "version"}
}
```

Version resumable records. A pending task may outlive the code, prompt, model, or tool contract that created it; resume through a compatible version or require explicit migration.

## Offline Harness-Improvement Loop

1. Sample real failures, successes, stalls, and human escalations.
2. Convert each material failure into a reproducible task or trace fixture with a known-solvable reference path.
3. Grade final environment outcomes first. Add trace graders for unsafe, wasteful, or policy-breaking paths that outcome tests cannot reveal.
4. Use multiple trials where model variance matters and isolate trial state.
5. Change one prompt, skill, tool, model, scheduler rule, or budget policy at a time.
6. Compare task success, regressions, validation/review results, stalls, repairs, intervention rate, cost, latency, and unsafe-action denials.
7. Promote or revert through an explicit governance gate.

Prefer receding-horizon execution: select the next bounded item from current evidence instead of blindly committing the entire campaign to an old projection. Use parallel or search branches only when their scopes are isolated and the join rule, evaluator, and losing-branch cleanup are explicit.
