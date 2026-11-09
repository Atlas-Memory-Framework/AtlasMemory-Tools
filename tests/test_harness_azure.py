from __future__ import annotations

from copy import deepcopy
import hashlib
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
        self.assertEqual({k: evidence["pull_requests"][0][k] for k in ("id", "status", "is_draft")}, {"id": 54, "status": "active", "is_draft": True})
        self.assertFalse(evidence["pull_requests"][0]["bindings_complete"])
        self.assertEqual(evidence["policies"], [{"id": 12, "is_enabled": True, "is_blocking": False}])
        self.assertEqual(evidence["policy_evaluations"][0]["status"], "approved")
        self.assertEqual(evidence["builds"][0]["result"], "failed")
        self.assertEqual({k: evidence["timelines"][0][k] for k in ("build_id", "record_count", "states_recognized")}, {"build_id": 99, "record_count": 1, "states_recognized": True})
        self.assertFalse(evidence["bindings_complete"])
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
        self.assertTrue(summary["binding_coverage"]["builds"]["count_capped"])
        self.assertTrue(summary["selected_build_ids_truncated"])
        self.assertEqual(summary["selected_builds_without_metadata"], [])
        self.assertEqual(summary["requested_build_ids_omitted_count"], 8)
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


# Frozen revision-2 consumer contract fixtures. These do not qualify a producer.
CONTRACT_TIMELINE = {'binding_malformed_fields': [],
 'binding_missing_fields': [],
 'bindings_complete': True,
 'build_id': 9,
 'native_parent_index_sha256': 'af166f0eccdde323e2b70248277ed83b59f178ffea68c8cb9d144fee25f69a4a',
 'parent_validation_facts': [{'acyclic': True,
                              'build_id': 9,
                              'child_id': '00000000-0000-0000-0000-000000000002',
                              'child_occurrences': 1,
                              'index_sha256': 'af166f0eccdde323e2b70248277ed83b59f178ffea68c8cb9d144fee25f69a4a',
                              'native_record_count': 3,
                              'parent_id': '00000000-0000-0000-0000-000000000001',
                              'parent_occurrences': 1,
                              'parent_type': 'Stage',
                              'resolution': 'resolved',
                              'schema_version': 'atlas-tools.azure-parent-validation.v1'},
                             {'acyclic': True,
                              'build_id': 9,
                              'child_id': '00000000-0000-0000-0000-000000000003',
                              'child_occurrences': 1,
                              'index_sha256': 'af166f0eccdde323e2b70248277ed83b59f178ffea68c8cb9d144fee25f69a4a',
                              'native_record_count': 3,
                              'parent_id': '00000000-0000-0000-0000-000000000002',
                              'parent_occurrences': 1,
                              'parent_type': 'Job',
                              'resolution': 'resolved',
                              'schema_version': 'atlas-tools.azure-parent-validation.v1'}],
 'projected_record_count': 3,
 'record_count': 3,
 'records': [{'attempt': 1,
              'binding_malformed_fields': [],
              'binding_missing_fields': [],
              'bindings_complete': True,
              'id': '00000000-0000-0000-0000-000000000001',
              'identifier_sha256': '6b27dff2c21aa7b1a0e478b4781ed8be168c4d6dc2ef5510a2af40d2c5244a68',
              'result': 'succeeded',
              'state': 'completed',
              'type': 'Stage'},
             {'attempt': 2,
              'binding_malformed_fields': [],
              'binding_missing_fields': [],
              'bindings_complete': True,
              'id': '00000000-0000-0000-0000-000000000002',
              'identifier_sha256': '670827e831da41b79957612af487e0b3569de26a3083a2f7dbcffc9ac36ddcec',
              'parent_id': '00000000-0000-0000-0000-000000000001',
              'result': 'succeeded',
              'state': 'completed',
              'type': 'Job'},
             {'binding_malformed_fields': [],
              'binding_missing_fields': [],
              'bindings_complete': True,
              'id': '00000000-0000-0000-0000-000000000003',
              'parent_id': '00000000-0000-0000-0000-000000000002',
              'result': 'succeeded',
              'state': 'completed',
              'type': 'Task'}],
 'records_truncated': False,
 'returned_record_count': 3,
 'states_recognized': True}

CONTRACT_OMITTED_PARENT = {'expected_public': {'accepted_progress': False,
                     'binding_coverage_complete': False,
                     'bindings_complete': False,
                     'completion': False,
                     'container.bindings_complete': False,
                     'private_fact_fields_not_exposed': True,
                     'record0.bindings_complete': True},
 'native_relation_index': [{'id': '00000000-0000-0000-0000-000000000001',
                            'native_position': 0,
                            'parent_id': '00000000-0000-0000-0000-000000000010',
                            'type': 'Job'},
                           {'id': '00000000-0000-0000-0000-000000000010',
                            'native_position': 1,
                            'parent_id': None,
                            'type': 'Stage'}],
 'private_timeline': {'binding_malformed_fields': [],
                      'binding_missing_fields': [],
                      'bindings_complete': False,
                      'build_id': 9,
                      'native_parent_index_sha256': '4dff25734873179dcb8575de00d5b6c9a30fafe9992160d6675c0db771cf9d14',
                      'parent_validation_facts': [{'acyclic': True,
                                                   'build_id': 9,
                                                   'child_id': '00000000-0000-0000-0000-000000000001',
                                                   'child_occurrences': 1,
                                                   'index_sha256': '4dff25734873179dcb8575de00d5b6c9a30fafe9992160d6675c0db771cf9d14',
                                                   'native_record_count': 2,
                                                   'parent_id': '00000000-0000-0000-0000-000000000010',
                                                   'parent_occurrences': 1,
                                                   'parent_type': 'Stage',
                                                   'resolution': 'resolved',
                                                   'schema_version': 'atlas-tools.azure-parent-validation.v1'}],
                      'projected_record_count': 1,
                      'record_count': 2,
                      'records': [{'binding_malformed_fields': [],
                                   'binding_missing_fields': [],
                                   'bindings_complete': True,
                                   'id': '00000000-0000-0000-0000-000000000001',
                                   'identifier_sha256': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                                   'parent_id': '00000000-0000-0000-0000-000000000010',
                                   'result': 'skipped',
                                   'state': 'completed',
                                   'type': 'Job'}],
                      'records_truncated': True,
                      'returned_record_count': 2,
                      'states_recognized': True},
 'reader_coverage': {'byte_capped': True, 'count_capped': False},
 'trust': 'Producer facts conditionally trusted only after consistency checks; no authentication claim.'}

