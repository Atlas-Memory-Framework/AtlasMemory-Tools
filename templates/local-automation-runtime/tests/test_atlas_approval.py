from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import atlas_approval as approval
import atlas_human_gates as gates
from atlas_authority import AuthorityError, canonical_digest
from fixtures.authority_fixture import AuthorityFixture, TEST_NOW, TEST_POLICY


class ApprovalFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.runtime = self.home / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.identity = mock.patch("pwd.getpwuid", return_value=SimpleNamespace(pw_dir=str(self.home)))
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.auth = AuthorityFixture(self.runtime)
        self.inbox = approval.ApprovalInbox(self.runtime)
        self.request = approval.make_request(
            repository_url="https://dev.azure.com/OWNER/PROJECT/_git/REPO", issue_id="azdo:OWNER:PROJECT:17",
            issue_revision=7, action="assess", owner="operator", question="Approve this exact bounded assessment?",
            artifact_sha256="a" * 64, policy_sha256=TEST_POLICY,
            bindings={"repository_url": "https://dev.azure.com/OWNER/PROJECT/_git/REPO", "intake_sha256": "b" * 64,
                      "effective_config_sha256": "c" * 64, "policy_sha256": TEST_POLICY},
            details={"models": {"planning": {"model": "gpt-6-astra", "reasoning": "max"}},
                     "scope": "One local assessment; no execution or publication."})

    def card(self, request=None):
        return self.inbox.prepare(request or self.request, now=TEST_NOW)

    def response(self, request=None, *, decision="accepted", response_text=None, **overrides):
        exported = self.inbox.export_request(request or self.request, decision=decision, response_text=response_text)
        subject = exported["signing_subject"]
        grant = self.auth.grant(subject["action"], subject["bindings"], grant_id=subject["grant_id"], **overrides)
        result = {key: exported[key] for key in ("schema_version", "request_id", "request_revision", "material_sha256", "decision", "response")}
        return {**result, "grant": grant}

    def human_request(self):
        gate = {"id": "design-choice", "kind": "taste", "stage": "after", "action": "completion", "owner": "operator",
                "question": "Does this candidate match the intended appearance?", "artifact_sha256": "e" * 64,
                "candidate_sha": "f" * 40, "issue_id": self.request["issue_id"], "issue_revision": 7}
        context = {"issue_id": gate["issue_id"], "issue_revision": 7, "worker_packet_sha256": "c" * 64,
                   "candidate_sha": gate["candidate_sha"], "action": "completion", "policy_sha256": TEST_POLICY}
        return approval.make_request(**{**self.request, "action": "human_gate", "step_id": "design", "question": gate["question"],
                                        "artifact_sha256": gate["artifact_sha256"], "bindings": None,
                                        "human_gate": {"gate": gate, "context": context}})

    def artifact_bytes(self):
        return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.inbox.root.iterdir() if path.name != "inbox.lock"}

    def enroll_adapter(self, code=None, *, response=None, **changes):
        directory = self.home / "operator-adapter"
        directory.mkdir(mode=0o700, exist_ok=True)
        executable = directory / "synthetic-public-response-adapter"
        if code is None:
            # Only a public signed response is in the executable. Synthetic
            # signing material remains inside AuthorityFixture's memory/memfd.
            code = ("import json, os, sys\n"
                    "assert sys.argv[1:] == ['--atlas-approval-stdio-v1']\n"
                    "assert not any(key in os.environ for key in ['HOME','ATLAS_TEST_CREDENTIAL','PYTHONPATH','OPENSSL_CONF'])\n"
                    "request = json.load(sys.stdin)\n"
                    f"response = json.loads({json.dumps(response)!r})\n"
                    "assert request['request_id'] == response['request_id']\n"
                    "assert request['request_revision'] == response['request_revision']\n"
                    "assert request['material_sha256'] == response['material_sha256']\n"
                    "assert request['signing_subject']['grant_id'] == response['grant']['payload']['grant_id']\n"
                    "print(json.dumps(response))\n")
        executable.write_text("#!/usr/bin/python3\n" + code, encoding="utf-8")
        executable.chmod(0o700)
        profile = {"schema_version": 1, "enabled": True, "issuer": "test-operator", "executable": str(executable),
                   "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(), "timeout_seconds": 1,
                   "actions": ["assess", "local_execute", "draft_pr", "board_write", "human_gate"], **changes}
        self.write_profile(profile)
        return profile, executable

    def write_profile(self, profile):
        path = self.runtime / "authority" / "issuer.json"
        path.write_text(json.dumps(profile), encoding="utf-8")
        path.chmod(0o600)


