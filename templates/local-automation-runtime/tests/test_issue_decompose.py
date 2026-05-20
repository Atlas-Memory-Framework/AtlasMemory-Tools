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

    def test_classify_decomposes_agent_one_point_with_oversized_body_points(self) -> None:
        record = self.decompose.classify_issue(
            "owner/repo",
            issue(labels=["agent:one-point"], body="Points: 5"),
        )

        self.assertEqual(record["action"], "decompose")
        self.assertEqual(record["points"], 5)

    def test_classify_decomposes_conflicting_point_metadata(self) -> None:
        record = self.decompose.classify_issue(
            "owner/repo",
            issue(labels=["points:1", "points:5"]),
        )

        self.assertEqual(record["action"], "decompose")
        self.assertEqual(record["reason"], "conflicting point metadata")
        self.assertEqual(record["point_values"], [1, 5])

    def test_extract_json_object_handles_repeated_planner_json(self) -> None:
        raw = (
            "thinking\n"
            '{"children":[{"title":"A","body":"B","labels":["points:1"]}],"notes":[]}\n'
            "tokens used\n"
            '{"children":[{"title":"A","body":"B","labels":["points:1"]}],"notes":[]}\n'
        )

        payload = self.decompose.extract_json_object(raw)

        self.assertEqual(payload["children"][0]["title"], "A")

    def test_extract_json_object_skips_prompt_schema_example(self) -> None:
        raw = (
            'Schema: {"children":[{"title":"...","body":"...","labels":["points:1"]}],"notes":["..."]}\n'
            "codex\n"
            '{"children":[{"title":"Add env docs","body":"Scope: docs.","labels":["points:1"]}],"notes":[]}\n'
        )

        payload = self.decompose.extract_json_object(raw)

        self.assertEqual(payload["children"][0]["title"], "Add env docs")

    def test_child_issue_inherits_parent_dependency_gate(self) -> None:
        parent = issue(
            body="""## Execution State
- Open dependencies: `#7; #9`
- Manual gates remaining: `none`
""",
            labels=["points:5"],
        )
        child = {"body": "Scope: update one file.", "labels": ["points:1", "status:ready", "agent:ready"]}

        self.assertEqual(
            self.decompose.child_labels(parent, child),
            ["agent:one-point", "points:1", "status:blocked"],
        )
        body = self.decompose.child_body(parent, "owner/repo", child)
        self.assertIn("- Open dependencies: `#7; #9`", body)
        self.assertIn("- Dispatch recommendation: `dependency-gated`", body)

    def test_child_body_infers_canonical_scope_and_validation_sections(self) -> None:
        parent = issue(
            body="""## Execution State
- Open dependencies: `none`
- Manual gates remaining: `none`
""",
            labels=["points:5"],
        )
        child = {
            "body": """Parent: #13
Scope: package.json only

Validation:
- Run npm test
- Confirm git diff is limited
""",
            "labels": ["points:1", "status:ready"],
        }

        body = self.decompose.child_body(parent, "owner/repo", child)

        self.assertIn("## Write Scope\n- `package.json`", body)
        self.assertIn("## Validation Commands\n- Run npm test\n- Confirm git diff is limited", body)

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

    def test_run_scans_multiple_candidate_labels_without_duplicates(self) -> None:
        calls: list[str] = []
        original_candidates = self.decompose.candidate_issues

        def candidates(_repo, label, _limit):
            calls.append(label)
            if label == "status:ready":
                return [issue(labels=["points:1"], number=1)]
            if label == "status:draft":
                return [issue(body="Points: 5", number=2), issue(labels=["points:1"], number=1)]
            return []

        self.decompose.candidate_issues = candidates
        try:
            with tempfile.TemporaryDirectory() as tmp:
                repos = Path(tmp) / "repos.txt"
                repos.write_text("owner/repo\n", encoding="utf-8")
                args = self.decompose.build_parser().parse_args(
                    [
                        "--repos-file",
                        str(repos),
                        "--candidate-label",
                        "status:ready",
                        "--candidate-label",
                        "status:draft",
                        "--dry-run",
                    ]
                )
                payload = self.decompose.run(args)
        finally:
            self.decompose.candidate_issues = original_candidates

        self.assertEqual(calls, ["status:ready", "status:draft"])
        self.assertEqual(payload["counts"], {"mark-one-point": 1, "decompose": 1})


if __name__ == "__main__":
    unittest.main()
