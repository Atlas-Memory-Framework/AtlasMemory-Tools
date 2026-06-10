from __future__ import annotations

import json
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


if __name__ == "__main__":
    unittest.main()
