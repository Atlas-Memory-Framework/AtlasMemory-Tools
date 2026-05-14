from __future__ import annotations

import importlib.machinery
import importlib.util
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


def issue(*, body: str = "", labels: list[str] | None = None, number: int = 7) -> dict:
    return {
        "number": number,
        "title": "Implement broad thing",
        "body": body,
        "labels": [{"name": label} for label in (labels or [])],
        "url": f"https://github.com/owner/repo/issues/{number}",
    }


class IssueDecomposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.decompose = load_script("atlas_agent_issue_decompose_test", "atlas-agent-issue-decompose")

    def test_point_parser_reads_labels_and_body_fields(self) -> None:
        self.assertEqual(self.decompose.issue_points(issue(labels=["points:1"])), 1)
        self.assertEqual(self.decompose.issue_points(issue(body="- Story points: `2`")), 2)
        self.assertEqual(self.decompose.issue_points(issue(body="Points: 5")), 5)
        self.assertIsNone(self.decompose.issue_points(issue(body="No estimate")))

    def test_classify_marks_one_point_and_decomposition_required(self) -> None:
        self.assertEqual(
            self.decompose.classify_issue("owner/repo", issue(labels=["points:1"]))["action"],
            "mark-one-point",
        )
        self.assertEqual(
            self.decompose.classify_issue("owner/repo", issue(body="Points: 5"))["action"],
            "decompose",
        )
        self.assertEqual(
            self.decompose.classify_issue("owner/repo", issue())["action"],
            "needs-points",
        )

    def test_dry_run_writes_summary_without_mutations(self) -> None:
        original_candidates = self.decompose.candidate_issues
        self.decompose.candidate_issues = lambda _repo, _label, _limit: [
            issue(labels=["points:1"], number=1),
            issue(body="Points: 3", number=2),
        ]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                repos = Path(tmp) / "repos.txt"
                repos.write_text("owner/repo\n", encoding="utf-8")
                summary = Path(tmp) / "summary.json"
                args = self.decompose.build_parser().parse_args(
                    ["--repos-file", str(repos), "--summary", str(summary), "--dry-run"]
                )
                payload = self.decompose.run(args)
                self.decompose.common.write_json(summary, payload)
                self.assertTrue(summary.exists())
        finally:
            self.decompose.candidate_issues = original_candidates

        self.assertEqual(payload["counts"], {"decompose": 1, "mark-one-point": 1})


if __name__ == "__main__":
    unittest.main()
