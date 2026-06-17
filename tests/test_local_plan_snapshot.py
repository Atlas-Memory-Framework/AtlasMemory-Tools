from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "local-plan-agent-runtime" / "scripts" / "snapshot_plan.py"


def write_plan(path: Path, plan_state: str) -> None:
    plan_state = textwrap.dedent(plan_state).strip()
    path.write_text(
        "# Feature: Snapshot Test\n\n"
        "## Plan State\n"
        f"{plan_state}\n\n"
        "## Problem Definition\n"
        "Problem narrative:\n"
        "Snapshot test.\n",
        encoding="utf-8",
    )


def sha256_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def write_package_manifest(path: Path, source_plan: str, members: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "plan-package-v0",
                "package_id": "pkg-test",
                "source_plan": {"path": source_plan},
                "members": members,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class LocalPlanSnapshotTests(unittest.TestCase):
    def test_snapshot_manifest_records_plan_metadata_and_persona_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "plan.md"
            run_dir = tmp_path / "run"
            write_plan(
                plan,
                """\
                PlanId: snapshot-test
                PlanGroup: atlas
                ParentPlan: P0
                DependsOnPlans: P1
                AtomicScope: snapshot metadata
                """,
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(plan),
                    "--run-dir",
                    str(run_dir),
                    "--persona",
                    "critical-plan-reviewer",
                    "--persona-trigger",
                    "baseline review",
                    "--persona-scope",
                    "whole plan",
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            )

            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["plan_id"], "snapshot-test")
            self.assertEqual(manifest["plan_group"], "atlas")
            self.assertEqual(manifest["parent_plan"], "P0")
            self.assertEqual(manifest["depends_on_plans"], "P1")
            self.assertEqual(manifest["atomic_scope"], "snapshot metadata")
            self.assertEqual(manifest["worker_persona_records"], [
                {"id": "critical-plan-reviewer", "trigger": "baseline review", "scope": "whole plan"}
            ])

    def test_snapshot_rejects_duplicate_plan_state_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "plan.md"
            write_plan(plan, "PlanId: first\nPlanId: second")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(plan), "--run-dir", str(tmp_path / "run")],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate Plan State key: PlanId", result.stderr + result.stdout)

    def test_snapshot_rejects_unknown_persona(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "plan.md"
            write_plan(plan, "PlanId: snapshot-test")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(plan),
                    "--run-dir",
                    str(tmp_path / "run"),
                    "--persona",
                    "not-a-real-persona",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown persona", result.stderr + result.stdout)

    def test_package_snapshot_records_files_and_file_qualified_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "PLAN.md"
            spec = tmp_path / "issues" / "leaf.md"
            spec.parent.mkdir()
            write_plan(plan, "PlanId: package-snapshot")
            spec_text = "# Leaf Spec\n\n## Acceptance\nDone.\n"
            spec.write_text(spec_text, encoding="utf-8")
            manifest = tmp_path / "PACKAGE.json"
            write_package_manifest(
                manifest,
                "PLAN.md",
                [
                    {"path": "PLAN.md", "kind": "plan", "hash": sha256_text(plan.read_text(encoding="utf-8")), "patchable": True},
                    {"path": "issues/leaf.md", "kind": "issue-spec", "hash": sha256_text(spec_text), "patchable": False},
                ],
            )
            run_dir = tmp_path / "run"

            subprocess.run(
                [sys.executable, str(SCRIPT), str(plan), "--package-manifest", str(manifest), "--out", str(run_dir)],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            )

            section_index = json.loads((run_dir / "section-index.json").read_text(encoding="utf-8"))
            manifest_json = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(section_index["package_mode"])
            self.assertRegex(manifest_json["source_package_sha256"], r"^sha256:[a-f0-9]{64}$")
            self.assertEqual(len(section_index["package_files"]), 2)
            self.assertTrue(all(item["sha256"].startswith("sha256:") for item in section_index["package_files"]))
            self.assertTrue(all(section["sha256"].startswith("sha256:") for section in section_index["sections"]))
            self.assertTrue((run_dir / "package.snapshot" / "PLAN.md").is_file())
            self.assertTrue((run_dir / "package.snapshot" / "issues" / "leaf.md").is_file())
            self.assertTrue(all(":" in section["section_id"] for section in section_index["sections"]))
            read_only_sections = [section for section in section_index["sections"] if section["file_path"] == "issues/leaf.md"]
            self.assertTrue(read_only_sections)
            self.assertFalse(read_only_sections[0]["patchable"])

    def test_package_snapshot_rejects_path_traversal_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "PLAN.md"
            write_plan(plan, "PlanId: package-snapshot")
            manifest = tmp_path / "PACKAGE.json"
            write_package_manifest(manifest, "PLAN.md", [{"path": "../outside.md", "kind": "context", "patchable": False}])

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(plan), "--package-manifest", str(manifest), "--out", str(tmp_path / "run")],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("escapes package root", result.stderr + result.stdout)

    def test_package_snapshot_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            outside = tmp_path / "outside.md"
            outside.write_text("# Outside\n", encoding="utf-8")
            package_root = tmp_path / "pkg"
            package_root.mkdir()
            plan = package_root / "PLAN.md"
            link = package_root / "linked.md"
            write_plan(plan, "PlanId: package-snapshot")
            link.symlink_to(outside)
            manifest = package_root / "PACKAGE.json"
            write_package_manifest(manifest, "PLAN.md", [{"path": "PLAN.md"}, {"path": "linked.md", "patchable": False}])

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(plan), "--package-manifest", str(manifest), "--out", str(tmp_path / "run")],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("escapes package root", result.stderr + result.stdout)

    def test_package_snapshot_rejects_manifest_outside_package_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package_root = tmp_path / "pkg"
            package_root.mkdir()
            plan = package_root / "PLAN.md"
            write_plan(plan, "PlanId: package-snapshot")
            manifest = package_root / "PACKAGE.json"
            write_package_manifest(manifest, "../outside.md", [{"path": "PLAN.md"}])

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(plan), "--package-manifest", str(manifest), "--out", str(tmp_path / "run")],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source_plan.path escapes package root", result.stderr + result.stdout)

    def test_package_snapshot_rejects_selected_plan_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "PLAN.md"
            other = tmp_path / "OTHER.md"
            write_plan(plan, "PlanId: package-snapshot")
            write_plan(other, "PlanId: other")
            manifest = tmp_path / "PACKAGE.json"
            write_package_manifest(manifest, "OTHER.md", [{"path": "OTHER.md"}])

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(plan), "--package-manifest", str(manifest), "--out", str(tmp_path / "run")],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source_plan.path does not match selected plan", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
