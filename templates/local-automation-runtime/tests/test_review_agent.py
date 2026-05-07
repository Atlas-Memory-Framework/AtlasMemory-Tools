from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
        "headRefOid": "abc123",
        "mergeStateStatus": "CLEAN",
        "mergeable": "MERGEABLE",
        "statusCheckRollup": [{"name": "unit-tests", "status": "COMPLETED", "conclusion": "SUCCESS"}],
        "labels": [],
        "comments": [],
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
            required_checks=["ci"],
        )

        self.assertEqual(decision.label, "agent:needs-repair")
        self.assertIn("no checks reported", decision.reasons)

    def test_review_requires_local_validation_for_no_check_pr_without_required_checks(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(statusCheckRollup=[]),
            issue=issue(),
            files=["src/app.py"],
        )

        self.assertEqual(decision.label, "agent:local-validation-required")
        self.assertIn("no checks reported; local validation required", decision.reasons)

    def test_review_accepts_local_validation_passed_for_no_check_pr(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(
                statusCheckRollup=[],
                labels=[{"name": "agent:local-validation-passed"}],
                comments=[
                    {
                        "body": "<!-- atlas-agent-local-validation -->\nHead: `abc123`\nResult: passed",
                    }
                ],
            ),
            issue=issue(),
            files=["src/app.py"],
        )

        self.assertEqual(decision.label, "agent:review-approved")
        self.assertIn("local validation passed with no GitHub checks", decision.reasons)

    def test_review_rejects_stale_local_validation_passed_label(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(
                statusCheckRollup=[],
                labels=[{"name": "agent:local-validation-passed"}],
                comments=[
                    {
                        "body": "<!-- atlas-agent-local-validation -->\nHead: `oldsha`\nResult: passed",
                    }
                ],
            ),
            issue=issue(),
            files=["src/app.py"],
            allow_no_checks=True,
        )

        self.assertEqual(decision.label, "agent:local-validation-required")
        self.assertIn("local validation pass missing for current head", decision.reasons)

    def test_review_requires_manual_validation_for_deployed_scope(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(),
            issue=issue(body="Validation scope: `deployed`"),
            files=["src/app.py"],
        )

        self.assertEqual(decision.label, "agent:manual-validation-required")

    def test_review_approves_deployed_scope_after_manual_validation_label(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(labels=[{"name": "agent:manual-validation-approved"}]),
            issue=issue(body="Validation scope: `deployed`"),
            files=["src/app.py"],
        )

        self.assertEqual(decision.label, "agent:review-approved")
        self.assertIn("manual or deployed validation approved", decision.reasons)

    def test_review_queues_direct_overlap(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(),
            issue=issue(),
            files=["src/app.py"],
            overlap_numbers=[8],
        )

        self.assertEqual(decision.label, "agent:overlap-queued")
        self.assertIn("overlaps open local-agent PRs: #8", decision.reasons)

    def test_manual_validation_waits_for_repair_blockers(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(statusCheckRollup=[]),
            issue=issue(body="Validation scope: `deployed`"),
            files=["src/app.py"],
            required_checks=["ci"],
        )

        self.assertEqual(decision.label, "agent:needs-repair")
        self.assertIn("no checks reported", decision.reasons)
        self.assertIn("manual/deployed validation pending after repair", decision.reasons)

    def test_review_marks_duplicate_as_superseded(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(),
            issue=issue(),
            files=["src/app.py"],
            duplicate_issue=True,
        )

        self.assertEqual(decision.label, "agent:superseded")

    def test_review_blocks_failed_checks_for_repair(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(statusCheckRollup=[{"name": "unit-tests", "status": "COMPLETED", "conclusion": "FAILURE"}]),
            issue=issue(),
            files=["src/app.py"],
        )

        self.assertEqual(decision.label, "agent:needs-repair")
        self.assertIn("checks failed", decision.reasons[0])

    def test_review_blocks_missing_required_check_for_repair(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(),
            issue=issue(),
            files=["src/app.py"],
            required_checks=["integration"],
        )

        self.assertEqual(decision.label, "agent:needs-repair")
        self.assertIn("required check missing: integration", decision.reasons[0])

    def test_review_blocks_unverified_linked_issue_for_repair(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(),
            issue=None,
            files=["src/app.py"],
        )

        self.assertEqual(decision.label, "agent:needs-repair")
        self.assertIn("linked issue #7 could not be verified", decision.reasons)

    def test_apply_decision_uses_issue_edit_for_labels(self) -> None:
        calls: list[list[str]] = []
        original_ensure = self.review.ensure_review_labels
        original_run = self.review.common.run
        self.review.ensure_review_labels = lambda _repo: None
        self.review.common.run = lambda args, **_kwargs: calls.append(args)
        try:
            self.review.apply_decision(
                self.review.ReviewDecision(
                    repo="owner/repo",
                    number=7,
                    title="agent: address issue #7",
                    url="https://example.invalid/pr/7",
                    issue_number=7,
                    label="agent:review-approved",
                    reasons=["green checks"],
                    files=[],
                ),
                comment=False,
            )
        finally:
            self.review.ensure_review_labels = original_ensure
            self.review.common.run = original_run

        self.assertTrue(all(call[:3] != ["gh", "pr", "edit"] for call in calls))
        self.assertIn(
            ["gh", "issue", "edit", "7", "--repo", "owner/repo", "--add-label", "agent:review-approved"],
            calls,
        )

    def test_overlap_frontier_approves_only_one_green_pr(self) -> None:
        decisions = [
            self.review.ReviewDecision("owner/repo", 7, "agent: address issue #7", "url", 7, "agent:review-approved", ["green"], ["src/app.py"]),
            self.review.ReviewDecision("owner/repo", 8, "agent: address issue #8", "url", 8, "agent:review-approved", ["green"], ["src/app.py"]),
        ]
        details = [
            ({"number": 7, "title": "agent: address issue #7", "headRefName": "agent/issue-7/a"}, ["src/app.py"]),
            ({"number": 8, "title": "agent: address issue #8", "headRefName": "agent/issue-8/a"}, ["src/app.py"]),
        ]

        self.review.apply_overlap_frontier(decisions, details)

        self.assertEqual(decisions[0].label, "agent:review-approved")
        self.assertEqual(decisions[1].label, "agent:overlap-queued")
        self.assertIn("queued behind overlapping PR #7", decisions[1].reasons)

    def test_overlap_frontier_does_not_promote_unsafe_pr(self) -> None:
        decisions = [
            self.review.ReviewDecision("owner/repo", 7, "agent: address issue #7", "url", 7, "agent:needs-repair", ["no checks reported"], ["src/app.py"]),
            self.review.ReviewDecision("owner/repo", 8, "agent: address issue #8", "url", 8, "agent:review-approved", ["green"], ["src/app.py"]),
        ]
        details = [
            ({"number": 7, "title": "agent: address issue #7", "headRefName": "agent/issue-7/a"}, ["src/app.py"]),
            ({"number": 8, "title": "agent: address issue #8", "headRefName": "agent/issue-8/a"}, ["src/app.py"]),
        ]

        self.review.apply_overlap_frontier(decisions, details)

        self.assertEqual(decisions[0].label, "agent:needs-repair")
        self.assertEqual(decisions[1].label, "agent:review-approved")


if __name__ == "__main__":
    unittest.main()
