from __future__ import annotations

import contextlib
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
import atlas_dispatch as dispatch
import atlas_azure_devops as az
import atlas_azure_worker as worker
import atlas_runtime_config as config
import atlas_routing as routing
import atlas_human_gates as gates
from atlas_authority import AuthorityError, canonical_digest
from authority_fixture import AuthorityFixture

NOW = 1_800_000_000
URL = "https://dev.azure.com/Instablinds/Instablinds/_git/Website"


def source(identifier, kind, content, path=None, revision=None):
    return {"id": identifier, "kind": kind, "content": content, "path": path,
            "sha256": hashlib.sha256(content.encode()).hexdigest(), "observed_at": NOW, "revision": revision}


def canonical_text(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def routing_inputs():
    policy = json.loads((ROOT / "config" / "routing.example.json").read_text())
    policy["repository_url"] = URL
    packet = {"schema_version": 1, "id": "azdo:Instablinds:Instablinds:17", "revision": 7,
              "repository_url": URL, "base_branch": "develop", "base_commit": "a" * 40,
              "branch": "feature/routing-test", "write_scope": ["src/change.py"], "task": "Implement the reviewed localized behavior.",
              "commands": [{"id": "unit", "argv": ["python3", "-B", "tests/acceptance.py"], "timeout_seconds": 30}],
              "acceptance": [{"id": "unit-pass", "command_id": "unit", "evidence_file": "unit.json"}], "role_timeout_seconds": 60}
    snapshot = {"complete": True, "dependency_complete": True, "blockers": [],
        "observed_at": datetime.fromtimestamp(NOW, timezone.utc).isoformat(),
        "items": [{"id": packet["id"], "revision": 7, "eligible": True, "blockers": [], "dependencies": []}]}
    evidence = [source("issue", "issue", canonical_text({"id": packet["id"], "revision": 7}), revision=7),
                source("dependencies", "dependencies", canonical_text(snapshot), revision=7),
                source("instructions", "instructions", "Keep changes bounded and run acceptance.", "AGENTS.md"),
                source("file", "file", "value = 1\n", "src/change.py"),
                source("tests", "tests", "Run the reviewed acceptance command and provide candidate-bound JSON.")]
    intake = {"schema_version": 1, "worker_packet": packet,
        "step": {"id": "prepare", "kind": "coding", "action": "local_execute", "candidate_sha": None},
        "evidence": evidence, "readiness": {"issue_revision": 7, "observed_at": NOW, "complete": True,
            "dependency_complete": True, "dependencies_satisfied": True, "execution_authority_established": True,
            "source_sha256": canonical_digest(snapshot)}, "affected_paths": ["src/change.py"], "points": 2,
        "human_gates": [], "attempts": [],
        "budget": {"max_model_calls": 10, "max_tokens": 100000, "model_calls_used": 0, "tokens_used": 0}}
    return policy, intake, snapshot


class AssessmentRunner:
    def __init__(self):
        self.calls, self.contexts = [], []
        self.mutate = None
        self.omit_output = False
        self.failure = None
        self.responses = {}
        self.on_model = None

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if "--help" in argv:
            return types.SimpleNamespace(returncode=0, stdout="--sandbox --model --output-last-message --skip-git-repo-check --json --ephemeral --permission-profile --config --cd", stderr="")
        if "--version" in argv:
            return types.SimpleNamespace(returncode=0, stdout="codex-cli 0.153.4\n", stderr="")
        if self.failure:
            raise self.failure
        context = json.loads(kwargs["input"].split("\n", 1)[1])
        self.contexts.append(context)
        if self.on_model:
            self.on_model(context, argv, kwargs)
        result = {"work_type": "coding", "risk": "low", "uncertainty": "low", "verification": "strong",
            "suggested_profile": "routine", "required_gates": [], "unknowns": [], "evidence_ids": ["issue", "file", "tests"],
            "reason": "The scoped file and concrete acceptance evidence support a routine route."}
        result.update(self.responses.get(context["role"], {}))
        if self.mutate:
            self.mutate(result)
        if not self.omit_output:
            Path(argv[argv.index("--output-last-message") + 1]).write_text(json.dumps(result))
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 50}}), stderr="")


