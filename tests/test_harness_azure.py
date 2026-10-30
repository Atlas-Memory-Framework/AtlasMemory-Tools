from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import harness_azure
from harness_execution import canonical_code_files
from harness_service import HarnessService, HarnessServiceError


class HarnessAzureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".azure-proposal-test-", dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.checkout = self.runtime / "worktrees" / "feature-task"
        self.checkout.mkdir(parents=True)
        for name in canonical_code_files(ROOT):
            shutil.copy2(ROOT / "templates/local-automation-runtime" / name, self.runtime / name)
        self.config = self.root / "remote.json"
        self.url = "https://dev.azure.com/ExampleOrg/ExampleProject/_git/ExampleRepo"
        self.configuration = {
            "schema_version": 1, "provider": "azure-devops", "runtime_dir": str(self.runtime),
            "repository": {"organization": "ExampleOrg", "project": "ExampleProject", "name": "ExampleRepo",
                           "url": self.url, "base_branch": "main", "checkout": str(self.checkout)},
            "capabilities": ["read"], "models": {"default": {"model": "fixture-model-never-run", "reasoning": "low"}},
            "sandbox": "workspace-write", "approval_policy": "on-request",
        }
        self.write_config()
        self.registry = self.root / "registry.json"
        self.registry.write_text(json.dumps({"version": 1, "runtimes": [{"id": "example", "provider": "azure-devops",
                                                                  "runtime_dir": str(self.runtime), "config": str(self.config)}], "installations": []}))
        self.service = HarnessService(self.registry)
        self.bridge = harness_azure.HarnessAzure(self.service)
        self.packet = self.root / "packet.json"
        self.task = {
            "schema_version": 1, "id": "azdo:ExampleOrg:ExampleProject:17", "revision": 3,
            "repository_url": self.url, "base_branch": "main", "base_commit": "a" * 40,
            "branch": "feature/bounded-fix", "write_scope": ["src"], "task": "Repair the reviewed fixture module.",
            "commands": [{"id": "unit", "argv": ["python3", "tests/unit.py"], "timeout_seconds": 30}],
            "acceptance": [{"id": "unit-pass", "command_id": "unit", "evidence_file": "unit.json"}],
            "role_timeout_seconds": 30,
        }
        self.packet.write_text(json.dumps(self.task))

    def write_config(self):
        self.config.write_text(json.dumps(self.configuration))

    def prepare(self, operation="azure-inspect", **options):
        return self.bridge.prepare("example", operation, options or {"ids": [17]})

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.stat().st_mtime_ns, path.read_bytes())
                for path in self.root.rglob("*") if path.is_file()}

    def authorize_fixture(self, capability):
        self.configuration["capabilities"] = ["read", capability]
        self.write_config()
        authority = self.runtime / "authority"
        authority.mkdir(exist_ok=True)
        (authority / "trust.json").write_text(json.dumps({"fixture": "public trust is not qualified by preparation"}))
        grant = self.root / "operation-grant.json"
        grant.write_text(json.dumps({"fixture": "native verification still required"}))
        return str(grant)

    def board_packet(self):
        from atlas_azure_reconcile import build_proposal

        now = time.time()
        item = {"id": 17, "rev": 3, "fields": {"System.State": "Active", "System.TeamProject": "ExampleProject",
                                              "System.Tags": "human-tag"}, "relations": []}
        proposal = build_proposal({"complete": True, "observed_at": now, "items": [item]},
                                  {"operator_owned_tags": ["harness:reviewed"], "approved_dependencies": [],
                                   "changes": [{"issue_id": "azdo:ExampleOrg:ExampleProject:17", "add_tags": ["harness:reviewed"]}]},
                                  "ExampleOrg", "ExampleProject", now=now)
        path = self.root / "board-proposal.json"
        path.write_text(json.dumps(proposal))
        return path

    def test_inspection_proposal_is_inert_and_has_no_cloud_write_or_authority(self):
        before = self.snapshot()
        with patch("subprocess.run", side_effect=AssertionError("prepare must not execute")), \
                patch("subprocess.Popen", side_effect=AssertionError("prepare must not dispatch")), \
                patch("socket.create_connection", side_effect=AssertionError("prepare must not connect")):
            report = self.prepare()
        self.assertEqual(report["status"], "prepared", report["blockers"])
        self.assertEqual(before, self.snapshot())
        proposal = report["proposal"]
        self.assertEqual(proposal["required_capabilities"], ["read"])
        self.assertIn("--dry-run", proposal["argv"])
        self.assertFalse(proposal["effects"]["provider_read"])
        self.assertFalse(proposal["effects"]["remote_comments"])
        self.assertFalse(proposal["required_authorization"]["granted"])

    def test_live_inspection_is_explicit_and_binds_scope(self):
        plain = self.prepare()
        live = self.prepare(ids=[17, 18], live_read=True, build_ids=[25], max_minutes=2)
        self.assertNotEqual(plain["proposal_id"], live["proposal_id"])
        self.assertIn("--live-read", live["proposal"]["argv"])
        self.assertNotIn("--dry-run", live["proposal"]["argv"])
        self.assertIn("17,18", live["proposal"]["argv"])
        self.assertTrue(live["proposal"]["effects"]["provider_read"])

    def test_inspection_requires_bounded_scope_and_rejects_wrong_types(self):
        report = self.bridge.prepare("example", "azure-inspect")
        self.assertIn("missing_inspection_scope", {x["code"] for x in report["blockers"]})
        for options in ({"ids": []}, {"ids": [True]}, {"ids": [17, 17]}, {"ids": [-1]}, {"ids": list(range(1, 202))},
                        {"ids": [17], "live_read": "yes"}, {"ids": [17], "max_minutes": True},
                        {"ids": [17], "max_minutes": 31}, {"ids": [17], "command": "echo bad"},
                        {"ids": [17], "build_ids": [1]}):
            with self.subTest(options=options), self.assertRaises(HarnessServiceError):
                self.bridge.prepare("example", "azure-inspect", options)

    def test_read_only_remote_inspects_without_models_but_worker_preview_requires_them(self):
        self.configuration.pop("models")
        self.write_config()
        inspection = self.prepare()
        self.assertEqual(inspection["status"], "prepared", inspection["blockers"])
        child = subprocess.run(inspection["proposal"]["argv"], cwd=self.runtime,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(json.loads(child.stdout)["effective_configuration"]["models"], {})
        preview = self.prepare("azure-worker-preview", packet=str(self.packet))
        self.assertIn("missing_worker_models", {row["code"] for row in preview["blockers"]})

    def test_input_hash_and_runtime_code_changes_invalidate_proposal(self):
        evidence = self.root / "snapshot.json"
        evidence.write_text("{}")
        before = self.prepare(ids=[17], snapshot=str(evidence))
        evidence.write_text('{"fresh": true}')
        after = self.prepare(ids=[17], snapshot=str(evidence))
        self.assertNotEqual(before["proposal_id"], after["proposal_id"])
        helper = self.runtime / "atlas_azure_devops.py"
        helper.write_text(helper.read_text() + "\n# changed\n")
        changed = self.prepare()
        self.assertEqual(changed["status"], "blocked")
        self.assertIn("runtime_script_drift", {x["code"] for x in changed["blockers"]})

    def test_snapshot_and_live_read_are_mutually_exclusive(self):
        path = self.root / "snapshot.json"
        path.write_text("{}")
        with self.assertRaises(HarnessServiceError):
            self.prepare(ids=[17], snapshot=str(path), live_read=True)

    def test_input_paths_cannot_read_credentials_links_or_traverse(self):
        for path in ("relative.json", str(self.root / ".." / "elsewhere.json"), str(self.root / "credentials.json")):
            with self.subTest(path=path):
                report = self.prepare(ids=[17], snapshot=path)
                self.assertEqual(report["status"], "blocked")
        link = self.root / "linked.json"
        link.symlink_to(self.packet)
        report = self.prepare(ids=[17], snapshot=str(link))
        self.assertEqual(report["status"], "blocked")
        self.assertNotIn(self.task["task"], json.dumps(report))

    def test_malformed_and_large_json_are_blocked_without_echoing_content(self):
        path = self.root / "malformed.json"
        for content in ('{"PRIVATE_SENTINEL":', '{"a":1,"a":2}', '{"number":NaN}', json.dumps({"PRIVATE_SENTINEL": "x" * 270000})):
            path.write_text(content)
            report = self.prepare(ids=[17], snapshot=str(path))
            self.assertEqual(report["status"], "blocked")
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(report))

    def test_worker_preview_uses_exact_packet_and_explicit_models(self):
        report = self.prepare("azure-worker-preview", packet=str(self.packet))
        self.assertEqual(report["status"], "prepared", report["blockers"])
        self.assertIn("--dry-run", report["proposal"]["argv"])
        self.assertFalse(report["proposal"]["effects"]["worker_execution"])
        self.assertEqual(report["proposal"]["task"]["id"], self.task["id"])
        self.assertNotIn(self.task["task"], json.dumps(report))

    def test_worker_target_drift_and_outside_worktree_are_blocked(self):
        for changes in ({"repository_url": "https://dev.azure.com/Another/Project/_git/Repo"}, {"base_branch": "other"},
                        {"id": "azdo:Another:Project:17"}, {"write_scope": ["../outside"]}, {"commands": []}):
            with self.subTest(changes=changes):
                self.packet.write_text(json.dumps({**self.task, **changes}))
                report = self.prepare("azure-worker-preview", packet=str(self.packet))
                self.assertIn("invalid_worker_packet", {x["code"] for x in report["blockers"]})

    def test_model_execution_has_separate_capability_grant_and_trust_requirements(self):
        with self.assertRaises(HarnessServiceError):
            self.prepare("azure-worker", packet=str(self.packet))
        grant = self.authorize_fixture("local_execute")
        report = self.prepare("azure-worker", packet=str(self.packet), authorization=grant)
        self.assertEqual(report["status"], "prepared", report["blockers"])
        self.assertIn("--execute", report["proposal"]["argv"])
        self.assertTrue(report["proposal"]["effects"]["worker_execution"])
        self.assertFalse(report["proposal"]["required_authorization"]["native_grant_verified"])
        (self.runtime / "authority" / "trust.json").unlink()
        self.assertIn("missing_authority_registry", {x["code"] for x in self.prepare("azure-worker", packet=str(self.packet), authorization=grant)["blockers"]})

    def test_draft_publication_is_not_model_execution_or_merge(self):
        grant = self.authorize_fixture("draft_pr")
        report = self.prepare("azure-publish", packet=str(self.packet), authorization=grant)
        self.assertEqual(report["status"], "prepared", report["blockers"])
        self.assertIn("--publish", report["proposal"]["argv"])
        self.assertNotIn("--execute", report["proposal"]["argv"])
        self.assertEqual(report["proposal"]["required_capabilities"], ["read", "draft_pr"])
        self.assertTrue(report["proposal"]["effects"]["draft_pr_publication"])
        self.assertFalse(report["proposal"]["effects"]["merge"])

    def test_board_preview_and_write_keep_exact_existing_proposal(self):
        packet = self.board_packet()
        preview = self.prepare("azure-reconcile-preview", packet=str(packet))
        self.assertEqual(preview["status"], "prepared", preview["blockers"])
        self.assertFalse(preview["proposal"]["effects"]["board_updates"])
        grant = self.authorize_fixture("board_write")
        write = self.prepare("azure-reconcile", packet=str(packet), authorization=grant)
        self.assertEqual(write["status"], "prepared", write["blockers"])
        self.assertTrue(write["proposal"]["effects"]["board_updates"])
        self.assertIn("--apply", write["proposal"]["argv"])

    def test_inspection_blockers_are_propagated(self):
        with patch.object(self.service, "inspect", return_value={"blockers": [{"code": "contradictory_runtime_evidence", "message": "Conflicting states.", "next_action": "Review evidence."}],
                                                               "next_actions": [{"operation": "review_runtime_evidence"}]}):
            report = self.prepare()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["next_actions"][0]["operation"], "review_runtime_evidence")

    def test_config_drift_after_service_validation_is_a_sanitized_domain_error(self):
        validated = self.service.get_runtime("example")
        self.config.write_text('{"PRIVATE_SENTINEL":')
        before = self.snapshot()
        with patch.object(self.service, "get_runtime", return_value=validated):
            with self.assertRaises(HarnessServiceError) as caught:
                self.prepare()
        self.assertEqual(caught.exception.code, "invalid_config")
        self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))
        self.assertEqual(before, self.snapshot())

    def test_real_inspector_dry_run_matches_generated_argv_without_provider_access(self):
        report = self.prepare()
        before = self.snapshot()
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        child = subprocess.run(report["proposal"]["argv"], cwd=self.runtime, env=environment, capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        body = json.loads(child.stdout)
        self.assertEqual(body["inspection_mode"], "dry-run")
        self.assertEqual(body["ids"], [17])
        self.assertEqual(before, self.snapshot())
        result = harness_azure.project_result(report["proposal"], child.stdout)
        self.assertEqual(result["status"], "observed")
        self.assertFalse(result["accepted_progress"])

    def test_real_worker_preview_matches_generated_argv_without_model_access(self):
        report = self.prepare("azure-worker-preview", packet=str(self.packet))
        before = self.snapshot()
        child = subprocess.run(report["proposal"]["argv"], cwd=self.runtime,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        body = json.loads(child.stdout)
        self.assertEqual(body["state"], "preview")
        self.assertTrue(body["inert"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(harness_azure.project_result(report["proposal"], child.stdout)["backend_state"], "preview")

    def test_real_board_preview_matches_generated_argv_without_cloud_access(self):
        packet = self.board_packet()
        report = self.prepare("azure-reconcile-preview", packet=str(packet))
        before = self.snapshot()
        child = subprocess.run(report["proposal"]["argv"], cwd=self.runtime,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(json.loads(child.stdout)["mode"], "preview")
        self.assertEqual(before, self.snapshot())


class AzureResultProjectionTests(unittest.TestCase):
    def proposal(self, operation="azure-inspect"):
        return {"operation": operation, "runtime_dir": "/home/example/runtime", "targets": ["https://dev.azure.com/ExampleOrg/ExampleProject/_git/ExampleRepo"],
                "remote": {"organization": "ExampleOrg", "project": "ExampleProject", "name": "ExampleRepo", "base_branch": "main"}}

    def project(self, body, operation="azure-inspect"):
        return harness_azure.project_result(self.proposal(operation), json.dumps(body).encode())

    def test_inspection_projection_preserves_only_known_structured_fields(self):
        result = self.project({"inspection_mode": "live-read-only", "complete": True, "dependency_complete": False,
                               "eligible_count": 0, "blockers": ["unresolved-dependency-closure", "PRIVATE ERROR WITH TOKEN"],
                               "items": [{"id": "azdo:ExampleOrg:ExampleProject:17", "revision": 3, "state": "Active", "title": "PRIVATE", "description": "TOKEN"},
                                         {"id": "azdo:Other:Project:1"}], "effective_configuration": {"TOKEN": "PRIVATE"}})
        self.assertEqual(result["items"], [{"id": "azdo:ExampleOrg:ExampleProject:17", "revision": 3, "state": "Active"}])
        self.assertEqual(result["blocker_codes"], ["unclassified_backend_blocker", "unresolved-dependency-closure"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertFalse(result["completion"])

    def test_native_errors_and_malformed_output_never_echo_raw_details(self):
        result = self.project({"state": "blocked", "error": "PRIVATE TOKEN"}, "azure-worker")
        self.assertEqual(result["failure_code"], "azure_backend_blocked")
        self.assertNotIn("PRIVATE", json.dumps(result))
        for raw in (b"TOKEN stdout", b'{"state":"preview","state":"pr_open"}', b'{"state":NaN}', b"x" * 262145):
            with self.subTest(raw=raw[:20]):
                result = harness_azure.project_result(self.proposal("azure-worker"), raw)
                self.assertEqual(result["status"], "unavailable")
                self.assertNotIn("TOKEN", json.dumps(result))

    def test_backend_type_errors_are_sanitized(self):
        for operation, body in (("azure-inspect", {"inspection_mode": []}), ("azure-worker", {"state": {}}), ("azure-reconcile", {"status": []})):
            with self.subTest(operation=operation):
                self.assertEqual(self.project(body, operation)["status"], "unavailable")

    def test_publication_url_is_constructed_from_bound_repository(self):
        result = self.project({"state": "pr_open", "pull_request_id": 54, "url": "https://attacker.invalid/PRIVATE", "signature": "PRIVATE"}, "azure-publish")
        self.assertEqual(result["pull_request_url"], "https://dev.azure.com/ExampleOrg/ExampleProject/_git/ExampleRepo/pullrequest/54")
        self.assertFalse(result["accepted_progress"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_unknown_result_cannot_claim_completion(self):
        result = self.project({"state": "done", "completion": True, "accepted_progress": True}, "azure-worker")
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["completion"])

    def test_inspection_summary_marks_bounded_item_coverage(self):
        result = self.project({"inspection_mode": "live-read-only", "items": [
            {"id": "azdo:ExampleOrg:ExampleProject:" + str(i), "state": "Active"} for i in range(1, 40)]})
        self.assertEqual(len(result["items"]), 32)
        self.assertTrue(result["items_truncated"])

    def test_board_summary_counts_proposal_and_applied_entries_without_raw_patches(self):
        preview = self.project({"mode": "preview", "proposal": {"patches": [{"PRIVATE": "patch"}]}}, "azure-reconcile-preview")
        self.assertEqual(preview["planned_patch_count"], 1)
        result = self.project({"status": "applied", "entries": [{"status": "applied", "PRIVATE": "data"}, {"status": "pending"}]}, "azure-reconcile")
        self.assertEqual(result["applied_entry_count"], 1)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def repository_evidence(self, *, complete=True):
        return {"complete": complete, "blockers": [],
                "repository": {"id": "00000000-0000-0000-0000-000000000001", "name": "ExampleRepo", "webUrl": "https://private.invalid/TOKEN"},
                "base_refs": [{"name": "refs/heads/main", "objectId": "a" * 40}],
                "pull_requests": [{"pullRequestId": 54, "status": "active", "isDraft": True, "title": "PRIVATE"}],
                "policies": [{"id": 12, "isEnabled": True, "isBlocking": False, "createdBy": "PRIVATE"}],
                "policy_evaluations": [{"pull_request_id": 54, "id": "00000000-0000-0000-0000-000000000002", "status": "approved", "context": "PRIVATE"}],
                "builds": [{"id": 99, "status": "completed", "result": "failed", "sourceVersion": "b" * 40, "buildNumber": "PRIVATE"}],
                "timelines": [{"build_id": 99, "records": [{"id": "00000000-0000-0000-0000-000000000003", "state": "completed", "result": "failed", "log": "TOKEN", "name": "PRIVATE"}]}],
                "timeline_scope": "first-ten-listed-builds", "unknown_private_field": "PRIVATE TOKEN"}

    def test_live_repository_evidence_retains_cloud_summary_without_private_fields(self):
        body = {"inspection_mode": "live-read-only", "complete": True, "dependency_complete": True,
                "repository_evidence": self.repository_evidence()}
        result = self.project(body)
        evidence = result["repository_evidence"]
        self.assertTrue(result["board_complete"])
        self.assertTrue(result["repository_checked"])
        self.assertTrue(result["complete"])
        self.assertEqual(evidence["pull_requests"], [{"id": 54, "status": "active", "is_draft": True}])
        self.assertEqual(evidence["policies"], [{"id": 12, "is_enabled": True, "is_blocking": False}])
        self.assertEqual(evidence["policy_evaluations"][0]["status"], "approved")
        self.assertEqual(evidence["builds"][0]["result"], "failed")
        self.assertEqual(evidence["timelines"], [{"build_id": 99, "record_count": 1, "states_recognized": True}])
        self.assertEqual(evidence["base_commit_sha"], "a" * 40)
        self.assertFalse(result["accepted_progress"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("TOKEN", json.dumps(result))

    def test_board_completeness_never_masks_incomplete_live_repository_evidence(self):
        evidence = self.repository_evidence(complete=False)
        evidence["blockers"] = ["PRIVATE TOKEN backend message"]
        result = self.project({"inspection_mode": "live-read-only", "complete": True,
                               "repository_evidence": evidence})
        self.assertTrue(result["board_complete"])
        self.assertFalse(result["complete"])
        self.assertFalse(result["repository_evidence"]["complete"])
        self.assertEqual(result["repository_evidence"]["blocker_codes"], ["unclassified_repository_blocker"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_live_repository_missing_or_wrong_scope_is_explicit(self):
        missing = self.project({"inspection_mode": "live-read-only", "complete": True})
        self.assertFalse(missing["complete"])
        self.assertFalse(missing["repository_checked"])
        self.assertIn("repository_evidence", missing["repository_evidence"]["missing_fields"])
        evidence = self.repository_evidence()
        evidence["repository"]["name"] = "AnotherRepository"
        wrong = self.project({"inspection_mode": "live-read-only", "complete": True, "repository_evidence": evidence})
        self.assertFalse(wrong["complete"])
        self.assertFalse(wrong["repository_evidence"]["repository_matches_profile"])
        self.assertEqual(wrong["repository_evidence"]["pull_requests"], [])

    def test_requested_build_and_timeline_summaries_are_available_and_capped(self):
        proposal = self.proposal()
        proposal["options"] = {"live_read": True, "build_ids": list(range(1, 41))}
        evidence = self.repository_evidence()
        evidence["timeline_scope"] = "explicit-build-ids"
        evidence["builds"] = [{"id": value, "status": "completed", "result": "succeeded", "sourceVersion": "b" * 40}
                              for value in range(1, 41)]
        evidence["timelines"] = [{"build_id": value, "records": []} for value in range(1, 41)]
        result = harness_azure.project_result(proposal, json.dumps({"inspection_mode": "live-read-only", "complete": True,
                                                                  "repository_evidence": evidence}).encode())
        summary = result["repository_evidence"]
        self.assertEqual(len(summary["builds"]), 32)
        self.assertEqual(len(summary["timelines"]), 32)
        self.assertEqual(summary["builds"][0]["id"], 1)
        self.assertTrue(summary["coverage"]["builds"]["truncated"])
        self.assertTrue(summary["selected_build_ids_truncated"])
        self.assertEqual(summary["selected_builds_without_metadata"], list(range(33, 41)))
        self.assertFalse(result["complete"])

    def test_unrecognized_policy_and_build_shapes_mark_omitted_coverage(self):
        proposal = self.proposal()
        proposal["options"] = {"live_read": True, "build_ids": [99]}
        evidence = self.repository_evidence()
        evidence["policy_evaluations"][0]["status"] = "PRIVATE TOKEN"
        evidence["builds"].append({"id": [], "status": "PRIVATE"})
        evidence["builds"][0]["status"] = {}
        result = harness_azure.project_result(proposal, json.dumps({"inspection_mode": "live-read-only", "complete": True,
                                                                  "repository_evidence": evidence}).encode())
        self.assertFalse(result["complete"])
        self.assertTrue(result["repository_evidence"]["coverage"]["policy_evaluations"]["omitted"])
        self.assertTrue(result["repository_evidence"]["coverage"]["builds"]["omitted"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_offline_board_completeness_does_not_claim_repository_was_checked(self):
        result = self.project({"inspection_mode": "offline-snapshot", "complete": True, "dependency_complete": True})
        self.assertTrue(result["board_complete"])
        self.assertTrue(result["complete"])
        self.assertFalse(result["repository_checked"])
        self.assertEqual(result["complete_scope"], "work_items_only")

    def test_other_base_prefix_refs_do_not_hide_the_requested_base(self):
        evidence = self.repository_evidence()
        evidence["base_refs"] += [{"name": "refs/heads/main-backup-" + str(i), "objectId": "c" * 40} for i in range(40)]
        result = self.project({"inspection_mode": "live-read-only", "complete": True, "repository_evidence": evidence})
        self.assertTrue(result["complete"])
        self.assertEqual(result["repository_evidence"]["base_commit_sha"], "a" * 40)
        self.assertEqual(result["repository_evidence"]["coverage"]["base_refs"]["scoped_count"], 1)


if __name__ == "__main__":
    unittest.main()
