from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import atlas_delta_review as delta_review


class FrozenDeltaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Delta Review Test")
        self.git("config", "user.email", "delta-review@example.invalid")
        (self.repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        (self.repo / "binary-old.bin").write_bytes(bytes(range(256)) * 3)
        self.git("add", "tracked.txt", "binary-old.bin")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        (self.repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
        (self.repo / "new.txt").write_text("new\n", encoding="utf-8")
        self.git("add", "tracked.txt", "new.txt")
        self.git("commit", "-qm", "candidate")
        self.candidate = self.git("rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True).strip()

    def test_freeze_binds_revisions_paths_and_diff(self):
        snapshot = delta_review.freeze_delta(self.repo, self.base, self.candidate)
        self.assertEqual(snapshot["base_revision"], self.base)
        self.assertEqual(snapshot["candidate_revision"], self.candidate)
        self.assertEqual(snapshot["changed_paths"], ["new.txt", "tracked.txt"])
        self.assertEqual(len(snapshot["diff_sha256"]), 64)

    def test_review_must_match_current_frozen_binding(self):
        snapshot = delta_review.freeze_delta(self.repo, self.base, self.candidate)
        review = self.review(snapshot)
        self.assertTrue(delta_review.validate_review(self.repo, snapshot, review)["evidence_valid"])
        review["snapshot"]["candidate_revision"] = self.base
        with self.assertRaisesRegex(delta_review.DeltaReviewError, "stale or bound"):
            delta_review.validate_review(self.repo, snapshot, review)

    def test_review_rejects_advanced_head_even_when_old_commit_is_clean(self):
        snapshot = delta_review.freeze_delta(self.repo, self.base, self.candidate)
        review = self.review(snapshot)
        (self.repo / "later.txt").write_text("later\n", encoding="utf-8")
        self.git("add", "later.txt")
        self.git("commit", "-qm", "advance candidate")
        with self.assertRaisesRegex(delta_review.DeltaReviewError, "not the current HEAD"):
            delta_review.validate_review(self.repo, snapshot, review)

    def test_findings_and_inconclusive_evidence_are_valid_but_never_eligible(self):
        snapshot = delta_review.freeze_delta(self.repo, self.base, self.candidate)
        plan, checks = self.checks_result(snapshot)
        for disposition, findings in (("findings", ["blocking defect"]), ("inconclusive", [])):
            with self.subTest(disposition=disposition):
                result = delta_review.validate_pilot_acceptance(self.repo, snapshot, self.review(snapshot, disposition, findings), plan, checks)
                self.assertTrue(result["evidence_valid"])
                self.assertFalse(result["pilot_acceptance_eligible"])

    def test_missing_or_stale_review_evidence_fails_closed(self):
        snapshot = delta_review.freeze_delta(self.repo, self.base, self.candidate)
        plan, checks = self.checks_result(snapshot)
        accepted = delta_review.validate_pilot_acceptance(self.repo, snapshot, self.review(snapshot), plan, checks)
        self.assertTrue(accepted["pilot_acceptance_eligible"])
        with self.assertRaisesRegex(delta_review.DeltaReviewError, "missing or has extra"):
            delta_review.validate_pilot_acceptance(self.repo, snapshot, {}, plan, checks)
        with self.assertRaisesRegex(delta_review.DeltaReviewError, "same-snapshot check results are missing"):
            delta_review.validate_pilot_acceptance(self.repo, snapshot, self.review(snapshot), plan, {})
        with self.assertRaisesRegex(delta_review.DeltaReviewError, "different delta"):
            delta_review.validate_pilot_acceptance(self.repo, snapshot, self.review(snapshot), plan, {**checks, "snapshot": {**checks["snapshot"], "candidate_revision": self.base}})

    def test_exact_plan_binds_argv_timeout_capability_and_multiple_checks_per_lane(self):
        snapshot = delta_review.freeze_delta(self.repo, self.base, self.candidate)
        plan, checks = self.checks_result(snapshot, multiple=True)
        self.assertTrue(delta_review.validate_pilot_acceptance(self.repo, snapshot, self.review(snapshot), plan, checks)["pilot_acceptance_eligible"])
        with self.assertRaisesRegex(delta_review.DeltaReviewError, "include code, environment and test lanes"):
            delta_review.validate_pilot_acceptance(self.repo, snapshot, self.review(snapshot),
                [plan[-1]], {**checks, "results": [checks["results"][-1]]})
        for field, replacement in (("argv", [sys.executable, "-c", "pass # substituted"]), ("timeout_seconds", 31), ("capability", "substituted capability")):
            altered = {**checks, "results": [dict(item) for item in checks["results"]]}
            altered["results"][0][field] = replacement
            with self.subTest(field=field), self.assertRaisesRegex(delta_review.DeltaReviewError, "does not match"):
                delta_review.validate_pilot_acceptance(self.repo, snapshot, self.review(snapshot), plan, altered)

    def test_plan_and_terminal_null_or_missing_fields_fail_closed(self):
        snapshot = delta_review.freeze_delta(self.repo, self.base, self.candidate)
        plan, checks = self.checks_result(snapshot)
        with self.assertRaisesRegex(delta_review.DeltaReviewError, "nonempty check plan"):
            delta_review.validate_pilot_acceptance(self.repo, snapshot, self.review(snapshot), [], checks)
        for shortened in (checks["results"][:-1], checks["results"] + [checks["results"][-1]]):
            with self.subTest(result_count=len(shortened)), self.assertRaisesRegex(delta_review.DeltaReviewError, "exactly cover"):
                delta_review.validate_pilot_acceptance(self.repo, snapshot, self.review(snapshot), plan,
                    {**checks, "results": shortened})
        for field, value in (("returncode", None), ("timed_out", None), ("status", None), ("argv", None), ("timeout_seconds", None)):
            altered = {**checks, "results": [dict(checks["results"][0]), *checks["results"][1:]]}
            altered["results"][0][field] = value
            with self.subTest(field=field), self.assertRaises(delta_review.DeltaReviewError):
                delta_review.validate_pilot_acceptance(self.repo, snapshot, self.review(snapshot), plan, altered)

    def test_rename_inventory_includes_both_paths_and_binary_changes_affect_binding(self):
        self.git("mv", "binary-old.bin", "binary-new.bin")
        content = bytearray((self.repo / "binary-new.bin").read_bytes())
        content[-1] ^= 0x01
        (self.repo / "binary-new.bin").write_bytes(content)
        self.git("add", "-A")
        self.git("commit", "-qm", "rename binary")
        first = self.git("rev-parse", "HEAD")
        manifest_one = delta_review.freeze_delta(self.repo, self.base, first)
        self.assertIn("binary-old.bin", manifest_one["changed_paths"])
        self.assertIn("binary-new.bin", manifest_one["changed_paths"])
        content[-2] ^= 0x01
        (self.repo / "binary-new.bin").write_bytes(content)
        self.git("add", "binary-new.bin")
        self.git("commit", "-qm", "change binary payload")
        second = self.git("rev-parse", "HEAD")
        manifest_two = delta_review.freeze_delta(self.repo, self.base, second)
        self.assertEqual(manifest_one["changed_paths"], manifest_two["changed_paths"])
        self.assertNotEqual(manifest_one["diff_sha256"], manifest_two["diff_sha256"])

    def test_dirty_candidate_cannot_be_frozen(self):
        snapshot = delta_review.freeze_delta(self.repo, self.base, self.candidate)
        review = self.review(snapshot)
        (self.repo / "tracked.txt").write_text("uncommitted\n", encoding="utf-8")
        with self.assertRaisesRegex(delta_review.DeltaReviewError, "must be clean"):
            delta_review.validate_review(self.repo, snapshot, review)
        with self.assertRaisesRegex(delta_review.DeltaReviewError, "must be clean"):
            delta_review.freeze_delta(self.repo, self.base, self.candidate)

    def test_checks_order_by_lane_and_failure_class_stays_explicit(self):
        checks = [
            {"id": "unit", "lane": "test", "argv": [sys.executable, "-c", "pass"]},
            {"id": "fd", "lane": "environment", "capability": "file descriptor passing", "argv": [sys.executable, "-c", "pass"]},
            {"id": "ruff", "lane": "code", "argv": [sys.executable, "-c", "pass"]},
        ]
        self.assertEqual([item["id"] for item in delta_review.ordered_checks(checks)], ["ruff", "fd", "unit"])
        self.assertEqual(delta_review.classify_failure("environment", capability_supported=False), "environment_blocked")
        self.assertEqual(delta_review.classify_failure("test"), "test_failure")
        self.assertEqual(delta_review.classify_failure("code"), "code_failure")

    def test_ordered_checks_actually_run_code_then_environment_then_tests(self):
        snapshot = delta_review.freeze_delta(self.repo, self.base, self.candidate)
        checks = [
            {"id": "test", "lane": "test", "argv": [sys.executable, "-c", "print('test')"]},
            {"id": "env", "lane": "environment", "capability": "fd passing", "argv": [sys.executable, "-c", "print('env')"]},
            {"id": "lint", "lane": "code", "argv": [sys.executable, "-c", "print('code')"]},
        ]
        result = delta_review.run_ordered_checks(self.repo, snapshot, checks)
        self.assertTrue(result["passed"])
        self.assertEqual([item["id"] for item in result["results"]], ["lint", "env", "test"])

    def test_environment_failure_reports_named_unsupported_capability(self):
        snapshot = delta_review.freeze_delta(self.repo, self.base, self.candidate)
        checks = [{"id": "fd-probe", "lane": "environment", "capability": "file descriptor passing", "argv": [sys.executable, "-c", "raise SystemExit(77)"]}]
        result = delta_review.run_ordered_checks(self.repo, snapshot, checks)
        self.assertFalse(result["passed"])
        self.assertEqual(result["results"][0]["failure_class"], "environment_blocked")
        self.assertEqual(result["results"][0]["unsupported_capability"], "file descriptor passing")

    def test_metrics_are_snapshot_bound_operator_reports_with_monotonic_events(self):
        snapshot = delta_review.freeze_delta(self.repo, self.base, self.candidate)
        started = datetime.fromisoformat(snapshot["created_at"]) + timedelta(seconds=1)
        start = started.isoformat()
        metrics = delta_review.new_metrics(snapshot, start)
        metrics = delta_review.record_metric_event(metrics, "useful_finding", snapshot, (started + timedelta(seconds=5)).isoformat())
        metrics = delta_review.record_metric_event(metrics, "useful_finding", snapshot, (started + timedelta(seconds=8)).isoformat())
        metrics = delta_review.record_metric_event(metrics, "rework", snapshot, (started + timedelta(seconds=10)).isoformat())
        metrics = delta_review.record_metric_event(metrics, "accepted", snapshot, (started + timedelta(seconds=20)).isoformat())
        self.assertEqual(metrics["first_useful_finding_seconds"], 5.0)
        self.assertEqual(metrics["rework_count"], 1)
        self.assertEqual(metrics["total_acceptance_seconds"], 20.0)
        with self.assertRaisesRegex(delta_review.DeltaReviewError, "chronology moves backwards"):
            delta_review.record_metric_event(metrics, "rework", snapshot, (started + timedelta(seconds=19)).isoformat())
        with self.assertRaisesRegex(delta_review.DeltaReviewError, "different delta"):
            delta_review.record_metric_event(metrics, "rework", {**snapshot, "candidate_revision": self.base})

    def review(self, snapshot, disposition="clear", findings=None):
        return {
            "snapshot": {key: snapshot[key] for key in ("base_revision", "candidate_revision", "changed_paths", "diff_sha256")},
            "reviewer": "operator-supplied",
            "reviewed_at": (datetime.fromisoformat(snapshot["created_at"]) + timedelta(seconds=1)).isoformat(),
            "findings": findings or [],
            "disposition": disposition,
        }

    def checks_result(self, snapshot, multiple=False):
        start = datetime.fromisoformat(snapshot["created_at"]) + timedelta(seconds=2)
        results = []
        lanes = ("code", "code", "environment", "test") if multiple else ("code", "environment", "test")
        plan = []
        for index, lane in enumerate(lanes):
            began = start + timedelta(seconds=2 * index)
            ended = began + timedelta(seconds=1)
            check = {"id": f"{lane}-check-{index}", "lane": lane, "argv": [sys.executable, "-c", "pass"], "timeout_seconds": 30}
            if lane == "environment":
                check["capability"] = "environment fixture"
            plan.append(check)
            results.append({
                **check, "capability": check.get("capability"),
                "started_at": began.isoformat(), "ended_at": ended.isoformat(), "returncode": 0,
                "timed_out": False, "status": "passed", "output": "",
            })
        return plan, {
            "snapshot": {key: snapshot[key] for key in ("base_revision", "candidate_revision", "changed_paths", "diff_sha256")},
            "results": results, "passed": True, "execution_source": "local_operator_pilot",
        }


if __name__ == "__main__":
    unittest.main()
