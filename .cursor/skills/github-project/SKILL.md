---
# atlas-tools-generated: source=skills/github-project/SKILL.md manifest=atlas-tools.v1 checksum=sha256:5d3b11b6e30193ce7da711a2658e4af00bc5dad4e433e812c5b9b4c2d46ddff8
# atlas-tools-generated-end
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
- `ExecutionRepo` text
- `BaseBranch` text
- `PlanKey` text
- `SourceId` text
- `ParentEpic` text
- `DependsOn` text
- `Blocks` text
- `ParallelGroup` text
- `CriticalPathRank` number
- `MergeGroup` text
- `CombinePolicy` text
- `ConflictClass` text
- `ValidationTier` text
- `AutomationBlockers` text
- `ReviewGates` text
- `GateTier` single select: `T0`, `T1`, `T2`, `T3`, `T4`, `T5`, `T6`
- `MergePoint` text
- `DispatchMode` single select: `agent-ready`, `manual-review`, `blocked`, `tracking-only`
- `DispatchRecommendation` single select: `auto-dispatch`, `review-before-dispatch`, `tracking-only`, `auto-dispatch-pilot`
- `IssueReady` single select: `Draft`, `Ready`, `Blocked`
- `AgentType` single select: `generalPurpose`, `test-engineer`, `code-reviewer`, `explore`
- `AutomationState` single select: `Manual`, `Draft`, `Planned`, `Ready`, `Queued`, `Running`, `PR Open`, `Review`, `Local Validation`, `Deployed Validation`, `Semantic Review`, `Repair`, `Waiting`, `Blocked`, `Human Action`, `Failed`, `Done`, `Superseded`
- `Priority` single select: `P0`, `P1`, `P2`, `P3`
- `Size` number
- `Risk` single select: `Low`, `Medium`, `High`
- `RiskTags` text
- `ValidationScope` single select: `local`, `ci`, `deployed`, `manual`
- `WriteScope` text
- `OnePRContract` single select: `Yes`, `No`, `N/A`
- `ReviewVerdict` single select: `Pending`, `Changes Requested`, `Approved`, `Validated`, `Merged`
- `ReviewRoute` single select: `wait`, `repair`, `local-validate`, `deployed-validate`, `semantic-review`, `human`, `approved`
- `BlockerType` text
- `BlockerReason` text
- `Checks` text
- `HeadSha` text
- `TargetDate` date
- `ActivePR` text
- `Validation` text

`ExecutionState` is kept for compatibility with existing automation. New boards should use `ItemType`
for shape and `AutomationState` for runtime lane. Labels such as `type:epic`, `type:story`,
`status:ready`, `agent:ready`, and `agent:pr-open` remain on issues.

The local project reconciler requires only `Status` and uses `ExecutionState=Epic` as one way to
identify epic items. Project fields are a human operating view, not planning authority.

## Template Map

Use this model for the standard template:

- One plan projects to one epic issue.
- Each Automation Issue Manifest leaf projects to one story/spike/task issue; dispatchable leaves
  should satisfy the one-PR contract.
- Workstream issues are legacy/fallback stories when no manifest exists.
- Oversized stories are decomposition candidates until `Size` is `1` or the issue is explicitly
  manual/tracking-only.
- Native GitHub sub-issues can be useful for manually decomposed oversized issues, but the current
  runtime reads parent links from issue bodies (`## Parent Epic` / `## Parent Issue`) and labels, so
  do not make native sub-issues required for automation.

Field source map:

- `Size` maps from `Points` / `Suggested points`.
- `ReviewGates` maps from manifest `Required gates` and workstream review gates.
- `GateTier` maps from `Highest tier` / `tier:*` labels.
- `DependsOn` should contain leaf ids or explicit GitHub issue refs.
- `Blocks`, `ParallelGroup`, `CriticalPathRank`, `MergeGroup`, `CombinePolicy`,
  `ConflictClass`, and `ValidationTier` map from manifest scheduler metadata.
- `AutomationBlockers`, `BlockerType`, and `BlockerReason` capture opaque dependencies, manual
  blockers, review routes, and dispatch guardrails.
- `DispatchMode` maps from the manifest `Dispatch` value.
- `DispatchRecommendation` maps from projection/runtime dispatch guidance.
- `ValidationScope`, `Validation`, and `Checks` expose local/CI/deployed/manual evidence.
- `ExecutionRepo`, `BaseBranch`, `ActivePR`, linked pull requests, and `HeadSha` expose PR safety state.

The template intentionally does not store plan-level dispatch policy as item fields. Keep
`AutomationTarget`, strategy, concurrency, branch/PR/merge policies, and human-approval rules in the
Project readme or plan/manifest, then use item fields only for filtering and operator triage.

