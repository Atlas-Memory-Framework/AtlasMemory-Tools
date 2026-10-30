from __future__ import annotations

import copy
import contextlib
import hashlib
import json
import sys
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock


RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import atlas_supervised_handoff as handoff
import atlas_delta_review
import atlas_workflows
import atlas_work_items


class SupervisedHandoffPureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        raw = json.loads((RUNTIME / "team-templates" / "work-item-change-lifecycle.json").read_text())
        cls.template = atlas_workflows.TeamTemplate.from_dict(raw)
        cls.context = {
            "title": "Bounded adapter test",
            "goal": "Expose exact role handoff data without mutation.",
            "write_scope": ["src/adapter.py", "tests/test_adapter.py"],
            "acceptance_criteria": [
                "Select a dependency-satisfied role deterministically.",
                "Bind its packet and claim to the observed revision.",
                "Reject conflicting imports without changing the inputs.",
            ],
            "local_execution_v1": {
                "policy_id": "local-luna-unit-v1",
                "role_purposes": {
                    "implementation": "implementation",
                    "test-runner": "validation",
                    "code-review": "review",
                    "semantic-alignment": "goal-review",
                    "evidence-rollup": "review",
                },
                "changed_interfaces": ["supervised local handoff v1"],
                "unresolved_questions": [],
                "complexity_flags": [],
            },
        }

    def make_claim_item(self) -> tuple[dict, dict]:
        claim = {"claimed_by": "supervisor:test", "claimed_at": "2026-10-15T12:00:00Z", "pid": 123}
        item = {
            "id": "WI-HANDOFF", "status": "running", "operation_id": "op-WI-HANDOFF",
            "claim": claim, "lifecycle": {"rework_count": 0}, "working_tree_dirty": True,
        }
        return item, claim

    def make_run(self, results: dict | None = None, *, status: str = "running") -> atlas_workflows.TeamRun:
        return atlas_workflows.TeamRun(
            id="run-1", template_id=self.template.id, work_item_id="WI-HANDOFF",
            status=status, created_at="2026-10-15T12:00:00Z",
            role_results={
                role_id: atlas_workflows.TeamRunRoleResult.from_dict(result)
                for role_id, result in (results or {}).items()
            },
        )

    def prepared(self, run: atlas_workflows.TeamRun | None = None) -> dict:
        item, claim = self.make_claim_item()
        return handoff.prepare_role_handoff(
            item=item, claim=claim, supervisor_id="supervisor:test", context=self.context,
            template=self.template, run=run or self.make_run(), checkout="/repo/atlas",
            revision="a" * 40, generation=1, handoff_id="00000000-0000-4000-8000-000000000001",
            prior_run_snapshot_hash="b" * 64,
        )

    def result_bytes(self, role_id: str, status: str = "complete") -> bytes:
        outputs = {name: f"{name} content" for name in next(role for role in self.template.roles if role.id == role_id).must_produce}
        if role_id == "semantic-alignment":
            goal = {"verdict": "pass", "reason": "All criteria met.", "evidence": ["Observed criteria."]}
        else:
            goal = None
        record = {"role_id": role_id, "status": status, "outputs": outputs,
                  "evidence": ["result artifact"], "notes": "role completed",
                  "contract_issues": [], "goal_review": goal}
        return json.dumps({"role_results": [record]}, sort_keys=True).encode()

    def envelope(self, prepared: dict, result_bytes: bytes) -> dict:
        binding = prepared["binding"]
        assignment = binding["role_assignment"]
        return {
            "binding": copy.deepcopy(binding),
            "host_receipt": {
                "invocation_id": "task:actual-123",
                "transport": "supervised_in_app",
                "checkout": binding["checkout"],
                "revision": binding["revision"],
                "model": assignment["model"],
                "reasoning": assignment["reasoning"],
            },
            "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
        }

    def test_prepare_selects_first_role_and_binds_claim_context_contract_and_packet(self) -> None:
        item, claim = self.make_claim_item()
        item_before, claim_before, context_before = copy.deepcopy(item), copy.deepcopy(claim), copy.deepcopy(self.context)
        result = handoff.prepare_role_handoff(
            item=item, claim=claim, supervisor_id="supervisor:test", context=self.context,
            template=self.template, run=self.make_run(), checkout="/repo/atlas", revision="a" * 40,
            generation=1, handoff_id="00000000-0000-4000-8000-000000000001", prior_run_snapshot_hash="b" * 64,
        )
        binding, packet = result["binding"], result["packet"]
        self.assertEqual(packet["role_id"], "implementation")
        self.assertEqual(binding["claim_fingerprint"], handoff.sha256_json(claim))
        self.assertEqual(binding["context_hash"], handoff.sha256_json(self.context))
        self.assertEqual(binding["contract_hash"], self.prepared()["binding"]["contract_hash"])
        self.assertEqual(binding["packet_hash"], handoff.sha256_json(packet))
        self.assertEqual(binding["run_id"], "run-1")
        self.assertEqual(binding["role_id"], "implementation")
        self.assertEqual(binding["generation"], 1)
        self.assertEqual(binding["revision"], "a" * 40)
        self.assertEqual(binding["role_assignment"]["model"], "gpt-6-luna")
        self.assertEqual((item, claim, self.context), (item_before, claim_before, context_before))

    def test_parallel_review_phase_selects_one_in_template_order(self) -> None:
        results = {
            "implementation": {"role_id": "implementation", "status": "complete", "outputs": {
                "change_summary": "done", "changed_files": "src/a.py", "implementation_notes": "done"}},
            "test-runner": {"role_id": "test-runner", "status": "complete", "outputs": {
                "commands_run": "python -m unittest", "test_results": "pass", "coverage_or_gap_notes": "covered"}},
        }
        prepared = self.prepared(self.make_run(results))
        self.assertEqual(prepared["packet"]["role_id"], "code-review")
        self.assertNotEqual(prepared["packet"]["role_id"], "semantic-alignment")

    def test_failed_goal_gate_or_blocked_run_cannot_unlock_rollup(self) -> None:
        results = {
            "implementation": {"role_id": "implementation", "status": "complete", "outputs": {
                "change_summary": "done", "changed_files": "src/a.py", "implementation_notes": "done"}},
            "test-runner": {"role_id": "test-runner", "status": "complete", "outputs": {
                "commands_run": "python -m unittest", "test_results": "pass", "coverage_or_gap_notes": "covered"}},
            "code-review": {"role_id": "code-review", "status": "complete", "outputs": {
                "findings": "none", "risk_level": "low", "required_fixes": "none"}},
            "semantic-alignment": {"role_id": "semantic-alignment", "status": "blocked", "outputs": {},
                "goal_review": {"verdict": "fail", "reason": "Not aligned.", "evidence": ["criterion missed"]}},
        }
        with self.assertRaises(handoff.HandoffRefusal):
            self.prepared(self.make_run(results, status="blocked"))
        results["semantic-alignment"]["status"] = "complete"
        with self.assertRaises(handoff.HandoffRefusal):
            self.prepared(self.make_run(results))
        results["semantic-alignment"]["goal_review"] = None
        with self.assertRaises(handoff.HandoffRefusal):
            self.prepared(self.make_run(results))

    def test_prior_attempts_are_renormalized_and_malformed_non_goal_results_refuse(self) -> None:
        base = {
            "implementation": {"role_id": "implementation", "status": "complete", "outputs": {
                "change_summary": "done", "changed_files": "src/adapter.py", "implementation_notes": "done"}},
            "test-runner": {"role_id": "test-runner", "status": "complete", "outputs": {
                "commands_run": "python -m unittest", "test_results": "pass", "coverage_or_gap_notes": "covered"}},
        }
        valid_review = {"role_id": "code-review", "status": "complete", "outputs": {
            "findings": "none", "risk_level": "low", "required_fixes": "none"}}
        malformed = [
            {"role_id": "code-review", "status": "complete", "outputs": {}},
            {**valid_review, "outputs": {**valid_review["outputs"], "unexpected": "value"}},
            {**valid_review, "status": "unknown-status"},
        ]
        for bad in malformed:
            with self.subTest(bad=bad):
                run = self.make_run({**base, "code-review": bad})
                before = copy.deepcopy(run.to_dict())
                normalized = copy.deepcopy(run)
                atlas_workflows.apply_role_results(template=self.template, run=normalized, results=[])
                self.assertEqual(normalized.status, "blocked")
                item, claim = self.make_claim_item()
                with self.assertRaises(handoff.HandoffRefusal):
                    handoff.prepare_role_handoff(item=item, claim=claim, supervisor_id="supervisor:test",
                        context=self.context, template=self.template, run=run, checkout="/repo/atlas",
                        revision="a" * 40, generation=1, handoff_id="00000000-0000-4000-8000-000000000003",
                        prior_run_snapshot_hash="b" * 64)
                self.assertEqual(run.to_dict(), before)

    def test_prior_attempt_key_must_match_inner_role_id_without_mutation(self) -> None:
        malformed = {"role_id": "code-review", "status": "complete", "outputs": {
            "change_summary": "done", "changed_files": "src/adapter.py", "implementation_notes": "done"}}
        run = self.make_run({"implementation": malformed})
        before = copy.deepcopy(run.to_dict())
        item, claim = self.make_claim_item()
        with self.assertRaises(handoff.HandoffRefusal):
            handoff.prepare_role_handoff(item=item, claim=claim, supervisor_id="supervisor:test",
                context=self.context, template=self.template, run=run, checkout="/repo/atlas",
                revision="a" * 40, generation=1, handoff_id="00000000-0000-4000-8000-000000000004",
                prior_run_snapshot_hash="b" * 64)
        self.assertEqual(run.to_dict(), before)
    def test_import_accepts_one_bound_terminal_role_and_identical_replay_is_duplicate(self) -> None:
        prepared = self.prepared()
        raw = self.result_bytes("implementation")
        envelope = self.envelope(prepared, raw)
        before = copy.deepcopy((envelope, prepared["binding"], prepared["packet"]))
        accepted = handoff.classify_role_result_import(
            envelope=envelope, result_bytes=raw, expected_binding=prepared["binding"],
            expected_packet=prepared["packet"],
        )
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual((envelope, prepared["binding"], prepared["packet"]), before)
        duplicate = handoff.classify_role_result_import(
            envelope=envelope, result_bytes=raw, expected_binding=prepared["binding"],
            expected_packet=prepared["packet"], accepted_receipts={
                "00000000-0000-4000-8000-000000000001": {"binding": envelope["binding"], "host_receipt": envelope["host_receipt"],
                              "result_sha256": envelope["result_sha256"], "acknowledgement": {"status": "accepted"}},
            },
        )
        self.assertEqual(duplicate, {"status": "duplicate", "handoff_id": "00000000-0000-4000-8000-000000000001", "receipt": {"status": "accepted"}})

    def test_import_refuses_malformed_multi_role_pending_and_wrong_role(self) -> None:
        prepared = self.prepared()
        raw = self.result_bytes("implementation")
        envelope = self.envelope(prepared, raw)
        for malformed in (b"{", b'{"role_results": []}', json.dumps({"role_results": [json.loads(raw)["role_results"][0]] * 2}).encode()):
            with self.subTest(raw=malformed), self.assertRaises(handoff.HandoffRefusal):
                handoff.classify_role_result_import(envelope=envelope, result_bytes=malformed,
                    expected_binding=prepared["binding"], expected_packet=prepared["packet"])
        pending = json.dumps({"role_results": [{"role_id": "implementation", "status": "pending"}]}).encode()
        with self.assertRaises(handoff.HandoffRefusal):
            handoff.classify_role_result_import(envelope=self.envelope(prepared, pending), result_bytes=pending,
                expected_binding=prepared["binding"], expected_packet=prepared["packet"])
        wrong = json.dumps({"role_results": [{"role_id": "test-runner", "status": "complete", "outputs": {}}]}).encode()
        with self.assertRaises(handoff.HandoffRefusal):
            handoff.classify_role_result_import(envelope=self.envelope(prepared, wrong), result_bytes=wrong,
                expected_binding=prepared["binding"], expected_packet=prepared["packet"])

    def test_import_refuses_wrong_owner_claim_revision_context_run_and_receipt(self) -> None:
        prepared = self.prepared()
        raw = self.result_bytes("implementation")
        original = self.envelope(prepared, raw)
        for field, value in (("supervisor_id", "other"), ("revision", "c" * 40),
                             ("context_hash", "d" * 64), ("run_id", "another-run"),
                             ("claim_fingerprint", "e" * 64), ("generation", 2),
                             ("role_id", "test-runner")):
            changed = copy.deepcopy(original)
            body = changed["binding"]
            body[field] = value
            body["binding_hash"] = handoff.sha256_json({key: val for key, val in body.items() if key != "binding_hash"})
            with self.subTest(field=field), self.assertRaises(handoff.HandoffRefusal):
                handoff.classify_role_result_import(envelope=changed, result_bytes=raw,
                    expected_binding=prepared["binding"], expected_packet=prepared["packet"])
        changed = copy.deepcopy(original)
        changed["host_receipt"]["invocation_id"] = ""
        with self.assertRaises(handoff.HandoffRefusal):
            handoff.classify_role_result_import(envelope=changed, result_bytes=raw,
                expected_binding=prepared["binding"], expected_packet=prepared["packet"])
        changed = copy.deepcopy(original)
        changed["host_receipt"]["artifact_path"] = "/caller/controlled/path"
        with self.assertRaises(handoff.HandoffRefusal):
            handoff.classify_role_result_import(envelope=changed, result_bytes=raw,
                expected_binding=prepared["binding"], expected_packet=prepared["packet"])

    def test_prepare_refuses_foreign_claim_malformed_revision_and_unqualified_scope(self) -> None:
        item, claim = self.make_claim_item()
        changed = copy.deepcopy(claim)
        changed["claimed_by"] = "another-supervisor"
        item["claim"] = changed
        with self.assertRaises(handoff.HandoffRefusal):
            handoff.prepare_role_handoff(item=item, claim=changed, supervisor_id="supervisor:test",
                context=self.context, template=self.template, run=self.make_run(), checkout="/repo/atlas",
                revision="a" * 40, generation=1, handoff_id="00000000-0000-4000-8000-000000000002", prior_run_snapshot_hash="b" * 64)
        item, claim = self.make_claim_item()
        with self.assertRaises(handoff.HandoffRefusal):
            handoff.prepare_role_handoff(item=item, claim=claim, supervisor_id="supervisor:test",
                context=self.context, template=self.template, run=self.make_run(), checkout="/repo/atlas",
                revision="abc", generation=1, handoff_id="00000000-0000-4000-8000-000000000002", prior_run_snapshot_hash="b" * 64)
        bad_context = copy.deepcopy(self.context)
        bad_context["local_execution_v1"]["complexity_flags"] = ["security_or_authority"]
        with self.assertRaises(handoff.HandoffRefusal):
            handoff.prepare_role_handoff(item=item, claim=claim, supervisor_id="supervisor:test",
                context=bad_context, template=self.template, run=self.make_run(), checkout="/repo/atlas",
                revision="a" * 40, generation=1, handoff_id="00000000-0000-4000-8000-000000000002", prior_run_snapshot_hash="b" * 64)