def claim_process(home, runtime, entered, release):
    with mock.patch.object(config.pwd, "getpwuid", return_value=types.SimpleNamespace(pw_dir=str(home))):
        with dispatch.DispatchStore(Path(runtime)).locked():
            entered.set()
            release.wait(10)


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.runtime = self.home / "runtime"
        self.runtime.mkdir(mode=0o700)
        (self.runtime / "worktrees").mkdir(mode=0o700)
        self.workspace = self.runtime / "worktrees" / "item-17"
        self.workspace.mkdir(mode=0o700)
        (self.workspace / ".git").mkdir(mode=0o700)
        (self.workspace / "src").mkdir(mode=0o700)
        (self.workspace / "src" / "change.py").write_text("value = 1\n")
        (self.workspace / "AGENTS.md").write_text("Keep changes bounded and run acceptance.")
        self.identity = mock.patch.object(config.pwd, "getpwuid", return_value=types.SimpleNamespace(pw_dir=str(self.home), pw_name="fixture"))
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.environment = mock.patch.dict(os.environ, {"HOME": str(self.home), "CODEX_HOME": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.policy, self.intake, self.snapshot = routing_inputs()
        self.config = config.RuntimeConfig("azure-devops", self.runtime,
            {"organization": "Instablinds", "project": "Instablinds", "name": "Website", "url": URL,
             "base_branch": "develop", "checkout": str(self.workspace)},
            frozenset({"read", "assess", "local_execute", "draft_pr"}),
            {role: config.RoleSettings("gpt-6-astra", "max", "fixture") for role in config.ROLES}, "fixture")
        self.runner = AssessmentRunner()
        self.now = NOW

    def controller(self, **kwargs):
        return dispatch.AzureDispatcher(self.config, self.policy, self.intake, self.snapshot,
            context_root=self.workspace, runner=self.runner, clock=lambda: self.now, **kwargs)

    def trust(self):
        return AuthorityFixture(self.runtime, policy_sha256=canonical_digest(self.policy), now=NOW)

    def assessed(self):
        controller = self.controller()
        authority = self.trust()
        grant = authority.grant("assess", controller.bindings)
        report = controller.assess(grant)
        return controller, authority, grant, report

    def snapshot_files(self):
        return {str(path.relative_to(self.home)): path.read_bytes() for path in self.home.rglob("*") if path.is_file()}

    def test_preview_creates_no_state_process_authorization_or_model_call(self):
        before = self.snapshot_files()
        with mock.patch.object(dispatch, "verify_grant", side_effect=AssertionError("preview auth")), mock.patch.object(dispatch.subprocess, "run", side_effect=AssertionError("preview process")):
            result = self.controller().preview()
        self.assertEqual(result["decision"]["state"], "needs_assessment")
        self.assertEqual(result["effects"], [])
        self.assertFalse(result["completion"])
        self.assertEqual(before, self.snapshot_files())

    def test_signed_assessment_runs_terra_and_blind_sol_with_parent_provenance(self):
        controller, authority, grant, result = self.assessed()
        self.assertEqual([item["role"] for item in self.runner.contexts], ["assessment", "challenge"])
        self.assertEqual(result["decision"]["profile"], "routine")
        self.assertEqual(result["resolved_configuration"]["models"]["implementation"]["model"], "gpt-5.6-terra")
        self.assertEqual(self.config.roles["implementation"].model, "gpt-6-astra")
        receipts = result["transport_receipts"]
        self.assertEqual([item["model"] for item in receipts], ["gpt-5.6-terra", "gpt-5.6-sol"])
        self.assertNotEqual(receipts[0]["workspace"], receipts[1]["workspace"])
        self.assertNotIn("prior_assessments", self.runner.contexts[1])
        self.assertEqual(result["budget_observed"]["model_calls"], 2)
        self.assertEqual(result["budget_observed"]["tokens_observed"], 300)
        for item in receipts:
            argv = item["argv"]
            self.assertEqual(argv[:3], ["codex", "exec", "--ignore-user-config"])
            for flag in ('approval_policy="on-request"', "sandbox_workspace_write.network_access=false", "sandbox_workspace_write.writable_roots=[]", "sandbox_workspace_write.exclude_slash_tmp=true"):
                self.assertIn(flag, argv)
            self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
            self.assertFalse((Path(item["workspace"]) / "result.json").exists())
        self.assertFalse(result["completion"])

    def test_primary_result_not_on_disk_when_independent_challenge_starts(self):
        def check(context, argv, kwargs):
            if context["role"] == "challenge":
                files = self.snapshot_files()
                phrase = b"The scoped file and concrete acceptance evidence support a routine route."
                self.assertFalse(any(phrase in data for data in files.values()))
        self.runner.on_model = check
        self.assessed()

    def test_missing_plain_forged_or_wrong_action_grant_cannot_assess(self):
        controller = self.controller()
        authority = self.trust()
        forged = authority.grant("assess", controller.bindings)
        forged["payload"]["bindings"]["packet_sha256"] = "c" * 64
        for grant in (None, {"approval_record": "approved"}, forged, authority.grant("local_execute", controller.bindings)):
            with self.subTest(grant=type(grant)), self.assertRaises(AuthorityError):
                controller.assess(grant)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse((self.runtime / ".azure-dispatch").exists())

    def test_waiting_dependencies_and_external_steps_consume_no_calls(self):
        for kind, action in (("human", "human_taste"), ("external", "pipeline_run"), ("deterministic", "inspect")):
            self.intake["step"].update(kind=kind, action=action)
            self.intake["human_gates"] = [] if kind == "deterministic" else [{"id": "human-step", "kind": "approval", "owner": "operator",
                "question": "Review the exact attached artifact.", "stage": "before", "action": action,
                "artifact_sha256": "d" * 64, "candidate_sha": None, "issue_id": self.intake["worker_packet"]["id"], "issue_revision": 7}]
            before = self.snapshot_files()
            report = self.controller().assess(None)
            self.assertEqual(self.runner.calls, [])
            self.assertEqual(self.snapshot_files(), before)
            self.assertFalse(report["completion"])
        self.intake["step"].update(kind="coding", action="local_execute")
        self.intake["human_gates"] = []
        self.snapshot["dependency_complete"] = False
        self.intake["readiness"]["dependency_complete"] = False
        self.intake["readiness"]["source_sha256"] = canonical_digest(self.snapshot)
        self.intake["evidence"][1] = source("dependencies", "dependencies", canonical_text(self.snapshot), revision=7)
        self.assertEqual(self.controller().assess(None)["decision"]["state"], "blocked")
        self.assertEqual(self.runner.calls, [])

    def test_unchanged_cache_reuses_no_model_call_but_reverifies_trust(self):
        controller, authority, grant, report = self.assessed()
        calls = len(self.runner.calls)
        cached = controller.assess(grant)
        self.assertTrue(cached["cached"])
        self.assertEqual(len(self.runner.calls), calls)
        authority.registry["revoked_grants"].append(grant["payload"]["grant_id"])
        authority.update_trust()
        with self.assertRaises(AuthorityError):
            controller.assess(grant)
        self.assertEqual(len(self.runner.calls), calls)

    def test_cache_expiry_and_source_drift_cannot_execute(self):
        controller, authority, grant, report = self.assessed()
        self.now += 901
        with self.assertRaises(dispatch.DispatchBlocked):
            controller.execute(None)
        self.now = NOW
        (self.workspace / "src" / "change.py").write_text("value = 2\n")
        with self.assertRaises(dispatch.DispatchBlocked):
            controller.execute(None)

    def test_changed_input_cannot_reuse_old_grant_or_reset_durable_budget(self):
        controller, authority, grant, report = self.assessed()
        self.intake["points"] = 3
        changed = self.controller()
        with self.assertRaises(AuthorityError):
            changed.assess(grant)
        # Account for already-consumed worker calls in this same immutable
        # issue/step/policy lineage; a fresh grant may not reset the counter.
        budget = controller.store.read("budget", controller.lineage)
        budget["model_calls"] = self.intake["budget"]["max_model_calls"]
        controller.store.write("budget", controller.lineage, budget)
        newer = authority.grant("assess", changed.bindings, grant_id="newly-issued-does-not-reset-budget")
        with self.assertRaisesRegex(dispatch.DispatchBlocked, "budget"):
            changed.assess(newer)
        self.assertEqual(len(self.runner.contexts), 2)

    def test_material_disagreement_gets_only_one_evidence_bound_reassessment(self):
        self.runner.responses["challenge"] = {"risk": "high", "suggested_profile": "sensitive"}
        self.runner.responses["reassessment"] = {"risk": "high", "suggested_profile": "sensitive"}
        controller, authority, grant, result = self.assessed()
        self.assertEqual([item["role"] for item in self.runner.contexts], ["assessment", "challenge", "reassessment"])
        self.assertIn("prior_assessments", self.runner.contexts[-1])
        self.assertEqual(result["decision"]["profile"], "sensitive")
        self.assertEqual(result["budget_observed"]["model_calls"], 3)
        self.assertTrue(controller.assess(grant)["cached"])

    def test_changed_intakes_and_new_grants_cannot_reset_attempt_limit(self):
        controller, authority, grant, report = self.assessed()
        self.intake["points"] = 3
        second = self.controller()
        second.assess(authority.grant("assess", second.bindings, grant_id="second-intake"))
        self.assertEqual(second.store.read("budget", second.lineage)["assessment_attempts"], 2)
        self.assertEqual(len(self.runner.contexts), 4)
        self.intake["points"] = 4
        third = self.controller()
        with self.assertRaisesRegex(dispatch.DispatchBlocked, "attempt"):
            third.assess(authority.grant("assess", third.bindings, grant_id="third-intake"))
        self.assertEqual(len(self.runner.contexts), 4)

    def test_corrupt_budget_counters_block_before_the_next_model_call(self):
        controller, authority, grant, report = self.assessed()
        self.intake["points"] = 3
        changed = self.controller()
        budget = controller.store.read("budget", controller.lineage)
        budget["tokens_observed"] = -100000
        controller.store.write("budget", controller.lineage, budget)
        with self.assertRaisesRegex(dispatch.DispatchBlocked, "counters"):
            changed.assess(authority.grant("assess", changed.bindings, grant_id="changed-input"))
        self.assertEqual(len(self.runner.contexts), 2)

    def test_unresolved_disagreement_stops_after_third_call(self):
        self.runner.responses["challenge"] = {"risk": "high"}
        self.runner.responses["reassessment"] = {"risk": "medium"}
        controller, authority, grant, result = self.assessed()
        self.assertFalse(result["decision"]["route_ready"])
        self.assertEqual(len(self.runner.contexts), 3)
        with self.assertRaises(config.RuntimeConfigError):
            controller.execute(None)

    def test_missing_output_and_timeout_consume_reserved_call_never_complete(self):
        controller = self.controller()
        authority = self.trust()
        grant = authority.grant("assess", controller.bindings)
        self.runner.omit_output = True
        with self.assertRaises(OSError):
            controller.assess(grant)
        self.assertEqual(controller.store.read("budget", controller.lineage)["model_calls"], 1)
        with self.assertRaises(dispatch.DispatchBlocked):
            controller.assess(grant)
        self.assertEqual(len(self.runner.contexts), 1)

    def test_timeout_is_not_retried_with_new_grant(self):
        controller = self.controller()
        authority = self.trust()
        self.runner.failure = subprocess.TimeoutExpired("codex", 180)
        with self.assertRaises(dispatch.DispatchBlocked):
            controller.assess(authority.grant("assess", controller.bindings))
        self.assertEqual(controller.store.read("budget", controller.lineage)["model_calls"], 1)
        with self.assertRaises(dispatch.DispatchBlocked):
            controller.assess(authority.grant("assess", controller.bindings, grant_id="replacement"))

    def test_missing_cli_fails_before_any_model_call(self):
        controller = self.controller()
        authority = self.trust()
        controller.runner = mock.Mock(side_effect=FileNotFoundError())
        with self.assertRaises(dispatch.DispatchBlocked):
            controller.assess(authority.grant("assess", controller.bindings))
        self.assertIsNone(controller.store.read("budget", controller.lineage))

    def test_model_cannot_forge_parent_wrapper_or_nonexistent_evidence(self):
        self.runner.mutate = lambda value: value.update(model="gpt-6-astra")
        controller = self.controller()
        authority = self.trust()
        with self.assertRaises(routing.RoutingError):
            controller.assess(authority.grant("assess", controller.bindings))
        self.assertEqual(len(self.runner.contexts), 1)

    def test_model_cannot_cite_nonexistent_evidence(self):
        self.runner.mutate = lambda value: value.update(evidence_ids=["imaginary-test"])
        controller = self.controller()
        authority = self.trust()
        with self.assertRaises(routing.RoutingError):
            controller.assess(authority.grant("assess", controller.bindings))

    def test_modified_parent_receipt_or_model_argv_is_rejected(self):
        controller, authority, grant, report = self.assessed()
        job = controller.store.read("job", controller.key)
        job["calls"][0]["transport"]["argv"][0] = "shell"
        entry = job["calls"][0]
        entry["receipt_sha256"] = canonical_digest({"wrapper": entry["wrapper"], "transport": entry["transport"]})
        controller.store.write("job", controller.key, job)
        with self.assertRaises(dispatch.DispatchBlocked):
            controller.assess(grant)

    def test_context_secret_paths_symlinks_binary_size_and_hash_are_rejected(self):
        for path in ("../secret", "/etc/passwd", ".env", "credentials/private.key", "authority/trust.json"):
            value = deepcopy(self.intake)
            value["evidence"][3]["path"] = path
            with self.subTest(path=path), self.assertRaises(dispatch.DispatchBlocked):
                dispatch.collect_context(value, self.workspace)
        path = self.workspace / "src" / "change.py"
        path.unlink()
        path.symlink_to(self.workspace / "AGENTS.md")
        with self.assertRaises(dispatch.DispatchBlocked):
            dispatch.collect_context(self.intake, self.workspace)

    def test_relevant_file_drift_between_model_calls_stops_challenge(self):
        def change(context, argv, kwargs):
            (self.workspace / "src" / "change.py").write_text("value = 9\n")
        self.runner.on_model = change
        controller = self.controller()
        authority = self.trust()
        with self.assertRaises(dispatch.DispatchBlocked):
            controller.assess(authority.grant("assess", controller.bindings))
        self.assertEqual(len(self.runner.contexts), 1)

    def test_concurrent_process_claim_prevents_duplicate_assessment(self):
        process_context = multiprocessing.get_context("fork")
        entered, release = process_context.Event(), process_context.Event()
        process = process_context.Process(target=claim_process, args=(self.home, self.runtime, entered, release))
        process.start()
        self.addCleanup(lambda: process.terminate() if process.is_alive() else None)
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(dispatch.DispatchBlocked):
                with dispatch.DispatchStore(self.runtime).locked():
                    self.fail("duplicate process entered claim")
        finally:
            release.set()
            process.join(5)
        self.assertEqual(process.exitcode, 0)

    def test_symlinked_state_root_never_writes_external_path(self):
        external = self.home / "external"
        external.mkdir(mode=0o700)
        (self.runtime / ".azure-dispatch").symlink_to(external, target_is_directory=True)
        controller = self.controller()
        authority = self.trust()
        with self.assertRaises(dispatch.DispatchBlocked):
            controller.assess(authority.grant("assess", controller.bindings))
        self.assertEqual(list(external.iterdir()), [])

    def test_execution_requires_separate_exact_signed_grant_before_executor(self):
        factory = mock.Mock()
        controller = self.controller(worker_factory=factory)
        authority = self.trust()
        assess_grant = authority.grant("assess", controller.bindings)
        controller.assess(assess_grant)
        with self.assertRaises(worker.WorkerBlocked):
            controller.execute(assess_grant)
        factory.assert_not_called()

    def human_gate(self, kind="input", action="local_execute"):
        gate = {"id": "human-input", "kind": kind, "owner": "operator", "question": "Which behavior should this candidate use?",
            "stage": "before", "action": action, "artifact_sha256": "d" * 64, "candidate_sha": None,
            "issue_id": self.intake["worker_packet"]["id"], "issue_revision": 7}
        self.intake["human_gates"] = [gate]
        return gate

    def human_receipt(self, authority, gate, response="Use the compact layout."):
        receipt = {"gate_id": gate["id"], "decision": "accepted", "response": response, "grant": {}}
        bindings = gates.gate_bindings(gate, receipt, {"issue_id": self.intake["worker_packet"]["id"], "issue_revision": 7,
            "worker_packet_sha256": canonical_digest(self.intake["worker_packet"]), "candidate_sha": None,
            "action": gate["action"], "policy_sha256": canonical_digest(self.policy)})
        receipt["grant"] = authority.grant("human_gate", bindings, grant_id="human-answer")
        return receipt

    def test_approval_can_follow_assessment_but_missing_input_waits_without_calls(self):
        self.human_gate(kind="input")
        before = self.snapshot_files()
        self.assertEqual(self.controller().assess(None)["mode"], "waiting")
        self.assertEqual(before, self.snapshot_files())
        self.assertEqual(self.runner.calls, [])
        self.intake["human_gates"][0]["kind"] = "approval"
        controller, authority, grant, result = self.assessed()
        self.assertEqual(len(self.runner.contexts), 2)
        self.assertEqual(result["decision"]["state"], "waiting_human")
        self.assertFalse(result["decision"]["dispatchable"])

    def test_signed_human_answer_reaches_both_independent_contexts_and_binds_cache(self):
        gate = self.human_gate()
        response = "Use the compact layout."
        self.intake["evidence"].append(source("human-answer:" + gate["id"], "issue",
            canonical_text({"gate_id": gate["id"], "response": response}), revision=7))
        controller = self.controller()
        authority = self.trust()
        receipt = self.human_receipt(authority, gate, response)
        grant = authority.grant("assess", controller.bindings)
        result = controller.assess(grant, human_receipts=[receipt])
        self.assertTrue(result["decision"]["route_ready"])
        for context in self.runner.contexts:
            self.assertIn(response, canonical_text(context["intake"]["evidence"]))
        old_calls = len(self.runner.calls)
        changed = self.human_receipt(authority, gate, "Use the expanded layout.")
        with self.assertRaises(gates.HumanGateError):
            controller.assess(grant, human_receipts=[changed])
        self.assertEqual(len(self.runner.calls), old_calls)

    def test_handoff_receipt_verification_never_executes_pipeline(self):
        self.intake["step"].update(kind="external", action="pipeline_run")
        gate = self.human_gate(kind="approval", action="pipeline_run")
        controller = self.controller()
        authority = self.trust()
        receipt = self.human_receipt(authority, gate)
        before = self.snapshot_files()
        report = controller.check_handoff([receipt])
        self.assertEqual(report["state"], "gate_evidence_verified")
        self.assertEqual(report["effects"], [])
        self.assertFalse(report["completion"])
        self.assertEqual(before, self.snapshot_files())
        self.assertEqual(self.runner.calls, [])

    def test_direct_worker_cannot_use_synthetic_recommendations_without_parent_run(self):
        controller, authority, grant, report = self.assessed()
        routed = config.resolve_routed_config(self.config, report["routing_provenance"], now=NOW)
        self.assertTrue(dispatch.verify_routing_transport(routed, now=NOW)["verified"])
        (controller.store.root / ("job-" + controller.key + ".json")).unlink()
        with self.assertRaises(dispatch.DispatchBlocked):
            dispatch.verify_routing_transport(routed, now=NOW)

    def test_direct_transport_rejects_changed_context_even_with_recomputed_outer_hash(self):
        controller, authority, grant, report = self.assessed()
        routed = config.resolve_routed_config(self.config, report["routing_provenance"], now=NOW)
        original = controller.store.read("job", controller.key)
        for key, value in (("context_sha256", "0" * 64), ("prompt_sha256", "0" * 64),
                           ("model", "gpt-6-astra"), ("protocol_version", True)):
            changed = deepcopy(original)
            call = changed["calls"][0]
            call["transport"][key] = value
            call["receipt_sha256"] = canonical_digest({"wrapper": call["wrapper"], "transport": call["transport"]})
            controller.store.write("job", controller.key, changed)
            with self.subTest(key=key), self.assertRaises(dispatch.DispatchBlocked):
                dispatch.verify_routing_transport(routed, now=NOW)

    def test_shared_worker_counter_cannot_exceed_assessment_budget(self):
        controller, authority, grant, report = self.assessed()
        routed = config.resolve_routed_config(self.config, report["routing_provenance"], now=NOW)
        dispatch.reserve_routing_call(routed, role="planning", timeout=60)
        with self.assertRaises(dispatch.DispatchBlocked):
            dispatch.reserve_routing_call(routed, role="implementation", timeout=60)
        dispatch.record_routing_usage(routed, 125)
        for number in range(7):
            dispatch.reserve_routing_call(routed, role="review", timeout=60)
            dispatch.record_routing_usage(routed, 125)
        self.assertEqual(dispatch.budget_report(routed)["model_calls"], 10)
        with self.assertRaises(dispatch.DispatchBlocked):
            dispatch.reserve_routing_call(routed, role="repair", timeout=60)

    def test_real_provider_and_worker_integration_preserves_manifest_and_auth_order(self):
        from test_azure_devops import Response
        from test_azure_worker import FakeRunner, FakeClient
        packet = self.intake["worker_packet"]
        manifest = {"schema_version": 1, "organization": "Instablinds", "project": "Instablinds",
                    "dependencies": {packet["id"]: []}}
        packet["expected_manifest"] = manifest
        packet["inspection_authority"] = {"dependency_contract_sha256": az.canonical_digest(manifest),
            "approval_record": "synthetic graph-only fixture", "execution_authorized": True}
        raw = {"id": 17, "rev": 7, "fields": {"System.State": "To Do", "System.TeamProject": "Instablinds", "System.Title": "Fixture"}, "relations": []}
        requests = []
        class LocalHTTP:
            def open(self, request, **kwargs):
                requests.append(request)
                return Response({"count": 1, "value": [raw]})
        original_client = az.AzureDevOpsClient
        local_client = original_client("Instablinds", "Instablinds", self.runtime, opener=LocalHTTP(), interval=0, clock=lambda: NOW)
        self.snapshot = az.AzureBoardsProvider(local_client).inspect([packet["id"]], expected_manifest=manifest, authority=packet["inspection_authority"], fresh=True)
        self.assertTrue(self.snapshot["items"][0]["eligible"])
        self.intake["readiness"]["source_sha256"] = canonical_digest(self.snapshot)
        self.intake["evidence"][1] = source("dependencies", "dependencies", canonical_text(self.snapshot), revision=7)
        controller, authority, assess_grant, report = self.assessed()
        routed = config.resolve_routed_config(self.config, report["routing_provenance"], now=NOW)
        local_runner = FakeRunner(packet, FakeClient())
        def runner(argv, **kwargs):
            result = local_runner(argv, **kwargs)
            if argv[:2] == ["codex", "exec"] and "--help" not in argv:
                result.stdout = json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}})
            return result
        controller.runner = runner
        signed = authority.grant("local_execute", worker.AzureWorker(routed, clock=lambda: NOW).authorization_bindings(packet, "local_execute"))
        observed_headers = []
        def create_client(*args, **kwargs):
            observed_headers.append(kwargs["headers"])
            return original_client(*args, **kwargs, opener=LocalHTTP(), interval=0, clock=lambda: NOW)
        with mock.patch.object(az, "AzureDevOpsClient", side_effect=create_client), mock.patch.object(az, "azure_cli_headers", return_value={"X-Test-Identity": "synthetic"}) as authenticate:
            provider = dispatch.deferred_azure_provider(self.config)
            with self.assertRaises(worker.WorkerBlocked):
                controller.execute(assess_grant, provider=provider)
            authenticate.assert_not_called()
            result = controller.execute(signed, provider=provider)
        self.assertEqual(result["worker_result"]["state"], "prepared")
        self.assertFalse(result["completion"])
        self.assertTrue(observed_headers)
        self.assertTrue(all(headers == {"X-Test-Identity": "synthetic"} for headers in observed_headers))
        self.assertTrue(any(request.get_header("X-test-identity") == "synthetic" for request in requests))

    def test_changed_snapshot_revision_does_not_get_laundered_as_fresh_readiness(self):
        self.snapshot["items"][0]["revision"] = 8
        self.intake["readiness"]["source_sha256"] = canonical_digest(self.snapshot)
        self.intake["evidence"][1] = source("dependencies", "dependencies", canonical_text(self.snapshot), revision=7)
        with self.assertRaises(dispatch.DispatchBlocked):
            self.controller()

    def test_preview_cli_without_B_does_not_write_bytecode_or_state(self):
        inputs = {"policy": self.policy, "intake": self.intake, "snapshot": self.snapshot,
            "config": {"schema_version": 1, "provider": "azure-devops", "repository": self.config.repository,
                "capabilities": ["read"], "models": {role: {"model": "gpt-6-astra", "reasoning": "max"} for role in config.ROLES},
                "sandbox": "workspace-write", "approval_policy": "on-request"}}
        for name, value in inputs.items():
            (self.home / (name + ".json")).write_text(json.dumps(value))
        source_dir = self.home / "source"
        source_dir.mkdir()
        for name in ("atlas-agent-azure-dispatch", "atlas_dispatch.py", "atlas_routing.py", "atlas_human_gates.py", "atlas_authority.py", "atlas_runtime_config.py", "atlas_azure_worker.py", "atlas_azure_devops.py"):
            (source_dir / name).write_bytes((ROOT / name).read_bytes())
        before = self.snapshot_files()
        launcher = ("import pwd,sys,types,runpy; home=sys.argv.pop(1); pwd.getpwuid=lambda uid: types.SimpleNamespace(pw_dir=home,pw_name='fixture'); runpy.run_path(sys.argv.pop(1),run_name='__main__')")
        argv = [sys.executable, "-c", launcher, str(self.home), str(source_dir / "atlas-agent-azure-dispatch"),
                "--runtime-dir", str(self.runtime), "--context-root", str(self.workspace)]
        for name in inputs:
            argv += ["--" + name, str(self.home / (name + ".json"))]
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "PYTHONPATH"}}
        result = subprocess.run(argv, text=True, capture_output=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["effects"], [])
        self.assertEqual(before, self.snapshot_files())


if __name__ == "__main__":
    unittest.main()