## Public Standard Template

The canonical reusable Project template is:

- Owner: `Atlas-Memory-Framework`
- Number: `4`
- URL: `https://github.com/orgs/Atlas-Memory-Framework/projects/4`
- Visibility: public
- Linked repo: `Atlas-Memory-Framework/AtlasMemory-Tools`

Copy it with:

```bash
gh project copy 4 \
  --source-owner Atlas-Memory-Framework \
  --target-owner OWNER \
  --title "New Execution Project"
```

GitHub only allows organization-owned Projects to be marked as templates. User-owned Projects can be
schema instances, but they cannot be marked as reusable GitHub templates.

Completion rule:

- A Project is not a complete reusable execution template until `--check-views` or `--ensure-views`
  passes against the live Project.
- If the live Project has only GitHub's default `View 1`, it is schema-only even if it is public,
  linked to a repo, and marked as a template.
- Do not tell the user the template is built, ready, or reusable unless the saved views have been
  configured in GitHub UI and verified.
- Existing Projects are not retroactively converted into the copied template. They either need the
  saved views configured manually or they need to be replaced by a new Project copied from a verified
  template.

## Standard Views

Create these views for every execution Project. GitHub Project v2 saved views are readable through
GraphQL. GitHub REST can create missing views with layout, filter, and visible fields, but it does
not document saved-view update, group-by, or sort mutation parameters. Do not use undocumented
mutation fields blindly. The helper can create fields, mark organization Projects as templates, copy
Projects, and verify saved view names/configuration; group-by and sort still have to come from a
configured template copy or GitHub UI.

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

The helper verifies the managed view names and readable configuration idempotently by reading Project
views through GraphQL. If views are missing or misconfigured on the canonical template, provision them
once in the GitHub UI. If views are missing or misconfigured on a downstream Project, copy from the
verified canonical template or configure the views manually in that Project.

To print the deterministic UI setup checklist generated from the same view specs:

```bash
python3 skills/github-project/scripts/create_project.py --view-setup
```

### 1. Dispatch

Purpose: decide what should run next.

- Layout: table
- Filter: open items where `Status` is not `Done` and `ItemType` is `Story` or `Spike`
- Group by: `Priority`
- Sort: `IssueReady` ascending, `Risk` descending
- Sort note: GitHub saved views currently expose at most two sort fields. `Priority` is handled by
  grouping.
- Fields: title, assignees, labels, `ItemType`, `Workstream`, `TargetRepo`, `ExecutionRepo`,
  `Priority`, `Risk`, `RiskTags`, `Size`, `IssueReady`, `DispatchMode`,
  `DispatchRecommendation`, `DependsOn`, `Blocks`, `ParallelGroup`, `CriticalPathRank`,
  `MergeGroup`, `CombinePolicy`, `ConflictClass`, `ValidationTier`, `AutomationBlockers`,
  `AutomationState`, `BlockerType`, `BlockerReason`, `ValidationScope`, `TargetDate`

This is the operator's main queue. If it does not show dependency and risk context, people will pick
the wrong next issue.

### 2. Automation Flow

Purpose: see what the runtime thinks is active.

- Layout: board
- Group by: `AutomationState`
- Filter: all open non-epic items
- Fields: title, assignees, labels, `ItemType`, `Workstream`, `TargetRepo`, `ExecutionRepo`,
  `IssueReady`, `DispatchRecommendation`, `ParallelGroup`, `MergeGroup`, `AutomationState`,
  `Status`, linked pull requests, `ActivePR`, `HeadSha`, `ValidationTier`, `Validation`

Keep `Status` intentionally simple because automation reconciles it. Group by `AutomationState` for
finer human detail like `Queued`, `Running`, `PR Open`, validation, review, repair, blocked, and
human-action routes.

### 3. Epics

Purpose: see outcome-level progress and whether child work still exists.

- Layout: table
- Filter: `ItemType` is `Epic` or `ExecutionState` is `Epic`
- Group by: `Workstream`
- Sort: `Priority` ascending, `TargetDate` ascending
- Fields: title, labels, `Status`, `Workstream`, `TargetRepo`, `PlanKey`, `ParentEpic`, `Priority`,
  `Risk`, `TargetDate`, `Blocks`, `ReviewGates`

Epics should stay few and readable. They answer whether a plan outcome is done, blocked, or still
has child work.

### 4. Dependencies

Purpose: expose blockers before they become stale board state.

- Layout: table
- Filter: open items where `DependsOn` is not empty, `Blocks` is not empty, or `AutomationState` is
  `Blocked`
