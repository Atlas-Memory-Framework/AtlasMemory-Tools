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


def pr(**overrides):
    data = {
        "number": 7,
        "title": "agent: address issue #7",
        "url": "https://example.invalid/pr/7",
        "state": "OPEN",
        "isDraft": False,
        "body": "Closes #7",
        "headRefName": "agent/issue-7/job",
        "mergeStateStatus": "CLEAN",
        "mergeable": "MERGEABLE",
        "statusCheckRollup": [{"name": "unit-tests", "status": "COMPLETED", "conclusion": "SUCCESS"}],
        "labels": [],
    }
    data.update(overrides)
    return data


def issue(**overrides):
    data = {
        "number": 7,
        "title": "[WS] Story",
        "body": "Open dependencies: none",
        "labels": [],
        "url": "https://example.invalid/issue/7",
    }
    data.update(overrides)
    return data


class ReviewAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.review = load_script("atlas_agent_review_test", "atlas-agent-review")

    def test_review_approves_green_pr_without_manual_validation(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(),
            issue=issue(),
            files=["src/app.py"],
            required_checks=["unit-tests"],
        )

        self.assertEqual(decision.label, "agent:review-approved")

    def test_review_blocks_no_check_pr_for_repair(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(statusCheckRollup=[]),
            issue=issue(),
            files=["src/app.py"],
        )

        self.assertEqual(decision.label, "agent:needs-repair")
        self.assertIn("no checks reported", decision.reasons)

    def test_review_requires_manual_validation_for_deployed_scope(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(),
            issue=issue(body="Validation scope: `deployed`"),
            files=["src/app.py"],
        )

        self.assertEqual(decision.label, "agent:manual-validation-required")

    def test_review_requires_manual_validation_for_overlap(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(),
            issue=issue(),
            files=["src/app.py"],
            overlap_numbers=[8],
        )

        self.assertEqual(decision.label, "agent:manual-validation-required")
        self.assertIn("overlaps open local-agent PRs: #8", decision.reasons)

    def test_review_marks_duplicate_as_superseded(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(),
            issue=issue(),
            files=["src/app.py"],
            duplicate_issue=True,
        )

        self.assertEqual(decision.label, "agent:superseded")


if __name__ == "__main__":
    unittest.main()
