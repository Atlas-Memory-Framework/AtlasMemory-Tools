from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "plan-to-html" / "scripts" / "plan_to_html.py"


spec = importlib.util.spec_from_file_location("plan_to_html", SCRIPT)
assert spec and spec.loader
plan_to_html = importlib.util.module_from_spec(spec)
sys.modules["plan_to_html"] = plan_to_html
spec.loader.exec_module(plan_to_html)


SAMPLE_PLAN = """# Feature: Render Plans

## Plan State
Status: Approved
CurrentStage: Reviews
PlanTier: Full
AutomationTarget: none
LastUpdated: 2026-05-21
PrimaryOwner: mat
NextRequiredUserAction: none

## Gate Results
ProblemDefinitionComplete: Pass
FeatureClarity: Pass
TechnicalClarity: Pass
PlanReadiness: Pass
AutomationReadiness: N/A
PlanningReviewsComplete: Fail

## Implementation Plan
<!-- owner: implementation-planning -->
- WS1: Renderer
  - [x] Convert headings
  - [ ] Escape raw HTML

```python
print("<safe>")
```

| Area | Status |
| --- | ---: |
| HTML | ready |

<script>alert("xss")</script>
"""


class PlanToHtmlTests(unittest.TestCase):
    def test_artifact_view_is_default_shape(self) -> None:
        rendered = plan_to_html.convert_plan_artifact(SAMPLE_PLAN, source_path=Path("plan.md"))

        self.assertIn("Plan Artifact Map", rendered)
        self.assertIn('class="artifact-map"', rendered)
        self.assertIn('class="tree-view"', rendered)
        self.assertIn('data-view-mode="tree"', rendered)
        self.assertIn('class="graph-viewport"', rendered)
        self.assertIn('data-zoom-action="fit-width"', rendered)
        self.assertIn('data-edge-mode="none"', rendered)
        self.assertIn('data-edge-mode="selected"', rendered)
        self.assertIn("Focus lines", rendered)
        self.assertIn('"id": "gate-planningreviewscomplete"', rendered)
        self.assertIn('"id": "workstream-ws1"', rendered)
        self.assertIn("Pick an artifact", rendered)
        self.assertIn("&lt;script&gt;alert", rendered)
        self.assertNotIn("<script>alert", rendered)

    def test_extracts_summary_and_escapes_raw_html(self) -> None:
        rendered = plan_to_html.convert_plan_markdown(SAMPLE_PLAN, source_path=Path("plan.md"))

        self.assertIn("Plan Summary", rendered)
        self.assertIn("Status</dt><dd><span class=\"summary-value summary-pass\">Approved</span>", rendered)
        self.assertIn("PlanningReviewsComplete", rendered)
        self.assertIn("gate-fail", rendered)
        self.assertIn("&lt;script&gt;alert", rendered)
        self.assertNotIn("<script>alert", rendered)
        self.assertNotIn("owner: implementation-planning", rendered)

    def test_renders_plan_markdown_features(self) -> None:
        rendered = plan_to_html.convert_plan_markdown(SAMPLE_PLAN, source_path=Path("plan.md"))

        self.assertIn('id="implementation-plan"', rendered)
        self.assertIn('href="#implementation-plan"', rendered)
        self.assertIn('type="checkbox" disabled aria-label="completed task" checked', rendered)
        self.assertIn('type="checkbox" disabled aria-label="open task"', rendered)
        self.assertIn('<pre><code class="language-python">print("&lt;safe&gt;")</code></pre>', rendered)
        self.assertIn("<table>", rendered)
        self.assertIn('<td class="align-right">ready</td>', rendered)

    def test_cli_writes_artifact_view_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "sample-plan.md"
            plan.write_text(SAMPLE_PLAN, encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(plan)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            output = plan.with_suffix(".html")
            self.assertTrue(output.is_file())
            self.assertIn(f"wrote {output}", result.stdout)
            self.assertIn("Plan Artifact Map", output.read_text(encoding="utf-8"))

    def test_cli_keeps_document_view_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "sample-plan.md"
            plan.write_text(SAMPLE_PLAN, encoding="utf-8")
            output = Path(tmp) / "document.html"

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(plan), "--view", "document", "--output", str(output)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            text = output.read_text(encoding="utf-8")
            self.assertIn("Plan Review Artifact", text)
            self.assertNotIn("Plan Artifact Map", text)


if __name__ == "__main__":
    unittest.main()
