#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


REQUIRED_STATUS_OPTIONS = ("Todo", "In Progress", "Done")
FIELD_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "ExecutionState",
        "SINGLE_SELECT",
        ("Epic", "Story", "Spike", "Tracker", "Queued", "Running", "Blocked", "Review", "Done"),
    ),
    ("ItemType", "SINGLE_SELECT", ("Epic", "Story", "Spike", "Tracker")),
    ("Workstream", "TEXT", ()),
    ("TargetRepo", "TEXT", ()),
    ("PlanKey", "TEXT", ()),
    ("SourceId", "TEXT", ()),
    ("ParentEpic", "TEXT", ()),
    ("DependsOn", "TEXT", ()),
    ("Blocks", "TEXT", ()),
    ("ReviewGates", "TEXT", ()),
    ("GateTier", "SINGLE_SELECT", ("T0", "T1", "T2", "T3", "T4", "T5", "T6")),
    (
        "AutomationState",
        "SINGLE_SELECT",
        ("Manual", "Ready", "Queued", "Running", "PR Open", "Review", "Repair", "Blocked", "Done"),
    ),
    ("Priority", "SINGLE_SELECT", ("P0", "P1", "P2", "P3")),
    ("Size", "NUMBER", ()),
    ("Risk", "SINGLE_SELECT", ("Low", "Medium", "High")),
    ("TargetDate", "DATE", ()),
    ("Owner", "TEXT", ()),
    ("PR", "TEXT", ()),
    ("Validation", "TEXT", ()),
)


VIEW_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "Dispatch",
        "layout": "table",
        "api_filter": "is:open -status:Done itemtype:Story,Spike",
        "purpose": "Decide what should run next.",
        "filter": "Open Story or Spike items where Status is not Done.",
        "group_by": "Priority",
        "sort": ["Priority asc", "Risk desc", "TargetDate asc", "Size asc"],
        "fields": [
            "Title",
            "Assignees",
            "Labels",
            "ItemType",
            "Workstream",
            "TargetRepo",
            "Priority",
            "Risk",
            "Size",
            "DependsOn",
            "AutomationState",
            "TargetDate",
        ],
    },
    {
        "name": "Automation Flow",
        "layout": "board",
        "api_filter": "is:open -itemtype:Epic",
        "purpose": "See what the runtime thinks is active.",
        "filter": "Open non-epic items.",
        "group_by": "Status",
        "sort": ["Priority asc", "TargetDate asc"],
        "fields": [
            "Title",
            "Assignees",
            "Labels",
            "ItemType",
            "Workstream",
            "TargetRepo",
            "AutomationState",
            "PR",
            "Validation",
        ],
    },
    {
        "name": "Epics",
        "layout": "table",
        "api_filter": "itemtype:Epic",
        "unsupported_filter_parts": [
            "GitHub Project filters do not support OR across ItemType and ExecutionState; ExecutionState-only legacy epics are not included by the saved filter."
        ],
        "purpose": "See outcome-level progress and whether child work still exists.",
        "filter": "ItemType is Epic or ExecutionState is Epic.",
        "group_by": "Workstream",
        "sort": ["Priority asc", "TargetDate asc"],
        "fields": [
            "Title",
            "Labels",
            "Status",
            "Workstream",
            "TargetRepo",
            "Priority",
            "Risk",
            "TargetDate",
            "Blocks",
            "ReviewGates",
        ],
    },
    {
        "name": "Dependencies",
        "layout": "table",
        "api_filter": "is:open",
        "unsupported_filter_parts": [
            "GitHub Project filters do not support OR across DependsOn, Blocks, and AutomationState; the saved filter stays broad."
        ],
        "purpose": "Expose blockers before they become stale board state.",
        "filter": "Open items where DependsOn or Blocks is set, or AutomationState is Blocked.",
        "group_by": "TargetRepo",
        "sort": ["Priority asc", "Risk desc"],
        "fields": [
            "Title",
            "ItemType",
            "Workstream",
            "TargetRepo",
            "Priority",
            "DependsOn",
            "Blocks",
            "ParentEpic",
            "AutomationState",
        ],
    },
    {
        "name": "Review Queue",
        "layout": "table",
        "api_filter": 'is:open automationstate:"PR Open",Review,Repair',
        "purpose": "Focus reviewers and finalizers.",
        "filter": "Open items where AutomationState is PR Open, Review, or Repair.",
        "group_by": "AutomationState",
        "sort": ["Priority asc", "TargetDate asc"],
        "fields": [
            "Title",
            "Assignees",
            "Labels",
            "TargetRepo",
            "PR",
            "Validation",
            "ReviewGates",
            "Risk",
            "Priority",
        ],
    },
    {
        "name": "Risk And Dates",
        "layout": "table-or-roadmap",
        "api_layout": "table",
        "api_filter": "is:open",
        "unsupported_filter_parts": [
            "GitHub Project filters do not support OR across Risk and TargetDate; the saved filter stays broad."
        ],
        "purpose": "Planning review and delivery pressure.",
        "filter": "Open items where Risk is High or TargetDate is set.",
        "group_by": "Risk",
        "sort": ["TargetDate asc", "Priority asc"],
        "fields": [
            "Title",
            "ItemType",
            "Workstream",
            "TargetRepo",
            "Priority",
            "Risk",
            "TargetDate",
            "DependsOn",
            "ReviewGates",
        ],
    },
    {
        "name": "Done Audit",
        "layout": "table",
        "api_filter": "status:Done",
        "purpose": "Inspect completed work without polluting active views.",
        "filter": "Status is Done.",
        "group_by": "ItemType",
        "sort": ["Updated desc"],
        "fields": ["Title", "Labels", "TargetRepo", "Workstream", "PR", "Validation", "TargetDate"],
    },
)


