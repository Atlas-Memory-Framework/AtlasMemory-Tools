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

Useful for human review and plan projection:

- `Workstream` text
- `TargetRepo` text
- `Priority` single select: `P0`, `P1`, `P2`, `P3`
- `Size` number
- `Risk` single select: `Low`, `Medium`, `High`
- `TargetDate` date

The local project reconciler requires only `Status` and uses `ExecutionState=Epic` as one way to identify epic items. Labels such as `type:epic`, `type:story`, `status:ready`, and `agent:ready` remain on issues.

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

## Output

Report:

- project title and owner
- whether it was created or reused
- project URL
- `projects.txt` line
- `plan-to-issues` argument
- any schema gaps that require manual GitHub UI changes

## Supporting Files

- Project creation helper: `scripts/create_project.py`
