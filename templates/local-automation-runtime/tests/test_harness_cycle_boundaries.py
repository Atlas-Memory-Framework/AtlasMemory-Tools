from __future__ import annotations

from contextlib import ExitStack
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_script(name: str, filename: str):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def issue(execution_repo: str = "owner/source", labels=None) -> dict:
    return {
        "number": 7, "title": "Bounded work", "author": {"login": "trusted-user"},
        "body": f"- Execution repo: `{execution_repo}`\n", "url": "https://example.invalid/7",
        "labels": [{"name": label} for label in (labels or ["agent:ready"])],
    }


class HarnessCycleBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orchestrator = load_script("harness_boundary_orchestrator", "atlas-agent-orchestrator")
        cls.loop = load_script("harness_boundary_unattended", "atlas-agent-unattended")

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inventory = self.root / "repos.txt"
        self.inventory.write_text("owner/source\n", encoding="utf-8")
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # Building parser defaults is allowed here, with configuration mocked;
        # no real operator config or credentials are inspected by these tests.
        self.stack.enter_context(patch.object(self.loop.common, "read_config", return_value={}))
        self.stack.enter_context(patch.object(self.loop.common, "config_int", side_effect=lambda name, default: default))
        self.stack.enter_context(patch.object(self.loop.common, "config_value", side_effect=lambda name, default="": default))

    def args(self, *extra: str):
        return self.orchestrator.build_parser().parse_args([
            "--once", "--publish", "--repos-file", str(self.inventory), "--no-write-scope-locks", *extra,
        ])

    def wire_process(self, item: dict, *, failed=None) -> dict[str, Mock]:
        mocked = {}
        for name, value in {
            "ready_issues": [item], "failed_issues": failed or [], "queue_candidate_issues": [item],
            "ensure_agent_labels": None, "has_open_pr_for_issue": False,
            "acquire_issue_lease": self.root / "lease", "release_issue_lease": None,
            "release_write_scope_lease": None, "dispatch_base_branch": "main",
            "maybe_dispatch_deploy_candidate": None, "run_worker": 0, "notify_worker_result": None,
            "admin_inspect": None,
        }.items():
            mocked[name] = self.stack.enter_context(patch.object(self.orchestrator, name, return_value=value))
        mocked["provider_mutation"] = self.stack.enter_context(patch.object(self.orchestrator.common, "run"))
        mocked["state_update"] = self.stack.enter_context(patch.object(self.orchestrator.common, "update_issue_automation_state"))
        self.stack.enter_context(patch.object(self.orchestrator.common, "trusted_authors", return_value={"trusted-user"}))
        return mocked

    def test_worker_notification_default_preserved_and_explicit_optout_suppresses_hook(self) -> None:
        self.assertTrue(self.args().worker_notifications)
        for enabled in [True, False]:
            with self.subTest(enabled=enabled), ExitStack() as local:
                args = self.args(*([] if enabled else ["--no-worker-notifications"]))
                worker = local.enter_context(patch.object(self.orchestrator, "run_worker", return_value=0))
                hooks = self.wire_process(issue())
                self.assertEqual(self.orchestrator.process_once(args), 1)
                hooks["run_worker"].assert_called_once()
                self.assertEqual(hooks["notify_worker_result"].call_count, int(enabled))

    def test_unattended_real_parser_and_dispatch_forward_quiet_mode_and_whole_allowlist(self) -> None:
        args = self.loop.build_parser().parse_args([
            "--publish", "--repos-file", str(self.inventory), "--execution-targets-file", str(self.inventory),
            "--no-worker-notifications",
        ])
        commands = self.loop.build_dispatch_commands(args, self.root, "fixture", 1)
        self.assertEqual(len(commands), 1)
        command = commands[0].args
        self.assertIn("--no-worker-notifications", command)
        self.assertEqual(command[command.index("--execution-targets-file") + 1], str(self.inventory))
        self.assertNotEqual(command[command.index("--repos-file") + 1], str(self.inventory))
        parsed = self.orchestrator.build_parser().parse_args(command[1:])
        self.assertFalse(parsed.worker_notifications)
        self.assertEqual(parsed.execution_targets_file, str(self.inventory))

    def test_unattended_notification_default_keeps_legacy_orchestrator_behavior(self) -> None:
        args = self.loop.build_parser().parse_args(["--repos-file", str(self.inventory)])
        self.assertTrue(args.worker_notifications)
        commands = self.loop.build_dispatch_commands(args, self.root, "fixture", 1)
        self.assertNotIn("--no-worker-notifications", commands[0].args)
        self.assertNotIn("--execution-targets-file", commands[0].args)

    def test_cross_repo_outside_allowlist_blocks_before_queue_claim_admin_or_provider_mutation(self) -> None:
        args = self.args("--execution-targets-file", str(self.inventory), "--inspect-failed", "--auto-queue-label", "status:ready")
        item = issue("outside/private", labels=["status:ready"])
        hooks = self.wire_process(item, failed=[issue("outside/private", labels=["agent:failed"])])
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(self.orchestrator.process_once(args), 0)
        for name in ["ensure_agent_labels", "provider_mutation", "state_update", "run_worker", "acquire_issue_lease", "admin_inspect", "has_open_pr_for_issue", "notify_worker_result"]:
            hooks[name].assert_not_called()
        self.assertIn("outside the explicit execution target allowlist", output.getvalue())

    def test_explicitly_allowed_cross_repo_dispatch_proceeds(self) -> None:
        self.inventory.write_text("owner/source\nowner/target\n", encoding="utf-8")
        args = self.args("--execution-targets-file", str(self.inventory), "--no-worker-notifications")
        hooks = self.wire_process(issue("owner/target"))
        # The actual unattended shard contains only one source repository.
        self.stack.enter_context(patch.object(self.orchestrator, "target_repos", return_value=["owner/source"]))
        self.assertEqual(self.orchestrator.process_once(args), 1)
        self.assertEqual(hooks["run_worker"].call_args.args[:3], ("owner/source", "owner/target", 7))
        hooks["notify_worker_result"].assert_not_called()

    def test_absent_allowlist_preserves_existing_cross_repo_dispatch(self) -> None:
        hooks = self.wire_process(issue("outside/legacy"))
        self.assertEqual(self.orchestrator.process_once(self.args()), 1)
        self.assertEqual(hooks["run_worker"].call_args.args[1], "outside/legacy")

    def test_restricted_bulk_triage_is_read_only_before_issue_route_inspection(self) -> None:
        args = self.args("--execution-targets-file", str(self.inventory), "--triage-needs-human",
                         "--triage-apply-stale", "--triage-approve-review-before-dispatch", "--triage-comment")
        self.wire_process(issue("outside/private"))
        with patch.object(self.orchestrator.subprocess, "run") as run:
            self.assertEqual(self.orchestrator.process_once(args), 0)
        command = run.call_args.args[0]
        for flag in ["--apply-stale", "--approve-review-before-dispatch", "--clean-pause-labels", "--comment"]:
            self.assertNotIn(flag, command)

    def test_invalid_execution_inventory_fails_before_any_provider_operation(self) -> None:
        for content in ["", "owner/source #inline", "https://github.com/owner/source", "owner/source\nOWNER/SOURCE", "Instablinds/Website"]:
            with self.subTest(content=content):
                self.inventory.write_text(content, encoding="utf-8")
                args = self.args("--execution-targets-file", str(self.inventory))
                with patch.object(self.orchestrator.common, "run") as mutate, patch.object(self.orchestrator, "ready_issues") as read:
                    with self.assertRaises(ValueError):
                        self.orchestrator.process_once(args)
                    mutate.assert_not_called()
                    read.assert_not_called()

    def test_symlink_or_foreign_writable_allowlist_is_rejected(self) -> None:
        linked = self.root / "linked.txt"
        linked.symlink_to(self.inventory)
        with self.assertRaises(ValueError):
            self.orchestrator.execution_targets(self.args("--execution-targets-file", str(linked)))
        self.inventory.chmod(0o666)
        with self.assertRaises(ValueError):
            self.orchestrator.execution_targets(self.args("--execution-targets-file", str(self.inventory)))

    def test_merged_parser_preserves_both_interfaces_without_mixing_bounded_authority(self) -> None:
        argv = [
            "--atlas-bounded", "--atlas-work-items", str(self.root / "queue.json"),
            "--atlas-role-command-config", str(self.root / "roles.json"),
            "--atlas-cycle-pins", str(self.root / "pins.json"),
            "--atlas-max-steps", "1", "--atlas-max-claims", "1", "--atlas-max-roles", "1",
            "--atlas-role-max", "1", "--atlas-cycle-seconds", "10",
            "--atlas-worker-timeout-seconds", "5", "--atlas-worker-termination-grace-seconds", "0.1",
            "--atlas-stop-file", str(self.root / "stop"),
        ]
        parser = self.orchestrator.build_parser()
        local = parser.parse_args(argv)
        self.assertTrue(local.atlas_bounded)
        self.assertEqual(local.atlas_max_steps, 1)
        self.assertTrue(local.worker_notifications)
        for extra in [["--execution-targets-file", str(self.inventory)], ["--no-worker-notifications"]]:
            with self.subTest(extra=extra):
                mixed = argv + extra
                args = parser.parse_args(mixed)
                with patch.object(self.orchestrator, "_cycle_guard_read", side_effect=AssertionError("mixed mode must refuse before source reads")), \
                        patch.object(self.orchestrator, "process_once", side_effect=AssertionError("mixed mode must not enter legacy dispatch")), \
                        self.assertRaisesRegex(ValueError, "forbids legacy/mixed modes"):
                    self.orchestrator._run_bounded_cli(args, mixed)

    def test_merged_main_keeps_ordinary_once_routing(self) -> None:
        with patch.object(sys, "argv", ["atlas-agent-orchestrator", "--once", "--no-worker-notifications"]), \
                patch.object(self.orchestrator, "process_once", return_value=0) as ordinary, \
                patch.object(self.orchestrator, "_run_bounded_cli", side_effect=AssertionError("ordinary mode cannot enter bounded supervisor")):
            self.orchestrator.main()
        ordinary.assert_called_once()
        self.assertFalse(ordinary.call_args.args[0].worker_notifications)


if __name__ == "__main__":
    unittest.main()
