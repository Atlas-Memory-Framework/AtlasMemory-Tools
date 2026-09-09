from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(FIXTURES))

import atlas_authority as authority
from authority_fixture import AuthorityFixture, TEST_NOW, TEST_POLICY, canonical_bytes, public_key, sign_envelope


class CanonicalAuthorityTests(unittest.TestCase):
    def test_utf8_sorted_compact_contract_has_independent_hash_oracle(self):
        value = {"z": "é", "a": [1, True, None]}
        expected = hashlib.sha256('{"a":[1,true,null],"z":"é"}'.encode("utf-8")).hexdigest()
        self.assertEqual(expected, authority.canonical_digest(value))

    def test_canonical_hash_preserves_json_types(self):
        values = [True, 1, 1.0, "1", None, [], {}, -0.0, 0]
        self.assertEqual(len(values), len({authority.canonical_digest(value) for value in values}))

    def test_duplicate_keys_are_rejected_at_every_depth(self):
        for text in ('{"x":1,"x":2}', '{"x":{"a":1,"a":1}}', '[{"x":1,"x":1}]'):
            with self.subTest(text=text), self.assertRaises(authority.AuthorityError):
                authority.strict_json_loads(text)

    def test_nonfinite_numbers_rejected_in_python_and_json(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(authority.AuthorityError):
                authority.canonical_digest({"nested": [value]})
        for text in ('{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
            with self.subTest(text=text), self.assertRaises(authority.AuthorityError):
                authority.strict_json_loads(text)

    def test_non_json_types_and_oversized_input_rejected(self):
        for value in ({1: "bad"}, {"x": (1, 2)}, {"x": b"bytes"}, {"x": 2 ** 64}, {"x": "\ud800"}):
            with self.subTest(kind=type(value)), self.assertRaises(authority.AuthorityError):
                authority.canonical_digest(value)
        with self.assertRaises(authority.AuthorityError):
            authority.strict_json_loads(" " * (authority.MAX_JSON_BYTES + 1))

    def test_deep_and_broad_inputs_are_bounded(self):
        value = None
        for _ in range(26):
            value = [value]
        with self.assertRaises(authority.AuthorityError):
            authority.canonical_digest(value)
        with self.assertRaises(authority.AuthorityError):
            authority.canonical_digest([None] * 20_000)


class GrantVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="atlas-authority-test-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.runtime = self.home / "runtime"
        self.runtime.mkdir(mode=0o700)
        identity = mock.patch.object(authority.pwd, "getpwuid", return_value=SimpleNamespace(pw_dir=str(self.home)))
        identity.start()
        self.addCleanup(identity.stop)
        self.fixture = AuthorityFixture(self.runtime, now=TEST_NOW, subject="human:operator")
        self.bindings = {"issue_id": "azdo:EXAMPLE:PROJECT:17", "issue_revision": 3,
                         "candidate_sha": "a" * 40, "runtime_dir": str(self.runtime),
                         "policy_sha256": TEST_POLICY}
        self.envelope = self.fixture.grant("local_execute", self.bindings)

    def verify(self, envelope=None, action="local_execute", bindings=None, *, now=TEST_NOW):
        return authority.verify_grant(self.runtime, self.envelope if envelope is None else envelope,
                                      action, self.bindings if bindings is None else bindings, now=now)

    def test_all_supported_actions_return_authenticated_subject_and_exact_receipt(self):
        for action in sorted(authority.ACTIONS):
            with self.subTest(action=action):
                envelope = self.fixture.grant(action, self.bindings)
                receipt = self.verify(envelope, action)
                self.assertTrue(receipt["verified"])
                self.assertEqual("human:operator", receipt["subject"])
                self.assertEqual(action, receipt["action"])
                self.assertEqual(authority.canonical_digest(self.bindings), receipt["bindings_sha256"])
                self.assertEqual(authority.canonical_digest(envelope), receipt["grant_sha256"])
                self.assertEqual(authority.canonical_digest(self.fixture.registry), receipt["trust_sha256"])
                self.assertNotIn("signature", receipt)
                self.assertNotIn("public_key_pem", receipt)

    def test_raw_strict_json_envelope_supported(self):
        self.assertTrue(self.verify(json.dumps(self.envelope))["verified"])
        self.assertTrue(self.verify(json.dumps(self.envelope).encode("utf-8"))["verified"])

    def test_changed_candidate_payload_fails_real_signature_verification(self):
        envelope = deepcopy(self.envelope)
        envelope["payload"]["bindings"]["candidate_sha"] = "b" * 40
        with self.assertRaisesRegex(authority.AuthorityError, "signature verification failed"):
            self.verify(envelope, bindings=envelope["payload"]["bindings"])

    def test_altered_signature_fails_real_crypto(self):
        envelope = deepcopy(self.envelope)
        signature = bytearray(base64.b64decode(envelope["signature"]))
        signature[-1] ^= 1
        envelope["signature"] = base64.b64encode(signature).decode("ascii")
        with self.assertRaisesRegex(authority.AuthorityError, "signature verification failed"):
            self.verify(envelope)

    def test_issuer_identity_is_covered_by_signature(self):
        self.fixture.registry["issuers"]["other-issuer"] = deepcopy(self.fixture.registry["issuers"]["test-operator"])
        self.fixture.registry["issuers"]["other-issuer"]["subject"] = "different-human"
        public_fixture = json.loads((FIXTURES / "authority-public-rsa.json").read_text(encoding="utf-8"))
        self.fixture.registry["issuers"]["other-issuer"]["public_key_pem"] = public_fixture["public_key_pem"]
        self.fixture.update_trust()
        envelope = deepcopy(self.envelope)
        envelope["issuer"] = "other-issuer"
        with self.assertRaisesRegex(authority.AuthorityError, "signature verification failed"):
            self.verify(envelope)

    def test_legacy_nonempty_approval_record_cannot_authorize(self):
        with self.assertRaises(authority.AuthorityError):
            self.verify({"approval_record": "operator said yes", "actions": ["local_execute"]})

    def test_unknown_fields_in_envelope_and_payload_fail_closed(self):
        for location in ("envelope", "payload"):
            envelope = deepcopy(self.envelope)
            target = envelope if location == "envelope" else envelope["payload"]
            target["trust_registry"] = "/tmp/self-selected-trust.json"
            with self.subTest(location=location), self.assertRaises(authority.AuthorityError):
                self.verify(envelope)

    def test_schema_and_time_booleans_cannot_impersonate_integers(self):
        for location, key in (("envelope", "schema"), ("payload", "schema"),
                              ("payload", "issued_at"), ("payload", "not_before"), ("payload", "expires_at")):
            envelope = deepcopy(self.envelope)
            target = envelope if location == "envelope" else envelope["payload"]
            target[key] = True
            with self.subTest(location=location, key=key), self.assertRaises(authority.AuthorityError):
                self.verify(envelope)

    def test_exact_bindings_reject_missing_extra_and_changed_fields(self):
        for bindings in ({**self.bindings, "issue_revision": True}, {**self.bindings, "issue_revision": 3.0},
                         {**self.bindings, "issue_revision": 4}, {**self.bindings, "extra": "scope"},
                         {key: value for key, value in self.bindings.items() if key != "candidate_sha"}):
            with self.subTest(bindings=bindings), self.assertRaisesRegex(authority.AuthorityError, "exact typed"):
                self.verify(bindings=bindings)

    def test_action_cannot_be_replayed_or_widened(self):
        with self.assertRaisesRegex(authority.AuthorityError, "requested action"):
            self.verify(action="draft_pr")
        for action in ("merge", "deploy", "approve", "pipeline_run", "*", True, None):
            with self.subTest(action=action), self.assertRaises(authority.AuthorityError):
                self.verify(action=action)

    def test_unsupported_or_malformed_signature_algorithm_is_rejected(self):
        for value in ("none", "hmac-sha256", "rsa-sha1", True):
            envelope = deepcopy(self.envelope)
            envelope["algorithm"] = value
            with self.subTest(value=value), self.assertRaises(authority.AuthorityError):
                self.verify(envelope)

    def test_signature_encoding_and_size_are_bounded(self):
        for value in ("", "!!!!", "a" * 3000, base64.b64encode(b"too short").decode(), True):
            envelope = deepcopy(self.envelope)
            envelope["signature"] = value
            with self.subTest(value_type=type(value)), self.assertRaises(authority.AuthorityError):
                self.verify(envelope)

    def test_not_yet_valid_and_expired_grants_rejected_at_boundaries(self):
        payload = self.envelope["payload"]
        with self.assertRaises(authority.AuthorityError):
            self.verify(now=payload["not_before"] - 0.001)
        self.assertTrue(self.verify(now=payload["not_before"])["verified"])
        with self.assertRaises(authority.AuthorityError):
            self.verify(now=payload["expires_at"])

    def test_invalid_and_excessive_validity_windows_rejected(self):
        windows = ({"issued_at": TEST_NOW + 1}, {"expires_at": TEST_NOW - 100},
                   {"expires_at": TEST_NOW + authority.MAX_GRANT_SECONDS + 1},
                   {"not_before": TEST_NOW - 100}, {"issued_at": -1})
        for values in windows:
            with self.subTest(values=values), self.assertRaises(authority.AuthorityError):
                self.verify(self.fixture.grant("local_execute", self.bindings, **values))

    def test_verification_clock_rejects_bool_nan_and_naive_datetime(self):
        for now in (True, math.nan, math.inf, -1, "1800000000", datetime(2027, 1, 1)):
            with self.subTest(now_type=type(now)), self.assertRaises(authority.AuthorityError):
                self.verify(now=now)
        self.assertTrue(self.verify(now=datetime.fromtimestamp(TEST_NOW, timezone.utc))["verified"])

    def test_grant_expiring_during_crypto_is_not_accepted(self):
        with mock.patch.object(authority.time, "time", side_effect=[TEST_NOW, TEST_NOW + 3600]):
            with self.assertRaisesRegex(authority.AuthorityError, "expired during"):
                self.verify(now=None)

    def test_numeric_caller_clock_cannot_hide_expiry_during_signature_verification(self):
        with mock.patch.object(authority.time, "monotonic", side_effect=[100.0, 3700.0]):
            with self.assertRaisesRegex(authority.AuthorityError, "expired during"):
                self.verify(now=TEST_NOW)

    def test_runtime_and_policy_are_pinned_outside_caller_bindings(self):
        for field, value in (("runtime_dir", str(self.runtime / "elsewhere")), ("policy_sha256", "e" * 64)):
            envelope = self.fixture.grant("local_execute", self.bindings, **{field: value})
            with self.subTest(field=field), self.assertRaises(authority.AuthorityError):
                self.verify(envelope)

    def test_legacy_bindings_without_policy_still_require_trusted_governance_digest(self):
        bindings = {"packet_sha256": "a" * 64}
        valid = self.fixture.grant("local_execute", bindings)
        self.assertTrue(self.verify(valid, bindings=bindings)["verified"])
        changed = self.fixture.grant("local_execute", bindings, policy_sha256="e" * 64)
        with self.assertRaisesRegex(authority.AuthorityError, "operator-trusted policy"):
            self.verify(changed, bindings=bindings)

    def test_runtime_binding_inside_operation_cannot_disagree(self):
        bindings = {**self.bindings, "runtime_dir": str(self.home / "other-runtime")}
        with self.assertRaisesRegex(authority.AuthorityError, "operation runtime"):
            self.verify(self.fixture.grant("local_execute", bindings), bindings=bindings)

    def test_unknown_revoked_or_insufficient_issuer_rejected(self):
        cases = ("unknown", "revoked", "unauthorized")
        original = deepcopy(self.fixture.registry)
        for case in cases:
            self.fixture.registry = deepcopy(original)
            envelope = deepcopy(self.envelope)
            if case == "unknown":
                envelope["issuer"] = "unknown-issuer"
            elif case == "revoked":
                self.fixture.registry["issuers"]["test-operator"]["revoked"] = True
            else:
                self.fixture.registry["issuers"]["test-operator"]["actions"] = ["assess"]
            self.fixture.update_trust()
            with self.subTest(case=case), self.assertRaisesRegex(authority.AuthorityError, "issuer is"):
                self.verify(envelope)

    def test_one_key_cannot_impersonate_two_distinct_human_subjects(self):
        second = deepcopy(self.fixture.registry["issuers"]["test-operator"])
        second["subject"] = "another-human"
        self.fixture.registry["issuers"]["second-operator"] = second
        self.fixture.update_trust()
        with self.assertRaisesRegex(authority.AuthorityError, "distinct human subjects"):
            self.verify()

    def test_revocation_is_reloaded_and_cannot_be_cached_away(self):
        self.assertTrue(self.verify()["verified"])
        self.fixture.registry["revoked_grants"] = [self.envelope["payload"]["grant_id"]]
        self.fixture.update_trust()
        with self.assertRaisesRegex(authority.AuthorityError, "revoked"):
            self.verify()

    def test_trust_change_during_crypto_is_rejected(self):
        original = authority._verify_signature

        def verify_then_revoke(*args):
            original(*args)
            self.fixture.registry["revoked_grants"] = [self.envelope["payload"]["grant_id"]]
            self.fixture.update_trust()

        with mock.patch.object(authority, "_verify_signature", side_effect=verify_then_revoke):
            with self.assertRaisesRegex(authority.AuthorityError, "trust changed"):
                self.verify()

    def test_trust_schema_scope_and_typed_revocation_fail_closed(self):
        mutations = [lambda t: t.update(schema=True), lambda t: t.update(runtime_dir=str(self.home)),
                     lambda t: t.update(policy_sha256="bad"), lambda t: t.update(unexpected=True),
                     lambda t: t.update(revoked_grants=[True]),
                     lambda t: t.update(revoked_grants=["same", "same"]),
                     lambda t: t["issuers"]["test-operator"].update(revoked=0),
                     lambda t: t["issuers"]["test-operator"].update(actions=["assess", "assess"]),
                     lambda t: t["issuers"]["test-operator"].update(actions=["merge"]),
                     lambda t: t["issuers"]["test-operator"].update(subject=""),
                     lambda t: t["issuers"]["test-operator"].update(subject="operator\nforged")]
        original = deepcopy(self.fixture.registry)
        for number, mutate in enumerate(mutations):
            self.fixture.registry = deepcopy(original)
            mutate(self.fixture.registry)
            self.fixture.update_trust()
            with self.subTest(number=number), self.assertRaises(authority.AuthorityError):
                self.verify()

    def test_duplicate_keys_in_trust_and_envelope_are_rejected(self):
        path = self.runtime / "authority" / "trust.json"
        path.write_text(json.dumps(self.fixture.registry).replace('"schema": 1', '"schema": 1, "schema": 1', 1))
        with self.assertRaisesRegex(authority.AuthorityError, "duplicate"):
            self.verify()
        self.fixture.update_trust()
        envelope = json.dumps(self.envelope).replace('"schema": 1', '"schema": 1, "schema": 1', 1)
        with self.assertRaisesRegex(authority.AuthorityError, "duplicate"):
            self.verify(envelope)

    def test_missing_registry_and_missing_verifier_fail_closed_without_installation(self):
        path = self.runtime / "authority" / "trust.json"
        path.rename(path.with_suffix(".saved"))
        before = sorted(str(p.relative_to(self.runtime)) for p in self.runtime.rglob("*"))
        with self.assertRaises(authority.AuthorityError):
            self.verify()
        self.assertEqual(before, sorted(str(p.relative_to(self.runtime)) for p in self.runtime.rglob("*")))
        path.with_suffix(".saved").rename(path)
        with mock.patch.object(authority, "OPENSSL", "/nonexistent-atlas-verifier"):
            with self.assertRaises(authority.AuthorityError):
                self.verify()

    def test_registry_rejects_nonpublic_weak_and_non_rsa_keys(self):
        values = ["-----BEGIN PRIVATE KEY-----\nNOT-A-KEY\n-----END PRIVATE KEY-----\n",
                  "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n",
                  public_key(bits=1024), public_key(kind="EC"), public_key() + "trailing text"]
        for number, value in enumerate(values):
            self.fixture.registry["issuers"]["test-operator"]["public_key_pem"] = value
            self.fixture.update_trust()
            with self.subTest(number=number), self.assertRaises(authority.AuthorityError):
                self.verify()

    def test_verifier_process_is_fixed_bounded_and_environment_sanitized(self):
        run = subprocess.run
        calls = []

        def capture(*args, **kwargs):
            calls.append((args, kwargs))
            return run(*args, **kwargs)

        with mock.patch.dict(os.environ, {"OPENSSL_CONF": "/unsafe/config", "LD_PRELOAD": "/unsafe/library", "PATH": "/unsafe"}):
            with mock.patch.object(authority.subprocess, "run", side_effect=capture):
                self.assertTrue(self.verify()["verified"])
        self.assertEqual(1, len(calls))
        argv, options = calls[0][0][0], calls[0][1]
        self.assertEqual(["/usr/bin/openssl", "dgst", "-sha256", "-verify"], argv[:4])
        self.assertEqual("/dev/null", options["env"]["OPENSSL_CONF"])
        self.assertNotIn("LD_PRELOAD", options["env"])
        self.assertEqual(5, options["timeout"])
        self.assertEqual(subprocess.DEVNULL, options["stdout"])
        self.assertEqual(subprocess.DEVNULL, options["stderr"])
        self.assertEqual("/", options["cwd"])
        self.assertNotIn("shell", options)

    def test_verifier_failure_and_timeout_expose_no_process_output(self):
        errors = [subprocess.TimeoutExpired("untrusted-value", 5, output=b"MUST_NOT_APPEAR"), OSError("MUST_NOT_APPEAR")]
        for error in errors:
            with mock.patch.object(authority.subprocess, "run", side_effect=error):
                with self.assertRaises(authority.AuthorityError) as raised:
                    self.verify()
                self.assertNotIn("MUST_NOT_APPEAR", str(raised.exception))
                self.assertNotIn("untrusted-value", str(raised.exception))

    def test_current_identity_owned_verifier_is_not_trusted_as_a_system_binary(self):
        original = Path.lstat

        def replaced_executable(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == Path("/usr/bin/openssl"):
                return SimpleNamespace(st_mode=info.st_mode, st_uid=os.getuid())
            return info

        if os.getuid() == Path("/").lstat().st_uid:
            self.skipTest("this ownership attack requires a distinct unprivileged identity")
        with mock.patch.object(Path, "lstat", replaced_executable):
            with self.assertRaisesRegex(authority.AuthorityError, "verifier is unavailable or unsafe"):
                self.verify()

    def test_authorization_verification_creates_no_files(self):
        before = {str(p.relative_to(self.home)): (p.stat().st_mtime_ns, p.stat().st_size)
                  for p in self.home.rglob("*")}
        self.assertTrue(self.verify()["verified"])
        after = {str(p.relative_to(self.home)): (p.stat().st_mtime_ns, p.stat().st_size)
                 for p in self.home.rglob("*")}
        self.assertEqual(before, after)

    def test_caller_cannot_select_its_own_trust_registry(self):
        with self.assertRaises(TypeError):
            authority.verify_grant(self.runtime, self.envelope, "local_execute", self.bindings,
                                   now=TEST_NOW, trust_registry=self.runtime / "authority" / "trust.json")


class AuthorityPathTests(GrantVerificationTests):
    # Path-specific methods inherit the realistic fixture, while unittest avoids
    # duplicate execution of inherited cases below by selecting owned methods.
    def test_runtime_must_be_current_identity_absolute_existing_and_outside_worktrees(self):
        for path in ("", "relative/runtime", self.home, self.home / "missing", self.home.parent,
                     self.runtime / ".." / "runtime", self.runtime / "worktrees" / "job"):
            if str(path).endswith("worktrees/job"):
                path.mkdir(parents=True)
            with self.subTest(path=str(path)), self.assertRaises(authority.AuthorityError):
                authority.verify_grant(path, self.envelope, "local_execute", self.bindings, now=TEST_NOW)

    def test_symlink_in_runtime_ancestry_is_rejected(self):
        alias = self.home / "alias"
        alias.symlink_to(self.runtime, target_is_directory=True)
        envelope = self.fixture.grant("local_execute", {"packet_sha256": "a" * 64}, runtime_dir=str(alias))
        with self.assertRaises(authority.AuthorityError):
            authority.verify_grant(alias, envelope, "local_execute", {"packet_sha256": "a" * 64}, now=TEST_NOW)

    def test_linked_git_worktree_ancestor_is_rejected(self):
        (self.home / ".git").write_text("gitdir: ignored-public-marker\n")
        with self.assertRaisesRegex(authority.AuthorityError, "linked Git worktree"):
            self.verify()

    def test_ordinary_git_checkout_ancestor_is_rejected(self):
        (self.home / ".git").mkdir(mode=0o700)
        with self.assertRaisesRegex(authority.AuthorityError, "Git checkout"):
            self.verify()

    def test_symlinked_authority_directory_and_registry_are_rejected(self):
        directory = self.runtime / "authority"
        public_copy = self.runtime / "public-copy"
        directory.rename(public_copy)
        directory.symlink_to(public_copy, target_is_directory=True)
        with self.assertRaises(authority.AuthorityError):
            self.verify()
        directory.unlink()
        public_copy.rename(directory)
        path = directory / "trust.json"
        saved = directory / "public-copy.json"
        path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaises(authority.AuthorityError):
            self.verify()

    def test_group_writable_registry_and_authority_directory_are_rejected(self):
        path = self.runtime / "authority" / "trust.json"
        path.chmod(0o660)
        with self.assertRaises(authority.AuthorityError):
            self.verify()
        path.chmod(0o600)
        path.parent.chmod(0o770)
        with self.assertRaises(authority.AuthorityError):
            self.verify()

    def test_group_or_world_writable_runtime_ancestry_cannot_replace_trust(self):
        for directory in (self.runtime, self.home):
            for mode in (0o770, 0o707):
                directory.chmod(mode)
                with self.subTest(directory=directory.name, mode=mode), self.assertRaises(authority.AuthorityError):
                    self.verify()
                directory.chmod(0o700)

    def test_hardlinked_registry_is_rejected(self):
        path = self.runtime / "authority" / "trust.json"
        os.link(path, path.with_suffix(".link"))
        with self.assertRaises(authority.AuthorityError):
            self.verify()

    def test_fifo_registry_is_rejected_without_blocking(self):
        path = self.runtime / "authority" / "trust.json"
        path.rename(path.with_suffix(".saved"))
        os.mkfifo(path, mode=0o600)
        with self.assertRaises(authority.AuthorityError):
            self.verify()

    def test_wrong_owner_runtime_and_registry_are_rejected(self):
        original_lstat = Path.lstat

        def altered_lstat(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            if path == self.runtime:
                return SimpleNamespace(st_mode=info.st_mode, st_uid=os.getuid() + 1)
            return info

        with mock.patch.object(Path, "lstat", altered_lstat):
            with self.assertRaises(authority.AuthorityError):
                self.verify()
        original_fstat = os.fstat

        def altered_fstat(descriptor):
            info = original_fstat(descriptor)
            if stat.S_ISREG(info.st_mode):
                return SimpleNamespace(st_mode=info.st_mode, st_uid=os.getuid() + 1)
            return info

        with mock.patch.object(authority.os, "fstat", side_effect=altered_fstat):
            with self.assertRaises(authority.AuthorityError):
                self.verify()

    def test_registry_change_during_read_fails_closed(self):
        original = os.fstat
        reads = 0

        def changing_fstat(descriptor):
            nonlocal reads
            info = original(descriptor)
            if stat.S_ISREG(info.st_mode):
                reads += 1
                if reads == 2:
                    return SimpleNamespace(st_ino=info.st_ino, st_size=info.st_size,
                                           st_mtime_ns=info.st_mtime_ns + 1, st_ctime_ns=info.st_ctime_ns)
            return info

        with mock.patch.object(authority.os, "fstat", side_effect=changing_fstat):
            with self.assertRaisesRegex(authority.AuthorityError, "changed during verification"):
                self.verify()


class StaticPublicSignatureTests(unittest.TestCase):
    def test_committed_public_fixture_verifies_and_altered_signature_does_not(self):
        fixture = json.loads((FIXTURES / "authority-public-rsa.json").read_text(encoding="utf-8"))
        message = {key: value for key, value in fixture["envelope"].items() if key != "signature"}
        self.assertEqual(fixture["signed_message_sha256"], hashlib.sha256(canonical_bytes(message)).hexdigest())
        public, _ = authority._rsa_public_key(fixture["public_key_pem"])
        signature = base64.b64decode(fixture["envelope"]["signature"])
        authority._verify_signature(public, signature, canonical_bytes(message))
        changed = signature[:-1] + bytes([signature[-1] ^ 1])
        with self.assertRaises(authority.AuthorityError):
            authority._verify_signature(public, changed, canonical_bytes(message))


def load_tests(loader, tests, pattern):
    # Reuse setup/assertion helpers without counting the inherited grant cases
    # twice. Each adversarial behavior runs once.
    suite = unittest.TestSuite()
    for case in (CanonicalAuthorityTests, GrantVerificationTests, AuthorityPathTests, StaticPublicSignatureTests):
        for name, method in vars(case).items():
            if name.startswith("test_") and callable(method):
                suite.addTest(case(name))
    return suite


if __name__ == "__main__":
    unittest.main()
