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
    ("Workstream", "TEXT", ()),
    ("TargetRepo", "TEXT", ()),
    ("Priority", "SINGLE_SELECT", ("P0", "P1", "P2", "P3")),
    ("Size", "NUMBER", ()),
    ("Risk", "SINGLE_SELECT", ("Low", "Medium", "High")),
    ("TargetDate", "DATE", ()),
)


DEFAULT_README = """# Execution Project

This Project is a downstream execution view for plan-projected GitHub issues.

Recommended flow:

- Epics describe plan outcomes and link back to the authoring plan.
- Stories and spikes carry workstream, acceptance criteria, gates, and parent epic links.
- Status tracks board flow only: Todo, In Progress, Done.
- ExecutionState identifies item shape for reviewers and automation: Epic, Story, Spike, Tracker, Queued, Running, Blocked, Review, Done.

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


def run_json(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
        if name not in by_name:
            create_field(owner, number, name, data_type, options)
    return warnings


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


def print_summary(summary: ProjectSummary, warnings: list[str]) -> None:
    payload = {
        "owner": summary.owner,
        "number": summary.number,
        "title": summary.title,
        "url": summary.url,
        "id": summary.id,
        "created": summary.created,
        "projects_txt": f"{summary.owner}/{summary.number}",
        "plan_to_issues_arg": f'--project-url "{summary.url}"',
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
    payload = {
        "mode": "dry-run",
        "owner": args.owner,
        "title": args.title,
        "visibility": args.visibility,
        "reuse_existing": not args.no_reuse,
        "required_fields": {
            "Status": list(REQUIRED_STATUS_OPTIONS),
            **{name: list(options) if options else data_type for name, data_type, options in FIELD_SPECS},
        },
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
    parser.add_argument(
        "--no-reuse",
        action="store_true",
        help="Always create a new project instead of reusing an exact title match.",
    )
    parser.add_argument("--apply", action="store_true", help="Create or update the project. Omit for dry-run output.")
    args = parser.parse_args()

    if not args.apply:
        print_dry_run(args)
        return

    project: dict[str, Any] | None = None
    if not args.no_reuse:
        project = find_project(args.owner, args.title, args.lookup_limit)
    created = project is None
    if project is None:
        project = create_project(args.owner, args.title)

    summary = summarize(args.owner, project, created)
    edit_project(args.owner, summary.number, args.description, args.readme, args.visibility)
    warnings = ensure_fields(args.owner, summary.number)
    print_summary(summary, warnings)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
