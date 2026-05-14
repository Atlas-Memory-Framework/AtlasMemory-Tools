---
name: github-project
description: Create or verify a GitHub Project v2 for plan-to-issues projection and local automation runtime review. Use when the user needs a new GitHub Project for epics/stories from a plan, asks for a project board/schema for issue automation, or has no existing Project URL for plan-to-issues.
---

# GitHub Project

## Purpose

Create or verify the downstream GitHub Project v2 used by `plan-to-issues` and the local automation runtime.

Use this skill when:

- a plan is ready to project to GitHub issues but no GitHub Project exists
- the user asks for a standard project board/schema
- automation needs a `projects.txt` target or `--project-url`
- a human reviewer needs a readable board for epics, stories, spikes, and runtime state

## Authority Contract

- The markdown plan remains the authoring surface.
- In `registry-first`, compiled registry YAML remains local planning authority.
- GitHub issues are execution records.
- GitHub Projects v2 is downstream UI/signal only.
- Never infer planning truth from board field values.

## Project Schema

Required for local automation:

- `Status` single select: `Todo`, `In Progress`, `Done`
- `ExecutionState` single select: `Epic`, `Story`, `Spike`, `Tracker`, `Queued`, `Running`, `Blocked`, `Review`, `Done`

Required for readable execution planning:

- `ItemType` single select: `Epic`, `Story`, `Spike`, `Tracker`
- `Workstream` text
- `TargetRepo` text
- `PlanKey` text
- `SourceId` text
- `ParentEpic` text
- `DependsOn` text
- `Blocks` text
- `ReviewGates` text
- `GateTier` single select: `T0`, `T1`, `T2`, `T3`, `T4`, `T5`, `T6`
- `AutomationState` single select: `Manual`, `Ready`, `Queued`, `Running`, `PR Open`, `Review`, `Repair`, `Blocked`, `Done`
- `Priority` single select: `P0`, `P1`, `P2`, `P3`
- `Size` number
- `Risk` single select: `Low`, `Medium`, `High`
- `TargetDate` date
- `Owner` text
- `PR` text
- `Validation` text

`ExecutionState` is kept for compatibility with existing automation. New boards should use `ItemType`
for shape and `AutomationState` for runtime lane. Labels such as `type:epic`, `type:story`,
`status:ready`, `agent:ready`, and `agent:pr-open` remain on issues.

The local project reconciler requires only `Status` and uses `ExecutionState=Epic` as one way to
identify epic items. Project fields are a human operating view, not planning authority.

## Standard Views

Create these views for every execution Project. GitHub Project v2 saved views are readable through
GraphQL, but the authenticated GraphQL schema does not expose create/update mutations for
`ProjectV2View`. Do not rely on direct saved-view mutation.

Use a preconfigured Project template/copy flow when a new Project must start with standard saved
views:

```bash
python3 skills/github-project/scripts/create_project.py \
  --owner OWNER \
  --title "TITLE" \
  --apply \
  --template-owner TEMPLATE_OWNER \
  --template-number TEMPLATE_NUMBER \
  --ensure-views
```

Useful view-only modes:

```bash
python3 skills/github-project/scripts/create_project.py --owner OWNER --title "TITLE" --check-views
python3 skills/github-project/scripts/create_project.py --owner OWNER --title "TITLE" --views-only --apply
```

The helper verifies the managed view names idempotently by reading Project views through GraphQL. If
views are missing, provision them by copying a prepared Project template; do not ask operators to
hand-build the same standard views repeatedly.

### 1. Dispatch

Purpose: decide what should run next.

- Layout: table
- Filter: open items where `Status` is not `Done` and `ItemType` is `Story` or `Spike`
- Group by: `Priority`
- Sort: `Priority` ascending, `Risk` descending, `TargetDate` ascending, `Size` ascending
- Fields: title, assignees, labels, `ItemType`, `Workstream`, `TargetRepo`, `Priority`, `Risk`,
  `Size`, `DependsOn`, `AutomationState`, `TargetDate`

This is the operator's main queue. If it does not show dependency and risk context, people will pick
the wrong next issue.

### 2. Automation Flow

Purpose: see what the runtime thinks is active.

- Layout: board
- Group by: `Status`
- Filter: all open non-epic items
- Fields: title, assignees, labels, `ItemType`, `Workstream`, `TargetRepo`, `AutomationState`, `PR`,
  `Validation`

Keep `Status` intentionally simple because automation reconciles it. Use `AutomationState` for
finer human detail like `Queued`, `Running`, `PR Open`, `Review`, and `Repair`.

### 3. Epics

Purpose: see outcome-level progress and whether child work still exists.

