from __future__ import annotations

import json
import os
import signal
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harness_execution
import harness_runs
from harness_service import HarnessServiceError


class FixtureService:
    def __init__(self, root: Path):
        self.registry = root / "registry.json"
        self.root = root
        self.capabilities = ["local_execute"]

    def _envelope(self, **payload):
        return {"schema_version": "atlas-tools.harness.v1", "read_only": True, **payload}

    def get_runtime(self, runtime_id):
        return {"id": runtime_id, "runtime_dir": str(self.root),
                "configuration": {"capabilities": self.capabilities}}


class HarnessRunsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.service = FixtureService(self.root)
        self.runs = harness_runs.HarnessRuns(self.service, self.root / "runs")
        self.run_ids = []
        self.addCleanup(self.stop_remaining)

    def proposal(self, code="print('fixture output')", **overrides):
        worker = self.root / ("worker-" + str(time.time_ns()) + ".py")
        worker.write_text(code + "\n")
        proposal = {"runtime_id": "fixture", "operation": "github-cycle", "provider": "github",
                    "runtime_dir": str(self.root), "options": {}, "argv": [sys.executable, str(worker)],
                    "cwd": str(self.root), "targets": ["fixture/repository"],
                    "effects": ["isolated fixture only"], "budgets": {"max_minutes": 1},
                    "bindings": {}, "required_authorization": {"granted": False}, "blockers": []}
        proposal.update(overrides)
        return {"status": "prepared", "proposal_id": harness_execution.proposal_digest(proposal), "proposal": proposal}

    def start(self, prepared):
        with patch.object(harness_execution.HarnessExecution, "prepare", return_value=prepared):
            result = self.runs.start("fixture", prepared["proposal_id"], authorization_ref="test-host-approval:fixture")
        self.run_ids.append(result["run_id"])
        return result

    def until_terminal(self, run_id, timeout=8):
        deadline = time.monotonic() + timeout
        result = None
        while time.monotonic() < deadline:
            result = self.runs.wait(run_id)
            if result["run"]["status"] in harness_runs.TERMINAL:
                return result
            time.sleep(0.05)
        self.fail(f"fixture did not terminate: {result}")

    def until_running(self, run_id):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            result = self.runs.wait(run_id)
            if result["run"]["status"] == "running":
                return result
            time.sleep(0.02)
        self.fail("fixture supervisor did not start")

    def stop_remaining(self):
        for run_id in self.run_ids:
            try:
                result = self.runs.wait(run_id)
                if result["run"]["status"] not in harness_runs.TERMINAL:
                    self.runs.cancel(run_id)
                    self.until_terminal(run_id)
            except (HarnessServiceError, AssertionError):
                pass

    def test_normal_finish_is_execution_evidence_and_private_output_only(self):
        started = self.start(self.proposal("print('SENTINEL_RAW_OUTPUT_NEVER_RETURNED')"))
        self.assertFalse(started["read_only"])
        result = self.until_terminal(started["run_id"])
        self.assertEqual(result["run"]["status"], "stopped")
        self.assertEqual(result["run"]["process_exit_code"], 0)
        self.assertFalse(result["run"]["completion"])
        self.assertFalse(result["run"]["accepted_progress"])
        self.assertNotIn("SENTINEL_RAW_OUTPUT", json.dumps(result))
        job = self.runs.state_dir / started["run_id"]
        self.assertIn("SENTINEL_RAW_OUTPUT", (job / "worker-output.log").read_text())
        self.assertEqual(stat.S_IMODE(job.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((job / "status.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((job / "worker-output.log").stat().st_mode), 0o600)
        self.assertFalse((self.runs.state_dir / "fixture.lock").exists())

    def test_failure_is_not_accepted_and_does_not_leak_output(self):
        started = self.start(self.proposal("import sys\nprint('sensitive fixture stderr',file=sys.stderr)\nsys.exit(7)"))
        result = self.until_terminal(started["run_id"])
        self.assertEqual(result["run"]["status"], "failed")
        self.assertEqual(result["run"]["process_exit_code"], 7)
        self.assertNotIn("sensitive fixture", json.dumps(result))

    def test_restart_observation_cursor_and_read_only_wait(self):
        started = self.start(self.proposal("import time\ntime.sleep(0.5)"))
        run_id = started["run_id"]
        observed = self.until_running(run_id)
        restarted = harness_runs.HarnessRuns(self.service, self.runs.state_dir)
        before = (self.runs.state_dir / run_id / "status.json").read_bytes()
        result = restarted.wait(run_id, cursor=observed["cursor"], timeout_seconds=0)
        self.assertFalse(result["changed"])
        self.assertTrue(result["read_only"])
        self.assertEqual((self.runs.state_dir / run_id / "status.json").read_bytes(), before)
        result = restarted.wait(run_id, cursor=result["cursor"], timeout_seconds=3)
        self.assertTrue(result["changed"])
        self.assertEqual(result["run"]["status"], "stopped")

    def test_duplicate_runtime_overlap_is_blocked_then_next_run_allowed(self):
        prepared = self.proposal("import time\ntime.sleep(20)")
        started = self.start(prepared)
        self.until_running(started["run_id"])
        with self.assertRaises(HarnessServiceError) as caught:
            self.start(prepared)
        self.assertEqual(caught.exception.code, "runtime_busy")
        self.runs.cancel(started["run_id"])
        self.until_terminal(started["run_id"])
        second = self.start(self.proposal())
        self.assertNotEqual(started["run_id"], second["run_id"])
        self.until_terminal(second["run_id"])

    def test_cancel_is_durable_and_terminates_owned_group(self):
        started = self.start(self.proposal("import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(30)"))
        run_id = started["run_id"]
        self.until_running(run_id)
        result = self.runs.cancel(run_id)
        self.assertTrue(result["cancellation_requested"])
        self.assertTrue((self.runs.state_dir / run_id / "cancel.json").exists())
        result = self.until_terminal(run_id)
        self.assertEqual(result["run"]["status"], "cancelled")
        self.assertIn(result["run"]["process_exit_code"], {-signal.SIGTERM, -signal.SIGKILL})
        self.assertFalse(result["run"]["completion"])
        before = (self.runs.state_dir / run_id / "status.json").read_bytes()
        result = self.runs.cancel(run_id)
        self.assertTrue(result["already_terminal"])
        self.assertEqual((self.runs.state_dir / run_id / "status.json").read_bytes(), before)

    def test_hard_timeout_private_fixture_override(self):
        prepared = self.proposal("import time\ntime.sleep(30)")
        job = self.root / "timeout-job"
        job.mkdir(mode=0o700)
        result = harness_runs._run_worker(job, prepared["proposal"], wall_seconds=0.1)
        self.assertEqual(result["status"], "timed_out")
        self.assertLess(result["elapsed_seconds"], 5)
        self.assertIn(result["process_exit_code"], {-signal.SIGTERM, -signal.SIGKILL})

    def test_bounded_log_is_drained_without_deadlock(self):
        started = self.start(self.proposal("import sys\nsys.stdout.write('x'*2000000)\nsys.stdout.flush()"))
        result = self.until_terminal(started["run_id"])
        self.assertEqual(result["run"]["status"], "stopped")
        self.assertTrue(result["run"]["output_truncated"])
        self.assertEqual(result["run"]["stored_output_bytes"], harness_runs.MAX_LOG_BYTES)
        self.assertEqual(result["run"]["output_bytes"], 2000000)
        self.assertEqual((self.runs.state_dir / started["run_id"] / "worker-output.log").stat().st_size, harness_runs.MAX_LOG_BYTES)

    def test_stale_proposal_denied_capability_and_missing_approval_write_nothing(self):
        prepared = self.proposal()
        with patch.object(harness_execution.HarnessExecution, "prepare", return_value=prepared):
            with self.assertRaises(HarnessServiceError) as caught:
                self.runs.start("fixture", "sha256:stale", authorization_ref="test-approval")
            self.assertEqual(caught.exception.code, "stale_proposal")
            self.service.capabilities = ["read"]
            with self.assertRaises(HarnessServiceError) as caught:
                self.runs.start("fixture", prepared["proposal_id"], authorization_ref="test-approval")
            self.assertEqual(caught.exception.code, "execution_disabled")
            with self.assertRaises(HarnessServiceError) as caught:
                self.runs.start("fixture", prepared["proposal_id"])
            self.assertEqual(caught.exception.code, "missing_authorization_reference")
        self.assertFalse(self.runs.state_dir.exists())

    def test_blocked_or_unbounded_proposal_is_never_launched(self):
        for prepared in (self.proposal(blockers=[{"code": "fixture-blocked"}]),
                         self.proposal(budgets={"max_minutes": 31}),
                         self.proposal(operation="arbitrary-command"),
                         self.proposal(cwd="/tmp")):
            with self.subTest(proposal=prepared["proposal"]):
                with self.assertRaises(HarnessServiceError):
                    self.start(prepared)
        self.assertFalse(self.runs.state_dir.exists())

    def test_orphaned_supervisor_is_unknown_and_does_not_reclaim_lock(self):
        root = self.runs._root(create=True)
        run_id = "run-" + "a" * 32
        job = root / run_id
        job.mkdir(mode=0o700)
        data = {"schema_version": harness_runs.RUN_SCHEMA, "run_id": run_id, "runtime_id": "fixture",
                "proposal_id": "sha256:" + "a" * 64, "status": "running", "cursor": 2,
                "created_at": "2020-01-01T00:00:00Z", "updated_at": "2020-01-01T00:00:00Z",
                "supervisor": {"pid": os.getpid(), "start_ticks": 0}}
        harness_runs._atomic(job / "status.json", data, root)
        lock = root / "fixture.lock"
        lock.write_text(run_id + "\n")
        result = self.runs.wait(run_id)
        self.assertEqual(result["run"]["status"], "unknown")
        self.assertEqual(result["run"]["recorded_status"], "running")
        self.assertTrue(lock.exists())
        with self.assertRaises(HarnessServiceError) as caught:
            self.start(self.proposal())
        self.assertEqual(caught.exception.code, "runtime_busy")

    def test_state_symlinks_hardlinks_and_parent_symlinks_are_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.root / "link"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HarnessServiceError):
            harness_runs.HarnessRuns(self.service, link / "runs")
        root = self.runs._root(create=True)
        run_id = "run-" + "b" * 32
        job = root / run_id
        job.mkdir()
        source = self.root / "source.json"
        source.write_text("{}")
        (job / "status.json").symlink_to(source)
        with self.assertRaises(HarnessServiceError):
            self.runs.wait(run_id)
        (job / "status.json").unlink()
        os.link(source, job / "status.json")
        with self.assertRaises(HarnessServiceError):
            self.runs.wait(run_id)

    def test_unknown_run_invalid_cursor_and_wait_bounds(self):
        for run_id in ("../outside", "run-wrong"):
            with self.assertRaises(HarnessServiceError):
                self.runs.wait(run_id)
        with self.assertRaises(HarnessServiceError) as caught:
            self.runs.wait("run-" + "c" * 32)
        self.assertEqual(caught.exception.code, "unknown_run")
        for timeout in (-1, 31, True, float("nan")):
            with self.assertRaises(HarnessServiceError):
                self.runs.wait("run-" + "c" * 32, timeout_seconds=timeout)
        for cursor in (-1, True, "wrong"):
            with self.assertRaises(HarnessServiceError):
                self.runs.wait("run-" + "c" * 32, cursor=cursor)

    def test_supervisor_launch_failure_is_durable_and_releases_lock(self):
        prepared = self.proposal()
        with patch.object(harness_execution.HarnessExecution, "prepare", return_value=prepared), \
                patch.object(harness_runs.subprocess, "Popen", side_effect=OSError("SENTINEL_INTERNAL_PATH")):
            with self.assertRaises(HarnessServiceError) as caught:
                self.runs.start("fixture", prepared["proposal_id"], authorization_ref="test-host-approval")
        self.assertEqual(caught.exception.code, "supervisor_launch_failed")
        self.assertNotIn("SENTINEL", str(caught.exception))
        self.assertFalse((self.runs.state_dir / "fixture.lock").exists())
        records = list(self.runs.state_dir.glob("run-*/status.json"))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())["status"], "failed")

    def descendants_fixture(self, pidfile):
        grandchild = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"
        return ("import os,signal,subprocess,sys,time\nfrom pathlib import Path\n"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                f"child=subprocess.Popen([sys.executable,'-c',{grandchild!r}])\n"
                f"Path({str(pidfile)!r}).write_text(str(os.getpid())+' '+str(child.pid))\n"
                "time.sleep(30)")

    def descendant_identities(self, pidfile):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if pidfile.exists():
                pids = [int(part) for part in pidfile.read_text().split()]
                identities = [harness_runs._process_identity(pid) for pid in pids]
                if len(identities) == 2 and all(identities):
                    return identities
            time.sleep(0.02)
        self.fail("worker and descendant fixture did not become live")

    def assert_processes_stopped(self, identities):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            # A killed orphan may remain a zombie until the host's init reaps
            # it. Birth identity excludes zombies and prevents PID reuse from
            # making a different process look like the original fixture.
            if all(harness_runs._process_identity(identity["pid"]) != identity for identity in identities):
                return
            time.sleep(0.02)
        self.fail("an owned worker-group fixture process remained live")

    def test_cancel_stops_real_worker_and_same_group_grandchild(self):
        pidfile = self.root / "cancel-descendants.pids"
        started = self.start(self.proposal(self.descendants_fixture(pidfile)))
        identities = self.descendant_identities(pidfile)
        self.runs.cancel(started["run_id"])
        result = self.until_terminal(started["run_id"])
        self.assertEqual(result["run"]["status"], "cancelled")
        self.assert_processes_stopped(identities)

    def test_timeout_stops_real_worker_and_same_group_grandchild(self):
        pidfile = self.root / "timeout-descendants.pids"
        proposal = self.proposal(self.descendants_fixture(pidfile))["proposal"]
        job = self.root / "timeout-descendants-job"
        job.mkdir(mode=0o700)
        outcomes = []
        worker = threading.Thread(target=lambda: outcomes.append(harness_runs._run_worker(job, proposal, wall_seconds=0.5)), daemon=True)
        worker.start()
        identities = self.descendant_identities(pidfile)
        worker.join(timeout=7)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcomes[0]["status"], "timed_out")
        self.assert_processes_stopped(identities)

    def test_daemon_reaps_supervisor_without_another_observation(self):
        started = self.start(self.proposal())
        run_id = started["run_id"]
        with self.runs._supervisors_lock:
            handle = self.runs._supervisors[run_id]
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            with self.runs._supervisors_lock:
                retained = run_id in self.runs._supervisors
            if not retained:
                break
            time.sleep(0.02)
        self.assertFalse(retained)
        with self.assertRaises(ChildProcessError):
            os.waitpid(handle.pid, os.WNOHANG)

    def test_recent_recovers_lost_run_id_after_restart_without_writes(self):
        started = self.start(self.proposal())
        self.until_terminal(started["run_id"])
        restarted = harness_runs.HarnessRuns(self.service, self.runs.state_dir)
        before = {str(path): path.read_bytes() for path in self.runs.state_dir.rglob("*") if path.is_file()}
        result = restarted.recent("fixture")
        self.assertTrue(result["read_only"])
        self.assertEqual([entry["run_id"] for entry in result["runs"]], [started["run_id"]])
        self.assertFalse(result["runs"][0]["completion"])
        self.assertFalse(result["truncated"])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.runs.state_dir.rglob("*") if path.is_file()})
        self.assertEqual(restarted.recent("other")["runs"], [])

    def test_recent_empty_state_is_read_only_and_does_not_create_root(self):
        result = self.runs.recent("fixture")
        self.assertEqual(result["runs"], [])
        self.assertFalse(self.runs.state_dir.exists())
        for limit in (0, 33, True, "8"):
            with self.assertRaises(HarnessServiceError):
                self.runs.recent("fixture", limit=limit)

    def test_recent_bounds_scan_and_reports_malformed_or_linked_records_without_contents(self):
        root = self.runs._root(create=True)
        malformed = root / ("run-" + "d" * 32)
        malformed.mkdir()
        (malformed / "status.json").write_text('{"raw":"NEVER_RETURN_THIS_RECORD_CONTENT"}')
        linked = root / ("run-" + "e" * 32)
        linked.symlink_to(malformed, target_is_directory=True)
        result = self.runs.recent("fixture")
        self.assertEqual(result["runs"], [])
        self.assertEqual(len(result["blockers"]), 2)
        self.assertNotIn("NEVER_RETURN", json.dumps(result))
        for index in range(140):
            (root / f"other-file-{index:03}").write_text("unrelated")
        result = self.runs.recent("fixture")
        self.assertLessEqual(result["scanned_entries"], 128)
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