class ApprovalTests(ApprovalFixture):
    def test_preview_is_pure_without_existing_runtime_or_authority(self):
        absent = self.home / "does-not-exist"
        before = sorted(str(path) for path in self.home.rglob("*"))
        with mock.patch("subprocess.Popen", side_effect=AssertionError("preview started a process")), \
                mock.patch("atlas_approval._runtime_directory", side_effect=AssertionError("preview read protected state")), \
                mock.patch("builtins.open", side_effect=AssertionError("preview opened a file")), \
                mock.patch("os.open", side_effect=AssertionError("preview opened a descriptor")):
            result = approval.ApprovalInbox(absent).preview(self.request)
        self.assertTrue(result["inert"])
        self.assertFalse(result["completion"])
        self.assertEqual(result["effects"], [])
        self.assertEqual(before, sorted(str(path) for path in self.home.rglob("*")))

    def test_repeated_material_preparation_preserves_card_revision_and_artifacts(self):
        first = self.card()
        before = self.artifact_bytes()
        second = self.inbox.prepare(self.request, now=TEST_NOW + 900)
        self.assertEqual(first, second)
        self.assertEqual(before, self.artifact_bytes())
        self.assertEqual(first["revision"], 1)
        self.assertFalse(first["completion"])
        self.assertIn("gpt-6-astra", Path(first["artifacts"]["text"]).read_text())

    def test_html_escapes_questions_owners_paths_and_untrusted_details(self):
        request = {**self.request, "question": '<script src="https://bad.invalid/x">alert(1)</script>',
                   "owner": '<img src=x onerror="bad()">', "artifact_path": 'javascript:alert("bad")',
                   "details": {"note": "</pre><iframe src='https://bad.invalid'></iframe>"}}
        card = self.card(request)
        document = Path(card["artifacts"]["html"]).read_text()
        self.assertNotIn("<script", document)
        self.assertNotIn("<img", document)
        self.assertNotIn("<iframe", document)
        self.assertIn("&lt;script", document)
        self.assertIn("default-src 'none'", document)
        self.assertIn("form-action 'none'", document)
        self.assertFalse((self.home / "bad").exists())

    def test_material_changes_invalidate_current_response_and_reverting_cannot_replay_old_grant(self):
        first = self.card()
        original = self.response()
        self.inbox.import_response(self.request, original, now=TEST_NOW)
        changed = {**self.request, "question": "An updated decision with the same exact operation."}
        second = self.card(changed)
        self.assertEqual(first["request_id"], second["request_id"])
        self.assertEqual(second["revision"], 2)
        self.assertEqual(self.inbox.find_response(self.request, now=TEST_NOW)["status"], "superseded")
        self.assertEqual(self.inbox.find_response(changed, now=TEST_NOW)["status"], "pending")
        third = self.card()
        self.assertEqual(third["revision"], 3)
        self.assertEqual(third["material_sha256"], first["material_sha256"])
        replay = {**original, "request_revision": 3}
        with self.assertRaisesRegex(approval.ApprovalError, "readable request revision"):
            self.inbox.import_response(self.request, replay, now=TEST_NOW)

    def test_native_revision_owner_artifact_policy_and_scope_change_material(self):
        first = self.card()
        changes = [{"issue_revision": 8}, {"owner": "different-owner"}, {"artifact_sha256": "f" * 64},
                   {"policy_sha256": "e" * 64, "bindings": {**self.request["bindings"], "policy_sha256": "e" * 64}},
                   {"bindings": {**self.request["bindings"], "intake_sha256": "a" * 64}},
                   {"details": {"models": {"planning": {"model": "gpt-6-astra", "reasoning": "high"}}}}]
        for delta in changes:
            with self.subTest(field=next(iter(delta))):
                next_card = self.card({**self.request, **delta})
                self.assertEqual(first["request_id"], next_card["request_id"])
                self.assertNotEqual(first["material_sha256"], next_card["material_sha256"])

    def test_distinct_logical_actions_and_steps_have_distinct_cards(self):
        first = self.card()
        for delta in ({"step_id": "second-assessment"}, {"action": "local_execute"}, {"issue_id": "azdo:OWNER:PROJECT:18"}):
            with self.subTest(delta=delta):
                self.assertNotEqual(first["request_id"], self.card({**self.request, **delta})["request_id"])

    def test_export_is_unsigned_and_exact_without_touching_state_unless_requested(self):
        card = self.card()
        before = self.artifact_bytes()
        with mock.patch("subprocess.Popen", side_effect=AssertionError("export called signer")):
            exported = self.inbox.export_request(self.request)
        self.assertEqual(exported["signing_subject"]["bindings"], self.request["bindings"])
        self.assertEqual(exported["signing_subject"]["grant_id"], card["grant_id"])
        self.assertNotIn("grant", exported)
        self.assertNotIn("signature", exported)
        self.assertEqual(before, self.artifact_bytes())
        self.inbox.export_request(self.request, write=True)
        self.assertEqual(json.loads((self.inbox.root / (card["request_id"] + ".export.json")).read_text()), exported)

    def test_real_signed_operation_response_is_accepted_and_duplicate_is_inert(self):
        self.card()
        response = self.response()
        result = self.inbox.import_response(self.request, response, now=TEST_NOW)
        self.assertEqual(result["status"], "accepted")
        self.assertTrue(result["verified"])
        self.assertFalse(result["completion"])
        self.assertEqual(result["grant"], response["grant"])
        before = self.artifact_bytes()
        again = self.inbox.import_response(self.request, response, now=TEST_NOW + 5)
        self.assertTrue(again["duplicate"])
        self.assertEqual(before, self.artifact_bytes())
        self.assertEqual(self.inbox.find_response(self.request, now=TEST_NOW)["grant"], response["grant"])

    def test_unicode_binding_remains_identical_through_export_crypto_and_readback(self):
        self.request["question"] = "Approuver l’aperçu — révision courante?"
        self.request["bindings"]["title"] = "L’aperçu doit garder la même teinte."
        self.card()
        response = self.response()
        self.assertEqual(response["grant"]["payload"]["bindings"], self.request["bindings"])
        self.assertTrue(self.inbox.import_response(self.request, response, now=TEST_NOW)["verified"])

    def test_plain_yes_fake_signature_and_signed_wrong_action_or_bindings_never_import(self):
        self.card()
        valid = self.response()
        wrong_action = deepcopy(valid)
        wrong_action["grant"] = self.auth.grant("local_execute", self.request["bindings"], grant_id=valid["grant"]["payload"]["grant_id"])
        wrong_binding = deepcopy(valid)
        wrong_binding["grant"] = self.auth.grant("assess", {**self.request["bindings"], "intake_sha256": "e" * 64}, grant_id=valid["grant"]["payload"]["grant_id"])
        signature = deepcopy(valid)
        signature["grant"]["signature"] = "A" * len(signature["grant"]["signature"])
        for supplied in ({"approved": True}, {**valid, "grant": {"approval": "yes"}}, signature, wrong_action, wrong_binding):
            with self.subTest(supplied_fields=list(supplied)):
                before = self.artifact_bytes()
                with self.assertRaises((approval.ApprovalError, AuthorityError)):
                    self.inbox.import_response(self.request, supplied, now=TEST_NOW)
                self.assertEqual(before, self.artifact_bytes())
                self.assertEqual(self.inbox.find_response(self.request, now=TEST_NOW)["status"], "pending")

    def test_declared_owner_must_match_authenticated_issuer_subject(self):
        self.request["owner"] = "another-person"
        self.card()
        with self.assertRaisesRegex(approval.ApprovalError, "owner"):
            self.inbox.import_response(self.request, self.response(), now=TEST_NOW)

    def test_expiry_and_revocation_are_rechecked_when_a_stored_response_is_consumed(self):
        self.card()
        response = self.response()
        self.inbox.import_response(self.request, response, now=TEST_NOW)
        self.assertEqual(self.inbox.find_response(self.request, now=TEST_NOW + 4000)["status"], "invalid")
        self.auth.registry["revoked_grants"] = [response["grant"]["payload"]["grant_id"]]
        self.auth.update_trust()
        result = self.inbox.find_response(self.request, now=TEST_NOW)
        self.assertEqual(result["status"], "invalid")
        self.assertNotIn("grant", result)

    def test_expired_grant_cannot_create_response_state(self):
        self.card()
        before = self.artifact_bytes()
        with self.assertRaises(AuthorityError):
            self.inbox.import_response(self.request, self.response(expires_at=TEST_NOW - 1), now=TEST_NOW)
        self.assertEqual(before, self.artifact_bytes())

    def test_revocation_between_precheck_and_locked_import_is_rechecked(self):
        self.card()
        response = self.response()
        original = self.inbox._verify_response
        calls = 0

        def revoke_after_first_check(*args, **kwargs):
            nonlocal calls
            result = original(*args, **kwargs)
            calls += 1
            if calls == 1:
                self.auth.registry["revoked_grants"] = [response["grant"]["payload"]["grant_id"]]
                self.auth.update_trust()
            return result

        before = self.artifact_bytes()
        with mock.patch.object(self.inbox, "_verify_response", side_effect=revoke_after_first_check), self.assertRaises(AuthorityError):
            self.inbox.import_response(self.request, response, now=TEST_NOW)
        self.assertEqual(before, self.artifact_bytes())

    def test_changed_request_during_signature_verification_cannot_be_imported(self):
        self.card()
        response = self.response()
        original = self.inbox._verify_response
        changed = {**self.request, "issue_revision": 8}

        def revise_after_verification(*args, **kwargs):
            result = original(*args, **kwargs)
            self.card(changed)
            return result

        with mock.patch.object(self.inbox, "_verify_response", side_effect=revise_after_verification), self.assertRaises(approval.ApprovalError):
            self.inbox.import_response(self.request, response, now=TEST_NOW)
        self.assertEqual(self.inbox.find_response(changed, now=TEST_NOW)["status"], "pending")

    def test_tampered_signed_card_response_is_invalid(self):
        card = self.card()
        self.inbox.import_response(self.request, self.response(), now=TEST_NOW)
        path = Path(card["artifacts"]["request"])
        stored = json.loads(path.read_text())
        stored["response"]["grant"]["payload"]["bindings"]["intake_sha256"] = "e" * 64
        path.write_text(json.dumps(stored))
        self.assertEqual(self.inbox.find_response(self.request, now=TEST_NOW)["status"], "invalid")

    def test_human_accepted_response_is_a_standard_bound_receipt(self):
        request = self.human_request()
        self.card(request)
        response = self.response(request, response_text="The exact image matches the intended appearance.")
        result = self.inbox.import_response(request, response, now=TEST_NOW)
        self.assertNotIn("grant", result)
        subject = request["human_gate"]
        evaluated = gates.evaluate_gates(self.runtime, [subject["gate"]], [result["human_receipt"]], subject["context"], stage="after", now=TEST_NOW)
        self.assertTrue(evaluated["satisfied"])
        self.assertFalse(evaluated["completion"])

    def test_human_feedback_is_verified_but_never_acceptance(self):
        request = self.human_request()
        for index, decision in enumerate(("rejected", "feedback")):
            request["step_id"] = "design-" + str(index)
            self.card(request)
            response = self.response(request, decision=decision, response_text="The contrast needs adjustment.")
            result = self.inbox.import_response(request, response, now=TEST_NOW)
            self.assertEqual(result["status"], decision)
            subject = request["human_gate"]
            evaluated = gates.evaluate_gates(self.runtime, [subject["gate"]], [result["human_receipt"]], subject["context"], stage="after", now=TEST_NOW)
            self.assertFalse(evaluated["satisfied"])

    def test_tampered_human_answer_decision_candidate_and_artifact_cannot_reuse_signature(self):
        request = self.human_request()
        self.card(request)
        original = self.response(request, response_text="The exact appearance was checked.")
        for field, value in (("response", "A different answer."), ("decision", "rejected")):
            with self.subTest(field=field), self.assertRaises(AuthorityError):
                self.inbox.import_response(request, {**original, field: value}, now=TEST_NOW)
        for field, value in (("candidate_sha", "a" * 40), ("artifact_sha256", "b" * 64)):
            changed = deepcopy(request)
            changed["human_gate"]["gate"][field] = value
            if field == "candidate_sha":
                changed["human_gate"]["context"][field] = value
            else:
                changed[field] = value
            self.card(changed)
            with self.assertRaises(approval.ApprovalError):
                self.inbox.import_response(changed, original, now=TEST_NOW)

    def test_negative_operation_decision_has_separate_nonexecuting_human_authority(self):
        self.card()
        response = self.response(decision="rejected", response_text="Keep the task blocked pending prerequisites.")
        self.assertEqual(response["grant"]["payload"]["action"], "human_gate")
        result = self.inbox.import_response(self.request, response, now=TEST_NOW)
        self.assertEqual(result["status"], "rejected")
        self.assertNotIn("grant", result)
        self.assertNotIn("human_receipt", result)

    def test_arbitrary_feedback_cannot_be_attached_to_an_unbound_operation_approval(self):
        self.card()
        with self.assertRaises(approval.ApprovalError):
            self.inbox.export_request(self.request, response_text="Also bypass the missing checks.")

    def test_conflicting_valid_response_requires_new_review_revision(self):
        self.card()
        self.inbox.import_response(self.request, self.response(), now=TEST_NOW)
        before = self.artifact_bytes()
        rejection = self.response(decision="rejected", response_text="I changed my mind.")
        with self.assertRaisesRegex(approval.ApprovalError, "conflicting"):
            self.inbox.import_response(self.request, rejection, now=TEST_NOW)
        self.assertEqual(before, self.artifact_bytes())

    def test_expired_reconciled_response_can_explicitly_reopen_with_new_grant_identity(self):
        initial = self.card()
        self.inbox.import_response(self.request, self.response(), now=TEST_NOW)
        self.assertEqual(self.inbox.find_response(self.request, now=TEST_NOW + 4000)["status"], "invalid")
        reopened = self.inbox.reopen(self.request, now=TEST_NOW + 4000)
        self.assertEqual(reopened["revision"], 2)
        self.assertEqual(reopened["material_sha256"], initial["material_sha256"])
        self.assertNotEqual(reopened["grant_id"], initial["grant_id"])
        self.assertEqual(self.inbox.find_response(self.request, now=TEST_NOW + 4000)["status"], "pending")
        self.auth.now = TEST_NOW + 4000
        renewed = self.response()
        self.enroll_adapter(response=renewed)
        result = self.inbox.operator_issue(self.request, now=TEST_NOW + 4000)
        self.assertTrue(result["verified"])

    def test_rejected_response_can_be_accepted_only_after_explicit_reopen(self):
        self.card()
        rejected = self.response(decision="rejected", response_text="Please wait for my review.")
        self.enroll_adapter(response=rejected)
        self.inbox.operator_issue(self.request, decision="rejected", response_text=rejected["response"], now=TEST_NOW)
        reopened = self.inbox.reopen(self.request, now=TEST_NOW + 10)
        accepted = self.response()
        self.enroll_adapter(response=accepted)
        result = self.inbox.operator_issue(self.request, now=TEST_NOW + 10)
        self.assertEqual(reopened["revision"], 2)
        self.assertEqual(result["status"], "accepted")

    def test_reopen_never_retries_an_uncertain_attempt_even_with_changed_local_decision(self):
        self.card()
        self.enroll_adapter(code="import json, sys\njson.load(sys.stdin)\nraise SystemExit(42)\n")
        with self.assertRaises(approval.ApprovalError):
            self.inbox.operator_issue(self.request, now=TEST_NOW)
        before = self.artifact_bytes()
        with self.assertRaisesRegex(approval.ApprovalError, "reconcile a signed"):
            self.inbox.reopen(self.request, now=TEST_NOW + 10)
        with mock.patch("atlas_approval._invoke_issuer", side_effect=AssertionError("uncertain issuer retry")), \
                self.assertRaisesRegex(approval.ApprovalError, "already attempted"):
            self.inbox.operator_issue(self.request, decision="rejected", response_text="Try a different decision.", now=TEST_NOW)
        self.assertEqual(before, self.artifact_bytes())

    def test_revoked_response_cannot_establish_reconciled_renewal(self):
        self.card()
        response = self.response()
        self.inbox.import_response(self.request, response, now=TEST_NOW)
        self.auth.registry["revoked_grants"] = [response["grant"]["payload"]["grant_id"]]
        self.auth.update_trust()
        with self.assertRaises(AuthorityError):
            self.inbox.reopen(self.request, now=TEST_NOW + 4000)

    def test_schema_type_confusion_and_unsupported_actions_are_rejected(self):
        for delta in ({"schema_version": True}, {"issue_revision": True}, {"issue_revision": 0}, {"action": "deploy"},
                      {"bindings": {}}, {"owner": []}, {"issue_id": "azdo:OTHER:PROJECT:17"}, {"details": []},
                      {"bindings": {"issue_revision": True}}, {"trusted": True}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                approval.validate_request({**self.request, **delta})

    def test_read_input_rejects_duplicate_keys_and_nonfinite_json(self):
        path = self.home / "input.json"
        for raw in ('{"schema_version":1,"schema_version":1}', '{"value":NaN}', '{"value":Infinity}'):
            path.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                approval.read_input(path)

    def test_tampered_stored_request_cannot_change_readable_subject(self):
        card = self.card()
        path = Path(card["artifacts"]["request"])
        value = json.loads(path.read_text())
        value["request"]["owner"] = "someone-else"
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(approval.ApprovalError, "altered"):
            self.inbox.request(card["request_id"])

    def test_concurrent_local_operation_fails_without_wait_or_duplicate_card(self):
        with self.inbox._locked(), self.assertRaisesRegex(approval.ApprovalError, "another approval"):
            approval.ApprovalInbox(self.runtime).prepare(self.request, now=TEST_NOW)
        self.assertEqual(list(self.inbox.root.glob("*.json")), [])
        self.assertEqual(self.card()["revision"], 1)

    def test_symlink_inbox_and_group_writable_runtime_are_rejected(self):
        destination = self.home / "foreign-inbox"
        destination.mkdir(mode=0o700)
        self.inbox.root.symlink_to(destination, target_is_directory=True)
        with self.assertRaises(approval.ApprovalError):
            self.card()
        self.assertEqual(list(destination.iterdir()), [])
        self.inbox.root.unlink()
        self.runtime.chmod(0o770)
        with self.assertRaises(AuthorityError):
            self.card()

    def test_symlink_and_hardlinked_cards_cannot_redirect_reads_or_writes(self):
        card = self.card()
        path = Path(card["artifacts"]["request"])
        preserved = self.home / "preserved.json"
        path.rename(preserved)
        for method in (lambda: path.symlink_to(preserved), lambda: os.link(preserved, path)):
            method()
            with self.assertRaises(approval.ApprovalError):
                self.inbox.request(card["request_id"])
            path.unlink()
        self.assertTrue(preserved.exists())

    def test_missing_or_disabled_issuer_is_actionable_but_never_invoked(self):
        self.card()
        self.assertFalse(self.inbox.issuer_status(self.request)["ready"])
        profile, _ = self.enroll_adapter(code="raise SystemExit(42)\n", enabled=False)
        with mock.patch("atlas_approval._invoke_issuer", side_effect=AssertionError("unsafe issuer invoked")):
            self.assertFalse(self.inbox.issuer_status(self.request)["ready"])
            with self.assertRaises(approval.ApprovalError):
                self.inbox.operator_issue(self.request, now=TEST_NOW)
        self.assertEqual(list(self.inbox.root.glob("*.issuer-intent.json")), [])

    def test_protected_public_profile_must_enroll_exact_owner_policy_and_actions(self):
        self.card()
        baseline, _ = self.enroll_adapter(code="raise SystemExit(42)\n")
        for delta in ({"issuer": "unknown"}, {"actions": ["local_execute"]}, {"timeout_seconds": True},
                      {"timeout_seconds": 61}, {"args": ["--shell"]}, {"actions": ["assess", "assess"]}):
            with self.subTest(delta=delta):
                self.write_profile({**baseline, **delta})
                self.assertFalse(self.inbox.issuer_status(self.request)["ready"])
        self.write_profile(baseline)
        self.auth.registry["issuers"]["test-operator"]["subject"] = "other-owner"
        self.auth.update_trust()
        self.assertFalse(self.inbox.issuer_status(self.request)["ready"])

    def test_issuer_binary_pin_symlinks_writable_ancestry_and_git_markers_fail_closed(self):
        self.card()
        profile, executable = self.enroll_adapter(code="raise SystemExit(42)\n")
        self.assertTrue(self.inbox.issuer_status(self.request)["ready"])
        executable.write_text(executable.read_text() + "# tampered\n")
        self.assertFalse(self.inbox.issuer_status(self.request)["ready"])
        profile["executable_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
        self.write_profile(profile)
        executable.parent.chmod(0o770)
        self.assertFalse(self.inbox.issuer_status(self.request)["ready"])
        executable.parent.chmod(0o700)
        marker = executable.parent / ".git"
        marker.symlink_to(executable.parent / "absent-git")
        self.assertFalse(self.inbox.issuer_status(self.request)["ready"])
        marker.unlink()
        target = executable.with_name("pinned-target")
        executable.rename(target)
        executable.symlink_to(target)
        self.assertFalse(self.inbox.issuer_status(self.request)["ready"])

    def test_profile_cannot_select_another_identity_or_untrusted_temporary_executable(self):
        self.card()
        baseline, _ = self.enroll_adapter(code="raise SystemExit(42)\n")
        for path in ("/home/another-person/bin/issuer", "/root/bin/issuer", "/tmp/untrusted-issuer", "relative-issuer"):
            with self.subTest(path=path):
                self.write_profile({**baseline, "executable": path})
                self.assertFalse(self.inbox.issuer_status(self.request)["ready"])

    def test_system_issuer_parent_symlink_is_rejected_before_descendant_metadata_access(self):
        self.card()
        baseline, _ = self.enroll_adapter(code="raise SystemExit(42)\n")
        parent = Path("/opt/atlas-approval-synthetic-link")
        leaf = parent / "must-not-inspect"
        self.write_profile({**baseline, "executable": str(leaf)})
        original = Path.lstat
        system_owner = Path("/").lstat().st_uid

        def metadata(path, *args, **kwargs):
            if path == leaf:
                raise AssertionError("inspected a descendant before rejecting the parent symlink")
            if path == parent:
                return SimpleNamespace(st_mode=stat.S_IFLNK | 0o755, st_uid=system_owner)
            if path == Path("/opt"):
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=system_owner)
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "lstat", metadata):
            self.assertFalse(self.inbox.issuer_status(self.request)["ready"])

    def test_operator_adapter_uses_real_signed_public_response_fixed_stdio_and_clean_environment(self):
        self.card()
        response = self.response()
        self.enroll_adapter(response=response)
        with mock.patch.dict(os.environ, {"ATLAS_TEST_CREDENTIAL": "nonsecret-test-sentinel", "PYTHONPATH": "unsafe-test-path", "OPENSSL_CONF": "/invalid-test-config"}):
            result = self.inbox.operator_issue(self.request, now=TEST_NOW)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["grant"], response["grant"])
        with mock.patch("atlas_approval._invoke_issuer", side_effect=AssertionError("duplicate adapter launch")), \
                self.assertRaisesRegex(approval.ApprovalError, "already attempted"):
            self.inbox.operator_issue(self.request, now=TEST_NOW)

    def test_uncertain_issuer_attempt_is_durable_and_cannot_automatically_retry(self):
        self.card()
        self.enroll_adapter(code="import json, sys\njson.load(sys.stdin)\nraise SystemExit(42)\n")
        with self.assertRaises(approval.ApprovalError):
            self.inbox.operator_issue(self.request, now=TEST_NOW)
        self.assertEqual(self.inbox.find_response(self.request, now=TEST_NOW)["status"], "pending")
        with mock.patch("atlas_approval._invoke_issuer", side_effect=AssertionError("uncertain adapter replay")), \
                self.assertRaisesRegex(approval.ApprovalError, "already attempted"):
            self.inbox.operator_issue(self.request, now=TEST_NOW)
        self.assertTrue(self.inbox.import_response(self.request, self.response(), now=TEST_NOW)["verified"])

    def test_excessive_or_malformed_adapter_output_is_never_accepted(self):
        self.card()
        scripts = ["import json, sys\njson.load(sys.stdin)\nprint('x' * 300000)\n",
                   "import json, sys\njson.load(sys.stdin)\nprint('{\"approved\":true,\"approved\":true}')\n"]
        for index, code in enumerate(scripts):
            request = {**self.request, "step_id": "bounded-" + str(index)}
            self.card(request)
            self.enroll_adapter(code=code)
            with self.subTest(index=index), self.assertRaises((approval.ApprovalError, AuthorityError)):
                self.inbox.operator_issue(request, now=TEST_NOW)
            self.assertEqual(self.inbox.find_response(request, now=TEST_NOW)["status"], "pending")

    def test_issuer_timeout_is_bounded_without_background_survivor(self):
        self.card()
        profile, _ = self.enroll_adapter(code="import json, sys, time\njson.load(sys.stdin)\ntime.sleep(30)\n")
        with mock.patch("atlas_approval.subprocess.Popen", wraps=subprocess.Popen) as popen, \
                self.assertRaisesRegex(approval.ApprovalError, "timed out"):
            self.inbox.operator_issue(self.request, now=TEST_NOW)
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(self.inbox.find_response(self.request, now=TEST_NOW)["status"], "pending")


