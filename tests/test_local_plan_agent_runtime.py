from __future__ import annotations

import importlib.util
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "local-plan-agent-runtime" / "scripts" / "validate_proposal.py"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("local_plan_validate_proposal", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class ProposalValidatorTests(unittest.TestCase):
    def setUp(self):
        self.validator = load_validator_module()
        self.section_index = {
            "plan_sha256": "abc123",
            "plan_path": str(ROOT / "plans" / "example.plan.md"),
            "sections": [
                {
                    "section_id": "S0001-intent-model",
                    "heading": "## Intent Model",
                    "sha256": "section123",
                }
            ],
        }

    def proposal(self, *, intent_gap_type=None):
        finding = {
            "id": "F-001",
            "severity": "high",
            "section_id": "S0001-intent-model",
            "section": "## Intent Model",
            "concrete_issue": "Latent target is flattened into implementation tasks.",
            "why_it_matters": "A zero-context implementer could build a plausible but wrong behavior.",
            "evidence": ["## Intent Model is missing anti-targets."],
            "proposed_remediation": "Add anti-targets and checksum failure examples.",
            "requires_user_decision": False,
            "decision_options": {"A": "", "B": "", "C": ""},
        }
        if intent_gap_type is not None:
            finding["intent_gap_type"] = intent_gap_type
        return {
            "agent_id": "agent-1",
            "persona": "intent-reconciliation-reviewer",
            "source_plan_path": self.section_index["plan_path"],
            "source_plan_sha256": self.section_index["plan_sha256"],
            "scope": ["## Intent Model"],
            "summary": "Intent review.",
            "findings": [finding],
            "patches": [
                {
                    "id": "P-001",
                    "finding_ids": ["F-001"],
                    "target_section_id": "S0001-intent-model",
                    "target_section": "## Intent Model",
                    "target_section_sha256": "section123",
                    "patch_type": "section-replacement",
                    "rationale": "Restore intent alignment.",
                    "replacement_text": "## Intent Model\nLatent target:\n- Preserved.\n",
                }
            ],
            "human_decisions": [],
            "blocked_items": [],
        }

    def package_section_index(self, package_root: Path):
        plan = package_root / "PLAN.md"
        readonly = package_root / "readonly.md"
        plan_text = "# Plan\n\n## Intent Model\nPlan body.\n"
        readonly_text = "# Read Only\n\n## Context\nContext body.\n"
        plan.write_text(plan_text, encoding="utf-8")
        readonly.write_text(readonly_text, encoding="utf-8")
        package_files = [
            {
                "file_id": "F0001",
                "path": "PLAN.md",
                "kind": "plan",
                "sha256": sha256_text(plan_text),
                "patchable": True,
            },
            {
                "file_id": "F0002",
                "path": "readonly.md",
                "kind": "context",
                "sha256": sha256_text(readonly_text),
                "patchable": False,
            },
        ]
        package_hash = self.validator.package_sha256(package_files)
        return {
            "package_mode": True,
            "package_root": str(package_root),
            "source_package_sha256": package_hash,
            "plan_sha256": sha256_text(plan_text),
            "plan_path": str(plan),
            "package_files": package_files,
            "sections": [
                {
                    "section_id": "F0001:S0001-plan",
                    "heading": "# Plan",
                    "sha256": sha256_text(plan_text),
                    "file_path": "PLAN.md",
                    "patchable": True,
                },
                {
                    "section_id": "F0002:S0001-read-only",
                    "heading": "# Read Only",
                    "sha256": sha256_text(readonly_text),
                    "file_path": "readonly.md",
                    "patchable": False,
                },
            ],
        }

    def package_proposal(self, section_index: dict):
        proposal = self.proposal()
        proposal["source_plan_path"] = section_index["plan_path"]
        proposal["source_plan_sha256"] = section_index["plan_sha256"]
        proposal["source_package_sha256"] = section_index["source_package_sha256"]
        proposal["findings"][0]["section_id"] = "F0001:S0001-plan"
        proposal["findings"][0]["section"] = "# Plan"
        proposal["patches"][0]["target_section_id"] = "F0001:S0001-plan"
        proposal["patches"][0]["target_section"] = "# Plan"
        proposal["patches"][0]["target_section_sha256"] = section_index["sections"][0]["sha256"]
        proposal["patches"][0]["replacement_text"] = "# Plan\n\n## Intent Model\nUpdated body.\n"
        return proposal

    def test_intent_gap_type_is_optional(self):
        errors = self.validator.validate(self.proposal(), self.section_index, check_canonical=False)
        self.assertEqual(errors, [])

    def test_valid_intent_gap_type_passes(self):
        errors = self.validator.validate(
            self.proposal(intent_gap_type="plan-output-gap"),
            self.section_index,
            check_canonical=False,
        )
        self.assertEqual(errors, [])

    def test_invalid_intent_gap_type_fails(self):
        errors = self.validator.validate(
            self.proposal(intent_gap_type="vibes-gap"),
            self.section_index,
            check_canonical=False,
        )
        self.assertIn("finding F-001 has invalid intent_gap_type", errors)

    def test_package_mode_requires_source_package_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            section_index = self.package_section_index(Path(tmp))
            proposal = self.package_proposal(section_index)
            proposal.pop("source_package_sha256")

            errors = self.validator.validate(proposal, section_index, check_canonical=False)

            self.assertIn("missing top-level field: source_package_sha256", errors)
            self.assertRegex(section_index["source_package_sha256"], r"^sha256:[a-f0-9]{64}$")

    def test_package_mode_rejects_stale_package_snapshot_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            section_index = self.package_section_index(Path(tmp))
            proposal = self.package_proposal(section_index)
            proposal["source_package_sha256"] = "stale"

            errors = self.validator.validate(proposal, section_index, check_canonical=False)

            self.assertIn("source_package_sha256 does not match section index", errors)

    def test_package_mode_rejects_changed_package_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_root = Path(tmp)
            section_index = self.package_section_index(package_root)
            proposal = self.package_proposal(section_index)
            (package_root / "readonly.md").write_text("# Read Only\n\n## Context\nChanged.\n", encoding="utf-8")

            errors = self.validator.validate(proposal, section_index, check_canonical=True)

            self.assertIn("package document changed since snapshot: readonly.md", errors)

    def test_package_mode_rejects_read_only_document_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            section_index = self.package_section_index(Path(tmp))
            proposal = self.package_proposal(section_index)
            proposal["findings"][0]["section_id"] = "F0002:S0001-read-only"
            proposal["findings"][0]["section"] = "# Read Only"
            proposal["patches"][0]["target_section_id"] = "F0002:S0001-read-only"
            proposal["patches"][0]["target_section"] = "# Read Only"
            proposal["patches"][0]["target_section_sha256"] = section_index["sections"][1]["sha256"]

            errors = self.validator.validate(proposal, section_index, check_canonical=False)

            self.assertIn("P-001 targets read-only package document: readonly.md", errors)


if __name__ == "__main__":
    unittest.main()
