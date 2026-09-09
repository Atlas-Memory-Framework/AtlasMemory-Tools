from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import atlas_routing as routing
from atlas_authority import canonical_digest

NOW = 1_800_000_000


def policy_fixture():
    return json.loads((ROOT / "config" / "routing.example.json").read_text())


def source(identifier, kind, content, path=None, revision=None):
    return {"id": identifier, "kind": kind, "path": path, "content": content,
            "sha256": hashlib.sha256(content.encode()).hexdigest(), "observed_at": NOW,
            "revision": revision}


def intake_fixture():
    packet = {"schema_version": 1, "id": "azdo:OWNER:PROJECT:17", "revision": 7,
              "repository_url": "https://dev.azure.com/OWNER/PROJECT/_git/REPOSITORY",
              "base_branch": "develop", "base_commit": "a" * 40, "branch": "feature/example",
              "write_scope": ["src/product.ts"], "task": "Implement the reviewed localized product behavior.",
              "commands": [{"id": "unit", "argv": ["python3", "-m", "unittest"], "timeout_seconds": 60}],
              "acceptance": [{"id": "unit", "command_id": "unit", "evidence_file": "unit.json"}],
              "role_timeout_seconds": 600}
    manifest = {"schema_version": 1, "organization": "OWNER", "project": "PROJECT", "dependencies": {packet["id"]: []}}
    packet["expected_manifest"] = manifest
    packet["inspection_authority"] = {"dependency_contract_sha256": canonical_digest(manifest),
                                      "approval_record": "synthetic-public-test-only", "execution_authorized": True}
    snapshot = {"complete": True, "dependency_complete": True, "blockers": [],
                "observed_at": datetime.fromtimestamp(NOW, timezone.utc).isoformat(),
                "items": [{"id": packet["id"], "revision": 7, "eligible": True, "blockers": [], "dependencies": []}]}
    evidence = [source("issue", "issue", json.dumps({"id": packet["id"], "revision": 7}), revision=7),
                source("dependencies", "dependencies", json.dumps(snapshot, sort_keys=True, separators=(",", ":")), revision=7),
                source("instructions", "instructions", "Reviewed repository instructions", "AGENTS.md"),
                source("file", "file", "export const value = 1;", "src/product.ts"),
                source("tests", "tests", "Targeted unit command exists and reports candidate-bound evidence.")]
    return {"schema_version": 1, "worker_packet": packet,
            "step": {"id": "prepare", "kind": "coding", "action": "local_execute", "candidate_sha": None},
            "evidence": evidence, "affected_paths": ["src/product.ts"], "points": 2,
            "readiness": {"issue_revision": 7, "observed_at": NOW, "complete": True,
                "dependency_complete": True, "dependencies_satisfied": True, "execution_authority_established": True,
                "source_sha256": evidence[1]["sha256"]}, "human_gates": [], "attempts": [],
            "budget": {"max_model_calls": 10, "max_tokens": 100000, "model_calls_used": 0, "tokens_used": 0}}


def assessment_fixture(intake, policy, role="assessment", *, assessment=None, challenge=None, **changes):
    result = {"work_type": intake["step"]["kind"], "risk": "low", "uncertainty": "low", "verification": "strong",
              "suggested_profile": "routine", "required_gates": [], "unknowns": [],
              "evidence_ids": ["issue", "file", "tests"], "reason": "The relevant source and targeted tests support this bounded route."}
    result.update(changes)
    return {"schema_version": 1, "role": role, "intake_sha256": canonical_digest(intake),
            "policy_sha256": canonical_digest(policy), "evidence_sha256": routing.evidence_digest(intake),
            "context_sha256": canonical_digest(routing.assessment_context(intake, policy, role, assessment=assessment, challenge=challenge)),
            **policy["assessment_models"][role], "created_at": NOW, "result": result}


