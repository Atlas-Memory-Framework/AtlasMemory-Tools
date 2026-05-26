---
name: automation-decomposition
description: Produce the Automation Issue Manifest for /plan when a plan must project into bounded issues or unattended issue-to-PR execution. Use after implementation planning and before planning reviews when AutomationTarget is not none.
---

# /automation-decomposition

## Purpose
Convert the accepted implementation plan into a machine-readable `## Automation Issue Manifest`. This section is the contract for downstream issue projection and local automation runtime dispatch. Run as a sub-agent and return a draft section; do not write the plan artifact directly.

## Inputs
- `## Implementation Plan`
- `## Technical Plan`
- `## Risks / Assumptions / Tests`
- `## Decision Log`
- Plan State, especially `AutomationTarget`

## Required distinction
- Containers: epics, workstreams, phases, and merge points. These are planning/tracking structure.
- Leaf issues: bounded executable units that one agent can turn into one PR.
- Dependencies: explicit references between leaf issue ids, or structured external/manual blockers.
- Gates: validation evidence attached to one or more leaf issues. Gates are not dependencies.

## AutomationTarget modes
- `none`: return `AutomationReadiness: N/A`; no manifest required.
- `manifest-only`: produce a valid manifest for human review; dispatch can remain blocked.
- `issue-projection`: every leaf issue can become a GitHub issue without additional decomposition.
- `unattended-prs`: every `agent-ready` leaf issue has enough scope, dependency, validation, and dispatch metadata for local issue-to-PR automation after human dispatch approval.

## Leaf issue rules
Each leaf issue must include:
- stable id, title, type, parent container, owner, and dispatch mode
- bounded files in scope and explicit files/areas out of scope when risk warrants it
- dependencies that resolve to other leaf issue ids, or external/manual blockers with owner and status
- required gate ids that exist in the implementation plan and define where/entrypoint/green means
- acceptance criteria that are executable by command or evidence artifact
- one-PR contract and source plan sections
- scheduler metadata for local automation: parallel group, blocks, critical path rank, merge group, combine policy, conflict class, and validation tier; use `none` only when the field is not applicable

Allowed dispatch modes:
- `agent-ready`: eligible for issue-to-PR automation after dependencies close and human dispatch approval is present.
- `manual-review`: issue can be created, but a human must review before any agent starts implementation.
- `blocked`: issue can be tracked, but cannot dispatch until blocker status changes.
- `tracking-only`: container or coordination issue; never dispatched as implementation work.

## Risk to dispatch policy
Convert risk into execution boundaries. Examples:
- live commerce/payment/checkout, secrets, auth, webhooks, migrations, infra/deploy, public API contracts, data deletion, compliance, or customer-impacting changes default to `manual-review` or `blocked`.
- uncertain vendor/API behavior becomes a spike leaf issue before production wiring.
- no frontend or mutation wiring should depend on a risky backend integration until the spike/contract issue closes.
- merge/integration work must be represented as a leaf issue when it requires code changes or validation beyond tracking.

## Validation checklist
Return `Fail` unless:
- no opaque dependency strings remain
- every dependency resolves to a leaf id, structured external blocker, or structured manual blocker
- no `G-*`, `MP*`, `DR-*`, `A*`, or `R*` token is used as a dependency unless wrapped as a structured blocker
- every gate is defined and attached to at least one leaf issue
- every `agent-ready` issue has bounded write scope, validation command/evidence, dispatch mode, and one-PR contract
- every `agent-ready` issue has explicit scheduler metadata, with `Blocks: none` when it does not unblock another leaf or issue
- no `agent-ready` issue exceeds a reasonable budget: more than one repo, broad cross-cutting file ownership, unclear risk, or no focused acceptance criteria

## Sub-agent output contract
Return a single block:

```md
DraftSection:
<exact section content for ## Automation Issue Manifest>

Checklist:
- <criterion>: Pass | Fail

Questions:
- <if blocked>

Notes:
- <optional risks/dispatch policy observations>
```

## Output template
Use this structure:

```md
## Automation Issue Manifest
### Dispatch policy
- Automation target: none | manifest-only | issue-projection | unattended-prs
- Dispatch strategy: sequential | parallel-bounded | fanout
- Max concurrent work items:
- Required labels:
- Default reviewer / reviewer pool:
- Branch policy:
- PR policy: draft | ready-for-review
- Merge policy: manual | auto-merge-after-gates
- Rebase/update policy:
- Failure policy:
- Human approval required before dispatch: yes | no

### Containers
- <ID>:
  - Type: epic | workstream | phase | merge-point
  - Parent:
  - Dispatch: tracking-only
  - Source plan sections:
    - ...

### Leaf issues
- <ID>: <title>
  - Type: spike | story | task | validation | integration | release
  - Parent: <container id>
  - Owner:
  - Agent type: generalPurpose | test-engineer | code-reviewer | explore
  - Dispatch: agent-ready | manual-review | blocked | tracking-only
  - Depends on:
    - <leaf issue id>
  - Parallel group: <group id or none>
  - Blocks:
    - <leaf issue id, GitHub issue ref, or none>
  - Critical path rank: <integer or none>
  - Merge group: <group id or none>
  - Combine policy: solo | combine-with-merge-group | never-combine | none
  - Conflict class: <class id or none>
  - Validation tier: T0 | T1 | T2 | T3 | T4 | T5 | T6 | none
  - External blockers:
    - <owner/status/blocker or none>
  - Manual blockers:
    - <owner/status/blocker or none>
  - Files in scope:
    - path/to/file.ext
  - Files out of scope:
    - path/to/file.ext
  - Required gates:
    - G-...
  - Validation:
    - <command or evidence artifact>
  - Acceptance criteria:
    - ...
  - One PR contract: yes | no
  - Risk / dispatch notes:
  - Source plan sections:
    - ...

### Manifest validation summary
- Dependency graph acyclic: Pass | Fail
- Dependencies resolvable: Pass | Fail
- Gate coverage complete: Pass | Fail
- File-scope conflicts resolved: Pass | Fail
- Acceptance criteria executable: Pass | Fail
- Required metadata complete: Pass | Fail
- Notes / waivers (must cite DR-xxx):
  - ...
```
