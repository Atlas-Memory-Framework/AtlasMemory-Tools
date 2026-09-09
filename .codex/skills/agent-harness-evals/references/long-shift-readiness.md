<!-- atlas-tools-generated: source=skills/agent-harness-evals/references/long-shift-readiness.md manifest=atlas-tools.v1 checksum=sha256:43d6643e620ccf26f1f598b195b2ce2d2146c5d931a2a891f7ca35dccab13324 -->
<!-- atlas-tools-generated-end -->
# Long-Shift Readiness

Use this gate before allowing a runtime to supervise multi-hour or unattended work.

## One-Item Canary

Require one representative item to complete the whole intended path:

```text
source truth -> task packet -> authority check -> isolated execution
-> result ingestion -> validation -> independent review
-> truthful terminal state -> resumable evidence -> handoff
```

Dry-run, prompt preparation, worker launch, or a zero process exit proves only that specific stage. It does not qualify the lane.

The canary must demonstrate:

- substantive task content and explicit success/forbidden-effect criteria;
- valid repository/worktree identity and required interpreter/toolchain;
- typed producer/consumer contracts tested through the generated prompt-to-parser path;
- durable exception capture and truthful `blocked` or `failed` transitions;
- outcome validation and independent review;
- idempotent retry/resume behavior;
- one declared accepted-progress unit within the canary budget;
- no repeated material approval for unchanged semantics.

## Failure Attribution

| Symptom | Attribute first to | Required route |
|---|---|---|
| Worker output cannot be parsed | Harness producer/consumer contract | Block durably; fix contract fixture before rerun |
| Worker exits zero but state remains running | Supervisor state machine | Stop; repair terminal-state transition |
| Task packet is empty or generic | Decomposition/packet construction | Invalidate trial; do not blame worker |
| Required tests cannot run in worker checkout | Environment projection | Fail pre-spawn qualification |
| Same authority decision requested after internal refreeze | Operator/authority interface | Measure approval amplification; preserve semantic decision |
| Multiple cycles repair wrappers without accepted task progress | Harness value failure | Stop shift; compare direct supervised execution |
| Projection disagrees with exact refs or durable evidence | Read-model/currentness | Reconcile once, then stop on recurrence |
| Same blocker repeats without new evidence | Supervisor policy | Stop child loop and replan or escalate |

## Shift Stop Policy

Define stop thresholds before launch. Use these defaults unless the task justifies stricter limits:

- zero accepted progress across two consecutive cycles;
- identical blocker on two consecutive attempts;
- more than one repair attempt for the same work item;
- any untruthful durable state after reconcile;
- any required authority expansion;
- operator attention exceeds the remaining direct-execution estimate;
- repair churn reaches `2` before the first accepted progress unit.

On stop, do not begin another repair cycle automatically. Emit:

- exact last truthful state and source refs;
- accepted progress, if any;
- blocker fingerprint and failure attribution;
- repair and approval counts;
- preserved candidate/worktree/artifact paths;
- direct supervised alternative;
- smallest harness regression fixture;
- authority required for any next action.

## Direct-Execution Comparator

Run or estimate a bounded direct-supervised baseline using the same task, model class, validation, authority, and evidence requirements. A runtime earns its complexity only if it provides material safety, concurrency, recovery, or throughput value that exceeds its orchestration and operator costs.

Do not treat “the runtime is safer because it asks more often” as sufficient. Test whether it asks at the correct semantic boundaries, remembers accepted decisions, blocks unauthorized effects, and avoids converting internal serialization changes into new human decisions.

## Promotion Levels

| Level | Evidence | Allowed use |
|---|---|---|
| Prepare-only | Valid packets/prompts; no execution | Review and fixture development |
| Canary | One real item reaches truthful terminal state | Supervised single-item operation |
| Bounded lane | Representative multi-trial eval passes | Short multi-item supervised cycles |
| Long shift | Recovery, terminal truth, operator burden, and stop policy pass | Multi-hour bounded supervision |
| Unattended | Broader regression suite plus production monitoring and rollback | Explicitly authorized unattended operation |

Promotion is lane- and version-specific. A model, prompt, skill, tool, environment, or policy change can require requalification.
