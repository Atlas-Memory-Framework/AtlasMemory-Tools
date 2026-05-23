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

    def test_create_followup_uses_parent_or_default_base_branch(self) -> None:
        captured_body = ""
        original_run = self.review.common.run
        original_jobs_dir = self.review.common.jobs_dir
        original_default_base = self.review.common.default_base_branch
        self.review.common.default_base_branch = lambda _repo: "main"

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

        self.assertEqual(url, "https://github.com/owner/repo/issues/42")
        self.assertIn("- Base branch: `main`", captured_body)
        self.assertNotIn("- Base branch: `mat`", captured_body)


if __name__ == "__main__":
    unittest.main()
