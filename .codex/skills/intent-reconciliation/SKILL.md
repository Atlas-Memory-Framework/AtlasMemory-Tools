---
# atlas-tools-generated: source=skills/intent-reconciliation/SKILL.md manifest=atlas-tools.v1 checksum=sha256:01cb00847cd3db44dc38512a621a3e8ec6da5440ab5b94e78d107f654e2403c8
# atlas-tools-generated-end
name: intent-reconciliation
description: Convert messy, partial, stream-of-thought, or under-specified user input into an explicit latent intent model, open-loop ledger, and intent checksum before downstream planning or implementation proceeds.
---

# Intent Reconciliation

## Purpose

Preserve the user's latent target before problem framing, technical planning, issue projection, or implementation turns messy expression into polished execution prose.

This skill maps user expression to intended outcome. It is not a replacement for `problem-definition`: it captures the relationship between what the user said, what they appear to mean, what they are reacting against, and which unresolved expression-state gaps could cause agents to build the wrong thing.

Run as a section-owner sub-agent and return a draft section to the `/plan` orchestrator. Do not write the plan artifact directly.

## When to use

Run before `ProblemDefinitionComplete` can pass when any of these are true:

- The user gives stream-of-thought, exploratory, or emotionally qualified input.
- The user says they are unsure how to express the target.
- The work is intended for zero-interaction implementers.
- The user references vibe, feel, taste, UX, cognition, architecture intuition, or "the thing in my head".
- Prior execution missed the user's intent despite a plausible plan.
- The plan has elevated `RubberStampSignals`.
- `PlanTier: Full` or `AutomationTarget: unattended-prs`.

## Required outputs

- Latent target, including what the user appears to be trying to achieve and any experiential/non-verbal target.
- Anti-targets: what the user is reacting against or explicitly does not want.
- Expression-state notes mapping user phrases to interpreted meaning, alternate plausible interpretations, confidence, and risk if wrong.
- Open Loop Ledger entries for unresolved gaps that may distort downstream planning or implementation.
- Intent checksum: success means, failure would look like, and any user confirmation needed.
- Draft section content for `## Intent Model`.

## Open loop types

- `lexical-gap`: a word or phrase may not mean what an implementer would assume.
- `concept-gap`: the concept exists in the user's mind but is not yet crisply represented.
- `referent-gap`: "this", "that", "the current thing", or a named object may point to multiple targets.
- `scope-gap`: boundaries are unclear enough to cause underbuild or overbuild.
- `acceptance-gap`: it is unclear what evidence would satisfy the user.
- `negative-constraint`: an anti-target or must-not-do constraint is implied but not encoded.
- `hidden-assumption`: an implementation-relevant assumption is carried by context rather than text.
- `plan-output-gap`: the written plan may represent a plausible but wrong version of the intended target.

## Sub-agent output contract

Return a single block in this shape:

```md
DraftSection:
<exact section content for ## Intent Model (must include the section header)>

Checklist:
- Latent target captured: Pass | Fail
- Anti-targets captured: Pass | Fail
- Expression-state notes captured: Pass | Fail
- Open loops typed: Pass | Fail
- Blocking open loops surfaced: Pass | Fail
- Intent checksum present: Pass | Fail

Questions:
- <only blocking questions>

Notes:
- <optional suggested updates to Problem Definition / Risks / Decision Log>
```

## Malformed output handling

- If you cannot produce the exact section header or required fields, return `Questions` explaining what is missing and leave `DraftSection` as `N/A`.
- Do not introduce new top-level sections.
- Do not mark gates, status, approval, projection, dispatch, or review fields.
- Do not encode a human decision as plan intent. Return a blocking question or decision-boundary suggestion instead.

## Success criteria (gate: IntentModelComplete)

- `## Intent Model` exists before `## Problem Definition`.
- Latent target has substantive content and is not a restatement of implementation tasks only.
- Anti-targets are explicit or explicitly marked none with rationale.
- Expression-state notes include at least one user phrase or state that no expression ambiguity was found.
- Open Loop Ledger exists and every open loop has Type, Source, Latent object, Why it matters, Status, Resolution evidence, and Blocks.
- Any open loop with `Status: Open` and `Blocks: Problem | Technical | Implementation | Automation` keeps the relevant downstream gate failing for high-risk plans.
- Intent checksum names both success and likely wrong-but-plausible failure.

## Process

1. Restate the user's target neutrally.
2. Identify anti-targets and "reacting against" signals before proposing implementation language.
3. Map ambiguous user phrases to interpreted meaning, alternatives, confidence, and risk.
4. Create open-loop entries only for gaps that could cause a wrong build, wrong acceptance criteria, wrong scope, or wrong review.
5. Decide whether each open loop blocks Problem, Technical, Implementation, Automation, or none.
6. Draft the intent checksum as a compact acceptance guard.
7. Return questions only when the user must resolve intent before downstream planning can proceed.

## Output template

Use this exact template:

```md
## Intent Model
<!-- owner: intent-reconciliation -->
Latent target:
- What the user appears to be trying to achieve:
- What the user is reacting against:
- Non-verbal / experiential target:
- Confidence: High | Medium | Low

Anti-targets:
- ...

Expression-state notes:
- User phrase:
  - Interpreted meaning:
  - Alternate plausible interpretations:
  - Confidence: High | Medium | Low
  - Risk if wrong:

Open Loop Ledger:
- OL-001:
  - Type: lexical-gap | concept-gap | referent-gap | scope-gap | acceptance-gap | negative-constraint | hidden-assumption | plan-output-gap
  - Source:
  - Latent object:
  - Why it matters:
  - Candidate interpretations:
    - A)
    - B)
    - C)
  - Status: Open | Resolved | Deferred
  - Resolution evidence:
  - Blocks: Problem | Technical | Implementation | Automation | none

Intent checksum:
- Success means:
  - ...
- Failure would look like:
  - ...
- User confirmation needed:
  - ...
```

## UX rules

- Preserve uncertainty instead of smoothing it away.
- Prefer a small number of high-signal open loops over exhaustive ambiguity lists.
- Ask only decision-bearing questions.
- Do not accept "looks good" when the checksum lacks a wrong-but-plausible implementation.
