from __future__ import annotations

import importlib.util
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
VALIDATE = load_module("validate_plan_package", ROOT / "skills/plan-package/scripts/validate_plan_package.py")
ISSUE_SPEC = load_module("validate_issue_spec", ROOT / "skills/issue-spec/scripts/validate_issue_spec.py")


class PlanPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "plans").mkdir()
        (self.root / "specs").mkdir()
        (self.root / "skills/example/scripts").mkdir(parents=True)
        (self.root / "tests").mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_package(
        self,
        *,
        second_leaf: bool = True,
        dep_override: str | None = None,
        second_dispatch: str = "manual-review",
    ) -> Path:
        spec_one = self.spec(
            source_id="plan-package-test#LEAF-001",
            manifest_leaf_id="LEAF-001",
            dependencies="- none",
            file_path="skills/example/scripts/build_example.py",
        )
        spec_two = self.spec(
            source_id="plan-package-test#LEAF-002",
            manifest_leaf_id="LEAF-002",
            dependencies=dep_override or "- plan-package-test#LEAF-001",
            file_path="skills/example/scripts/validate_example.py",
            dispatch_mode=second_dispatch,
        )
        (self.root / "specs/leaf-001.md").write_text(spec_one, encoding="utf-8")
        if second_leaf:
            (self.root / "specs/leaf-002.md").write_text(spec_two, encoding="utf-8")
        plan = f"""# Feature: Plan Package Test

## Plan State
PlanId: plan-package-test

## Automation Issue Manifest
- LEAF-001: Build example
  - Spec path: specs/leaf-001.md
  - Spec hash: {ISSUE_SPEC.canonical_spec_hash(spec_one)}
  - Dispatch: manual-review
  - Depends on:
    - none
  - Files in scope:
    - `skills/example/scripts/build_example.py`
  - Files out of scope:
    - `skills/example/scripts/other.py`
  - Required gates:
    - G-CI-Example
  - Validation:
    - python3 -m unittest tests.test_example
  - Acceptance criteria:
    - Example build passes.
  - One PR contract: yes
"""
        if second_leaf:
            plan += f"""
- LEAF-002: Validate example
  - Spec path: specs/leaf-002.md
  - Spec hash: {ISSUE_SPEC.canonical_spec_hash(spec_two)}
  - Dispatch: {second_dispatch}
  - Depends on:
    - plan-package-test#LEAF-001
  - Files in scope:
    - `skills/example/scripts/validate_example.py`
  - Files out of scope:
    - `skills/example/scripts/other.py`
  - Required gates:
    - G-CI-Example
  - Validation:
    - python3 -m unittest tests.test_example
  - Acceptance criteria:
    - Example validation passes.
  - One PR contract: yes
"""
        path = self.root / "plans/example.plan.md"
        path.write_text(plan, encoding="utf-8")
        return path

    def spec(
        self,
        *,
        source_id: str,
        manifest_leaf_id: str,
        dependencies: str,
        file_path: str,
        dispatch_mode: str = "manual-review",
    ) -> str:
        return f"""# Issue Spec: {manifest_leaf_id}

SpecId: {manifest_leaf_id.lower()}-spec
SourceId: {source_id}
ParentPlanId: plan-package-test
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
- G-CI-Example

## Validation
- python3 -m unittest tests.test_example

## Acceptance criteria
- Example validation passes.

## Depth contract
- Covers one package fixture and one failure case.

## Open decisions
- none
"""

    def compile(self) -> dict:
        return COMPILE.compile_registry(self.write_package(), root=self.root)

    def write_inline_package(self) -> Path:
        plan = """# Feature: Inline Package Test

## Plan State
PlanId: plan-package-test

## Automation Issue Manifest
- LEAF-001: Inline example
  - Spec: inline
  - Dispatch: agent-ready
  - Depends on:
    - none
  - Files in scope:
    - `skills/example/scripts/inline_example.py`
  - Files out of scope:
    - `skills/example/scripts/other.py`
  - Required gates:
    - G-CI-Example
  - Validation:
    - python3 -m unittest tests.test_example
  - Acceptance criteria:
    - Inline example passes.
  - One PR contract: yes
"""
        path = self.root / "plans/inline.plan.md"
        path.write_text(plan, encoding="utf-8")
        return path

    def test_compile_output_is_deterministic_and_records_required_metadata(self) -> None:
        first = self.compile()
        second = self.compile()
        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "plan-package.v0")
        self.assertRegex(first["package_hash"], r"^sha256:[a-f0-9]{64}$")
        self.assertEqual(first["source_plan"]["path"], "plans/example.plan.md")
        self.assertRegex(first["source_plan"]["hash"], r"^sha256:[a-f0-9]{64}$")
        self.assertIn("members", first)
        self.assertIn("leaves", first)
        leaf = first["leaves"][0]
        for field in VALIDATE.REQUIRED_LEAF:
            self.assertIn(field, leaf)
        self.assertEqual(leaf["local_export"]["format"], "plan-package-work-item.v0")
        self.assertEqual(leaf["projection_hints"]["mode"], "optional-github-issue")

        text = COMPILE.canonical_json_text(first)
        self.assertTrue(text.endswith("\n"))
        self.assertIn('\n  "leaves": [', text)
        self.assertEqual(first["package_hash"], COMPILE.package_hash(first))

    def test_validator_accepts_compiled_registry(self) -> None:
        result = VALIDATE.validate_registry(self.compile(), root=self.root)
        self.assertTrue(result.ok, result.errors)

    def test_tracking_only_leaf_is_not_local_export_enabled(self) -> None:
        registry = COMPILE.compile_registry(
            self.write_package(second_dispatch="tracking-only"),
            root=self.root,
        )

        second = next(leaf for leaf in registry["leaves"] if leaf["manifest_leaf_id"] == "LEAF-002")

        self.assertFalse(second["local_export"]["enabled"])

    def test_compiler_includes_inline_manifest_leaves(self) -> None:
        registry = COMPILE.compile_registry(self.write_inline_package(), root=self.root)
        result = VALIDATE.validate_registry(registry, root=self.root)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(len(registry["leaves"]), 1)
        leaf = registry["leaves"][0]
        self.assertEqual(leaf["source_id"], "plan-package-test#LEAF-001")
        self.assertIsNone(leaf["spec_path"])
        self.assertEqual(leaf["dispatch_mode"], "agent-ready")
        self.assertEqual(leaf["files_in_scope"], ["skills/example/scripts/inline_example.py"])
        self.assertTrue(leaf["local_export"]["enabled"])
        self.assertNotIn(None, [member["path"] for member in registry["members"]])

    def test_validator_rejects_missing_package_member(self) -> None:
        registry = self.compile()
        registry["members"] = [member for member in registry["members"] if member["path"] != "specs/leaf-001.md"]
        registry["package_hash"] = COMPILE.package_hash(registry)
        result = VALIDATE.validate_registry(registry, root=self.root)
        self.assertFalse(result.ok)
        self.assertTrue(any("Missing package member record: specs/leaf-001.md" in error for error in result.errors))

    def test_validator_rejects_malformed_hash(self) -> None:
        registry = self.compile()
        registry["source_plan"]["hash"] = "sha256:BAD"
        registry["package_hash"] = COMPILE.package_hash(registry)
        result = VALIDATE.validate_registry(registry, root=self.root)
        self.assertFalse(result.ok)
        self.assertTrue(any("Malformed hash" in error for error in result.errors))

    def test_validator_rejects_hash_mismatch(self) -> None:
        registry = self.compile()
        registry["members"][0]["hash"] = "sha256:" + "0" * 64
        registry["package_hash"] = COMPILE.package_hash(registry)
        result = VALIDATE.validate_registry(registry, root=self.root)
        self.assertFalse(result.ok)
        self.assertTrue(any("Hash mismatch for member" in error for error in result.errors))

    def test_validator_rejects_path_escape(self) -> None:
        registry = self.compile()
        registry["members"][0]["path"] = "../escape.md"
        registry["package_hash"] = COMPILE.package_hash(registry)
        result = VALIDATE.validate_registry(registry, root=self.root)
        self.assertFalse(result.ok)
        self.assertTrue(any("path escapes package root" in error for error in result.errors))

    def test_validator_rejects_duplicate_source_ids(self) -> None:
        registry = self.compile()
        registry["leaves"][1]["source_id"] = registry["leaves"][0]["source_id"]
        registry["package_hash"] = COMPILE.package_hash(registry)
        result = VALIDATE.validate_registry(registry, root=self.root)
        self.assertFalse(result.ok)
        self.assertTrue(any("Duplicate source id" in error for error in result.errors))

    def test_validator_rejects_missing_required_registry_field(self) -> None:
        registry = self.compile()
        del registry["leaves"][0]["local_export"]
        registry["package_hash"] = COMPILE.package_hash(registry)
        result = VALIDATE.validate_registry(registry, root=self.root)
        self.assertFalse(result.ok)
        self.assertTrue(any("local_export" in error for error in result.errors))

    def test_validator_rejects_dependency_mismatch(self) -> None:
        registry = self.compile()
        registry["leaves"][1]["dependencies"] = ["missing-source"]
        registry["package_hash"] = COMPILE.package_hash(registry)
        result = VALIDATE.validate_registry(registry, root=self.root)
        self.assertFalse(result.ok)
        self.assertTrue(any("Dependency mismatch" in error for error in result.errors))

    def test_validator_rejects_stale_regenerated_leaf_metadata(self) -> None:
        registry = self.compile()
        registry["leaves"][0]["files_in_scope"] = ["skills/example/scripts/stale.py"]
        registry["package_hash"] = COMPILE.package_hash(registry)
        result = VALIDATE.validate_registry(registry, root=self.root)
        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "Regenerated leaf metadata mismatch" in error and "files_in_scope" in error
                for error in result.errors
            )
        )

    def test_compiler_rejects_manifest_spec_hash_mismatch(self) -> None:
        plan_path = self.write_package(second_leaf=False)
        text = plan_path.read_text(encoding="utf-8").replace("sha256:", "sha256:0", 1)
        plan_path.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Manifest Spec hash must use"):
            COMPILE.compile_registry(plan_path, root=self.root)


if __name__ == "__main__":
    unittest.main()
