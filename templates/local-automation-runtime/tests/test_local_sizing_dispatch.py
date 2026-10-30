from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import atlas_work_items
import atlas_workflows
import atlas_local_sizing


class LocalSizingDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = self.root / "queue.json"
        self.jobs = self.root / "jobs"
        self.commands = self.root / "commands.json"
        self.item = {
            "id": "LOCAL-SIZED", "status": "ready", "title": "Bounded local change",
            "goal": "Preserve local task state and independent acceptance without remote requests.",
            "acceptance_criteria": ["A completed role retains concrete validation evidence."],
            "scheduler": {"execution_repo": str(self.root), "workflow_kind": "work-item",
                          "team_template": "work-item-change-lifecycle",
                          "write_scope": ["src/change.py", "tests/test_change.py"]},
            "metadata": {"local_execution_v1": {
                "policy_id": "local-luna-unit-v1", "role_purposes": {
                    "implementation": "implementation", "test-runner": "validation",
                    "code-review": "review", "semantic-alignment": "goal-review", "evidence-rollup": "review"},
                "changed_interfaces": [], "unresolved_questions": [], "complexity_flags": []}},
        }
        self.commands.write_text(json.dumps({"default": ["./atlas-agent-role-codex"]}))

    def tearDown(self):
        self.temp.cleanup()

    def run_once(self):
        self.store.write_text(json.dumps({"version": 1, "work_items": [self.item]}))
        env = os.environ.copy()
        env["AGENT_JOBS"] = str(self.jobs)
        proc = subprocess.run([sys.executable, str(ROOT / "atlas-agent-orchestrator"), "--once", "--max-items", "1",
                               "--atlas-work-items", str(self.store), "--atlas-role-command-config", str(self.commands),
                               "--atlas-role-max", "1"], env=env, text=True, capture_output=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(self.store.read_text())["work_items"][0]

    def test_qualified_packet_reaches_fixed_luna_preview_without_model_startup(self):
        item = self.run_once()
        self.assertEqual(item["status"], "blocked")  # prepare-only cannot count as implementation
        sizing = item["result"]["evidence"]["local_sizing"]
        self.assertEqual(sizing["status"], "qualified")
        self.assertEqual(sizing["assignments"]["implementation"]["model"], "gpt-6-luna")
        self.assertEqual(sizing["assignments"]["semantic-alignment"]["model"], "gpt-6.1-sol")
        reports = list(self.jobs.glob("**/*.invocation.json"))
        self.assertEqual(len(reports), 1)
        report = reports[0].read_text()
        self.assertIn("gpt-6-luna", report)
        self.assertIn("medium", report)
        self.assertIn("--model", report)
        self.assertNotEqual(item["result"]["evidence"]["goal_acceptance"]["verdict"], "pass")

    def test_oversized_or_uncertain_packet_never_claims_or_starts_a_job(self):
        for mutation, expected in [
            (lambda item: item["scheduler"].update(write_scope=[f"src/file{i}.py" for i in range(5)]), "split_required"),
            (lambda item: item["metadata"]["local_execution_v1"].update(unresolved_questions=["Which interface owns the change?"]), "decomposition_required"),
        ]:
            with self.subTest(expected=expected):
                original = json.loads(json.dumps(self.item))
                mutation(self.item)
                item = self.run_once()
                provider = atlas_work_items.AtlasWorkItemOperationProvider(atlas_work_items.AtlasWorkItemStore(self.store))
                operation = provider.operation_states()[0]
                self.assertFalse(operation.ready)
                self.assertIn(expected, " ".join(operation.blockers))
                self.assertNotIn("claim", item)
                self.assertFalse(self.jobs.exists())
                self.item = original

    def test_contract_rejects_custom_command_map_before_it_can_run(self):
        marker = self.root / "unexpected-execution"
        self.commands.write_text(json.dumps({"default": [sys.executable, "-c", f"open({str(marker)!r},'w').write('bad')"]}))
        item = self.run_once()
        self.assertEqual(item["status"], "blocked")
        self.assertFalse(marker.exists())
        result_files = list(self.jobs.glob("**/team-role-results.json"))
        self.assertTrue(result_files)
        self.assertIn("contract", result_files[0].read_text().lower())

    def test_raw_worker_command_cannot_bypass_contract(self):
        self.store.write_text(json.dumps({"version": 1, "work_items": [self.item]}))
        provider = atlas_work_items.AtlasWorkItemOperationProvider(atlas_work_items.AtlasWorkItemStore(self.store))
        marker = self.root / "raw-bypass"
        worker = atlas_work_items.LocalCommandOperationWorker(
            [sys.executable, "-c", f"open({str(marker)!r},'w').write('bad')"], jobs_dir=self.jobs)
        self.assertEqual(atlas_work_items.run_worker_daemon_once(provider, worker), 1)
        self.assertFalse(marker.exists())
        self.assertEqual(json.loads(self.store.read_text())["work_items"][0]["status"], "blocked")

    def test_unknown_provider_payload_is_blocked_without_copying_values_to_context(self):
        self.item["metadata"]["local_execution_v1"]["provider"] = "placeholder-do-not-copy"
        self.run_once()
        provider = atlas_work_items.AtlasWorkItemOperationProvider(atlas_work_items.AtlasWorkItemStore(self.store))
        operation = provider.operation_states()[0]
        self.assertFalse(operation.ready)
        self.assertNotIn("placeholder-do-not-copy", json.dumps(operation.work_item_context))
        self.assertFalse(self.jobs.exists())

    def test_canonical_runner_cannot_replace_generated_packets_with_legacy_tasks(self):
        marker = self.root / "substituted-packet-execution"
        legacy = self.root / "legacy-tasks.json"
        legacy.write_text(json.dumps({"tasks": [{"role_id": "legacy", "status": "pending",
            "must_produce": ["result"], "missing_outputs": ["result"]}]}))
        self.commands.write_text(json.dumps({"default": [sys.executable, "-c", f"open({str(marker)!r},'w').write('bad')"]}))
        raw = shlex.join([str(ROOT / "atlas-agent-role-runner"), "--command-config", str(self.commands),
            "--max-roles", "1", "--tasks", str(legacy), "--results", str(self.root / "legacy-results.json")])
        self.store.write_text(json.dumps({"version": 1, "work_items": [self.item]}))
        env = os.environ.copy()
        env["AGENT_JOBS"] = str(self.jobs)
        proc = subprocess.run([sys.executable, str(ROOT / "atlas-agent-orchestrator"), "--once", "--max-items", "1",
            "--atlas-work-items", str(self.store), "--atlas-work-item-command", raw],
            env=env, text=True, capture_output=True, timeout=15)
        self.assertEqual(proc.returncode, 0)
        item = json.loads(self.store.read_text())["work_items"][0]
        self.assertEqual(item["status"], "blocked")
        self.assertIn("canonical runner arguments", item["result"]["summary"])
        self.assertFalse(marker.exists())
        self.assertFalse(self.jobs.exists())

    def test_dotted_existing_directory_does_not_count_as_one_file(self):
        (self.root / "src.v1").mkdir()
        self.item["scheduler"]["write_scope"] = ["src.v1"]
        self.run_once()
        operation = atlas_work_items.AtlasWorkItemOperationProvider(atlas_work_items.AtlasWorkItemStore(self.store)).operation_states()[0]
        self.assertFalse(operation.ready)
        self.assertIn("directory", " ".join(operation.blockers))
        self.assertFalse(self.jobs.exists())

    def test_partial_run_binds_sizing_inputs_before_resuming(self):
        self.store.write_text(json.dumps({"version": 1, "work_items": [self.item]}))
        provider = atlas_work_items.AtlasWorkItemOperationProvider(atlas_work_items.AtlasWorkItemStore(self.store))
        operation = provider.ready_operations()[0]
        worker = atlas_work_items.LocalCommandOperationWorker(None, jobs_dir=self.jobs,
            templates_dir=ROOT / "team-templates")
        first = self.root / "first"
        first.mkdir()
        evidence = worker.write_workflow_artifacts(operation, first, "first", self.store)
        result_file = first / "roles.json"
        result_file.write_text(json.dumps([{"role_id": "implementation", "status": "complete",
            "outputs": {"change_summary": "change", "changed_files": "src/change.py", "implementation_notes": "bounded"}}]))
        refreshed = worker.apply_workflow_role_results(evidence, result_file)
        provider.record_result(operation, atlas_work_items.OperationResult("ready", 3, "bounded pause", refreshed))
        unchanged = self.root / "unchanged"
        unchanged.mkdir()
        same = worker.write_workflow_artifacts(provider.ready_operations()[0], unchanged, "same", self.store)
        self.assertTrue(same["workflow_resumed"])
        run = atlas_workflows.load_team_run(same["team_run_path"])
        self.assertEqual(run.role_results["implementation"].status, "complete")
        changed = json.loads(self.store.read_text())
        changed["work_items"][0]["metadata"]["local_execution_v1"]["changed_interfaces"] = ["one-interface"]
        self.store.write_text(json.dumps(changed))
        last = self.root / "changed"
        last.mkdir()
        blocked = worker.write_workflow_artifacts(provider.ready_operations()[0], last, "changed", self.store)
        self.assertIn("contract changed", blocked["workflow_error"])
        self.assertFalse((last / "team-role-tasks.json").exists())

    def set_v2(self, implementation="gpt-6-luna", review="gpt-6.1-sol"):
        contract = self.item["metadata"]["local_execution_v1"]
        contract.update(policy_id="local-reviewed-unit-v2", implementation_model=implementation,
                        review_model=review, sizing_review={"reviewer": "operator review record",
                        "rationale": "This bounded change fits the chosen route.", "subject_sha256": "pending"})
        projected = atlas_work_items.work_item_context(self.item)
        contract["sizing_review"]["subject_sha256"] = atlas_local_sizing.sizing_subject_sha256(projected)

    def test_v2_projected_provider_and_role_packets_bind_models(self):
        for implementation, effort in (("gpt-6-luna", "medium"), ("gpt-6.1-sol", "high"),
                                       ("gpt-6.1-terra", "high")):
            for review in ("gpt-6.1-sol", "gpt-6.1-terra"):
                with self.subTest(implementation=implementation, review=review):
                    self.set_v2(implementation, review)
                    self.store.write_text(json.dumps({"version": 1, "work_items": [self.item]}))
                    provider = atlas_work_items.AtlasWorkItemOperationProvider(atlas_work_items.AtlasWorkItemStore(self.store))
                    operation = provider.ready_operations()[0]
                    self.assertEqual(operation.work_item_context, atlas_work_items.work_item_context(self.item))
                    job = self.root / (implementation + review)
                    job.mkdir(exist_ok=True)
                    worker = atlas_work_items.LocalCommandOperationWorker(None, jobs_dir=self.jobs,
                        templates_dir=ROOT / "team-templates")
                    evidence = worker.write_workflow_artifacts(operation, job, "preview", self.store)
                    self.assertEqual(evidence["local_sizing"]["status"], "qualified", evidence)
                    packets = json.loads((job / "team-role-tasks.json").read_text())["tasks"]
                    for packet in packets:
                        self.assertEqual(packet["work_item_context"], operation.work_item_context)
                        route = atlas_local_sizing.assignment_for_task(packet)
                        self.assertEqual(route, evidence["local_sizing"]["assignments"][packet["role_id"]])
                        if route["purpose"] in {"implementation", "validation"}:
                            self.assertEqual((route["model"], route["reasoning"]), (implementation, effort))
                        else:
                            self.assertEqual((route["model"], route["reasoning"]), (review, "high"))

    def test_v2_projection_refuses_stale_and_unknown_fields(self):
        for mutate in (
            lambda item: item["scheduler"].update(write_scope=["src/other.py"]),
            lambda item: item.update(spec_hash="changed-spec-hash"),
            lambda item: item["metadata"]["local_execution_v1"].update(implementation_model="gpt-6.1-terra"),
            lambda item: item["metadata"]["local_execution_v1"].update(provider="private-value"),
            lambda item: item["metadata"]["local_execution_v1"]["sizing_review"].update(provider="private-value"),
            lambda item: item["metadata"]["local_execution_v1"].update(review_model={"provider": "private-value"}),
            lambda item: item["metadata"]["local_execution_v1"].update(sizing_review=None),
        ):
            original = json.loads(json.dumps(self.item))
            self.set_v2()
            mutate(self.item)
            self.store.write_text(json.dumps({"version": 1, "work_items": [self.item]}))
            operation = atlas_work_items.AtlasWorkItemOperationProvider(atlas_work_items.AtlasWorkItemStore(self.store)).operation_states()[0]
            self.assertFalse(operation.ready)
            self.assertNotIn("private-value", json.dumps(operation.work_item_context))
            self.item = original


if __name__ == "__main__":
    unittest.main()
