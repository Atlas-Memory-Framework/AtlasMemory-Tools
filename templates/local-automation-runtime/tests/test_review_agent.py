from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import tempfile
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

    def test_review_requested_changes_blocks_for_repair(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(reviewDecision="CHANGES_REQUESTED", latestReviews=[{"state": "CHANGES_REQUESTED"}]),
            issue=issue(),
            files=["src/app.py"],
            required_checks=["unit-tests"],
        )

        self.assertEqual(decision.label, "agent:needs-repair")
        self.assertIn("review changes requested", decision.reasons)

    def test_review_requires_current_semantic_review_when_enabled(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(),
            issue=issue(),
            files=["src/app.py"],
            required_checks=["unit-tests"],
            require_semantic_review=True,
        )

        self.assertEqual(decision.label, "agent:semantic-review-required")
        self.assertIn("semantic review required for current head", decision.reasons)

    def test_review_accepts_current_semantic_review_pass(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(
                comments=[
                    {
                        "body": "<!-- atlas-agent-semantic-review -->\nHead: `abc123`\nResult: passed",
                    }
                ],
            ),
            issue=issue(),
            files=["src/app.py"],
            required_checks=["unit-tests"],
            require_semantic_review=True,
        )

        self.assertEqual(decision.label, "agent:review-approved")
        self.assertIn("semantic review passed for current head", decision.reasons)

    def test_review_blocks_current_semantic_review_failure(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(
                comments=[
                    {
                        "body": "<!-- atlas-agent-semantic-review -->\nHead: `abc123`\nResult: failed",
                    }
                ],
            ),
            issue=issue(),
            files=["src/app.py"],
            required_checks=["unit-tests"],
            require_semantic_review=True,
        )

        self.assertEqual(decision.label, "agent:needs-repair")
        self.assertIn("semantic review failed for current head", decision.reasons)

    def test_semantic_scope_gap_is_not_current_repo_repairable(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(
                comments=[
                    {
                        "body": (
                            "<!-- atlas-agent-semantic-review -->\n"
                            "Head: `abc123`\n"
                            "Result: failed\n"
                            "Blocking Findings:\n"
                            "- This PR must modify the Admin UI repo to satisfy the issue.\n"
                            "- Missing deployed validation evidence.\n"
                        ),
                    }
                ],
            ),
            issue=issue(),
            files=["src/app.py"],
            required_checks=["unit-tests"],
            require_semantic_review=True,
        )

        blocker_types = self.review.blocker_types_for(decision.label, decision.reasons)
        self.assertEqual(decision.label, "agent:needs-repair")
        self.assertIn("semantic review failed: cross-repo scope gap", decision.reasons)
        self.assertIn("semantic review failed: deployed validation evidence missing", decision.reasons)
        self.assertEqual(self.review.route_for_decision(decision), "human")
        self.assertEqual(self.review.repair_scope_for(blocker_types), "cross-repo")
        self.assertFalse(self.review.repairable_for(blocker_types))

    def test_semantic_failure_overrides_manual_validation_wait(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(
                comments=[
                    {
                        "body": "<!-- atlas-agent-semantic-review -->\nHead: `abc123`\nResult: failed",
                    }
                ],
            ),
            issue=issue(body="Validation scope: deployed"),
            files=["src/app.py"],
            required_checks=["unit-tests"],
            require_semantic_review=True,
        )

        self.assertEqual(decision.label, "agent:needs-repair")
        self.assertIn("manual or deployed validation required", decision.reasons)
        self.assertIn("semantic review failed for current head", decision.reasons)

    def test_review_uses_latest_current_head_semantic_review_comment(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(
                comments=[
                    {
                        "body": "<!-- atlas-agent-semantic-review -->\nHead: `abc123`\nResult: failed",
                    },
                    {
                        "body": "<!-- atlas-agent-semantic-review -->\nHead: `abc123`\nResult: passed",
                    },
                ],
            ),
            issue=issue(),
            files=["src/app.py"],
            required_checks=["unit-tests"],
            require_semantic_review=True,
        )

        self.assertEqual(decision.label, "agent:review-approved")
        self.assertIn("semantic review passed for current head", decision.reasons)

    def test_review_ignores_stale_semantic_review_pass(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(
                comments=[
                    {
                        "body": "<!-- atlas-agent-semantic-review -->\nHead: `oldsha`\nResult: passed",
                    }
                ],
            ),
            issue=issue(),
            files=["src/app.py"],
            required_checks=["unit-tests"],
            require_semantic_review=True,
        )

        self.assertEqual(decision.label, "agent:semantic-review-required")

    def test_review_routes_required_no_check_pr_to_local_validation(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(statusCheckRollup=[]),
            issue=issue(),
            files=["src/app.py"],
            required_checks=["ci"],
        )

        self.assertEqual(decision.label, "agent:local-validation-required")
        self.assertIn("no GitHub checks reported; required checks missing", decision.reasons)

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

    def test_review_accepts_draft_blocked_after_current_local_validation_pass(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(
                isDraft=True,
                mergeStateStatus="BLOCKED",
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
            required_checks=["ci"],
        )

        self.assertEqual(decision.label, "agent:local-validation-required")
        self.assertIn("no GitHub checks reported; required checks missing", decision.reasons)

    def test_review_does_not_approve_local_validation_when_required_checks_are_absent(self) -> None:
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
            required_checks=["ci"],
        )

        self.assertEqual(decision.label, "agent:local-validation-required")
        self.assertIn("no GitHub checks reported; required checks missing", decision.reasons)

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
        self.assertEqual(self.review.route_for_decision(decision), "wait")

    def test_manual_validation_no_check_routes_to_deployed_validation(self) -> None:
        decision = self.review.classify(
            "owner/repo",
            pr(statusCheckRollup=[]),
            issue=issue(body="Validation scope: `deployed`"),
            files=["src/app.py"],
            required_checks=["ci"],
        )

        self.assertEqual(decision.label, "agent:manual-validation-required")
        self.assertIn("manual or deployed validation required", decision.reasons)

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

    def test_review_comment_includes_files_and_next_action(self) -> None:
        body = self.review.review_comment_body(
            self.review.ReviewDecision(
                repo="owner/repo",
                number=7,
                title="agent: #7 Add route",
                url="https://example.invalid/pr/7",
                issue_number=7,
                label="agent:manual-validation-required",
                reasons=["manual or deployed validation required"],
                files=["src/workflows.py", "tests/test_workflows.py"],
            )
        )

        self.assertIn("Automated Review Decision", body)
        self.assertIn("`src/workflows.py`", body)
        self.assertIn("agent:manual-validation-approved", body)
        self.assertIn("Finalization requires `agent:review-approved`", body)

    def test_review_comment_calls_out_remaining_deployed_gate_after_local_pass(self) -> None:
        body = self.review.review_comment_body(
            self.review.ReviewDecision(
                repo="owner/repo",
                number=7,
                title="agent: #7 Add route",
                url="https://example.invalid/pr/7",
                issue_number=7,
                label="agent:manual-validation-required",
                reasons=["local validation passed with no GitHub checks", "manual or deployed validation required"],
                files=["src/workflows.py"],
            )
        )

        self.assertIn("Local validation is current", body)
        self.assertIn("./atlas-agent-deployed-validate owner/repo#7 --apply", body)

    def test_review_comment_includes_semantic_next_action(self) -> None:
        body = self.review.review_comment_body(
            self.review.ReviewDecision(
                repo="owner/repo",
                number=7,
                title="agent: #7 Add route",
                url="https://example.invalid/pr/7",
                issue_number=7,
                label="agent:semantic-review-required",
                reasons=["semantic review required for current head"],
                files=["src/workflows.py"],
            )
        )

        self.assertIn("atlas-agent-semantic-review OWNER/REPO#PR --apply", body)

    def test_write_summary_includes_route_and_repair_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.json"
            self.review.write_summary(
                str(path),
                [
                    self.review.ReviewDecision(
                        repo="owner/repo",
                        number=7,
                        title="agent: #7 Add route",
                        url="https://example.invalid/pr/7",
                        issue_number=7,
                        label="agent:needs-repair",
                        reasons=["semantic review failed for current head"],
                        files=["src/workflows.py"],
                    )
                ],
            )

            payload = json.loads(path.read_text(encoding="utf-8"))

        decision = payload["decisions"][0]
        self.assertEqual(decision["route"], "repair")
        self.assertEqual(decision["repair_scope"], "current-repo")
        self.assertTrue(decision["repairable"])
        self.assertIn("semantic_scope_repair", decision["blocker_types"])

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
