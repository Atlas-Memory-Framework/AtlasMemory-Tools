from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harnesslib  # noqa: E402
import enforce_local_ssot  # noqa: E402


class ManifestAndHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((ROOT / "manifests" / "atlas-tools.v1.json").read_text(encoding="utf-8"))

    def test_manifest_paths_exist(self) -> None:
        for skill in self.manifest["skills"]:
            skill_dir = ROOT / skill["path"]
            self.assertTrue((skill_dir / "SKILL.md").is_file(), skill["name"])
            for path in skill_dir.rglob("*"):
                if path.is_file():
                    self.assertTrue(path.exists())

        for agent in self.manifest["agents"]:
            self.assertTrue((ROOT / agent["path"]).is_file(), agent["name"])

        for template in self.manifest["templates"]:
            self.assertTrue((ROOT / template["path"]).is_dir(), template["name"])

    def test_canonical_skills_do_not_point_at_cursor_sources(self) -> None:
        offenders: list[str] = []
        for path in (ROOT / "skills").rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if ".cursor/skills" in text or ".cursor/agents" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_install_and_verify_each_harness(self) -> None:
        for harness in self.manifest["adapters"]:
            with self.subTest(harness=harness), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)
                changed = harnesslib.install_harness(harness, target)
                self.assertTrue(changed)
                self.assertEqual(harnesslib.verify_harness_target(target), [])

    def test_manual_edit_to_generated_file_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            harnesslib.install_harness("cursor", target)
            generated = target / ".cursor" / "skills" / "plan" / "SKILL.md"
            generated.write_text(generated.read_text(encoding="utf-8") + "\nmanual edit\n", encoding="utf-8")

            errors = harnesslib.verify_harness_target(target)

        self.assertTrue(any("generated body differs" in error for error in errors))

    def test_missing_generated_file_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            harnesslib.install_harness("cursor", target)
            generated = target / ".cursor" / "skills" / "plan" / "SKILL.md"
            generated.unlink()

            errors = harnesslib.verify_harness_target(target)

        self.assertTrue(any("missing generated file" in error for error in errors))

    def test_committed_cursor_copy_matches_generated_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            harnesslib.install_harness("cursor", target)
            generated_root = target / ".cursor"
            committed_root = ROOT / ".cursor"
            self.assertTrue(committed_root.exists())
            mismatches: list[str] = []
            for path in generated_root.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(generated_root)
                committed = committed_root / rel
                if not committed.exists() or committed.read_bytes() != path.read_bytes():
                    mismatches.append(str(rel))
            extra = [
                str(path.relative_to(committed_root))
                for path in committed_root.rglob("*")
                if path.is_file() and not (generated_root / path.relative_to(committed_root)).exists()
            ]
        self.assertEqual(mismatches, [])
        self.assertEqual(extra, [])

    def test_codex_gemini_claude_targets_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for harness in ("codex", "gemini", "claude"):
                harnesslib.install_harness(harness, target)
            self.assertTrue((target / ".codex" / "skills" / "plan" / "SKILL.md").exists())
            self.assertTrue((target / ".gemini" / "skills" / "plan" / "SKILL.md").exists())
            self.assertTrue((target / ".claude" / "skills" / "plan" / "SKILL.md").exists())


class LocalSsotEnforcementTests(unittest.TestCase):
    def run_git(self, cwd: Path, *args: str) -> None:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

    def test_registry_check_and_repair_generated_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "project"
            target.mkdir()
            harnesslib.install_harness("codex", target)
            registry = Path(tmp) / "ssot.json"
            registry.write_text(
                json.dumps({"projects": [{"path": str(target), "harnesses": ["codex"]}]}),
                encoding="utf-8",
            )
            generated = target / ".codex" / "skills" / "plan" / "SKILL.md"
            generated.write_text(generated.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")

            projects = enforce_local_ssot.load_registry(registry)
            self.assertEqual(len(projects), 1)
            self.assertTrue(enforce_local_ssot.check_project(projects[0]))

            changed = enforce_local_ssot.repair_project(projects[0])

            self.assertIn(generated, changed)
            self.assertEqual(enforce_local_ssot.check_project(projects[0]), [])

    def test_registry_harnesses_scope_check_and_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "project"
            target.mkdir()
            harnesslib.install_harness("codex", target)
            harnesslib.install_harness("claude", target)
            project = enforce_local_ssot.Project(target, ("codex",))
            generated = target / ".claude" / "skills" / "plan" / "SKILL.md"
            generated.write_text(generated.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")

            self.assertEqual(enforce_local_ssot.check_project(project), [])
            self.assertTrue(harnesslib.verify_harness_target(target))

    def test_hook_install_preserves_existing_hook_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hook = Path(tmp) / "pre-commit"
            hook.write_text("#!/usr/bin/env sh\necho existing\n", encoding="utf-8")

            enforce_local_ssot.install_hook(hook, "echo managed")

            text = hook.read_text(encoding="utf-8")
            self.assertIn("echo existing", text)
            self.assertIn(enforce_local_ssot.HOOK_BEGIN, text)
            self.assertIn("echo managed", text)
            self.assertTrue(hook.stat().st_mode & 0o111)

    def test_hook_install_runs_managed_block_before_existing_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hook = Path(tmp) / "pre-commit"
            hook.write_text("#!/usr/bin/env sh\nset -eu\nexit 0\necho existing\n", encoding="utf-8")

            enforce_local_ssot.install_hook(hook, "echo managed")

            text = hook.read_text(encoding="utf-8")
            self.assertLess(text.index("echo managed"), text.index("exit 0"))
            self.assertIn("echo existing", text)

    def test_project_hook_installs_into_git_worktree_hook_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            worktree = root / "worktree"
            repo.mkdir()
            self.run_git(repo, "init")
            self.run_git(repo, "config", "user.email", "test@example.invalid")
            self.run_git(repo, "config", "user.name", "Test User")
            (repo / "README.md").write_text("test\n", encoding="utf-8")
            self.run_git(repo, "add", "README.md")
            self.run_git(repo, "commit", "-m", "init")
            self.run_git(repo, "worktree", "add", "-b", "worktree-test", str(worktree))

            project = enforce_local_ssot.Project(worktree, ("codex",))
            hook_path = enforce_local_ssot.hook_path_for_repo(worktree)
            self.assertIsNotNone(hook_path)
            enforce_local_ssot.install_project_hook(project)

            self.assertTrue(hook_path.exists())
            self.assertIn("--harness codex", hook_path.read_text(encoding="utf-8"))


class PortabilityTests(unittest.TestCase):
    FORBIDDEN = (
        "Atlas-" "Memory-Framework",
        "Atlat-" "Memory-Azure-Implmentation",
        "Mateusz" "Kordasiewicz",
        "AtlasMemory" "-Dev",
        "fix/mime-" "resolution-pins-mainline",
    )

    def test_no_atlas_specific_defaults_outside_examples(self) -> None:
        offenders: list[str] = []
        for base in ("skills", "agents", "templates", "scripts", "tests", "manifests"):
            for path in (ROOT / base).rglob("*"):
                if not path.is_file():
                    continue
                if "__pycache__" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for token in self.FORBIDDEN:
                    if token in text:
                        offenders.append(f"{path.relative_to(ROOT)}: {token}")
        self.assertEqual(offenders, [])

    def test_runtime_examples_are_placeholder_safe(self) -> None:
        for path in (ROOT / "templates" / "local-automation-runtime").rglob("*example*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertIn("OWNER", text, path)


if __name__ == "__main__":
    unittest.main()
