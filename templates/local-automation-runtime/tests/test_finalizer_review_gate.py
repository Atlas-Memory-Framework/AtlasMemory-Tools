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


def green_pr(*, labels: list[str] | None = None, **overrides) -> dict:
    payload = {
        "number": 7,
        "title": "agent: address issue #12",
        "url": "https://example.invalid/pr/7",
        "body": "Closes #12",
        "headRefName": "agent/issue-12/work",
        "headRefOid": "abc123",
        "state": "OPEN",
        "mergeStateStatus": "CLEAN",
        "mergeable": "MERGEABLE",
        "isDraft": False,
        "labels": [{"name": label} for label in (labels or [])],
        "comments": [],
        "files": [{"path": "src/app.py"}],
        "statusCheckRollup": [
            {
                "name": "test",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
            }
        ],
    }
    payload.update(overrides)
    return payload


class FinalizerReviewGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.finalize = load_script("atlas_agent_finalize_review_gate_test", "atlas-agent-finalize")

    def test_green_pr_without_required_review_label_is_blocked(self) -> None:
        decision = self.finalize.decide(
            "owner/repo",
            green_pr(),
            allow_no_checks=False,
            merge=True,
            check_dependencies=False,
            require_review_label="reviewed",
        )

        self.assertEqual(decision.action, "blocked")
        self.assertIn("review-label missing: reviewed", decision.reasons)

    def test_green_pr_with_required_review_label_can_merge(self) -> None:
        decision = self.finalize.decide(
            "owner/repo",
            green_pr(labels=["reviewed"]),
            allow_no_checks=False,
            merge=True,
            check_dependencies=False,
            require_review_label="reviewed",
        )

        self.assertEqual(decision.action, "merge")
        self.assertEqual(decision.reasons, [])

    def test_pr_view_fields_include_labels(self) -> None:
        self.assertIn("labels", self.finalize.PR_VIEW_FIELDS.split(","))
        self.assertIn("files", self.finalize.PR_VIEW_FIELDS.split(","))

    def test_local_validation_passed_no_check_draft_is_readied_not_merged(self) -> None:
        decision = self.finalize.decide(
            "owner/repo",
            green_pr(
                labels=["reviewed", "agent:local-validation-passed"],
                statusCheckRollup=[],
                isDraft=True,
                comments=[
                    {
                        "body": "<!-- atlas-agent-local-validation -->\nHead: `abc123`\nResult: passed",
                    }
                ],
            ),
            allow_no_checks=False,
            merge=True,
            check_dependencies=False,
            require_review_label="reviewed",
        )

        self.assertEqual(decision.action, "ready")

    def test_stale_local_validation_passed_label_is_blocked(self) -> None:
        decision = self.finalize.decide(
            "owner/repo",
            green_pr(
                labels=["reviewed", "agent:local-validation-passed"],
                statusCheckRollup=[],
                comments=[
                    {
                        "body": "<!-- atlas-agent-local-validation -->\nHead: `oldsha`\nResult: passed",
                    }
                ],
            ),
            allow_no_checks=True,
            merge=True,
            check_dependencies=False,
            require_review_label="reviewed",
        )

        self.assertEqual(decision.action, "blocked")
        self.assertIn("local validation pass missing for current head", decision.reasons)

    def test_local_validation_does_not_override_required_github_checks(self) -> None:
        decision = self.finalize.decide(
            "owner/repo",
            green_pr(labels=["reviewed", "agent:local-validation-passed"], statusCheckRollup=[]),
            allow_no_checks=False,
            merge=True,
            required_check_names=["ci"],
            check_dependencies=False,
            require_review_label="reviewed",
        )

        self.assertEqual(decision.action, "blocked")
        self.assertIn("no checks reported", decision.reasons)

    def test_deployed_validation_does_not_override_required_github_checks(self) -> None:
        decision = self.finalize.decide(
            "owner/repo",
            green_pr(
                labels=["reviewed", "agent:deployed-validation-passed"],
                statusCheckRollup=[],
                comments=[
                    {
                        "body": "<!-- atlas-agent-deployed-validation -->\nHead: `abc123`\nResult: passed",
                    }
                ],
            ),
            allow_no_checks=False,
            merge=True,
            required_check_names=["ci"],
            check_dependencies=False,
            require_review_label="reviewed",
        )

        self.assertEqual(decision.action, "blocked")
        self.assertIn("no checks reported", decision.reasons)

    def test_no_checks_path_policy_can_merge_docs_only_pr(self) -> None:
        decision = self.finalize.decide(
            "OWNER/REPO",
            green_pr(
                labels=["reviewed", "agent:no-checks-expected"],
                statusCheckRollup=[],
                files=[{"path": "docs/readme.md"}],
            ),
            allow_no_checks=False,
            merge=True,
            required_check_names=[],
            required_checks_file=str(ROOT / "config" / "required-checks.example.json"),
            check_dependencies=False,
            require_review_label="reviewed",
        )

        self.assertEqual(decision.action, "merge")


if __name__ == "__main__":
    unittest.main()
