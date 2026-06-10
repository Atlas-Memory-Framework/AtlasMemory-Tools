#!/usr/bin/env python3
# atlas-tools-generated: source=skills/github-project/scripts/create_project.py manifest=atlas-tools.v1 checksum=sha256:67b5ca005f3b1164ce900336d57409e47fea55aa232c3468a63b85f9ce5877c2
# atlas-tools-generated-end
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


REQUIRED_STATUS_OPTIONS = ("Todo", "In Progress", "Done")
STANDARD_TEMPLATE_OWNER = "Atlas-Memory-Framework"
STANDARD_TEMPLATE_NUMBER = 4
STANDARD_TEMPLATE_TITLE = "Atlas Execution Project Template"
STANDARD_TEMPLATE_URL = f"https://github.com/orgs/{STANDARD_TEMPLATE_OWNER}/projects/{STANDARD_TEMPLATE_NUMBER}"
VIEW_CREATION_NOTE = (
    "Saved Project v2 views are GraphQL-verifiable but are not fully created or updated by this helper. "
    "A Project with the standard fields and only GitHub's default 'View 1' is schema-only, not a "
    "complete reusable execution template. GitHub REST can create a missing view with layout, filter, "
    "and visible fields, but it does not document saved-view update, group-by, or sort mutation. "
    "Configure the saved views once in the GitHub UI, then "
    "run --check-views or --ensure-views before reporting the template as ready."
)
BUILT_IN_VIEW_FIELDS = {"Title", "Assignees", "Labels", "Linked pull requests"}
FIELD_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "ExecutionState",
        "SINGLE_SELECT",
        ("Epic", "Story", "Spike", "Tracker", "Queued", "Running", "Blocked", "Review", "Done"),
    ),
    ("ItemType", "SINGLE_SELECT", ("Epic", "Story", "Spike", "Tracker")),
    ("Workstream", "TEXT", ()),
    ("TargetRepo", "TEXT", ()),
    ("ExecutionRepo", "TEXT", ()),
    ("BaseBranch", "TEXT", ()),
    ("PlanKey", "TEXT", ()),
    ("SourceId", "TEXT", ()),
    ("ParentEpic", "TEXT", ()),
    ("DependsOn", "TEXT", ()),
    ("Blocks", "TEXT", ()),
    ("ParallelGroup", "TEXT", ()),
    ("CriticalPathRank", "NUMBER", ()),
    ("MergeGroup", "TEXT", ()),
    ("CombinePolicy", "TEXT", ()),
    ("ConflictClass", "TEXT", ()),
    ("ValidationTier", "TEXT", ()),
    ("AutomationBlockers", "TEXT", ()),
    ("ReviewGates", "TEXT", ()),
    ("GateTier", "SINGLE_SELECT", ("T0", "T1", "T2", "T3", "T4", "T5", "T6")),
    ("MergePoint", "TEXT", ()),
    ("DispatchMode", "SINGLE_SELECT", ("agent-ready", "manual-review", "blocked", "tracking-only")),
    (
        "DispatchRecommendation",
        "SINGLE_SELECT",
        ("auto-dispatch", "review-before-dispatch", "tracking-only", "auto-dispatch-pilot"),
    ),
    ("IssueReady", "SINGLE_SELECT", ("Draft", "Ready", "Blocked")),
    ("AgentType", "SINGLE_SELECT", ("generalPurpose", "test-engineer", "code-reviewer", "explore")),
    (
        "AutomationState",
        "SINGLE_SELECT",
        (
            "Manual",
            "Draft",
            "Planned",
            "Ready",
            "Queued",
            "Running",
            "PR Open",
            "Review",
            "Local Validation",
            "Deployed Validation",
            "Semantic Review",
            "Repair",
            "Waiting",
            "Blocked",
            "Human Action",
            "Failed",
            "Done",
            "Superseded",
        ),
    ),
    ("Priority", "SINGLE_SELECT", ("P0", "P1", "P2", "P3")),
    ("Size", "NUMBER", ()),
    ("Risk", "SINGLE_SELECT", ("Low", "Medium", "High")),
    ("RiskTags", "TEXT", ()),
    ("ValidationScope", "SINGLE_SELECT", ("local", "ci", "deployed", "manual")),
    ("WriteScope", "TEXT", ()),
    ("OnePRContract", "SINGLE_SELECT", ("Yes", "No", "N/A")),
    ("ReviewVerdict", "SINGLE_SELECT", ("Pending", "Changes Requested", "Approved", "Validated", "Merged")),
    ("ReviewRoute", "SINGLE_SELECT", ("wait", "repair", "local-validate", "deployed-validate", "semantic-review", "human", "approved")),
    ("BlockerType", "TEXT", ()),
    ("BlockerReason", "TEXT", ()),
    ("Checks", "TEXT", ()),
    ("HeadSha", "TEXT", ()),
    ("TargetDate", "DATE", ()),
    ("ActivePR", "TEXT", ()),
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
        "sort": ["IssueReady asc", "Risk desc"],
        "sort_note": "GitHub saved views currently expose at most two sort fields. Priority is handled by grouping.",
        "fields": [
            "Title",
            "Assignees",
            "Labels",
            "ItemType",
            "Workstream",
            "TargetRepo",
            "ExecutionRepo",
            "Priority",
            "Risk",
            "RiskTags",
            "Size",
            "IssueReady",
            "DispatchMode",
            "DispatchRecommendation",
            "DependsOn",
            "Blocks",
            "ParallelGroup",
            "CriticalPathRank",
            "MergeGroup",
            "CombinePolicy",
            "ConflictClass",
            "ValidationTier",
            "AutomationBlockers",
            "AutomationState",
            "BlockerType",
            "BlockerReason",
            "ValidationScope",
            "TargetDate",
        ],
    },
    {
        "name": "Automation Flow",
        "layout": "board",
        "api_filter": "is:open -itemtype:Epic",
        "purpose": "See what the runtime thinks is active.",
        "filter": "Open non-epic items.",
        "group_by": "AutomationState",
        "sort": ["Priority asc", "TargetDate asc"],
        "fields": [
            "Title",
            "Assignees",
            "Labels",
            "ItemType",
            "Workstream",
            "TargetRepo",
            "ExecutionRepo",
            "IssueReady",
            "DispatchRecommendation",
            "ParallelGroup",
            "MergeGroup",
            "AutomationState",
            "Status",
            "Linked pull requests",
            "ActivePR",
            "HeadSha",
            "ValidationTier",
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
            "PlanKey",
            "ParentEpic",
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
            "ExecutionRepo",
            "Priority",
            "DependsOn",
            "Blocks",
            "ParallelGroup",
            "CriticalPathRank",
            "MergeGroup",
            "CombinePolicy",
            "ConflictClass",
            "ValidationTier",
            "AutomationBlockers",
            "ParentEpic",
            "DispatchRecommendation",
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
            "ExecutionRepo",
            "Linked pull requests",
            "ActivePR",
            "Validation",
            "ValidationScope",
            "ReviewVerdict",
            "ReviewRoute",
            "Checks",
            "HeadSha",
            "ReviewGates",
            "Risk",
            "Priority",
        ],
    },
    {
        "name": "Cross-Repo",
        "layout": "table",
        "api_filter": "is:open",
        "unsupported_filter_parts": [
            "GitHub Project filters do not compare TargetRepo and ExecutionRepo; filter by RiskTags manually when needed."
        ],
        "purpose": "Keep repo-boundary and explicit-base-branch work visible.",
        "filter": "Open items where TargetRepo differs from ExecutionRepo, or RiskTags contains cross-repo.",
        "group_by": "ExecutionRepo",
        "sort": ["Priority asc", "Risk desc"],
        "fields": [
            "Title",
            "Labels",
            "ItemType",
            "Workstream",
            "TargetRepo",
            "ExecutionRepo",
            "BaseBranch",
            "DispatchRecommendation",
            "RiskTags",
            "ConflictClass",
            "DependsOn",
            "ReviewGates",
        ],
    },
    {
        "name": "Gate Audit",
        "layout": "table",
        "api_filter": "is:open",
        "purpose": "Audit gate coverage, validation scope, and one-PR dispatch safety.",
        "filter": "Open items with named gates, validation requirements, or higher gate tiers.",
        "group_by": "GateTier",
        "sort": ["GateTier desc", "Priority asc"],
        "sort_note": "GitHub saved views currently expose at most two sort fields.",
        "fields": [
            "Title",
            "ItemType",
            "Workstream",
            "TargetRepo",
            "ReviewGates",
            "GateTier",
            "ValidationTier",
            "ValidationScope",
            "Validation",
            "Checks",
            "OnePRContract",
            "WriteScope",
            "ConflictClass",
            "RiskTags",
        ],
    },
    {
        "name": "Decomposition",
        "layout": "table",
        "api_filter": "is:open",
        "purpose": "Find issues that are not one-point and should be split before unattended dispatch.",
        "filter": "Open story or spike items where Size is greater than 1, OnePRContract is not Yes, or DispatchRecommendation is tracking-only.",
        "group_by": "DispatchRecommendation",
        "sort": ["Size desc", "Priority asc"],
        "fields": [
            "Title",
            "Labels",
            "ItemType",
            "Workstream",
            "TargetRepo",
            "Size",
            "OnePRContract",
            "DispatchMode",
            "DispatchRecommendation",
            "MergeGroup",
            "CombinePolicy",
            "ConflictClass",
            "WriteScope",
            "AutomationBlockers",
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
            "RiskTags",
            "TargetDate",
            "DependsOn",
            "ReviewGates",
            "ValidationScope",
        ],
    },
    {
        "name": "Done Audit",
        "layout": "table",
        "api_filter": "status:Done",
        "purpose": "Inspect completed work without polluting active views.",
        "filter": "Status is Done.",
        "group_by": "ItemType",
        "sort": [],
        "sort_note": "Leave manual/default; GitHub UI does not expose a reliable saved Updated-desc sort.",
        "fields": [
            "Title",
            "Labels",
            "TargetRepo",
            "ExecutionRepo",
            "Workstream",
            "Linked pull requests",
            "ActivePR",
            "ReviewVerdict",
            "Validation",
            "TargetDate",
        ],
    },
)


