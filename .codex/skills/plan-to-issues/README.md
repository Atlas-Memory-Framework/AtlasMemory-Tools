<!-- atlas-tools-generated: source=skills/plan-to-issues/README.md manifest=atlas-tools.v1 checksum=sha256:22cf7a6fb6b2513e1e1c92dd20e195ac0f2c6caea80841696468cd17c5ffbe87 -->
<!-- atlas-tools-generated-end -->
# /plan-to-issues skill

This skill helps project one plan artifact into GitHub issues and an optional GitHub Project without making those downstream tracking surfaces the new planning authority.

## Typical flow

1. Reference the plan explicitly:

```text
@project/plans/workflow-surfaces.plan.md
```

2. Ask for a preview first:

```text
Use plan-to-issues in dry-run mode for this plan and show me the proposed epic and child issues.
```

3. If no GitHub Project exists, create the standard board first:

```text
Use github-project to create the execution Project for this plan.
```

4. After review, ask for apply mode:

```text
Create the issues in the root repo and add them to the workflow readiness project.
```

## When to use it

- when a plan is stable enough to track in GitHub
- when you want story-level breakdown from workstreams
- when you want a project board populated from the plan

## When not to use it

- when multiple plan files are in scope and no authoring artifact is selected
- when the plan is still changing heavily and issue churn would create noise
- when the user only wants design help and no tracking artifacts yet

## Current default

Dry-run first. Apply only on explicit approval.

Authority reminders:

- markdown plans remain the authoring write surface
- compiled registry YAML remains local planning authority after compile in `registry-first`
- issues and PRs are execution truth
- GitHub Projects v2 is an execution board and signal surface, not an authoring input
- if a story appears in multiple projects, only one project may be the designated execution board; other memberships are advisory views

## CLI Notes

- The parser accepts workstreams written either as `### WS...` headings or as bullet items under `### Workstreams + merge points`.
- If you already have a GitHub Project URL, pass it as `--project-url "https://github.com/orgs/<owner>/projects/<number>"` instead of splitting owner and number by hand.
- Dry-run output now includes suggested labels, suggested points, dependencies, blockers, merge points, named gates, repo-boundary hints, deployed/manual validation requirements, and a plan stability summary.
- For stable multi-repo projection, prefer adding `tracking.epicRepo` in frontmatter and per-workstream metadata such as `Issue ready`, `Target repo`, `Blocked by`, `Points`, `Highest tier`, and `Deployed closeout only`.
- For unattended local automation, prefer `--strategy leaf-issues` and one-point Automation Issue Manifest leaves (`Points: 1`).
- To keep cloud agents off the wrong PR base, add `tracking.baseBranch` in frontmatter or `Base branch:` on a workstream when a repo should merge somewhere other than its GitHub default. The generated issues now emit `Execution repo` and `Base branch` instructions so agents do not fall back to `main`.
