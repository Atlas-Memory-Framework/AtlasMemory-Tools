from __future__ import annotations

import contextlib
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import atlas_intake as intake
import atlas_azure_devops as az
import atlas_runtime_config as config
from atlas_authority import canonical_digest
from atlas_dispatch import AzureDispatcher, DispatchBlocked
from atlas_human_gates import gate_bindings

NOW = 1_800_000_000
URL = "https://dev.azure.com/Instablinds/Instablinds/_git/Website"
ID = "azdo:Instablinds:Instablinds:17"


def definition_fixture():
    manifest = {"schema_version": 1, "organization": "Instablinds", "project": "Instablinds", "dependencies": {ID: []}}
    packet = {"schema_version": 1, "id": ID, "revision": 7, "repository_url": URL, "base_branch": "develop",
        "base_commit": "a" * 40, "branch": "feature/intake", "task": "Implement the reviewed product behavior.",
        "write_scope": ["src/product.py"], "commands": [{"id": "unit", "argv": ["python3", "-B", "tests/acceptance.py"], "timeout_seconds": 30}],
        "acceptance": [{"id": "unit", "command_id": "unit", "evidence_file": "unit.json"}], "role_timeout_seconds": 60,
        "expected_manifest": manifest, "inspection_authority": {"dependency_contract_sha256": az.canonical_digest(manifest),
            "approval_record": "synthetic-graph-fixture-only", "execution_authorized": True}}
    return {"schema_version": 1, "owner": "operator", "worker_packet": packet,
        "step": {"id": "prepare", "kind": "coding", "action": "local_execute", "candidate_sha": None},
        "sources": [{"id": "instructions", "kind": "instructions", "path": "AGENTS.md"},
                    {"id": "product", "kind": "file", "path": "src/product.py"},
                    {"id": "tests", "kind": "tests", "path": "tests/acceptance.py"}],
        "affected_paths": ["src/product.py"], "points": 2, "human_gates": [], "attempts": [],
        "budget": {"max_model_calls": 10, "max_tokens": 100000, "model_calls_used": 0, "tokens_used": 0}}


