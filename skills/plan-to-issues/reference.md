# Plan-To-Issues Reference

## Goal

Convert one plan artifact into a small, stable issue set that can be tracked in GitHub Projects without duplicating the full plan.

## Recommended Mapping

- `1 plan -> 1 epic`
- `1 Automation Issue Manifest leaf -> 1 story/task/spike`
- `1 workstream -> 1 story` as a legacy/fallback projection
- `1 unresolved decision or time-boxed exploration -> 1 spike`

Default to workstream-based issue creation unless the plan is explicitly phase-oriented.
Use `leaf-issues` when the plan contains an automation-ready manifest of executable leaves.

## Recommended Labels

- `type:epic`
- `type:story`
- `type:spike`
- `workstream:ws1`
- `workstream:ws2`
- `workstream:ws3`
- `workstream:ws4`
- `area:core`
- `area:admin-ui`
- `area:chainlit`
- `area:infra`
- `phase:planning`
- `phase:implementation`

## Story Point Guidance

Use Fibonacci sizing:

- `1`: tiny
- `2`: small
- `3`: standard single-slice delivery
- `5`: medium multi-file work
- `8`: high-risk or cross-module work
- `13`: too large, split it

For unattended local automation, only `1` point issues are implementation-ready. Anything larger should be decomposed into one-point child issues before dispatch.

## Optional Plan Tracking Metadata

Keep tracking metadata additive and optional.

```yaml
tracking:
  provider: github
  project: "OWNER workflow readiness"
  epic: ""
  mode: draft
```

Optional per-todo references:

```yaml
todos:
  - id: ws4-contract-map
    content: Map each MVP operator surface to concrete workflow endpoints.
    status: pending
    issue: 123
```

Optional section-level comment:

```md
<!-- trackingIssue: org/repo#123 -->
```

## Issue Body Conventions

Epic body should include:

- problem and outcome
- links to the authoring plan artifact and any compiled-registry or roadmap views used for context
- success criteria
- scope and anti-scope
- dependencies
- named gates

Story body should include:

- parent epic
- workstream id
- functional owner role
- user or operator outcome
- technical scope
- acceptance criteria
- gate list
- out-of-scope note

Manifest leaf issue body should include:

- source `## Automation Issue Manifest` / `### Leaf issues` leaf id
- dispatch mode and dispatch recommendation
- execution repo and base branch
- write scope
- validation commands
- dependencies and linked issue refs
- gates
- dispatch guardrails for opaque or unsupported dependencies

Spike body should include:

- decision question
- options
- recommendation or decision method
- timebox
- evidence needed
- expected outputs

## Dry-Run Before Apply

Always run dry-run first. Preview:

- titles
- labels
- generated bodies
- target repo
- inferred workstream ids
- unresolved gaps that need user input

Only apply after the user explicitly confirms.

## Automation Issue Manifest

Canonical section:

```md
## Automation Issue Manifest
### Leaf issues
- LEAF-001: Parser support for manifest leaves
  - Dispatch: agent-ready
  - Points: 1
  - Target repo: service
  - Files in scope:
    - `skills/plan-to-issues/scripts/plan_to_issues.py`
    - `skills/plan-to-issues/scripts/test_plan_to_issues.py`
  - Validation:
    - `pytest skills/plan-to-issues/scripts/test_plan_to_issues.py`
  - Depends on: OWNER/service#42
  - Required gates: `G-ISSUE-Dry-Run`
```

Dependency rules:

- GitHub issue refs and sibling manifest leaf ids are projectable.
- Merge points, gates, decisions, assumptions, risks, and opaque prose dependencies are guardrails.
- Guardrailed leaves remain `tracking-only` until dependencies are converted to explicit issue refs or runnable manifest leaf ids.
