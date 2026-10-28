from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ORCHESTRATOR = ROOT / "atlas-agent-orchestrator"
TEMPLATES = ROOT / "team-templates"
WORK_ITEM_TEMPLATE = TEMPLATES / "work-item-change-lifecycle.json"


PRODUCER = r'''import json, os
from pathlib import Path

task = json.loads(Path(os.environ["ATLAS_ROLE_TASK_FILE"]).read_text())
role = task["role_id"]
with open(os.environ["ATLAS_DISPATCH_LOG"], "a", encoding="utf-8") as log:
    log.write(role + "\n")
with open(os.environ["ATLAS_CONTEXT_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"role": role, "work_item_context": task.get("work_item_context", {})}) + "\n")
outputs = {name: role + ":" + name for name in task.get("must_produce", [])}
result = {"role_id": role, "status": "complete", "outputs": outputs, "evidence": ["fake-producer:" + role]}
if role == "implementation" and os.environ.get("GOAL_MODE") == "no-progress":
    result["status"] = "pending"
    result["outputs"] = {}
if task.get("goal_gate") is True:
    mode = os.environ.get("GOAL_MODE", "pass")
    consumed = task.get("consumed_role_results") or {}
    evidence = [
        dependency + "." + name + "=" + str(value)
        for dependency, dependency_result in consumed.items()
        for name, value in (dependency_result.get("outputs") or {}).items()
    ] or ["local goal and acceptance criteria reviewed"]
    if mode == "missing":
        pass
    elif mode == "wrong-type":
        result["goal_review"] = {"verdict": 3, "reason": ["not a string"], "evidence": [7]}
    else:
        verdict = mode if mode in {"pass", "fail", "inconclusive"} else "pass"
        result["goal_review"] = {
            "verdict": verdict,
            "reason": "Controlled local review: " + verdict,
            "evidence": evidence,
        }
Path(os.environ["ATLAS_ROLE_RESULT_FILE"]).write_text(json.dumps(result), encoding="utf-8")
'''


def load_work_items_module():
    name = "local_goal_acceptance_work_items"
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / "atlas_work_items.py"))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


