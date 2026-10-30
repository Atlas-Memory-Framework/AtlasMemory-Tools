from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import harness_remotes as remotes
import atlas_runtime_config as runtime_config
from harness_service import HarnessService, HarnessServiceError


class HarnessRemoteConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.identity = patch.object(remotes.pwd, "getpwuid", return_value=SimpleNamespace(pw_dir=str(self.home)))
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.registry = self.home / ".config" / "atlasmemory-tools" / "harness.json"
        self.service = HarnessService(registry=self.registry)
        self.api = remotes.HarnessRemotes(self.service)
        self.url = "https://dev.azure.com/ExampleOrg/Example%20Project/_git/Example%20Repo"

    def configure(self, **options):
        values = {"remote_id": "example", "provider": "azure-devops", "repository_url": self.url,
                  "base_branch": "main"}
        values.update(options)
        return self.api.configure(**values)

    def files(self):
        return {str(path.relative_to(self.home)): (path.stat().st_mode, path.read_bytes())
                for path in self.home.rglob("*") if path.is_file()}

    def test_preview_creates_no_directories_files_network_or_workers(self):
        before = sorted(self.home.rglob("*"))
        with patch("subprocess.Popen", side_effect=AssertionError("no worker")), \
                patch("socket.create_connection", side_effect=AssertionError("no network")):
            result = self.configure()
        self.assertTrue(result["read_only"])
        self.assertTrue(result["changed"])
        self.assertFalse(result["runtime_code_ready"])
        self.assertTrue(result["runtime_code_ready_after_apply"])
        self.assertEqual(sorted(self.home.rglob("*")), before)
        self.assertEqual(result["capabilities"], ["read"])

    def test_apply_registers_pinned_runtime_and_is_idempotent(self):
        result = self.configure(apply=True)
        self.assertGreater(result["applied"], 10)
        self.assertTrue(result["runtime_code_ready"])
        runtime = Path(result["runtime_dir"])
        self.assertTrue((runtime / "atlas-agent-azure-inspect").is_file())
        self.assertTrue((runtime / "team-templates").is_dir())
        self.assertFalse((runtime / "config.env").exists())
        self.assertFalse((runtime / "codex-home").exists())
        self.assertTrue((runtime / remotes.MARKER).is_file())
        profile = json.loads(Path(result["profile"]).read_text())
        self.assertEqual(profile["repository"]["project"], "Example Project")
        self.assertEqual(profile["repository"]["name"], "Example Repo")
        self.assertNotIn("models", profile)
        self.assertEqual(profile["capabilities"], ["read"])
        self.assertEqual(stat.S_IMODE(Path(result["profile"]).stat().st_mode), 0o600)
        self.assertEqual(runtime_config.load_runtime_config(result["profile"]).report()["models"], {})
        self.assertTrue(self.service.discover()["runtimes"][0]["available"])
        before = self.files()
        again = self.configure(apply=True)
        self.assertEqual(again["applied"], 0)
        self.assertIsNone(again["receipt"])
        self.assertEqual(self.files(), before)

    def test_preserves_other_registered_remotes_and_unrelated_state(self):
        self.registry.parent.mkdir(parents=True)
        other = {"id": "other", "provider": "github", "runtime_dir": str(self.home / "other-runtime")}
        self.registry.write_text(json.dumps({"version": 1, "runtimes": [other],
                                             "installations": [{"target": str(self.home), "harness": "codex"}]}))
        sentinel = self.home / "unrelated.txt"
        sentinel.write_text("keep this\n")
        self.configure(apply=True)
        after = json.loads(self.registry.read_text())
        self.assertEqual(after["runtimes"][0], other)
        self.assertEqual(after["installations"], [{"target": str(self.home), "harness": "codex"}])
        self.assertEqual(sentinel.read_text(), "keep this\n")

    def test_existing_selected_runtime_is_never_overwritten(self):
        runtime = self.home / "existing"
        runtime.mkdir()
        existing = runtime / "atlas-agent-azure-inspect"
        existing.write_text("# locally maintained\n")
        (runtime / "config.env").write_text("DO_NOT_READ=sentinel\n")
        result = self.configure(runtime_dir=str(runtime), apply=True)
        self.assertFalse(result["runtime_code_ready"])
        self.assertEqual(existing.read_text(), "# locally maintained\n")
        self.assertEqual((runtime / "config.env").read_text(), "DO_NOT_READ=sentinel\n")
        self.assertEqual({p.name for p in runtime.iterdir()}, {"atlas-agent-azure-inspect", "config.env"})

    def test_duplicate_id_retarget_and_profile_edits_are_conflicts(self):
        result = self.configure(apply=True)
        before = self.files()
        with self.assertRaises(HarnessServiceError):
            self.configure(repository_url="https://dev.azure.com/ExampleOrg/Example%20Project/_git/Different", apply=True)
        self.assertEqual(self.files(), before)
        profile = Path(result["profile"])
        profile.write_text(profile.read_text() + "\n")
        modified = json.loads(profile.read_text())
        modified["capabilities"] = ["read", "board_write"]
        profile.write_text(json.dumps(modified))
        before = self.files()
        with self.assertRaises(HarnessServiceError):
            self.configure(apply=True)
        self.assertEqual(self.files(), before)

    def test_existing_unregistered_managed_directory_is_preserved(self):
        runtime = self.home / ".local" / "share" / "atlasmemory-tools" / "remotes" / "example" / "runtime"
        runtime.mkdir(parents=True)
        sentinel = runtime / "jobs.txt"
        sentinel.write_text("existing\n")
        before = self.files()
        with self.assertRaises(HarnessServiceError):
            self.configure(apply=True)
        self.assertEqual(self.files(), before)

    def test_project_url_requires_repo_and_branch_without_side_effects(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                before = sorted(self.home.rglob("*"))
                result = self.configure(repository_url="https://dev.azure.com/ExampleOrg/Example%20Project",
                                        base_branch=None, apply=apply)
                self.assertEqual(result["status"], "needs_selection")
                self.assertEqual(result["required_fields"], ["repository_name", "base_branch"])
                self.assertTrue(result["read_only"])
                self.assertFalse(result["applied"])
                self.assertEqual(sorted(self.home.rglob("*")), before)
        result = self.configure(repository_url="https://dev.azure.com/ExampleOrg/Example%20Project",
                                repository_name="Chosen Repo")
        self.assertEqual(result["repository"]["name"], "Chosen Repo")
        self.assertIn("/_git/Chosen%20Repo", result["repository"]["url"])

    def test_full_repository_url_without_branch_never_infers_default(self):
        result = self.configure(base_branch=None, apply=True)
        self.assertEqual(result["required_fields"], ["base_branch"])
        self.assertEqual(result["next_actions"][0]["operation"], "inspect_azure_repository")
        self.assertEqual(sorted(self.home.rglob("*")), [])

    def test_repo_name_conflicts_and_unsafe_urls_are_rejected(self):
        urls = ["https://secret@dev.azure.com/ExampleOrg/Project/_git/Repo",
                "https://dev.azure.com/ExampleOrg/Project/_git/Repo?token=secret",
                "https://dev.azure.com/ExampleOrg/Project/_git/Repo#part",
                "https://example.visualstudio.com/Project/_git/Repo",
                "https://dev.azure.com:443/ExampleOrg/Project/_git/Repo",
                "https://dev.azure.com/ExampleOrg/Project/_git/%2FRepo",
                "https://dev.azure.com/ExampleOrg/Project/_git/%2e%2e",
                "https://github.com/example/repo"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(HarnessServiceError):
                self.configure(repository_url=url, apply=True)
        with self.assertRaises(HarnessServiceError):
            self.configure(repository_name="Wrong")
        self.assertEqual(sorted(self.home.rglob("*")), [])

    def test_symlink_hardlink_and_foreign_writable_paths_are_rejected(self):
        root = self.home / ".config" / "atlasmemory-tools"
        root.mkdir(parents=True)
        outside = self.home / "other"
        outside.mkdir()
        (root / "remotes").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HarnessServiceError):
            self.configure()
        (root / "remotes").unlink()
        root.chmod(0o777)
        with self.assertRaises(HarnessServiceError):
            self.configure()
        root.chmod(0o700)
        original = self.home / "original.json"
        original.write_text('{"version":1,"runtimes":[]}')
        os.link(original, self.registry)
        with self.assertRaises(HarnessServiceError):
            self.configure()

    def test_rejects_source_template_outside_identity_and_unknown_provider(self):
        for values in ({"runtime_dir": str(ROOT / "templates/local-automation-runtime")},
                       {"runtime_dir": "/tmp/unselected-runtime"}, {"provider": "github"},
                       {"remote_id": "../other"}):
            with self.subTest(values=values), self.assertRaises(HarnessServiceError):
                self.configure(**values)
        self.assertEqual(sorted(self.home.rglob("*")), [])

    def test_explicit_models_preserved_but_do_not_enable_effect_capabilities(self):
        models = {"default": {"model": "selected-model", "reasoning": "high"}}
        result = self.configure(models=models, apply=True)
        profile = json.loads(Path(result["profile"]).read_text())
        self.assertEqual(profile["models"], models)
        self.assertEqual(profile["capabilities"], ["read"])
        self.assertEqual(runtime_config.load_runtime_config(result["profile"]).roles["review"].model, "selected-model")
        for models in ({}, {"default": {"model": "test", "reasoning": "high", "token": "secret"}}):
            with self.subTest(models=models), self.assertRaises(HarnessServiceError):
                self.configure(remote_id="other", models=models)

    def test_effect_capabilities_are_explicit_and_require_models_without_granting_authority(self):
        for capabilities in (["read", "local_execute"], ["read", "draft_pr"], ["read", "assess"]):
            with self.subTest(capabilities=capabilities), self.assertRaises(HarnessServiceError):
                self.configure(capabilities=capabilities)
        result = self.configure(capabilities=["read", "board_write"], apply=True)
        profile = json.loads(Path(result["profile"]).read_text())
        self.assertEqual(profile["capabilities"], ["board_write", "read"])
        self.assertNotIn("models", profile)
        self.assertEqual(runtime_config.load_runtime_config(result["profile"]).roles, {})
        self.assertIn("grants no", result["cloud_authority"])
        for capabilities in (["read", "merge"], ["read", "read"], [], ["local_execute"]):
            with self.subTest(capabilities=capabilities), self.assertRaises(HarnessServiceError):
                self.configure(remote_id="other", capabilities=capabilities)

    def worker_update(self):
        installed = self.configure(apply=True)
        workspace = Path(installed["runtime_dir"]) / "worktrees" / "task-one"
        workspace.mkdir(parents=True)
        options = {"capabilities": ["read", "local_execute", "draft_pr"],
                   "models": {"default": {"model": "explicit-model", "reasoning": "high"}},
                   "checkout": str(workspace), "base_branch": None}
        return installed, workspace, options

    def test_reviewed_profile_update_adds_models_capabilities_and_selected_checkout(self):
        installed, workspace, options = self.worker_update()
        runtime = Path(installed["runtime_dir"])
        marker_before = (runtime / remotes.MARKER).read_bytes()
        jobs = runtime / "jobs"
        jobs.mkdir()
        history = jobs / "preserved.json"
        history.write_text('{"historical":true}\n')
        preview = self.configure(**options)
        self.assertTrue(preview["requires_expected_profile_sha256"])
        self.assertEqual(preview["repository"]["base_branch"], "main")
        self.assertEqual(preview["repository"]["checkout"], str(workspace))
        self.assertEqual([item["category"] for item in preview["changed"]], ["remote_profile"])
        before = self.files()
        with self.assertRaises(HarnessServiceError) as caught:
            self.configure(**options, apply=True)
        self.assertEqual(caught.exception.code, "profile_update_requires_review")
        self.assertEqual(self.files(), before)
        result = self.configure(**options, expected_profile_sha256=preview["current_profile_sha256"], apply=True)
        self.assertEqual(result["applied"], 1)
        loaded = runtime_config.load_runtime_config(result["profile"])
        self.assertEqual(loaded.repository["checkout"], str(workspace))
        self.assertEqual(loaded.roles["implementation"].model, "explicit-model")
        self.assertEqual((runtime / remotes.MARKER).read_bytes(), marker_before)
        self.assertEqual(history.read_text(), '{"historical":true}\n')
        restored = self.api.rollback(result["receipt"], apply=True)
        self.assertFalse(restored["conflicts"])
        self.assertEqual(runtime_config.load_runtime_config(result["profile"]).capabilities, frozenset({"read"}))
        self.assertTrue(workspace.exists())
        self.assertTrue(history.exists())

    def test_omitted_optional_settings_preserve_models_capabilities_branch_checkout_and_runtime(self):
        installed, workspace, options = self.worker_update()
        preview = self.configure(**options)
        self.configure(**options, expected_profile_sha256=preview["current_profile_sha256"], apply=True)
        before = self.files()
        result = self.configure(repository_url="https://dev.azure.com/ExampleOrg/Example%20Project",
                                base_branch=None, apply=True)
        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["repository"]["name"], "Example Repo")
        self.assertEqual(result["repository"]["base_branch"], "main")
        self.assertEqual(result["repository"]["checkout"], str(workspace))
        self.assertEqual(result["models"], options["models"])
        self.assertEqual(result["runtime_dir"], installed["runtime_dir"])
        self.assertEqual(self.files(), before)

    def test_stale_profile_update_hash_cannot_overwrite_or_retarget(self):
        installed = self.configure(apply=True)
        preview = self.configure(base_branch="release")
        profile = Path(installed["profile"])
        profile.write_text(profile.read_text() + "\n")
        before = self.files()
        with self.assertRaises(HarnessServiceError) as caught:
            self.configure(base_branch="release", expected_profile_sha256=preview["current_profile_sha256"], apply=True)
        self.assertEqual(caught.exception.code, "stale_remote_profile")
        self.assertEqual(self.files(), before)
        current = self.configure(base_branch=None)["current_profile_sha256"]
        with self.assertRaises(HarnessServiceError) as caught:
            self.configure(repository_url="https://dev.azure.com/DifferentOrg/Project/_git/Repo",
                           expected_profile_sha256=current, apply=True)
        self.assertEqual(caught.exception.code, "remote_conflict")
        self.assertEqual(self.files(), before)

    def test_worker_configuration_requires_existing_owned_workspace_below_worktrees(self):
        installed = self.configure(apply=True)
        options = {"capabilities": ["read", "local_execute"],
                   "models": {"default": {"model": "explicit-model", "reasoning": "high"}}}
        before = self.files()
        incomplete = self.configure(**options, apply=True)
        self.assertEqual(incomplete["status"], "needs_selection")
        self.assertEqual(incomplete["required_fields"], ["checkout"])
        self.assertEqual(self.files(), before)
        runtime = Path(installed["runtime_dir"])
        (runtime / "worktrees").mkdir()
        outside = self.home / "outside-worktree"
        outside.mkdir()
        (runtime / "worktrees" / "linked").symlink_to(outside, target_is_directory=True)
        for checkout in (runtime, runtime / "worktrees", outside, runtime / "worktrees/missing", runtime / "worktrees/linked"):
            with self.subTest(checkout=checkout), self.assertRaises(HarnessServiceError):
                self.configure(**options, checkout=str(checkout))

    def discovery(self, rows=None, code=None):
        (self.home / ".azure").mkdir(exist_ok=True)
        rows = rows if rows is not None else [{"name": "Choice One", "default_branch": "refs/heads/main",
                                               "id": "fixed-id", "url": "https://benign-user@dev.azure.com/ExampleOrg/Example%20Project/_git/Choice%20One"}]
        original = subprocess.Popen
        calls = []
        def fake_cli(argv, **kwargs):
            calls.append((argv, kwargs))
            program = code if code is not None else "print(" + repr(json.dumps(rows)) + ")"
            return original([sys.executable, "-c", program], **kwargs)
        with patch.dict(os.environ, {}, clear=True), patch.object(remotes.subprocess, "Popen", side_effect=fake_cli):
            result = self.api.repositories("https://dev.azure.com/ExampleOrg/Example%20Project")
        return result, calls

    def test_repository_discovery_uses_get_only_and_returns_sanitized_choices_without_selecting(self):
        result, calls = self.discovery()
        self.assertTrue(result["read_only"])
        self.assertIsNone(result["selected_repository"])
        self.assertEqual(result["repositories"][0]["url"], "https://dev.azure.com/ExampleOrg/Example%20Project/_git/Choice%20One")
        self.assertEqual(result["repositories"][0]["base_branch"], "main")
        self.assertNotIn("benign-user", json.dumps(result))
        argv, kwargs = calls[0]
        self.assertEqual(argv[:4], ["az", "rest", "--method", "get"])
        self.assertEqual(argv[argv.index("--resource") + 1], "499b84ac-1321-427f-aa17-267ca6975798")
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(kwargs["env"]["AZURE_EXTENSION_USE_DYNAMIC_INSTALL"], "no")
        self.assertFalse(self.registry.exists())

    def test_repository_discovery_failure_and_oversized_output_never_return_raw_cli_text(self):
        with self.assertRaises(HarnessServiceError) as caught:
            self.discovery(code="import sys;sys.stderr.write('PRIVATE_SENTINEL');sys.exit(2)")
        self.assertEqual(caught.exception.code, "azure_read_failed")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(caught.exception.as_dict()))
        with self.assertRaises(HarnessServiceError) as caught:
            self.discovery(code="print('x'*300000)")
        self.assertEqual(caught.exception.code, "azure_read_too_large")

    def test_repository_discovery_timeout_and_malformed_metadata_are_bounded(self):
        with patch.object(remotes, "DISCOVERY_TIMEOUT", 0.1), self.assertRaises(HarnessServiceError) as caught:
            self.discovery(code="import time;time.sleep(10)")
        self.assertEqual(caught.exception.code, "azure_read_timeout")
        for rows in ({"unexpected": []}, [{"name": "../outside", "default_branch": "refs/heads/main"}],
                     [{"name": "same", "default_branch": "refs/heads/main"}, {"name": "SAME", "default_branch": None}]):
            with self.subTest(rows=rows), self.assertRaises(HarnessServiceError):
                self.discovery(rows=rows)

    def test_repository_discovery_rejects_foreign_auth_and_requires_existing_config(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(HarnessServiceError) as caught:
            self.api.repositories("https://dev.azure.com/ExampleOrg/Project")
        self.assertEqual(caught.exception.code, "azure_auth_unavailable")
        with patch.dict(os.environ, {"HOME": "/other-identity"}), self.assertRaises(HarnessServiceError) as caught:
            self.api.repositories("https://dev.azure.com/ExampleOrg/Project")
        self.assertEqual(caught.exception.code, "azure_identity_mismatch")

    def test_rollback_restores_registry_and_removes_only_installed_files(self):
        self.registry.parent.mkdir(parents=True)
        original = '{"version": 1, "runtimes": [], "installations": []}\n'
        self.registry.write_text(original)
        result = self.configure(apply=True)
        receipt = result["receipt"]
        before = self.files()
        preview = self.api.rollback(receipt)
        self.assertTrue(preview["read_only"])
        self.assertEqual(self.files(), before)
        restored = self.api.rollback(receipt, apply=True)
        self.assertFalse(restored["conflicts"])
        self.assertEqual(self.registry.read_text(), original)
        self.assertFalse(Path(result["profile"]).exists())
        self.assertFalse(Path(result["runtime_dir"]).exists())

    def test_rollback_preserves_user_changes_and_refuses_partial_restore(self):
        result = self.configure(apply=True)
        profile = Path(result["profile"])
        profile.write_text(profile.read_text() + "\n")
        before = self.files()
        rollback = self.api.rollback(result["receipt"], apply=True)
        self.assertTrue(rollback["conflicts"])
        self.assertEqual(self.files(), before)

    def test_invalid_registry_never_overwrites_existing_bytes(self):
        self.registry.parent.mkdir(parents=True)
        for value in ('{"version":1,"version":1,"runtimes":[]}', '{"version":1,"runtimes":[],"secret":"sentinel"}'):
            self.registry.write_text(value)
            before = self.files()
            with self.assertRaises(HarnessServiceError):
                self.configure(apply=True)
            self.assertEqual(self.files(), before)

    def test_apply_failure_rolls_back_files_and_allows_safe_retry(self):
        import setup_harness_interface as setup
        original = setup.atomic_write
        failed = []
        def fail_profile_once(path, data, mode, home):
            if path.name == "example.json" and not failed:
                failed.append(True)
                raise OSError("fixture failure")
            return original(path, data, mode, home)
        with patch.object(setup, "atomic_write", side_effect=fail_profile_once), self.assertRaises(HarnessServiceError):
            self.configure(apply=True)
        self.assertFalse(self.registry.exists())
        runtime = self.home / ".local/share/atlasmemory-tools/remotes/example/runtime"
        self.assertFalse(runtime.exists())
        receipts = list((self.home / ".local/state/atlasmemory-tools/installations").glob("*/receipt.json"))
        self.assertEqual(json.loads(receipts[0].read_text())["status"], "failed_rolled_back")
        self.assertTrue(self.configure(apply=True)["runtime_code_ready"])


if __name__ == "__main__":
    unittest.main()
