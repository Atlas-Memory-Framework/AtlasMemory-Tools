from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, filename: str):
    path = ROOT / filename
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def labels(*names: str) -> list[dict[str, str]]:
    return [{"name": name} for name in names]


def body(
    *,
    dependencies: str = "none",
    manual_gates: str = "none",
    dispatch_mode: str = "blocked",
    recommendation: str = "tracking-only",
) -> str:
    return f"""## Automation Manifest Metadata
- Suggested points: `1`
- Issue ready: `false`
- Dispatch mode: `{dispatch_mode}`
- Dispatch recommendation: `{recommendation}`

## Execution State
- Open dependencies: `{dependencies}`
- Manual gates remaining: `{manual_gates}`

## Write Scope
- `src/app.py`

## Validation Commands
- `pytest`
"""


def issue(number: int, issue_body: str, *label_names: str) -> dict:
    return {
        "number": number,
        "title": f"[WS-{number}] story",
        "url": f"https://github.com/owner/repo/issues/{number}",
        "body": issue_body,
        "author": {"login": "trusted"},
        "labels": labels("points:1", *label_names),
    }


def item(number: int, **fields) -> dict:
    payload = {
        "id": f"ITEM{number}",
        "content": {
            "type": "Issue",
            "repository": "owner/repo",
            "number": number,
            "title": f"[WS-{number}] story",
            "url": f"https://github.com/owner/repo/issues/{number}",
        },
        "sourceId": f"WS-{number}",
        "workstream": f"WS-{number}",
        "itemType": "Story",
        "executionState": "Story",
        "onePRContract": "Yes",
        "size": 1,
        "writeScope": "src/app.py",
        "validation": "pytest",
        "dispatchMode": "blocked",
        "dispatchRecommendation": "tracking-only",
        "issueReady": "Blocked",
        "automationState": "Planned",
        "status": "Todo",
        "labels": ["points:1"],
    }
    payload.update(fields)
    return payload


class DependencyPromoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.promote = load_script("atlas_agent_dependency_promote_test", "atlas-agent-dependency-promote")

    def setUp(self) -> None:
        self.original_gh = self.promote.common.gh_json_or_none
        self.original_authors = self.promote.common.trusted_authors
        self.original_prs = self.promote.open_prs_for_issue
        self.promote.common.trusted_authors = lambda: {"trusted"}
        self.promote.open_prs_for_issue = lambda _repo, _number: []
        self.issue_states: dict[tuple[str, int], str] = {}
        self.pr_merged: dict[tuple[str, int], bool] = {}

        def fake_gh(args, retries=3):
            if args[:2] == ["issue", "view"]:
                number = int(args[2])
                repo = args[4]
                return {"state": self.issue_states.get((repo, number), "CLOSED"), "url": f"https://github.com/{repo}/issues/{number}"}
            if args[:2] == ["pr", "view"]:
                number = int(args[2])
                repo = args[4]
                merged = self.pr_merged.get((repo, number), False)
                return {"state": "MERGED" if merged else "OPEN", "merged": merged, "url": f"https://github.com/{repo}/pull/{number}"}
            return None

        self.promote.common.gh_json_or_none = fake_gh

    def tearDown(self) -> None:
        self.promote.common.gh_json_or_none = self.original_gh
        self.promote.common.trusted_authors = self.original_authors
        self.promote.open_prs_for_issue = self.original_prs

    def decide(self, candidate_issue: dict, candidate_item: dict, all_items: list[dict] | None = None):
        all_items = all_items or [candidate_item]
        dependency_map = self.promote.build_dependency_map(all_items)
        project = self.promote.ProjectTarget("owner", 1)
        return self.promote.classify_issue("owner/repo", candidate_issue, candidate_item, project, dependency_map)

    def test_ws_token_closed_upstream_promotes_downstream(self) -> None:
        upstream = item(3, sourceId="WS-3", workstream="WS-3")
        candidate_item = item(4, sourceId="WS-4", dependsOn="WS-3")
        candidate_issue = issue(4, body(dependencies="WS-3"))
        self.issue_states[("owner/repo", 3)] = "CLOSED"

        decision = self.decide(candidate_issue, candidate_item, [upstream, candidate_item])

        self.assertEqual(decision.action, "promote")
        self.assertEqual(decision.project_updates["DependsOn"], "")
        self.assertEqual(decision.body_updates["Open dependencies"], "none")

    def test_ws_token_open_upstream_remains_blocked(self) -> None:
        upstream = item(3, sourceId="WS-3", workstream="WS-3")
        candidate_item = item(4, sourceId="WS-4", dependsOn="WS-3")
        candidate_issue = issue(4, body(dependencies="WS-3"))
        self.issue_states[("owner/repo", 3)] = "OPEN"

        decision = self.decide(candidate_issue, candidate_item, [upstream, candidate_item])

        self.assertEqual(decision.action, "blocked")
        self.assertTrue(any("open dependency" in reason for reason in decision.reasons))

    def test_manual_gate_closed_issue_promotes_downstream(self) -> None:
        candidate_item = item(4, blockerType="manual", blockerReason="owner/repo#61")
        candidate_issue = issue(4, body(manual_gates="owner/repo#61"))
        self.issue_states[("owner/repo", 61)] = "CLOSED"

        decision = self.decide(candidate_issue, candidate_item)

        self.assertEqual(decision.action, "promote")
        self.assertEqual(decision.body_updates["Manual gates remaining"], "none")

    def test_manual_gate_open_blocks_downstream(self) -> None:
        candidate_item = item(4, blockerType="manual", blockerReason="owner/repo#61")
        candidate_issue = issue(4, body(manual_gates="owner/repo#61"))
        self.issue_states[("owner/repo", 61)] = "OPEN"

        decision = self.decide(candidate_issue, candidate_item)

        self.assertEqual(decision.action, "blocked")
        self.assertTrue(any("manual gate remaining" in reason for reason in decision.reasons))

    def test_explicit_pr_dependency_requires_merged_pr(self) -> None:
        candidate_item = item(4, dependsOn="PR owner/repo#90")
        candidate_issue = issue(4, body(dependencies="PR owner/repo#90"))
        self.pr_merged[("owner/repo", 90)] = False

        decision = self.decide(candidate_issue, candidate_item)
        self.assertEqual(decision.action, "blocked")

        self.pr_merged[("owner/repo", 90)] = True
        decision = self.decide(candidate_issue, candidate_item)
        self.assertEqual(decision.action, "promote")

    def test_project_body_disagreement_is_reconciled_as_promotion(self) -> None:
        candidate_item = item(4, dependsOn="WS-3", dispatchMode="blocked", issueReady="Blocked")
        candidate_issue = issue(
            4,
            body(dependencies="none", dispatch_mode="agent-ready", recommendation="auto-dispatch"),
            "status:ready",
            "agent:approved-dispatch",
            "agent:ready",
        )
        upstream = item(3, sourceId="WS-3")
        self.issue_states[("owner/repo", 3)] = "CLOSED"

        decision = self.decide(candidate_issue, candidate_item, [upstream, candidate_item])

        self.assertEqual(decision.action, "promote")
        self.assertEqual(decision.body_updates, {"Issue ready": "true"})
        self.assertEqual(decision.project_updates["DispatchMode"], "agent-ready")
        self.assertEqual(decision.project_updates["IssueReady"], "Ready")

    def test_epics_and_trackers_are_never_promoted(self) -> None:
        candidate_item = item(4, itemType="Epic", executionState="Epic", onePRContract="N/A")
        candidate_issue = issue(4, body(), "type:epic")

        decision = self.decide(candidate_issue, candidate_item)

        self.assertEqual(decision.action, "blocked")
        self.assertTrue(any("epic" in reason for reason in decision.reasons))

    def test_stale_failed_label_removed_only_when_checks_pass(self) -> None:
        blocked_issue = issue(4, body(dependencies="WS-3"), "agent:failed")
        candidate_item = item(4, dependsOn="WS-3")
        upstream = item(3, sourceId="WS-3")
        self.issue_states[("owner/repo", 3)] = "OPEN"

        decision = self.decide(blocked_issue, candidate_item, [upstream, candidate_item])
        self.assertEqual(decision.action, "blocked")
        self.assertEqual(decision.labels_remove, [])

        self.issue_states[("owner/repo", 3)] = "CLOSED"
        decision = self.decide(blocked_issue, candidate_item, [upstream, candidate_item])
        self.assertEqual(decision.action, "promote")
        self.assertIn("agent:failed", decision.labels_remove)

    def test_dry_run_summary_records_decision_without_mutation(self) -> None:
        decision = self.decide(issue(4, body()), item(4))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            self.promote.write_summary(str(path), [decision])
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["counts"]["promote"], 1)
        self.assertEqual(payload["decisions"][0]["action"], "promote")


if __name__ == "__main__":
    unittest.main()
