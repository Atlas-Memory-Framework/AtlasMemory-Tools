from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


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
            "atlas-agent-issue-decompose",
            "atlas-agent-reconcile",
            "atlas-agent-project-reconcile",
            "atlas-agent-review",
            "atlas-agent-semantic-review",
            "atlas-agent-finalize",
            "atlas-agent-local-validate",
            "atlas-agent-deployed-validate",
            "atlas-agent-worker",
            "atlas-agent-cycle-summary",
            "atlas_agent_common.py",
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


if __name__ == "__main__":
    unittest.main()
