from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "issue-spec" / "scripts" / "validate_issue_spec.py"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("issue_spec_validator_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def valid_manifest() -> str:
    return textwrap.dedent(
        """\
        ## Automation Issue Manifest
        ### Leaf issues
        - PPV0-LEAF-001: Add issue spec template and validator
          - Dispatch: manual-review
          - Depends on:
            - none
          - Files in scope:
            - `skills/issue-spec/SKILL.md`
            - `skills/issue-spec/reference.md`
            - `skills/issue-spec/scripts/validate_issue_spec.py`
            - `tests/test_issue_spec_validator.py`
          - Files out of scope:
            - `skills/plan-to-issues/scripts/plan_to_issues.py`
            - `skills/local-plan-agent-runtime/scripts/snapshot_plan.py`
          - Required gates:
            - G-CI-IssueSpec-Validator
          - Validation:
            - python3 -m unittest tests.test_issue_spec_validator
          - Acceptance criteria:
            - Valid issue specs with required fields pass.
          - One PR contract: yes
        """
    )


def valid_spec(**overrides: str) -> str:
    fields = {
        "SpecId": "plan-package-v0-PPV0-LEAF-001-spec",
        "SourceId": "plan-package-v0#PPV0-LEAF-001",
        "ParentPlanId": "plan-package-v0",
        "ManifestLeafId": "PPV0-LEAF-001",
        "Dispatch mode": "manual-review",
        "One PR contract": "yes",
    }
    fields.update(overrides)
    header = "\n".join(f"{key}: {value}" for key, value in fields.items())
    return textwrap.dedent(
        f"""\
        # Issue Spec: Add issue spec template and validator

        {header}

        ## Intent
        Create the issue-spec skill, reference template, and deterministic validator.

        ## Anti-scope
        - Do not modify plan-to-issues or local-plan-agent-runtime.

        ## Files in scope
        - `skills/issue-spec/SKILL.md`
        - `skills/issue-spec/reference.md`
        - `skills/issue-spec/scripts/validate_issue_spec.py`
        - `tests/test_issue_spec_validator.py`

        ## Files out of scope
        - `skills/plan-to-issues/scripts/plan_to_issues.py`
        - `skills/local-plan-agent-runtime/scripts/snapshot_plan.py`

        ## Dependencies
        - none

        ## Required gates
        - G-CI-IssueSpec-Validator

        ## Validation
        - `python3 -m unittest tests.test_issue_spec_validator`

        ## Acceptance criteria
        - Valid issue specs with required fields pass.

        ## Depth contract
        - Cover valid sidecar, missing fields, source alignment, missing validation, and inline acceptance.
        - Keep validation deterministic and local-only.

        ## Open decisions
        - none
        """
    )


class IssueSpecValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_validator_module()

    def assert_valid(self, spec: str, manifest: str | None = None) -> None:
        result = self.mod.validate_sidecar(spec, manifest, "PPV0-LEAF-001")
        self.assertTrue(result.ok, result.errors)

    def assert_invalid_contains(self, spec: str, expected: str, manifest: str | None = None) -> None:
        result = self.mod.validate_sidecar(spec, manifest, "PPV0-LEAF-001")
        self.assertFalse(result.ok)
        self.assertTrue(
            any(expected in error for error in result.errors),
            f"expected {expected!r} in {result.errors!r}",
        )

    def test_valid_spec_passes_against_manifest(self) -> None:
        self.assert_valid(valid_spec(), valid_manifest())

    def test_missing_required_fields_emit_specific_messages(self) -> None:
        spec = "# Issue Spec\n"
        result = self.mod.validate_sidecar(spec)

        self.assertFalse(result.ok)
        for field in self.mod.REQUIRED_FIELDS:
            self.assertIn(f"Missing required field: {field}.", result.errors)

    def test_missing_depth_contract_for_multi_file_leaf_fails(self) -> None:
        spec = valid_spec().replace(
            "\n        ## Depth contract\n"
            "        - Cover valid sidecar, missing fields, source alignment, missing validation, and inline acceptance.\n"
            "        - Keep validation deterministic and local-only.\n",
            "\n",
        )

        self.assert_invalid_contains(spec, "Depth contract is required", valid_manifest())

    def test_missing_depth_contract_for_single_test_file_fails(self) -> None:
        manifest = valid_manifest().replace(
            "- `skills/issue-spec/SKILL.md`\n"
            "        - `skills/issue-spec/reference.md`\n"
            "        - `skills/issue-spec/scripts/validate_issue_spec.py`\n"
            "        - `tests/test_issue_spec_validator.py`",
            "- `tests/test_issue_spec_validator.py`",
        )
        spec = valid_spec().replace(
            "- `skills/issue-spec/SKILL.md`\n"
            "        - `skills/issue-spec/reference.md`\n"
            "        - `skills/issue-spec/scripts/validate_issue_spec.py`\n"
            "        - `tests/test_issue_spec_validator.py`",
            "- `tests/test_issue_spec_validator.py`",
        ).replace(
            "\n        ## Depth contract\n"
            "        - Cover valid sidecar, missing fields, source alignment, missing validation, and inline acceptance.\n"
            "        - Keep validation deterministic and local-only.\n",
            "\n",
        )

        self.assert_invalid_contains(spec, "Depth contract is required", manifest)

    def test_bad_source_id_alignment_fails(self) -> None:
        spec = valid_spec(SourceId="wrong-plan#PPV0-LEAF-001")

        self.assert_invalid_contains(spec, "SourceId must align", valid_manifest())

    def test_bare_source_id_alignment_fails(self) -> None:
        spec = valid_spec(SourceId="PPV0-LEAF-001")

        self.assert_invalid_contains(spec, "SourceId must align", valid_manifest())

    def test_manifest_spec_source_id_mismatch_fails(self) -> None:
        spec = valid_spec()
        manifest = valid_manifest().replace(
            "- Dispatch: manual-review",
            "- Spec source id: wrong-plan#PPV0-LEAF-001\n          - Dispatch: manual-review",
        )

        self.assert_invalid_contains(spec, "Spec source id mismatch", manifest)

    def test_manifest_spec_hash_mismatch_fails(self) -> None:
        spec = valid_spec()
        manifest = valid_manifest().replace(
            "- Dispatch: manual-review",
            "- Spec hash: sha256:" + ("0" * 64) + "\n          - Dispatch: manual-review",
        )

        self.assert_invalid_contains(spec, "Spec hash mismatch", manifest)

    def test_manifest_spec_hash_match_passes(self) -> None:
        spec = valid_spec()
        manifest = valid_manifest().replace(
            "- Dispatch: manual-review",
            f"- Spec hash: {self.mod.canonical_spec_hash(spec)}\n          - Dispatch: manual-review",
        )

        self.assert_valid(spec, manifest)

    def test_sidecar_manifest_leaf_mismatch_fails(self) -> None:
        spec = valid_spec(ManifestLeafId="PPV0-LEAF-999", SourceId="plan-package-v0#PPV0-LEAF-999")

        self.assert_invalid_contains(spec, "ManifestLeafId mismatch", valid_manifest())

    def test_missing_validation_fails(self) -> None:
        spec = valid_spec().replace(
            "\n        ## Validation\n        - `python3 -m unittest tests.test_issue_spec_validator`\n",
            "\n        ## Validation\n        - TBD\n",
        )

        self.assert_invalid_contains(spec, "Missing required field: Validation.", valid_manifest())

    def test_sidecar_cannot_introduce_manifest_absent_file_gate_dependency_or_dispatch(self) -> None:
        spec = valid_spec().replace(
            "- `tests/test_issue_spec_validator.py`",
            "- `tests/test_issue_spec_validator.py`\n        - `skills/plan-to-issues/scripts/plan_to_issues.py`",
        )

        self.assert_invalid_contains(spec, "Sidecar cannot introduce Files in scope", valid_manifest())

        gate_spec = valid_spec().replace("- G-CI-IssueSpec-Validator", "- G-CI-IssueSpec-Validator\n        - G-CI-Other")
        self.assert_invalid_contains(gate_spec, "Sidecar cannot introduce Required gates", valid_manifest())

        dispatch_spec = valid_spec(**{"Dispatch mode": "agent-ready"})
        self.assert_invalid_contains(dispatch_spec, "Sidecar cannot override dispatch mode", valid_manifest())

    def test_sidecar_cannot_introduce_approval_or_authority_semantics(self) -> None:
        spec = valid_spec() + "\nApproval state: approved\nAuthority: sidecar overrides manifest\n"

        self.assert_invalid_contains(spec, "approval state", valid_manifest())
        self.assert_invalid_contains(spec, "authority semantics", valid_manifest())

    def test_sidecar_cannot_introduce_leaf_shaped_bullets(self) -> None:
        spec = valid_spec() + "\n- PPV0-LEAF-999: New leaf\n"

        self.assert_invalid_contains(spec, "Sidecar cannot introduce or override leaves", valid_manifest())

    def test_inline_manifest_acceptance(self) -> None:
        manifest = valid_manifest().replace(
            "- Dispatch: manual-review",
            "- Spec: inline\n"
            "          - Dispatch: manual-review\n"
            "          - Depth contract:\n"
            "            - Covers all four issue-spec files and the validator test gate.",
        )

        result = self.mod.validate_inline_manifest(manifest, "PPV0-LEAF-001")

        self.assertTrue(result.ok, result.errors)

    def test_inline_manifest_rejects_missing_required_context(self) -> None:
        manifest = textwrap.dedent(
            """\
            ## Automation Issue Manifest
            ### Leaf issues
            - PPV0-LEAF-001: Add issue spec template and validator
              - Spec: inline
              - Dispatch: manual-review
              - Files in scope:
                - `skills/issue-spec/SKILL.md`
              - One PR contract: yes
            """
        )

        result = self.mod.validate_inline_manifest(manifest, "PPV0-LEAF-001")

        self.assertFalse(result.ok)
        self.assertIn("Inline manifest is missing required field: Dependencies.", result.errors)
        self.assertIn("Inline manifest is missing required field: Validation.", result.errors)
        self.assertIn("Inline manifest is missing required field: Acceptance criteria.", result.errors)

    def test_cli_returns_nonzero_and_specific_error(self) -> None:
        with self.subTest("missing validation"):
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                spec_path = tmp / "spec.md"
                manifest_path = tmp / "plan.md"
                spec_path.write_text(
                    valid_spec().replace(
                        "\n        ## Validation\n        - `python3 -m unittest tests.test_issue_spec_validator`\n",
                        "\n        ## Validation\n        - TBD\n",
                    ),
                    encoding="utf-8",
                )
                manifest_path.write_text(valid_manifest(), encoding="utf-8")

                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        str(spec_path),
                        "--manifest",
                        str(manifest_path),
                        "--leaf-id",
                        "PPV0-LEAF-001",
                    ],
                    capture_output=True,
                    text=True,
                )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing required field: Validation.", result.stderr)


if __name__ == "__main__":
    unittest.main()