MANAGED_VIEW_NAMES = tuple(str(view["name"]) for view in VIEW_SPECS)

TEMPLATE_MAP: dict[str, Any] = {
    "authority": {
        "plan": "Authoring intent, rationale, and amendments.",
        "registry": "Compiled local planning structure when registry-first is active.",
        "issues": "Execution records, labels, PR links, and closure state.",
        "project": "Downstream operator UI and signal surface only.",
    },
    "item_model": {
        "plan": "One epic issue.",
        "automation_manifest_leaf": "One story/spike/task issue; one PR when dispatchable.",
        "workstream": "Legacy/fallback story issue.",
        "oversized_story": "Decomposition candidate until points/Size is 1 or explicitly manual.",
    },
    "field_sources": {
        "Size": "Points or Suggested points from the plan projection.",
        "ReviewGates": "Required gates and named review gates.",
        "GateTier": "Highest tier / tier:* labels.",
        "DependsOn": "Leaf ids or explicit GitHub issue refs only.",
        "Blocks": "Scheduler metadata for downstream ordering; leaf ids or explicit GitHub issue refs.",
        "ParallelGroup": "Manifest parallel group for bounded fanout scheduling.",
        "CriticalPathRank": "Manifest critical-path rank used to order dependency-sensitive work.",
        "MergeGroup": "Manifest merge group for PR batching decisions.",
        "CombinePolicy": "Manifest combine policy for whether leaves can share a PR.",
        "ConflictClass": "Manifest conflict class for write-scope collision review.",
        "ValidationTier": "Manifest validation tier for scheduler and operator triage.",
        "AutomationBlockers": "Opaque dependencies, manual blockers, and dispatch guardrails.",
        "DispatchMode": "Automation Issue Manifest Dispatch value.",
        "DispatchRecommendation": "Projection/runtime dispatch recommendation.",
        "ValidationScope": "Projection-inferred local/ci/deployed/manual validation scope.",
        "WriteScope": "Manifest files in scope / write scope.",
        "OnePRContract": "Manifest one-PR contract and one-point decomposition readiness.",
        "ActivePR": "Current linked automation PR URL or number when the built-in linked PR field is insufficient.",
        "HeadSha": "Current automation PR head SHA when available.",
    },
    "runtime_states": {
        "labels": [
            "agent:ready",
            "agent:running",
            "agent:pr-open",
            "agent:needs-repair",
            "agent:review-approved",
            "agent:human-action-required",
            "agent:done",
        ],
        "automation_state": [
            "Manual",
            "Draft",
            "Planned",
            "Ready",
            "Queued",
            "Running",
            "PR Open",
            "Review",
            "Local Validation",
            "Deployed Validation",
            "Semantic Review",
            "Repair",
            "Waiting",
            "Blocked",
            "Human Action",
            "Failed",
            "Done",
            "Superseded",
        ],
    },
    "views": {
        "Dispatch": "Operator queue for selecting the next runnable story/spike.",
        "Automation Flow": "Runtime lane board grouped by AutomationState.",
        "Epics": "Outcome-level plan containers and child-work progress.",
        "Dependencies": "Dependency, blocker, and guardrail audit surface.",
        "Review Queue": "PR-linked review, validation, repair, and finalizer queue.",
        "Cross-Repo": "Repo-boundary and base-branch safety surface.",
        "Gate Audit": "Validation gate, tier, and one-PR safety audit.",
        "Decomposition": "Oversized/tracking-only items that need one-point child issues.",
        "Risk And Dates": "Human planning review for high-risk or dated work.",
        "Done Audit": "Completed work and validation evidence archive.",
    },
}

