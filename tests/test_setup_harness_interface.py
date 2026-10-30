from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harnesslib
import setup_harness_interface as setup


class SetupHarnessInterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.registry = self.home / ".config" / "atlasmemory-tools" / "harness.json"
        self.manifest = {
            "version": "atlas-tools.v1", "skills": [{"name": "action-plan", "path": "skills/action-plan"}],
            "agents": [], "adapters": {"codex": {"skills_path": ".codex/skills", "agents_path": ".codex/agents"}},
        }
        self.manifest_patch = patch.object(setup, "load_manifest", return_value=self.manifest)
        self.manifest_patch.start()
        self.addCleanup(self.manifest_patch.stop)

    def main(self, *args: str) -> tuple[int, dict]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = setup.main(["--home", str(self.home), *args])
        return status, json.loads(output.getvalue())

    def snapshot(self) -> dict[str, bytes]:
        return {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}

    def test_default_preview_and_check_write_nothing(self) -> None:
        before = self.snapshot()
        status, result = self.main()
        self.assertEqual(status, 0)
        self.assertTrue(result["read_only"])
        self.assertGreater(len(result["changed"]), 2)
        self.assertEqual(self.snapshot(), before)
        status, result = self.main("--check")
        self.assertEqual(status, 1)
        self.assertEqual(self.snapshot(), before)

    def test_apply_idempotence_and_protocol_registration(self) -> None:
        status, result = self.main("--apply")
        self.assertEqual(status, 0, result)
        self.assertEqual(result["applied"], len(result["changed"]))
        receipt = Path(result["receipt"])
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        config = tomllib.loads((self.home / ".codex" / "config.toml").read_text())
        expected = setup.server_configuration(self.registry)
        self.assertEqual(config["mcp_servers"]["atlasmemory_tools"], expected)
        registry = json.loads(self.registry.read_text())
        self.assertEqual(registry, {"version": 1, "runtimes": [], "installations": [{"target": str(self.home), "harness": "codex"}]})
        before = self.snapshot()
        status, result = self.main("--apply")
        self.assertEqual(status, 0, result)
        self.assertEqual(result["applied"], 0)
        self.assertIsNone(result["receipt"])
        self.assertEqual(self.snapshot(), before)

    def test_unrelated_config_and_skills_are_preserved_byte_for_byte(self) -> None:
        codex = self.home / ".codex"
        codex.mkdir(mode=0o700)
        config = codex / "config.toml"
        original = b'# keep all comments\nmodel = "existing"\n\n[mcp_servers.node_repl]\ncommand = "existing-node"\n'
        config.write_bytes(original)
        skill = codex / "skills" / "unrelated" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_bytes(b"unrelated skill\n")
        status, result = self.main("--apply")
        self.assertEqual(status, 0, result)
        self.assertTrue(config.read_bytes().startswith(original))
        self.assertEqual(skill.read_bytes(), b"unrelated skill\n")
        self.assertEqual(tomllib.loads(config.read_text())["model"], "existing")

    def test_stale_generated_body_updates_but_local_edit_conflicts(self) -> None:
        target = self.home / ".codex" / "skills" / "action-plan" / "SKILL.md"
        target.parent.mkdir(parents=True)
        source = "skills/action-plan/SKILL.md"
        old = b"---\nname: old\n---\nold canonical body\n"
        first, _, rest = old.decode().partition("\n")
        stale = (first + "\n" + harnesslib.generated_header(source, "atlas-tools.v1", setup.digest(old), "#") + rest).encode()
        target.write_bytes(stale)
        status, result = self.main()
        self.assertEqual(status, 0, result)
        self.assertEqual(next(c for c in result["changed"] if c["path"] == str(target))["status"], "stale")
        target.write_bytes(stale + b"local edit\n")
        before = self.snapshot()
        status, result = self.main("--apply")
        self.assertEqual(status, 2)
        self.assertTrue(result["conflicts"])
        self.assertEqual(self.snapshot(), before)

    def test_current_generated_header_is_not_misclassified_as_drift(self) -> None:
        harnesslib.install_harness("codex", self.home)
        changes, conflicts = setup.plan_setup(self.home, self.registry, skills_only=True)
        # install_harness installs the real manifest, but unrelated managed files
        # are intentionally untouched by this narrowed test manifest.
        self.assertEqual(changes, [])
        self.assertEqual(conflicts, [])

    def test_unmanaged_skill_is_preserved_and_blocks_entire_apply(self) -> None:
        target = self.home / ".codex" / "skills" / "action-plan" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"custom content\n")
        before = self.snapshot()
        status, result = self.main("--apply")
        self.assertEqual(status, 2)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("preserved", result["conflicts"][0]["reason"])

    def test_config_conflicts_and_invalid_toml_are_not_echoed(self) -> None:
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir()
        sentinel = "DO_NOT_ECHO_CONFIG_CONTENTS"
        for content in (f'[mcp_servers.atlasmemory_tools]\ncommand = "{sentinel}"\n',
                        f'mcp_servers = {{ other = {{ command = "{sentinel}" }} }}\n',
                        f'bad = "{sentinel}\n'):
            with self.subTest(content=content[:20]):
                config.write_text(content)
                before = self.snapshot()
                status, result = self.main("--apply")
                self.assertEqual(status, 2, result)
                self.assertNotIn(sentinel, json.dumps(result))
                self.assertEqual(self.snapshot(), before)

    def test_edited_managed_mcp_block_is_preserved(self) -> None:
        status, result = self.main("--apply")
        self.assertEqual(status, 0)
        config = self.home / ".codex" / "config.toml"
        config.write_text(config.read_text().replace("enabled = true", "enabled = false"))
        before = self.snapshot()
        status, result = self.main("--apply")
        self.assertEqual(status, 2)
        self.assertIn("edited locally", str(result["conflicts"]))
        self.assertEqual(self.snapshot(), before)

    def test_register_explicit_runtime_and_preserve_other_registry_entries(self) -> None:
        runtime = self.home / "runtime"
        runtime.mkdir()
        config = runtime / "provider.json"
        config.write_text('{"provider":"github"}\n')
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(json.dumps({"version": 1, "runtimes": [{"id": "previous", "provider": "github", "runtime_dir": str(runtime)}]}))
        status, result = self.main("--apply", "--runtime-dir", str(runtime), "--provider", "github", "--runtime-id", "new", "--runtime-config", str(config))
        self.assertEqual(status, 0, result)
        data = json.loads(self.registry.read_text())
        self.assertEqual([entry["id"] for entry in data["runtimes"]], ["previous", "new"])
        self.assertEqual(data["runtimes"][1]["config"], str(config))

    def test_runtime_registration_rejects_incomplete_options_or_duplicate_retarget(self) -> None:
        runtime = self.home / "runtime"
        runtime.mkdir()
        status, result = self.main("--runtime-dir", str(runtime))
        self.assertEqual(status, 2)
        self.assertIn("--provider", str(result))
        status, result = self.main("--apply", "--runtime-dir", str(runtime), "--provider", "github", "--runtime-id", "existing")
        self.assertEqual(status, 0, result)
        other = self.home / "other"
        other.mkdir()
        before = self.snapshot()
        status, result = self.main("--apply", "--runtime-dir", str(other), "--provider", "github", "--runtime-id", "existing")
        self.assertEqual(status, 2)
        self.assertEqual(self.snapshot(), before)

    def test_symlink_hardlink_and_outside_registry_are_rejected(self) -> None:
        outside_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(outside_tmp.cleanup)
        outside = Path(outside_tmp.name)
        (self.home / ".codex").symlink_to(outside, target_is_directory=True)
        status, result = self.main("--apply")
        self.assertEqual(status, 2)
        self.assertEqual(list(outside.iterdir()), [])
        (self.home / ".codex").unlink()
        status, result = self.main("--apply", "--registry", str(outside / "registry.json"))
        self.assertEqual(status, 2)
        codex = self.home / ".codex"
        codex.mkdir()
        source = self.home / "source"
        source.write_text("some config\n")
        os.link(source, codex / "config.toml")
        status, result = self.main("--apply")
        self.assertEqual(status, 2)
        self.assertIn("hard-linked", str(result))

    def test_rollback_restores_originals_and_removes_only_new_files(self) -> None:
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text('# original\nmodel = "existing"\n')
        before = self.snapshot()
        status, result = self.main("--apply")
        self.assertEqual(status, 0)
        receipt = result["receipt"]
        status, preview = self.main("--rollback", receipt)
        self.assertEqual(status, 0, preview)
        self.assertTrue(self.registry.exists())
        status, result = self.main("--rollback", receipt, "--apply")
        self.assertEqual(status, 0, result)
        self.assertEqual(config.read_bytes(), before[".codex/config.toml"])
        self.assertFalse(self.registry.exists())
        self.assertFalse((self.home / ".codex/skills/action-plan/SKILL.md").exists())
        status, result = self.main("--rollback", receipt, "--apply")
        self.assertEqual(status, 0)
        self.assertTrue(result["already_rolled_back"])

    def test_rollback_preserves_user_edits_and_is_all_or_nothing(self) -> None:
        status, result = self.main("--apply")
        self.assertEqual(status, 0)
        receipt = result["receipt"]
        config = self.home / ".codex" / "config.toml"
        config.write_text(config.read_text() + '\nmodel_after = "user edit"\n')
        before = self.snapshot()
        status, result = self.main("--rollback", receipt, "--apply")
        self.assertEqual(status, 2, result)
        self.assertTrue(result["conflicts"])
        self.assertEqual(self.snapshot(), before)

    def test_rollback_rejects_tampered_backup(self) -> None:
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text('model = "existing"\n')
        status, result = self.main("--apply")
        self.assertEqual(status, 0)
        receipt = Path(result["receipt"])
        payload = json.loads(receipt.read_text())
        entry = next(record for record in payload["files"] if record["backup"])
        (receipt.parent / entry["backup"]).write_bytes(b"tampered\n")
        before = self.snapshot()
        status, result = self.main("--rollback", str(receipt), "--apply")
        self.assertEqual(status, 2)
        self.assertEqual(self.snapshot(), before)

    def test_preserve_local_installs_safe_updates_and_receipt_records_partial_consistency(self) -> None:
        local = self.home / ".codex" / "skills" / "action-plan" / "SKILL.md"
        local.parent.mkdir(parents=True)
        local.write_bytes(b"locally maintained skill\n")
        unrelated = self.home / ".codex" / "skills" / "unrelated" / "SKILL.md"
        unrelated.parent.mkdir()
        unrelated.write_bytes(b"unrelated skill\n")
        status, result = self.main("--apply", "--preserve-local")
        self.assertEqual(status, 0, result)
        self.assertEqual(result["consistency"], "local_changes_preserved")
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["preserved"], [{"path": str(local), "category": "generated", "reason": "modified or unmanaged file preserved"}])
        self.assertEqual(local.read_bytes(), b"locally maintained skill\n")
        self.assertEqual(unrelated.read_bytes(), b"unrelated skill\n")
        self.assertTrue(self.registry.exists())
        receipt = Path(result["receipt"])
        saved = json.loads(receipt.read_text())
        self.assertEqual(saved["preserved"], result["preserved"])
        self.assertNotIn(str(local.relative_to(self.home)), [entry["path"] for entry in saved["files"]])
        status, result = self.main("--check", "--preserve-local")
        self.assertEqual(status, 1)
        self.assertEqual(result["changed"], [])
        self.assertEqual(result["consistency"], "local_changes_preserved")
        status, result = self.main("--apply", "--rollback", str(receipt))
        self.assertEqual(status, 0, result)
        self.assertFalse(self.registry.exists())
        self.assertEqual(local.read_bytes(), b"locally maintained skill\n")
        self.assertEqual(unrelated.read_bytes(), b"unrelated skill\n")

    def test_preserve_local_does_not_bypass_mcp_config_conflicts(self) -> None:
        local = self.home / ".codex" / "skills" / "action-plan" / "SKILL.md"
        local.parent.mkdir(parents=True)
        local.write_bytes(b"locally maintained skill\n")
        config = self.home / ".codex" / "config.toml"
        config.write_text('[mcp_servers.atlasmemory_tools]\ncommand = "other"\n')
        before = self.snapshot()
        status, result = self.main("--apply", "--preserve-local")
        self.assertEqual(status, 2, result)
        self.assertTrue(result["preserved"])
        self.assertTrue(result["conflicts"])
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
