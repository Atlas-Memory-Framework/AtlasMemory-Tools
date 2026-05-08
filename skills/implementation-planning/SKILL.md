---
name: implementation-planning
description: Produce the execution plan in the current plan artifact including file deltas, workstreams, phases, and gates. Use during /plan Implementation stage.
---

# /implementation-planning

## Purpose
Create the Implementation Plan section for build execution. Run as a sub-agent and return a draft section to the orchestrator; do not write the plan artifact directly.

## Required outputs
- Exhaustive file deltas with change type, explicit owner (existing agent/WS), and rationale.
- Workstreams with dependencies, merge points, and explicitly owned files.
- An integration / merge points checklist (what gets integrated, how, and what gates run).
- Enforce the workstream file-ownership rule: each file delta is owned by exactly one workstream until an explicit merge point.
- Phases and tasks mapped to workstreams/owners.
- Evidence-based exit criteria per phase.
- Build-time gates for each phase.
- Test Plan including at least a minimal test matrix (risk -> test type -> where it runs).
- Rollout/Deployment steps (even minimal) and an explicit rollback trigger + rollback steps.
 - Draft section content for `## Implementation Plan`

## Anti-placeholder rule (hard rule)
- Do not use placeholder language like “run smoke tests” or “add gates” without naming:
  - the gate name(s),
  - where they run (CI vs local vs deployed), and
  - the entrypoint/command (or test runner/target) and what “green” means.
- If specifics are truly unknown, convert them into either:
  - an explicit Decision boundary (A/B/C) with a recommended default, OR
  - a DR-backed Defer with an explicit trigger.

## Q/A wrapper
- The orchestrator must run the inline Q/A loop to confirm user understanding and agreement on scope, ownership, and gates.

## Ownership policy
- Prefer existing agents from the plan's `## Context Snapshot` or the user-provided roster.
- If no roster is available, return `Questions` asking for the available agents/owners before assigning work.
- Do not default all ownership to the user unless the user explicitly requests it.

## Parallel workstreams / multi-agent contract (hard rule)
- If the user requests multiple agents or parallel workstreams:
  - Ensure the draft includes an explicit **agent roster** (names/handles) and assigns ownership for each workstream and file-delta cluster.
  - If the roster is missing, ask a single focused question to obtain it (do not guess).
  - The orchestrator should mirror this roster into `## Context Snapshot` (call this out explicitly in `Notes` if needed).

## Sub-agent output contract
Return a single block in this shape:

```md
DraftSection:
<exact section content for ## Implementation Plan (must include the section header)>

Checklist:
- <criterion>: Pass | Fail

Questions:
- <if blocked>

Notes:
- <optional risks/assumptions/tests updates>
```

## Malformed output handling
- If you cannot produce the exact section header or required fields, return `Questions` explaining what is missing and leave `DraftSection` as `N/A`.

## User experience rule (no "go read the plan")
- When asking the user to confirm plan readiness, paste the key parts directly in the chat response:
  - File deltas (owned)
  - Workstreams + owned files + merge points
  - Phase list with exit criteria
  - Test matrix + rollback

## Output template (required for PlanTier: Full)
Use this exact structure so the `/plan` validator can deterministically check executability:

```md
## Implementation Plan
### Agent roster (required for PlanTier: Full)
- <agent/owner>: <responsibilities>

### File Deltas (exhaustive) + rationale
- path/to/file.ext - change type (create/modify/delete) - owner (WSx / agent) - rationale

### Workstreams + merge points
- WS1: <name>
  - Owner:
  - Depends on:
  - Review gates (named):
    - G-...
  - Owns files:
    - path/to/file.ext
  - Merge point / integration step:

### Phases + tasks + exit criteria
#### Phase 1: <name>
- Owner(s):
- Depends on:
- Tasks (by owner):
  - Owner: <agent>
    - [ ] Task
- Exit criteria (evidence):
- Gates (named):
  - G-...

### Review gates (named + definitions)
- G-...:
  - Where it runs: CI | Local | Deployed
  - Entry point / command:
  - Green means:

### Merge points -> required gates
- MP1: <merge point>
  - Blocks on:
    - G-...

### Test Matrix
- Area/component - risk - test type - where it runs

### Test plan (CI vs deployed)
- CI:
  - ...
- Deployed environment:
  - ...

### Rollout / Rollback
- Rollout:
- Rollback trigger:
- Rollback steps:
```
