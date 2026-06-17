from __future__ import annotations

import importlib.util
import sys
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


if __name__ == "__main__":
    unittest.main()
