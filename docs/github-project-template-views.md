# GitHub Project Template Views

Canonical template:

- Owner: `Atlas-Memory-Framework`
- Project: `4`
- URL: `https://github.com/orgs/Atlas-Memory-Framework/projects/4`
- Repository link: `Atlas-Memory-Framework/AtlasMemory-Tools`

The standard execution Project uses these saved view names:

- `Dispatch`
- `Automation Flow`
- `Epics`
- `Dependencies`
- `Review Queue`
- `Cross-Repo`
- `Gate Audit`
- `Decomposition`
- `Risk And Dates`
- `Done Audit`

Saved Project v2 views are a template/UI concern. The helper can verify these names through GraphQL
with `--ensure-views`, `--check-views`, or `--views-only --apply`, but it does not create or update
saved view configuration directly because GitHub does not expose Project v2 saved-view mutations
through the CLI/API surface this skill can use.

For a new Project that must include the standard saved views, copy a prepared template Project:

```bash
gh project copy 4 \
  --source-owner Atlas-Memory-Framework \
  --target-owner OWNER \
  --title "TITLE"
```

Then verify the copied Project:

```bash
python3 skills/github-project/scripts/create_project.py \
  --owner OWNER \
  --title "TITLE" \
  --ensure-views
```

The same copy path can be used directly through the skill:

```bash
python3 skills/github-project/scripts/create_project.py \
  --owner OWNER \
  --title "TITLE" \
  --apply \
  --template-owner Atlas-Memory-Framework \
  --template-number 4 \
  --ensure-views
```

Projected issues should be added through `plan-to-issues` with `--project-url` or project
owner/number arguments. The projection path adds each issue to the Project and then syncs the
template fields (`ItemType`, `Workstream`, `TargetRepo`, `DependsOn`, `AutomationState`,
`ValidationScope`, `OnePRContract`, and the rest of the execution metadata) so the saved views are
usable immediately after issue creation.

To print the exact UI setup checklist for the canonical template:

```bash
python3 skills/github-project/scripts/create_project.py --view-setup
```

After configuring or copying views, run:

```bash
python3 skills/github-project/scripts/create_project.py \
  --owner Atlas-Memory-Framework \
  --title "Atlas Execution Project Template" \
  --check-views
```
