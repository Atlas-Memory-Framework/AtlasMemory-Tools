from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
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
    author: str = "trusted-user",
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
        cls.worker = load_script("atlas_agent_worker_test", "atlas-agent-worker")
        cls.admin = load_script("atlas_agent_admin_test", "atlas-agent-admin")
        cls.finalize = load_script("atlas_agent_finalize_test", "atlas-agent-finalize")
        cls.review = load_script("atlas_agent_review_test", "atlas-agent-review")
        cls.reconcile = load_script("atlas_agent_reconcile_test", "atlas-agent-reconcile")
        cls.project_reconcile = load_script("atlas_agent_project_reconcile_test", "atlas-agent-project-reconcile")
        cls.semantic_review = load_script("atlas_agent_semantic_review_test", "atlas-agent-semantic-review")
        cls.pr_repair = load_script("atlas_agent_pr_repair_test", "atlas-agent-pr-repair")
        for module in (cls.triage, cls.orchestrator, cls.reconcile):
            module.common.trusted_authors = lambda: {"trusted-user"}

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

    def test_review_does_not_treat_unbackticked_manual_gate_none_as_manual_validation(self) -> None:
        self.assertFalse(self.review.issue_has_manual_validation(issue(body="Manual gates remaining: none")))
        self.assertFalse(self.review.issue_has_manual_validation(issue(body="Manual gates remaining: `none`")))

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

    def test_worker_honors_requested_issue_argument(self) -> None:
        self.assertEqual(self.worker.requested_issue_number(["atlas-agent-worker", "--once", "--issue", "17"]), 17)
        self.assertIsNone(self.worker.requested_issue_number(["atlas-agent-worker", "--once"]))

    def test_codex_profile_args_read_role_specific_configuration(self) -> None:
        original_env = os.environ.copy()
        os.environ["AGENT_CODEX_IMPLEMENTATION_PROFILE"] = "impl-low"
        os.environ["AGENT_CODEX_IMPLEMENTATION_MODEL"] = "gpt-5.5-low"
        os.environ["AGENT_CODEX_IMPLEMENTATION_EXTRA_ARGS"] = '--config model_reasoning_effort="low"'
        try:
            args = self.worker.common.codex_profile_args("implementation")
        finally:
            os.environ.clear()
            os.environ.update(original_env)

        self.assertEqual(
            args,
            [
                "--profile",
                "impl-low",
                "--model",
                "gpt-5.5-low",
                "--config",
                "model_reasoning_effort=low",
            ],
        )

    def test_orchestrator_treats_approved_review_wait_as_recoverable(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(
                labels=["agent:approved-dispatch", "agent:ready"],
                body="Dispatch recommendation: `review-before-dispatch`\nNext action: `wait_human`",
            )
        )

        self.assertEqual(reasons, [])

    def test_orchestrator_blocks_oversized_issue_when_one_point_required(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(labels=["status:ready", "points:5"], body="Points: 5"),
            require_one_point=True,
        )

        self.assertIn("points:5 requires decomposition before dispatch", reasons)

    def test_orchestrator_allows_one_point_issue_when_required(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(labels=["status:ready", "points:1"], body="Points: 1"),
            require_one_point=True,
        )

        self.assertEqual(reasons, [])

    def test_orchestrator_blocks_missing_points_when_one_point_required(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(labels=["status:ready"], body="Implement this."),
            require_one_point=True,
        )

        self.assertIn("missing one-point metadata", reasons)

    def test_orchestrator_blocks_dependencies_section_without_runtime_field(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(body="## Dependencies\n- owner/repo#2\n")
        )

        self.assertIn("dependencies section without Open dependencies field", reasons)

    def test_orchestrator_blocks_later_nonempty_open_dependencies_after_none(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(body="- Open dependencies: `none`\n- Open dependencies: `owner/repo#2`")
        )

        self.assertIn("open dependencies", reasons)

    def test_orchestrator_blocks_multiline_open_dependencies_field(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(body="- Open dependencies:\n  - owner/repo#2\n")
        )

        self.assertIn("open dependencies", reasons)

    def test_orchestrator_blocks_dispatch_mode_blocked(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(issue(body="- Dispatch mode: `blocked`"))

        self.assertIn("blocked dispatch mode", reasons)

    def test_orchestrator_blocks_issue_ready_false(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(issue(body="- Issue ready: `false`"))

        self.assertIn("issue ready false", reasons)

    def test_orchestrator_blocks_dispatch_guardrails_section(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(body="## Dispatch Guardrails\n- Requires decomposition\n")
        )

        self.assertIn("dispatch guardrails", reasons)

    def test_orchestrator_blocks_manual_validation_requirements_without_runtime_field(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(body="## Deployed / Manual Validation Requirements\n- Run hosted smoke\n")
        )

        self.assertIn("manual validation requirements without Manual gates remaining field", reasons)

    def test_orchestrator_blocks_conflicting_point_metadata(self) -> None:
        reasons = self.orchestrator.hard_non_execution_reasons(
            issue(labels=["points:1", "points:5"]),
            require_one_point=True,
        )

        self.assertIn("conflicting point metadata (points:1, points:5)", reasons)

    def test_worker_marks_published_issue_as_pr_open_not_done(self) -> None:
        calls: list[str] = []
        original_run = self.worker.run
        original_env = os.environ.copy()
        self.worker.run = lambda cmd, **_kwargs: calls.append(cmd) or ""
        os.environ.update(
            {
                "AGENT_READY_LABEL": "agent:ready",
                "AGENT_RUNNING_LABEL": "agent:running",
                "AGENT_DONE_LABEL": "agent:done",
                "AGENT_FAILED_LABEL": "agent:failed",
                "AGENT_PR_OPEN_LABEL": "agent:pr-open",
            }
        )
        try:
            self.worker.clear_running_labels("owner/repo", 7, pr_open=True)
        finally:
            self.worker.run = original_run
            os.environ.clear()
            os.environ.update(original_env)

        self.assertTrue(any('--add-label "agent:pr-open"' in call for call in calls))
        self.assertFalse(any('--add-label "agent:done"' in call for call in calls))

    def test_worker_changed_paths_include_staged_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (repo / "new-file.txt").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            paths, statuses = self.worker.changed_paths(repo)

        self.assertEqual(paths, ["new-file.txt"])
        self.assertEqual(statuses, ["A"])

    def test_worker_executable_paths_include_staged_untracked_executables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            script = repo / "run.sh"
            script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            paths = self.worker.executable_paths(repo)

        self.assertEqual(paths, ["run.sh"])

    def test_repo_env_overlay_copies_secret_files_into_worktree(self) -> None:
        original_env = os.environ.copy()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay = root / "repo-env" / "owner__repo" / "server"
            overlay.mkdir(parents=True)
            (overlay / ".env").write_text("SHOPIFY_SHOP=example\n", encoding="utf-8")
            worktree = root / "worktree"
            worktree.mkdir()
            os.environ["AGENT_REPO_ENV_OVERLAY_DIR"] = str(root / "repo-env")
            try:
                copied = self.worker.common.apply_repo_env_overlay("owner/repo", worktree)
                copied_text = (worktree / "server" / ".env").read_text(encoding="utf-8")
            finally:
                os.environ.clear()
                os.environ.update(original_env)

        self.assertEqual(copied, ["server/.env"])
        self.assertEqual(copied_text, "SHOPIFY_SHOP=example\n")

    def test_worker_builds_descriptive_pr_body_with_validation_evidence(self) -> None:
        body = self.worker.build_pr_body(
            issue(
                number=7,
                title="[WS] Add workflow route",
                body="## Excerpt\nImplement the workflow route.\n\n## Other\nIgnore",
            ),
            job_id="20260507T000000Z",
            base_sha="abc123",
            base_branch="main",
            branch="agent/issue-7/20260507T000000Z",
            status="M src/workflows.py\nA tests/test_workflows.py\n",
            diff_stat=" src/workflows.py | 10 +++++\n tests/test_workflows.py | 20 ++++++++++\n",
            codex_log=(
                "noise\n"
                "Implemented workflow route.\n\n"
                "Changed:\n"
                "- src/workflows.py\n\n"
                "Verification:\n"
                "- `pytest tests/test_workflows.py` passed: `2 passed`\n"
                "tokens used\n"
                "123"
            ),
        )

        self.assertIn("## Issue Context", body)
        self.assertIn("Implement the workflow route.", body)
        self.assertIn("`src/workflows.py`", body)
        self.assertIn("pytest tests/test_workflows.py", body)
        self.assertIn("Review Requirements", body)

    def test_worker_pr_body_warns_when_validation_is_missing(self) -> None:
        body = self.worker.build_pr_body(
            issue(number=7, title="[WS] Add workflow route", body="Body"),
            job_id="20260507T000000Z",
            base_sha="abc123",
            base_branch="main",
            branch="agent/issue-7/20260507T000000Z",
            status="M src/workflows.py\n",
            diff_stat=" src/workflows.py | 10 +++++\n",
            codex_log="Implemented change without a validation section.",
        )

        self.assertIn("No explicit test command/result section was found", body)

    def test_semantic_review_parses_result_values(self) -> None:
        self.assertEqual(self.semantic_review.parse_result("Result: pass\n"), "passed")
        self.assertEqual(self.semantic_review.parse_result("Result: failed\n"), "failed")
        self.assertEqual(self.semantic_review.parse_result("Result: needs-human\n"), "needs-human")
        self.assertEqual(self.semantic_review.parse_result("Summary only\n"), "failed")

    def test_semantic_review_extracts_final_answer_from_codex_transcript(self) -> None:
        raw = (
            "OpenAI Codex v0.128.0\n"
            "user\n"
            "Return exactly these sections:\n"
            "Result: pass|fail|needs-human\n"
            "codex\n"
            "Result: fail\n"
            "Summary:\n"
            "Needs deployed evidence.\n"
            "Blocking Findings:\n"
            "- Hosted validation evidence is missing.\n"
            "Validation Assessment:\n"
            "Insufficient.\n"
            "Rationale:\n"
            "CI does not exercise the hosted endpoint.\n"
            "tokens used\n"
            "120\n"
        )

        text = self.semantic_review.extract_review_text(raw)
        body = self.semantic_review.comment_body(7, "abc123", "failed", text, Path("/tmp/job"))

        self.assertNotIn("OpenAI Codex", body)
        self.assertNotIn("Result: pass|fail|needs-human", body)
        self.assertEqual(body.count("Result:"), 1)
        self.assertIn("Needs deployed evidence.", body)

    def test_semantic_review_prompt_includes_issue_diff_and_validation_rules(self) -> None:
        prompt = self.semantic_review.build_prompt(
            "owner/repo",
            {
                "number": 7,
                "title": "agent: #7 Add route",
                "url": "https://example.invalid/pr/7",
                "body": "## Validation Evidence\nNo explicit test command/result section was found",
                "headRefOid": "abc123",
                "baseRefName": "main",
            },
            {"number": 7, "title": "[WS] Story", "url": "https://example.invalid/issue/7", "body": "Implement route."},
            ["src/workflows.py"],
            "diff --git a/src/workflows.py b/src/workflows.py",
        )

        self.assertIn("Result: pass|fail|needs-human", prompt)
        self.assertIn("Treat a PR body that says", prompt)
        self.assertIn("Implement route.", prompt)
        self.assertIn("src/workflows.py", prompt)

    def test_semantic_review_needs_human_clears_stale_failed_label(self) -> None:
        calls: list[list[str]] = []
        original_run = self.semantic_review.common.run
        original_gh_json_or_none = self.semantic_review.common.gh_json_or_none
        self.semantic_review.common.run = lambda args, **_kwargs: calls.append(args)
        self.semantic_review.common.gh_json_or_none = lambda *_args, **_kwargs: {"comments": []}
        try:
            self.semantic_review.apply_result("owner/repo", 7, "needs-human", "body")
        finally:
            self.semantic_review.common.run = original_run
            self.semantic_review.common.gh_json_or_none = original_gh_json_or_none

        self.assertIn(
            ["gh", "issue", "edit", "7", "--repo", "owner/repo", "--remove-label", "agent:semantic-review-failed"],
            calls,
        )
        self.assertIn(
            ["gh", "issue", "edit", "7", "--repo", "owner/repo", "--add-label", "agent:semantic-review-required"],
            calls,
        )

    def test_semantic_review_command_failure_needs_human(self) -> None:
        class Completed:
            returncode = 30
            stdout = "Error: Read-only file system"

        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            original_run = self.semantic_review.common.run
            original_home = self.semantic_review.common.codex_home_copy
            self.semantic_review.common.run = lambda *_args, **_kwargs: Completed()
            self.semantic_review.common.codex_home_copy = lambda _job_dir: job_dir / "codex-home-copy"
            (job_dir / "codex-home-copy").mkdir()
            try:
                output = self.semantic_review.run_codex_review(job_dir, "Review this PR.")
            finally:
                self.semantic_review.common.run = original_run
                self.semantic_review.common.codex_home_copy = original_home

        self.assertIn("Result: needs-human", output)
        self.assertIn("Semantic review infrastructure exited 30", output)
        self.assertEqual(self.semantic_review.parse_result(output), "needs-human")

    def test_pr_repair_prompt_includes_inline_review_comments(self) -> None:
        body = self.pr_repair.build_prompt(
            {
                "number": 7,
                "url": "https://example.invalid/pr/7",
                "title": "agent: address issue #7",
                "baseRefName": "main",
                "headRefName": "agent/issue-7/job",
                "body": "Closes #7",
                "comments": [],
                "reviews": [{"state": "CHANGES_REQUESTED", "body": "Please fix auth."}],
            },
            checks="unit-tests failed",
            failed_log="AssertionError",
            review_comments='[{"path":"src/app.py","body":"This branch misses tenant validation."}]',
        )

        self.assertIn("Inline review comments", body)
        self.assertIn("This branch misses tenant validation.", body)
        self.assertIn("semantic review findings", body)

    def test_reconcile_requeues_open_stale_done_issue_without_open_pr(self) -> None:
        original_open_prs = self.reconcile.open_prs_for_issue
        self.reconcile.open_prs_for_issue = lambda _repo, _number: []
        try:
            decision = self.reconcile.decide_issue(
                "owner/repo",
                issue(labels=["agent:done", "status:ready"], number=9),
            )
        finally:
            self.reconcile.open_prs_for_issue = original_open_prs

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.action, "requeue")
        self.assertIn("agent:done", decision.labels_remove)
        self.assertIn("agent:ready", decision.labels_add)

    def test_reconcile_marks_stale_done_issue_with_open_pr(self) -> None:
        original_open_prs = self.reconcile.open_prs_for_issue
        self.reconcile.open_prs_for_issue = lambda _repo, _number: [{"number": 3}]
        try:
            decision = self.reconcile.decide_issue(
                "owner/repo",
                issue(labels=["agent:done", "status:ready"], number=9),
            )
        finally:
            self.reconcile.open_prs_for_issue = original_open_prs

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.action, "mark-pr-open")
        self.assertIn("agent:done", decision.labels_remove)
        self.assertIn("agent:pr-open", decision.labels_add)

    def test_project_reconcile_demotes_done_epic_with_open_children(self) -> None:
        config = self.project_reconcile.ProjectConfig(
            project_id="project",
            status_field_id="status",
            status_options={"Todo": "todo", "In Progress": "progress", "Done": "done"},
            execution_state_field_id="execution",
            execution_state_options={"Epic": "epic"},
        )
        parent = {
            "id": "parent-item",
            "status": "Done",
            "executionState": "Epic",
            "labels": ["type:story"],
            "content": {
                "repository": "owner/repo",
                "number": 1,
                "title": "[WS1][Epic] Parent",
                "url": "https://github.com/owner/repo/issues/1",
                "body": "",
            },
        }
        child = {
            "id": "child-item",
            "status": "Todo",
            "executionState": "Ready Now",
            "labels": ["type:story"],
            "content": {
                "repository": "owner/repo",
                "number": 2,
                "title": "[WS1-A] Child",
                "url": "https://github.com/owner/repo/issues/2",
                "body": "## Parent Epic\nhttps://github.com/owner/repo/issues/1",
            },
        }
        original_issue_state = self.project_reconcile.issue_state
        self.project_reconcile.issue_state = lambda repo, number: "OPEN"
        try:
            decisions = self.project_reconcile.decide("owner", 2, config, [parent, child])
        finally:
            self.project_reconcile.issue_state = original_issue_state

        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].repo, "owner/repo")
        self.assertEqual(decisions[0].number, 1)
        self.assertEqual(decisions[0].status_from, "Done")
        self.assertEqual(decisions[0].status_to, "In Progress")
        self.assertEqual(decisions[0].child_refs, ["owner/repo#2"])

    def test_project_reconcile_project_targets_file_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "projects.txt"
            path.write_text(
                "# comments are ignored\n"
                "OWNER/2\n"
                "OtherOrg 7\n",
                encoding="utf-8",
            )

            targets = self.project_reconcile.project_targets(str(path), "fallback", 1)

        self.assertEqual(targets, [("OWNER", 2), ("OtherOrg", 7)])

    def test_project_reconcile_dry_run_flag_is_accepted_as_explicit_preview(self) -> None:
        args = self.project_reconcile.build_parser().parse_args(["--dry-run"])

        self.assertTrue(args.dry_run)
        self.assertFalse(args.apply)

    def test_orchestrator_preserves_real_hard_blockers(self) -> None:
        review_reasons = self.orchestrator.hard_non_execution_reasons(
            issue(body="Dispatch recommendation: `review-before-dispatch`")
        )
        gate_reasons = self.orchestrator.hard_non_execution_reasons(
            issue(labels=["needs-human"], body="Manual gates remaining: `run hosted smoke`")
        )

        self.assertEqual(review_reasons, ["review-before-dispatch requires explicit queueing"])
        self.assertEqual(gate_reasons, ["manual gates remaining"])

    def test_reconcile_allows_unbackticked_none_execution_fields(self) -> None:
        blockers = self.reconcile.queue_blockers(
            issue(body="Open dependencies: none\nManual gates remaining: none"),
            set(),
        )

        self.assertNotIn("open dependencies", blockers)
        self.assertNotIn("manual gates remaining", blockers)

    def test_finalizer_blocks_pr_linked_to_epic_issue(self) -> None:
        original_issue_view = self.finalize.issue_view
        self.finalize.issue_view = lambda _repo, _number: issue(labels=["type:epic"], title="[Epic] Parent", number=7)
        try:
            reasons = self.finalize.issue_guard_reasons(
                "owner/repo",
                7,
                check_dependencies=True,
            )
        finally:
            self.finalize.issue_view = original_issue_view

        self.assertEqual(reasons, ["linked issue is an epic/tracker/non-execution issue"])

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
        self.orchestrator.common.trusted_authors = lambda: {"trusted-user"}
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

    def test_dependency_blockers_ignore_execution_state_none_with_parent_epic(self) -> None:
        blockers = self.finalize.common.issue_dependency_blockers(
            "owner/repo",
            issue(
                body=(
                    "## Parent Epic\n"
                    "https://github.com/owner/repo/issues/56\n\n"
                    "<!-- AGENTIC_EXECUTION_STATE:START -->\n"
                    "## Execution State\n"
                    "- Open dependencies: `none`\n"
                    "- Manual gates remaining: `none`\n"
                    "<!-- AGENTIC_EXECUTION_STATE:END -->\n"
                ),
                number=1,
            ),
        )

        self.assertEqual(blockers, [])

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
