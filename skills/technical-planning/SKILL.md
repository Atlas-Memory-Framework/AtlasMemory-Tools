---
name: technical-planning
description: Convert feature intent into a coherent technical approach tied to the codebase. Use during /plan Technical stage.
---

# /technical-planning

## Purpose
Translate the Design into a technical plan grounded in the current system and aligned with risks, constraints, and NFRs. The section must start with a plain-language technical narrative that a new engineer can use to understand what is being built and why before reading execution mechanics. Run as a sub-agent and return a draft section to the orchestrator; do not write the plan artifact directly.

## Ownership
- Edit only the `## Technical Plan` section in the plan template.
- Do not modify other sections except updating Risks/Assumptions/Tests when needed.

## Inputs
- Problem Definition
- Challenge Artifacts
- Context Snapshot (if available)
- Constraints, NFRs, and decision log

## Required outputs (Technical Plan)
- Technical Plan Intro: 1–3 paragraphs explaining what changes, why this approach fits, and which existing components/data flows are touched.
- Named integration points (interfaces, APIs, data contracts).
- Proposed architecture changes and integration steps.
- Failure modes per integration point.
- Explicit invariants and non-changes.
- NFR alignment (perf/security/privacy/cost/operability).
- Risks/assumptions/tests updated to reflect technical reality.
- Open questions or decision-boundary notes for any implementation-critical unknown.
- Draft section content for `## Technical Plan`

## Sub-agent output contract
Return a single block in this shape:

```md
DraftSection:
<exact section content for ## Technical Plan (must include the section header)>

Checklist:
- <criterion>: Pass | Fail

Questions:
- <if blocked>

Notes:
- <optional risks/assumptions/tests updates>
```

## Malformed output handling
- If you cannot produce the exact section header or required fields, return `Questions` explaining what is missing and leave `DraftSection` as `N/A`.

## Success criteria (gate: TechnicalClarity)
- Technical Plan Intro is readable without knowing the planning framework and ties the technical approach to the product/system problem.
- Integration points are explicit and named.
- Failure modes exist for each integration point.
- Risks/assumptions/tests are updated and consistent.
- Invariants are listed and respected.
- NFRs are addressed or explicitly deferred with DR entry.
- No implementation-critical `TBD` remains outside Open questions or a DR-backed Decision Log entry.
- Authority-contract, projection, and dispatch details are absent from the intro unless they are the system being changed.

## Decision Log / DR reference integrity (hard rule)
- Any `DR-xxx` referenced in the Technical Plan MUST already exist in the plan’s Decision Log.
- Do not write “per DR-xxx” unless:
  - that DR exists, OR
  - you also instruct the orchestrator to create it (and include the exact decision text to log).
- If you cannot locate/confirm the DR id, remove the reference and instead describe the decision plainly (and/or request a DR to be created).

## Process
1) Read the Problem Definition and extract the current workflow, desired workflow, why-now, and current-state facts.
2) Write the Technical Plan Intro in product/system language before listing mechanics.
3) Identify integration points and named interfaces.
4) Describe architecture changes and sequencing.
5) Enumerate failure modes per integration point.
6) Update risks/assumptions/tests to match the plan.
7) Confirm invariants and non-changes.
8) Check NFR alignment and document tradeoffs.

## Zero-interaction implementer rules
- If a future implementation agent would need to ask "what behavior did the user want here?", return `Questions` instead of passing.
- Use repo names, file paths, interfaces, schemas, commands, or observed code facts when available.
- If evidence is not available, mark the unknown explicitly with owner/status; do not smooth it over with "follow existing patterns" unless the exact pattern is named.
- Keep planning framework mechanics out of the intro. Put source-of-truth, projection, and dispatch constraints in execution sections or notes.

## Output template
Use this exact structure in `## Technical Plan`:

```md
## Technical Plan
### Technical Plan Intro
<1-3 paragraphs explaining what will change in the system, why this approach fits the problem, and which existing components/data flows it touches.>

### Integration Points
- ...

### Proposed Architecture Changes
- ...

### Failure Modes (per integration point)
- ...

### Invariants / Non-Changes
- ...

### NFRs alignment
- ...
```

## UX rules (no "go read the plan")
- If you need user confirmation on a technical choice or integration point, paste the relevant excerpt(s) in the chat response (interfaces/integration points, failure modes, key risks).
- Summarize what changed and what decision (if any) is needed, without requiring the user to open the plan artifact.
