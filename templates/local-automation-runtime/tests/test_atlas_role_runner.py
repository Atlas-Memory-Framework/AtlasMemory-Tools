from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shlex
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_script(name: str, filename: str):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


class AtlasRoleRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load_script("atlas_role_runner_test", "atlas-agent-role-runner")

    def write_tasks(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "role_id": "author",
                            "phase_index": 0,
                            "agent_ref": "agent-registry://author",
                            "skills": ["write"],
                            "consumes": [],
                            "must_produce": ["summary"],
                            "missing_outputs": ["summary"],
                            "status": "pending",
                        },
                        {
                            "role_id": "rollup",
                            "phase_index": 1,
                            "agent_ref": "agent-registry://rollup",
                            "skills": ["rollup"],
                            "consumes": ["author"],
                            "must_produce": ["decision"],
                            "missing_outputs": ["decision"],
                            "status": "pending",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

    def test_runnable_tasks_wait_for_consumed_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            self.write_tasks(path)
            tasks = self.runner.load_tasks(path)

        runnable = self.runner.runnable_tasks(tasks)

        self.assertEqual([task["role_id"] for task in runnable], ["author"])

    def test_command_config_resolves_role_agent_skill_and_default(self) -> None:
        task = {"role_id": "author", "agent_ref": "agent-registry://author", "skills": ["write"]}

        self.assertEqual(
            self.runner.command_from_config(task, {"roles": {"author": ["role-cmd"]}}),
            ["role-cmd"],
        )
        self.assertEqual(
            self.runner.command_from_config(task, {"agents": {"agent-registry://author": ["agent-cmd"]}}),
            ["agent-cmd"],
        )
        self.assertEqual(
            self.runner.command_from_config(task, {"agent_ids": {"author": ["agent-id-cmd"]}}),
            ["agent-id-cmd"],
        )
        self.assertEqual(
            self.runner.command_from_config(task, {"skills": {"write": ["skill-cmd"]}}),
            ["skill-cmd"],
        )
        self.assertEqual(self.runner.command_from_config(task, {"default": "default-cmd --flag"}), ["default-cmd", "--flag"])

    def test_command_config_resolves_agent_definition_profile(self) -> None:
        task = {
            "role_id": "security",
            "agent_ref": "agent-registry://security",
            "skills": ["critical-ideation"],
            "agent_definition": {
                "id": "security",
                "execution_profile": "review",
                "source": "agents/security.md",
            },
        }

        self.assertEqual(
            self.runner.command_from_config(task, {"profiles": {"review": ["profile-cmd"]}}),
            ["profile-cmd"],
        )

    def test_runtime_relative_command_resolves_from_runtime_dir(self) -> None:
        resolved = self.runner.resolve_command(["./atlas-agent-role-codex", "--flag"])

        self.assertEqual(resolved[0], str(ROOT / "atlas-agent-role-codex"))
        self.assertEqual(resolved[1], "--flag")

    def test_attach_consumed_role_results_hydrates_dependency_outputs(self) -> None:
        task = {"role_id": "rollup", "consumes": ["author"]}
        results = {
            "author": {
                "role_id": "author",
                "status": "complete",
                "outputs": {"summary": "done"},
            }
        }

        hydrated = self.runner.attach_consumed_role_results(task, results)

        self.assertEqual(hydrated["consumed_role_results"]["author"]["outputs"]["summary"], "done")

    def test_resumed_runner_keeps_prior_declared_dependency_and_overlays_current_result(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.json"
            results = root / "role-results.json"
            config = root / "commands.json"
            results_dir = root / "resumed-run"
            old_implementation = {
                "role_id": "implementation", "status": "complete",
                "outputs": {"changed_files": "src/feature.py", "design_decision": "keep API stable"},
            }
            current_author = {
                "role_id": "author", "status": "complete", "outputs": {"summary": "latest summary"},
            }
            tasks.write_text(json.dumps({"tasks": [
                {"role_id": "implementation", "status": "complete", "consumes": [], "missing_outputs": []},
                {"role_id": "author", "status": "pending", "consumes": [], "must_produce": ["summary"], "missing_outputs": ["summary"]},
                {
                    "role_id": "reviewer", "phase_index": 2, "status": "pending",
                    "consumes": ["implementation", "author"], "must_produce": ["decision"],
                    "missing_outputs": ["decision"], "dependency_blockers": [],
                    "consumed_role_results": {
                        "implementation": old_implementation,
                        "author": {"role_id": "author", "status": "complete", "outputs": {"summary": "stale summary"}},
                        "unrelated": {"role_id": "unrelated", "status": "complete", "outputs": {"note": "exclude"}},
                    },
                },
            ]}), encoding="utf-8")
            results.write_text(json.dumps([current_author, {
                "role_id": "unrelated", "status": "complete", "outputs": {"secret": "exclude"},
            }]), encoding="utf-8")
            config.write_text(json.dumps({"roles": {"reviewer": [
                "python3", "-c",
                "import json,os; t=json.load(open(os.environ['ATLAS_ROLE_TASK_FILE'])); "
                "json.dump({'status':'complete','outputs':{'decision':json.dumps(t['consumed_role_results'],sort_keys=True)}}, "
                "open(os.environ['ATLAS_ROLE_RESULT_FILE'],'w'))",
            ]}}), encoding="utf-8")

            rc = self.runner.main([
                "--tasks", str(tasks), "--results", str(results), "--command-config", str(config),
                "--results-dir", str(results_dir),
            ])
            role_task = json.loads((results_dir / "reviewer.task.json").read_text(encoding="utf-8"))
            saved_results = json.loads(results.read_text(encoding="utf-8"))

        consumed = role_task["consumed_role_results"]
        self.assertEqual(rc, 0)
        self.assertEqual(set(consumed), {"implementation", "author"})
        self.assertEqual(consumed["implementation"]["outputs"]["design_decision"], "keep API stable")
        self.assertEqual(consumed["author"]["outputs"]["summary"], "latest summary")
        reviewer_result = next(result for result in saved_results if result["role_id"] == "reviewer")
        self.assertIn("keep API stable", reviewer_result["outputs"]["decision"])
        self.assertNotIn("unrelated", reviewer_result["outputs"]["decision"])

    def test_runner_executes_dependency_ordered_roles_and_appends_results(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.json"
            results = root / "role-results.json"
            config = root / "commands.json"
            self.write_tasks(tasks)
            config.write_text(
                json.dumps(
                    {
                        "roles": {
                            "author": [
                                "python3",
                                "-c",
                                (
                                    "import json, os;"
                                    "json.dump({"
                                    "'status':'complete',"
                                    "'outputs':{'summary':'done'}"
                                    "}, open(os.environ['ATLAS_ROLE_RESULT_FILE'], 'w'))"
                                ),
                            ],
                            "rollup": [
                                "python3",
                                "-c",
                                (
                                    "import json, os;"
                                    "task=json.load(open(os.environ['ATLAS_ROLE_TASK_FILE']));"
                                    "summary=task['consumed_role_results']['author']['outputs']['summary'];"
                                    "assert os.environ['ATLAS_AGENT_ID'] == 'rollup';"
                                    "json.dump({"
                                    "'status':'complete',"
                                    "'outputs':{'decision':'ship '+summary}"
                                    "}, open(os.environ['ATLAS_ROLE_RESULT_FILE'], 'w'))"
                                ),
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            rc = self.runner.main(
                [
                    "--tasks",
                    str(tasks),
                    "--results",
                    str(results),
                    "--command-config",
                    str(config),
                    "--results-dir",
                    str(root / "role-run"),
                ]
            )
            payload = json.loads(results.read_text(encoding="utf-8"))
            summary = json.loads((root / "role-run" / "role-runner-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(payload[0]["role_id"], "author")
        self.assertEqual(payload[0]["outputs"]["summary"], "done")
        self.assertEqual(payload[0]["status"], "complete")
        self.assertEqual(payload[1]["role_id"], "rollup")
        self.assertEqual(payload[1]["outputs"]["decision"], "ship done")
        self.assertEqual([task["phase_index"] for task in summary["tasks"]], [0, 1])
        self.assertEqual(summary["incomplete_tasks"], [])

    def test_runner_fails_closed_when_required_outputs_remain(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.json"
            results = root / "role-results.json"
            config = root / "commands.json"
            self.write_tasks(tasks)
            config.write_text(
                json.dumps(
                    {
                        "roles": {
                            "author": [
                                "python3",
                                "-c",
                                (
                                    "import json, os;"
                                    "json.dump({"
                                    "'status':'complete',"
                                    "'outputs':{'summary':'done'}"
                                    "}, open(os.environ['ATLAS_ROLE_RESULT_FILE'], 'w'))"
                                ),
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            rc = self.runner.main(
                [
                    "--tasks",
                    str(tasks),
                    "--results",
                    str(results),
                    "--command-config",
                    str(config),
                    "--results-dir",
                    str(root / "role-run"),
                ]
            )
            summary = json.loads((root / "role-run" / "role-runner-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 3)
        self.assertEqual(summary["incomplete_tasks"][0]["role_id"], "rollup")
        self.assertEqual(summary["incomplete_tasks"][0]["phase_index"], 1)
        self.assertIn("incomplete output(s): decision", summary["incomplete_tasks"][0]["blockers"])
        self.assertIn("status: blocked", summary["incomplete_tasks"][0]["blockers"])

    def test_incomplete_summary_includes_contract_and_dependency_blockers(self) -> None:
        tasks = [
            {
                "role_id": "rollup",
                "phase_index": 1,
                "status": "incomplete",
                "missing_outputs": ["decision"],
                "contract_issues": ["dependency not complete: author"],
                "dependency_blockers": ["dependency not complete: author"],
                "consumes": ["author"],
            }
        ]

        summary = self.runner.incomplete_task_summary(tasks)

        self.assertEqual(summary[0]["contract_issues"], ["dependency not complete: author"])
        self.assertEqual(summary[0]["dependency_blockers"], ["dependency not complete: author"])
        self.assertIn("contract issue: dependency not complete: author", summary[0]["blockers"])
        self.assertIn("dependency not complete: author", summary[0]["blockers"])

    def test_apply_result_to_tasks_preserves_contract_issues_as_incomplete(self) -> None:
        tasks = [
            {
                "role_id": "author",
                "phase_index": 0,
                "status": "pending",
                "must_produce": ["summary"],
                "missing_outputs": ["summary"],
            }
        ]

        self.runner.apply_result_to_tasks(
            tasks,
            {
                "role_id": "author",
                "status": "complete",
                "outputs": {"summary": "done"},
                "contract_issues": ["manual review required"],
            },
        )
        summary = self.runner.incomplete_task_summary(tasks)

        self.assertEqual(tasks[0]["status"], "incomplete")
        self.assertEqual(tasks[0]["contract_issues"], ["manual review required"])
        self.assertEqual(self.runner.completed_roles(tasks), set())
        self.assertIn("contract issue: manual review required", summary[0]["blockers"])

    def test_runner_exits_nonzero_when_role_result_has_contract_issues(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.json"
            results = root / "role-results.json"
            config = root / "commands.json"
            tasks.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "role_id": "author",
                                "phase_index": 0,
                                "agent_ref": "agent-registry://author",
                                "consumes": [],
                                "must_produce": ["summary"],
                                "missing_outputs": ["summary"],
                                "status": "pending",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config.write_text(
                json.dumps(
                    {
                        "default": [
                            "python3",
                            "-c",
                            (
                                "import json, os;"
                                "json.dump({"
                                "'status':'complete',"
                                "'outputs':{'summary':'done'},"
                                "'contract_issues':['manual review required']"
                                "}, open(os.environ['ATLAS_ROLE_RESULT_FILE'], 'w'))"
                            ),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            rc = self.runner.main(
                [
                    "--tasks",
                    str(tasks),
                    "--results",
                    str(results),
                    "--command-config",
                    str(config),
                    "--results-dir",
                    str(root / "role-run"),
                ]
            )
            updated_tasks = json.loads(tasks.read_text(encoding="utf-8"))["tasks"]
            summary = json.loads((root / "role-run" / "role-runner-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 3)
        self.assertEqual(updated_tasks[0]["status"], "incomplete")
        self.assertEqual(summary["incomplete_tasks"][0]["contract_issues"], ["manual review required"])

    def test_runner_executes_profile_mapped_role_with_agent_env(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.json"
            results = root / "role-results.json"
            config = root / "commands.json"
            tasks.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "role_id": "security",
                                "phase_index": 0,
                                "agent_ref": "agent-registry://security",
                                "agent_definition": {
                                    "id": "security",
                                    "source": "agents/security.md",
                                    "execution_profile": "review",
                                },
                                "skills": ["critical-ideation"],
                                "consumes": [],
                                "must_produce": ["decision"],
                                "missing_outputs": ["decision"],
                                "status": "pending",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config.write_text(
                json.dumps(
                    {
                        "profiles": {
                            "review": [
                                "python3",
                                "-c",
                                (
                                    "import json, os;"
                                    "json.dump({"
                                    "'status':'complete',"
                                    "'outputs':{'decision':os.environ['ATLAS_AGENT_ID']+' '+os.environ['ATLAS_AGENT_EXECUTION_PROFILE']},"
                                    "'evidence':[os.environ['ATLAS_AGENT_SOURCE']]"
                                    "}, open(os.environ['ATLAS_ROLE_RESULT_FILE'], 'w'))"
                                ),
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            rc = self.runner.main(
                [
                    "--tasks",
                    str(tasks),
                    "--results",
                    str(results),
                    "--command-config",
                    str(config),
                    "--results-dir",
                    str(root / "role-run"),
                ]
            )
            payload = json.loads(results.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(payload[0]["outputs"]["decision"], "security review")
        self.assertEqual(payload[0]["evidence"][0], "agents/security.md")

    def test_role_commands_example_is_safe_stub(self) -> None:
        config = json.loads((ROOT / "config" / "role-commands.example.json").read_text(encoding="utf-8"))

        command = self.runner.command_from_config(
            {
                "role_id": "unmapped",
                "agent_ref": "agent-registry://unmapped",
                "skills": ["unknown"],
            },
            config,
        )

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command[:2], ["python3", "-c"])
        self.assertIn("'status': 'failed'", command[2])
        self.assertIn("agent_ids", config)
        self.assertIn("profiles", config)

    def test_goal_gate_pass_allows_rollup_but_fail_inconclusive_and_missing_verdict_block_it(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        reviews = {
            "pass": {"verdict": "pass", "reason": "Goal met", "evidence": ["acceptance.md"]},
            "fail": {"verdict": "fail", "reason": "Goal missed", "evidence": ["gap.md"]},
            "inconclusive": {"verdict": "inconclusive", "reason": "Need evidence", "evidence": ["tests.log"]},
            "missing": {"reason": "Missing verdict", "evidence": ["evidence.md"]},
        }
        for label, review in reviews.items():
            with self.subTest(verdict=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tasks = root / "tasks.json"
                results = root / "results.json"
                config = root / "commands.json"
                tasks.write_text(json.dumps({"tasks": [
                    {"role_id": "gate", "status": "pending", "goal_gate": True,
                     "consumes": [], "must_produce": ["alignment"], "missing_outputs": ["alignment"]},
                    {"role_id": "rollup", "status": "pending", "consumes": ["gate"],
                     "must_produce": ["decision"], "missing_outputs": ["decision"]},
                ]}), encoding="utf-8")
                review_json = json.dumps(review)
                config.write_text(json.dumps({"roles": {
                    "gate": ["python3", "-c", (
                        "import json,os; json.dump({'status':'complete','outputs':{'alignment':'done'},"
                        f"'goal_review':json.loads({review_json!r})" + "},open(os.environ['ATLAS_ROLE_RESULT_FILE'],'w'))"
                    )],
                    "rollup": ["python3", "-c", (
                        "import json,os; json.dump({'status':'complete','outputs':{'decision':'rolled'}},"
                        "open(os.environ['ATLAS_ROLE_RESULT_FILE'],'w'))"
                    )],
                }}), encoding="utf-8")
                rc = self.runner.main([
                    "--tasks", str(tasks), "--results", str(results), "--command-config", str(config),
                    "--results-dir", str(root / "run"),
                ])
                saved = json.loads(results.read_text(encoding="utf-8"))
                task_payload = json.loads(tasks.read_text(encoding="utf-8"))["tasks"]
                executed = [item["role_id"] for item in saved]
                if label == "pass":
                    self.assertEqual(rc, 0)
                    self.assertEqual(executed, ["gate", "rollup"])
                    self.assertEqual(task_payload[0]["goal_review"], review)
                else:
                    self.assertEqual(rc, 3)
                    self.assertEqual(executed, ["gate"])
                    self.assertEqual(task_payload[0]["goal_review"], review)
                    self.assertNotEqual(task_payload[0]["status"], "complete")
                    self.assertNotEqual(task_payload[1]["status"], "complete")

    def test_runner_persists_missing_mapping_and_missing_or_malformed_results(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        cases = {
            "unmapped": {},
            "missing-result": {"roles": {"gate": ["python3", "-c", "pass"]}},
            "malformed-result": {"roles": {"gate": ["python3", "-c", (
                "import os; open(os.environ['ATLAS_ROLE_RESULT_FILE'],'w').write('{')"
            )]}},
        }
        for label, config_payload in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tasks = root / "tasks.json"
                results = root / "results.json"
                config = root / "commands.json"
                tasks.write_text(json.dumps({"tasks": [
                    {"role_id": "gate", "status": "pending", "goal_gate": True,
                     "consumes": [], "must_produce": ["alignment"], "missing_outputs": ["alignment"]},
                    {"role_id": "rollup", "status": "pending", "consumes": ["gate"],
                     "must_produce": ["decision"], "missing_outputs": ["decision"]},
                ]}), encoding="utf-8")
                config.write_text(json.dumps(config_payload), encoding="utf-8")
                rc = self.runner.main([
                    "--tasks", str(tasks), "--results", str(results), "--command-config", str(config),
                    "--results-dir", str(root / "run"),
                ])
                saved = json.loads(results.read_text(encoding="utf-8"))
                task_payload = json.loads(tasks.read_text(encoding="utf-8"))["tasks"]
                self.assertEqual(rc, 3)
                self.assertEqual([item["role_id"] for item in saved], ["gate"])
                self.assertIn(saved[0]["status"], {"failed", "blocked"})
                self.assertEqual(task_payload[0]["status"], saved[0]["status"])
                self.assertNotEqual(task_payload[1]["status"], "complete")

    def test_nonzero_command_cannot_complete_even_with_complete_json(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = {"role_id": "author", "must_produce": ["summary"]}
            result = self.runner.run_role_task(
                task,
                ["python3", "-c", (
                    "import json,os,sys; json.dump({'status':'complete','outputs':{'summary':'done'}},"
                    "open(os.environ['ATLAS_ROLE_RESULT_FILE'],'w')); sys.exit(7)"
                )],
                results_dir=root,
                base_env={},
            )
        self.assertEqual(result["status"], "failed")

    def test_mismatched_role_result_is_persisted_as_failure_without_retry_or_gate_spoofing(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.json"
            results = root / "results.json"
            config = root / "commands.json"
            count = root / "invoked.txt"
            results_dir = root / "run"
            tasks.write_text(json.dumps({"tasks": [
                {"role_id": "gate", "status": "pending", "goal_gate": True,
                 "consumes": [], "must_produce": ["alignment"], "missing_outputs": ["alignment"]},
                {"role_id": "rollup", "status": "pending", "consumes": ["gate"],
                 "must_produce": ["decision"], "missing_outputs": ["decision"]},
            ]}), encoding="utf-8")
            impostor_result = {
                "role_id": "rollup",
                "status": "complete",
                "outputs": {"alignment": "done"},
                "goal_review": {"verdict": "pass", "reason": "Goal met", "evidence": ["evidence.md"]},
            }
            gate_command = (
                "import json,os; "
                f"open({str(count)!r},'a').write('x'); "
                f"json.dump({impostor_result!r},open(os.environ['ATLAS_ROLE_RESULT_FILE'],'w'))"
            )
            config.write_text(json.dumps({"roles": {
                "gate": ["python3", "-c", gate_command],
                "rollup": ["python3", "-c", "pass"],
            }}), encoding="utf-8")
            rc = self.runner.main([
                "--tasks", str(tasks), "--results", str(results), "--command-config", str(config),
                "--results-dir", str(results_dir),
            ])
            saved = json.loads(results.read_text(encoding="utf-8"))
            task_payload = json.loads(tasks.read_text(encoding="utf-8"))["tasks"]
            raw_result = json.loads((results_dir / "gate.invalid-role-result.json").read_text(encoding="utf-8"))
            invoked = count.read_text(encoding="utf-8")

        self.assertEqual(rc, 3)
        self.assertEqual(invoked, "x")
        self.assertEqual([item["role_id"] for item in saved], ["gate"])
        self.assertEqual(saved[0]["status"], "failed")
        self.assertIn("expected 'gate'", saved[0]["notes"])
        self.assertTrue(saved[0]["evidence"][-1].endswith("gate.invalid-role-result.json"))
        self.assertEqual(raw_result, impostor_result)
        self.assertEqual(task_payload[0]["status"], "failed")
        self.assertNotEqual(task_payload[1]["status"], "complete")

    def test_contracted_task_rejects_custom_command_mapping_before_invocation(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.json"
            results = root / "results.json"
            config = root / "commands.json"
            marker = root / "invoked.txt"
            role = {
                "role_id": "semantic-review",
                "status": "pending",
                "goal_gate": True,
                "consumes": [],
                "must_produce": ["alignment"],
                "missing_outputs": ["alignment"],
                "work_item_context": {
                    "local_execution_v1": {
                        "policy_id": "local-luna-unit-v1",
                        "role_purposes": {"semantic-review": "goal-review"},
                        "changed_interfaces": [],
                        "unresolved_questions": [],
                        "complexity_flags": [],
                    }
                },
            }
            tasks.write_text(json.dumps({"tasks": [role]}), encoding="utf-8")
            command_code = f"open({str(marker)!r},'w').write('invoked')"
            config.write_text(json.dumps({"roles": {
                "semantic-review": ["python3", "-c", command_code],
            }}), encoding="utf-8")

            rc = self.runner.main([
                "--tasks", str(tasks), "--results", str(results), "--command-config", str(config),
                "--results-dir", str(root / "run"),
            ])
            saved = json.loads(results.read_text(encoding="utf-8"))
            task_payload = json.loads(tasks.read_text(encoding="utf-8"))["tasks"]

        self.assertEqual(rc, 3)
        self.assertFalse(marker.exists())
        self.assertEqual(saved[0]["role_id"], "semantic-review")
        self.assertEqual(saved[0]["status"], "blocked")
        self.assertIn("must map directly", saved[0]["notes"])
        self.assertEqual(task_payload[0]["status"], "blocked")

    def test_supervisor_execution_mode_handoff_is_explicit_and_keeps_wrapper_gates(self) -> None:
        codex = load_script("atlas_role_codex_supervisor_handoff_test", "atlas-agent-role-codex")
        mode_value = self.runner.SUPERVISOR_CODEX_EXECUTION_MODE
        mode_env = self.runner.SUPERVISOR_CODEX_EXECUTION_MODE_ENV
        task = {
            "run_id": "run-supervisor", "template_id": "review-evidence-gate", "work_item_id": "WI-SUPERVISOR",
            "role_id": "implementation", "phase_index": 0, "agent_ref": "agents/implementation.md",
            "skills": [], "consumes": [], "must_produce": ["summary"], "missing_outputs": ["summary"],
            "status": "pending", "acceptance_criteria": ["Complete the assigned bounded task."],
            "work_item_context": {
                "acceptance_criteria": ["Complete the assigned bounded task."],
                "write_scope": ["src/example.py"],
                "local_execution_v1": {
                    "policy_id": "local-luna-unit-v1",
                    "role_purposes": {"implementation": "implementation"},
                    "changed_interfaces": [], "unresolved_questions": [], "complexity_flags": [],
                },
            },
        }

        def run_case(*, config_mode: str | None, route_qualified: bool, inherited_mode: bool) -> bool:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tasks = root / "tasks.json"
                results = root / "results.json"
                config = root / "commands.json"
                tasks.write_text(json.dumps({"tasks": [task]}), encoding="utf-8")
                command_config = {"roles": {"implementation": ["./atlas-agent-role-codex"]}}
                if config_mode is not None:
                    command_config["supervisor_codex_execution_mode"] = config_mode
                config.write_text(json.dumps(command_config), encoding="utf-8")
                launched = {"execute": False, "assignment": None, "argv": None}

                def fake_wrapper_execute(_task, _result_path, _prompt_path, _prompt, assignment, argv, *_args):
                    launched["execute"] = True
                    launched["assignment"] = assignment
                    launched["argv"] = argv
                    result = {"role_id": "implementation", "status": "complete",
                              "outputs": {"summary": "offline fake result"}, "evidence": []}
                    codex.publish_contracted_result_handoff(result)
                    return 0

                def fake_subprocess_run(_command, *, env, **_kwargs):
                    with patch.dict(os.environ, env, clear=True), \
                            patch.object(codex.common, "read_config", return_value={
                                "ATLAS_ROLE_CODEX_STANDALONE_ROUTE_QUALIFICATION": (
                                    "chatgpt_subscription" if route_qualified else None
                                ),
                                "ATLAS_ROLE_CODEX_ALLOW_EXECUTE": "true",
                            }), \
                            patch.object(codex, "execute_contracted_invocation", side_effect=fake_wrapper_execute):
                        wrapper_rc = codex.main([])
                    return types.SimpleNamespace(returncode=wrapper_rc, stdout="fake wrapper")

                inherited = {mode_env: mode_value} if inherited_mode else {}
                with patch.dict(os.environ, inherited, clear=True), \
                        patch.object(self.runner.subprocess, "run", side_effect=fake_subprocess_run):
                    self.runner.main([
                        "--tasks", str(tasks), "--results", str(results), "--command-config", str(config),
                        "--results-dir", str(root / "run"),
                    ])
                return launched

        qualified = run_case(config_mode=mode_value, route_qualified=True, inherited_mode=False)
        self.assertTrue(qualified["execute"])
        self.assertEqual(qualified["assignment"]["model"], "gpt-6-luna")
        self.assertEqual(qualified["argv"], codex.contracted_argv(qualified["assignment"]))
        self.assertFalse(run_case(config_mode=mode_value, route_qualified=False, inherited_mode=False)["execute"])
        self.assertFalse(run_case(config_mode=None, route_qualified=True, inherited_mode=True)["execute"])

    def test_contracted_mapping_rejects_canonical_wrapper_with_legacy_task_substitution(self) -> None:
        if not shutil.which("python3"):
            self.skipTest("python3 command unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.json"
            results = root / "results.json"
            config = root / "commands.json"
            marker = root / "invoked.txt"
            legacy_task = root / "legacy-task.json"
            legacy_result = root / "legacy-result.json"
            legacy_task.write_text(json.dumps({
                "role_id": "legacy-role",
                "must_produce": [],
                "acceptance_criteria": [],
            }), encoding="utf-8")
            tasks.write_text(json.dumps({"tasks": [{
                "role_id": "semantic-review",
                "status": "pending",
                "goal_gate": True,
                "consumes": [],
                "must_produce": ["alignment"],
                "missing_outputs": ["alignment"],
                "work_item_context": {
                    "local_execution_v1": {
                        "policy_id": "local-luna-unit-v1",
                        "role_purposes": {"semantic-review": "goal-review"},
                        "changed_interfaces": [],
                        "unresolved_questions": [],
                        "complexity_flags": [],
                    }
                },
            }]}), encoding="utf-8")
            marker_code = f"open({str(marker)!r},'w').write('invoked')"
            command = [
                "./atlas-agent-role-codex",
                "--task", str(legacy_task),
                "--result", str(legacy_result),
                "--execute", "--allow-execute", "--timeout-seconds", "0",
                "--codex-command", f"python3 -c {shlex.quote(marker_code)}",
            ]
            config.write_text(json.dumps({"roles": {"semantic-review": command}}), encoding="utf-8")

            rc = self.runner.main([
                "--tasks", str(tasks), "--results", str(results), "--command-config", str(config),
                "--results-dir", str(root / "run"),
            ])
            saved = json.loads(results.read_text(encoding="utf-8"))
            task_payload = json.loads(tasks.read_text(encoding="utf-8"))["tasks"]

        self.assertEqual(rc, 3)
        self.assertFalse(marker.exists())
        self.assertFalse(legacy_result.exists())
        self.assertEqual(saved[0]["role_id"], "semantic-review")
        self.assertEqual(saved[0]["status"], "blocked")
        self.assertIn("must map directly", saved[0]["notes"])
        self.assertEqual(task_payload[0]["status"], "blocked")

    def test_canonical_main_aborts_pathname_finalization_after_contracted_parent_swap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.json"
            results = root / "results.json"
            config = root / "commands.json"
            results_dir = root / "run"
            external = root / "external"
            external.mkdir()
            sentinel = external / "role-runner-summary.json"
            sentinel.write_text("keep external bytes", encoding="utf-8")
            role = {
                "role_id": "semantic-review",
                "status": "pending",
                "goal_gate": True,
                "consumes": [],
                "must_produce": ["alignment"],
                "missing_outputs": ["alignment"],
                "work_item_context": {"local_execution_v1": {
                    "policy_id": "local-luna-unit-v1",
                    "role_purposes": {"semantic-review": "goal-review"},
                    "changed_interfaces": [],
                    "unresolved_questions": [],
                    "complexity_flags": [],
                }},
            }
            tasks.write_text(json.dumps({"tasks": [role]}), encoding="utf-8")
            config.write_text(json.dumps({"roles": {"semantic-review": ["./atlas-agent-role-codex"]}}), encoding="utf-8")

            def swap_after_result(command, *, env, cwd, pass_fds, **_kwargs):
                handoff_fd = int(env[self.runner.CONTRACTED_RESULT_HANDOFF_ENV])
                os.write(handoff_fd, json.dumps({"role_id": "semantic-review", "status": "complete",
                                                "outputs": {"alignment": "reviewed"}}).encode("utf-8"))
                held = root / "held-run"
                results_dir.rename(held)
                results_dir.symlink_to(external, target_is_directory=True)
                return types.SimpleNamespace(stdout="", returncode=0)

            with patch.object(self.runner.subprocess, "run", side_effect=swap_after_result):
                rc = self.runner.main([
                    "--tasks", str(tasks), "--results", str(results), "--command-config", str(config),
                    "--results-dir", str(results_dir),
                ])

            held = root / "held-run"
            summary = json.loads((held / "role-runner-summary.json").read_text(encoding="utf-8"))
            saved_tasks = json.loads(tasks.read_text(encoding="utf-8"))["tasks"]
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep external bytes")
            self.assertFalse(results.exists())
            self.assertEqual(saved_tasks[0]["status"], "pending")

        self.assertEqual(rc, 3)
        self.assertIn("aborted after contracted results-directory identity changed", summary["finalization"])

    def test_canonical_main_refuses_mixed_contract_and_legacy_tasks_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.json"
            results = root / "results.json"
            config = root / "commands.json"
            results_dir = root / "run"
            results.write_text('[{"role_id":"preserved","status":"complete"}]', encoding="utf-8")
            results_dir.mkdir()
            sentinel = results_dir / "role-runner.out.txt"
            sentinel.write_text("preserve this artifact", encoding="utf-8")
            contracted = {
                "role_id": "semantic-review", "status": "pending", "goal_gate": True,
                "consumes": [], "must_produce": ["alignment"], "missing_outputs": ["alignment"],
                "work_item_context": {"local_execution_v1": {
                    "policy_id": "local-luna-unit-v1",
                    "role_purposes": {"semantic-review": "goal-review"},
                    "changed_interfaces": [], "unresolved_questions": [], "complexity_flags": [],
                }},
            }
            legacy = {"role_id": "legacy-review", "status": "pending", "consumes": [],
                     "must_produce": ["decision"], "missing_outputs": ["decision"]}
            tasks.write_text(json.dumps({"tasks": [contracted, legacy]}), encoding="utf-8")
            config.write_text(json.dumps({"roles": {"semantic-review": ["./atlas-agent-role-codex"]}}), encoding="utf-8")

            with patch.object(self.runner.subprocess, "run") as run_mock:
                rc = self.runner.main([
                    "--tasks", str(tasks), "--results", str(results), "--command-config", str(config),
                    "--results-dir", str(results_dir),
                ])

            saved_results = results.read_text(encoding="utf-8")
            saved_sentinel = sentinel.read_text(encoding="utf-8")
            summary = json.loads((results_dir / "role-runner-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 3)
        run_mock.assert_not_called()
        self.assertEqual(saved_results, '[{"role_id":"preserved","status":"complete"}]')
        self.assertEqual(saved_sentinel, "preserve this artifact")
        self.assertEqual(summary["result_count"], 0)
        self.assertIn("refused mixed contracted and legacy", summary["finalization"])

    def test_canonical_main_refuses_job_parent_swap_when_results_subdirectory_is_moved_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "job"
            job.mkdir()
            tasks = job / "tasks.json"
            results = job / "team-role-results.json"
            results_dir = job / "roles"
            config = root / "commands.json"
            contracted = {
                "role_id": "semantic-review", "status": "pending", "goal_gate": True,
                "consumes": [], "must_produce": ["alignment"], "missing_outputs": ["alignment"],
                "work_item_context": {"local_execution_v1": {
                    "policy_id": "local-luna-unit-v1",
                    "role_purposes": {"semantic-review": "goal-review"},
                    "changed_interfaces": [], "unresolved_questions": [], "complexity_flags": [],
                }},
            }
            tasks.write_text(json.dumps({"tasks": [contracted]}), encoding="utf-8")
            results.write_text("[]", encoding="utf-8")
            config.write_text(json.dumps({"roles": {"semantic-review": ["./atlas-agent-role-codex"]}}), encoding="utf-8")
            external_sentinel = root / "external-sentinel.json"
            external_sentinel.write_text("keep", encoding="utf-8")

            def swap_job_and_move_results_back(_command, *, env, **_kwargs):
                handoff_fd = int(env[self.runner.CONTRACTED_RESULT_HANDOFF_ENV])
                os.write(handoff_fd, json.dumps({
                    "role_id": "semantic-review", "status": "complete",
                    "outputs": {"alignment": "reviewed"},
                }).encode("utf-8"))
                held_job = root / "job.held"
                job.rename(held_job)
                job.mkdir()
                (job / "team-role-results.json").write_text("forged results", encoding="utf-8")
                (job / "tasks.json").write_text("forged tasks", encoding="utf-8")
                held_roles = held_job / "roles"
                held_roles.rename(job / "roles")
                return types.SimpleNamespace(stdout="", returncode=0)

            with patch.object(self.runner.subprocess, "run", side_effect=swap_job_and_move_results_back):
                rc = self.runner.main([
                    "--tasks", str(tasks), "--results", str(results), "--command-config", str(config),
                    "--results-dir", str(results_dir),
                ])

            self.assertEqual((job / "team-role-results.json").read_text(encoding="utf-8"), "forged results")
            self.assertEqual((job / "tasks.json").read_text(encoding="utf-8"), "forged tasks")
            self.assertEqual(external_sentinel.read_text(encoding="utf-8"), "keep")
            held_summary = json.loads((job / "roles" / "role-runner-summary.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 3)
        self.assertIn("publication directory identity changed", held_summary["finalization"])


if __name__ == "__main__":
    unittest.main()
