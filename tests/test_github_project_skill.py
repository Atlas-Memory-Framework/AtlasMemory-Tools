from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "github-project" / "scripts" / "create_project.py"


def load_create_project_module():
    spec = importlib.util.spec_from_file_location("github_project_create_project", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GithubProjectSkillTests(unittest.TestCase):
    def test_dry_run_exposes_standard_fields_and_views(self) -> None:
        module = load_create_project_module()
        args = argparse.Namespace(owner="OWNER", title="Execution", visibility="PRIVATE", no_reuse=False)
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            module.print_dry_run(args)

        payload = json.loads(output.getvalue())
        fields = payload["required_fields"]
        self.assertEqual(fields["Status"], ["Todo", "In Progress", "Done"])
        self.assertEqual(fields["ItemType"], ["Epic", "Story", "Spike", "Tracker"])
        self.assertIn("DependsOn", fields)
        self.assertIn("Blocks", fields)
        self.assertIn("AutomationState", fields)
        self.assertIn("DispatchMode", fields)
        self.assertIn("DispatchRecommendation", fields)
        self.assertIn("ValidationScope", fields)
        self.assertIn("WriteScope", fields)
        self.assertIn("OnePRContract", fields)
        self.assertIn("template_map", payload)
        self.assertEqual(payload["standard_template"]["owner"], "Atlas-Memory-Framework")
        self.assertEqual(payload["standard_template"]["number"], 4)
        view_names = [view["name"] for view in payload["recommended_views"]]
        self.assertEqual(
            view_names,
            [
                "Dispatch",
                "Automation Flow",
                "Epics",
                "Dependencies",
                "Review Queue",
                "Cross-Repo",
                "Gate Audit",
                "Decomposition",
                "Risk And Dates",
                "Done Audit",
            ],
        )

    def test_dry_run_documents_saved_views_need_template_setup(self) -> None:
        module = load_create_project_module()
        args = argparse.Namespace(owner="OWNER", title="Execution", visibility="PRIVATE", no_reuse=False)
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            module.print_dry_run(args)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["managed_view_names"], [view["name"] for view in payload["recommended_views"]])
        self.assertIn("Saved Project v2 views", payload["view_creation_note"])
        self.assertIn("not fully created or updated by this helper", payload["view_creation_note"])
        self.assertIn("group-by, or sort", payload["view_creation_note"])
        self.assertIn("schema-only", payload["view_creation_note"])
        self.assertIn("--check-views or --ensure-views", payload["view_creation_note"])

    def test_summary_marks_views_incomplete_when_not_checked(self) -> None:
        module = load_create_project_module()
        summary = module.ProjectSummary(
            owner="OWNER",
            number=1,
            title="Execution",
            url="https://github.com/orgs/OWNER/projects/1",
            id="PVT_project",
            created=True,
        )
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            module.print_summary(summary, ["warning"], None)

        payload = json.loads(output.getvalue())
        self.assertFalse(payload["view_completion"]["complete"])
        self.assertEqual(payload["view_completion"]["state"], "not_checked")
        self.assertIn("schema-only", payload["view_completion"]["note"])

    def test_summary_marks_views_verified_after_check(self) -> None:
        module = load_create_project_module()
        summary = module.ProjectSummary(
            owner="OWNER",
            number=1,
            title="Execution",
            url="https://github.com/orgs/OWNER/projects/1",
            id="PVT_project",
            created=False,
        )
        results = [module.ViewSyncResult(name, "present", index) for index, name in enumerate(module.MANAGED_VIEW_NAMES, start=1)]
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            module.print_summary(summary, [], results)

        payload = json.loads(output.getvalue())
        self.assertTrue(payload["view_completion"]["complete"])
        self.assertEqual(payload["view_completion"]["state"], "verified")

    def test_existing_single_selects_warn_when_options_are_missing(self) -> None:
        module = load_create_project_module()
        existing_fields = [
            {
                "name": "Status",
                "options": [{"name": "Todo"}, {"name": "In Progress"}, {"name": "Done"}],
            },
            {
                "name": "ItemType",
                "options": [{"name": "Epic"}, {"name": "Story"}],
            },
        ]

        with (
            patch.object(module, "field_list", return_value=existing_fields),
            patch.object(module, "create_field") as create_field,
        ):
            warnings = module.ensure_fields("OWNER", 1)

        self.assertTrue(any("ItemType field is missing option(s): Spike, Tracker" in warning for warning in warnings))
        created_names = [call.args[2] for call in create_field.call_args_list]
        self.assertIn("DependsOn", created_names)
        self.assertIn("AutomationState", created_names)
        self.assertIn("DispatchMode", created_names)
        self.assertIn("ValidationScope", created_names)

    def test_view_setup_markdown_is_generated_from_managed_views(self) -> None:
        module = load_create_project_module()

        setup = module.view_setup_markdown()

        self.assertIn("Atlas Execution Project Template Views", setup)
        self.assertIn("https://github.com/orgs/Atlas-Memory-Framework/projects/4", setup)
        for name in module.MANAGED_VIEW_NAMES:
            self.assertIn(f". {name}", setup)
        self.assertIn("--check-views", setup)
        self.assertIn("gh project copy 4", setup)

    def test_ensure_standard_views_fails_missing_with_template_guidance(self) -> None:
        module = load_create_project_module()
        initial_state = {
            "fields": {
                "nodes": [
                    {"name": "Status", "databaseId": 1},
                    {"name": "ItemType", "databaseId": 2},
                    {"name": "Priority", "databaseId": 3},
                    {"name": "Risk", "databaseId": 4},
                    {"name": "TargetDate", "databaseId": 5},
                    {"name": "Size", "databaseId": 6},
                    {"name": "AutomationState", "databaseId": 7},
                    {"name": "Workstream", "databaseId": 8},
                    {"name": "TargetRepo", "databaseId": 9},
                    {"name": "DependsOn", "databaseId": 10},
                    {"name": "Blocks", "databaseId": 11},
                    {"name": "ParentEpic", "databaseId": 12},
                    {"name": "PR", "databaseId": 13},
                    {"name": "Validation", "databaseId": 14},
                    {"name": "ReviewGates", "databaseId": 15},
                ]
            },
            "views": {"nodes": [{"name": "View 1", "number": 1}]},
        }

        with patch.object(module, "fetch_project_view_state", return_value=initial_state):
            with self.assertRaises(SystemExit) as raised:
                module.ensure_standard_views("PVT_project")

        message = str(raised.exception)
        self.assertIn("missing managed Project view: Dispatch", message)
        self.assertIn("--template-owner and --template-number", message)

    def test_ensure_standard_views_does_not_duplicate_existing_views(self) -> None:
        module = load_create_project_module()
        state = {
            "fields": {"nodes": []},
            "views": {
                "nodes": [
                    {"name": "View 1", "number": 1},
                    *[
                        {"name": name, "number": index + 2}
                        for index, name in enumerate(module.MANAGED_VIEW_NAMES)
                    ],
                ]
            },
        }

        with patch.object(module, "fetch_project_view_state", return_value=state):
            results = module.ensure_standard_views("PVT_project")

        self.assertEqual([result.action for result in results], ["present"] * len(module.MANAGED_VIEW_NAMES))

    def test_check_standard_views_fails_misconfigured_view_details(self) -> None:
        module = load_create_project_module()
        state = {
            "views": {
                "nodes": [
                    {
                        "name": "Dispatch",
                        "number": 2,
                        "layout": "table",
                        "filter": "",
                        "fields": {"nodes": [{"name": "ItemType"}]},
                        "groupByFields": {"nodes": []},
                        "sortByFields": {"nodes": []},
                    },
                    *[
                        {"name": name, "number": index + 3}
                        for index, name in enumerate(module.MANAGED_VIEW_NAMES)
                        if name != "Dispatch"
                    ],
                ]
            },
        }

        with self.assertRaises(SystemExit) as raised:
            module.check_standard_views(state)

        message = str(raised.exception)
        self.assertIn("misconfigured managed Project view Dispatch", message)
        self.assertIn("filter is ''", message)
        self.assertIn("group by is none", message)
        self.assertIn("sort is none", message)

    def test_check_standard_views_fails_with_named_missing_view(self) -> None:
        module = load_create_project_module()
        state = {"views": {"nodes": [{"name": "Dispatch", "number": 2}]}}

        with self.assertRaises(SystemExit) as raised:
            module.check_standard_views(state)

        self.assertIn("missing managed Project view: Automation Flow", str(raised.exception))

    def test_copy_project_template_invokes_gh_project_copy(self) -> None:
        module = load_create_project_module()

        with patch.object(module, "run_json", return_value={"number": 3}) as run_json:
            result = module.copy_project_template("SOURCE", 2, "TARGET", "Execution")

        self.assertEqual(result, {"number": 3})
        run_json.assert_called_once_with(
            [
                "gh",
                "project",
                "copy",
                "2",
                "--source-owner",
                "SOURCE",
                "--target-owner",
                "TARGET",
                "--title",
                "Execution",
                "--format",
                "json",
            ]
        )


if __name__ == "__main__":
    unittest.main()
