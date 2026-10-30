from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import atlas_agent_common as common


def load_script(name: str, filename: str):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


class RemoteCommentPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = load_script("communication_policy_worker", "atlas-agent-worker")
        cls.review = load_script("communication_policy_review", "atlas-agent-review")
        cls.loop = load_script("communication_policy_unattended", "atlas-agent-unattended")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"AGENT_REMOTE_COMMENTS": "local", "AGENT_GITHUB_THROTTLE": "false"}))
        self.stack.enter_context(patch.object(common, "read_config", return_value={}))
        self.stack.enter_context(patch.object(common, "jobs_dir", return_value=self.root))

    def decision(self):
        return self.review.ReviewDecision(repo="owner/repo", number=7, title="Review", url="https://example.invalid/pr/7",
                                          issue_number=1, label="agent:review-approved", reasons=["checks passed"], files=["code.py"])

    def test_local_comment_commands_never_reach_process_and_do_not_log_body(self):
        calls = [
            ["gh", "issue", "comment", "1", "--repo", "owner/repo", "--body", "PRIVATE_BODY"],
            ["gh", "pr", "comment", "7", "--repo", "owner/repo", "--body", "PRIVATE_BODY"],
            ["gh", "api", "repos/owner/repo/issues/comments/1", "-X", "PATCH", "-f", "body=PRIVATE_BODY"],
            ["gh", "api", "--method", "POST", "repos/owner/repo/issues/1/comments", "-f", "body=PRIVATE_BODY"],
            ["gh", "api", "repos/owner/repo/issues/1/comments", "-f", "body=PRIVATE_BODY"],
            ["gh", "api", "graphql", "-f", "query=mutation { updateIssueComment }", "-f", "body=PRIVATE_BODY"],
        ]
        with patch.object(common.subprocess, "run", side_effect=AssertionError("must not call provider")), redirect_stdout(io.StringIO()) as output:
            for args in calls:
                with self.subTest(args=args[:3]):
                    result = common.run(args, check=False)
                    self.assertEqual(result.returncode, 78)
                    self.assertNotIn("PRIVATE_BODY", str(result.args) + result.stdout)
                    with self.assertRaisesRegex(RuntimeError, "Remote comments are disabled") as caught:
                        common.run(args)
                    self.assertNotIn("PRIVATE_BODY", str(caught.exception))
        self.assertNotIn("PRIVATE_BODY", output.getvalue())

    def test_comment_only_reads_are_local_empty_evidence_without_api_calls(self):
        with patch.object(common.subprocess, "run", side_effect=AssertionError("no provider")):
            self.assertEqual(common.gh_json(["api", "repos/owner/repo/issues/1/comments"]), [])
            self.assertEqual(common.gh_json(["api", "--method", "GET", "repos/owner/repo/pulls/7/comments"]), [])
            self.assertEqual(common.gh_json(["pr", "view", "7", "--json", "comments"]), {})
            self.assertEqual(common.gh_json(["issue", "list", "--json=comments"]), [])

    def test_cloud_pr_metadata_still_reads_without_requesting_comment_context(self):
        completed = subprocess.CompletedProcess([], 0, stdout='{"headRefOid":"abc","statusCheckRollup":[]}')
        with patch.object(common.subprocess, "run", return_value=completed) as run:
            data = common.gh_json(["pr", "view", "7", "--repo", "owner/repo", "--json", "headRefOid,comments,statusCheckRollup"])
        self.assertEqual(data["headRefOid"], "abc")
        fields = run.call_args.args[0][run.call_args.args[0].index("--json") + 1]
        self.assertEqual(fields, "headRefOid,statusCheckRollup")
        prepared, _ = common.github_comment_command(["gh", "pr", "view", "7", "--comments", "--json=comments,title"])
        self.assertNotIn("--comments", prepared)
        self.assertIn("--json=title", prepared)

    def test_explicit_pr_creation_and_check_operations_remain_available(self):
        completed = subprocess.CompletedProcess([], 0, stdout="ok")
        with patch.object(common.subprocess, "run", return_value=completed) as run:
            common.run(["gh", "pr", "create", "--draft", "--body-file", "review.md"])
            common.run(["gh", "pr", "checks", "7"])
        self.assertEqual(run.call_count, 2)

    def test_worker_preserves_local_result_and_never_posts_issue_ipc(self):
        for mode in ["local", "cloud-review"]:
            with self.subTest(mode=mode), patch.dict(os.environ, {"AGENT_REMOTE_COMMENTS": mode}), patch.object(self.worker, "run") as provider:
                self.worker.comment_issue("owner/repo", 1, self.root, "worker result")
                self.assertEqual((self.root / "comment.md").read_text(), "worker result")
                provider.assert_not_called()

    def test_worker_shell_read_strips_comments_and_blocks_write_before_logging(self):
        completed = subprocess.CompletedProcess([], 0, stdout='{"number":1}')
        with patch.object(self.worker.subprocess, "run", return_value=completed) as run:
            self.worker.run("gh issue view 1 --json number,comments")
            self.assertNotIn("comments", run.call_args.args[0])
        with patch.object(self.worker.subprocess, "run", side_effect=AssertionError("no provider")), redirect_stdout(io.StringIO()) as output:
            self.worker.run("gh issue comment 1 --body PRIVATE_BODY", check=False)
        self.assertNotIn("PRIVATE_BODY", output.getvalue())

    def test_local_worker_prompt_does_not_ingest_remote_comment_messages(self):
        prompt = self.worker.build_prompt({"number": 1, "body": "Task", "comments": [{"body": "REMOTE_IPC_MARKER"}]}, "owner/repo")
        self.assertNotIn("REMOTE_IPC_MARKER", prompt)

    def test_local_review_does_not_post_or_poll_comment_threads(self):
        with patch.object(common, "gh_json_or_none", side_effect=AssertionError("no comment read")), \
                patch.object(common, "run", side_effect=AssertionError("no comment write")):
            self.review.post_review_comment(self.decision())
            self.review.post_failed_workflow_review("owner/repo", 7, {"head": "abc"})

    def test_comment_only_acceptance_stays_blocked_in_local_policy(self):
        pr = {"headRefOid": "abc", "labels": [{"name": "agent:local-validation-passed"}, {"name": "agent:manual-validation-approved"}],
              "comments": [{"body": "<!-- atlas-agent-local-validation -->\nHead: `abc`\nResult: passed"},
                           {"body": "<!-- atlas-agent-deployed-validation -->\nHead: `abc`\nResult: passed"},
                           {"body": "<!-- atlas-agent-semantic-review -->\nHead: `abc`\nResult: passed"}]}
        self.assertFalse(self.review.local_validation_passed_for_head(pr))
        self.assertFalse(self.review.deployed_validation_passed_for_head(pr))
        self.assertEqual(self.review.semantic_review_state_for_head(pr), "missing")
        self.assertEqual(self.review.semantic_review_body_for_head(pr), "")

    def test_successful_cloud_review_is_published_once_per_material_body(self):
        with patch.dict(os.environ, {"AGENT_REMOTE_COMMENTS": "cloud-review"}), \
                patch.object(common, "gh_json_or_none", return_value=[]) as reads, \
                patch.object(common, "run", return_value=subprocess.CompletedProcess([], 0, stdout="created")) as writes:
            decision = self.decision()
            self.review.post_review_comment(decision)
            self.review.post_review_comment(decision)
            self.assertEqual(reads.call_count, 1)
            self.assertEqual(writes.call_count, 1)
            decision.reasons.append("a new material reason")
            self.review.post_review_comment(decision)
            self.assertEqual(writes.call_count, 2)
            decision.head = "new-head"
            self.review.post_review_comment(decision)
            self.assertEqual(writes.call_count, 3)
        records = list((self.root / "cloud-comment-publications").glob("*.json"))
        self.assertEqual(len(records), 1)
        self.assertNotIn("a new material reason", records[0].read_text())

    def test_existing_identical_cloud_summary_needs_no_patch(self):
        with patch.dict(os.environ, {"AGENT_REMOTE_COMMENTS": "cloud-review"}):
            decision = self.decision()
            body = self.review.review_comment_body(decision)
            with patch.object(common, "gh_json_or_none", return_value=[{"id": 23, "body": body}]) as reads, patch.object(common, "run") as writes:
                self.review.post_review_comment(decision)
                self.review.post_review_comment(decision)
            self.assertEqual(reads.call_count, 1)
            writes.assert_not_called()

    def test_failed_publication_is_not_cached_as_success(self):
        with patch.dict(os.environ, {"AGENT_REMOTE_COMMENTS": "cloud-review"}), \
                patch.object(common, "gh_json_or_none", return_value=[]), \
                patch.object(common, "run", return_value=subprocess.CompletedProcess([], 1, stdout="failure")) as writes:
            self.review.post_review_comment(self.decision())
            self.review.post_review_comment(self.decision())
        self.assertEqual(writes.call_count, 2)
        self.assertFalse((self.root / "cloud-comment-publications").exists())

    def test_failed_workflow_local_path_churn_does_not_repost_same_cloud_evidence(self):
        review = {"head": "abc", "root_cause": "unit tests failed", "category": "code", "next_action": "repair", "artifacts": "/local/run-one"}
        with patch.dict(os.environ, {"AGENT_REMOTE_COMMENTS": "cloud-review"}), \
                patch.object(common, "gh_json_or_none", return_value={}) as reads, \
                patch.object(common, "run", return_value=subprocess.CompletedProcess([], 0, stdout="created")) as writes:
            self.review.post_failed_workflow_review("owner/repo", 7, review)
            self.review.post_failed_workflow_review("owner/repo", 7, {**review, "artifacts": "/local/run-two"})
        self.assertEqual(reads.call_count, 1)
        self.assertEqual(writes.call_count, 1)

    def test_legacy_worker_behavior_remains_explicitly_available(self):
        with patch.dict(os.environ, {"AGENT_REMOTE_COMMENTS": "legacy"}), patch.object(self.worker, "run") as run:
            self.worker.comment_issue("owner/repo", 1, self.root, "legacy result")
        run.assert_called_once()

    def test_cloud_review_transport_allows_pr_summary_but_blocks_issue_ipc(self):
        with patch.dict(os.environ, {"AGENT_REMOTE_COMMENTS": "cloud-review"}), patch.object(common.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="ok")) as run:
            blocked = common.run(["gh", "issue", "comment", "1", "--body", "hidden"], check=False)
            self.assertEqual(blocked.returncode, 78)
            common.run(["gh", "pr", "comment", "7", "--body", "explicit cloud review"])
            self.assertEqual(run.call_count, 1)

    def test_runtime_parser_exposes_explicit_policy_and_defaults_legacy(self):
        with patch.dict(os.environ, {"AGENT_REMOTE_COMMENTS": "legacy"}):
            parser = self.loop.build_parser()
            self.assertEqual(parser.parse_args([]).remote_comments, "legacy")
            self.assertEqual(parser.parse_args(["--remote-comments", "local"]).remote_comments, "local")

    def test_invalid_policy_is_not_silently_treated_as_legacy(self):
        with patch.dict(os.environ, {"AGENT_REMOTE_COMMENTS": "invented"}), self.assertRaises(ValueError):
            common.run(["gh", "pr", "checks", "7"])


if __name__ == "__main__":
    unittest.main()
