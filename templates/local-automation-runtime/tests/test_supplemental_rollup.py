"""Synthetic fixtures for the pure foundation, never production case admission."""

import builtins
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import unittest
from unittest import mock
import uuid


SOURCE = Path(__file__).resolve().parents[1] / "atlas_supplemental_rollup.py"
SPEC = importlib.util.spec_from_file_location("supplemental_rollup_under_test", SOURCE)
rollup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollup)

# Literal JSON lets an independent tool reproduce the digest without running the
# assessor or its validation/canonicalization helpers. No fixture enters source.
FIXTURE_JSON = r'''{
  "schema_version": "atlas.supplemental-rollup-facts.v1",
  "binding": {
    "case_id": "SYNTHETIC-S1",
    "work_item_id": "SYNTHETIC:ROLLUP-1",
    "operator_owner": "operator:synthetic",
    "worker_thread_id": "00000000-0000-0000-0000-000000000001",
    "failed_handoff_id": "00000000-0000-0000-0000-000000000002",
    "failed_invocation_id": "00000000-0000-0000-0000-000000000003",
    "failed_result_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "failure_evidence_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "spec_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "context_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "contract_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "revision": "ffffffffffffffffffffffffffffffffffffffff",
    "source_file_sha256": {
      "src/a.py": "1111111111111111111111111111111111111111111111111111111111111111",
      "tests/test_a.py": "2222222222222222222222222222222222222222222222222222222222222222"
    },
    "prior_result_sha256": {
      "implementation": "3333333333333333333333333333333333333333333333333333333333333333",
      "test-runner": "4444444444444444444444444444444444444444444444444444444444444444",
      "code-review": "5555555555555555555555555555555555555555555555555555555555555555",
      "semantic-alignment": "6666666666666666666666666666666666666666666666666666666666666666"
    }
  },
  "failure_kind": "capture_helper_parse_failure",
  "work_item_state": "blocked",
  "failed_role": "evidence-rollup",
  "failed_result_status": "blocked",
  "handoff_consumed": true,
  "rework_count": 1,
  "pending_handoff": false,
  "process_uncertainty": false,
  "supplemental_count": 0,
  "requested_operator_owner": "operator:synthetic",
  "requested_worker_thread_id": "00000000-0000-0000-0000-000000000001",
  "prior_roles": {
    "implementation": {"status": "complete", "outputs_complete": true, "contract_issues": []},
    "test-runner": {"status": "complete", "outputs_complete": true, "contract_issues": []},
    "code-review": {"status": "complete", "outputs_complete": true, "contract_issues": []},
    "semantic-alignment": {"status": "complete", "outputs_complete": true, "contract_issues": []}
  },
  "goal_review": {
    "verdict": "pass", "reason_nonempty": true, "evidence_nonempty": true,
    "context_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "contract_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
  },
  "started_epoch_seconds": 100,
  "deadline_epoch_seconds": 1000
}'''
EXPECTED_DIGEST = "b70f1ba685f263b228a05e87b191f43475c93a6b2df2df05a8aee766a9945476"
ROLES = ("implementation", "test-runner", "code-review", "semantic-alignment")
REASONS = {
    "unknown_case", "invalid_disposition", "invalid_facts", "binding_mismatch",
    "wrong_item_state", "wrong_failed_role", "wrong_failed_result_status",
    "unconsumed_handoff", "rework_count_mismatch", "pending_handoff",
    "process_uncertainty", "supplemental_already_used", "owner_mismatch",
    "not_helper_failure", "prior_roles_not_complete", "goal_not_pass",
    "goal_binding_mismatch", "budget_invalid_or_expired",
}


def fixture():
    facts = json.loads(FIXTURE_JSON)
    disposition = {
        "schema_version": "atlas.supplemental-rollup-source-disposition.v1",
        "binding": copy.deepcopy(facts["binding"]),
        "failure_kind": facts["failure_kind"],
        "review_evidence_sha256": {name: "7" * 64 for name in ("code", "security", "protocol", "goal")},
    }
    return facts, disposition


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