DEFAULT_README = """# Execution Project

This Project is a downstream execution view for plan-projected GitHub issues.

Recommended flow:

- Epics describe plan outcomes and link back to the authoring plan.
- Stories and spikes carry workstream, acceptance criteria, gates, and parent epic links.
- Status tracks board flow only: Todo, In Progress, Done.
- ExecutionState is retained for existing automation compatibility.
- ItemType identifies item shape: Epic, Story, Spike, Tracker.
- AutomationState identifies human-readable runtime state: Manual, Draft, Planned, Ready, Queued, Running, PR Open, Review, Local Validation, Deployed Validation, Semantic Review, Repair, Waiting, Blocked, Human Action, Failed, Done, Superseded.
- DispatchMode and DispatchRecommendation explain whether a story can run, needs explicit approval, or is tracking-only.
- ParallelGroup, CriticalPathRank, MergeGroup, CombinePolicy, ConflictClass, and ValidationTier
  expose scheduler metadata from the Automation Issue Manifest.
- ExecutionRepo and BaseBranch prevent cross-repo/base-branch ambiguity during PR creation.
- WriteScope, OnePRContract, ValidationScope, and ReviewGates make one-PR safety and finalization gates visible without opening the issue body.

Planning authority stays in the markdown plan or compiled registry. Issue labels and PR links remain the execution source of truth.
"""


