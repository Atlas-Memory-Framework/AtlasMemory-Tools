---
name: human-qa-loop
description: Enforce completion of a target planning output by iterating with the user until explicit success criteria are met. Use to wrap problem definition, challenge loops, technical planning, and reviews.
---

# Human Q/A Loop (Wrapper)

## Purpose
Iterate with the user until a target section meets its explicit success criteria. The orchestrator owns plan writes; this wrapper only validates and returns updated draft content.

## When to use
- Wrap `/problem-definition`
- Wrap `/challenge-loop` (ideation or technical)
- Wrap `/technical-planning`
- Wrap `/planning-reviews` dispositions

## Inputs
- Target output (draft section or review findings)
- Explicit success criteria for the target gate
- Known blockers / missing inputs
- Mode: `comprehension` | `disposition` | `default`

## Outputs
- Updated target output (draft section)
- Success criteria checklist with Pass/Fail status
- NextRequiredUserAction if blocked
- HumanAgencyFindings (only items that require explicit user approval/decision)

## Output contract preservation
- Preserve the sub-agent output contract fields: `DraftSection`, `Checklist`, `Questions`, `Notes`.
- If you add or remove items, keep the same field names and ordering.
- If a field is not applicable, return it with `N/A`.

## Modes
### mode=comprehension
Use for technical/implementation planning. The goal is user understanding and informed judgment.
- Ask either:
  - the user to restate the plan in their own words, OR
  - the user to answer 2–3 targeted confirmation questions + confirm boundaries.
- Ask 2-3 targeted questions on risks, scope, and tradeoffs.
- Require explicit confirmation of scope/ownership and gates.
- Prefer structured questions for decision boundaries and confirmations when possible.

### mode=disposition
Use for planning reviews. The goal is explicit Accept/Reject/Defer per finding.
- Present findings and require A/R/D for each id.
- If Accept/Defer, require DR entry and trigger (if deferred).

### mode=default
Fallback for generic clarification. Use the standard loop behavior.

## Loop behavior
1) Validate target output vs criteria.
2) Ask concrete, targeted questions for missing items.
3) Reject vague confirmations ("looks good") and require specifics.
4) Patch the target output based on responses.
5) Filter findings: only keep items that require human agency (policy/source approval, contradictions with explicit assumptions/SSOT, or Unknown remediation target).
6) Repeat until criteria pass or a DR-backed deferral is logged.

## Stop rules
- Stop only when criteria are satisfied or explicitly deferred with DR entry.
- Do not advance stages if criteria are incomplete.
- Do not ask for dispositions on items that were auto-remediated or are not human-agency items.

## UX rules
- Keep questions short and specific.
- If the user defers, record the decision and the trigger to revisit.