def snapshot_fixture(definition, *, now=NOW, revision=7, complete=True):
    packet = definition["worker_packet"]
    raw = {"id": 17, "rev": revision, "fields": {"System.State": "To Do", "System.Title": "Private title not projected", "System.TeamProject": "Instablinds"}, "relations": []}
    return az.project_snapshot({"items": [raw], "complete": complete,
        "observed_at": datetime.fromtimestamp(now, timezone.utc).isoformat()}, organization="Instablinds", project="Instablinds",
        expected_manifest=packet.get("expected_manifest"), authority=packet.get("inspection_authority"), clock=lambda: now)


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.runtime = self.home / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.workspace = self.home / "repo"
        self.workspace.mkdir(mode=0o700)
        (self.workspace / "src").mkdir(mode=0o700)
        (self.workspace / "tests").mkdir(mode=0o700)
        (self.workspace / "AGENTS.md").write_text("Keep source scoped. Run reviewed acceptance commands.")
        (self.workspace / "src/product.py").write_text("VALUE = 1\n")
        (self.workspace / "tests/acceptance.py").write_text("assert True  # primary fixture implementation, never executed\n")
        self.identity = mock.patch.object(config.pwd, "getpwuid", return_value=types.SimpleNamespace(pw_dir=str(self.home), pw_name="fixture"))
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.config = config.RuntimeConfig("azure-devops", self.runtime,
            {"organization": "Instablinds", "project": "Instablinds", "name": "Website", "url": URL,
             "base_branch": "develop", "checkout": str(self.workspace)}, frozenset({"read"}),
            {role: config.RoleSettings("gpt-6-astra", "max", "fixture") for role in config.ROLES}, "fixture")
        self.definition = definition_fixture()
        self.policy = json.loads((ROOT / "config/routing.example.json").read_text())
        self.policy["repository_url"] = URL
        self.snapshot = snapshot_fixture(self.definition)

    def build(self, **kwargs):
        return intake.build_intake(self.config, self.policy, self.definition, self.snapshot, context_root=self.workspace, now=kwargs.pop("now", NOW), **kwargs)

    def files(self):
        return {str(path.relative_to(self.home)): path.read_bytes() for path in self.home.rglob("*") if path.is_file()}

    def test_complete_explicit_definition_is_actual_dispatcher_input(self):
        before = self.files()
        report = self.build()
        self.assertTrue(report["valid"])
        self.assertEqual(report["state"], "ready_for_routing")
        self.assertEqual(report["intake"]["worker_packet"], self.definition["worker_packet"])
        dispatcher = AzureDispatcher(self.config, self.policy, report["intake"], report["snapshot"], context_root=self.workspace, clock=lambda: NOW)
        preview = dispatcher.preview()
        self.assertTrue(preview["decision"]["assessment_required"])
        self.assertEqual(report["intake"]["readiness"]["source_sha256"], canonical_digest(report["snapshot"]))
        self.assertEqual(before, self.files())
        self.assertFalse(report["execution_authorized"])
        self.assertFalse(report["completion"])

    def test_missing_commands_scope_acceptance_and_owner_are_actionable_draft(self):
        original = deepcopy(self.definition)
        for field in ("commands", "acceptance", "write_scope", "base_commit"):
            self.definition["worker_packet"].pop(field)
        self.definition.pop("owner")
        report = self.build()
        self.assertEqual(report["state"], "draft")
        self.assertIsNone(report["intake"])
        self.assertIn("worker_packet.commands", report["missing_fields"])
        self.assertIn("worker_packet.acceptance", report["missing_fields"])
        self.assertIn("owner", report["missing_fields"])
        self.assertFalse(any(question["owner"] for question in report["human_questions"]))
        self.assertNotIn("commands", report["draft"]["worker_packet"])
        self.assertNotEqual(original, self.definition)  # Only explicit fixture edits above.

    def test_snapshot_revision_can_fill_initial_draft_but_not_rebind_reviewed_revision(self):
        del self.definition["worker_packet"]["revision"]
        report = self.build()
        self.assertEqual(report["intake"]["worker_packet"]["revision"], 7)
        self.assertNotIn("revision", self.definition["worker_packet"])
        self.definition["worker_packet"]["revision"] = 6
        changed = self.build()
        self.assertFalse(changed["valid"])
        self.assertIn("worker_packet.revision", changed["missing_fields"])
        self.assertEqual(changed["draft"]["worker_packet"]["revision"], 6)

    def test_unchanged_fresh_refresh_preserves_exact_intake_and_snapshot(self):
        first = self.build()
        self.snapshot = snapshot_fixture(self.definition, now=NOW + 20)
        second = self.build(now=NOW + 20, previous=first)
        self.assertTrue(second["reused"])
        self.assertEqual(first["material_fingerprint"], second["material_fingerprint"])
        self.assertEqual(first["intake_sha256"], second["intake_sha256"])
        self.assertEqual(first["snapshot"], second["snapshot"])
        self.assertNotEqual(second["snapshot_sha256"], second["current_observation"]["snapshot_sha256"])

    def test_expired_prior_intake_refreshes_exact_hash_without_material_churn(self):
        first = self.build()
        self.snapshot = snapshot_fixture(self.definition, now=NOW + 301)
        second = self.build(now=NOW + 301, previous=first)
        self.assertFalse(second["reused"])
        self.assertEqual(first["material_fingerprint"], second["material_fingerprint"])
        self.assertNotEqual(first["intake_sha256"], second["intake_sha256"])

    def test_same_blocked_dependencies_reuse_without_new_authority_annotations(self):
        self.definition["worker_packet"]["inspection_authority"]["execution_authorized"] = False
        self.snapshot = snapshot_fixture(self.definition)
        first = self.build()
        self.assertEqual(first["state"], "blocked")
        self.snapshot = snapshot_fixture(self.definition, now=NOW + 20)
        second = self.build(now=NOW + 20, previous=first)
        self.assertTrue(second["reused"])
        self.assertFalse(second["intake"]["readiness"]["execution_authority_established"])
        self.assertFalse(second["intake"]["worker_packet"]["inspection_authority"]["execution_authorized"])

    def test_source_content_policy_config_or_scope_change_invalidates_material(self):
        first = self.build()
        (self.workspace / "src/product.py").write_text("VALUE = 2\n")
        second = self.build(previous=first)
        self.assertFalse(second["reused"])
        self.assertNotEqual(first["material_fingerprint"], second["material_fingerprint"])
        self.policy["version"] += 1
        third = self.build(previous=second)
        self.assertNotEqual(second["material_fingerprint"], third["material_fingerprint"])
        self.config = replace(self.config, capabilities=frozenset({"read", "assess"}))
        fourth = self.build(previous=third)
        self.assertNotEqual(third["material_fingerprint"], fourth["material_fingerprint"])

    def test_forged_previous_intake_cannot_launder_changed_commands(self):
        first = self.build()
        first["intake"]["worker_packet"]["commands"][0]["argv"] = ["python3", "other.py"]
        first["intake_sha256"] = canonical_digest(first["intake"])
        self.snapshot = snapshot_fixture(self.definition, now=NOW + 10)
        second = self.build(now=NOW + 10, previous=first)
        self.assertFalse(second["reused"])
        self.assertEqual(second["intake"]["worker_packet"]["commands"], self.definition["worker_packet"]["commands"])

    def test_stale_partial_or_missing_selected_reads_cannot_route(self):
        stale = self.build(now=NOW + 301)
        self.assertEqual(stale["state"], "blocked")
        self.assertIn("snapshot-is-stale-or-future-dated", stale["blockers"])
        self.snapshot = snapshot_fixture(self.definition, complete=False)
        partial = self.build()
        self.assertEqual(partial["state"], "blocked")
        self.assertFalse(partial["intake"]["readiness"]["complete"])
        self.snapshot["items"] = []
        missing = self.build()
        self.assertEqual(missing["state"], "draft")
        self.assertIn("snapshot.issue_revision", missing["missing_fields"])

    def test_missing_snapshot_never_uses_current_time_as_board_observation(self):
        self.snapshot = None
        result = self.build()
        self.assertEqual(result["state"], "draft")
        self.assertIsNone(result["current_observation"]["observed_at"])
        self.assertIn("snapshot.observed_at", result["missing_fields"])

    def test_duplicate_boolean_revision_and_cross_namespace_fail_closed(self):
        for change in (lambda value: value["items"].append(deepcopy(value["items"][0])),
                       lambda value: value["items"][0].update(id="azdo:Other:Project:17")):
            self.snapshot = snapshot_fixture(self.definition)
            change(self.snapshot)
            with self.assertRaises(intake.IntakeError):
                self.build()
        self.snapshot = snapshot_fixture(self.definition)
        self.snapshot["items"][0]["revision"] = True
        self.assertEqual(self.build()["state"], "draft")

    def test_native_dependency_change_is_material_even_when_still_blocked(self):
        first = self.build()
        dependency = "azdo:Instablinds:Instablinds:18"
        self.snapshot["items"][0]["dependencies"] = [dependency]
        self.snapshot["items"][0]["native_dependencies"] = [dependency]
        self.snapshot["items"][0]["eligible"] = False
        self.snapshot["items"][0]["blockers"] = ["dependency-not-completed:" + dependency]
        self.snapshot["dependency_complete"] = False
        self.snapshot["blockers"] = ["unresolved-dependency-closure"]
        result = self.build(previous=first)
        self.assertEqual(result["native_dependencies"], [dependency])
        self.assertEqual(result["intake"]["snapshot"] if "snapshot" in result["intake"] else result["snapshot"], self.snapshot)
        self.assertNotEqual(result["material_fingerprint"], first["material_fingerprint"])
        self.assertEqual(result["state"], "blocked")

    def test_no_snapshot_eligibility_or_local_flag_amplifies_execution_authority(self):
        self.definition["worker_packet"]["inspection_authority"]["execution_authorized"] = False
        # Even a caller-supplied clear snapshot cannot override the explicit
        # original inspection annotation, and neither would confer a grant.
        result = self.build()
        self.assertFalse(result["intake"]["readiness"]["execution_authority_established"])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["state"], "blocked")
        self.definition["execution_authorized"] = True
        with self.assertRaises(intake.IntakeError):
            self.build()

    def test_nested_instructions_must_be_declared_without_automatic_content_injection(self):
        (self.workspace / "src/AGENTS.md").write_text("Additional scope rule.")
        result = self.build()
        self.assertIn("sources.instructions:src/AGENTS.md", result["missing_fields"])
        self.definition["sources"].append({"id": "nested-instructions", "kind": "instructions", "path": "src/AGENTS.md"})
        complete = self.build()
        self.assertTrue(complete["valid"])
        self.assertEqual(complete["instruction_coverage"]["required"], ["AGENTS.md", "src/AGENTS.md"])

    def test_unsafe_paths_and_symlinked_sources_are_rejected_before_read(self):
        for path in ("../other", "/etc/passwd", ".env", "authority/trust.json"):
            self.definition["sources"][1]["path"] = path
            with self.subTest(path=path), self.assertRaises(DispatchBlocked):
                self.build()
        self.definition["sources"][1]["path"] = "src/product.py"
        path = self.workspace / "src/product.py"
        path.unlink()
        path.symlink_to(self.workspace / "AGENTS.md")
        with self.assertRaises(DispatchBlocked):
            self.build()

    def test_declared_missing_source_yields_question_not_fabricated_file_evidence(self):
        (self.workspace / "tests/acceptance.py").unlink()
        result = self.build()
        self.assertFalse(result["valid"])
        self.assertIn("sources.unavailable:tests/acceptance.py", result["missing_fields"])
        self.assertIsNone(result["intake"])

    def test_parent_symlink_is_rejected_before_any_leaf_lookup_or_content_read(self):
        (self.workspace / "src/product.py").unlink()
        (self.workspace / "src").rmdir()
        (self.workspace / "src").symlink_to("/home/a-different-identity/source", target_is_directory=True)
        original = Path.lstat
        def checked(path, *args, **kwargs):
            self.assertNotEqual(path, self.workspace / "src/product.py", "must reject symlink parent before leaf stat")
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "lstat", new=checked), self.assertRaises(DispatchBlocked):
            self.build()

    def test_missing_file_declaration_rejects_file_that_has_appeared(self):
        self.definition["sources"][1]["kind"] = "file_missing"
        with self.assertRaises(intake.IntakeError):
            self.build()
        (self.workspace / "src/product.py").unlink()
        self.assertTrue(self.build()["valid"])

    def test_empty_or_unsafe_commands_never_generate_acceptance(self):
        self.definition["worker_packet"]["commands"][0]["argv"] = ["bash", "-c", "exit 0"]
        result = self.build()
        self.assertEqual(result["state"], "draft")
        self.assertIn("worker_packet.commands", result["missing_fields"])
        self.assertEqual(result["draft"]["worker_packet"]["commands"][0]["argv"], ["bash", "-c", "exit 0"])

    def test_human_answers_bind_primary_evidence_but_do_not_grant_approval(self):
        gate = {"id": "appearance", "kind": "taste", "owner": "operator", "question": "Which appearance is intended?",
            "stage": "before", "action": "local_execute", "artifact_sha256": "d" * 64, "candidate_sha": None,
            "issue_id": ID, "issue_revision": 7}
        self.definition["human_gates"] = [gate]
        self.definition["human_answers"] = [{"gate_id": "appearance", "response": "Use the compact layout."}]
        result = self.build()
        answers = [source for source in result["intake"]["evidence"] if source["id"] == "human-answer:appearance"]
        self.assertEqual(len(answers), 1)
        self.assertEqual(json.loads(answers[0]["content"]), self.definition["human_answers"][0])
        self.assertEqual(result["intake"]["human_gates"], [gate])
        self.assertFalse(result["decision"]["dispatchable"])
        self.assertFalse(result["execution_authorized"])

    def test_stale_gate_revision_must_be_rebound_by_human(self):
        self.definition["human_gates"] = [{"id": "approve", "kind": "approval", "owner": "operator", "question": "Approve this exact artifact?",
            "stage": "before", "action": "local_execute", "artifact_sha256": "d" * 64, "candidate_sha": None,
            "issue_id": ID, "issue_revision": 6}]
        result = self.build()
        self.assertIn("human_gates", result["missing_fields"])
        self.assertEqual(self.definition["human_gates"][0]["issue_revision"], 6)

    def test_ten_minute_human_wait_refreshes_execution_proof_but_keeps_exact_answer_subject(self):
        gate = {"id": "business-input", "kind": "input", "owner": "operator", "question": "Choose the intended behavior.",
            "stage": "before", "action": "human_input", "artifact_sha256": "d" * 64, "candidate_sha": None,
            "issue_id": ID, "issue_revision": 7}
        self.definition["step"].update(kind="human", action="human_input")
        self.definition["human_gates"] = [gate]
        first = self.build()
        self.snapshot = snapshot_fixture(self.definition, now=NOW + 600)
        with mock.patch.object(intake, "azure_cli_headers", side_effect=AssertionError("no auth")), mock.patch.object(subprocess, "run", side_effect=AssertionError("no model")):
            second = self.build(now=NOW + 600, previous=first)
        self.assertFalse(second["reused"])
        self.assertNotEqual(first["intake_sha256"], second["intake_sha256"])
        self.assertEqual(first["material_fingerprint"], second["material_fingerprint"])
        receipt = {"gate_id": gate["id"], "decision": "accepted", "response": "Use the concise variant.", "grant": {}}
        def subject(report):
            packet = report["intake"]["worker_packet"]
            return gate_bindings(gate, receipt, {"issue_id": ID, "issue_revision": 7,
                "worker_packet_sha256": canonical_digest(packet), "candidate_sha": None, "action": "human_input",
                "policy_sha256": canonical_digest(self.policy)})
        self.assertEqual(subject(first), subject(second))
        self.assertFalse(second["completion"])

    def test_missing_observation_and_missing_command_cli_returns_truthful_zero_completion_draft(self):
        self.snapshot.pop("observed_at")
        self.definition["worker_packet"]["commands"] = []
        result = self.build()
        self.assertEqual(result["state"], "draft")
        self.assertIn("snapshot.observed_at", result["missing_fields"])
        self.assertIn("worker_packet.commands", result["missing_fields"])
        self.assertIsNone(result["current_observation"]["observed_at"])
        self.assertFalse(result["completion"])

    def test_source_timestamps_inside_real_file_text_remain_material(self):
        first = self.build()
        (self.workspace / "src/product.py").write_text('VALUE = {"observed_at": "new product data"}\n')
        second = self.build(previous=first)
        self.assertNotEqual(first["material_fingerprint"], second["material_fingerprint"])

    def test_pilot_can_select_one_real_issue_only_after_complete_provider_graph_read(self):
        from test_azure_devops import Response
        second = "azdo:Instablinds:Instablinds:18"
        manifest = self.definition["worker_packet"]["expected_manifest"]
        manifest["dependencies"][second] = []
        self.definition["worker_packet"]["inspection_authority"]["execution_authorized"] = False
        reads = []
        class FakeHTTP:
            def open(self, request, **kwargs):
                body = json.loads(request.data)
                reads.append(body["ids"])
                return Response({"count": len(body["ids"]), "value": [{"id": number, "rev": 7,
                    "fields": {"System.State": "To Do", "System.TeamProject": "Instablinds"}, "relations": []} for number in body["ids"]]})
        client = az.AzureDevOpsClient("Instablinds", "Instablinds", self.runtime, opener=FakeHTTP(), clock=lambda: NOW, interval=0)
        self.snapshot = az.AzureBoardsProvider(client).inspect([ID], expected_manifest=manifest, authority=self.definition["worker_packet"]["inspection_authority"], fresh=True)
        report = self.build()
        self.assertTrue(all(set(batch) == {17, 18} for batch in reads))
        self.assertGreaterEqual(len(reads), 2)
        self.assertEqual(report["issue_id"], ID)
        self.assertEqual(len(report["snapshot"]["items"]), 2)
        self.assertEqual(report["state"], "blocked")

    def test_cli_preview_without_B_writes_no_bytecode_state_or_auth(self):
        source_dir = self.home / "source"
        source_dir.mkdir()
        for name in ("atlas-agent-azure-intake", "atlas_intake.py", "atlas_dispatch.py", "atlas_routing.py", "atlas_human_gates.py", "atlas_authority.py", "atlas_runtime_config.py", "atlas_azure_worker.py", "atlas_azure_devops.py"):
            (source_dir / name).write_bytes((ROOT / name).read_bytes())
        inputs = {"definition": self.definition, "snapshot": self.snapshot, "policy": self.policy,
            "config": {"schema_version": 1, "provider": "azure-devops", "repository": self.config.repository,
                "capabilities": ["read"], "models": {role: {"model": "gpt-6-astra", "reasoning": "max"} for role in config.ROLES},
                "sandbox": "workspace-write", "approval_policy": "on-request"}}
        for key, value in inputs.items():
            (self.home / (key + ".json")).write_text(json.dumps(value))
        before = self.files()
        launcher = "import pwd,sys,types,runpy; root=sys.argv.pop(1); pwd.getpwuid=lambda uid:types.SimpleNamespace(pw_dir=root,pw_name='fixture'); runpy.run_path(sys.argv.pop(1),run_name='__main__')"
        argv = [sys.executable, "-c", launcher, str(self.home), str(source_dir / "atlas-agent-azure-intake"),
                "--runtime-dir", str(self.runtime), "--context-root", str(self.workspace)]
        for key in inputs:
            argv += ["--" + key, str(self.home / (key + ".json"))]
        environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "PYTHONPATH"}}
        result = subprocess.run(argv, env=environment, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["effects"], [])
        self.assertEqual(self.files(), before)


if __name__ == "__main__":
    unittest.main()
