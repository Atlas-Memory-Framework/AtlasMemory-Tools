from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


RUNTIME = Path(__file__).resolve().parents[1]
TOOLS = RUNTIME.parents[1]
sys.path.insert(0, str(RUNTIME))
import atlas_runtime_config as config


spec = importlib.util.spec_from_file_location("runtime_control_azure_tests", TOOLS / "scripts" / "runtime_control.py")
control = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = control
spec.loader.exec_module(control)


class AzureRuntimeControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.runtime = self.home / "runtime"
        self.runtime.mkdir()
        for name in ("atlas-agent-azure-inspect", "atlas-agent-azure-worker", "atlas-agent-azure-reconcile", "atlas-agent-azure-dispatch",
                     "atlas-agent-azure-supervise", "atlas-agent-azure-intake", "atlas-agent-azure-approval",
                     "atlas-agent-plan-queue", "atlas-agent-unattended", "atlas-agent-shift", "atlas-agent-review",
                     "atlas-agent-finalize", "check_runtime.sh"):
            (self.runtime / name).write_text("fixture only\n", encoding="utf-8")
        (self.runtime / "repos.txt").write_text("other/repo\n", encoding="utf-8")
        self.config = self.home / "azure.json"
        self.config.write_text((RUNTIME.parents[1] / "examples" / "instablinds" / "local-automation-runtime" / "config" / "azure-website.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.identity = mock.patch.object(config.pwd, "getpwuid", return_value=types.SimpleNamespace(pw_dir=str(self.home)))
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.environment = mock.patch.dict(os.environ, {"ATLAS_RUNTIME_DIR": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def invoke(self, arguments: list[str], *, azure: bool = True, child_returncode: int = 0):
        prefix = ["--runtime-dir", str(self.runtime)]
        prefix += ["--config", str(self.config)] if azure else ["--provider", "github"]
        output = io.StringIO()
        with mock.patch.object(control.subprocess, "run", return_value=types.SimpleNamespace(returncode=child_returncode)) as run:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                result = control.main(prefix + arguments)
        return result, output.getvalue(), run

    def test_status_reports_models_and_does_not_run_checks_or_sync(self) -> None:
        before = {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        result, output, run = self.invoke(["status", "--check"])
        self.assertEqual(result, 0, output)
        run.assert_not_called()
        self.assertIn('"provider": "azure-devops"', output)
        self.assertIn('"model": "gpt-6-astra"', output)
        self.assertIn('"reasoning": "max"', output)
        self.assertEqual(before, {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()})

    def test_all_azure_previews_are_inert_even_if_effect_flags_are_present(self) -> None:
        for args in (["azure-inspect", "--ids", "17,18", "--live-read", "--dry-run"],
                     ["azure-worker", "--packet", "packet.json"],
                     ["azure-worker", "--packet", "packet.json", "--execute", "--authorization", "auth.json", "--dry-run"],
                     ["azure-reconcile", "--packet", "packet.json"],
                     ["azure-reconcile", "--packet", "packet.json", "--apply", "--authorize-packet-sha256", "a" * 64, "--dry-run"],
                     ["sync"], ["sync", "--apply", "--yes", "--dry-run"]):
            with self.subTest(args=args):
                result, output, run = self.invoke(list(args))
                self.assertEqual(result, 0, output)
                self.assertIn('"dispatched": false', output)
                run.assert_not_called()

    def test_azure_inspection_routes_to_one_azure_command_without_sync(self) -> None:
        result, output, run = self.invoke(["azure-inspect", "--ids", "17,18", "--snapshot", "snapshot.json"])
        self.assertEqual(result, 0, output)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[0], str(self.runtime / "atlas-agent-azure-inspect"))
        self.assertIn("--snapshot", command)
        self.assertNotIn("sync_runtime_template.py", str(command))
        self.assertNotIn("--live-read", command)

    def test_azure_cannot_route_into_github_merge_or_unattended_operations(self) -> None:
        for args in (["run-once", "--yes", "--merge"], ["finalize", "--yes", "--merge"],
                     ["queue", "--plan", "plan.md", "--repo", "other/repo", "--yes"],
                     ["shift", "--yes"], ["review", "--apply", "--yes"]):
            with self.subTest(args=args):
                result, output, run = self.invoke(list(args))
                self.assertEqual(result, 2, output)
                self.assertIn("no GitHub fallback", output)
                run.assert_not_called()

    def test_provider_mismatch_unknown_or_missing_location_cannot_dispatch(self) -> None:
        result, output, run = self.invoke(["--provider", "github", "azure-inspect", "--ids", "17"])
        self.assertEqual(result, 2, output)
        run.assert_not_called()
        with mock.patch.object(control.subprocess, "run") as run, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(control.main(["--provider", "github", "status"]), 2)
            self.assertEqual(control.main(["--runtime-dir", str(self.runtime), "status"]), 2)
        run.assert_not_called()

    def test_execution_and_publication_need_different_explicit_action_and_authorization(self) -> None:
        for action in ("--execute", "--publish"):
            result, output, run = self.invoke(["azure-worker", "--packet", "packet.json", action])
            self.assertEqual(result, 2, output)
            run.assert_not_called()
            result, output, run = self.invoke(["azure-worker", "--packet", "packet.json", action, "--authorization", "auth.json"])
            self.assertEqual(result, 0, output)
            run.assert_called_once()
            self.assertIn(action, run.call_args.args[0])
            self.assertNotIn("--execute" if action == "--publish" else "--publish", run.call_args.args[0])

    def test_github_other_repositories_remain_explicit_and_never_autosync(self) -> None:
        result, output, run = self.invoke(["run-once", "--yes", "--no-review-apply", "--no-post-cycle-summary"], azure=False)
        self.assertEqual(result, 0, output)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][0], str(self.runtime / "atlas-agent-unattended"))
        result, output, run = self.invoke(["run-once", "--no-review-apply", "--no-post-cycle-summary"], azure=False)
        self.assertEqual(result, 2, output)
        run.assert_not_called()

    def test_github_previews_do_not_execute_legacy_commands(self) -> None:
        for args in (["plan-preview", "--plan", "plan.md", "--repo", "other/repo"],
                     ["dry-cycle", "--review-apply"], ["review"], ["finalize"],
                     ["run-once", "--publish", "--dry-run"], ["status", "--check"]):
            with self.subTest(args=args):
                result, output, run = self.invoke(list(args), azure=False)
                self.assertEqual(result, 0, output)
                run.assert_not_called()

    def test_azure_targets_and_website_archive_are_denied_in_github_inputs(self) -> None:
        for target in ("azdo:Instablinds:Instablinds:17", "https://dev.azure.com/Instablinds/Instablinds/_git/Website",
                       "Instablinds/Website", "/INSTABLINDS/WEBSITE.git/", "https://github.com/Instablinds/Website.git"):
            with self.subTest(target=target):
                result, output, run = self.invoke(["plan-preview", "--plan", "plan.md", "--repo", target], azure=False)
                self.assertEqual(result, 2, output)
                run.assert_not_called()
                (self.runtime / "repos.txt").write_text(target + "\n", encoding="utf-8")
                result, output, run = self.invoke(["run-once", "--yes"], azure=False)
                self.assertEqual(result, 2, output)
                run.assert_not_called()

    def test_missing_scripts_or_symlink_escape_never_reports_preview_success(self) -> None:
        (self.runtime / "atlas-agent-azure-worker").unlink()
        result, output, run = self.invoke(["azure-worker", "--packet", "packet.json"])
        self.assertEqual(result, 2, output)
        run.assert_not_called()
        outside = self.home / "external-script"
        outside.write_text("outside runtime", encoding="utf-8")
        (self.runtime / "atlas-agent-azure-worker").symlink_to(outside)
        result, output, run = self.invoke(["azure-worker", "--packet", "packet.json"])
        self.assertEqual(result, 2, output)
        run.assert_not_called()

    def test_explicit_sync_requires_confirmation_and_never_happens_on_status(self) -> None:
        result, output, run = self.invoke(["sync", "--apply"])
        self.assertEqual(result, 2, output)
        run.assert_not_called()
        result, output, run = self.invoke(["sync", "--apply", "--yes"])
        self.assertEqual(result, 0, output)
        run.assert_called_once()
        self.assertTrue(run.call_args.args[0][1].endswith("sync_runtime_template.py"))

    def test_ordinary_preview_process_does_not_create_bytecode_or_runtime_state(self) -> None:
        # Copy only the wrapper and config module into an isolated source tree.
        # No -B or PYTHONDONTWRITEBYTECODE protects this process: the CLI must.
        source = self.home / "source"
        scripts = source / "scripts"
        template = source / "templates" / "local-automation-runtime"
        scripts.mkdir(parents=True)
        template.mkdir(parents=True)
        script = scripts / "runtime_control.py"
        script.write_bytes((TOOLS / "scripts" / "runtime_control.py").read_bytes())
        (template / "atlas_runtime_config.py").write_bytes((RUNTIME / "atlas_runtime_config.py").read_bytes())
        before = {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        environment = {k: v for k, v in os.environ.items() if k not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPATH", "PYTHONPYCACHEPREFIX", "ATLAS_RUNTIME_DIR"}}
        # An omitted runtime is a blocked inert preview, before any child launch.
        result = subprocess.run([sys.executable, str(script), "--provider", "github", "dry-cycle"],
                                text=True, capture_output=True, env=environment, cwd=source)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        # Run a successful preview with only passwd lookup adapted to this temp
        # identity; the CLI parser/import path and child-process boundary are real.
        launcher = ("import pwd,sys,types,runpy; fixture_home=sys.argv.pop(1); "
                    "pwd.getpwuid=lambda uid: types.SimpleNamespace(pw_dir=fixture_home); "
                    "runpy.run_path(sys.argv.pop(1), run_name='__main__')")
        result = subprocess.run([sys.executable, "-c", launcher, str(self.home), str(script),
                                 "--runtime-dir", str(self.runtime), "--provider", "github", "dry-cycle"],
                                text=True, capture_output=True, env=environment, cwd=source)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"dispatched": false', result.stdout)
        after = {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(list(source.rglob("__pycache__")))

    def dispatch_args(self):
        return ["azure-dispatch", "--policy", "policy.json", "--intake", "intake.json", "--snapshot", "snapshot.json"]

    def test_dispatch_modes_and_supplied_model_recommendations_are_inert_in_preview(self):
        for extra in ([], ["--assess", "--dry-run"], ["--execute", "--dry-run"],
                      ["--check-handoff", "--handoff-action", "completion", "--dry-run"],
                      ["--assessment", "assessment.json", "--challenge", "challenge.json"]):
            with self.subTest(extra=extra):
                result, output, run = self.invoke(self.dispatch_args() + extra)
                self.assertEqual(result, 0, output)
                self.assertIn('"dispatched": false', output)
                run.assert_not_called()

    def test_dispatch_requires_separate_signed_envelope_and_existing_entrypoint(self):
        for action in ("--assess", "--execute"):
            result, output, run = self.invoke(self.dispatch_args() + [action])
            self.assertEqual(result, 2, output)
            run.assert_not_called()
            result, output, run = self.invoke(self.dispatch_args() + [action, "--authorization", "grant.json"])
            self.assertEqual(result, 0, output)
            self.assertIn(action, run.call_args.args[0])
        (self.runtime / "atlas-agent-azure-dispatch").unlink()
        result, output, run = self.invoke(self.dispatch_args())
        self.assertEqual(result, 2, output)
        run.assert_not_called()

    def test_worker_routing_human_receipts_and_handoff_flags_forward_exactly(self):
        result, output, run = self.invoke(["azure-worker", "--packet", "packet.json", "--execute", "--authorization", "grant.json",
            "--routing", "routing.json", "--human-receipts", "receipts.json"])
        self.assertEqual(result, 0, output)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--routing") + 1], str(Path("routing.json").resolve()))
        self.assertEqual(command[command.index("--human-receipts") + 1], str(Path("receipts.json").resolve()))
        result, output, run = self.invoke(self.dispatch_args() + ["--check-handoff", "--human-receipts", "receipts.json",
            "--handoff-stage", "after", "--handoff-action", "completion"])
        self.assertEqual(result, 0, output)
        command = run.call_args.args[0]
        self.assertIn("--check-handoff", command)
        self.assertEqual(command[command.index("--handoff-stage") + 1], "after")
        self.assertEqual(command[command.index("--handoff-action") + 1], "completion")

    def test_reconciliation_forwards_new_signed_authority_and_requires_it_for_apply(self):
        args = ["azure-reconcile", "--packet", "packet.json", "--apply", "--authorize-packet-sha256", "a" * 64]
        result, output, run = self.invoke(args)
        self.assertEqual(result, 2, output)
        run.assert_not_called()
        result, output, run = self.invoke(args + ["--authorization", "grant.json"])
        self.assertEqual(result, 0, output)
        self.assertIn("--authorization", run.call_args.args[0])

    def supervise_args(self):
        return ["azure-supervise", "--queue", "queue.json", "--policy", "policy.json"]

    def intake_args(self):
        return ["azure-intake", "--policy", "policy.json", "--definition", "definition.json", "--context-root", "source"]

    def approval_args(self):
        return ["azure-approval", "--request", "request.json"]

    def test_new_supervisor_intake_and_approval_defaults_are_inert(self):
        before = {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        for args in (self.supervise_args(), self.intake_args(), self.approval_args(),
                     self.approval_args() + ["--decision", "accepted", "--response-text", "I accept this candidate."]):
            with self.subTest(command=args[0]):
                result, output, run = self.invoke(args)
                self.assertEqual(result, 0, output)
                preview = json.loads(output)
                self.assertFalse(preview["dispatched"])
                self.assertFalse(preview["completion"])
                self.assertIn("--dry-run", preview["argv"])
                self.assertNotIn("--operator-issue", preview["argv"])
                run.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in self.home.rglob("*") if p.is_file()})

    def test_explicit_dry_run_suppresses_every_new_effect_mode(self):
        operations = [self.supervise_args() + ["--observe"], self.supervise_args() + ["--run"],
                      self.intake_args() + ["--live-read"], self.approval_args() + ["--prepare"],
                      self.approval_args() + ["--export"], self.approval_args() + ["--reopen"],
                      self.approval_args() + ["--import-response", "signed-response.json"],
                      self.approval_args() + ["--operator-issue", "--decision", "accepted", "--response-file", "human-answer.txt"]]
        for args in operations:
            with self.subTest(args=args):
                result, output, run = self.invoke(args + ["--dry-run"])
                self.assertEqual(result, 0, output)
                self.assertFalse(json.loads(output)["dispatched"])
                run.assert_not_called()

    def test_supervisor_modes_have_bounded_defaults_and_no_hidden_child_authority(self):
        for action in ("--observe", "--run"):
            result, output, run = self.invoke(self.supervise_args() + [action])
            self.assertEqual(result, 0, output)
            run.assert_called_once()
            argv = run.call_args.args[0]
            self.assertEqual(argv[0], str(self.runtime / "atlas-agent-azure-supervise"))
            for flag, expected in (("--max-cycles", "1"), ("--max-items", "1"), ("--max-seconds", "60")):
                self.assertEqual(argv[argv.index(flag) + 1], expected)
            self.assertIn(action, argv)
            self.assertFalse({"--yes", "--merge", "--full-auto", "--approve", "--authorize", "--publish"} & set(argv))
            self.assertNotIn('"completion": true', output)

    def test_intake_forwards_explicit_sources_without_model_or_write_flags(self):
        result, output, run = self.invoke(self.intake_args() + ["--live-read", "--snapshot", "snapshot.json", "--previous", "previous.json"])
        self.assertEqual(result, 0, output)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], str(self.runtime / "atlas-agent-azure-intake"))
        for flag, value in (("--definition", "definition.json"), ("--context-root", "source"), ("--previous", "previous.json")):
            self.assertEqual(argv[argv.index(flag) + 1], str(Path(value).resolve()))
        self.assertIn("--live-read", argv)
        self.assertFalse({"--assess", "--execute", "--apply", "--publish", "--model"} & set(argv))

    def test_approval_modes_forward_explicit_intent_without_signing_or_enrollment(self):
        for flags in (["--prepare"], ["--export"], ["--reopen"], ["--import-response", "signed-response.json"],
                      ["--operator-issue", "--decision", "feedback", "--response-text", "Use the quieter fabric."]):
            with self.subTest(flags=flags):
                result, output, run = self.invoke(self.approval_args() + flags)
                self.assertEqual(result, 0, output)
                argv = run.call_args.args[0]
                self.assertEqual(argv[0], str(self.runtime / "atlas-agent-azure-approval"))
                self.assertIn(flags[0], argv)
                self.assertFalse({"--private-key", "--enroll", "--install", "--yes", "--approve"} & set(argv))
                self.assertNotIn('"completion": true', output)

    def test_new_modes_propagate_blocked_child_exit_without_claiming_completion(self):
        for args in (self.supervise_args() + ["--run"], self.intake_args() + ["--live-read"],
                     self.approval_args() + ["--import-response", "untrusted-response.json"]):
            with self.subTest(args=args):
                result, output, run = self.invoke(args, child_returncode=7)
                self.assertEqual(result, 7, output)
                run.assert_called_once()
                self.assertNotIn('"completion": true', output)

    def test_new_commands_never_fall_back_to_github_or_missing_entrypoints(self):
        for args in (self.supervise_args(), self.intake_args(), self.approval_args()):
            with self.subTest(args=args):
                result, output, run = self.invoke(args, azure=False)
                self.assertEqual(result, 2, output)
                run.assert_not_called()
                name = {"azure-supervise": "atlas-agent-azure-supervise", "azure-intake": "atlas-agent-azure-intake",
                        "azure-approval": "atlas-agent-azure-approval"}[args[0]]
                (self.runtime / name).unlink()
                result, output, run = self.invoke(args)
                self.assertEqual(result, 2, output)
                self.assertIn("missing runtime script", output)
                run.assert_not_called()

    def test_invalid_bounds_conflicting_modes_and_prohibited_flags_never_invoke_children(self):
        cases = [self.supervise_args() + ["--max-cycles", "0"], self.supervise_args() + ["--observe", "--run"],
                 self.supervise_args() + ["--merge"], self.intake_args() + ["--execute"],
                 self.approval_args() + ["--private-key", "forbidden.pem"],
                 self.approval_args() + ["--prepare", "--operator-issue"],
                 self.approval_args() + ["--reopen", "--operator-issue"],
                 self.approval_args() + ["--request-id", "another-request"]]
        for args in cases:
            with self.subTest(args=args), mock.patch.object(control.subprocess, "run") as run, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    control.main(["--runtime-dir", str(self.runtime), "--config", str(self.config), *args])
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