- Group by: `TargetRepo`
- Sort: `Priority` ascending, `Risk` descending
- Fields: title, `ItemType`, `Workstream`, `TargetRepo`, `ExecutionRepo`, `Priority`, `DependsOn`,
  `Blocks`, `ParallelGroup`, `CriticalPathRank`, `MergeGroup`, `CombinePolicy`, `ConflictClass`,
  `ValidationTier`, `AutomationBlockers`, `ParentEpic`, `DispatchRecommendation`,
  `AutomationState`

This view is required for multi-repo or staged work. A board without dependencies will make blocked
items look idle or forgotten.

### 5. Review Queue

Purpose: focus reviewers and finalizers.

- Layout: table
- Filter: open items where `AutomationState` is `PR Open`, `Review`, or `Repair`
- Group by: `AutomationState`
- Sort: `Priority` ascending, `TargetDate` ascending
- Fields: title, assignees, labels, `TargetRepo`, `ExecutionRepo`, linked pull requests,
  `ActivePR`, `Validation`, `ValidationScope`, `ReviewVerdict`, `ReviewRoute`, `Checks`, `HeadSha`,
  `ReviewGates`, `Risk`, `Priority`

This is the view to use before merge/finalize automation. It should make missing validation and
requested changes obvious.

### 6. Cross-Repo

Purpose: keep repo-boundary and explicit-base-branch work visible.

- Layout: table
- Filter: open items where `TargetRepo` differs from `ExecutionRepo`, or `RiskTags` contains
  `cross-repo`
- Group by: `ExecutionRepo`
- Sort: `Priority` ascending, `Risk` descending
- Fields: title, labels, `ItemType`, `Workstream`, `TargetRepo`, `ExecutionRepo`, `BaseBranch`,
  `DispatchRecommendation`, `RiskTags`, `ConflictClass`, `DependsOn`, `ReviewGates`

GitHub saved filters cannot compare two Project fields, so template copies should keep this broad
and operators can narrow by `RiskTags`.

### 7. Gate Audit

Purpose: audit gate coverage, validation scope, and one-PR dispatch safety.

- Layout: table
- Filter: open items with named gates, validation requirements, or higher gate tiers
- Group by: `GateTier`
- Sort: `GateTier` descending, `Priority` ascending
- Sort note: GitHub saved views currently expose at most two sort fields.
- Fields: title, `ItemType`, `Workstream`, `TargetRepo`, `ReviewGates`, `GateTier`,
  `ValidationTier`, `ValidationScope`, `Validation`, `Checks`, `OnePRContract`, `WriteScope`,
  `ConflictClass`, `RiskTags`

Use this before approving dispatch or finalization for risky work.

### 8. Decomposition

Purpose: find issues that are too broad for unattended issue-to-PR automation.

- Layout: table
- Filter: open story or spike items where `Size` is greater than `1`, `OnePRContract` is not `Yes`,
  or `DispatchRecommendation` is `tracking-only`
- Group by: `DispatchRecommendation`
- Sort: `Size` descending, `Priority` ascending
- Fields: title, labels, `ItemType`, `Workstream`, `TargetRepo`, `Size`, `OnePRContract`,
  `DispatchMode`, `DispatchRecommendation`, `MergeGroup`, `CombinePolicy`, `ConflictClass`,
  `WriteScope`, `AutomationBlockers`

For unattended local automation, one-point leaves are the intended executable unit. Larger issues
should be split or explicitly kept manual/tracking-only.

### 9. Risk And Dates

Purpose: planning review and delivery pressure.

- Layout: table or roadmap when dates are populated
- Filter: open items where `Risk` is `High` or `TargetDate` is not empty
- Group by: `Risk`
- Sort: `TargetDate` ascending, `Priority` ascending
- Fields: title, `ItemType`, `Workstream`, `TargetRepo`, `Priority`, `Risk`, `RiskTags`,
  `TargetDate`, `DependsOn`, `ReviewGates`, `ValidationScope`

Use this for human review, not automation dispatch.

### 10. Done Audit

Purpose: inspect completed work without polluting active views.

- Layout: table
- Filter: `Status` is `Done`
- Group by: `ItemType`
- Sort: manual/default
- Sort note: GitHub UI does not expose a reliable saved `Updated` descending sort for this view.
- Fields: title, labels, `TargetRepo`, `ExecutionRepo`, `Workstream`, linked pull requests,
  `ActivePR`, `ReviewVerdict`, `Validation`, `TargetDate`

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
   - Prefer `--template-owner Atlas-Memory-Framework --template-number 4 --ensure-views` for Projects that need the standard saved views.
   - Add `--ensure-views` to fail clearly if the standard saved views are missing.
   - Treat output with `view_completion.state=not_checked` as incomplete; it means fields/schema
     were handled but saved views were not verified.
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
