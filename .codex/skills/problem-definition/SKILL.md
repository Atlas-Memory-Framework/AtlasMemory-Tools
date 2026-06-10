---
# atlas-tools-generated: source=skills/problem-definition/SKILL.md manifest=atlas-tools.v1 checksum=sha256:94f1312f89018af53a733db6a1ac44d00e50713b86cf8fd83adf2f8dab14c459
# atlas-tools-generated-end
name: problem-definition
description: Define a clear problem statement with measurable success criteria and explicit scope boundaries. Use at the start of /plan or when the user asks to define the problem.
---

# Problem Definition

## Purpose
Turn a vague idea into a crisp, testable, product-grounded problem definition before ideation or technical planning. The output must explain the real system/workflow gap well enough that future implementation agents with no user access understand what matters and why. Run as a sub-agent and return a draft section to the orchestrator; do not write the plan artifact directly.

## When to use
- At the start of `/plan`
- When the user asks to "define the problem"
- Before challenge/ideation loops

## Required outputs
- Problem narrative (1–2 paragraphs, non-solutionized, product/system focused)
- Current broken workflow and desired workflow
- Why this matters / why now
- At least 3 concrete current-state facts from repo inspection and/or user context, with sources
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
- The first paragraph describes the real product/system failure or opportunity, not the need for a plan.
- The first two paragraphs avoid planning-meta terms: `plan`, `artifact`, `gate`, `issue manifest`, `registry`, `projection`, `dispatch`.
- Current broken workflow, desired workflow, why the gap matters, and why this work exists now are explicit.
- At least 3 concrete current-state facts are captured with sources (`file`, `command`, `user`, or `issue`).
- Problem narrative is specific and not a solution.
- At least 2 measurable success criteria.
- Success criteria measure product/system outcomes and verification evidence, not document completeness.
- Explicit scope and anti-scope exist.
- At least 1 constraint is captured (or "none").
- Any forks are captured as decision boundaries.

## Process
1) Restate the user goal neutrally.
2) Interrogate for the product/system reality: current workflow, desired workflow, affected users/agents, why the gap matters, and why now.
3) Collect at least 3 current-state facts from available repo context and/or user-provided context. Do not invent facts; if a fact is unavailable, ask for it or mark the gate failing.
4) Propose measurable success criteria tied to behavior, evidence, and verification.
5) Capture constraints, scope, and anti-scope.
6) Identify decision boundaries (A/B/C).
7) Finalize the Problem Definition block.

## Interrogation rules
- Ask targeted questions before returning `Pass` if any of these are missing: current workflow, desired workflow, why now, affected actor, concrete repo/user facts, non-negotiable constraint, or pass/fail evidence.
- Do not accept generic answers like "make it better", "clean up the plan", or "improve automation" as the problem statement. Convert them into specific workflow gaps or ask for clarification.
- If the user cannot answer a detail needed for implementation, record it as an Open question with owner/status or as a Decision boundary with A/B/C options and a recommended default.
- Do not use authority-contract, registry, projection, dispatch, or artifact language in the opening narrative unless that machinery is itself the product/system being changed.

## Output template
Use this exact template:

```md
## Problem Definition

Problem narrative:
<1-2 paragraphs describing the real product/system failure or opportunity. The first two paragraphs must avoid planning-meta terms: plan, artifact, gate, issue manifest, registry, projection, dispatch.>

Current broken workflow:
- ...

Desired workflow:
- ...

Why this matters / why now:
- ...

Current-state facts:
- Fact 1: ... (source: file|command|user|issue)
- Fact 2: ... (source: file|command|user|issue)
- Fact 3: ... (source: file|command|user|issue)

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
