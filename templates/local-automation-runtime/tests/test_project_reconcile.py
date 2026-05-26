from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


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

    def test_limit_defaults_from_runtime_config(self) -> None:
        with mock.patch.dict(os.environ, {"AGENT_PROJECT_ITEM_LIMIT": "750"}):
            args = self.reconcile.build_parser().parse_args([])

        self.assertEqual(args.limit, 750)

    def test_issue_filters_accept_numbers_refs_and_urls(self) -> None:
        self.assertEqual(self.reconcile.issue_filter("28"), (None, 28))
        self.assertEqual(self.reconcile.issue_filter("#28"), (None, 28))
        self.assertEqual(self.reconcile.issue_filter("owner/repo#28"), ("owner/repo", 28))
        self.assertEqual(
            self.reconcile.issue_filter("https://github.com/owner/repo/issues/28"),
            ("owner/repo", 28),
        )
        self.assertTrue(self.reconcile.item_matches_issue_filters(item(28), {(None, 28)}))
        self.assertTrue(self.reconcile.item_matches_issue_filters(item(28), {("owner/repo", 28)}))
        self.assertFalse(self.reconcile.item_matches_issue_filters(item(28), {("other/repo", 28)}))

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

    def test_issue_states_for_items_batches_by_repo(self) -> None:
        calls = []
        original_gh_json_or_none = self.reconcile.common.gh_json_or_none
        original_issue_state = self.reconcile.issue_state

        def fake_gh_json_or_none(args, retries=1):
            calls.append(args)
            self.assertEqual(args[:4], ["issue", "list", "--repo", "owner/repo"])
            return [{"number": 28, "state": "OPEN"}, {"number": 29, "state": "CLOSED"}]

        self.reconcile.common.gh_json_or_none = fake_gh_json_or_none
        self.reconcile.issue_state = lambda _repo, _number: "UNKNOWN"
        try:
            states = self.reconcile.issue_states_for_items([item(28), item(29)])
        finally:
            self.reconcile.common.gh_json_or_none = original_gh_json_or_none
            self.reconcile.issue_state = original_issue_state

        self.assertEqual(states[("owner/repo", 28)], "OPEN")
        self.assertEqual(states[("owner/repo", 29)], "CLOSED")
        self.assertEqual(len(calls), 1)

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

    def test_metadata_decision_inherits_parent_project_fields_for_decomposed_children(self) -> None:
        original_latest_pr = self.reconcile.latest_pr_for_issue
        self.reconcile.latest_pr_for_issue = lambda _repo, _number: None
        fields = {
            name: {"id": name, "options": []}
            for name in (
                "PlanKey",
                "ParentEpic",
                "ReviewGates",
                "Risk",
                "RiskTags",
                "ValidationScope",
                "Priority",
            )
        }
        fields["Risk"]["options"] = [{"name": "High", "id": "high"}]
        fields["ValidationScope"]["options"] = [{"name": "ci", "id": "ci"}]
        fields["Priority"]["options"] = [{"name": "P1", "id": "p1"}]
        try:
            config = self.reconcile.ProjectConfig(
                project_id="PROJECT",
                status_field_id="Status",
                status_options={},
                execution_state_field_id=None,
                execution_state_options={},
                fields=fields,
            )
            parent = item(
                5,
                planKey="PLAN-1",
                parentEpic="https://github.com/owner/repo/issues/1",
                reviewGates="G-BACKEND-BUILD",
                risk="High",
                riskTags="needs-ci-validation, migration",
                validationScope="ci",
                priority="P1",
            )
            child = item(
                49,
                content={
                    "type": "Issue",
                    "repository": "owner/repo",
                    "number": 49,
                    "title": "[WS2-QUOTE-CONTRACT] Child",
                    "url": "https://github.com/owner/repo/issues/49",
                    "body": """## Automation Manifest Metadata
- Suggested points: `1`

## Execution State
- Open dependencies: `none`
- Manual gates remaining: `none`

## Parent Issue
Parent issue: #5
https://github.com/owner/repo/issues/5
""",
                },
                labels=["points:1", "agent:one-point", "workstream:ws2-quote-contract"],
            )

            decisions = self.reconcile.metadata_decisions(
                "owner",
                1,
                config,
                [parent, child],
                {("owner/repo", 5): "OPEN", ("owner/repo", 49): "OPEN"},
                hydrate_metadata=True,
            )

            child_decision = next(decision for decision in decisions if decision.number == 49)
            self.assertEqual(child_decision.field_updates["PlanKey"], "PLAN-1")
            self.assertEqual(child_decision.field_updates["ParentEpic"], "https://github.com/owner/repo/issues/1")
            self.assertEqual(child_decision.field_updates["ReviewGates"], "G-BACKEND-BUILD")
            self.assertEqual(child_decision.field_updates["Risk"], "High")
            self.assertEqual(child_decision.field_updates["RiskTags"], "needs-ci-validation, migration")
            self.assertEqual(child_decision.field_updates["ValidationScope"], "ci")
            self.assertEqual(child_decision.field_updates["Priority"], "P1")
        finally:
            self.reconcile.latest_pr_for_issue = original_latest_pr

    def test_metadata_decision_inherits_parent_body_fields_when_project_fields_missing(self) -> None:
        original_latest_pr = self.reconcile.latest_pr_for_issue
        self.reconcile.latest_pr_for_issue = lambda _repo, _number: None
        fields = {
            name: {"id": name, "options": []}
            for name in (
                "Workstream",
                "TargetRepo",
                "ExecutionRepo",
                "BaseBranch",
                "PlanKey",
                "ParentEpic",
                "ReviewGates",
                "GateTier",
                "Risk",
                "RiskTags",
                "ValidationScope",
                "Priority",
            )
        }
        fields["GateTier"]["options"] = [{"name": "T0", "id": "t0"}]
        fields["Risk"]["options"] = [{"name": "High", "id": "high"}]
        fields["ValidationScope"]["options"] = [{"name": "ci", "id": "ci"}]
        fields["Priority"]["options"] = [{"name": "P1", "id": "p1"}]
        try:
            config = self.reconcile.ProjectConfig(
                project_id="PROJECT",
                status_field_id="Status",
                status_options={},
                execution_state_field_id=None,
                execution_state_options={},
                fields=fields,
            )
            parent = item(
                5,
                content={
                    "type": "Issue",
                    "repository": "owner/repo",
                    "number": 5,
                    "title": "[WS2-RUNTIME-SAFETY] Parent",
                    "url": "https://github.com/owner/repo/issues/5",
                    "body": """## Source Plan
- Plan key: `PLAN-1`

## Automation Manifest Metadata
- Target repo(s): `owner/repo`
- Execution repo: `owner/repo`
- Base branch: `main`
- Risk tags: `needs-ci-validation, migration`
- Validation scope: `ci`
- Priority: `P1`

## Named Gates
- G-BACKEND-BUILD

## Parent Epic
https://github.com/owner/repo/issues/1
""",
                },
                labels=["points:5", "tier:t0", "workstream:ws2-runtime-safety"],
            )
            child = item(
                49,
                content={
                    "type": "Issue",
                    "repository": "owner/repo",
                    "number": 49,
                    "title": "Child",
                    "url": "https://github.com/owner/repo/issues/49",
                    "body": """## Automation Manifest Metadata
- Suggested points: `1`

## Execution State
- Open dependencies: `none`
- Manual gates remaining: `none`

## Parent Issue
Parent issue: #5
https://github.com/owner/repo/issues/5
""",
                },
                labels=["points:1", "agent:one-point"],
            )

            decisions = self.reconcile.metadata_decisions(
                "owner",
                1,
                config,
                [parent, child],
                {("owner/repo", 5): "OPEN", ("owner/repo", 49): "OPEN"},
                hydrate_metadata=True,
            )

            child_decision = next(decision for decision in decisions if decision.number == 49)
            self.assertEqual(child_decision.field_updates["Workstream"], "WS2-RUNTIME-SAFETY")
            self.assertEqual(child_decision.field_updates["TargetRepo"], "owner/repo")
            self.assertEqual(child_decision.field_updates["ExecutionRepo"], "owner/repo")
            self.assertEqual(child_decision.field_updates["BaseBranch"], "main")
            self.assertEqual(child_decision.field_updates["PlanKey"], "PLAN-1")
            self.assertEqual(child_decision.field_updates["ParentEpic"], "https://github.com/owner/repo/issues/1")
            self.assertEqual(child_decision.field_updates["ReviewGates"], "G-BACKEND-BUILD")
            self.assertEqual(child_decision.field_updates["GateTier"], "T0")
            self.assertEqual(child_decision.field_updates["Risk"], "High")
            self.assertEqual(child_decision.field_updates["RiskTags"], "needs-ci-validation, migration")
            self.assertEqual(child_decision.field_updates["ValidationScope"], "ci")
            self.assertEqual(child_decision.field_updates["Priority"], "P1")
        finally:
            self.reconcile.latest_pr_for_issue = original_latest_pr

    def test_metadata_decision_inherits_unambiguous_workstream_priority(self) -> None:
        original_latest_pr = self.reconcile.latest_pr_for_issue
        self.reconcile.latest_pr_for_issue = lambda _repo, _number: None
        fields = {"Priority": {"id": "Priority", "options": [{"name": "P0", "id": "p0"}]}}
        try:
            config = self.reconcile.ProjectConfig(
                project_id="PROJECT",
                status_field_id="Status",
                status_options={},
                execution_state_field_id=None,
                execution_state_options={},
                fields=fields,
            )
            seeded = item(17, workstream="WS1-CONFIG-TYPES-01", priority="P0")
            child = item(31, workstream="WS1-CONFIG-TYPES", priority="")

            decisions = self.reconcile.metadata_decisions(
                "owner",
                1,
                config,
                [seeded, child],
                {("owner/repo", 17): "OPEN", ("owner/repo", 31): "OPEN"},
                hydrate_metadata=True,
            )

            child_decision = next(decision for decision in decisions if decision.number == 31)
            self.assertEqual(child_decision.field_updates["Priority"], "P0")
        finally:
            self.reconcile.latest_pr_for_issue = original_latest_pr

    def test_metadata_decision_defaults_priority_from_gate_tier(self) -> None:
        original_latest_pr = self.reconcile.latest_pr_for_issue
        self.reconcile.latest_pr_for_issue = lambda _repo, _number: None
        fields = {"Priority": {"id": "Priority", "options": [{"name": "P1", "id": "p1"}]}}
        try:
            config = self.reconcile.ProjectConfig(
                project_id="PROJECT",
                status_field_id="Status",
                status_options={},
                execution_state_field_id=None,
                execution_state_options={},
                fields=fields,
            )
            row = item(5, labels=["tier:t0", "type:story"], priority="")

            decisions = self.reconcile.metadata_decisions(
                "owner",
                1,
                config,
                [row],
                {("owner/repo", 5): "OPEN"},
                hydrate_metadata=True,
            )

            self.assertEqual(decisions[0].field_updates["Priority"], "P1")
        finally:
            self.reconcile.latest_pr_for_issue = original_latest_pr


if __name__ == "__main__":
    unittest.main()
