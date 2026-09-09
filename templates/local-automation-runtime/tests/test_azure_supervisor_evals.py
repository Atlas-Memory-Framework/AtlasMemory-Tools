"""Offline outcome contract for the deterministic Azure supervisor lane.

Eval: azure-supervisor-offline-v1; decision: defer unattended operation.
Baseline: the same intake, signed authority, dispatcher and bounded worker run
directly. Variant: the supervisor selects those existing operations and ingests
their durable outcomes. External Azure/model/issuer transports are synthetic;
intake, routing, signature verification, claims, acceptance and budgets are real.
Each trial starts with an isolated identity/runtime and at most one queue item.
The declared progress unit is a candidate with independently checked acceptance
and review artifacts, never a timestamp, child launch, exit zero or narrative.
Outcome/trace graders are deterministic; no model grades itself. Trials assert
exact model/argv evidence, terminal truth, stale-authority denial, bounded stops,
and approval cards per unique material decision. Missing or corrupt evidence is
a failure, while an intentionally incomplete example is an expected draft.
No cost/quality/latency or production readiness claim follows from these fixtures.
A real qualified one-item canary remains necessary before promoting this lane.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

import atlas_approval as approval
import atlas_azure_devops as azure
import atlas_azure_worker as worker
import atlas_dispatch as dispatch
import atlas_intake as intake_builder
import atlas_runtime_config as runtime_config
from atlas_authority import canonical_digest
from authority_fixture import AuthorityFixture
from test_atlas_dispatch import AssessmentRunner, NOW, URL, routing_inputs
from test_azure_devops import Response
from test_azure_worker import FakeClient, FakeRunner


def oracle_digest(value):
    """Independent serialization oracle for durable outcome grading."""
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


class NativeFixtureHTTP:
    def __init__(self):
        self.requests = []
        self.raw = {"id": 17, "rev": 7,
                    "fields": {"System.State": "To Do", "System.TeamProject": "Instablinds", "System.Title": "Scoped fixture"},
                    "relations": []}
        self.missing = False

    def open(self, request, **kwargs):
        self.requests.append(request)
        if not urlparse(request.full_url).path.endswith("/_apis/wit/workitemsbatch"):
            raise AssertionError("offline evaluator forbids every Azure operation except native work-item batch reads")
        body = json.loads(request.data)
        if body["ids"] != [17]:
            raise AssertionError("unexpected native fixture item selection")
        return Response({"count": 0 if self.missing else 1, "value": [] if self.missing else [deepcopy(self.raw)]})


class BoundedFixtureRunner:
    """Produce actual protocol files; never return a fabricated child report."""
    def __init__(self, packet):
        self.assessment = AssessmentRunner()
        self.execution = FakeRunner(packet, FakeClient())
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if "--help" in argv or "--version" in argv:
            return self.assessment(argv, **kwargs)
        if argv[:2] == ["codex", "exec"]:
            payload = json.loads(kwargs["input"].split("\n", 1)[1])
            if payload["role"] in {"assessment", "challenge", "reassessment"}:
                return self.assessment(argv, **kwargs)
        return self.execution(argv, **kwargs)

    def roles(self):
        return [json.loads(kwargs["input"].split("\n", 1)[1])["role"] for argv, kwargs in self.calls
                if argv[:2] == ["codex", "exec"] and "--help" not in argv]


class AzureSupervisorOutcomeEvals(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.runtime = self.home / "runtime"
        self.runtime.mkdir(mode=0o700)
        (self.runtime / "worktrees").mkdir(mode=0o700)
        self.workspace = self.runtime / "worktrees" / "item-17"
        self.workspace.mkdir(mode=0o700)
        for relative in (".git", "src", "tests"):
            (self.workspace / relative).mkdir(mode=0o700)
        (self.workspace / "AGENTS.md").write_text("Keep changes bounded and run acceptance.")
        (self.workspace / "src" / "change.py").write_text("value = 1\n")
        (self.workspace / "tests" / "acceptance.py").write_text("# Reviewed fixture command emits unit.json bound to its candidate.\n")
        self.identity = mock.patch.object(runtime_config.pwd, "getpwuid",
                                          return_value=types.SimpleNamespace(pw_dir=str(self.home), pw_name="fixture"))
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.environment = mock.patch.dict(os.environ, {"HOME": str(self.home), "CODEX_HOME": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.now = NOW
        self.policy, original, _ = routing_inputs()
        self.packet = deepcopy(original["worker_packet"])
        self.manifest = {"schema_version": 1, "organization": "Instablinds", "project": "Instablinds",
                         "dependencies": {self.packet["id"]: []}}
        self.packet["expected_manifest"] = self.manifest
        self.packet["inspection_authority"] = {"dependency_contract_sha256": canonical_digest(self.manifest),
            "approval_record": "Synthetic dependency inspection annotation; no operation authority.", "execution_authorized": True}
        self.config = runtime_config.RuntimeConfig("azure-devops", self.runtime,
            {"organization": "Instablinds", "project": "Instablinds", "name": "Website", "url": URL,
             "base_branch": "develop", "checkout": str(self.workspace)},
            frozenset({"read", "assess", "local_execute", "draft_pr"}),
            {role: runtime_config.RoleSettings("gpt-6-astra", "max", "eval-baseline") for role in runtime_config.ROLES},
            "eval-baseline")
        self.definition = {"schema_version": 1, "worker_packet": self.packet, "step": original["step"],
            "sources": [{"id": "instructions", "kind": "instructions", "path": "AGENTS.md"},
                        {"id": "file", "kind": "file", "path": "src/change.py"},
                        {"id": "tests", "kind": "tests", "path": "tests/acceptance.py"}],
            "affected_paths": ["src/change.py"], "points": 2, "human_gates": [], "attempts": [],
            "budget": original["budget"], "owner": "operator"}
        self.queue = {"schema_version": 1, "repository_url": URL,
            "limits": {"max_cycles": 2, "max_items": 1, "max_seconds": 3600},
            "items": [{"id": self.packet["id"], "definition": self.definition,
                       "context_root": str(self.workspace), "actions": ["assess", "local_execute"]}]}
        self.http = NativeFixtureHTTP()
        self.client = azure.AzureDevOpsClient("Instablinds", "Instablinds", self.runtime,
            opener=self.http, interval=0, clock=lambda: self.now)
        self.provider = azure.AzureBoardsProvider(self.client)
        self.runner = BoundedFixtureRunner(self.packet)
        self.authority = None

    def trust(self):
        if self.authority is None:
            self.authority = AuthorityFixture(self.runtime, policy_sha256=canonical_digest(self.policy), now=self.now)
        return self.authority

    def assembled(self, *, previous=None):
        snapshot = self.provider.inspect([self.packet["id"]], expected_manifest=self.manifest,
            authority=self.packet["inspection_authority"], fresh=True)
        return intake_builder.build_intake(self.config, self.policy, self.definition, snapshot,
            context_root=self.workspace, previous=previous, now=self.now)

    def controller(self, report):
        return dispatch.AzureDispatcher(self.config, self.policy, report["intake"], report["snapshot"],
            context_root=self.workspace, runner=self.runner, clock=lambda: self.now)

    def supervisor(self):
        import atlas_supervisor
        return atlas_supervisor.AzureSupervisor(self.config, self.policy, self.queue,
            provider=self.provider, client=self.client, runner=self.runner, clock=lambda: self.now)

    def signed_response(self, request, *, decision="accepted", response_text=None, **overrides):
        inbox = approval.ApprovalInbox(self.runtime)
        exported = inbox.export_request(request, decision=decision, response_text=response_text)
        subject = exported["signing_subject"]
        grant = self.trust().grant(subject["action"], subject["bindings"], grant_id=subject["grant_id"], **overrides)
        response = {"schema_version": 1, "request_id": exported["request_id"],
                    "request_revision": exported["request_revision"], "material_sha256": exported["material_sha256"],
                    "decision": exported["decision"], "response": exported["response"], "grant": grant}
        return response

    def accept(self, request, **kwargs):
        response = self.signed_response(request, **kwargs)
        result = approval.ApprovalInbox(self.runtime).import_response(request, response, now=self.now)
        self.assertTrue(result["verified"])
        return response

    def files(self):
        return {str(path.relative_to(self.home)): path.read_bytes() for path in self.home.rglob("*") if path.is_file()}

    def assert_candidate_evidence(self, result):
        """Grade the environment, independently of a supervisor's state string."""
        self.assertEqual(result["state"], "prepared")
        self.assertIsNot(result.get("completion"), True)
        claims = json.loads((self.runtime / "state" / "azure-worker" / "claims.json").read_text())
        claim = claims[oracle_digest(self.packet)]
        self.assertEqual(claim["state"], "prepared")
        self.assertEqual(claim["candidate_sha"], "b" * 40)
        self.assertEqual(claim["evidence_sha256"], oracle_digest(claim["evidence"]))
        self.assertEqual(result["evidence_sha256"], claim["evidence_sha256"])
        evidence = self.workspace / ".atlas-worker" / oracle_digest(self.packet)
        expected_roles = {"planning-0.json", "implementation-0.json", "review-0.json"}
        self.assertEqual(set(claim["evidence"]["role_artifacts"]), expected_roles)
        for name, expected in claim["evidence"]["role_artifacts"].items():
            artifact = json.loads((evidence / name).read_text())
            self.assertEqual(oracle_digest(artifact), expected)
            self.assertEqual(artifact["packet_sha256"], oracle_digest(self.packet))
            self.assertEqual(artifact["decision"], "pass")
        acceptance = json.loads((evidence / "unit.json").read_text())
        self.assertEqual(acceptance["candidate_sha"], claim["candidate_sha"])
        self.assertEqual(acceptance["packet_sha256"], oracle_digest(self.packet))
        self.assertEqual(acceptance["result"], "pass")
        self.assertEqual(acceptance["acceptance_id"], "unit-pass")
        self.assertEqual(oracle_digest(acceptance), claim["evidence"]["acceptance"]["artifacts"]["unit.json"])
        self.assertEqual(self.runner.roles(), ["assessment", "challenge", "planning", "implementation", "review"])
        model_calls = [(argv, kwargs) for argv, kwargs in self.runner.calls
                       if argv[:2] == ["codex", "exec"] and "--help" not in argv]
        self.assertEqual([argv[argv.index("--model" if "--model" in argv else "-m") + 1] for argv, _ in model_calls],
                         ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-sol"])
        self.assertTrue(all("--ignore-user-config" in argv and "workspace-write" in argv for argv, _ in model_calls))
        self.assertTrue(all('approval_policy="on-request"' in argv for argv, _ in model_calls))

    def operation_request(self, report, action):
        self.assertFalse(report["completion"])
        rows = [row for item in report["items"] for row in item["requests"] if row["request"]["action"] == action]
        self.assertEqual(len(rows), 1, report)
        return rows[0]["request"]

    def supervisor_state(self):
        identifier = oracle_digest({"repository_url": URL, "id": self.packet["id"]})
        return json.loads((self.runtime / ".azure-supervisor" / ("item-" + identifier + ".json")).read_text())

    def assess_via_supervisor(self):
        pending = self.supervisor().observe(max_cycles=1)
        self.assertEqual(pending["items"][0]["state"], "waiting_authority", pending)
        self.assertEqual(self.runner.calls, [])
        self.accept(self.operation_request(pending, "assess"))
        assessed = self.supervisor().run(max_cycles=1)
        self.assertEqual(assessed["items"][0]["state"], "assessed", assessed)
        self.assertEqual(self.runner.roles(), ["assessment", "challenge"])
        self.assertEqual(self.supervisor_state()["operation"]["state"], "verified")
        return assessed

    def pending_execution(self):
        self.assess_via_supervisor()
        pending = self.supervisor().observe(max_cycles=1)
        self.assertEqual(pending["items"][0]["state"], "waiting_authority", pending)
        return self.operation_request(pending, "local_execute")

    def test_supervisor_refresh_signed_responses_and_real_bounded_child_ingestion(self):
        request = self.pending_execution()
        self.accept(request)
        prepared = self.supervisor().run(max_cycles=1)
        self.assertEqual(prepared["items"][0]["state"], "prepared", prepared)
        self.assert_candidate_evidence(prepared["items"][0]["child_evidence"])
        durable = self.supervisor_state()
        self.assertEqual(durable["last_state"], "prepared")
        self.assertEqual(durable["operation"]["state"], "verified")
        self.assertEqual(durable["child_evidence"], prepared["items"][0]["child_evidence"])
        before_roles = self.runner.roles()
        resumed = self.supervisor().observe(max_cycles=1)
        self.assertEqual(resumed["items"][0]["state"], "prepared", resumed)
        self.assertEqual(self.runner.roles(), before_roles)
        cards = list((self.runtime / "approval-inbox").glob("*.json"))
        self.assertEqual(len(cards), 2)  # Assessment and execution are distinct material decisions.
        self.assertTrue(all(json.loads(path.read_text())["revision"] == 1 for path in cards))
        self.assertFalse(resumed["completion"])

    def test_verified_human_answer_reaches_independent_assessors_and_worker_contexts(self):
        gate = {"id": "operator-choice", "kind": "input", "owner": "operator",
                "question": "Which label should the prepared candidate use?", "stage": "before",
                "action": "local_execute", "artifact_sha256": "e" * 64, "candidate_sha": None,
                "issue_id": self.packet["id"], "issue_revision": self.packet["revision"]}
        self.definition["human_gates"] = [gate]
        awaiting = self.supervisor().observe(max_cycles=1)
        request = self.operation_request(awaiting, "human_gate")
        self.assertEqual(request["question"], gate["question"])
        self.accept(request, response_text="Use the concise label Confirm order.")
        execution = self.pending_execution()
        self.accept(execution)
        result = self.supervisor().run(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "prepared", result)
        self.assert_candidate_evidence(result["items"][0]["child_evidence"])
        for context in self.runner.assessment.contexts:
            serialized = json.dumps(context)
            self.assertIn("Use the concise label Confirm order.", serialized)
            self.assertIn("human-answer:operator-choice", serialized)
        payloads = [json.loads(kwargs["input"].split("\n", 1)[1]) for argv, kwargs in self.runner.execution.calls
                    if argv[:2] == ["codex", "exec"] and "--help" not in argv]
        self.assertEqual(len(payloads), 3)
        for payload in payloads:
            answers = payload["verified_human_inputs"]
            self.assertEqual(len(answers), 1)
            self.assertEqual(answers[0]["gate_id"], gate["id"])
            self.assertEqual(answers[0]["owner"], gate["owner"])
            self.assertEqual(answers[0]["question"], gate["question"])
            self.assertEqual(answers[0]["response"], "Use the concise label Confirm order.")
        # Historical execution inputs are retained after preparation. Expired
        # input grants cannot demand a new answer for an already prepared step.
        roles = self.runner.roles()
        self.now += 172800
        delayed = self.supervisor().observe(max_cycles=1)
        self.assertEqual(delayed["items"][0]["state"], "prepared", delayed)
        self.assertEqual(delayed["items"][0]["requests"], [])
        self.assertEqual(self.runner.roles(), roles)
        self.assertFalse(delayed["completion"])

    def test_changed_prepared_scope_remains_conflicted_on_every_resume(self):
        self.accept(self.pending_execution())
        prepared = self.supervisor().run(max_cycles=1)
        self.assertEqual(prepared["items"][0]["state"], "prepared", prepared)
        original = self.supervisor_state()
        calls = len(self.runner.calls)
        claim_path = self.runtime / "state" / "azure-worker" / "claims.json"
        claims = claim_path.read_bytes()
        self.definition["worker_packet"]["task"] += " Also change the footer."
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                result = self.supervisor().run(max_cycles=1)
                self.assertEqual(result["items"][0]["state"], "conflict", result)
                self.assertEqual(self.supervisor_state()["entry_sha256"], original["entry_sha256"])
                self.assertEqual(len(self.runner.calls), calls)
                self.assertEqual(claim_path.read_bytes(), claims)
                self.assertFalse(result["completion"])

    def test_corrupted_prepared_artifact_cannot_remain_an_accepted_progress_unit(self):
        self.accept(self.pending_execution())
        prepared = self.supervisor().run(max_cycles=1)
        self.assertEqual(prepared["items"][0]["state"], "prepared", prepared)
        evidence = self.workspace / ".atlas-worker" / oracle_digest(self.packet) / "unit.json"
        changed = json.loads(evidence.read_text())
        changed["result"] = "fail"
        evidence.write_text(json.dumps(changed))
        roles = self.runner.roles()
        result = self.supervisor().observe(max_cycles=1)
        self.assertIn(result["items"][0]["state"], {"blocked", "conflict", "uncertain"}, result)
        self.assertNotEqual(self.supervisor_state()["last_state"], "prepared")
        self.assertEqual(self.runner.roles(), roles)
        self.assertFalse(result["completion"])

    def test_missing_independent_review_cannot_remain_a_prepared_candidate(self):
        self.accept(self.pending_execution())
        prepared = self.supervisor().run(max_cycles=1)
        self.assertEqual(prepared["items"][0]["state"], "prepared", prepared)
        review = self.workspace / ".atlas-worker" / oracle_digest(self.packet) / "review-0.json"
        review.unlink()
        roles = self.runner.roles()
        result = self.supervisor().observe(max_cycles=1)
        self.assertIn(result["items"][0]["state"], {"blocked", "conflict", "uncertain"}, result)
        self.assertEqual(self.runner.roles(), roles)
        self.assertFalse(result["completion"])

    def test_current_candidate_drift_cannot_keep_historical_prepared_projection(self):
        self.accept(self.pending_execution())
        prepared = self.supervisor().run(max_cycles=1)
        self.assertEqual(prepared["items"][0]["state"], "prepared", prepared)
        self.runner.execution.head = "c" * 40
        roles = self.runner.roles()
        result = self.supervisor().observe(max_cycles=1)
        self.assertIn(result["items"][0]["state"], {"blocked", "conflict", "uncertain"}, result)
        self.assertEqual(self.runner.roles(), roles)
        self.assertFalse(result["completion"])

    def test_signed_draft_publication_and_later_observation_require_current_native_pr(self):
        self.queue["items"][0]["actions"].append("draft_pr")
        # Keep the real native Board provider. This transport supplies only the
        # remote publication endpoints, while the actual worker enforces grants.
        self.client = FakeClient()
        self.runner.execution.client = self.client
        self.accept(self.pending_execution())
        prepared = self.supervisor().run(max_cycles=1)
        self.assertEqual(prepared["items"][0]["state"], "prepared", prepared)
        pending = self.supervisor().observe(max_cycles=1)
        request = self.operation_request(pending, "draft_pr")
        waiting = self.supervisor().run(max_cycles=1)
        self.assertEqual(waiting["items"][0]["state"], "waiting_authority", waiting)
        self.assertEqual(self.client.writes, [])
        self.accept(request)
        published = self.supervisor().run(max_cycles=1)
        self.assertEqual(published["items"][0]["state"], "pr_open", published)
        self.assertEqual(published["items"][0]["child_evidence"]["pull_request_id"], 51)
        self.assertEqual(len(self.client.writes), 1)
        self.assertIs(self.client.prs[0]["isDraft"], True)
        self.assertEqual(self.client.prs[0]["targetRefName"], "refs/heads/develop")
        self.assertFalse(published["completion"])
        roles = self.runner.roles()
        good_pr, good_ref = deepcopy(self.client.prs[0]), deepcopy(self.client.refs[0])
        for drift in ("abandoned", "ref_changed", "missing"):
            with self.subTest(drift=drift):
                self.client.prs, self.client.refs = [deepcopy(good_pr)], [deepcopy(good_ref)]
                if drift == "abandoned":
                    self.client.prs[0]["status"] = "abandoned"
                elif drift == "ref_changed":
                    self.client.refs[0]["objectId"] = "c" * 40
                else:
                    self.client.prs = []
                observed = self.supervisor().observe(max_cycles=1)
                self.assertIn(observed["items"][0]["state"], {"blocked", "conflict", "uncertain"}, observed)
                self.assertEqual(len(self.client.writes), 1)
                self.assertEqual(self.runner.roles(), roles)
                self.assertFalse(observed["completion"])

    def test_unchanged_wait_stops_without_model_calls_or_duplicate_approval_cards(self):
        first = self.supervisor().observe(max_cycles=1)
        request = self.operation_request(first, "assess")
        inbox = approval.ApprovalInbox(self.runtime)
        first_card = inbox._current(request)
        first_bytes = (self.runtime / "approval-inbox" / (first_card["request_id"] + ".json")).read_bytes()
        self.now += 1
        repeated = self.supervisor().run(max_cycles=2)
        self.assertEqual(repeated["cycles"], 1, repeated)
        self.assertEqual(repeated["stop_reason"], "two_unchanged_observations", repeated)
        self.assertEqual(self.operation_request(repeated, "assess"), request)
        self.assertEqual((self.runtime / "approval-inbox" / (first_card["request_id"] + ".json")).read_bytes(), first_bytes)
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(len(list((self.runtime / "approval-inbox").glob("*.json"))), 1)
        self.assertFalse(repeated["completion"])

    def test_expired_accepted_response_cannot_start_child_or_become_progress(self):
        pending = self.supervisor().observe(max_cycles=1)
        request = self.operation_request(pending, "assess")
        self.accept(request, expires_at=self.now + 2)
        self.now += 3
        result = self.supervisor().run(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "waiting_authority", result)
        self.assertEqual(result["items"][0]["authority_status"], "invalid")
        self.assertEqual(self.runner.calls, [])
        self.assertIsNone(result["items"][0]["child_evidence"])
        self.assertFalse(result["completion"])

    def test_revoked_execution_response_does_not_claim_or_start_any_worker_role(self):
        request = self.pending_execution()
        response = self.accept(request)
        self.trust().registry["revoked_grants"].append(response["grant"]["payload"]["grant_id"])
        self.trust().update_trust()
        result = self.supervisor().run(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "waiting_authority", result)
        self.assertEqual(self.runner.roles(), ["assessment", "challenge"])
        self.assertFalse((self.runtime / "state" / "azure-worker" / "claims.json").exists())

    def test_native_revision_change_cannot_consume_previous_execution_approval(self):
        request = self.pending_execution()
        self.accept(request)
        self.http.raw["rev"] = 8
        result = self.supervisor().run(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "draft", result)
        self.assertIn("worker_packet.revision", result["items"][0]["missing_fields"])
        self.assertEqual(self.runner.roles(), ["assessment", "challenge"])
        self.assertFalse((self.runtime / "state" / "azure-worker" / "claims.json").exists())

    def test_incomplete_native_refresh_blocks_even_with_verified_execution_response(self):
        request = self.pending_execution()
        self.accept(request)
        self.http.missing = True
        result = self.supervisor().run(max_cycles=1)
        self.assertIn(result["items"][0]["state"], {"draft", "blocked"}, result)
        self.assertEqual(self.runner.roles(), ["assessment", "challenge"])
        self.assertFalse((self.runtime / "state" / "azure-worker" / "claims.json").exists())

    def test_changed_primary_source_requires_new_material_assessment_approval(self):
        request = self.pending_execution()
        self.accept(request)
        (self.workspace / "src" / "change.py").write_text("value = 2\n")
        result = self.supervisor().run(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "waiting_authority", result)
        self.assertEqual(result["items"][0]["next_action"], "assess")
        new_request = self.operation_request(result, "assess")
        self.assertNotEqual(new_request["bindings"], request["bindings"])
        self.assertEqual(self.runner.roles(), ["assessment", "challenge"])
        self.assertFalse((self.runtime / "state" / "azure-worker" / "claims.json").exists())

    def test_lost_successful_worker_response_reconciles_durable_candidate_before_retry(self):
        self.accept(self.pending_execution())
        original_execute = worker.AzureWorker.execute
        def successful_but_lost(instance, *args, **kwargs):
            original_execute(instance, *args, **kwargs)
            raise TimeoutError("synthetic lost child return after durable prepared receipt")
        with mock.patch.object(worker.AzureWorker, "execute", new=successful_but_lost):
            uncertain = self.supervisor().run(max_cycles=1)
        self.assertEqual(uncertain["items"][0]["state"], "uncertain", uncertain)
        before_roles = self.runner.roles()
        resumed = self.supervisor().observe(max_cycles=1)
        self.assertEqual(resumed["items"][0]["state"], "prepared", resumed)
        self.assert_candidate_evidence(resumed["items"][0]["child_evidence"])
        self.assertEqual(self.runner.roles(), before_roles)
        self.assertEqual(self.supervisor_state()["operation"]["state"], "verified")
        self.assertFalse(resumed["completion"])

    def test_exit_zero_without_acceptance_cannot_be_ingested_as_prepared(self):
        request = self.pending_execution()
        self.accept(request)
        self.runner.execution.write_acceptance_evidence = False
        result = self.supervisor().run(max_cycles=1)
        self.assertEqual(result["items"][0]["state"], "uncertain", result)
        claims = json.loads((self.runtime / "state" / "azure-worker" / "claims.json").read_text())
        self.assertNotEqual(claims[oracle_digest(self.packet)]["state"], "prepared")
        self.assertNotEqual(self.supervisor_state().get("child_evidence", {}).get("state"), "prepared")
        before_roles = self.runner.roles()
        restarted = self.supervisor().run(max_cycles=1)
        self.assertEqual(restarted["items"][0]["state"], "uncertain", restarted)
        self.assertEqual(self.runner.roles(), before_roles)
        self.assertFalse(restarted["completion"])

    def test_preview_reads_no_native_state_authority_or_process_and_creates_nothing(self):
        before = self.files()
        with mock.patch.object(approval, "verify_grant", side_effect=AssertionError("preview authority")), \
             mock.patch.object(self.provider, "inspect", side_effect=AssertionError("preview native read")), \
             mock.patch.object(dispatch, "AzureDispatcher", side_effect=AssertionError("preview child")):
            result = self.supervisor().preview()
        self.assertEqual(result["effects"], [])
        self.assertTrue(result["inert"])
        self.assertFalse(result["completion"])
        self.assertEqual(self.files(), before)
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(result["configuration"]["models"], self.config.report()["models"])

    def test_direct_baseline_reaches_verified_candidate_through_real_child_guards(self):
        report = self.assembled()
        self.assertTrue(report["valid"], report["missing_fields"])
        controller = self.controller(report)
        assessed = controller.assess(self.trust().grant("assess", controller.bindings))
        routed = runtime_config.resolve_routed_config(self.config, assessed["routing_provenance"], now=self.now)
        subject = worker.AzureWorker(routed, clock=lambda: self.now).authorization_bindings(self.packet, "local_execute")
        result = controller.execute(self.trust().grant("local_execute", subject), provider=self.provider)
        self.assert_candidate_evidence(result["worker_result"])

    def test_example_definitions_remain_actionable_drafts_without_fabricated_scope(self):
        directory = ROOT.parents[1] / "examples" / "instablinds" / "local-automation-runtime"
        definition = json.loads((directory / "supervisor-definition.example.json").read_text())
        queue = json.loads((directory / "supervisor-queue.example.json").read_text())
        self.assertEqual(queue["items"][0]["definition"], definition)
        self.assertEqual(queue["items"][0]["id"], definition["worker_packet"]["id"])
        (self.workspace / "docs" / "ai").mkdir(parents=True)
        (self.workspace / "docs" / "ai" / "agent-policy.md").write_text("Explicit operation approval is required.\n")
        before = self.files()
        report = intake_builder.build_intake(self.config, self.policy, definition, None,
                                             context_root=self.workspace, now=self.now)
        self.assertEqual(report["state"], "draft")
        self.assertFalse(report["completion"])
        self.assertFalse(report["execution_authorized"])
        self.assertTrue({"owner", "worker_packet.commands", "worker_packet.acceptance", "worker_packet.write_scope",
                         "worker_packet.base_commit", "worker_packet.branch"}.issubset(report["missing_fields"]))
        self.assertEqual(report["draft"]["worker_packet"]["commands"], [])
        self.assertEqual(report["draft"]["worker_packet"]["acceptance"], [])
        self.assertEqual(report["draft"]["worker_packet"]["write_scope"], [])
        self.assertEqual(report["effects"], [])
        self.assertEqual(self.files(), before)
        self.assertEqual(self.http.requests, [])
        self.assertEqual(self.runner.calls, [])

    def test_observed_guid_url_shape_preserves_53_applied_edges_and_prepares_only_18_unapproved_edges(self):
        """Synthetic protocol replay of the observed Azure URL format only.

        The committed historical fixture supplies the reviewed 37-node/71-edge
        contract. The applied subset is all predecessor additions on the 21
        rollout IDs recorded in the September 8 receipt. Neither those historical
        facts nor this simulated observation establishes current live state.
        """
        import atlas_azure_reconcile as reconcile
        manifest = json.loads((ROOT / "tests/fixtures/azure-website-dependencies.expected.json").read_text())
        rollout = {17, 18, 19, 21, 22, 24, 26, 28, 30, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43}
        expected = {(issue, predecessor) for issue, predecessors in manifest["dependencies"].items()
                    for predecessor in predecessors}
        applied = {(issue, predecessor) for issue, predecessor in expected if int(issue.rsplit(":", 1)[1]) in rollout}
        missing = expected - applied
        self.assertEqual(len(manifest["dependencies"]), 37)
        self.assertEqual((len(expected), len(applied), len(missing)), (71, 53, 18))
        self.assertEqual(manifest["approval_status"], "unapproved")
        self.assertIs(manifest["execution_authorized"], False)
        project_guid = "6fb87f10-7d68-41ad-88ae-7ec8cfce0699"
        def native_url(identifier):
            return "https://dev.azure.com/Instablinds/" + project_guid + "/_apis/wit/workItems/" + identifier.rsplit(":", 1)[1]
        items = {identifier: {"id": int(identifier.rsplit(":", 1)[1]), "rev": 7, "url": native_url(identifier),
                    "fields": {"System.TeamProject": "Instablinds", "System.State": "To Do",
                               "System.Title": "Synthetic historical dependency fixture",
                               "System.Tags": "human-owned-tag",
                               "System.Description": "SYNTHETIC PRIVATE DESCRIPTION MUST NOT ENTER PROPOSAL"},
                    "relations": []}
                 for identifier in manifest["dependencies"]}
        for issue, predecessor in sorted(applied):
            items[issue]["relations"].append({"rel": "System.LinkTypes.Dependency-Reverse", "url": native_url(predecessor)})
            items[predecessor]["relations"].append({"rel": "System.LinkTypes.Dependency-Forward", "url": native_url(issue)})
        class RawGuidHTTP:
            def __init__(self):
                self.requests = []
            def open(self, request, **kwargs):
                self.requests.append(request)
                if request.get_method() != "POST" or not urlparse(request.full_url).path.endswith("/_apis/wit/workitemsbatch"):
                    raise AssertionError("GUID shape evaluation permits only native batch reads")
                identifiers = json.loads(request.data)["ids"]
                rows = [deepcopy(items["azdo:Instablinds:Instablinds:" + str(identifier)]) for identifier in identifiers]
                return Response({"count": len(rows), "value": rows})
        self.http = RawGuidHTTP()
        self.client = azure.AzureDevOpsClient("Instablinds", "Instablinds", self.runtime,
            opener=self.http, interval=0, clock=lambda: self.now)
        self.provider = azure.AzureBoardsProvider(self.client)
        self.config = replace(self.config, capabilities=frozenset({"read"}))
        self.manifest = manifest
        self.packet["expected_manifest"] = manifest
        self.packet["inspection_authority"] = {}
        raw_before = deepcopy(items)
        with mock.patch.object(dispatch.AzureDispatcher, "assess", side_effect=AssertionError("no assessment")) as assess, \
             mock.patch.object(dispatch.AzureDispatcher, "execute", side_effect=AssertionError("no dispatch")) as execute, \
             mock.patch.object(worker.AzureWorker, "execute", side_effect=AssertionError("no worker")) as worker_execute, \
             mock.patch.object(worker.AzureWorker, "publish", side_effect=AssertionError("no publication")) as publish, \
             mock.patch.object(approval, "_invoke_issuer", side_effect=AssertionError("no signer")) as issuer, \
             mock.patch.object(azure, "azure_cli_headers", side_effect=AssertionError("no live authentication")) as authenticate:
            result = self.supervisor().observe(max_cycles=1)
        for action in (assess, execute, worker_execute, publish, issuer, authenticate):
            action.assert_not_called()
        self.assertEqual(result["items"][0]["state"], "blocked", result)
        self.assertFalse(result["completion"])
        self.assertEqual(result["requests"], [])
        diff = result["items"][0]["dependency_diff"]
        self.assertEqual((diff["expected_count"], diff["native_count"]), (71, 53))
        self.assertEqual({tuple(edge) for edge in diff["missing"]}, missing)
        self.assertEqual(diff["unexpected"], [])
        self.assertEqual(diff["preparation_status"], "prepared_unapproved", diff)
        snapshot = self.supervisor_state()["intake_report"]["snapshot"]
        self.assertTrue(snapshot["complete"])
        self.assertFalse(snapshot["dependency_complete"])
        self.assertEqual(snapshot["eligible_count"], 0)
        self.assertEqual(len(snapshot["items"]), 37)
        self.assertIn("execution-authority-not-established", snapshot["blockers"])
        proposal = json.loads(Path(diff["proposal_path"]).read_text())
        self.assertEqual(reconcile.validate_proposal(proposal, now=self.now), diff["proposal_sha256"])
        self.assertEqual(proposal["execution_eligibility"], "blocked")
        self.assertEqual(proposal["operator_owned_tags"], [])
        additions = {(change["issue_id"], predecessor) for change in proposal["changes"] for predecessor in change["add_predecessors"]}
        self.assertEqual(additions, missing)
        self.assertEqual({(edge["issue_id"], edge["predecessor"]) for edge in proposal["approved_dependencies"]}, missing)
        operations = [operation for patch in proposal["patches"] for operation in patch["json_patch"]]
        self.assertEqual(sum(operation["path"] == "/relations/-" for operation in operations), 18)
        self.assertTrue(all(operation["path"] in {"/rev", "/relations/-"} for operation in operations))
        self.assertTrue(all(patch["json_patch"][0]["op"] == "test" and patch["json_patch"][0]["path"] == "/rev" for patch in proposal["patches"]))
        self.assertEqual(len(proposal["baseline"]), 37)
        self.assertTrue(all(row["tags"] == "human-owned-tag" for row in proposal["baseline"].values()))
        self.assertNotIn("SYNTHETIC PRIVATE DESCRIPTION", json.dumps(proposal))
        self.assertEqual(items, raw_before)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse((self.runtime / "authority").exists())
        self.assertFalse((self.runtime / ".azure-dispatch").exists())
        self.assertFalse((self.runtime / "state" / "azure-worker").exists())
        self.assertTrue(self.http.requests)


if __name__ == "__main__":
    unittest.main()
