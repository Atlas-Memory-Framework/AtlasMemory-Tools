---
name: critical-ideation
description: Stress-test the defined problem with concrete weaknesses, risks, assumptions-to-tests, and alternatives. Use after problem definition and before technical planning.
---

# Critical Ideation (Adversarial)

## Purpose
Challenge the idea to surface hidden risks, weak assumptions, and better alternatives before technical design. Run as a sub-agent and return a draft section to the orchestrator; do not write the plan artifact directly.

## When to use
- After problem definition is complete
- Before technical planning

## Required outputs (Challenge Packet)
- 2 concrete weaknesses (specific scenario -> impact)
- 1 end-to-end failure mode
- Assumptions -> tests (pass/fail)
- Ranked risks with owners + status
- Alternatives considered (include one disliked alternative)
- At least 1 measurable milestone
- Decision boundary if a real fork exists
 - Draft section content for `## Challenge Artifacts`

## Sub-agent output contract
Return a single block in this shape:

```md
DraftSection:
<exact section content for ## Challenge Artifacts (must include the section header)>

Checklist:
- <criterion>: Pass | Fail

Questions:
- <if blocked>

Notes:
- <optional risks/assumptions/tests updates>
```

## Malformed output handling
- If you cannot produce the exact section header or required fields, return `Questions` explaining what is missing and leave `DraftSection` as `N/A`.

## Success criteria (gate: FeatureClarity)
- Weaknesses are concrete and distinct
- At least 1 failure mode is end-to-end
- Top assumptions have tests
- Top risks have owners + status
- Alternatives include one disliked option
- Evaluation criteria is present in the plan

## Process
1) Restate the problem definition neutrally.
2) Identify weaknesses and failure mode.
3) Convert assumptions to tests.
4) Rank risks and assign owners/status.
5) List alternatives (include disliked alternative).
6) Define milestone + evidence.
7) Add decision boundary if needed.

## Output template
Use this exact template:

```md
### Challenge Packet
#### 1) What I think you’re trying to do (1–3 bullets)
- ...

#### 2) Two concrete weaknesses (must be concrete)
- W1:
- W2:

#### 3) One failure mode (end-to-end)
- FM1: <failure> — detection — mitigation/prevention

#### 4) Assumptions → tests (pass/fail)
- A1: <assumption>
  - Test:
  - Pass/Fail criteria:
  - Status: Untested | Tested | Accepted | Deferred
- A2: ...

#### 5) Ranked risks (with owners + status)
- R1 (High): <risk>
  - Mitigation:
  - Owner:
  - Status: Mitigated | Tested | Accepted | Deferred
  - Trigger (if deferred):

#### 6) Alternatives considered (including one you dislike)
- Alt A:
  - Why it might win:
  - Why you’d reject it:

#### 7) Milestone(s) + evidence
- Milestone:
  - Evidence:

#### 8) Decision boundary (ONLY if required)
- Decision needed:
  - A) ...
  - B) ...
  - C) ...
Recommended default: <A/B/C> (why)
```

## UX rules
- Be direct; avoid praise or marketing language.
- Do not invent context; challenge only what is provided.
- If the user rubber-stamps, require specifics or run the human Q/A loop.
- **Deferred requires DR + trigger (hard rule)**: do not mark any assumption/test/risk “Deferred” unless you also provide a `DR-xxx` and an explicit trigger for revisit.
