from __future__ import annotations

import importlib.machinery
import importlib.util
import json
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
        cls.issue_decompose = load_script("atlas_agent_issue_decompose_test", "atlas-agent-issue-decompose")
        cls.workstream_review = load_script("atlas_agent_workstream_review_test", "atlas-agent-workstream-review")
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

    def test_operator_env_overrides_runtime_state_paths(self) -> None:
        original_jobs = os.environ.get("AGENT_JOBS")
        original_logs = os.environ.get("AGENT_LOGS")
        original_repos = os.environ.get("AGENT_REPOS")
        os.environ["AGENT_JOBS"] = "/tmp/runtime-jobs-test"
        os.environ["AGENT_LOGS"] = "/tmp/runtime-logs-test"
        os.environ["AGENT_REPOS"] = "/tmp/runtime-repos-test"
        try:
            self.assertEqual(self.triage.common.jobs_dir(), Path("/tmp/runtime-jobs-test"))
            self.assertEqual(self.triage.common.logs_dir(), Path("/tmp/runtime-logs-test"))
            self.assertEqual(self.triage.common.repo_dir("owner/repo"), Path("/tmp/runtime-repos-test/owner__repo"))
        finally:
            for key, value in {
                "AGENT_JOBS": original_jobs,
                "AGENT_LOGS": original_logs,
                "AGENT_REPOS": original_repos,
            }.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

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

    def test_common_rejects_shared_codex_home_by_default(self) -> None:
        common = self.worker.common
        original_env = os.environ.copy()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            codex_home = home / ".codex"
            codex_home.mkdir(parents=True, mode=0o700)
            config_path = codex_home / "config.toml"
            auth_path = codex_home / "auth.json"
            config_path.write_text('model = "gpt-5"\n', encoding="utf-8")
            auth_path.write_text("{}\n", encoding="utf-8")
            os.chmod(config_path, 0o600)
            os.chmod(auth_path, 0o600)
            try:
                os.environ["HOME"] = str(home)
                os.environ["AGENT_CODEX_HOME"] = str(codex_home)
                os.environ["AGENT_CODEX_ISOLATION_REQUIRED"] = "true"
                os.environ["AGENT_ALLOW_SHARED_CODEX_HOME"] = "false"

                validation = common.validate_codex_home()

                os.environ["AGENT_ALLOW_SHARED_CODEX_HOME"] = "true"
                override_validation = common.validate_codex_home()
            finally:
                os.environ.clear()
                os.environ.update(original_env)

        self.assertFalse(validation["ok"])
        self.assertTrue(validation["codex_home"]["shared_global_home"])
        self.assertIn("shared/global Codex home", " ".join(validation["errors"]))
        self.assertTrue(override_validation["ok"])
        self.assertIn("shared/global Codex home", " ".join(override_validation["warnings"]))

    def test_common_writes_non_secret_provider_metadata_for_codex_copy(self) -> None:
        common = self.worker.common
        original_env = os.environ.copy()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            source = root / "runtime" / "codex-home"
            job_dir = root / "job"
            source.mkdir(parents=True, mode=0o700)
            job_dir.mkdir()
            home.mkdir()
            config_path = source / "config.toml"
            auth_path = source / "auth.json"
            config_path.write_text('forced_chatgpt_workspace_id = "ws-atlas"\n', encoding="utf-8")
            auth_path.write_text("{}\n", encoding="utf-8")
            os.chmod(config_path, 0o600)
            os.chmod(auth_path, 0o600)
            try:
                os.environ["HOME"] = str(home)
                os.environ["AGENT_REPO"] = "owner/repo"
                os.environ["AGENT_BASE_BRANCH"] = "main"
                os.environ["AGENT_CODEX_HOME"] = str(source)
                os.environ["AGENT_CODEX_ISOLATION_REQUIRED"] = "true"
                os.environ["AGENT_ALLOW_SHARED_CODEX_HOME"] = "false"
                os.environ["AGENT_PROVIDER_ACCOUNT_ID"] = "acct-atlas"
                os.environ["AGENT_PROVIDER_ACCOUNT_LABEL"] = "Atlas"
                os.environ["AGENT_PROVIDER_SUBSCRIPTION_LABEL"] = "GPT Pro Atlas"
                os.environ["AGENT_CODEX_WORKSPACE_ID"] = "ws-atlas"

                run_home = common.codex_home_copy(job_dir)
                run_home_config_exists = (run_home / "config.toml").exists()
                metadata = json.loads((job_dir / "provider-account.json").read_text(encoding="utf-8"))
            finally:
                os.environ.clear()
                os.environ.update(original_env)

        self.assertTrue(run_home_config_exists)
        self.assertEqual(metadata["runtime"]["repo"], "owner/repo")
        self.assertEqual(metadata["provider"]["account_id"], "acct-atlas")
        self.assertEqual(metadata["provider"]["subscription_label"], "GPT Pro Atlas")
        self.assertEqual(metadata["codex"]["workspace_id"], "ws-atlas")
        self.assertEqual(metadata["codex"]["auth_indicator"], "auth.json")
        self.assertTrue(metadata["codex"]["validation"]["ok"])
        self.assertNotIn(str(source), json.dumps(metadata))

    def test_codex_stages_share_common_home_copy_validation(self) -> None:
        stages = [
            self.worker,
            self.issue_decompose,
            self.workstream_review,
            self.semantic_review,
            self.pr_repair,
        ]

        for stage in stages:
            self.assertIs(stage.common, self.worker.common)
            self.assertIs(stage.common.codex_home_copy, self.worker.common.codex_home_copy)

    def test_worker_disables_repo_hooks_by_default_with_env_override(self) -> None:
        original_env = os.environ.copy()
        try:
            os.environ.pop("AGENT_DISABLE_REPO_HOOKS", None)
            self.assertTrue(self.worker.disable_repo_hooks())

            os.environ["AGENT_DISABLE_REPO_HOOKS"] = "0"
            self.assertFalse(self.worker.disable_repo_hooks())

            os.environ["AGENT_DISABLE_REPO_HOOKS"] = "false"
            self.assertFalse(self.worker.disable_repo_hooks())
        finally:
            os.environ.clear()
            os.environ.update(original_env)

    def test_worker_configures_worktree_git_identity(self) -> None:
        original_env = os.environ.copy()
        original_run = self.worker.run
        calls: list[tuple[str, Path]] = []
        worktree = Path("/tmp/worktree")

        def fake_run(command, cwd=None, **_kwargs):
            calls.append((command, cwd))
            return ""

        try:
            os.environ["AGENT_GIT_USER_NAME"] = "Custom Agent"
            os.environ["AGENT_GIT_USER_EMAIL"] = "custom-agent@example.invalid"
            self.worker.run = fake_run

            self.worker.configure_worktree_identity(worktree)
        finally:
            self.worker.run = original_run
            os.environ.clear()
            os.environ.update(original_env)

        self.assertEqual(
            calls,
            [
                ("git config user.name 'Custom Agent'", worktree),
                ("git config user.email custom-agent@example.invalid", worktree),
            ],
        )

    def test_worker_container_volumes_mount_git_cache_and_tools_readonly(self) -> None:
        original_env = os.environ.copy()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "AtlasMemory-Tools"
            tools.mkdir()
            os.environ["AGENT_TOOLS_MOUNT_PATHS"] = str(tools)
            try:
                volumes = self.worker.worker_container_volumes(
                    root / "job" / "codex-home",
                    root / "jobs" / "checkouts" / "owner__repo" / "issue-7",
                    root / "job",
                    root / "repos" / "owner__repo",
                )
            finally:
                os.environ.clear()
                os.environ.update(original_env)

        self.assertIn(f"-v {root / 'job' / 'codex-home'}:/home/agent/.codex:Z", volumes)
        self.assertIn(f"-v {root / 'jobs' / 'checkouts' / 'owner__repo' / 'issue-7'}:/work:Z", volumes)
        self.assertIn(f"-v {root / 'job'}:/job:Z", volumes)
        self.assertIn(
            f"-v {root / 'repos' / 'owner__repo'}:{root / 'repos' / 'owner__repo'}:Z",
            volumes,
        )
        self.assertIn(f"-v {tools}:{tools}:ro,Z", volumes)

    def test_pr_repair_disables_repo_hooks_by_default_with_env_override(self) -> None:
        original_env = os.environ.copy()
        try:
            os.environ.pop("AGENT_DISABLE_REPO_HOOKS", None)
            self.assertTrue(self.pr_repair.disable_repo_hooks())

            os.environ["AGENT_DISABLE_REPO_HOOKS"] = "0"
            self.assertFalse(self.pr_repair.disable_repo_hooks())

            os.environ["AGENT_DISABLE_REPO_HOOKS"] = "no"
            self.assertFalse(self.pr_repair.disable_repo_hooks())
        finally:
            os.environ.clear()
            os.environ.update(original_env)

    def test_pr_repair_container_volumes_mount_git_cache_and_tools_readonly(self) -> None:
        original_env = os.environ.copy()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "AtlasMemory-Tools"
            tools.mkdir()
            os.environ["AGENT_TOOLS_MOUNT_PATHS"] = str(tools)
            try:
                volumes = self.pr_repair.repair_container_volumes(
                    root / "job" / "codex-home",
                    root / "jobs" / "checkouts" / "owner__repo" / "pr-7-repair",
                    root / "job",
                    root / "repos" / "owner__repo",
                )
            finally:
                os.environ.clear()
                os.environ.update(original_env)

        self.assertIn("-v", volumes)
        self.assertIn(f"{root / 'job' / 'codex-home'}:/home/agent/.codex:Z", volumes)
        self.assertIn(f"{root / 'jobs' / 'checkouts' / 'owner__repo' / 'pr-7-repair'}:/work:Z", volumes)
        self.assertIn(f"{root / 'job'}:/job:Z", volumes)
        self.assertIn(
            f"{root / 'repos' / 'owner__repo'}:{root / 'repos' / 'owner__repo'}:Z",
            volumes,
        )
        self.assertIn(f"{tools}:{tools}:ro,Z", volumes)

    def test_common_classifies_github_commands_for_throttling(self) -> None:
        common = self.orchestrator.common

        self.assertTrue(common.gh_command_is_project(["project", "list", "--owner", "Instablinds"]))
        self.assertTrue(common.gh_command_is_graphql_heavy(["issue", "list", "--json", "number,title"]))
        self.assertTrue(common.gh_command_is_mutating(["issue", "edit", "7", "--add-label", "agent:ready"]))
        self.assertFalse(common.gh_command_is_mutating(["issue", "list", "--json", "number"]))

    def test_common_records_shared_github_rate_limit_pause(self) -> None:
        common = self.orchestrator.common
        original_jobs_dir = common.jobs_dir
        original_env = os.environ.copy()
        with tempfile.TemporaryDirectory() as tmp:
            common.jobs_dir = lambda: Path(tmp)
            os.environ["AGENT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS"] = "1"
            try:
                common.github_throttle_after(
                    ["issue", "list", "--json", "number"],
                    "GraphQL: API rate limit already exceeded for user ID 1.",
                    1,
                )
                state = common.read_json_file(Path(tmp) / "github-api-throttle" / "state.json")
            finally:
                common.jobs_dir = original_jobs_dir
                os.environ.clear()
                os.environ.update(original_env)

        self.assertIn("pause_until", state)
        self.assertEqual(state["last_rate_limit_command"], "gh issue list --json number")

    def test_common_reports_throttle_status_without_github(self) -> None:
        common = self.orchestrator.common
        original_jobs_dir = common.jobs_dir
        with tempfile.TemporaryDirectory() as tmp:
            common.jobs_dir = lambda: Path(tmp)
            try:
                state_path, lock_path = common.github_throttle_paths()
                common.write_json(
                    state_path,
                    {
                        "pause_until": 100.0,
                        "next_allowed_at": 200.0,
                        "last_command": "gh issue list",
                        "last_rate_limit_command": "gh api graphql",
                    },
                )
                common.write_json(lock_path, {"pid": 123})
                os.utime(lock_path, (1, 1))

                status = common.github_throttle_status(stale_seconds=1)
            finally:
                common.jobs_dir = original_jobs_dir

        self.assertEqual(status["last_command"], "gh issue list")
        self.assertEqual(status["last_rate_limit_command"], "gh api graphql")
        self.assertTrue(status["stale_lock"]["exists"])
        self.assertTrue(status["stale_lock"]["stale"])

    def test_common_reports_dead_pid_lock_as_stale(self) -> None:
        common = self.orchestrator.common
        original_jobs_dir = common.jobs_dir
        with tempfile.TemporaryDirectory() as tmp:
            common.jobs_dir = lambda: Path(tmp)
            try:
                _state_path, lock_path = common.github_throttle_paths()
                common.write_json(lock_path, {"pid": 999999999})

                status = common.github_throttle_status(stale_seconds=120.0)
            finally:
                common.jobs_dir = original_jobs_dir

        self.assertTrue(status["stale_lock"]["exists"])
        self.assertTrue(status["stale_lock"]["stale"])

    def test_common_skips_issue_project_automation_state_by_default(self) -> None:
        common = self.orchestrator.common
        original_targets = common.project_targets
        try:
            common.project_targets = lambda _path=None: [("owner", 2)]

            common.update_issue_automation_state("owner/repo", 9, "Running", status="In Progress")
        finally:
            common.project_targets = original_targets

    def test_common_updates_issue_project_automation_state_when_explicit(self) -> None:
        common = self.orchestrator.common
        original_targets = common.project_targets
        original_info = common.project_info
        original_fields = common.project_fields
        original_items = common.project_items
        original_run = common.run
        original_env = os.environ.copy()
        calls: list[list[str]] = []
        try:
            os.environ["AGENT_PROJECT_STATE_UPDATE_MODE"] = "direct"
            common.project_targets = lambda _path=None: [("owner", 2)]
            common.project_info = lambda _owner, _number: {"id": "PROJECT"}
            common.project_fields = lambda _owner, _number: [
                {"name": "AutomationState", "id": "STATE", "options": [{"name": "Running", "id": "RUNNING"}]},
                {"name": "Status", "id": "STATUS", "options": [{"name": "In Progress", "id": "INPROGRESS"}]},
            ]
            common.project_items = lambda _owner, _number: [
                {"id": "ITEM", "content": {"repository": "owner/repo", "number": 9}}
            ]
            common.run = lambda args, **_kwargs: calls.append(args)

            common.update_issue_automation_state(
                "owner/repo",
                9,
                "Running",
                status="In Progress",
                projects_file="projects.txt",
            )
        finally:
            common.project_targets = original_targets
            common.project_info = original_info
            common.project_fields = original_fields
            common.project_items = original_items
            common.run = original_run
            os.environ.clear()
            os.environ.update(original_env)

        self.assertEqual(len(calls), 2)
        self.assertIn("--single-select-option-id", calls[0])
        self.assertIn("RUNNING", calls[0])
        self.assertIn("INPROGRESS", calls[1])

    def test_common_queues_issue_project_automation_state_without_github(self) -> None:
        common = self.orchestrator.common
        original_jobs_dir = common.jobs_dir
        original_targets = common.project_targets
        original_info = common.project_info
        original_env = os.environ.copy()
        with tempfile.TemporaryDirectory() as tmp:
            common.jobs_dir = lambda: Path(tmp)
            common.project_targets = lambda _path=None: [("owner", 2)]
            common.project_info = lambda _owner, _number: self.fail("queue mode should not inspect GitHub Projects")
            os.environ["AGENT_PROJECT_STATE_UPDATES"] = "true"
            os.environ["AGENT_PROJECT_STATE_UPDATE_MODE"] = "queue"
            try:
                common.update_issue_automation_state("owner/repo", 9, "Running", status="In Progress")
                records = common.iter_project_sync_records()
            finally:
                common.jobs_dir = original_jobs_dir
                common.project_targets = original_targets
                common.project_info = original_info
                os.environ.clear()
                os.environ.update(original_env)

        self.assertEqual(len(records), 1)
        record = records[0][2]
        self.assertEqual(record["kind"], "project_field_update")
        self.assertEqual(record["repo"], "owner/repo")
        self.assertEqual(record["project_owner"], "owner")
        self.assertEqual(record["project_number"], 2)
        self.assertEqual(record["fields"], {"AutomationState": "Running", "Status": "In Progress"})

    def test_common_label_cache_skips_repeated_label_create(self) -> None:
        common = self.orchestrator.common
        original_jobs_dir = common.jobs_dir
        original_run = common.run
        calls: list[list[str]] = []

        def fake_run(args, **_kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "already exists\n")

        with tempfile.TemporaryDirectory() as tmp:
            common.jobs_dir = lambda: Path(tmp)
            common.run = fake_run
            try:
                common.ensure_labels_cached("owner/repo", {"agent:ready": "0E8A16", "agent:failed": "B60205"})
                common.ensure_labels_cached("owner/repo", {"agent:ready": "0E8A16", "agent:failed": "B60205"})
                cache = json.loads((Path(tmp) / "label-cache" / "owner__repo.json").read_text(encoding="utf-8"))
            finally:
                common.jobs_dir = original_jobs_dir
                common.run = original_run

        self.assertEqual(len(calls), 2)
        self.assertEqual(cache["labels"], {"agent:failed": "B60205", "agent:ready": "0E8A16"})

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

    def test_orchestrator_extracts_write_scope_metadata(self) -> None:
        scopes = self.orchestrator.issue_write_scope(
            issue(
                body=(
                    "## Write Scope\n"
                    "- `src/routes/workflow.ts`\n"
                    "- `tests/workflow.test.ts`\n\n"
                    "WriteScope: `docs/runtime.md`"
                )
            )
        )

        self.assertEqual(scopes, ["src/routes/workflow.ts", "tests/workflow.test.ts", "docs/runtime.md"])

    def test_orchestrator_routes_cross_repo_issue_to_execution_repo(self) -> None:
        item = issue(
            body="- Execution repo: `owner/ui`\n- Base branch: `main`\n",
            number=328,
        )

        self.assertEqual(self.orchestrator.execution_repo_for_issue("owner/planning", item), "owner/ui")

    def test_worker_pr_body_closes_source_issue_for_cross_repo_dispatch(self) -> None:
        body = self.worker.build_pr_body(
            issue(number=328, title="Add visualizer"),
            "job-1",
            "abc123",
            "main",
            "agent/issue-328/job-1",
            "M src/app.ts\n",
            "1 file changed\n",
            "Summary\nTests: passed\n",
            "owner/planning",
        )

        self.assertIn("- Issue repo: `owner/planning`", body)
        self.assertIn("Closes owner/planning#328", body)

    def test_review_and_finalize_parse_cross_repo_linked_issue_ref(self) -> None:
        pr = {"body": "Closes owner/planning#328\n", "headRefName": "agent/issue-328/job-1"}

        self.assertEqual(self.review.linked_issue_ref("owner/ui", pr), ("owner/planning", 328))
        self.assertEqual(self.finalize.linked_issue_ref("owner/ui", pr), ("owner/planning", 328))

    def test_orchestrator_write_scope_overlap_is_conservative(self) -> None:
        self.assertTrue(self.orchestrator.scopes_overlap("src/routes", "src/routes/workflow.ts"))
        self.assertTrue(self.orchestrator.scopes_overlap("db/migrations/001.sql", "db/migrations/002.sql"))
        self.assertFalse(self.orchestrator.scopes_overlap("src/routes/workflow.ts", "src/models/blind.ts"))

    def test_orchestrator_write_scope_lease_blocks_overlaps_but_allows_disjoint_paths(self) -> None:
        original_jobs_dir = self.orchestrator.common.jobs_dir
        with tempfile.TemporaryDirectory() as tmp:
            self.orchestrator.common.jobs_dir = lambda: Path(tmp)
            try:
                lease, blocker = self.orchestrator.acquire_write_scope_lease(
                    "owner/repo",
                    issue(number=7, body="## Write Scope\n- `src/routes/workflow.ts`\n"),
                    "main",
                    3600,
                )
                overlapping, overlap_blocker = self.orchestrator.acquire_write_scope_lease(
                    "owner/repo",
                    issue(number=8, body="## Write Scope\n- `src/routes`\n"),
                    "main",
                    3600,
                )
                disjoint, disjoint_blocker = self.orchestrator.acquire_write_scope_lease(
                    "owner/repo",
                    issue(number=9, body="## Write Scope\n- `src/models/blind.ts`\n"),
                    "main",
                    3600,
                )
            finally:
                self.orchestrator.common.jobs_dir = original_jobs_dir
                self.orchestrator.release_write_scope_lease(lease if "lease" in locals() else [])
                self.orchestrator.release_write_scope_lease(disjoint if "disjoint" in locals() else [])

        self.assertIsNone(blocker)
        self.assertTrue(lease)
        self.assertEqual(overlapping, [])
        self.assertIn("overlaps", str(overlap_blocker))
        self.assertIsNone(disjoint_blocker)
        self.assertTrue(disjoint)

    def test_orchestrator_unknown_write_scope_consumes_exclusive_repo_base_lock(self) -> None:
        original_jobs_dir = self.orchestrator.common.jobs_dir
        with tempfile.TemporaryDirectory() as tmp:
            self.orchestrator.common.jobs_dir = lambda: Path(tmp)
            try:
                exclusive, blocker = self.orchestrator.acquire_write_scope_lease(
                    "owner/repo",
                    issue(number=7, body="## Write Scope\n- `unknown`\n"),
                    "main",
                    3600,
                )
                disjoint, disjoint_blocker = self.orchestrator.acquire_write_scope_lease(
                    "owner/repo",
                    issue(number=8, body="## Write Scope\n- `src/models/blind.ts`\n"),
                    "main",
                    3600,
                )
            finally:
                self.orchestrator.common.jobs_dir = original_jobs_dir
                self.orchestrator.release_write_scope_lease(exclusive if "exclusive" in locals() else [])
                self.orchestrator.release_write_scope_lease(disjoint if "disjoint" in locals() else [])

        self.assertIsNone(blocker)
        self.assertTrue(exclusive)
        self.assertEqual(disjoint, [])
        self.assertIn("exclusive", str(disjoint_blocker))

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

    def test_worker_policy_gate_record_captures_required_labels_and_diff_stats(self) -> None:
        original_env = os.environ.copy()
        os.environ.update(
            {
                "AGENT_ALLOW_WORKFLOWS_LABEL": "agent:allow-workflows",
                "AGENT_ALLOW_INFRA_LABEL": "agent:allow-infra",
            }
        )
        try:
            requirements = self.worker.blocked_policy_requirements(
                [".github/workflows/ci.yml", "infra/main.tf"],
                labels=[],
            )

            with tempfile.TemporaryDirectory() as tmp:
                job_dir = Path(tmp)
                policy_errors = [f"{item['path']} requires {item['label']}" for item in requirements]
                record = self.worker.write_policy_gate_record(
                    job_dir=job_dir,
                    issue=issue(number=7, title="[WS] Gate", body="Body"),
                    repo="owner/repo",
                    job_id="20260523T000000Z",
                    base_sha="abc123",
                    paths=[".github/workflows/ci.yml", "infra/main.tf"],
                    statuses=["M", "A"],
                    required_labels=[item["label"] for item in requirements],
                    diff_stat=" .github/workflows/ci.yml | 4 ++\n infra/main.tf | 8 ++++++\n",
                    diff_lines=42,
                    policy_errors=policy_errors,
                )
                persisted = json.loads((job_dir / "policy-gate.json").read_text(encoding="utf-8"))
        finally:
            os.environ.clear()
            os.environ.update(original_env)

        self.assertEqual(record, persisted)
        self.assertEqual(persisted["issue"]["number"], 7)
        self.assertEqual(persisted["repo"], "owner/repo")
        self.assertEqual(persisted["job_id"], "20260523T000000Z")
        self.assertEqual(persisted["required_labels"], ["agent:allow-infra", "agent:allow-workflows"])
        self.assertEqual(
            persisted["changed_files"],
            [
                {"path": ".github/workflows/ci.yml", "status": "M"},
                {"path": "infra/main.tf", "status": "A"},
            ],
        )
        self.assertEqual(persisted["diff_stats"]["file_count"], 2)
        self.assertEqual(persisted["diff_stats"]["line_count"], 42)
        self.assertIn("rerun from scratch", persisted["next_action"])

    def test_worker_policy_gate_comment_says_awaiting_human_approval(self) -> None:
        body = self.worker.build_policy_gate_comment(
            number=7,
            job_id="20260523T000000Z",
            base_sha="abc123",
            required_labels=["agent:allow-infra"],
            policy_errors=["infra/main.tf requires agent:allow-infra"],
            status="A infra/main.tf\n",
            job_dir=Path("/tmp/job"),
        )

        self.assertIn("awaiting human policy approval", body)
        self.assertIn("`agent:allow-infra`", body)
        self.assertIn("requeue the issue", body)
        self.assertIn("will not auto-apply this saved diff", body)
        self.assertIn("/tmp/job/policy-gate.json", body)

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

    def test_worker_validation_gate_fails_missing_section_without_waiver(self) -> None:
        gate = self.worker.classify_validation_gate(
            issue(number=7),
            "Implemented the change.\n\nSummary:\n- Updated the route.",
        )

        self.assertEqual(gate["status"], "failed")
        self.assertFalse(gate["publish_allowed"])
        self.assertIn("No explicit Tests or Verification section", gate["reason"])

    def test_worker_validation_gate_fails_empty_section(self) -> None:
        gate = self.worker.classify_validation_gate(
            issue(number=7),
            "Summary:\n- Updated the route.\n\nTests:\n\nNext Steps:\n- Review.",
        )

        self.assertEqual(gate["status"], "failed")
        self.assertFalse(gate["publish_allowed"])
        self.assertIn("No explicit Tests or Verification section", gate["reason"])

    def test_worker_validation_gate_fails_unreasoned_skip(self) -> None:
        gate = self.worker.classify_validation_gate(
            issue(number=7),
            "Summary:\n- Updated docs.\n\nTests:\n- Not run.",
        )

        self.assertEqual(gate["status"], "failed")
        self.assertFalse(gate["publish_allowed"])
        self.assertIn("without a reason", gate["reason"])

    def test_worker_validation_gate_fails_skip_with_none_reason(self) -> None:
        gate = self.worker.classify_validation_gate(
            issue(number=7),
            "Verification: Not run: none",
        )

        self.assertEqual(gate["status"], "failed")
        self.assertFalse(gate["publish_allowed"])

    def test_worker_validation_gate_allows_skip_with_reason(self) -> None:
        gate = self.worker.classify_validation_gate(
            issue(number=7),
            "Summary:\n- Updated docs.\n\nVerification: Not run - documentation only change.",
        )

        self.assertEqual(gate["status"], "passed")
        self.assertTrue(gate["publish_allowed"])
        self.assertIn("Not run - documentation only change.", gate["validation"])

    def test_worker_validation_gate_accepts_bold_tests_heading(self) -> None:
        gate = self.worker.classify_validation_gate(
            issue(number=7),
            "Summary:\n- Updated route.\n\n**Tests**\n- `pytest tests/test_routes.py` passed: `4 passed`.",
        )

        self.assertEqual(gate["status"], "passed")
        self.assertTrue(gate["publish_allowed"])
        self.assertIn("pytest tests/test_routes.py", gate["validation"])

    def test_worker_final_response_extracts_bold_tests_heading(self) -> None:
        final_response = self.worker.extract_codex_final_response(
            "noise\n"
            "Summary:\n"
            "- Updated route.\n\n"
            "**Tests**\n"
            "- `pytest tests/test_routes.py` passed: `4 passed`.\n"
            "tokens used\n"
            "123"
        )

        self.assertTrue(final_response.startswith("**Tests**"))
        self.assertIn("pytest tests/test_routes.py", final_response)

    def test_worker_validation_gate_allows_body_waiver_for_missing_evidence(self) -> None:
        gate = self.worker.classify_validation_gate(
            issue(number=7, body="Validation waiver: tracked in external QA run 123"),
            "Implemented the change without a validation section.",
        )

        self.assertEqual(gate["status"], "waived")
        self.assertTrue(gate["publish_allowed"])
        self.assertIn("external QA", gate["waiver"])

    def test_worker_validation_gate_allows_label_waiver_for_unreasoned_skip(self) -> None:
        gate = self.worker.classify_validation_gate(
            issue(number=7, labels=["agent:validation-waived"]),
            "Verification:\n- Tests skipped.",
        )

        self.assertEqual(gate["status"], "waived")
        self.assertTrue(gate["publish_allowed"])
        self.assertIn("agent:validation-waived", gate["waiver"])

    def test_worker_validation_waiver_rejects_none_values(self) -> None:
        self.assertEqual(self.worker.validation_waiver(issue(body="ValidationWaiver: none")), "")
        self.assertEqual(self.worker.validation_waiver(issue(body="Validation waiver: `n/a`")), "")

    def test_worker_pr_body_includes_validation_waiver(self) -> None:
        body = self.worker.build_pr_body(
            issue(number=7, title="[WS] Add workflow route", body="Validation waiver: manual run approved by QA"),
            job_id="20260507T000000Z",
            base_sha="abc123",
            base_branch="main",
            branch="agent/issue-7/20260507T000000Z",
            status="M src/workflows.py\n",
            diff_stat=" src/workflows.py | 10 +++++\n",
            codex_log="Implemented change without a validation section.",
        )

        self.assertIn("Validation waiver: manual run approved by QA", body)

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
        state_updates: list[tuple[str, int, str]] = []
        original_run = self.orchestrator.common.run
        original_state = self.orchestrator.common.update_issue_automation_state
        original_skip = self.orchestrator.has_open_pr_for_issue
        self.orchestrator.common.run = lambda args, **_kwargs: calls.append(args)
        self.orchestrator.common.update_issue_automation_state = (
            lambda repo, number, state, **_kwargs: state_updates.append((repo, number, state))
        )
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
            self.orchestrator.common.update_issue_automation_state = original_state
            self.orchestrator.has_open_pr_for_issue = original_skip

        self.assertTrue(queued)
        self.assertEqual(calls, [["gh", "issue", "edit", "9", "--repo", "owner/repo", "--add-label", "agent:ready"]])
        self.assertEqual(state_updates, [("owner/repo", 9, "Queued")])

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

    def test_process_once_writes_dispatch_preview_with_policy_blockers(self) -> None:
        body_ready = "Open dependencies: none\nManual gates remaining: none\n"
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
        self.orchestrator.ready_issues = lambda _repo, _limit: [
            issue(labels=["agent:ready", "points:1"], body=body_ready, number=9, title="Runnable"),
            issue(labels=["agent:ready", "points:1"], body=body_ready + "Touches infra", number=10, title="Needs allow"),
        ]
        self.orchestrator.has_open_pr_for_issue = lambda _repo, _number: False
        self.orchestrator.run_worker = lambda *_args, **_kwargs: 0
        self.orchestrator.common.run = lambda args, **_kwargs: calls.append(args)
        self.orchestrator.common.trusted_authors = lambda: {"trusted-user"}
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "triage.json"
            args = types.SimpleNamespace(
                triage_needs_human=False,
                triage_summary=str(summary),
                repos_file=None,
                auto_queue_label=None,
                auto_queue_max=1,
                limit=20,
                inspect_failed=False,
                auto_queue_skip_open_pr=True,
                publish=False,
                dry_run=True,
                max_items=3,
                max_per_repo=1,
                dispatch_deploy_candidates=False,
                require_one_point=True,
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

            payload = json.loads(summary.read_text(encoding="utf-8"))

        self.assertEqual(processed, 1)
        self.assertEqual(payload["dispatch_preview"]["next_runnable"][0]["number"], 9)
        self.assertEqual(payload["dispatch_preview"]["blocked"][0]["number"], 10)
        self.assertIn("missing policy allow label", payload["dispatch_preview"]["blocked"][0]["reasons"][0])

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
