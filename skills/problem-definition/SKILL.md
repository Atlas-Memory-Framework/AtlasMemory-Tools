---
name: problem-definition
description: Define a clear problem statement with measurable success criteria and explicit scope boundaries. Use at the start of /plan or when the user asks to define the problem.
---

# Problem Definition

## Purpose
Turn a vague idea into a crisp, testable problem definition before ideation or technical planning. Run as a sub-agent and return a draft section to the orchestrator; do not write the plan artifact directly.

## When to use
- At the start of `/plan`
- When the user asks to "define the problem"
- Before challenge/ideation loops

## Required outputs
- Problem statement (1–3 sentences, non-solutionized)
- Success criteria (measurable, pass/fail)
- Constraints (non-negotiables or explicit "none")
- Scope and anti-scope
- Definitions / glossary for key terms
- Open questions (true unknowns only)
- Decision boundaries (A/B/C if a fork exists)
 - Draft section content for `## Problem Definition`

## Sub-agent output contract
Return a single block in this shape:

```md
DraftSection:
<exact section content for ## Problem Definition (must include the section header)>

Checklist:
- <criterion>: Pass | Fail

Questions:
- <if blocked>

Notes:
- <optional risks/assumptions/tests updates>
```

## Malformed output handling
- If you cannot produce the exact section header or required fields, return `Questions` explaining what is missing and leave `DraftSection` as `N/A`.

## Success criteria (gate: ProblemDefinitionComplete)
- Problem statement is specific and not a solution.
- At least 2 measurable success criteria.
- Explicit scope and anti-scope exist.
- At least 1 constraint is captured (or "none").
- Any forks are captured as decision boundaries.

## Process
1) Restate the user goal neutrally.
2) Extract missing details.
3) Propose measurable success criteria.
4) Capture constraints, scope, and anti-scope.
5) Identify decision boundaries (A/B/C).
6) Finalize the Problem Definition block.

## Output template
Use this exact template:

```md
## Problem Definition

Problem statement:
- ...

Success criteria (measurable):
- SC1:
- SC2:

Constraints:
- ...

Scope:
- In scope:
  - ...
- Out of scope:
  - ...

Definitions / glossary:
- Term: ...

Open questions:
- Q1:

Decision boundaries (if any):
- Decision needed:
  - A) ...
  - B) ...
  - C) ...
Recommended default: <A/B/C> (why)
```

## UX rules
- Do not accept "looks good" without measurable criteria.
- Ask targeted questions for gaps.
- If the user defers, record a decision log entry.
- **Deferred requires DR + trigger (hard rule)**: do not mark anything “Deferred” (scope boundary, constraint, success criteria, or decision boundary) unless there is a `DR-xxx` and an explicit trigger for revisit.
