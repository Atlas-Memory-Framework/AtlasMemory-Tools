from __future__ import annotations

import importlib.machinery
import importlib.util
import argparse
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

    def test_classify_reports_dispatch_blockers_separately_from_decomposition(self) -> None:
        record = self.decompose.classify_issue(
            "owner/repo",
            issue(
                body="""Points: 3
Dispatch recommendation: `tracking-only`
Open dependencies: `#12`
Manual gates remaining: `none`
""",
                labels=["status:ready"],
            ),
        )

        self.assertEqual(record["action"], "decompose")
        self.assertEqual(record["dispatch_blockers"], ["open-dependencies", "dispatch-recommendation:tracking-only"])
        self.assertFalse(record["dispatchable_after_decomposition"])

    def test_run_filters_label_scan_to_project_issues(self) -> None:
        originals = {
            "target_repos": self.decompose.target_repos,
            "candidate_issues_for_labels": self.decompose.candidate_issues_for_labels,
            "project_targets": self.decompose.project_targets,
            "project_items": self.decompose.common.project_items,
        }
        self.decompose.target_repos = lambda _path: ["owner/repo"]
        self.decompose.candidate_issues_for_labels = lambda _repo, _labels, _limit: [
            issue(number=3, labels=["points:5"]),
            issue(number=74, labels=["points:3"]),
        ]
        self.decompose.project_targets = lambda _path: [("owner", 1)]
        self.decompose.common.project_items = lambda _owner, _number: [
            {"content": {"repository": "owner/repo", "number": 74}}
        ]
        try:
            result = self.decompose.run(
                argparse.Namespace(
                    repos_file=None,
                    candidate_label=["status:ready"],
                    issue=[],
                    max=10,
                    projects_file="projects.txt",
                    apply=False,
                )
            )
        finally:
            for name, value in originals.items():
                if name == "project_items":
                    setattr(self.decompose.common, name, value)
                else:
                    setattr(self.decompose, name, value)

        self.assertEqual([record["number"] for record in result["records"]], [74])

    def test_project_issue_keys_can_use_snapshot_without_project_api(self) -> None:
        original_project_items = self.decompose.common.project_items
        self.decompose.common.project_items = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("project API should not be called")
        )
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "project.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "items": [
                            {"content": {"repository": "owner/repo", "number": 74}},
                            {"content": {"repository": "owner/other", "number": 2}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            try:
                keys = self.decompose.project_issue_keys(None, str(snapshot))
            finally:
                self.decompose.common.project_items = original_project_items

        self.assertEqual(keys, {("owner/repo", 74), ("owner/other", 2)})

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
            ["agent:one-point", "points:1", "status:blocked", "type:story"],
        )
        body = self.decompose.child_body(parent, "owner/repo", child)
        self.assertIn("- Open dependencies: `#7; #9`", body)
        self.assertIn("- Dispatch recommendation: `dependency-gated`", body)

    def test_planning_prompt_uses_blocked_child_status_for_gated_parent(self) -> None:
        prompt = self.decompose.planning_prompt(
            issue(
                body="""Points: 3
Open dependencies: `#7`
Manual gates remaining: `none`
""",
                labels=["status:ready"],
            ),
            4,
        )

        self.assertIn("`status:blocked`", prompt)
        self.assertIn("children must remain blocked until gates clear", prompt)

    def test_child_labels_inherit_parent_project_routing_metadata(self) -> None:
        parent = issue(
            body="""## Execution State
- Open dependencies: `none`
- Manual gates remaining: `none`
""",
            labels=[
                "points:5",
                "status:ready",
                "agent:decomposition-required",
                "area:core",
                "owner:runtime",
                "repo:atlas-memory",
                "tier:t0",
                "type:story",
                "workstream:ws2-runtime-safety",
                "priority:p1",
            ],
        )
        child = {"body": "Scope: update one file.", "labels": ["points:7", "status:ready"]}

        labels = self.decompose.child_labels(parent, child)

        self.assertIn("area:core", labels)
        self.assertIn("owner:runtime", labels)
        self.assertIn("repo:atlas-memory", labels)
        self.assertIn("tier:t0", labels)
        self.assertIn("type:story", labels)
        self.assertIn("workstream:ws2-runtime-safety", labels)
        self.assertIn("priority:p1", labels)
        self.assertIn("points:1", labels)
        self.assertIn("status:ready", labels)
        self.assertNotIn("points:5", labels)
        self.assertNotIn("points:7", labels)
        self.assertNotIn("agent:decomposition-required", labels)

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

    def test_child_body_inherits_parent_project_metadata(self) -> None:
        parent = issue(
            number=5,
            body="""## Source Plan
- Plan key: `PLAN-1`
- Source section: `Automation Issue Manifest` / `WS2-QUOTE`

## Automation Manifest Metadata
- Suggested points: `5`
- Risk tags: `needs-ci-validation, migration`
- Highest tier: `T0`
- Priority: `P1`
- Validation scope: `ci`
- Target repo(s): `owner/repo`
- Execution repo: `owner/repo`
- Base branch: `main`

## Execution State
- Open dependencies: `none`
- Manual gates remaining: `none`

## Named Gates
- G-BACKEND-BUILD

## Parent Epic
https://github.com/owner/repo/issues/1
""",
            labels=["points:5", "tier:t0"],
        )
        child = {"body": "Scope: server/src/app.py", "labels": ["points:1"]}

        body = self.decompose.child_body(parent, "owner/repo", child)

        self.assertIn("## Source Plan\n- Plan key: `PLAN-1`", body)
        self.assertIn("- Risk tags: `needs-ci-validation, migration`", body)
        self.assertIn("- Highest tier: `T0`", body)
        self.assertIn("- Priority: `P1`", body)
        self.assertIn("## Named Gates\n- G-BACKEND-BUILD", body)
        self.assertIn("## Parent Epic\nhttps://github.com/owner/repo/issues/1", body)
        self.assertIn("Parent issue: #5", body)

    def test_child_body_uses_first_scalar_routing_metadata(self) -> None:
        parent = issue(
            number=5,
            body="""## Source Plan
- Execution repo: `owner/repo`

## Automation Manifest Metadata
- Target repo(s): `owner/repo`
- Execution repo: `owner/repo`
- Validation scope: `ci`

## Execution State
- Open dependencies: `none`
- Manual gates remaining: `none`
""",
            labels=["points:5"],
        )
        child = {"body": "Scope: server/src/app.py", "labels": ["points:1"]}

        body = self.decompose.child_body(parent, "owner/repo", child)

        self.assertIn("- Execution repo: `owner/repo`", body)
        self.assertNotIn("- Execution repo: `owner/repo; owner/repo`", body)

    def test_child_body_includes_scheduler_metadata(self) -> None:
        parent = issue(
            body="""## Automation Manifest Metadata
- Highest tier: `T0`
- Depends on: `CORE-001`
- Blocks: `UI-002`
- Parallel group: `pg-ui-contract`
- Critical path rank: `3`
- Merge group: `mg-contract`
- Combine policy: `one-issue-one-pr`
- Conflict class: `src-api`
- Validation tier: `T0`

## Execution State
- Open dependencies: `none`
- Manual gates remaining: `none`
""",
            labels=["points:5"],
        )
        child = {"body": "Scope: src/api/workflows.ts", "labels": ["points:1"]}

        body = self.decompose.child_body(parent, "owner/repo", child)

        self.assertIn("- Depends on: `CORE-001`", body)
        self.assertIn("- Blocks: `UI-002`", body)
        self.assertIn("- Parallel group: `pg-ui-contract`", body)
        self.assertIn("- Critical path rank: `3`", body)
        self.assertIn("- Merge group: `mg-contract`", body)
        self.assertIn("- Combine policy: `one-issue-one-pr`", body)
        self.assertIn("- Conflict class: `src-api`", body)
        self.assertIn("- Validation tier: `T0`", body)

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

    def test_run_can_target_explicit_issue_refs_without_label_scan(self) -> None:
        original_fetch = self.decompose.fetch_issue
        original_candidates = self.decompose.candidate_issues_for_labels
        self.decompose.fetch_issue = lambda repo, number: issue(body="Points: 3", number=number) if repo == "owner/repo" else None
        self.decompose.candidate_issues_for_labels = lambda *_args, **_kwargs: self.fail("label scan should be bypassed")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                repos = Path(tmp) / "repos.txt"
                repos.write_text("owner/repo\n", encoding="utf-8")
                args = self.decompose.build_parser().parse_args(
                    ["--repos-file", str(repos), "--issue", "7", "--issue", "owner/repo#8", "--dry-run"]
                )
                payload = self.decompose.run(args)
        finally:
            self.decompose.fetch_issue = original_fetch
            self.decompose.candidate_issues_for_labels = original_candidates

        self.assertEqual([record["number"] for record in payload["records"]], [7, 8])
        self.assertEqual(payload["counts"], {"decompose": 2})

    def test_run_mixed_explicit_issue_refs_do_not_apply_unqualified_refs_to_extra_repos(self) -> None:
        fetched: list[tuple[str, int]] = []
        original_fetch = self.decompose.fetch_issue
        original_candidates = self.decompose.candidate_issues_for_labels

        def fetch(repo, number):
            fetched.append((repo, number))
            return issue(body="Points: 3", number=number)

        self.decompose.fetch_issue = fetch
        self.decompose.candidate_issues_for_labels = lambda *_args, **_kwargs: self.fail("label scan should be bypassed")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                repos = Path(tmp) / "repos.txt"
                repos.write_text("owner/repo\n", encoding="utf-8")
                args = self.decompose.build_parser().parse_args(
                    ["--repos-file", str(repos), "--issue", "7", "--issue", "other/repo#8", "--dry-run"]
                )
                payload = self.decompose.run(args)
        finally:
            self.decompose.fetch_issue = original_fetch
            self.decompose.candidate_issues_for_labels = original_candidates

        self.assertEqual(fetched, [("owner/repo", 7), ("other/repo", 8)])
        self.assertEqual([(record["repo"], record["number"]) for record in payload["records"]], [("owner/repo", 7), ("other/repo", 8)])


if __name__ == "__main__":
    unittest.main()
