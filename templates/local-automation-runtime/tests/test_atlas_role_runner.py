from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