MANAGED_VIEW_NAMES = tuple(str(view["name"]) for view in VIEW_SPECS)

DEFAULT_README = """# Execution Project

This Project is a downstream execution view for plan-projected GitHub issues.

Recommended flow:

- Epics describe plan outcomes and link back to the authoring plan.
- Stories and spikes carry workstream, acceptance criteria, gates, and parent epic links.
- Status tracks board flow only: Todo, In Progress, Done.
- ExecutionState is retained for existing automation compatibility.
- ItemType identifies item shape: Epic, Story, Spike, Tracker.
- AutomationState identifies human-readable runtime state: Manual, Ready, Queued, Running, PR Open, Review, Repair, Blocked, Done.

Planning authority stays in the markdown plan or compiled registry. Issue labels and PR links remain the execution source of truth.
"""


@dataclass(frozen=True)
class ProjectSummary:
    owner: str
    number: int
    title: str
    url: str
    id: str | None
    created: bool


@dataclass(frozen=True)
class ViewSyncResult:
    name: str
    action: str
    number: int | None = None
    unsupported_parts: tuple[str, ...] = ()


def run_json(args: list[str], input_text: str | None = None) -> dict[str, Any]:
    proc = subprocess.run(args, input=input_text, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"command failed: {' '.join(args)}\n{detail}")
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON from {' '.join(args)}: {exc}") from exc


