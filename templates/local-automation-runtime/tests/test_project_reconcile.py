from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, filename: str):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def item(number: int, **fields) -> dict:
    payload = {
        "id": f"ITEM{number}",
        "content": {
            "type": "Issue",
            "repository": "owner/repo",
            "number": number,
            "title": "[WS1-CONFIG-TYPES-05] Add factory export metadata type fields",
            "url": f"https://github.com/owner/repo/issues/{number}",
            "body": """## Automation Manifest Metadata
- Suggested points: `1`
- Issue ready: `true`
- Dispatch mode: `agent-ready`
- Dispatch recommendation: `auto-dispatch`

## Execution State
- Open dependencies: `none`
- Manual gates remaining: `none`

## Write Scope
- `src/types/blindConfigTree.types.ts`
- `src/__tests__/blindConfigTree.types.test.ts`

## Validation Commands
- `npm run test -- src/__tests__/blindConfigTree.types.test.ts`
- `npm run build`

Parent: #2
Base branch: mat
""",
        },
        "labels": [
            "repo:instablinds2",
            "status:ready",
            "area:app",
            "area:core",
            "owner:renderer-owner-friend",
            "tier:t0",
            "type:story",
            "workstream:ws1-config-types",
            "points:1",
            "agent:one-point",
        ],
        "status": "Todo",
        "automationState": "Ready",
    }
    payload.update(fields)
    return payload


class ProjectReconcileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reconcile = load_script("atlas_agent_project_reconcile_test", "atlas-agent-project-reconcile")

    def test_desired_metadata_hydrates_child_issue_fields(self) -> None:
        pr = {
            "state": "MERGED",
            "url": "https://github.com/owner/repo/pull/35",
            "labels": [{"name": "agent:review-approved"}],
        }

        metadata = self.reconcile.desired_metadata(item(28), "CLOSED", pr)

        self.assertEqual(metadata["ItemType"], "Story")
        self.assertEqual(metadata["ExecutionState"], "Story")
        self.assertEqual(metadata["Workstream"], "WS1-CONFIG-TYPES")
        self.assertEqual(metadata["TargetRepo"], "owner/repo")
        self.assertEqual(metadata["ExecutionRepo"], "owner/repo")
        self.assertEqual(metadata["BaseBranch"], "mat")
        self.assertEqual(metadata["SourceId"], "WS1-CONFIG-TYPES-05")
        self.assertEqual(metadata["GateTier"], "T0")
        self.assertEqual(metadata["DispatchMode"], "agent-ready")
        self.assertEqual(metadata["DispatchRecommendation"], "auto-dispatch")
        self.assertEqual(metadata["IssueReady"], "Ready")
        self.assertEqual(metadata["OnePRContract"], "Yes")
        self.assertEqual(metadata["Size"], "1")
        self.assertEqual(metadata["Status"], "Done")
        self.assertEqual(metadata["AutomationState"], "Done")
        self.assertEqual(metadata["ReviewVerdict"], "Merged")
        self.assertEqual(metadata["ActivePR"], "https://github.com/owner/repo/pull/35")
        self.assertIn("src/types/blindConfigTree.types.ts", metadata["WriteScope"])
        self.assertIn("npm run build", metadata["Validation"])

    def test_metadata_decision_only_backfills_missing_static_fields(self) -> None:
        original_latest_pr = self.reconcile.latest_pr_for_issue
        self.reconcile.latest_pr_for_issue = lambda _repo, _number: None
        fields = {
            name: {"id": name, "options": []}
            for name in (
                "ItemType",
                "Workstream",
                "TargetRepo",
                "ExecutionRepo",
                "BaseBranch",
                "AutomationState",
                "Status",
                "ActivePR",
            )
        }
        fields["AutomationState"]["options"] = [{"name": "Ready", "id": "ready"}, {"name": "Done", "id": "done"}]
        fields["Status"]["options"] = [{"name": "Todo", "id": "todo"}, {"name": "Done", "id": "done"}]
        try:
            config = self.reconcile.ProjectConfig(
                project_id="PROJECT",
                status_field_id="Status",
                status_options={"Todo": "todo", "Done": "done"},
                execution_state_field_id=None,
                execution_state_options={},
                fields=fields,
            )
            row = item(28, itemType="Story")
            decisions = self.reconcile.metadata_decisions(
                "owner",
                1,
                config,
                [row],
                {("owner/repo", 28): "CLOSED"},
                hydrate_metadata=True,
            )

            self.assertEqual(len(decisions), 1)
            updates = decisions[0].field_updates
            self.assertNotIn("ItemType", updates)
            self.assertEqual(updates["Workstream"], "WS1-CONFIG-TYPES")
            self.assertEqual(updates["AutomationState"], "Done")
            self.assertEqual(updates["Status"], "Done")
        finally:
            self.reconcile.latest_pr_for_issue = original_latest_pr


if __name__ == "__main__":
    unittest.main()
