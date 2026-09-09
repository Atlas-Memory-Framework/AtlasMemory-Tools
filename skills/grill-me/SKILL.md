---
name: grill-me
description: Interactively uncover and resolve material product, design, scope, and technical decisions before planning or implementation. Use when the user explicitly asks to be grilled, interviewed, or challenged about what should be built.
---

# Grill Me

Help the user discover the smallest sufficiently precise version of what they actually want before planning or implementation begins.

This is an interactive decision-elicitation procedure, not plan mode, implementation, or a completeness questionnaire.

## Boundaries

- Inspect available project context, code, documentation, evidence, and prior decisions before asking the user for facts the environment can answer.
- Use read-only investigation. Do not edit files, write a plan, implement, install dependencies, or make external state changes.
- Ask only questions whose answers could materially change the result. Question count is operator burden, not evidence of rigor.
- Approval of the final specification closes this interview; it does not authorize implementation.

## Decision Ledger

Maintain a compact ledger throughout the interview:

- confirmed decisions;
- assumptions;
- rejected alternatives and rationale;
- must-haves;
- explicitly out-of-scope or deleted scope;
- unresolved decisions;
- evidence, prototype, or external-authority needs.

Update it after each answer. Show a short checkpoint after a material scope change, contradiction, or long decision sequence so the user can correct drift. Keep decisions, not a transcript.

## Procedure

### Establish the current model

Restate the intended outcome and inspect the available context. Separate:

- facts answerable from the repository or existing evidence;
- consequential decisions that belong to the user;
- reversible assumptions the agent may safely carry;
- uncertainties requiring research, measurement, a test, or a prototype.

Investigate answerable facts before asking questions. Do not ask the user to rediscover their own repository.

### Build the decision frontier

Identify unresolved decisions that could materially alter the user-visible outcome, scope, architecture, data contracts, expensive or irreversible choices, acceptance evidence, safety, authority, or operations.

Model dependencies between decisions. A question is eligible only when its prerequisite decisions are resolved. Rank eligible questions comparatively by:

```text
chance the answer changes the decision * cost of being wrong
-------------------------------------------------------------
                         cost of asking
```

Do not invent numeric precision. Drop questions whose answers would not materially change the proposed specification.

### Ask the highest-value question

Ask one highest-value eligible question at a time unless the user requests a compact round and the questions are genuinely independent.

For every question provide:

- why the answer matters;
- the recommended answer and rationale;
- the strongest viable alternative;
- what changes depending on the answer.

Challenge contradictions, unsupported must-haves, and unnecessary scope. When a smaller outcome satisfies the underlying need, recommend deleting the extra scope explicitly.

If the user delegates a reversible decision, take the recommended default and record it as an assumption. Preserve user authority over consequential product, policy, value, and risk decisions.

After every answer, update the ledger, remove invalidated branches, recompute dependencies and materiality, and repeat from the highest-value eligible question.

### Escalate uncertainty correctly

Stop questioning a branch when discussion cannot resolve it:

- inspect the project for a missing local fact;
- research an externally verifiable fact when permitted;
- propose the smallest test or benchmark for empirical uncertainty;
- propose a bounded prototype or comparison for experiential uncertainty such as interface feel;
- identify the decision owner and required input when another person holds the authority.

Record the unresolved branch, the evidence needed, and what result would change the specification. Continue with other independent material decisions when possible.

### Stop

Stop when any of these is true:

- no unresolved eligible question would materially change the design;
- the user explicitly ends the interview;
- every remaining material branch requires evidence, a prototype, or external authority rather than more discussion.

Do not keep asking plausible but low-value questions to create an appearance of rigor.

## Final Output

Produce a concise decision record containing the intended outcome, confirmed decisions, must-haves, scope, explicitly deleted scope, assumptions, rejected alternatives with rationale, and unresolved evidence/prototype/authority needs.

Then propose a specification covering user-visible behavior, relevant system constraints, acceptance criteria, risks and tradeoffs, required validation, and the recommended next workflow.

Ask the user to approve, revise, or resume questioning. Do not implement.

## Maintenance Validation

When changing this skill, evaluate behavior using [references/eval-cases.md](references/eval-cases.md). Grade observable decisions and effects, not exact headings or phrasing.
