from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "AtlasMemory-Tools" / "templates" / "local-automation-runtime"
if not TEMPLATE_ROOT.exists():
    TEMPLATE_ROOT = ROOT


def load_script(name: str, filename: str):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / filename))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


class RuntimeTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.finalize = load_script("template_finalize", "atlas-agent-finalize")
        cls.cycle = load_script("template_cycle_summary", "atlas-agent-cycle-summary")
        cls.bridge = load_script("template_plan_queue", "atlas-agent-plan-queue")
        cls.local_validate = load_script("template_local_validate", "atlas-agent-local-validate")
        cls.deployed_validate = load_script("template_deployed_validate", "atlas-agent-deployed-validate")
        cls.cleanup = load_script("template_cleanup", "atlas-agent-cleanup")
        cls.unattended = load_script("template_unattended", "atlas-agent-unattended")

    def test_finalizer_summary_serializes_decisions(self) -> None:
        decision = self.finalize.FinalizeDecision(
            repo="owner/repo",
            number=7,
            title="agent: address issue #7",
            url="https://example.invalid/pr/7",
            issue_number=7,
            action="blocked",
            reasons=["no checks reported"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            self.finalize.write_summary(str(path), [decision])
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["decisions"][0]["repo"], "owner/repo")
        self.assertEqual(payload["decisions"][0]["action"], "blocked")
        self.assertEqual(payload["decisions"][0]["reasons"], ["no checks reported"])

    def test_cycle_summary_aggregates_build_and_finalizer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            chain_dir = Path(tmp)
            (chain_dir / "build-cycle-1.results.tsv").write_text(
                "ok\towner/repo/lane-1\tlogs/ok.log\nfailed\towner/repo/lane-2\tlogs/fail.log\n",
                encoding="utf-8",
            )
            (chain_dir / "finalize-cycle-1.json").write_text(
                json.dumps(
                    {
                        "decisions": [
                            {
                                "repo": "owner/repo",
                                "number": 3,
                                "action": "blocked",
                                "reasons": ["dependency blocked"],
                            },
                            {"repo": "owner/repo", "number": 4, "action": "merge", "reasons": []},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (chain_dir / "review-cycle-1.json").write_text(
                json.dumps(
                    {
                        "decisions": [
                            {"repo": "owner/repo", "number": 3, "label": "agent:needs-repair"},
                            {"repo": "owner/repo", "number": 4, "label": "agent:review-approved"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = self.cycle.summarize(chain_dir, 1)

        self.assertEqual(summary["build"]["ok"], 1)
        self.assertEqual(summary["build"]["failed"], 1)
        self.assertEqual(summary["finalizer"]["counts"]["blocked"], 1)
        self.assertEqual(summary["finalizer"]["counts"]["merge"], 1)
        self.assertEqual(summary["review"]["counts"]["agent:needs-repair"], 1)
        self.assertEqual(summary["review"]["counts"]["agent:review-approved"], 1)

    def test_cycle_summary_reads_items_triage_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            chain_dir = Path(tmp)
            (chain_dir / "local-needs-human-summary-owner__repo-cycle-1.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "repo": "owner/repo",
                                "entity_id": "9",
                                "dedupe_key": "owner/repo#9",
                                "reasons": ["manual_gates_remaining"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = self.cycle.summarize(chain_dir, 1)

        self.assertEqual(summary["triage"]["blocker_count"], 1)
        self.assertEqual(summary["triage"]["blockers"][0]["repo"], "owner/repo")

    def test_urgent_message_contains_explicit_manual_validation_instruction(self) -> None:
        summary = {
            "chain_id": "unattended-test",
            "chain_dir": "/tmp/chain",
            "cycle": 1,
            "build": {"results": []},
            "triage": {"blockers": [], "blocker_count": 0},
            "review": {
                "blocked": [
                    {
                        "repo": "owner/repo",
                        "number": 7,
                        "url": "https://github.com/owner/repo/pull/7",
                        "label": "agent:manual-validation-required",
                        "reasons": ["manual or deployed validation required"],
                    }
                ]
            },
            "finalizer": {"blocked": []},
        }

        card = self.cycle.urgent_message_card(summary)

        self.assertIn("URGENT", card["title"])
        self.assertIn("[owner/repo#7](https://github.com/owner/repo/pull/7)", card["text"])
        self.assertIn("add `agent:manual-validation-approved`", card["text"])

    def test_plan_queue_blocks_children_with_dependencies(self) -> None:
        child = {
            "labels": ["status:ready"],
            "dispatch_recommendation": "auto-dispatch",
            "dependencies": ["owner/repo#1"],
        }

        self.assertIn("dependencies: owner/repo#1", self.bridge.child_blockers(child))
        self.assertIn("missing Open dependencies execution field", self.bridge.child_blockers(child))

    def test_plan_queue_blocks_oversized_ready_children(self) -> None:
        child = {
            "labels": ["status:ready", "points:5"],
            "dispatch_recommendation": "auto-dispatch",
            "suggested_points": 5,
            "dependencies": [],
            "blockers": [],
            "dependency_issue_refs": [],
            "blocker_issue_refs": [],
            "automation_blockers": [],
            "body": "## Execution State\n- Open dependencies: `none`\n- Manual gates remaining: `none`\n",
        }

        self.assertIn("points:5 requires decomposition before dispatch", self.bridge.child_blockers(child))

    def test_plan_queue_blocks_manual_gates_and_dispatch_guardrails(self) -> None:
        child = {
            "labels": ["status:ready"],
            "dispatch_recommendation": "auto-dispatch",
            "dependencies": [],
            "blockers": [],
            "dependency_issue_refs": [],
            "blocker_issue_refs": [],
            "automation_blockers": [],
            "body": (
                "## Execution State\n"
                "- Open dependencies: `none`\n"
                "- Manual gates remaining: `hosted smoke`\n\n"
                "## Dispatch Guardrails\n"
                "- Requires decomposition\n"
            ),
        }

        blockers = self.bridge.child_blockers(child)
        self.assertIn("manual gates remaining", blockers)
        self.assertIn("dispatch guardrails", blockers)

    def test_plan_queue_allows_unbackticked_manual_gate_none(self) -> None:
        child = {
            "labels": ["status:ready"],
            "dispatch_recommendation": "auto-dispatch",
            "dependencies": [],
            "blockers": [],
            "dependency_issue_refs": [],
            "blocker_issue_refs": [],
            "automation_blockers": [],
            "body": "## Execution State\n- Open dependencies: none\n- Manual gates remaining: none\n",
        }

        self.assertNotIn("manual gates remaining", self.bridge.child_blockers(child))

    def test_plan_queue_allows_clean_ready_child(self) -> None:
        child = {
            "labels": ["status:ready"],
            "dispatch_recommendation": "auto-dispatch",
            "dependencies": [],
            "blockers": [],
            "dependency_issue_refs": [],
            "blocker_issue_refs": [],
            "automation_blockers": [],
        }

        self.assertEqual(self.bridge.child_blockers(child), [])

    def test_plan_queue_blocks_closed_ready_child_from_live_preview(self) -> None:
        payload = {
            "children": [
                {
                    "source_id": "PROXY-PLANNING-CONTRACT-001",
                    "title": "[PROXY-PLANNING-CONTRACT-001] Stale ready issue",
                    "labels": ["status:ready"],
                    "dispatch_recommendation": "auto-dispatch",
                    "dependencies": [],
                    "blockers": [],
                    "dependency_issue_refs": [],
                    "blocker_issue_refs": [],
                    "automation_blockers": [],
                }
            ],
            "sync_preview": {
                "operations": [
                    {
                        "source_id": "PROXY-PLANNING-CONTRACT-001",
                        "issue_repo": "owner/repo",
                        "match": {
                            "number": 716,
                            "title": "[PROXY-PLANNING-CONTRACT-001] Stale ready issue",
                            "url": "https://github.com/owner/repo/issues/716",
                            "state": "CLOSED",
                        },
                        "labels": {"existing": ["status:ready"], "desired": ["status:ready"]},
                    }
                ]
            },
        }

        preview = self.bridge.compact_preview(payload)

        self.assertEqual(preview["queueable_count"], 0)
        self.assertEqual(preview["blocked"][0]["reasons"], ["live issue state CLOSED"])

    def test_plan_queue_blocks_completed_closed_child_from_live_preview(self) -> None:
        payload = {
            "children": [
                {
                    "source_id": "DONE-CHILD-001",
                    "title": "[DONE-CHILD-001] Completed stale ready issue",
                    "labels": ["status:ready"],
                    "dispatch_recommendation": "auto-dispatch",
                    "dependencies": [],
                    "blockers": [],
                    "dependency_issue_refs": [],
                    "blocker_issue_refs": [],
                    "automation_blockers": [],
                }
            ],
            "sync_preview": {
                "operations": [
                    {
                        "source_id": "DONE-CHILD-001",
                        "issue_repo": "owner/repo",
                        "match": {
                            "number": 717,
                            "title": "[DONE-CHILD-001] Completed stale ready issue",
                            "url": "https://github.com/owner/repo/issues/717",
                            "state": "CLOSED",
                        },
                        "labels": {"existing": ["agent:done", "status:ready"], "desired": ["status:ready"]},
                    }
                ]
            },
        }

        preview = self.bridge.compact_preview(payload)

        self.assertEqual(preview["queueable_count"], 0)
        self.assertIn("live issue state CLOSED", preview["blocked"][0]["reasons"])

    def test_plan_queue_blocks_blocked_parent_shape(self) -> None:
        child = {
            "source_id": "SKILLOPT-ATLAS-EVAL-001",
            "title": "[SKILLOPT-ATLAS-EVAL-001] Parent packet",
            "labels": ["status:blocked", "points:8"],
            "dispatch_recommendation": "review-before-dispatch",
            "suggested_points": 8,
            "dependencies": [],
            "blockers": [],
            "dependency_issue_refs": [],
            "blocker_issue_refs": [],
            "automation_blockers": ["review-before-dispatch"],
            "body": (
                "## Execution State\n"
                "- Open dependencies: `none`\n"
                "- Manual gates remaining: `decompose into reviewed one-point child issues`\n\n"
                "## Dispatch Guardrails\n"
                "- Do not add agent:ready or queue this parent.\n"
            ),
        }

        blockers = self.bridge.child_blockers(child)

        self.assertIn("automation_blockers: review-before-dispatch", blockers)
        self.assertIn("points:8 requires decomposition before dispatch", blockers)
        self.assertIn("dispatch_recommendation: review-before-dispatch", blockers)
        self.assertIn("missing status:ready", blockers)
        self.assertIn("manual gates remaining", blockers)
        self.assertIn("dispatch guardrails", blockers)

    def test_plan_queue_allows_open_one_point_child_from_live_preview(self) -> None:
        payload = {
            "children": [
                {
                    "source_id": "ATLASFS-CODEX-CHILD-001",
                    "title": "[ATLASFS-CODEX-CHILD-001] One point child",
                    "labels": ["status:ready", "points:1"],
                    "dispatch_recommendation": "auto-dispatch",
                    "suggested_points": 1,
                    "dependencies": [],
                    "blockers": [],
                    "dependency_issue_refs": [],
                    "blocker_issue_refs": [],
                    "automation_blockers": [],
                    "body": "## Execution State\n- Open dependencies: `none`\n- Manual gates remaining: `none`\n",
                }
            ],
            "sync_preview": {
                "operations": [
                    {
                        "source_id": "ATLASFS-CODEX-CHILD-001",
                        "issue_repo": "owner/repo",
                        "match": {
                            "number": 801,
                            "title": "[ATLASFS-CODEX-CHILD-001] One point child",
                            "url": "https://github.com/owner/repo/issues/801",
                            "state": "OPEN",
                        },
                        "labels": {"existing": ["status:ready", "points:1"], "desired": ["status:ready", "points:1"]},
                    }
                ]
            },
        }

        preview = self.bridge.compact_preview(payload)

        self.assertEqual(preview["queueable_count"], 1)
        self.assertEqual(preview["blocked_count"], 0)

    def test_plan_queue_supports_leaf_issue_strategy(self) -> None:
        args = types.SimpleNamespace(
            plan="plan.md",
            registry_root=None,
            registry_project_id=None,
            registry_epic_id=None,
            registry_story_id=[],
            repo="owner/repo",
            strategy="leaf-issues",
            project_url=None,
            project_owner=None,
            project_number=None,
        )

        cmd = self.bridge.projection_args(args, "--dry-run")

        self.assertIn("leaf-issues", cmd)

    def test_durable_template_contains_unattended_validation_runtime(self) -> None:
        for relative in (
            "atlas-agent-unattended",
            "atlas-agent-cleanup",
            "atlas-agent-issue-decompose",
            "atlas-agent-reconcile",
            "atlas-agent-project-reconcile",
            "atlas-agent-review",
            "atlas-agent-semantic-review",
            "atlas-agent-shift",
            "atlas-agent-finalize",
            "atlas-agent-local-validate",
            "atlas-agent-deployed-validate",
            "atlas-agent-worker",
            "atlas-agent-cycle-summary",
            "atlas-agent-role-codex",
            "atlas-agent-role-fake-codex",
            "atlas-agent-role-runner",
            "atlas-agent-workflow-lint",
            "atlas-agent-workflow-select",
            "atlas-agent-workflow-template-add",
            "atlas-agent-work-item-add",
            "atlas-agent-work-item-inspect",
            "atlas-agent-work-item-requeue-stale",
            "atlas-agent-throttle-status",
            "atlas-agent-project-sync",
            "atlas_agent_common.py",
            "atlas_work_items.py",
            "atlas_workflows.py",
        ):
            self.assertEqual(
                (ROOT / relative).read_bytes(),
                (TEMPLATE_ROOT / relative).read_bytes(),
                f"{relative} should be synced into the durable runtime template",
            )

    def test_durable_template_contains_local_validation_example(self) -> None:
        source = ROOT / "local-validation.json"
        expected = (TEMPLATE_ROOT / "config" / "local-validation.example.json").read_text(encoding="utf-8")
        if source.exists() and source.read_text(encoding="utf-8") != expected:
            self.skipTest("installed runtime has customized local-validation.json")
        if not source.exists():
            source = ROOT / "config" / "local-validation.example.json"
        self.assertEqual(
            source.read_text(encoding="utf-8"),
            expected,
        )

    def test_local_validation_supports_legacy_command_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "local-validation.json"
            path.write_text(json.dumps({"owner/repo": ["npm test"]}), encoding="utf-8")

            commands = self.local_validate.configured_commands("owner/repo", str(path))

        self.assertEqual(commands, ["npm test"])

    def test_local_validation_runs_install_commands_before_targeted_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "local-validation.json"
            path.write_text(
                json.dumps(
                    {
                        "owner/repo": {
                            "install_commands": ["npm ci"],
                            "commands": ["npm test -- --run", "npm run build"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            commands = self.local_validate.configured_commands("owner/repo", str(path))

        self.assertEqual(commands, ["npm ci", "npm test -- --run", "npm run build"])

    def test_durable_template_contains_deployed_validation_example(self) -> None:
        source = ROOT / "deployed-validation.json"
        expected = (TEMPLATE_ROOT / "config" / "deployed-validation.example.json").read_text(encoding="utf-8")
        if source.exists() and source.read_text(encoding="utf-8") != expected:
            self.skipTest("installed runtime has customized deployed-validation.json")
        if not source.exists():
            source = ROOT / "config" / "deployed-validation.example.json"
        self.assertEqual(
            source.read_text(encoding="utf-8"),
            expected,
        )

    def test_deployed_validation_example_uses_supported_schema(self) -> None:
        entry = self.deployed_validate.config_entry(
            "OWNER/REPO",
            str(ROOT / "config" / "deployed-validation.example.json"),
        )

        self.assertEqual(
            self.deployed_validate.configured_install_commands(entry),
            ["python3 -m pip install -r requirements-dev.txt"],
        )
        self.assertEqual(self.deployed_validate.configured_commands(entry), ["python3 -m pytest tests/deployed"])
        workflows = self.deployed_validate.configured_workflows(entry)
        self.assertEqual(len(workflows), 1)
        self.assertEqual(workflows[0]["workflow"], "deployed-validation.yml")
        self.assertEqual(entry["env"], {"DEPLOYED_VALIDATION_DRY_RUN": "true"})

    def test_deployed_validation_supports_install_commands(self) -> None:
        entry = {"install_commands": ["npm ci"], "commands": ["npm run build"]}

        self.assertEqual(self.deployed_validate.configured_install_commands(entry), ["npm ci"])
        self.assertEqual(self.deployed_validate.configured_commands(entry), ["npm run build"])

    def test_cleanup_selects_stale_checkout_beyond_keep_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "jobs"
            repo_checkouts = jobs / "checkouts" / "owner__repo"
            old = repo_checkouts / "issue-1-old"
            new = repo_checkouts / "issue-2-new"
            old.mkdir(parents=True)
            new.mkdir()
            now = time.time()
            os.utime(old, (now - 4 * 3600, now - 4 * 3600))
            os.utime(new, (now, now))
            args = types.SimpleNamespace(
                active_job_hours=12,
                checkout_max_age_hours=24,
                keep_checkouts_per_repo=1,
                protect_recent_hours=0,
            )

            with mock.patch.dict(os.environ, {"AGENT_JOBS": str(jobs)}, clear=False):
                candidates = self.cleanup.checkout_candidates(args, now)

        self.assertEqual([candidate.path.name for candidate in candidates], ["issue-1-old"])
        self.assertEqual(candidates[0].reason, "exceeds per-repo checkout keep count")

    def test_cleanup_protects_recent_job_worktree_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "jobs"
            worktree = jobs / "checkouts" / "owner__repo" / "issue-1-old"
            worktree.mkdir(parents=True)
            job = jobs / "issue-1-20260101T000000Z"
            job.mkdir()
            (job / "worktree.txt").write_text(str(worktree) + "\n", encoding="utf-8")
            now = time.time()
            os.utime(worktree, (now - 4 * 3600, now - 4 * 3600))
            args = types.SimpleNamespace(
                active_job_hours=12,
                checkout_max_age_hours=1,
                keep_checkouts_per_repo=0,
                protect_recent_hours=0,
            )

            with mock.patch.dict(os.environ, {"AGENT_JOBS": str(jobs)}, clear=False):
                candidates = self.cleanup.checkout_candidates(args, now)

        self.assertEqual(candidates, [])

    def test_unattended_cleanup_command_respects_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            chain_dir = Path(tmp)
            args = types.SimpleNamespace(
                cleanup_measure_size=True,
                cleanup_max_delete=3,
                cleanup_target=["checkouts"],
                cleanup_mode="apply",
                dry_run=True,
            )

            command = self.unattended.build_cleanup_command(args, chain_dir, "chain", 2)

        self.assertNotIn("--apply", command.args)
        self.assertIn("--measure-size", command.args)
        self.assertIn("--target", command.args)
        self.assertIn("checkouts", command.args)
        self.assertEqual(command.summary_file, chain_dir / "cleanup-cycle-2.json")

    def test_unattended_cleanup_command_can_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            chain_dir = Path(tmp)
            args = types.SimpleNamespace(
                cleanup_measure_size=False,
                cleanup_max_delete=None,
                cleanup_target=[],
                cleanup_mode="apply",
                dry_run=False,
            )

            command = self.unattended.build_cleanup_command(args, chain_dir, "chain", 1)

        self.assertIn("--apply", command.args)
        self.assertEqual(command.name, "cleanup-apply")


if __name__ == "__main__":
    unittest.main()
