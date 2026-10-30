from __future__ import annotations

import ast
import json
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harness_execution  # noqa: E402
from harness_service import HarnessServiceError  # noqa: E402


class FixtureService:
    tools_root = ROOT

    def __init__(self, root: Path):
        self.registry = root / "registry.json"
        self.runtime = {
            "id": "test", "provider": "github", "runtime_dir": str(root / "runtime"),
            "config": str(root / "runtime.json"),
            "configuration": {"capabilities": ["read", "local_execute", "draft_pr"]},
        }
        self.observation_blockers = []
        self.observation_next_actions = []

    def get_runtime(self, runtime_id: str) -> dict:
        if runtime_id != "test":
            raise HarnessServiceError("unknown_runtime", "The runtime is not registered.")
        return self.runtime

    def inspect(self, runtime_id: str) -> dict:
        return {"blockers": self.observation_blockers, "next_actions": self.observation_next_actions}

    def _envelope(self, **values) -> dict:
        return {"schema_version": "atlas-tools.harness.v1", "read_only": True, **values}


class HarnessPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = FixtureService(self.root)
        self.runtime = Path(self.service.runtime["runtime_dir"])
        self.runtime.mkdir()
        self.service.registry.write_text(json.dumps({"version": 1, "runtimes": [{"id": "test"}]}), encoding="utf-8")
        Path(self.service.runtime["config"]).write_text(json.dumps({"capabilities": ["local_execute", "draft_pr"]}), encoding="utf-8")
        (self.runtime / "repos.txt").write_text("example/project\n", encoding="utf-8")
        (self.runtime / "required-checks.json").write_text("{}\n", encoding="utf-8")
        (self.runtime / "local-validation.json").write_text("{}\n", encoding="utf-8")
        (self.runtime / "config.env").write_text("SECRET_MARKER=not-to-be-read\n", encoding="utf-8")
        for name in harness_execution.canonical_code_files(ROOT):
            shutil.copy2(ROOT / "templates" / "local-automation-runtime" / name, self.runtime / name)
        self.execution = harness_execution.HarnessExecution(self.service)

    def prepare(self, **options) -> dict:
        return self.execution.prepare("test", options=options or None)

    def test_prepare_is_inert_and_does_not_read_secret_config(self) -> None:
        before = {str(path): (path.stat().st_mtime_ns, path.read_bytes()) for path in self.root.rglob("*") if path.is_file()}
        original_read = harness_execution._read_bytes

        def guarded_read(path, **kwargs):
            self.assertNotEqual(Path(path).name, "config.env")
            return original_read(path, **kwargs)

        with patch.object(harness_execution, "_read_bytes", side_effect=guarded_read), \
                patch("subprocess.run", side_effect=AssertionError("must not execute")), \
                patch("subprocess.Popen", side_effect=AssertionError("must not launch")), \
                patch("socket.create_connection", side_effect=AssertionError("must not connect")):
            result = self.prepare()
        self.assertEqual(result["status"], "prepared", result.get("blockers"))
        self.assertTrue(result["read_only"])
        self.assertFalse(result["proposal"]["required_authorization"]["granted"])
        self.assertNotIn("SECRET_MARKER", json.dumps(result))
        after = {str(path): (path.stat().st_mtime_ns, path.read_bytes()) for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_identity_is_stable_and_binds_every_material_field(self) -> None:
        first = self.prepare()
        self.assertEqual(first["proposal_id"], self.prepare()["proposal_id"])
        self.assertEqual(first["proposal_id"], harness_execution.proposal_digest(first["proposal"]))
        self.assertNotEqual(first["proposal_id"], self.prepare(max_minutes=1)["proposal_id"])
        self.assertNotEqual(first["proposal_id"], self.prepare(cycles=2)["proposal_id"])
        self.assertNotEqual(first["proposal_id"], self.prepare(publish=True)["proposal_id"])
        tampered = json.loads(json.dumps(first["proposal"]))
        tampered["effects"]["merge"] = True
        self.assertNotEqual(first["proposal_id"], harness_execution.proposal_digest(tampered))

    def test_registry_configuration_inventory_and_policy_changes_invalidate_identity(self) -> None:
        for path in [self.service.registry, Path(self.service.runtime["config"]), self.runtime / "required-checks.json"]:
            with self.subTest(path=path):
                before = self.prepare()["proposal_id"]
                path.write_text(path.read_text() + "\n", encoding="utf-8")
                self.assertNotEqual(before, self.prepare()["proposal_id"])
        before = self.prepare()["proposal_id"]
        (self.runtime / "repos.txt").write_text("example/another\n", encoding="utf-8")
        changed = self.prepare()
        self.assertNotEqual(before, changed["proposal_id"])
        self.assertEqual(changed["proposal"]["targets"], ["example/another"])

    def test_secret_config_metadata_changes_invalidate_without_content_exposure(self) -> None:
        before = self.prepare()["proposal_id"]
        (self.runtime / "config.env").write_text("SECRET_MARKER=changed-secret\n", encoding="utf-8")
        result = self.prepare()
        self.assertNotEqual(before, result["proposal_id"])
        self.assertNotIn("changed-secret", json.dumps(result))

    def test_script_drift_or_missing_script_blocks_and_changes_digest(self) -> None:
        before = self.prepare()["proposal_id"]
        path = self.runtime / "atlas-agent-shift"
        path.write_text(path.read_text() + "\n# local change\n", encoding="utf-8")
        result = self.prepare()
        self.assertEqual(result["status"], "blocked")
        self.assertNotEqual(before, result["proposal_id"])
        self.assertIn("runtime_script_drift", {item["code"] for item in result["blockers"]})
        path.unlink()
        result = self.prepare()
        self.assertIn("missing_runtime_script", {item["code"] for item in result["blockers"]})

    def test_transitive_runtime_helper_is_pinned_and_drift_blocks(self) -> None:
        before = self.prepare()
        name = "atlas_workflows.py"
        self.assertIn(name, before["proposal"]["bindings"]["scripts"])
        path = self.runtime / name
        path.write_text(path.read_text() + "\n# transitive helper change\n", encoding="utf-8")
        after = self.prepare()
        self.assertEqual(after["status"], "blocked")
        self.assertNotEqual(before["proposal_id"], after["proposal_id"])
        self.assertIn("runtime_script_drift", {item["code"] for item in after["blockers"]})

    def test_non_executable_entrypoint_blocks(self) -> None:
        path = self.runtime / "atlas-agent-shift"
        path.chmod(path.stat().st_mode & ~stat.S_IXUSR)
        self.assertIn("runtime_script_not_executable", {item["code"] for item in self.prepare()["blockers"]})

    def test_foreign_writable_code_and_inventory_block_before_execution(self) -> None:
        path = self.runtime / "atlas_workflows.py"
        path.chmod(0o666)
        self.assertIn("unsafe_runtime_code_mode", {item["code"] for item in self.prepare()["blockers"]})
        (self.runtime / "repos.txt").chmod(0o666)
        self.assertIn("unsafe_inventory", {item["code"] for item in self.prepare()["blockers"]})

    def test_missing_legacy_configuration_or_invalid_required_policy_blocks(self) -> None:
        (self.runtime / "config.env").unlink()
        self.assertIn("missing_runtime_config", {item["code"] for item in self.prepare()["blockers"]})
        (self.runtime / "required-checks.json").write_text("not json", encoding="utf-8")
        self.assertIn("unsafe_runtime_policy", {item["code"] for item in self.prepare()["blockers"]})
        (self.runtime / "required-checks.json").unlink()
        self.assertIn("missing_runtime_policy", {item["code"] for item in self.prepare()["blockers"]})

    def test_symlinked_inventory_script_and_secret_config_are_not_followed(self) -> None:
        for name in ["repos.txt", "atlas-agent-shift", "config.env"]:
            with self.subTest(name=name):
                path = self.runtime / name
                backup = path.with_name(name + ".original")
                path.rename(backup)
                path.symlink_to(backup)
                self.assertEqual(self.prepare()["status"], "blocked")
                path.unlink()
                backup.rename(path)

    def test_unknown_or_wrong_type_options_cannot_supply_commands_or_authorization(self) -> None:
        cases = [[], {"command": "touch file"}, {"argv": []}, {"merge": True}, {"close_issues": True},
                 {"authorization_ref": "anything"}, {"max_minutes": True}, {"max_minutes": 0},
                 {"max_minutes": 31}, {"cycles": 4}, {"max_per_repo": 3}, {"publish": "true"},
                 {"apply": 1}, {"review_apply": None}]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(HarnessServiceError):
                self.execution.prepare("test", options=options)
        with self.assertRaises(HarnessServiceError):
            self.execution.prepare("test", operation="shell")

    def test_default_mode_has_no_project_code_execution_or_external_writes(self) -> None:
        proposal = self.prepare()["proposal"]
        args = proposal["argv"]
        self.assertIn("--dry-run", args)
        self.assertEqual(args[args.index("--stages") + 1], "reconcile,dispatch,review,summary")
        for effect in ["worker_execution", "draft_pr_publication", "project_validation_commands", "issue_labels_comments", "merge", "close_issues", "deployment_requested", "cleanup", "notifications"]:
            self.assertFalse(proposal["effects"][effect], effect)
        self.assertEqual(args[args.index("--cleanup-mode") + 1], "off")
        self.assertEqual(args.count("--project-reconcile-every"), 2)
        self.assertNotIn("--post-cycle-summary", args)
        self.assertNotIn("--no-post-cycle-summary", args)
        self.assertIn("--no-worker-notifications", args)
        self.assertEqual(args[args.index("--execution-targets-file") + 1], str(self.runtime / "repos.txt"))

    def test_explicit_effect_options_never_add_merge_close_deploy_or_cleanup(self) -> None:
        proposal = self.prepare(apply=True, publish=True, review_apply=True, max_minutes=30, cycles=3, max_per_repo=2)["proposal"]
        args = proposal["argv"]
        self.assertIn("--apply", args)
        self.assertIn("--publish", args)
        self.assertIn("--review-apply", args)
        self.assertTrue(proposal["effects"]["project_validation_commands"])
        self.assertTrue(proposal["effects"]["dispatch_readiness_changes"])
        self.assertTrue(proposal["effects"]["missing_base_branch_creation"])
        stages = args[args.index("--stages") + 1].split(",")
        self.assertNotIn("finalize", stages)
        self.assertNotIn("deployed-validate", stages)
        for flag in ["--merge", "--close-issues", "--post-cycle-summary"]:
            self.assertNotIn(flag, args)
        self.assertEqual(proposal["budgets"]["cycle_timeout_seconds"], 1800)

    def test_nonsecret_capabilities_do_not_grant_authority(self) -> None:
        self.service.runtime["configuration"] = {"capabilities": ["read"]}
        result = self.prepare(publish=True)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual({item["code"] for item in result["blockers"]}, {"missing_execution_capability", "missing_publication_capability"})
        self.assertFalse(result["proposal"]["required_authorization"]["granted"])

    def test_azure_is_explicitly_unsupported_and_has_no_github_proposal(self) -> None:
        self.service.runtime["provider"] = "azure-devops"
        result = self.prepare()
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["proposal"])
        self.assertIsNone(result["proposal_id"])
        self.assertEqual(result["blockers"][0]["code"], "unsupported_provider_operation")

    def test_bad_inventory_is_blocked_and_never_echoes_untrusted_text(self) -> None:
        values = ["", "https://github.com/example/project", "example/project #inline", "example/project; touch x", "-owner/project", "Instablinds/Website", "example/project\nEXAMPLE/PROJECT"]
        for content in values:
            with self.subTest(content=content):
                (self.runtime / "repos.txt").write_text(content, encoding="utf-8")
                result = self.prepare()
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["proposal"]["targets"], [])
                self.assertNotIn("touch x", json.dumps(result))

    def test_full_line_inventory_comments_are_safe_and_preserve_binding(self) -> None:
        (self.runtime / "repos.txt").write_text("# ignored; $(touch anything)\n\nexample/project\n", encoding="utf-8")
        result = self.prepare()
        self.assertEqual(result["status"], "prepared")
        self.assertEqual(result["proposal"]["targets"], ["example/project"])

    def test_active_or_stale_runtime_requires_reconciliation(self) -> None:
        self.service.observation_blockers = [{"code": "stale_active_evidence", "message": "stale", "next_action": "reconcile"}]
        self.assertEqual(self.prepare()["status"], "blocked")

    def test_all_unresolved_inspection_failures_block_and_preserve_actions(self) -> None:
        for code in ["unsafe_path", "invalid_json", "input_too_large", "unavailable_path", "unsafe_handoff", "contradictory_runtime_evidence"]:
            with self.subTest(code=code):
                self.service.observation_blockers = [{"code": code, "message": "Unresolved inspection evidence", "next_action": "Inspect exact evidence."}]
                action = {"operation": "reconcile_evidence", "runtime_id": "test", "code": code}
                self.service.observation_next_actions = [action]
                result = self.prepare()
                self.assertEqual(result["status"], "blocked")
                self.assertIn(code, {item["code"] for item in result["blockers"]})
                self.assertIn(action, result["next_actions"])
        self.service.observation_blockers = [{"code": "no_runtime_evidence", "message": "new runtime", "next_action": "prepare"}]
        self.assertEqual(self.prepare()["status"], "prepared")

    def test_generated_flags_are_supported_by_real_parser_sources(self) -> None:
        # Check parser declarations statically; importing legacy parsers could
        # read config.env while constructing their defaults.
        def declared_flags(name: str) -> set[str]:
            tree = ast.parse((ROOT / "templates" / "local-automation-runtime" / name).read_text())
            flags = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
                    boolean_optional = any(keyword.arg == "action" and isinstance(keyword.value, ast.Attribute) and keyword.value.attr == "BooleanOptionalAction" for keyword in node.keywords)
                    for argument in node.args:
                        if isinstance(argument, ast.Constant) and isinstance(argument.value, str) and argument.value.startswith("--"):
                            flags.add(argument.value)
                            if boolean_optional:
                                flags.add("--no-" + argument.value[2:])
            return flags

        flags = declared_flags("atlas-agent-shift") | declared_flags("atlas-agent-unattended")
        for options in [{}, {"publish": True, "apply": True, "review_apply": True}]:
            for value in self.prepare(**options)["proposal"]["argv"]:
                if value.startswith("--") and value != "--":
                    self.assertIn(value, flags)


if __name__ == "__main__":
    unittest.main()