def project_number(project: dict[str, Any]) -> int:
    try:
        return int(project["number"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"project result did not include a numeric number: {project}") from exc


def project_url(owner: str, number: int, raw_url: str | None) -> str:
    if raw_url:
        return raw_url
    if owner == "@me":
        return f"https://github.com/users/@me/projects/{number}"
    return f"https://github.com/orgs/{owner}/projects/{number}"


def list_projects(owner: str, limit: int) -> list[dict[str, Any]]:
    data = run_json(["gh", "project", "list", "--owner", owner, "--format", "json", "--limit", str(limit)])
    projects = data.get("projects")
    if not isinstance(projects, list):
        return []
    return [project for project in projects if isinstance(project, dict)]


def find_project(owner: str, title: str, limit: int) -> dict[str, Any] | None:
    for project in list_projects(owner, limit):
        if project.get("title") == title:
            return project
    return None


def create_project(owner: str, title: str) -> dict[str, Any]:
    return run_json(["gh", "project", "create", "--owner", owner, "--title", title, "--format", "json"])


def copy_project_template(source_owner: str, source_number: int, target_owner: str, title: str) -> dict[str, Any]:
    return run_json(
        [
            "gh",
            "project",
            "copy",
            str(source_number),
            "--source-owner",
            source_owner,
            "--target-owner",
            target_owner,
            "--title",
            title,
            "--format",
            "json",
        ]
    )


def edit_project(owner: str, number: int, description: str, readme: str, visibility: str) -> None:
    run_json(
        [
            "gh",
            "project",
            "edit",
            str(number),
            "--owner",
            owner,
            "--description",
            description,
            "--readme",
            readme,
            "--visibility",
            visibility,
            "--format",
            "json",
        ]
    )


def field_list(owner: str, number: int) -> list[dict[str, Any]]:
    data = run_json(["gh", "project", "field-list", str(number), "--owner", owner, "--format", "json", "--limit", "100"])
    fields = data.get("fields")
    if not isinstance(fields, list):
        return []
    return [field for field in fields if isinstance(field, dict)]


def field_options(field: dict[str, Any]) -> set[str]:
    options = field.get("options") or []
    if not isinstance(options, list):
        return set()
    return {str(option.get("name")) for option in options if isinstance(option, dict) and option.get("name")}


def create_field(owner: str, number: int, name: str, data_type: str, options: tuple[str, ...]) -> None:
    args = [
        "gh",
        "project",
        "field-create",
        str(number),
        "--owner",
        owner,
        "--name",
        name,
        "--data-type",
        data_type,
        "--format",
        "json",
    ]
    if options:
        args.extend(["--single-select-options", ",".join(options)])
    run_json(args)


PROJECT_VIEW_STATE_QUERY = """
query($projectId: ID!) {
  node(id: $projectId) {
    ... on ProjectV2 {
      id
      number
      title
      fields(first: 100) {
        nodes {
          __typename
          ... on ProjectV2Field {
            id
            databaseId
            name
            dataType
          }
          ... on ProjectV2SingleSelectField {
            id
            databaseId
            name
            dataType
            options {
              id
              name
            }
          }
          ... on ProjectV2IterationField {
            id
            databaseId
            name
            dataType
          }
        }
      }
      views(first: 100) {
        nodes {
          id
          number
          name
          layout
          filter
          fields(first: 50) {
            nodes {
              __typename
              ... on ProjectV2Field {
                id
                databaseId
                name
              }
              ... on ProjectV2SingleSelectField {
                id
                databaseId
                name
              }
              ... on ProjectV2IterationField {
                id
                databaseId
                name
              }
            }
          }
          groupByFields(first: 10) {
            nodes {
              __typename
              ... on ProjectV2Field {
                id
                databaseId
                name
              }
              ... on ProjectV2SingleSelectField {
                id
                databaseId
                name
              }
              ... on ProjectV2IterationField {
                id
                databaseId
                name
              }
            }
          }
          sortByFields(first: 10) {
            nodes {
              direction
              field {
                __typename
                ... on ProjectV2Field {
                  id
                  databaseId
                  name
                }
                ... on ProjectV2SingleSelectField {
                  id
                  databaseId
                  name
                }
                ... on ProjectV2IterationField {
                  id
                  databaseId
                  name
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


def run_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for name, value in variables.items():
        args.extend(["-F", f"{name}={value}"])
    data = run_json(args)
    errors = data.get("errors")
    if errors:
        raise SystemExit("GitHub GraphQL request failed: " + json.dumps(errors, indent=2, sort_keys=True))
    payload = data.get("data")
    if not isinstance(payload, dict):
        raise SystemExit("GitHub GraphQL response did not include a data object.")
    return payload


def project_id_from_view(owner: str, number: int) -> str:
    project = run_json(["gh", "project", "view", str(number), "--owner", owner, "--format", "json"])
    project_id = project.get("id")
    if not isinstance(project_id, str) or not project_id:
        raise SystemExit(f"project {owner}/{number} did not include a ProjectV2 node id.")
    return project_id


def fetch_project_view_state(project_id: str) -> dict[str, Any]:
    data = run_graphql(PROJECT_VIEW_STATE_QUERY, {"projectId": project_id})
    project = data.get("node")
    if not isinstance(project, dict):
        raise SystemExit(f"GraphQL node {project_id} is not a ProjectV2 or is not visible to this token.")
    return project


def field_database_ids(project: dict[str, Any]) -> dict[str, int]:
    fields = ((project.get("fields") or {}).get("nodes") or [])
    field_ids: dict[str, int] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        database_id = field.get("databaseId")
        if isinstance(name, str) and isinstance(database_id, int):
            field_ids[name] = database_id
    return field_ids


def managed_views(project: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    views = ((project.get("views") or {}).get("nodes") or [])
    by_name = {name: [] for name in MANAGED_VIEW_NAMES}
    for view in views:
        if not isinstance(view, dict):
            continue
        name = view.get("name")
        if isinstance(name, str) and name in by_name:
            by_name[name].append(view)
    return by_name


def check_standard_views(project: dict[str, Any]) -> list[ViewSyncResult]:
    by_name = managed_views(project)
    results: list[ViewSyncResult] = []
    errors: list[str] = []
    for name in MANAGED_VIEW_NAMES:
        views = by_name[name]
        if not views:
            results.append(ViewSyncResult(name, "missing"))
            errors.append(f"missing managed Project view: {name}")
        elif len(views) > 1:
            results.append(ViewSyncResult(name, "duplicate", views[0].get("number") if isinstance(views[0], dict) else None))
            errors.append(f"duplicate managed Project view name: {name}")
        else:
            number_value = views[0].get("number")
            results.append(ViewSyncResult(name, "present", number_value if isinstance(number_value, int) else None))
    if errors:
        raise SystemExit("Project view check failed:\n- " + "\n- ".join(errors))
    return results


def ensure_standard_views(project_id: str) -> list[ViewSyncResult]:
    project = fetch_project_view_state(project_id)
    try:
        return check_standard_views(project)
    except SystemExit as exc:
        raise SystemExit(
            str(exc)
            + "\n\n"
            + "Saved Project v2 views are verified through GraphQL, but this helper does not create "
            + "or update saved views directly. Current GitHub GraphQL exposes ProjectV2View reads, "
            + "not view create/update mutations, and REST only documents view creation with token "
            + "limitations and no update endpoint. Provision standard views by copying a preconfigured "
            + "Project template with --template-owner and --template-number."
        ) from exc


def ensure_fields(owner: str, number: int) -> list[str]:
    warnings: list[str] = []
    fields = field_list(owner, number)
    by_name = {str(field.get("name")): field for field in fields if field.get("name")}

    status = by_name.get("Status")
    if status is None:
        create_field(owner, number, "Status", "SINGLE_SELECT", REQUIRED_STATUS_OPTIONS)
    else:
        missing = [option for option in REQUIRED_STATUS_OPTIONS if option not in field_options(status)]
        if missing:
            warnings.append(
                "Status field is missing required option(s): "
                + ", ".join(missing)
                + ". Add them in GitHub before running local project reconciliation."
            )

    for name, data_type, options in FIELD_SPECS:
        existing = by_name.get(name)
        if existing is None:
            create_field(owner, number, name, data_type, options)
            continue
        if options:
            missing = [option for option in options if option not in field_options(existing)]
            if missing:
                warnings.append(
                    f"{name} field is missing option(s): "
                    + ", ".join(missing)
                    + ". Add them in GitHub to match the standard execution schema."
                )
    return warnings


def required_fields() -> dict[str, Any]:
    return {
        "Status": list(REQUIRED_STATUS_OPTIONS),
        **{name: list(options) if options else data_type for name, data_type, options in FIELD_SPECS},
    }


def summarize(owner: str, project: dict[str, Any], created: bool) -> ProjectSummary:
    number = project_number(project)
    return ProjectSummary(
        owner=owner,
        number=number,
        title=str(project.get("title") or ""),
        url=project_url(owner, number, project.get("url") if isinstance(project.get("url"), str) else None),
        id=str(project.get("id")) if project.get("id") else None,
        created=created,
    )


def view_results_payload(results: list[ViewSyncResult]) -> list[dict[str, Any]]:
    return [
        {
            "name": result.name,
            "action": result.action,
            "number": result.number,
            "unsupported_parts": list(result.unsupported_parts),
        }
        for result in results
    ]


def print_summary(summary: ProjectSummary, warnings: list[str], view_results: list[ViewSyncResult] | None = None) -> None:
    payload = {
        "owner": summary.owner,
        "number": summary.number,
        "title": summary.title,
        "url": summary.url,
        "id": summary.id,
        "created": summary.created,
        "projects_txt": f"{summary.owner}/{summary.number}",
        "plan_to_issues_arg": f'--project-url "{summary.url}"',
        "recommended_views": list(VIEW_SPECS),
        "managed_views": view_results_payload(view_results or []),
        "warnings": warnings,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_dry_run(args: argparse.Namespace) -> None:
    apply_command = [
        "python3",
        "skills/github-project/scripts/create_project.py",
        "--owner",
        args.owner,
        "--title",
        args.title,
        "--visibility",
        args.visibility,
        "--apply",
    ]
    if args.no_reuse:
        apply_command.append("--no-reuse")
    if getattr(args, "template_owner", None) and getattr(args, "template_number", None):
        apply_command.extend(["--template-owner", args.template_owner, "--template-number", str(args.template_number)])
    if getattr(args, "ensure_views", False):
        apply_command.append("--ensure-views")
    payload = {
        "mode": "dry-run",
        "owner": args.owner,
        "title": args.title,
        "visibility": args.visibility,
        "reuse_existing": not args.no_reuse,
        "required_fields": required_fields(),
        "recommended_views": list(VIEW_SPECS),
        "managed_view_names": list(MANAGED_VIEW_NAMES),
        "view_creation_note": "Saved Project v2 views are GraphQL-verifiable but not directly updated by this helper. Use --template-owner and --template-number to copy a preconfigured Project with views, then --ensure-views or --check-views to verify.",
        "apply_command": apply_command,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or verify a plan-projection GitHub Project v2.")
    parser.add_argument("--owner", required=True, help='Project owner login or org. Use "@me" for the current user.')
    parser.add_argument("--title", required=True, help="Project title.")
    parser.add_argument("--description", default="Execution board for plan-projected GitHub issues.")
    parser.add_argument("--readme", default=DEFAULT_README)
    parser.add_argument("--visibility", choices=("PRIVATE", "PUBLIC"), default="PRIVATE")
    parser.add_argument("--lookup-limit", type=int, default=100)
    parser.add_argument("--template-owner", help="Copy this owner/name's preconfigured Project template when creating.")
    parser.add_argument("--template-number", type=int, help="Project number to copy from --template-owner.")
    parser.add_argument(
        "--no-reuse",
        action="store_true",
        help="Always create a new project instead of reusing an exact title match.",
    )
    parser.add_argument("--apply", action="store_true", help="Create or update the project. Omit for dry-run output.")
    parser.add_argument(
        "--ensure-views",
        action="store_true",
        help="Verify standard Project v2 views after ensuring fields. Missing views fail with template-copy guidance.",
    )
    parser.add_argument(
        "--views-only",
        action="store_true",
        help="Only verify standard Project v2 views on an existing project. Does not create projects or fields.",
    )
    parser.add_argument(
        "--check-views",
        action="store_true",
        help="Verify standard Project v2 views through GraphQL without writing changes.",
    )
    parser.add_argument(
        "--force-managed-views",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    if not args.apply and not args.check_views:
        print_dry_run(args)
        return

    if args.force_managed_views:
        parser.error("--force-managed-views is not supported; use a preconfigured Project template/copy flow.")
    if bool(args.template_owner) != bool(args.template_number):
        parser.error("--template-owner and --template-number must be provided together")

    project: dict[str, Any] | None = None
    if not args.no_reuse:
        project = find_project(args.owner, args.title, args.lookup_limit)
    if (args.views_only or args.check_views) and project is None:
        raise SystemExit(
            f"{'--check-views' if args.check_views else '--views-only'} requires an existing Project titled "
            f"{args.title!r} for owner {args.owner!r}."
        )
    created = project is None
    if project is None:
        if args.template_owner and args.template_number:
            project = copy_project_template(args.template_owner, args.template_number, args.owner, args.title)
        else:
            project = create_project(args.owner, args.title)

    summary = summarize(args.owner, project, created)
    warnings: list[str] = []
    if not args.views_only and not args.check_views:
        edit_project(args.owner, summary.number, args.description, args.readme, args.visibility)
        warnings = ensure_fields(args.owner, summary.number)

    view_results: list[ViewSyncResult] = []
    if args.ensure_views or args.views_only or args.check_views:
        project_id = summary.id or project_id_from_view(args.owner, summary.number)
        view_results = ensure_standard_views(project_id)

    print_summary(summary, warnings, view_results)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