class ApprovalCliTests(ApprovalFixture):
    # CLI tests use the same real signature fixtures, with fresh private test
    # material held only by the existing in-memory fixture.
    def config(self):
        source = self.home / "azure.json"
        source.write_text(json.dumps({"schema_version": 1, "provider": "azure-devops", "runtime_dir": str(self.runtime),
            "repository": {"organization": "OWNER", "project": "PROJECT", "name": "REPO",
                           "url": self.request["repository_url"], "base_branch": "develop"},
            "capabilities": ["read"], "models": {"default": {"model": "gpt-6-astra", "reasoning": "max"}},
            "sandbox": "workspace-write", "approval_policy": "on-request"}))
        return source

    def cli(self, args):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = approval.main(["--config", str(self.config()), "--runtime-dir", str(self.runtime), *args])
        return status, json.loads(output.getvalue() or errors.getvalue())

    def test_cli_stored_request_exports_plain_text_human_response_without_manual_json(self):
        request = self.human_request()
        card = self.card(request)
        answer = self.home / "answer.txt"
        answer.write_text("The spacing and color match the intended design.")
        status, result = self.cli(["--request-id", card["request_id"], "--export", "--response-file", str(answer)])
        self.assertEqual(status, 0)
        self.assertEqual(result["response"], answer.read_text())
        self.assertIn("--request-id", result["operator_commands"]["import"])
        self.assertIn("--operator-issue", result["operator_commands"]["request_external_approval"])
        self.assertEqual(result["signing_subject"]["bindings"]["response_sha256"], canonical_digest(answer.read_text()))

    def test_entrypoint_help_without_bytecode_flags_is_inert_in_fresh_copy(self):
        copied = self.home / "source-copy"
        copied.mkdir(mode=0o700)
        for filename in ("atlas-agent-azure-approval", "atlas_approval.py", "atlas_authority.py", "atlas_runtime_config.py", "atlas_human_gates.py"):
            (copied / filename).write_bytes((ROOT / filename).read_bytes())
        before = sorted(str(path.relative_to(copied)) for path in copied.rglob("*"))
        result = subprocess.run([sys.executable, str(copied / "atlas-agent-azure-approval"), "--help"],
                                env={"PATH": "/usr/bin:/bin"}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=copied, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(before, sorted(str(path.relative_to(copied)) for path in copied.rglob("*")))

    def test_cli_reopen_advances_review_without_signing(self):
        card = self.card()
        self.inbox.import_response(self.request, self.response(), now=TEST_NOW)
        with mock.patch("atlas_approval._invoke_issuer", side_effect=AssertionError("reopen invoked issuer")), \
                mock.patch("atlas_approval.time.time", return_value=TEST_NOW + 4000):
            status, result = self.cli(["--request-id", card["request_id"], "--reopen"])
        self.assertEqual(status, 0)
        self.assertEqual(result["revision"], 2)
        self.assertFalse(result["completion"])

    def test_cli_exported_rejection_commands_preserve_the_actual_decision_and_answer(self):
        card = self.card()
        response = "Wait for the current prerequisites to be verified."
        status, result = self.cli(["--request-id", card["request_id"], "--export", "--decision", "rejected", "--response-text", response])
        self.assertEqual(status, 0)
        for command in (result["operator_commands"]["export"], result["operator_commands"]["request_external_approval"]):
            self.assertEqual(command[command.index("--decision") + 1], "rejected")
            self.assertEqual(command[command.index("--response-text") + 1], response)

    def test_cli_preview_ignores_response_file_and_never_accesses_authority_or_creates_inbox(self):
        request_file = self.home / "request.json"
        request_file.write_text(json.dumps(self.request))
        with mock.patch("atlas_approval.verify_grant", side_effect=AssertionError("preview verified auth")), \
                mock.patch("atlas_approval._invoke_issuer", side_effect=AssertionError("preview called issuer")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("preview launched a subprocess")):
            status, result = self.cli(["--request", str(request_file), "--dry-run", "--response-file", str(self.home / "nonexistent-answer")])
        self.assertEqual(status, 0)
        self.assertTrue(result["inert"])
        self.assertFalse(self.inbox.root.exists())

    def test_cli_signed_response_import_by_request_id_never_calls_issuer(self):
        card = self.card()
        response = self.home / "signed-response.json"
        response.write_text(json.dumps(self.response()))
        with mock.patch("atlas_approval._invoke_issuer", side_effect=AssertionError("import invoked issuer")), \
                mock.patch("atlas_approval.time.time", return_value=TEST_NOW):
            status, result = self.cli(["--request-id", card["request_id"], "--import-response", str(response)])
        self.assertEqual(status, 0)
        self.assertTrue(result["verified"])
        self.assertFalse(result["completion"])

    def test_cli_mismatched_provider_repository_fails_before_local_write(self):
        request = {**self.request, "repository_url": "https://dev.azure.com/OWNER/PROJECT/_git/OTHER",
                   "bindings": {**self.request["bindings"], "repository_url": "https://dev.azure.com/OWNER/PROJECT/_git/OTHER"}}
        path = self.home / "request.json"
        path.write_text(json.dumps(request))
        status, result = self.cli(["--request", str(path), "--prepare"])
        self.assertEqual(status, 2)
        self.assertFalse(result["completion"])
        self.assertFalse(self.inbox.root.exists())


if __name__ == "__main__":
    unittest.main()