class LocalGoalAcceptanceE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("python3"):
            raise unittest.SkipTest("python3 is required for subprocess integration tests")
        cls.work_items = load_work_items_module()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store_path = self.root / "work-items.json"
        self.jobs_dir = self.root / "jobs"
        self.execution_repo = self.root / "execution-repo"
        self.execution_repo.mkdir()
        self.template_dir = self.root / "team-templates"
        self.template_dir.mkdir()
        shutil.copyfile(WORK_ITEM_TEMPLATE, self.template_dir / WORK_ITEM_TEMPLATE.name)
        self.dispatch_log = self.root / "dispatches.txt"
        self.context_log = self.root / "role-context.jsonl"
        self.producer_path = self.root / "fake_result_producer.py"
        self.producer_path.write_text(PRODUCER, encoding="utf-8")
        self.command_config = self.root / "role-commands.json"
        self.command_config.write_text(
            json.dumps({"default": [sys.executable, str(self.producer_path)]}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def new_item(self, item_id: str = "WI-GOAL-1") -> dict:
        return {
            "id": item_id,
            "status": "ready",
            "title": "Implement a local acceptance audit",
            "goal": "Add deterministic acceptance evidence to the local workflow without contacting services.",
            "acceptance_criteria": [
                "The workflow records implementation and test context.",
                "An independent goal review decides pass, fail, or inconclusive with evidence.",
            ],
            "scheduler": {
                "workflow_kind": "work-item",
                "team_template": "work-item-change-lifecycle",
                "execution_repo": str(self.execution_repo),
                "write_scope": ["src/local_acceptance"],
                "required_outputs": [
                    "change_summary", "test_results", "plan_alignment", "final_evidence_document"
                ],
            },
            "evidence": [],
        }

    def write_store(self, items: list[dict]) -> None:
        self.store_path.write_text(
            json.dumps({"version": 1, "work_items": items}, indent=2) + "\n",
            encoding="utf-8",
        )

    def items(self) -> list[dict]:
        return json.loads(self.store_path.read_text(encoding="utf-8"))["work_items"]

    def invoke(self, *, mode: str = "pass", max_roles: int = 100) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "AGENT_JOBS": str(self.jobs_dir),
                "ATLAS_DISPATCH_LOG": str(self.dispatch_log),
                "ATLAS_CONTEXT_LOG": str(self.context_log),
                "GOAL_MODE": mode,
            }
        )
        return subprocess.run(
            [
                sys.executable,
                str(ORCHESTRATOR),
                "--once",
                "--atlas-work-items",
                str(self.store_path),
                "--atlas-role-command-config",
                str(self.command_config),
                "--atlas-role-max",
                str(max_roles),
                "--team-templates",
                str(self.template_dir),
                "--max-items",
                "1",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def dispatches(self) -> list[str]:
        if not self.dispatch_log.exists():
            return []
        return self.dispatch_log.read_text(encoding="utf-8").splitlines()

    def role_contexts(self) -> list[dict]:
        if not self.context_log.exists():
            return []
        return [json.loads(line) for line in self.context_log.read_text(encoding="utf-8").splitlines()]

    def run_file(self, item: dict) -> dict:
        evidence = item["result"]["evidence"]
        return json.loads(Path(evidence["team_run_path"]).read_text(encoding="utf-8"))

    def test_pass_finishes_workflow_and_releases_dependent_operation(self) -> None:
        first = self.new_item()
        dependent = {
            "id": "WI-GOAL-2",
            "status": "ready",
            "title": "Follow-up after accepted work",
            "scheduler": {"depends_on": [first["id"]], "execution_repo": str(self.execution_repo)},
        }
        self.write_store([first, dependent])

        completed = self.invoke(mode="pass")

        self.assertEqual(completed.returncode, 0, completed.stdout)
        saved, follow_up = self.items()
        self.assertEqual(saved["status"], "done")
        self.assertEqual(saved["result"]["evidence"]["goal_acceptance"]["verdict"], "pass")
        self.assertEqual(follow_up["status"], "ready")
        provider = self.work_items.AtlasWorkItemOperationProvider(
            self.work_items.AtlasWorkItemStore(self.store_path)
        )
        ready_ids = [operation.source_id for operation in provider.ready_operations()]
        self.assertIn("WI-GOAL-2", ready_ids)
        self.assertNotIn("WI-GOAL-1", ready_ids)
        self.assertEqual(self.dispatches()[-1], "evidence-rollup")

        saved["scheduler"]["required_outputs"] = ["a-different-request"]
        payload = {"version": 1, "work_items": [saved, follow_up]}
        self.store_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        changed_provider = self.work_items.AtlasWorkItemOperationProvider(
            self.work_items.AtlasWorkItemStore(self.store_path)
        )
        changed_ready_ids = [operation.source_id for operation in changed_provider.ready_operations()]
        self.assertNotIn("WI-GOAL-2", changed_ready_ids)
        dependency_state = next(
            operation for operation in changed_provider.operation_states() if operation.source_id == "WI-GOAL-2"
        )
        self.assertTrue(any("open dependency: WI-GOAL-1" in blocker for blocker in dependency_state.blockers))

    def test_negative_and_malformed_gate_results_block_and_cannot_reach_rollup(self) -> None:
        for index, mode in enumerate(("fail", "inconclusive", "missing", "wrong-type")):
            with self.subTest(mode=mode):
                if index:
                    self.tearDown()
                    self.setUp()
                first = self.new_item()
                dependent = {
                    "id": "WI-GOAL-2",
                    "status": "ready",
                    "title": "Follow-up after accepted work",
                    "scheduler": {"depends_on": [first["id"]], "execution_repo": str(self.execution_repo)},
                }
                self.write_store([first, dependent])

                completed = self.invoke(mode=mode)

                self.assertEqual(completed.returncode, 0, completed.stdout)
                saved, follow_up = self.items()
                self.assertEqual(saved["status"], "blocked")
                self.assertEqual(follow_up["status"], "ready")
                gate = self.run_file(saved)["role_results"]["semantic-alignment"]
                self.assertEqual(gate["outputs"]["plan_alignment"], "semantic-alignment:plan_alignment")
                if mode == "wrong-type":
                    self.assertEqual(gate["goal_review"], {"verdict": 3, "reason": ["not a string"], "evidence": [7]})
                elif mode == "missing":
                    self.assertIsNone(gate["goal_review"])
                else:
                    self.assertEqual(gate["goal_review"]["verdict"], mode)
                    self.assertTrue(gate["goal_review"]["evidence"])
                rollup = Path(saved["result"]["evidence"]["team_rollup_path"]).read_text(encoding="utf-8")
                if mode == "fail":
                    self.assertIn("- Goal gate verdict: `fail`", rollup)
                    self.assertIn("Controlled local review: fail", rollup)
                    self.assertIn("implementation.change_summary=implementation:change_summary", rollup)
                if mode == "wrong-type":
                    self.assertTrue(any(issue.startswith("goal review:") for issue in gate["contract_issues"]))
                self.assertNotIn("evidence-rollup", self.dispatches())
                provider = self.work_items.AtlasWorkItemOperationProvider(
                    self.work_items.AtlasWorkItemStore(self.store_path)
                )
                ready_ids = [operation.source_id for operation in provider.ready_operations()]
                self.assertNotIn("WI-GOAL-2", ready_ids)
                self.assertNotIn("WI-GOAL-1", ready_ids)
                self.temp.cleanup()

    def test_one_role_ticks_resume_with_implementation_and_test_context(self) -> None:
        self.write_store([self.new_item()])

        first = self.invoke(mode="pass", max_roles=1)
        self.assertEqual(first.returncode, 0, first.stdout)
        after_first = self.items()[0]
        first_run_id = after_first["workflow_runs"][0]["team_run"]["run_id"]
        self.assertEqual(after_first["status"], "ready")
        self.assertEqual(self.dispatches(), ["implementation"])

        resumed = self.invoke(mode="pass", max_roles=100)

        self.assertEqual(resumed.returncode, 0, resumed.stdout)
        done = self.items()[0]
        self.assertEqual(done["status"], "done")
        self.assertEqual(len(done["workflow_runs"]), 1)
        run = self.run_file(done)
        self.assertEqual(run["id"], first_run_id)
        self.assertEqual(run["role_results"]["implementation"]["outputs"]["change_summary"],
                         "implementation:change_summary")
        self.assertEqual(run["role_results"]["test-runner"]["outputs"]["test_results"],
                         "test-runner:test_results")
        gate_evidence = run["role_results"]["semantic-alignment"]["goal_review"]["evidence"]
        self.assertIn("implementation.change_summary=implementation:change_summary", gate_evidence)
        self.assertIn("test-runner.test_results=test-runner:test_results", gate_evidence)

    def test_negative_repeated_ticks_do_not_redispatch(self) -> None:
        self.write_store([self.new_item()])

        first = self.invoke(mode="fail")
        self.assertEqual(first.returncode, 0, first.stdout)
        first_dispatches = self.dispatches()
        self.assertEqual(self.items()[0]["status"], "blocked")

        second = self.invoke(mode="pass")

        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertEqual(self.dispatches(), first_dispatches)
        self.assertEqual(self.items()[0]["status"], "blocked")

    def test_no_progress_run_is_blocked_and_not_redispatched(self) -> None:
        self.write_store([self.new_item()])

        first = self.invoke(mode="no-progress", max_roles=1)
        self.assertEqual(first.returncode, 0, first.stdout)
        first_dispatches = self.dispatches()
        self.assertEqual(first_dispatches, ["implementation"])
        self.assertEqual(self.items()[0]["status"], "blocked")

        second = self.invoke(mode="pass")

        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertEqual(self.dispatches(), first_dispatches)
        self.assertEqual(self.items()[0]["status"], "blocked")

    def test_one_evidenced_rework_archives_prior_run_and_enforces_budget(self) -> None:
        self.write_store([self.new_item()])
        first = self.invoke(mode="fail")
        self.assertEqual(first.returncode, 0, first.stdout)
        original = self.items()[0]
        old_run_id = original["workflow_runs"][0]["team_run"]["run_id"]
        provider = self.work_items.AtlasWorkItemOperationProvider(
            self.work_items.AtlasWorkItemStore(self.store_path)
        )

        provider.requeue_for_rework(
            "WI-GOAL-1", reason="Acceptance changed after review", evidence=["updated-goal.md", "review-request.json"]
        )
        after_requeue = self.items()[0]
        self.assertEqual(after_requeue["status"], "ready")
        self.assertEqual(after_requeue["lifecycle"]["rework_count"], 1)
        self.assertEqual(after_requeue["previous_attempts"][0]["workflow_runs"][0]["team_run"]["run_id"], old_run_id)
        self.assertEqual(after_requeue["previous_attempts"][0]["evidence"], ["updated-goal.md", "review-request.json"])

        second = self.invoke(mode="fail")
        self.assertEqual(second.returncode, 0, second.stdout)
        retried = self.items()[0]
        self.assertEqual(retried["status"], "blocked")
        new_run_id = retried["workflow_runs"][0]["team_run"]["run_id"]
        self.assertNotEqual(new_run_id, old_run_id)
        role_contexts = [entry for entry in self.role_contexts() if entry["role"] == "implementation"]
        self.assertEqual(role_contexts[-1]["work_item_context"]["rework"]["reason"],
                         "Acceptance changed after review")
        self.assertEqual(role_contexts[-1]["work_item_context"]["rework"]["evidence"],
                         ["updated-goal.md", "review-request.json"])
        prior_review = role_contexts[-1]["work_item_context"]["rework"]["prior_goal_review"]
        self.assertEqual(prior_review["verdict"], "fail")
        self.assertEqual(prior_review["reason"], "Controlled local review: fail")
        self.assertTrue(prior_review["evidence"])
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            provider.requeue_for_rework(
                "WI-GOAL-1", reason="Try again", evidence=["retry-review.md"]
            )

    def test_changed_goal_after_partial_run_blocks_before_role_invocation(self) -> None:
        for index, change in enumerate(("goal", "template")):
            with self.subTest(change=change):
                if index:
                    self.tearDown()
                    self.setUp()
                self.write_store([self.new_item()])
                partial = self.invoke(mode="pass", max_roles=1)
                self.assertEqual(partial.returncode, 0, partial.stdout)
                before = self.dispatches()
                self.assertEqual(before, ["implementation"])

                if change == "goal":
                    payload = json.loads(self.store_path.read_text(encoding="utf-8"))
                    payload["work_items"][0]["goal"] = "A materially different goal with a changed acceptance boundary."
                    self.store_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                else:
                    template_path = self.template_dir / WORK_ITEM_TEMPLATE.name
                    template = json.loads(template_path.read_text(encoding="utf-8"))
                    gate = next(role for role in template["roles"] if role.get("goal_gate") is True)
                    gate["acceptance_criteria"].append("Also assess the changed local evidence contract.")
                    template_path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")

                changed = self.invoke(mode="pass")

                self.assertEqual(changed.returncode, 0, changed.stdout)
                item = self.items()[0]
                self.assertEqual(item["status"], "blocked")
                self.assertIn("contract changed", item["result"]["evidence"]["workflow_error"])
                self.assertEqual(self.dispatches(), before)


if __name__ == "__main__":
    unittest.main()
