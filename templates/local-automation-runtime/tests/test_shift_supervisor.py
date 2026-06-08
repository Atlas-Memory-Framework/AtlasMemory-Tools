from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, filename: str):
    path = ROOT / filename
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


class ShiftSupervisorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.shift = load_script("atlas_agent_shift_test", "atlas-agent-shift")

    def test_build_unattended_command_forces_single_cycle(self) -> None:
        command = self.shift.build_unattended_command(["--publish", "--apply", "--review-apply"])

        self.assertIn("atlas-agent-unattended", command[0])
        self.assertEqual(command[1:3], ["--cycles", "1"])
        self.assertIn("--publish", command)
        self.assertIn("--apply", command)
        self.assertNotIn("--", command)

    def test_build_unattended_command_can_force_project_reconcile_checkpoint(self) -> None:
        command = self.shift.build_unattended_command(["--apply"], project_reconcile_checkpoint=True)

        self.assertIn("--project-reconcile-every", command)
        every_index = command.index("--project-reconcile-every") + 1
        self.assertEqual(command[every_index], "1")

    def test_project_reconcile_checkpoint_interval_uses_shift_cycle_number(self) -> None:
        args = self.shift.build_parser().parse_args(["--project-reconcile-every", "3"])

        self.assertFalse(self.shift.project_reconcile_checkpoint_enabled(args, 1))
        self.assertFalse(self.shift.project_reconcile_checkpoint_enabled(args, 2))
        self.assertTrue(self.shift.project_reconcile_checkpoint_enabled(args, 3))

    def test_parse_deadline_accepts_utc_z_suffix(self) -> None:
        deadline = self.shift.parse_deadline("2026-05-23T12:00:00Z")

        self.assertEqual(deadline.tzinfo, timezone.utc)
        self.assertEqual(deadline.year, 2026)
        self.assertEqual(deadline.hour, 12)

    def test_should_not_start_cycle_inside_deadline_guard_band(self) -> None:
        deadline = self.shift.utc_now() + timedelta(seconds=10)

        self.assertFalse(self.shift.should_start_cycle(deadline, stop_before_seconds=30))

    def test_extract_chain_dir_reads_last_unattended_state_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "cycle.log"
            log.write_text(
                "Unattended chain complete. Chain state is /tmp/old\n"
                "Unattended chain complete. Chain state is /tmp/new\n",
                encoding="utf-8",
            )

            self.assertEqual(self.shift.extract_chain_dir(log), "/tmp/new")

    def test_write_status_records_last_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / "status.json"
            cycle = self.shift.ShiftCycle(
                cycle=1,
                status="ok",
                returncode=0,
                started_at="2026-05-23T01:00:00Z",
                finished_at="2026-05-23T01:10:00Z",
                log_file="/tmp/cycle.log",
                chain_dir="/tmp/chain",
            )

            self.shift.write_status(
                status,
                shift_id="shift",
                state="complete",
                started_at="2026-05-23T01:00:00Z",
                deadline=None,
                cycle_limit=1,
                cycles=[cycle],
                last_command=["atlas-agent-unattended", "--cycles", "1"],
                stop_reason="cycle limit reached",
            )

            payload = json.loads(status.read_text(encoding="utf-8"))

        self.assertEqual(payload["state"], "complete")
        self.assertEqual(payload["cycles_completed"], 1)
        self.assertEqual(payload["last_chain_dir"], "/tmp/chain")
        self.assertEqual(payload["stop_reason"], "cycle limit reached")

    def test_handoff_contains_resume_pointers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff.md"
            self.shift.write_handoff(
                handoff,
                shift_id="shift",
                status_file=Path(tmp) / "status.json",
                heartbeat_file=Path(tmp) / "heartbeat.json",
                state="failed",
                stop_reason="cycle 1 returned 1",
                cycles=[],
                next_command=["atlas-agent-shift", "--cycles", "1"],
            )

            text = handoff.read_text(encoding="utf-8")

        self.assertIn("Status file:", text)
        self.assertIn("Heartbeat file:", text)
        self.assertIn("Candidate resume command", text)


if __name__ == "__main__":
    unittest.main()
