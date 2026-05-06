from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import tempfile
import types
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


def issue(
    *,
    body: str = "",
    labels: list[str] | None = None,
    author: str = "AtlasMemory-Dev",
    title: str = "[WS] Story",
    number: int = 1,
) -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "author": {"login": author},
        "labels": [{"name": label} for label in (labels or [])],
        "url": f"https://example.invalid/{number}",
        "updatedAt": "2026-05-05T00:00:00Z",
    }


class LocalAgentAutonomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.triage = load_script("atlas_agent_triage_test", "atlas-agent-triage")
        cls.orchestrator = load_script("atlas_agent_orchestrator_test", "atlas-agent-orchestrator")
        cls.admin = load_script("atlas_agent_admin_test", "atlas-agent-admin")
        cls.finalize = load_script("atlas_agent_finalize_test", "atlas-agent-finalize")

    def test_triage_approves_review_before_dispatch_with_stale_needs_human(self) -> None:
        record = self.triage.classify_issue(
            "owner/repo",
            issue(
                labels=["needs-human"],
                body="Dispatch recommendation: `review-before-dispatch`",
            ),
        )

        self.assertEqual(record["reasons"], ["review_before_dispatch", "needs_human_label"])
        self.assertTrue(self.triage.can_approve_review_before_dispatch(record))

    def test_triage_requeues_stale_wait_human_pause_without_hard_blockers(self) -> None:
        record = self.triage.classify_issue(
            "owner/repo",
            issue(labels=["needs-human"], body="Next action: `wait_human`"),
        )

        self.assertTrue(record["stale_unblockable"])
        self.assertEqual(record["severity"], "info")

    def test_triage_keeps_manual_gates_as_hard_blockers(self) -> None:
        record = self.triage.classify_issue(
            "owner/repo",
            issue(
                labels=["needs-human"],
                body="Next action: `wait_human`\nManual gates remaining: `run hosted smoke`",
            ),
        )

        self.assertFalse(record["stale_unblockable"])
        self.assertIn("manual_gates_remaining", record["reasons"])
        self.assertFalse(self.triage.can_approve_review_before_dispatch(record))

    def test_triage_keeps_failed_human_pauses_as_hard_blockers(self) -> None:
        record = self.triage.classify_issue(
            "owner/repo",
            issue(labels=["needs-human", "agent:failed"], body="Next action: `wait_human`"),
        )

        self.assertFalse(record["stale_unblockable"])
        self.assertIn("agent_failed", record["reasons"])

    def test_triage_field_parser_considers_later_nonempty_values(self) -> None:
        body = "Manual gates remaining: `none`\nManual gates remaining: `review interrupted job`"

        self.assertTrue(self.triage.body_has_nonempty_field(body, "Manual gates remaining"))

    def test_approve_review_before_dispatch_removes_human_and_terminal_labels(self) -> None:
        calls: list[list[str]] = []
        original_run = self.triage.common.run
        self.triage.common.run = lambda args, **_kwargs: calls.append(args)
        try:
            count = self.triage.approve_review_before_dispatch(
                [
                    {
                        "repo": "owner/repo",
                        "number": 7,
                        "labels": ["needs-human"],
                        "reasons": ["review_before_dispatch", "needs_human_label"],
                    }
                ],
                comment=False,
            )
        finally:
            self.triage.common.run = original_run

        self.assertEqual(count, 1)
        self.assertIn(["gh", "issue", "edit", "7", "--repo", "owner/repo", "--remove-label", "needs-human"], calls)
        self.assertIn(["gh", "issue", "edit", "7", "--repo", "owner/repo", "--add-label", "agent:ready"], calls)

    def test_orchestrator_treats_needs_human_wait_as_recoverable(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(labels=["needs-human"], body="Next action: `wait_human`")
        )

        self.assertEqual(reasons, [])

    def test_orchestrator_treats_approved_review_wait_as_recoverable(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(
                labels=["agent:approved-dispatch", "agent:ready"],
                body="Dispatch recommendation: `review-before-dispatch`\nNext action: `wait_human`",
            )
        )

        self.assertEqual(reasons, [])

    def test_orchestrator_preserves_real_hard_blockers(self) -> None:
        review_reasons = self.orchestrator.hard_non_execution_reasons(
            issue(body="Dispatch recommendation: `review-before-dispatch`")
        )
        gate_reasons = self.orchestrator.hard_non_execution_reasons(
            issue(labels=["needs-human"], body="Manual gates remaining: `run hosted smoke`")
        )

        self.assertEqual(review_reasons, ["review-before-dispatch requires explicit queueing"])
        self.assertEqual(gate_reasons, ["manual gates remaining"])

    def test_maybe_queue_issue_queues_recoverable_human_pause(self) -> None:
        calls: list[list[str]] = []
        original_run = self.orchestrator.common.run
        original_skip = self.orchestrator.has_open_pr_for_issue
        self.orchestrator.common.run = lambda args, **_kwargs: calls.append(args)
        self.orchestrator.has_open_pr_for_issue = lambda _repo, _number: False
        args = types.SimpleNamespace(auto_queue_label="status:ready", auto_queue_skip_open_pr=True)
        try:
            queued = self.orchestrator.maybe_queue_issue(
                "owner/repo",
                issue(labels=["needs-human"], body="Next action: `wait_human`", number=9),
                args,
            )
        finally:
            self.orchestrator.common.run = original_run
            self.orchestrator.has_open_pr_for_issue = original_skip

        self.assertTrue(queued)
        self.assertEqual(calls, [["gh", "issue", "edit", "9", "--repo", "owner/repo", "--add-label", "agent:ready"]])

    def test_process_once_removes_ready_when_open_pr_exists(self) -> None:
        calls: list[list[str]] = []
        originals = {
            "target_repos": self.orchestrator.target_repos,
            "ensure_agent_labels": self.orchestrator.ensure_agent_labels,
            "queue_candidate_issues": self.orchestrator.queue_candidate_issues,
            "failed_issues": self.orchestrator.failed_issues,
            "ready_issues": self.orchestrator.ready_issues,
            "has_open_pr_for_issue": self.orchestrator.has_open_pr_for_issue,
            "run_worker": self.orchestrator.run_worker,
            "run": self.orchestrator.common.run,
            "trusted_authors": self.orchestrator.common.trusted_authors,
        }
        self.orchestrator.target_repos = lambda _path: ["owner/repo"]
        self.orchestrator.ensure_agent_labels = lambda _repo: None
        self.orchestrator.queue_candidate_issues = lambda _repo, _label, _limit: []
        self.orchestrator.failed_issues = lambda _repo, _limit: []
        self.orchestrator.ready_issues = lambda _repo, _limit: [issue(labels=["agent:ready"], number=9)]
        self.orchestrator.has_open_pr_for_issue = lambda _repo, _number: True
        self.orchestrator.run_worker = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("worker should not run")
        )
        self.orchestrator.common.run = lambda args, **_kwargs: calls.append(args)
        self.orchestrator.common.trusted_authors = lambda: {"AtlasMemory-Dev"}
        args = types.SimpleNamespace(
            triage_needs_human=False,
            repos_file=None,
            auto_queue_label=None,
            auto_queue_max=1,
            limit=20,
            inspect_failed=False,
            auto_queue_skip_open_pr=True,
            publish=True,
            max_items=3,
            dispatch_deploy_candidates=False,
        )
        try:
            processed = self.orchestrator.process_once(args)
        finally:
            self.orchestrator.target_repos = originals["target_repos"]
            self.orchestrator.ensure_agent_labels = originals["ensure_agent_labels"]
            self.orchestrator.queue_candidate_issues = originals["queue_candidate_issues"]
            self.orchestrator.failed_issues = originals["failed_issues"]
            self.orchestrator.ready_issues = originals["ready_issues"]
            self.orchestrator.has_open_pr_for_issue = originals["has_open_pr_for_issue"]
            self.orchestrator.run_worker = originals["run_worker"]
            self.orchestrator.common.run = originals["run"]
            self.orchestrator.common.trusted_authors = originals["trusted_authors"]

        self.assertEqual(processed, 0)
        self.assertEqual(calls, [["gh", "issue", "edit", "9", "--repo", "owner/repo", "--remove-label", "agent:ready"]])

    def test_common_git_identity_defaults_are_available(self) -> None:
        name, email = self.orchestrator.common.git_identity()

        self.assertTrue(name)
        self.assertIn("@", email)

    def test_admin_detects_git_identity_error(self) -> None:
        error = """Command failed: git commit -m "agent: address issue #17"
Author identity unknown
fatal: unable to auto-detect email address
"""

        self.assertTrue(self.admin.is_git_identity_error(error))

    def test_worker_success_notification_extracts_pr_url(self) -> None:
        original_config = self.orchestrator.common.read_config
        self.orchestrator.common.read_config = lambda: {"TEAMS_ISSUES_WEBHOOK_URL": "https://example.invalid/issues"}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                job_dir = Path(tmp) / "issue-7-20260506T000000Z"
                job_dir.mkdir()
                (job_dir / "comment.md").write_text(
                    "Local Codex agent created a draft PR for issue #7.\n\n"
                    "PR: https://github.com/owner/repo/pull/9\n"
                    "Job: `20260506T000000Z`\n",
                    encoding="utf-8",
                )

                result = self.orchestrator.build_worker_notification(
                    repo="owner/repo",
                    issue=issue(number=7),
                    job_dir=job_dir,
                    rc=0,
                )
        finally:
            self.orchestrator.common.read_config = original_config

        self.assertIsNotNone(result)
        _webhook, payload = result
        self.assertEqual(payload["themeColor"], "107C10")
        self.assertIn("https://github.com/owner/repo/pull/9", payload["text"])

    def test_worker_failure_notification_uses_urgent_webhook(self) -> None:
        original_config = self.orchestrator.common.read_config
        self.orchestrator.common.read_config = lambda: {"TEAMS_URGENT_WEBHOOK_URL": "https://example.invalid/urgent"}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                job_dir = Path(tmp) / "issue-7-20260506T000000Z"
                job_dir.mkdir()
                (job_dir / "error.txt").write_text("boom", encoding="utf-8")

                result = self.orchestrator.build_worker_notification(
                    repo="owner/repo",
                    issue=issue(number=7),
                    job_dir=job_dir,
                    rc=1,
                )
        finally:
            self.orchestrator.common.read_config = original_config

        self.assertIsNotNone(result)
        webhook, payload = result
        self.assertEqual(webhook, "https://example.invalid/urgent")
        self.assertEqual(payload["themeColor"], "D13438")
        self.assertIn("boom", payload["text"])

    def test_triage_parses_utc_timestamp(self) -> None:
        parsed = self.triage.parse_utc_timestamp("2026-05-06T03:18:31Z")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.year, 2026)

    def test_finalizer_detects_agent_pr_and_issue(self) -> None:
        pr = {
            "title": "agent: address issue #35",
            "headRefName": "agent/issue-35/20260506T031442Z",
            "body": "Automated local Codex agent run for #35.\n\nCloses #35\n",
        }

        self.assertTrue(self.finalize.is_local_agent_pr(pr))
        self.assertEqual(self.finalize.linked_issue_number(pr), 35)

    def test_finalizer_blocks_no_check_pr_by_default(self) -> None:
        decision = self.finalize.decide(
            "owner/repo",
            {
                "number": 1,
                "title": "agent: address issue #1",
                "url": "https://example.invalid/pr/1",
                "state": "OPEN",
                "isDraft": True,
                "body": "Closes #1",
                "headRefName": "agent/issue-1/job",
                "statusCheckRollup": [],
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
            },
            allow_no_checks=False,
            merge=False,
        )

        self.assertEqual(decision.action, "blocked")
        self.assertIn("no checks reported", decision.reasons)

    def test_finalizer_readies_green_draft_pr(self) -> None:
        decision = self.finalize.decide(
            "owner/repo",
            {
                "number": 1,
                "title": "agent: address issue #1",
                "url": "https://example.invalid/pr/1",
                "state": "OPEN",
                "isDraft": True,
                "body": "Closes #1",
                "headRefName": "agent/issue-1/job",
                "statusCheckRollup": [{"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}],
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
            },
            allow_no_checks=False,
            merge=False,
        )

        self.assertEqual(decision.action, "ready")

    def test_finalizer_blocks_missing_required_check(self) -> None:
        decision = self.finalize.decide(
            "owner/repo",
            {
                "number": 1,
                "title": "agent: address issue #1",
                "url": "https://example.invalid/pr/1",
                "state": "OPEN",
                "isDraft": False,
                "body": "Closes #1",
                "headRefName": "agent/issue-1/job",
                "statusCheckRollup": [{"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}],
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
            },
            allow_no_checks=False,
            merge=True,
            required_check_names=["unit-tests"],
        )

        self.assertEqual(decision.action, "blocked")
        self.assertIn("required check missing: unit-tests", decision.reasons[0])

    def test_finalizer_allows_extra_checks_when_required_checks_pass(self) -> None:
        decision = self.finalize.decide(
            "owner/repo",
            {
                "number": 1,
                "title": "agent: address issue #1",
                "url": "https://example.invalid/pr/1",
                "state": "OPEN",
                "isDraft": False,
                "body": "Closes #1",
                "headRefName": "agent/issue-1/job",
                "statusCheckRollup": [
                    {"name": "unit-tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
                    {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
                ],
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
            },
            allow_no_checks=False,
            merge=True,
            required_check_names=["unit-tests"],
        )

        self.assertEqual(decision.action, "merge")

    def test_dependency_blockers_verify_referenced_issue_state(self) -> None:
        calls: list[list[str]] = []
        original = self.finalize.common.gh_json_or_none

        def fake_gh(args: list[str], **_kwargs):
            calls.append(args)
            return {"state": "OPEN", "url": "https://example.invalid/2"}

        self.finalize.common.gh_json_or_none = fake_gh
        try:
            blockers = self.finalize.common.issue_dependency_blockers(
                "owner/repo",
                issue(body="Open dependencies:\n- owner/repo#2\n", number=1),
            )
        finally:
            self.finalize.common.gh_json_or_none = original

        self.assertEqual(blockers, ["owner/repo issue #2 is not closed"])
        self.assertEqual(calls[0][:4], ["issue", "view", "2", "--repo"])

    def test_finalizer_blocks_duplicate_issue_prs(self) -> None:
        originals = {
            "target_repos": self.finalize.target_repos,
            "open_prs": self.finalize.open_prs,
            "pr_view": self.finalize.pr_view,
        }
        self.finalize.target_repos = lambda _path: ["owner/repo"]
        self.finalize.open_prs = lambda _repo, _limit: [
            {"number": 1, "title": "agent: address issue #7", "headRefName": "agent/issue-7/a"},
            {"number": 2, "title": "agent: address issue #7", "headRefName": "agent/issue-7/b"},
        ]

        def pr_view(_repo: str, number: int) -> dict:
            return {
                "number": number,
                "title": "agent: address issue #7",
                "url": f"https://example.invalid/pr/{number}",
                "state": "OPEN",
                "isDraft": False,
                "body": "Closes #7",
                "headRefName": f"agent/issue-7/{number}",
                "statusCheckRollup": [{"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}],
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
            }

        self.finalize.pr_view = pr_view
        try:
            decisions = self.finalize.scan(
                types.SimpleNamespace(repos_file=None, limit=50, issue=None, allow_no_checks=False, merge=True)
            )
        finally:
            self.finalize.target_repos = originals["target_repos"]
            self.finalize.open_prs = originals["open_prs"]
            self.finalize.pr_view = originals["pr_view"]

        self.assertEqual([decision.action for decision in decisions], ["blocked", "blocked"])
        self.assertTrue(all("duplicate linked issue #7" in decision.reasons[-1] for decision in decisions))


if __name__ == "__main__":
    unittest.main()