CONTRACT_PR_CASES = [{'expected_public': {'binding_malformed_fields': [],
                      'binding_missing_fields': [],
                      'bindings_complete': True,
                      'id': 4,
                      'is_draft': False,
                      'source_commit_sha': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                      'source_ref_sha256': 'd8f2d99dcb8151ef9a5d5aaa0b7445a4507d2cd979934c9dd2784a37fea6bf54',
                      'status': 'active',
                      'target_commit_sha': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                      'target_ref_sha256': 'fd3dfe2cab8ed1e2796f40171ae41d65cc758d9dabc013b8dd150764225fbea4'},
  'id': 'active',
  'native': {'isDraft': False,
             'lastMergeSourceCommit': {'commitId': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'},
             'lastMergeTargetCommit': {'commitId': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'},
             'pullRequestId': 4,
             'sourceRefName': 'refs/heads/PRIVATE_SENTINEL/é',
             'status': 'active',
             'targetRefName': 'refs/heads/develop',
             'title': 'PRIVATE_SENTINEL'}},
 {'expected_public': {'binding_malformed_fields': [],
                      'binding_missing_fields': [],
                      'bindings_complete': True,
                      'id': 4,
                      'is_draft': False,
                      'source_commit_sha': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                      'source_ref_sha256': 'd8f2d99dcb8151ef9a5d5aaa0b7445a4507d2cd979934c9dd2784a37fea6bf54',
                      'status': 'abandoned',
                      'target_commit_sha': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                      'target_ref_sha256': 'fd3dfe2cab8ed1e2796f40171ae41d65cc758d9dabc013b8dd150764225fbea4'},
  'id': 'abandoned',
  'native': {'isDraft': False,
             'lastMergeSourceCommit': {'commitId': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'},
             'lastMergeTargetCommit': {'commitId': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'},
             'pullRequestId': 4,
             'sourceRefName': 'refs/heads/PRIVATE_SENTINEL/é',
             'status': 'abandoned',
             'targetRefName': 'refs/heads/develop',
             'title': 'PRIVATE_SENTINEL'}},
 {'expected_public': {'binding_malformed_fields': [],
                      'binding_missing_fields': ['pr.merge_commit_sha'],
                      'bindings_complete': False,
                      'id': 4,
                      'is_draft': False,
                      'source_commit_sha': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                      'source_ref_sha256': 'd8f2d99dcb8151ef9a5d5aaa0b7445a4507d2cd979934c9dd2784a37fea6bf54',
                      'status': 'completed',
                      'target_commit_sha': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                      'target_ref_sha256': 'fd3dfe2cab8ed1e2796f40171ae41d65cc758d9dabc013b8dd150764225fbea4'},
  'id': 'completed',
  'native': {'isDraft': False,
             'lastMergeSourceCommit': {'commitId': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'},
             'lastMergeTargetCommit': {'commitId': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'},
             'pullRequestId': 4,
             'sourceRefName': 'refs/heads/PRIVATE_SENTINEL/é',
             'status': 'completed',
             'targetRefName': 'refs/heads/develop',
             'title': 'PRIVATE_SENTINEL'}},
 {'expected_public': {'binding_malformed_fields': [],
                      'binding_missing_fields': ['pr.source_commit_sha'],
                      'bindings_complete': False,
                      'id': 4,
                      'is_draft': True,
                      'merge_commit_sha': 'cccccccccccccccccccccccccccccccccccccccc',
                      'source_ref_sha256': 'd8f2d99dcb8151ef9a5d5aaa0b7445a4507d2cd979934c9dd2784a37fea6bf54',
                      'status': 'active',
                      'target_commit_sha': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                      'target_ref_sha256': 'fd3dfe2cab8ed1e2796f40171ae41d65cc758d9dabc013b8dd150764225fbea4'},
  'id': 'draft-source',
  'native': {'isDraft': True,
             'lastMergeCommit': {'commitId': 'cccccccccccccccccccccccccccccccccccccccc'},
             'lastMergeTargetCommit': {'commitId': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'},
             'pullRequestId': 4,
             'sourceRefName': 'refs/heads/PRIVATE_SENTINEL/é',
             'status': 'active',
             'targetRefName': 'refs/heads/develop',
             'title': 'PRIVATE_SENTINEL'}},
 {'expected_public': {'binding_malformed_fields': ['pr.merge_commit_sha'],
                      'binding_missing_fields': [],
                      'bindings_complete': False,
                      'id': 4,
                      'is_draft': False,
                      'source_commit_sha': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                      'source_ref_sha256': 'd8f2d99dcb8151ef9a5d5aaa0b7445a4507d2cd979934c9dd2784a37fea6bf54',
                      'status': 'active',
                      'target_commit_sha': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                      'target_ref_sha256': 'fd3dfe2cab8ed1e2796f40171ae41d65cc758d9dabc013b8dd150764225fbea4'},
  'id': 'malformed-optional-merge',
  'native': {'isDraft': False,
             'lastMergeCommit': {'commitId': 'PRIVATE_SENTINEL'},
             'lastMergeSourceCommit': {'commitId': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'},
             'lastMergeTargetCommit': {'commitId': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'},
             'pullRequestId': 4,
             'sourceRefName': 'refs/heads/PRIVATE_SENTINEL/é',
             'status': 'active',
             'targetRefName': 'refs/heads/develop',
             'title': 'PRIVATE_SENTINEL'}}]


class AzureBindingContractTests(unittest.TestCase):
    """Consumer-only synthetic contracts, never live/native reader acceptance."""
    def setUp(self):
        self.proposal = {"operation": "azure-inspect", "options": {"build_ids": [9], "live_read": True},
                         "remote": {"name": "Website", "base_branch": "develop"}}
        repository_id = "11111111-2222-3333-4444-555555555555"
        pr = deepcopy(CONTRACT_PR_CASES[0]["native"])
        self.evidence = {
            "complete": True, "blockers": [], "evidence_contract": "atlas-tools.azure-observation.v1",
            "observed_at": "2026-11-09T15:02:00Z", "repository_id": repository_id,
            "repository": {"id": repository_id, "name": "Website"}, "timeline_scope": "explicit-build-ids",
            "requested_build_ids": [9], "request_ids_invalid_count": 0, "requested_build_ids_omitted_count": 0,
            "bindings_complete": True, "binding_coverage_complete": True,
            "binding_missing_fields": [], "binding_malformed_fields": [],
            "base_refs": [{"name": "refs/heads/develop", "objectId": "b" * 40}],
            "pull_requests": [pr], "policies": [], "policy_evaluations": [],
            "builds": [{"id": 9, "status": "completed", "result": "succeeded", "sourceVersion": "a" * 40,
                        "sourceBranch": pr["sourceRefName"], "queueTime": "2026-11-09T15:00:00Z",
                        "startTime": "2026-11-09T15:01:00Z", "finishTime": "2026-11-09T15:02:00Z"}],
            "build_bindings": [self.binding(build_id=9, repository_id=repository_id, definition_id=7, definition_revision=3)],
            "build_source_bindings": [self.binding(build_id=9, source_commit_sha="a" * 40,
                                                   source_ref_sha256=hashlib.sha256(pr["sourceRefName"].encode()).hexdigest())],
            "build_time_bindings": [self.binding(build_id=9, status="completed", result="succeeded",
                                                 queue_time="2026-11-09T15:00:00Z", start_time="2026-11-09T15:01:00Z", finish_time="2026-11-09T15:02:00Z")],
            "pr_bindings": [self.binding(pull_request_id=4, **{k: v for k, v in CONTRACT_PR_CASES[0]["expected_public"].items() if k in {"source_commit_sha", "target_commit_sha", "source_ref_sha256", "target_ref_sha256"}})],
            "timelines": [{"build_id": 9, "records": [{"id": r["id"], "state": r["state"], "result": r["result"]} for r in CONTRACT_TIMELINE["records"]]}],
            "timeline_bindings": [deepcopy(CONTRACT_TIMELINE)],
            "binding_coverage": {name: {"returned_count": 1, "projected_count": 1, "bound_count": 1,
                                        "malformed_count": 0, "omitted_count": 0, "upstream_complete": True,
                                        "count_capped": False, "byte_capped": False}
                                 for name in ("observation", "pull_requests", "builds", "timelines")},
            "budget": {"reader_bytes": 0, "public_bytes": None, "reader_byte_limit": 98304,
                       "public_byte_limit": 98304, "aggregate_truncated": False, "report_omitted": False},
        }

    @staticmethod
    def binding(**values):
        return {**values, "bindings_complete": True, "binding_missing_fields": [], "binding_malformed_fields": []}

    def project(self):
        # A synthetic producer byte counter, using the frozen serializer directly.
        self.evidence["budget"]["reader_bytes"] = 0
        for _ in range(7):
            size = len((json.dumps({"repository_evidence": self.evidence}, indent=2, sort_keys=True,
                                   ensure_ascii=True, allow_nan=False) + "\n").encode())
            if size == self.evidence["budget"]["reader_bytes"]:
                break
            self.evidence["budget"]["reader_bytes"] = size
        return harness_azure.project_result(self.proposal, json.dumps({"inspection_mode": "live-read-only", "complete": True,
                                                                     "repository_evidence": self.evidence}).encode())

    def repo(self):
        return self.project()["repository_evidence"]

    def test_complete_contract_fixture_and_exact_public_byte_accounting(self):
        result = self.project()
        e = result["repository_evidence"]
        self.assertTrue(e["bindings_complete"], e)
        self.assertTrue(e["binding_coverage_complete"])
        self.assertTrue(result["complete"])
        self.assertEqual(e["timelines"][0]["records"], CONTRACT_TIMELINE["records"])
        self.assertEqual(e["budget"]["public_bytes"], len((json.dumps({"repository_evidence": e}, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()))
        text = json.dumps(result)
        for secret in ("PRIVATE_SENTINEL", "sourceRefName", "sourceBranch", "parent_validation_facts", "native_parent_index_sha256"):
            self.assertNotIn(secret, text)
        self.assertFalse(result["accepted_progress"])
        self.assertFalse(result["completion"])
        self.assertFalse(e["deployment_authority"])

    def test_exact_pr_requiredness_consumer_fixtures(self):
        for case in CONTRACT_PR_CASES:
            with self.subTest(case=case["id"]):
                self.evidence["pull_requests"] = [deepcopy(case["native"])]
                self.evidence.pop("pr_bindings", None)
                self.assertEqual(self.repo()["pull_requests"][0], case["expected_public"])

    def test_exact_ref_bytes_and_invalid_optional_values(self):
        original = self.repo()["pull_requests"][0]["source_ref_sha256"]
        self.evidence["pull_requests"][0]["sourceRefName"] = "refs/heads/PRIVATE_SENTINEL/e\u0301"
        self.evidence.pop("pr_bindings")
        self.assertNotEqual(original, self.repo()["pull_requests"][0]["source_ref_sha256"])
        for value in ("refs/", "refs/x\x00", "refs/x\x85", "refs/x\ud800", "refs/" + "é" * 127, 4, False):
            with self.subTest(value=repr(value)):
                self.evidence["pull_requests"][0]["sourceRefName"] = value
                row = self.repo()["pull_requests"][0]
                self.assertIn("pr.source_ref_sha256", row["binding_malformed_fields"])
                self.assertNotIn("source_ref_sha256", row)

    def test_pr_conflicts_do_not_replace_observed_values(self):
        self.evidence["pr_bindings"][0]["source_commit_sha"] = "d" * 40
        row = self.repo()["pull_requests"][0]
        self.assertEqual(row["source_commit_sha"], "a" * 40)
        self.assertFalse(row["bindings_complete"])
        self.assertIn("pr.id", row["binding_malformed_fields"])
        other = deepcopy(self.evidence["pull_requests"][0])
        other["lastMergeSourceCommit"]["commitId"] = "e" * 40
        self.evidence["pull_requests"].append(other)
        e = self.repo()
        for row in e["pull_requests"]:
            self.assertNotIn("source_commit_sha", row)
            self.assertIn("pr.id", row["binding_malformed_fields"])

    def test_optional_malformed_native_diagnostics_survive_sanitized_null(self):
        self.evidence["builds"][0].update(status="notStarted", result=None, startTime=None, finishTime=None)
        sidecar = self.evidence["build_time_bindings"][0]
        sidecar.update(status="notStarted", result=None)
        sidecar.pop("start_time")
        sidecar.pop("finish_time")
        self.assertTrue(self.repo()["builds"][0]["bindings_complete"])
        sidecar["binding_malformed_fields"] = ["build.finish_time"]
        row = self.repo()["builds"][0]
        self.assertFalse(row["bindings_complete"])
        self.assertIn("build.finish_time", row["binding_malformed_fields"])

    def test_build_requiredness_across_every_recognized_status(self):
        for status in ("none", "notStarted", "postponed", "inProgress", "cancelling", "completed"):
            for result in (None, "none", "succeeded", "failed", "canceled", "partiallySucceeded"):
                with self.subTest(status=status, result=result):
                    native, timing = self.evidence["builds"][0], self.evidence["build_time_bindings"][0]
                    native.update(status=status, result=result)
                    timing.update(status=status, result=result)
                    e = self.repo()
                    if status == "completed" and result in (None, "none"):
                        self.assertFalse(e["bindings_complete"])
                    else:
                        self.assertTrue(e["builds"][0]["bindings_complete"], e["builds"])
        self.evidence["builds"][0].update(status="inProgress", result=None, startTime=None)
        self.evidence["build_time_bindings"][0].update(status="inProgress", result=None)
        self.evidence["build_time_bindings"][0].pop("start_time")
        self.assertIn("build.start_time", self.repo()["builds"][0]["binding_missing_fields"])

    def test_timestamp_calendar_offsets_and_frozen_leap_dates(self):
        for value, valid in (("1991-01-01T00:59:60+01:00", True), ("2016-12-31t23:59:60.123456789z", True),
                             ("2028-12-31T23:59:60Z", False), ("2026-02-29T12:00:00Z", False),
                             ("2024-02-29T12:00:00+23:59", True), ("2026-11-09T15:00:00", False),
                             ("2026-11-09T15:00:00+24:00", False), ("2026-11-09T15:00:00.123456789Z", True)):
            with self.subTest(value=value):
                self.evidence["builds"][0]["queueTime"] = value
                self.evidence["build_time_bindings"][0]["queue_time"] = value
                row = self.repo()["builds"][0]
                self.assertEqual(row["bindings_complete"], valid, row)
                self.assertEqual(row.get("queue_time"), value if valid else None)

    def test_strict_integer_guid_and_cross_family_source_guards(self):
        cases = [("build_bindings", "definition_revision", True, "build.definition_revision"),
                 ("build_bindings", "repository_id", "22222222-2222-3333-4444-555555555555", "build.repository_id"),
                 ("build_source_bindings", "source_commit_sha", "b" * 40, "build.source_commit_sha"),
                 ("build_source_bindings", "source_ref_sha256", "b" * 64, "build.source_ref_sha256"),
                 ("build_time_bindings", "status", "inProgress", "build.status"),
                 ("build_time_bindings", "result", "failed", "build.result")]
        for family, field, value, code in cases:
            with self.subTest(field=field):
                saved = deepcopy(self.evidence[family])
                self.evidence[family][0][field] = value
                row = self.repo()["builds"][0]
                self.assertFalse(row["bindings_complete"])
                self.assertIn(code, row["binding_malformed_fields"])
                self.evidence[family] = saved

    def test_identical_family_duplicates_and_conflicts(self):
        for family in ("build_bindings", "build_source_bindings", "build_time_bindings", "pr_bindings"):
            with self.subTest(family=family):
                saved = deepcopy(self.evidence[family])
                self.evidence[family].append(deepcopy(saved[0]))
                self.assertTrue(self.repo()["bindings_complete"])
                self.evidence[family][-1]["binding_malformed_fields"] = ["pr.id" if family == "pr_bindings" else "build.id"]
                self.assertFalse(self.repo()["bindings_complete"])
                self.evidence[family] = saved

    def test_default_transport_and_no_cross_mode_fallback(self):
        self.proposal["options"]["build_ids"] = []
        self.evidence.update(requested_build_ids=[], timeline_scope="first-ten-listed-builds")
        self.evidence["default_build_bindings"] = {key: self.evidence.pop(source) for key, source in (
            ("repository_definition", "build_bindings"), ("source", "build_source_bindings"), ("time", "build_time_bindings"))}
        self.assertTrue(self.repo()["bindings_complete"])
        self.evidence["build_source_bindings"] = self.evidence["default_build_bindings"].pop("source")
        e = self.repo()
        self.assertFalse(e["bindings_complete"])
        self.assertIn("observation.build_bindings", e["binding_malformed_fields"])
        self.assertNotIn("source_ref_sha256", e["builds"][0])

    def test_request_selection_exact_sorted_capped_and_invalid_never_defaults(self):
        self.proposal["options"]["build_ids"] = [False, "9", 0, -1, 2147483648, 1.0]
        self.evidence.update(requested_build_ids=[], request_ids_invalid_count=6)
        e = self.repo()
        self.assertEqual(e["requested_build_ids"], [])
        self.assertEqual(e["request_ids_invalid_count"], 6)
        self.assertFalse(e["binding_coverage_complete"])
        self.assertEqual(e["builds"], [])
        self.assertEqual(e["timelines"], [])
        self.proposal["options"]["build_ids"] = list(range(33, 0, -1)) + [2, 2]
        self.evidence.update(requested_build_ids=list(range(1, 33)), request_ids_invalid_count=0, requested_build_ids_omitted_count=1)
        e = self.repo()
        self.assertEqual(e["requested_build_ids"], list(range(1, 33)))
        self.assertEqual(e["requested_build_ids_omitted_count"], 1)
        self.assertFalse(e["binding_coverage_complete"])
        self.assertNotIn(33, e["selected_builds_without_metadata"])

    def test_wrong_request_mode_and_missing_families_cannot_bind(self):
        self.evidence["timeline_scope"] = "first-ten-listed-builds"
        e = self.repo()
        self.assertFalse(e["builds"][0]["bindings_complete"])
        self.assertFalse(e["timelines"][0]["bindings_complete"])
        self.assertIn("observation.request_ids", e["binding_malformed_fields"])
        self.evidence["timeline_scope"] = "explicit-build-ids"
        for family in ("build_bindings", "build_source_bindings", "build_time_bindings", "pr_bindings", "timeline_bindings"):
            saved = self.evidence.pop(family)
            self.assertFalse(self.repo()["bindings_complete"], family)
            self.evidence[family] = saved

    def test_typed_container_requires_exact_diagnostic_arrays(self):
        container = self.evidence["timeline_bindings"][0]
        for field in ("binding_missing_fields", "binding_malformed_fields"):
            for value in (None, "PRIVATE_SENTINEL", ["PRIVATE_SENTINEL"], ["timeline.id", "timeline.id"]):
                with self.subTest(field=field, value=value):
                    saved = container.pop(field)
                    if value is not None:
                        container[field] = value
                    row = self.repo()["timelines"][0]
                    self.assertFalse(row["bindings_complete"])
                    self.assertEqual(row.get("records", []), [])
                    self.assertIn("timeline.records", row["binding_malformed_fields"])
                    container[field] = saved

    def test_parent_fact_exact_counterexamples(self):
        container = self.evidence["timeline_bindings"][0]
        mutations = [("parent_type", "Task", "timeline.parent_resolution"), ("child_id", "f" * 8 + "-0000-0000-0000-000000000000", "timeline.parent_resolution"),
                     ("build_id", 10, "timeline.build_id"), ("index_sha256", "f" * 64, "timeline.parent_resolution"),
                     ("native_record_count", 4, "timeline.parent_resolution"), ("parent_occurrences", 2, "timeline.parent_resolution"),
                     ("acyclic", False, "timeline.parent_resolution"), ("child_occurrences", True, "timeline.parent_resolution"),
                     ("resolution", "ambiguous", "timeline.parent_resolution")]
        for field, value, code in mutations:
            with self.subTest(field=field):
                saved = deepcopy(container["parent_validation_facts"])
                container["parent_validation_facts"][0][field] = value
                row = self.repo()["timelines"][0]
                self.assertFalse(row["bindings_complete"])
                self.assertFalse(row["records"][1]["bindings_complete"])
                self.assertIn(code, row["binding_malformed_fields"])
                container["parent_validation_facts"] = saved
        container["parent_validation_facts"].append(deepcopy(container["parent_validation_facts"][0]))
        row = self.repo()["timelines"][0]
        self.assertIn("timeline.duplicate_id", row["binding_malformed_fields"])
        self.assertFalse(row["records"][1]["bindings_complete"])

    def test_retained_duplicate_identity_self_and_ancestor_cycles(self):
        saved = deepcopy(self.evidence["timeline_bindings"][0])
        container = self.evidence["timeline_bindings"][0]
        container["records"][1]["id"] = container["records"][0]["id"]
        self.assertIn("timeline.duplicate_id", self.repo()["timelines"][0]["binding_malformed_fields"])
        self.evidence["timeline_bindings"][0] = deepcopy(saved)
        container = self.evidence["timeline_bindings"][0]
        container["records"][1]["parent_id"] = container["records"][1]["id"]
        container["parent_validation_facts"][0]["parent_id"] = container["records"][1]["id"]
        self.assertIn("timeline.parent_resolution", self.repo()["timelines"][0]["binding_malformed_fields"])
        self.evidence["timeline_bindings"][0] = deepcopy(saved)
        container = self.evidence["timeline_bindings"][0]
        first, second = container["records"][:2]
        first["parent_id"] = second["id"]
        fact = deepcopy(container["parent_validation_facts"][0])
        fact.update(child_id=first["id"], parent_id=second["id"], parent_type="Job")
        container["parent_validation_facts"].insert(0, fact)
        row = self.repo()["timelines"][0]
        self.assertTrue(all(not r["bindings_complete"] for r in row["records"]))
        self.assertIn("timeline.parent_resolution", row["binding_malformed_fields"])

    def test_producer_omitted_parent_conditionally_local_not_global(self):
        container = deepcopy(CONTRACT_OMITTED_PARENT["private_timeline"])
        self.evidence["timeline_bindings"] = [container]
        self.evidence["timelines"][0]["records"] = [{"id": container["records"][0]["id"], "state": "completed", "result": "skipped"}]
        self.evidence["binding_coverage"]["timelines"].update(CONTRACT_OMITTED_PARENT["reader_coverage"])
        row = self.repo()["timelines"][0]
        self.assertTrue(row["records"][0]["bindings_complete"], row)
        self.assertFalse(row["bindings_complete"])
        self.assertFalse(self.repo()["binding_coverage_complete"])
        self.assertFalse(self.repo()["bindings_complete"])
        self.evidence["binding_coverage"]["timelines"]["byte_capped"] = False
        row = self.repo()["timelines"][0]
        self.assertFalse(row["records"][0]["bindings_complete"])
        self.assertIn("timeline.parent_resolution", row["records"][0]["binding_missing_fields"])
        self.evidence["binding_coverage"]["timelines"]["byte_capped"] = True
        container["parent_validation_facts"] = []
        self.assertFalse(self.repo()["timelines"][0]["records"][0]["bindings_complete"])

    def test_consistent_forged_hidden_cycle_is_explicit_consumer_trust_limit(self):
        # No unseen native index is supplied: the public layer cannot detect a
        # coherent lie about it. The actual reader/composition must detect cycles.
        self.evidence["timeline_bindings"] = [deepcopy(CONTRACT_OMITTED_PARENT["private_timeline"])]
        container = self.evidence["timeline_bindings"][0]
        container["native_parent_index_sha256"] = "e" * 64
        container["parent_validation_facts"][0]["index_sha256"] = "e" * 64
        self.evidence["timelines"][0]["records"] = [{"id": container["records"][0]["id"], "state": "completed", "result": "skipped"}]
        self.evidence["binding_coverage"]["timelines"]["byte_capped"] = True
        e = self.repo()
        self.assertTrue(e["timelines"][0]["records"][0]["bindings_complete"])
        self.assertFalse(e["bindings_complete"])
        self.assertFalse(e["binding_coverage_complete"])

    def test_timeline_type_state_requiredness_and_safe_unknown_type(self):
        for field, value, code in (("type", "PRIVATE_SENTINEL", "timeline.type"), ("state", "PRIVATE_SENTINEL", "timeline.state"),
                                   ("result", "PRIVATE_SENTINEL", "timeline.result"), ("attempt", False, "timeline.attempt"),
                                   ("identifier_sha256", None, "timeline.identifier_sha256")):
            with self.subTest(field=field):
                record = self.evidence["timeline_bindings"][0]["records"][0]
                saved = deepcopy(record)
                record[field] = value
                row = self.repo()["timelines"][0]["records"][0]
                self.assertFalse(row["bindings_complete"])
                self.assertIn(code, row["binding_missing_fields"] + row["binding_malformed_fields"])
                if field == "type":
                    self.assertEqual(set(row), {"id", "bindings_complete", "binding_missing_fields", "binding_malformed_fields"})
                self.evidence["timeline_bindings"][0]["records"][0] = saved

    def test_global_coverage_is_recomputed_and_upstream_unknown_stays_unknown(self):
        self.evidence["binding_coverage"]["builds"]["returned_count"] = None
        self.evidence["binding_coverage"]["builds"]["omitted_count"] = None
        self.evidence["binding_coverage"]["builds"]["upstream_complete"] = False
        e = self.repo()
        self.assertIsNone(e["binding_coverage"]["builds"]["returned_count"])
        self.assertFalse(e["binding_coverage_complete"])
        self.assertFalse(e["bindings_complete"])
        self.assertTrue(e["builds"][0]["bindings_complete"])
        self.assertEqual(e["binding_coverage"]["builds"]["projected_count"], 1)

    def test_repository_guid_configuration_cannot_be_matched_by_foreign_name(self):
        self.proposal["remote"]["name"] = self.evidence["repository_id"]
        self.evidence["repository"]["name"] = self.proposal["remote"]["name"]
        self.evidence["repository"]["id"] = "22222222-2222-3333-4444-555555555555"
        e = self.repo()
        self.assertFalse(e["repository_matches_profile"])
        self.assertEqual(e["builds"], [])
        self.assertEqual(e["timelines"], [])

    def test_marked_missing_envelope_and_unknown_diagnostics_fail_closed(self):
        for key in ("evidence_contract", "observed_at", "repository_id", "requested_build_ids", "binding_coverage", "budget"):
            with self.subTest(key=key):
                saved = self.evidence.pop(key)
                if key == "budget":
                    result = harness_azure._project_repository_evidence(self.proposal, self.evidence)
                else:
                    result = self.repo()
                self.assertFalse(result["bindings_complete"])
                self.evidence[key] = saved
        self.evidence["build_source_bindings"][0]["binding_malformed_fields"] = ["PRIVATE_SENTINEL"]
        e = self.repo()
        self.assertFalse(e["builds"][0]["bindings_complete"])
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(e))

    def test_frozen_minimal_fallback_object_is_preserved(self):
        minimal = harness_azure._minimal_repository_fallback()
        self.assertEqual(harness_azure._project_repository_evidence(self.proposal, minimal), minimal)
        self.assertIsNone(minimal["budget"]["public_bytes"])

    def test_whole_public_overflow_returns_complete_json_omission(self):
        prefix = "azdo:" + "x" * 110000 + ":p:"
        proposal = {"operation": "azure-inspect", "remote": {"organization": "x" * 110000, "project": "p"}}
        body = {"inspection_mode": "offline-snapshot", "complete": True,
                "items": [{"id": prefix + "1"}, {"id": prefix + "2"}]}
        result = harness_azure.project_result(proposal, json.dumps(body).encode())
        self.assertTrue(result["items_truncated"])
        self.assertEqual(result["items"], [])
        self.assertFalse(result["complete"])
        self.assertEqual(result["repository_evidence"], harness_azure._minimal_repository_fallback())
        self.assertLessEqual(len((json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()), 196608)

    def stage_records(self, count):
        return [self.binding(id="00000000-0000-0000-0000-%012x" % (number + 1), type="Stage", state="completed",
                             result="skipped", identifier_sha256="a" * 64, attempt=2147483647) for number in range(count)]

    def set_timeline_records(self, records, *, returned=None):
        returned = len(records) if returned is None else returned
        self.evidence["timeline_bindings"][0] = self.binding(
            build_id=9, record_count=returned, returned_record_count=returned, projected_record_count=len(records),
            records=records, states_recognized=True, records_truncated=returned > len(records),
            native_parent_index_sha256="a" * 64, parent_validation_facts=[])
        self.evidence["timelines"][0]["records"] = [{"id": row["id"], "state": row["state"], "result": row["result"], "type": row["type"]} for row in records]

    def test_public_count_and_byte_caps_preserve_original_counts_and_prefix(self):
        records = self.stage_records(256)
        self.set_timeline_records(records, returned=257)
        self.evidence["binding_coverage"]["timelines"]["count_capped"] = True
        result = self.project()
        e = result["repository_evidence"]
        row = e["timelines"][0]
        self.assertEqual(row["record_count"], 257)
        self.assertEqual(row["returned_record_count"], 257)
        self.assertEqual(row["projected_record_count"], len(row["records"]))
        self.assertLess(len(row["records"]), 256)
        self.assertEqual(row["records"], records[:len(row["records"])])
        self.assertTrue(row["records_truncated"])
        self.assertTrue(e["binding_coverage"]["timelines"]["count_capped"])
        self.assertTrue(e["binding_coverage"]["timelines"]["byte_capped"])
        self.assertTrue(e["budget"]["aggregate_truncated"])
        self.assertFalse(e["bindings_complete"])
        self.assertFalse(e["complete"])
        self.assertLessEqual(e["budget"]["public_bytes"], 98304)
        self.assertEqual(e["budget"]["public_bytes"], len((json.dumps({"repository_evidence": e}, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode()))
        self.assertLessEqual(len((json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()), 196608)

    def test_global_record_tail_removal_uses_ascending_build_id(self):
        records = self.stage_records(180)
        self.set_timeline_records(deepcopy(records))
        original = deepcopy(self.evidence["timeline_bindings"][0])
        original["build_id"] = 2
        self.evidence["timeline_bindings"].append(original)
        self.evidence["timelines"].append({"build_id": 2, "records": deepcopy(self.evidence["timelines"][0]["records"])})
        self.proposal["options"]["build_ids"] = [9, 2]
        self.evidence["requested_build_ids"] = [2, 9]
        build = deepcopy(self.evidence["builds"][0]);build["id"] = 2
        self.evidence["builds"].append(build)
        for family in ("build_bindings", "build_source_bindings", "build_time_bindings"):
            row = deepcopy(self.evidence[family][0]);row["build_id"] = 2
            self.evidence[family].insert(0, row)
        for family in ("builds", "timelines"):
            self.evidence["binding_coverage"][family].update(returned_count=2, projected_count=2, bound_count=2)
        e = self.repo()
        by_build = {row["build_id"]: row for row in e["timelines"]}
        self.assertEqual(by_build[2]["records"], records)
        self.assertLess(len(by_build[9]["records"]), len(records))
        self.assertEqual(by_build[9]["records"], records[:len(by_build[9]["records"])])
        self.assertEqual(by_build[2]["records"], records[:len(by_build[2]["records"])])
        self.assertLessEqual(e["budget"]["public_bytes"], 98304)

    def test_legacy_typed_state_and_parent_contradictions_are_refused(self):
        for key, value, code in (("state", "inProgress", "timeline.state"), ("result", "failed", "timeline.result"),
                                 ("type", "Task", "timeline.type"), ("parentId", "00000000-0000-0000-0000-000000000003", "timeline.parent_id")):
            saved = deepcopy(self.evidence["timelines"][0]["records"][1])
            self.evidence["timelines"][0]["records"][1][key] = value
            row = self.repo()["timelines"][0]
            self.assertFalse(row["records"][1]["bindings_complete"])
            self.assertIn(code, row["binding_malformed_fields"])
            self.evidence["timelines"][0]["records"][1] = saved

    def test_normalized_build_duplicates_do_not_overwrite_legacy_summary(self):
        second = deepcopy(self.evidence["builds"][0])
        second["buildNumber"] = "PRIVATE_SENTINEL"
        self.evidence["builds"].append(second)
        self.evidence["binding_coverage"]["builds"].update(returned_count=2, projected_count=2, bound_count=2)
        self.assertTrue(all(row["bindings_complete"] for row in self.repo()["builds"]))
        second["result"] = "failed"
        rows = self.repo()["builds"]
        self.assertEqual([row["result"] for row in rows], ["succeeded", "failed"])
        self.assertTrue(all(not row["bindings_complete"] for row in rows))
        self.assertTrue(all("build.id" in row["binding_malformed_fields"] for row in rows))

    def test_missing_parent_fact_does_not_taint_valid_root_binding(self):
        self.evidence["timeline_bindings"][0]["parent_validation_facts"].pop(0)
        records = self.repo()["timelines"][0]["records"]
        self.assertTrue(records[0]["bindings_complete"])
        self.assertFalse(records[1]["bindings_complete"])
        self.assertIn("timeline.parent_resolution", records[1]["binding_missing_fields"])

    def test_reader_byte_counter_is_checked_against_actual_private_representation(self):
        self.project()
        self.evidence["budget"]["reader_bytes"] += 1
        e = harness_azure._project_repository_evidence(self.proposal, self.evidence)
        self.assertFalse(e["bindings_complete"])
        self.assertIn("observation.coverage", e["binding_malformed_fields"])

    def test_exact_repository_threshold_and_one_byte_over(self):
        # Find a valid public record sequence just above the real limit, then
        # shorten only strict positive integer attempts to land on byte 98304.
        for count in range(200, 240):
            self.set_timeline_records(self.stage_records(count))
            with patch.object(harness_azure, "_REPOSITORY_BYTE_LIMIT", 1000000):
                size = self.repo()["budget"]["public_bytes"]
            if 98304 < size <= 98304 + 9 * count:
                break
        else:
            self.fail("No exact-threshold fixture found")
        records = self.evidence["timeline_bindings"][0]["records"]
        for record in records:
            gap = size - 98304
            if gap <= 0:
                break
            shorten = min(9, gap)
            record["attempt"] = 10 ** (9 - shorten)
            with patch.object(harness_azure, "_REPOSITORY_BYTE_LIMIT", 1000000):
                size = self.repo()["budget"]["public_bytes"]
        self.assertEqual(size, 98304)
        exact = self.repo()
        self.assertEqual(exact["budget"]["public_bytes"], 98304)
        self.assertFalse(exact["budget"]["aggregate_truncated"])
        self.assertEqual(exact["timelines"][0]["projected_record_count"], count)
        record = next(row for row in records if row["attempt"] < 1000000000)
        record["attempt"] *= 10
        with patch.object(harness_azure, "_REPOSITORY_BYTE_LIMIT", 1000000):
            self.assertEqual(self.repo()["budget"]["public_bytes"], 98305)
        over = self.repo()
        self.assertTrue(over["budget"]["aggregate_truncated"])
        self.assertLessEqual(over["budget"]["public_bytes"], 98304)
        self.assertLess(over["timelines"][0]["projected_record_count"], count)

    def test_exact_whole_public_threshold_and_one_byte_over(self):
        proposal = {"operation": "azure-inspect", "remote": {"organization": "o", "project": "p"}}
        body = {"inspection_mode": "offline-snapshot", "complete": True, "items": [{"id": "azdo:o:p:1"}]}
        def project():
            return harness_azure.project_result(proposal, json.dumps(body).encode())
        size = len((json.dumps(project(), sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode())
        body["items"][0]["id"] += "1" * (196608 - size)
        exact = project()
        self.assertEqual(len((json.dumps(exact, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()), 196608)
        self.assertFalse(exact["items_truncated"])
        body["items"][0]["id"] += "1"
        over = project()
        self.assertEqual(over["items"], [])
        self.assertTrue(over["items_truncated"])
        self.assertFalse(over["complete"])

    def test_public_omitted_parent_preserves_prevalidated_local_child(self):
        records = self.stage_records(256)
        records[0].update(type="Job", parent_id=records[-1]["id"])
        self.set_timeline_records(records)
        container = self.evidence["timeline_bindings"][0]
        fact = deepcopy(CONTRACT_OMITTED_PARENT["private_timeline"]["parent_validation_facts"][0])
        fact.update(parent_id=records[-1]["id"], native_record_count=256, index_sha256="a" * 64)
        container["parent_validation_facts"] = [fact]
        self.evidence["timelines"][0]["records"][0]["parentId"] = records[-1]["id"]
        e = self.repo()
        retained = e["timelines"][0]["records"]
        self.assertEqual(retained[0]["id"], records[0]["id"])
        self.assertTrue(retained[0]["bindings_complete"])
        self.assertNotIn(records[-1]["id"], {row["id"] for row in retained})
        self.assertFalse(e["timelines"][0]["bindings_complete"])
        self.assertFalse(e["binding_coverage_complete"])
        self.assertTrue(e["binding_coverage"]["timelines"]["byte_capped"])

    def test_default_selection_counts_original_positions_including_invalid_rows(self):
        self.proposal["options"]["build_ids"] = []
        self.evidence.update(requested_build_ids=[], timeline_scope="first-ten-listed-builds")
        self.evidence["default_build_bindings"] = {key: self.evidence.pop(source) for key, source in (
            ("repository_definition", "build_bindings"), ("source", "build_source_bindings"), ("time", "build_time_bindings"))}
        self.evidence["builds"] = [None] * 10 + self.evidence["builds"]
        self.evidence["binding_coverage"]["builds"].update(returned_count=11, projected_count=11)
        e = self.repo()
        self.assertFalse(e["bindings_complete"])
        self.assertFalse(e["builds"][0]["bindings_complete"])
        self.assertIn("observation.build_bindings", e["binding_malformed_fields"])

    def test_malformed_json_values_at_all_binding_boundaries_are_bounded(self):
        paths = [("evidence_contract",), ("observed_at",), ("repository_id",), ("requested_build_ids",),
                 ("request_ids_invalid_count",), ("requested_build_ids_omitted_count",),
                 ("binding_coverage",), ("binding_coverage", "builds", "returned_count"),
                 ("binding_coverage", "observation", "projected_count"), ("budget",),
                 ("pull_requests", 0, "pullRequestId"), ("pull_requests", 0, "status"),
                 ("pull_requests", 0, "lastMergeSourceCommit"), ("pull_requests", 0, "sourceRefName"),
                 ("builds", 0, "id"), ("builds", 0, "status"), ("builds", 0, "result"),
                 ("build_bindings", 0, "build_id"), ("build_source_bindings", 0, "binding_missing_fields"),
                 ("build_time_bindings", 0, "queue_time"), ("timeline_bindings", 0, "build_id"),
                 ("timeline_bindings", 0, "records"), ("timeline_bindings", 0, "records", 0, "id"),
                 ("timeline_bindings", 0, "records", 0, "type"), ("timeline_bindings", 0, "records", 0, "state"),
                 ("timeline_bindings", 0, "records", 0, "attempt"), ("timeline_bindings", 0, "parent_validation_facts"),
                 ("timeline_bindings", 0, "parent_validation_facts", 0, "child_id"),
                 ("timeline_bindings", 0, "parent_validation_facts", 0, "parent_type"),
                 ("timeline_bindings", 0, "parent_validation_facts", 0, "resolution"),
                 ("timeline_bindings", 0, "parent_validation_facts", 0, "native_record_count"),
                 ("timelines", 0, "records", 0, "id")]
        original = deepcopy(self.evidence)
        for path in paths:
            for value in (None, True, -1, 1.5, "PRIVATE_SENTINEL", [], {}, ["PRIVATE_SENTINEL"]):
                with self.subTest(path=path, value=value):
                    self.evidence = deepcopy(original)
                    obj = self.evidence
                    for key in path[:-1]:
                        obj = obj[key]
                    obj[path[-1]] = value
                    if isinstance(self.evidence.get("budget"), dict):
                        result = self.project()
                    else:
                        result = harness_azure.project_result(self.proposal, json.dumps({"inspection_mode": "live-read-only", "repository_evidence": self.evidence}).encode())
                    public = json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
                    self.assertLessEqual(len(public.encode()), 196608)
                    self.assertNotIn("PRIVATE_SENTINEL", public)
                    self.assertFalse(result["accepted_progress"])
                    self.assertFalse(result["completion"])
                    self.assertLessEqual(len((json.dumps({"repository_evidence": result["repository_evidence"]}, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()), 98304)

    def test_missing_repository_binding_is_missing_and_foreign_is_malformed(self):
        row = self.evidence["build_bindings"][0]
        row.pop("repository_id")
        e = self.repo()
        self.assertIn("build.repository_id", e["builds"][0]["binding_missing_fields"])
        self.assertNotIn("build.repository_id", e["builds"][0]["binding_malformed_fields"])
        self.assertEqual(e["selected_builds_without_repository"], [9])
        row["repository_id"] = "22222222-2222-3333-4444-555555555555"
        e = self.repo()
        self.assertIn("build.repository_id", e["builds"][0]["binding_malformed_fields"])
        self.assertNotIn("build.repository_id", e["builds"][0]["binding_missing_fields"])

    def test_selected_source_summary_includes_contradictory_binding(self):
        self.evidence["build_source_bindings"][0]["source_commit_sha"] = "b" * 40
        self.assertEqual(self.repo()["selected_builds_without_source"], [9])

    def test_review_default_selected_build_requires_both_timeline_transports(self):
        self.proposal["options"]["build_ids"] = []
        self.evidence.update(requested_build_ids=[], timeline_scope="first-ten-listed-builds")
        self.evidence["default_build_bindings"] = {key: self.evidence.pop(source) for key, source in (
            ("repository_definition", "build_bindings"), ("source", "build_source_bindings"), ("time", "build_time_bindings"))}
        original = deepcopy(self.evidence)
        for absent in (("timelines", "timeline_bindings"), ("timelines",), ("timeline_bindings",)):
            with self.subTest(absent=absent):
                self.evidence = deepcopy(original)
                for key in absent:
                    self.evidence[key] = []
                count = 0 if len(absent) == 2 else 1
                self.evidence["binding_coverage"]["timelines"].update(returned_count=count, projected_count=count, bound_count=count)
                e = self.repo()
                self.assertFalse(e["complete"])
                self.assertFalse(e["bindings_complete"])
                self.assertFalse(e["binding_coverage_complete"])
                self.assertIn("observation.timeline_bindings", e["binding_missing_fields"])
                self.assertIn("timeline.records", e["binding_missing_fields"])
                self.assertEqual(e["requested_build_ids"], [])
                self.assertEqual(e["selected_builds_without_timeline"], [])

    def test_review_unmatched_legacy_failed_or_skipped_records_are_not_complete(self):
        original = deepcopy(self.evidence)
        for result in ("failed", "skipped"):
            with self.subTest(result=result):
                self.evidence = deepcopy(original)
                self.evidence["timelines"][0]["records"].append({"id": "00000000-0000-0000-0000-000000000099", "state": "completed", "result": result})
                e = self.repo()
                timeline = e["timelines"][0]
                self.assertFalse(e["complete"])
                self.assertFalse(e["bindings_complete"])
                self.assertFalse(e["binding_coverage_complete"])
                self.assertFalse(timeline["bindings_complete"])
                self.assertIn("timeline.records", timeline["binding_malformed_fields"])
                self.assertEqual(timeline["record_count"], 4)
                self.assertIsNone(timeline["returned_record_count"])
                self.assertTrue(timeline["records_truncated"])
        self.evidence = deepcopy(original)
        timeline = self.evidence["timeline_bindings"][0]
        timeline.update(record_count=4, returned_record_count=4)
        e = self.repo()
        self.assertFalse(e["bindings_complete"])
        self.assertTrue(e["timelines"][0]["records_truncated"])
        self.assertIn("timeline.records", e["binding_malformed_fields"])

    def test_review_supplied_legacy_parent_and_attempt_cannot_be_omitted(self):
        original = deepcopy(self.evidence)
        for key, value, code in (("parentId", "PRIVATE_SENTINEL", "timeline.parent_id"),
                                 ("parentId", original["timelines"][0]["records"][0]["id"], "timeline.parent_resolution"),
                                 ("attempt", False, "timeline.attempt"), ("attempt", [], "timeline.attempt")):
            with self.subTest(key=key, value=value):
                self.evidence = deepcopy(original)
                self.evidence["timelines"][0]["records"][0][key] = value
                if key == "attempt":
                    self.evidence["timeline_bindings"][0]["records"][0].pop("attempt")
                e = self.repo()
                row = e["timelines"][0]["records"][0]
                self.assertFalse(row["bindings_complete"])
                self.assertFalse(e["bindings_complete"])
                self.assertIn(code, row["binding_malformed_fields"])
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(e))
        self.evidence = deepcopy(original)
        self.evidence["timelines"][0]["records"][0]["parentId"] = original["timelines"][0]["records"][1]["id"]
        self.evidence["timelines"][0]["records"][1]["parentId"] = original["timelines"][0]["records"][0]["id"]
        rows = self.repo()["timelines"][0]["records"]
        for row in rows[:2]:
            self.assertIn("timeline.parent_resolution", row["binding_malformed_fields"])
            self.assertFalse(row["bindings_complete"])
        self.evidence = deepcopy(original)
        self.evidence["timelines"][0]["records"][0]["attempt"] = 2
        self.evidence["timeline_bindings"][0]["records"][0].pop("attempt")
        row = self.repo()["timelines"][0]["records"][0]
        self.assertIn("timeline.attempt", row["binding_missing_fields"])

    def test_review_native_optional_timestamps_validate_without_sidecar_counterpart(self):
        self.evidence["builds"][0].update(status="notStarted", result=None, startTime=None, finishTime=None)
        timing = self.evidence["build_time_bindings"][0]
        timing.update(status="notStarted", result=None)
        timing.pop("start_time");timing.pop("finish_time")
        self.assertTrue(self.repo()["builds"][0]["bindings_complete"])
        for raw, public in (("startTime", "start_time"), ("finishTime", "finish_time")):
            for invalid in ([], False, "PRIVATE_SENTINEL", "2028-12-31T23:59:60Z"):
                with self.subTest(raw=raw, invalid=invalid):
                    self.evidence["builds"][0][raw] = invalid
                    e = self.repo()
                    self.assertFalse(e["bindings_complete"])
                    self.assertIn("build." + public, e["builds"][0]["binding_malformed_fields"])
                    self.assertNotIn(public, e["builds"][0])
            self.evidence["builds"][0][raw] = "2026-11-09T15:01:00Z"
            self.assertIn("build." + public, self.repo()["builds"][0]["binding_missing_fields"])
            self.evidence["builds"][0][raw] = None
        row = self.evidence["timelines"][0]["records"][0]
        row.update(parentId=None, attempt=None)
        self.assertTrue(self.repo()["bindings_complete"])

    def test_review_exponent_overflow_rejected_even_in_discarded_fields(self):
        paths = [("private",), ("build_bindings", 0, "definition_revision"),
                 ("build_source_bindings", 0, "source_commit_sha"),
                 ("timeline_bindings", 0, "parent_validation_facts", 0, "native_record_count")]
        for path in paths:
            for number in ("1e999", "-1e999", "1e309", "NaN", "Infinity", "-Infinity"):
                with self.subTest(path=path, number=number):
                    evidence = deepcopy(self.evidence)
                    obj = evidence
                    for key in path[:-1]:
                        obj = obj[key]
                    obj[path[-1]] = "OVERFLOW_TOKEN"
                    raw = json.dumps({"inspection_mode": "live-read-only", "repository_evidence": evidence}).replace('"OVERFLOW_TOKEN"', number).encode()
                    result = harness_azure.project_result(self.proposal, raw)
                    self.assertEqual(result, {"schema_version": "atlas-tools.azure-result.v1", "operation": "azure-inspect", "status": "unavailable", "accepted_progress": False, "completion": False, "failure_code": "invalid_backend_json"})
                    self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))


    def test_review_measurement_failure_has_fixed_sanitized_unavailable_shape(self):
        for error in (ValueError("PRIVATE_SENTINEL"), RecursionError("PRIVATE_SENTINEL")):
            with self.subTest(error=type(error).__name__), patch.object(harness_azure, "_repository_bytes", side_effect=error):
                result = self.project()
                self.assertEqual(result, {"schema_version": "atlas-tools.azure-result.v1", "operation": "azure-inspect", "status": "unavailable", "accepted_progress": False, "completion": False, "failure_code": "invalid_backend_json"})
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