def view_setup_markdown() -> str:
    lines = [
        "# Atlas Execution Project Template Views",
        "",
        f"Canonical template: {STANDARD_TEMPLATE_URL}",
        "",
        "GitHub's public GraphQL/CLI surface can create fields and mark org-owned Projects as templates.",
        "GitHub REST can create missing views with layout, filter, and visible fields, but it does not",
        "document saved-view update, group-by, or sort mutation. Configure group-by and sort once in the",
        "GitHub UI on the canonical template; copied Projects should inherit them.",
        "",
        "## Setup Checklist",
        "",
        "- Ensure the Project is public if it should be discoverable from public repos.",
        "- Ensure the Project is marked as a template.",
        "- Link the Project to the public tooling repo if desired.",
        "- Rename the default view or create saved views with the exact names below.",
        "",
    ]
    for index, view in enumerate(VIEW_SPECS, start=1):
        fields = ", ".join(f"`{field}`" for field in view["fields"])
        sort = ", ".join(f"`{item}`" for item in view.get("sort", ())) or "manual/default"
        grouping_label = "Column by" if view["layout"] == "board" else "Group by"
        lines.extend(
            [
                f"## {index}. {view['name']}",
                "",
                f"- Purpose: {view['purpose']}",
                f"- Layout: `{view['layout']}`",
                f"- Filter: {view['filter']}",
                f"- Filter query: `{view.get('api_filter', '')}`",
                f"- {grouping_label}: `{view['group_by']}`",
                f"- Sort: {sort}",
                f"- Fields: {fields}",
            ]
        )
        if view.get("sort_note"):
            lines.append(f"- Sort note: {view['sort_note']}")
        unsupported = view.get("unsupported_filter_parts") or []
        if unsupported:
            lines.append("- Saved-filter note:")
            lines.extend(f"  - {item}" for item in unsupported)
        lines.append("")
    lines.extend(
        [
            "## Verification",
            "",
            "After configuring the template views, verify with:",
            "",
            "```bash",
            f"python3 skills/github-project/scripts/create_project.py --owner {STANDARD_TEMPLATE_OWNER} --title \"{STANDARD_TEMPLATE_TITLE}\" --check-views",
            "```",
            "",
            "Copy from the template with:",
            "",
            "```bash",
            f"gh project copy {STANDARD_TEMPLATE_NUMBER} --source-owner {STANDARD_TEMPLATE_OWNER} --target-owner OWNER --title \"New Execution Project\"",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


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
    details: tuple[str, ...] = ()


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
          verticalGroupByFields(first: 10) {
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


def connection_nodes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    nodes = value.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, dict)]


def project_field_name(field: Any) -> str | None:
    if not isinstance(field, dict):
        return None
    name = field.get("name")
    return name if isinstance(name, str) and name else None


def view_field_names(view: dict[str, Any], key: str) -> list[str]:
    return [name for node in connection_nodes(view.get(key)) if (name := project_field_name(node))]


def parse_sort_spec(value: str) -> tuple[str, str] | None:
    parts = value.rsplit(" ", 1)
    if len(parts) != 2:
        return None
    field, direction = parts[0].strip(), parts[1].strip().lower()
    if not field or direction not in {"asc", "desc"}:
        return None
    return field, direction


def view_sort_entries(view: dict[str, Any]) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for node in connection_nodes(view.get("sortByFields")):
        field = project_field_name(node.get("field"))
        direction = node.get("direction")
        if field and isinstance(direction, str):
            entries.append((field, direction.lower()))
    return entries


def normalized_filter(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def normalized_layout(value: Any) -> str:
    text = str(value or "").lower()
    if text.endswith("_layout"):
        return text.removesuffix("_layout")
    return text


def view_configuration_details(view: dict[str, Any], spec: dict[str, Any]) -> tuple[str, ...]:
    config_keys = ("layout", "filter", "fields", "groupByFields", "sortByFields")
    if not any(key in view for key in config_keys):
        return ()

    details: list[str] = []
    expected_layout = str(spec.get("api_layout") or spec.get("layout") or "").lower()
    actual_layout = normalized_layout(view.get("layout"))
    if expected_layout and actual_layout and actual_layout != expected_layout:
        details.append(f"layout is {actual_layout!r}, expected {expected_layout!r}")

    expected_filter = normalized_filter(spec.get("api_filter"))
    actual_filter = normalized_filter(view.get("filter"))
    if expected_filter and actual_filter != expected_filter:
        details.append(f"filter is {actual_filter!r}, expected {expected_filter!r}")

    actual_fields = set(view_field_names(view, "fields"))
    expected_custom_fields = [
        str(field)
        for field in spec.get("fields", ())
        if isinstance(field, str) and field not in BUILT_IN_VIEW_FIELDS
    ]
    missing_fields = [field for field in expected_custom_fields if field not in actual_fields]
    if missing_fields:
        details.append("missing visible field(s): " + ", ".join(missing_fields))

    expected_group = spec.get("group_by")
    group_key = "verticalGroupByFields" if normalized_layout(view.get("layout")) == "board" else "groupByFields"
    actual_group = view_field_names(view, group_key)
    if isinstance(expected_group, str) and expected_group and expected_group not in actual_group:
        found = ", ".join(actual_group) if actual_group else "none"
        label = "column by" if group_key == "verticalGroupByFields" else "group by"
        details.append(f"{label} is {found}, expected {expected_group}")

    expected_sort = tuple(
        parsed
        for item in spec.get("sort", ())
        if isinstance(item, str) and (parsed := parse_sort_spec(item))
    )
    actual_sort = tuple(view_sort_entries(view))
    if expected_sort and actual_sort != expected_sort:
        expected = ", ".join(f"{field} {direction}" for field, direction in expected_sort)
        found = ", ".join(f"{field} {direction}" for field, direction in actual_sort) or "none"
        details.append(f"sort is {found}, expected {expected}")

    return tuple(details)


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
    specs_by_name = {view["name"]: view for view in VIEW_SPECS}
    results: list[ViewSyncResult] = []
    errors: list[str] = []
    for name in MANAGED_VIEW_NAMES:
        unsupported_parts = tuple(specs_by_name.get(name, {}).get("unsupported_filter_parts", ()))
        views = by_name[name]
        if not views:
            results.append(ViewSyncResult(name, "missing", unsupported_parts=unsupported_parts))
            errors.append(f"missing managed Project view: {name}")
        elif len(views) > 1:
            results.append(
                ViewSyncResult(
                    name,
                    "duplicate",
                    views[0].get("number") if isinstance(views[0], dict) else None,
                    unsupported_parts,
                )
            )
            errors.append(f"duplicate managed Project view name: {name}")
        else:
            number_value = views[0].get("number")
            details = view_configuration_details(views[0], specs_by_name.get(name, {}))
            if details:
                results.append(
                    ViewSyncResult(
                        name,
                        "misconfigured",
                        number_value if isinstance(number_value, int) else None,
                        unsupported_parts,
                        details,
                    )
                )
                errors.append(f"misconfigured managed Project view {name}: " + "; ".join(details))
                continue
            results.append(
                ViewSyncResult(
                    name,
                    "present",
                    number_value if isinstance(number_value, int) else None,
                    unsupported_parts,
                )
            )
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
            "details": list(result.details),
        }
        for result in results
    ]


