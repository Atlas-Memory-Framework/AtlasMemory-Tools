# GitHub Project Template Views

Canonical template:

- Owner: `Atlas-Memory-Framework`
- Project: `4`
- URL: `https://github.com/orgs/Atlas-Memory-Framework/projects/4`
- Repository link: `Atlas-Memory-Framework/AtlasMemory-Tools`

What this means:

- The template is the live GitHub Project above, not a file in this repo.
- The code in `skills/github-project/scripts/create_project.py` creates/verifies schema fields,
  copies the live template, and verifies saved view configuration.
- The code in `skills/plan-to-issues/scripts/plan_to_issues.py` adds issues to a selected Project
  and populates item field values.
- Existing Projects do not inherit later template edits. Copy a verified template for new work, or
  manually configure the existing Project's views.

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

Saved Project v2 views are a template/UI concern. The helper can verify these names and readable
configuration through GraphQL with `--check-views`. `--ensure-views` is intentionally conservative:
when saved views are missing it fails with template-copy guidance instead of mutating view layout,
grouping, or sort state. The supported full setup path is still to configure the canonical template
in GitHub UI once, then copy it.

Do not treat the canonical Project as a complete reusable template until view verification passes.
A Project with the standard fields and only `View 1`, or with blank tabs using the standard names,
is schema-only. Existing downstream Projects are not converted into the copied template; either
configure their views manually or create a new Project by copying the verified canonical template.

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
  --check-views
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

Use `--apply --ensure-views` only as part of field/template setup. Use `--check-views` for read-only
verification of an existing copied Project.

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