- Layout: table
- Filter: `ItemType` is `Epic` or `ExecutionState` is `Epic`
- Group by: `Workstream`
- Sort: `Priority` ascending, `TargetDate` ascending
- Fields: title, labels, `Status`, `Workstream`, `TargetRepo`, `Priority`, `Risk`, `TargetDate`,
  `Blocks`, `ReviewGates`

Epics should stay few and readable. They answer whether a plan outcome is done, blocked, or still
has child work.

### 4. Dependencies

Purpose: expose blockers before they become stale board state.

- Layout: table
- Filter: open items where `DependsOn` is not empty, `Blocks` is not empty, or `AutomationState` is
  `Blocked`
- Group by: `TargetRepo`
- Sort: `Priority` ascending, `Risk` descending
- Fields: title, `ItemType`, `Workstream`, `TargetRepo`, `Priority`, `DependsOn`, `Blocks`,
  `ParentEpic`, `AutomationState`

This view is required for multi-repo or staged work. A board without dependencies will make blocked
items look idle or forgotten.

### 5. Review Queue

Purpose: focus reviewers and finalizers.

- Layout: table
- Filter: open items where `AutomationState` is `PR Open`, `Review`, or `Repair`
- Group by: `AutomationState`
- Sort: `Priority` ascending, `TargetDate` ascending
- Fields: title, assignees, labels, `TargetRepo`, `PR`, `Validation`, `ReviewGates`, `Risk`,
  `Priority`

This is the view to use before merge/finalize automation. It should make missing validation and
requested changes obvious.

### 6. Risk And Dates

Purpose: planning review and delivery pressure.

- Layout: table or roadmap when dates are populated
- Filter: open items where `Risk` is `High` or `TargetDate` is not empty
- Group by: `Risk`
- Sort: `TargetDate` ascending, `Priority` ascending
- Fields: title, `ItemType`, `Workstream`, `TargetRepo`, `Priority`, `Risk`, `TargetDate`,
  `DependsOn`, `ReviewGates`

Use this for human review, not automation dispatch.

### 7. Done Audit

Purpose: inspect completed work without polluting active views.

- Layout: table
- Filter: `Status` is `Done`
- Group by: `ItemType`
- Sort: most recently updated first
- Fields: title, labels, `TargetRepo`, `Workstream`, `PR`, `Validation`, `TargetDate`

This view exists so completed issues can remain searchable while active views stay clean.

## Inputs

Resolve before applying:

- Project owner login or org, for example `OWNER`
- Project title, usually `<repo or plan name> execution`
- Optional visibility: `PRIVATE` by default, `PUBLIC` only when the user asks
- Optional description/readme text
- Optional target repo for issue projection

If owner or title is unclear, ask. Do not create a project in a guessed account.

## Workflow

1. Verify GitHub CLI project scope:
   - `gh auth status`
   - If missing project scope: `gh auth refresh -s project`
2. Preview the project:
   - `python3 skills/github-project/scripts/create_project.py --owner OWNER --title "TITLE"`
3. Apply only when the user explicitly asked to create/sync:
   - `python3 skills/github-project/scripts/create_project.py --owner OWNER --title "TITLE" --apply`
   - Prefer `--template-owner TEMPLATE_OWNER --template-number TEMPLATE_NUMBER --ensure-views` for Projects that need the standard saved views.
   - Add `--ensure-views` to fail clearly if the standard saved views are missing.
   - Use `--views-only --apply` or `--check-views` to verify the standard view names through GraphQL without touching project metadata or fields.
4. Capture the output:
   - Project URL: `https://github.com/orgs/OWNER/projects/NUMBER` or user-project equivalent
   - Runtime target: `OWNER/NUMBER` for `projects.txt`
   - Plan-to-issues argument: `--project-url "<url>"`
5. When projecting the plan, pass the project URL to `plan-to-issues`:
   - `python3 skills/plan-to-issues/scripts/plan_to_issues.py --plan "<path>" --repo "<owner/repo>" --project-url "<url>" --dry-run`

## Guardrails

- Default to dry-run.
- Reuse an open project with the exact same title unless the user asks for a new one.
- Do not delete fields or close projects.
- If an existing `Status` field lacks `Todo`, `In Progress`, or `Done`, stop and report it; the runtime depends on those exact option names.
- Do not add issues to a Project until `plan-to-issues` has produced a dry-run preview.
- For multiple Project memberships, name exactly one execution project; others are advisory views.
- Do not call undocumented saved-view update endpoints.
- Do not treat missing standard views as routine manual setup; use a maintained Project template/copy source.
- Preserve existing views unless the user explicitly chooses to replace the Project by copying from a template.

## Output

Report:

- project title and owner
- whether it was created or reused
- project URL
- `projects.txt` line
- `plan-to-issues` argument
- managed view actions and any explicitly unsupported view configuration parts
- any schema gaps that require operator action

## Supporting Files

- Project creation helper: `scripts/create_project.py`
