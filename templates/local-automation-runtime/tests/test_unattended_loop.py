from __future__ import annotations

import importlib.machinery
import importlib.util
import inspect
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, filename: str):
    path = ROOT / filename
    if not path.exists():
        raise AssertionError(f"{filename} is expected to exist at {path}")
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def stage_names_from(value) -> list[str]:
    if isinstance(value, dict):
        value = value.keys()
    names: list[str] = []
    for item in value:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, (tuple, list)) and item:
            names.append(str(item[0]))
        elif hasattr(item, "name"):
            names.append(str(item.name))
        elif hasattr(item, "stage"):
            names.append(str(item.stage))
    return names


def default_stage_names(module) -> list[str]:
    if hasattr(module, "parse_args"):
        args = module.parse_args([])
        for attr in ("stages", "stage_order", "enabled_stages"):
            if hasattr(args, attr):
                names = stage_names_from(getattr(args, attr))
                if names:
                    return names

    for attr in ("DEFAULT_STAGES", "STAGES", "STAGE_ORDER"):
        if hasattr(module, attr):
            names = stage_names_from(getattr(module, attr))
            if names:
                return names

    for attr in ("build_stage_commands", "stage_commands", "build_commands"):
        if hasattr(module, attr):
            fn = getattr(module, attr)
            for call in (
                lambda: fn(types.SimpleNamespace(chain_dir="chain", cycle=1, dry_run=True)),
                fn,
            ):
                try:
                    names = stage_names_from(call())
                except TypeError:
                    continue
                if names:
                    return names

    raise AssertionError(
        "atlas-agent-unattended should expose parse_args defaults, DEFAULT_STAGES/STAGES, "
        "or build_stage_commands()"
    )


def call_with_supported_kwargs(fn, **kwargs):
    signature = inspect.signature(fn)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return fn(**kwargs)
    return fn(**{key: value for key, value in kwargs.items() if key in signature.parameters})


class UnattendedLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.loop = load_script("atlas_agent_unattended_test", "atlas-agent-unattended")

    def test_defaults_include_dispatch_repair_review_finalize_stages(self) -> None:
        names = default_stage_names(self.loop)

        self.assertIn("dispatch", names)
        self.assertIn("reconcile", names)
        self.assertIn("project-reconcile", names)
        self.assertIn("decompose", names)
        self.assertIn("dependency-promote", names)
        self.assertIn("repair", names)
        self.assertIn("local-validate", names)
        self.assertIn("deployed-validate", names)
        self.assertIn("semantic-review", names)
        self.assertIn("review", names)
        self.assertIn("finalize", names)
        self.assertLess(names.index("reconcile"), names.index("dispatch"))
        self.assertLess(names.index("project-reconcile"), names.index("dispatch"))
        self.assertLess(names.index("decompose"), names.index("dispatch"))
        self.assertLess(names.index("dependency-promote"), names.index("dispatch"))
        self.assertLess(names.index("review"), names.index("local-validate"))
        self.assertLess(names.index("review"), names.index("semantic-review"))
        self.assertLess(names.index("local-validate"), names.index("deployed-validate"))
        self.assertLess(names.index("review"), names.index("repair"))

    def test_dry_run_flag_is_accepted_as_explicit_preview(self) -> None:
        args = self.loop.build_parser().parse_args(["--dry-run"])

        self.assertTrue(args.dry_run)
        self.assertFalse(args.apply)
        self.assertFalse(args.publish)
        self.assertFalse(args.merge)
        self.assertFalse(args.close_issues)

    def test_build_decompose_command_uses_candidate_label_and_summary(self) -> None:
        args = self.loop.build_parser().parse_args(
            ["--dry-run", "--repos-file", "repos.txt", "--auto-queue-label", "status:ready"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            command = self.loop.build_decompose_command(args, Path(tmp), "chain", 1)

        self.assertIn("atlas-agent-issue-decompose", command.args[0])
        self.assertIn("--repos-file", command.args)
        self.assertIn("repos.txt", command.args)
        self.assertIn("--candidate-label", command.args)
        self.assertIn("status:ready", command.args)
        self.assertIn("status:draft", command.args)
        self.assertIn("agent:decomposition-required", command.args)
        self.assertIn("--dry-run", command.args)
        self.assertIsNotNone(command.summary_file)
        assert command.summary_file is not None
        self.assertEqual(command.summary_file.name, "decompose-cycle-1.json")

    def test_dry_run_dispatch_command_cannot_launch_mutating_orchestrator_path(self) -> None:
        args = self.loop.build_parser().parse_args(
            ["--dry-run", "--publish", "--repos-file", "repos.txt", "--auto-queue-label", "status:ready"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            repos = Path(tmp) / "repos.txt"
            repos.write_text("owner/repo\n", encoding="utf-8")
            args.repos_file = str(repos)
            commands = self.loop.build_dispatch_commands(args, Path(tmp), "chain", 1)

        self.assertEqual(len(commands), 1)
        command = commands[0].args
        self.assertIn("atlas-agent-orchestrator", command[0])
        self.assertIn("--dry-run", command)
        self.assertNotIn("--publish", command)
        self.assertNotIn("--auto-create-missing-base", command)
        self.assertNotIn("--triage-apply-stale", command)
        self.assertNotIn("--triage-approve-review-before-dispatch", command)

    def test_dry_run_overrides_mutating_stage_apply_flags(self) -> None:
        args = self.loop.build_parser().parse_args(
            [
                "--dry-run",
                "--apply",
                "--review-apply",
                "--merge",
                "--close-issues",
                "--project-reconcile-apply",
                "--dependency-promote-apply",
                "--decompose-apply",
                "--decompose-create-subissues",
                "--local-validation-apply",
                "--semantic-review-apply",
                "--deployed-validation-apply",
            ]
        )

        self.assertFalse(self.loop.reconcile_apply_enabled(args))
        self.assertFalse(self.loop.project_reconcile_apply_enabled(args))
        self.assertFalse(self.loop.decompose_apply_enabled(args))
        self.assertFalse(self.loop.decompose_create_subissues_enabled(args))
        self.assertFalse(self.loop.dependency_promote_apply_enabled(args))
        self.assertFalse(self.loop.local_validation_apply_enabled(args))
        self.assertFalse(self.loop.semantic_review_apply_enabled(args))
        self.assertFalse(self.loop.deployed_validation_apply_enabled(args))

        with tempfile.TemporaryDirectory() as tmp:
            chain_dir = Path(tmp)
            review = self.loop.build_review_command(args, chain_dir, "chain", 1, "dry")
            finalize = self.loop.build_finalize_command(args, chain_dir, "chain", 1)

        self.assertNotIn("--apply", review.args)
        self.assertNotIn("--apply", finalize.args)
        self.assertNotIn("--merge", finalize.args)
        self.assertNotIn("--close-issues", finalize.args)

    def test_dependency_promote_uses_owner_number_when_projects_file_is_absent(self) -> None:
        args = self.loop.build_parser().parse_args(
            ["--dry-run", "--repos-file", "repos.txt", "--project-owner", "Instablinds", "--project-number", "1"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            command = self.loop.build_dependency_promote_command(args, Path(tmp), "chain", 1)
            projects_index = command.args.index("--projects-file") + 1
            projects_file = Path(command.args[projects_index])

            self.assertEqual(projects_file.read_text(encoding="utf-8"), "Instablinds/1\n")
            self.assertNotIn("None", command.args)

    def test_finalize_command_receives_repos_file(self) -> None:
        args = self.loop.build_parser().parse_args(["--dry-run", "--repos-file", "repos.txt"])
        with tempfile.TemporaryDirectory() as tmp:
            command = self.loop.build_finalize_command(args, Path(tmp), "chain", 1)

        self.assertIn("--repos-file", command.args)
        repos_index = command.args.index("--repos-file") + 1
        self.assertEqual(command.args[repos_index], "repos.txt")

    def test_decompose_command_creates_subissues_by_default_when_apply_is_used(self) -> None:
        args = self.loop.build_parser().parse_args(["--apply", "--repos-file", "repos.txt"])
        with tempfile.TemporaryDirectory() as tmp:
            command = self.loop.build_decompose_command(args, Path(tmp), "chain", 1)

        self.assertIn("--apply", command.args)
        self.assertIn("--create-subissues", command.args)

    def test_decompose_create_subissues_can_be_disabled(self) -> None:
        args = self.loop.build_parser().parse_args(
            ["--apply", "--no-decompose-create-subissues", "--repos-file", "repos.txt"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            command = self.loop.build_decompose_command(args, Path(tmp), "chain", 1)

        self.assertIn("--apply", command.args)
        self.assertNotIn("--create-subissues", command.args)

    def test_chain_continues_to_summary_when_no_pr_is_approved(self) -> None:
        if hasattr(self.loop, "should_continue_to_summary"):
            should_continue = self.loop.should_continue_to_summary(
                review={"decisions": [{"label": "agent:needs-repair"}]},
                finalize={"decisions": [{"action": "blocked"}]},
            )
            self.assertTrue(should_continue)
            return

        if not hasattr(self.loop, "run_chain"):
            raise AssertionError(
                "atlas-agent-unattended should expose should_continue_to_summary() "
                "or run_chain() for chain loop testing"
            )

        calls: list[str] = []

        def fake_run_stage(stage: str, *args, **kwargs):
            calls.append(stage)
            if stage == "review":
                return {"decisions": [{"repo": "owner/repo", "number": 7, "label": "agent:needs-repair"}]}
            if stage == "finalize":
                return {"decisions": [{"repo": "owner/repo", "number": 7, "action": "blocked"}]}
            return {"ok": True}

        original_run_stage = getattr(self.loop, "run_stage", None)
        self.loop.run_stage = fake_run_stage
        try:
            with tempfile.TemporaryDirectory() as tmp:
                args = types.SimpleNamespace(
                    cycles=1,
                    chain_dir=tmp,
                    stages=["dispatch", "repair", "review", "finalize"],
                    summary=True,
                    stop_when_no_approved_pr=False,
                    dry_run=False,
                )
                call_with_supported_kwargs(
                    self.loop.run_chain,
                    args=args,
                    chain_dir=Path(tmp),
                    cycles=1,
                    stages=args.stages,
                )
        finally:
            if original_run_stage is None:
                delattr(self.loop, "run_stage")
            else:
                self.loop.run_stage = original_run_stage

        self.assertIn("review", calls)
        self.assertIn("finalize", calls)
        self.assertTrue(
            any(stage in calls for stage in ("summary", "cycle-summary")),
            "chain should still run summary when review produces no agent:review-approved PRs",
        )

    def test_review_and_finalize_logs_capture_stderr_safely(self) -> None:
        for attr in ("build_stage_command", "stage_command", "command_for_stage"):
            if not hasattr(self.loop, attr):
                continue
            fn = getattr(self.loop, attr)
            commands = []
            for stage in ("review", "finalize"):
                command = call_with_supported_kwargs(
                    fn,
                    stage=stage,
                    chain_dir=Path("chain"),
                    cycle=1,
                    log_dir=Path("logs"),
                )
                commands.append(command if isinstance(command, str) else " ".join(command))
            joined = "\n".join(commands)
            self.assert_stderr_capture_is_safe(joined)
            return

        source = inspect.getsource(self.loop)
        self.assertIn("atlas-agent-review", source, "script should invoke atlas-agent-review")
        self.assertIn("atlas-agent-finalize", source, "script should invoke atlas-agent-finalize")
        self.assert_stderr_capture_is_safe(source)

    def assert_stderr_capture_is_safe(self, text: str) -> None:
        safe_patterns = (
            "2>&1",
            "|&",
            "stderr=subprocess.PIPE",
            "stderr=subprocess.STDOUT",
            "stderr=STDOUT",
            "capture_output=True",
        )
        self.assertTrue(
            any(pattern in text for pattern in safe_patterns),
            "review/finalize log capture should include stderr",
        )

        if "|" in text or "tee" in text:
            self.assertTrue(
                "pipefail" in text or "subprocess.run" in text or "capture_output=True" in text,
                "pipeline log capture should be pipefail-safe",
            )

    def test_stage_status_marks_hidden_traceback_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "stage.log"
            log.write_text("Traceback (most recent call last):\nRuntimeError: Command failed:\n", encoding="utf-8")

            self.assertEqual(self.loop.stage_status(0, log), "warning")

    def test_repair_skips_targets_already_repaired_in_same_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            chain_dir = Path(tmp)
            (chain_dir / "repair-cycle-1.results.json").write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "name": "owner/repo#7",
                                "status": "ok",
                                "returncode": 0,
                                "log_file": "log",
                                "stage": "repair",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(self.loop.repaired_targets_in_chain(chain_dir, 2), {"owner/repo#7"})

    def test_target_from_pr_payload_uses_github_url(self) -> None:
        self.assertEqual(
            self.loop.target_from_pr_payload({"url": "https://github.com/owner/repo/pull/17"}),
            "owner/repo#17",
        )

    def test_repair_targets_skip_no_check_only_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.json"
            path.write_text(
                json.dumps(
                    {
                        "decisions": [
                            {
                                "repo": "owner/repo",
                                "number": 7,
                                "label": "agent:needs-repair",
                                "reasons": ["no checks reported"],
                            },
                            {
                                "repo": "owner/repo",
                                "number": 8,
                                "label": "agent:needs-repair",
                                "reasons": ["checks failed: unit-tests=FAILURE"],
                            },
                            {
                                "repo": "owner/repo",
                                "number": 9,
                                "label": "agent:needs-repair",
                                "reasons": ["semantic review failed for current head"],
                            },
                            {
                                "repo": "owner/repo",
                                "number": 10,
                                "label": "agent:needs-repair",
                                "reasons": ["review changes requested"],
                            },
                            {
                                "repo": "owner/repo",
                                "number": 11,
                                "label": "agent:needs-repair",
                                "reasons": ["dependency blocked: owner/repo issue #2 is not closed"],
                            },
                            {
                                "repo": "owner/repo",
                                "number": 12,
                                "label": "agent:needs-repair",
                                "reasons": ["linked issue #12 could not be verified"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                self.loop.repair_targets_from_summary(path, 10),
                ["owner/repo#8", "owner/repo#9", "owner/repo#10"],
            )

    def test_local_validation_targets_from_review_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.json"
            path.write_text(
                json.dumps(
                    {
                        "decisions": [
                            {
                                "repo": "owner/repo",
                                "number": 7,
                                "label": "agent:local-validation-required",
                                "reasons": ["no checks reported; local validation required"],
                            },
                            {
                                "repo": "owner/repo",
                                "number": 8,
                                "label": "agent:needs-repair",
                                "reasons": ["checks failed: ci=FAILURE"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(self.loop.local_validation_targets_from_summary(path, 10), ["owner/repo#7"])

    def test_deployed_validation_targets_from_review_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.json"
            path.write_text(
                json.dumps(
                    {
                        "decisions": [
                            {
                                "repo": "owner/repo",
                                "number": 7,
                                "label": "agent:manual-validation-required",
                                "reasons": ["manual or deployed validation required"],
                            },
                            {
                                "repo": "owner/repo",
                                "number": 8,
                                "label": "agent:needs-repair",
                                "reasons": ["checks failed: ci=FAILURE"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(self.loop.deployed_validation_targets_from_summary(path, 10), ["owner/repo#7"])
            self.assertEqual(
                self.loop.deployed_validation_targets_from_summary(
                    path,
                    10,
                    configured_repos={"other/repo"},
                    wildcard=False,
                ),
                [],
            )
            self.assertEqual(
                self.loop.deployed_validation_targets_from_summary(
                    path,
                    10,
                    configured_repos={"owner/repo"},
                    wildcard=False,
                ),
                ["owner/repo#7"],
            )

    def test_semantic_review_targets_from_review_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.json"
            path.write_text(
                json.dumps(
                    {
                        "decisions": [
                            {
                                "repo": "owner/repo",
                                "number": 7,
                                "label": "agent:semantic-review-required",
                                "reasons": ["semantic review required for current head"],
                            },
                            {
                                "repo": "owner/repo",
                                "number": 8,
                                "label": "agent:needs-repair",
                                "reasons": ["checks failed: ci=FAILURE"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(self.loop.semantic_review_targets_from_summary(path, 10), ["owner/repo#7"])

    def test_local_validation_apply_defaults_to_review_apply(self) -> None:
        args = types.SimpleNamespace(review_apply=True, apply=False, local_validation_apply=None)

        self.assertTrue(self.loop.local_validation_apply_enabled(args))

    def test_local_validation_apply_can_be_disabled_explicitly(self) -> None:
        args = types.SimpleNamespace(review_apply=True, apply=True, local_validation_apply=False)

        self.assertFalse(self.loop.local_validation_apply_enabled(args))

    def test_deployed_validation_apply_defaults_to_review_apply(self) -> None:
        args = types.SimpleNamespace(review_apply=True, apply=False, deployed_validation_apply=None)

        self.assertTrue(self.loop.deployed_validation_apply_enabled(args))

    def test_deployed_validation_apply_can_be_disabled_explicitly(self) -> None:
        args = types.SimpleNamespace(review_apply=True, apply=True, deployed_validation_apply=False)

        self.assertFalse(self.loop.deployed_validation_apply_enabled(args))

    def test_semantic_review_apply_defaults_to_review_apply(self) -> None:
        args = types.SimpleNamespace(review_apply=True, apply=False, semantic_review_apply=None)

        self.assertTrue(self.loop.semantic_review_apply_enabled(args))

    def test_semantic_review_apply_can_be_disabled_explicitly(self) -> None:
        args = types.SimpleNamespace(review_apply=True, apply=True, semantic_review_apply=False)

        self.assertFalse(self.loop.semantic_review_apply_enabled(args))

    def test_reconcile_apply_defaults_to_apply_or_review_apply(self) -> None:
        self.assertTrue(
            self.loop.reconcile_apply_enabled(
                types.SimpleNamespace(apply=True, review_apply=False, reconcile_apply=None)
            )
        )
        self.assertTrue(
            self.loop.reconcile_apply_enabled(
                types.SimpleNamespace(apply=False, review_apply=True, reconcile_apply=None)
            )
        )
        self.assertFalse(
            self.loop.reconcile_apply_enabled(
                types.SimpleNamespace(apply=True, review_apply=True, reconcile_apply=False)
            )
        )

    def test_project_reconcile_apply_defaults_to_apply_or_review_apply(self) -> None:
        self.assertTrue(
            self.loop.project_reconcile_apply_enabled(
                types.SimpleNamespace(apply=True, review_apply=False, project_reconcile_apply=None)
            )
        )
        self.assertTrue(
            self.loop.project_reconcile_apply_enabled(
                types.SimpleNamespace(apply=False, review_apply=True, project_reconcile_apply=None)
            )
        )
        self.assertFalse(
            self.loop.project_reconcile_apply_enabled(
                types.SimpleNamespace(apply=True, review_apply=True, project_reconcile_apply=False)
            )
        )

    def test_project_reconcile_command_can_use_projects_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            projects_file = Path(tmp) / "projects.txt"
            projects_file.write_text("owner/2\n", encoding="utf-8")
            args = types.SimpleNamespace(
                projects_file=str(projects_file),
                project_owner="ignored",
                project_number=99,
                project_item_limit=50,
                project_reconcile_apply=False,
                apply=True,
                review_apply=True,
            )

            command = self.loop.build_project_reconcile_command(args, Path(tmp), "chain", 1)

        self.assertIn("--projects-file", command.args)
        self.assertIn(str(projects_file), command.args)
        self.assertNotIn("--owner", command.args)

    def test_dependency_promote_apply_defaults_to_apply_or_review_apply(self) -> None:
        self.assertTrue(
            self.loop.dependency_promote_apply_enabled(
                types.SimpleNamespace(apply=True, review_apply=False, dependency_promote_apply=None)
            )
        )
        self.assertTrue(
            self.loop.dependency_promote_apply_enabled(
                types.SimpleNamespace(apply=False, review_apply=True, dependency_promote_apply=None)
            )
        )
        self.assertFalse(
            self.loop.dependency_promote_apply_enabled(
                types.SimpleNamespace(apply=True, review_apply=True, dependency_promote_apply=False)
            )
        )

    def test_dependency_promote_command_runs_before_dispatch_with_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repos_file = Path(tmp) / "repos.txt"
            projects_file = Path(tmp) / "projects.txt"
            repos_file.write_text("owner/repo\n", encoding="utf-8")
            projects_file.write_text("owner/2\n", encoding="utf-8")
            args = types.SimpleNamespace(
                repos_file=str(repos_file),
                projects_file=str(projects_file),
                project_item_limit=50,
                dependency_promote_apply=False,
                apply=True,
                review_apply=True,
            )

            command = self.loop.build_dependency_promote_command(args, Path(tmp), "chain", 1)

        self.assertIn("atlas-agent-dependency-promote", command.args[0])
        self.assertIn("--repos-file", command.args)
        self.assertIn(str(repos_file), command.args)
        self.assertIn("--projects-file", command.args)
        self.assertIn(str(projects_file), command.args)
        self.assertIn("--dry-run", command.args)
        self.assertIsNotNone(command.summary_file)
        assert command.summary_file is not None
        self.assertEqual(command.summary_file.name, "dependency-promote-cycle-1.json")


if __name__ == "__main__":
    unittest.main()
