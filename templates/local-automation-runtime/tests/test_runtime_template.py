from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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

            summary = self.cycle.summarize(chain_dir, 1)

        self.assertEqual(summary["build"]["ok"], 1)
        self.assertEqual(summary["build"]["failed"], 1)
        self.assertEqual(summary["finalizer"]["counts"]["blocked"], 1)
        self.assertEqual(summary["finalizer"]["counts"]["merge"], 1)

    def test_plan_queue_blocks_children_with_dependencies(self) -> None:
        child = {
            "labels": ["status:ready"],
            "dispatch_recommendation": "auto-dispatch",
            "dependencies": ["owner/repo#1"],
        }

        self.assertIn("dependencies: owner/repo#1", self.bridge.child_blockers(child))

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


if __name__ == "__main__":
    unittest.main()
