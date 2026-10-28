from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
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

    def contracted_task(self, role_id: str = "implementation", *, goal_gate: bool = False) -> dict:
        purpose = "goal-review" if goal_gate else "implementation"
        task = self.role_task() | {
            "role_id": role_id,
            "goal_gate": goal_gate,
            "work_item_context": {
                "acceptance_criteria": ["The requested bounded behavior works correctly."]
                if not goal_gate else [],
                "write_scope": ["src/feature.py"] if not goal_gate else [],
                "local_execution_v1": {
                    "policy_id": "local-luna-unit-v1",
                    "role_purposes": {role_id: purpose},
                    "changed_interfaces": [],
                    "unresolved_questions": [],
                    "complexity_flags": [],
                },
            },
        }
        return task

    def test_build_prompt_names_role_outputs_and_result_file(self) -> None:
        prompt = self.role_codex.build_prompt(self.role_task(), "/tmp/result.json")

        self.assertIn("Role: code-review", prompt)
        self.assertIn("- correctness_findings", prompt)
        self.assertIn("- test_gaps", prompt)
        self.assertIn("`/tmp/result.json`", prompt)

    def test_goal_gate_prompt_has_separate_typed_contract_and_acceptance_warning(self) -> None:
        task = self.role_task() | {"goal_gate": True}
        prompt = self.role_codex.build_prompt(task, "/tmp/result.json")

        self.assertIn("\"goal_review\"", prompt)
        self.assertIn('"verdict": "pass"', prompt)
        self.assertIn('"reason": "Why the goal is or is not met"', prompt)
        self.assertIn('"evidence": ["Concrete evidence supporting the verdict"]', prompt)
        self.assertIn("Passing tests alone does not", prompt)
        self.assertIn("separate from `outputs`", prompt)

    def test_contracted_prepare_writes_fixed_model_and_explicit_argv_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            task_path = root / "task.json"
            result_path = root / "result.json"
            task_path.write_text(json.dumps(self.contracted_task()), encoding="utf-8")

            rc = self.role_codex.main(["--task", str(task_path), "--result", str(result_path)])
            report = json.loads(result_path.with_suffix(".invocation.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 2)
        self.assertEqual(report["status"], "prepared")
        self.assertFalse(report["policy"]["provider_billing_qualified"])
        self.assertEqual(report["assignment"]["model"], "gpt-6-luna")
        self.assertEqual(report["assignment"]["reasoning"], "medium")
        self.assertEqual(report["argv"], [
            "codex", "exec", "--ignore-user-config", "--sandbox", "workspace-write",
            "--ephemeral", "--skip-git-repo-check", "--model", "gpt-6-luna",
            "-c", 'model_reasoning_effort="medium"', "-",
        ])

    def test_contracted_goal_review_uses_fixed_reasoning_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            task_path = root / "task.json"
            result_path = root / "result.json"
            task_path.write_text(
                json.dumps(self.contracted_task("semantic-alignment", goal_gate=True)),
                encoding="utf-8",
            )
            self.role_codex.main(["--task", str(task_path), "--result", str(result_path)])
            report = json.loads(result_path.with_suffix(".invocation.json").read_text(encoding="utf-8"))

        self.assertEqual(report["assignment"]["model"], "gpt-6.1-sol")
        self.assertEqual(report["assignment"]["reasoning"], "high")

    def test_contracted_role_rejects_model_profile_provider_and_raw_command_overrides(self) -> None:
        cases = [
            ({"AGENT_CODEX_WORKFLOW_ROLE_MODEL": "unapproved-model"}, []),
            ({"AGENT_CODEX_WORKFLOW_ROLE_PROFILE": "unapproved-profile"}, []),
            ({"OPENAI_BASE_URL": "https://example.invalid"}, []),
            ({}, ["--profile-kind", "workflow-role"]),
            ({}, ["--codex-command", "python3 -c pass"]),
            ({}, ["--model", "unapproved-model"]),
        ]
        for env, extra_args in cases:
            with self.subTest(env=list(env), args=extra_args), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                task_path = root / "task.json"
                result_path = root / "result.json"
                task_path.write_text(json.dumps(self.contracted_task()), encoding="utf-8")
                with patch.dict(os.environ, env, clear=True):
                    rc = self.role_codex.main([
                        "--task", str(task_path), "--result", str(result_path), *extra_args,
                    ])
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                report = json.loads(result_path.with_suffix(".invocation.json").read_text(encoding="utf-8"))

                self.assertEqual(rc, 2)
                self.assertEqual(report["status"], "blocked")
                self.assertTrue(report["rejected_overrides"])
                self.assertNotIn("unapproved-model", result_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["status"], "failed")

    def test_contracted_execute_rejects_auth_overrides_without_disclosing_values(self) -> None:
        for key in ("CODEX_API_KEY", "OPENAI_API_KEY", "CODEX_ACCESS_TOKEN", "CODEX_HOME"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                task_path = root / "task.json"
                result_path = root / "result.json"
                task_path.write_text(json.dumps(self.contracted_task()), encoding="utf-8")
                secret = "synthetic-auth-override-marker"
                with patch.dict(os.environ, {key: secret}, clear=True), patch.object(
                    self.role_codex, "contracted_route_qualified", return_value=True,
                ), patch.object(self.role_codex.subprocess, "Popen") as popen_mock:
                    rc = self.role_codex.main([
                        "--task", str(task_path), "--result", str(result_path),
                        "--execute", "--allow-execute",
                    ])
                result_bytes = result_path.read_bytes()
                report_bytes = result_path.with_suffix(".invocation.json").read_bytes()
                report = json.loads(report_bytes)

                self.assertEqual(rc, 2)
                self.assertEqual(report["status"], "blocked")
                self.assertEqual(report["rejected_overrides"], [key])
                self.assertNotIn(secret.encode(), result_bytes + report_bytes)
                popen_mock.assert_not_called()

    def test_contracted_execute_fails_unqualified_without_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            task_path = root / "task.json"
            result_path = root / "result.json"
            task_path.write_text(json.dumps(self.contracted_task()), encoding="utf-8")
            with patch.object(self.role_codex.subprocess, "Popen") as popen_mock:
                rc = self.role_codex.main([
                    "--task", str(task_path), "--result", str(result_path), "--execute", "--allow-execute",
                ])
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            report = json.loads(result_path.with_suffix(".invocation.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 2)
        self.assertEqual(payload["notes"], "standalone provider/billing/startup not qualified")
        self.assertEqual(report["reason"], "standalone provider/billing/startup not qualified")
        popen_mock.assert_not_called()

    def test_contracted_result_artifact_read_rejects_oversized_regular_json(self) -> None:
        self_limit = self.role_codex.CONTRACTED_RESULT_LIMIT_BYTES + 1

        class InputSink:
            def write(self, value):
                return len(value)

            def flush(self):
                return None

            def close(self):
                return None

        class OversizedResultProcess:
            def __init__(self, _command, **kwargs):
                self.kwargs = kwargs
                self.stdin = InputSink()
                self.stdout = io.BytesIO(b"bounded output\n")
                self.returncode = 0
                self.pid = 7654325
                Path(kwargs["env"]["ATLAS_ROLE_RESULT_FILE"]).write_bytes(
                    b'{"role_id":"implementation","status":"complete","outputs":{}}'
                    + b" " * self_limit
                )

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            task_path = root / "task.json"
            result_path = root / "result.json"
            task_path.write_text(json.dumps(self.contracted_task()), encoding="utf-8")
            with patch.object(self.role_codex.common, "read_config", return_value={
                "ATLAS_ROLE_CODEX_ALLOW_EXECUTE": "true",
                "ATLAS_ROLE_CODEX_STANDALONE_ROUTE_QUALIFICATION": "chatgpt_subscription",
            }), patch.object(
                self.role_codex.subprocess, "Popen", side_effect=OversizedResultProcess,
            ):
                rc = self.role_codex.main([
                    "--task", str(task_path), "--result", str(result_path), "--execute", "--allow-execute",
                ])
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(rc, 2)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("byte limit", payload["notes"])

    def test_contracted_runner_uses_bounded_handoff_and_anchors_late_directory_swap(self) -> None:
        class Completed:
            returncode = 0
            stdout = "wrapper stdout"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks_path = root / "tasks.json"
            aggregate_path = root / "team-role-results.json"
            command_config = root / "commands.json"
            results_dir = root / "results"
            moved_results = root / "results-held"
            external_dir = root / "external"
            results_dir.mkdir()
            external_dir.mkdir()
            sentinel = external_dir / "sentinel.txt"
            sentinel.write_text("external stays unchanged", encoding="utf-8")
            task = self.contracted_task()
            tasks_path.write_text(json.dumps({"tasks": [task]}), encoding="utf-8")
            command_config.write_text(
                json.dumps({"roles": {task["role_id"]: ["./atlas-agent-role-codex"]}}), encoding="utf-8",
            )

            def fake_run(_command, *, env, pass_fds, **_kwargs):
                handoff_fd = int(env[self.runner.CONTRACTED_RESULT_HANDOFF_ENV])
                self.assertEqual(pass_fds, (handoff_fd,))
                os.write(handoff_fd, json.dumps({
                    "role_id": "implementation", "status": "complete",
                    "outputs": {"correctness_findings": "none", "test_gaps": "none"},
                    "evidence": [],
                }).encode("utf-8"))
                external_result = external_dir / "implementation.json"
                external_result.write_text(json.dumps({
                    "role_id": "implementation", "status": "complete",
                    "outputs": {"correctness_findings": "forged", "test_gaps": "forged"},
                }), encoding="utf-8")
                results_dir.rename(moved_results)
                results_dir.symlink_to(external_dir, target_is_directory=True)
                return Completed()

            with patch.object(self.runner.subprocess, "run", side_effect=fake_run):
                rc = self.runner.main([
                    "--tasks", str(tasks_path), "--results", str(aggregate_path),
                    "--command-config", str(command_config), "--results-dir", str(results_dir),
                ])
            held_result = json.loads((moved_results / "implementation.json").read_text(encoding="utf-8"))
            held_summary = json.loads((moved_results / "role-runner-summary.json").read_text(encoding="utf-8"))
            saved_tasks = json.loads(tasks_path.read_text(encoding="utf-8"))["tasks"]
            sentinel_text = sentinel.read_text(encoding="utf-8")
            external_names = {path.name for path in external_dir.iterdir()}
            aggregate_exists = aggregate_path.exists()

        self.assertEqual(held_result["status"], "failed")
        self.assertIn("directory identity changed", held_result["notes"])
        self.assertEqual(rc, 3)
        self.assertEqual(held_summary["finalization"],
                         "aborted after contracted results-directory identity changed")
        self.assertEqual(saved_tasks[0]["status"], "pending")
        self.assertFalse(aggregate_exists)
        self.assertEqual(sentinel_text, "external stays unchanged")
        self.assertEqual(external_names, {"sentinel.txt", "implementation.json"})

    def test_contracted_runner_accepts_bounded_parent_handoff(self) -> None:
        class Completed:
            returncode = 0
            stdout = "wrapper stdout"

        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "results"
            results_dir.mkdir()

            def fake_run(_command, *, env, pass_fds, **_kwargs):
                handoff_fd = int(env[self.runner.CONTRACTED_RESULT_HANDOFF_ENV])
                self.assertEqual(pass_fds, (handoff_fd,))
                os.write(handoff_fd, json.dumps({
                    "role_id": "implementation", "status": "complete",
                    "outputs": {"correctness_findings": "none", "test_gaps": "none"},
                    "evidence": [],
                }).encode("utf-8"))
                return Completed()

            with patch.object(self.runner.subprocess, "run", side_effect=fake_run):
                result = self.runner.run_role_task(
                    self.contracted_task(), ["./atlas-agent-role-codex"],
                    results_dir=results_dir, base_env={},
                )
            stored = json.loads((results_dir / "implementation.json").read_text(encoding="utf-8"))
            output = (results_dir / "implementation.out.txt").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["outputs"]["correctness_findings"], "none")
        self.assertEqual(stored, result)
        self.assertEqual(output, "wrapper stdout")

    def test_contracted_runner_rejects_oversized_handoff(self) -> None:
        class Completed:
            returncode = 0
            stdout = ""

        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "results"
            results_dir.mkdir()

            def fake_run(_command, *, env, **_kwargs):
                handoff_fd = int(env[self.runner.CONTRACTED_RESULT_HANDOFF_ENV])
                os.write(handoff_fd, b" " * (self.runner.CONTRACTED_RESULT_LIMIT_BYTES + 1))
                return Completed()

            with patch.object(self.runner.subprocess, "run", side_effect=fake_run):
                result = self.runner.run_role_task(
                    self.contracted_task(), ["./atlas-agent-role-codex"],
                    results_dir=results_dir, base_env={},
                )

        self.assertEqual(result["status"], "failed")
        self.assertIn("byte limit", result["notes"])

    def test_task_or_environment_cannot_assert_supervisor_route_qualification(self) -> None:
        task = self.contracted_task()
        task["standalone_route_qualification"] = "chatgpt_subscription"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"ATLAS_ROLE_CODEX_STANDALONE_ROUTE_QUALIFICATION": "chatgpt_subscription"},
            clear=True,
        ):
            root = Path(tmp)
            task_path = root / "task.json"
            result_path = root / "result.json"
            task_path.write_text(json.dumps(task), encoding="utf-8")
            with patch.object(self.role_codex.common, "read_config", return_value={
                "ATLAS_ROLE_CODEX_ALLOW_EXECUTE": "true",
            }):
                rc = self.role_codex.main([
                    "--task", str(task_path), "--result", str(result_path), "--execute", "--allow-execute",
                ])
            report = json.loads(result_path.with_suffix(".invocation.json").read_text(encoding="utf-8"))
        self.assertEqual(rc, 2)
        self.assertEqual(report["reason"], "standalone provider/billing/startup not qualified")

    def test_qualified_route_runs_fixed_argv_and_binds_prompt_result_and_bounded_log(self) -> None:
        class InputSink:
            def __init__(self):
                self.data = bytearray()
                self.closed = False

            def write(self, value):
                self.data.extend(value)
                return len(value)

            def flush(self):
                return None

            def close(self):
                self.closed = True

        class CompletedFakeProcess:
            def __init__(self, command, **kwargs):
                self.command = command
                self.kwargs = kwargs
                self.stdin = InputSink()
                self.stdout = io.BytesIO(b"fake process completed\\n")
                self.returncode = 0
                self.pid = 7654321
                output_path = Path(kwargs["env"]["ATLAS_ROLE_RESULT_FILE"])
                output_path.write_text(json.dumps({
                    "role_id": "implementation", "status": "complete",
                    "outputs": {
                        "correctness_findings": "none",
                        "test_gaps": "none",
                    },
                    "evidence": [],
                }), encoding="utf-8")

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

            def terminate(self):
                raise AssertionError("completed fake child must not be terminated")

            def kill(self):
                raise AssertionError("completed fake child must not be killed")

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode="w+b") as handoff:
            with patch.dict(
                os.environ,
                {self.role_codex.CONTRACTED_RESULT_HANDOFF_ENV: str(handoff.fileno())},
                clear=True,
            ):
                root = Path(tmp)
                task_path = root / "task.json"
                result_path = root / "result.json"
                task_path.write_text(json.dumps(self.contracted_task()), encoding="utf-8")
                created = []

                def fake_popen(command, **kwargs):
                    self.assertNotIn(self.role_codex.CONTRACTED_RESULT_HANDOFF_ENV, kwargs["env"])
                    proc = CompletedFakeProcess(command, **kwargs)
                    created.append(proc)
                    # Model a child that rewrites its adjacent diagnostic report.
                    # The wrapper must rebuild that report from its held parent copy.
                    report_path = Path(kwargs["env"]["ATLAS_ROLE_RESULT_FILE"]).with_suffix(".invocation.json")
                    attacker_path = root / "attacker-report.json"
                    attacker_path.write_text(json.dumps({
                        "status": "completed",
                        "assignment": {"model": "attacker-selected-model"},
                        "argv": ["attacker-selected-command"],
                        "policy": {"provider_billing_qualified": True},
                    }), encoding="utf-8")
                    report_path.unlink(missing_ok=True)
                    report_path.symlink_to(attacker_path)
                    attacker_log = root / "attacker-log.txt"
                    attacker_log.write_text("keep this external target unchanged", encoding="utf-8")
                    log_path = Path(kwargs["env"]["ATLAS_ROLE_RESULT_FILE"]).with_suffix(".codex.log")
                    log_path.unlink(missing_ok=True)
                    log_path.symlink_to(attacker_log)
                    return proc

                with patch.object(self.role_codex.common, "read_config", return_value={
                    "ATLAS_ROLE_CODEX_ALLOW_EXECUTE": "true",
                    "ATLAS_ROLE_CODEX_STANDALONE_ROUTE_QUALIFICATION": "chatgpt_subscription",
                }), patch.object(self.role_codex.subprocess, "Popen", side_effect=fake_popen):
                    rc = self.role_codex.main([
                        "--task", str(task_path), "--result", str(result_path), "--execute", "--allow-execute",
                    ])
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                report = json.loads(result_path.with_suffix(".invocation.json").read_text(encoding="utf-8"))
                attacker_report = json.loads((root / "attacker-report.json").read_text(encoding="utf-8"))
                invocation_is_symlink = result_path.with_suffix(".invocation.json").is_symlink()
                attacker_log_text = (root / "attacker-log.txt").read_text(encoding="utf-8")
                log_is_symlink = result_path.with_suffix(".codex.log").is_symlink()
                handoff.seek(0)
                handed_result = json.loads(handoff.read().decode("utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(payload["outputs"]["correctness_findings"], "none")
        self.assertEqual(created[0].command, [
            "codex", "exec", "--ignore-user-config", "--sandbox", "workspace-write",
            "--ephemeral", "--skip-git-repo-check", "--model", "gpt-6-luna",
            "-c", 'model_reasoning_effort="medium"', "-",
        ])
        self.assertEqual(created[0].kwargs["stdin"], subprocess.PIPE)
        self.assertEqual(created[0].kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(created[0].kwargs["stderr"], subprocess.STDOUT)
        self.assertFalse(created[0].kwargs.get("start_new_session", False))
        self.assertIn(b"Task packet:", created[0].stdin.data)
        self.assertEqual(report["status"], "completed")
        self.assertTrue(report["custody"]["stdout_closed"])
        self.assertEqual(report["assignment"]["model"], "gpt-6-luna")
        self.assertEqual(report["argv"], created[0].command)
        self.assertEqual(report["policy"]["qualification_source"], "runtime config.env")
        self.assertEqual(handed_result, payload)
        self.assertEqual(attacker_report["assignment"]["model"], "attacker-selected-model")
        self.assertFalse(invocation_is_symlink)
        self.assertEqual(attacker_log_text, "keep this external target unchanged")
        self.assertFalse(log_is_symlink)
        self.assertTrue(report["custody"]["direct_child_reaped"])
        self.assertTrue(report["custody"]["io_threads_closed"])
        self.assertEqual(
            report["custody"]["process_group_scope"],
            "inherited outer worker group; group cleanup is parent-owned",
        )
        self.assertLessEqual(report["custody"]["output_bytes"], self.role_codex.CONTRACTED_OUTPUT_LIMIT_BYTES)

    def test_result_symlink_is_rejected_and_fail_closed_output_replaces_link(self) -> None:
        class InputSink:
            def write(self, value):
                return len(value)

            def flush(self):
                return None

            def close(self):
                return None

        class ResultSymlinkFakeProcess:
            def __init__(self, command, **kwargs):
                self.command = command
                self.kwargs = kwargs
                self.stdin = InputSink()
                self.stdout = io.BytesIO(b"fake process completed\\n")
                self.returncode = 0
                self.pid = 7654323
                result_path = Path(kwargs["env"]["ATLAS_ROLE_RESULT_FILE"])
                attacker_path = root / "attacker-result.json"
                attacker_path.write_text(json.dumps({
                    "role_id": "implementation", "status": "complete",
                    "outputs": {"correctness_findings": "forged", "test_gaps": "forged"},
                    "evidence": [],
                }), encoding="utf-8")
                result_path.symlink_to(attacker_path)

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            task_path = root / "task.json"
            result_path = root / "result.json"
            task_path.write_text(json.dumps(self.contracted_task()), encoding="utf-8")
            with patch.object(self.role_codex.common, "read_config", return_value={
                "ATLAS_ROLE_CODEX_ALLOW_EXECUTE": "true",
                "ATLAS_ROLE_CODEX_STANDALONE_ROUTE_QUALIFICATION": "chatgpt_subscription",
            }), patch.object(
                self.role_codex.subprocess, "Popen", side_effect=ResultSymlinkFakeProcess,
            ):
                rc = self.role_codex.main([
                    "--task", str(task_path), "--result", str(result_path), "--execute", "--allow-execute",
                ])
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            attacker_payload = json.loads((root / "attacker-result.json").read_text(encoding="utf-8"))
            result_is_symlink = result_path.is_symlink()

        self.assertEqual(rc, 2)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("invalid result", payload["notes"])
        self.assertFalse(result_is_symlink)
        self.assertEqual(attacker_payload["outputs"]["correctness_findings"], "forged")

    def test_contract_refusal_replaces_dangling_result_symlink_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            task_path = root / "task.json"
            result_path = root / "result.json"
            missing_target = root / "missing-external-target.json"
            task_path.write_text(json.dumps(self.contracted_task()), encoding="utf-8")
            result_path.symlink_to(missing_target)
            with patch.object(self.role_codex.subprocess, "Popen") as popen_mock:
                rc = self.role_codex.main(["--task", str(task_path), "--result", str(result_path)])
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            result_is_symlink = result_path.is_symlink()
            target_exists = missing_target.exists()

        self.assertEqual(rc, 2)
        self.assertEqual(payload["status"], "failed")
        self.assertFalse(result_is_symlink)
        self.assertFalse(target_exists)
        popen_mock.assert_not_called()

    def test_contracted_artifact_parent_swap_cannot_redirect_wrapper_writes(self) -> None:
        class InputSink:
            def write(self, value):
                return len(value)

            def flush(self):
                return None

            def close(self):
                return None

        class ParentSwapFakeProcess:
            def __init__(self, command, **kwargs):
                self.command = command
                self.kwargs = kwargs
                self.stdin = InputSink()
                self.stdout = io.BytesIO(b"fake process completed\\n")
                self.returncode = 0
                self.pid = 7654324
                Path(kwargs["env"]["ATLAS_ROLE_RESULT_FILE"]).write_text(json.dumps({
                    "role_id": "implementation", "status": "complete",
                    "outputs": {"correctness_findings": "none", "test_gaps": "none"},
                    "evidence": [],
                }), encoding="utf-8")
                (external_dir / "result.json").write_text(json.dumps({
                    "role_id": "implementation", "status": "complete",
                    "outputs": {"correctness_findings": "external-forgery", "test_gaps": "external-forgery"},
                    "evidence": [],
                }), encoding="utf-8")
                artifact_dir.rename(held_artifact_dir)
                artifact_dir.symlink_to(external_dir, target_is_directory=True)

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            task_path = root / "task.json"
            artifact_dir = root / "artifacts"
            held_artifact_dir = root / "artifacts-held"
            external_dir = root / "external"
            artifact_dir.mkdir()
            external_dir.mkdir()
            sentinel_path = external_dir / "sentinel.txt"
            sentinel_path.write_text("do not modify", encoding="utf-8")
            task_path.write_text(json.dumps(self.contracted_task()), encoding="utf-8")
            result_path = artifact_dir / "result.json"
            with patch.object(self.role_codex.common, "read_config", return_value={
                "ATLAS_ROLE_CODEX_ALLOW_EXECUTE": "true",
                "ATLAS_ROLE_CODEX_STANDALONE_ROUTE_QUALIFICATION": "chatgpt_subscription",
            }), patch.object(
                self.role_codex.subprocess, "Popen", side_effect=ParentSwapFakeProcess,
            ):
                rc = self.role_codex.main([
                    "--task", str(task_path), "--result", str(result_path), "--execute", "--allow-execute",
                ])
            held_result = json.loads((held_artifact_dir / "result.json").read_text(encoding="utf-8"))
            external_result = json.loads((external_dir / "result.json").read_text(encoding="utf-8"))
            sentinel_text = sentinel_path.read_text(encoding="utf-8")
            external_entries = {path.name for path in external_dir.iterdir()}
            artifact_path_is_symlink = artifact_dir.is_symlink()

        self.assertEqual(rc, 2)
        self.assertEqual(held_result["status"], "failed")
        self.assertIn("directory changed", held_result["notes"])
        self.assertEqual(external_result["outputs"]["correctness_findings"], "external-forgery")
        self.assertTrue(artifact_path_is_symlink)
        self.assertEqual(sentinel_text, "do not modify")
        self.assertEqual(external_entries, {"sentinel.txt", "result.json"})

    def test_bounded_process_timeout_reaps_direct_child(self) -> None:
        with self.role_codex.cancellation_events() as cancelled:
            outcome = self.role_codex.run_contracted_process(
                [sys.executable, "-c", "import time; time.sleep(10)"], "prompt", os.environ.copy(), 0.1, cancelled,
            )
        self.assertEqual(outcome["status"], "timed_out")
        self.assertTrue(outcome["direct_child_reaped"])
        self.assertTrue(outcome["stdout_closed"])
        self.assertIsNotNone(outcome["returncode"])

    def test_bounded_process_output_overflow_reaps_direct_child(self) -> None:
        with self.role_codex.cancellation_events() as cancelled:
            outcome = self.role_codex.run_contracted_process(
                [sys.executable, "-c", "import sys; sys.stdout.write('x' * 100000)"],
                "prompt", os.environ.copy(), 5, cancelled,
            )
        self.assertEqual(outcome["status"], "output_limit")
        self.assertTrue(outcome["direct_child_reaped"])
        self.assertTrue(outcome["stdout_closed"])
        self.assertTrue(outcome["output_overflow"])
        self.assertEqual(len(outcome["output"]), self.role_codex.CONTRACTED_OUTPUT_LIMIT_BYTES)

    def test_bounded_process_cancellation_reaps_direct_child(self) -> None:
        cancelled = threading.Event()
        timer = threading.Timer(0.1, cancelled.set)
        timer.start()
        try:
            outcome = self.role_codex.run_contracted_process(
                [sys.executable, "-c", "import time; time.sleep(10)"], "prompt", os.environ.copy(), 5, cancelled,
            )
        finally:
            timer.cancel()
        self.assertEqual(outcome["status"], "cancelled")
        self.assertTrue(outcome["direct_child_reaped"])
        self.assertTrue(outcome["stdout_closed"])
        self.assertIsNotNone(outcome["returncode"])

    def test_bounded_process_stdout_close_failure_keeps_cleanup_uncertain(self) -> None:
        class CloseFailureStream(io.BytesIO):
            def close(self):
                raise OSError("synthetic close failure")

        class CompletedProcess:
            pid = 7654325
            returncode = 0

            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = CloseFailureStream(b"complete output")

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

        proc = CompletedProcess()
        with patch.object(self.role_codex.subprocess, "Popen", return_value=proc):
            outcome = self.role_codex.run_contracted_process(
                ["fake-codex"], "prompt", os.environ.copy(), 5, threading.Event(),
            )
        try:
            self.assertEqual(outcome["status"], "cleanup_uncertain")
            self.assertTrue(outcome["io_threads_closed"])
            self.assertFalse(outcome["stdout_closed"])
            self.assertEqual(outcome["output"], b"complete output")
        finally:
            io.BytesIO.close(proc.stdout)

    def test_bounded_process_does_not_close_stdout_while_reader_remains_active(self) -> None:
        class BlockingStream:
            def __init__(self):
                self.entered = threading.Event()
                self.release = threading.Event()
                self.close_calls = 0

            def read1(self, _size):
                self.entered.set()
                self.release.wait(2)
                return b""

            def read(self, size):
                return self.read1(size)

            def close(self):
                self.close_calls += 1

        class CompletedProcess:
            pid = 7654326
            returncode = 0

            def __init__(self, stdout):
                self.stdin = io.BytesIO()
                self.stdout = stdout

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

        stream = BlockingStream()
        proc = CompletedProcess(stream)
        try:
            with patch.object(self.role_codex, "CONTRACTED_TERMINATION_GRACE_SECONDS", 0.01), patch.object(
                self.role_codex.subprocess, "Popen", return_value=proc,
            ):
                outcome = self.role_codex.run_contracted_process(
                    ["fake-codex"], "prompt", os.environ.copy(), 5, threading.Event(),
                )
            self.assertTrue(stream.entered.is_set())
            self.assertEqual(outcome["status"], "cleanup_uncertain")
            self.assertFalse(outcome["io_threads_closed"])
            self.assertFalse(outcome["stdout_closed"])
            self.assertEqual(stream.close_calls, 0)
        finally:
            stream.release.set()
            readers = [thread for thread in threading.enumerate() if thread.name == "atlas-codex-output"]
            for reader in readers:
                reader.join(1)
            self.assertFalse(any(reader.is_alive() for reader in readers))
            stream.close()

    def test_bounded_process_reports_uncertain_cleanup_without_claiming_reap(self) -> None:
        class InputSink:
            def write(self, value):
                return len(value)

            def flush(self):
                return None

            def close(self):
                return None

        class UnreapedFakeProcess:
            pid = 7654322
            stdin = InputSink()
            stdout = io.BytesIO(b"")

            def poll(self):
                return None

            def terminate(self):
                return None

            def kill(self):
                return None

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("fake", timeout)

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            task_path = root / "task.json"
            result_path = root / "result.json"
            task_path.write_text(json.dumps(self.contracted_task()), encoding="utf-8")
            with patch.object(self.role_codex.common, "read_config", return_value={
                "ATLAS_ROLE_CODEX_ALLOW_EXECUTE": "true",
                "ATLAS_ROLE_CODEX_STANDALONE_ROUTE_QUALIFICATION": "chatgpt_subscription",
            }), patch.object(
                self.role_codex.subprocess, "Popen", return_value=UnreapedFakeProcess(),
            ):
                rc = self.role_codex.main([
                    "--task", str(task_path), "--result", str(result_path), "--execute",
                    "--allow-execute", "--timeout-seconds", "1",
                ])
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            report = json.loads(result_path.with_suffix(".invocation.json").read_text(encoding="utf-8"))
        self.assertEqual(rc, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("do not retry until reconciled", payload["notes"])
        self.assertEqual(report["status"], "cleanup_uncertain")
        self.assertTrue(report["custody"]["custody_uncertain"])
        self.assertFalse(report["custody"]["direct_child_reaped"])
        self.assertTrue(report["custody"]["stdout_closed"])

    def test_contracted_helper_rejects_extra_route_fields_without_fallback(self) -> None:
        task = self.contracted_task()
        task["work_item_context"]["local_execution_v1"]["model"] = "gpt-6.1-sol"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            task_path = root / "task.json"
            result_path = root / "result.json"
            task_path.write_text(json.dumps(task), encoding="utf-8")
            rc = self.role_codex.main(["--task", str(task_path), "--result", str(result_path)])
            report = json.loads(result_path.with_suffix(".invocation.json").read_text(encoding="utf-8"))
        self.assertEqual(rc, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertNotIn("argv", report)
    def test_planning_and_task_authors_receive_writing_instructions_before_packet(self) -> None:
        for role in ("architecture", "product-semantics", "rollup-editor", "implementation"):
            with self.subTest(role=role):
                task = self.role_task()
                task.update(role_id=role, label=role, skills=["plan"])
                prompt = self.role_codex.build_prompt(task, "/tmp/result.json")
                self.assertLess(prompt.index("Writing instructions"), prompt.index("Task packet:"))
                for requirement in ("plain, direct technical English", "first draft",
                                    "technical precision, depth and breadth", "uncertainty",
                                    "outcome, owner, action, conditions, reason",
                                    "acceptance", "arbitrary word limit"):
                    self.assertIn(requirement, prompt)
                self.assertIn('"role_id": "' + role + '"', prompt)
                self.assertIn("every required output has a concrete, non-empty value", prompt)

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

    def test_fake_codex_emits_explicitly_synthetic_review_only_for_goal_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            result = root / "result.json"
            task.write_text(json.dumps(self.role_task() | {"goal_gate": True}), encoding="utf-8")
            rc = self.role_codex.main([
                "--task", str(task), "--result", str(result), "--execute", "--allow-execute",
                "--timeout-seconds", "0", "--codex-command", "./atlas-agent-role-fake-codex",
            ])
            payload = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(rc, 0)
        self.assertEqual(payload["goal_review"]["verdict"], "pass")
        self.assertIn("Synthetic", payload["goal_review"]["reason"])
        self.assertIn("synthetic", payload["notes"].lower())

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
