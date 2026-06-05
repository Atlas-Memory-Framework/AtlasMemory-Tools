from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
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


class AtlasRoleCodexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.role_codex = load_script("atlas_role_codex_test", "atlas-agent-role-codex")
        cls.runner = load_script("atlas_role_runner_for_codex_test", "atlas-agent-role-runner")

    def role_task(self) -> dict:
        return {
            "run_id": "run-1",
            "template_id": "review-evidence-gate",
            "work_item_id": "WI-1",
            "role_id": "code-review",
            "label": "Code Review",
            "agent_ref": "agents/code-reviewer.md",
            "skills": ["review"],
            "consumes": [],
            "must_produce": ["correctness_findings", "test_gaps"],
            "missing_outputs": ["correctness_findings", "test_gaps"],
            "status": "pending",
            "acceptance_criteria": ["Find concrete defects."],
        }

    def test_build_prompt_names_role_outputs_and_result_file(self) -> None:
        prompt = self.role_codex.build_prompt(self.role_task(), "/tmp/result.json")

        self.assertIn("Role: code-review", prompt)
        self.assertIn("- correctness_findings", prompt)
        self.assertIn("- test_gaps", prompt)
        self.assertIn("`/tmp/result.json`", prompt)

    def test_prepare_mode_writes_failed_result_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            result = root / "result.json"
            prompt = root / "prompt.md"
            task.write_text(json.dumps(self.role_task()), encoding="utf-8")

            rc = self.role_codex.main(["--task", str(task), "--result", str(result), "--prompt", str(prompt)])
            payload = json.loads(result.read_text(encoding="utf-8"))

        self.assertEqual(rc, 2)
        self.assertEqual(payload["role_id"], "code-review")
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["outputs"], {})
        self.assertIn(str(prompt), payload["evidence"])
        self.assertIn("not executed", payload["notes"])

    def test_execute_requires_second_allow_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            result = root / "result.json"
            task.write_text(json.dumps(self.role_task()), encoding="utf-8")

            rc = self.role_codex.main(
                [
                    "--task",
                    str(task),
                    "--result",
                    str(result),
                    "--execute",
                    "--codex-command",
                    "python3 -c pass",
                ]
            )
            payload = json.loads(result.read_text(encoding="utf-8"))

        self.assertEqual(rc, 2)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("not allowed", payload["notes"])

    def test_runtime_relative_codex_command_resolves_from_runtime_dir(self) -> None:
        resolved = self.role_codex.resolve_command(["./atlas-agent-role-fake-codex"])

        self.assertEqual(resolved, [str(ROOT / "atlas-agent-role-fake-codex")])

    def test_execute_with_fake_codex_command_writes_required_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            result = root / "result.json"
            task.write_text(json.dumps(self.role_task()), encoding="utf-8")

            rc = self.role_codex.main(
                [
                    "--task",
                    str(task),
                    "--result",
                    str(result),
                    "--execute",
                    "--allow-execute",
                    "--timeout-seconds",
                    "0",
                    "--codex-command",
                    "./atlas-agent-role-fake-codex",
                ]
            )
            payload = json.loads(result.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(sorted(payload["outputs"]), ["correctness_findings", "test_gaps"])
        self.assertTrue(payload["outputs"]["correctness_findings"])

    def test_execute_with_allow_uses_result_env_and_records_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            result = root / "result.json"
            task.write_text(json.dumps(self.role_task()), encoding="utf-8")
            command = (
                "python3 -c \"import json, os; "
                "json.dump({'role_id': os.environ['ATLAS_ROLE_ID'] if 'ATLAS_ROLE_ID' in os.environ else 'code-review', "
                "'status':'complete', 'outputs': {'correctness_findings':'none', 'test_gaps':'none'}}, "
                "open(os.environ['ATLAS_ROLE_RESULT_FILE'], 'w'))\""
            )

            rc = self.role_codex.main(
                [
                    "--task",
                    str(task),
                    "--result",
                    str(result),
                    "--execute",
                    "--allow-execute",
                    "--timeout-seconds",
                    "0",
                    "--codex-command",
                    command,
                ]
            )
            payload = json.loads(result.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["outputs"]["correctness_findings"], "none")
        self.assertTrue(any(item.endswith(".codex.log") for item in payload["evidence"]))

    def test_default_command_uses_workflow_role_profile_args(self) -> None:
        old_profile = os.environ.get("AGENT_CODEX_WORKFLOW_ROLE_PROFILE")
        old_model = os.environ.get("AGENT_CODEX_WORKFLOW_ROLE_MODEL")
        try:
            os.environ["AGENT_CODEX_WORKFLOW_ROLE_PROFILE"] = "role-profile"
            os.environ["AGENT_CODEX_WORKFLOW_ROLE_MODEL"] = "role-model"
            command = self.role_codex.codex_command(None, profile_kind="workflow-role")
        finally:
            if old_profile is None:
                os.environ.pop("AGENT_CODEX_WORKFLOW_ROLE_PROFILE", None)
            else:
                os.environ["AGENT_CODEX_WORKFLOW_ROLE_PROFILE"] = old_profile
            if old_model is None:
                os.environ.pop("AGENT_CODEX_WORKFLOW_ROLE_MODEL", None)
            else:
                os.environ["AGENT_CODEX_WORKFLOW_ROLE_MODEL"] = old_model

        self.assertIn("--profile", command)
        self.assertIn("role-profile", command)
        self.assertIn("--model", command)
        self.assertIn("role-model", command)

    def test_codex_example_maps_known_default_roles_to_wrapper(self) -> None:
        config = json.loads((ROOT / "config" / "role-commands.codex.example.json").read_text(encoding="utf-8"))

        command = self.runner.command_from_config(self.role_task(), config)

        self.assertEqual(command, ["./atlas-agent-role-codex"])

    def test_fake_execute_example_maps_roles_to_allowed_fake_wrapper(self) -> None:
        config = json.loads((ROOT / "config" / "role-commands.fake-execute.example.json").read_text(encoding="utf-8"))

        command = self.runner.command_from_config(self.role_task(), config)

        self.assertEqual(
            command,
            [
                "./atlas-agent-role-codex",
                "--execute",
                "--allow-execute",
                "--timeout-seconds",
                "0",
                "--codex-command",
                "./atlas-agent-role-fake-codex",
            ],
        )


if __name__ == "__main__":
    unittest.main()
