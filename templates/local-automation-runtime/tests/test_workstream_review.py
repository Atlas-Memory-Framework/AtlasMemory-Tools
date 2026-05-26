from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import tempfile
import types
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


class WorkstreamReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.review = load_script("template_workstream_review", "atlas-agent-workstream-review")

    def test_prompt_requires_completion_review_categories(self) -> None:
        prompt = self.review.build_prompt(
            "owner/repo",
            {"number": 7, "title": "Parent", "state": "open", "body": "Parent body"},
            [],
            {},
            "none",
            "",
        )

        self.assertIn('"completion_review"', prompt)
        self.assertIn('"semantic_correctness"', prompt)
        self.assertIn('"garbage_collection"', prompt)
        self.assertIn('"documentation_updates"', prompt)
        self.assertIn('"validation_evidence"', prompt)
        self.assertIn('"downstream_readiness"', prompt)
        self.assertIn("stale artifacts, obsolete branches/files/config, generated junk, and duplicate authority", prompt)
        self.assertIn("exact validation commands and results", prompt)
        self.assertIn("downstream dependency promotion", prompt)
        self.assertIn('Set followup.completion_category to "semantic", "garbage-collection", or "documentation"', prompt)

    def test_old_pass_without_completion_review_needs_human(self) -> None:
        review = {
            "result": "pass",
            "summary": "Older shaped output.",
            "blocking_findings": [],
            "followups": [],
        }

        result = self.review.normalize_result(review)

        self.assertEqual(result, "needs-human")
        self.assertIn("Semantic correctness completion check was missing", "\n".join(review["blocking_findings"]))
        self.assertIn("downstream work remains blocked", review["summary"])

    def test_documentation_completion_pass_requires_rationale(self) -> None:
        review = {
            "completion_review": {
                "semantic_correctness": {"status": "pass", "rationale": "Parent intent satisfied."},
                "garbage_collection": {"status": "pass", "rationale": "No stale artifacts found."},
                "documentation_updates": {"status": "pass"},
                "validation_evidence": {"status": "pass", "rationale": "Validation commands recorded."},
                "downstream_readiness": {"status": "pass", "rationale": "No blockers remain."},
            }
        }

        checks = self.review.completion_review(review)

        self.assertEqual(checks["documentation_updates"]["status"], "missing")
        self.assertIn("docs-not-needed rationale", checks["documentation_updates"]["rationale"])

    def test_create_followup_uses_parent_or_default_base_branch(self) -> None:
        captured_body = ""
        original_run = self.review.common.run
        original_jobs_dir = self.review.common.jobs_dir
        original_default_base = self.review.common.default_base_branch
        original_ensure_labels = self.review.common.ensure_labels_cached
        self.review.common.default_base_branch = lambda _repo: "main"
        self.review.common.ensure_labels_cached = lambda *_args, **_kwargs: None

        with tempfile.TemporaryDirectory() as tmp:
            self.review.common.jobs_dir = lambda: Path(tmp)

            def fake_run(args, **_kwargs):
                nonlocal captured_body
                body_path = Path(args[args.index("--body-file") + 1])
                captured_body = body_path.read_text(encoding="utf-8")
                return types.SimpleNamespace(stdout="https://github.com/owner/repo/issues/42\n")

            self.review.common.run = fake_run
            try:
                url = self.review.create_followup(
                    "owner/repo",
                    {
                        "number": 7,
                        "body": "",
                        "url": "https://github.com/owner/repo/issues/7",
                        "labels": [{"name": "workstream:ws1"}],
                    },
                    {
                        "title": "Follow up",
                        "body": "Fix the remaining edge case.",
                        "write_scope": ["src/workflow.py"],
                        "ready": True,
                    },
                    None,
                )
            finally:
                self.review.common.run = original_run
                self.review.common.jobs_dir = original_jobs_dir
                self.review.common.default_base_branch = original_default_base
                self.review.common.ensure_labels_cached = original_ensure_labels

        self.assertEqual(url, "https://github.com/owner/repo/issues/42")
        self.assertIn("- Base branch: `main`", captured_body)
        self.assertNotIn("- Base branch: `mat`", captured_body)

    def test_create_followup_includes_completion_category_metadata(self) -> None:
        captured_body = ""
        original_run = self.review.common.run
        original_jobs_dir = self.review.common.jobs_dir
        original_default_base = self.review.common.default_base_branch
        original_ensure_labels = self.review.common.ensure_labels_cached
        self.review.common.default_base_branch = lambda _repo: "main"
        self.review.common.ensure_labels_cached = lambda *_args, **_kwargs: None

        with tempfile.TemporaryDirectory() as tmp:
            self.review.common.jobs_dir = lambda: Path(tmp)

            def fake_run(args, **_kwargs):
                nonlocal captured_body
                body_path = Path(args[args.index("--body-file") + 1])
                captured_body = body_path.read_text(encoding="utf-8")
                return types.SimpleNamespace(stdout="https://github.com/owner/repo/issues/43\n")

            self.review.common.run = fake_run
            try:
                url = self.review.create_followup(
                    "owner/repo",
                    {
                        "number": 7,
                        "body": "",
                        "url": "https://github.com/owner/repo/issues/7",
                        "labels": [{"name": "workstream:ws1"}],
                    },
                    {
                        "title": "Document operator handoff",
                        "body": "Update the operator-facing notes for the completed workflow.",
                        "write_scope": ["README.md"],
                        "completion_category": "documentation_updates",
                        "ready": True,
                    },
                    None,
                )
            finally:
                self.review.common.run = original_run
                self.review.common.jobs_dir = original_jobs_dir
                self.review.common.default_base_branch = original_default_base
                self.review.common.ensure_labels_cached = original_ensure_labels

        self.assertEqual(url, "https://github.com/owner/repo/issues/43")
        self.assertIn("- Completion category: `documentation`", captured_body)
        self.assertIn("## Completion Review Follow-up", captured_body)
        self.assertIn("- Category: `documentation`", captured_body)
        self.assertIn("Resolve this category before downstream workstream dependencies are unblocked.", captured_body)

    def test_cross_repo_followup_is_not_auto_ready(self) -> None:
        captured_body = ""
        original_run = self.review.common.run
        original_jobs_dir = self.review.common.jobs_dir
        original_default_base = self.review.common.default_base_branch
        original_ensure_labels = self.review.common.ensure_labels_cached
        self.review.common.default_base_branch = lambda _repo: "main"
        self.review.common.ensure_labels_cached = lambda *_args, **_kwargs: None

        with tempfile.TemporaryDirectory() as tmp:
            self.review.common.jobs_dir = lambda: Path(tmp)

            def fake_run(args, **_kwargs):
                nonlocal captured_body
                body_path = Path(args[args.index("--body-file") + 1])
                captured_body = body_path.read_text(encoding="utf-8")
                return types.SimpleNamespace(stdout="https://github.com/owner/source/issues/44\n")

            self.review.common.run = fake_run
            try:
                self.review.create_followup(
                    "owner/source",
                    {
                        "number": 7,
                        "body": "- Target repo(s): `owner/target`\n- Execution repo: `owner/source`",
                        "url": "https://github.com/owner/source/issues/7",
                        "labels": [{"name": "workstream:ws1"}],
                    },
                    {
                        "title": "Follow up",
                        "body": "Fix the target repo item.",
                        "write_scope": ["target/src/file.ts"],
                        "ready": True,
                    },
                    None,
                )
            finally:
                self.review.common.run = original_run
                self.review.common.jobs_dir = original_jobs_dir
                self.review.common.default_base_branch = original_default_base
                self.review.common.ensure_labels_cached = original_ensure_labels

        self.assertIn("- Issue ready: `false`", captured_body)
        self.assertIn("- Dispatch mode: `blocked`", captured_body)
        self.assertIn("- Target repo(s): `owner/target`", captured_body)
        self.assertIn("- Manual gates remaining: `cross-repo mirror required`", captured_body)

    def test_linked_pr_refs_include_comment_pr_urls(self) -> None:
        issue = {
            "body": "",
            "comments": [
                {"body": "Implemented by https://github.com/owner/ui/pull/7."},
                {"body": "Duplicate mention https://github.com/owner/ui/pull/7 and https://github.com/owner/api/pull/8"},
            ],
        }

        self.assertEqual(self.review.linked_pr_refs(issue), [("owner/ui", 7), ("owner/api", 8)])

    def test_repo_relative_path_strips_target_repo_name_prefix(self) -> None:
        self.assertEqual(self.review.repo_relative_path("owner/Atlas-Memory-UI", "Atlas-Memory-UI/src/api/intake.ts"), "src/api/intake.ts")
        self.assertEqual(self.review.repo_relative_path("owner/Atlas-Memory-UI", "src/api/intake.ts"), "src/api/intake.ts")

    def test_child_issues_excludes_workstream_followups(self) -> None:
        original_gh_json_or_none = self.review.common.gh_json_or_none
        original_issue_json = self.review.issue_json
        self.review.common.gh_json_or_none = lambda *_args, **_kwargs: [
            {"number": 8, "labels": [{"name": "workstream:ws1"}]},
            {"number": 9, "labels": [{"name": "workstream:ws1"}, {"name": "agent:workstream-followup"}]},
        ]
        self.review.issue_json = lambda _repo, number: {"number": number, "labels": [{"name": "workstream:ws1"}]}
        try:
            children = self.review.child_issues(
                "owner/repo",
                {"number": 7, "labels": [{"name": "workstream:ws1"}]},
            )
        finally:
            self.review.common.gh_json_or_none = original_gh_json_or_none
            self.review.issue_json = original_issue_json

        self.assertEqual([child["number"] for child in children], [8])

    def test_cross_repo_pr_collection_uses_explicit_linked_prs_only(self) -> None:
        calls = []
        original_gh_json_or_none = self.review.common.gh_json_or_none
        self.review.common.gh_json_or_none = lambda args, **_kwargs: calls.append(args) or {
            "number": 7,
            "title": "Target PR",
            "url": "https://github.com/owner/target/pull/7",
        }
        try:
            rows = self.review.prs_for_issue(
                "owner/source",
                {
                    "number": 106,
                    "body": "- Target repo(s): `owner/target`",
                    "comments": [{"body": "Merged via https://github.com/owner/target/pull/7"}],
                },
            )
        finally:
            self.review.common.gh_json_or_none = original_gh_json_or_none

        self.assertEqual(rows[0]["repository"], "owner/target")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ["pr", "view", "7"])

    def test_completed_by_pr_collection_skips_pr_search(self) -> None:
        calls = []
        original_gh_json_or_none = self.review.common.gh_json_or_none

        def fake_gh_json_or_none(args, **_kwargs):
            calls.append(args)
            if args[:2] == ["pr", "list"]:
                raise AssertionError("broad PR search should not run")
            return {
                "number": 7,
                "title": "Target PR",
                "url": "https://github.com/owner/repo/pull/7",
            }

        self.review.common.gh_json_or_none = fake_gh_json_or_none
        try:
            rows = self.review.prs_for_issue(
                "owner/repo",
                {
                    "number": 106,
                    "body": "- Completion mode: `merge-group`\n- Completed by: https://github.com/owner/repo/pull/7",
                },
            )
        finally:
            self.review.common.gh_json_or_none = original_gh_json_or_none

        self.assertEqual(rows[0]["repository"], "owner/repo")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ["pr", "view", "7"])

    def test_prompt_includes_completion_evidence(self) -> None:
        prompt = self.review.build_prompt(
            "owner/repo",
            {"number": 1, "title": "Parent", "body": ""},
            [
                {
                    "number": 2,
                    "title": "Child",
                    "body": "- Completion mode: `mirror-pr`\n- Completed by: https://github.com/owner/ui/pull/9",
                    "comments": [],
                }
            ],
            {2: []},
            "",
            "",
        )

        self.assertIn('"completion_mode": "mirror-pr"', prompt)
        self.assertIn('"completed_by": [', prompt)
        self.assertIn('"owner/ui#9"', prompt)


if __name__ == "__main__":
    unittest.main()
