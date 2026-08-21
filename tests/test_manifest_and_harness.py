from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harnesslib  # noqa: E402
import enforce_local_ssot  # noqa: E402
import verify_repo  # noqa: E402
import sync_runtime_template  # noqa: E402
import runtime_control  # noqa: E402


def read_skill_frontmatter(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("missing opening frontmatter delimiter")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ValueError("missing closing frontmatter delimiter") from None

    try:
        fields = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(fields, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return fields


def skill_catalog_errors(manifest: dict) -> list[str]:
    errors: list[str] = []
    skills = manifest.get("skills") or []
    aliases = manifest.get("aliases") or {}
    names = [str(skill.get("name", "")) for skill in skills]
    paths = [str(skill.get("path", "")) for skill in skills]

    if len(names) != len(set(names)):
        errors.append("duplicate manifest skill name")
    if len(paths) != len(set(paths)):
        errors.append("duplicate manifest skill path")

    known_names = set(names)
    for owner in aliases:
        if owner not in known_names:
            errors.append(f"alias owner is not a manifest skill: {owner}")

    for skill in skills:
        install_name = str(skill.get("name", ""))
        relative = str(skill.get("path", ""))
        skill_file = ROOT / relative / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            frontmatter = read_skill_frontmatter(skill_file)
        except ValueError as exc:
            errors.append(f"{relative}: {exc}")
            continue
        public_name_value = frontmatter.get("name")
        description_value = frontmatter.get("description")
        public_name = public_name_value.strip() if isinstance(public_name_value, str) else ""
        description = description_value.strip() if isinstance(description_value, str) else ""
        if not public_name:
            errors.append(f"{relative}: missing frontmatter name")
        if not description:
            errors.append(f"{relative}: missing frontmatter description")
        if public_name and public_name != install_name and public_name not in aliases.get(install_name, []):
            errors.append(
                f"{relative}: frontmatter name {public_name!r} differs from manifest name "
                f"{install_name!r} without an explicit alias"
            )

    registered_paths = set(paths)
    for skill_file in (ROOT / "skills").glob("*/SKILL.md"):
        relative = skill_file.parent.relative_to(ROOT).as_posix()
        if relative not in registered_paths:
            errors.append(f"unregistered canonical skill: {relative}")
    return errors


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

    def test_skill_catalog_identity_is_explicit_and_complete(self) -> None:
        self.assertEqual(skill_catalog_errors(self.manifest), [])

    def test_skill_catalog_rejects_undeclared_frontmatter_name_drift(self) -> None:
        manifest = deepcopy(self.manifest)
        manifest["aliases"].pop("implement")

        errors = skill_catalog_errors(manifest)

        self.assertTrue(any("skills/implement" in error and "without an explicit alias" in error for error in errors))

    def test_skill_catalog_rejects_duplicate_identity_and_unknown_alias_owner(self) -> None:
        manifest = deepcopy(self.manifest)
        manifest["skills"].append(deepcopy(manifest["skills"][0]))
        manifest["aliases"]["not-a-skill"] = ["ghost"]

        errors = skill_catalog_errors(manifest)

        self.assertIn("duplicate manifest skill name", errors)
        self.assertIn("duplicate manifest skill path", errors)
        self.assertIn("alias owner is not a manifest skill: not-a-skill", errors)

    def test_skill_frontmatter_rejects_malformed_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_file = Path(tmp) / "SKILL.md"
            skill_file.write_text(
                '---\nname: "unterminated\ndescription:\n  - broken\n---\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "invalid YAML frontmatter"):
                read_skill_frontmatter(skill_file)

    def test_skill_catalog_rejects_non_string_required_frontmatter(self) -> None:
        manifest = deepcopy(self.manifest)
        manifest["skills"] = [{"name": "invalid", "path": "skills/invalid"}]
        manifest["aliases"] = {}
        with tempfile.TemporaryDirectory(dir=ROOT / "skills") as tmp:
            skill_dir = Path(tmp)
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text("---\nname: []\ndescription: null\n---\n", encoding="utf-8")
            manifest["skills"][0]["path"] = skill_dir.relative_to(ROOT).as_posix()

            errors = skill_catalog_errors(manifest)

        self.assertTrue(any("missing frontmatter name" in error for error in errors))
        self.assertTrue(any("missing frontmatter description" in error for error in errors))

    def test_canonical_skills_do_not_point_at_retired_hidden_sources(self) -> None:
        retired_path = "." + "cur" + "sor/"
        offenders: list[str] = []
        for path in (ROOT / "skills").rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if retired_path in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_install_and_verify_each_harness(self) -> None:
        for harness in self.manifest["adapters"]:
            with self.subTest(harness=harness), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)
                changed = harnesslib.install_harness(harness, target)
                self.assertTrue(changed)
                self.assertEqual(harnesslib.verify_harness_target(target), [])

    def test_generated_skill_metadata_is_valid_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            harnesslib.install_harness("codex", target)
            generated_files = sorted((target / ".codex" / "skills").glob("*/agents/openai.yaml"))
            parsed_by_skill: dict[str, dict] = {}
            for generated in generated_files:
                lines = generated.read_text(encoding="utf-8").splitlines()
                self.assertTrue(lines[0].startswith("# atlas-tools-generated:"), generated)
                self.assertEqual(lines[1], "# atlas-tools-generated-end", generated)
                self.assertFalse(any("<!--" in line or "-->" in line for line in lines), generated)
                parsed = yaml.safe_load("\n".join(lines))
                self.assertIsInstance(parsed, dict, generated)
                parsed_by_skill[generated.parents[1].name] = parsed

        self.assertEqual(parsed_by_skill["grill-me"]["policy"]["allow_implicit_invocation"], False)

    def test_manual_edit_to_generated_file_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            harnesslib.install_harness("codex", target)
            generated = target / ".codex" / "skills" / "plan" / "SKILL.md"
            generated.write_text(generated.read_text(encoding="utf-8") + "\nmanual edit\n", encoding="utf-8")

            errors = harnesslib.verify_harness_target(target)

        self.assertTrue(any("generated body differs" in error for error in errors))

    def test_missing_generated_file_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            harnesslib.install_harness("codex", target)
            generated = target / ".codex" / "skills" / "plan" / "SKILL.md"
            generated.unlink()

            errors = harnesslib.verify_harness_target(target)

        self.assertTrue(any("missing generated file" in error for error in errors))

    def test_committed_codex_copy_matches_generated_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            harnesslib.install_harness("codex", target)
            generated_root = target / ".codex"
            committed_root = ROOT / ".codex"
            self.assertTrue(committed_root.exists())
            mismatches: list[str] = []
            extra: list[str] = []
            for subdir in ("skills", "agents"):
                generated_subdir = generated_root / subdir
                committed_subdir = committed_root / subdir
                for path in generated_subdir.rglob("*"):
                    if not path.is_file():
                        continue
                    rel = path.relative_to(generated_root)
                    committed = committed_root / rel
                    if not committed.exists() or committed.read_bytes() != path.read_bytes():
                        mismatches.append(str(rel))
                extra.extend(
                    str(path.relative_to(committed_root))
                    for path in committed_subdir.rglob("*")
                    if path.is_file() and not (generated_root / path.relative_to(committed_root)).exists()
                )
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


class RuntimeTemplateSyncTests(unittest.TestCase):
    def test_runtime_control_accepts_leaf_issue_strategy(self) -> None:
        parser = runtime_control.build_parser()

        preview = parser.parse_args(
            ["plan-preview", "--plan", "plan.md", "--repo", "OWNER/REPO", "--strategy", "leaf-issues"]
        )
        queue = parser.parse_args(
            ["queue", "--plan", "plan.md", "--repo", "OWNER/REPO", "--strategy", "leaf-issues", "--yes"]
        )

        self.assertEqual(preview.strategy, "leaf-issues")
        self.assertEqual(queue.strategy, "leaf-issues")

    def test_runtime_sync_preserves_local_config_and_adds_missing_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            (runtime / "config.env").write_text('AGENT_REPO="OWNER/LOCAL"\n', encoding="utf-8")
            (runtime / "required-checks.json").write_text('{"local": true}\n', encoding="utf-8")

            result = sync_runtime_template.sync_runtime(
                runtime,
                apply=True,
                migrate_config=True,
                readonly=False,
            )

            self.assertEqual(result, 0)
            self.assertTrue((runtime / "atlas-agent-worker").exists())
            self.assertEqual((runtime / "required-checks.json").read_text(encoding="utf-8"), '{"local": true}\n')
            config = (runtime / "config.env").read_text(encoding="utf-8")
            self.assertIn('AGENT_REPO="OWNER/LOCAL"', config)
            self.assertIn("AGENT_CODEX_PLANNING_PROFILE", config)


class PortabilityTests(unittest.TestCase):
    FORBIDDEN = (
        "Atlas-" "Memory-Framework",
        "Atlat-" "Memory-Azure-Implmentation",
        "Mateusz" "Kordasiewicz",
        "AtlasMemory" "-Dev",
        "fix/mime-" "resolution-pins-mainline",
    )
    ALLOWED_CANONICAL_TEMPLATE_REFERENCES = {
        "Atlas-" "Memory-Framework": {
            "skills/github-project/SKILL.md",
            "skills/github-project/scripts/create_project.py",
            "tests/test_github_project_skill.py",
        },
    }

    def test_no_atlas_specific_defaults_outside_examples(self) -> None:
        offenders: list[str] = []
        for base in ("skills", "agents", "templates", "scripts", "tests", "manifests"):
            for path in verify_repo.iter_tree_files(ROOT / base):
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for token in self.FORBIDDEN:
                    relative = path.relative_to(ROOT).as_posix()
                    if token in text and relative not in self.ALLOWED_CANONICAL_TEMPLATE_REFERENCES.get(token, set()):
                        offenders.append(f"{relative}: {token}")
        self.assertEqual(offenders, [])

    def test_runtime_examples_are_placeholder_safe(self) -> None:
        for path in verify_repo.iter_tree_files(ROOT / "templates" / "local-automation-runtime"):
            if not path.is_file():
                continue
            if "example" not in path.name:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertIn("OWNER", text, path)

    def test_atlas_deployed_validation_example_includes_mvp_evidence_lanes(self) -> None:
        path = ROOT / "examples" / "atlasmemory" / "local-automation-runtime" / "config" / "deployed-validation.example.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        org = "Atlas-" "Memory-Framework"

        azure = data[f"{org}/Atlas-Memory-Azure"]
        azure_workflows = [item["workflow"] for item in azure["workflows"]]
        self.assertIn("deploy-candidate.yml", azure_workflows)
        self.assertIn("deploy-dev-sequence.yml", azure_workflows)
        self.assertIn("deployed-e2e.yml", azure_workflows)
        self.assertIn("include_drafting_parity", json.dumps(azure))
        self.assertIn("include_operator_walkthrough", json.dumps(azure))

        admin = json.dumps(data[f"{org}/Atlas-Memory-Admin-UI"]).lower()
        chainlit = json.dumps(data[f"{org}/Atlas-Memory-Chainlit"]).lower()
        self.assertIn("playwright", admin)
        self.assertIn("playwright", chainlit)


if __name__ == "__main__":
    unittest.main()