def gate_fixture(intake, **changes):
    gate = {"id": "human-review", "kind": "taste", "owner": "business-owner", "question": "Does this candidate meet the intended appearance?",
            "stage": "after", "action": "completion", "artifact_sha256": "d" * 64,
            "candidate_sha": None, "issue_id": intake["worker_packet"]["id"], "issue_revision": intake["worker_packet"]["revision"]}
    gate.update(changes)
    return gate


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.intake, self.policy = intake_fixture(), policy_fixture()

    def decision(self, **changes):
        primary = assessment_fixture(self.intake, self.policy, **changes)
        challenge = assessment_fixture(self.intake, self.policy, "challenge", **changes)
        return routing.decide_route(self.intake, self.policy, primary, challenge, now=NOW)

    def test_routine_selects_explicit_cheaper_implementation_and_independent_review(self):
        result = self.decision()
        self.assertTrue(result["route_ready"])
        self.assertEqual(result["models"]["implementation"], {"model": "gpt-5.6-terra", "reasoning": "medium"})
        self.assertEqual(result["models"]["review"], {"model": "gpt-5.6-sol", "reasoning": "high"})
        self.assertFalse(result["authority_verified"])
        self.assertFalse(result["completion"])

    def test_clerical_uses_luna_only_when_task_and_evidence_agree(self):
        self.intake["step"]["kind"] = "clerical"
        result = self.decision(suggested_profile="clerical")
        self.assertEqual(result["models"]["implementation"]["model"], "gpt-5.6-luna")

    def test_points_never_lower_sensitive_path_floor(self):
        self.intake["points"] = 1
        self.intake["affected_paths"] = ["src/auth/session.ts"]
        self.intake["worker_packet"]["write_scope"] = ["src/auth/session.ts"]
        self.intake["evidence"][3]["path"] = "src/auth/session.ts"
        result = self.decision(suggested_profile="clerical")
        self.assertEqual(result["profile"], "sensitive")
        self.assertEqual(result["models"]["review"]["reasoning"], "max")

    def test_sensitive_filename_stems_and_camelcase_auth_receive_floor(self):
        for path in ("tools/auth.py", "src/security.ts", "src/AuthProvider.ts", "tools/atlas_authority.py"):
            with self.subTest(path=path):
                self.intake["affected_paths"] = [path]
                self.intake["worker_packet"]["write_scope"] = [path]
                self.intake["evidence"][3]["path"] = path
                self.assertEqual(self.decision()["profile"], "sensitive")

    def test_point_size_requests_decomposition_without_escalating(self):
        self.intake["points"] = 13
        result = self.decision()
        self.assertFalse(result["route_ready"])
        self.assertEqual(result["profile"], "routine")
        self.assertTrue(any("decompose" in reason for reason in result["blockers"]))

    def test_sensitive_scope_cannot_hide_behind_unrelated_affected_path(self):
        self.intake["worker_packet"]["write_scope"] = ["src", "infra"]
        result = self.decision()
        self.assertFalse(result["route_ready"])
        self.assertEqual(result["profile"], "sensitive")

    def test_sensitive_profile_cannot_be_configured_as_luna(self):
        self.policy["profiles"]["sensitive"]["implementation"] = {"model": "gpt-5.6-luna", "reasoning": "low"}
        with self.assertRaises(routing.RoutingError):
            routing.validate_policy(self.policy)

    def test_missing_dependencies_or_authority_remain_blocked(self):
        for key in ("complete", "dependency_complete", "dependencies_satisfied", "execution_authority_established"):
            with self.subTest(key=key):
                intake = deepcopy(self.intake)
                intake["readiness"][key] = False
                result = routing.decide_route(intake, self.policy, now=NOW)
                self.assertFalse(result["route_ready"])
                self.assertFalse(result["assessment_required"])

    def test_stale_read_and_stale_assessment_fail_closed(self):
        self.assertFalse(routing.decide_route(self.intake, self.policy, now=NOW + 901)["route_ready"])
        primary = assessment_fixture(self.intake, self.policy)
        primary["created_at"] = NOW - 901
        with self.assertRaises(routing.RoutingError):
            routing.decide_route(self.intake, self.policy, primary, now=NOW)

    def test_revision_drift_blocks_without_model_override(self):
        self.intake["readiness"]["issue_revision"] = 8
        self.assertFalse(self.decision()["route_ready"])

    def test_missing_file_or_instruction_evidence_blocks(self):
        for kind in ("file", "instructions"):
            with self.subTest(kind=kind):
                intake = deepcopy(self.intake)
                intake["evidence"] = [entry for entry in intake["evidence"] if entry["kind"] != kind]
                self.assertFalse(routing.decide_route(intake, self.policy, now=NOW)["route_ready"])

    def test_source_digest_must_identify_actual_dependency_evidence(self):
        self.intake["readiness"]["source_sha256"] = "b" * 64
        self.assertFalse(self.decision()["route_ready"])

    def test_self_asserted_readiness_cannot_override_source_blockers(self):
        snapshot = json.loads(self.intake["evidence"][1]["content"])
        snapshot["blockers"] = ["execution-authority-not-established"]
        self.intake["evidence"][1] = source("dependencies", "dependencies", json.dumps(snapshot, sort_keys=True, separators=(",", ":")), revision=7)
        self.intake["readiness"]["source_sha256"] = self.intake["evidence"][1]["sha256"]
        self.assertFalse(self.decision()["route_ready"])

    def test_changed_file_content_without_updated_digest_is_rejected(self):
        self.intake["evidence"][3]["content"] = "Changed source"
        with self.assertRaises(routing.RoutingError):
            routing.decide_route(self.intake, self.policy, now=NOW)

    def test_missing_command_or_acceptance_never_reports_ready(self):
        for field in ("commands", "acceptance"):
            with self.subTest(field=field):
                intake = deepcopy(self.intake)
                intake["worker_packet"][field] = []
                with self.assertRaises(routing.RoutingError):
                    routing.decide_route(intake, self.policy, now=NOW)

    def test_unknown_schema_fields_and_bool_as_revision_rejected(self):
        for mutate in (lambda value: value.update(authorized=True),
                       lambda value: value["worker_packet"].update(revision=True),
                       lambda value: value["readiness"].update(complete=1),
                       lambda value: value.update(points=False)):
            with self.subTest(mutate=mutate):
                intake = deepcopy(self.intake)
                mutate(intake)
                with self.assertRaises(routing.RoutingError):
                    routing.validate_intake(intake)

    def test_unknown_or_traversing_paths_rejected(self):
        for path in ("../other", "/etc/passwd", "src/*", "src/../auth.ts", "src\\auth.ts", "*"):
            with self.subTest(path=path):
                intake = deepcopy(self.intake)
                intake["affected_paths"] = [path]
                with self.assertRaises(routing.RoutingError):
                    routing.validate_intake(intake)

    def test_primary_and_challenge_context_are_blind(self):
        primary = assessment_fixture(self.intake, self.policy)
        context = routing.assessment_context(self.intake, self.policy, "challenge")
        self.assertNotIn("prior_assessments", context)
        with self.assertRaises(routing.RoutingError):
            routing.assessment_context(self.intake, self.policy, "challenge", assessment=primary)

    def test_missing_challenge_requests_one_without_claiming_ready(self):
        primary = assessment_fixture(self.intake, self.policy)
        result = routing.decide_route(self.intake, self.policy, primary, now=NOW)
        self.assertEqual(result["state"], "needs_challenge")
        self.assertTrue(result["challenge_required"])
        self.assertFalse(result["route_ready"])

    def test_challenge_cannot_reuse_primary_context_or_changed_model(self):
        primary = assessment_fixture(self.intake, self.policy)
        for key, value in (("context_sha256", primary["context_sha256"]), ("model", "gpt-6-astra")):
            with self.subTest(key=key):
                challenge = assessment_fixture(self.intake, self.policy, "challenge")
                challenge[key] = value
                with self.assertRaises(routing.RoutingError):
                    routing.decide_route(self.intake, self.policy, primary, challenge, now=NOW)

    def test_changed_intake_invalidates_prior_assessment(self):
        primary = assessment_fixture(self.intake, self.policy)
        self.intake["worker_packet"]["task"] += " Changed scope."
        with self.assertRaises(routing.RoutingError):
            routing.decide_route(self.intake, self.policy, primary, now=NOW)

    def test_agreement_does_not_require_manufactured_dissent(self):
        self.assertTrue(self.decision()["route_ready"])

    def test_cost_only_disagreement_selects_cheapest_route_above_floor(self):
        primary = assessment_fixture(self.intake, self.policy, suggested_profile="sensitive")
        challenge = assessment_fixture(self.intake, self.policy, "challenge", suggested_profile="routine")
        result = routing.decide_route(self.intake, self.policy, primary, challenge, now=NOW)
        self.assertEqual(result["profile"], "routine")
        self.assertFalse(result["reassessment_required"])

    def test_material_disagreement_requires_bounded_reassessment(self):
        primary = assessment_fixture(self.intake, self.policy)
        challenge = assessment_fixture(self.intake, self.policy, "challenge", risk="high")
        result = routing.decide_route(self.intake, self.policy, primary, challenge, now=NOW)
        self.assertTrue(result["reassessment_required"])
        self.assertFalse(result["route_ready"])
        challenge["reassessment"] = assessment_fixture(self.intake, self.policy, "reassessment", assessment=primary, challenge=challenge)
        self.assertTrue(routing.decide_route(self.intake, self.policy, primary, challenge, now=NOW)["route_ready"])

    def test_unresolved_reassessment_blocks_and_cannot_nest_again(self):
        primary = assessment_fixture(self.intake, self.policy)
        challenge = assessment_fixture(self.intake, self.policy, "challenge", risk="high")
        challenge["reassessment"] = assessment_fixture(self.intake, self.policy, "reassessment", assessment=primary, challenge=challenge, risk="medium")
        self.assertFalse(routing.decide_route(self.intake, self.policy, primary, challenge, now=NOW)["route_ready"])
        challenge["reassessment"]["reassessment"] = {}
        with self.assertRaises(routing.RoutingError):
            routing.decide_route(self.intake, self.policy, primary, challenge, now=NOW)

    def test_reassessment_cannot_vote_away_counterfactual_human_gates(self):
        primary = assessment_fixture(self.intake, self.policy)
        challenge = assessment_fixture(self.intake, self.policy, "challenge", risk="high", required_gates=["missing-owner-answer"])
        challenge["reassessment"] = assessment_fixture(self.intake, self.policy, "reassessment", assessment=primary, challenge=challenge)
        result = routing.decide_route(self.intake, self.policy, primary, challenge, now=NOW)
        self.assertFalse(result["route_ready"])
        self.assertTrue(any("human gates" in reason for reason in result["blockers"]))

    def test_sampling_identity_does_not_reroll_with_prose_or_timestamps(self):
        self.policy["limits"]["require_challenge"] = False
        results = []
        for index in range(12):
            self.intake["worker_packet"]["task"] = "Edited prose " + str(index)
            self.intake["evidence"][3]["observed_at"] = NOW - index
            primary = assessment_fixture(self.intake, self.policy)
            results.append(routing.decide_route(self.intake, self.policy, primary, now=NOW)["challenge_required"])
        self.assertEqual(len(set(results)), 1)

    def test_unknowns_missing_gates_and_fabricated_citations_fail_closed(self):
        self.assertFalse(self.decision(unknowns=["Business appearance is unspecified"])["route_ready"])
        self.assertFalse(self.decision(required_gates=["missing-approval"])["route_ready"])
        with self.assertRaises(routing.RoutingError):
            self.decision(evidence_ids=["invented"])

    def test_future_visual_acceptance_does_not_block_preparation(self):
        self.intake["human_gates"] = [gate_fixture(self.intake)]
        result = self.decision(verification="human", required_gates=["human-review"])
        self.assertTrue(result["route_ready"])
        self.assertTrue(result["dispatchable"])
        self.assertEqual(result["later_gates"], ["human-review"])
        self.assertFalse(result["completion"])

    def test_pre_step_human_input_requires_verified_response_and_no_model_calls(self):
        self.intake["human_gates"] = [gate_fixture(self.intake, kind="input", stage="before", action="local_execute")]
        result = self.decision()
        self.assertTrue(result["route_ready"])
        self.assertFalse(result["dispatchable"])
        self.assertEqual(result["state"], "waiting_human")
        preview = routing.decide_route(self.intake, self.policy, now=NOW)
        self.assertTrue(preview["assessment_required"])
        self.assertEqual(preview["state"], "waiting_human")

    def test_deterministic_step_has_no_model_and_still_no_authority(self):
        self.intake["step"].update(kind="deterministic", action="inspect")
        result = routing.decide_route(self.intake, self.policy, now=NOW)
        self.assertEqual(result["models"], {})
        self.assertFalse(result["assessment_required"])
        self.assertFalse(result["authority_verified"])

    def test_external_work_is_tracked_with_owner_and_never_executed(self):
        for action in routing.EXECUTABLE_ACTIONS["external"]:
            with self.subTest(action=action):
                intake = deepcopy(self.intake)
                intake["step"].update(kind="external", action=action)
                intake["human_gates"] = [gate_fixture(intake, kind="approval", stage="before", action=action)]
                result = routing.decide_route(intake, self.policy, now=NOW)
                self.assertEqual(result["state"], "waiting_external")
                self.assertFalse(result["route_ready"])
                self.assertEqual(result["models"], {})

    def test_human_step_without_owner_question_artifact_is_invalid(self):
        self.intake["step"].update(kind="human", action="human_input")
        with self.assertRaises(routing.RoutingError):
            routing.validate_intake(self.intake)

    def test_exhausted_budget_blocks_model_work_but_not_polling(self):
        self.intake["budget"]["model_calls_used"] = 10
        self.assertFalse(self.decision()["route_ready"])
        self.intake["step"].update(kind="deterministic", action="inspect")
        self.assertTrue(routing.decide_route(self.intake, self.policy, now=NOW)["route_ready"])

    def test_budget_must_cover_assessment_and_bounded_worker_sequence(self):
        self.intake["budget"]["max_model_calls"] = 1
        result = self.decision()
        self.assertFalse(result["route_ready"])
        self.assertEqual(result["required_model_calls"], 7)
        self.intake["budget"]["max_model_calls"] = 7
        self.assertTrue(self.decision()["route_ready"])

    def test_verified_code_failure_permits_only_one_stronger_attempt(self):
        self.intake["attempts"] = [{"number": 1, "outcome": "code_failure", "verified": True,
                                    "evidence_id": "tests", "profile": "routine", "candidate_sha": "b" * 40}]
        artifact = {"schema_version": 1, "worker_packet_sha256": canonical_digest(self.intake["worker_packet"]),
                    "issue_id": self.intake["worker_packet"]["id"], "issue_revision": 7, "candidate_sha": "b" * 40,
                    "attempt_number": 1, "outcome": "code_failure", "command_id": "unit", "exit_code": 1, "review_decision": None}
        self.intake["evidence"][4] = source("tests", "tests", json.dumps(artifact, sort_keys=True, separators=(",", ":")))
        self.assertEqual(self.decision()["profile"], "complex")
        self.intake["attempts"].append({**self.intake["attempts"][0], "number": 2, "profile": "complex"})
        self.assertFalse(self.decision()["route_ready"])

    def test_verified_boolean_and_unrelated_test_text_do_not_prove_failure(self):
        self.intake["attempts"] = [{"number": 1, "outcome": "code_failure", "verified": True,
                                    "evidence_id": "tests", "profile": "routine", "candidate_sha": "b" * 40}]
        result = self.decision()
        self.assertFalse(result["route_ready"])
        self.assertEqual(result["profile"], "routine")

    def test_passing_command_and_wrong_candidate_cannot_trigger_escalation(self):
        self.intake["attempts"] = [{"number": 1, "outcome": "code_failure", "verified": True,
                                    "evidence_id": "tests", "profile": "routine", "candidate_sha": "b" * 40}]
        artifact = {"schema_version": 1, "worker_packet_sha256": canonical_digest(self.intake["worker_packet"]),
                    "issue_id": self.intake["worker_packet"]["id"], "issue_revision": 7, "candidate_sha": "b" * 40,
                    "attempt_number": 1, "outcome": "code_failure", "command_id": "unit", "exit_code": 1, "review_decision": None}
        for key, value in (("exit_code", 0), ("exit_code", True), ("candidate_sha", "c" * 40), ("issue_revision", 8)):
            with self.subTest(key=key):
                bad = {**artifact, key: value}
                self.intake["evidence"][4] = source("tests", "tests", json.dumps(bad, sort_keys=True, separators=(",", ":")))
                self.assertFalse(self.decision()["route_ready"])

    def test_infrastructure_authority_and_human_failures_cannot_escalate(self):
        for outcome in ("infrastructure_failure", "missing_authority", "missing_human", "success"):
            with self.subTest(outcome=outcome):
                self.intake["attempts"] = [{"number": 1, "outcome": outcome, "verified": True,
                                            "evidence_id": "tests", "profile": "routine", "candidate_sha": "b" * 40}]
                result = self.decision()
                self.assertFalse(result["route_ready"])
                self.assertEqual(result["profile"], "routine")

    def test_unverified_failure_cannot_escalate(self):
        self.intake["attempts"] = [{"number": 1, "outcome": "code_failure", "verified": False,
                                    "evidence_id": "tests", "profile": "routine", "candidate_sha": "b" * 40}]
        self.assertFalse(self.decision()["route_ready"])

    def test_decisions_reproduce_and_reject_tampered_models_or_policy(self):
        primary = assessment_fixture(self.intake, self.policy)
        challenge = assessment_fixture(self.intake, self.policy, "challenge")
        decision = routing.decide_route(self.intake, self.policy, primary, challenge, now=NOW)
        self.assertEqual(routing.validate_decision(decision, self.intake, self.policy, primary, challenge, now=NOW), decision)
        changed = deepcopy(decision)
        changed["models"]["implementation"]["model"] = "gpt-5.6-luna"
        with self.assertRaises(routing.RoutingError):
            routing.validate_decision(changed, self.intake, self.policy, primary, challenge, now=NOW)

    def test_unicode_task_has_one_shared_packet_hash(self):
        self.intake["worker_packet"]["task"] = "Réviser l’apparence du store — aperçu."
        result = self.decision()
        self.assertEqual(result["worker_packet_sha256"], canonical_digest(self.intake["worker_packet"]))

    def test_preview_never_reads_writes_or_launches_subprocesses(self):
        with mock.patch("builtins.open", side_effect=AssertionError("file effect")), mock.patch("subprocess.run", side_effect=AssertionError("process effect")):
            result = routing.decide_route(self.intake, self.policy, now=NOW)
        self.assertEqual(result["state"], "needs_assessment")

    def test_website_example_retains_unauthorized_dependency_blockers(self):
        examples = ROOT.parents[1] / "examples" / "instablinds" / "local-automation-runtime"
        intake = json.loads((examples / "routing-intake.example.json").read_text())
        policy = json.loads((examples / "config" / "azure-website-routing.json").read_text())
        result = routing.decide_route(intake, policy, now=NOW)
        self.assertFalse(result["route_ready"])
        dependencies = json.loads(next(item["content"] for item in intake["evidence"] if item["kind"] == "dependencies"))
        self.assertEqual(dependencies["applied_dependency_links"], 53)
        self.assertEqual(dependencies["unauthorized_prerequisite_edges"], 18)


if __name__ == "__main__":
    unittest.main()