def view_completion_payload(results: list[ViewSyncResult] | None) -> dict[str, Any]:
    if not results:
        return {
            "complete": False,
            "state": "not_checked",
            "note": VIEW_CREATION_NOTE,
        }
    incomplete = [result.name for result in results if result.action != "present"]
    return {
        "complete": not incomplete,
        "state": "verified" if not incomplete else "incomplete",
        "incomplete": incomplete,
        "note": "Standard saved view names were verified through GraphQL."
        if not incomplete
        else VIEW_CREATION_NOTE,
    }


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
        "template_map": TEMPLATE_MAP,
        "managed_views": view_results_payload(view_results or []),
        "view_completion": view_completion_payload(view_results),
        "standard_template": {
            "owner": STANDARD_TEMPLATE_OWNER,
            "number": STANDARD_TEMPLATE_NUMBER,
            "url": STANDARD_TEMPLATE_URL,
        },
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
        "template_map": TEMPLATE_MAP,
        "managed_view_names": list(MANAGED_VIEW_NAMES),
        "standard_template": {
            "owner": STANDARD_TEMPLATE_OWNER,
            "number": STANDARD_TEMPLATE_NUMBER,
            "url": STANDARD_TEMPLATE_URL,
            "copy_command": [
                "gh",
                "project",
                "copy",
                str(STANDARD_TEMPLATE_NUMBER),
                "--source-owner",
                STANDARD_TEMPLATE_OWNER,
                "--target-owner",
                args.owner,
                "--title",
                args.title,
            ],
        },
        "view_creation_note": VIEW_CREATION_NOTE,
        "apply_command": apply_command,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or verify a plan-projection GitHub Project v2.")
    parser.add_argument("--owner", help='Project owner login or org. Use "@me" for the current user.')
    parser.add_argument("--title", help="Project title.")
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
    parser.add_argument(
        "--view-setup",
        action="store_true",
        help="Print the manual saved-view setup checklist generated from the standard view specs.",
    )
    args = parser.parse_args()

    if args.view_setup:
        print(view_setup_markdown(), end="")
        return
    if not args.owner or not args.title:
        parser.error("--owner and --title are required unless --view-setup is used")

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
    elif args.apply:
        warnings.append(VIEW_CREATION_NOTE)

    print_summary(summary, warnings, view_results)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
