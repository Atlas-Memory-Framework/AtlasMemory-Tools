from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import atlas_human_gates as gates
from atlas_authority import canonical_digest
from fixtures.authority_fixture import AuthorityFixture, TEST_NOW, TEST_POLICY


class HumanGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.runtime = self.home / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.auth = AuthorityFixture(self.runtime, subject="business-owner")
        identity = mock.patch("atlas_authority.pwd.getpwuid", return_value=SimpleNamespace(pw_dir=str(self.home)))
        identity.start()
        self.addCleanup(identity.stop)
        self.gate = {"id": "visual-review", "kind": "taste", "owner": "business-owner",
                     "question": "Does this exact appearance satisfy the agreed design?", "stage": "after",
                     "action": "completion", "artifact_sha256": "a" * 64, "candidate_sha": "b" * 40,
                     "issue_id": "azdo:OWNER:PROJECT:17", "issue_revision": 7}
        self.context = {"issue_id": self.gate["issue_id"], "issue_revision": 7, "worker_packet_sha256": "c" * 64,
                        "candidate_sha": "b" * 40, "action": "completion", "policy_sha256": TEST_POLICY}

    def receipt(self, **changes):
        receipt = {"gate_id": self.gate["id"], "decision": "accepted", "response": "Accepted after checking the exact candidate and image.", "grant": {}}
        receipt.update(changes)
        receipt["grant"] = self.auth.grant("human_gate", gates.gate_bindings(self.gate, receipt, self.context))
        return receipt

    def evaluate(self, receipts, **options):
        return gates.evaluate_gates(self.runtime, [self.gate], receipts, self.context, stage="after", now=TEST_NOW, **options)

    def test_valid_signed_owner_response_satisfies_gate_without_completion_or_execution(self):
        result = self.evaluate([self.receipt()])
        self.assertTrue(result["satisfied"])
        self.assertEqual(result["verified"][0]["subject"], "business-owner")
        self.assertFalse(result["completion"])

    def test_missing_receipt_stays_pending_without_cryptographic_subprocess(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("unexpected verification")):
            result = self.evaluate([])
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["pending"], ["visual-review"])

    def test_plain_approval_string_cannot_replace_authenticated_human_receipt(self):
        receipt = {"gate_id": self.gate["id"], "decision": "accepted", "response": "Approved", "grant": {"approval_record": "approved-by-owner"}}
        result = self.evaluate([receipt])
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["invalid"], ["visual-review"])

    def test_forged_or_altered_signature_cannot_satisfy_gate(self):
        receipt = self.receipt()
        receipt["grant"]["signature"] = "A" * len(receipt["grant"]["signature"])
        self.assertFalse(self.evaluate([receipt])["satisfied"])

    def test_expired_or_revoked_receipt_remains_pending(self):
        receipt = self.receipt()
        result = gates.evaluate_gates(self.runtime, [self.gate], [receipt], self.context, stage="after", now=TEST_NOW + 4000)
        self.assertFalse(result["satisfied"])
        self.auth.registry["revoked_grants"] = [receipt["grant"]["payload"]["grant_id"]]
        self.auth.update_trust()
        self.assertFalse(self.evaluate([receipt])["satisfied"])

    def test_verified_issuer_must_be_exact_required_owner(self):
        receipt = self.receipt()
        self.auth.registry["issuers"]["test-operator"]["subject"] = "different-owner"
        self.auth.update_trust()
        self.assertFalse(self.evaluate([receipt])["satisfied"])

    def test_replay_across_candidate_issue_revision_artifact_or_question_rejected(self):
        original_gate, original_context = deepcopy(self.gate), deepcopy(self.context)
        receipt = self.receipt()
        mutations = [lambda: self.context.update(candidate_sha="d" * 40),
                     lambda: self.context.update(issue_revision=8),
                     lambda: self.context.update(issue_id="azdo:OWNER:PROJECT:18"),
                     lambda: self.context.update(worker_packet_sha256="e" * 64),
                     lambda: self.gate.update(artifact_sha256="f" * 64),
                     lambda: self.gate.update(question="A different approval question")]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.gate, self.context = deepcopy(original_gate), deepcopy(original_context)
                mutate()
                self.assertFalse(self.evaluate([receipt])["satisfied"])

    def test_tampered_signed_response_or_decision_rejected(self):
        for field, value in (("response", "A different response"), ("decision", "rejected")):
            with self.subTest(field=field):
                receipt = self.receipt()
                receipt[field] = value
                self.assertFalse(self.evaluate([receipt])["satisfied"])

    def test_authentic_feedback_and_rejection_do_not_imply_acceptance(self):
        for decision in ("feedback", "rejected"):
            with self.subTest(decision=decision):
                result = self.evaluate([self.receipt(decision=decision)])
                self.assertFalse(result["satisfied"])
                self.assertEqual(result["invalid"], [])
                if decision == "rejected":
                    self.assertEqual(result["rejected"], ["visual-review"])

    def test_after_acceptance_cannot_be_signed_for_missing_candidate(self):
        self.gate["candidate_sha"] = self.context["candidate_sha"] = None
        with self.assertRaises(gates.HumanGateError):
            self.receipt()

    def test_before_input_can_bind_packet_without_yet_existing_candidate(self):
        self.gate.update(kind="input", stage="before", action="local_execute", candidate_sha=None)
        self.context.update(action="local_execute", candidate_sha=None)
        result = gates.evaluate_gates(self.runtime, [self.gate], [self.receipt()], self.context, stage="before", now=TEST_NOW)
        self.assertTrue(result["satisfied"])

    def test_later_gate_does_not_block_earlier_preparation(self):
        context = {**self.context, "action": "local_execute", "candidate_sha": None}
        result = gates.evaluate_gates(self.runtime, [self.gate], [], context, stage="before", now=TEST_NOW)
        self.assertTrue(result["satisfied"])

    def test_unknown_and_duplicate_receipts_rejected(self):
        receipt = self.receipt()
        for supplied in ([receipt, receipt], [{**receipt, "gate_id": "unknown"}]):
            with self.subTest(supplied_count=len(supplied)), self.assertRaises(gates.HumanGateError):
                self.evaluate(supplied)

    def test_gate_and_receipt_type_confusion_rejected(self):
        for key, value in (("issue_revision", True), ("kind", []), ("owner", ""), ("artifact_sha256", 1)):
            with self.subTest(key=key):
                gate = {**self.gate, key: value}
                with self.assertRaises(gates.HumanGateError):
                    gates.validate_gates([gate])
        receipt = self.receipt()
        self.context["issue_revision"] = True
        self.assertFalse(self.evaluate([receipt])["satisfied"])

    def test_exact_action_scope_blocks_using_worker_grant_as_human_receipt(self):
        receipt = self.receipt()
        receipt["grant"] = self.auth.grant("local_execute", gates.gate_bindings(self.gate, receipt, self.context))
        self.assertFalse(self.evaluate([receipt])["satisfied"])

    def test_routing_policy_drift_invalidates_human_receipt(self):
        receipt = self.receipt()
        self.context["policy_sha256"] = "e" * 64
        self.assertFalse(self.evaluate([receipt])["satisfied"])

    def test_deferred_candidate_receipt_also_binds_original_gate_template(self):
        self.context["gate_template_sha256"] = canonical_digest({**self.gate, "candidate_sha": None})
        receipt = self.receipt()
        self.assertTrue(self.evaluate([receipt])["satisfied"])
        self.context["gate_template_sha256"] = "e" * 64
        self.assertFalse(self.evaluate([receipt])["satisfied"])

    def test_unicode_question_and_response_use_the_shared_canonical_digest(self):
        self.gate["question"] = "L’apparence répond-elle à l’intention — aperçu?"
        receipt = self.receipt(response="Oui, l’aperçu a été vérifié.")
        bindings = gates.gate_bindings(self.gate, receipt, self.context)
        self.assertEqual(bindings["gate_sha256"], canonical_digest(self.gate))
        self.assertEqual(bindings["response_sha256"], canonical_digest(receipt["response"]))
        self.assertTrue(self.evaluate([receipt])["satisfied"])

    def test_validation_preview_creates_no_files_and_launches_nothing(self):
        before = sorted(str(path.relative_to(self.home)) for path in self.home.rglob("*"))
        with mock.patch("subprocess.run", side_effect=AssertionError("preview invoked verifier")), mock.patch("builtins.open", side_effect=AssertionError("preview accessed file")):
            gates.validate_gates([self.gate])
        self.assertEqual(before, sorted(str(path.relative_to(self.home)) for path in self.home.rglob("*")))

    def test_authenticated_answer_is_bound_to_primary_model_evidence(self):
        self.gate.update(kind="input", stage="before", action="local_execute", candidate_sha=None)
        self.context.update(action="local_execute", candidate_sha=None)
        receipt = self.receipt(response="Use the darker blue and retain the existing spacing.")
        evaluation = gates.evaluate_gates(self.runtime, [self.gate], [receipt], self.context, stage="before", now=TEST_NOW)
        answer = {"gate_id": self.gate["id"], "response": receipt["response"]}
        intake = {"worker_packet": {"revision": 7}, "step": {"action": "local_execute"}, "human_gates": [self.gate],
                  "evidence": [{"id": "human-answer:" + self.gate["id"], "kind": "issue", "path": None, "revision": 7,
                                "content": json.dumps(answer, sort_keys=True, separators=(",", ":"), ensure_ascii=False), "sha256": canonical_digest(answer)}]}
        result = gates.bound_human_answers(intake, [receipt], evaluation)
        self.assertEqual(result[0]["response"], receipt["response"])
        self.assertEqual(result[0]["question"], self.gate["question"])
        for mutate in (lambda value: value.update(evidence=[]),
                       lambda value: value["evidence"][0].update(revision=8),
                       lambda value: value["evidence"][0].update(content='{"gate_id":"visual-review","response":"Use red instead"}')):
            with self.subTest(mutate=mutate):
                changed = deepcopy(intake)
                mutate(changed)
                with self.assertRaises(gates.HumanGateError):
                    gates.bound_human_answers(changed, [receipt], evaluation)

    def test_unverified_answer_cannot_become_primary_human_feedback(self):
        self.gate.update(kind="input", stage="before", action="local_execute", candidate_sha=None)
        self.context.update(action="local_execute", candidate_sha=None)
        receipt = self.receipt()
        intake = {"worker_packet": {"revision": 7}, "step": {"action": "local_execute"}, "human_gates": [self.gate], "evidence": []}
        with self.assertRaises(gates.HumanGateError):
            gates.bound_human_answers(intake, [receipt], {"verified": []})


if __name__ == "__main__":
    unittest.main()
