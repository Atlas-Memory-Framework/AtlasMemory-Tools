<!-- atlas-tools-generated: source=skills/plan-to-issues/reference.md manifest=atlas-tools.v1 checksum=sha256:98c30a63d11a13391fd119fa1b996036e02fdb78b5fde2a2663543e7e550e5d0 -->
<!-- atlas-tools-generated-end -->
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
- stable `SourceId` / plan-source marker in the issue body
- dispatch mode and dispatch recommendation
- scheduler metadata when present: parallel group, blocks, critical path rank, merge group, combine policy, conflict class, validation tier
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

Before apply, audit existing target issues and Project rows for duplicate or conflicting source mappings.
Fail the apply if any `SourceId`, manifest leaf id, workstream id, or `trackingIssue` mapping points to
more than one open issue/row, or if a Project row has no matching issue-body source marker.

Only apply after the user explicitly confirms and the duplicate/source-id audit passes.

After apply, run `project-queue-audit` against the created or updated issues and execution Project.
Treat these as hard failures: missing `Priority`, duplicate `SourceId`, ready/agent-ready state on an
issue larger than one point, Project-only rows, and Project `Size` mismatches against body `Points` or
`points:*` labels.

## Automation Issue Manifest

Canonical section:

```md
## Automation Issue Manifest
### Leaf issues
- LEAF-001: Parser support for manifest leaves
  - Dispatch: agent-ready
  - Points: 1
  - Target repo: service
  - Parallel group: parser-docs
  - Blocks: LEAF-002
  - Critical path rank: 1
  - Merge group: manifest-projection
  - Combine policy: combine-with-merge-group
  - Conflict class: plan-to-issues-parser
  - Validation tier: T2
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
- `Blocks` is scheduler metadata for downstream ordering; it is projected to issue bodies and the `Blocks` Project field when present. It does not replace `Depends on`.
