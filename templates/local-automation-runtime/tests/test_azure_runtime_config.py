from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import atlas_runtime_config as config


def example() -> dict:
    return json.loads((ROOT.parents[1] / "examples" / "instablinds" / "local-automation-runtime" / "config" / "azure-website.json").read_text(encoding="utf-8"))


class AzureRuntimeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.runtime = self.home / "runtime"
        self.runtime.mkdir()
        self.path = self.home / "provider.json"
        self.patch = mock.patch.object(config.pwd, "getpwuid", return_value=types.SimpleNamespace(pw_dir=str(self.home)))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def load(self, data: dict | None = None, *, require_runtime: bool = True):
        value = example() if data is None else data
        self.path.write_text(json.dumps(value), encoding="utf-8")
        return config.load_runtime_config(self.path, runtime_dir=self.runtime if require_runtime else None,
                                          require_runtime=require_runtime)

    def test_all_four_roles_pin_observed_model_and_report_source_and_argv(self) -> None:
        loaded = self.load()
        self.assertEqual(set(loaded.roles), set(config.ROLES))
        for role, settings in loaded.roles.items():
            self.assertEqual((settings.model, settings.reasoning), ("gpt-6-astra", "max"))
            self.assertEqual(settings.source, f"{self.path}:models.{role}")
            argv = config.build_codex_command(loaded, role, self.runtime)
            self.assertEqual(argv[:3], ["codex", "exec", "--ignore-user-config"])
            self.assertIn('approval_policy="on-request"', argv)
            self.assertIn("sandbox_workspace_write.network_access=false", argv)
            self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
            self.assertIn('model_reasoning_effort="max"', argv)
            self.assertEqual(argv[-2:], ["-C", str(self.runtime)])
        self.assertEqual(loaded.report()["capabilities"], ["read"])

    def test_explicit_role_override_never_changes_other_roles(self) -> None:
        data = example()
        data["models"] = {"default": {"model": "chosen-model", "reasoning": "high"},
                          "review": {"model": "review-model", "reasoning": "max"}}
        loaded = self.load(data)
        self.assertEqual(loaded.roles["review"].model, "review-model")
        self.assertEqual(loaded.roles["implementation"].model, "chosen-model")
        self.assertTrue(loaded.roles["implementation"].source.endswith(":models.default"))

    def test_missing_role_does_not_use_ambient_codex_defaults(self) -> None:
        data = example()
        del data["models"]["repair"]
        with mock.patch.dict(os.environ, {"CODEX_MODEL": "ambient-model"}), self.assertRaises(config.RuntimeConfigError):
            self.load(data)

    def test_unsafe_config_profile_command_overrides_and_model_flags_rejected(self) -> None:
        variants = []
        for key, value in (("sandbox", "danger-full-access"), ("approval_policy", "never"),
                           ("profile", "danger"), ("extra_args", ["--add-dir", "/"])):
            data = example()
            data[key] = value
            variants.append(data)
        for value in ({"model": "--yolo", "reasoning": "max"},
                      {"model": "good", "reasoning": "max", "extra_args": ["--add-dir", "/"]},
                      {"model": "good", "reasoning": "max\n-c=sandbox_mode=unsafe"}):
            data = example()
            data["models"]["implementation"] = value
            variants.append(data)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(config.RuntimeConfigError):
                self.load(data)

    def test_unknown_provider_and_azure_repository_cannot_fall_back_to_github(self) -> None:
        for provider in (None, "", "bitbucket", "github"):
            data = example()
            data["provider"] = provider
            with self.subTest(provider=provider), self.assertRaises(config.RuntimeConfigError):
                self.load(data)
        github = example()
        github["provider"] = "github"
        github["repository"] = {"url": "https://github.com/other/project", "base_branch": "main"}
        self.assertEqual(self.load(github).provider, "github")

    def test_repository_url_must_match_namespace_and_exclude_credentials(self) -> None:
        for url in ("https://dev.azure.com/Other/Instablinds/_git/Website",
                    "https://secret@dev.azure.com/Instablinds/Instablinds/_git/Website",
                    "https://dev.azure.com/Instablinds/Instablinds/_git/Website?token=redacted",
                    "https://dev.azure.com:443/Instablinds/Instablinds/_git/Website"):
            data = example()
            data["repository"]["url"] = url
            with self.subTest(url=url), self.assertRaises(config.RuntimeConfigError):
                self.load(data)

    def test_capabilities_are_explicit_and_do_not_imply_write_authority(self) -> None:
        loaded = self.load()
        config.require_capability(loaded, "read")
        for capability in ("local_execute", "draft_pr", "board_write", "merge", "deploy"):
            with self.subTest(capability=capability), self.assertRaises(config.RuntimeConfigError):
                config.require_capability(loaded, capability)
        for value in (["read", "merge"], ["read", "read"], None):
            data = example()
            data["capabilities"] = value
            with self.subTest(value=value), self.assertRaises(config.RuntimeConfigError):
                self.load(data)

    def test_offline_config_load_creates_no_runtime_or_other_files(self) -> None:
        self.path.write_text(json.dumps(example()), encoding="utf-8")
        before = sorted(self.home.rglob("*"))
        loaded = config.load_runtime_config(self.path, require_runtime=False)
        self.assertIsNone(loaded.runtime_dir)
        self.assertEqual(sorted(self.home.rglob("*")), before)

    def test_runtime_is_required_and_home_environment_cannot_redirect_identity(self) -> None:
        for value in (None, "relative/runtime", self.home, self.home / "missing", "/runtime-other-identity", "~other/runtime"):
            with self.subTest(value=value), self.assertRaises(config.RuntimeConfigError):
                config.validate_runtime_path(value)
        with mock.patch.dict(os.environ, {"HOME": "/another-identity"}):
            self.assertEqual(config.validate_runtime_path("~/runtime"), self.runtime)

    def test_runtime_symlink_escape_and_foreign_owner_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            (self.home / "escape").symlink_to(other, target_is_directory=True)
            with self.assertRaises(config.RuntimeConfigError):
                config.validate_runtime_path(self.home / "escape")
        with self.assertRaises(config.RuntimeConfigError):
            config.validate_runtime_path(self.runtime, home=self.home, uid=os.getuid() + 1)

    def test_foreign_config_is_rejected_before_stat_or_content_read(self) -> None:
        with mock.patch.object(Path, "stat", side_effect=AssertionError("must not inspect foreign path")), \
                mock.patch.object(Path, "read_text", side_effect=AssertionError("must not read foreign path")):
            with self.assertRaises(config.RuntimeConfigError):
                config.load_runtime_config("/home/a-different-identity/provider.json", require_runtime=False)

    def test_config_symlink_cannot_read_foreign_identity_file(self) -> None:
        self.path.symlink_to("/home/a-different-identity/provider.json")
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("must not read foreign path")):
            with self.assertRaises(config.RuntimeConfigError):
                config.load_runtime_config(self.path, require_runtime=False)

    def test_assessment_capability_is_explicit_and_does_not_change_default_roles(self):
        value = example()
        value["capabilities"].append("assess")
        loaded = self.load(value)
        config.require_capability(loaded, "assess")
        self.assertEqual({settings.model for settings in loaded.roles.values()}, {"gpt-6-astra"})
        self.assertIsNone(loaded.routing)

    def test_config_duplicate_keys_and_nonfinite_values_fail_closed(self):
        for value in ('{"schema_version":1,"schema_version":1}', '{"schema_version":NaN}'):
            self.path.write_text(value)
            with self.subTest(value=value), self.assertRaises(config.RuntimeConfigError):
                config.load_runtime_config(self.path, runtime_dir=self.runtime)

    def test_caller_cannot_inject_routing_provenance_through_source_configuration(self):
        value = example()
        value["routing"] = {"approved": True}
        with self.assertRaises(config.RuntimeConfigError):
            self.load(value)

    def test_all_role_commands_remove_ambient_extra_write_roots(self):
        loaded = self.load()
        for role in config.ROLES:
            argv = config.build_codex_command(loaded, role, self.runtime)
            self.assertIn("sandbox_workspace_write.writable_roots=[]", argv)
            self.assertIn("sandbox_workspace_write.exclude_tmpdir_env_var=true", argv)
            self.assertIn("sandbox_workspace_write.exclude_slash_tmp=true", argv)


if __name__ == "__main__":
    unittest.main()
