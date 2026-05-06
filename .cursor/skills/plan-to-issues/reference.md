# Plan-To-Issues Reference

## Goal

Convert one plan artifact into a small, stable issue set that can be tracked in GitHub Projects without duplicating the full plan.

## Recommended Mapping

- `1 plan -> 1 epic`
- `1 workstream -> 1 story`
- `1 unresolved decision or time-boxed exploration -> 1 spike`

Default to workstream-based issue creation unless the plan is explicitly phase-oriented.

## Recommended Labels

- `type:epic`
- `type:story`
- `type:spike`
- `workstream:ws1`
- `workstream:ws2`
- `workstream:ws3`
- `workstream:ws4`
- `area:atlas-memory`
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

## Optional Plan Tracking Metadata

Keep tracking metadata additive and optional.

```yaml
tracking:
  provider: github
  project: "MateuszKordasiewicz's Workflow readiness"
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