def dict_nodes(value):
    if type(value) is dict:
        yield value
        for child in value.values():
            yield from dict_nodes(child)


class SupplementalRollupTests(unittest.TestCase):
    def assess(self, facts, disposition, now=101):
        result = rollup.assess_supplemental_rollup(facts, disposition, now_epoch_seconds=now)
        self.assertEqual(set(result), {"schema_version", "status", "reason_codes", "facts_sha256", "case_id"})
        self.assertEqual(result["schema_version"], "atlas.supplemental-rollup-assessment.v1")
        self.assertEqual(result["reason_codes"], sorted(set(result["reason_codes"])))
        self.assertLess(len(canonical(result)), 1024)
        self.assertTrue(set(result["reason_codes"]) <= REASONS)
        self.assertEqual(result["status"], "refused" if result["reason_codes"] else "eligible")
        return result

    def reasons(self, facts, disposition, *expected, now=101):
        result = self.assess(facts, disposition, now)
        self.assertEqual(result["reason_codes"], sorted(expected))
        return result

    def test_literal_digest_exact_output_and_unregistered_trust_boundary(self):
        facts, disposition = fixture()
        self.assertEqual(rollup.SOURCE_SUPPLEMENTAL_ROLLUP_CASES_V1, {})
        self.assertEqual(self.assess(facts, disposition), {
            "schema_version": "atlas.supplemental-rollup-assessment.v1",
            "status": "eligible", "reason_codes": [],
            "facts_sha256": EXPECTED_DIGEST, "case_id": "SYNTHETIC-S1",
        })
        self.assertEqual(hashlib.sha256(canonical(facts)).hexdigest(), EXPECTED_DIGEST)
        reversed_facts = dict(reversed(list(facts.items())))
        self.assertEqual(self.assess(reversed_facts, disposition), self.assess(facts, disposition))

    def test_every_binding_scalar_and_map_entry_drift(self):
        original, disposition = fixture()
        for key, value in original["binding"].items():
            if type(value) is dict:
                for entry in value:
                    with self.subTest(key=key, entry=entry):
                        facts = copy.deepcopy(original)
                        facts["binding"][key][entry] = "9" * 64
                        self.assertIn("binding_mismatch", self.assess(facts, disposition)["reason_codes"])
            else:
                with self.subTest(key=key):
                    facts = copy.deepcopy(original)
                    if key == "case_id":
                        drift = "SYNTHETIC-S2"
                    elif key == "work_item_id":
                        drift = "OTHER:ITEM"
                    elif key == "operator_owner":
                        drift = "operator:other"
                    elif key.endswith("_id"):
                        drift = "ffffffff-ffff-ffff-ffff-ffffffffffff"
                    else:
                        drift = "9" * len(value)
                    facts["binding"][key] = drift
                    self.assertIn("binding_mismatch", self.assess(facts, disposition)["reason_codes"])
        # Map key and membership changes also bind, not just map values.
        for mapping in ({"different.py": "1" * 64}, {"src/a.py": "1" * 64}):
            facts = copy.deepcopy(original)
            facts["binding"]["source_file_sha256"] = mapping
            self.reasons(facts, disposition, "binding_mismatch")

    def test_each_independent_semantic_gate(self):
        changes = (
            ("work_item_state", "ready", "wrong_item_state"),
            ("failed_role", "implementation", "wrong_failed_role"),
            ("failed_result_status", "failed", "wrong_failed_result_status"),
            ("handoff_consumed", False, "unconsumed_handoff"),
            ("rework_count", 0, "rework_count_mismatch"),
            ("rework_count", 2, "rework_count_mismatch"),
            ("pending_handoff", True, "pending_handoff"),
            ("process_uncertainty", True, "process_uncertainty"),
            ("supplemental_count", 1, "supplemental_already_used"),
            ("requested_operator_owner", "operator:other", "owner_mismatch"),
            ("requested_worker_thread_id", "ffffffff-ffff-ffff-ffff-ffffffffffff", "owner_mismatch"),
        )
        for key, value, reason in changes:
            with self.subTest(key=key, value=value):
                facts, disposition = fixture()
                facts[key] = value
                self.reasons(facts, disposition, reason)

    def test_original_source_owner_cannot_be_rebound_through_facts(self):
        for field, requested, drift in (
            ("operator_owner", "requested_operator_owner", "operator:other"),
            ("worker_thread_id", "requested_worker_thread_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
        ):
            facts, disposition = fixture()
            facts["binding"][field] = drift
            # A facts-only drift has not changed the original requested owner.
            self.reasons(facts, disposition, "binding_mismatch")
            facts[requested] = drift
            self.reasons(facts, disposition, "binding_mismatch", "owner_mismatch")

    def test_helper_classification_is_semantic_and_all_three_are_supported(self):
        helpers = ("capture_helper_parse_failure", "capture_helper_path_failure",
                   "capture_helper_serialization_failure")
        for kind in helpers:
            facts, disposition = fixture()
            facts["failure_kind"] = disposition["failure_kind"] = kind
            self.reasons(facts, disposition)
        for kind in ("test_failure", "source_failure", "goal_failure", "", "PRIVATE_SENTINEL", helpers[1]):
            facts, disposition = fixture()
            facts["failure_kind"] = kind
            self.reasons(facts, disposition, "not_helper_failure")
        facts, disposition = fixture()
        disposition["failure_kind"] = "test_failure"
        self.reasons(facts, disposition, "not_helper_failure")
        facts["failure_kind"] = "test_failure"
        self.reasons(facts, disposition, "not_helper_failure")

    def test_prior_roles_and_goal(self):
        for name in ROLES:
            for field, value in (("status", "blocked"), ("outputs_complete", False),
                                 ("contract_issues", ["PRIVATE_ISSUE_SENTINEL"])):
                facts, disposition = fixture()
                facts["prior_roles"][name][field] = value
                result = self.reasons(facts, disposition, "prior_roles_not_complete")
                self.assertNotIn("PRIVATE_ISSUE_SENTINEL", json.dumps(result))
        for field, value in (("verdict", "fail"), ("verdict", "inconclusive"),
                             ("verdict", ""), ("reason_nonempty", False), ("evidence_nonempty", False)):
            facts, disposition = fixture()
            facts["goal_review"][field] = value
            self.reasons(facts, disposition, "goal_not_pass")
        for field in ("context_sha256", "contract_sha256"):
            facts, disposition = fixture()
            facts["goal_review"][field] = "9" * 64
            self.reasons(facts, disposition, "goal_binding_mismatch")

    def test_budget_boundaries(self):
        for start, deadline, now, eligible in (
            (100, 1000, 100, True), (100, 1000, 999, True),
            (100, 1000, 99, False), (100, 1000, 1000, False),
            (100, 1000, 1001, False), (100, 100, 100, False),
            (101, 100, 100, False), (100, 1001, 101, False),
            (0, 1, 0, True), ((1 << 63) - 2, (1 << 63) - 1, (1 << 63) - 2, True),
        ):
            with self.subTest(start=start, deadline=deadline, now=now):
                facts, disposition = fixture()
                facts.update(started_epoch_seconds=start, deadline_epoch_seconds=deadline)
                self.reasons(facts, disposition, *([] if eligible else ["budget_invalid_or_expired"]), now=now)
        for now in (True, -1, 1 << 63, 101.0, float("nan"), float("inf"), "101", None, [], {}):
            facts, disposition = fixture()
            result = self.reasons(facts, disposition, "budget_invalid_or_expired", now=now)
            self.assertEqual(result["facts_sha256"], EXPECTED_DIGEST)

    def test_every_dict_rejects_missing_and_unknown_keys(self):
        for side in (0, 1):
            originals = fixture()
            for index, node in enumerate(dict_nodes(originals[side])):
                for key in node:
                    values = fixture()
                    target = list(dict_nodes(values[side]))[index]
                    del target[key]
                    with self.subTest(side=side, missing=key, index=index):
                        result = self.assess(*values)
                        # File-map membership is variable (1..4), unlike
                        # every fixed schema object. Removing one of two files
                        # is valid structure but a binding mismatch.
                        expected = ("binding_mismatch" if node is originals[side]["binding"]["source_file_sha256"]
                                    else "invalid_facts" if side == 0 else "invalid_disposition")
                        self.assertEqual(result["reason_codes"], [expected])
                values = fixture()
                list(dict_nodes(values[side]))[index]["EXTRA_PRIVATE_SENTINEL"] = True
                result = self.assess(*values)
                self.assertEqual(result["reason_codes"], ["invalid_facts" if side == 0 else "invalid_disposition"])

    def test_strict_primitive_types_and_bounds(self):
        bad_fields = {
            "schema_version": [False, [], {}, None],
            "binding": [[], None],
            "failure_kind": [1, "x" * 65, "é"],
            "work_item_state": [None, True, "x" * 33, "é"],
            "failed_role": [[], "x" * 33], "failed_result_status": [1, "é"],
            "handoff_consumed": [0, 1, "true"], "pending_handoff": [0], "process_uncertainty": [1],
            "rework_count": [True, -1, 1 << 63, 1.0, float("nan"), float("inf")],
            "supplemental_count": [False, -1, 1 << 63],
            "started_epoch_seconds": [True, -1, 1 << 63],
            "deadline_epoch_seconds": [False, -1, 1 << 63],
            "requested_operator_owner": ["", "é", "a" * 257, "x\n", "/owner"],
            "requested_worker_thread_id": ["A" * 36, "00000000-0000-0000-0000-00000000000g"],
            "prior_roles": [[], None], "goal_review": [[], None],
        }
        for key, candidates in bad_fields.items():
            for value in candidates:
                facts, disposition = fixture()
                facts[key] = value
                result = self.reasons(facts, disposition, "invalid_facts")
                self.assertIsNone(result["facts_sha256"])
        for field, values in {
            "case_id": ["", "a", "A" * 97, "Ａ", "A\n"],
            "work_item_id": ["", "-bad", "a" * 129, "é"],
            "operator_owner": ["", "a" * 257, "x\t"],
            "worker_thread_id": ["00000000-0000-0000-0000-00000000000A", "x"],
            "revision": ["a" * 39, "a" * 41, "a" * 63, "A" * 40],
            "spec_sha256": ["A" * 64, "é" * 64, "a" * 63, None],
        }.items():
            for value in values:
                facts, disposition = fixture()
                facts["binding"][field] = value
                self.reasons(facts, disposition, "invalid_facts")
        facts, disposition = fixture()
        facts["binding"]["revision"] = disposition["binding"]["revision"] = "f" * 64
        # IDs intentionally do not impose UUID version/variant semantics.
        facts["binding"]["worker_thread_id"] = disposition["binding"]["worker_thread_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        facts["requested_worker_thread_id"] = facts["binding"]["worker_thread_id"]
        self.reasons(facts, disposition)

    def test_paths_digest_maps_and_boundaries(self):
        for path in ("", "/a", "a/", "a//b", ".", "..", "a/./b", "a/../b", "a\\b",
                     "a\x00b", "a\x1fb", "a\x7fb", "é", "a" * 257):
            facts, disposition = fixture()
            facts["binding"]["source_file_sha256"] = {path: "a" * 64}
            self.reasons(facts, disposition, "invalid_facts")
        for files in ({}, {str(i): "a" * 64 for i in range(5)}, {"a": "A" * 64}, {1: "a" * 64}):
            facts, disposition = fixture()
            disposition["binding"]["source_file_sha256"] = files
            self.reasons(facts, disposition, "invalid_disposition")
        facts, disposition = fixture()
        files = {"a" * 256: "1" * 64, "b/c": "2" * 64, "d": "3" * 64, "e": "4" * 64}
        facts["binding"]["source_file_sha256"] = copy.deepcopy(files)
        disposition["binding"]["source_file_sha256"] = files
        self.reasons(facts, disposition)
        for name in ("code", "security", "protocol", "goal"):
            facts, disposition = fixture()
            disposition["review_evidence_sha256"][name] = "9" * 63
            self.reasons(facts, disposition, "invalid_disposition")

    def test_issue_utf8_controls_and_collection_bounds(self):
        for issues, valid in (([], True), (["é" * 128], True), (["é" * 129], False),
                              (["x" * 256], True), (["x" * 257], False),
                              (["x"] * 16, True), (["x"] * 17, False), ([""], False),
                              (["x\n"], False), (["x\x85"], False), (["\ud800"], False),
                              (("x",), False), ([1], False), ([{}], False)):
            facts, disposition = fixture()
            facts["prior_roles"]["code-review"]["contract_issues"] = issues
            expected = ["prior_roles_not_complete"] if valid and issues else ([] if valid else ["invalid_facts"])
            self.reasons(facts, disposition, *expected)
        for value in (0, 1, None, "true"):
            facts, disposition = fixture()
            facts["goal_review"]["reason_nonempty"] = value
            self.reasons(facts, disposition, "invalid_facts")

    def test_structural_refusals_suppress_semantics_and_unknown_case(self):
        for disposition in (None, {}, {"schema_version": "unrecognized"}):
            facts, _ = fixture()
            result = self.reasons(facts, disposition, "unknown_case")
            self.assertIsNone(result["case_id"])
            self.assertEqual(result["facts_sha256"], EXPECTED_DIGEST)
        facts, disposition = fixture()
        facts["pending_handoff"] = True
        disposition["binding"]["case_id"] = "PRIVATE INVALID CASE"
        result = self.reasons(facts, disposition, "invalid_disposition", now=-1)
        self.assertIsNone(result["case_id"])
        result = self.reasons({}, {}, "invalid_facts", "unknown_case")
        self.assertIsNone(result["facts_sha256"])
        self.reasons({}, [], "invalid_facts", "invalid_disposition")

    def test_hostile_subclasses_cycles_and_unsupported_objects(self):
        class Hostile:
            def __eq__(self, other):
                raise AssertionError("foreign equality executed")
            def __str__(self):
                raise AssertionError("foreign string conversion executed")
            def __hash__(self):
                return 1
        class Dict(dict):
            def items(self):
                raise AssertionError("foreign dict executed")
        class List(list):
            def __iter__(self):
                raise AssertionError("foreign list executed")
        class String(str):
            def __eq__(self, other):
                raise AssertionError("foreign string executed")
        class Integer(int):
            pass
        for bad in (Hostile(), Dict(), List(), String("blocked"), Integer(1), (), set(), b"x"):
            facts, disposition = fixture()
            self.reasons(bad, disposition, "invalid_facts")
            self.reasons(facts, bad, "invalid_disposition")
            facts["work_item_state"] = bad
            self.reasons(facts, disposition, "invalid_facts")
        facts, disposition = fixture()
        facts["binding"]["case_id"] = String("SYNTHETIC-S1")
        self.reasons(facts, disposition, "invalid_facts")
        facts, disposition = fixture()
        facts[Hostile()] = "private"
        self.reasons(facts, disposition, "invalid_facts")
        cyclic = []
        cyclic.append(cyclic)
        facts, disposition = fixture()
        facts["prior_roles"]["implementation"]["contract_issues"] = cyclic
        self.reasons(facts, disposition, "invalid_facts")
        facts, disposition = fixture()
        facts["binding"] = facts
        disposition["binding"] = disposition
        self.reasons(facts, disposition, "invalid_facts", "invalid_disposition")
        facts, disposition = fixture()
        facts["rework_count"] = Integer(1)
        self.reasons(facts, disposition, "invalid_facts")
        facts, disposition = fixture()
        facts["prior_roles"]["code-review"]["contract_issues"] = List(["x"])
        self.reasons(facts, disposition, "invalid_facts")

    def test_canonical_size_exact_cap_and_no_clipping(self):
        for target in (16383, 16384, 16385):
            facts, disposition = fixture()
            for role in facts["prior_roles"].values():
                role["contract_issues"] = ["x"] * 16
            remaining = target - len(canonical(facts))
            for role in facts["prior_roles"].values():
                for index in range(16):
                    extra = min(255, remaining)
                    role["contract_issues"][index] += "x" * extra
                    remaining -= extra
            self.assertEqual(remaining, 0)
            self.assertEqual(len(canonical(facts)), target)
            result = self.assess(facts, disposition)
            if target <= 16384:
                self.assertEqual(result["reason_codes"], ["prior_roles_not_complete"])
                self.assertEqual(result["facts_sha256"], hashlib.sha256(canonical(facts)).hexdigest())
            else:
                self.assertEqual(result["reason_codes"], ["invalid_facts"])
                self.assertIsNone(result["facts_sha256"])
        facts, disposition = fixture()
        disposition["binding"]["case_id"] = "A" * 20000
        self.reasons(facts, disposition, "invalid_disposition")
        facts, disposition = fixture()
        facts["work_item_state"] = "PRIVATE_SENTINEL" * 100000
        result = self.reasons(facts, disposition, "invalid_facts")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))

    def test_all_semantic_reasons_accumulate_without_input_mutation(self):
        facts, disposition = fixture()
        disposition["binding"]["case_id"] = "A" * 96
        facts.update(work_item_state="ready", failed_role="implementation", failed_result_status="complete",
                     handoff_consumed=False, rework_count=0, pending_handoff=True,
                     process_uncertainty=True, supplemental_count=1,
                     requested_operator_owner="operator:other", failure_kind="goal_failure")
        facts["prior_roles"]["code-review"]["outputs_complete"] = False
        facts["goal_review"].update(verdict="fail", context_sha256="9" * 64)
        before = copy.deepcopy((facts, disposition))
        result = self.assess(facts, disposition, now=1000)
        self.assertEqual(set(result["reason_codes"]), REASONS - {"unknown_case", "invalid_disposition", "invalid_facts"})
        self.assertEqual((facts, disposition), before)
        self.assertEqual(result, self.assess(facts, disposition, now=1000))
        self.assertEqual(result["case_id"], "A" * 96)
        self.assertEqual(len(result["facts_sha256"]), 64)

    def test_purity_tripwires_and_deep_immutability(self):
        for refused in (False, True):
            facts, disposition = fixture()
            if refused:
                facts["pending_handoff"] = True
            before = copy.deepcopy((facts, disposition))
            with mock.patch.object(builtins, "open", side_effect=AssertionError("I/O")), \
                 mock.patch.object(io, "open", side_effect=AssertionError("I/O")), \
                 mock.patch.object(os, "open", side_effect=AssertionError("I/O")), \
                 mock.patch.object(os, "system", side_effect=AssertionError("process")), \
                 mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process")), \
                 mock.patch.object(socket, "socket", side_effect=AssertionError("network")), \
                 mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("network")), \
                 mock.patch.object(time, "time", side_effect=AssertionError("clock")), \
                 mock.patch.object(uuid, "uuid4", side_effect=AssertionError("uuid")):
                self.reasons(facts, disposition, *(["pending_handoff"] if refused else []))
            self.assertEqual((facts, disposition), before)
        self.assertEqual(rollup.SOURCE_SUPPLEMENTAL_ROLLUP_CASES_V1, {})


if __name__ == "__main__":
    unittest.main()