class SupervisedHandoffPersistenceTests(SupervisedHandoffPureContractTests):
    def make_persistent_fixture(self, root: Path, *, source_id: str = "WI-PERSIST"):
        checkout = root / "checkout"
        checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "base"], check=True)
        revision = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                                  check=True, capture_output=True, text=True).stdout.strip()
        store_path = root / "queue.json"
        claim = {"claimed_by": "supervisor:test", "claimed_at": "2026-10-15T12:00:00Z", "pid": 123}
        item = {
            "id": source_id, "title": self.context["title"], "description": self.context["goal"],
            "status": "running", "state": "running", "claim": claim,
            "scheduler": {"execution_repo": str(checkout), "workflow_kind": "work-item",
                "team_template": "work-item-change-lifecycle", "write_scope": ["src/adapter.py", "tests/test_adapter.py"]},
            "metadata": {"acceptance_criteria": self.context["acceptance_criteria"],
                "local_execution_v1": self.context["local_execution_v1"]},
            "lifecycle": {"state": "running", "rework_count": 0},
        }
        store_path.write_text(json.dumps({"version": 1, "work_items": [item]}))
        provider = atlas_work_items.AtlasWorkItemOperationProvider(
            atlas_work_items.AtlasWorkItemStore(store_path), claimed_by="supervisor:test")
        worker = atlas_work_items.LocalCommandOperationWorker(None,
            jobs_dir=root / "jobs", templates_dir=RUNTIME / "team-templates")
        return store_path, provider, worker, revision

    def _first_role_result(self, prepared: dict, status: str = "complete", marker: str = "verified") -> bytes:
        role_id = prepared["binding"]["role_id"]
        role = next(role for role in self.template.roles if role.id == role_id)
        record = {"role_id": role_id, "status": status,
            "outputs": {key: f"{marker} {key}" for key in role.must_produce},
            "evidence": ["fixture evidence"], "notes": marker, "contract_issues": [],
            "goal_review": None}
        return json.dumps({"role_results": [record]}, sort_keys=True).encode()

    def _envelope_for(self, prepared: dict, raw: bytes, invocation: str = "task:fixture") -> dict:
        binding = prepared["binding"]
        assignment = binding["role_assignment"]
        return {"binding": binding, "host_receipt": {"invocation_id": invocation,
            "transport": "supervised_in_app", "checkout": binding["checkout"],
            "revision": binding["revision"], "model": assignment["model"],
            "reasoning": assignment["reasoning"]}, "result_sha256": hashlib.sha256(raw).hexdigest()}

    def test_pilot_completion_cannot_skip_trusted_evidence_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_path, provider, worker, revision = self.make_persistent_fixture(root)
            payload = json.loads(store_path.read_text())
            payload["work_items"][0]["metadata"]["atlas_delta_review_pilot_v1"] = {
                "enabled": True,
                "repository_root": str(root / "checkout"),
                "required_checks": [{"id": "unit", "lane": "test", "argv": [sys.executable, "-c", "pass"], "timeout_seconds": 30}],
                "evidence": {},
            }
            store_path.write_text(json.dumps(payload))
            prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            raw = self._first_role_result(prepared)
            envelope = self._envelope_for(prepared, raw)
            before = store_path.read_bytes()
            with mock.patch.object(worker, "apply_workflow_role_results", return_value={
                    "team_run_status": "complete", "goal_acceptance": {"verdict": "pass"}}):
                with self.assertRaises(handoff.HandoffRefusal) as refusal:
                    handoff.ingest_handoff(provider, worker, envelope=envelope, result_bytes=raw)
            self.assertEqual(refusal.exception.code, "pilot_acceptance")
            self.assertIn("pilot evidence references are incomplete", str(refusal.exception))
            self.assertEqual(store_path.read_bytes(), before)

    def test_complete_pilot_evidence_allows_supervised_import_to_reach_done(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_path, provider, worker, base_revision = self.make_persistent_fixture(root)
            checkout = root / "checkout"
            (checkout / "src").mkdir()
            (checkout / "src" / "pilot-fixture.txt").write_text("candidate\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(checkout), "add", "src/pilot-fixture.txt"], check=True)
            subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Fixture", "-c",
                            "user.email=fixture@example.invalid", "commit", "-qm", "candidate"], check=True)
            candidate_revision = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                                                check=True, capture_output=True, text=True).stdout.strip()
            snapshot = atlas_delta_review.freeze_delta(checkout, base_revision, candidate_revision)
            binding = {key: snapshot[key] for key in (
                "base_revision", "candidate_revision", "changed_paths", "diff_sha256"
            )}
            plan = atlas_delta_review.validate_check_plan([
                {"id": "code-check", "lane": "code", "argv": [sys.executable, "-c", "pass"]},
                {"id": "environment-check", "lane": "environment", "argv": [sys.executable, "-c", "pass"],
                 "capability": "fixture environment"},
                {"id": "test-check", "lane": "test", "argv": [sys.executable, "-c", "pass"]},
            ])
            start = datetime.fromisoformat(snapshot["created_at"])
            checks = {"snapshot": binding, "passed": True, "execution_source": "local_operator_pilot", "results": []}
            for index, check in enumerate(plan):
                began = start + timedelta(seconds=2 * index + 1)
                ended = began + timedelta(seconds=1)
                checks["results"].append({
                    **check,
                    "capability": check.get("capability"),
                    "started_at": began.isoformat(),
                    "ended_at": ended.isoformat(),
                    "returncode": 0,
                    "timed_out": False,
                    "status": "passed",
                    "output": "fixture passed",
                })
            review = {
                "snapshot": binding,
                "reviewer": "offline positive-pilot fixture",
                "reviewed_at": (start + timedelta(seconds=10)).isoformat(),
                "findings": [],
                "disposition": "clear",
            }
            evidence_root = root / "pilot-evidence"
            evidence_root.mkdir()
            evidence = {}
            for name, document in (("snapshot", snapshot), ("review", review), ("checks", checks)):
                path = evidence_root / f"{name}.json"
                raw = json.dumps(document, sort_keys=True).encode("utf-8")
                path.write_bytes(raw)
                evidence[name] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
            payload = json.loads(store_path.read_text(encoding="utf-8"))
            payload["work_items"][0]["metadata"]["atlas_delta_review_pilot_v1"] = {
                "enabled": True,
                "repository_root": str(checkout),
                "required_checks": plan,
                "evidence": evidence,
            }
            store_path.write_text(json.dumps(payload), encoding="utf-8")

            prepared = handoff.prepare_handoff(
                provider, worker, source_id="WI-PERSIST", expected_revision=candidate_revision
            )
            for expected_role in ("implementation", "test-runner", "code-review", "semantic-alignment", "evidence-rollup"):
                self.assertEqual(prepared["binding"]["role_id"], expected_role)
                role = next(role for role in self.template.roles if role.id == expected_role)
                record = {"role_id": expected_role, "status": "complete",
                    "outputs": {key: f"valid {key}" for key in role.must_produce},
                    "evidence": ["fixture evidence"], "notes": "verified", "contract_issues": [],
                    "goal_review": ({"verdict": "pass", "reason": "Criteria met.",
                        "evidence": ["Observed each criterion."]} if role.goal_gate else None)}
                raw = json.dumps({"role_results": [record]}, sort_keys=True).encode("utf-8")
                receipt = handoff.ingest_handoff(
                    provider, worker, envelope=self._envelope_for(prepared, raw, f"task:{expected_role}"),
                    result_bytes=raw,
                )
                self.assertEqual(receipt["status"], "accepted")
                if expected_role != "evidence-rollup":
                    operation = provider.ready_operations()[0]
                    self.assertIsNotNone(provider.claim(operation))
                    prepared = handoff.prepare_handoff(
                        provider, worker, source_id="WI-PERSIST", expected_revision=candidate_revision
                    )

            final_item = atlas_work_items.AtlasWorkItemStore(store_path).load()["work_items"][0]
            self.assertEqual(final_item["state"], "done")
            self.assertEqual(receipt["item_status"], "done")

    def _install_other_pending(self, store_path: Path, source_id: str) -> bytes:
        payload = json.loads(store_path.read_text())
        other = copy.deepcopy(next(item for item in payload["work_items"] if item["id"] == source_id))
        other["id"] = "WI-OTHER-PENDING"
        other["supervised_handoff_v1"]["pending"]["binding"]["work_item_id"] = other["id"]
        payload["work_items"].append(other)
        store_path.write_text(json.dumps(payload))
        return store_path.read_bytes()

    def test_atlas_wrapper_survives_persistent_prepare_and_capture_preserves_original_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_path, provider, worker, revision = self.make_persistent_fixture(root)
            wrapper = {"schema": "atlas.daily_supervised_handoff.correlation.v1",
                "binding_sha256": "a" * 64,
                "work_packet": {"work_packet_id": "wp-fixture", "nested": [1, {"x": True}]}}
            payload = json.loads(store_path.read_text())
            payload["work_items"][0]["metadata"].update({"atlas_daily_task": wrapper,
                "unrelated_secret": "excluded"})
            store_path.write_text(json.dumps(payload))
            source_before = copy.deepcopy(wrapper)
            prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            persisted = json.loads(Path(prepared["artifacts"]["team_role_tasks_path"]).read_text())
            packet = next(task for task in persisted["tasks"] if task["role_id"] == prepared["binding"]["role_id"])
            self.assertEqual(packet["work_item_context"]["atlas_daily_task"], wrapper)
            self.assertNotIn("unrelated_secret", packet["work_item_context"])
            packet["work_item_context"]["atlas_daily_task"]["work_packet"]["nested"][1]["x"] = False
            self.assertEqual(wrapper, source_before)
            prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            raw = b'{ "candidate": {"text":"original\\u00e9"}, "n": 1 }\n'
            binding = prepared["binding"]
            assignment = binding["role_assignment"]
            receipt = {"invocation_id": "task:observed", "transport": "supervised_in_app",
                "checkout": binding["checkout"], "revision": binding["revision"],
                "model": assignment["model"], "reasoning": assignment["reasoning"]}
            before = store_path.read_bytes()
            with mock.patch.object(provider.store, "save", side_effect=AssertionError("save called")), \
                    mock.patch.object(worker, "apply_workflow_role_results", side_effect=AssertionError("apply called")):
                captured = handoff.capture_host_return(provider, worker, expected_reservation=prepared,
                    host_receipt=receipt, dispatched_packet_sha256=binding["packet_hash"], result_bytes=raw)
            self.assertEqual(captured["result_bytes"], raw)
            self.assertEqual(captured["host_observation"]["result_bytes"], raw)
            self.assertEqual(captured["envelope"]["result_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(store_path.read_bytes(), before)
            replay = handoff.capture_host_return(provider, worker, expected_reservation=prepared,
                host_receipt=receipt, dispatched_packet_sha256=binding["packet_hash"], result_bytes=raw,
                prior_capture=captured)
            self.assertEqual(replay, captured)
            with self.assertRaises(handoff.HandoffRefusal) as conflict:
                handoff.capture_host_return(provider, worker, expected_reservation=prepared,
                    host_receipt=receipt, dispatched_packet_sha256=binding["packet_hash"], result_bytes=raw + b" ",
                    prior_capture=captured)
            self.assertEqual(conflict.exception.code, "replay_conflict")
            with self.assertRaises(handoff.HandoffRefusal):
                handoff.ingest_handoff(provider, worker, envelope=captured["envelope"], result_bytes=raw)
            self.assertEqual(store_path.read_bytes(), before)

    def test_capture_replay_rejects_malformed_prior_types_and_digests(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_path, provider, worker, revision = self.make_persistent_fixture(root)
            prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            binding = prepared["binding"]
            assignment = binding["role_assignment"]
            receipt = {"invocation_id": "task:observed", "transport": "supervised_in_app",
                "checkout": binding["checkout"], "revision": binding["revision"],
                "model": assignment["model"], "reasoning": assignment["reasoning"]}
            raw = b'{ "candidate": true }\n'
            kwargs = {"expected_reservation": prepared, "host_receipt": receipt,
                "dispatched_packet_sha256": binding["packet_hash"], "result_bytes": raw}
            captured = handoff.capture_host_return(provider, worker, **kwargs)
            before = store_path.read_bytes()
            bad_prior = []
            for location in ("expected_reservation", "envelope"):
                changed = copy.deepcopy(captured)
                changed[location]["binding"]["generation"] = True
                bad_prior.append(changed)
            changed = copy.deepcopy(captured)
            changed["expected_reservation"]["packet"]["role_id"] = "wrong"
            bad_prior.append(changed)
            changed = copy.deepcopy(captured)
            changed["host_observation"]["result_bytes"] = bytearray(raw)
            bad_prior.append(changed)
            for prior in bad_prior:
                with self.subTest(prior=prior), self.assertRaises(handoff.HandoffRefusal) as refusal:
                    handoff.capture_host_return(provider, worker, prior_capture=prior, **kwargs)
                self.assertEqual(refusal.exception.code, "prior_capture")
            self.assertEqual(store_path.read_bytes(), before)

    def test_capture_exact_replay_accepts_supported_deep_wrapper(self) -> None:
        for child_depth in (28, 29, 30):
            with self.subTest(child_depth=child_depth), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                store_path, provider, worker, revision = self.make_persistent_fixture(root)
                nested: Any = "leaf"
                for _ in range(child_depth):
                    nested = [nested]
                wrapper = {"schema": "atlas.daily_supervised_handoff.correlation.v1",
                    "binding_sha256": "a" * 64,
                    "work_packet": {"work_packet_id": "wp-deep", "nested": nested}}
                payload = json.loads(store_path.read_text())
                payload["work_items"][0]["metadata"]["atlas_daily_task"] = wrapper
                store_path.write_text(json.dumps(payload))
                prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
                binding = prepared["binding"]
                assignment = binding["role_assignment"]
                receipt = {"invocation_id": "task:deep", "transport": "supervised_in_app",
                    "checkout": binding["checkout"], "revision": binding["revision"],
                    "model": assignment["model"], "reasoning": assignment["reasoning"]}
                raw = b'{ "candidate": "deep" }\n'
                args = {"expected_reservation": prepared, "host_receipt": receipt,
                    "dispatched_packet_sha256": binding["packet_hash"], "result_bytes": raw}
                captured = handoff.capture_host_return(provider, worker, **args)
                replay = handoff.capture_host_return(provider, worker, prior_capture=captured, **args)
                self.assertEqual(replay, captured)
                self.assertIsNot(replay, captured)

    def test_atlas_daily_task_malformed_present_wrapper_refuses_instead_of_falling_back(self) -> None:
        invalid = [
            {"schema": "foreign", "binding_sha256": "a" * 64, "work_packet": {"work_packet_id": "x"}},
            {"schema": "atlas.daily_supervised_handoff.correlation.v1", "binding_sha256": "A" * 64,
             "work_packet": {"work_packet_id": "x"}},
            {"schema": "atlas.daily_supervised_handoff.correlation.v1", "binding_sha256": "a" * 64,
             "work_packet": {}},
            {"schema": "atlas.daily_supervised_handoff.correlation.v1", "binding_sha256": "a" * 64,
             "work_packet": {"work_packet_id": "x"}, "extra": True},
        ]
        for wrapper in invalid:
            with self.subTest(wrapper=wrapper), self.assertRaisesRegex(ValueError, "invalid atlas_daily_task wrapper"):
                atlas_work_items.work_item_context({"id": "x", "metadata": {"atlas_daily_task": wrapper}})
        cyc = {"schema": "atlas.daily_supervised_handoff.correlation.v1", "binding_sha256": "a" * 64,
               "work_packet": {"work_packet_id": "x"}}
        cyc["work_packet"]["cycle"] = cyc["work_packet"]
        with self.assertRaisesRegex(ValueError, "invalid atlas_daily_task wrapper"):
            atlas_work_items.work_item_context({"id": "x", "metadata": {"atlas_daily_task": cyc}})
        huge = {"schema": "atlas.daily_supervised_handoff.correlation.v1", "binding_sha256": "a" * 64,
            "work_packet": {"work_packet_id": "x", "large": 2 ** 1000000}}
        with self.assertRaisesRegex(ValueError, "^invalid atlas_daily_task wrapper$"):
            atlas_work_items.work_item_context({"id": "x", "metadata": {"atlas_daily_task": huge}})

    def test_global_pending_blocks_resume_and_unaccepted_import(self) -> None:
        for action in ("prepare", "import"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                store_path, provider, worker, revision = self.make_persistent_fixture(root)
                prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
                raw = self._first_role_result(prepared)
                envelope = self._envelope_for(prepared, raw)
                self._install_other_pending(store_path, "WI-PERSIST")
                before = store_path.read_bytes()
                with self.assertRaises(handoff.HandoffRefusal):
                    if action == "prepare":
                        handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
                    else:
                        handoff.ingest_handoff(provider, worker, envelope=envelope, result_bytes=raw)
                self.assertEqual(store_path.read_bytes(), before)

    def test_other_pending_added_during_staging_blocks_import_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_path, provider, worker, revision = self.make_persistent_fixture(root)
            prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            raw = self._first_role_result(prepared)
            envelope = self._envelope_for(prepared, raw)
            original = worker.apply_workflow_role_results
            baseline = []
            def interleave(evidence, result_path):
                updated = original(evidence, result_path)
                baseline.append(self._install_other_pending(store_path, "WI-PERSIST"))
                return updated
            with mock.patch.object(worker, "apply_workflow_role_results", side_effect=interleave):
                with self.assertRaises(handoff.HandoffRefusal):
                    handoff.ingest_handoff(provider, worker, envelope=envelope, result_bytes=raw)
            self.assertEqual(store_path.read_bytes(), baseline[0])

    def test_staged_artifact_and_original_result_bytes_are_rechecked_before_save(self) -> None:
        for drift in ("team-run.json", "original-role-results.json"):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                store_path, provider, worker, revision = self.make_persistent_fixture(root)
                prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
                raw = self._first_role_result(prepared)
                envelope = self._envelope_for(prepared, raw)
                before = store_path.read_bytes()
                original_lock = provider.store.lock
                @contextlib.contextmanager
                def mutate_staged_then_lock():
                    staged = next((root / "jobs").glob(f"supervised-import-*/{drift}"))
                    staged.write_bytes(staged.read_bytes() + b"\n")
                    with original_lock():
                        yield
                with mock.patch.object(provider.store, "lock", side_effect=mutate_staged_then_lock):
                    with self.assertRaises(handoff.HandoffRefusal):
                        handoff.ingest_handoff(provider, worker, envelope=envelope, result_bytes=raw)
                self.assertEqual(store_path.read_bytes(), before)

    def test_template_and_reserved_artifact_drift_refuse_without_queue_publication(self) -> None:
        for drift in ("template", "artifact-during-staging"):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                store_path, provider, worker, revision = self.make_persistent_fixture(root)
                prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
                raw = self._first_role_result(prepared)
                envelope = self._envelope_for(prepared, raw)
                if drift == "template":
                    templates = root / "templates"
                    import shutil
                    shutil.copytree(RUNTIME / "team-templates", templates)
                    worker.templates_dir = templates
                    template_path = templates / "work-item-change-lifecycle.json"
                    template_data = json.loads(template_path.read_text())
                    template_data["roles"][0]["must_produce"].append("drifted_output")
                    template_path.write_text(json.dumps(template_data))
                before = store_path.read_bytes()
                if drift == "template":
                    with self.assertRaises(handoff.HandoffRefusal):
                        handoff.ingest_handoff(provider, worker, envelope=envelope, result_bytes=raw)
                else:
                    original = worker.apply_workflow_role_results
                    def mutate_reserved(evidence, result_path):
                        reserved = Path(prepared["artifacts"]["team_run_path"])
                        reserved.write_bytes(reserved.read_bytes() + b"\n")
                        return original(evidence, result_path)
                    with mock.patch.object(worker, "apply_workflow_role_results", side_effect=mutate_reserved):
                        with self.assertRaises(handoff.HandoffRefusal):
                            handoff.ingest_handoff(provider, worker, envelope=envelope, result_bytes=raw)
                self.assertEqual(store_path.read_bytes(), before)

    def test_publication_save_failure_leaves_pending_reservation_and_old_run_intact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_path, provider, worker, revision = self.make_persistent_fixture(root)
            prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            raw = self._first_role_result(prepared)
            envelope = self._envelope_for(prepared, raw)
            before_queue = store_path.read_bytes()
            run_path = Path(prepared["artifacts"]["team_run_path"])
            before_run = run_path.read_bytes()
            with mock.patch.object(provider.store, "save", side_effect=OSError("simulated publication interruption")):
                with self.assertRaises(OSError):
                    handoff.ingest_handoff(provider, worker, envelope=envelope, result_bytes=raw)
            self.assertEqual(store_path.read_bytes(), before_queue)
            self.assertEqual(run_path.read_bytes(), before_run)
            live = atlas_work_items.AtlasWorkItemStore(store_path).load()["work_items"][0]
            self.assertEqual(live["supervised_handoff_v1"]["pending"]["binding"], prepared["binding"])

    def test_interleaved_conflicting_import_is_refused_after_winner_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_path, provider, worker, revision = self.make_persistent_fixture(root)
            prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            first = self._first_role_result(prepared, marker="winning result")
            second = self._first_role_result(prepared, marker="conflicting result")
            first_envelope = self._envelope_for(prepared, first, "task:winner")
            second_envelope = self._envelope_for(prepared, second, "task:conflict")
            original = worker.apply_workflow_role_results
            winner = []
            def interleave(evidence, result_path):
                if not winner:
                    winner.append(None)
                    winner[0] = handoff.ingest_handoff(provider, worker, envelope=first_envelope, result_bytes=first)
                return original(evidence, result_path)
            with mock.patch.object(worker, "apply_workflow_role_results", side_effect=interleave):
                with self.assertRaises(handoff.HandoffRefusal):
                    handoff.ingest_handoff(provider, worker, envelope=second_envelope, result_bytes=second)
            self.assertEqual(winner[0]["status"], "accepted")
            item = atlas_work_items.AtlasWorkItemStore(store_path).load()["work_items"][0]
            self.assertEqual(item["supervised_handoff_v1"]["accepted"][prepared["binding"]["handoff_id"]]["result_sha256"],
                hashlib.sha256(first).hexdigest())

    def test_maintained_goal_pass_completes_and_goal_failure_stays_blocked(self) -> None:
        for verdict, expected in (("pass", "done"), ("fail", "blocked")):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                store_path, provider, worker, revision = self.make_persistent_fixture(root)
                prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
                old_generations = []
                for expected_role in ("implementation", "test-runner", "code-review", "semantic-alignment", "evidence-rollup"):
                    self.assertEqual(prepared["binding"]["role_id"], expected_role)
                    prior_bytes = {path: Path(path).read_bytes() for path in prepared["artifacts"].values()}
                    old_generations.append(prior_bytes)
                    role = next(role for role in self.template.roles if role.id == expected_role)
                    record = {"role_id": expected_role, "status": "complete",
                        "outputs": {key: f"valid {key}" for key in role.must_produce},
                        "evidence": ["fixture evidence"], "notes": "verified", "contract_issues": [],
                        "goal_review": ({"verdict": verdict, "reason": "Reviewed frozen criteria.",
                            "evidence": ["Observed each criterion."]} if role.goal_gate else None)}
                    raw = json.dumps({"role_results": [record]}, sort_keys=True).encode()
                    envelope = self._envelope_for(prepared, raw, f"task:{expected_role}")
                    receipt = handoff.ingest_handoff(provider, worker, envelope=envelope, result_bytes=raw)
                    self.assertEqual(receipt["status"], "accepted")
                    for snapshot in old_generations:
                        for path, contents in snapshot.items():
                            self.assertEqual(Path(path).read_bytes(), contents)
                    current = atlas_work_items.AtlasWorkItemStore(store_path).load()["work_items"][0]
                    if current["state"] in {"done", "blocked"}:
                        break
                    operation = provider.ready_operations()[0]
                    self.assertIsNotNone(provider.claim(operation))
                    prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
                final_item = atlas_work_items.AtlasWorkItemStore(store_path).load()["work_items"][0]
                self.assertEqual(final_item["state"], expected)
                self.assertEqual(atlas_work_items.accepted_dependency(final_item), verdict == "pass")

    def test_prepare_resume_import_and_duplicate_are_fenced_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkout = root / "checkout"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Fixture", "-c",
                            "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "base"], check=True)
            revision = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                                      check=True, capture_output=True, text=True).stdout.strip()
            store_path = root / "queue.json"
            claim = {"claimed_by": "supervisor:test", "claimed_at": "2026-10-15T12:00:00Z", "pid": 123}
            item = {
                "id": "WI-PERSIST", "title": self.context["title"], "description": self.context["goal"],
                "status": "running", "state": "running", "claim": claim,
                "scheduler": {"execution_repo": str(checkout), "workflow_kind": "work-item",
                    "team_template": "work-item-change-lifecycle", "write_scope": ["src/adapter.py", "tests/test_adapter.py"]},
                "metadata": {"acceptance_criteria": self.context["acceptance_criteria"],
                    "local_execution_v1": self.context["local_execution_v1"]},
                "lifecycle": {"state": "running", "rework_count": 0},
            }
            store_path.write_text(json.dumps({"version": 1, "work_items": [item]}))
            provider = atlas_work_items.AtlasWorkItemOperationProvider(
                atlas_work_items.AtlasWorkItemStore(store_path), claimed_by="supervisor:test")
            worker = atlas_work_items.LocalCommandOperationWorker(None,
                jobs_dir=root / "jobs", templates_dir=RUNTIME / "team-templates")
            first = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            reserved_bytes = store_path.read_bytes()
            live_payload = json.loads(reserved_bytes)
            live_payload["work_items"][0]["claim"]["claimed_by"] = "foreign-supervisor"
            store_path.write_text(json.dumps(live_payload))
            with self.assertRaises(handoff.HandoffRefusal):
                handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            store_path.write_bytes(reserved_bytes)
            with self.assertRaises(handoff.HandoffRefusal):
                handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision="f" * 40)
            reserved_run = Path(first["artifacts"]["team_run_path"])
            saved_run_bytes = reserved_run.read_bytes()
            reserved_run.write_bytes(saved_run_bytes + b" ")
            with self.assertRaises(handoff.HandoffRefusal):
                handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            reserved_run.write_bytes(saved_run_bytes)
            second = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            self.assertEqual(first, second)
            self.assertEqual(store_path.read_bytes(), reserved_bytes)
            role = first["binding"]["role_id"]
            raw = json.dumps({"role_results": [{"role_id": role, "status": "complete",
                "outputs": {key: f"verified {key}" for key in next(r for r in self.template.roles if r.id == role).must_produce},
                "evidence": ["fixture evidence"], "notes": "completed", "contract_issues": [],
                "goal_review": None}]}, sort_keys=True).encode()
            binding = first["binding"]
            assignment = binding["role_assignment"]
            envelope = {"binding": binding, "host_receipt": {"invocation_id": "task:fixture",
                "transport": "supervised_in_app", "checkout": binding["checkout"],
                "revision": binding["revision"], "model": assignment["model"],
                "reasoning": assignment["reasoning"]}, "result_sha256": hashlib.sha256(raw).hexdigest()}
            accepted = handoff.ingest_handoff(provider, worker, envelope=envelope, result_bytes=raw)
            committed_bytes = store_path.read_bytes()
            self.assertEqual(accepted["status"], "accepted")
            foreign_provider = atlas_work_items.AtlasWorkItemOperationProvider(
                atlas_work_items.AtlasWorkItemStore(store_path), claimed_by="different-supervisor")
            with self.assertRaises(handoff.HandoffRefusal):
                handoff.ingest_handoff(foreign_provider, worker, envelope=envelope, result_bytes=raw)
            changed_raw = raw + b" "
            changed_envelope = copy.deepcopy(envelope)
            changed_envelope["result_sha256"] = hashlib.sha256(changed_raw).hexdigest()
            with self.assertRaises(handoff.HandoffRefusal):
                handoff.ingest_handoff(provider, worker, envelope=changed_envelope, result_bytes=changed_raw)
            self.assertEqual(store_path.read_bytes(), committed_bytes)
            self.assertEqual(handoff.ingest_handoff(provider, worker, envelope=envelope, result_bytes=raw)["status"], "duplicate")
            self.assertEqual(store_path.read_bytes(), committed_bytes)
            committed = atlas_work_items.AtlasWorkItemStore(store_path).load()["work_items"][0]
            self.assertEqual(committed["state"], "ready")
            self.assertNotIn("pending", committed["supervised_handoff_v1"])
            self.assertIn(binding["handoff_id"], committed["supervised_handoff_v1"]["accepted"])
            next_operation = provider.ready_operations()[0]
            self.assertIsNotNone(provider.claim(next_operation))
            next_handoff = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            self.assertEqual(next_handoff["binding"]["role_id"], "test-runner")
            saved_run = json.loads(Path(next_handoff["artifacts"]["team_run_path"]).read_text())
            self.assertEqual(saved_run["role_results"]["implementation"]["status"], "complete")

    def test_missing_execution_checkout_refuses_without_queue_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_path = root / "queue.json"
            claim = {"claimed_by": "supervisor:test", "claimed_at": "2026-10-15T12:00:00Z", "pid": 123}
            item = {"id": "WI-NO-CHECKOUT", "title": self.context["title"], "status": "running",
                "claim": claim, "scheduler": {"execution_repo": "", "workflow_kind": "work-item",
                    "team_template": "work-item-change-lifecycle"},
                "metadata": {"acceptance_criteria": self.context["acceptance_criteria"],
                    "local_execution_v1": self.context["local_execution_v1"]},
                "lifecycle": {"state": "running", "rework_count": 0}}
            store_path.write_text(json.dumps({"version": 1, "work_items": [item]}))
            provider = atlas_work_items.AtlasWorkItemOperationProvider(
                atlas_work_items.AtlasWorkItemStore(store_path), claimed_by="supervisor:test")
            worker = atlas_work_items.LocalCommandOperationWorker(None, jobs_dir=root / "jobs",
                templates_dir=RUNTIME / "team-templates")
            before = store_path.read_bytes()
            with self.assertRaises(handoff.HandoffRefusal):
                handoff.prepare_handoff(provider, worker, source_id="WI-NO-CHECKOUT", expected_revision="a" * 40)
            self.assertEqual(store_path.read_bytes(), before)

    def test_persistence_selects_eligible_phase_not_raw_template_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_path, provider, worker, revision = self.make_persistent_fixture(root)
            templates = root / "templates"
            import shutil
            shutil.copytree(RUNTIME / "team-templates", templates)
            worker.templates_dir = templates
            template_path = templates / "work-item-change-lifecycle.json"
            template_data = json.loads(template_path.read_text())
            template_data["roles"][0], template_data["roles"][1] = template_data["roles"][1], template_data["roles"][0]
            parsed = atlas_workflows.TeamTemplate.from_dict(template_data)
            self.assertEqual(parsed.validate(), [])
            self.assertEqual(parsed.role_phases()[0], ["implementation"])
            template_path.write_text(json.dumps(template_data))
            prepared = handoff.prepare_handoff(provider, worker, source_id="WI-PERSIST", expected_revision=revision)
            self.assertEqual(prepared["binding"]["role_id"], "implementation")


if __name__ == "__main__":
    unittest.main()
