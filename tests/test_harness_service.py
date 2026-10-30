from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import harness_service as service  # noqa: E402
import harnesslib  # noqa: E402


class HarnessServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.registry = self.root / "harness.json"
        self.write_registry()
        self.api = service.HarnessService(self.registry)
        self.validator = patch.object(service, "validate_runtime_path", side_effect=lambda path: Path(path).resolve(strict=True))
        self.validator.start()
        self.addCleanup(self.validator.stop)

    def write_registry(self, **overrides):
        data = {"version": 1, "runtimes": [{"id": "fixture", "provider": "github", "runtime_dir": str(self.runtime)}], "installations": []}
        data.update(overrides)
        self.registry.write_text(json.dumps(data))

    def status(self, data, name="shift-20261029-status.json"):
        jobs = self.runtime / "jobs"
        jobs.mkdir(exist_ok=True)
        path = jobs / name
        path.write_text(json.dumps(data))
        return path

    def test_discover_is_read_only_and_does_not_load_shell_config(self):
        sentinel = self.runtime / "config.env"
        sentinel.write_text("DO_NOT_LOAD=private-sentinel\n")
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with patch.object(subprocess, "run", side_effect=AssertionError("no subprocess")), patch.object(subprocess, "Popen", side_effect=AssertionError("no subprocess")):
            result = self.api.discover()
        after = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(result["read_only"])
        self.assertEqual(result["runtimes"][0]["id"], "fixture")
        self.assertNotIn("private-sentinel", json.dumps(result))
        self.assertIn("source_fingerprint", result)

    def test_missing_registry_is_actionable_without_creation(self):
        self.registry.unlink()
        report = self.api.discover()
        self.assertEqual(report["runtimes"], [])
        self.assertEqual(report["next_actions"][0]["operation"], "configure_registry")
        self.assertFalse(self.registry.exists())

    def test_unknown_runtime_is_a_domain_error(self):
        with self.assertRaisesRegex(service.HarnessServiceError, "not registered"):
            self.api.inspect("missing")

    def test_registry_rejects_duplicate_keys_nonfinite_and_wrong_types(self):
        for data in [
            '{"version":1,"version":1,"runtimes":[]}',
            '{"version":1,"runtimes":[],"anything":NaN}',
            json.dumps({"version": True, "runtimes": []}),
            json.dumps({"version": 1, "runtimes": [{"id": "safe", "provider": {}, "runtime_dir": str(self.runtime)}]}),
            json.dumps({"version": 1, "runtimes": [], "installations": [{"target": str(self.runtime), "harness": {}}]}),
        ]:
            with self.subTest(data=data):
                self.registry.write_text(data)
                result = self.api.discover()
                self.assertTrue(result["blockers"])
                self.assertEqual(result["runtimes"], [])

    def test_duplicate_ids_and_extra_fields_are_rejected(self):
        entry = {"id": "duplicate", "provider": "github", "runtime_dir": str(self.runtime)}
        self.write_registry(runtimes=[entry, entry])
        self.assertEqual(self.api.discover()["blockers"][0]["code"], "invalid_registry")
        self.write_registry(runtimes=[{**entry, "command": "do not run"}])
        self.assertEqual(self.api.discover()["blockers"][0]["code"], "invalid_registry")

    def test_invalid_runtime_is_reported_per_registration(self):
        with patch.object(service, "validate_runtime_path", side_effect=service.RuntimeConfigError("private error text")):
            result = self.api.discover()
        self.assertFalse(result["runtimes"][0]["available"])
        self.assertEqual(result["runtimes"][0]["blockers"][0]["code"], "invalid_runtime")
        self.assertNotIn("private error text", json.dumps(result))

    def test_source_template_is_never_an_installed_runtime(self):
        self.write_registry(runtimes=[{"id": "fixture", "provider": "github", "runtime_dir": str(ROOT / "templates/local-automation-runtime")}])
        self.assertEqual(self.api.discover()["runtimes"][0]["blockers"][0]["code"], "source_template")

    def test_parent_traversal_and_relative_runtime_are_rejected(self):
        for location in ["relative", str(self.runtime / ".." / "runtime")]:
            self.write_registry(runtimes=[{"id": "fixture", "provider": "github", "runtime_dir": location}])
            self.assertEqual(self.api.discover()["runtimes"], [])

    def test_azure_requires_explicit_configuration(self):
        self.write_registry(runtimes=[{"id": "fixture", "provider": "azure-devops", "runtime_dir": str(self.runtime)}])
        self.assertEqual(self.api.discover()["runtimes"][0]["blockers"][0]["code"], "missing_config")

    def test_runtime_configuration_cannot_be_shell_environment(self):
        self.write_registry(runtimes=[{"id": "fixture", "provider": "github", "runtime_dir": str(self.runtime), "config": str(self.runtime / "config.env")}])
        self.assertEqual(self.api.discover()["runtimes"], [])

    def test_no_artifacts_does_not_claim_idle_or_completion(self):
        result = self.api.inspect("fixture")
        self.assertEqual(result["current_work"], [])
        self.assertEqual(result["validation"]["status"], "unverified")
        self.assertEqual(result["blockers"][0]["code"], "no_runtime_evidence")
        self.assertFalse(result["coverage"]["provider_live_read"])

    def test_active_status_is_projected_without_command_or_secret(self):
        updated = datetime.now(timezone.utc).isoformat()
        self.status({"state": "running", "shift_id": "s1", "updated_at": updated, "cycles_completed": 2, "last_command": ["SECRET"], "env": {"TOKEN": "SECRET"}})
        result = self.api.inspect("fixture")
        self.assertEqual(result["current_work"][0]["state"], "running")
        self.assertTrue(result["current_work"][0]["fresh"])
        self.assertIn("active_run", [blocker["code"] for blocker in result["blockers"]])
        self.assertNotIn("SECRET", json.dumps(result))

    def test_stale_active_record_blocks_overlap(self):
        updated = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.status({"state": "running", "updated_at": updated})
        result = self.api.inspect("fixture")
        self.assertFalse(result["current_work"][0]["fresh"])
        self.assertIn("stale_active_evidence", [blocker["code"] for blocker in result["blockers"]])
        self.assertEqual(result["next_actions"][0]["operation"], "review_runtime_evidence")

    def test_terminal_record_is_evidence_not_accepted_completion(self):
        self.status({"state": "completed", "updated_at": datetime.now(timezone.utc).isoformat(), "last_returncode": 0})
        result = self.api.inspect("fixture")
        self.assertEqual(result["evidence"][0]["state"], "completed")
        self.assertEqual(result["validation"]["status"], "unverified")
        self.assertNotIn("completion", result)

    def test_newer_terminal_heartbeat_supersedes_active_status_for_same_shift(self):
        now = datetime.now(timezone.utc)
        self.status({"shift_id": "one", "state": "running", "updated_at": (now - timedelta(hours=1)).isoformat()}, "shift-one-status.json")
        self.status({"shift_id": "one", "state": "completed", "updated_at": now.isoformat()}, "atlas-agent-shift-heartbeat.json")
        report = self.api.inspect("fixture")
        self.assertEqual(len(report["evidence"]), 2)
        self.assertEqual(report["current_work"], [])
        self.assertNotIn("stale_active_evidence", [item["code"] for item in report["blockers"]])
        self.assertNotIn("active_run", [item["code"] for item in report["blockers"]])

    def test_older_terminal_heartbeat_does_not_suppress_newer_active_status(self):
        now = datetime.now(timezone.utc)
        self.status({"shift_id": "one", "state": "running", "updated_at": now.isoformat()}, "shift-one-status.json")
        self.status({"shift_id": "one", "state": "completed", "updated_at": (now - timedelta(hours=1)).isoformat()}, "atlas-agent-shift-heartbeat.json")
        report = self.api.inspect("fixture")
        self.assertEqual(len(report["current_work"]), 1)
        self.assertEqual(report["current_work"][0]["state"], "running")
        self.assertIn("active_run", [item["code"] for item in report["blockers"]])

    def test_terminal_other_shift_does_not_suppress_active_identity(self):
        now = datetime.now(timezone.utc)
        self.status({"shift_id": "one", "state": "running", "updated_at": (now - timedelta(hours=1)).isoformat()}, "shift-one-status.json")
        self.status({"shift_id": "two", "state": "completed", "updated_at": now.isoformat()}, "atlas-agent-shift-heartbeat.json")
        report = self.api.inspect("fixture")
        self.assertEqual(report["current_work"][0]["shift_id"], "one")
        self.assertIn("stale_active_evidence", [item["code"] for item in report["blockers"]])

    def test_missing_identity_terminal_does_not_suppress_unknown_active_file(self):
        now = datetime.now(timezone.utc)
        self.status({"state": "running", "updated_at": (now - timedelta(hours=1)).isoformat()}, "shift-one-status.json")
        self.status({"state": "completed", "updated_at": now.isoformat()}, "atlas-agent-shift-heartbeat.json")
        report = self.api.inspect("fixture")
        self.assertEqual(len(report["current_work"]), 1)
        self.assertIsNone(report["current_work"][0]["shift_id"])
        self.assertIn("stale_active_evidence", [item["code"] for item in report["blockers"]])

    def test_equal_time_contradictory_states_require_reconciliation(self):
        now = datetime.now(timezone.utc).isoformat()
        self.status({"shift_id": "one", "state": "running", "updated_at": now}, "shift-one-status.json")
        self.status({"shift_id": "one", "state": "completed", "updated_at": now}, "atlas-agent-shift-heartbeat.json")
        report = self.api.inspect("fixture")
        self.assertEqual(len(report["current_work"]), 1)
        self.assertIn("contradictory_runtime_evidence", [item["code"] for item in report["blockers"]])
        self.assertEqual(report["next_actions"][0]["operation"], "review_runtime_evidence")

    def test_matching_equal_time_heartbeat_does_not_duplicate_current_work(self):
        now = datetime.now(timezone.utc).isoformat()
        self.status({"shift_id": "one", "state": "running", "updated_at": now}, "shift-one-status.json")
        self.status({"shift_id": "one", "state": "running", "updated_at": now}, "atlas-agent-shift-heartbeat.json")
        report = self.api.inspect("fixture")
        self.assertEqual(len(report["current_work"]), 1)
        self.assertEqual(report["current_work"][0]["kind"], "shift_status")
        self.assertEqual(len(report["evidence"]), 2)

    def test_undated_active_record_is_not_suppressed_by_dated_terminal(self):
        self.status({"shift_id": "one", "state": "running"}, "shift-one-status.json")
        self.status({"shift_id": "one", "state": "completed", "updated_at": datetime.now(timezone.utc).isoformat()}, "atlas-agent-shift-heartbeat.json")
        report = self.api.inspect("fixture")
        self.assertEqual(len(report["current_work"]), 1)
        self.assertIn("stale_active_evidence", [item["code"] for item in report["blockers"]])

    def test_malformed_state_does_not_crash(self):
        self.status({"state": {"secret": "not returned"}})
        result = self.api.inspect("fixture")
        self.assertEqual(result["evidence"][0]["state"], "unknown")
        self.assertNotIn("not returned", json.dumps(result))

    def test_symlink_artifact_and_jobs_directory_are_rejected(self):
        outside = self.root / "outside.json"
        outside.write_text('{"state":"running","env":"private"}')
        jobs = self.runtime / "jobs"
        jobs.mkdir()
        (jobs / "shift-linked-status.json").symlink_to(outside)
        result = self.api.inspect("fixture")
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["blockers"][0]["code"], "unsafe_path")
        (jobs / "shift-linked-status.json").unlink()
        jobs.rmdir()
        jobs.symlink_to(self.root, target_is_directory=True)
        result = self.api.inspect("fixture")
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["blockers"][0]["code"], "unsafe_path")

    def test_large_artifact_is_not_read(self):
        path = self.status({"state": "running"})
        path.write_bytes(b"x" * (service.MAX_INPUT_BYTES + 1))
        result = self.api.inspect("fixture")
        self.assertEqual(result["blockers"][0]["code"], "input_too_large")

    def test_inspection_directory_work_is_bounded(self):
        jobs = self.runtime / "jobs"
        jobs.mkdir()
        for index in range(12):
            (jobs / f"ignored-{index}").touch()
        with patch.object(service, "MAX_DIRECTORY_ENTRIES", 4):
            result = self.api.inspect("fixture")
        self.assertIn("inspection_truncated", [blocker["code"] for blocker in result["blockers"]])

    def test_generated_installation_current_and_body_edit(self):
        target = self.root / "target"
        target.mkdir()
        harnesslib.install_harness("codex", target)
        result = self.api.installation_status(str(target))
        self.assertEqual(result["status"], "current")
        self.assertEqual(result["counts"]["modified"], 0)
        installed = target / ".codex/skills/local-automation-runtime-operate/SKILL.md"
        installed.write_bytes(installed.read_bytes() + b"\nlocal custom change\n")
        result = self.api.installation_status(str(target))
        self.assertEqual(result["counts"]["modified"], 1)
        action = result["next_actions"][0]
        self.assertFalse(action["requires_authorization"])
        self.assertTrue(action["read_only"])
        self.assertEqual(action["operation"], "retain_local_overrides")
        self.assertEqual(result["actionable_update_count"], 0)
        self.assertEqual(result["local_override_count"], 1)
        self.assertNotIn("argv", action)

    def test_prior_clean_generated_copy_is_stale_not_modified(self):
        target = self.root / "target"
        target.mkdir()
        harnesslib.install_harness("codex", target)
        source = "skills/local-automation-runtime-operate/SKILL.md"
        old = b"---\nname: old\n---\nold generated source\n"
        checksum = hashlib.sha256(old).hexdigest()
        rendered = old.replace(b"---\n", b"---\n" + harnesslib.generated_header(source, "atlas-tools.v1", checksum, "#").encode(), 1)
        (target / ".codex" / source).write_bytes(rendered)
        result = self.api.installation_status(str(target))
        self.assertEqual(result["counts"]["stale"], 1)
        self.assertEqual(result["counts"]["modified"], 0)

    def test_installation_symlink_is_unsafe_and_not_read(self):
        target = self.root / "target"
        target.mkdir()
        harnesslib.install_harness("codex", target)
        installed = target / ".codex/skills/local-automation-runtime-operate/SKILL.md"
        installed.unlink()
        private = self.root / "private"
        private.write_text("sentinel-secret")
        installed.symlink_to(private)
        result = self.api.installation_status(str(target))
        self.assertEqual(result["counts"]["unsafe"], 1)
        self.assertNotIn("sentinel-secret", json.dumps(result))
        action = result["next_actions"][0]
        self.assertEqual(action["operation"], "resolve_installation_conflicts")
        self.assertNotIn("argv", action)
        self.assertNotIn("command", action)

    def test_other_harness_modified_files_require_resolution_without_overwrite_command(self):
        for harness in ("claude", "gemini"):
            with self.subTest(harness=harness):
                target = self.root / harness
                target.mkdir()
                harnesslib.install_harness(harness, target)
                path = target / f".{harness}/skills/local-automation-runtime-operate/SKILL.md"
                path.write_bytes(path.read_bytes() + b"\nlocal edits\n")
                report = self.api.installation_status(str(target), harness)
                self.assertEqual(report["counts"]["modified"], 1)
                action = report["next_actions"][0]
                self.assertEqual(action["operation"], "retain_local_overrides")
                self.assertNotIn("argv", action)
                self.assertNotIn("command", action)

    def test_clean_codex_drift_recommends_only_safe_setup_preview(self):
        target = self.root / "target"
        target.mkdir()
        report = self.api.installation_status(str(target))
        action = report["next_actions"][0]
        self.assertEqual(action["operation"], "preview_installation_update")
        self.assertIn(str(ROOT / "scripts/setup_harness_interface.py"), action["argv"])
        self.assertNotIn("--apply", action["argv"])
        self.assertNotIn("--preserve-local", action["argv"])
        self.assertTrue(action["read_only"])

    def test_mixed_codex_updates_preserve_overrides_then_do_not_repeat_update(self):
        target = self.root / "target"
        target.mkdir()
        harnesslib.install_harness("codex", target)
        modified = target / ".codex/skills/local-automation-runtime-operate/SKILL.md"
        modified.write_bytes(modified.read_bytes() + b"\nlocal edit\n")
        missing = target / ".codex/skills/local-automation-runtime-setup/SKILL.md"
        original = missing.read_bytes()
        missing.unlink()
        report = self.api.installation_status(str(target))
        action = report["next_actions"][0]
        self.assertEqual(report["actionable_update_count"], 1)
        self.assertIn("--preserve-local", action["argv"])
        self.assertIn(str(ROOT / "scripts/setup_harness_interface.py"), action["argv"])
        missing.write_bytes(original)
        report = self.api.installation_status(str(target))
        self.assertEqual(report["actionable_update_count"], 0)
        self.assertEqual(report["next_actions"][0]["operation"], "retain_local_overrides")
        self.assertNotIn("argv", report["next_actions"][0])

    def test_unchanged_stale_observation_returns_concrete_nonlooping_diagnostic(self):
        path = self.status({"shift_id": "one", "state": "running", "updated_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}, "shift-one-status.json")
        lock = self.runtime / "jobs/atlas-agent-shift.lock"
        lock.write_text(json.dumps({"pid": 1234, "created_at": "20261029T120000Z", "secret": "not-returned"}))
        before = {str(item): item.read_bytes() for item in self.runtime.rglob("*") if item.is_file()}
        for _ in range(2):
            report = self.api.inspect("fixture")
            action = report["next_actions"][0]
            self.assertEqual(action["operation"], "review_runtime_evidence")
            self.assertTrue(action["read_only"])
            self.assertIn(str(path), action["evidence_paths"])
            self.assertEqual(action["lock_observation"]["pid"], 1234)
            self.assertEqual(action["lock_observation"]["process_liveness"], "not_observed")
            self.assertTrue(action["expected_new_evidence"])
            self.assertNotIn("not-returned", json.dumps(report))
            self.assertNotIn("argv", action)
            for location in action["evidence_paths"] + action["expected_artifact_paths"]:
                self.assertIn(self.runtime, Path(location).parents)
        self.assertEqual(before, {str(item): item.read_bytes() for item in self.runtime.rglob("*") if item.is_file()})

    def test_truncated_coverage_diagnostic_names_bounded_known_paths(self):
        jobs = self.runtime / "jobs"
        jobs.mkdir()
        for number in range(6):
            (jobs / f"ignored-{number}").touch()
        with patch.object(service, "MAX_DIRECTORY_ENTRIES", 2):
            report = self.api.inspect("fixture")
        action = report["next_actions"][0]
        self.assertEqual(action["operation"], "review_runtime_evidence")
        self.assertTrue(action["coverage"]["limited"])
        self.assertEqual(action["coverage"]["max_directory_entries"], 2)
        self.assertEqual(action["coverage"]["inventory_directory"], str(jobs))
        self.assertEqual(action["evidence_paths"], [])

    def test_diagnostic_does_not_follow_symlinked_shift_lock(self):
        self.status({"state": "running", "updated_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()})
        secret = self.root / "secret.json"
        secret.write_text('{"pid":9876,"secret":"not-returned"}')
        (self.runtime / "jobs/atlas-agent-shift.lock").symlink_to(secret)
        action = self.api.inspect("fixture")["next_actions"][0]
        self.assertEqual(action["lock_observation"]["error"]["code"], "unsafe_path")
        self.assertNotIn("pid", action["lock_observation"])
        self.assertNotIn("not-returned", json.dumps(action))

    def test_cli_discover_uses_explicit_registry(self):
        self.write_registry(runtimes=[])
        result = subprocess.run([sys.executable, str(ROOT / "scripts/harness_service.py"), "--registry", str(self.registry), "discover"], capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], service.SCHEMA_VERSION)
        self.assertEqual(payload["runtimes"], [])
        self.assertEqual(result.stderr, "")

    def test_real_subprocess_inspects_owned_home_fixture_without_validator_patch(self):
        # /tmp is intentionally outside the production runtime boundary.
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".harness-read-canary-") as fixture:
            runtime = Path(fixture)
            (runtime / "jobs").mkdir()
            (runtime / "config.env").write_text("PRIVATE_SENTINEL=never-read\n")
            (runtime / "jobs/shift-canary-status.json").write_text(json.dumps({
                "shift_id": "canary", "state": "completed", "updated_at": datetime.now(timezone.utc).isoformat(),
            }))
            (runtime / "jobs/shift-canary-handoff.md").write_text("private handoff body not returned")
            self.write_registry(runtimes=[{"id": "canary", "provider": "github", "runtime_dir": str(runtime)}])
            before = {str(path): path.read_bytes() for path in runtime.rglob("*") if path.is_file()}
            result = subprocess.run([sys.executable, str(ROOT / "scripts/harness_service.py"), "--registry", str(self.registry), "inspect", "canary"], capture_output=True, text=True, check=True)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["evidence"][0]["state"], "completed")
            self.assertTrue(payload["evidence"][0]["handoff_path"].endswith("shift-canary-handoff.md"))
            self.assertNotIn("private handoff body", result.stdout)
            self.assertNotIn("never-read", result.stdout)
            self.assertEqual(before, {str(path): path.read_bytes() for path in runtime.rglob("*") if path.is_file()})

    def test_future_active_timestamp_is_not_fresh(self):
        self.status({"state": "running", "updated_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()})
        result = self.api.inspect("fixture")
        self.assertFalse(result["current_work"][0]["fresh"])
        self.assertIn("stale_active_evidence", [blocker["code"] for blocker in result["blockers"]])

    def test_passwd_home_alias_is_canonicalized_before_runtime_validation(self):
        from types import SimpleNamespace
        canonical = self.root / "canonical-home"
        canonical.mkdir()
        (canonical / "runtime").mkdir()
        alias = self.root / "home-alias"
        alias.symlink_to(canonical, target_is_directory=True)
        self.write_registry(runtimes=[{"id": "alias", "provider": "github", "runtime_dir": str(alias / "runtime")}])
        with patch.object(service.pwd, "getpwuid", return_value=SimpleNamespace(pw_dir=str(alias))):
            with patch.object(service, "validate_runtime_path", return_value=canonical / "runtime") as validator:
                self.api.get_runtime("alias")
        validator.assert_called_once_with(canonical / "runtime")

    def test_invalid_cli_inspect_is_structured_error(self):
        self.write_registry(runtimes=[])
        result = subprocess.run([sys.executable, str(ROOT / "scripts/harness_service.py"), "--registry", str(self.registry), "inspect", "missing"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "unknown_runtime")
        self.assertEqual(result.stderr, "")

    def test_inspection_recovers_active_interface_run_and_blocks_overlap(self):
        recent = {"runs": [{"run_id": "run-" + "a" * 32, "status": "running", "cursor": 2}], "truncated": False, "blockers": []}
        with patch.object(self.api, "_interface_runs", return_value=recent):
            result = self.api.inspect("fixture")
        self.assertIn("interface_run_active", {item["code"] for item in result["blockers"]})
        self.assertEqual(result["next_actions"][0], {"operation": "wait", "run_id": "run-" + "a" * 32, "cursor": 2})
        self.assertNotIn("prepare", {item["operation"] for item in result["next_actions"]})

    def test_discovery_recovers_run_ids_even_if_runtime_configuration_is_unavailable(self):
        recent = {"runs": [{"run_id": "run-" + "b" * 32, "status": "unknown", "cursor": 1}], "truncated": False, "blockers": []}
        with patch.object(self.api, "get_runtime", side_effect=service.HarnessServiceError("invalid_config", "Configuration unavailable.")), \
                patch.object(self.api, "_interface_runs", return_value=recent):
            result = self.api.discover()
        runtime = result["runtimes"][0]
        self.assertFalse(runtime["available"])
        self.assertEqual(runtime["interface_runs"]["runs"][0]["run_id"], "run-" + "b" * 32)


if __name__ == "__main__":
    unittest.main()
