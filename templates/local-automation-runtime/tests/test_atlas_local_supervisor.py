from __future__ import annotations

import copy
import hashlib
import hashlib
import importlib.machinery
import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader("atlas_agent_orchestrator_budget_test", str(ROOT / "atlas-agent-orchestrator"))
spec = importlib.util.spec_from_loader(loader.name, loader)
orchestrator = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = orchestrator
loader.exec_module(orchestrator)


def fixtures():
    return (
        {"max_steps": 3, "max_claims": 2, "max_roles": 5, "role_max": 3, "cycle_seconds": 10.0},
        {"steps": 0, "claims_reserved": 0, "roles_reserved": 0, "cancelled": False, "cancel_reason": None},
        {"kind": "check", "elapsed_seconds": 0.0, "stop_requested": False},
    )


class BudgetReducerTests(unittest.TestCase):
    reduce = staticmethod(orchestrator._bounded_budget_reduce)

    def test_budget_reduce_each_event_shape_and_reservation(self):
        limits, state, event = fixtures()
        expected = {
            "step": {"steps": 1, "claims_reserved": 0, "roles_reserved": 0, "cancelled": False, "cancel_reason": None},
            "claim": {"steps": 0, "claims_reserved": 1, "roles_reserved": 0, "cancelled": False, "cancel_reason": None},
            "launch": {"steps": 0, "claims_reserved": 0, "roles_reserved": 3, "cancelled": False, "cancel_reason": None},
        }
        for kind, new_state in expected.items():
            with self.subTest(kind=kind):
                result = self.reduce(limits, state, {**event, "kind": kind})
                self.assertEqual(list(result), ["state", "allowed", "role_allowance", "stop_reason"])
                self.assertEqual(result["state"], new_state)
                self.assertEqual(result["allowed"], True)
                self.assertIsNone(result["stop_reason"])
                self.assertEqual(result["role_allowance"], 3 if kind == "launch" else 0)

    def test_budget_reduce_last_step_claim_last_claim_launch_and_partial_allowance(self):
        limits, state, event = fixtures()
        state.update(steps=2, claims_reserved=1)
        result = self.reduce(limits, state, {**event, "kind": "step"})
        self.assertTrue(result["allowed"])
        self.assertEqual(result["state"]["steps"], 3)
        result = self.reduce(limits, result["state"], {**event, "kind": "claim"})
        self.assertTrue(result["allowed"])
        self.assertEqual(result["state"]["claims_reserved"], 2)
        result = self.reduce(limits, result["state"], {**event, "kind": "launch"})
        self.assertEqual(result["role_allowance"], 3)
        state["roles_reserved"] = 4
        result = self.reduce(limits, state, {**event, "kind": "launch"})
        self.assertEqual(result["role_allowance"], 1)
        self.assertEqual(result["state"]["roles_reserved"], 5)

    def test_budget_reduce_exhausted_budgets_and_check_settlement(self):
        limits, state, event = fixtures()
        for field, kind in (("steps", "step"), ("claims_reserved", "claim"), ("roles_reserved", "launch")):
            exhausted = copy.deepcopy(state)
            exhausted[field] = limits[{"steps": "max_steps", "claims_reserved": "max_claims", "roles_reserved": "max_roles"}[field]]
            refused = self.reduce(limits, exhausted, {**event, "kind": kind})
            self.assertFalse(refused["allowed"], field)
            self.assertEqual(refused["stop_reason"], "budget_stop")
            settled = self.reduce(limits, exhausted, {**event, "kind": "check"})
            self.assertTrue(settled["allowed"])
            self.assertEqual(settled["state"], exhausted)
        # step gates on any exhausted cycle budget; claim gates on claims and roles.
        for field, value in (("claims_reserved", 2), ("roles_reserved", 5)):
            exhausted = {**state, field: value}
            self.assertEqual(self.reduce(limits, exhausted, {**event, "kind": "step"})["stop_reason"], "budget_stop")
        self.assertEqual(self.reduce(limits, {**state, "roles_reserved": 5}, {**event, "kind": "claim"})["stop_reason"], "budget_stop")

    def test_budget_reduce_deadline_equality_stop_precedence_and_stable_latch(self):
        limits, state, event = fixtures()
        deadline = self.reduce(limits, state, {**event, "kind": "step", "elapsed_seconds": 10})
        self.assertEqual(deadline["state"]["cancel_reason"], "deadline")
        self.assertFalse(deadline["allowed"])
        both = self.reduce(limits, state, {**event, "stop_requested": True, "elapsed_seconds": 10})
        self.assertEqual(both["state"]["cancel_reason"], "stop")
        stable = self.reduce(limits, both["state"], {**event, "kind": "claim"})
        self.assertEqual(stable["state"]["cancel_reason"], "stop")
        self.assertFalse(stable["allowed"])
        self.assertEqual(stable["stop_reason"], "cancelled")

    def test_budget_reduce_no_refund_and_inputs_never_mutate(self):
        limits, state, event = fixtures()
        before = copy.deepcopy((limits, state, event))
        first = self.reduce(limits, state, {**event, "kind": "claim"})
        lost_ack_state = first["state"]
        self.assertEqual(lost_ack_state["claims_reserved"], 1)
        self.assertEqual(self.reduce(limits, lost_ack_state, {**event, "kind": "claim"})["state"]["claims_reserved"], 2)
        self.assertEqual((limits, state, event), before)
        self.assertIsNot(first["state"], state)

    def test_budget_reduce_rejects_bad_shapes_types_and_domains(self):
        base_limits, base_state, base_event = fixtures()
        for value in (None, [], {**base_limits, "extra": 1}, {k: v for k, v in base_limits.items() if k != "max_steps"}):
            with self.subTest(group="limits-shape", value=value):
                with self.assertRaises(ValueError): self.reduce(value, base_state, base_event)
        for field in ("max_steps", "max_claims", "max_roles", "role_max"):
            for value in (True, 1.0, 0, -1):
                bad = {**base_limits, field: value}
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError): self.reduce(bad, base_state, base_event)
        with self.assertRaises(ValueError): self.reduce({**base_limits, "role_max": 101}, base_state, base_event)
        for value in (True, 0, -1, float("nan"), float("inf"), -float("inf"), "1", []):
            with self.subTest(cycle_seconds=value):
                with self.assertRaises(ValueError): self.reduce({**base_limits, "cycle_seconds": value}, base_state, base_event)
        for field, maximum in (("steps", 3), ("claims_reserved", 2), ("roles_reserved", 5)):
            for value in (True, 1.0, -1, maximum + 1):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError): self.reduce(base_limits, {**base_state, field: value}, base_event)
        for bad_state in (
            None,
            {**base_state, "unexpected": 1},
            {k: v for k, v in base_state.items() if k != "steps"},
            {**base_state, "cancelled": 1},
            {**base_state, "cancelled": True},
            {**base_state, "cancel_reason": "unknown"},
        ):
            with self.subTest(state=bad_state):
                with self.assertRaises(ValueError): self.reduce(base_limits, bad_state, base_event)
        for bad_event in (
            None,
            {**base_event, "extra": 1},
            {k: v for k, v in base_event.items() if k != "kind"},
            {**base_event, "kind": "refund"},
            {**base_event, "stop_requested": 0},
        ):
            with self.subTest(event=bad_event):
                with self.assertRaises(ValueError): self.reduce(base_limits, base_state, bad_event)
        for value in (True, -1, float("nan"), float("inf"), -float("inf"), "0", {}):
            with self.subTest(elapsed=value):
                with self.assertRaises(ValueError): self.reduce(base_limits, base_state, {**base_event, "elapsed_seconds": value})
        huge = 10**10000
        self.assertTrue(self.reduce({**base_limits, "max_steps": huge}, {**base_state, "steps": huge - 1}, {**base_event, "kind": "step"})["allowed"])
        self.assertTrue(math.isfinite(base_limits["cycle_seconds"]))


RESULT_ROLES = [
    {"role_id": "implementation", "required_outputs": ["change_summary", "changed_files", "implementation_notes"], "consumes": [], "goal_gate": False},
    {"role_id": "test-runner", "required_outputs": ["commands_run", "test_results", "coverage_or_gap_notes"], "consumes": ["implementation"], "goal_gate": False},
    {"role_id": "code-review", "required_outputs": ["findings", "risk_level", "required_fixes"], "consumes": ["implementation", "test-runner"], "goal_gate": False},
    {"role_id": "semantic-alignment", "required_outputs": ["plan_alignment", "intent_model_alignment", "behavioral_risks", "vision_drift_notes"], "consumes": ["implementation", "test-runner"], "goal_gate": True},
    {"role_id": "evidence-rollup", "required_outputs": ["final_evidence_document", "remaining_risks", "next_actions"], "consumes": ["implementation", "test-runner", "code-review", "semantic-alignment"], "goal_gate": False},
]


def result_assessment_fixture(completed, attempted, *, goal_verdict="missing", status="ready", baseline=None):
    expected = {
        "source_type": "atlas_work_item", "source_id": "work/123", "operation_id": "op-456",
        "work_item_id": "work/123", "template_id": "work-item-change-lifecycle",
        "template_workflow_kind": "work-item", "request_workflow_kind": "work-item", "run_id": "work-123-invoke-1" if baseline else None,
        "completed_roles_before": sorted(baseline or []), "roles": copy.deepcopy(RESULT_ROLES),
        "goal_required": True, "context_hash": "a" * 64, "contract_hash": "b" * 64,
    }
    completed_set, attempted_set = set(completed), set(attempted)
    goal_review = None
    if goal_verdict in {"pass", "fail", "inconclusive"}:
        goal_review = {"verdict": goal_verdict, "reason": "Reviewed against the plan.", "evidence": ["synthetic review evidence"]}
    summary_roles = []
    for role in RESULT_ROLES:
        rid = role["role_id"]
        is_done = rid in completed_set
        summary_roles.append({
            "role_id": rid, "status": "complete" if is_done else "pending",
            "required_outputs": list(role["required_outputs"]),
            "completed_outputs": list(role["required_outputs"]) if is_done else [],
            "contract_issues": [], "dependency_blockers": [], "goal_gate": role["goal_gate"],
            "goal_review": goal_review if role["goal_gate"] and rid in attempted_set else None,
        })
    missing = {role["role_id"]: list(role["required_outputs"]) for role in RESULT_ROLES if role["role_id"] not in completed_set}
    phases = [["implementation"], ["test-runner"], ["code-review", "semantic-alignment"], ["evidence-rollup"]]
    run_status = "running" if missing else "complete"
    gate_review = summary_roles[3]["goal_review"]
    goal_evidence = {
        "verdict": goal_verdict, "reason": "Goal review not available." if goal_verdict == "missing" else gate_review["reason"],
        "evidence": [] if goal_verdict == "missing" else gate_review["evidence"],
        "role_id": "semantic-alignment", "context_hash": expected["context_hash"], "contract_hash": expected["contract_hash"],
    }
    evidence = {
        "process_invocation_id": "invoke-1", "invocation_completed": True, "termination_proved": True,
        "completed_roles_before": list(expected["completed_roles_before"]), "completed_roles": [r["role_id"] for r in RESULT_ROLES if r["role_id"] in completed_set],
        "attempted_roles": [r["role_id"] for r in RESULT_ROLES if r["role_id"] in attempted_set],
        "team_roles": [r["role_id"] for r in RESULT_ROLES], "team_run_status": run_status,
        "missing_outputs": copy.deepcopy(missing), "goal_review_required": True, "goal_acceptance": goal_evidence,
        "contract_hash": expected["contract_hash"],
        "team_run": {"run_id": "work-123-invoke-1", "template_id": expected["template_id"], "work_item_id": expected["work_item_id"],
                     "workflow_kind": expected["template_workflow_kind"], "status": run_status, "role_phases": phases,
                     "missing_outputs": copy.deepcopy(missing), "roles": summary_roles},
        "workflow_continuation": {"reason": "continue staged execution", "next_status": status},
    }
    return {"status": status, "returncode": 0, "summary": "synthetic", "evidence": evidence}, expected


class ResultAssessmentTests(unittest.TestCase):
    assess = staticmethod(orchestrator._bounded_result_assessment)

    def test_budget_reduce_regression_contract_is_present(self):
        self.assertTrue(callable(orchestrator._bounded_budget_reduce))

    def test_result_assessment_five_role_staged_goal_then_rollup_and_done(self):
        first, expected = result_assessment_fixture(["implementation", "test-runner"], ["implementation", "test-runner"], goal_verdict="missing")
        first_before = copy.deepcopy(first)
        assessment = self.assess(first, expected)
        self.assertEqual(assessment, {"decision": "continue_candidate", "reason": None, "new_completed_roles": ["implementation", "test-runner"]})
        self.assertEqual(first, first_before)
        second, expected2 = result_assessment_fixture(["implementation", "test-runner", "semantic-alignment"], ["implementation", "test-runner", "semantic-alignment"], goal_verdict="pass", status="queued", baseline=["implementation", "test-runner"])
        self.assertEqual(self.assess(second, expected2)["new_completed_roles"], ["semantic-alignment"])
        third, expected3 = result_assessment_fixture([role["role_id"] for role in RESULT_ROLES], [role["role_id"] for role in RESULT_ROLES], goal_verdict="pass", status="done", baseline=["implementation", "test-runner", "semantic-alignment"])
        final = self.assess(third, expected3)
        self.assertEqual(final, {"decision": "done_candidate", "reason": None, "new_completed_roles": ["code-review", "evidence-rollup"]})

    def test_result_assessment_invalid_expected_raises_and_result_corruption_stops(self):
        result, expected = result_assessment_fixture(["implementation", "test-runner"], ["implementation", "test-runner"])
        for field, value in (("source_id", "foreign"), ("context_hash", "bad"), ("goal_required", False)):
            changed = copy.deepcopy(expected)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.assess(result, changed)
        fresh_with_baseline = copy.deepcopy(expected)
        fresh_with_baseline["completed_roles_before"] = ["implementation"]
        with self.assertRaises(ValueError):
            self.assess(result, fresh_with_baseline)
        for mutate in (
            lambda e: e["team_roles"].pop(),
            lambda e: e.update(goal_review_required=False),
            lambda e: e["missing_outputs"].update([("foreign", ["x"])]),
            lambda e: e["team_run"].update(template_id="foreign-template"),
            lambda e: e["team_run"].update(run_id="foreign-run"),
            lambda e: e["team_run"]["roles"][0].update(required_outputs=["weaker-output"]),
            lambda e: e["goal_acceptance"].update(contract_hash="c" * 64),
        ):
            changed = copy.deepcopy(result)
            mutate(changed["evidence"])
            self.assertEqual(self.assess(changed, expected), {"decision": "stop", "reason": "invalid_result", "new_completed_roles": []})

    def test_result_assessment_result_data_errors_and_zero_progress_are_stops(self):
        result, expected = result_assessment_fixture(["implementation", "test-runner"], ["implementation", "test-runner"])
        self.assertEqual(self.assess([], expected)["reason"], "invalid_result")
        cyclic = {"status": "ready", "returncode": 0, "summary": "x", "evidence": {}}
        cyclic["evidence"]["self"] = cyclic["evidence"]
        self.assertEqual(self.assess(cyclic, expected)["reason"], "invalid_result")
        no_progress, no_progress_expected = result_assessment_fixture([], [], status="ready")
        self.assertEqual(self.assess(no_progress, no_progress_expected)["reason"], "zero_progress")
        attempted_missing_gate, attempted_expected = result_assessment_fixture([], [], status="ready")
        attempted_missing_gate["evidence"]["attempted_roles"] = ["semantic-alignment"]
        self.assertEqual(self.assess(attempted_missing_gate, attempted_expected)["reason"], "invalid_result")
        uncertain = copy.deepcopy(result)
        uncertain["evidence"]["termination_proved"] = False
        self.assertEqual(self.assess(uncertain, expected)["reason"], "process_uncertain")
        inconsistent_done, done_expected = result_assessment_fixture(
            ["implementation", "test-runner"], ["implementation", "test-runner"], status="ready")
        inconsistent_done["status"] = "done"
        inconsistent_done["evidence"]["termination_proved"] = False
        self.assertEqual(self.assess(inconsistent_done, done_expected)["reason"], "invalid_result")
        failed, failed_expected = result_assessment_fixture([], [], status="blocked")
        failed["returncode"] = 3
        self.assertEqual(self.assess(failed, failed_expected)["reason"], "blocked")

    def test_result_assessment_malformed_continuation_and_executed_goal_failure(self):
        no_progress, expected = result_assessment_fixture([], [], status="ready")
        no_progress["evidence"]["workflow_continuation"]["extra"] = "bad"
        self.assertEqual(self.assess(no_progress, expected)["reason"], "invalid_result")
        failed_goal, failed_expected = result_assessment_fixture(
            ["implementation", "test-runner"],
            ["implementation", "test-runner", "semantic-alignment"],
            goal_verdict="fail",
        )
        evidence = failed_goal["evidence"]
        gate = evidence["team_run"]["roles"][3]
        gate["status"] = "blocked"
        gate["goal_review"] = {"verdict": "fail", "reason": "The plan is not met.", "evidence": ["synthetic failing review"]}
        evidence["goal_acceptance"].update(gate["goal_review"])
        evidence["team_run"]["missing_outputs"] = {
            role["role_id"]: list(role["required_outputs"])
            for role in RESULT_ROLES if role["role_id"] not in evidence["completed_roles"]
        }
        evidence["missing_outputs"] = copy.deepcopy(evidence["team_run"]["missing_outputs"])
        self.assertEqual(self.assess(failed_goal, failed_expected)["reason"], "goal_review_failed")

    def test_result_assessment_uses_full_accepted_goal_review_shape(self):
        passing, expected = result_assessment_fixture(
            ["implementation", "test-runner", "semantic-alignment"],
            ["implementation", "test-runner", "semantic-alignment"],
            goal_verdict="pass", status="queued", baseline=["implementation", "test-runner"],
        )
        passing["evidence"]["team_run"]["roles"][3]["goal_review"]["evidence"] = []
        passing["evidence"]["goal_acceptance"]["evidence"] = []
        self.assertEqual(self.assess(passing, expected)["reason"], "invalid_result")

    def test_result_assessment_malformed_continuation_and_executed_goal_failure(self):
        no_progress, expected = result_assessment_fixture([], [], status="ready")
        no_progress["evidence"]["workflow_continuation"]["extra"] = "bad"
        self.assertEqual(self.assess(no_progress, expected)["reason"], "invalid_result")
        failed_goal, failed_expected = result_assessment_fixture(
            ["implementation", "test-runner"],
            ["implementation", "test-runner", "semantic-alignment"],
            goal_verdict="fail",
        )
        evidence = failed_goal["evidence"]
        gate = evidence["team_run"]["roles"][3]
        gate["status"] = "blocked"
        gate["goal_review"] = {"verdict": "fail", "reason": "The plan is not met.", "evidence": ["synthetic failing review"]}
        evidence["goal_acceptance"].update(gate["goal_review"])
        evidence["team_run"]["missing_outputs"] = {
            role["role_id"]: list(role["required_outputs"])
            for role in RESULT_ROLES if role["role_id"] not in evidence["completed_roles"]
        }
        evidence["missing_outputs"] = copy.deepcopy(evidence["team_run"]["missing_outputs"])
        self.assertEqual(self.assess(failed_goal, failed_expected)["reason"], "goal_review_failed")

    def test_result_assessment_uses_full_accepted_goal_review_shape(self):
        passing, expected = result_assessment_fixture(
            ["implementation", "test-runner", "semantic-alignment"],
            ["implementation", "test-runner", "semantic-alignment"],
            goal_verdict="pass", status="queued", baseline=["implementation", "test-runner"],
        )
        passing["evidence"]["team_run"]["roles"][3]["goal_review"]["evidence"] = []
        passing["evidence"]["goal_acceptance"]["evidence"] = []
        self.assertEqual(self.assess(passing, expected)["reason"], "invalid_result")


def pins_fixture():
    return {
        "schema_version": 1,
        "kind": "atlas-local-supervisor-pins",
        "queue_path": "/work/queue.json",
        "runtime": {"checkout_path": "/work/runtime", "head": "a" * 40},
        "execution_checkouts": [{"checkout_path": "/work/repo", "head": "b" * 40, "entry_changes": []}],
        "inputs": [
            {"kind": "role_command_config", "path": "/work/config.json", "sha256": "1" * 64},
            {"kind": "team_template", "path": "/work/templates/a.json", "sha256": "2" * 64},
        ],
        "admitted_item_ids": ["item-a"],
        "item_closure": [
            {"item_id": "dep-b", "operation_id": "op-b", "execution_checkout": "/work/repo", "depends_on": [], "immutable_sha256": "3" * 64},
            {"item_id": "item-a", "operation_id": "op-a", "execution_checkout": "/work/repo", "depends_on": ["dep-b"], "immutable_sha256": "4" * 64},
        ],
        "template_source": {"mode": "directory", "path": "/work/templates", "candidates": ["/work/templates/a.json"]},
    }


class PinsDecodeTests(unittest.TestCase):
    decode = staticmethod(orchestrator._decode_cycle_pins)

    def encode(self, value):
        return json.dumps(value, separators=(",", ":")).encode("utf-8")

    def test_pins_decode_valid_complete_closure_returns_fresh_value(self):
        pins = pins_fixture()
        raw = self.encode(pins)
        decoded = self.decode(raw)
        self.assertEqual(decoded, pins)
        self.assertIsNot(decoded, pins)
        self.assertIsNot(decoded["item_closure"], pins["item_closure"])
        self.assertEqual(self.decode(raw), pins)

    def test_pins_decode_allows_shared_runtime_and_execution_checkout(self):
        pins = pins_fixture()
        pins["runtime"]["checkout_path"] = "/work/repo"
        self.assertEqual(self.decode(self.encode(pins)), pins)

    def test_pins_decode_strict_json_and_exact_shape(self):
        for raw in (b"[]", b"null", b"{} {}", b"\xff", b"{\"schema_version\":1,\"schema_version\":1}", b"{\"x\":NaN}", b"{\"x\":Infinity}"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.decode(raw)
        with self.assertRaises(ValueError): self.decode("{}")
        pins = pins_fixture()
        for bad in (
            {**pins, "unexpected": True},
            {key: value for key, value in pins.items() if key != "runtime"},
            {**pins, "schema_version": True},
            {**pins, "schema_version": 1.0},
            {**pins, "schema_version": 2},
            {**pins, "runtime": {**pins["runtime"], "extra": 1}},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.decode(self.encode(bad))

    def test_pins_decode_path_digest_order_and_template_mapping_refuse(self):
        base = pins_fixture()
        mutations = (
            lambda p: p.update(queue_path="/work/../queue.json"),
            lambda p: p["runtime"].update(head="A" * 40),
            lambda p: p["inputs"].__setitem__(0, {**p["inputs"][0], "path":"/work/has*glob"}),
            lambda p: p["inputs"].reverse(),
            lambda p: p["inputs"].__setitem__(1, {**p["inputs"][1], "sha256":p["inputs"][0]["sha256"]}),
            lambda p: p["template_source"].update(candidates=["/work/templates/z.json", "/work/templates/a.json"]),
            lambda p: p["template_source"].update(candidates=["/work/templates/other.json"]),
            lambda p: p["template_source"].update(mode="file", path="/work/templates/a.json", candidates=["/work/templates/other.json"]),
        )
        for mutate in mutations:
            bad = copy.deepcopy(base)
            mutate(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.decode(self.encode(bad))

    def test_pins_decode_rejects_dangling_cyclic_and_irrelevant_closure(self):
        for dependency_change in (
            ["missing"],
            ["item-a"],
            [],
        ):
            bad = pins_fixture()
            bad["item_closure"][1]["depends_on"] = dependency_change
            if dependency_change == []:
                bad["item_closure"][0]["item_id"] = "z-unreachable"
            with self.subTest(dependencies=dependency_change), self.assertRaises(ValueError): self.decode(self.encode(bad))
        cycle = pins_fixture()
        cycle["item_closure"][0]["depends_on"] = ["item-a"]
        cycle["item_closure"][1]["depends_on"] = ["dep-b"]
        with self.assertRaises(ValueError): self.decode(self.encode(cycle))

    def test_pins_decode_accepts_long_finite_dependency_chain_and_rejects_deep_cycle(self):
        pins = pins_fixture()
        count = 1300
        pins["item_closure"] = [
            {"item_id": f"item-{index:04d}", "operation_id": f"operation-{index:04d}",
             "execution_checkout": "/work/repo",
             "depends_on": [f"item-{index - 1:04d}"] if index else [],
             "immutable_sha256": hashlib.sha256(str(index).encode()).hexdigest()}
            for index in range(count)
        ]
        pins["admitted_item_ids"] = [f"item-{count - 1:04d}"]
        decoded = self.decode(self.encode(pins))
        self.assertEqual(len(decoded["item_closure"]), count)
        self.assertEqual(decoded["admitted_item_ids"], [f"item-{count - 1:04d}"])

        cyclic = copy.deepcopy(pins)
        cyclic["item_closure"][0]["depends_on"] = [f"item-{count - 1:04d}"]
        with self.assertRaises(ValueError):
            self.decode(self.encode(cyclic))

    def test_pins_decode_handles_shared_dense_dag_without_enumerating_paths(self):
        pins = pins_fixture()
        count = 36
        pins["item_closure"] = [
            {"item_id": f"node-{index:02d}", "operation_id": f"dense-op-{index:02d}",
             "execution_checkout": "/work/repo",
             "depends_on": [f"node-{prior:02d}" for prior in range(index)],
             "immutable_sha256": hashlib.sha256(f"dense-{index}".encode()).hexdigest()}
            for index in range(count)
        ]
        pins["admitted_item_ids"] = [f"node-{count - 1:02d}"]
        decoded = self.decode(self.encode(pins))
        self.assertEqual(len(decoded["item_closure"]), count)
        self.assertEqual(sum(len(node["depends_on"]) for node in decoded["item_closure"]), count * (count - 1) // 2)

    def test_pins_decode_entry_state_and_declared_file_consistency(self):
        pins = pins_fixture()
        entry = {"path": "src/main.py", "index_sha256": "5" * 64, "worktree_sha256": "6" * 64,
                 "index_state": "modified", "worktree_state": "modified"}
        pins["execution_checkouts"][0]["entry_changes"] = [entry]
        pins["inputs"].append({"kind": "entry_file", "path": "/work/repo/src/main.py", "sha256": "6" * 64})
        pins["inputs"].sort(key=lambda item: item["path"])
        self.assertEqual(self.decode(self.encode(pins)), pins)
        for mutation in (
            lambda p: p["execution_checkouts"][0]["entry_changes"][0].update(index_sha256=None),
            lambda p: p["execution_checkouts"][0]["entry_changes"][0].update(worktree_sha256=None),
            lambda p: next(item for item in p["inputs"] if item["kind"] == "entry_file").update(sha256="8" * 64),
            lambda p: p["inputs"].pop(0),
            lambda p: p["execution_checkouts"][0]["entry_changes"][0].update(index_state=[]),
        ):
            bad = copy.deepcopy(pins)
            mutation(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError): self.decode(self.encode(bad))


def receipt_event(seq=0, *, prior=None, elapsed=0.0, counters=None):
    queue_path = "/work/queue.json"
    return {
        "schema_version": 1, "kind": "atlas-local-supervisor-event", "queue_path": queue_path,
        "queue_key": hashlib.sha256(queue_path.encode()).hexdigest(), "cycle_id": "c" * 32,
        "seq": seq, "event": "opened", "elapsed_seconds": elapsed,
        "prior_event_acknowledged": prior, "initialization_ack": "acknowledged",
        "pins_sha256": "a" * 64, "admitted_fingerprints": {"item-1": "b" * 64},
        "limits": {"max_steps": 3, "max_claims": 2, "max_roles": 5, "role_max": 3,
                   "cycle_seconds": 30.0, "worker_timeout_seconds": 60.0,
                   "worker_termination_grace_seconds": 2.0, "stop_file": "/work/stop.flag"},
        "counters": counters or {"steps": 0, "claims_reserved": 0, "roles_reserved": 0, "observed_completed_roles": 0},
        "operation_id": None, "source_id": None, "claim_key": None, "invocation_id": None,
        "effects": {name: {"attempted": False, "ack": "not_attempted"} for name in ("claim", "launch", "result")},
        "result_sha256": None, "stored_result_sha256": None, "controller_reason": None,
        "terminal_outcome": None, "unresolved": False,
    }


class ReceiptDecodeTests(unittest.TestCase):
    decode = staticmethod(orchestrator._decode_cycle_receipt)

    def line(self, value):
        return json.dumps(value, separators=(",", ":"), allow_nan=True).encode("utf-8") + b"\n"

    def test_receipt_decode_preserves_ack_observations_and_returns_fresh_events(self):
        first = receipt_event()
        second = receipt_event(1, prior=0, elapsed=2.5, counters={"steps": 1, "claims_reserved": 1, "roles_reserved": 0, "observed_completed_roles": 0})
        second["effects"]["claim"] = {"attempted": False, "ack": "pending"}
        second["effects"]["result"] = {"attempted": True, "ack": "unknown"}
        raw = self.line(first) + self.line(second)
        first_before = copy.deepcopy(first)
        decoded = self.decode(raw)
        self.assertEqual(decoded, [first, second])
        self.assertIsNot(decoded[0], first)
        self.assertEqual(decoded[1]["effects"]["claim"]["ack"], "pending")
        self.assertEqual(decoded[1]["effects"]["result"]["ack"], "unknown")
        decoded[0]["counters"]["steps"] = 99
        self.assertEqual(first, first_before)

    def test_receipt_decode_requires_strict_newline_jsonl(self):
        valid = self.line(receipt_event())
        for raw in (b"", valid[:-1], valid.replace(b"\n", b"\r\n"), valid + b" \n", valid + b"\n", b"\xff\n", b"{\"x\":NaN}\n", b"{\"x\":Infinity}\n", b"{\"x\":1,\"x\":2}\n"):
            with self.subTest(raw=raw), self.assertRaises(ValueError): self.decode(raw)
        with self.assertRaises(ValueError): self.decode("{}\n")

    def test_receipt_decode_rejects_exact_shape_types_and_lexical_values(self):
        valid = receipt_event()
        bad_events = []
        for mutate in (
            lambda e: e.pop("unresolved"),
            lambda e: e.update(extra="no"),
            lambda e: e.update(schema_version=True),
            lambda e: e.update(schema_version=1.0),
            lambda e: e.update(schema_version=2),
            lambda e: e.update(seq=True),
            lambda e: e.update(event="mystery"),
            lambda e: e.update(queue_path="/work/../queue.json"),
            lambda e: e.update(queue_key="0" * 64),
            lambda e: e.update(cycle_id="C" * 32),
            lambda e: e.update(pins_sha256="z" * 64),
            lambda e: e.update(initialization_ack="pending"),
            lambda e: e.update(elapsed_seconds=float("inf")),
            lambda e: e.update(elapsed_seconds=True),
            lambda e: e.update(admitted_fingerprints={}),
            lambda e: e.update(admitted_fingerprints={"": "b" * 64}),
            lambda e: e["limits"].update(max_steps=True),
            lambda e: e["limits"].update(role_max=101),
            lambda e: e["limits"].update(cycle_seconds=float("nan")),
            lambda e: e["limits"].update(stop_file="relative/path"),
            lambda e: e["counters"].update(steps=True),
            lambda e: e["counters"].update(observed_completed_roles=1),
            lambda e: e["effects"]["claim"].update(ack="mystery"),
            lambda e: e["effects"]["claim"].update(ack="pending", attempted=True),
            lambda e: e.update(result_sha256="bad"),
            lambda e: e.update(controller_reason="unknown"),
            lambda e: e.update(terminal_outcome="unknown"),
            lambda e: e.update(unresolved=1),
        ):
            bad = copy.deepcopy(valid)
            mutate(bad)
            bad_events.append(bad)
        for bad in bad_events:
            with self.subTest(event=bad), self.assertRaises(ValueError): self.decode(self.line(bad))

    def test_receipt_decode_enforces_identity_sequence_and_monotone_bounds(self):
        first = receipt_event(elapsed=1.0, counters={"steps": 1, "claims_reserved": 0, "roles_reserved": 0, "observed_completed_roles": 0})
        second = receipt_event(1, prior=0, elapsed=2.0, counters={"steps": 2, "claims_reserved": 1, "roles_reserved": 2, "observed_completed_roles": 1})
        self.assertEqual(len(self.decode(self.line(first) + self.line(second))), 2)
        for mutate in (
            lambda events: events[0].update(seq=1),
            lambda events: events[1].update(seq=3),
            lambda events: events[1].update(prior_event_acknowledged=None),
            lambda events: events[1].update(queue_path="/work/other.json", queue_key=hashlib.sha256(b"/work/other.json").hexdigest()),
            lambda events: events[1].update(cycle_id="d" * 32),
            lambda events: events[1].update(pins_sha256="e" * 64),
            lambda events: events[1].update(admitted_fingerprints={"item-2": "f" * 64}),
            lambda events: events[1]["limits"].update(max_claims=4),
            lambda events: events[1].update(elapsed_seconds=0.5),
            lambda events: events[1]["counters"].update(steps=0),
            lambda events: events[1]["counters"].update(claims_reserved=3),
            lambda events: events[1]["counters"].update(observed_completed_roles=3),
        ):
            events = [copy.deepcopy(first), copy.deepcopy(second)]
            mutate(events)
            with self.subTest(events=events), self.assertRaises(ValueError): self.decode(self.line(events[0]) + self.line(events[1]))




def recovery_protocol_history(*, settle=False, no_launch=False, baseline=None, completed=None):
    """Pure receipt fixture: no files, providers, workers or role runners."""
    completed = completed if completed is not None else ["implementation"]
    complete = set(completed) == {role["role_id"] for role in RESULT_ROLES}
    result, expected = result_assessment_fixture(completed, completed, baseline=baseline,
        goal_verdict="pass" if complete else "missing", status="done" if complete else "ready")
    sid = expected["source_id"]
    operation = {"operation_id": expected["operation_id"], "source_type": "atlas_work_item", "source_id": sid,
        "title": "synthetic", "state": "ready", "ready": True, "blockers": [], "labels": [],
        "target_repo": "", "execution_repo": "/work/repo", "base_branch": "", "write_scope": ["file.txt"],
        "metadata": {}, "work_item_context": {}}
    immutable = orchestrator._cycle_guard_immutable(operation, [])
    static = {key: value for key, value in expected.items() if key not in {"run_id", "completed_roles_before"}}
    snapshot = {"input_digests": {"/work/template.json": "a" * 64}, "template_candidates": ["/work/template.json"],
        "runtime_head": "b" * 40, "execution_heads": {"/work/repo": "c" * 40}, "entry_changes": {"/work/repo": []},
        "immutable_inputs": {sid: immutable}, "expected_static": {sid: static}}
    state = {"source_snapshot": snapshot, "progress_by_item": {sid: {"run_id": expected["run_id"], "completed_roles": sorted(baseline or [])}},
        "done_ids": [], "cancellation": {"cancelled": False, "cancel_reason": None}, "jobs_identity": {"device": 1, "inode": 2},
        "disposition": {"action": "continue", "reason": None, "outcome": None}, "settlement": None}
    first = receipt_event()
    first.update(schema_version=2, controller_epoch="d" * 32,
        origin={"boot_id": "12345678-1234-1234-1234-123456789abc", "entry_monotonic": 100.0, "pins_path": "/work/pins.json"},
        recovery_state=None, revalidated_prefix_sha256=None, old_tail_acknowledgment=None,
        admitted_fingerprints={sid: orchestrator.atlas_work_items.content_hash(immutable)})
    first["limits"].update(max_roles=10, role_max=5)
    events = [first]
    recovery_protocol_append(events, "recovery_ready", recovery_state=state)
    if not settle:
        return events
    recovery_protocol_append(events, "step_reserved", counters=events[-1]["counters"] | {"steps": 1})
    recovery_protocol_append(events, "step_started")
    effects = orchestrator._CycleJournal._empty_effects()
    effects["claim"] = {"attempted": False, "ack": "pending"}
    recovery_protocol_append(events, "claim_intent", counters=events[-1]["counters"] | {"claims_reserved": 1},
                             operation_id=expected["operation_id"], source_id=sid, effects=effects)
    claim = {"claimed_by": "synthetic", "claimed_at": "2026-10-16T00:00:00Z", "pid": 123, "operation": operation}
    effects = copy.deepcopy(effects)
    effects["claim"] = {"attempted": True, "ack": "acknowledged"}
    recovery_protocol_append(events, "claimed", claim_key=orchestrator.atlas_work_items.content_hash(claim), effects=effects)
    if no_launch:
        result = {"status": "blocked", "returncode": 125, "summary": "Bounded supervisor did not launch this held claim.",
                  "evidence": {"supervisor_no_launch": True}}
        assessment = {"decision": "stop", "reason": None, "new_completed_roles": []}
    else:
        effects = copy.deepcopy(effects)
        effects["launch"] = {"attempted": False, "ack": "pending"}
        recovery_protocol_append(events, "launch_intent", counters=events[-1]["counters"] | {"roles_reserved": 5}, effects=effects)
        effects = copy.deepcopy(effects)
        effects["launch"] = {"attempted": True, "ack": "acknowledged"}
        recovery_protocol_append(events, "worker_returned", effects=effects, invocation_id="invoke-1",
                                 result_sha256=orchestrator.atlas_work_items.content_hash(result))
        assessment = orchestrator._bounded_result_assessment(result, expected)
    effects = copy.deepcopy(effects)
    effects["result"] = {"attempted": False, "ack": "pending"}
    recovery_protocol_append(events, "result_intent", effects=effects, result_sha256=orchestrator.atlas_work_items.content_hash(result))
    effects = copy.deepcopy(effects)
    effects["result"] = {"attempted": True, "ack": "acknowledged"}
    recovery_protocol_append(events, "result_acknowledged", effects=effects)
    state = copy.deepcopy(state)
    state["settlement"] = {"result": result, "claim": claim, "trusted_expectation": expected, "assessment": assessment}
    if no_launch:
        state["disposition"] = {"action": "halt", "reason": "blocked", "outcome": "blocked"}
    else:
        state["progress_by_item"][sid] = {"run_id": result["evidence"]["team_run"]["run_id"], "completed_roles": sorted(completed)}
        action = "done" if assessment["decision"] == "done_candidate" else "continue"
        state["disposition"] = {"action": action, "reason": None, "outcome": None}
        if action == "done":
            state["done_ids"] = [sid]
    recovery_protocol_append(events, "claim_settled", counters=events[-1]["counters"] | {"observed_completed_roles": len(assessment["new_completed_roles"])},
                             stored_result_sha256=events[-1]["result_sha256"], recovery_state=state)
    return events


def recovery_protocol_append(events, name, **patch):
    event = copy.deepcopy(events[-1])
    event.update(seq=len(events), prior_event_acknowledged=len(events) - 1, event=name,
                 elapsed_seconds=len(events) / 10, recovery_state=None,
                 revalidated_prefix_sha256=None, old_tail_acknowledgment=None)
    event.update(patch)
    events.append(event)
    return event


class RecoveryProtocolTests(unittest.TestCase):
    decode = staticmethod(orchestrator._decode_cycle_receipt_v2)

    def raw(self, events):
        return b"".join(orchestrator._CycleJournal._line(event) for event in events)

    def candidate(self, events, **kwargs):
        return orchestrator._validate_recovery_candidate(self.raw(events),
            boot_id=kwargs.get("boot_id", events[0]["origin"]["boot_id"]), monotonic=kwargs.get("monotonic", 102.0))

    def readmit(self, events, epoch="e" * 32):
        prefix = self.raw(events)
        return recovery_protocol_append(events, "recovery_admitted", controller_epoch=epoch,
            prior_event_acknowledged=None, old_tail_acknowledgment="unknown",
            revalidated_prefix_sha256=hashlib.sha256(prefix).hexdigest(), recovery_state=copy.deepcopy(events[-1]["recovery_state"]))

    def test_recovery_protocol_ready_settlement_and_readmission_are_only_candidates(self):
        for settle in (False, True):
            events = recovery_protocol_history(settle=settle)
            before = copy.deepcopy(events)
            decoded = self.decode(self.raw(events))
            self.assertEqual(decoded, events)
            candidate = self.candidate(events)
            self.assertEqual(candidate["status"], "continuation_candidate")
            self.assertEqual(candidate["old_tail_acknowledgment"], "unknown")
            self.assertEqual(candidate["prefix_sha256"], hashlib.sha256(self.raw(events)).hexdigest())
            self.assertEqual(events, before)
            candidate["recovery_state"]["done_ids"].append("mutated")
            self.assertEqual(events, before)
            self.readmit(events)
            self.assertEqual(self.candidate(events)["status"], "continuation_candidate")
            self.assertEqual(events[-1]["counters"], before[-1]["counters"])

    def test_recovery_protocol_does_not_charge_completed_baseline_roles(self):
        events = recovery_protocol_history(settle=True, baseline=["implementation"], completed=["implementation", "test-runner"])
        self.assertEqual(self.candidate(events)["counters"]["observed_completed_roles"], 1)
        self.assertEqual(events[-1]["recovery_state"]["progress_by_item"]["work/123"]["completed_roles"], ["implementation", "test-runner"])

    def test_recovery_protocol_done_and_halt_settlements(self):
        done = recovery_protocol_history(settle=True, completed=[role["role_id"] for role in RESULT_ROLES])
        self.assertEqual(self.candidate(done)["status"], "continuation_candidate")
        no_launch = recovery_protocol_history(settle=True, no_launch=True)
        self.assertEqual(self.candidate(no_launch)["status"], "report_only")
        self.assertEqual(self.candidate(no_launch)["counters"]["observed_completed_roles"], 0)
        with self.assertRaises(ValueError):
            self.readmit(no_launch)
            self.decode(self.raw(no_launch))

    def test_recovery_protocol_terminal_and_closed_are_report_only(self):
        for settle in (False, True):
            events = recovery_protocol_history(settle=settle)
            capsule = copy.deepcopy(events[-1]["recovery_state"])
            capsule["disposition"] = {"action": "halt", "reason": "budget_stop", "outcome": "budget_stop"}
            recovery_protocol_append(events, "terminal", controller_reason="budget_stop", terminal_outcome="budget_stop", recovery_state=capsule)
            self.assertEqual(self.candidate(events)["status"], "report_only")
            terminal = copy.deepcopy(events[-1])
            recovery_protocol_append(events, "closed", elapsed_seconds=terminal["elapsed_seconds"], recovery_state=capsule)
            self.assertEqual(self.candidate(events)["status"], "report_only")
            with self.assertRaises(ValueError):
                self.readmit(events)
                self.decode(self.raw(events))

    def test_recovery_protocol_closed_preserves_entire_terminal_capsule(self):
        complete = sorted(role["role_id"] for role in RESULT_ROLES)
        events = recovery_protocol_history(baseline=complete)
        capsule = copy.deepcopy(events[-1]["recovery_state"])
        capsule["disposition"] = {"action": "halt", "reason": "completed", "outcome": "completed"}
        capsule["done_ids"] = ["work/123"]
        terminal = recovery_protocol_append(events, "terminal", controller_reason="completed", terminal_outcome="completed", recovery_state=capsule)
        recovery_protocol_append(events, "closed", elapsed_seconds=terminal["elapsed_seconds"], recovery_state=copy.deepcopy(capsule))
        self.assertEqual(self.candidate(events)["status"], "report_only")
        for mutate in (lambda state: state["cancellation"].update(cancelled=True, cancel_reason="stop"),
                       lambda state: state["done_ids"].append("work/123")):
            changed = copy.deepcopy(events)
            mutate(changed[-1]["recovery_state"])
            with self.subTest(mutation=mutate), self.assertRaisesRegex(ValueError, "closed must preserve terminal recovery capsule"):
                self.candidate(changed)

    def test_recovery_protocol_every_exact_unsafe_or_unsupported_tail_refuses(self):
        events = recovery_protocol_history(settle=True)
        unsupported = {"opened", "step_reserved", "step_started"}
        unsafe = {"claim_intent", "claimed", "launch_intent", "worker_returned", "result_intent", "result_acknowledged"}
        for index, event in enumerate(events):
            if event["event"] not in unsupported | unsafe:
                continue
            with self.subTest(frontier=event["event"]):
                candidate = self.candidate(events[:index + 1])
                self.assertEqual(candidate["status"], "reconciliation_required")
                self.assertEqual(candidate["reason"], "unsupported_frontier" if event["event"] in unsupported else "unsafe_frontier")
                self.assertEqual(candidate["seq"], index)
                self.assertIsNone(candidate["recovery_state"])
        no_claim = recovery_protocol_history(settle=True)[:5]
        effect = copy.deepcopy(no_claim[-1]["effects"])
        effect["claim"] = {"attempted": True, "ack": "acknowledged"}
        recovery_protocol_append(no_claim, "claim_not_acquired", effects=effect)
        self.assertEqual(self.candidate(no_claim)["reason"], "unsupported_frontier")
        unresolved = recovery_protocol_history(settle=True)[:5]
        capsule = copy.deepcopy(unresolved[1]["recovery_state"])
        capsule["disposition"] = {"action": "halt", "reason": "claim_unknown", "outcome": "blocked"}
        effect = copy.deepcopy(unresolved[-1]["effects"])
        effect["claim"] = {"attempted": True, "ack": "unknown"}
        recovery_protocol_append(unresolved, "terminal", effects=effect, controller_reason="claim_unknown", terminal_outcome="blocked", unresolved=True, recovery_state=capsule)
        self.assertEqual(self.candidate(unresolved)["status"], "reconciliation_required")

    def test_recovery_protocol_entire_tail_is_required_without_fallback(self):
        events = recovery_protocol_history()
        valid = self.raw(events)
        for raw in (b"", valid[:-1], valid + b"{", valid + b"\n", valid + b" \n", valid + b"\xff\n", valid.replace(b"\n", b"\r\n"),
                    valid + b'{"unknown":true}\n', valid + self.raw([receipt_event()])):
            with self.subTest(raw=raw[-30:]), self.assertRaises(ValueError):
                self.decode(raw)
        newer = recovery_protocol_append(events, "step_reserved", counters=events[-1]["counters"] | {"steps": 1})
        self.assertEqual(self.candidate(events)["frontier"], newer["event"])
        self.assertEqual(self.candidate(events)["status"], "reconciliation_required")

    def test_recovery_protocol_strict_canonical_json_and_duplicate_nested_keys(self):
        valid = self.raw(recovery_protocol_history())
        for raw in (valid.replace(b'"schema_version":2', b'"schema_version":2,"schema_version":2', 1),
                    valid.replace(b'"device":1', b'"device":1,"device":1'),
                    valid.replace(b'"entry_monotonic":100.0', b'"entry_monotonic":NaN'),
                    valid.replace(b'"entry_monotonic":100.0', b'"entry_monotonic":Infinity'),
                    valid.replace(b'"entry_monotonic":100.0', b'"entry_monotonic":1e999'),
                    valid.replace(b'"seq":0', b'"seq": 0', 1), valid.replace(b'"seq":0', b'"seq":0.0', 1),
                    json.dumps(recovery_protocol_history()[0]).encode() + b"\n"):
            with self.subTest(raw=raw[:60]), self.assertRaises(ValueError): self.decode(raw)
        with self.assertRaises(ValueError): self.decode(valid.decode())

    def test_recovery_protocol_exact_domains_and_immutable_origin(self):
        mutations = [lambda e: e[0].update(extra=True), lambda e: e[0].pop("old_tail_acknowledgment"),
            lambda e: e[0].update(schema_version=True), lambda e: e[0].update(event="unknown"),
            lambda e: e[0].update(controller_epoch="D" * 32), lambda e: e[0]["origin"].update(boot_id="host"),
            lambda e: e[0]["origin"].update(entry_monotonic=True), lambda e: e[0]["origin"].update(extra=1),
            lambda e: e[0]["origin"].update(pins_path="/work/../pins.json"),
            lambda e: e[1]["origin"].update(pins_path="/work/equal-byte-copy.json"),
            lambda e: e[1]["origin"].update(entry_monotonic=99), lambda e: e[1]["origin"].update(boot_id="0" * 8 + "-1234-1234-1234-123456789abc"),
            lambda e: e[1].update(seq=3), lambda e: e[1].update(prior_event_acknowledged=True),
            lambda e: e[1]["limits"].update(max_steps=4), lambda e: e[1].update(pins_sha256="f" * 64),
            lambda e: e[1].update(queue_path="/work/other.json", queue_key=hashlib.sha256(b"/work/other.json").hexdigest()),
            lambda e: e[1]["counters"].update(steps=1), lambda e: e[1].update(revalidated_prefix_sha256="f" * 64)]
        for mutate in mutations:
            events = recovery_protocol_history()
            mutate(events)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError): self.decode(self.raw(events))

    def test_recovery_protocol_epoch_admission_requires_exact_raw_prefix_and_unknown_ack(self):
        mutations = [lambda e: e[-1].update(controller_epoch=e[0]["controller_epoch"]),
            lambda e: e[-1].update(prior_event_acknowledged=e[-2]["seq"]),
            lambda e: e[-1].update(old_tail_acknowledgment="acknowledged"),
            lambda e: e[-1].update(revalidated_prefix_sha256="0" * 64),
            lambda e: e[-1]["recovery_state"]["jobs_identity"].update(inode=3),
            lambda e: e[-1]["counters"].update(steps=1),
            lambda e: e[-1].update(elapsed_seconds=0), lambda e: e[-1].update(elapsed_seconds=30),
            lambda e: e[-1]["origin"].update(pins_path="/work/copy.json")]
        for mutate in mutations:
            events = recovery_protocol_history()
            self.readmit(events)
            mutate(events)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError): self.decode(self.raw(events))
        events = recovery_protocol_history()
        self.readmit(events)
        self.readmit(events, "f" * 32)
        self.assertEqual(self.candidate(events)["controller_epoch"], "f" * 32)
        self.readmit(events, "e" * 32)
        with self.assertRaises(ValueError): self.decode(self.raw(events))
        events = recovery_protocol_history()
        events[-1]["controller_epoch"] = "f" * 32
        with self.assertRaises(ValueError): self.decode(self.raw(events))

    def test_recovery_protocol_capsule_exact_shapes_types_and_domains(self):
        mutations = [lambda s: s.pop("settlement"), lambda s: s.update(extra=1), lambda s: s.update(jobs_identity=None),
            lambda s: s["jobs_identity"].update(inode=True), lambda s: s["jobs_identity"].update(extra=1),
            lambda s: s.update(done_ids=["work/123"]), lambda s: s["cancellation"].update(cancelled=1),
            lambda s: s["cancellation"].update(cancelled=True, cancel_reason="signal"),
            lambda s: s["progress_by_item"]["work/123"].update(completed_roles=["unknown"]),
            lambda s: s["progress_by_item"]["work/123"].update(completed_roles=["implementation", "implementation"]),
            lambda s: s["progress_by_item"]["work/123"].update(run_id=None, completed_roles=["implementation"]),
            lambda s: s["source_snapshot"].update(extra=1), lambda s: s["source_snapshot"].update(runtime_head="x" * 40),
            lambda s: s["source_snapshot"]["input_digests"].update({"relative": "a" * 64}),
            lambda s: s["source_snapshot"].update(template_candidates=["/work/missing.json"]),
            lambda s: s["source_snapshot"]["entry_changes"].update({"/work/other": []}),
            lambda s: s["source_snapshot"]["immutable_inputs"]["work/123"].update(title="changed"),
            lambda s: s["source_snapshot"]["expected_static"]["work/123"].update(extra=1),
            lambda s: s["disposition"].update(action="retry"), lambda s: s["disposition"].update(outcome="completed"),
            lambda s: s.update(settlement={})]
        for mutate in mutations:
            events = recovery_protocol_history()
            mutate(events[-1]["recovery_state"])
            with self.subTest(mutation=mutate), self.assertRaises(ValueError): self.decode(self.raw(events))

    def test_recovery_protocol_settlement_binds_assessment_digests_identity_and_progress(self):
        mutations = [lambda e, s: s["settlement"].update(extra=1), lambda e, s: s["settlement"]["assessment"].update(new_completed_roles=[]),
            lambda e, s: s["settlement"]["trusted_expectation"].update(run_id="repinned"),
            lambda e, s: s["settlement"]["claim"].update(pid=True),
            lambda e, s: s["settlement"]["claim"]["operation"].update(source_id="other"),
            lambda e, s: s["settlement"]["result"].update(summary="changed"),
            lambda e, s: s["progress_by_item"]["work/123"].update(run_id="different"),
            lambda e, s: s["progress_by_item"]["work/123"].update(completed_roles=[]),
            lambda e, s: e[-1].update(invocation_id="different"), lambda e, s: e[-1]["counters"].update(observed_completed_roles=0),
            lambda e, s: s["disposition"].update(action="done"), lambda e, s: s.update(done_ids=["work/123"])]
        for mutate in mutations:
            events = recovery_protocol_history(settle=True)
            mutate(events, events[-1]["recovery_state"])
            with self.subTest(mutation=mutate), self.assertRaises(ValueError): self.decode(self.raw(events))
        for flag in ("invocation_completed", "termination_proved"):
            events = recovery_protocol_history(settle=True)
            result = events[-1]["recovery_state"]["settlement"]["result"]
            result["evidence"][flag] = False
            digest = orchestrator.atlas_work_items.content_hash(result)
            for event in events:
                if event["result_sha256"] is not None: event["result_sha256"] = digest
                if event["stored_result_sha256"] is not None: event["stored_result_sha256"] = digest
            with self.assertRaises(ValueError): self.decode(self.raw(events))

    def test_recovery_protocol_multiple_settlements_preserve_full_progress_lineage(self):
        first = recovery_protocol_history(settle=True)
        second = recovery_protocol_history(settle=True, baseline=["implementation"], completed=["implementation", "test-runner"])
        events = copy.deepcopy(first)
        for row in second[2:]:
            patch = copy.deepcopy(row)
            for key in ("seq", "prior_event_acknowledged", "event", "elapsed_seconds"):
                patch.pop(key)
            patch["counters"] = {key: value + first[-1]["counters"][key] for key, value in row["counters"].items()}
            if row["event"] == "step_reserved":
                patch.update({key: copy.deepcopy(events[-1][key]) for key in (*orchestrator._CycleJournal._IDENTITY, "effects")})
            recovery_protocol_append(events, row["event"], **patch)
        self.assertEqual(self.candidate(events)["counters"]["observed_completed_roles"], 2)
        self.assertEqual(self.candidate(events)["counters"]["roles_reserved"], 10)
        before = copy.deepcopy(events)
        for mutate in (lambda state: state["source_snapshot"].update(runtime_head="e" * 40),
                       lambda state: state["jobs_identity"].update(inode=3),
                       lambda state: state["progress_by_item"]["work/123"].update(run_id="changed"),
                       lambda state: state["progress_by_item"]["work/123"].update(completed_roles=[])):
            bad = copy.deepcopy(before)
            mutate(bad[-1]["recovery_state"])
            with self.assertRaises(ValueError): self.decode(self.raw(bad))

    def test_recovery_protocol_fresh_epoch_continues_with_ordinary_acknowledgments(self):
        events = recovery_protocol_history(settle=True)
        self.readmit(events)
        recovery_protocol_append(events, "step_reserved", counters=events[-1]["counters"] | {"steps": 2})
        recovery_protocol_append(events, "step_started", **dict.fromkeys(orchestrator._CycleJournal._IDENTITY), effects=orchestrator._CycleJournal._empty_effects())
        self.assertEqual(self.decode(self.raw(events)), events)
        self.assertEqual(events[-1]["controller_epoch"], "e" * 32)
        self.assertEqual(events[-1]["prior_event_acknowledged"], events[-2]["seq"])
        self.assertIsNone(events[-1]["old_tail_acknowledgment"])
        self.assertIsNone(events[-1]["revalidated_prefix_sha256"])
        events[-1]["prior_event_acknowledged"] = None
        with self.assertRaises(ValueError): self.decode(self.raw(events))

    def test_recovery_protocol_counter_and_transition_integrity(self):
        for mutate in (lambda e: e[2]["counters"].update(steps=0),
                       lambda e: e[3]["counters"].update(steps=2),
                       lambda e: e[2].update(prior_event_acknowledged=True),
                       lambda e: e[4].update(source_id="not-admitted"),
                       lambda e: e[4].update(operation_id="not-admitted"),
                       lambda e: e[4]["counters"].update(claims_reserved=2),
                       lambda e: e[6]["counters"].update(roles_reserved=4),
                       lambda e: e[-1]["counters"].update(observed_completed_roles=6),
                       lambda e: e[3].update(event="claim_intent"),
                       lambda e: e[-1].update(recovery_state=None)):
            events = recovery_protocol_history(settle=True)
            mutate(events)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError): self.decode(self.raw(events))
        events = recovery_protocol_history(settle=True)
        last = copy.deepcopy(events[-1])
        reserved = recovery_protocol_append(events, "step_reserved", counters=last["counters"] | {"steps": 2})
        self.assertEqual(self.candidate(events)["status"], "reconciliation_required")
        self.assertEqual(reserved["invocation_id"], last["invocation_id"])
        recovery_protocol_append(events, "step_started", **dict.fromkeys(orchestrator._CycleJournal._IDENTITY), effects=orchestrator._CycleJournal._empty_effects())
        self.assertEqual(self.candidate(events)["counters"]["steps"], 2)

    def test_recovery_protocol_cancellation_cannot_be_cleared_or_reopened(self):
        events = recovery_protocol_history(settle=True)
        state = events[-1]["recovery_state"]
        state["cancellation"] = {"cancelled": True, "cancel_reason": "stop"}
        state["disposition"] = {"action": "halt", "reason": "stop", "outcome": "cancelled"}
        self.assertEqual(self.candidate(events)["reason"], "halt")
        recovery_protocol_append(events, "step_reserved", counters=events[-1]["counters"] | {"steps": 2})
        with self.assertRaises(ValueError): self.decode(self.raw(events))
        events.pop()
        state = copy.deepcopy(events[-1]["recovery_state"])
        state["cancellation"] = {"cancelled": False, "cancel_reason": None}
        recovery_protocol_append(events, "terminal", controller_reason="stop", terminal_outcome="cancelled", recovery_state=state)
        with self.assertRaises(ValueError): self.decode(self.raw(events))

    def test_recovery_protocol_deadline_charges_downtime_and_never_refunds(self):
        events = recovery_protocol_history(settle=True)
        original = self.candidate(events)
        later = self.candidate(events, monotonic=129.9)
        self.assertAlmostEqual(later["elapsed_seconds"], 29.9)
        self.assertEqual(later["counters"], original["counters"])
        for monotonic in (130, 140):
            candidate = self.candidate(events, monotonic=monotonic)
            self.assertEqual((candidate["status"], candidate["reason"]), ("report_only", "deadline"))
            self.assertEqual(candidate["limits"], original["limits"])

    def test_recovery_protocol_boot_backward_and_nonfinite_clocks_refuse(self):
        events = recovery_protocol_history(settle=True)
        for value in (True, -1, 99, 100.1, float("nan"), float("inf"), -float("inf"), "102", 10**10000):
            with self.subTest(value=str(value)[:30] if type(value) is not int else type(value)), self.assertRaises(ValueError):
                self.candidate(events, monotonic=value)
        with self.assertRaises(ValueError): self.candidate(events, boot_id="87654321-1234-1234-1234-123456789abc")
        origin = events[0]["origin"]
        self.assertEqual(orchestrator._same_boot_recovery_elapsed(origin, origin["boot_id"], 101, 1), 1)
        for bad in (True, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError): orchestrator._same_boot_recovery_elapsed(origin, origin["boot_id"], 102, bad)

    def test_recovery_protocol_v1_decoder_remains_strict_and_separate(self):
        with self.assertRaises(ValueError): orchestrator._decode_cycle_receipt(self.raw(recovery_protocol_history()))
        with self.assertRaises(ValueError): self.decode(self.raw([receipt_event()]))
        self.assertEqual(orchestrator._decode_cycle_receipt(self.raw([receipt_event()])), [receipt_event()])


class RecoveryJournalTests(unittest.TestCase):
    Journal = orchestrator._RecoverableCycleJournal

    def fixture(self, *, settle=False, existing=True, frontier=None):
        import tempfile
        temporary = tempfile.TemporaryDirectory(prefix="atlas-recovery-journal-")
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        queue = directory / "queue.json"
        queue.write_text('{"work_items":[]}')
        events = recovery_protocol_history(settle=settle)
        if frontier is not None:
            events = events[:next(i for i, row in enumerate(events) if row["event"] == frontier) + 1]
        for row in events:
            row.update(queue_path=str(queue), queue_key=hashlib.sha256(str(queue).encode()).hexdigest())
            row["origin"]["pins_path"] = str(directory / "pins.json")
        state = directory / ".atlas-supervisor" / events[0]["queue_key"]
        pins = pins_fixture()
        pins.update(queue_path=str(queue), admitted_item_ids=["work/123"], item_closure=[{
            "item_id": "work/123", "operation_id": "op-456", "execution_checkout": "/work/repo", "depends_on": [],
            "immutable_sha256": events[0]["admitted_fingerprints"]["work/123"]}])
        if existing:
            state.mkdir(parents=True)
            jobs = state / (events[0]["cycle_id"] + ".jobs")
            jobs.mkdir()
            identity = {"device": jobs.stat().st_dev, "inode": jobs.stat().st_ino}
            for row in events:
                if row["recovery_state"] is not None:
                    row["recovery_state"]["jobs_identity"] = copy.deepcopy(identity)
            (state / "controller.lock").touch()
            (state / (events[0]["cycle_id"] + ".jsonl")).write_bytes(self.raw(events))
        return directory, queue, state, events, pins

    def raw(self, events):
        return b"".join(orchestrator._CycleJournal._line(event) for event in events)

    def patch(self, event):
        return {key: copy.deepcopy(event[key]) for key in self.Journal._PATCH}

    def acquire(self, queue, events):
        owner = self.Journal.acquire_for_recovery(str(queue), events[0]["cycle_id"])
        self.addCleanup(owner.release)
        return owner

    def adopt(self, owner, pins, *, epoch="e" * 32, closures=None):
        snapshot = owner.snapshot()
        journal = self.Journal.from_recovery_candidate(owner, pins, snapshot["tail"]["pins_sha256"], snapshot["tail"]["limits"],
            controller_epoch=epoch, acknowledged_closures={} if closures is None else closures)
        self.addCleanup(journal.release)
        return journal

    def admission(self, journal):
        evidence = journal.recovery_evidence()
        patch = self.patch(evidence["tail"])
        patch.update(event="recovery_admitted", elapsed_seconds=2.0)
        return patch, evidence["prefix_sha256"]

    def fresh(self):
        directory, queue, state, events, pins = self.fixture(existing=False)
        first = events[0]
        journal = self.Journal(str(queue), pins, first["pins_sha256"], first["limits"], cycle_id=first["cycle_id"],
            acknowledged_closures={}, controller_epoch=first["controller_epoch"], origin=first["origin"])
        self.addCleanup(journal.release)
        journal.acquire_and_open(self.patch(first))
        ready = self.patch(events[1])
        ready["recovery_state"]["jobs_identity"] = None
        return directory, queue, state, events, pins, journal, ready

    def test_recovery_journal_fresh_root_ready_has_exact_synced_identity_and_reservation(self):
        import os
        from unittest.mock import patch
        _, _, state, events, _, journal, ready = self.fresh()
        jobs = state / (events[0]["cycle_id"] + ".jobs")
        self.assertFalse(jobs.exists())
        real_sync, seen = os.fsync, []
        def sync(fd):
            seen.append(os.readlink("/proc/self/fd/" + str(fd)))
            return real_sync(fd)
        with patch.object(os, "fsync", side_effect=sync): identity = journal.initialize_jobs_and_ready(ready)
        self.assertEqual(identity, (jobs.stat().st_dev, jobs.stat().st_ino))
        self.assertEqual(seen, [str(jobs), str(state), str(state / (events[0]["cycle_id"] + ".jsonl"))])
        self.assertIsNone(ready["recovery_state"]["jobs_identity"])
        saved = journal.recovery_evidence()
        self.assertIsNone(saved["local_recovery_ack"])
        reserved = self.patch(saved["tail"])
        reserved.update(event="step_reserved", recovery_state=None, counters=reserved["counters"] | {"steps": 1})
        journal.append(reserved)
        started = copy.deepcopy(reserved)
        started["event"] = "step_started"
        journal.append(started)
        decoded = orchestrator._decode_cycle_receipt_v2(journal._raw)
        self.assertEqual([row["event"] for row in decoded], ["opened", "recovery_ready", "step_reserved", "step_started"])
        self.assertEqual(decoded[-1]["counters"]["steps"], 1)

    def test_recovery_journal_existing_only_acquisition_and_copied_evidence(self):
        from unittest.mock import patch
        _, queue, _, events, _ = self.fixture(settle=True)
        real_open = orchestrator.os.open
        def opened(name, flags, *args, **kwargs):
            self.assertEqual(flags & (orchestrator.os.O_CREAT | orchestrator.os.O_TRUNC), 0)
            return real_open(name, flags, *args, **kwargs)
        with patch.object(orchestrator.os, "mkdir", side_effect=AssertionError("recovery creation")), patch.object(orchestrator.os, "open", side_effect=opened):
            owner = self.acquire(queue, events)
        snapshot = owner.snapshot()
        self.assertEqual(snapshot["raw"], self.raw(events))
        self.assertEqual(snapshot["tail"], events[-1])
        self.assertEqual(snapshot["old_tail_acknowledgment"], "unknown")
        self.assertEqual(len([value for value in snapshot["held_identities"] if value["name"].endswith(".jsonl")]), 1)
        snapshot["tail"]["origin"]["pins_path"] = "changed"
        snapshot["events"].clear()
        self.assertEqual(owner.snapshot()["tail"], events[-1])
        self.assertEqual(len(owner.snapshot()["events"]), len(events))

    def test_recovery_journal_same_fd_transfer_keeps_lock_and_requires_local_admission(self):
        import fcntl
        import os
        _, queue, state, events, pins = self.fixture(settle=True)
        owner = self.acquire(queue, events)
        receipt, lock, descriptors = owner._receipt, owner._lock, list(owner._fds)
        journal = self.adopt(owner, pins)
        self.assertEqual((journal._receipt, journal._lock, journal._fds), (receipt, lock, descriptors))
        self.assertTrue(owner._transferred)
        owner.release()
        self.assertEqual(os.fstat(receipt).st_ino, (state / (events[0]["cycle_id"] + ".jsonl")).stat().st_ino)
        contender = os.open(state / "controller.lock", os.O_RDWR)
        try:
            with self.assertRaises(BlockingIOError): fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally: os.close(contender)
        with self.assertRaises(ValueError): self.adopt(owner, pins)
        before = journal.recovery_evidence()
        self.assertIsNone(before["local_recovery_ack"])
        patch, prefix = self.admission(journal)
        journal.acknowledge_recovery(patch, expected_prefix_sha256=prefix)
        after = journal.recovery_evidence()
        self.assertIs(after["owner_token"], before["owner_token"])
        self.assertIs(after["local_recovery_ack"]["owner_token"], before["owner_token"])
        self.assertEqual(after["local_recovery_ack"]["revalidated_prefix_sha256"], prefix)
        self.assertEqual(after["local_recovery_ack"]["acknowledged_prefix_sha256"], after["prefix_sha256"])
        self.assertEqual(after["tail"]["controller_epoch"], "e" * 32)
        self.assertIsNone(after["tail"]["prior_event_acknowledged"])
        self.assertEqual(after["tail"]["old_tail_acknowledgment"], "unknown")
        after["local_recovery_ack"]["seq"] = -1
        self.assertGreater(journal.recovery_evidence()["local_recovery_ack"]["seq"], 0)
        reserved = self.patch(journal._events[-1])
        reserved.update(event="step_reserved", recovery_state=None, counters=reserved["counters"] | {"steps": 2})
        journal.append(reserved)
        self.assertEqual(journal._events[-1]["prior_event_acknowledged"], journal._events[-2]["seq"])
        self.assertIsNone(journal._events[-1]["old_tail_acknowledgment"])

    def test_recovery_journal_unadmitted_append_close_and_epoch_reuse_refuse_without_bytes(self):
        for action in ("append", "close", "epoch", "prefix"):
            with self.subTest(action=action):
                _, queue, state, events, pins = self.fixture()
                owner = self.acquire(queue, events)
                original = self.raw(events)
                if action == "epoch":
                    with self.assertRaises(ValueError): self.adopt(owner, pins, epoch=events[-1]["controller_epoch"])
                else:
                    journal = self.adopt(owner, pins)
                    patch, prefix = self.admission(journal)
                    with self.assertRaises(ValueError):
                        if action == "append": journal.append(patch | {"event": "step_reserved"})
                        elif action == "close": journal.close(patch | {"event": "terminal"})
                        else: journal.acknowledge_recovery(patch, expected_prefix_sha256="0" * 64)
                    self.assertTrue(journal._poisoned)
                    self.assertIsNone(journal._local_recovery_ack)
                self.assertEqual((state / (events[0]["cycle_id"] + ".jsonl")).read_bytes(), original)

    def test_recovery_journal_original_binding_and_move_failure_keep_candidate_owned(self):
        from unittest.mock import patch
        for kind in ("pins", "limits", "admission", "wrap"):
            with self.subTest(kind=kind):
                _, queue, _, events, pins = self.fixture()
                owner = self.acquire(queue, events)
                fd = owner._receipt
                if kind == "pins":
                    with self.assertRaises(ValueError): self.Journal.from_recovery_candidate(owner, pins, "f" * 64, events[0]["limits"], controller_epoch="e" * 32, acknowledged_closures={})
                elif kind == "limits":
                    with self.assertRaises(ValueError): self.Journal.from_recovery_candidate(owner, pins, events[0]["pins_sha256"], events[0]["limits"] | {"max_steps": 4}, controller_epoch="e" * 32, acknowledged_closures={})
                elif kind == "admission":
                    pins["item_closure"][0]["immutable_sha256"] = "f" * 64
                    with self.assertRaises(ValueError): self.adopt(owner, pins)
                else:
                    with patch.object(orchestrator.os, "fdopen", side_effect=OSError("synthetic wrap fault")):
                        with self.assertRaises(OSError): self.adopt(owner, pins)
                self.assertFalse(owner._transferred)
                self.assertEqual(orchestrator.os.fstat(fd).st_ino, owner._regular(fd).st_ino)
                owner.release()
                with self.assertRaises(OSError): orchestrator.os.fstat(fd)
                owner.release()

    def test_recovery_journal_unsafe_unsupported_and_report_only_candidates_never_admit(self):
        for frontier in ("step_reserved", "step_started", "claim_intent", "claimed", "launch_intent", "worker_returned", "result_intent", "result_acknowledged", "terminal", "closed", "halt"):
            with self.subTest(frontier=frontier):
                _, queue, state, events, pins = self.fixture(settle=True, frontier=frontier if frontier not in {"terminal", "closed", "halt"} else None)
                if frontier in {"terminal", "closed", "halt"}:
                    capsule = copy.deepcopy(events[-1]["recovery_state"])
                    capsule["disposition"] = {"action": "halt", "reason": "stop", "outcome": "cancelled"}
                    capsule["cancellation"] = {"cancelled": True, "cancel_reason": "stop"}
                    if frontier == "halt": events[-1]["recovery_state"] = capsule
                    else:
                        terminal = recovery_protocol_append(events, "terminal", controller_reason="stop", terminal_outcome="cancelled", recovery_state=capsule)
                        if frontier == "closed": recovery_protocol_append(events, "closed", elapsed_seconds=terminal["elapsed_seconds"], recovery_state=copy.deepcopy(capsule))
                    (state / (events[0]["cycle_id"] + ".jsonl")).write_bytes(self.raw(events))
                owner = self.acquire(queue, events)
                original = owner.snapshot()["raw"]
                self.assertEqual(owner.snapshot()["tail"]["event"], events[-1]["event"])
                journal = self.adopt(owner, pins)
                self.assertEqual(journal.recovery_evidence()["tail"], events[-1])
                self.assertIsNone(journal.recovery_evidence()["local_recovery_ack"])
                admission, prefix = self.admission(journal)
                with self.assertRaises(ValueError): journal.acknowledge_recovery(admission, expected_prefix_sha256=prefix)
                self.assertTrue(journal._poisoned)
                self.assertEqual(journal._closures, {})
                self.assertEqual((state / (events[0]["cycle_id"] + ".jsonl")).read_bytes(), original)

    def test_recovery_journal_missing_old_malformed_and_sibling_history_refuse(self):
        for kind in ("state", "lock", "receipt", "jobs", "v1", "torn", "unknown", "sibling", "jobs_identity"):
            with self.subTest(kind=kind):
                _, queue, state, events, _ = self.fixture(existing=kind != "state")
                receipt = state / (events[0]["cycle_id"] + ".jsonl")
                if kind in {"lock", "receipt"}: (state / ("controller.lock" if kind == "lock" else receipt.name)).unlink()
                elif kind == "jobs": (state / (events[0]["cycle_id"] + ".jobs")).rmdir()
                elif kind == "v1": receipt.write_bytes(self.raw([receipt_event()]))
                elif kind == "torn": receipt.write_bytes(receipt.read_bytes()[:-1])
                elif kind == "unknown": (state / "unknown").write_bytes(b"evidence")
                elif kind == "sibling": (state / ("f" * 32 + ".jsonl")).write_bytes(b"evidence")
                elif kind == "jobs_identity":
                    events[-1]["recovery_state"]["jobs_identity"]["inode"] += 1
                    receipt.write_bytes(self.raw(events))
                names = set(state.iterdir()) if state.exists() else set()
                raw = receipt.read_bytes() if receipt.exists() else None
                with self.assertRaises((ValueError, OSError)): self.Journal.acquire_for_recovery(str(queue), events[0]["cycle_id"])
                self.assertEqual(set(state.iterdir()) if state.exists() else set(), names)
                self.assertEqual(receipt.read_bytes() if receipt.exists() else None, raw)

    def test_recovery_journal_held_link_inode_and_prefix_changes_poison_without_retry(self):
        import os
        for kind in ("receipt", "lock", "jobs", "ancestor", "hardlink", "symlink", "append", "same_length"):
            with self.subTest(kind=kind):
                directory, queue, state, events, pins = self.fixture()
                owner = self.acquire(queue, events)
                journal = self.adopt(owner, pins)
                receipt = state / (events[0]["cycle_id"] + ".jsonl")
                if kind in {"append", "same_length"}:
                    original = receipt.read_bytes()
                    receipt.write_bytes(original + b"{\n" if kind == "append" else original.replace(b'"elapsed_seconds":0.0', b'"elapsed_seconds":0.1', 1))
                elif kind == "hardlink": os.link(receipt, directory / "hardlink")
                elif kind == "ancestor":
                    parent = state.parent
                    parent.rename(directory / "old-state")
                    parent.mkdir()
                else:
                    target = receipt if kind in {"receipt", "symlink"} else state / ("controller.lock" if kind == "lock" else events[0]["cycle_id"] + ".jobs")
                    backup = directory / "backup"
                    target.rename(backup)
                    if kind == "symlink": os.symlink(backup, target)
                    elif kind == "jobs": target.mkdir()
                    else: target.write_bytes(backup.read_bytes())
                with self.assertRaises((ValueError, OSError)): journal.recovery_evidence()
                self.assertTrue(journal._poisoned)
                with self.assertRaises(ValueError): journal.recovery_evidence()

    def test_recovery_journal_queue_replacement_is_allowed_but_links_refuse(self):
        import os
        for kind in ("replace", "hardlink", "symlink"):
            with self.subTest(kind=kind):
                directory, queue, _, events, pins = self.fixture()
                owner = self.acquire(queue, events)
                journal = self.adopt(owner, pins)
                replacement = directory / "replacement"
                replacement.write_text('{"work_items":[]}')
                if kind == "replace": replacement.replace(queue)
                elif kind == "hardlink": os.link(queue, directory / "hardlink")
                else:
                    queue.unlink()
                    os.symlink(replacement, queue)
                if kind == "replace": self.assertIsNone(journal.recovery_evidence()["local_recovery_ack"])
                else:
                    with self.assertRaises((ValueError, OSError)): journal.recovery_evidence()
                    self.assertTrue(journal._poisoned)

    def test_recovery_journal_active_or_uncertain_queue_remains_inspectable_but_never_admits(self):
        for row in ({"id": "work/123", "status": "running", "claim": {"pid": 123}},
                    {"id": "work/123", "status": "blocked", "process_uncertainty": {"status": "unresolved"}}):
            with self.subTest(row=row):
                _, queue, state, events, pins = self.fixture()
                queue.write_text(json.dumps({"work_items": [row]}))
                queue_raw = queue.read_bytes()
                owner = self.acquire(queue, events)
                self.assertEqual(owner.snapshot()["raw"], self.raw(events))
                journal = self.adopt(owner, pins)
                self.assertIsNone(journal.recovery_evidence()["local_recovery_ack"])
                admission, prefix = self.admission(journal)
                with self.assertRaisesRegex(ValueError, "active claim or process uncertainty"):
                    journal.acknowledge_recovery(admission, expected_prefix_sha256=prefix)
                self.assertTrue(journal._poisoned)
                self.assertIsNone(journal._local_recovery_ack)
                self.assertEqual(journal._closures, {})
                self.assertEqual((state / (events[0]["cycle_id"] + ".jsonl")).read_bytes(), self.raw(events))
                self.assertEqual(queue.read_bytes(), queue_raw)

    def test_recovery_journal_root_creation_and_each_ready_sync_fault_preserve_evidence(self):
        import os
        from unittest.mock import patch
        for kind in ("mkdir", "open", "sync_child", "sync_parent", "sync_receipt"):
            with self.subTest(kind=kind):
                _, _, state, events, _, journal, ready = self.fresh()
                name = events[0]["cycle_id"] + ".jobs"
                original = journal._raw
                calls = []
                real_open, real_mkdir, real_sync = os.open, os.mkdir, os.fsync
                def opened(target, *args, **kwargs):
                    if kind == "open" and target == name: raise OSError("synthetic root open fault")
                    return real_open(target, *args, **kwargs)
                def made(target, *args, **kwargs):
                    if kind == "mkdir" and target == name: raise OSError("synthetic root create fault")
                    return real_mkdir(target, *args, **kwargs)
                def synced(fd):
                    calls.append(fd)
                    ordinal = {"sync_child": 1, "sync_parent": 2, "sync_receipt": 3}.get(kind)
                    if len(calls) == ordinal: raise OSError("synthetic root sync fault")
                    return real_sync(fd)
                with patch.object(os, "open", side_effect=opened), patch.object(os, "mkdir", side_effect=made), patch.object(os, "fsync", side_effect=synced):
                    with self.assertRaises(OSError): journal.initialize_jobs_and_ready(ready)
                self.assertTrue(journal._poisoned)
                self.assertEqual(journal._raw, original)
                self.assertEqual(journal._events[-1]["event"], "opened")
                self.assertEqual((state / name).exists(), kind != "mkdir")
                with self.assertRaises(ValueError): journal.initialize_jobs_and_ready(ready)
                journal.release()
                if kind == "sync_receipt":
                    inspection = self.acquire(Path(events[0]["queue_path"]), events)
                    self.assertEqual(inspection.snapshot()["tail"]["event"], "recovery_ready")
                    inspection.release()
                else:
                    with self.assertRaises(ValueError): self.acquire(Path(events[0]["queue_path"]), events)

    def test_recovery_journal_write_flush_short_write_and_sync_faults_never_ack_or_retry(self):
        from unittest.mock import patch
        for stage in ("ready", "admission", "reserved"):
            for fault in ("write", "short", "flush", "sync"):
                with self.subTest(stage=stage, fault=fault):
                    if stage == "ready":
                        _, _, state, events, _, journal, ready = self.fresh()
                        action = lambda: journal.initialize_jobs_and_ready(ready)
                    else:
                        _, queue, state, events, pins = self.fixture()
                        journal = self.adopt(self.acquire(queue, events), pins)
                        admission, prefix = self.admission(journal)
                        if stage == "admission": action = lambda: journal.acknowledge_recovery(admission, expected_prefix_sha256=prefix)
                        else:
                            journal.acknowledge_recovery(admission, expected_prefix_sha256=prefix)
                            reserved = self.patch(journal._events[-1])
                            reserved.update(event="step_reserved", recovery_state=None, counters=reserved["counters"] | {"steps": 1})
                            action = lambda: journal.append(reserved)
                    raw, sequence = journal._raw, len(journal._events)
                    stream = journal._stream
                    class StreamFault:
                        def fileno(self): return stream.fileno()
                        def close(self): return stream.close()
                        def write(self, value):
                            if fault == "write": raise OSError("synthetic write fault")
                            return stream.write(value[:len(value)//2] if fault == "short" else value)
                        def flush(self):
                            if fault == "flush": raise OSError("synthetic flush fault")
                            return stream.flush()
                    journal._stream = StreamFault()
                    real_sync = orchestrator.os.fsync
                    def sync(fd):
                        if fault == "sync" and fd == stream.fileno(): raise OSError("synthetic receipt sync fault")
                        return real_sync(fd)
                    with patch.object(orchestrator.os, "fsync", side_effect=sync):
                        with self.assertRaises(OSError): action()
                    self.assertTrue(journal._poisoned)
                    self.assertEqual(journal._raw, raw)
                    self.assertEqual(len(journal._events), sequence)
                    landed = (state / (events[0]["cycle_id"] + ".jsonl")).read_bytes()
                    self.assertTrue(landed.startswith(raw))
                    with self.assertRaises(ValueError): action()
                    self.assertEqual((state / (events[0]["cycle_id"] + ".jsonl")).read_bytes(), landed)
                    if stage == "admission": self.assertIsNone(journal._local_recovery_ack)

    def test_recovery_journal_lost_admission_ack_is_unknown_and_next_process_epoch_is_fresh(self):
        from unittest.mock import patch
        _, queue, _, events, pins = self.fixture()
        journal = self.adopt(self.acquire(queue, events), pins)
        admission, prefix = self.admission(journal)
        with patch.object(orchestrator.os, "fsync", side_effect=OSError("lost admission acknowledgment")):
            with self.assertRaises(OSError): journal.acknowledge_recovery(admission, expected_prefix_sha256=prefix)
        self.assertIsNone(journal._local_recovery_ack)
        self.assertEqual(journal._events[-1]["event"], "recovery_ready")
        journal.release()
        next_owner = self.acquire(queue, events)
        self.assertEqual(next_owner.snapshot()["tail"]["event"], "recovery_admitted")
        next_journal = self.adopt(next_owner, pins, epoch="f" * 32)
        self.assertIsNone(next_journal.recovery_evidence()["local_recovery_ack"])
        admission, prefix = self.admission(next_journal)
        next_journal.acknowledge_recovery(admission, expected_prefix_sha256=prefix)
        self.assertEqual(next_journal._events[-1]["old_tail_acknowledgment"], "unknown")
        self.assertEqual(next_journal._closures, {})

    def test_recovery_journal_release_attempts_all_closes_once_after_a_close_error(self):
        import os
        from unittest.mock import patch
        _, queue, _, events, pins = self.fixture()
        owner = self.acquire(queue, events)
        journal = self.adopt(owner, pins)
        descriptors = [journal._lock, *reversed(journal._fds)]
        real_close, closed = os.close, []
        def close(fd):
            closed.append(fd)
            real_close(fd)
            if len(closed) == 1: raise OSError("synthetic close acknowledgment fault")
        with patch.object(os, "close", side_effect=close):
            with self.assertRaises(OSError): journal.release()
            owner.release()
            journal.release()
        self.assertEqual(closed, descriptors)
        self.assertEqual(len(closed), len(set(closed)))
        self.assertTrue(journal._poisoned)
        for fd in descriptors:
            with self.assertRaises(OSError): os.fstat(fd)

    def test_recovery_journal_contender_process_and_inherited_owner_cannot_admit(self):
        import subprocess
        from unittest.mock import patch
        _, queue, _, events, pins = self.fixture()
        owner = self.acquire(queue, events)
        with patch.object(orchestrator.os, "getpid", return_value=owner._pid + 1):
            with self.assertRaises(ValueError): self.adopt(owner, pins)
        script = """import importlib.machinery,importlib.util,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).parent))
loader=importlib.machinery.SourceFileLoader('recovery_contender',sys.argv[1]);spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)
try:m._RecoverableCycleJournal.acquire_for_recovery(sys.argv[2],sys.argv[3])
except BlockingIOError:print('contended');sys.exit(0)
sys.exit(3)
"""
        child = subprocess.run([sys.executable, "-B", "-c", script, str(ROOT / "atlas-agent-orchestrator"), str(queue), events[0]["cycle_id"]],
                               capture_output=True, text=True, timeout=5)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), "contended")
        owner.release()
        next_owner = self.acquire(queue, events)
        next_owner.release()



    def test_recovery_journal_every_acquisition_open_lock_and_read_fault_closes_owned_fds(self):
        import collections
        import fcntl
        import os
        from unittest.mock import patch
        _, queue, _, events, _ = self.fixture()
        real_open, real_close = os.open, os.close
        successful_opens = []
        def observed(name, *args, **kwargs):
            successful_opens.append(name)
            return real_open(name, *args, **kwargs)
        with patch.object(os, "open", side_effect=observed): owner = self.acquire(queue, events)
        owner.release()
        faults = list(range(1, len(successful_opens) + 1)) + ["lock", "read"]
        for fault in faults:
            with self.subTest(fault=fault):
                _, queue, state, events, _ = self.fixture()
                receipt = state / (events[0]["cycle_id"] + ".jsonl")
                raw, opened, closed, calls = receipt.read_bytes(), [], [], []
                def opening(name, *args, **kwargs):
                    calls.append(name)
                    if fault == len(calls): raise OSError("synthetic acquisition open fault")
                    fd = real_open(name, *args, **kwargs)
                    opened.append(fd)
                    return fd
                def closing(fd):
                    closed.append(fd)
                    return real_close(fd)
                real_lock, real_read = fcntl.flock, os.pread
                def locking(*args):
                    if fault == "lock": raise OSError("synthetic acquisition lock fault")
                    return real_lock(*args)
                def reading(*args):
                    if fault == "read": raise OSError("synthetic acquisition read fault")
                    return real_read(*args)
                with patch.object(os, "open", side_effect=opening), patch.object(os, "close", side_effect=closing), patch.object(fcntl, "flock", side_effect=locking), patch.object(os, "pread", side_effect=reading):
                    with self.assertRaises(OSError): self.Journal.acquire_for_recovery(str(queue), events[0]["cycle_id"])
                self.assertEqual(collections.Counter(opened), collections.Counter(closed))
                self.assertEqual(receipt.read_bytes(), raw)

    def test_recovery_journal_each_new_opened_sync_failure_poisons_before_jobs_creation(self):
        from unittest.mock import patch
        real_sync = orchestrator.os.fsync
        for ordinal in range(1, 9):
            with self.subTest(ordinal=ordinal):
                _, queue, state, events, pins = self.fixture(existing=False)
                first = events[0]
                journal = self.Journal(str(queue), pins, first["pins_sha256"], first["limits"], cycle_id=first["cycle_id"],
                    acknowledged_closures={}, controller_epoch=first["controller_epoch"], origin=first["origin"])
                self.addCleanup(journal.release)
                calls = []
                def sync(fd):
                    calls.append(fd)
                    if len(calls) == ordinal: raise OSError("synthetic v2 opened sync fault")
                    return real_sync(fd)
                with patch.object(orchestrator.os, "fsync", side_effect=sync):
                    with self.assertRaises(OSError): journal.acquire_and_open(self.patch(first))
                self.assertEqual(len(calls), ordinal)
                self.assertTrue(journal._poisoned)
                self.assertEqual(journal._events, [])
                self.assertFalse((state / (first["cycle_id"] + ".jobs")).exists())
                with self.assertRaises(ValueError): journal.acquire_and_open(self.patch(first))
                journal.release()

    def test_recovery_journal_only_own_successful_close_issues_a_new_witness(self):
        _, queue, state, events, pins = self.fixture()
        closures = {}
        journal = self.adopt(self.acquire(queue, events), pins, closures=closures)
        admission, prefix = self.admission(journal)
        journal.acknowledge_recovery(admission, expected_prefix_sha256=prefix)
        terminal = self.patch(journal._events[-1])
        terminal.update(event="terminal", controller_reason="budget_stop", terminal_outcome="budget_stop")
        terminal["recovery_state"]["disposition"] = {"action": "halt", "reason": "budget_stop", "outcome": "budget_stop"}
        witness = journal.close(terminal)
        self.assertEqual(witness, (events[0]["queue_key"], events[0]["cycle_id"], hashlib.sha256(journal._line(journal._events[-1])).hexdigest()))
        self.assertEqual(closures, {witness[:2]: witness[2]})
        self.assertEqual(journal._events[-1]["recovery_state"], journal._events[-2]["recovery_state"])
        journal.release()
        receipt = state / (events[0]["cycle_id"] + ".jsonl")
        raw = receipt.read_bytes()
        observation = self.acquire(queue, events)
        self.assertEqual(observation.snapshot()["tail"]["event"], "closed")
        report = self.adopt(observation, pins, epoch="f" * 32, closures={})
        self.assertIsNone(report.recovery_evidence()["local_recovery_ack"])
        self.assertEqual(report.recovery_evidence()["tail"]["event"], "closed")
        self.assertEqual(report._closures, {})
        observation.release()
        report.release()
        self.assertEqual(receipt.read_bytes(), raw)

    def test_recovery_journal_lifecycle_fields_root_exclusivity_and_repeat_admission_refuse(self):
        from unittest.mock import patch
        _, queue, state, events, _, journal, ready = self.fresh()
        jobs = state / (events[0]["cycle_id"] + ".jobs")
        jobs.mkdir()
        with self.assertRaises((ValueError, FileExistsError)): journal.initialize_jobs_and_ready(ready)
        self.assertTrue(journal._poisoned)
        self.assertEqual(journal._events[-1]["event"], "opened")
        for name in ("recovery_ready", "recovery_admitted", "closed", "opened"):
            _, _, _, _, _, fresh, patch_value = self.fresh()
            patch_value["event"] = name
            with self.assertRaises(ValueError): fresh.append(patch_value)
            self.assertTrue(fresh._poisoned)
        _, queue, state, events, pins = self.fixture()
        owner = self.acquire(queue, events)
        journal = self.adopt(owner, pins)
        admission, prefix = self.admission(journal)
        journal.acknowledge_recovery(admission, expected_prefix_sha256=prefix)
        raw = journal._raw
        with self.assertRaises(ValueError): journal.acknowledge_recovery(admission, expected_prefix_sha256=prefix)
        self.assertTrue(journal._poisoned)
        self.assertEqual(journal._raw, raw)
        self.assertEqual((state / (events[0]["cycle_id"] + ".jsonl")).read_bytes(), raw)
        _, queue, _, events, pins = self.fixture(existing=False)
        with patch.object(orchestrator.os, "open", side_effect=AssertionError("constructor I/O")):
            pure = self.Journal(str(queue), pins, events[0]["pins_sha256"], events[0]["limits"], cycle_id=events[0]["cycle_id"],
                acknowledged_closures={}, controller_epoch="e" * 32, origin=events[0]["origin"])
            pure.release()



class CycleAdapterHarness:
    """In-memory public-seam doubles; never runs a command or opens a queue."""
    def __init__(self, *, ids=None, role_max=1, max_roles=8, max_claims=10, max_steps=20):
        self.ids = ids or ["work/123"]
        self.rows = {sid: {"id": sid, "operation_id": "op-" + sid.split("/")[-1], "status": "ready"} for sid in self.ids}
        self.dependencies = {}
        self.trace, self.events, self.frames, self.results, self.allowances = [], [], [], [], []
        self.guard_operations = []
        self.hooks = {}
        self.now, self.cancelled = 100.0, False
        self.claim_count = self.worker_count = self.record_count = self.load_count = self.ready_count = self.release_count = self.close_count = 0
        self.claim_none = False
        self.fail_event = None
        self.fail_after_event = False
        self.worker_transform = None
        self.guard_transform = None
        self.inputs = {"queue_path": "/synthetic/queue.json", "pins_path": "/synthetic/pins.json",
                       "pins_raw_sha256": "a" * 64, "cycle_id": "b" * 32, "entry_monotonic": 100.0,
                       "limits": {"max_steps": max_steps, "max_claims": max_claims, "max_roles": max_roles,
                                  "role_max": role_max, "cycle_seconds": 30.0, "worker_timeout_seconds": 5.0,
                                  "worker_termination_grace_seconds": 0.0, "stop_file": "/synthetic/stop"},
                       "admitted_item_ids": sorted(self.ids), "progress_by_item": {}}
        self.provider = self.Provider(self)
        self.journal = self.Journal(self)
        self.cancellation = self.Cancellation(self)

    def hit(self, label):
        self.trace.append(label)
        callback = self.hooks.get(label)
        if callback:
            callback(self)

    def clock(self):
        return self.now

    def expectation(self, sid):
        _, expected = result_assessment_fixture([], [])
        expected.update(source_id=sid, work_item_id=sid, operation_id=self.rows[sid]["operation_id"])
        progress = self.inputs["progress_by_item"][sid]
        expected.update(run_id=progress["run_id"], completed_roles_before=copy.deepcopy(progress["completed_roles"]))
        return expected

    def guard(self, checkpoint, operation):
        self.hit("guard:" + checkpoint)
        if checkpoint == "entry":
            self.assert_empty = self.inputs["progress_by_item"] == {}
            self.inputs["progress_by_item"].update({sid: {"run_id": None, "completed_roles": []} for sid in self.ids})
        assert operation is None or type(operation) is dict
        self.guard_operations.append((checkpoint, copy.deepcopy(operation)))
        frame = {"changed": False, "reason": None, "head_changed": False,
                 "trusted_expectation": None if operation is None else self.expectation(operation["source_id"])}
        if self.guard_transform:
            frame = self.guard_transform(self, checkpoint, frame)
        self.frames.append((checkpoint, copy.deepcopy(frame)))
        return frame

    def worker_factory(self, allowance):
        self.hit("factory")
        self.allowances.append(allowance)
        return self.Worker(self, allowance)

    def run(self):
        return orchestrator._run_bounded_cycle(self.inputs, provider=self.provider,
            worker_factory=self.worker_factory, monotonic=self.clock,
            cancellation=self.cancellation, journal=self.journal, guard=self.guard)

    class Cancellation:
        def __init__(self, h): self.h = h
        def is_set(self):
            self.h.hit("cancel")
            return self.h.cancelled

    class Store:
        path = Path("/synthetic/queue.json")
        def __init__(self, h): self.h = h
        def load(self):
            self.h.load_count += 1
            self.h.hit("load")
            return {"work_items": copy.deepcopy(list(self.h.rows.values()))}

    class Provider:
        claimed_by = "synthetic-controller"
        def __init__(self, h):
            self.h, self.store = h, CycleAdapterHarness.Store(h)
        def project(self, item, by_id):
            sid = item["id"]
            ready = item["status"] in {"ready", "queued"} and all(
                by_id[dep]["status"] == "done" for dep in self.h.dependencies.get(sid, []))
            return orchestrator.atlas_work_items.OperationState(
                operation_id=item["operation_id"], source_type="atlas_work_item", source_id=sid,
                title="Synthetic " + sid, state=item["status"], ready=ready,
                metadata={"workflow_kind": "work-item", "team_template": "work-item-change-lifecycle"})
        def ready_operations(self):
            self.h.ready_count += 1
            self.h.hit("ready")
            return [op for row in self.h.rows.values() if (op := self.project(row, self.h.rows)).ready]
        def claim(self, operation):
            self.h.claim_count += 1
            self.h.hit("claim")
            if self.h.claim_none:
                return None
            row = self.h.rows[operation.source_id]
            row["claim"] = {"operation": copy.deepcopy(operation.to_dict()), "claimed_by": self.claimed_by,
                            "claimed_at": "synthetic-" + str(self.h.claim_count), "pid": 0}
            row["status"] = "running"
            self.h.hit("claim_applied")
            return self.project(row, self.h.rows)
        def record_result(self, operation, result):
            self.h.record_count += 1
            self.h.hit("record")
            row = self.h.rows[operation.source_id]
            row["result"] = copy.deepcopy(result.to_dict())
            row["status"] = result.status
            if result.status in {"ready", "queued"}:
                row.setdefault("previous_claims", []).append(row.pop("claim"))
            if ("process_uncertainty" in row and type(result.evidence) is dict
                and result.evidence.get("process_invocation_id") == row["process_uncertainty"]["invocation_id"]
                and result.evidence.get("invocation_completed") is True and result.evidence.get("termination_proved") is True):
                row["process_uncertainty"]["status"] = "resolved"
            self.h.hit("record_applied")

    class Worker:
        def __init__(self, h, allowance): self.h, self.allowance = h, allowance
        def run(self, operation, path, *, cancel_event):
            h = self.h
            h.worker_count += 1
            h.hit("worker")
            h.held_operation = operation
            assert path == h.provider.store.path
            assert cancel_event.is_set() is False
            sid = operation.source_id
            baseline = h.inputs["progress_by_item"][sid]["completed_roles"]
            previous = set(baseline)
            new = [r["role_id"] for r in RESULT_ROLES if r["role_id"] not in previous][:self.allowance]
            completed = [r["role_id"] for r in RESULT_ROLES if r["role_id"] in previous or r["role_id"] in new]
            raw, _ = result_assessment_fixture(completed, completed,
                goal_verdict="pass" if "semantic-alignment" in completed else "missing",
                status="done" if len(completed) == len(RESULT_ROLES) else "ready", baseline=baseline)
            run_id = h.inputs["progress_by_item"][sid]["run_id"] or orchestrator.atlas_work_items.safe_id(sid) + "-invoke-1"
            raw["evidence"]["team_run"].update(run_id=run_id, work_item_id=sid)
            raw["evidence"]["process_invocation_id"] = "invoke-1" if not baseline else "invoke-" + str(h.worker_count)
            h.rows[sid]["process_uncertainty"] = {"status": "unresolved", "invocation_id": raw["evidence"]["process_invocation_id"]}
            if h.worker_transform:
                raw = h.worker_transform(h, raw, cancel_event)
            h.hit("worker_return")
            result = orchestrator.atlas_work_items.OperationResult(**raw)
            h.results.append((result, copy.deepcopy(result.to_dict())))
            return result

    class Journal:
        PATCH = {"event", "elapsed_seconds", "counters", "operation_id", "source_id", "claim_key", "invocation_id",
                 "effects", "result_sha256", "stored_result_sha256", "controller_reason", "terminal_outcome", "unresolved"}
        def __init__(self, h): self.h, self.poisoned, self.lines = h, False, []
        def acquire_and_open(self, patch):
            self.h.hit("open")
            self.append(patch)
        def append(self, patch):
            h = self.h
            assert not self.poisoned
            assert set(patch) == self.PATCH
            if patch["event"] == "terminal" and h.events and h.events[-1]["event"] in {"claim_settled", "claim_not_acquired"}:
                previous = h.events[-1]
                for key in ("operation_id", "source_id", "claim_key", "invocation_id", "result_sha256", "stored_result_sha256", "effects"):
                    assert patch[key] == previous[key], "terminal erased a settled observation: " + key
                assert 0 <= patch["counters"]["steps"] - previous["counters"]["steps"] <= 1
                assert all(patch["counters"][key] == previous["counters"][key]
                    for key in ("claims_reserved", "roles_reserved", "observed_completed_roles"))
            h.hit("journal:" + patch["event"])
            fail = h.fail_event == patch["event"]
            if fail and not h.fail_after_event:
                self.poisoned = True
                raise OSError("synthetic receipt acknowledgment loss")
            h.events.append(copy.deepcopy(patch))
            seq = len(self.lines)
            owned = {"schema_version": 1, "kind": "atlas-local-supervisor-event",
                "queue_path": h.inputs["queue_path"], "queue_key": hashlib.sha256(h.inputs["queue_path"].encode()).hexdigest(),
                "cycle_id": h.inputs["cycle_id"], "seq": seq, "prior_event_acknowledged": seq - 1 if seq else None,
                "initialization_ack": "acknowledged", "pins_sha256": h.inputs["pins_raw_sha256"],
                "admitted_fingerprints": {sid: "c" * 64 for sid in h.ids}, "limits": copy.deepcopy(h.inputs["limits"])}
            self.lines.append((json.dumps(owned | patch, sort_keys=True) + "\n").encode())
            if fail:
                self.poisoned = True
                raise OSError("synthetic readable tail without acknowledgment")
        def close(self, patch):
            self.h.close_count += 1
            assert patch["event"] == "terminal" and patch["unresolved"] is False
            self.append(patch)
            closed = copy.deepcopy(patch)
            closed["event"] = "closed"
            self.append(closed)
            self.h.hit("close_ack")
            return (hashlib.sha256(self.h.inputs["queue_path"].encode()).hexdigest(), self.h.inputs["cycle_id"],
                    hashlib.sha256(self.lines[-1]).hexdigest())
        def release(self):
            self.h.release_count += 1
            self.h.hit("release")


class CycleAdapterTests(unittest.TestCase):
    def assert_resolved(self, h, result):
        self.assertFalse(result["unresolved"])
        self.assertIsNotNone(result["closure_witness"])
        self.assertEqual(result["closure_witness"][2], hashlib.sha256(h.journal.lines[-1]).hexdigest())
        self.assertEqual(h.release_count, 1)
        self.assertEqual(set(result), {"terminal_outcome", "unresolved", "counters", "elapsed_seconds", "closure_witness", "progress_by_item", "failure"})
        for returned, original in h.results:
            self.assertEqual(returned.to_dict(), original)

    def test_cycle_adapter_staged_five_roles_progress_after_ack_then_goal_and_done(self):
        h = CycleAdapterHarness()
        progress_at_settlement = []
        h.hooks["journal:claim_settled"] = lambda h: progress_at_settlement.append(copy.deepcopy(h.inputs["progress_by_item"]))
        result = h.run()
        self.assert_resolved(h, result)
        self.assertEqual(result["terminal_outcome"], "completed")
        self.assertEqual((h.claim_count, h.worker_count, h.record_count, h.load_count), (5, 5, 5, 10))
        self.assertEqual(result["counters"], {"steps": 6, "claims_reserved": 5, "roles_reserved": 5, "observed_completed_roles": 5})
        self.assertEqual(progress_at_settlement[0]["work/123"], {"run_id": None, "completed_roles": []})
        self.assertEqual(progress_at_settlement[1]["work/123"]["completed_roles"], ["implementation"])
        self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], sorted(r["role_id"] for r in RESULT_ROLES))
        held = [f for checkpoint, f in h.frames if checkpoint == "after_claim"]
        self.assertIsNone(held[0]["trusted_expectation"]["run_id"])
        self.assertEqual(held[1]["trusted_expectation"]["run_id"], "work-123-invoke-1")
        self.assertEqual(held[0]["trusted_expectation"]["completed_roles_before"], [])
        self.assertEqual(h.allowances, [1] * 5)
        self.assertEqual([p["event"] for p in h.events][-2:], ["terminal", "closed"])

    def test_cycle_adapter_dependency_chain_reprojects_and_excludes_new_queue_item(self):
        h = CycleAdapterHarness(ids=["work/123", "work/456"], role_max=5, max_roles=20)
        h.dependencies["work/456"] = ["work/123"]
        h.rows["unadmitted"] = {"id": "unadmitted", "operation_id": "op-foreign", "status": "ready"}
        result = h.run()
        self.assert_resolved(h, result)
        self.assertEqual(result["terminal_outcome"], "completed")
        self.assertEqual((h.claim_count, h.worker_count), (2, 2))
        self.assertEqual([p["source_id"] for p in h.events if p["event"] == "claimed"], ["work/123", "work/456"])
        self.assertEqual(h.rows["unadmitted"]["status"], "ready")

    def test_cycle_adapter_reoffered_completed_item_cannot_replay_or_starve_unfinished_item(self):
        h = CycleAdapterHarness(ids=["work/123", "work/456"], role_max=5, max_roles=20)
        accepted_first = []
        def reoffer_completed(h):
            if h.worker_count:
                h.rows["work/123"]["status"] = "ready"
                accepted_first.append(copy.deepcopy(h.inputs["progress_by_item"]["work/123"]))
        h.hooks["ready"] = reoffer_completed
        result = h.run()
        self.assert_resolved(h, result)
        self.assertEqual(result["terminal_outcome"], "completed")
        self.assertEqual((h.claim_count, h.worker_count, h.record_count), (2, 2, 2))
        self.assertEqual([p["source_id"] for p in h.events if p["event"] == "claim_intent"], ["work/123", "work/456"])
        self.assertEqual(result["counters"], {"steps": 3, "claims_reserved": 2, "roles_reserved": 10, "observed_completed_roles": 10})
        self.assertTrue(accepted_first)
        self.assertTrue(all(record == result["progress_by_item"]["work/123"] for record in accepted_first))
        self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], sorted(role["role_id"] for role in RESULT_ROLES))

    def test_cycle_adapter_trusted_complete_resume_is_skipped_before_claim_reservation(self):
        for remaining in (False, True):
            with self.subTest(remaining=remaining):
                ids = ["work/123", "work/456"] if remaining else ["work/123"]
                h = CycleAdapterHarness(ids=ids, role_max=5, max_steps=3 if remaining else 1)
                complete = {"run_id": "accepted-prior-run", "completed_roles": sorted(role["role_id"] for role in RESULT_ROLES)}
                def initialize_complete(h, point, frame):
                    if point == "entry":
                        h.inputs["progress_by_item"]["work/123"] = copy.deepcopy(complete)
                    return frame
                h.guard_transform = initialize_complete
                result = h.run()
                self.assert_resolved(h, result)
                self.assertEqual(result["terminal_outcome"], "completed")
                self.assertEqual((h.claim_count, h.worker_count, h.record_count), (int(remaining),) * 3)
                self.assertEqual(result["progress_by_item"]["work/123"], complete)
                self.assertEqual(result["counters"]["claims_reserved"], int(remaining))
                self.assertEqual(result["counters"]["roles_reserved"], 5 * int(remaining))
                self.assertEqual(result["counters"]["observed_completed_roles"], 5 * int(remaining))
                self.assertEqual([p["source_id"] for p in h.events if p["event"] == "claim_intent"], ["work/456"] if remaining else [])
                self.assertNotIn("claim", h.rows["work/123"])
                self.assertNotIn("result", h.rows["work/123"])

    def test_cycle_adapter_elapsed_overflow_retains_finite_evidence_and_held_settlement(self):
        import math
        for mode in ("before_effect", "returned", "returned_uncertain"):
            with self.subTest(mode=mode):
                h = CycleAdapterHarness(ids=["work/123", "work/456"])
                h.inputs["entry_monotonic"] = -1e308
                h.now = 1e308 if mode == "before_effect" else -1e308
                if mode != "before_effect":
                    h.hooks["worker_return"] = lambda h: setattr(h, "now", 1e308)
                if mode == "returned_uncertain":
                    def uncertain(h, raw, token):
                        raw["status"] = "blocked"
                        raw["evidence"]["invocation_completed"] = False
                        return raw
                    h.worker_transform = uncertain
                result = h.run()
                self.assertEqual(h.release_count, 1)
                self.assertTrue(math.isfinite(result["elapsed_seconds"]))
                self.assertEqual(result["elapsed_seconds"], 0.0)
                self.assertTrue(all(math.isfinite(p["elapsed_seconds"]) and p["elapsed_seconds"] == 0.0 for p in h.events))
                self.assertEqual((h.claim_count, h.worker_count, h.record_count), (0, 0, 0) if mode == "before_effect" else (1, 1, 1))
                self.assertTrue(all(not p["completed_roles"] and p["run_id"] is None for p in result["progress_by_item"].values()))
                if mode == "returned_uncertain":
                    self.assertTrue(result["unresolved"])
                    self.assertIsNone(result["closure_witness"])
                    self.assertEqual(result["failure"], "process_uncertain")
                    self.assertEqual(h.rows["work/123"]["process_uncertainty"]["status"], "unresolved")
                else:
                    self.assert_resolved(h, result)
                    self.assertEqual(result["failure"], "invalid_result")
                if mode != "before_effect":
                    self.assertEqual(h.rows["work/123"]["result"], h.results[0][1])
                    self.assertEqual(h.rows["work/123"]["process_uncertainty"]["status"], "unresolved" if mode == "returned_uncertain" else "resolved")
                orchestrator._decode_cycle_receipt(b"".join(h.journal.lines))

    def test_cycle_adapter_no_work_and_competing_none_claim_consume_finite_budgets(self):
        h = CycleAdapterHarness()
        h.rows["work/123"]["status"] = "blocked"
        result = h.run()
        self.assert_resolved(h, result)
        self.assertEqual(result["terminal_outcome"], "no_work")
        self.assertEqual((h.ready_count, h.claim_count, h.worker_count), (1, 0, 0))
        h = CycleAdapterHarness(max_claims=2)
        h.claim_none = True
        result = h.run()
        self.assert_resolved(h, result)
        self.assertEqual(result["terminal_outcome"], "budget_stop")
        self.assertEqual(result["counters"], {"steps": 2, "claims_reserved": 2, "roles_reserved": 0, "observed_completed_roles": 0})
        self.assertEqual((h.claim_count, h.worker_count, h.record_count), (2, 0, 0))

    def test_cycle_adapter_partial_last_role_reservation_and_last_step_claim(self):
        h = CycleAdapterHarness(role_max=3, max_roles=4, max_steps=2, max_claims=2)
        result = h.run()
        self.assert_resolved(h, result)
        self.assertEqual(h.allowances, [3, 1])
        self.assertEqual(result["counters"], {"steps": 2, "claims_reserved": 2, "roles_reserved": 4, "observed_completed_roles": 4})
        self.assertEqual(result["terminal_outcome"], "budget_stop")
        self.assertIn("semantic-alignment", result["progress_by_item"]["work/123"]["completed_roles"])
        self.assertNotIn("evidence-rollup", result["progress_by_item"]["work/123"]["completed_roles"])

    def test_cycle_adapter_terminal_retains_settled_observations_after_each_budget_exhaustion(self):
        for limit in ("max_steps", "max_claims", "max_roles"):
            with self.subTest(limit=limit):
                h = CycleAdapterHarness(**{limit: 1})
                result = h.run()
                self.assert_resolved(h, result)
                self.assertEqual(result["failure"], "budget_stop")
                self.assertEqual((h.claim_count, h.worker_count, h.record_count), (1, 1, 1))
                settled = next(p for p in h.events if p["event"] == "claim_settled")
                terminal = h.events[-2]
                self.assertEqual(terminal["event"], "terminal")
                self.assertEqual(terminal["counters"], settled["counters"])
                for key in ("operation_id", "source_id", "claim_key", "invocation_id", "result_sha256", "stored_result_sha256", "effects"):
                    self.assertEqual(terminal[key], settled[key])
                self.assertEqual(result["progress_by_item"]["work/123"],
                    {"run_id": "work-123-invoke-1", "completed_roles": ["implementation"]})

    def test_cycle_adapter_terminal_retains_acknowledged_unacquired_claim_after_budget_stop(self):
        h = CycleAdapterHarness(max_claims=1)
        h.claim_none = True
        result = h.run()
        self.assert_resolved(h, result)
        self.assertEqual(result["failure"], "budget_stop")
        self.assertEqual((h.claim_count, h.worker_count, h.record_count), (1, 0, 0))
        previous, terminal = h.events[-3], h.events[-2]
        self.assertEqual(previous["event"], "claim_not_acquired")
        self.assertEqual(terminal["counters"], previous["counters"])
        self.assertEqual(terminal["source_id"], "work/123")
        self.assertEqual(terminal["effects"], previous["effects"])
        self.assertEqual(terminal["effects"]["claim"], {"attempted": True, "ack": "acknowledged"})
        self.assertIsNone(terminal["claim_key"])
        self.assertEqual(result["progress_by_item"]["work/123"], {"run_id": None, "completed_roles": []})

    def test_cycle_adapter_terminal_preserves_settlement_when_next_reservation_or_guard_refuses(self):
        for mode in ("guard", "cancel", "clock"):
            with self.subTest(mode=mode):
                h = CycleAdapterHarness()
                def progressed():
                    return bool(h.inputs["progress_by_item"].get("work/123", {}).get("completed_roles"))
                if mode == "guard":
                    def changed(h, point, frame):
                        if point == "before_step" and progressed():
                            frame.update(changed=True, reason="input_changed", trusted_expectation=None)
                        return frame
                    h.guard_transform = changed
                elif mode == "cancel":
                    h.hooks["cancel"] = lambda h: setattr(h, "cancelled", progressed())
                else:
                    h.clock = lambda: float("nan") if progressed() else h.now
                result = h.run()
                self.assert_resolved(h, result)
                self.assertEqual(result["failure"], {"guard": "input_changed", "cancel": "stop", "clock": "invalid_result"}[mode])
                self.assertEqual((h.claim_count, h.worker_count, h.record_count), (1, 1, 1))
                self.assertEqual(h.ready_count, 1)
                settled = next(p for p in h.events if p["event"] == "claim_settled")
                terminal = h.events[-2]
                for key in ("operation_id", "source_id", "claim_key", "invocation_id", "result_sha256", "stored_result_sha256", "effects"):
                    self.assertEqual(terminal[key], settled[key])
                self.assertEqual(terminal["counters"]["steps"], settled["counters"]["steps"] + (mode == "guard"))
                self.assertTrue(math.isfinite(result["elapsed_seconds"]))
                self.assertEqual(result["progress_by_item"]["work/123"],
                    {"run_id": "work-123-invoke-1", "completed_roles": ["implementation"]})
                self.assertEqual(h.rows["work/123"]["result"], h.results[0][1])

    def test_cycle_adapter_stop_before_claim_and_stop_after_claim_no_launch_settlement(self):
        h = CycleAdapterHarness()
        h.cancelled = True
        result = h.run()
        self.assert_resolved(h, result)
        self.assertEqual((h.claim_count, h.worker_count, h.record_count), (0, 0, 0))
        self.assertEqual(result["terminal_outcome"], "cancelled")
        for point in ("claim_applied", "journal:launch_intent", "factory"):
            with self.subTest(point=point):
                h = CycleAdapterHarness()
                h.hooks[point] = lambda h: setattr(h, "cancelled", True)
                result = h.run()
                self.assert_resolved(h, result)
                self.assertEqual((h.claim_count, h.worker_count, h.record_count, h.load_count), (1, 0, 1, 2))
                self.assertEqual(result["progress_by_item"]["work/123"], {"run_id": None, "completed_roles": []})
                self.assertEqual(result["terminal_outcome"], "cancelled")
                self.assertEqual(h.rows["work/123"]["result"]["evidence"], {"supervisor_no_launch": True})
                self.assertIsNone(h.events[-1]["invocation_id"])
                self.assertEqual(h.events[-1]["effects"]["launch"], {"attempted": False, "ack": "not_attempted"})
                self.assertEqual(result["counters"]["roles_reserved"], 0 if point == "claim_applied" else 1)

    def test_cycle_adapter_preclaim_intent_stop_does_not_attempt_or_repair_claim(self):
        h = CycleAdapterHarness()
        h.hooks["journal:claim_intent"] = lambda h: setattr(h, "cancelled", True)
        result = h.run()
        self.assertTrue(result["unresolved"])
        self.assertIsNone(result["closure_witness"])
        self.assertEqual((h.claim_count, h.worker_count, h.record_count), (0, 0, 0))
        self.assertEqual(result["counters"]["claims_reserved"], 1)
        self.assertEqual(h.events[-1]["effects"]["claim"], {"attempted": False, "ack": "pending"})

    def test_cycle_adapter_original_entry_deadline_charges_fake_queue_wait(self):
        for point in ("ready", "load"):
            with self.subTest(point=point):
                h = CycleAdapterHarness()
                h.hooks[point] = lambda h: setattr(h, "now", 200.0)
                result = h.run()
                self.assert_resolved(h, result)
                self.assertEqual(result["terminal_outcome"], "cancelled")
                self.assertEqual(result["failure"], "deadline")
                self.assertEqual(h.worker_count, 0)
                self.assertEqual(result["elapsed_seconds"], 100.0)
                self.assertEqual(h.record_count, 1 if point == "load" else 0)

    def test_cycle_adapter_token_cancels_held_worker_and_preserves_original_uncertainty(self):
        h = CycleAdapterHarness()
        def held_stop(h, raw, token):
            h.now = 200.0
            self.assertTrue(token.is_set())
            raw["status"] = "blocked"
            raw["evidence"].update(invocation_completed=False, termination_proved=True)
            return raw
        h.worker_transform = held_stop
        result = h.run()
        self.assertTrue(result["unresolved"])
        self.assertEqual(result["failure"], "process_uncertain")
        self.assertEqual((h.claim_count, h.worker_count, h.record_count, h.load_count), (1, 1, 1, 2))
        self.assertIsNone(result["closure_witness"])
        self.assertEqual(h.rows["work/123"]["result"], h.results[0][1])
        self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], [])

    def test_cycle_adapter_applied_claim_or_result_lost_ack_never_replayed_or_read_back_as_ack(self):
        for point, reason, expected_loads in (("claim_applied", "claim_unknown", 0), ("record_applied", "result_unknown", 1)):
            with self.subTest(point=point):
                h = CycleAdapterHarness()
                h.hooks[point] = lambda h: (_ for _ in ()).throw(OSError("synthetic lost acknowledgment"))
                result = h.run()
                self.assertTrue(result["unresolved"])
                self.assertEqual(result["failure"], reason)
                self.assertEqual(h.claim_count, 1)
                self.assertEqual(h.load_count, expected_loads)
                self.assertEqual(h.record_count, 1 if point == "record_applied" else 0)
                self.assertIsNone(result["closure_witness"])
                self.assertEqual(h.release_count, 1)
                self.assertEqual(h.events[-1]["effects"]["result" if point == "record_applied" else "claim"]["ack"], "unknown")

    def test_cycle_adapter_worker_exception_is_launch_unknown_without_invented_result(self):
        h = CycleAdapterHarness()
        h.hooks["worker"] = lambda h: (_ for _ in ()).throw(OSError("unknown held process"))
        result = h.run()
        self.assertEqual(result["failure"], "launch_unknown")
        self.assertTrue(result["unresolved"])
        self.assertEqual((h.claim_count, h.worker_count, h.record_count), (1, 1, 0))
        self.assertIsNone(h.events[-1]["result_sha256"])
        self.assertIsNone(h.events[-1]["invocation_id"])

    def test_cycle_adapter_receipt_failure_every_transition_has_no_repair_write(self):
        events = ("opened", "step_started", "claim_intent", "claimed", "launch_intent", "worker_returned",
                  "result_intent", "result_acknowledged", "claim_settled", "terminal", "closed")
        for event in events:
            for readable_tail in (False, True):
                with self.subTest(event=event, readable_tail=readable_tail):
                    h = CycleAdapterHarness()
                    h.fail_event, h.fail_after_event = event, readable_tail
                    result = h.run()
                    self.assertTrue(result["unresolved"])
                    self.assertEqual(result["failure"], "receipt_unknown")
                    self.assertIsNone(result["closure_witness"])
                    self.assertEqual(h.release_count, 1)
                    tail = h.trace[h.trace.index("journal:" + event) + 1:]
                    self.assertFalse(any(v.startswith("journal:") for v in tail))
                    if event in {"opened", "step_started", "claim_intent"}:
                        self.assertEqual(h.claim_count, 0)
                    if event in {"claimed", "launch_intent"}:
                        self.assertEqual(h.worker_count, 0)
                    if event in {"worker_returned", "result_intent"}:
                        self.assertEqual(h.record_count, 0)
                    if event == "claim_settled":
                        self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], [])

    def test_cycle_adapter_input_drift_before_and_after_launch_preserves_result_and_progress(self):
        for checkpoint in ("before_claim", "after_claim", "after_worker"):
            with self.subTest(checkpoint=checkpoint):
                h = CycleAdapterHarness()
                def changed(h, point, frame):
                    if point == checkpoint:
                        frame.update(changed=True, reason="input_changed", head_changed=point == "after_worker", trusted_expectation=None)
                    return frame
                h.guard_transform = changed
                result = h.run()
                self.assert_resolved(h, result)
                self.assertEqual(result["terminal_outcome"], "input_changed")
                self.assertEqual(h.worker_count, 1 if checkpoint == "after_worker" else 0)
                self.assertEqual(h.record_count, 0 if checkpoint == "before_claim" else 1)
                self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], [])
                if checkpoint == "after_worker":
                    self.assertEqual(h.rows["work/123"]["result"], h.results[0][1])
                    self.assertEqual(h.rows["work/123"]["result"]["status"], "ready")

    def test_cycle_adapter_cancellation_after_return_or_during_settlement_preserves_worker_result(self):
        for point in ("worker_return", "journal:result_intent", "record_applied", "journal:claim_settled"):
            with self.subTest(point=point):
                h = CycleAdapterHarness()
                h.hooks[point] = lambda h: setattr(h, "cancelled", True)
                result = h.run()
                self.assert_resolved(h, result)
                self.assertEqual(result["terminal_outcome"], "cancelled")
                self.assertEqual((h.claim_count, h.worker_count, h.record_count), (1, 1, 1))
                self.assertEqual(h.rows["work/123"]["result"], h.results[0][1])
                self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], [])

    def test_cycle_adapter_zero_progress_and_wrong_result_stop_after_one_settlement(self):
        for mode in ("zero", "invalid", "too_many"):
            with self.subTest(mode=mode):
                h = CycleAdapterHarness()
                def alter(h, raw, token):
                    if mode == "zero":
                        raw, _ = result_assessment_fixture([], [])
                    elif mode == "invalid":
                        raw["evidence"]["goal_acceptance"]["context_hash"] = "c" * 64
                    else:
                        raw, _ = result_assessment_fixture(["implementation", "test-runner"], ["implementation", "test-runner"])
                    return raw
                h.worker_transform = alter
                result = h.run()
                self.assert_resolved(h, result)
                self.assertEqual(result["failure"], "zero_progress" if mode == "zero" else "invalid_result")
                self.assertEqual((h.worker_count, h.record_count), (1, 1))
                self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], [])

    def test_cycle_adapter_verifying_read_disagreement_is_once_and_unresolved(self):
        h = CycleAdapterHarness()
        h.hooks["record_applied"] = lambda h: h.rows["work/123"]["result"].update(summary="foreign stored result")
        result = h.run()
        self.assertTrue(result["unresolved"])
        self.assertEqual(result["failure"], "queue_disagreement")
        self.assertEqual((h.claim_count, h.worker_count, h.record_count, h.load_count), (1, 1, 1, 2))
        self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], [])
        self.assertIsNone(result["closure_witness"])

    def test_cycle_adapter_changed_guard_expectation_or_progress_cannot_replace_held_trust(self):
        for mode in ("expectation", "progress"):
            with self.subTest(mode=mode):
                h = CycleAdapterHarness()
                def corrupt(h, point, frame):
                    if point == "after_worker":
                        if mode == "expectation":
                            frame["trusted_expectation"]["context_hash"] = "c" * 64
                        else:
                            h.inputs["progress_by_item"]["work/123"]["run_id"] = "foreign-run"
                    return frame
                h.guard_transform = corrupt
                result = h.run()
                self.assert_resolved(h, result)
                self.assertEqual(result["failure"], "invalid_result")
                self.assertEqual(h.rows["work/123"]["result"], h.results[0][1])
                self.assertEqual(h.inputs["progress_by_item"], result["progress_by_item"])
                self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], [])

    def test_cycle_adapter_failed_close_or_release_never_reports_witness_success(self):
        for point in ("close_ack", "release"):
            with self.subTest(point=point):
                h = CycleAdapterHarness()
                h.hooks[point] = lambda h: (_ for _ in ()).throw(OSError("synthetic cleanup acknowledgment loss"))
                result = h.run()
                self.assertTrue(result["unresolved"])
                self.assertIsNone(result["closure_witness"])
                self.assertEqual(result["failure"], "receipt_unknown")
                self.assertEqual(h.release_count, 1)
                self.assertEqual(h.events[-1]["event"], "closed")

    def test_cycle_adapter_invalid_input_clock_or_cancel_observation_refuses_before_worker(self):
        for mode in ("extra", "fraction", "bad_raw_digest"):
            with self.subTest(mode=mode):
                h = CycleAdapterHarness()
                if mode == "extra": h.inputs["unexpected"] = True
                elif mode == "fraction": h.inputs["limits"]["max_claims"] = 1.5
                else: h.inputs["pins_raw_sha256"] = "bad"
                with self.assertRaises(ValueError): h.run()
                self.assertEqual((h.claim_count, h.worker_count, h.release_count), (0, 0, 1))
                self.assertEqual(h.events, [])
        for value in (99.0, float("nan")):
            h = CycleAdapterHarness()
            h.hooks["ready"] = lambda h, value=value: setattr(h, "now", value)
            result = h.run()
            self.assert_resolved(h, result)
            self.assertEqual(result["failure"], "invalid_result")
            self.assertEqual((h.claim_count, h.worker_count), (0, 0))
        h = CycleAdapterHarness()
        h.cancellation.is_set = lambda: (_ for _ in ()).throw(OSError("synthetic inspection failure"))
        result = h.run()
        self.assert_resolved(h, result)
        self.assertEqual(result["failure"], "stop_inspection_error")
        self.assertEqual(h.claim_count, 0)

    def test_cycle_adapter_frozen_held_operation_survives_nested_worker_and_guard_mutation(self):
        h = CycleAdapterHarness(max_roles=1)
        original_guard = h.guard
        def mutate_guard(checkpoint, operation):
            frame = original_guard(checkpoint, operation)
            if checkpoint == "after_claim":
                operation["metadata"]["team_template"] = "guard-mutated"
            return frame
        h.guard = mutate_guard
        def mutate_held(h, raw, token):
            h.held_operation.metadata["team_template"] = "worker-mutated"
            return raw
        h.worker_transform = mutate_held
        result = h.run()
        self.assert_resolved(h, result)
        after_claim = next(op for point, op in h.guard_operations if point == "after_claim")
        after_worker = next(op for point, op in h.guard_operations if point == "after_worker")
        self.assertEqual(after_worker, after_claim)
        self.assertEqual(after_worker["metadata"]["team_template"], "work-item-change-lifecycle")
        self.assertEqual(h.held_operation.metadata["team_template"], "worker-mutated")
        self.assertEqual(h.record_count, 1)

    def test_cycle_adapter_malformed_return_never_advances_or_invents_process_proof(self):
        for mode in ("evidence_list", "nonfinite", "wrong_invocation"):
            with self.subTest(mode=mode):
                h = CycleAdapterHarness()
                def corrupt(h, raw, token):
                    if mode == "evidence_list": raw["evidence"] = []
                    elif mode == "nonfinite": raw["evidence"]["extra"] = float("nan")
                    else: raw["evidence"]["process_invocation_id"] = "foreign-invocation"
                    return raw
                h.worker_transform = corrupt
                result = h.run()
                self.assertTrue(result["unresolved"])
                self.assertIsNone(result["closure_witness"])
                self.assertEqual(h.worker_count, 1)
                self.assertEqual(h.record_count, 0 if mode == "nonfinite" else 1)
                self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], [])
                self.assertEqual(h.release_count, 1)

    def test_cycle_adapter_goal_fail_and_inconclusive_stop_after_original_settlement(self):
        for verdict in ("fail", "inconclusive"):
            with self.subTest(verdict=verdict):
                h = CycleAdapterHarness(role_max=5)
                def fail_goal(h, raw, token):
                    raw, _ = result_assessment_fixture(["implementation", "test-runner", "code-review"],
                        ["implementation", "test-runner", "code-review", "semantic-alignment"],
                        goal_verdict=verdict, status="blocked")
                    return raw
                h.worker_transform = fail_goal
                result = h.run()
                self.assert_resolved(h, result)
                self.assertEqual(result["failure"], "goal_review_failed")
                self.assertEqual((h.worker_count, h.record_count), (1, 1))
                self.assertEqual(h.rows["work/123"]["result"], h.results[0][1])
                self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], [])

    def test_cycle_adapter_patches_decode_with_exact_journal_owned_fields(self):
        for no_launch in (False, True):
            with self.subTest(no_launch=no_launch):
                h = CycleAdapterHarness(role_max=3)
                if no_launch:
                    h.hooks["claim_applied"] = lambda h: setattr(h, "cancelled", True)
                result = h.run()
                self.assert_resolved(h, result)
                events = []
                for seq, patch in enumerate(h.events):
                    owned = {"schema_version": 1, "kind": "atlas-local-supervisor-event",
                        "queue_path": h.inputs["queue_path"], "queue_key": hashlib.sha256(h.inputs["queue_path"].encode()).hexdigest(),
                        "cycle_id": h.inputs["cycle_id"], "seq": seq, "prior_event_acknowledged": seq - 1 if seq else None,
                        "initialization_ack": "acknowledged", "pins_sha256": h.inputs["pins_raw_sha256"],
                        "admitted_fingerprints": {sid: "c" * 64 for sid in h.ids}, "limits": h.inputs["limits"]}
                    self.assertFalse(set(owned) & set(patch))
                    events.append(owned | copy.deepcopy(patch))
                raw = b"".join((json.dumps(event, sort_keys=True) + "\n").encode() for event in events)
                self.assertEqual(orchestrator._decode_cycle_receipt(raw), events)
                self.assertEqual(events[-1]["counters"], result["counters"])
                self.assertEqual(events[-1]["elapsed_seconds"], events[-2]["elapsed_seconds"])

    def test_cycle_adapter_guard_and_provider_observation_failures_do_not_retry(self):
        for point in ("guard:entry", "guard:after_claim", "guard:after_worker", "ready", "load"):
            with self.subTest(point=point):
                h = CycleAdapterHarness()
                h.hooks[point] = lambda h: (_ for _ in ()).throw(OSError("synthetic observation failure"))
                result = h.run()
                self.assertEqual(h.trace.count(point), 1)
                self.assertEqual(h.release_count, 1)
                self.assertEqual(h.worker_count, 1 if point == "guard:after_worker" else 0)
                self.assertEqual(h.record_count, 1 if point in {"guard:after_claim", "guard:after_worker"} else 0)
                self.assertTrue(all(not v["completed_roles"] for v in result["progress_by_item"].values()))
                if point == "guard:entry":
                    self.assertEqual(h.events, [])
                    self.assertIsNone(result["closure_witness"])
                elif point in {"ready", "load"}:
                    self.assertTrue(result["unresolved"])
                    self.assertIsNone(result["closure_witness"])
                else:
                    self.assert_resolved(h, result)

    def test_cycle_adapter_return_elapsed_includes_close_without_rewriting_receipt(self):
        h = CycleAdapterHarness(max_roles=1)
        h.hooks["close_ack"] = lambda h: setattr(h, "now", 105.0)
        result = h.run()
        self.assert_resolved(h, result)
        self.assertEqual(result["elapsed_seconds"], 5.0)
        self.assertEqual(h.events[-1]["elapsed_seconds"], 0.0)
        self.assertEqual(h.events[-1]["counters"], result["counters"])
        self.assertEqual(orchestrator._decode_cycle_receipt(b"".join(h.journal.lines))[-1]["event"], "closed")

    def test_cycle_adapter_remains_unreachable_from_production_entry(self):
        import ast
        tree = ast.parse((ROOT / "atlas-agent-orchestrator").read_text())
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in {"main", "process_once", "process_atlas_work_items_once"}:
                self.assertFalse(any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "_run_bounded_cycle" for call in ast.walk(node)))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        branch = next(node for node in main.body if isinstance(node, ast.If) and ast.unparse(node.test) == "args.atlas_bounded")
        self.assertEqual(sum(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "_run_bounded_cli" for call in ast.walk(branch)), 1)
        self.assertTrue(any(isinstance(node, ast.Return) for node in branch.body))


class CycleJournalTests(unittest.TestCase):
    def make(self, *, h=None, directory=None, cycle="b" * 32, closures=None):
        import tempfile
        if directory is None:
            temporary = tempfile.TemporaryDirectory(prefix="atlas-journal-")
            self.addCleanup(temporary.cleanup)
            directory = Path(temporary.name)
        h = h or CycleAdapterHarness(role_max=3)
        queue = directory / "queue.json"
        if not queue.exists():
            queue.write_text(json.dumps({"version": 1, "work_items": []}))
        h.inputs.update(queue_path=str(queue), pins_raw_sha256="e" * 64, cycle_id=cycle)
        pins = pins_fixture()
        pins.update(queue_path=str(queue), admitted_item_ids=sorted(h.ids), item_closure=[
            {"item_id": sid, "operation_id": h.rows[sid]["operation_id"], "execution_checkout": "/work/repo",
             "depends_on": [], "immutable_sha256": str(index + 3) * 64} for index, sid in enumerate(sorted(h.ids))])
        closures = {} if closures is None else closures
        journal = orchestrator._CycleJournal(str(queue), pins, h.inputs["pins_raw_sha256"], h.inputs["limits"],
            cycle_id=cycle, acknowledged_closures=closures)
        self.addCleanup(journal.release)
        h.journal = journal
        state = directory / ".atlas-supervisor" / hashlib.sha256(str(queue).encode()).hexdigest()
        return h, journal, state, closures

    def patches(self):
        h = CycleAdapterHarness(role_max=5)
        h.run()
        return copy.deepcopy(h.events)

    def open_to(self, patches, target):
        h, journal, state, closures = self.make(h=CycleAdapterHarness(role_max=5))
        for patch in patches:
            if patch["event"] == "opened": journal.acquire_and_open(patch)
            elif patch["event"] == "terminal": journal.close(patch)
            elif patch["event"] != "closed": journal.append(patch)
            if patch["event"] == target: break
        return h, journal, state, closures

    def test_cycle_journal_real_adapter_staged_receipt_exact_raw_digest_and_closure(self):
        h, journal, state, closures = self.make()
        result = h.run()
        self.assertEqual(result["terminal_outcome"], "completed")
        self.assertFalse(result["unresolved"])
        raw = (state / (h.inputs["cycle_id"] + ".jsonl")).read_bytes()
        events = orchestrator._decode_cycle_receipt(raw)
        self.assertEqual([e["event"] for e in events].count("claim_settled"), 2)
        self.assertEqual(events[-1]["event"], "closed")
        self.assertEqual(events[-1]["counters"], result["counters"])
        self.assertEqual(events[-1]["pins_sha256"], "e" * 64)
        digest = hashlib.sha256(raw.splitlines(keepends=True)[-1]).hexdigest()
        self.assertEqual(result["closure_witness"], (state.name, h.inputs["cycle_id"], digest))
        self.assertEqual(closures[(state.name, h.inputs["cycle_id"])], digest)
        self.assertEqual(raw, b"".join(journal._line(event) for event in events))
        self.assertTrue(journal._released)

    def test_cycle_journal_real_adapter_no_launch_before_and_after_launch_intent(self):
        for point in ("claim_applied", "factory"):
            with self.subTest(point=point):
                h, journal, state, closures = self.make()
                h.hooks[point] = lambda h: setattr(h, "cancelled", True)
                result = h.run()
                self.assertEqual((h.worker_count, h.record_count), (0, 1))
                self.assertFalse(result["unresolved"])
                events = journal._events
                intent = next(e for e in events if e["event"] == "result_intent")
                self.assertEqual(intent["effects"]["launch"], {"attempted": False, "ack": "not_attempted"})
                self.assertIsNone(intent["invocation_id"])
                self.assertEqual(any(e["event"] == "launch_intent" for e in events), point == "factory")
                self.assertIsNotNone(result["closure_witness"])

    def test_cycle_journal_constructor_is_pure_and_retains_frozen_copies(self):
        from unittest.mock import patch
        h, journal, state, closures = self.make()
        with patch.object(orchestrator.os, "open", side_effect=AssertionError("constructor IO")):
            duplicate = orchestrator._CycleJournal(h.inputs["queue_path"], journal._pins, "f" * 64,
                h.inputs["limits"], cycle_id="c" * 32, acknowledged_closures={})
        h.inputs["limits"]["max_claims"] = 999
        self.assertNotEqual(journal._owned["limits"], h.inputs["limits"])
        duplicate.release()
        self.assertFalse(state.exists())

    def test_cycle_journal_same_process_witness_allows_next_cycle_but_missing_or_changed_witness_refuses(self):
        h, journal, state, closures = self.make()
        self.assertFalse(h.run()["unresolved"])
        directory = state.parent.parent
        fresh, next_journal, _, _ = self.make(directory=directory, cycle="c" * 32, closures=closures)
        self.assertFalse(fresh.run()["unresolved"])
        self.assertEqual(fresh.worker_count, 2)
        for held in ({}, dict.fromkeys(closures, "0" * 64)):
            with self.subTest(held=bool(held)):
                other, candidate, _, _ = self.make(directory=directory, cycle="d" * 32, closures=held)
                result = other.run()
                self.assertTrue(result["unresolved"])
                self.assertEqual((other.claim_count, other.worker_count), (0, 0))
                self.assertFalse((state / ("d" * 32 + ".jsonl")).exists())

    def test_cycle_journal_new_process_refuses_readable_closed_receipt(self):
        import subprocess
        h, journal, state, closures = self.make()
        self.assertFalse(h.run()["unresolved"])
        script = """import importlib.machinery,importlib.util,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).parent))
loader=importlib.machinery.SourceFileLoader('journal_child',sys.argv[1]);spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)
data=json.loads(sys.argv[2]);j=m._CycleJournal(data['queue'],data['pins'],data['digest'],data['limits'],cycle_id='d'*32,acknowledged_closures={})
try:
 j.acquire_and_open(data['patch'])
except ValueError as error:
 print(str(error));sys.exit(0)
finally:j.release()
sys.exit(3)
"""
        data = {"queue": h.inputs["queue_path"], "pins": journal._pins, "digest": "e" * 64,
                "limits": h.inputs["limits"], "patch": self.patches()[0]}
        child = subprocess.run([sys.executable, "-B", "-c", script, str(ROOT / "atlas-agent-orchestrator"), json.dumps(data)],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertIn("still-held closure", child.stdout)
        self.assertFalse((state / ("d" * 32 + ".jsonl")).exists())

    def test_cycle_journal_nonblocking_competitor_child_cannot_create_receipt(self):
        import subprocess
        h, journal, state, closures = self.make(h=CycleAdapterHarness(role_max=5))
        journal.acquire_and_open(self.patches()[0])
        script = """import importlib.machinery,importlib.util,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).parent))
loader=importlib.machinery.SourceFileLoader('journal_competitor',sys.argv[1]);spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);loader.exec_module(m)
d=json.loads(sys.argv[2]);j=m._CycleJournal(d['queue'],d['pins'],'e'*64,d['limits'],cycle_id='c'*32,acknowledged_closures={})
try:
 j.acquire_and_open(d['patch'])
except BlockingIOError:
 print('contended');sys.exit(0)
finally:j.release()
sys.exit(3)
"""
        data = {"queue": h.inputs["queue_path"], "pins": journal._pins, "limits": h.inputs["limits"], "patch": self.patches()[0]}
        child = subprocess.run([sys.executable, "-B", "-c", script, str(ROOT / "atlas-agent-orchestrator"), json.dumps(data)],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), "contended")
        other, candidate, _, _ = self.make(directory=state.parent.parent, cycle="c" * 32)
        result = other.run()
        self.assertTrue(result["unresolved"])
        self.assertEqual(other.claim_count, 0)
        self.assertFalse((state / ("c" * 32 + ".jsonl")).exists())
        self.assertTrue((state / "controller.lock").is_file())

    def test_cycle_journal_queue_replace_keeps_path_identity_and_hardlinks_symlinks_refuse(self):
        import os
        h, journal, state, closures = self.make()
        old_inode = Path(h.inputs["queue_path"]).stat().st_ino
        replacement = state.parent.parent / "replacement"
        replacement.write_text('{"work_items": []}')
        replacement.replace(h.inputs["queue_path"])
        self.assertNotEqual(Path(h.inputs["queue_path"]).stat().st_ino, old_inode)
        self.assertFalse(h.run()["unresolved"])
        for kind in ("queue_link", "queue_hardlink", "state_link", "key_link", "lock_link", "receipt_link"):
            with self.subTest(kind=kind):
                h, journal, state, closures = self.make()
                queue = Path(h.inputs["queue_path"])
                target = queue.parent / "target"
                if kind in {"queue_link", "queue_hardlink"}:
                    queue.rename(target)
                    os.symlink(target, queue) if kind == "queue_link" else os.link(target, queue)
                elif kind == "state_link":
                    target.mkdir(); os.symlink(target, queue.parent / ".atlas-supervisor")
                elif kind == "key_link":
                    state.parent.mkdir(); target.mkdir(); os.symlink(target, state)
                else:
                    state.mkdir(parents=True)
                    target.write_text("{}")
                    os.symlink(target, state / ("controller.lock" if kind == "lock_link" else "a" * 32 + ".jsonl"))
                result = h.run()
                self.assertTrue(result["unresolved"])
                self.assertEqual((h.claim_count, h.worker_count), (0, 0))

    def test_cycle_journal_active_claim_or_unresolved_process_refuses_before_open(self):
        for row in ({"id": "x", "status": "running", "claim": {}},
                    {"id": "x", "status": "ready", "process_uncertainty": {"status": "unresolved"}}):
            with self.subTest(row=row):
                h, journal, state, closures = self.make()
                Path(h.inputs["queue_path"]).write_text(json.dumps({"work_items": [row]}))
                result = h.run()
                self.assertTrue(result["unresolved"])
                self.assertEqual(h.claim_count, 0)
                self.assertFalse(state.exists())

    def test_cycle_journal_every_initialization_sync_failure_prevents_claim_and_never_retries(self):
        from unittest.mock import patch
        real_sync = orchestrator.os.fsync
        for ordinal in range(1, 9):
            with self.subTest(ordinal=ordinal):
                h, journal, state, closures = self.make()
                calls = []
                def fail_sync(fd):
                    calls.append(fd)
                    if len(calls) == ordinal: raise OSError("synthetic initialization sync failure")
                    return real_sync(fd)
                with patch.object(orchestrator.os, "fsync", side_effect=fail_sync): result = h.run()
                self.assertTrue(result["unresolved"])
                self.assertEqual((h.claim_count, h.worker_count), (0, 0))
                self.assertEqual(len(calls), ordinal)
                self.assertEqual(closures, {})
                self.assertTrue(journal._released)

    def test_cycle_journal_initialization_create_open_and_lock_failures_prevent_effects(self):
        from unittest.mock import patch
        import fcntl
        for kind in ("mkdir_state", "mkdir_key", "open_state", "open_key", "open_lock", "open_receipt", "lock"):
            with self.subTest(kind=kind):
                h, journal, state, closures = self.make()
                target = {"mkdir_state": ".atlas-supervisor", "mkdir_key": state.name, "open_state": ".atlas-supervisor",
                          "open_key": state.name, "open_lock": "controller.lock", "open_receipt": "b" * 32 + ".jsonl"}.get(kind)
                module, method = (fcntl, "flock") if kind == "lock" else (orchestrator.os, "mkdir" if kind.startswith("mkdir") else "open")
                real = getattr(module, method)
                calls = []
                def fail(name, *args, **kwargs):
                    if kind == "lock" or name == target:
                        calls.append(name)
                        raise OSError("synthetic initialization operation failure")
                    return real(name, *args, **kwargs)
                with patch.object(module, method, side_effect=fail): result = h.run()
                self.assertEqual(len(calls), 1)
                self.assertTrue(result["unresolved"])
                self.assertEqual((h.claim_count, h.worker_count), (0, 0))

    def test_cycle_journal_every_transition_write_flush_sync_and_short_write_poison(self):
        from unittest.mock import patch
        names = [p["event"] for p in self.patches()]
        for event in names:
            for fault in ("write", "short", "flush", "sync"):
                with self.subTest(event=event, fault=fault):
                    h, journal, state, closures = self.make(h=CycleAdapterHarness(role_max=5))
                    original_append, real_sync = journal._append, orchestrator.os.fsync
                    reached = []
                    class FaultStream:
                        def __init__(self, stream): self.stream = stream
                        def write(self, data):
                            reached.append("write")
                            if fault == "write": raise OSError("synthetic write failure")
                            if fault == "short": return self.stream.write(data[:len(data)//2])
                            return self.stream.write(data)
                        def flush(self):
                            reached.append("flush")
                            if fault == "flush": raise OSError("synthetic flush failure")
                            return self.stream.flush()
                        def fileno(self): return self.stream.fileno()
                        def close(self): return self.stream.close()
                    def append(patch_value, *, creation=False):
                        if patch_value["event"] == event:
                            journal._stream = FaultStream(journal._stream)
                        return original_append(patch_value, creation=creation)
                    def sync(fd):
                        if fault == "sync" and reached and journal._stream is not None and fd == journal._stream.fileno():
                            reached.append("sync")
                            raise OSError("synthetic receipt sync failure")
                        return real_sync(fd)
                    journal._append = append
                    with patch.object(orchestrator.os, "fsync", side_effect=sync): result = h.run()
                    self.assertTrue(reached)
                    self.assertTrue(result["unresolved"])
                    self.assertIsNone(result["closure_witness"])
                    self.assertEqual(closures, {})
                    self.assertTrue(journal._poisoned)
                    self.assertNotEqual(journal._events[-1]["event"] if journal._events else None, event)
                    self.assertEqual(reached.count("write"), 1)
                    if event in {"opened", "step_started", "claim_intent"}: self.assertEqual(h.claim_count, 0)
                    if event in {"claimed", "launch_intent"}: self.assertEqual(h.worker_count, 0)
                    if event in {"worker_returned", "result_intent"}: self.assertEqual(h.record_count, 0)

    def test_cycle_journal_invalid_transition_field_ownership_identity_and_counters_poison_before_write(self):
        from unittest.mock import patch
        patches = self.patches()
        for target in ("opened", "step_started", "claim_intent", "claimed", "launch_intent", "worker_returned", "result_intent", "result_acknowledged", "claim_settled"):
            with self.subTest(target=target):
                h, journal, state, closures = self.open_to(patches, target)
                raw = journal._raw
                invalid = copy.deepcopy(journal._events[-1])
                invalid = {key: invalid[key] for key in journal._PATCH}
                # Repeating any acknowledged event violates the transition table.
                with self.assertRaises(ValueError): journal.append(invalid)
                self.assertEqual(journal._raw, raw)
                with self.assertRaises(ValueError): journal.close(patches[-2])
                self.assertEqual(closures, {})
        for mutation in (lambda p: p.update(seq=1), lambda p: p.pop("effects"),
                         lambda p: p["counters"].update(steps=2),
                         lambda p: p.update(operation_id="op-foreign"),
                         lambda p: p["effects"]["claim"].update(ack="acknowledged", attempted=True)):
            h, journal, state, closures = self.open_to(patches, "step_started")
            value = copy.deepcopy(patches[2]); mutation(value)
            raw = journal._raw
            with self.assertRaises(ValueError): journal.append(value)
            self.assertEqual(journal._raw, raw)

    def test_cycle_journal_fresh_current_jobs_directory_is_not_an_orphaned_prior_cycle(self):
        h, journal, state, closures = self.make()
        jobs = state / (h.inputs["cycle_id"] + ".jobs")
        jobs.mkdir(parents=True)
        result = h.run()
        self.assertFalse(result["unresolved"])
        self.assertTrue(jobs.is_dir())
        self.assertIsNotNone(result["closure_witness"])

    def test_cycle_journal_settled_guard_refusal_preserves_prior_claim_observations(self):
        # Blocked by the separately assigned accepted-A3 reset-placement repair.
        h, journal, state, closures = self.make()
        def changed(h, point, frame):
            if point == "before_step" and h.worker_count:
                frame.update(changed=True, reason="input_changed", trusted_expectation=None)
            return frame
        h.guard_transform = changed
        result = h.run()
        self.assertFalse(result["unresolved"])
        self.assertEqual(result["failure"], "input_changed")
        self.assertEqual((h.claim_count, h.worker_count, h.record_count), (1, 1, 1))
        self.assertEqual(result["counters"]["steps"], 2)
        terminal = journal._events[-2]
        self.assertEqual(terminal["event"], "terminal")
        self.assertEqual(terminal["source_id"], "work/123")
        self.assertEqual(terminal["effects"]["result"]["ack"], "acknowledged")

    def test_cycle_journal_guard_refusal_retains_spent_preprojection_step(self):
        h, journal, state, closures = self.make()
        def changed(h, point, frame):
            if point == "before_step":
                frame.update(changed=True, reason="input_changed", trusted_expectation=None)
            return frame
        h.guard_transform = changed
        result = h.run()
        self.assertFalse(result["unresolved"])
        self.assertEqual(result["terminal_outcome"], "input_changed")
        self.assertEqual((h.ready_count, h.claim_count, h.worker_count), (0, 0, 0))
        self.assertEqual(result["counters"]["steps"], 1)
        self.assertEqual([e["event"] for e in journal._events], ["opened", "terminal", "closed"])

    def test_cycle_journal_unknown_effect_or_process_termination_never_closes(self):
        for point, reason in (("claim_applied", "claim_unknown"), ("worker", "launch_unknown"),
                              ("record_applied", "result_unknown"), ("process", "process_uncertain")):
            with self.subTest(point=point):
                h, journal, state, closures = self.make()
                if point == "process":
                    def uncertain(h, raw, token):
                        raw["status"] = "blocked"
                        raw["evidence"]["invocation_completed"] = False
                        return raw
                    h.worker_transform = uncertain
                else:
                    h.hooks[point] = lambda h: (_ for _ in ()).throw(OSError("synthetic unknown effect"))
                result = h.run()
                self.assertEqual(result["failure"], reason)
                self.assertTrue(result["unresolved"])
                self.assertEqual(journal._events[-1]["event"], "terminal")
                self.assertEqual(closures, {})
                self.assertNotIn("closed", [event["event"] for event in journal._events])
                orchestrator._decode_cycle_receipt(journal._raw)

    def test_cycle_journal_claim_not_acquired_spends_reservation_and_has_legal_receipt(self):
        # Blocked by the separately assigned accepted-A3 reset-placement repair.
        h, journal, state, closures = self.make(h=CycleAdapterHarness(max_claims=2))
        h.claim_none = True
        result = h.run()
        self.assertFalse(result["unresolved"])
        self.assertEqual(result["failure"], "budget_stop")
        self.assertEqual((h.claim_count, h.worker_count, h.record_count), (2, 0, 0))
        self.assertEqual([e["event"] for e in journal._events].count("claim_not_acquired"), 2)
        self.assertEqual(result["counters"]["claims_reserved"], 2)
        self.assertIsNotNone(result["closure_witness"])

    def test_cycle_journal_initialization_order_and_existing_directory_sync_are_explicit(self):
        import os
        from unittest.mock import patch
        h, journal, state, closures = self.make()
        real_sync = orchestrator.os.fsync
        seen = []
        def sync(fd):
            seen.append(os.readlink("/proc/self/fd/" + str(fd)))
            return real_sync(fd)
        with patch.object(orchestrator.os, "fsync", side_effect=sync): result = h.run()
        self.assertFalse(result["unresolved"])
        expected = [str(state.parent), str(state.parent.parent), str(state), str(state.parent),
                    str(state / "controller.lock"), str(state), str(state / ("b" * 32 + ".jsonl")), str(state)]
        self.assertEqual(seen[:8], expected)
        other, candidate, _, _ = self.make(directory=state.parent.parent, cycle="c" * 32, closures=closures)
        seen.clear()
        with patch.object(orchestrator.os, "fsync", side_effect=sync): result = other.run()
        self.assertFalse(result["unresolved"])
        expected[6] = str(state / ("c" * 32 + ".jsonl"))
        self.assertEqual(seen[:8], expected)

    def test_cycle_journal_refuses_invented_identity_or_progress_in_no_launch_settlement(self):
        h = CycleAdapterHarness()
        h.hooks["factory"] = lambda h: setattr(h, "cancelled", True)
        h.run()
        patches = h.events
        for target in ("result_acknowledged", "claim_settled"):
            with self.subTest(target=target):
                _, journal, _, _ = self.make(h=CycleAdapterHarness())
                for patch in patches:
                    if patch["event"] == target:
                        value = copy.deepcopy(patch)
                        if target == "result_acknowledged": value["invocation_id"] = "invented"
                        else: value["counters"]["observed_completed_roles"] = 1
                        before = journal._raw
                        with self.assertRaises(ValueError): journal.append(value)
                        self.assertEqual(journal._raw, before)
                        break
                    if patch["event"] == "opened": journal.acquire_and_open(patch)
                    else: journal.append(patch)

    def test_cycle_journal_missing_known_receipt_without_jobs_marker_refuses_new_effects(self):
        h, journal, state, closures = self.make()
        self.assertFalse(h.run()["unresolved"])
        receipt = state / (h.inputs["cycle_id"] + ".jsonl")
        receipt.unlink()  # Synthetic corruption; the journal supplies no deletion operation.
        self.assertFalse(any(state.glob("*.jobs")))
        held = copy.deepcopy(closures)
        other, candidate, _, _ = self.make(directory=state.parent.parent, cycle="c" * 32, closures=closures)
        result = other.run()
        self.assertTrue(result["unresolved"])
        self.assertEqual(result["failure"], "receipt_unknown")
        self.assertEqual((other.claim_count, other.worker_count, other.record_count), (0, 0, 0))
        self.assertFalse((state / ("c" * 32 + ".jsonl")).exists())
        self.assertEqual(closures, held)
        self.assertTrue(candidate._released)

    def test_cycle_journal_unrelated_queue_witnesses_do_not_require_local_receipts(self):
        unrelated = {("0" * 64, "a" * 32): "1" * 64}
        h, journal, state, closures = self.make(closures=unrelated)
        self.assertFalse(h.run()["unresolved"])
        other, candidate, _, _ = self.make(directory=state.parent.parent, cycle="c" * 32, closures=closures)
        self.assertFalse(other.run()["unresolved"])
        self.assertEqual(closures[("0" * 64, "a" * 32)], "1" * 64)
        self.assertTrue((state / ("b" * 32 + ".jsonl")).exists())
        self.assertTrue((state / ("c" * 32 + ".jsonl")).exists())

    def replay_prefix(self, h, source, target):
        clone = CycleAdapterHarness(ids=h.ids, **{key: h.inputs["limits"][key]
            for key in ("role_max", "max_roles", "max_claims", "max_steps")})
        _, journal, state, _ = self.make(h=clone)
        final_index = max(index for index, event in enumerate(source._events) if event["event"] == target)
        for event in source._events[:final_index + 1]:
            value = {key: copy.deepcopy(event[key]) for key in journal._PATCH}
            if value["event"] == "opened": journal.acquire_and_open(value)
            else: journal.append(value)
        return journal, state / (clone.inputs["cycle_id"] + ".jsonl")

    def test_cycle_journal_bad_integer_reservations_poison_before_any_write(self):
        cases = (("role_step", {"role_max": 1, "max_roles": 1}, "claim_settled"),
                 ("claim_step", {"role_max": 1, "max_claims": 1}, "claim_settled"),
                 ("undersized_launch", {"role_max": 5}, "claimed"),
                 ("claim_jump", {"role_max": 5}, "step_started"),
                 ("aborted_role_step", {"role_max": 1, "max_roles": 1}, "claim_settled"))
        for mode, limits, target in cases:
            with self.subTest(mode=mode):
                h, source, _, _ = self.make(h=CycleAdapterHarness(**limits))
                self.assertFalse(h.run()["unresolved"])
                journal, path = self.replay_prefix(h, source, target)
                value = {key: copy.deepcopy(journal._events[-1][key]) for key in journal._PATCH}
                if mode in {"role_step", "claim_step"}:
                    value.update(event="step_started", **dict.fromkeys(journal._IDENTITY), effects=journal._empty_effects())
                    value["counters"]["steps"] += 1
                elif mode == "undersized_launch":
                    value["event"] = "launch_intent"
                    value["counters"]["roles_reserved"] += 1  # Exact required allowance is five.
                    value["effects"]["launch"] = {"attempted": False, "ack": "pending"}
                elif mode == "claim_jump":
                    value.update(event="claim_intent", source_id="work/123", operation_id=h.rows["work/123"]["operation_id"])
                    value["counters"]["claims_reserved"] += 2
                    value["effects"]["claim"] = {"attempted": False, "ack": "pending"}
                else:
                    value.update(event="terminal", controller_reason="input_changed", terminal_outcome="input_changed")
                    value["counters"]["steps"] += 1
                before, acknowledged = path.read_bytes(), copy.deepcopy(journal._events)
                with self.assertRaises(ValueError): journal.append(value)
                self.assertTrue(journal._poisoned)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(journal._events, acknowledged)
                with self.assertRaises(ValueError): journal.append(value)
                self.assertEqual(path.read_bytes(), before)

    def test_cycle_journal_claim_admission_requires_remaining_role_capacity(self):
        # Independently exercise this defensive admission boundary with a typed
        # prior snapshot; a correct new step could not enter this exhausted state.
        previous = receipt_event(counters={"steps": 1, "claims_reserved": 0, "roles_reserved": 5, "observed_completed_roles": 0})
        previous["event"] = "step_started"
        current = copy.deepcopy(previous)
        current.update(event="claim_intent", operation_id="op", source_id="item-1")
        current["counters"]["claims_reserved"] = 1
        current["effects"]["claim"] = {"attempted": False, "ack": "pending"}
        with self.assertRaisesRegex(ValueError, "prior integer budget capacity"):
            orchestrator._CycleJournal._transition([previous], current)

    def test_cycle_journal_later_receipt_elapsed_does_not_reconstruct_admission_timing(self):
        h, journal, _, _ = self.make(h=CycleAdapterHarness(role_max=5))
        values = self.patches()
        journal.acquire_and_open(values[0])
        step = copy.deepcopy(values[1])
        step["elapsed_seconds"] = h.inputs["limits"]["cycle_seconds"] + 1
        journal.append(step)  # Reservation may precede a slow guard/receipt append.
        terminal = copy.deepcopy(step)
        terminal.update(event="terminal", controller_reason="deadline", terminal_outcome="cancelled")
        witness = journal.close(terminal)
        self.assertEqual(journal._events[-1]["event"], "closed")
        self.assertEqual(journal._events[-1]["elapsed_seconds"], step["elapsed_seconds"])
        self.assertEqual(witness[:2], (journal._owned["queue_key"], h.inputs["cycle_id"]))

    def test_cycle_journal_last_step_last_claim_and_exact_partial_launch_still_work(self):
        cases = ({"max_steps": 1, "max_claims": 1, "role_max": 1},
                 {"max_steps": 2, "max_claims": 2, "max_roles": 4, "role_max": 3})
        for limits in cases:
            with self.subTest(limits=limits):
                h, journal, _, _ = self.make(h=CycleAdapterHarness(**limits))
                result = h.run()
                self.assertFalse(result["unresolved"])
                self.assertEqual(result["failure"], "budget_stop")
                self.assertEqual(h.allowances, [3, 1] if limits.get("max_roles") == 4 else [1])
                self.assertEqual((h.claim_count, h.worker_count, h.record_count), (len(h.allowances),) * 3)
                self.assertIsNotNone(result["closure_witness"])
                self.assertEqual(journal._events[-1]["counters"], result["counters"])

    def test_cycle_journal_unclosed_truncated_forged_or_changed_history_is_never_recovery(self):
        for kind in ("unclosed", "truncated", "changed", "noncanonical", "missing"):
            with self.subTest(kind=kind):
                h, journal, state, closures = self.make()
                self.assertFalse(h.run()["unresolved"])
                receipt = state / (h.inputs["cycle_id"] + ".jsonl")
                raw = receipt.read_bytes()
                if kind == "unclosed": receipt.write_bytes(b"".join(raw.splitlines(keepends=True)[:-1]))
                elif kind == "truncated": receipt.write_bytes(raw[:-1])
                elif kind == "changed": receipt.write_bytes(raw.replace(b'"completed"', b'"no_work"'))
                elif kind == "noncanonical": receipt.write_bytes(raw.replace(b'"kind":', b'"kind": '))
                else:
                    receipt.unlink()
                    (state / ("b" * 32 + ".jobs")).mkdir()
                other, candidate, _, _ = self.make(directory=state.parent.parent, cycle="c" * 32, closures=closures)
                result = other.run()
                self.assertTrue(result["unresolved"])
                self.assertEqual((other.claim_count, other.worker_count), (0, 0))
                self.assertFalse((state / ("c" * 32 + ".jsonl")).exists())


class InputGuardFixture:
    """Temporary real repositories and accepted provider/workflow artifacts."""
    def __init__(self, case, *, source_id="work/123"):
        import tempfile
        import atlas_workflows
        self.case = case
        self.temporary = tempfile.TemporaryDirectory()
        case.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime, self.execution = self.root / "runtime", self.root / "execution"
        self.inputs_root = self.root / "inputs"
        self.runtime.mkdir(); self.execution.mkdir(); self.inputs_root.mkdir()
        for checkout in (self.runtime, self.execution):
            self.git(checkout, "init", "-q")
        implementation = self.runtime / "templates/local-automation-runtime"
        implementation.mkdir(parents=True)
        (implementation / "runtime.py").write_text("runtime implementation\n")
        for name in ("a.txt", "b.txt", "outside.txt"):
            (self.execution / name).write_text(name + " baseline\n")
        self.commit(self.runtime); self.commit(self.execution)
        self.queue = self.root / "queue.json"
        self.pins_path = self.root / "pins.json"
        self.plan, self.spec, self.config = [self.inputs_root / name for name in ("plan.md", "spec.md", "commands.json")]
        self.plan.write_text("source plan\n"); self.spec.write_text("source specification\n")
        self.config.write_text('{"commands": {"default": ["synthetic-never-executed"]}}\n')
        self.templates = self.inputs_root / "templates"; self.templates.mkdir()
        self.template_path = self.templates / "lifecycle.json"
        self.template_value = json.loads((ROOT / "team-templates/work-item-change-lifecycle.json").read_text())
        self.template_path.write_text(json.dumps(self.template_value))
        self.agent_root = self.inputs_root / "instructions"
        self.instructions = []
        for name in ("test-engineer", "code-reviewer"):
            path = self.agent_root / "agents" / (name + ".md")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("---\nname: " + name + "\n---\n" + name + " instructions\n")
            self.instructions.append(path)
        self.registry = self.inputs_root / "registry.json"
        self.registry_value = {"agents": {name: {"source": "", "description": name} for name in
            ("implementation", "semantic-alignment", "evidence-rollup")}}
        self.registry.write_text(json.dumps(self.registry_value))
        self.source_id = source_id
        self.item = {"id": source_id, "operation_id": "operation:" + source_id, "title": "Synthetic scoped change",
            "status": "ready", "goal": "Update the scoped file with useful evidence.",
            "spec_path": str(self.spec), "spec_hash": self.sha(self.spec),
            "scheduler": {"execution_repo": str(self.execution), "base_branch": "main", "write_scope": ["a.txt"],
                "workflow_kind": "work-item", "team_template": "work-item-change-lifecycle"},
            "metadata": {"acceptance_criteria": ["The change has concrete verification."],
                "source_plan": {"path": str(self.plan), "hash": self.sha(self.plan)}}}
        self.payload = {"version": 1, "work_items": [self.item]}
        self.write_queue()
        self.pins = {"schema_version": 1, "kind": "atlas-local-supervisor-pins", "queue_path": str(self.queue),
            "runtime": {"checkout_path": str(self.runtime), "head": self.head(self.runtime)},
            "execution_checkouts": [{"checkout_path": str(self.execution), "head": self.head(self.execution), "entry_changes": []}],
            "inputs": [], "template_source": {"mode": "directory", "path": str(self.templates), "candidates": [str(self.template_path)]},
            "admitted_item_ids": [source_id], "item_closure": []}
        self.extra_inputs = []
        self.repin()
        self.store = orchestrator.atlas_work_items.AtlasWorkItemStore(self.queue)
        self.provider = orchestrator.atlas_work_items.AtlasWorkItemOperationProvider(self.store, claimed_by="synthetic-input-guard")

    def git(self, checkout, *args):
        return orchestrator._cycle_guard_git(str(checkout), "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", *args)

    def commit(self, checkout):
        self.git(checkout, "add", ".")
        self.git(checkout, "commit", "-qm", "synthetic baseline")

    def head(self, checkout):
        return self.git(checkout, "rev-parse", "HEAD").decode().strip()

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_queue(self):
        self.queue.write_text(json.dumps(self.payload))

    def reload(self):
        self.payload = json.loads(self.queue.read_text())
        self.item = self.payload["work_items"][0]

    def repin(self):
        rows = [("plan", self.plan), ("spec", self.spec), ("role_command_config", self.config),
                ("team_template", self.template_path)]
        if self.registry is not None:
            rows.append(("registry", self.registry))
        rows.extend(("agent_instruction", path) for path in self.instructions)
        rows.extend(self.extra_inputs)
        self.pins["inputs"] = sorted([{"kind": kind, "path": str(path), "sha256": self.sha(path)} for kind, path in rows], key=lambda row: row["path"])
        closure = []
        by_id = {orchestrator.atlas_work_items.item_id(item): item for item in self.payload["work_items"]}
        for source_id in sorted(by_id):
            item = by_id[source_id]
            operation = orchestrator._cycle_guard_project(item, by_id)
            scheduler = item.get("scheduler", {})
            deps = sorted(set(orchestrator.atlas_work_items.list_value(scheduler.get("depends_on") or item.get("depends_on"))))
            closure.append({"item_id": source_id, "operation_id": operation["operation_id"],
                "execution_checkout": operation["execution_repo"], "depends_on": deps,
                "immutable_sha256": orchestrator.atlas_work_items.content_hash(orchestrator._cycle_guard_immutable(operation, deps))})
        self.pins["item_closure"] = closure
        self.write_pins()

    def write_pins(self):
        raw = (json.dumps(self.pins, indent=2) + "\n").encode()
        self.pins_path.write_bytes(raw)
        self.pins = orchestrator._decode_cycle_pins(raw)
        self.frozen = {"pins_path": str(self.pins_path), "pins_raw_sha256": hashlib.sha256(raw).hexdigest(),
            "cycle_id": "a" * 32, "source_snapshot": None, "progress_by_item": {}}

    @property
    def jobs(self):
        key = hashlib.sha256(str(self.queue).encode()).hexdigest()
        return self.queue.parent / ".atlas-supervisor" / key / (self.frozen["cycle_id"] + ".jobs")

    def observe(self, checkpoint="entry", operation=None):
        return orchestrator._observe_cycle_inputs(self.pins, self.frozen, checkpoint, operation)

    def operation(self):
        self.reload()
        return self.provider.project(self.item, {orchestrator.atlas_work_items.item_id(row): row for row in self.payload["work_items"]})

    def selectors(self):
        import atlas_workflows
        templates = atlas_workflows.load_team_templates(self.templates)
        registry = atlas_workflows.load_agent_registry(self.registry) if self.registry else None
        return orchestrator._cycle_guard_selectors(self.pins, templates, registry)

    def worker(self):
        selected = self.selectors()
        return orchestrator.atlas_work_items.LocalCommandOperationWorker(None, jobs_dir=self.jobs,
            templates_dir=selected["templates_dir"], agent_registry_path=selected["agent_registry_path"], agent_root=selected["agent_root"])

    def stage(self, operation, role_number, *, invocation=None, job_dir=None):
        import atlas_workflows
        invocation = invocation or format(role_number + 1, "032x")
        worker = self.worker()
        job_dir = job_dir or self.jobs / ("atlas-work-item-" + orchestrator.atlas_work_items.safe_id(operation.source_id) + "-" + invocation)
        job_dir.mkdir(parents=True)
        evidence = worker.write_workflow_artifacts(operation, job_dir, invocation, self.queue)
        self.case.assertNotIn("workflow_error", evidence)
        template = atlas_workflows.load_team_template(self.template_path)
        role = template.roles[role_number]
        review = {"verdict": "pass", "reason": "Scoped implementation matches every stated acceptance condition.",
                  "evidence": ["Inspected the implementation and focused verification output."]} if role.goal_gate else None
        result = atlas_workflows.TeamRunRoleResult(role.id, "complete", {key: "Substantive " + key for key in role.must_produce},
            evidence=["Synthetic focused verification passed."], goal_review=review)
        results_path = job_dir / "team-role-results.json"
        results_path.write_text(json.dumps([result.to_dict()]))
        evidence = worker.apply_workflow_role_results(evidence, results_path)
        self.case.assertNotIn("workflow_result_error", evidence)
        status = "done" if evidence["team_run_status"] == "complete" else "ready"
        if status == "ready":
            evidence["workflow_continuation"] = {"reason": "required workflow outputs remain incomplete", "next_status": "ready"}
        return orchestrator.atlas_work_items.OperationResult(status, 0, "Synthetic role completed", evidence | {
            "process_invocation_id": invocation, "invocation_completed": True, "termination_proved": True})

    def settle(self, operation, result):
        self.provider.record_result(operation, result)
        self.reload()
        self.case.assertEqual(self.item["result"], result.to_dict())
        self.frozen["progress_by_item"][operation.source_id] = {"run_id": result.evidence["team_run"]["run_id"],
            "completed_roles": sorted(result.evidence["completed_roles"])}

    def declared_resume(self, *, complete=False):
        import atlas_workflows
        template = atlas_workflows.load_team_template(self.template_path)
        operation = self.operation()
        run = atlas_workflows.TeamRun.start(run_id="preexisting-logical-run", template=template, work_item_id=self.source_id)
        count = len(template.roles) if complete else 1
        for role in template.roles[:count]:
            review = {"verdict": "pass", "reason": "All intended requirements and checks are satisfied.",
                "evidence": ["Reviewed implementation and tests against the specification."]} if role.goal_gate else None
            run.record_role_result(atlas_workflows.TeamRunRoleResult(role.id, "complete", {name: "accepted " + name for name in role.must_produce}, goal_review=review))
        run.refresh_status(template)
        path = self.execution / "resume.json"
        atlas_workflows.save_team_run(path, run)
        self.git(self.execution, "add", "resume.json"); self.git(self.execution, "commit", "-qm", "declared resume")
        self.pins["execution_checkouts"][0]["head"] = self.head(self.execution)
        expected = orchestrator._cycle_guard_expected(operation.to_dict(), template)
        self.item["workflow_runs"] = [{"contract_hash": expected["contract_hash"], "rework_count": 0,
            "team_run": atlas_workflows.team_run_summary(template, run), "artifacts": {"team_run_path": str(path)}}]
        self.write_queue()
        self.extra_inputs.append(("entry_file", path)); self.repin()
        return path


class RecoveryTrustTests(unittest.TestCase):
    class Cancellation:
        def __init__(self): self.stopped, self.error = False, None
        def is_set(self):
            if self.error: raise self.error
            return self.stopped

    def fixture(self, *, stages=0, qualified=True, second=False, dependency=False, terminal=False, no_launch=False, baseline_complete=False):
        f = InputGuardFixture(self)
        if qualified:
            f.item["metadata"]["local_execution_v1"] = {"policy_id": "local-luna-unit-v1", "role_purposes": {
                "implementation": "implementation", "test-runner": "validation", "code-review": "review",
                "semantic-alignment": "goal-review", "evidence-rollup": "review"}, "changed_interfaces": ["Scoped file"],
                "unresolved_questions": [], "complexity_flags": []}
        if second or dependency:
            other = copy.deepcopy(f.item)
            other.update(id="other", operation_id="operation:other", title="Other synthetic item")
            f.payload["work_items"].append(other)
            if dependency:
                other["status"] = "done"
                f.item["scheduler"]["depends_on"] = ["other"]
        if second:
            f.pins["admitted_item_ids"] = sorted([f.source_id, "other"])
        f.write_queue(); f.repin()
        if baseline_complete:
            f.declared_resume(complete=True)
        self.assertFalse(f.observe()["changed"])
        snapshot = copy.deepcopy(f.frozen["source_snapshot"])
        first = receipt_event()
        first.update(queue_path=str(f.queue), queue_key=hashlib.sha256(str(f.queue).encode()).hexdigest(), cycle_id=f.frozen["cycle_id"],
                     pins_sha256=f.frozen["pins_raw_sha256"], admitted_fingerprints={sid: row["immutable_sha256"] for row in f.pins["item_closure"] for sid in f.pins["admitted_item_ids"] if sid == row["item_id"]})
        first["limits"].update(max_steps=8, max_claims=8, max_roles=8, role_max=1, cycle_seconds=60, stop_file=str(f.root / "stop"))
        origin = {"boot_id": "12345678-1234-1234-1234-123456789abc", "entry_monotonic": 100.0, "pins_path": str(f.pins_path)}
        journal = orchestrator._RecoverableCycleJournal(str(f.queue), f.pins, f.frozen["pins_raw_sha256"], first["limits"],
            cycle_id=f.frozen["cycle_id"], acknowledged_closures={}, controller_epoch="d" * 32, origin=origin)
        self.addCleanup(journal.release)
        patch = {key: copy.deepcopy(first[key]) for key in orchestrator._CycleJournal._PATCH} | {"recovery_state": None}
        journal.acquire_and_open(patch)
        capsule = {"source_snapshot": snapshot, "progress_by_item": copy.deepcopy(f.frozen["progress_by_item"]), "done_ids": [],
            "cancellation": {"cancelled": False, "cancel_reason": None}, "jobs_identity": None,
            "disposition": {"action": "continue", "reason": None, "outcome": None}, "settlement": None}
        journal.initialize_jobs_and_ready(patch | {"event": "recovery_ready", "recovery_state": capsule})
        def emit(name, **updates):
            row = {key: copy.deepcopy(journal._events[-1][key]) for key in journal._PATCH}
            row.update(event=name, elapsed_seconds=len(journal._events) / 10, recovery_state=None)
            row.update(updates); journal.append(row)
        targets = [(f.source_id, index) for index in range(stages or int(no_launch))] + ([("other", 0)] if second and stages else [])
        for ordinal, (sid, role) in enumerate(targets):
            f.reload()
            by_id = {item["id"]: item for item in f.payload["work_items"]}
            selected = f.provider.project(by_id[sid], by_id)
            expected = f.observe("before_claim", selected.to_dict())["trusted_expectation"]
            count = journal._events[-1]["counters"]
            emit("step_reserved", counters=count | {"steps": count["steps"] + 1})
            emit("step_started", **dict.fromkeys(journal._IDENTITY), effects=journal._empty_effects())
            effects = journal._empty_effects(); effects["claim"] = {"attempted": False, "ack": "pending"}
            emit("claim_intent", operation_id=selected.operation_id, source_id=sid, effects=effects,
                 counters=journal._events[-1]["counters"] | {"claims_reserved": count["claims_reserved"] + 1})
            held = f.provider.claim(selected)
            self.assertIsNotNone(held)
            f.reload(); item = next(item for item in f.payload["work_items"] if item["id"] == sid)
            claim = copy.deepcopy(item["claim"])
            effects["claim"] = {"attempted": True, "ack": "acknowledged"}
            emit("claimed", claim_key=orchestrator.atlas_work_items.content_hash(claim), effects=copy.deepcopy(effects))
            if no_launch:
                returned = orchestrator.atlas_work_items.OperationResult("blocked", 125,
                    "Bounded supervisor did not launch this held claim.", {"supervisor_no_launch": True})
            else:
                effects["launch"] = {"attempted": False, "ack": "pending"}
                emit("launch_intent", counters=journal._events[-1]["counters"] | {"roles_reserved": count["roles_reserved"] + 1}, effects=copy.deepcopy(effects))
                invocation = format(ordinal + 1, "032x")
                returned = f.stage(held, role, invocation=invocation)
                job = f.jobs / ("atlas-work-item-" + orchestrator.atlas_work_items.safe_id(sid) + "-" + invocation)
                returned.evidence.update(job_dir=str(job), operation_path=str(job / "operation.json"), output_path=str(job / "worker-output.txt"))
                command = [str(f.runtime / "templates/local-automation-runtime/atlas-agent-role-runner"), "--command-config", str(f.config), "--max-roles", "1"]
                item["process_uncertainty"] = {"status": "unresolved", "invocation_id": invocation, "job_dir": str(job),
                    "command_sha256": hashlib.sha256(json.dumps(command).encode()).hexdigest(), "started_at": "2026-10-16T00:00:00Z"}
                f.write_queue()
            f.provider.record_result(held, returned)
            f.reload()
            original = returned.to_dict(); digest = orchestrator.atlas_work_items.content_hash(original)
            if not no_launch:
                effects["launch"] = {"attempted": True, "ack": "acknowledged"}
                emit("worker_returned", invocation_id=invocation, result_sha256=digest, effects=copy.deepcopy(effects))
            effects["result"] = {"attempted": False, "ack": "pending"}
            emit("result_intent", result_sha256=digest, effects=copy.deepcopy(effects))
            effects["result"] = {"attempted": True, "ack": "acknowledged"}
            emit("result_acknowledged", effects=copy.deepcopy(effects))
            assessment = ({"decision": "stop", "reason": None, "new_completed_roles": []} if no_launch
                          else orchestrator._bounded_result_assessment(original, expected))
            if not no_launch:
                self.assertIn(assessment["decision"], {"continue_candidate", "done_candidate"})
                f.frozen["progress_by_item"][sid] = {"run_id": original["evidence"]["team_run"]["run_id"], "completed_roles": sorted(original["evidence"]["completed_roles"])}
            capsule = copy.deepcopy(journal._events[1]["recovery_state"])
            capsule.update(progress_by_item=copy.deepcopy(f.frozen["progress_by_item"]), settlement={"result": original, "claim": claim,
                "trusted_expectation": expected, "assessment": assessment}, disposition={"action": "done" if assessment["decision"] == "done_candidate" else "continue", "reason": None, "outcome": None})
            if no_launch:
                capsule["disposition"] = {"action": "halt", "reason": "blocked", "outcome": "blocked"}
            capsule["done_ids"] = sorted(source for source, progress in capsule["progress_by_item"].items() if len(progress["completed_roles"]) == 5)
            emit("claim_settled", recovery_state=capsule, stored_result_sha256=digest,
                 counters=journal._events[-1]["counters"] | {"observed_completed_roles": count["observed_completed_roles"] + len(assessment["new_completed_roles"])})
        if terminal:
            row = {key: copy.deepcopy(journal._events[-1][key]) for key in journal._PATCH}
            row.update(event="terminal", controller_reason="completed" if stages == 5 else "budget_stop", terminal_outcome="completed" if stages == 5 else "budget_stop")
            row["recovery_state"]["disposition"] = {"action": "halt", "reason": row["controller_reason"], "outcome": row["terminal_outcome"]}
            journal.close(row)
        journal.release()
        live = {key: copy.deepcopy(f.frozen[key]) for key in ("pins_path", "pins_raw_sha256", "cycle_id")}
        live.update(source_snapshot=None, progress_by_item={})
        return f, self.reopen(f), live

    def reopen(self, f):
        owner = orchestrator._RecoverableCycleJournal.acquire_for_recovery(str(f.queue), f.frozen["cycle_id"])
        self.addCleanup(owner.release)
        journal = orchestrator._RecoverableCycleJournal.from_recovery_candidate(owner, f.pins, f.frozen["pins_raw_sha256"],
            owner.snapshot()["tail"]["limits"], controller_epoch="e" * 32, acknowledged_closures={})
        self.addCleanup(journal.release)
        return journal

    def validate(self, f, journal, live, *, monotonic=None, cancellation=None, boot_id=None):
        return orchestrator._admit_cycle_recovery(f.pins, live, journal=journal,
            boot_id=boot_id or "12345678-1234-1234-1234-123456789abc", monotonic=monotonic or (lambda: 120.0),
            cancellation=cancellation or self.Cancellation())

    def rewrite(self, f, journal, mutation):
        journal.release()
        receipt = f.jobs.parent / (f.frozen["cycle_id"] + ".jsonl")
        events = orchestrator._decode_cycle_receipt_v2(receipt.read_bytes())
        mutation(events)
        receipt.write_bytes(b"".join(orchestrator._CycleJournal._line(row) for row in events))
        return self.reopen(f)

    def test_recovery_trust_ready_seed_is_sealed_and_requires_this_process_ack_then_one_consume(self):
        f, journal, live = self.fixture()
        before, raw = copy.deepcopy(live), journal._raw
        validated = self.validate(f, journal, live)
        self.assertEqual(validated["status"], "continuation_candidate", validated)
        self.assertTrue(validated["observation"]["validated"])
        seed = validated["seed"]
        self.assertIs(type(seed._payload), bytes)
        self.assertEqual(live, before); self.assertEqual(journal._raw, raw)
        with self.assertRaises(ValueError): orchestrator._recovery_seed_state(seed, journal=journal)
        first_patch = seed.admission_patch(elapsed_seconds=21)
        first_patch["counters"]["steps"] = 99
        patch = seed.admission_patch(elapsed_seconds=21)
        self.assertEqual(patch["counters"]["steps"], 0)
        journal.acknowledge_recovery(patch, expected_prefix_sha256=validated["observation"]["prefix_sha256"])
        state = orchestrator._recovery_seed_state(seed, journal=journal)
        self.assertEqual(state["elapsed_seconds"], 21)
        self.assertEqual(state["tail_patch"]["event"], "recovery_admitted")
        state["frozen"]["progress_by_item"][f.source_id]["completed_roles"].append("tampered")
        state = orchestrator._recovery_seed_state(seed, journal=journal)
        self.assertEqual(state["frozen"]["progress_by_item"][f.source_id]["completed_roles"], [])
        inputs = {key: copy.deepcopy(state[key]) for key in ("queue_path", "pins_path", "pins_raw_sha256", "cycle_id", "limits", "admitted_item_ids")}
        inputs.update(entry_monotonic=state["origin"]["entry_monotonic"], progress_by_item=copy.deepcopy(state["frozen"]["progress_by_item"]))
        with self.assertRaises(ValueError): orchestrator._consume_recovery_seed(seed, inputs | {"entry_monotonic": 0}, journal=journal)
        self.assertEqual(orchestrator._consume_recovery_seed(seed, inputs, journal=journal)["counters"]["steps"], 0)
        with self.assertRaises(ValueError): orchestrator._consume_recovery_seed(seed, inputs, journal=journal)
        self.assertEqual(live, before)

    def test_recovery_trust_settled_roles_keep_logical_run_across_invocation_paths_without_marker_pid(self):
        from unittest.mock import patch
        f, journal, live = self.fixture(stages=2)
        self.assertNotIn("pid", f.item["process_uncertainty"])
        with patch.object(orchestrator.atlas_work_items, "workflow_run_record", side_effect=AssertionError("not pure")):
            validated = self.validate(f, journal, live)
        self.assertEqual(validated["status"], "continuation_candidate", validated)
        self.assertEqual(validated["observation"]["counters"]["observed_completed_roles"], 2)
        self.assertEqual(len(validated["observation"]["progress_by_item"][f.source_id]["completed_roles"]), 2)
        settlements = [row for row in journal._events if row["event"] == "claim_settled"]
        self.assertNotEqual(settlements[0]["invocation_id"], settlements[1]["invocation_id"])
        self.assertEqual(settlements[0]["recovery_state"]["progress_by_item"][f.source_id]["run_id"], settlements[1]["recovery_state"]["progress_by_item"][f.source_id]["run_id"])

    def test_recovery_trust_each_items_latest_settlement_is_required(self):
        f, journal, live = self.fixture(stages=1, second=True)
        validation = self.validate(f, journal, live)
        self.assertEqual(validation["status"], "continuation_candidate", validation)
        sealed = orchestrator._cycle_guard_json(validation["seed"]._payload)
        self.assertEqual(set(sealed["settlement_bindings"]), {f.source_id, "other"})
        self.assertNotEqual(sealed["settlement_bindings"][f.source_id]["invocation_id"], sealed["settlement_bindings"]["other"]["invocation_id"])
        f.reload(); f.payload["work_items"][0]["result"]["summary"] = "changed first item"
        f.write_queue()
        refused = self.validate(f, journal, live)
        self.assertEqual(refused["status"], "reconciliation_required")
        self.assertIsNone(refused["seed"])
        self.assertIn("latest settlement", refused["reason"])

    def test_recovery_trust_baseline_pin_bindings_refuse_before_guard(self):
        from unittest.mock import patch
        mutations = [lambda s: s["input_digests"].update({"/extra": "f" * 64}),
            lambda s: s.update(template_candidates=sorted(s["template_candidates"] + [next(path for path in s["input_digests"] if path not in s["template_candidates"])])),
            lambda s: s.update(runtime_head="f" * 40), lambda s: s["execution_heads"].update({next(iter(s["execution_heads"])): "f" * 40}),
            lambda s: s["entry_changes"][next(iter(s["entry_changes"]))].append({"path": "outside.txt", "index_sha256": "a" * 64,
                "worktree_sha256": "b" * 64, "index_state": "unchanged", "worktree_state": "modified"})]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                f, journal, live = self.fixture()
                def change(events):
                    for row in events:
                        if row["recovery_state"] is not None: mutate(row["recovery_state"]["source_snapshot"])
                journal = self.rewrite(f, journal, change)
                before = copy.deepcopy(live)
                with patch.object(orchestrator, "_observe_cycle_inputs", side_effect=AssertionError("guard consumed unbound baseline")):
                    refused = self.validate(f, journal, live)
                self.assertEqual(refused["status"], "reconciliation_required")
                self.assertIn("original pins", refused["reason"])
                self.assertEqual(live, before)
        f, journal, live = self.fixture(dependency=True)
        def change(events):
            for row in events:
                if row["recovery_state"] is not None: row["recovery_state"]["source_snapshot"]["immutable_inputs"]["other"]["title"] = "repinned dependency"
        journal = self.rewrite(f, journal, change)
        with patch.object(orchestrator, "_observe_cycle_inputs", side_effect=AssertionError("unbound closure")):
            refused = self.validate(f, journal, live)
        self.assertIn("closure fingerprint", refused["reason"])

    def test_recovery_trust_original_pins_path_and_explicit_routing_cannot_be_replaced(self):
        from unittest.mock import patch
        f, journal, live = self.fixture()
        alternate = f.root / "equal-copy.json"; alternate.write_bytes(f.pins_path.read_bytes())
        changed = copy.deepcopy(live); changed["pins_path"] = str(alternate)
        real_read, reads = orchestrator._cycle_guard_read, []
        def read(path):
            reads.append(path)
            self.assertNotEqual(path, str(alternate))
            return real_read(path)
        with patch.object(orchestrator, "_cycle_guard_read", side_effect=read): refused = self.validate(f, journal, changed)
        self.assertEqual(refused["status"], "reconciliation_required")
        self.assertEqual(reads, [])
        f, journal, live = self.fixture(qualified=False)
        with patch.object(orchestrator, "_observe_cycle_inputs", side_effect=AssertionError("unqualified guard")):
            refused = self.validate(f, journal, live)
        self.assertIn("qualified explicit", refused["reason"])

    def test_recovery_trust_current_source_scope_template_and_pins_drift_never_install(self):
        for kind in ("spec", "registry", "candidate", "scope", "head", "pins"):
            with self.subTest(kind=kind):
                f, journal, live = self.fixture()
                if kind == "spec": f.spec.write_text("changed source")
                elif kind == "registry": f.registry.write_text('{}')
                elif kind == "candidate": (f.templates / "new.json").write_text('{}')
                elif kind == "scope": (f.execution / "outside.txt").write_text("outside scope")
                elif kind == "head":
                    (f.execution / "a.txt").write_text("changed head"); f.commit(f.execution)
                else: f.pins_path.write_bytes(f.pins_path.read_bytes() + b" ")
                before = copy.deepcopy(live)
                refused = self.validate(f, journal, live)
                self.assertEqual(refused["status"], "reconciliation_required")
                self.assertIsNone(refused["seed"]); self.assertEqual(live, before)
        f, journal, live = self.fixture(stages=1)
        (f.execution / "a.txt").write_text("valid in-scope worker change")
        self.assertEqual(self.validate(f, journal, live)["status"], "continuation_candidate")

    def test_recovery_trust_result_claim_and_resolved_marker_must_match_latest_item(self):
        for kind in ("result", "claim", "marker_missing", "marker_invocation", "marker_job", "marker_command", "marker_resolved", "metadata"):
            with self.subTest(kind=kind):
                f, journal, live = self.fixture(stages=1)
                f.reload()
                if kind == "result": f.item["result"]["summary"] = "changed"
                elif kind == "claim": f.item["previous_claims"].append({"unrelated": "claim"})
                elif kind == "marker_missing": f.item.pop("process_uncertainty")
                elif kind == "marker_invocation": f.item["process_uncertainty"]["invocation_id"] = "f" * 32
                elif kind == "marker_job": f.item["process_uncertainty"]["job_dir"] = "/foreign"
                elif kind == "marker_command": f.item["process_uncertainty"]["command_sha256"] = "f" * 64
                elif kind == "marker_resolved": f.item["process_uncertainty"]["status"] = "unresolved"
                else: f.item["workflow_runs"][-1]["goal_acceptance"] = {}
                f.write_queue()
                refused = self.validate(f, journal, live)
                self.assertEqual(refused["status"], "reconciliation_required")
                self.assertIsNone(refused["seed"])

    def test_recovery_trust_foreign_invocation_path_refuses_before_any_target_probe(self):
        from unittest.mock import patch
        f, journal, live = self.fixture(stages=1)
        f.reload()
        old = f.item["result"]["evidence"]["team_run_path"]
        foreign = old.replace("00000000000000000000000000000001", "f" * 32)
        f.item["result"]["evidence"]["team_run_path"] = foreign
        f.item["workflow_runs"][-1]["artifacts"]["team_run_path"] = foreign
        changed_result = copy.deepcopy(f.item["result"]); f.write_queue()
        def change(events):
            digest = orchestrator.atlas_work_items.content_hash(changed_result)
            for row in events:
                if row["result_sha256"] is not None: row["result_sha256"] = digest
                if row["stored_result_sha256"] is not None: row["stored_result_sha256"] = digest
                if row["event"] == "claim_settled": row["recovery_state"]["settlement"]["result"] = changed_result
        journal = self.rewrite(f, journal, change)
        real_read, reads = orchestrator._cycle_guard_read, []
        def read(path):
            reads.append(path)
            self.assertNotEqual(path, foreign, "foreign invocation target was probed")
            return real_read(path)
        with patch.object(orchestrator, "_cycle_guard_read", side_effect=read): refused = self.validate(f, journal, live)
        self.assertIn("exact invocation", refused["reason"])
        self.assertNotIn(foreign, reads)

    def test_recovery_trust_loaded_run_outputs_rollup_and_links_are_verified(self):
        import os
        for kind in ("source_id", "output", "rollup", "link"):
            with self.subTest(kind=kind):
                f, journal, live = self.fixture(stages=1)
                artifact = Path(f.item["result"]["evidence"]["team_run_path"])
                if kind == "rollup": Path(f.item["result"]["evidence"]["team_rollup_path"]).write_text("changed rollup")
                elif kind == "link":
                    backup = f.root / "run.json"; artifact.rename(backup); os.symlink(backup, artifact)
                else:
                    value = json.loads(artifact.read_text())
                    if kind == "source_id": value["work_item_id"] = "other"
                    else: value["role_results"]["implementation"]["outputs"] = {}
                    artifact.write_text(json.dumps(value))
                self.assertEqual(self.validate(f, journal, live)["status"], "reconciliation_required")

    def test_recovery_trust_deadline_stop_and_terminal_return_validated_observations_only(self):
        for kind in ("deadline", "stop", "inspection", "terminal"):
            with self.subTest(kind=kind):
                f, journal, live = self.fixture(stages=5 if kind == "terminal" else 0, terminal=kind == "terminal")
                cancellation = self.Cancellation()
                if kind == "stop": cancellation.stopped = True
                elif kind == "inspection": cancellation.error = OSError("stop inspection failed")
                readings = iter([120, 160 if kind == "deadline" else 120])
                raw = journal._raw
                observed = self.validate(f, journal, live, monotonic=lambda: next(readings), cancellation=cancellation)
                self.assertEqual(observed["status"], "report_only", observed)
                self.assertTrue(observed["observation"]["validated"])
                self.assertIsNone(observed["seed"])
                self.assertEqual(journal._raw, raw); self.assertEqual(journal._closures, {})
                self.assertIsNone(journal.recovery_evidence()["local_recovery_ack"])

    def test_recovery_trust_unsafe_frontier_clock_and_all_queue_blockers_never_produce_seed(self):
        for kind in ("unsafe", "boot", "backward", "nan", "clock_error", "active", "uncertain", "duplicate"):
            with self.subTest(kind=kind):
                f, journal, live = self.fixture()
                if kind == "unsafe":
                    def change(events): recovery_protocol_append(events, "step_reserved", counters=events[-1]["counters"] | {"steps": 1})
                    journal = self.rewrite(f, journal, change)
                elif kind in {"active", "uncertain", "duplicate"}:
                    f.reload()
                    f.payload["work_items"].append(copy.deepcopy(f.item) if kind == "duplicate" else {"id": "unrelated", "status": "running" if kind == "active" else "blocked", **({"process_uncertainty": {"status": "unresolved"}} if kind == "uncertain" else {})})
                    f.write_queue()
                readings = iter([120, 119])
                def clock_error(): raise RuntimeError("clock unavailable")
                observed = self.validate(f, journal, live, boot_id="other" if kind == "boot" else None,
                    monotonic=clock_error if kind == "clock_error" else (lambda: float("nan")) if kind == "nan" else (lambda: next(readings)) if kind == "backward" else None)
                self.assertEqual(observed["status"], "reconciliation_required", observed)
                self.assertIsNone(observed["seed"])

    def test_recovery_trust_lost_ack_released_foreign_and_loaded_ack_cannot_install_seed(self):
        from unittest.mock import patch
        f, journal, live = self.fixture()
        validated = self.validate(f, journal, live); seed = validated["seed"]
        self.assertIsNotNone(seed, validated)
        with patch.object(orchestrator.os, "getpid", return_value=seed._pid + 1):
            with self.assertRaises(ValueError): seed.admission_patch(elapsed_seconds=21)
        with patch.object(orchestrator.os, "fsync", side_effect=OSError("lost acknowledgment")):
            with self.assertRaises(OSError): journal.acknowledge_recovery(seed.admission_patch(elapsed_seconds=21), expected_prefix_sha256=validated["observation"]["prefix_sha256"])
        with self.assertRaises(ValueError): orchestrator._recovery_seed_state(seed, journal=journal)
        journal.release()
        owner = orchestrator._RecoverableCycleJournal.acquire_for_recovery(str(f.queue), f.frozen["cycle_id"])
        self.addCleanup(owner.release)
        loaded = orchestrator._RecoverableCycleJournal.from_recovery_candidate(owner, f.pins, live["pins_raw_sha256"], owner.snapshot()["tail"]["limits"], controller_epoch="f" * 32, acknowledged_closures={})
        self.addCleanup(loaded.release)
        self.assertIsNone(loaded.recovery_evidence()["local_recovery_ack"])
        with self.assertRaises(ValueError): orchestrator._recovery_seed_state(seed, journal=loaded)
        self.assertIsNone(live["source_snapshot"]); self.assertEqual(live["progress_by_item"], {})



    def test_recovery_trust_complete_baseline_is_uncharged_and_no_launch_halt_needs_no_marker(self):
        f, journal, live = self.fixture(second=True, baseline_complete=True)
        validated = self.validate(f, journal, live)
        self.assertEqual(validated["status"], "continuation_candidate", validated)
        self.assertEqual(validated["observation"]["counters"]["observed_completed_roles"], 0)
        self.assertEqual(len(validated["observation"]["progress_by_item"][f.source_id]["completed_roles"]), 5)
        self.assertEqual(validated["observation"]["progress_by_item"]["other"], {"run_id": None, "completed_roles": []})
        self.assertNotIn("process_uncertainty", f.item)
        f, journal, live = self.fixture(no_launch=True)
        raw = journal._raw
        observed = self.validate(f, journal, live)
        self.assertEqual(observed["status"], "report_only", observed)
        self.assertTrue(observed["observation"]["validated"])
        self.assertIsNone(observed["seed"])
        self.assertEqual(observed["observation"]["counters"]["observed_completed_roles"], 0)
        self.assertNotIn("process_uncertainty", f.item)
        self.assertEqual(journal._raw, raw)

    def test_recovery_trust_changed_final_queue_and_stop_during_preflight_never_install(self):
        from unittest.mock import patch
        f, journal, live = self.fixture()
        original_observe, calls = orchestrator._observe_cycle_inputs, []
        def observe(*args):
            frame = original_observe(*args)
            calls.append(frame)
            if len(calls) == 1:
                f.reload(); f.payload["work_items"].append({"id": "new-unrelated", "status": "done"}); f.write_queue()
            return frame
        with patch.object(orchestrator, "_observe_cycle_inputs", side_effect=observe): refused = self.validate(f, journal, live)
        self.assertEqual(refused["status"], "reconciliation_required")
        self.assertIn("queue changed during", refused["reason"])
        self.assertIsNone(live["source_snapshot"])
        f, journal, live = self.fixture()
        class StopAfterPreflight:
            calls = 0
            def is_set(self):
                self.calls += 1
                return self.calls > 1
        observed = self.validate(f, journal, live, cancellation=StopAfterPreflight())
        self.assertEqual((observed["status"], observed["reason"]), ("report_only", "stop"))
        self.assertTrue(observed["observation"]["validated"])
        self.assertIsNone(observed["seed"])

    def test_recovery_trust_seed_rechecks_stop_clock_release_and_authority_before_admission(self):
        f, journal, live = self.fixture()
        cancellation = self.Cancellation()
        validation = self.validate(f, journal, live, cancellation=cancellation)
        seed = validation["seed"]
        for elapsed in (True, -1, 19, 60, float("nan"), float("inf")):
            with self.subTest(elapsed=elapsed), self.assertRaises(ValueError): seed.admission_patch(elapsed_seconds=elapsed)
        cancellation.stopped = True
        with self.assertRaises(ValueError): seed.admission_patch(elapsed_seconds=21)
        cancellation.stopped = False
        journal.release()
        with self.assertRaises(ValueError): seed.admission_patch(elapsed_seconds=21)
        self.assertIsNone(live["source_snapshot"]); self.assertEqual(live["progress_by_item"], {})



class InputGuardTests(unittest.TestCase):
    def healthy(self, frame):
        self.assertEqual(set(frame), {"changed", "reason", "head_changed", "trusted_expectation"})
        self.assertFalse(frame["changed"], frame)
        self.assertIsNone(frame["reason"])
        self.assertFalse(frame["head_changed"])

    def refused(self, fixture, checkpoint="entry", operation=None, *, reason="input_changed", head=False):
        before = copy.deepcopy(fixture.frozen)
        frame = fixture.observe(checkpoint, operation)
        self.assertEqual(frame, {"changed": True, "reason": reason, "head_changed": head, "trusted_expectation": None})
        self.assertEqual(fixture.frozen, before)
        return frame

    def test_input_guard_fresh_shape_expectations_and_write_once_custody(self):
        f = InputGuardFixture(self)
        self.healthy(f.observe())
        self.assertEqual(set(f.frozen), {"pins_path", "pins_raw_sha256", "cycle_id", "source_snapshot", "progress_by_item"})
        self.assertEqual(set(f.frozen["source_snapshot"]), {"input_digests", "template_candidates", "runtime_head", "execution_heads", "entry_changes", "immutable_inputs", "expected_static"})
        self.assertEqual(f.frozen["progress_by_item"], {f.source_id: {"run_id": None, "completed_roles": []}})
        frame = f.observe("before_claim", f.operation().to_dict()); self.healthy(frame)
        expected = frame["trusted_expectation"]
        self.assertEqual(len(expected["roles"]), 5)
        self.assertEqual(expected["completed_roles_before"], [])
        self.assertIsNone(expected["run_id"])
        expected["roles"][0]["required_outputs"].append("foreign")
        self.assertEqual(len(f.frozen["source_snapshot"]["expected_static"][f.source_id]["roles"][0]["required_outputs"]), 3)
        self.refused(f)
        self.healthy(f.observe("before_step"))

    def test_input_guard_five_real_stages_move_artifacts_keep_run_and_provider_rollup(self):
        from unittest.mock import patch
        f = InputGuardFixture(self, source_id="Unicode/é")
        self.healthy(f.observe())
        f.jobs.mkdir(parents=True)
        run_id = None
        seen_paths = []
        for number in range(5):
            with self.subTest(role=number):
                self.healthy(f.observe("before_step"))
                selected = f.operation()
                before = f.observe("before_claim", selected.to_dict()); self.healthy(before)
                claimed = f.provider.claim(selected)
                held = f.observe("after_claim", claimed.to_dict()); self.healthy(held)
                result = f.stage(claimed, number)
                after = f.observe("after_worker", claimed.to_dict()); self.healthy(after)
                self.assertEqual(after["trusted_expectation"], held["trusted_expectation"])
                assessment = orchestrator._bounded_result_assessment(result.to_dict(), held["trusted_expectation"])
                self.assertEqual(assessment["decision"], "done_candidate" if number == 4 else "continue_candidate")
                path = result.evidence["team_run_path"]; seen_paths.append(path)
                run_id = run_id or result.evidence["team_run"]["run_id"]
                self.assertEqual(result.evidence["team_run"]["run_id"], run_id)
                reads = []
                original = Path.read_text
                def read_text(path, *args, **kwargs):
                    if path.name == "team-rollup.md":
                        reads.append(str(path))
                    return original(path, *args, **kwargs)
                with patch.object(Path, "read_text", read_text):
                    f.settle(claimed, result)
                self.assertEqual(reads, [])
                retained = f.item["workflow_runs"][-1]["team_rollup_markdown"]
                self.assertEqual(retained, result.evidence["team_rollup_markdown"][:20000])
                self.assertEqual(retained, Path(result.evidence["team_rollup_path"]).read_text()[:20000])
                self.healthy(f.observe("before_step"))
                if number < 3:
                    self.assertEqual(result.evidence["goal_acceptance"]["verdict"], "missing")
                else:
                    self.assertEqual(result.evidence["goal_acceptance"]["verdict"], "pass")
        self.assertEqual(len(set(seen_paths)), 5)
        self.assertTrue(all(str(f.jobs) in path for path in seen_paths))
        self.assertEqual(len(f.frozen["progress_by_item"][f.source_id]["completed_roles"]), 5)

    def test_input_guard_declared_entry_resume_and_complete_baseline(self):
        for complete in (False, True):
            with self.subTest(complete=complete):
                f = InputGuardFixture(self)
                f.declared_resume(complete=complete)
                self.healthy(f.observe())
                frame = f.observe("before_claim", f.operation().to_dict()); self.healthy(frame)
                self.assertEqual(frame["trusted_expectation"]["run_id"], "preexisting-logical-run")
                self.assertEqual(len(frame["trusted_expectation"]["completed_roles_before"]), 5 if complete else 1)
                loaded = f.worker().load_resumable_team_run(f.queue, f.source_id, "work-item-change-lifecycle",
                    contract_hash=frame["trusted_expectation"]["contract_hash"], rework_count=0, required=not complete)
                self.assertEqual(loaded.id, "preexisting-logical-run") if not complete else self.assertIsNone(loaded)

    def test_input_guard_template_membership_type_barrier_precedes_all_contents(self):
        from unittest.mock import patch
        for change in ("new", "missing", "symlink", "directory", "fifo"):
            with self.subTest(change=change):
                f = InputGuardFixture(self)
                candidate = f.templates / "extra.json"
                if change == "new": candidate.write_text("new template")
                elif change == "missing": f.template_path.unlink()
                elif change == "symlink": f.template_path.unlink(); f.template_path.symlink_to(f.plan)
                elif change == "directory": f.template_path.unlink(); f.template_path.mkdir()
                else:
                    import os
                    f.template_path.unlink(); os.mkfifo(f.template_path)
                original = orchestrator._cycle_guard_read
                reads = []
                def reader(path):
                    reads.append(path)
                    return original(path)
                with patch.object(orchestrator, "_cycle_guard_read", reader):
                    self.refused(f)
                self.assertFalse(set(f.pins["template_source"]["candidates"]) & set(reads))
                self.assertNotIn(str(candidate), reads)

    def test_input_guard_all_read_set_bytes_and_raw_pins_rechecked(self):
        for kind in ("plan", "spec", "role_command_config", "team_template", "registry", "agent_instruction", "entry_file", "raw-pins"):
            for checkpoint in ("entry", "before_step", "before_claim", "after_claim", "after_worker"):
                with self.subTest(kind=kind, checkpoint=checkpoint):
                    f = InputGuardFixture(self)
                    if kind == "entry_file":
                        path = f.execution / "dirty.txt"; path.write_text("declared dirty bytes")
                        f.extra_inputs.append(("entry_file", path))
                        f.pins["execution_checkouts"][0]["entry_changes"] = [{"path": "dirty.txt", "index_state": "untracked", "worktree_state": "untracked",
                            "index_sha256": None, "worktree_sha256": f.sha(path)}]
                        f.repin()
                    operation = f.operation().to_dict() if checkpoint not in {"entry", "before_step"} else None
                    if checkpoint != "entry": self.healthy(f.observe())
                    if kind == "raw-pins":
                        f.pins_path.write_bytes(f.pins_path.read_bytes() + b" ")
                    else:
                        path = Path(next(row["path"] for row in f.pins["inputs"] if row["kind"] == kind))
                        path.write_bytes(path.read_bytes() + b"\nchanged")
                    self.refused(f, checkpoint, operation)

    def test_input_guard_lifecycle_result_counters_new_items_do_not_change_fingerprint(self):
        f = InputGuardFixture(self)
        self.healthy(f.observe())
        initial = copy.deepcopy(f.frozen["source_snapshot"])
        f.item.update(status="running", state="running", claim={"owner": "synthetic"}, result={"status": "ready"}, evidence=["mutable"],
            lifecycle={"state": "running", "rework_count": 9}, previous_claims=[{"owner": "old"}], process_uncertainty={"status": "resolved"})
        f.payload["work_items"].append({"id": "new-unadmitted", "goal": "does not join cycle"})
        f.write_queue()
        self.healthy(f.observe("before_step"))
        self.assertEqual(f.frozen["source_snapshot"], initial)
        self.assertEqual(set(f.frozen["progress_by_item"]), {f.source_id})

    def test_input_guard_immutable_effective_fields_rework_and_dependency_drift(self):
        mutations = [lambda f: f.item.update(goal="Changed instructions"), lambda f: f.item.update(title="Changed title"),
            lambda f: f.item["scheduler"].update(write_scope=["b.txt"]), lambda f: f.item["scheduler"].update(depends_on=["foreign"]),
            lambda f: f.item["scheduler"].update(workflow_kind="review"), lambda f: f.item["scheduler"].update(required_outputs=["foreign"]),
            lambda f: f.item.update(labels=["priority:p0"]), lambda f: f.item["scheduler"].update(parallel_group="other"),
            lambda f: f.item.update(previous_attempts=[{"reason": "new rework", "evidence": ["changed"]}]),
            lambda f: f.item["metadata"]["source_plan"].update(hash="f" * 64), lambda f: f.item.update(operation_id="foreign-operation")]
        for index, mutation in enumerate(mutations):
            with self.subTest(field=index):
                f = InputGuardFixture(self); self.healthy(f.observe()); mutation(f); f.write_queue()
                self.refused(f, "before_step")

    def test_input_guard_closure_completed_dependency_is_pinned_and_not_dispatchable(self):
        f = InputGuardFixture(self)
        dependency = copy.deepcopy(f.item)
        dependency.update(id="dependency", operation_id="operation:dependency", status="done", goal="Completed dependency goal")
        dependency["scheduler"]["workflow_kind"] = "generic"
        dependency["scheduler"]["team_template"] = ""
        f.item["scheduler"]["depends_on"] = ["dependency"]
        f.payload["work_items"].append(dependency); f.write_queue(); f.repin()
        self.healthy(f.observe())
        self.assertEqual(set(f.frozen["source_snapshot"]["immutable_inputs"]), {f.source_id, "dependency"})
        self.assertEqual(set(f.frozen["source_snapshot"]["expected_static"]), {f.source_id})
        self.refused(f, "before_claim", f.provider.project(dependency).to_dict())
        dependency["goal"] = "Changed dependency instructions"; f.write_queue()
        self.refused(f, "before_step")

    def test_input_guard_execution_scope_add_delete_rename_and_commit(self):
        for mode in ("in-scope", "out-of-scope", "delete", "rename", "commit-in", "commit-out", "runtime-dirty", "runtime-unrelated", "runtime-head"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self); self.healthy(f.observe())
                if mode in {"in-scope", "commit-in"}: (f.execution / "a.txt").write_text("new scoped bytes")
                elif mode in {"out-of-scope", "commit-out"}: (f.execution / "outside.txt").write_text("escaped bytes")
                elif mode == "delete": (f.execution / "outside.txt").unlink()
                elif mode == "rename": (f.execution / "a.txt").rename(f.execution / "outside-new.txt")
                elif mode == "runtime-dirty": (f.runtime / "templates/local-automation-runtime/runtime.py").write_text("modified runtime")
                elif mode == "runtime-unrelated":
                    (f.runtime / "notes.md").write_text("unrelated")
                    (f.runtime / "unrelated-link").symlink_to(f.plan)
                elif mode == "runtime-head":
                    (f.runtime / "notes.md").write_text("committed unrelated"); f.commit(f.runtime)
                if mode.startswith("commit-"): f.commit(f.execution)
                if mode in {"in-scope", "runtime-unrelated"}: self.healthy(f.observe("before_step"))
                else:
                    self.refused(f, "before_step", reason="out_of_scope_change" if mode in {"out-of-scope", "delete", "rename", "commit-out"} else "input_changed",
                        head=mode.startswith("commit-") or mode == "runtime-head")

    def test_input_guard_entry_index_and_worktree_exact_states(self):
        for mode in ("modified", "staged", "staged-and-modified", "added", "deleted", "staged-deleted", "untracked"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self)
                path = f.execution / ("new.txt" if mode in {"added", "untracked"} else "a.txt")
                if mode in {"deleted", "staged-deleted"}:
                    path.unlink()
                else:
                    path.write_text("entry dirty " + mode)
                if mode in {"staged", "staged-and-modified", "added", "staged-deleted"}: f.git(f.execution, "add", "-A")
                if mode == "staged-and-modified": path.write_text("worktree differs from staged")
                _, tree, index, paths = orchestrator._cycle_guard_checkout(str(f.execution))
                rows = orchestrator._cycle_guard_changes(str(f.execution), tree, index, paths)
                f.pins["execution_checkouts"][0]["entry_changes"] = rows
                if path.exists(): f.extra_inputs.append(("entry_file", path))
                f.repin(); self.healthy(f.observe())
                self.assertEqual(f.frozen["source_snapshot"]["entry_changes"][str(f.execution)], rows)
                self.healthy(f.observe("before_step"))
                if rows[0]["index_sha256"]:
                    f.pins["execution_checkouts"][0]["entry_changes"][0]["index_sha256"] = "f" * 64
                    f.write_pins(); self.refused(f)

    def test_input_guard_unexpected_entry_changes_and_layer_digest_mismatch(self):
        for mode in ("untracked", "deletion", "staged", "symlink", "ignored"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self)
                if mode == "untracked": (f.execution / "new.txt").write_text("unexpected")
                elif mode == "deletion": (f.execution / "a.txt").unlink()
                elif mode == "staged": (f.execution / "a.txt").write_text("unexpected staged"); f.git(f.execution, "add", "a.txt")
                elif mode == "symlink": (f.execution / "a.txt").unlink(); (f.execution / "a.txt").symlink_to(f.plan)
                else:
                    (f.execution / ".gitignore").write_text("ignored.txt\n"); f.commit(f.execution)
                    f.pins["execution_checkouts"][0]["head"] = f.head(f.execution); f.write_pins()
                    (f.execution / "ignored.txt").write_text("ignored is still untracked")
                self.refused(f)

    def test_input_guard_shape_cycles_and_partial_initialization_refuse_before_read(self):
        from unittest.mock import patch
        for mutation in (lambda f: f.frozen.pop("cycle_id"), lambda f: f.frozen.update(cycle_id="stale"),
            lambda f: f.frozen.update(extra="owner"), lambda f: f.frozen.update(progress_by_item=[]),
            lambda f: f.frozen.update(pins_raw_sha256=True)):
            f = InputGuardFixture(self); mutation(f)
            with patch.object(orchestrator, "_cycle_guard_read", side_effect=AssertionError("must refuse before reads")):
                self.refused(f)
        f = InputGuardFixture(self)
        f.frozen["progress_by_item"][f.source_id] = {"run_id": None, "completed_roles": []}
        self.refused(f)
        f = InputGuardFixture(self); self.healthy(f.observe())
        for checkpoint, operation in (("unknown", None), ("entry", {}), ("before_claim", None)):
            self.refused(f, checkpoint, operation)

    def test_input_guard_selector_registry_first_zero_one_multiple_and_sources(self):
        import atlas_workflows
        from unittest.mock import patch
        f = InputGuardFixture(self)
        # Registry shadows a Markdown reference, so its nonexistent local root
        # must not constrain the derived root or cause a fallback probe.
        f.registry_value["agents"]["shadow"] = {"ref": "agents/test-engineer.md", "source": str(f.instructions[1])}
        f.registry.write_text(json.dumps(f.registry_value)); f.repin()
        self.healthy(f.observe()); self.assertEqual(f.selectors()["agent_root"], str(f.agent_root))
        template = atlas_workflows.load_team_template(f.template_path)
        registry = atlas_workflows.load_agent_registry(f.registry)
        resolved = atlas_workflows.resolve_role_agent(template.roles[1], registry=registry, agent_root=f.agent_root)
        self.assertEqual(resolved.source, str(f.instructions[1]))
        for source in ("agents/relative.md", "https://example.invalid/instruction", str(f.inputs_root / "undeclared.md")):
            with self.subTest(source=source):
                f = InputGuardFixture(self)
                f.registry_value["agents"]["implementation"]["source"] = source
                f.registry.write_text(json.dumps(f.registry_value)); f.repin()
                self.refused(f)
        f = InputGuardFixture(self)
        other = f.inputs_root / "other-registry.json"; other.write_text('{"agents":{"other":{"source":""}}}')
        f.extra_inputs.append(("registry", other)); f.repin()
        original = orchestrator._cycle_guard_read
        with patch.object(orchestrator, "_cycle_guard_read", side_effect=lambda path: (_ for _ in ()).throw(AssertionError("registry content read")) if path in {str(f.registry), str(other)} else original(path)):
            self.refused(f)
        f = InputGuardFixture(self)
        for role in f.template_value["roles"]:
            role["agent_ref"] = role["id"]
        f.template_path.write_text(json.dumps(f.template_value)); f.registry = None; f.repin()
        self.healthy(f.observe()); self.assertIsNone(f.selectors()["agent_registry_path"]); self.assertIsNone(f.selectors()["agent_root"])

    def test_input_guard_selector_root_ambiguity_unresolved_uri_and_absolute_sentinel(self):
        import atlas_workflows
        for mode in ("ambiguous", "absent", "uri", "absolute"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self)
                if mode == "ambiguous":
                    for instruction in list(f.instructions):
                        alternate = f.inputs_root / "other-instructions" / "agents" / instruction.name
                        alternate.parent.mkdir(parents=True, exist_ok=True); alternate.write_text("different " + instruction.name)
                        f.instructions.append(alternate)
                elif mode == "absent": f.instructions = f.instructions[:1]
                elif mode == "uri": f.registry = None
                else:
                    for role in f.template_value["roles"]:
                        if role["agent_ref"].startswith("agents/"):
                            role["agent_ref"] = str(f.agent_root / role["agent_ref"])
                    f.template_path.write_text(json.dumps(f.template_value))
                f.repin()
                if mode != "absolute": self.refused(f)
                else:
                    self.healthy(f.observe()); selectors = f.selectors()
                    self.assertEqual(selectors["agent_root"], str(f.queue.parent))
                    template = atlas_workflows.load_team_template(f.template_path)
                    self.assertIsNone(atlas_workflows.resolve_role_agent(template.roles[1], agent_root=None))
                    self.assertEqual(atlas_workflows.resolve_role_agent(template.roles[1], agent_root=selectors["agent_root"]).source, str(f.instructions[0]))

    def test_input_guard_declared_resume_drift_missing_metadata_and_loaded_evidence(self):
        mutations = {
            "contract": lambda f, p: f.item["workflow_runs"][-1].update(contract_hash="f" * 64),
            "rework": lambda f, p: f.item["workflow_runs"][-1].update(rework_count=1),
            "missing-path": lambda f, p: f.item["workflow_runs"][-1].update(artifacts={}),
            "undeclared": lambda f, p: f.item["workflow_runs"][-1]["artifacts"].update(team_run_path=str(f.root / "unreadable-foreign.json")),
            "newest-wrong": lambda f, p: f.item["workflow_runs"].append({"team_run": {"template_id": "foreign"}}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                f = InputGuardFixture(self); path = f.declared_resume(); mutate(f, path); f.write_queue()
                self.refused(f)
        for mode in ("identity", "run-id", "role-key", "outputs", "goal", "summary", "missing", "symlink", "hardlink"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self); path = f.declared_resume()
                if mode == "missing": path.unlink()
                elif mode == "symlink": path.unlink(); path.symlink_to(f.plan)
                elif mode == "hardlink":
                    import os
                    os.link(path, f.execution / "hardlink.json")
                elif mode == "summary": f.item["workflow_runs"][-1]["team_run"]["work_item_id"] = "foreign"; f.write_queue()
                else:
                    value = json.loads(path.read_text())
                    if mode == "identity": value["work_item_id"] = "foreign"
                    elif mode == "run-id": value["id"] = "foreign"
                    elif mode == "role-key": value["role_results"]["implementation"]["role_id"] = "foreign"
                    elif mode == "outputs": value["role_results"]["implementation"]["outputs"] = {}
                    else: value["role_results"]["unknown-goal"] = value["role_results"]["implementation"]
                    path.write_text(json.dumps(value))
                    # Pin malformed bytes deliberately, so content validation is
                    # independently tested rather than only hash refusal.
                    f.git(f.execution, "add", "resume.json"); f.git(f.execution, "commit", "-qm", "malformed resume fixture")
                    f.pins["execution_checkouts"][0]["head"] = f.head(f.execution); f.repin()
                self.refused(f)

    def test_input_guard_owned_resume_path_refusal_precedes_target_probe(self):
        from unittest.mock import patch
        for mode in ("foreign-cycle", "lookalike", "traversal", "uri", "extra-level", "wrong-slug", "bad-uuid", "pre-entry"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self); self.healthy(f.observe()); f.jobs.mkdir(parents=True)
                operation = f.provider.claim(f.operation()); result = f.stage(operation, 0); f.settle(operation, result)
                path = Path(result.evidence["team_run_path"])
                if mode == "foreign-cycle": bad = str(path).replace("a" * 32 + ".jobs", "b" * 32 + ".jobs")
                elif mode == "lookalike": bad = str(path).replace("a" * 32 + ".jobs", "a" * 32 + ".jobs-lookalike")
                elif mode == "traversal": bad = str(path.parent / ".." / path.parent.name / "team-run.json")
                elif mode == "uri": bad = "file://" + str(path)
                elif mode == "extra-level": bad = str(path.parent / "extra" / "team-run.json")
                elif mode == "wrong-slug": bad = str(path).replace("atlas-work-item-work-123-", "atlas-work-item-other-")
                elif mode == "bad-uuid": bad = str(path).replace("00000000000000000000000000000001", "unknown")
                else: bad = str(path)
                f.item["workflow_runs"][-1]["artifacts"]["team_run_path"] = bad; f.write_queue()
                if mode == "pre-entry": f.frozen["source_snapshot"] = None; f.frozen["progress_by_item"].clear()
                original = orchestrator._cycle_guard_read
                def reader(target):
                    if target == bad: raise AssertionError("inadmissible artifact target read")
                    return original(target)
                with patch.object(orchestrator, "_cycle_guard_read", reader):
                    self.refused(f, "entry" if mode == "pre-entry" else "before_step")

    def test_input_guard_owned_resume_held_progress_links_missing_and_safe_id_collision(self):
        for mode in ("missing", "symlink", "ancestor-link", "wrong-run", "wrong-item-collision", "progress", "contract", "rework"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self); self.healthy(f.observe()); f.jobs.mkdir(parents=True)
                operation = f.provider.claim(f.operation()); result = f.stage(operation, 0); f.settle(operation, result)
                path = Path(result.evidence["team_run_path"])
                if mode == "missing": path.unlink()
                elif mode == "symlink": path.unlink(); path.symlink_to(f.plan)
                elif mode == "ancestor-link":
                    saved = path.parent.with_name("saved-invocation"); path.parent.rename(saved); path.parent.symlink_to(saved, target_is_directory=True)
                elif mode in {"wrong-run", "wrong-item-collision"}:
                    value = json.loads(path.read_text())
                    if mode == "wrong-run": value["id"] = "foreign-logical-run"
                    else:
                        value["work_item_id"] = "work?123"
                        self.assertEqual(orchestrator.atlas_work_items.safe_id(value["work_item_id"]), orchestrator.atlas_work_items.safe_id(f.source_id))
                    path.write_text(json.dumps(value))
                elif mode == "progress": f.frozen["progress_by_item"][f.source_id]["completed_roles"] = []
                elif mode == "contract": f.item["workflow_runs"][-1]["contract_hash"] = "f" * 64; f.write_queue()
                else: f.item["lifecycle"]["rework_count"] = 1; f.write_queue()
                self.refused(f, "before_step")

    def test_input_guard_canonical_paths_hardlinks_and_reference_declarations(self):
        for mode in ("queue-link", "input-link", "checkout-alias", "input-hardlink", "undeclared-spec", "undeclared-plan", "deleted-closure", "duplicate-id"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self)
                if mode == "queue-link":
                    moved = f.root / "actual-queue.json"; f.queue.rename(moved); f.queue.symlink_to(moved)
                elif mode == "input-link":
                    moved = f.inputs_root / "actual-plan.md"; f.plan.rename(moved); f.plan.symlink_to(moved)
                elif mode == "checkout-alias":
                    alias = f.root / "execution-alias"; alias.symlink_to(f.execution, target_is_directory=True)
                    f.item["scheduler"]["execution_repo"] = str(alias); f.pins["execution_checkouts"][0]["checkout_path"] = str(alias)
                    f.write_queue(); f.repin()
                elif mode == "input-hardlink":
                    import os
                    os.link(f.plan, f.inputs_root / "plan-hardlink.md")
                elif mode == "undeclared-spec":
                    f.pins["inputs"] = [row for row in f.pins["inputs"] if row["kind"] != "spec"]; f.write_pins()
                elif mode == "undeclared-plan":
                    f.pins["inputs"] = [row for row in f.pins["inputs"] if row["kind"] != "plan"]; f.write_pins()
                elif mode == "deleted-closure": f.payload["work_items"].clear(); f.write_queue()
                else: f.payload["work_items"].append(copy.deepcopy(f.item)); f.write_queue()
                self.refused(f)

    def test_input_guard_safe_git_ignores_external_helpers_and_ambient_configuration(self):
        import os
        from unittest.mock import patch
        f = InputGuardFixture(self)
        marker = f.root / "forbidden-helper-ran"
        helper = f.root / "helper.sh"; helper.write_text("#!/bin/sh\ntouch '" + str(marker) + "'\nexit 1\n"); helper.chmod(0o755)
        f.git(f.execution, "config", "core.fsmonitor", str(helper))
        f.git(f.execution, "config", "diff.external", str(helper))
        f.git(f.execution, "config", "core.hooksPath", str(helper))
        with patch.dict(os.environ, {"GIT_DIR": "/unrelated", "GIT_WORK_TREE": "/unrelated", "GIT_EXTERNAL_DIFF": str(helper), "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": str(helper)}):
            self.healthy(f.observe()); (f.execution / "a.txt").write_text("allowed change")
            self.healthy(f.observe("before_step"))
        self.assertFalse(marker.exists())

    def test_input_guard_actual_adapter_provider_journal_five_stage_composition(self):
        from unittest.mock import patch
        f = InputGuardFixture(self)
        limits = {"max_steps": 8, "max_claims": 7, "max_roles": 6, "role_max": 1, "cycle_seconds": 100,
            "worker_timeout_seconds": 10, "worker_termination_grace_seconds": 0, "stop_file": str(f.root / "stop")}
        inputs = {"queue_path": str(f.queue), "pins_path": str(f.pins_path), "pins_raw_sha256": f.frozen["pins_raw_sha256"],
            "cycle_id": f.frozen["cycle_id"], "entry_monotonic": 0, "limits": limits, "admitted_item_ids": [f.source_id],
            "progress_by_item": f.frozen["progress_by_item"]}
        journal = orchestrator._CycleJournal(str(f.queue), f.pins, f.frozen["pins_raw_sha256"], limits,
            cycle_id=f.frozen["cycle_id"], acknowledged_closures={})
        calls = []
        class Worker:
            def run(self, operation, store_path, *, cancel_event):
                self_number = len(calls); calls.append(operation.source_id)
                return f.stage(operation, self_number)
        class Cancellation:
            def is_set(self): return False
        initialized = False
        def guard(checkpoint, operation):
            nonlocal initialized
            if checkpoint == "before_step" and not initialized:
                self.assertTrue(journal._opened)
                f.jobs.mkdir(); initialized = True
            return f.observe(checkpoint, operation)
        with patch.object(orchestrator.common, "read_config", side_effect=AssertionError("ambient config forbidden")):
            result = orchestrator._run_bounded_cycle(inputs, provider=f.provider, worker_factory=lambda allowance: Worker(),
                monotonic=lambda: 0, cancellation=Cancellation(), journal=journal, guard=guard)
        self.assertFalse(result["unresolved"], result)
        self.assertEqual(result["terminal_outcome"], "completed", result)
        self.assertEqual(len(calls), 5)
        self.assertIsNotNone(result["closure_witness"])
        self.assertEqual(len(result["progress_by_item"][f.source_id]["completed_roles"]), 5)


    def test_input_guard_exact_missing_file_scope_refuses_directory_and_link_substitution(self):
        for mode in ("file", "directory", "ancestor-link"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self)
                f.item["scheduler"]["write_scope"] = ["planned/new.py" if mode == "ancestor-link" else "new.py"]
                f.write_queue(); f.repin(); self.healthy(f.observe())
                if mode == "file":
                    (f.execution / "new.py").write_text("new scoped file")
                    self.healthy(f.observe("before_step"))
                elif mode == "directory":
                    (f.execution / "new.py").mkdir(); (f.execution / "new.py/extra.py").write_text("escaped descendant")
                    self.refused(f, "before_step", reason="out_of_scope_change")
                else:
                    (f.execution / "planned").symlink_to(f.inputs_root, target_is_directory=True)
                    self.refused(f, "before_step", reason="out_of_scope_change")

    def test_input_guard_resume_metadata_barrier_precedes_declared_artifact_hash_read(self):
        from unittest.mock import patch
        for mode in ("contract", "rework", "newest-template", "missing-path"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self); path = f.declared_resume()
                if mode == "contract": f.item["workflow_runs"][-1]["contract_hash"] = "f" * 64
                elif mode == "rework": f.item["workflow_runs"][-1]["rework_count"] = 1
                elif mode == "newest-template": f.item["workflow_runs"].append({"team_run": {"template_id": "foreign"}})
                else: f.item["workflow_runs"][-1]["artifacts"] = {}
                f.write_queue()
                original = orchestrator._cycle_guard_read
                def reader(target):
                    if target == str(path): raise AssertionError("artifact read preceded resume metadata admission")
                    return original(target)
                with patch.object(orchestrator, "_cycle_guard_read", reader):
                    self.refused(f)

    def test_input_guard_pending_resume_evidence_and_optional_review_shape(self):
        import atlas_workflows
        for mode in ("pending", "malformed-nongate-review", "failed-goal", "dependency-gap"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self); path = f.declared_resume()
                value = json.loads(path.read_text())
                if mode == "pending":
                    value["role_results"]["test-runner"] = atlas_workflows.TeamRunRoleResult("test-runner", "pending", {}).to_dict()
                elif mode == "malformed-nongate-review":
                    value["role_results"]["implementation"]["goal_review"] = {"unexpected": "malformed review"}
                elif mode == "failed-goal":
                    value["role_results"]["semantic-alignment"] = atlas_workflows.TeamRunRoleResult("semantic-alignment", "pending", {},
                        goal_review={"verdict": "fail", "reason": "A stated acceptance condition remains unmet.", "evidence": ["A focused check failed."]}).to_dict()
                else:
                    value["role_results"] = {"test-runner": atlas_workflows.TeamRunRoleResult("test-runner", "complete",
                        {name: "accepted evidence" for name in ("commands_run", "test_results", "coverage_or_gap_notes")}).to_dict()}
                path.write_text(json.dumps(value))
                template = atlas_workflows.load_team_template(f.template_path)
                run = atlas_workflows.TeamRun.from_dict(value); run.refresh_status(template)
                f.item["workflow_runs"][-1]["team_run"] = atlas_workflows.team_run_summary(template, run)
                f.write_queue(); f.commit(f.execution); f.pins["execution_checkouts"][0]["head"] = f.head(f.execution); f.repin()
                if mode == "pending":
                    self.healthy(f.observe())
                    self.assertEqual(f.frozen["progress_by_item"][f.source_id]["completed_roles"], ["implementation"])
                else: self.refused(f)

    def test_input_guard_raw_git_never_executes_clean_filter_or_hides_eol_changes(self):
        for mode in ("filter", "eol"):
            with self.subTest(mode=mode):
                f = InputGuardFixture(self)
                (f.execution / ".gitattributes").write_text("a.txt filter=guard-forbidden\n" if mode == "filter" else "a.txt text eol=lf\n")
                f.commit(f.execution)
                f.pins["execution_checkouts"][0]["head"] = f.head(f.execution); f.repin()
                marker = f.root / "clean-filter-ran"
                if mode == "filter":
                    command = "touch '" + str(marker) + "'; cat"
                    f.git(f.execution, "config", "filter.guard-forbidden.clean", command)
                    f.git(f.execution, "config", "filter.guard-forbidden.required", "true")
                    self.healthy(f.observe()); (f.execution / "a.txt").write_text("scoped replacement")
                    self.healthy(f.observe("before_step")); self.assertFalse(marker.exists())
                else:
                    (f.execution / "a.txt").write_bytes((f.execution / "a.txt").read_bytes().replace(b"\n", b"\r\n"))
                    self.refused(f)

    def test_input_guard_admitted_complete_baseline_skips_actual_claim_and_worker(self):
        f = InputGuardFixture(self); f.declared_resume(complete=True)
        limits = {"max_steps": 2, "max_claims": 1, "max_roles": 1, "role_max": 1, "cycle_seconds": 100,
            "worker_timeout_seconds": 10, "worker_termination_grace_seconds": 0, "stop_file": str(f.root / "stop")}
        inputs = {"queue_path": str(f.queue), "pins_path": str(f.pins_path), "pins_raw_sha256": f.frozen["pins_raw_sha256"],
            "cycle_id": f.frozen["cycle_id"], "entry_monotonic": 0, "limits": limits, "admitted_item_ids": [f.source_id],
            "progress_by_item": f.frozen["progress_by_item"]}
        journal = orchestrator._CycleJournal(str(f.queue), f.pins, f.frozen["pins_raw_sha256"], limits,
            cycle_id=f.frozen["cycle_id"], acknowledged_closures={})
        from unittest.mock import patch
        class Cancellation:
            def is_set(self): return False
        def forbidden(*args, **kwargs): raise AssertionError("complete baseline must not claim or launch")
        with patch.object(f.provider, "claim", forbidden):
            result = orchestrator._run_bounded_cycle(inputs, provider=f.provider, worker_factory=forbidden,
                monotonic=lambda: 0, cancellation=Cancellation(), journal=journal, guard=f.observe)
        self.assertEqual(result["terminal_outcome"], "completed", result)
        self.assertFalse(result["unresolved"])
        self.assertEqual(result["counters"]["claims_reserved"], 0)
        self.assertEqual(result["counters"]["roles_reserved"], 0)
        self.assertEqual(len(result["progress_by_item"][f.source_id]["completed_roles"]), 5)

    def test_input_guard_sizing_exact_worker_formula_and_unqualified_refusal(self):
        import atlas_local_sizing
        import atlas_workflows
        for invalid in (False, True):
            with self.subTest(invalid=invalid):
                f = InputGuardFixture(self)
                purposes = {"implementation": "implementation", "test-runner": "validation", "code-review": "review",
                    "semantic-alignment": "goal-review", "evidence-rollup": "review"}
                f.item["metadata"]["local_execution_v1"] = {"policy_id": "local-luna-unit-v1", "role_purposes": purposes,
                    "changed_interfaces": ["one_file()"], "unresolved_questions": ["unresolved"] if invalid else [], "complexity_flags": []}
                f.write_queue(); f.repin()
                if invalid:
                    self.refused(f)
                else:
                    self.healthy(f.observe())
                    operation = f.operation(); template = atlas_workflows.load_team_template(f.template_path)
                    sizing = atlas_local_sizing.qualify(operation.work_item_context,
                        roles=[{"role_id": role.id, "goal_gate": role.goal_gate} for role in template.roles])
                    self.assertEqual(sizing["status"], "qualified")
                    expected = f.observe("before_claim", operation.to_dict())["trusted_expectation"]
                    self.assertEqual(expected["contract_hash"], orchestrator.atlas_work_items.content_hash({"context": operation.work_item_context,
                        "template": template.to_dict(), "local_sizing": sizing}))

    def test_input_guard_entry_multi_item_initialization_has_no_partial_custody(self):
        f = InputGuardFixture(self)
        other = copy.deepcopy(f.item)
        other.update(id="z-other", operation_id="operation:z-other", goal="A second admitted scoped goal")
        other["scheduler"]["write_scope"] = ["b.txt"]
        other["workflow_runs"] = [{"team_run": {"template_id": "foreign"}}]
        f.payload["work_items"].append(other); f.pins["admitted_item_ids"] = sorted([f.source_id, "z-other"])
        f.write_queue(); f.repin(); self.refused(f)
        self.assertIsNone(f.frozen["source_snapshot"])
        self.assertEqual(f.frozen["progress_by_item"], {})
        other.pop("workflow_runs"); f.write_queue()
        self.healthy(f.observe())
        self.assertEqual(set(f.frozen["progress_by_item"]), {f.source_id, "z-other"})

    def test_input_guard_later_context_shapes_and_snapshot_progress_custody(self):
        for checkpoint in ("before_step", "before_claim", "after_claim", "after_worker"):
            for mutation in (lambda f: f.frozen.update(cycle_id=True),
                             lambda f: f.frozen["source_snapshot"].update(extra="hidden owner"),
                             lambda f: f.frozen["progress_by_item"][f.source_id].update(extra="hidden owner"),
                             lambda f: f.frozen["progress_by_item"].clear()):
                with self.subTest(checkpoint=checkpoint, mutation=mutation):
                    f = InputGuardFixture(self); self.healthy(f.observe()); mutation(f)
                    operation = None if checkpoint == "before_step" else f.operation().to_dict()
                    self.refused(f, checkpoint, operation)

    def test_input_guard_file_template_mode_all_relevant_candidates_and_foreign_operation(self):
        f = InputGuardFixture(self)
        f.pins["template_source"] = {"mode": "file", "path": str(f.template_path), "candidates": [str(f.template_path)]}
        f.write_pins(); self.healthy(f.observe())
        self.healthy(f.observe("before_claim", f.operation().to_dict()))
        foreign = f.operation().to_dict(); foreign["source_id"] = "foreign"
        self.refused(f, "before_claim", foreign)
        f = InputGuardFixture(self)
        extra = f.templates / "unselected.json"
        value = copy.deepcopy(f.template_value); value["id"] = "unselected-lifecycle"
        extra.write_text(json.dumps(value))
        f.extra_inputs.append(("team_template", extra)); f.pins["template_source"]["candidates"] = sorted([str(f.template_path), str(extra)])
        f.repin(); self.healthy(f.observe()); extra.write_text(extra.read_text() + "\nchanged")
        self.refused(f, "before_step")

class BoundedCliTests(unittest.TestCase):
    """Real composition; only the source-location and inference launch are synthetic."""
    def fixture(self):
        f = InputGuardFixture(self)
        f.item["metadata"]["local_execution_v1"] = {
            "policy_id": "local-luna-unit-v1", "role_purposes": {"implementation": "implementation",
                "test-runner": "validation", "code-review": "review", "semantic-alignment": "goal-review", "evidence-rollup": "review"},
            "changed_interfaces": ["Synthetic scoped file"], "unresolved_questions": [], "complexity_flags": []}
        f.write_queue(); f.repin()
        return f

    def argv(self, f, **changes):
        values = {"atlas-work-items": str(f.queue), "atlas-role-command-config": str(f.config),
            "atlas-cycle-pins": str(f.pins_path), "atlas-max-steps": 8, "atlas-max-claims": 8,
            "atlas-max-roles": 8, "atlas-role-max": 1, "atlas-cycle-seconds": 120,
            "atlas-worker-timeout-seconds": 10, "atlas-worker-termination-grace-seconds": 0.2,
            "atlas-stop-file": str(f.root / "stop")}
        values.update(changes)
        return ["--atlas-bounded"] + ["--" + key + "=" + str(value) for key, value in values.items() if value is not None]

    def invoke(self, argv):
        from unittest.mock import patch
        import contextlib, io
        output, error = io.StringIO(), io.StringIO()
        code = 0
        with patch.object(sys, "argv", ["atlas-agent-orchestrator", *argv]), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:
                orchestrator.main()
            except SystemExit as exc:
                code = exc.code
        text = output.getvalue().strip()
        return code, json.loads(text) if text.startswith("{") else None, error.getvalue()

    def run_fixture(self, f, *, argv=None, verdict="pass", hook=None, **patches):
        from unittest.mock import patch
        from contextlib import ExitStack
        import subprocess
        original_popen = subprocess.Popen
        worker_class = orchestrator.atlas_work_items.LocalCommandOperationWorker
        original_init = worker_class.__init__
        constructions, launches, reads = [], [], []
        fake_runtime = f.runtime / "templates/local-automation-runtime"
        producer = '''import os,sys,json
sys.path.insert(0,sys.argv[1])
import atlas_local_sizing
rows=json.load(open(os.environ['ATLAS_TEAM_ROLE_TASKS_FILE']))
tasks=rows['tasks'] if isinstance(rows,dict) else rows
complete={t['role_id'] for t in tasks if t.get('status')=='complete' and not t.get('missing_outputs')}
results=[]
for task in tasks:
 if task['role_id'] in complete or not set(task.get('consumes',[])).issubset(complete): continue
 atlas_local_sizing.assignment_for_task(task)
 review={'verdict':sys.argv[3], 'reason':'Inspected the scoped implementation and substantive verification against its goal.', 'evidence':['Focused synthetic verification satisfies the acceptance contract.']} if task.get('goal_gate') else None
 result={'role_id':task['role_id'],'status':'complete','outputs':{key:'Substantive synthetic '+key for key in task['must_produce']},'evidence':['Finite Python role fixture completed.'],'goal_review':review}
 results.append(result);complete.add(task['role_id'])
 if len(results)>=int(sys.argv[2]) or review and review['verdict']!='pass':break
json.dump(results,open(os.environ['ATLAS_TEAM_ROLE_RESULTS_FILE'],'w'))
'''
        def init(worker, command, **kwargs):
            constructions.append((command, dict(kwargs)))
            return original_init(worker, command, **kwargs)
        def popen(command, *args, **kwargs):
            if isinstance(command, list) and command and command[0] == str(fake_runtime / "atlas-agent-role-runner"):
                launches.append((list(command), dict(kwargs)))
                if hook:
                    hook(len(launches), kwargs)
                command = [sys.executable, "-B", "-c", producer, str(ROOT), command[4], verdict]
            return original_popen(command, *args, **kwargs)
        original_read = Path.read_text
        def read(path, *args, **kwargs):
            if path.name in {"team-rollup.md", "team-run.json"}:
                reads.append(str(path))
            return original_read(path, *args, **kwargs)
        with ExitStack() as stack:
            stack.enter_context(patch.object(orchestrator, "_bounded_cli_runtime", return_value=fake_runtime))
            stack.enter_context(patch.object(orchestrator.atlas_work_items, "__file__", str(fake_runtime / "atlas_work_items.py")))
            stack.enter_context(patch.object(worker_class, "__init__", init))
            stack.enter_context(patch.object(subprocess, "Popen", popen))
            stack.enter_context(patch.object(Path, "read_text", read))
            for name in ("process_once", "process_atlas_work_items_once", "target_repos"):
                stack.enter_context(patch.object(orchestrator, name, side_effect=AssertionError("forbidden legacy " + name)))
            for name in ("read_config", "jobs_dir"):
                stack.enter_context(patch.object(orchestrator.common, name, side_effect=AssertionError("forbidden ambient " + name)))
            for name, value in patches.items():
                stack.enter_context(patch.object(orchestrator, name, value))
            result = self.invoke(argv or self.argv(f))
        return result, constructions, launches, reads

    def test_bounded_cli_five_staged_roles_canonical_factory_and_moving_artifacts(self):
        f = self.fixture()
        (code, result, error), factories, launches, reads = self.run_fixture(f)
        self.assertEqual(code, 0, (result, error))
        self.assertEqual(result["terminal_outcome"], "completed")
        self.assertEqual(len(launches), 5)
        self.assertEqual(len(factories), 5)
        f.reload(); self.assertEqual(f.item["status"], "done")
        paths = [kwargs["env"]["ATLAS_TEAM_RUN_FILE"] for command, kwargs in launches]
        self.assertEqual(len(set(paths)), 5)
        artifacts = [json.loads(Path(path).read_text()) for path in paths]
        self.assertEqual(len({run["id"] for run in artifacts}), 1)
        self.assertEqual([len(run["role_results"]) for run in artifacts], [1, 2, 3, 4, 5])
        self.assertNotIn("semantic-alignment", artifacts[2]["role_results"])
        self.assertEqual(artifacts[3]["role_results"]["semantic-alignment"]["goal_review"]["verdict"], "pass")
        self.assertNotIn("evidence-rollup", artifacts[3]["role_results"])
        roots = {str(Path(path).parent.parent) for path in paths}
        self.assertEqual(len(roots), 1)
        jobs = Path(next(iter(roots)))
        self.assertRegex(jobs.name, r"^[0-9a-f]{32}\.jobs$")
        for command, kwargs in factories:
            self.assertEqual(command, [str(f.runtime / "templates/local-automation-runtime/atlas-agent-role-runner"), "--command-config", str(f.config), "--max-roles", "1"])
            self.assertEqual(kwargs, {"jobs_dir": jobs, "templates_dir": str(f.templates), "agent_registry_path": str(f.registry),
                "agent_root": str(f.agent_root), "timeout_seconds": 10.0, "termination_grace_seconds": 0.2})
        self.assertFalse(any(Path(path).name == "team-rollup.md" for path in reads))
        self.assertEqual(f.item["workflow_runs"][-1]["team_rollup_markdown"],
                         Path(paths[-1]).with_name("team-rollup.md").read_text()[:20000])
        self.assertTrue(all(Path(path).is_relative_to(jobs) for path in reads))
        receipt = next(jobs.parent.glob("*.jsonl"))
        events = orchestrator._decode_cycle_receipt(receipt.read_bytes())
        self.assertEqual({event["cycle_id"] for event in events}, {jobs.stem})
        self.assertEqual(events[-1]["event"], "closed")
        self.assertEqual(result["counters"]["observed_completed_roles"], 5)

    def test_bounded_cli_required_options_duplicates_equal_and_forbidden_mixes(self):
        from unittest.mock import patch
        f = self.fixture(); base = self.argv(f)
        with patch.object(orchestrator, "_cycle_guard_read", side_effect=AssertionError("must refuse before reads")), patch.object(orchestrator, "process_once", side_effect=AssertionError("legacy")):
            for index in range(len(base)):
                with self.subTest(missing=base[index]):
                    code, result, error = self.invoke(base[:index] + base[index + 1:])
                    self.assertEqual(code, 2); self.assertIsNone(result)
            for option in ["--daemon", "--publish", "--dry-run", "--atlas-work-item-command=", "--sleep-seconds=60", "--limit=20", "--repos-file=", "--triage-needs-human", "--dispatch-deploy-candidates", "--auto-queue-max=1", "--no-write-scope-locks", "--atlas-role-max=1", "--atlas-max-st=1"]:
                with self.subTest(option=option):
                    self.assertEqual(self.invoke(base + [option])[0], 2)

    def test_bounded_cli_abbreviations_without_mode_refuse_and_legacy_stays_ordinary(self):
        from unittest.mock import patch
        for option in ["--atlas-cycle-pin=/tmp/x", "--atlas-max-st=1", "--atlas-max-cl=1", "--atlas-max-ro=1", "--atlas-cycle-sec=1", "--atlas-worker-timeout-sec=1", "--atlas-worker-termination-grace-sec=0", "--atlas-stop-fil=/tmp/x"]:
            with self.subTest(option=option), patch.object(orchestrator, "process_once", side_effect=AssertionError("legacy reached")):
                self.assertEqual(self.invoke(["--once", option])[0], 2)
        with patch.object(orchestrator, "process_once", return_value=0) as legacy:
            self.assertEqual(self.invoke(["--once"])[0], 0); legacy.assert_called_once()

    def test_bounded_cli_numeric_and_path_domains(self):
        f = self.fixture()
        for key, value in [("atlas-max-steps", 0), ("atlas-max-claims", -1), ("atlas-max-roles", "1.5"), ("atlas-role-max", 101),
            ("atlas-cycle-seconds", "nan"), ("atlas-cycle-seconds", "inf"), ("atlas-worker-timeout-seconds", 0),
            ("atlas-worker-termination-grace-seconds", -1), ("atlas-work-items", "relative.json"), ("atlas-stop-file", str(f.root / ".." / "stop"))]:
            with self.subTest(key=key, value=value):
                (code, result, error), factories, launches, _ = self.run_fixture(f, argv=self.argv(f, **{key: value}))
                self.assertEqual(code, 2, (result, error)); self.assertFalse(launches); self.assertFalse(factories)

    def test_bounded_cli_explicit_qualified_routing_required_before_claim(self):
        for contract in ["missing", None, [], {}, {"policy_id": "wrong"}]:
            with self.subTest(contract=contract):
                f = self.fixture()
                if contract == "missing": f.item["metadata"].pop("local_execution_v1")
                else: f.item["metadata"]["local_execution_v1"] = contract
                f.write_queue(); f.repin()
                (code, result, error), factories, launches, _ = self.run_fixture(f)
                self.assertEqual(code, 2, (result, error)); self.assertFalse(factories); self.assertFalse(launches)
                f.reload(); self.assertEqual(f.item["status"], "ready")

    def test_bounded_cli_source_and_selectors_are_exact(self):
        from unittest.mock import patch
        f = self.fixture()
        with patch.object(orchestrator, "_bounded_cli_runtime", return_value=ROOT):
            code, result, error = self.invoke(self.argv(f))
        self.assertEqual(code, 2); self.assertIn("executing runtime", error)
        for key in ["team-templates", "agent-registry", "agent-root", "atlas-role-command-config", "atlas-work-items"]:
            with self.subTest(key=key):
                (code, result, error), factories, launches, _ = self.run_fixture(f, argv=self.argv(f, **{key: str(f.root / "wrong")}))
                self.assertEqual(code, 2); self.assertFalse(factories); self.assertFalse(launches)

    def test_bounded_cli_signal_restore_normal_preflight_partial_install(self):
        from unittest.mock import patch
        import signal
        f = self.fixture(); original = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        self.run_fixture(f, argv=self.argv(f, **{"atlas-work-items": str(f.root / "wrong")}))
        self.assertEqual({sig: signal.getsignal(sig) for sig in original}, original)
        changes = []
        def install(sig, handler):
            changes.append((sig, handler))
            if sig == signal.SIGTERM: raise RuntimeError("partial installation")
        with patch.object(signal, "signal", install):
            self.assertEqual(self.invoke(self.argv(f))[0], 2)
        self.assertEqual(changes[-1], (signal.SIGINT, original[signal.SIGINT]))
        token = orchestrator._BoundedCliCancellation(str(f.root / "stop"))
        with patch.object(orchestrator, "_cycle_guard_open", side_effect=AssertionError("signal performed IO")):
            token.signal(signal.SIGTERM, None); self.assertTrue(token.is_set())

    def test_bounded_cli_stop_parent_errors_and_presence_latch(self):
        from unittest.mock import patch
        f = self.fixture(); token = orchestrator._BoundedCliCancellation(str(f.root / "stop"))
        self.assertFalse(token.is_set()); (f.root / "stop").symlink_to(f.root / "missing")
        self.assertTrue(token.is_set()); (f.root / "stop").unlink(); self.assertTrue(token.is_set())
        for path in [f.root / "missing" / "stop", f.root / "alias" / "stop"]:
            if path.parent.name == "alias": path.parent.symlink_to(f.inputs_root)
            with self.subTest(path=path):
                token = orchestrator._BoundedCliCancellation(str(path))
                with self.assertRaises(OSError): token.is_set()
                with patch.object(orchestrator, "_cycle_guard_open", side_effect=AssertionError("retried failed inspection")):
                    with self.assertRaises(OSError): token.is_set()
        (f.root / "stop").touch()
        (code, result, _), factories, launches, _ = self.run_fixture(f)
        self.assertEqual(result["terminal_outcome"], "cancelled"); self.assertFalse(factories); self.assertFalse(launches)

    def test_bounded_cli_deadline_charges_preflight_and_restores_signals(self):
        from unittest.mock import patch
        f = self.fixture(); now = [0.0]; original = orchestrator._cycle_guard_read
        def read(path):
            now[0] += 200
            return original(path)
        with patch.object(orchestrator.time, "monotonic", lambda: now[0]):
            (code, result, _), factories, launches, _ = self.run_fixture(f, _cycle_guard_read=read)
        self.assertEqual(result["terminal_outcome"], "cancelled"); self.assertEqual(result["failure"], "deadline")
        self.assertGreaterEqual(result["elapsed_seconds"], 200); self.assertFalse(factories); self.assertFalse(launches)

    def test_bounded_cli_root_ack_before_readiness_and_failure_no_launch(self):
        from unittest.mock import patch
        original = orchestrator._bounded_cli_jobs
        for failure in ["mkdir", "parent_open", "child_open", "child_fsync", "parent_fsync", "collision"]:
            f = self.fixture(); seen = []
            def initialize(root, identity=None):
                if identity is None:
                    receipt = next(root.parent.glob("*.jsonl"))
                    self.assertEqual(orchestrator._decode_cycle_receipt(receipt.read_bytes())[-1]["event"], "opened")
                    seen.append("opened")
                    if failure == "collision": root.mkdir()
                    import os
                    if failure == "mkdir":
                        with patch.object(orchestrator.os, "mkdir", side_effect=OSError("synthetic init fault")):
                            return original(root, identity)
                    if failure in {"parent_open", "child_open", "child_fsync", "parent_fsync"}:
                        name = "open" if failure.endswith("open") else "fsync"
                        actual = getattr(os, name); calls = [0]
                        def fault(*args, **kwargs):
                            calls[0] += 1
                            hit = (failure == "parent_open" or failure == "child_open" and args[0] == root.name
                                or failure == "child_fsync" and calls[0] == 1 or failure == "parent_fsync" and calls[0] == 2)
                            if hit: raise OSError("synthetic init fault")
                            return actual(*args, **kwargs)
                        with patch.object(orchestrator.os, name, fault):
                            return original(root, identity)
                return original(root, identity)
            with self.subTest(failure=failure):
                (code, result, _), factories, launches, _ = self.run_fixture(f, _bounded_cli_jobs=initialize)
                self.assertEqual(code, 2); self.assertEqual(seen, ["opened"]); self.assertFalse(factories); self.assertFalse(launches)
                f.reload(); self.assertEqual(f.item["status"], "ready")

    def test_bounded_cli_captured_cycle_refuses_mutation_before_next_observation(self):
        original = orchestrator._observe_cycle_inputs
        for value in [None, "wrong", "b" * 32, "missing"]:
            f = self.fixture(); calls = []
            def observe(pins, frozen, checkpoint, operation):
                calls.append(checkpoint)
                result = original(pins, frozen, checkpoint, operation)
                if checkpoint == "entry":
                    if value == "missing": frozen.pop("cycle_id")
                    else: frozen["cycle_id"] = value
                return result
            with self.subTest(value=value):
                (code, result, _), factories, launches, _ = self.run_fixture(f, _observe_cycle_inputs=observe)
                self.assertEqual(code, 2); self.assertEqual(calls, ["entry"]); self.assertFalse(launches); self.assertFalse(factories)

    def test_bounded_cli_failed_goal_stops_before_rollup(self):
        f = self.fixture()
        (code, result, _), _, launches, _ = self.run_fixture(f, verdict="fail")
        self.assertEqual(code, 2); self.assertEqual(len(launches), 4)
        f.reload(); self.assertNotEqual(f.item["status"], "done")
        self.assertNotIn("evidence-rollup", f.item["result"]["evidence"]["completed_roles"])

    def test_bounded_cli_declared_resume_and_prior_cycle_refusal(self):
        f = self.fixture(); f.declared_resume()
        (code, result, error), _, launches, _ = self.run_fixture(f)
        self.assertEqual(code, 0, (result, error)); self.assertEqual(len(launches), 4)
        f.reload(); self.assertEqual(f.item["workflow_runs"][-1]["team_run"]["run_id"], "preexisting-logical-run")
        # A fresh invocation cannot reconstruct the previous process-held closure witness.
        (code, result, _), _, launches, _ = self.run_fixture(f)
        self.assertEqual(code, 2); self.assertFalse(launches)

    def test_bounded_cli_two_real_providers_one_queue_single_claim(self):
        from unittest.mock import patch
        f = self.fixture(); provider_type = orchestrator.atlas_work_items.AtlasWorkItemOperationProvider
        competitor = provider_type(orchestrator.atlas_work_items.AtlasWorkItemStore(f.queue), claimed_by="competing-owner")
        stale = competitor.ready_operations()[0]
        original = provider_type.claim; calls = []; competing = []
        def claim(provider, operation):
            if provider is not competitor and not competing:
                competing.append(original(competitor, stale))
            result = original(provider, operation); calls.append((provider, result)); return result
        with patch.object(provider_type, "claim", claim):
            (code, result, _), factories, launches, _ = self.run_fixture(f)
        self.assertIsNotNone(competing[0]); self.assertEqual(len(calls), 1); self.assertIsNone(calls[0][1])
        self.assertFalse(factories); self.assertFalse(launches)
        self.assertEqual(result["counters"]["claims_reserved"], 1)
        f.reload(); self.assertEqual(f.item["claim"]["claimed_by"], "competing-owner"); self.assertNotIn("result", f.item)

    def test_bounded_cli_dependency_chain_and_new_item_exclusion(self):
        f = self.fixture(); second = copy.deepcopy(f.item); second.update(id="work/second", operation_id="operation:second")
        second["scheduler"]["depends_on"] = [f.source_id]
        f.payload["work_items"].append(second); f.pins["admitted_item_ids"].append(second["id"])
        f.write_queue(); f.repin()
        def inject(count, kwargs):
            if count == 1:
                payload = json.loads(f.queue.read_text()); extra = copy.deepcopy(f.item)
                extra.update(id="new/unadmitted", operation_id="new:operation")
                payload["work_items"].append(extra); f.queue.write_text(json.dumps(payload))
        (code, result, error), _, launches, _ = self.run_fixture(f,
            argv=self.argv(f, **{"atlas-role-max": 5, "atlas-max-roles": 10}), hook=inject)
        self.assertEqual(code, 0, (result, error)); self.assertEqual(len(launches), 2)
        states = {item["id"]: item["status"] for item in json.loads(f.queue.read_text())["work_items"]}
        self.assertEqual(states, {f.source_id: "done", second["id"]: "done", "new/unadmitted": "ready"})

    def test_bounded_cli_real_controller_lock_loser_leaves_no_jobs_orphan(self):
        import subprocess
        f = self.fixture()
        key = hashlib.sha256(str(f.queue).encode()).hexdigest(); state = f.queue.parent / ".atlas-supervisor" / key
        state.mkdir(parents=True)
        # A finite child holds the exact OS lock while the real bounded entry attempts it.
        script = "import fcntl,sys; f=open(sys.argv[1],'a+b'); fcntl.flock(f,fcntl.LOCK_EX); print('held',flush=True); sys.stdin.readline()"
        child = subprocess.Popen([sys.executable, "-c", script, str(state / "controller.lock")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "held")
            (code, result, _), factories, launches, _ = self.run_fixture(f)
            self.assertEqual(code, 2, result); self.assertFalse(factories); self.assertFalse(launches)
            self.assertEqual(list(state.glob("*.jobs")), [])
        finally:
            child.communicate("release\n", timeout=5)
        self.assertEqual(child.returncode, 0)

    def test_bounded_cli_source_location_canonical_positive_and_copied_driver_refusal(self):
        from unittest.mock import patch
        original = orchestrator._bounded_cli_runtime
        self.assertEqual(original(), ROOT)
        f = self.fixture(); runtime = f.runtime / "templates/local-automation-runtime"
        with patch.object(orchestrator, "__file__", str(runtime / "atlas-agent-orchestrator")), patch.object(orchestrator.common, "RUNTIME_DIR", runtime):
            (code, result, error), _, launches, _ = self.run_fixture(f, _bounded_cli_runtime=original)
        self.assertEqual(code, 0, (result, error)); self.assertEqual(len(launches), 5)
        for driver in [f.root / "copied-driver.py", ROOT / "renamed-orchestrator"]:
            with self.subTest(driver=driver), patch.object(orchestrator, "__file__", str(driver)):
                with self.assertRaises(ValueError): original()

    def test_bounded_cli_partial_final_allowance_and_explicit_selectors(self):
        f = self.fixture()
        argv = self.argv(f, **{"atlas-role-max": 2, "atlas-max-roles": 5, "team-templates": str(f.templates),
            "agent-registry": str(f.registry), "agent-root": str(f.agent_root), "atlas-worker-termination-grace-seconds": 0})
        (code, result, error), factories, launches, _ = self.run_fixture(f, argv=argv)
        self.assertEqual(code, 0, (result, error)); self.assertEqual(len(launches), 3)
        self.assertEqual([command[-1] for command, _ in factories], ["2", "2", "1"])
        self.assertEqual(result["counters"]["roles_reserved"], 5)

    def test_bounded_cli_raw_separated_options_and_explicit_default_role_max(self):
        f = self.fixture(); argv = []
        for option in self.argv(f, **{"atlas-role-max": 100, "atlas-max-roles": 5}):
            argv.extend(option.split("=", 1))
        (code, result, error), factories, launches, _ = self.run_fixture(f, argv=argv)
        self.assertEqual(code, 0, (result, error)); self.assertEqual(len(launches), 1)
        self.assertEqual(factories[0][0][-1], "5")  # A1 allowance, not the declared 100.

    def test_bounded_cli_input_cycle_mutation_refuses_before_guard_reads(self):
        original = orchestrator._run_bounded_cycle
        observed = orchestrator._observe_cycle_inputs
        for value in [None, "wrong", "b" * 32, "missing"]:
            f = self.fixture(); calls = []
            def adapter(inputs, **kwargs):
                if value == "missing": inputs.pop("cycle_id")
                else: inputs["cycle_id"] = value
                # Exercise the captured boundary directly; don't give corrupt inputs to A3.
                frame = kwargs["guard"]("entry", None)
                self.assertEqual(frame, {"changed": True, "reason": "input_changed", "head_changed": False, "trusted_expectation": None})
                return {"terminal_outcome": "input_changed", "unresolved": False}
            def observe(*args): calls.append(args); return observed(*args)
            with self.subTest(value=value):
                (code, result, _), factories, launches, _ = self.run_fixture(f, _run_bounded_cycle=adapter, _observe_cycle_inputs=observe)
                self.assertEqual(code, 2); self.assertFalse(calls); self.assertFalse(launches); self.assertFalse(factories)

    def test_bounded_cli_before_read_resume_admission_no_foreign_content(self):
        original = orchestrator._cycle_guard_read
        for mutation in ["undeclared", "symlink", "missing"]:
            f = self.fixture(); path = f.declared_resume(); forbidden = f.root / "foreign.json"
            forbidden.write_text(path.read_text())
            if mutation == "undeclared":
                f.item["workflow_runs"][0]["artifacts"]["team_run_path"] = str(forbidden); f.write_queue()
            elif mutation == "symlink":
                path.unlink(); path.symlink_to(forbidden)
            else: path.unlink()
            reads = []
            def read(value):
                if str(value) == str(forbidden): raise AssertionError("foreign content read before admission")
                reads.append(str(value)); return original(value)
            with self.subTest(mutation=mutation):
                (code, result, _), factories, launches, _ = self.run_fixture(f, _cycle_guard_read=read)
                self.assertEqual(code, 2); self.assertFalse(launches); self.assertFalse(factories)
                self.assertNotIn(str(forbidden), reads)

    def test_bounded_cli_guard_admits_all_template_candidates_before_content(self):
        f = self.fixture(); extra = f.templates / "new.json"; extra.write_text("untrusted content")
        original = orchestrator._cycle_guard_read; reads = []
        def read(path):
            reads.append(path)
            if str(path) in {str(extra), str(f.template_path)}: raise AssertionError("template read before membership admission")
            return original(path)
        (code, result, _), _, launches, _ = self.run_fixture(f, _cycle_guard_read=read)
        self.assertEqual(code, 2); self.assertFalse(launches)
        self.assertNotIn(str(extra), reads); self.assertNotIn(str(f.template_path), reads)

    def test_bounded_cli_root_inode_replacement_refuses_without_reinitialization(self):
        f = self.fixture(); original = orchestrator._bounded_cli_jobs; calls = []
        def jobs(root, identity=None):
            calls.append(identity)
            result = original(root, identity)
            if identity is None:
                root.rename(root.with_suffix(".displaced")); root.mkdir()
            return result
        (code, result, _), factories, launches, _ = self.run_fixture(f, _bounded_cli_jobs=jobs)
        self.assertEqual(code, 2); self.assertFalse(launches); self.assertFalse(factories)
        self.assertEqual(sum(value is None for value in calls), 1)

    def test_bounded_cli_deadline_worker_construction_charged_no_process(self):
        from unittest.mock import patch
        f = self.fixture(); now = [1.0]
        worker = orchestrator.atlas_work_items.LocalCommandOperationWorker
        original = worker.__init__
        def initialize(instance, *args, **kwargs):
            result = original(instance, *args, **kwargs); now[0] = 200.0; return result
        with patch.object(worker, "__init__", initialize), patch.object(orchestrator.time, "monotonic", lambda: now[0]):
            (code, result, error), factories, launches, _ = self.run_fixture(f)
        self.assertEqual(result["terminal_outcome"], "cancelled", (result, error)); self.assertFalse(launches)
        f.reload(); self.assertTrue(f.item["result"]["evidence"]["supervisor_no_launch"])
        self.assertEqual(result["counters"]["roles_reserved"], 1)

    def test_bounded_cli_signal_during_worker_preserves_original_uncertainty(self):
        import signal
        original = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        f = self.fixture()
        def stop(count, kwargs): signal.raise_signal(signal.SIGTERM)
        (code, result, error), _, launches, _ = self.run_fixture(f, hook=stop)
        self.assertEqual(code, 2); self.assertEqual(len(launches), 1)
        f.reload(); self.assertEqual(f.item["status"], "blocked")
        self.assertFalse(f.item["result"]["evidence"]["invocation_completed"])
        self.assertEqual(f.item["process_uncertainty"]["status"], "unresolved")
        self.assertTrue(result["unresolved"]); self.assertIsNone(result["closure_witness"])
        self.assertEqual({sig: signal.getsignal(sig) for sig in original}, original)

    def test_bounded_cli_stop_created_during_preflight_prevents_claim(self):
        f = self.fixture(); original = orchestrator._observe_cycle_inputs
        def observe(pins, frozen, checkpoint, operation):
            frame = original(pins, frozen, checkpoint, operation)
            if checkpoint == "entry": (f.root / "stop").touch()
            return frame
        (code, result, error), factories, launches, _ = self.run_fixture(f, _observe_cycle_inputs=observe)
        self.assertEqual(result["terminal_outcome"], "cancelled", (result, error)); self.assertFalse(factories); self.assertFalse(launches)
        self.assertEqual(result["counters"]["claims_reserved"], 0)


    def test_bounded_cli_unknown_result_ack_preserves_once_and_releases_lock(self):
        from unittest.mock import patch
        import fcntl, os
        f = self.fixture(); provider = orchestrator.atlas_work_items.AtlasWorkItemOperationProvider
        original = provider.record_result; calls = []
        def record(instance, operation, result):
            calls.append(copy.deepcopy(result.to_dict()))
            original(instance, operation, result)
            raise OSError("lost returned acknowledgment")
        with patch.object(provider, "record_result", record):
            (code, result, error), factories, launches, _ = self.run_fixture(f)
        self.assertEqual(code, 2); self.assertEqual(len(calls), 1); self.assertEqual(len(launches), 1)
        f.reload(); self.assertEqual(f.item["result"], calls[0]); self.assertTrue(result["unresolved"])
        self.assertEqual(result["failure"], "result_unknown"); self.assertIsNone(result["closure_witness"])
        lock = next((f.root / ".atlas-supervisor").glob("*/controller.lock"))
        fd = os.open(lock, os.O_RDWR)
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally: os.close(fd)

    def test_bounded_cli_stop_inspection_permission_failure_is_latched(self):
        from unittest.mock import patch
        f = self.fixture(); token = orchestrator._BoundedCliCancellation(str(f.root / "stop"))
        with patch.object(orchestrator, "_cycle_guard_open", side_effect=PermissionError("uninspectable")) as opening:
            for _ in range(2):
                with self.assertRaises(PermissionError): token.is_set()
            self.assertEqual(opening.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class RecoveryAdapterHarness(CycleAdapterHarness):
    """Synthetic adapter effects with the actual strict temp-file v2 journal."""
    def __init__(self, testcase, **kwargs):
        import tempfile
        super().__init__(**kwargs)
        temporary = tempfile.TemporaryDirectory(prefix="atlas-recovery-adapter-")
        testcase.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs.update(queue_path=str(self.root / "queue.json"), pins_path=str(self.root / "pins.json"))
        Path(self.inputs["queue_path"]).write_text('{"work_items":[]}')
        self.inputs["limits"]["stop_file"] = str(self.root / "stop")
        self.provider = self.Provider(self)
        self.provider.store.path = Path(self.inputs["queue_path"])
        immutable, static = {}, {}
        for sid in self.ids:
            operation = self.provider.project(self.rows[sid], self.rows)
            immutable[sid] = orchestrator._cycle_guard_immutable(operation.to_dict(), [])
            _, expected = result_assessment_fixture([], [])
            expected.update(source_id=sid, work_item_id=sid, operation_id=operation.operation_id)
            static[sid] = {key: value for key, value in expected.items() if key not in {"run_id", "completed_roles_before"}}
        self.snapshot = {"input_digests": {"/work/template.json": "a" * 64}, "template_candidates": ["/work/template.json"],
            "runtime_head": "b" * 40, "execution_heads": {"/work/repo": "c" * 40}, "entry_changes": {"/work/repo": []},
            "immutable_inputs": immutable, "expected_static": static}
        pins = pins_fixture()
        pins.update(queue_path=self.inputs["queue_path"], admitted_item_ids=sorted(self.ids), item_closure=[{
            "item_id": sid, "operation_id": immutable[sid]["operation_id"], "execution_checkout": "/work/repo", "depends_on": [],
            "immutable_sha256": orchestrator.atlas_work_items.content_hash(immutable[sid])} for sid in self.ids])
        self.journal = orchestrator._RecoverableCycleJournal(self.inputs["queue_path"], pins, self.inputs["pins_raw_sha256"],
            self.inputs["limits"], cycle_id=self.inputs["cycle_id"], acknowledged_closures={}, controller_epoch="d" * 32,
            origin={"boot_id": "12345678-1234-1234-1234-123456789abc", "entry_monotonic": self.inputs["entry_monotonic"],
                    "pins_path": self.inputs["pins_path"]})
        testcase.addCleanup(self.journal.release)
        self.factory_calls, self.factory_transform = [], None
        # Keep every real write/flush/fsync and add only test observation hooks.
        append = self.journal._append
        def hooked(row, **kwargs):
            self.hit("journal:" + row["event"])
            if self.fail_event == row["event"] and not self.fail_after_event:
                self.journal._poisoned = True
                raise OSError("synthetic pre-append failure")
            append(row, **kwargs)
            self.events.append(copy.deepcopy(self.journal._events[-1]))
            if self.fail_event == row["event"]:
                self.journal._poisoned = True
                raise OSError("synthetic lost append return")
        self.journal._append = hooked

    class Provider(CycleAdapterHarness.Provider):
        def project(self, item, by_id):
            operation = super().project(item, by_id)
            return orchestrator.atlas_work_items.OperationState(**(operation.to_dict() | {
                "execution_repo": "/work/repo", "write_scope": ["file.txt"]}))
        def claim(self, operation):
            held = super().claim(operation)
            if held is not None:
                self.h.rows[operation.source_id]["claim"]["pid"] = 123
            return held

    def capsule_factory(self, *, progress_by_item, done_ids, cancellation, disposition, settlement):
        self.hit("capsule_factory")
        values = copy.deepcopy({"progress_by_item": progress_by_item, "done_ids": done_ids, "cancellation": cancellation,
            "disposition": disposition, "settlement": settlement})
        self.factory_calls.append(values)
        result = values | {"source_snapshot": copy.deepcopy(self.snapshot), "jobs_identity": None}
        return self.factory_transform(result) if self.factory_transform else result

    def run(self):
        return orchestrator._run_bounded_cycle(self.inputs, provider=self.provider, worker_factory=self.worker_factory,
            monotonic=self.clock, cancellation=self.cancellation, journal=self.journal, guard=self.guard,
            recovery_capsule_factory=self.capsule_factory)

    def history(self):
        receipt = self.root / ".atlas-supervisor" / hashlib.sha256(self.inputs["queue_path"].encode()).hexdigest() / (self.inputs["cycle_id"] + ".jsonl")
        return orchestrator._decode_cycle_receipt_v2(receipt.read_bytes())


class RecoveryAdapterTests(unittest.TestCase):
    def test_recovery_adapter_fresh_staged_progress_exact_capsules_and_v2_reservations(self):
        h = RecoveryAdapterHarness(self)
        before = []
        h.hooks["journal:claim_settled"] = lambda h: before.append(copy.deepcopy(h.inputs["progress_by_item"]))
        result = h.run()
        self.assertEqual(result["terminal_outcome"], "completed", result)
        self.assertFalse(result["unresolved"])
        self.assertIsNotNone(result["closure_witness"])
        self.assertEqual(result["counters"], {"steps": 6, "claims_reserved": 5, "roles_reserved": 5, "observed_completed_roles": 5})
        self.assertEqual(len(h.factory_calls), 1)
        self.assertEqual(h.trace.index("guard:entry") < h.trace.index("journal:opened") < h.trace.index("capsule_factory"), True)
        self.assertEqual(h.trace.index("journal:recovery_ready") < h.trace.index("journal:step_reserved") < h.trace.index("guard:before_step"), True)
        events = h.history()
        self.assertEqual(events[0]["recovery_state"], None)
        self.assertEqual(events[1]["event"], "recovery_ready")
        identity = events[1]["recovery_state"]["jobs_identity"]
        self.assertIsNotNone(identity)
        for index, row in enumerate(events):
            if row["event"] == "step_reserved":
                previous = events[index - 1]
                self.assertEqual(row["counters"]["steps"], previous["counters"]["steps"] + 1)
                for key in set(orchestrator._CycleJournal._IDENTITY) | {"effects"}:
                    self.assertEqual(row[key], previous[key])
                self.assertEqual(events[index + 1]["counters"], row["counters"])
            if row["recovery_state"] is not None:
                self.assertEqual(row["recovery_state"]["source_snapshot"], h.snapshot)
                self.assertEqual(row["recovery_state"]["jobs_identity"], identity)
        settlements = [row for row in events if row["event"] == "claim_settled"]
        for index, row in enumerate(settlements):
            cap = row["recovery_state"]
            self.assertEqual(len(before[index]["work/123"]["completed_roles"]), index)
            self.assertEqual(len(cap["progress_by_item"]["work/123"]["completed_roles"]), index + 1)
            self.assertEqual(cap["settlement"]["result"], h.results[index][1])
            self.assertEqual(cap["settlement"]["trusted_expectation"]["completed_roles_before"], before[index]["work/123"]["completed_roles"])
        self.assertEqual(events[-1]["recovery_state"], events[-2]["recovery_state"])
        self.assertEqual(events[-1]["recovery_state"]["settlement"], settlements[-1]["recovery_state"]["settlement"])
        self.assertEqual(events[-1]["recovery_state"]["disposition"], {"action": "halt", "reason": "completed", "outcome": "completed"})
        self.assertEqual(set(result), {"terminal_outcome", "unresolved", "counters", "elapsed_seconds", "closure_witness", "progress_by_item", "failure"})

    def test_recovery_adapter_factory_exact_fields_and_no_live_mutation(self):
        for key in ("progress_by_item", "done_ids", "cancellation", "disposition", "settlement", "jobs_identity", "source_snapshot", "extra", "live"):
            with self.subTest(key=key):
                h = RecoveryAdapterHarness(self)
                def change(cap):
                    if key == "live": h.inputs["progress_by_item"]["work/123"]["run_id"] = "mutated"
                    elif key == "extra": cap["extra"] = None
                    elif key == "source_snapshot": cap[key]["runtime_head"] = "invalid"
                    else: cap[key] = {"bad": True}
                    return cap
                h.factory_transform = change
                result = h.run()
                self.assertEqual(result["failure"], "invalid_result", result)
                self.assertEqual((h.claim_count, h.worker_count, h.record_count), (0, 0, 0))
                self.assertEqual([row["event"] for row in h.history()], ["opened", "terminal", "closed"])
                self.assertTrue(all(row["recovery_state"] is None for row in h.history()))
                self.assertEqual(result["progress_by_item"], {"work/123": {"run_id": None, "completed_roles": []}})
                self.assertEqual(h.inputs["progress_by_item"], result["progress_by_item"])
                self.assertFalse(any(path.name.endswith(".jobs") for path in h.root.rglob("*")))

    def test_recovery_adapter_pre_ready_stop_deadline_and_factory_clock_are_terminal_without_root(self):
        for mode in ("stop", "deadline", "factory_stop", "factory_deadline", "factory_clock"):
            with self.subTest(mode=mode):
                h = RecoveryAdapterHarness(self)
                if mode == "stop": h.cancelled = True
                if mode == "deadline": h.now = 130
                if mode.startswith("factory_"):
                    def factory_hook(h):
                        if mode == "factory_stop": h.cancelled = True
                        elif mode == "factory_deadline": h.now = 130
                        else: h.now = float("nan")
                    h.hooks["capsule_factory"] = factory_hook
                result = h.run()
                self.assertEqual(result["failure"], "invalid_result" if mode == "factory_clock" else "deadline" if "deadline" in mode else "stop", result)
                self.assertEqual((h.claim_count, h.worker_count), (0, 0))
                self.assertNotIn("recovery_ready", [row["event"] for row in h.history()])
                self.assertTrue(all(row["recovery_state"] is None for row in h.history()))

    def test_recovery_adapter_ack_loss_does_not_install_or_run_next_guard(self):
        for name in ("recovery_ready", "step_reserved", "claim_settled"):
            for after in (False, True):
                with self.subTest(name=name, after=after):
                    h = RecoveryAdapterHarness(self)
                    h.fail_event, h.fail_after_event = name, after
                    result = h.run()
                    self.assertEqual(result["failure"], "receipt_unknown", result)
                    self.assertTrue(result["unresolved"]); self.assertIsNone(result["closure_witness"])
                    self.assertEqual(h.inputs["progress_by_item"]["work/123"]["completed_roles"], [])
                    events = h.history()
                    self.assertEqual(events[-1]["event"], name if after else {"recovery_ready": "opened", "step_reserved": "recovery_ready", "claim_settled": "result_acknowledged"}[name])
                    if name == "step_reserved":
                        self.assertNotIn("guard:before_step", h.trace)
                        self.assertEqual(result["counters"]["steps"], 0)
                    self.assertEqual(h.worker_count, int(name == "claim_settled"))
                    if name == "claim_settled" and after:
                        self.assertEqual(events[-1]["recovery_state"]["progress_by_item"]["work/123"]["completed_roles"], ["implementation"])

    def test_recovery_adapter_settlement_installs_before_late_stop_and_keeps_full_terminal(self):
        for mode in ("late_stop", "late_deadline", "after_worker_stop", "after_worker_drift", "before_step_drift", "no_launch"):
            with self.subTest(mode=mode):
                h = RecoveryAdapterHarness(self)
                if mode.startswith("late_"):
                    def late(h):
                        # Runs before the real append; patch is already computed.
                        if mode == "late_stop": h.cancelled = True
                        else: h.now = 130
                    h.hooks["journal:claim_settled"] = late
                if mode == "after_worker_stop": h.hooks["worker_return"] = lambda h: setattr(h, "cancelled", True)
                if mode in {"after_worker_drift", "before_step_drift"}:
                    h.guard_transform = lambda h, point, frame: frame | ({"changed": True, "reason": "input_changed"} if point == ("after_worker" if mode == "after_worker_drift" else "before_step") else {})
                    if mode == "after_worker_drift":
                        h.guard_transform = lambda h, point, frame: ({"changed": True, "reason": "input_changed", "head_changed": False, "trusted_expectation": None} if point == "after_worker" else frame)
                if mode == "no_launch": h.hooks["journal:claimed"] = lambda h: setattr(h, "cancelled", True)
                result = h.run(); events = h.history()
                self.assertFalse(result["unresolved"], result)
                self.assertIsNotNone(result["closure_witness"])
                cap = events[-1]["recovery_state"]
                self.assertEqual(cap, events[-2]["recovery_state"])
                wanted = [] if mode in {"before_step_drift", "no_launch"} else ["implementation"]
                self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], wanted)
                self.assertEqual(cap["progress_by_item"], result["progress_by_item"])
                self.assertEqual(cap["disposition"]["action"], "halt")
                if mode == "no_launch":
                    self.assertFalse(cap["settlement"]["result"]["evidence"].get("process_invocation_id"))
                    self.assertEqual(result["counters"]["roles_reserved"], 0)
                    self.assertEqual(cap["settlement"]["assessment"], {"decision": "stop", "reason": None, "new_completed_roles": []})

    def test_recovery_adapter_healthy_jobs_accessor_works_at_reserved_null_capsule_then_refuses_release(self):
        h = RecoveryAdapterHarness(self)
        identities = []
        def before_step(h):
            self.assertEqual(h.journal._events[-1]["event"], "step_reserved")
            self.assertIsNone(h.journal._events[-1]["recovery_state"])
            identity = h.journal.owned_jobs_identity()
            identities.append(copy.deepcopy(identity)); identity["inode"] = -1
            self.assertEqual(h.journal.owned_jobs_identity(), identities[-1])
        h.hooks["guard:before_step"] = before_step
        self.assertEqual(h.run()["terminal_outcome"], "completed")
        self.assertEqual(len(identities), 6)
        self.assertTrue(all(value == identities[0] for value in identities))
        with self.assertRaises(ValueError): h.journal.owned_jobs_identity()


    def test_recovery_adapter_protocol_completed_requires_every_admitted_done_item(self):
        complete = sorted(role["role_id"] for role in RESULT_ROLES)
        for label, kwargs, done in (("ready_false", {}, []), ("partial_false", {"settle": True}, []),
                                  ("complete_missing_done", {"baseline": complete}, []),
                                  ("complete_baseline", {"baseline": complete}, ["work/123"]),
                                  ("complete_settled", {"settle": True, "completed": complete}, ["work/123"])):
            with self.subTest(label=label):
                events = recovery_protocol_history(**kwargs)
                cap = copy.deepcopy(events[-1]["recovery_state"])
                cap.update(done_ids=done, disposition={"action": "halt", "reason": "completed", "outcome": "completed"})
                terminal = recovery_protocol_append(events, "terminal", controller_reason="completed", terminal_outcome="completed", recovery_state=cap)
                for closed in (False, True):
                    if closed: recovery_protocol_append(events, "closed", elapsed_seconds=terminal["elapsed_seconds"], recovery_state=copy.deepcopy(cap))
                    raw = b"".join(orchestrator._CycleJournal._line(row) for row in events)
                    if done:
                        self.assertEqual(orchestrator._validate_recovery_candidate(raw,
                            boot_id=events[0]["origin"]["boot_id"], monotonic=120)["status"], "report_only")
                    else:
                        with self.assertRaisesRegex(ValueError, "completed terminal lacks every admitted done item"):
                            orchestrator._decode_cycle_receipt_v2(raw)

    def test_recovery_adapter_trust_false_completed_history_refuses_before_any_role_or_provider(self):
        from unittest.mock import patch
        for stages in (0, 1):
            with self.subTest(stages=stages):
                helper = RecoveryTrustTests(); self.addCleanup(helper.doCleanups)
                f, journal, live = helper.fixture(stages=stages)
                path = f.jobs.parent / (f.frozen["cycle_id"] + ".jsonl")
                events = copy.deepcopy(journal._events)
                cap = copy.deepcopy(events[-1]["recovery_state"])
                cap["disposition"] = {"action": "halt", "reason": "completed", "outcome": "completed"}
                terminal = recovery_protocol_append(events, "terminal", controller_reason="completed", terminal_outcome="completed", recovery_state=cap)
                recovery_protocol_append(events, "closed", elapsed_seconds=terminal["elapsed_seconds"], recovery_state=copy.deepcopy(cap))
                journal.release(); path.write_bytes(b"".join(orchestrator._CycleJournal._line(row) for row in events))
                raw = path.read_bytes()
                with patch.object(orchestrator.atlas_work_items.AtlasWorkItemOperationProvider, "ready_operations", side_effect=AssertionError("no provider")), \
                     patch.object(orchestrator.atlas_work_items.LocalCommandOperationWorker, "run", side_effect=AssertionError("no role")):
                    with self.assertRaisesRegex(ValueError, "completed terminal lacks every admitted done item"):
                        orchestrator._RecoverableCycleJournal.acquire_for_recovery(str(f.queue), f.frozen["cycle_id"])
                self.assertEqual(path.read_bytes(), raw)
                self.assertIsNone(live["source_snapshot"]); self.assertEqual(live["progress_by_item"], {})

    def prepared_seed(self, *, stages=2, second=False, baseline_complete=False, acknowledge=True):
        helper = RecoveryTrustTests(); self.addCleanup(helper.doCleanups)
        f, journal, live = helper.fixture(stages=stages, second=second, baseline_complete=baseline_complete)
        cancellation = helper.Cancellation()
        validated = helper.validate(f, journal, live, cancellation=cancellation)
        self.assertEqual(validated["status"], "continuation_candidate", validated)
        seed = validated["seed"]
        if acknowledge:
            journal.acknowledge_recovery(seed.admission_patch(elapsed_seconds=21), expected_prefix_sha256=validated["observation"]["prefix_sha256"])
            restored = orchestrator._recovery_seed_state(seed, journal=journal)
            # R4b owns this exact-copy installation after acknowledgment.
            live.update(copy.deepcopy(restored["frozen"]))
            inputs = {key: copy.deepcopy(restored[key]) for key in ("queue_path", "pins_path", "pins_raw_sha256", "cycle_id", "limits", "admitted_item_ids")}
            inputs.update(entry_monotonic=restored["origin"]["entry_monotonic"], progress_by_item=live["progress_by_item"])
        else:
            restored = orchestrator._cycle_guard_json(seed._payload)
            inputs = {key: copy.deepcopy(restored[key]) for key in ("queue_path", "pins_path", "pins_raw_sha256", "cycle_id", "limits", "admitted_item_ids")}
            inputs.update(entry_monotonic=restored["origin"]["entry_monotonic"], progress_by_item=copy.deepcopy(restored["frozen"]["progress_by_item"]))
        return f, journal, live, seed, restored, inputs, cancellation

    def test_recovery_adapter_resumed_seed_restores_all_state_before_guard_and_continues_without_entry(self):
        f, journal, live, seed, restored, inputs, cancellation = self.prepared_seed()
        f.frozen = live
        guards, workers, reserved = [], [], []
        old_tail = copy.deepcopy(restored["tail_patch"])
        append = journal._append
        def appended(row, **kwargs):
            if row["event"] == "step_reserved": reserved.append(copy.deepcopy(row))
            return append(row, **kwargs)
        journal._append = appended
        def guard(point, operation):
            self.assertNotEqual(point, "entry")
            if not guards:
                self.assertEqual(journal._events[-1]["event"], "step_reserved")
                row = journal._events[-1]
                self.assertEqual(row["counters"], restored["counters"] | {"steps": restored["counters"]["steps"] + 1})
                for key in set(orchestrator._CycleJournal._IDENTITY) | {"effects"}: self.assertEqual(row[key], old_tail[key])
                self.assertEqual(live["progress_by_item"], restored["capsule"]["progress_by_item"])
            guards.append(point)
            return orchestrator._observe_cycle_inputs(f.pins, live, point, operation)
        class Worker:
            def run(inner, held, path, *, cancel_event):
                self.assertFalse(cancel_event.is_set())
                completed = live["progress_by_item"][held.source_id]["completed_roles"]
                role = len(completed); invocation = format(100 + role, "032x")
                workers.append((held.source_id, role))
                returned = f.stage(held, role, invocation=invocation)
                job = f.jobs / ("atlas-work-item-" + orchestrator.atlas_work_items.safe_id(held.source_id) + "-" + invocation)
                returned.evidence.update(job_dir=str(job), operation_path=str(job / "operation.json"), output_path=str(job / "worker-output.txt"))
                f.reload()
                item = next(row for row in f.payload["work_items"] if row["id"] == held.source_id)
                command = [str(f.runtime / "templates/local-automation-runtime/atlas-agent-role-runner"), "--command-config", str(f.config), "--max-roles", "1"]
                item["process_uncertainty"] = {"status": "unresolved", "invocation_id": invocation, "job_dir": str(job),
                    "command_sha256": hashlib.sha256(json.dumps(command).encode()).hexdigest(), "started_at": "2026-10-16T00:00:00Z"}
                f.write_queue()
                return returned
        def factory(allowance):
            self.assertEqual(allowance, 1)
            return Worker()
        def forbidden(**kwargs): raise AssertionError("resumed mode must not invoke capsule factory")
        result = orchestrator._run_bounded_cycle(inputs, provider=f.provider, worker_factory=factory, monotonic=lambda: 122,
            cancellation=cancellation, journal=journal, guard=guard, recovery_seed=seed, recovery_capsule_factory=forbidden)
        self.assertEqual(result["terminal_outcome"], "completed", result)
        self.assertFalse(result["unresolved"]); self.assertIsNotNone(result["closure_witness"])
        self.assertEqual(workers, [(f.source_id, 2), (f.source_id, 3), (f.source_id, 4)])
        self.assertEqual(result["counters"], {"steps": 6, "claims_reserved": 5, "roles_reserved": 5, "observed_completed_roles": 5})
        self.assertEqual(result["elapsed_seconds"], 22)
        self.assertTrue(seed._consumed)
        self.assertEqual([row["event"] for row in journal._events].count("opened"), 1)
        self.assertEqual([row["event"] for row in journal._events].count("recovery_ready"), 1)
        self.assertEqual(journal._events[-1]["recovery_state"], journal._events[-2]["recovery_state"])
        self.assertEqual(journal._events[-1]["recovery_state"]["source_snapshot"], restored["capsule"]["source_snapshot"])
        self.assertEqual(result["progress_by_item"][f.source_id]["run_id"], restored["capsule"]["progress_by_item"][f.source_id]["run_id"])

    def test_recovery_adapter_resumed_stop_deadline_backward_clock_preserve_spent_state_and_old_identity(self):
        for mode in ("stop", "deadline", "backward", "nan", "inspection"):
            with self.subTest(mode=mode):
                f, journal, live, seed, restored, inputs, cancellation = self.prepared_seed()
                if mode == "stop": cancellation.stopped = True
                if mode == "inspection": cancellation.error = OSError("stop failure")
                now = {"deadline": 160, "backward": 120, "nan": float("nan")}.get(mode, 122)
                def forbidden(*args, **kwargs): raise AssertionError("stopped recovered cycle must not observe source or launch")
                result = orchestrator._run_bounded_cycle(inputs, provider=f.provider, worker_factory=forbidden,
                    monotonic=lambda: now, cancellation=cancellation, journal=journal, guard=forbidden, recovery_seed=seed)
                self.assertFalse(result["unresolved"], result)
                self.assertEqual(result["counters"], restored["counters"])
                self.assertEqual(result["progress_by_item"], restored["capsule"]["progress_by_item"])
                terminal = journal._events[-2]
                for key in set(orchestrator._CycleJournal._IDENTITY) | {"effects"}: self.assertEqual(terminal[key], restored["tail_patch"][key])
                self.assertEqual(terminal["recovery_state"]["settlement"], restored["capsule"]["settlement"])
                self.assertGreaterEqual(result["elapsed_seconds"], 21)
                self.assertEqual(result["failure"], {"stop": "stop", "deadline": "deadline", "backward": "invalid_result", "nan": "invalid_result", "inspection": "stop_inspection_error"}[mode])

    def test_recovery_adapter_requires_ack_and_exact_installed_inputs_before_consuming_or_appending(self):
        for mode in ("unacknowledged", "progress", "anchor", "foreign"):
            with self.subTest(mode=mode):
                f, journal, live, seed, restored, inputs, cancellation = self.prepared_seed(acknowledge=mode != "unacknowledged")
                raw = journal._raw
                if mode == "progress": inputs["progress_by_item"][f.source_id]["completed_roles"].append("invented")
                if mode == "anchor": inputs["entry_monotonic"] = 0
                if mode == "foreign": seed = object()
                def forbidden(*args, **kwargs): raise AssertionError("no source, provider or worker call")
                with self.assertRaises(ValueError):
                    orchestrator._run_bounded_cycle(inputs, provider=f.provider, worker_factory=forbidden, monotonic=lambda: 122,
                        cancellation=cancellation, journal=journal, guard=forbidden, recovery_seed=seed)
                self.assertEqual(journal._raw, raw)
                if type(seed) is orchestrator._CycleRecoverySeed: self.assertFalse(seed._consumed)

    def test_recovery_adapter_factory_snapshot_is_copied_once_and_later_capsules_do_not_repin(self):
        h = RecoveryAdapterHarness(self)
        returned = []
        def retain(cap): returned.append(cap); return cap
        h.factory_transform = retain
        original = copy.deepcopy(h.snapshot)
        def mutate_external(h):
            returned[0]["source_snapshot"]["runtime_head"] = "e" * 40
            returned[0]["progress_by_item"]["work/123"]["run_id"] = "foreign"
            h.snapshot["runtime_head"] = "f" * 40
        h.hooks["guard:before_step"] = mutate_external
        result = h.run()
        self.assertEqual(result["terminal_outcome"], "completed", result)
        self.assertEqual(len(h.factory_calls), 1)
        for row in h.history():
            if row["recovery_state"] is not None:
                self.assertEqual(row["recovery_state"]["source_snapshot"], original)
                self.assertNotEqual(row["recovery_state"]["progress_by_item"]["work/123"]["run_id"], "foreign")

    def test_recovery_adapter_uncertain_effects_keep_only_last_accepted_capsule_and_never_close(self):
        for mode in ("worker_error", "result_error", "unresolved_marker", "roles_exceed_allowance", "factory_error"):
            with self.subTest(mode=mode):
                h = RecoveryAdapterHarness(self)
                if mode in {"worker_error", "result_error", "factory_error"}:
                    def fail(h): raise OSError("synthetic effect failure")
                    h.hooks[{"worker_error": "worker", "result_error": "record", "factory_error": "factory"}[mode]] = fail
                if mode == "unresolved_marker":
                    h.hooks["record_applied"] = lambda h: h.rows["work/123"]["process_uncertainty"].update(status="unresolved")
                if mode == "roles_exceed_allowance":
                    def excess(h, raw, token):
                        changed, _ = result_assessment_fixture(["implementation", "test-runner"], ["implementation", "test-runner"])
                        changed["evidence"]["team_run"]["run_id"] = raw["evidence"]["team_run"]["run_id"]
                        return changed
                    h.worker_transform = excess
                result = h.run(); events = h.history()
                if mode == "factory_error":
                    self.assertFalse(result["unresolved"], result)
                    self.assertEqual(result["failure"], "invalid_result")
                    self.assertEqual(events[-1]["event"], "closed")
                    self.assertEqual(events[-1]["recovery_state"]["settlement"]["assessment"]["new_completed_roles"], [])
                else:
                    self.assertTrue(result["unresolved"], result)
                    self.assertIsNone(result["closure_witness"])
                    self.assertEqual(events[-1]["event"], "terminal")
                    self.assertIsNone(events[-1]["recovery_state"]["settlement"])
                self.assertEqual(result["progress_by_item"]["work/123"]["completed_roles"], [])
                self.assertEqual(events[-1]["recovery_state"]["progress_by_item"], result["progress_by_item"])

    def test_recovery_adapter_resumed_complete_baseline_skips_claim_and_keeps_zero_role_charge(self):
        f, journal, live, seed, restored, inputs, cancellation = self.prepared_seed(stages=0, baseline_complete=True)
        counts = restored["counters"]
        self.assertEqual(counts, dict.fromkeys(("steps", "claims_reserved", "roles_reserved", "observed_completed_roles"), 0))
        calls = []
        def guard(point, operation):
            self.assertNotEqual(point, "entry"); calls.append(point)
            return orchestrator._observe_cycle_inputs(f.pins, live, point, operation)
        def forbidden(*args, **kwargs): raise AssertionError("complete baseline must never claim/launch/record")
        from unittest.mock import patch
        with patch.object(f.provider, "claim", side_effect=forbidden), patch.object(f.provider, "record_result", side_effect=forbidden):
            result = orchestrator._run_bounded_cycle(inputs, provider=f.provider, worker_factory=forbidden,
                monotonic=lambda: 122, cancellation=cancellation, journal=journal, guard=guard, recovery_seed=seed)
        self.assertEqual(result["terminal_outcome"], "completed", result)
        self.assertFalse(result["unresolved"])
        self.assertEqual(result["counters"], counts | {"steps": 1})
        self.assertEqual(journal._events[-1]["recovery_state"]["done_ids"], [f.source_id])
        self.assertIsNone(journal._events[-1]["recovery_state"]["settlement"])
        self.assertEqual(result["progress_by_item"], restored["capsule"]["progress_by_item"])

    def test_recovery_adapter_owned_jobs_accessor_refuses_replacement_and_poisoned_owner(self):
        for mode in ("replaced", "poisoned"):
            with self.subTest(mode=mode):
                h = RecoveryAdapterHarness(self)
                def before_step(h):
                    identity = h.journal.owned_jobs_identity()
                    jobs = h.root / ".atlas-supervisor" / hashlib.sha256(h.inputs["queue_path"].encode()).hexdigest() / (h.inputs["cycle_id"] + ".jobs")
                    if mode == "replaced":
                        jobs.rename(jobs.with_suffix(".moved")); jobs.mkdir()
                    else: h.journal._poisoned = True
                    with self.assertRaises(ValueError): h.journal.owned_jobs_identity()
                    self.assertGreater(identity["inode"], 0)
                h.hooks["guard:before_step"] = before_step
                result = h.run()
                self.assertEqual(result["failure"], "receipt_unknown", result)
                self.assertTrue(result["unresolved"])
                self.assertEqual(h.worker_count, 0)


class RecoveryCliTests(unittest.TestCase):
    """Cold CLI composition with real finite role subprocesses, in one test host."""
    def fixture(self):
        helper = BoundedCliTests(); self.addCleanup(helper.doCleanups)
        return helper, helper.fixture()

    def argv(self, helper, f, *, cycle=None, **changes):
        return helper.argv(f, **changes) + ["--atlas-recoverable"] + (["--atlas-resume-cycle=" + cycle] if cycle else [])

    def clock(self, value):
        from types import SimpleNamespace
        return SimpleNamespace(monotonic=value if callable(value) else lambda: value)

    def receipt(self, f):
        receipts = list((f.root / ".atlas-supervisor").rglob("*.jsonl"))
        self.assertEqual(len(receipts), 1)
        return receipts[0]

    def cold(self, *, stages=1, frontier="claim_settled"):
        from unittest.mock import patch
        helper, f = self.fixture()
        actual, seen = orchestrator._RecoverableCycleJournal._append, []
        def interrupt(journal, row, **kwargs):
            actual(journal, row, **kwargs)
            if row["event"] == frontier:
                seen.append(row["event"])
                if len(seen) == stages:
                    raise SystemExit(73)  # Simulates abrupt loss before volatile install.
        with patch.object(orchestrator._RecoverableCycleJournal, "_append", interrupt):
            (code, result, error), _, launches, _ = helper.run_fixture(f, argv=self.argv(helper, f), time=self.clock(100))
        self.assertEqual(code, 73, (result, error))
        self.assertIsNone(result)
        receipt = self.receipt(f)
        events = orchestrator._decode_cycle_receipt_v2(receipt.read_bytes())
        self.assertEqual(events[-1]["event"], frontier)
        return helper, f, receipt, events, launches

    def test_recovery_cli_fresh_five_roles_exact_factory_and_jobs_order(self):
        helper, f = self.fixture(); calls = []
        original = orchestrator._bounded_cli_jobs
        def jobs(root, identity=None):
            self.assertIsNotNone(identity, "v2 must verify journal-owned root, never mkdir twice")
            receipt = next(root.parent.glob("*.jsonl"))
            events = orchestrator._decode_cycle_receipt_v2(receipt.read_bytes())
            calls.append(events[-1]["event"])
            self.assertEqual((root.stat().st_dev, root.stat().st_ino), identity)
            return original(root, identity)
        (code, result, error), factories, launches, _ = helper.run_fixture(f,
            argv=self.argv(helper, f), time=self.clock(100), _bounded_cli_jobs=jobs)
        self.assertEqual(code, 0, (result, error))
        self.assertEqual(result["terminal_outcome"], "completed")
        self.assertEqual(len(launches), 5); self.assertEqual(len(factories), 5)
        self.assertIn("step_reserved", calls)
        events = orchestrator._decode_cycle_receipt_v2(self.receipt(f).read_bytes())
        self.assertEqual(events[0]["origin"], {"boot_id": orchestrator._bounded_cli_boot_id(), "entry_monotonic": 100,
            "pins_path": str(f.pins_path)})
        self.assertEqual(events[1]["event"], "recovery_ready")
        self.assertEqual(events[-1]["event"], "closed")
        self.assertEqual(events[-1]["recovery_state"], events[-2]["recovery_state"])
        self.assertEqual(result["recovery"]["status"], "new_cycle")
        self.assertEqual(result["recovery"]["frontier"], "closed")
        self.assertEqual(result["recovery"]["prefix_sha256"], hashlib.sha256(self.receipt(f).read_bytes()).hexdigest())
        self.assertEqual(result["recovery"]["evidence_source"], "controller_memory_after_release")
        self.assertFalse(result["recovery"]["validated"])
        self.assertFalse(result["recovery"]["local_recovery_admitted"])
        self.assertEqual(result["counters"], {"steps": 6, "claims_reserved": 5, "roles_reserved": 5, "observed_completed_roles": 5})
        expected = [str(f.runtime / "templates/local-automation-runtime/atlas-agent-role-runner"), "--command-config", str(f.config), "--max-roles", "1"]
        self.assertTrue(all(command == expected for command, kwargs in factories))

    def test_recovery_cli_cold_settlement_resume_then_terminal_observation_changes_no_bytes(self):
        from unittest.mock import patch
        helper, f, receipt, first, launches_a = self.cold(stages=2)
        cycle, epoch_a = first[-1]["cycle_id"], first[-1]["controller_epoch"]
        run_a = first[-1]["recovery_state"]["progress_by_item"][f.source_id]["run_id"]
        raw_a = receipt.read_bytes()
        (code, result, error), factories, launches_b, _ = helper.run_fixture(f,
            argv=self.argv(helper, f, cycle=cycle), time=self.clock(110))
        self.assertEqual(code, 0, (result, error))
        self.assertEqual(result["terminal_outcome"], "completed")
        self.assertEqual(len(launches_a), 2); self.assertEqual(len(launches_b), 3)
        self.assertEqual(len(factories), 3)
        self.assertEqual(result["progress_by_item"][f.source_id]["run_id"], run_a)
        self.assertEqual(result["counters"], {"steps": 6, "claims_reserved": 5, "roles_reserved": 5, "observed_completed_roles": 5})
        self.assertEqual(result["elapsed_seconds"], 10)
        self.assertTrue(result["recovery"]["local_recovery_admitted"])
        self.assertEqual(result["recovery"]["old_tail_acknowledgment"], "unknown")
        events = orchestrator._decode_cycle_receipt_v2(receipt.read_bytes())
        admission = events[len(first)]
        self.assertEqual(admission["event"], "recovery_admitted")
        self.assertNotEqual(admission["controller_epoch"], epoch_a)
        self.assertIsNone(admission["prior_event_acknowledged"])
        self.assertEqual(admission["old_tail_acknowledgment"], "unknown")
        self.assertEqual(admission["revalidated_prefix_sha256"], hashlib.sha256(raw_a).hexdigest())
        self.assertEqual(admission["counters"], first[-1]["counters"])
        f.reload()
        before = {path: path.read_bytes() for path in [receipt, f.queue, *Path(f.item["result"]["evidence"]["job_dir"]).rglob("*")] if path.is_file()}
        def forbidden(*args, **kwargs): raise AssertionError("terminal observation must not enter adapter or mutate provider")
        with patch.object(orchestrator, "_run_bounded_cycle", side_effect=forbidden), \
             patch.object(orchestrator.atlas_work_items.AtlasWorkItemOperationProvider, "claim", side_effect=forbidden), \
             patch.object(orchestrator.atlas_work_items.AtlasWorkItemOperationProvider, "record_result", side_effect=forbidden):
            (code, observed, error), factories, launches_c, _ = helper.run_fixture(f,
                argv=self.argv(helper, f, cycle=cycle), time=self.clock(115))
        self.assertEqual(code, 0, (observed, error))
        self.assertEqual(observed["recovery"]["status"], "report_only")
        self.assertTrue(observed["recovery"]["validated"])
        self.assertEqual(observed["terminal_outcome"], "completed")
        self.assertIsNone(observed["closure_witness"])
        self.assertEqual(observed["counters"], result["counters"])
        self.assertFalse(factories); self.assertFalse(launches_c)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(observed["recovery"]["evidence_source"], "held_existing_history")
        json.dumps(observed, allow_nan=False)

    def test_recovery_cli_option_spelling_mode_duplicates_defaults_and_domains_refuse_before_reads(self):
        from unittest.mock import patch
        helper, f = self.fixture(); base = self.argv(helper, f)
        cases = [["--once", "--atlas-recoverable"], ["--once", "--atlas-resume-cycle=" + "a" * 32],
            [option for option in base if option != "--atlas-recoverable"] + ["--atlas-resume-cycle=" + "a" * 32]]
        cases += [base[:index] + base[index + 1:] for index in range(len(base) - 1)]
        cases += [base + [option] for option in ("--atlas-recoverable", "--atlas-max-steps=8", "--daemon", "--limit=20", "--max-items=3",
            "--atlas-reco", "--atlas-resume-cyc=" + "a" * 32, "--atlas-resume-cycle=A" + "a" * 31,
            "--atlas-resume-cycle=bad", "--atlas-resume-cycle=", "--atlas-work-item-command=", "--publish", "--dry-run")]
        cases += [base + ["--atlas-resume-cycle=" + "a" * 32, "--atlas-resume-cycle=" + "a" * 32]]
        with patch.object(orchestrator, "_cycle_guard_read", side_effect=AssertionError("must refuse before reads")), \
             patch.object(orchestrator._RecoverableCycleJournal, "acquire_for_recovery", side_effect=AssertionError("must refuse before acquisition")), \
             patch.object(orchestrator, "process_once", side_effect=AssertionError("legacy forbidden")):
            for argv in cases:
                with self.subTest(argv=argv): self.assertEqual(helper.invoke(argv)[0], 2)
        with patch.object(orchestrator, "process_once", return_value=0) as ordinary:
            self.assertEqual(helper.invoke(["--once"])[0], 0); ordinary.assert_called_once()

    def test_recovery_cli_equal_byte_pins_copy_refuses_before_read_and_limits_bind_before_pins(self):
        from unittest.mock import patch
        helper, f, receipt, events, _ = self.cold()
        original = orchestrator._cycle_guard_read
        alternate = f.root / "equal-pins.json"; alternate.write_bytes(f.pins_path.read_bytes())
        before = {p: p.read_bytes() for p in (receipt, f.queue, f.pins_path, alternate)}
        for changes in ({"atlas-cycle-pins": str(alternate)}, {"atlas-max-steps": 9}, {"atlas-worker-timeout-seconds": 11},
                        {"atlas-stop-file": str(f.root / "alternate-stop")}, {"atlas-worker-termination-grace-seconds": 0.3}):
            def read(path):
                self.assertNotIn(str(path), {str(f.pins_path), str(alternate)}, "must compare path/limits before any pins read")
                return original(path)
            with self.subTest(changes=changes), patch.object(orchestrator, "_cycle_guard_read", read):
                (code, result, error), factories, launches, _ = helper.run_fixture(f,
                    argv=self.argv(helper, f, cycle=events[-1]["cycle_id"], **changes), time=self.clock(110))
            self.assertEqual(code, 2, (result, error))
            self.assertEqual(result["recovery"]["status"], "reconciliation_required")
            self.assertFalse(result["recovery"]["validated"])
            self.assertIsNone(result["closure_witness"])
            self.assertFalse(factories); self.assertFalse(launches)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_recovery_cli_source_config_selectors_admission_and_result_disagreement_refuse_unchanged(self):
        for mode in ("pins_bytes", "config_bytes", "config_option", "selector", "source", "outside", "head", "result", "marker", "routing"):
            with self.subTest(mode=mode):
                helper, f, receipt, events, _ = self.cold()
                argv = self.argv(helper, f, cycle=events[-1]["cycle_id"])
                if mode == "pins_bytes": f.pins_path.write_bytes(f.pins_path.read_bytes() + b"\n")
                if mode == "config_bytes": f.config.write_text('{"commands":{"default":["altered"]}}')
                if mode == "config_option": argv = self.argv(helper, f, cycle=events[-1]["cycle_id"], **{"atlas-role-command-config": str(f.root / "other-config.json")})
                if mode == "selector": argv += ["--team-templates=" + str(f.root)]
                if mode == "source": f.plan.write_text("changed plan")
                if mode == "outside": (f.execution / "outside.txt").write_text("outside scope")
                if mode == "head": f.commit(f.execution) if f.git(f.execution, "status", "--porcelain").strip() else f.git(f.execution, "commit", "--allow-empty", "-qm", "new HEAD")
                if mode in {"result", "marker", "routing"}:
                    f.reload()
                    if mode == "result": f.item["result"]["summary"] = "altered result"
                    elif mode == "marker": f.item["process_uncertainty"]["status"] = "unresolved"
                    else: f.item["metadata"].pop("local_execution_v1")
                    f.write_queue()
                before = {p: p.read_bytes() for p in (receipt, f.queue)}
                (code, result, error), factories, launches, _ = helper.run_fixture(f, argv=argv, time=self.clock(110))
                self.assertEqual(code, 2, (result, error))
                self.assertEqual(result["recovery"]["status"], "reconciliation_required", result)
                self.assertIsNone(result["closure_witness"]); self.assertFalse(factories); self.assertFalse(launches)
                self.assertEqual(before, {p: p.read_bytes() for p in before})
                json.dumps(result, allow_nan=False)

    def test_recovery_cli_current_stop_deadline_boot_and_clock_have_no_admission_or_budget_refund(self):
        from unittest.mock import patch
        for mode in ("stop", "deadline", "boot", "backward", "nan_after_entry", "inspection", "late_stop", "late_deadline"):
            with self.subTest(mode=mode):
                helper, f, receipt, events, _ = self.cold(stages=1, frontier="recovery_ready")
                before = {p: p.read_bytes() for p in (receipt, f.queue)}
                if mode == "stop": (f.root / "stop").touch()
                clock_value = {"deadline": 220, "backward": 99}.get(mode, 110)
                now = [clock_value]; calls = [0]
                def clock():
                    calls[0] += 1
                    return float("nan") if mode == "nan_after_entry" and calls[0] > 1 else now[0]
                actual = orchestrator._admit_cycle_recovery
                def admit(*args, **kwargs):
                    admitted = actual(*args, **kwargs)
                    if mode == "late_stop": (f.root / "stop").touch()
                    if mode == "late_deadline": now[0] = 220
                    return admitted
                kwargs = {"time": self.clock(clock), "_admit_cycle_recovery": admit}
                if mode == "boot": kwargs["_bounded_cli_boot_id"] = lambda: "87654321-1234-1234-1234-123456789abc"
                def inspection(token): raise PermissionError("cannot inspect stop parent")
                with patch.object(orchestrator._BoundedCliCancellation, "is_set", inspection) if mode == "inspection" else patch.object(orchestrator, "_bounded_cli_boot_id", kwargs.pop("_bounded_cli_boot_id", orchestrator._bounded_cli_boot_id)):
                    (code, result, error), factories, launches, _ = helper.run_fixture(f,
                        argv=self.argv(helper, f, cycle=events[-1]["cycle_id"]), **kwargs)
                report_only = mode in {"stop", "deadline", "inspection", "late_stop", "late_deadline"}
                self.assertEqual(code, 0 if report_only else 2, (result, error))
                self.assertEqual(result["recovery"]["status"], "report_only" if report_only else "reconciliation_required")
                self.assertEqual(result["counters"], events[-1]["counters"])
                self.assertIsNone(result["closure_witness"])
                self.assertFalse(factories); self.assertFalse(launches)
                self.assertEqual(before, {p: p.read_bytes() for p in before})
                json.dumps(result, allow_nan=False)

    def test_recovery_cli_missing_v1_sibling_torn_and_unsafe_tail_never_fall_back_or_create_cycle(self):
        from unittest.mock import patch
        for mode in ("missing", "v1", "sibling", "torn", "step_reserved", "step_started", "claim_intent", "claimed", "worker_returned", "result_intent", "result_acknowledged"):
            with self.subTest(mode=mode):
                if mode == "missing":
                    helper, f = self.fixture(); cycle = "a" * 32
                    before_names = sorted(str(p) for p in f.root.rglob("*"))
                    before = {f.queue: f.queue.read_bytes()}
                elif mode == "v1":
                    helper, f = self.fixture()
                    (code, _, error), _, _, _ = helper.run_fixture(f, time=self.clock(100))
                    self.assertEqual(code, 0, error)
                    receipt = self.receipt(f); cycle = receipt.stem
                    before = {receipt: receipt.read_bytes(), f.queue: f.queue.read_bytes()}
                else:
                    helper, f, receipt, events, _ = self.cold(frontier=mode if mode not in {"sibling", "torn"} else "claim_settled")
                    cycle = events[-1]["cycle_id"]
                    if mode == "sibling": (receipt.parent / ("f" * 32 + ".jsonl")).write_bytes(receipt.read_bytes())
                    if mode == "torn": receipt.write_bytes(receipt.read_bytes() + b'{"torn":')
                    before = {p: p.read_bytes() for p in [f.queue, *receipt.parent.glob("*.jsonl")]}
                def forbidden(*args, **kwargs): raise AssertionError("refused history must not enter adapter")
                with patch.object(orchestrator, "_run_bounded_cycle", side_effect=forbidden):
                    (code, result, error), factories, launches, _ = helper.run_fixture(f,
                        argv=self.argv(helper, f, cycle=cycle), time=self.clock(110))
                self.assertEqual(code, 2, (result, error))
                self.assertEqual(result["recovery"]["status"], "reconciliation_required")
                self.assertIsNone(result["closure_witness"]); self.assertFalse(factories); self.assertFalse(launches)
                self.assertEqual(before, {p: p.read_bytes() for p in before})
                if mode == "missing":
                    self.assertEqual(before_names, sorted(str(p) for p in f.root.rglob("*")))
                    self.assertIsNone(result["counters"], "unknown receipt counters cannot be fabricated as fresh zero")

    def test_recovery_cli_fresh_preflight_charges_original_entry_and_requires_current_boot_and_routing(self):
        for mode in ("deadline", "boot_error", "routing"):
            with self.subTest(mode=mode):
                helper, f = self.fixture(); now = [100]
                actual = orchestrator._cycle_guard_read
                def read(path):
                    if mode == "deadline": now[0] += 200
                    return actual(path)
                def boot_error(): raise OSError("boot identity unavailable")
                if mode == "routing": f.item["metadata"].pop("local_execution_v1"); f.write_queue(); f.repin()
                kwargs = {"time": self.clock(lambda: now[0]), "_cycle_guard_read": read}
                if mode == "boot_error": kwargs["_bounded_cli_boot_id"] = boot_error
                (code, result, error), factories, launches, _ = helper.run_fixture(f, argv=self.argv(helper, f), **kwargs)
                self.assertFalse(factories); self.assertFalse(launches)
                if mode == "deadline":
                    self.assertEqual(code, 0, (result, error)); self.assertEqual(result["failure"], "deadline")
                    self.assertGreaterEqual(result["elapsed_seconds"], 200)
                    events = orchestrator._decode_cycle_receipt_v2(self.receipt(f).read_bytes())
                    self.assertEqual(events[0]["origin"]["entry_monotonic"], 100)
                    self.assertNotIn("recovery_ready", [row["event"] for row in events])
                    self.assertFalse(list(self.receipt(f).parent.glob("*.jobs")))
                else:
                    self.assertEqual(code, 2, (result, error))
                    self.assertFalse(list(f.root.rglob("*.jobs")))

    def test_recovery_cli_all_original_limits_and_saved_admission_bind_and_release_on_refusal(self):
        helper, f, receipt, events, _ = self.cold(frontier="recovery_ready")
        changes = {"atlas-max-steps": 9, "atlas-max-claims": 9, "atlas-max-roles": 9, "atlas-role-max": 2,
            "atlas-cycle-seconds": 121, "atlas-worker-timeout-seconds": 11, "atlas-worker-termination-grace-seconds": 0.3,
            "atlas-stop-file": str(f.root / "different-stop")}
        before = {receipt: receipt.read_bytes(), f.queue: f.queue.read_bytes()}
        for name, value in changes.items():
            with self.subTest(name=name):
                (code, result, error), _, launches, _ = helper.run_fixture(f,
                    argv=self.argv(helper, f, cycle=events[-1]["cycle_id"], **{name: value}), time=self.clock(110))
                self.assertEqual(code, 2, (result, error)); self.assertFalse(launches)
                self.assertIn("limits differ", result["failure"])
                owner = orchestrator._RecoverableCycleJournal.acquire_for_recovery(str(f.queue), events[-1]["cycle_id"])
                owner.release()
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_recovery_cli_restores_signal_handlers_after_resume_and_read_only_refusal(self):
        import signal
        original = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        helper, f, receipt, events, _ = self.cold(frontier="recovery_ready")
        for bad in (True, False, False):
            argv = self.argv(helper, f, cycle=events[-1]["cycle_id"], **({"atlas-max-steps": 9} if bad else {}))
            (code, result, error), _, _, _ = helper.run_fixture(f, argv=argv, time=self.clock(110))
            self.assertEqual(code, 2 if bad else 0, (result, error))
            self.assertEqual({sig: signal.getsignal(sig) for sig in original}, original)

    def test_recovery_cli_release_error_still_restores_signals_and_releases_all_custody(self):
        from unittest.mock import patch
        import signal
        helper, f, receipt, events, _ = self.cold(frontier="recovery_ready")
        (f.root / "stop").touch()
        raw = receipt.read_bytes()
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        actual = orchestrator._RecoverableCycleJournal.release
        def release(journal):
            first = not journal._released
            actual(journal)
            if first: raise OSError("synthetic custody release error")
        with patch.object(orchestrator._RecoverableCycleJournal, "release", release):
            (code, result, error), factories, launches, _ = helper.run_fixture(f,
                argv=self.argv(helper, f, cycle=events[-1]["cycle_id"]), time=self.clock(110))
        self.assertEqual(code, 2); self.assertIsNone(result)
        self.assertIn("custody release error", error)
        self.assertFalse(factories); self.assertFalse(launches)
        self.assertEqual(receipt.read_bytes(), raw)
        self.assertEqual({sig: signal.getsignal(sig) for sig in handlers}, handlers)
        owner = orchestrator._RecoverableCycleJournal.acquire_for_recovery(str(f.queue), events[-1]["cycle_id"])
        owner.release()

    def test_recovery_cli_lost_result_return_reports_reconciliation_without_old_witness(self):
        from unittest.mock import patch
        helper, f = self.fixture()
        provider = orchestrator.atlas_work_items.AtlasWorkItemOperationProvider
        actual, returns = provider.record_result, []
        def record(instance, operation, result):
            original = copy.deepcopy(result.to_dict())
            actual(instance, operation, result)
            returns.append(original)
            raise OSError("synthetic lost result return")
        with patch.object(provider, "record_result", record):
            (code, result, error), factories, launches, _ = helper.run_fixture(f,
                argv=self.argv(helper, f), time=self.clock(100))
        self.assertEqual(code, 2, (result, error))
        self.assertEqual(len(returns), 1); self.assertEqual(len(launches), 1)
        self.assertTrue(result["unresolved"]); self.assertIsNone(result["closure_witness"])
        self.assertEqual(result["recovery"]["status"], "reconciliation_required")
        self.assertEqual(result["recovery"]["mode"], "fresh")
        self.assertEqual(result["recovery"]["evidence_source"], "controller_memory_after_release")
        events = orchestrator._decode_cycle_receipt_v2(self.receipt(f).read_bytes())
        self.assertEqual(events[-1]["event"], "terminal")
        self.assertTrue(events[-1]["unresolved"])
        f.reload(); self.assertEqual(f.item["result"], returns[0])
        raw = self.receipt(f).read_bytes()
        (code, refused, error), factories, launches, _ = helper.run_fixture(f,
            argv=self.argv(helper, f, cycle=events[-1]["cycle_id"]), time=self.clock(110))
        self.assertEqual(code, 2, (refused, error))
        self.assertEqual(refused["recovery"]["status"], "reconciliation_required")
        self.assertFalse(factories); self.assertFalse(launches)
        self.assertEqual(self.receipt(f).read_bytes(), raw)


_RECOVERY_ROLE_PROCESS = r'''
import json,os,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import atlas_local_sizing
control=json.loads(sys.argv[2]); fd=int(sys.argv[3])
def notify(value): os.write(fd,(json.dumps(value)+'\n').encode())
def wait_file(name):
 deadline=time.monotonic()+15
 while not Path(control[name]).exists():
  if time.monotonic()>=deadline: raise RuntimeError('finite producer release deadline')
  time.sleep(.01)
rows=json.load(open(os.environ['ATLAS_TEAM_ROLE_TASKS_FILE']))
tasks=rows['tasks'] if isinstance(rows,dict) else rows
complete={t['role_id'] for t in tasks if t.get('status')=='complete' and not t.get('missing_outputs')}
run=json.load(open(os.environ['ATLAS_TEAM_RUN_FILE']))
results=[]
for task in tasks:
 if task['role_id'] in complete or not set(task.get('consumes',[])).issubset(complete): continue
 atlas_local_sizing.assignment_for_task(task)
 marker={'work_item_id':os.environ['ATLAS_WORK_ITEM_ID'],'role_id':task['role_id'],'run_id':run['id'],
  'invocation':str(Path(os.environ['ATLAS_TEAM_RUN_FILE']).parent),'producer_pid':os.getpid()}
 out=os.open(control['markers'],os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
 try: os.write(out,(json.dumps(marker,sort_keys=True)+'\n').encode());os.fsync(out)
 finally: os.close(out)
 if control['cut'] in {'live_worker','descendant'}:
  descendant=None
  if control['cut']=='descendant':
   script="import sys,time;from pathlib import Path;deadline=time.monotonic()+15\nwhile not Path(sys.argv[1]).exists():\n if time.monotonic()>=deadline: raise SystemExit(0)\n time.sleep(.01)\n"
   descendant=subprocess.Popen([sys.executable,'-B','-c',script,control['descendant_release']],close_fds=True)
  notify({'event':'producer_live','leader':os.getpid(),'descendant':None if descendant is None else descendant.pid,'pgid':os.getpgrp()})
  wait_file('producer_release')
 review={'verdict':'pass','reason':'Inspected the scoped implementation and substantive verification against its goal.',
  'evidence':['Finite process verification satisfies the acceptance contract.']} if task.get('goal_gate') else None
 results.append({'role_id':task['role_id'],'status':'complete','outputs':{key:'Substantive finite process '+key for key in task['must_produce']},
  'evidence':['Independent finite Python producer completed.'],'goal_review':review})
 break
if len(results)!=1: raise RuntimeError('producer must execute exactly one new role')
with open(os.environ['ATLAS_TEAM_ROLE_RESULTS_FILE'],'w') as stream:
 json.dump(results,stream);stream.flush();os.fsync(stream.fileno())
notify({'event':'producer_published','pid':os.getpid(),'path':os.environ['ATLAS_TEAM_ROLE_RESULTS_FILE']})
'''


_RECOVERY_COORDINATOR_PROCESS = r'''
import importlib.machinery,importlib.util,json,os,selectors,signal,subprocess,sys,time,traceback
from pathlib import Path
manifest=json.loads(Path(sys.argv[1]).read_text()); fd=int(sys.argv[2]); label=sys.argv[3]
signal.alarm(40)
sys.path.insert(0,manifest['runtime_source'])
loader=importlib.machinery.SourceFileLoader('actual_recovery_candidate_'+label,manifest['driver'])
spec=importlib.util.spec_from_loader(loader.name,loader);m=importlib.util.module_from_spec(spec);sys.modules[loader.name]=m;loader.exec_module(m)
control=manifest['control'];cut=manifest.get('cut');observing=manifest.get('observe',False)
def notify(value):
 value={'coordinator_pid':os.getpid(),'label':label,**value}
 os.write(fd,(json.dumps(value,sort_keys=True)+'\n').encode())
 with open(control['records'],'a') as stream: stream.write(json.dumps(value,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
def barrier(event):
 notify({'event':event})
 selector=selectors.DefaultSelector();selector.register(sys.stdin,selectors.EVENT_READ)
 try:
  if not selector.select(20) or sys.stdin.readline().strip()!='go': raise RuntimeError('explicit coordinator IPC deadline/release')
 finally: selector.close()
def cut_at(name):
 if cut==name: barrier('cut:'+name)
notify({'event':'imported'})
m._bounded_cli_runtime=lambda:Path(manifest['runtime_fixture'])
m.atlas_work_items.__file__=str(Path(manifest['runtime_fixture'])/'atlas_work_items.py')
original_popen=subprocess.Popen
expected=[str(Path(manifest['runtime_fixture'])/'atlas-agent-role-runner'),'--command-config',manifest['command_config'],'--max-roles','1']
def popen(command,*args,**kwargs):
 if isinstance(command,list) and command and 'atlas-agent-role-runner' in str(command[0]):
  if command!=expected: raise AssertionError('unexpected canonical role argv: '+repr(command))
  if observing: raise AssertionError('terminal observer launched a role')
  notify({'event':'role_launch','argv':command,'cwd':str(kwargs.get('cwd')),'start_new_session':kwargs.get('start_new_session')})
  if kwargs.get('start_new_session') is not True: raise AssertionError('role fixture lost owned process group')
  kwargs['pass_fds']=(fd,)
  command=[sys.executable,'-B',manifest['producer'],manifest['runtime_source'],json.dumps(control|{'cut':cut}),str(fd)]
 return original_popen(command,*args,**kwargs)
subprocess.Popen=popen
provider=m.atlas_work_items.AtlasWorkItemOperationProvider
claim=provider.claim;record=provider.record_result
calls={'claim':0,'record_result':0,'append':0}
def claimed(self,operation):
 if observing: raise AssertionError('terminal observer claimed work')
 calls['claim']+=1;result=claim(self,operation);notify({'event':'claim_applied'})
 cut_at('claim_applied');return result
def recorded(self,operation,result):
 if observing: raise AssertionError('terminal observer wrote result')
 calls['record_result']+=1;record(self,operation,result);notify({'event':'result_applied'})
 cut_at('result_applied')
 if cut=='result_lost_return': raise OSError('deterministic lost actual result return')
provider.claim=claimed;provider.record_result=recorded
append=m._RecoverableCycleJournal._append
def appended(self,row,**kwargs):
 if observing: raise AssertionError('terminal observer appended receipt')
 append(self,row,**kwargs);calls['append']+=1
 notify({'event':'append_return','frontier':row['event'],'seq':self._events[-1]['seq']})
 if cut=='persisted_stop' and row['event']=='claim_settled':Path(manifest['stop_file']).touch()
 cut_at(row['event'])
m._RecoverableCycleJournal._append=appended
if manifest.get('hold_acquire'):
 acquire=m._RecoverableCycleJournal.acquire_for_recovery.__func__
 def acquired(cls,queue,cycle):
  owner=acquire(cls,queue,cycle);barrier('owner');return owner
 m._RecoverableCycleJournal.acquire_for_recovery=classmethod(acquired)
if manifest.get('start_barrier'): barrier('ready_to_start')
sys.argv=['atlas-agent-orchestrator',*manifest['argv']]
code=0
try:
 m.main()
except SystemExit as exc: code=exc.code
except BaseException:
 traceback.print_exc();code=97
notify({'event':'finished','code':code,'calls':calls})
raise SystemExit(code)
'''


class _RecoveryHarnessInjectedFailure(Exception):
    """A named harness-only failure, never a dependency or product refusal."""


def _capture_recovery_test_host(child, control: Path, *, timeout=65):
    """Boundedly drain/reap/close an owned host and retain facts before assertions."""
    import subprocess
    out, err = b'', b''
    facts = {'pid': child.pid, 'timed_out': False, 'capture_errors': [], 'actions': []}
    complete = False
    def retain(previous, value):
        if value is None: return previous
        value = value.encode() if isinstance(value, str) else value
        if value.startswith(previous): return value
        if previous.startswith(value): return previous
        return previous + value
    def capture(exception):
        nonlocal out, err
        out, err = retain(out, exception.output), retain(err, exception.stderr)
    try:
        try:
            stdout, stderr = child.communicate(timeout=timeout)
            out, err, complete = retain(out, stdout), retain(err, stderr), True
        except subprocess.TimeoutExpired as exc:
            facts['timed_out'] = True; capture(exc)
        except BaseException as exc:
            facts['capture_errors'].append(repr(exc))
    finally:
        try:
            if not complete:
                # Drain even when poll observes an exited-at-timeout race.
                for action in ('terminate', 'kill'):
                    if child.poll() is None:
                        facts['actions'].append(action)
                        try: getattr(child, action)()
                        except ProcessLookupError: pass
                    try:
                        stdout, stderr = child.communicate(timeout=3)
                        out, err, complete = retain(out, stdout), retain(err, stderr), True
                        break
                    except subprocess.TimeoutExpired as exc: capture(exc)
                    except BaseException as exc: facts['capture_errors'].append(repr(exc))
            try:
                facts['returncode'] = child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                if child.poll() is None:
                    facts['actions'].append('kill-before-final-wait'); child.kill()
                facts['returncode'] = child.wait(timeout=3)
        except BaseException as exc:
            facts['capture_errors'].append(repr(exc)); facts['returncode'] = child.returncode
        finally:
            for name in ('stdin', 'stdout', 'stderr'):
                stream = getattr(child, name, None)
                if stream is not None:
                    try: stream.close()
                    except BaseException as exc: facts['capture_errors'].append(repr(exc))
            facts['streams_closed'] = {name: getattr(child, name, None) is None or getattr(child, name).closed
                for name in ('stdin', 'stdout', 'stderr')}
            facts.update(stdout_size=len(out), stderr_size=len(err), drain_complete=complete,
                stdout_sha256=hashlib.sha256(out).hexdigest(), stderr_sha256=hashlib.sha256(err).hexdigest())
            (control/'host.stdout').write_bytes(out); (control/'host.stderr').write_bytes(err)
            (control/'host-result.json').write_text(json.dumps(facts, indent=2)+'\n')
    return facts, out, err


class _RecoveryProcessTrial:
    """Helper-only subreaper host; all process identities come from owned IPC."""
    def __init__(self, control: Path, trial: str):
        import ctypes
        self.case, self.control, self.trial = unittest.TestCase(), control, trial
        import signal
        def interrupted(signum, frame): raise RuntimeError("finite subreaper host interrupted/deadline")
        signal.signal(signal.SIGTERM, interrupted); signal.signal(signal.SIGALRM, interrupted); signal.alarm(35)
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "test child-subreaper unavailable")
        self.helper = BoundedCliTests(); self.case.addCleanup(self.helper.doCleanups)
        self.f = self.helper.fixture()
        self.children, self.events, self.adopted = [], [], []
        self.case.addCleanup(self.cleanup_adopted)
        self.producer = control / 'producer.py'; self.producer.write_text(_RECOVERY_ROLE_PROCESS)
        self.coordinator = control / 'coordinator.py'; self.coordinator.write_text(_RECOVERY_COORDINATOR_PROCESS)
        self.control_values = {key: str(control / value) for key, value in {
            'markers':'role-effects.jsonl','records':'coordinator-records.jsonl',
            'producer_release':'producer.release','descendant_release':'descendant.release'}.items()}
        self.base = self.helper.argv(self.f, **{'atlas-cycle-seconds':120,'atlas-worker-timeout-seconds':20}) + ['--atlas-recoverable']
        self.summary = {'trial':trial,'host_pid':__import__('os').getpid(),'coordinators':[]}

    def spawn(self, label, *, cycle=None, cut=None, observe=False, hold=False, start=False):
        import os, subprocess
        values = {'driver':str(ROOT/'atlas-agent-orchestrator'),'runtime_source':str(ROOT),
            'runtime_fixture':str(self.f.runtime/'templates/local-automation-runtime'),'command_config':str(self.f.config),
            'producer':str(self.producer),'control':self.control_values,'stop_file':str(self.f.root/'stop'),
            'argv':self.base+(['--atlas-resume-cycle='+cycle] if cycle else []),'cut':cut,'observe':observe,
            'hold_acquire':hold,'start_barrier':start}
        manifest=self.control/(label+'.manifest.json');manifest.write_text(json.dumps(values))
        read,write=os.pipe()
        stdout=(self.control/(label+'.stdout')).open('wb');stderr=(self.control/(label+'.stderr')).open('wb')
        child=subprocess.Popen([sys.executable,'-B',str(self.coordinator),str(manifest),str(write),label],
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'},
            stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,pass_fds=(write,),close_fds=True)
        # Register ownership before assertions, writes or IPC observations.
        row={'process':child,'fd':read,'buffer':b'','label':label,'stdout':stdout,'stderr':stderr,'events':[]}
        self.children.append(row);self.case.addCleanup(self.cleanup_child,row)
        os.close(write);os.set_blocking(read,False)
        return row

    def cleanup_child(self, row):
        import subprocess
        child=row['process']
        if child.poll() is None:
            child.terminate()
            try: child.wait(timeout=2)
            except subprocess.TimeoutExpired: child.kill();child.wait(timeout=3)
        else: child.wait(timeout=1)
        if child.stdin: child.stdin.close()
        if row['fd'] is not None: __import__('os').close(row['fd']);row['fd']=None
        row['stdout'].close();row['stderr'].close()
        self.summary.setdefault('owned_children_reaped',[]).append({'pid':child.pid,'exit':child.returncode,
            'label':row['label'],'streams_closed':True,'event_fd_closed':row['fd'] is None})

    def event(self, row, wanted=None, timeout=8):
        import os,selectors,time
        deadline=time.monotonic()+timeout
        selector=selectors.DefaultSelector();selector.register(row['fd'],selectors.EVENT_READ)
        try:
            while time.monotonic()<deadline:
                while b'\n' in row['buffer']:
                    line,row['buffer']=row['buffer'].split(b'\n',1);value=json.loads(line)
                    row['events'].append(value);self.events.append(value)
                    if wanted is None or value['event']==wanted: return value
                if not selector.select(max(0,deadline-time.monotonic())): break
                data=os.read(row['fd'],65536)
                if not data: break
                row['buffer']+=data
        finally: selector.close()
        raise AssertionError('missing process IPC '+str(wanted)+' for '+row['label']+'; '+(self.control/(row['label']+'.stderr')).read_text())

    def release(self,row):
        row['process'].stdin.write(b'go\n');row['process'].stdin.flush()

    def finish(self,row,code=0):
        event=self.event(row,'finished',timeout=15)
        actual=row['process'].wait(timeout=5)
        self.case.assertEqual(actual,code,(event,(self.control/(row['label']+'.stderr')).read_text()))
        self.case.assertEqual(event['code'],code)
        text=(self.control/(row['label']+'.stdout')).read_text().strip()
        result=json.loads(text) if text.startswith('{') else None
        self.summary['coordinators'].append({'label':row['label'],'pid':row['process'].pid,'exit':actual,'result':result,'calls':event['calls']})
        return result,event['calls']

    def kill(self,row):
        row['process'].kill();self.case.assertEqual(row['process'].wait(timeout=5),-9)
        self.summary['coordinators'].append({'label':row['label'],'pid':row['process'].pid,'exit':-9,'cut':row['events'][-1]})

    def receipt(self):
        receipts=list((self.f.root/'.atlas-supervisor').rglob('*.jsonl'));self.case.assertEqual(len(receipts),1)
        path=receipts[0];return path,orchestrator._decode_cycle_receipt_v2(path.read_bytes())

    def markers(self):
        path=Path(self.control_values['markers'])
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def snapshot(self):
        return {str(p.relative_to(self.f.root)):p.read_bytes() for p in self.f.root.rglob('*')
            if p.is_file() and '.git' not in p.parts}

    def save_state(self,label):
        data=self.snapshot();directory=self.control/'facts'/label;directory.mkdir(parents=True)
        hashes={}
        for name,raw in data.items():
            target=directory/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            hashes[name]=hashlib.sha256(raw).hexdigest()
        markers=Path(self.control_values['markers'])
        raw=markers.read_bytes() if markers.exists() else b''
        (directory/'independent-role-effects.jsonl').write_bytes(raw)
        self.summary.setdefault('facts',{})[label]={'original_fixture_root':str(self.f.root),
            'directory':str(directory),'files':hashes,'marker_sha256':hashlib.sha256(raw).hexdigest(),
            'markers':self.markers()}
        return data

    def assert_refusal(self,label,cycle,before):
        child=self.spawn(label,cycle=cycle);result,calls=self.finish(child,2)
        self.case.assertEqual(result['recovery']['status'],'reconciliation_required',result)
        self.case.assertIsNone(result['closure_witness'])
        self.case.assertEqual(calls,{'claim':0,'record_result':0,'append':0})
        self.case.assertEqual(self.snapshot(),before)
        self.case.assertFalse(any(event['event']=='role_launch' for event in child['events']))
        return result

    def cut(self,name='claim_settled'):
        child=self.spawn('A',cut=name)
        self.event(child,'cut:'+name)
        receipt,events=self.receipt()
        self.case.assertEqual(events[-1]['event'],{'claim_applied':'claim_intent','result_applied':'result_intent'}.get(name,name))
        return child,receipt,events

    def verify_complete(self,cycle,initial,baseline=None):
        receipt,events=self.receipt();markers=self.markers()
        self.case.assertEqual(len(markers),5)
        self.case.assertEqual([m['role_id'] for m in markers],[r['role_id'] for r in RESULT_ROLES])
        self.case.assertEqual({m['work_item_id'] for m in markers},{self.f.source_id})
        self.case.assertEqual(len({m['run_id'] for m in markers}),1)
        self.case.assertEqual(len({m['invocation'] for m in markers}),5)
        self.case.assertEqual(len({m['producer_pid'] for m in markers}),5)
        runs=[json.loads((Path(m['invocation'])/'team-run.json').read_text()) for m in markers]
        self.case.assertEqual([len(r['role_results']) for r in runs],[1,2,3,4,5])
        self.case.assertEqual({r['id'] for r in runs},{markers[0]['run_id']})
        self.case.assertEqual({Path(m['invocation']).parent.name for m in markers},{cycle+'.jobs'})
        admission=events[len(initial)]
        self.case.assertEqual(admission['event'],'recovery_admitted')
        self.case.assertNotEqual(admission['controller_epoch'],initial[-1]['controller_epoch'])
        self.case.assertEqual(admission['old_tail_acknowledgment'],'unknown')
        self.case.assertIsNone(admission['prior_event_acknowledged'])
        self.case.assertEqual(admission['revalidated_prefix_sha256'],hashlib.sha256(b''.join(orchestrator._CycleJournal._line(e) for e in initial)).hexdigest())
        self.case.assertEqual(admission['counters'],initial[-1]['counters'])
        self.case.assertEqual(admission['origin'],initial[-1]['origin'])
        self.case.assertGreaterEqual(admission['elapsed_seconds'],initial[-1]['elapsed_seconds'])
        if baseline is not None:
            self.f.reload();self.case.assertEqual(self.f.payload['work_items'][0],baseline)
        before=self.save_state('before-terminal-C');before_markers=Path(self.control_values['markers']).read_bytes()
        c=self.spawn('C',cycle=cycle,observe=True);observed,calls=self.finish(c)
        self.case.assertEqual(observed['recovery']['status'],'report_only')
        self.case.assertTrue(observed['recovery']['validated'])
        self.case.assertEqual(observed['terminal_outcome'],'completed')
        self.case.assertIsNone(observed['closure_witness'])
        self.case.assertEqual(calls,{'claim':0,'record_result':0,'append':0})
        self.case.assertEqual(self.snapshot(),before)
        self.case.assertEqual(Path(self.control_values['markers']).read_bytes(),before_markers)
        self.case.assertEqual(events[-1]['event'],'closed')
        self.save_state('after-terminal-C')
        self.summary.update(markers=markers,terminal_bytes_unchanged=True,final_counters=events[-1]['counters'],cycle=cycle,
            epochs=[initial[-1]['controller_epoch'],admission['controller_epoch']],original_origin=initial[-1]['origin'])
        self.case.assertEqual(len({row['pid'] for row in self.summary['coordinators']}),len(self.summary['coordinators']))

    def positive(self,mixed=False):
        baseline=None
        if mixed:
            f=self.f
            f.declared_resume(complete=True)
            baseline=copy.deepcopy(f.item)
            other=copy.deepcopy(f.item)
            other.update(id='pending',operation_id='operation:pending',title='Pending finite workflow')
            for key in ('workflow_runs','result','claim','previous_claims','process_uncertainty'):other.pop(key,None)
            f.payload['work_items'].append(other);f.pins['admitted_item_ids']=sorted([f.source_id,'pending'])
            f.write_queue();f.repin();f.source_id='pending'
        self.summary['baseline_before_A']=copy.deepcopy(baseline)
        self.save_state('before-A')
        a,receipt,initial=self.cut()
        self.case.assertEqual(initial[-1]['recovery_state']['progress_by_item'][self.f.source_id]['completed_roles'],['implementation'])
        self.case.assertEqual(initial[-1]['counters'],{'steps':1,'claims_reserved':1,'roles_reserved':1,'observed_completed_roles':1})
        self.summary['initial_tail']=copy.deepcopy(initial[-1])
        self.save_state('A-settled-before-volatile-install')
        cycle=initial[-1]['cycle_id'];self.kill(a)
        b=self.spawn('B',cycle=cycle);result,calls=self.finish(b)
        self.case.assertEqual(result['terminal_outcome'],'completed',result)
        self.case.assertEqual(calls['claim'],4);self.case.assertEqual(calls['record_result'],4)
        self.case.assertEqual(result['counters'],{'steps':6,'claims_reserved':5,'roles_reserved':5,'observed_completed_roles':5})
        self.verify_complete(cycle,initial,baseline)

    def wait_adopted_exit(self,pid,timeout=5):
        import os,time
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            status=os.waitid(os.P_PID,pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
            if status is not None:return status
            time.sleep(.01)
        raise AssertionError('owned adopted child did not exit before deadline')

    def matrix(self,name):
        import os,selectors,time
        if name=='persisted_stop':
            a=self.spawn('A',cut=name);result,calls=self.finish(a)
            self.case.assertEqual(result['terminal_outcome'],'cancelled',result)
            self.case.assertEqual(result['failure'],'stop');self.case.assertEqual(len(self.markers()),1)
            receipt,events=self.receipt();cycle=events[-1]['cycle_id']
            self.case.assertEqual(events[-1]['recovery_state']['cancellation'],{'cancelled':True,'cancel_reason':'stop'})
            self.save_state('persisted-stop-before-removal');(self.f.root/'stop').unlink()
            before=self.snapshot();b=self.spawn('B-stop-removed',cycle=cycle,observe=True)
            observed,calls=self.finish(b)
            self.case.assertEqual(observed['terminal_outcome'],'cancelled')
            self.case.assertEqual(observed['recovery']['status'],'report_only');self.case.assertTrue(observed['recovery']['validated'])
            self.case.assertEqual(calls,{'claim':0,'record_result':0,'append':0})
            self.case.assertIsNone(observed['closure_witness']);self.case.assertEqual(self.snapshot(),before)
            self.case.assertEqual(len(self.markers()),1)
        elif name=='result_lost_return':
            a=self.spawn('A',cut=name);result,calls=self.finish(a,2)
            self.case.assertTrue(result['unresolved']);self.case.assertEqual(calls['record_result'],1)
            receipt,events=self.receipt();self.case.assertEqual(events[-1]['event'],'terminal')
            self.case.assertEqual(len(self.markers()),1)
            before=self.save_state('lost-actual-result-return')
            self.assert_refusal('B',events[-1]['cycle_id'],before)
        elif name in {'live_worker','descendant','ipc_failure_live','ipc_failure_descendant'}:
            producer_kind='descendant' if name in {'descendant','ipc_failure_descendant'} else 'live_worker'
            a=self.spawn('A',cut=producer_kind);live=self.event(a,'producer_live')
            leader,descendant=live['leader'],live['descendant']
            self.adopted.append((leader,descendant)) # Pending custody precedes every fallible check/I/O.
            if name.startswith('ipc_failure_'):
                self.summary['pending_registered_before_injection']=[leader,descendant]
                raise _RecoveryHarnessInjectedFailure('after fresh producer IPC before receipt/check/kill')
            self.case.assertEqual(live['pgid'],leader)
            self.case.assertEqual(descendant is not None,producer_kind=='descendant')
            receipt,events=self.receipt();self.case.assertEqual(events[-1]['event'],'launch_intent')
            self.case.assertEqual(len(self.markers()),1)
            self.save_state('live-before-controller-kill');self.kill(a)
            # This succeeds only for this host's fresh adopted unreaped child.
            self.case.assertIsNone(os.waitid(os.P_PID,leader,os.WEXITED|os.WNOHANG|os.WNOWAIT))
            self.summary['owned_adoption']={'fresh_ipc_leader':leader,'fresh_ipc_descendant':descendant,'leader_waitid_proved_child':True}
            before=self.snapshot();self.assert_refusal('B-live',events[-1]['cycle_id'],before)
            Path(self.control_values['producer_release']).touch()
            published=self.event(a,'producer_published');self.case.assertTrue(Path(published['path']).is_file())
            leader_status=self.wait_adopted_exit(leader)
            self.case.assertEqual(leader_status.si_status,0)
            if descendant is not None:
                self.case.assertIsNone(os.waitid(os.P_PID,descendant,os.WEXITED|os.WNOHANG|os.WNOWAIT),
                    'descendant must still live after producer exit')
                self.summary['owned_adoption']['descendant_live_after_leader_exit']=True
            before=self.save_state('later-artifact-leader-exited')
            self.assert_refusal('B-later-artifact',events[-1]['cycle_id'],before)
            self.case.assertEqual(len(self.markers()),1)
        elif name=='lock':
            a,receipt,events=self.cut('recovery_ready');before=self.save_state('controller-lock-held')
            result=self.assert_refusal('B-lock-loser',events[-1]['cycle_id'],before)
            self.case.assertIn('temporarily unavailable',result['failure'].lower())
            self.release(a);result,calls=self.finish(a)
            self.case.assertEqual(result['terminal_outcome'],'completed');self.case.assertEqual(len(self.markers()),5)
        elif name=='contenders':
            a,receipt,events=self.cut();self.save_state('contender-origin-settled');self.kill(a)
            cycle=events[-1]['cycle_id'];before=self.snapshot()
            contenders=[self.spawn(label,cycle=cycle,hold=True,start=True) for label in ('B1','B2')]
            for row in contenders:self.event(row,'ready_to_start')
            for row in contenders:self.release(row)
            winner=None;loser=None;deadline=time.monotonic()+8
            while time.monotonic()<deadline and (winner is None or loser is None):
                ready,_,_=__import__('select').select([row['fd'] for row in contenders],[],[],max(0,deadline-time.monotonic()))
                self.case.assertTrue(ready,'contender ownership IPC deadline')
                for fd in ready:
                    row=next(row for row in contenders if row['fd']==fd)
                    value=self.event(row,timeout=1)
                    if value['event']=='owner':
                        self.case.assertIsNone(winner,'two simultaneous custody owners');winner=row
                    elif value['event']=='finished':
                        self.case.assertEqual(value['code'],2);loser=row
                        row['finished_event']=value
                    # A finished loser can close its event pipe before winner release.
                    if loser is not None:break
                if loser is not None and winner is None:
                    remaining=next(row for row in contenders if row is not loser)
                    self.event(remaining,'owner');winner=remaining
            self.case.assertIsNotNone(winner);self.case.assertIsNotNone(loser)
            self.case.assertEqual(loser['process'].wait(timeout=3),2)
            self.case.assertEqual(loser['finished_event']['calls'],{'claim':0,'record_result':0,'append':0})
            loser_result=json.loads((self.control/(loser['label']+'.stdout')).read_text())
            self.summary['coordinators'].append({'label':loser['label'],'pid':loser['process'].pid,
                'exit':2,'result':loser_result,'calls':loser['finished_event']['calls']})
            self.case.assertEqual(self.snapshot(),before)
            self.summary['contender_custody']={'winner':winner['process'].pid,'loser':loser['process'].pid,'single_owner':True}
            self.release(winner);result,calls=self.finish(winner)
            self.case.assertEqual(result['terminal_outcome'],'completed',result)
            self.case.assertEqual(calls['claim'],4)
            self.verify_complete(cycle,events)
        else:
            a,receipt,events=self.cut(name)
            self.summary['initial_tail']=copy.deepcopy(events[-1])
            self.save_state('unsafe-cut-before-controller-kill');self.kill(a)
            before=self.snapshot();result=self.assert_refusal('B',events[-1]['cycle_id'],before)
            self.case.assertEqual(result['counters'],events[-1]['counters'])
            if name=='step_reserved':self.case.assertEqual(result['recovery']['reason'],'unsupported_frontier')
            self.case.assertEqual(len(self.markers()),0 if name in {'claim_applied','step_reserved'} else 1)
        self.save_state('final-preserved-evidence')
        self.summary['unsafe_or_ownership_row']=name

    def cleanup_adopted(self):
        import os,signal,time
        # Registered coordinator cleanups run first. A may already have reaped
        # its producer; any remaining orphan becomes this subreaper's child.
        Path(self.control_values['producer_release']).touch();Path(self.control_values['descendant_release']).touch()
        for leader,descendant in self.adopted:
            pids=[pid for pid in (leader,descendant) if pid is not None]
            self.case.assertTrue(all(type(pid) is int and pid>0 for pid in pids))
            def current():
                states={}
                for pid in pids:
                    try:states[pid]=os.waitid(os.P_PID,pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
                    except ChildProcessError:pass
                return states
            for sig,seconds in ((None,2),(signal.SIGTERM,1),(signal.SIGKILL,2)):
                states=current()
                if sig is not None:
                    if leader in states:
                        # Retain an owned unreaped leader through group cleanup.
                        os.waitid(os.P_PID,leader,os.WEXITED|os.WNOHANG|os.WNOWAIT)
                        try:
                            if os.getpgid(leader)==leader:os.killpg(leader,sig)
                        except ProcessLookupError:pass
                    for pid,state in current().items():
                        if state is None:
                            os.waitid(os.P_PID,pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
                            try:os.kill(pid,sig)
                            except ProcessLookupError:pass
                deadline=time.monotonic()+seconds
                while time.monotonic()<deadline:
                    states=current()
                    if all(state is not None for state in states.values()):break
                    time.sleep(.01)
                if all(state is not None for state in states.values()):break
            self.case.assertTrue(all(state is not None for state in states.values()),'finite adopted fixture still live')
            reaped=[]
            for pid in pids:
                if pid not in states:
                    self.summary.setdefault('pending_not_current_child_after_coordinator_reap',[]).append(pid)
                    continue
                got,status=os.waitpid(pid,os.WNOHANG)
                self.case.assertEqual(got,pid,'finite adopted fixture failed to reap')
                reaped.append({'pid':pid,'wait_status':status})
            self.summary.setdefault('adopted_reaped',[]).append(reaped)

    def run(self):
        import shutil,traceback
        error=None
        try:
            if self.trial=='positive':self.positive()
            elif self.trial=='mixed':self.positive(True)
            else:self.matrix(self.trial)
        except _RecoveryHarnessInjectedFailure as exc:
            if self.trial not in {'ipc_failure_live','ipc_failure_descendant'}:raise
            self.summary.update(expected_injection=str(exc),injection_traceback=traceback.format_exc())
        except BaseException:
            error=traceback.format_exc();raise
        finally:
            body_error=error;snapshot_error=cleanup_error=None;snapshot_exception=None;clean=False
            try:
                try:
                    if self.f.root.exists() and 'failure-state' not in self.summary.get('facts',{}):self.save_state('failure-state' if error else 'final-state')
                except BaseException as exc:
                    snapshot_exception=exc;snapshot_error=traceback.format_exc()
                finally:
                    # Snapshot/proof I/O cannot bypass bounded owned cleanup.
                    try:clean=self.case.doCleanups()
                    except BaseException:cleanup_error=traceback.format_exc()
                    if not clean and cleanup_error is None:cleanup_error='owned child/custody cleanup failed'
                    self.summary['cleanup_passed']=clean
            finally:
                error=error or snapshot_error or cleanup_error
                self.summary.update(error=error,snapshot_error=snapshot_error,cleanup_error=cleanup_error,events=self.events)
                (self.control/'proof.json').write_text(json.dumps(self.summary,indent=2)+'\n')
            if not clean:raise AssertionError(cleanup_error)
            if snapshot_exception is not None and body_error is None:raise snapshot_exception



class RecoveryProcessTests(unittest.TestCase):
    """Each method launches its own finite subreaper host and fresh coordinators."""
    def trial(self,name):
        import os,subprocess,tempfile,uuid
        configured=os.environ.get('ATLAS_RECOVERY_TEST_EVIDENCE')
        base=Path(configured) if configured else Path(tempfile.mkdtemp(prefix='atlas-recovery-process-'))
        base.mkdir(parents=True,exist_ok=True)
        control=base/(name+'-'+uuid.uuid4().hex);control.mkdir()
        script="import importlib.util,sys;from pathlib import Path\ns=importlib.util.spec_from_file_location('actual_recovery_process_tests',sys.argv[1]);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);m._RecoveryProcessTrial(Path(sys.argv[2]),sys.argv[3]).run()"
        child=subprocess.Popen([sys.executable,'-B','-c',script,str(Path(__file__).resolve()),str(control),name],
            env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'},
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        captured=[]
        def capture(timeout):
            if not captured:captured.append(_capture_recovery_test_host(child,control,timeout=timeout))
            return captured[0]
        self.addCleanup(lambda:capture(0)) # Registered before any host observation.
        facts,out,err=capture(65)
        self.assertFalse(facts['timed_out'],'finite subreaper host deadline; evidence '+str(control))
        self.assertFalse(facts['capture_errors'],facts)
        self.assertTrue(facts['drain_complete'] and all(facts['streams_closed'].values()),facts)
        self.assertEqual(facts['returncode'],0,'process trial failed; evidence '+str(control)+'\n'+err.decode())
        proof=json.loads((control/'proof.json').read_text())
        self.assertIsNone(proof['error'],proof)
        return proof

    def test_recovery_process_distinct_A_B_C_five_once_markers(self):
        self.trial('positive')

    def test_recovery_process_mixed_complete_baseline_and_pending_item(self):
        self.trial('mixed')


    def test_recovery_process_actual_claim_applied_before_ack_refuses(self):
        self.trial('claim_applied')

    def test_recovery_process_actual_result_applied_kill_refuses(self):
        self.trial('result_applied')

    def test_recovery_process_actual_result_applied_lost_return_refuses(self):
        self.trial('result_lost_return')

    def test_recovery_process_actual_worker_returned_refuses(self):
        self.trial('worker_returned')

    def test_recovery_process_live_orphan_later_artifact_still_refuses(self):
        self.trial('live_worker')

    def test_recovery_process_descendant_survives_leader_refuses(self):
        self.trial('descendant')

    def test_recovery_process_live_controller_lock_loser(self):
        self.trial('lock')

    def test_recovery_process_two_resume_contenders_single_owner(self):
        self.trial('contenders')

    def test_recovery_process_actual_step_reserved_frontier_refuses(self):
        self.trial('step_reserved')


    def test_recovery_process_persisted_stop_removal_cannot_reopen(self):
        self.trial('persisted_stop')


class RecoveryHarnessFailureTests(unittest.TestCase):
    def test_recovery_harness_failure_after_fresh_ipc_retains_pending_ownership_and_cleans(self):
        for name in ('ipc_failure_live','ipc_failure_descendant'):
            with self.subTest(trial=name):
                runner=RecoveryProcessTests();self.addCleanup(runner.doCleanups)
                proof=runner.trial(name)
                pending={pid for pid in proof['pending_registered_before_injection'] if pid is not None}
                self.assertTrue(pending)
                self.assertEqual(proof['expected_injection'],'after fresh producer IPC before receipt/check/kill')
                self.assertTrue(proof['cleanup_passed'])
                self.assertEqual(len(proof['owned_children_reaped']),1)
                self.assertTrue(proof['owned_children_reaped'][0]['streams_closed'])
                reaped={row['pid'] for group in proof['adopted_reaped'] for row in group}
                not_current=set(proof.get('pending_not_current_child_after_coordinator_reap',[]))
                self.assertEqual(pending,reaped|not_current)
                self.assertFalse(reaped&not_current)

    def host(self,already_exited=False):
        import io,subprocess
        class Host:
            pid=43210
            def __init__(self):
                self.returncode=0 if already_exited else None
                self.stdin,self.stdout,self.stderr=io.BytesIO(),io.BytesIO(),io.BytesIO()
                self.calls=[];self.communications=0
            def communicate(self,timeout):
                self.calls.append(('communicate',timeout));self.communications+=1
                if self.communications==1:
                    raise subprocess.TimeoutExpired('synthetic host',timeout,output=b'partial stdout',stderr=b'partial stderr')
                if not already_exited and self.communications==2:
                    raise subprocess.TimeoutExpired('synthetic host',timeout,output=b'partial stdout after TERM',stderr=b'partial stderr after TERM')
                self.returncode=0 if already_exited else -9
                return b'partial stdout after TERM drained',b'partial stderr after TERM drained'
            def poll(self):self.calls.append(('poll',self.returncode));return self.returncode
            def terminate(self):self.calls.append(('terminate',))
            def kill(self):self.calls.append(('kill',));self.returncode=-9
            def wait(self,timeout):self.calls.append(('wait',timeout));return self.returncode
        return Host()

    def directory(self,name):
        import os,tempfile,uuid
        configured=os.environ.get('ATLAS_RECOVERY_TEST_EVIDENCE')
        if configured:
            directory=Path(configured)/(name+'-'+uuid.uuid4().hex);directory.mkdir(parents=True)
            return directory
        temporary=tempfile.TemporaryDirectory(prefix='atlas-harness-failure-');self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def capture_host(self,already_exited):
        directory=self.directory('host-timeout-exited' if already_exited else 'host-timeout-live');host=self.host(already_exited)
        facts,out,err=_capture_recovery_test_host(host,directory,timeout=.01)
        saved=json.loads((directory/'host-result.json').read_text())
        self.assertEqual(saved,facts)
        self.assertTrue(facts['timed_out']);self.assertTrue(facts['drain_complete'])
        self.assertTrue(all(facts['streams_closed'].values()))
        self.assertFalse(facts['capture_errors'])
        self.assertEqual((directory/'host.stdout').read_bytes(),out)
        self.assertEqual((directory/'host.stderr').read_bytes(),err)
        self.assertIn(b'partial stdout',out);self.assertIn(b'drained',out)
        self.assertIn(b'partial stderr',err)
        self.assertEqual(facts['stdout_sha256'],hashlib.sha256(out).hexdigest())
        self.assertEqual(facts['stderr_sha256'],hashlib.sha256(err).hexdigest())
        self.assertTrue(host.stdout.closed and host.stderr.closed and host.stdin.closed)
        return facts,host.calls

    def test_recovery_harness_live_host_timeout_keeps_partial_output_kills_reaps_and_closes(self):
        facts,calls=self.capture_host(False)
        self.assertEqual(facts['returncode'],-9)
        self.assertEqual(facts['actions'],['terminate','kill'])
        self.assertIn(('wait',1),calls)

    def test_recovery_harness_exited_at_timeout_still_drains_records_exit_and_closes(self):
        facts,calls=self.capture_host(True)
        self.assertEqual(facts['returncode'],0)
        self.assertEqual(facts['actions'],[])
        self.assertEqual(len([call for call in calls if call[0]=='communicate']),2)
        self.assertIn(('wait',1),calls)


    def fake_run(self,directory,*,body_error=True,cleanup_ok=True,proof_error=False):
        from types import SimpleNamespace
        calls=[]
        class Cleanup:
            def doCleanups(inner):calls.append('cleanup');return cleanup_ok
        class BrokenProof:
            def __truediv__(inner,name):return inner
            def write_text(inner,text):calls.append('proof');raise OSError('synthetic proof save error')
        trial=_RecoveryProcessTrial.__new__(_RecoveryProcessTrial)
        trial.case=Cleanup();trial.f=SimpleNamespace(root=directory);trial.events=[];trial.summary={};trial.trial='positive'
        trial.control=BrokenProof() if proof_error else directory
        def positive():
            if body_error:raise RuntimeError('synthetic original trial error')
        def snapshot(label):calls.append('snapshot');raise OSError('synthetic failure-state snapshot error')
        trial.positive=positive;trial.save_state=snapshot
        return trial,calls

    def test_recovery_harness_snapshot_failure_cannot_skip_cleanup_and_retains_all_errors(self):
        for cleanup_ok in (True,False):
            with self.subTest(cleanup_ok=cleanup_ok):
                directory=self.directory('snapshot-error')
                trial,calls=self.fake_run(directory,cleanup_ok=cleanup_ok)
                expected=RuntimeError if cleanup_ok else AssertionError
                with self.assertRaises(expected):trial.run()
                self.assertEqual(calls,['snapshot','cleanup'])
                proof=json.loads((directory/'proof.json').read_text())
                self.assertIn('synthetic original trial error',proof['error'])
                self.assertIn('synthetic failure-state snapshot error',proof['snapshot_error'])
                self.assertEqual(proof['cleanup_passed'],cleanup_ok)
                self.assertEqual(proof['cleanup_error'],None if cleanup_ok else 'owned child/custody cleanup failed')

    def test_recovery_harness_proof_save_failure_occurs_only_after_unconditional_cleanup(self):
        directory=self.directory('proof-save-error')
        trial,calls=self.fake_run(directory,body_error=False,proof_error=True)
        with self.assertRaisesRegex(OSError,'synthetic proof save error'):trial.run()
        self.assertEqual(calls,['snapshot','cleanup','proof'])
        self.assertTrue(trial.summary['cleanup_passed'])
        self.assertIn('snapshot error',trial.summary['snapshot_error'])
        (directory/'control-result.json').write_text(json.dumps({'calls':calls,'cleanup_passed':trial.summary['cleanup_passed'],
            'snapshot_error':trial.summary['snapshot_error'],'proof_error':'synthetic proof save error'},indent=2)+'\n')


    def test_recovery_harness_pending_cleanup_checks_current_child_and_group_before_signaling(self):
        import signal
        from types import SimpleNamespace
        from unittest.mock import patch
        for owned in (False,True):
            with self.subTest(current_child=owned):
                directory=self.directory('pending-custody-check')
                trial=_RecoveryProcessTrial.__new__(_RecoveryProcessTrial)
                trial.case=self;trial.summary={};trial.adopted=[(123,None)]
                trial.control_values={name:str(directory/name) for name in ('producer_release','descendant_release')}
                state={'exited':False,'clock':0}
                def waitid(*args):
                    if not owned:raise ChildProcessError('not this host child')
                    return SimpleNamespace(si_status=0) if state['exited'] else None
                def clock():state['clock']+=.1;return state['clock']
                def terminate(pid,sig):state['exited']=True
                with patch('os.waitid',side_effect=waitid),patch('os.getpgid',return_value=999), \
                     patch('os.kill',side_effect=terminate) as kill,patch('os.killpg') as group, \
                     patch('os.waitpid',return_value=(123,0)),patch('time.monotonic',side_effect=clock),patch('time.sleep'):
                    trial.cleanup_adopted()
                group.assert_not_called()
                if owned:
                    kill.assert_called_once_with(123,signal.SIGTERM)
                    self.assertEqual(trial.summary['adopted_reaped'],[[{'pid':123,'wait_status':0}]])
                else:
                    kill.assert_not_called()
                    self.assertEqual(trial.summary['pending_not_current_child_after_coordinator_reap'],[123])
                (directory/'control-result.json').write_text(json.dumps({'current_child':owned,
                    'group_signal_calls':group.call_count,'direct_signal_calls':kill.call_count,'summary':trial.summary},indent=2)+'\n')
