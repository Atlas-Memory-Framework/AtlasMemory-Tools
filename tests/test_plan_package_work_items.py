from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


COMPILE = load_module("compile_plan_package", ROOT / "skills/plan-package/scripts/compile_plan_package.py")
EXPORT = load_module("export_work_items", ROOT / "skills/plan-package/scripts/export_work_items.py")
ISSUE_SPEC = load_module("validate_issue_spec", ROOT / "skills/issue-spec/scripts/validate_issue_spec.py")


class PlanPackageWorkItemExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "plans").mkdir()
        (self.root / "specs").mkdir()
        (self.root / "skills/example/scripts").mkdir(parents=True)
        (self.root / "tests").mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_package(self, *, leaf_count: int = 2, tracking_only: set[int] | None = None) -> Path:
        tracking_only = tracking_only or set()
        plan = """# Feature: Plan Package Work Items

## Plan State
PlanId: plan-package-work-items

## Automation Issue Manifest
"""
        for number in range(1, leaf_count + 1):
            leaf_id = f"LEAF-{number:03d}"
            source_id = f"plan-package-work-items#{leaf_id}"
            dependency = "- none" if number == 1 else f"- plan-package-work-items#LEAF-{number - 1:03d}"
            spec = self.spec(
                source_id=source_id,
                manifest_leaf_id=leaf_id,
                dependencies=dependency,
                file_path=f"skills/example/scripts/leaf_{number:03d}.py",
                dispatch_mode="tracking-only" if number in tracking_only else "agent-ready",
            )
            spec_path = self.root / f"specs/leaf-{number:03d}.md"
            spec_path.write_text(spec, encoding="utf-8")
            manifest_dependency = "none" if number == 1 else f"plan-package-work-items#LEAF-{number - 1:03d}"
            plan += f"""- {leaf_id}: Export work item {number}
  - Spec path: specs/leaf-{number:03d}.md
  - Spec hash: {ISSUE_SPEC.canonical_spec_hash(spec)}
  - Dispatch: {"tracking-only" if number in tracking_only else "agent-ready"}
  - Depends on:
    - {manifest_dependency}
  - Files in scope:
    - `skills/example/scripts/leaf_{number:03d}.py`
  - Files out of scope:
    - `skills/example/scripts/other.py`
  - Required gates:
    - G-CI-LocalWorkItemExport
  - Validation:
    - python3 -m unittest tests.test_example
  - Acceptance criteria:
    - Example export passes.
  - One PR contract: yes
"""
        path = self.root / "plans/work-items.plan.md"
        path.write_text(plan, encoding="utf-8")
        return path

    def spec(
        self,
        *,
        source_id: str,
        manifest_leaf_id: str,
        dependencies: str,
        file_path: str,
        dispatch_mode: str = "agent-ready",
    ) -> str:
        return f"""# Issue Spec: {manifest_leaf_id}

SpecId: {manifest_leaf_id.lower()}-spec
SourceId: {source_id}
ParentPlanId: plan-package-work-items
ManifestLeafId: {manifest_leaf_id}
Dispatch mode: {dispatch_mode}
One PR contract: yes

## Intent
Implement {manifest_leaf_id}.

## Anti-scope
- Do not touch unrelated files.

## Files in scope
- `{file_path}`

## Files out of scope
- `skills/example/scripts/other.py`

## Dependencies
{dependencies}

## Required gates
- G-CI-LocalWorkItemExport

## Validation
- python3 -m unittest tests.test_example

## Acceptance criteria
- Example export passes.

## Depth contract
- Covers local work-item metadata export.

## Open decisions
- none
"""

    def compile_registry(self, *, leaf_count: int = 2) -> dict:
        return COMPILE.compile_registry(self.write_package(leaf_count=leaf_count), root=self.root)

    def test_exports_local_records_from_compiled_leaf_metadata(self) -> None:
        registry = self.compile_registry()
        store = EXPORT.export_work_items(registry)

        self.assertEqual(store["schema_version"], "plan-package-work-items.v0")
        self.assertEqual(store["source"]["kind"], "plan-package")
        self.assertEqual(store["source"]["package_hash"], registry["package_hash"])
        self.assertEqual(len(store["work_items"]), 2)

        second = store["work_items"][1]
        compiled_second = registry["leaves"][1]
        self.assertEqual(second["id"], "plan-package-work-items#LEAF-002")
        self.assertEqual(second["SourceId"], compiled_second["source_id"])
        self.assertEqual(second["SpecHash"], compiled_second["spec_hash"])
        self.assertEqual(second["depends_on"], ["plan-package-work-items#LEAF-001"])
        self.assertEqual(second["scheduler"]["depends_on"], ["plan-package-work-items#LEAF-001"])
        self.assertEqual(second["write_scope"], ["skills/example/scripts/leaf_002.py"])
        self.assertEqual(second["scheduler"]["write_scope"], ["skills/example/scripts/leaf_002.py"])
        self.assertEqual(second["validation"], ["python3 -m unittest tests.test_example"])
        self.assertEqual(second["dispatch_mode"], "agent-ready")
        self.assertEqual(second["scope_budget_status"], "pass")
        self.assertEqual(second["metadata"]["spec_hash"], compiled_second["spec_hash"])
        self.assertEqual(second["metadata"]["scope_budget"]["executable_leaf_count"], 2)

    def test_export_does_not_reparse_sidecar_specs(self) -> None:
        registry = self.compile_registry()
        (self.root / "specs/leaf-001.md").unlink()

        store = EXPORT.export_work_items(registry)

        first = store["work_items"][0]
        self.assertEqual(first["SourceId"], "plan-package-work-items#LEAF-001")
        self.assertEqual(first["SpecHash"], registry["leaves"][0]["spec_hash"])

    def test_tracking_only_leaves_are_not_exported_or_counted_executable(self) -> None:
        registry = COMPILE.compile_registry(
            self.write_package(leaf_count=3, tracking_only={2}),
            root=self.root,
        )

        store = EXPORT.export_work_items(registry)

        self.assertEqual(
            [item["SourceId"] for item in store["work_items"]],
            ["plan-package-work-items#LEAF-001", "plan-package-work-items#LEAF-003"],
        )
        self.assertEqual(store["source"]["scope_budget"]["executable_leaf_count"], 2)

    def test_scope_budget_status_warns_and_fails_from_compiled_leaf_count(self) -> None:
        warn_store = EXPORT.export_work_items(self.compile_registry(leaf_count=9))
        fail_store = EXPORT.export_work_items(self.compile_registry(leaf_count=13))

        self.assertEqual(warn_store["source"]["scope_budget"]["status"], "warn")
        self.assertTrue(all(item["scope_budget_status"] == "warn" for item in warn_store["work_items"]))
        self.assertEqual(fail_store["source"]["scope_budget"]["status"], "fail")
        self.assertTrue(all(item["metadata"]["scope_budget"]["status"] == "fail" for item in fail_store["work_items"]))

    def test_rejects_stale_or_edited_registry_hash(self) -> None:
        registry = self.compile_registry()
        registry["leaves"][0]["dependencies"] = ["plan-package-work-items#missing"]

        with self.assertRaisesRegex(ValueError, "Package hash mismatch"):
            EXPORT.export_work_items(registry)

    def test_cli_writes_canonical_work_item_store(self) -> None:
        registry_path = self.root / "package.json"
        output_path = self.root / "work-items.json"
        registry_path.write_text(COMPILE.canonical_json_text(self.compile_registry()), encoding="utf-8")

        exit_code = EXPORT.main([str(registry_path), "--out", str(output_path)])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "plan-package-work-items.v0")
        self.assertEqual(payload["work_items"][0]["SourceId"], "plan-package-work-items#LEAF-001")
        self.assertTrue(output_path.read_text(encoding="utf-8").endswith("\n"))


if __name__ == "__main__":
    unittest.main()
