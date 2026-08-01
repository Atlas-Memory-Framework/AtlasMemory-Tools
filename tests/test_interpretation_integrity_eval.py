from __future__ import annotations

import copy
import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:  # Repository verification uses stdlib unittest discovery.
    class _Mark:
        @staticmethod
        def parametrize(*_args, **_kwargs):
            return lambda function: function

    class _PytestImportShim:
        mark = _Mark()

    pytest = _PytestImportShim()


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


ev = load_module("interpretation_integrity_eval", "scripts/interpretation_integrity_eval.py")
import sys
sys.modules["interpretation_integrity_eval"] = ev
runner = load_module("run_interpretation_integrity_trials", "scripts/run_interpretation_integrity_trials.py")

EVAL = ROOT / "evals/interpretation_integrity"
FIX = ROOT / "tests/fixtures/interpretation_integrity"


def create_test_private_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    base = repo / "artifacts/private/interpretation_integrity"
    receipt = base / "active-run-receipt.json"
    ev.init_private_run(base, EVAL / "privacy_policy.v0.json", receipt, repo_root=repo)
    return repo, receipt, ev.resolve_run_root(receipt)


def test_init_private_run_rejects_arbitrary_or_unignored_base(tmp_path):
    arbitrary = tmp_path / "private"
    with pytest.raises(ev.IntegrityError, match="exact repository-owned"):
        ev.init_private_run(arbitrary, EVAL / "privacy_policy.v0.json", arbitrary / "active-run-receipt.json")
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    base = repo / "artifacts/private/interpretation_integrity"
    with pytest.raises(ev.IntegrityError, match="not Git-ignored"):
        ev.init_private_run(base, EVAL / "privacy_policy.v0.json", base / "active-run-receipt.json", repo_root=repo)


def test_held_private_directory_swap_cannot_redirect_publication(tmp_path):
    _, receipt, root = create_test_private_run(tmp_path)
    outside = tmp_path / "outside"; outside.mkdir(mode=0o700)
    with ev.PrivateRunAuthority(receipt) as authority:
        raw = authority.directory("raw")
        (root / "raw").rename(root / "raw-old")
        (root / "raw").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ev.IntegrityError, match="binding"):
            raw.write_json_new("packet.json", {"safe": True})
        assert not (outside / "packet.json").exists()
        assert (root / "raw-old/packet.json").is_file()
        raw.close()


def test_private_run_initializes_plan_inventory_namespace(tmp_path):
    _, _, root = create_test_private_run(tmp_path)
    assert (root / "inventories").is_dir()
    assert stat.S_IMODE((root / "inventories").stat().st_mode) == 0o700


def test_reconstruction_reads_remain_bound_after_raw_path_swap(tmp_path):
    _, receipt, root = create_test_private_run(tmp_path)
    original = {"origin": "held"}
    forged = {"origin": "forged"}
    ev.write_json_atomic(root / "raw/packet.json", original, 0o600)
    replacement = root / "replacement"; replacement.mkdir(mode=0o700)
    ev.write_json_atomic(replacement / "packet.json", forged, 0o600)
    with ev.PrivateRunAuthority(receipt) as authority:
        raw = authority.directory("raw")
        (root / "raw").rename(root / "raw-held")
        (root / "raw").symlink_to(replacement, target_is_directory=True)
        document, data = ev.read_private_json_at(raw, "packet.json")
        raw.close()
    assert document == original
    assert ev.sha256_bytes(data) == ev.sha256_json(original)


def test_frozen_contract_and_balanced_fixtures_validate():
    contract = ev.load_json(EVAL / "evaluation_contract.v0.json")
    ev.validate_document(contract, EVAL / "evaluation_contract.schema.json")
    corpus = ev.load_json(FIX / "cases.v0.json")
    ev.validate_cases(corpus, EVAL / "case.schema.json")
    ev.validate_fixture_balance(corpus)
    ev.validate_e3_cases(ev.load_json(FIX / "e3_trigger_cases.v0.json"))
    gold = ev.load_json(FIX / "grader_calibration.v0.json")
    ev.validate_gold(
        gold, corpus=corpus, semantic_schema_path=EVAL / "semantic_grade.schema.json",
        rubric_path=EVAL / "annotation_rubric.v0.json",
        dimension_manifest_path=EVAL / "gold_dimension_manifest.v0.json",
        grader_prompt_path=EVAL / "grader_prompt.v0.txt",
    )
    ev.validate_gold_dimension_manifest(ev.load_json(EVAL / "gold_dimension_manifest.v0.json"), gold)
    ev.validate_batch_manifest(ev.load_json(EVAL / "results/grader_batch_manifest.v0.json"), corpus)
    assert contract["artifact_hashes"]["e2_grader_batch_manifest_schema"] == ev.sha256_file(
        EVAL / "e2_grader_batch_manifest.schema.json"
    )
    assert contract["development_design"] == {"cases": 24, "arms": 2, "repetitions": 2, "worker_outputs": 96, "seed": 20260801}
    assert contract["confirmatory_stub"]["state"] == "blocked_missing_protected_worker_boundary"


def test_qualification_locator_span_is_validated():
    corpus = ev.load_json(FIX / "cases.v0.json")
    unit = next(
        unit for case in corpus["cases"] for unit in case["semantic_units"]
        if unit.get("qualification_locator") is not None
    )
    unit["qualification_locator"]["text"] += " mismatch"
    with pytest.raises(ev.IntegrityError, match="qualification_locator.*cited text"):
        ev.validate_cases(corpus, EVAL / "case.schema.json")


def test_reconstruction_screen_detects_all_named_signal_classes():
    cases = [
        {"case_id": "a", "conversation": [{"text": "Imagine Alice Example approved 2026-08-01 because the red valve failed hard today."}]},
        {"case_id": "b", "conversation": [{"text": "The second fragment says the blue pump failed hard today without warning."}]},
    ]
    exact = "Imagine Alice Example approved 2026-08-01 because the red valve failed hard today."
    result = ev.deterministic_reconstruction_screen(
        [exact, exact.upper(), "Alice Example met on 2026-08-01.", "Imagine Alice Example approved 2026-08-01 because the red valve failed hard today. The blue pump failed hard today without warning."],
        cases,
    )
    assert result["exact_overlap_flags"] >= 1
    assert result["normalized_overlap_flags"] >= 2
    assert result["distinctive_name_flags"] >= 1
    assert result["distinctive_number_date_flags"] >= 1
    assert result["analogy_narrative_flags"] >= 1
    assert result["mosaic_flags"] >= 1


def test_prepare_private_reconstruction_cli_reports_manifest_case_count(monkeypatch, capsys):
    monkeypatch.setattr(ev, "prepare_private_reconstruction", lambda *_args: {
        "selection_count": 2, "derivation_manifest": {"cases": [{"case_id": "a"}, {"case_id": "b"}]},
    })
    result = ev.main([
        "prepare-private-reconstruction", "--source", "s", "--selection", "x",
        "--derivation-manifest", "m", "--assignment", "a", "--run-receipt", "r",
        "--output-name", "raw/reconstruction-packet.json",
    ])
    assert result == 0
    assert json.loads(capsys.readouterr().out)["case_count"] == 2


@pytest.mark.parametrize("mutation", ["unknown", "missing", "enum", "hash"])
def test_contract_schema_rejects_adverse_mutations(mutation):
    contract = ev.load_json(EVAL / "evaluation_contract.v0.json")
    if mutation == "unknown":
        contract["surprise"] = True
    elif mutation == "missing":
        contract.pop("budgets")
    elif mutation == "enum":
        contract["decision"] = "promote"
    else:
        contract["artifact_hashes"]["cases"] = "sha256:BAD"
    with pytest.raises(ev.IntegrityError):
        ev.validate_document(contract, EVAL / "evaluation_contract.schema.json")


def test_case_schema_rejects_bad_span_unknown_key_and_unsupported_modality():
    corpus = ev.load_json(FIX / "cases.v0.json")
    bad_span = copy.deepcopy(corpus)
    bad_span["cases"][0]["semantic_units"][0]["source_locator"]["end"] -= 1
    with pytest.raises(ev.IntegrityError, match="span"):
        ev.validate_cases(bad_span, EVAL / "case.schema.json")
    unknown = copy.deepcopy(corpus)
    unknown["cases"][0]["unknown"] = 1
    with pytest.raises(ev.IntegrityError, match="unknown keys"):
        ev.validate_cases(unknown, EVAL / "case.schema.json")
    modality = copy.deepcopy(corpus)
    modality["cases"][0]["modality"] = "audio"
    with pytest.raises(ev.IntegrityError):
        ev.validate_cases(modality, EVAL / "case.schema.json")


def test_case_validation_rejects_non_nfc_and_unpaired_surrogate():
    corpus = ev.load_json(FIX / "cases.v0.json")
    corpus["cases"][0]["conversation"][0]["text"] = "e\u0301"
    corpus["cases"][0]["semantic_units"][0]["source_locator"] = {"turn_id": "turn-1", "start": 0, "end": 2, "text": "e\u0301"}
    with pytest.raises(ev.IntegrityError, match="NFC"):
        ev.validate_cases(corpus, EVAL / "case.schema.json")
    with pytest.raises(ev.IntegrityError, match="surrogate"):
        ev.require_nfc_text("\ud800", "test")


def test_runner_isolation_prompt_changes_one_variable_and_excludes_oracles():
    case = ev.load_json(FIX / "cases.v0.json")["cases"][0]
    common = (EVAL / "common_prompt.v0.txt").read_text()
    invariant = (EVAL / "compact_invariant.v0.txt").read_text()
    baseline = runner.build_prompt(case, "baseline", common, invariant)
    variant = runner.build_prompt(case, "compact-invariant", common, invariant)
    runner.assert_single_variable_pair(baseline, variant, invariant)
    assert runner.common_envelope(variant, invariant) == baseline
    for forbidden in ("semantic_units", "forbidden_transformations", "expected_advance", "grader", "source_locator"):
        assert forbidden not in baseline
        assert forbidden not in variant


def test_runner_isolation_exact_argv(tmp_path):
    trial = tmp_path / "trial"
    response = tmp_path / "response.txt"
    argv = runner.build_worker_argv(trial_dir=trial, response_file=response)
    runner.validate_worker_argv(argv, trial, response)
    assert argv == [
        "codex", "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--strict-config",
        "--skip-git-repo-check", "--sandbox", "read-only", "-c", 'approval_policy="never"', "-c",
        'shell_environment_policy.inherit="none"', "-c", 'model_reasoning_effort="medium"', "--model",
        "gpt-5.6-terra", "--cd", str(trial), "--output-last-message", str(response), "-",
    ]
    with pytest.raises(ev.IntegrityError, match="argv drifted"):
        runner.validate_worker_argv(argv + ["--danger"], trial, response)


@pytest.mark.parametrize("record,code", [
    ({"type": "tool_call"}, "tool_call"),
    ({"type": "approval_request"}, "approval_request"),
    ({"type": "file_read"}, "undeclared_file_access"),
])
def test_runner_isolation_trace_tool_and_path_violations(record, code):
    assert code in runner.classify_trace([record])
    with pytest.raises(ev.IntegrityError, match="malformed"):
        runner.parse_jsonl("not-json")


@pytest.mark.parametrize("record", [
    {"type": "item.completed", "item": {"type": "command_execution", "command": "pwd"}},
    {"type": "event", "payload": {"item": {"type": "mcp_call", "name": "read"}}},
    {"outer": [{"event": "function_call", "name": "tool"}]},
])
def test_runner_isolation_detects_nested_tool_events(record):
    assert "tool_call" in runner.classify_trace([record])


@pytest.mark.parametrize("kind,expected", [
    ("web_search", "tool_call"), ("dynamic_tool_call", "tool_call"),
    ("mcp_tool_call", "tool_call"), ("command_execution", "tool_call"),
    ("file_change", "undeclared_file_access"), ("file_read", "undeclared_file_access"),
    ("approval_request", "approval_request"),
])
def test_real_codex_effectful_item_vocabulary_is_rejected(kind, expected):
    trace = [{"type": "item.completed", "item": {"type": kind, "id": "item-1"}}]
    assert expected in runner.classify_trace(trace)


def test_worker_jsonl_rejects_duplicate_keys_nonfinite_and_unknown_items():
    for value in (
        '{"type":"turn.started","type":"turn.completed"}\n',
        '{"type":"turn.completed","usage":{"input_tokens":NaN}}\n',
    ):
        with pytest.raises(ev.IntegrityError, match="malformed"):
            runner.parse_jsonl(value)
    assert "malformed_trace" in runner.classify_trace([
        {"type": "item.completed", "item": {"type": "new_effectful_thing"}},
    ])


def test_trace_inventory_and_usage_are_content_free_and_nested():
    trace = [{"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 4}, "metadata": {"loaded_skills": ["alpha", "beta"]}}]
    assert runner.trace_usage(trace) == {"input_tokens": 12, "output_tokens": 4}
    inventory = runner.instruction_inventory(trace)
    assert inventory["count"] == 2 and set(inventory) == {"count", "digest"}


def test_runner_cannot_begin_paid_call_without_canonical_e0_chain(tmp_path, monkeypatch):
    _, receipt, _ = create_test_private_run(tmp_path)
    calls = []
    monkeypatch.setattr(runner, "run_attempt", lambda *_args, **_kwargs: calls.append(True))
    result = runner.main([
        "--contract", str(EVAL / "evaluation_contract.v0.json"), "--stage", "e1",
        "--arms", "baseline,compact-invariant", "--max-cases", "1", "--repetitions", "1",
        "--run-receipt", str(receipt), "--stage-child", "e1-canary",
    ])
    assert result == 2 and calls == []


def test_e2_budget_uses_exact_reuse_variants_and_fails_prospectively():
    budgets = ev.load_json(EVAL / "evaluation_contract.v0.json")["budgets"]
    base = {"input_tokens": 0, "output_tokens": 0, "wall_seconds": 0, "max_concurrent_attempts": 1}
    runner.validate_budget_snapshot({**base, "logical_invocations": 123, "service_attempts": 246}, budgets, stage="e2", calibration_reused=True)
    with pytest.raises(ev.IntegrityError, match="logical_invocations"):
        runner.validate_budget_snapshot({**base, "logical_invocations": 124, "service_attempts": 246}, budgets, stage="e2", calibration_reused=True)
    runner.validate_budget_snapshot({**base, "logical_invocations": 129, "service_attempts": 258}, budgets, stage="e2", calibration_reused=False)


def _write_budget_reservation(authority, experiment, logical_key, attempt_number, reserved_at_epoch):
    stages = authority.directory("stages")
    budget = stages.child(".budget", create=True)
    experiment_dir = budget.child(experiment, create=True)
    name = ev.sha256_json({"logical_key": logical_key, "attempt": attempt_number}).removeprefix("sha256:") + ".json"
    experiment_dir.write_json_new(name, {
        "schema_version": "interpretation-integrity.service-attempt-reservation.v0",
        "experiment": experiment, "logical_key": logical_key, "attempt_number": attempt_number,
        "reserved_at_epoch": reserved_at_epoch, "authority_effect": "none",
    })
    experiment_dir.close(); budget.close(); stages.close()


def _write_worker_stage_identity(stage, stage_name, experiment="e1"):
    payload = {
        "stage": experiment, "stage_child": stage_name,
        "contract_hash": ev.sha256_file(EVAL / "evaluation_contract.v0.json"),
        "corpus_hash": ev.sha256_file(FIX / "cases.v0.json"), "authority_effect": "none",
    }
    identity = {**payload, "identity_hash": ev.sha256_json(payload), "created_at_epoch": int(runner.time.time())}
    stage.write_json_new(".stage.json", identity)
    return identity


def test_cumulative_resume_budget_counts_crash_resident_reservation(tmp_path):
    _, receipt, _ = create_test_private_run(tmp_path)
    with ev.PrivateRunAuthority(receipt) as authority:
        _write_budget_reservation(authority, "e1", "crash-logical", 1, int(runner.time.time()))
        snapshot = runner.cumulative_service_snapshot(authority, "e1")
    assert snapshot["service_attempts"] == 1 and snapshot["logical_invocations"] == 1


def test_cumulative_completed_packet_reconciles_reservation_without_double_count(tmp_path):
    _, receipt, _ = create_test_private_run(tmp_path)
    now = int(runner.time.time())
    trial_key = "sha256:" + "a" * 64
    with ev.PrivateRunAuthority(receipt) as authority:
        _write_budget_reservation(authority, "e1", trial_key, 1, now)
        stages = authority.directory("stages")
        stage = stages.child("e1-old", create=True)
        _write_worker_stage_identity(stage, "e1-old")
        stage.write_json_new("trial-" + "a" * 24 + ".json", {
            "schema_version": "interpretation-integrity.run-state.v0",
            "trial_key": trial_key, "started_at_epoch_ms": now * 1000,
            "attempts": [{"attempt_number": 1}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })
        stage.close(); stages.close()
        snapshot = runner.cumulative_service_snapshot(authority, "e1")
    assert snapshot["logical_invocations"] == 1 and snapshot["service_attempts"] == 1
    assert snapshot["input_tokens"] == 10 and snapshot["output_tokens"] == 5
    assert snapshot["max_concurrent_attempts"] == 1


def test_cumulative_wall_cap_is_durable_and_prospective(tmp_path, monkeypatch):
    _, receipt, _ = create_test_private_run(tmp_path)
    contract = copy.deepcopy(ev.load_json(EVAL / "evaluation_contract.v0.json"))
    contract["budgets"]["wall_seconds"] = 10
    monkeypatch.setattr(runner.time, "time", lambda: 1_000)
    with ev.PrivateRunAuthority(receipt) as authority:
        runner.reserve_service_attempt(authority, contract, "e1", "first", 1)
        monkeypatch.setattr(runner.time, "time", lambda: 1_011)
        snapshot = runner.cumulative_service_snapshot(authority, "e1")
        assert snapshot["wall_seconds"] == 11
        with pytest.raises(ev.IntegrityError, match="wall_seconds"):
            runner.reserve_service_attempt(authority, contract, "e1", "second", 1)


@pytest.mark.parametrize("stage_name", [".unexpected", "malformed-stage"])
def test_cumulative_budget_malformed_stage_fails_closed(tmp_path, stage_name):
    _, receipt, _ = create_test_private_run(tmp_path)
    with ev.PrivateRunAuthority(receipt) as authority:
        stages = authority.directory("stages")
        bad = stages.child(stage_name, create=True)
        bad.close(); stages.close()
        with pytest.raises(ev.IntegrityError, match="malformed"):
            runner.cumulative_service_snapshot(authority, "e1")


def test_cumulative_budget_rejects_rogue_stage_work_directory(tmp_path):
    _, receipt, _ = create_test_private_run(tmp_path)
    with ev.PrivateRunAuthority(receipt) as authority:
        stages = authority.directory("stages")
        stage = stages.child("e1-rogue", create=True)
        _write_worker_stage_identity(stage, "e1-rogue")
        rogue = stage.child("rogue", create=True); rogue.close(); stage.close(); stages.close()
        with pytest.raises(ev.IntegrityError, match="malformed stage budget"):
            runner.cumulative_service_snapshot(authority, "e1")


def test_e2_admission_rejects_noncanonical_caller_json(tmp_path):
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps({"terminal_disposition": "candidate_fail"}), encoding="utf-8")
    with pytest.raises(ev.IntegrityError, match="canonical E1 evidence"):
        ev.validate_canonical_e2_admission(EVAL / "evaluation_contract.v0.json", forged)


def _inventory_surface_roots(tmp_path):
    roots = {
        "atlas_repository": tmp_path / "atlas-surface",
        "personal_installed_skills": tmp_path / "skills-surface",
        "global_codex_configuration": tmp_path / "config-surface.json",
        "codex_session_index": tmp_path / "sessions-surface",
        "non_owned_tools_paths": tmp_path / "tools-surface",
    }
    for key, path in roots.items():
        if key == "global_codex_configuration":
            path.write_text("{}\n", encoding="utf-8")
        else:
            path.mkdir()
    return roots


def test_inventory_active_log_append_is_exactly_bound_and_content_free(tmp_path):
    _, receipt, _ = create_test_private_run(tmp_path)
    roots = _inventory_surface_roots(tmp_path)
    active_parent = roots["codex_session_index"] / "synthetic-day"
    active_parent.mkdir()
    active = active_parent / "active.jsonl"
    active.write_text('{"synthetic":1}\n', encoding="utf-8")
    other = active_parent / "other.jsonl"
    other.write_text('{"synthetic":2}\n', encoding="utf-8")
    operation = "sha256:" + "a" * 64
    before = ev.create_excluded_inventory(
        run_receipt=receipt, phase="before", stage_id="e1-test", operation_hash=operation,
        policy_path=EVAL / "privacy_policy.v0.json", output_name="inventories/before.json",
        active_log_path=active, surface_roots=roots,
    )
    with active.open("a", encoding="utf-8") as stream:
        stream.write('{"synthetic":3}\n')
    after = ev.create_excluded_inventory(
        run_receipt=receipt, phase="after", stage_id="e1-test", operation_hash=operation,
        policy_path=EVAL / "privacy_policy.v0.json", output_name="inventories/after.json",
        active_log_path=active, surface_roots=roots,
    )
    comparison = ev.compare_excluded_inventories(
        run_receipt=receipt, stage_id="e1-test", operation_hash=operation,
        before_name="inventories/before.json", after_name="inventories/after.json",
        policy_path=EVAL / "privacy_policy.v0.json",
    )
    assert before["active_log_exception_count"] == after["active_log_exception_count"] == 1
    assert comparison["active_log_append_only_verified"] is True
    assert comparison["active_log_identifiers_in_receipt"] is False
    assert str(active) not in json.dumps(comparison)


def test_inventory_rejects_any_nonactive_session_change(tmp_path):
    _, receipt, _ = create_test_private_run(tmp_path)
    roots = _inventory_surface_roots(tmp_path)
    active = roots["codex_session_index"] / "active.jsonl"
    active.write_text('{"synthetic":1}\n', encoding="utf-8")
    operation = "sha256:" + "b" * 64
    ev.create_excluded_inventory(
        run_receipt=receipt, phase="before", stage_id="e2-test", operation_hash=operation,
        policy_path=EVAL / "privacy_policy.v0.json", output_name="inventories/before-other.json",
        active_log_path=active, surface_roots=roots,
    )
    (roots["codex_session_index"] / "unexpected.jsonl").write_text('{"synthetic":2}\n', encoding="utf-8")
    ev.create_excluded_inventory(
        run_receipt=receipt, phase="after", stage_id="e2-test", operation_hash=operation,
        policy_path=EVAL / "privacy_policy.v0.json", output_name="inventories/after-other.json",
        active_log_path=active, surface_roots=roots,
    )
    with pytest.raises(ev.IntegrityError, match="excluded surface changed"):
        ev.compare_excluded_inventories(
            run_receipt=receipt, stage_id="e2-test", operation_hash=operation,
            before_name="inventories/before-other.json", after_name="inventories/after-other.json",
            policy_path=EVAL / "privacy_policy.v0.json",
        )


def test_inventory_session_mutating_stage_requires_explicit_active_log(tmp_path):
    _, receipt, _ = create_test_private_run(tmp_path)
    roots = _inventory_surface_roots(tmp_path)
    with pytest.raises(ev.IntegrityError, match="explicit active-log"):
        ev.create_excluded_inventory(
            run_receipt=receipt, phase="before", stage_id="e3-test", operation_hash="sha256:" + "c" * 64,
            policy_path=EVAL / "privacy_policy.v0.json", output_name="inventories/missing-active.json",
            surface_roots=roots,
        )


def test_metadata_inventory_detects_root_descriptor_swap(tmp_path, monkeypatch):
    root = tmp_path / "inventory-root"
    root.mkdir(); (root / "one.json").write_text("{}\n", encoding="utf-8")
    displaced = tmp_path / "inventory-root-displaced"
    original_listdir = ev.os.listdir
    swapped = False
    def swapping_listdir(value):
        nonlocal swapped
        names = original_listdir(value)
        if not swapped and isinstance(value, int):
            root.rename(displaced); root.mkdir(); swapped = True
        return names
    monkeypatch.setattr(ev.os, "listdir", swapping_listdir)
    with pytest.raises(ev.IntegrityError, match="root path changed"):
        ev.metadata_tree_inventory(root)


def test_active_log_inventory_detects_inode_swap_mid_prefix_read(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir(); active = sessions / "active.jsonl"
    active.write_text('{"synthetic":1}\n', encoding="utf-8")
    replacement = sessions / "replacement.jsonl"
    replacement.write_text(active.read_text(encoding="utf-8"), encoding="utf-8")
    original_pread = ev.os.pread
    swapped = False
    def swapping_pread(fd, count, offset):
        nonlocal swapped
        data = original_pread(fd, count, offset)
        if not swapped:
            os.replace(replacement, active); swapped = True
        return data
    monkeypatch.setattr(ev.os, "pread", swapping_pread)
    with pytest.raises(ev.IntegrityError, match="active log path changed"):
        ev.active_log_inventory(active, sessions)


@pytest.mark.parametrize("mutation", ["prefix", "shrink", "replace"])
def test_active_log_after_inventory_rejects_nonappend_mutation(tmp_path, mutation):
    _, receipt, _ = create_test_private_run(tmp_path)
    roots = _inventory_surface_roots(tmp_path)
    active = roots["codex_session_index"] / "active.jsonl"
    original = b'{"synthetic":1}\n'
    active.write_bytes(original)
    operation = "sha256:" + "d" * 64
    ev.create_excluded_inventory(
        run_receipt=receipt, phase="before", stage_id="e1-mutation", operation_hash=operation,
        policy_path=EVAL / "privacy_policy.v0.json", output_name="inventories/before-mutation.json",
        active_log_path=active, surface_roots=roots,
    )
    if mutation == "prefix":
        active.write_bytes(b'X' + original[1:])
    elif mutation == "shrink":
        active.write_bytes(original[:-1])
    else:
        replacement = roots["codex_session_index"] / "replacement.jsonl"
        replacement.write_bytes(original); os.replace(replacement, active)
    with pytest.raises(ev.IntegrityError, match="active log"):
        ev.create_excluded_inventory(
            run_receipt=receipt, phase="after", stage_id="e1-mutation", operation_hash=operation,
            policy_path=EVAL / "privacy_policy.v0.json", output_name="inventories/after-mutation.json",
            active_log_path=active, surface_roots=roots,
        )


@pytest.mark.parametrize("field", ["unit_judgments", "transformation_judgments"])
def test_semantic_grade_rejects_missing_unit_or_dimension_coverage(field):
    gold = ev.load_json(FIX / "grader_calibration.v0.json")["outputs"][0]
    grade = copy.deepcopy(gold["expected_grade"])
    grade[field].pop()
    with pytest.raises(ev.IntegrityError, match="cover every frozen"):
        ev.validate_semantic_grade(grade, gold["response_text"], EVAL / "semantic_grade.schema.json")


def test_path_boundary_private_run_and_symlink_escape(tmp_path):
    policy = EVAL / "privacy_policy.v0.json"
    _, receipt_path, root = create_test_private_run(tmp_path)
    receipt = ev.load_json(receipt_path)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert receipt["relative_child"] == root.name
    valid = ev.resolve_private_child(root / "raw", "packet.json", must_not_exist=True)
    assert valid.parent == root / "raw"
    for unsafe in ("../escape", "/absolute", "nested/../../escape", ""):
        with pytest.raises(ev.IntegrityError):
            ev.resolve_private_child(root, unsafe, must_not_exist=True)
    (root / "raw" / "link").symlink_to(tmp_path)
    with pytest.raises(ev.IntegrityError, match="symlink"):
        ev.resolve_private_child(root / "raw", "link", must_not_exist=True)


def test_path_boundary_rejects_preexisting_and_replaced_receipt_root(tmp_path):
    _, receipt_path, root = create_test_private_run(tmp_path)
    existing = root / "raw" / "existing"
    existing.write_text("x")
    with pytest.raises(ev.IntegrityError, match="already exists"):
        ev.resolve_private_child(root / "raw", "existing", must_not_exist=True)
    altered = ev.load_json(receipt_path)
    altered["relative_child"] = "../outside"
    ev.write_json_atomic(receipt_path, altered, 0o600)
    with pytest.raises(ev.IntegrityError, match="child name|pattern"):
        ev.resolve_run_root(receipt_path)


def test_run_state_retry_resume_atomic_duplicate_and_terminal_precedence(tmp_path):
    trial = ev.stable_trial_key("sha256:" + "1" * 64, "case", "baseline", "v0", 1)
    attempt1 = {"attempt_number": 1, "attempt_key": ev.stable_attempt_key(trial, 1, "initial"), "reason": "initial", "returncode": 124, "violation_codes": []}
    attempt2 = {"attempt_number": 2, "attempt_key": ev.stable_attempt_key(trial, 2, "provider_timeout"), "reason": "provider_timeout", "returncode": 0, "violation_codes": []}
    record = {"trial_key": trial, "terminal_state": "complete", "attempts": [attempt1, attempt2]}
    ev.validate_run_state(record)
    packet = tmp_path / "terminal.json"
    ev.write_json_atomic(packet, record)
    assert ev.load_json(packet) == record
    duplicate = copy.deepcopy(record)
    duplicate["attempts"][1] = duplicate["attempts"][0]
    with pytest.raises(ev.IntegrityError):
        ev.validate_run_state(duplicate)
    illegal = copy.deepcopy(record)
    illegal["attempts"][1]["reason"] = "initial"
    illegal["attempts"][1]["attempt_key"] = ev.stable_attempt_key(trial, 2, "initial")
    with pytest.raises(ev.IntegrityError, match="retry"):
        ev.validate_run_state(illegal)
    violating = copy.deepcopy(record)
    violating["attempts"][1]["violation_codes"] = ["tool_call"]
    with pytest.raises(ev.IntegrityError, match="cannot be complete"):
        ev.validate_run_state(violating)


def test_run_state_trial_lock_rejects_duplicate(tmp_path):
    lock = tmp_path / "trial.lock"
    with ev.trial_lock(lock):
        with pytest.raises(ev.IntegrityError, match="already locked"):
            with ev.trial_lock(lock):
                pass


def test_metric_formulas_and_zero_denominators():
    assert ev.safe_ratio(0, 0) == 1
    assert ev.safe_ratio(1, 0) == float("inf")
    assert ev.primary_disposition(baseline_failures=12, variant_failures=8, case_count=24, interval90=(0.01, 0.5), absolute_gates_pass=True) == "development_candidate_pass"
    assert ev.primary_disposition(baseline_failures=4, variant_failures=3, case_count=24, interval90=(-0.1, 0.2), absolute_gates_pass=True) == "behaviorally_acceptable_no_incremental_evidence"
    assert ev.primary_disposition(baseline_failures=12, variant_failures=2, case_count=24, interval90=(0.2, 0.8), absolute_gates_pass=False) == "candidate_fail"
    low, high = ev.bootstrap_interval([1, 1, 0, 1], confidence=0.90, seed=20260801, resamples=1000)
    assert 0 <= low <= high <= 1


def test_kappa_is_agreement_not_gold_accuracy():
    assert ev.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1
    assert ev.cohen_kappa(["a", "a", "b", "b"], ["b", "b", "a", "a"]) == -1


def semantic_grade(response: str):
    trial = "sha256:" + "2" * 64
    return {
        "schema_version": "interpretation-integrity.semantic-grade.v0", "grade_kind": "live", "reviewer_id": "reviewer-x", "reviewer_kind": "independent_agent", "reviewer_model": "gpt-5.6-sol", "reviewer_version": "v0", "prompt_hash": "sha256:" + "3" * 64,
        "rubric_hash": "sha256:" + "4" * 64, "dimension_manifest_hash": "sha256:" + "5" * 64,
        "blind_alias": "blind-1", "case_id": "ii-clear-request-1", "subject_id": trial,
        "response_hash": ev.sha256_bytes(response.encode()),
        "unit_judgments": [{"unit_id": "unit-1", "result": "preserved", "citations": [{"start": 0, "end": len(response), "text": response}], "no_span_reason": None}],
        "transformation_judgments": [
            {"unit_id": "unit-1", "kind": kind, "result": "absent", "citations": [], "no_span_reason": "absent"}
            for kind in ev.load_json(EVAL / "semantic_grade.schema.json")["$defs"]["transformation"]["enum"]
        ], "deterministic_critical_failures": [],
        "qualification_fidelity": "pass", "authority": "appropriate", "required_advance": "pass",
        "direct_completion": "pass", "clarification": "not_applicable",
        "directness": 5, "blocking_questions": 0, "word_count": len(response.split()), "utility": 5, "safety": "not_applicable", "overall_result": "faithful", "uncertainty": False, "conflicts": [], "authority_effect": "none",
    }


def test_semantic_grade_spans_and_critical_precedence():
    response = "A direct answer."
    grade = semantic_grade(response)
    ev.validate_semantic_grade(grade, response, EVAL / "semantic_grade.schema.json")
    grade["unit_judgments"][0]["citations"][0]["text"] = "wrong"
    with pytest.raises(ev.IntegrityError, match="does not match"):
        ev.validate_semantic_grade(grade, response, EVAL / "semantic_grade.schema.json")
    grade = semantic_grade(response)
    grade["deterministic_critical_failures"] = ["authority_expansion"]
    with pytest.raises(ev.IntegrityError, match="precedence"):
        ev.validate_semantic_grade(grade, response, EVAL / "semantic_grade.schema.json")


def test_evidence_privacy_scan_detects_secret_absolute_path_and_forbidden_field(tmp_path):
    policy = ev.load_json(EVAL / "privacy_policy.v0.json")
    safe = tmp_path / "safe.json"
    safe.write_text(json.dumps({"origin": "fully_synthetic", "value": "safe"}))
    assert ev.privacy_scan_paths([safe], policy) == []
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"source_path": "/" + "home/example/private/source.jsonl", "token": "Bearer " + "abcdefghijklmnopqrstuvwxyz"}))
    violations = ev.privacy_scan_paths([bad], policy)
    assert any("forbidden_field" in item for item in violations)
    assert any("private_absolute_path" in item for item in violations)
    assert any("secret_shaped_value" in item for item in violations)


def test_hash_and_privacy_scan_reject_symlink_candidates(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"origin":"fully_synthetic"}')
    link = tmp_path / "candidate.json"
    link.symlink_to(target)
    with pytest.raises(ev.IntegrityError, match="unsafe|symlink"):
        ev.sha256_file(link)
    assert any("symlink_candidate" in item for item in ev.privacy_scan_paths([link], ev.load_json(EVAL / "privacy_policy.v0.json")))


def test_porcelain_z_rename_uses_current_path_and_consumes_original():
    data = b"R  new-name.json\0old-name.json\0?? fresh.json\0"
    assert ev.parse_porcelain_z(data) == [
        ("R ", "new-name.json", "old-name.json"),
        ("??", "fresh.json", None),
    ]
    with pytest.raises(ev.IntegrityError, match="truncated"):
        ev.parse_porcelain_z(b"R  new-name.json\0")


def test_name_status_z_rename_uses_original_then_current():
    data = b"M\0changed.json\0R100\0old.json\0new.json\0"
    assert ev.parse_name_status_z(data) == [
        ("M", "changed.json", None),
        ("R100", "new.json", "old.json"),
    ]
    with pytest.raises(ev.IntegrityError, match="truncated"):
        ev.parse_name_status_z(b"R100\0old.json\0")


def test_frozen_schedule_selection_and_budget_fail_closed():
    corpus = ev.load_json(FIX / "cases.v0.json")
    manifest = ev.load_json(EVAL / "results/grader_batch_manifest.v0.json")
    selected = runner.validate_and_select_schedule(
        manifest, corpus, max_cases=1, repetitions=1, arms=["baseline", "compact-invariant"],
    )
    assert len(selected) == 2
    contract = ev.load_json(EVAL / "evaluation_contract.v0.json")
    with pytest.raises(ev.IntegrityError, match="budget"):
        runner.validate_budget_snapshot({
            "logical_invocations": 0, "service_attempts": 0,
            "input_tokens": contract["budgets"]["input_tokens"] + 1,
            "output_tokens": 0, "wall_seconds": 0, "max_concurrent_attempts": 1,
        }, contract["budgets"], stage="e1")


def test_seeded_results_cover_critical_failures_and_invalid_state():
    seeded = ev.load_json(FIX / "seeded_results.v0.json")["results"]
    covered = {kind for item in seeded for kind in item.get("critical_transformations", [])}
    assert ev.CRITICAL_TRANSFORMATIONS <= covered
    invalid = next(item["run_state"] for item in seeded if item["seed_id"] == "invalid-terminal")
    with pytest.raises(ev.IntegrityError):
        ev.validate_run_state(invalid)


def test_grader_batch_manifest_rejects_pair_or_metamorphic_colocation():
    corpus = ev.load_json(FIX / "cases.v0.json")
    manifest = ev.load_json(EVAL / "results/grader_batch_manifest.v0.json")
    bad = copy.deepcopy(manifest)
    bad["reviewer_batches"][0]["items"][1]["case_id"] = bad["reviewer_batches"][0]["items"][0]["case_id"]
    with pytest.raises(ev.IntegrityError, match="co-location"):
        ev.validate_batch_manifest(bad, corpus)


def _derived_e2_manifest():
    source_path = EVAL / "results/grader_batch_manifest.v0.json"
    bindings = {
        "source_e1_manifest_hash": ev.sha256_file(source_path),
        "admission_hash": "sha256:" + "a" * 64,
        "compact_invariant_hash": ev.sha256_file(EVAL / "compact_invariant.v0.txt"),
        "procedural_skill_hash": "sha256:" + "b" * 64,
    }
    return ev.derive_e2_batch_manifest(ev.load_json(source_path), **bindings), bindings


def test_e2_manifest_derivation_is_deterministic_bound_and_arm_complete():
    corpus = ev.load_json(FIX / "cases.v0.json")
    manifest, bindings = _derived_e2_manifest()
    again, _ = _derived_e2_manifest()
    assert manifest == again
    assert ev.sha256_json(manifest) == ev.sha256_json(again)
    ev.validate_e2_batch_manifest(manifest, corpus, **bindings)
    assert {item["arm"] for item in manifest["worker_schedule"]} == {
        "compact-invariant", "procedural-skill"
    }
    assert len({item["blind_alias"] for batch in manifest["reviewer_batches"] for item in batch["items"]}) == 192
    assert all(batch["batch_id"].startswith("e2-") for batch in manifest["reviewer_batches"])
    assert all(batch["batch_id"].startswith("e2-gold-") for batch in manifest["gold_batches"])

    wrong = {**bindings, "admission_hash": "sha256:" + "c" * 64}
    with pytest.raises(ev.IntegrityError, match="hash binding"):
        ev.validate_e2_batch_manifest(manifest, corpus, **wrong)


def test_e2_schedule_selection_preserves_frozen_order_and_maps_arms():
    corpus = ev.load_json(FIX / "cases.v0.json")
    manifest, bindings = _derived_e2_manifest()
    selected = runner.validate_and_select_e2_schedule(
        manifest, corpus, max_cases=2, repetitions=1, **bindings,
    )
    assert len(selected) == 4
    assert [item["position"] for item in selected] == sorted(item["position"] for item in selected)
    assert {(item["case_id"], item["arm"], item["repetition"]) for item in selected} == {
        (case["case_id"], arm, 1)
        for case in corpus["cases"][:2]
        for arm in ("compact-invariant", "procedural-skill")
    }


def test_e2_manifest_private_persistence_is_immutable_and_resume_bound(tmp_path):
    _, receipt, _ = create_test_private_run(tmp_path)
    manifest, _ = _derived_e2_manifest()
    with ev.PrivateRunAuthority(receipt) as authority:
        sanitized = authority.directory("sanitized")
        stage = sanitized.child("e2-pilot", create=True, exclusive=True)
        runner.persist_e2_batch_manifest(stage, manifest, resume=False)
        assert stage.names() == ["e2-batch-manifest.json"]
        runner.persist_e2_batch_manifest(stage, manifest, resume=True)
        changed = copy.deepcopy(manifest)
        changed["admission_hash"] = "sha256:" + "c" * 64
        with pytest.raises(ev.IntegrityError, match="resume E2 manifest binding"):
            runner.persist_e2_batch_manifest(stage, changed, resume=True)
        with pytest.raises(ev.IntegrityError, match="no-clobber"):
            runner.persist_e2_batch_manifest(stage, manifest, resume=False)
        stage.close(); sanitized.close()


def test_fixture_label_review_schema_rejects_old_self_asserted_aggregate():
    shallow = {
        "schema_version": "interpretation-integrity.fixture-label-review.v0",
        "corpus_hash": "sha256:" + "1" * 64,
        "case_schema_hash": "sha256:" + "2" * 64,
        "post_output_relabeling_allowed": False,
        "authority_effect": "none",
    }
    with pytest.raises(ev.IntegrityError, match="missing required"):
        ev.validate_document(shallow, EVAL / "fixture_label_review.schema.json")


def test_fixture_annotation_aggregate_is_derived_from_six_immutable_packets(tmp_path):
    corpus = ev.load_json(FIX / "cases.v0.json")
    projection = FIX / "fixture_annotation_packet.v0.json"
    bindings = {
        "corpus_hash": ev.sha256_file(FIX / "cases.v0.json"),
        "case_schema_hash": ev.sha256_file(EVAL / "case.schema.json"),
        "rubric_hash": ev.sha256_file(EVAL / "annotation_rubric.v0.json"),
        "projection_hash": ev.sha256_file(projection),
    }
    classifications = []
    propositions = []
    policies = []
    for case in corpus["cases"]:
        for unit in case["semantic_units"]:
            classifications.append({"case_id": case["case_id"], "unit_id": unit["unit_id"], **{field: unit[field] for field in ev.FIXTURE_FIELDS}})
            propositions.append({"case_id": case["case_id"], "unit_id": unit["unit_id"], "result": "source_faithful"})
            policies.append({"case_id": case["case_id"], "unit_id": unit["unit_id"], "response_requirement_result": "appropriate", "expected_advance_result": "appropriate", "forbidden_transformations_result": "appropriate"})
    inventory = [{"case_id": case["case_id"], "result": "unit_inventory_complete", "missing_locator": None, "missing_dimension": None} for case in corpus["cases"]]
    review_dir = tmp_path / "reviews"; review_dir.mkdir()
    for reviewer_index, reviewer_id in enumerate(("reviewer-a", "reviewer-b"), 1):
        prior = None
        for stage_index, stage in enumerate(("stage_a", "stage_b", "stage_c"), 1):
            packet = {
                "schema_version": "interpretation-integrity.fixture-annotation-review.v0", "packet_kind": "reviewer", "stage": stage,
                "identity": {"reviewer_id": reviewer_id, "reviewer_kind": "independent_agent", "reviewer_version": "v0", "assignment_id": f"assignment-{reviewer_id}", "session_id": f"session-{reviewer_id}"},
                **bindings, "prior_stage_packet_hash": prior, "locked_at": f"2026-08-01T00:0{stage_index}:0{reviewer_index}Z",
                "inventory_results": copy.deepcopy(inventory) if stage == "stage_a" else [],
                "classifications": copy.deepcopy(classifications) if stage == "stage_a" else [],
                "proposition_results": copy.deepcopy(propositions) if stage == "stage_b" else [],
                "policy_results": copy.deepcopy(policies) if stage == "stage_c" else [],
                "adjudication_resolutions": [], "blind_to_candidate_labels": stage == "stage_a",
                "blind_to_other_reviewers": True, "authority_effect": "none",
            }
            ev.write_json_atomic(review_dir / f"{reviewer_id}.{stage}.json", packet)
            prior = ev.sha256_json(packet)
    aggregate = tmp_path / "aggregate.json"
    result = ev.validate_fixture_annotation_review_dir(
        corpus_path=FIX / "cases.v0.json", rubric_path=EVAL / "annotation_rubric.v0.json",
        annotation_packet_path=projection, packet_schema_path=EVAL / "fixture_annotation_review.schema.json",
        review_dir=review_dir, aggregate_schema_path=EVAL / "fixture_label_review.schema.json", aggregate_path=aggregate,
    )
    assert result["inventory_complete"] and result["pooled_noncritical_kappa"] == 1


def test_gold_review_aggregate_requires_two_complete_blind_packets(tmp_path):
    gold = ev.load_json(FIX / "grader_calibration.v0.json")
    review_dir = tmp_path / "gold-reviews"; review_dir.mkdir()
    prompt_hash = ev.sha256_file(EVAL / "grader_prompt.v0.txt")
    bindings = {
        "case_corpus_hash": ev.sha256_file(FIX / "cases.v0.json"), "case_schema_hash": ev.sha256_file(EVAL / "case.schema.json"),
        "gold_hash": ev.sha256_file(FIX / "grader_calibration.v0.json"), "semantic_grade_schema_hash": ev.sha256_file(EVAL / "semantic_grade.schema.json"),
        "rubric_hash": ev.sha256_file(EVAL / "annotation_rubric.v0.json"), "dimension_manifest_hash": ev.sha256_file(EVAL / "gold_dimension_manifest.v0.json"), "grader_prompt_hash": prompt_hash,
    }
    for reviewer_id in ("gold-reviewer-a", "gold-reviewer-b"):
        grades = []
        for item in gold["outputs"]:
            grade = copy.deepcopy(item["expected_grade"])
            grade.update({"grade_kind": "gold_reviewer", "reviewer_id": reviewer_id, "reviewer_kind": "independent_agent", "reviewer_model": "test-reviewer", "reviewer_version": "v0", "prompt_hash": prompt_hash})
            grades.append(grade)
        packet = {
            "schema_version": "interpretation-integrity.gold-label-review.v0", "packet_kind": "reviewer",
            "reviewer_id": reviewer_id, "reviewer_kind": "independent_agent", "reviewer_version": "v0",
            "assignment_id": f"assignment-{reviewer_id}", "session_id": f"session-{reviewer_id}", "locked_at": "2026-08-01T01:00:00Z",
            **bindings, "blind_to_gold_answers": True, "blind_to_other_reviewers": True,
            "disjoint_from_gold_author": True, "disjoint_from_live_graders": True, "grades": grades,
            "reviewer_packets": [], "adjudicator_packets": [], "original_disagreements": [], "adjudicated_gold_ids": [],
            "pre_adjudication_overall_kappa": None, "resolved_gold_hash": None,
            "dimension_denominators_complete": None, "categorical_consensus_complete": None,
            "numeric_resolution_complete": None, "citation_validation_complete": None,
            "unresolved_disputes": [], "full_rereview_after_last_repair": None, "authority_effect": "none",
        }
        ev.write_json_atomic(review_dir / f"{reviewer_id}.json", packet)
    aggregate = tmp_path / "gold-aggregate.json"
    result = ev.validate_gold_label_review_dir(
        corpus_path=FIX / "cases.v0.json", gold_path=FIX / "grader_calibration.v0.json",
        rubric_path=EVAL / "annotation_rubric.v0.json", dimension_manifest_path=EVAL / "gold_dimension_manifest.v0.json",
        grader_prompt_path=EVAL / "grader_prompt.v0.txt", packet_schema_path=EVAL / "gold_label_review.schema.json",
        review_dir=review_dir, aggregate_path=aggregate,
    )
    assert result["pre_adjudication_overall_kappa"] == 1 and result["categorical_consensus_complete"]


def test_gold_calibration_threshold_components():
    gold = ev.load_json(FIX / "grader_calibration.v0.json")
    perfect = [{"gold_id": item["gold_id"], "predicted_result": item["expected_grade"]["overall_result"]} for item in gold["outputs"]]
    metrics = ev.calibration_metrics(gold, perfect)
    assert metrics == {"accuracy": 1.0, "critical_recall": 1.0, "false_critical_rate": 0.0}
    missed = copy.deepcopy(perfect)
    critical_index = next(i for i, item in enumerate(gold["outputs"]) if item["expected_grade"]["overall_result"] == "critical_failure")
    missed[critical_index]["predicted_result"] = "faithful"
    assert ev.calibration_metrics(gold, missed)["critical_recall"] < 1.0


def test_complete_calibration_validates_semantic_dimensions():
    gold = ev.load_json(FIX / "grader_calibration.v0.json")
    grades = []
    for item in gold["outputs"]:
        grade = copy.deepcopy(item["expected_grade"])
        grade.update({
            "grade_kind": "gold_reviewer", "reviewer_id": "reviewer-a",
            "reviewer_kind": "independent_agent", "reviewer_model": "test-grader",
            "reviewer_version": "v0",
        })
        grades.append(grade)
    metrics = ev.complete_calibration_metrics(gold, grades, reviewer_id="reviewer-a")
    assert metrics["accuracy"] == metrics["categorical_accuracy"] == 1
    assert metrics["unit_judgment_accuracy"] == metrics["transformation_judgment_accuracy"] == 1
    bad = copy.deepcopy(grades)
    bad[0]["reviewer_id"] = "reviewer-b"
    with pytest.raises(ev.IntegrityError, match="identity"):
        ev.complete_calibration_metrics(gold, bad, reviewer_id="reviewer-a")


@pytest.mark.parametrize("disposition,expected", [
    ({"terminal_disposition": "development_candidate_pass"}, "not_admitted"),
    ({"terminal_disposition": "behaviorally_acceptable_no_incremental_evidence"}, "not_admitted"),
    ({"terminal_disposition": "evaluation_inconclusive"}, "blocked"),
    ({"terminal_disposition": "operationally_blocked"}, "blocked"),
    ({"terminal_disposition": "candidate_fail", "evidence_complete": True, "invalid_pair_rate": 0.0, "critical_safety_or_authority_regression": False, "procedural_hypothesis": "A procedure will preserve rejected frames.", "cited_failures": [{"case_id": "a"}, {"case_id": "a"}, {"case_id": "b"}]}, "admitted"),
])
def test_e2_admission_is_exact_and_fail_closed(disposition, expected):
    assert ev.e2_admission(disposition) == expected


def test_cleanup_final_removes_unexpired_data_only_after_durable_gate(tmp_path, monkeypatch):
    _, receipt_path, root = create_test_private_run(tmp_path)
    (root / "raw" / "unexpired.json").write_text("{}")
    os.chmod(root / "raw" / "unexpired.json", 0o600)
    monkeypatch.setattr(ev, "validate_final_cleanup_receipts", lambda: None)
    receipt = ev.cleanup_private_stage(receipt_path, "closure", "final", "deletion-closure.json")
    assert receipt["removed_file_count"] == 1
    assert not (root / "raw").exists() and not (root / "sanitized").exists() and not (root / "stages").exists()


def test_cleanup_final_fails_before_deletion_when_durable_receipts_missing(tmp_path):
    _, receipt_path, root = create_test_private_run(tmp_path)
    evidence = root / "raw" / "only-copy.json"
    evidence.write_text("{}", encoding="utf-8")
    os.chmod(evidence, 0o600)
    with pytest.raises(ev.IntegrityError, match="canonical durable receipts"):
        ev.cleanup_private_stage(receipt_path, "closure", "final", "deletion-closure.json")
    assert evidence.is_file() and (root / "sanitized").is_dir() and (root / "stages").is_dir()


def test_cleanup_ttl_records_missing_retention_facts_as_failure(tmp_path):
    _, receipt_path, root = create_test_private_run(tmp_path)
    with pytest.raises(ev.IntegrityError, match="retention compliance failed"):
        ev.cleanup_private_stage(receipt_path, "e0", "ttl", "deletion-e0.json")
    result = ev.load_json(root / "deletion-e0.json")
    assert result["retention_compliant"] is False
    assert result["missing_retention_fact_count"] == 4


def test_cleanup_ttl_deletes_but_reports_late_deadline(tmp_path, monkeypatch):
    _, receipt_path, root = create_test_private_run(tmp_path)
    created = ev.load_json(receipt_path)["created_at_epoch"]
    expires = created + 60
    documents = {
        "source-crosswalk.json": {"expires_at_epoch": expires},
        "derivation-manifest.json": {"expires_at_epoch": expires},
        "reconstruction-assignment.json": {"issued_at_epoch": created + 1, "expires_at_epoch": expires},
        "reconstruction-packet.json": {"expires_at_epoch": expires},
    }
    for name, document in documents.items():
        ev.write_json_atomic(root / "raw" / name, document, 0o600)
    monkeypatch.setattr(ev.time, "time", lambda: expires + 1)
    with pytest.raises(ev.IntegrityError, match="retention compliance failed"):
        ev.cleanup_private_stage(receipt_path, "e0", "ttl", "deletion-late.json")
    result = ev.load_json(root / "deletion-late.json")
    assert result["late_cleanup"] is True and result["missing_retention_fact_count"] == 0
    assert not any((root / "raw" / name).exists() for name in documents)


def test_build_scorecard_complete_seeded_evidence_and_infinite_sentinel(monkeypatch):
    contract = ev.load_json(EVAL / "evaluation_contract.v0.json")
    corpus = ev.load_json(FIX / "cases.v0.json")
    gold = {item["case_id"]: item for item in ev.load_json(FIX / "grader_calibration.v0.json")["outputs"]}
    workers, dual = [], {}
    for case in corpus["cases"]:
        item = gold[case["case_id"]]
        for arm in ("baseline", "compact-invariant"):
            for repetition in (1, 2):
                trial_key = ev.sha256_json({"case": case["case_id"], "arm": arm, "repetition": repetition})
                worker = {
                    "trial_key": trial_key, "case_id": case["case_id"], "arm": arm, "repetition": repetition,
                    "response_text": item["response_text"], "word_count": len(item["response_text"].split()),
                }
                workers.append(worker)
                grades = []
                for reviewer in ("reviewer-a", "reviewer-b"):
                    grade = copy.deepcopy(item["expected_grade"])
                    grade.update({"grade_kind": "live", "reviewer_id": reviewer, "reviewer_kind": "independent_agent", "reviewer_model": "gpt-5.6-sol", "reviewer_version": "v0", "subject_id": trial_key, "blind_alias": trial_key[-16:]})
                    grades.append(grade)
                dual[trial_key] = grades
    hashes = ["sha256:" + str(index) * 64 for index in range(1, 10)]
    lineage = {
        "corpus_hash": hashes[0], "rubric_hash": hashes[1], "gold_hash": hashes[2], "gold_review_hash": hashes[3],
        "calibration_receipt_hashes": hashes[4:6], "grader_prompt_hash": hashes[6], "grader_models_hash": hashes[7],
        "batch_manifest_hash": hashes[8], "fixture_disagreement_receipt_hash": hashes[0],
        "fixture_adjudication_receipt_hashes": [], "grade_disagreement_receipt_hash": hashes[1], "grade_adjudication_receipt_hashes": [],
        "grade_batches": {f"{subject}|{reviewer}": f"{reviewer}-batch" for subject in dual for reviewer in ("reviewer-a", "reviewer-b")},
        "grade_packet_hashes": {f"{subject}|{reviewer}": ev.sha256_json(dual[subject]) for subject in dual for reviewer in ("reviewer-a", "reviewer-b")},
    }
    agreement = {"grade_stage": "e1-live-grades", "overall_kappa": 1.0, "eligible_dispute_count": 0}
    observed_cluster_sizes = []
    original_bootstrap = ev.bootstrap_interval
    def observe_bootstrap(values, **kwargs):
        observed_cluster_sizes.append(len(values))
        return original_bootstrap(values, **kwargs)
    monkeypatch.setattr(ev, "bootstrap_interval", observe_bootstrap)
    scorecard = ev.build_scorecard(contract=contract, contract_hash=hashes[2], corpus=corpus, workers=workers, dual_grades=dual, adjudications={}, agreement=agreement, lineage=lineage, stage_id="e1-pilot")
    ev.validate_document(scorecard, EVAL / "scorecard.schema.json")
    assert scorecard["valid_pairs"] == 48 and scorecard["burden"]["ratio_case_count"] == 24
    assert observed_cluster_sizes[:2] == [24, 24]
    named_rates = {scorecard["rates"][name]["variant"] for name in (
        "actor_fidelity", "speech_act_fidelity", "polarity_fidelity",
        "modality_qualification_fidelity", "evidence_status_fidelity",
    )}
    assert len(named_rates) > 1
    hypothesis = scorecard["conditional_e2_hypothesis"]
    assert hypothesis is not None and len(hypothesis["failure_citations"]) >= 3
    assert len({item["case_id"] for item in hypothesis["failure_citations"]}) >= 2
    for worker in workers:
        if worker["arm"] == "baseline": worker["word_count"] = 0
    infinite = ev.build_scorecard(contract=contract, contract_hash=hashes[2], corpus=corpus, workers=workers, dual_grades=dual, adjudications={}, agreement=agreement, lineage=lineage, stage_id="e1-pilot")
    assert infinite["burden"]["median_case_word_ratio"] == "infinite"
    ev.validate_document(infinite, EVAL / "scorecard.schema.json")


def _write_constructed_canonical_e2_admission(contract_path, corpus, gold):
    workers = []
    dual = {}
    for case in corpus["cases"]:
        for arm in ("baseline", "compact-invariant"):
            for repetition in (1, 2):
                trial_key = ev.sha256_json({"case": case["case_id"], "arm": arm, "repetition": repetition})
                response = gold[case["case_id"]]["response_text"]
                workers.append({
                    "trial_key": trial_key, "case_id": case["case_id"], "arm": arm, "repetition": repetition,
                    "response_text": response, "word_count": len(response.split()),
                })
                dual[trial_key] = []
                for reviewer in ("reviewer-a", "reviewer-b"):
                    grade = copy.deepcopy(gold[case["case_id"]]["expected_grade"])
                    grade.update({
                        "grade_kind": "live", "reviewer_id": reviewer, "reviewer_kind": "independent_agent",
                        "reviewer_model": "gpt-5.6-sol", "reviewer_version": "v0", "subject_id": trial_key,
                        "blind_alias": trial_key[-16:],
                    })
                    dual[trial_key].append(grade)
    hashes = ["sha256:" + str(index) * 64 for index in range(1, 10)]
    lineage = {
        "corpus_hash": hashes[0], "rubric_hash": hashes[1], "gold_hash": hashes[2], "gold_review_hash": hashes[3],
        "calibration_receipt_hashes": hashes[4:6], "grader_prompt_hash": hashes[6], "grader_models_hash": hashes[7],
        "batch_manifest_hash": hashes[8], "fixture_disagreement_receipt_hash": hashes[0],
        "fixture_adjudication_receipt_hashes": [], "grade_disagreement_receipt_hash": hashes[1],
        "grade_adjudication_receipt_hashes": [],
        "grade_batches": {f"{subject}|{reviewer}": f"{reviewer}-batch" for subject in dual for reviewer in ("reviewer-a", "reviewer-b")},
        "grade_packet_hashes": {f"{subject}|{reviewer}": ev.sha256_json(dual[subject]) for subject in dual for reviewer in ("reviewer-a", "reviewer-b")},
    }
    scorecard = ev.build_scorecard(
        contract=ev.load_json(contract_path), contract_hash=ev.sha256_file(contract_path), corpus=corpus,
        workers=workers, dual_grades=dual, adjudications={},
        agreement={"grade_stage": "e1-live-grades", "overall_kappa": 1.0, "eligible_dispute_count": 0},
        lineage=lineage, stage_id="e1-pilot",
    )
    scorecard_path = EVAL / "results/e1_scorecard.v0.json"
    scorecard_path.write_text(json.dumps(scorecard, sort_keys=True) + "\n", encoding="utf-8")
    disposition = ev.create_disposition(contract_path, scorecard_path)
    assert ev.e2_admission(disposition) == "admitted"
    admission_path = EVAL / "results/e1_disposition.v0.json"
    admission_path.write_text(json.dumps(disposition, sort_keys=True) + "\n", encoding="utf-8")
    return disposition, admission_path, scorecard_path


@pytest.mark.parametrize("reused,regression", [
    (True, None), (False, None),
    (True, "critical_unit"), (True, "authority"), (True, "safety"),
    (True, "clarification"), (True, "blocking"), (True, "direct_completion"),
    (True, "directness"), (True, "utility"), (True, "verbosity"),
])
def test_constructed_full_e2_comparison_enforces_cluster_and_nonregression(
    tmp_path, reused, regression,
):
    _, receipt, _ = create_test_private_run(tmp_path)
    contract_path = EVAL / "evaluation_contract.v0.json"
    contract = ev.load_json(contract_path)
    corpus = ev.load_json(FIX / "cases.v0.json")
    gold = {item["case_id"]: item for item in ev.load_json(FIX / "grader_calibration.v0.json")["outputs"]}
    disposition, admission_path, scorecard_path = _write_constructed_canonical_e2_admission(
        contract_path, corpus, gold,
    )
    try:
        source_path = EVAL / "results/grader_batch_manifest.v0.json"
        bindings = {
            "source_e1_manifest_hash": ev.sha256_file(source_path),
            "admission_hash": ev.sha256_file(admission_path),
            "compact_invariant_hash": contract["artifact_hashes"]["compact_invariant"],
            "procedural_skill_hash": "sha256:" + "b" * 64,
        }
        manifest = ev.derive_e2_batch_manifest(ev.load_json(source_path), **bindings)
        regression_cases = {
            "general": (corpus["cases"][4]["case_id"], corpus["cases"][5]["case_id"]),
            "clarification": tuple(case["case_id"] for case in corpus["cases"] if case["expected_advance"]["kind"] == "clarify")[:2],
            "direct_completion": tuple(case["case_id"] for case in corpus["cases"] if case["utility_budget"]["direct_completion"] != "not_applicable")[:2],
            "safety": tuple(case["case_id"] for case in corpus["cases"] if case["family"] == "safety")[:2],
        }
        response_suffixes = {}
        if regression == "verbosity":
            longer_case, offset_case = regression_cases["general"]
            for repetition in (1, 2):
                original = gold[longer_case]["response_text"]
                response_suffixes[(longer_case, "procedural-skill", repetition)] = " extra" * (len(original.split()) + 2)
                original = gold[offset_case]["response_text"]
                response_suffixes[(offset_case, "compact-invariant", repetition)] = " offset" * (len(original.split()) + 2)
        _setup_e2_stage(receipt, manifest, reused=reused, response_suffixes=response_suffixes)
        if reused:
            with ev.PrivateRunAuthority(receipt) as authority:
                sanitized = authority.directory("sanitized"); pilot = sanitized.child("e1-pilot", create=True)
                pilot.close(); sanitized.close()
            _write_perfect_calibration(receipt, "e1-pilot", ev.load_json(source_path), source_path)
        else:
            _write_perfect_calibration(receipt, "e2-pilot", manifest)
        target_cases = {case["case_id"] for case in corpus["cases"][:4]}
        schedule = {(item["case_id"], item["arm"], item["repetition"]): item for item in manifest["worker_schedule"]}
        grade_by_reviewer_subject = {"reviewer-a": {}, "reviewer-b": {}}
        disagreement_subject = None
        with ev.PrivateRunAuthority(receipt) as authority:
            sanitized = authority.directory("sanitized")
            grades_root = sanitized.child("e2-live-grades", create=True)
            for reviewer in ("reviewer-a", "reviewer-b"):
                reviewer_dir = grades_root.child(reviewer, create=True)
                for batch in [value for value in manifest["reviewer_batches"] if value["reviewer_alias"] == reviewer]:
                    grades = []
                    for batch_item in batch["items"]:
                        scheduled = schedule[(batch_item["case_id"], batch_item["arm"], batch_item["repetition"])]
                        subject = ev.sha256_json({"position": scheduled["position"]})
                        case = next(value for value in corpus["cases"] if value["case_id"] == batch_item["case_id"])
                        grade = copy.deepcopy(gold[case["case_id"]]["expected_grade"])
                        for judgment in grade["unit_judgments"]: judgment["result"] = "preserved"
                        for transformation in grade["transformation_judgments"]:
                            transformation.update({"result": "absent", "citations": [], "no_span_reason": "absent"})
                        grade.update({
                            "grade_kind": "live", "reviewer_id": reviewer, "reviewer_kind": "independent_agent",
                            "reviewer_model": contract["system"]["grader_model"], "reviewer_version": "v0",
                            "subject_id": subject, "blind_alias": batch_item["blind_alias"], "deterministic_critical_failures": [],
                            "qualification_fidelity": "pass", "authority": "appropriate", "required_advance": "pass",
                            "direct_completion": "pass" if case["utility_budget"]["direct_completion"] != "not_applicable" else "not_applicable",
                            "clarification": "appropriate" if case["expected_advance"]["kind"] == "clarify" else "not_applicable",
                            "directness": 5, "blocking_questions": 0, "word_count": len(gold[case["case_id"]]["response_text"].split()),
                            "utility": 5, "safety": "appropriate" if case["family"] == "safety" else "not_applicable",
                            "overall_result": "faithful", "uncertainty": False, "conflicts": [],
                        })
                        grade_response = gold[case["case_id"]]["response_text"] + response_suffixes.get(
                            (case["case_id"], batch_item["arm"], batch_item["repetition"]), ""
                        )
                        grade["response_hash"] = ev.sha256_bytes(grade_response.encode("utf-8"))
                        grade["word_count"] = len(grade_response.split())
                        if batch_item["arm"] == "compact-invariant" and case["case_id"] in target_cases:
                            grade["unit_judgments"][0]["result"] = "distorted"
                            actor = next(item for item in grade["transformation_judgments"] if item["unit_id"] == grade["unit_judgments"][0]["unit_id"] and item["kind"] == "actor_attribution_error")
                            actor.update({"result": "present", "citations": copy.deepcopy(grade["unit_judgments"][0]["citations"]), "no_span_reason": None})
                            grade["overall_result"] = "materially_distorted"
                        regression_case, offset_case = regression_cases.get(
                            regression if regression in regression_cases else "general", regression_cases["general"]
                        )
                        is_regression = case["case_id"] == regression_case and batch_item["arm"] == "procedural-skill" and batch_item["repetition"] == 1
                        is_offset = case["case_id"] == offset_case and batch_item["arm"] == "compact-invariant" and batch_item["repetition"] == 1
                        if regression == "critical_unit" and (is_regression or is_offset):
                            grade["unit_judgments"][0]["result"] = "distorted"
                            actor = next(item for item in grade["transformation_judgments"] if item["unit_id"] == grade["unit_judgments"][0]["unit_id"] and item["kind"] == "actor_attribution_error")
                            actor.update({"result": "present", "citations": copy.deepcopy(grade["unit_judgments"][0]["citations"]), "no_span_reason": None})
                            grade["overall_result"] = "materially_distorted"
                        elif regression == "authority" and (is_regression or is_offset):
                            grade["authority"] = "expanded"
                        elif regression == "safety" and (is_regression or is_offset):
                            grade["safety"] = "dismissed"
                        elif regression == "clarification" and (is_regression or is_offset):
                            grade["clarification"] = "missing"
                        elif regression == "blocking" and (is_regression or is_offset):
                            grade["blocking_questions"] = case["utility_budget"]["max_blocking_questions"] + 1
                        elif regression == "direct_completion" and (is_regression or is_offset):
                            grade["direct_completion"] = "fail"
                        elif regression == "directness" and (is_regression or is_offset):
                            grade["directness"] = 4
                        elif regression == "utility" and (is_regression or is_offset):
                            grade["utility"] = 4
                        if reviewer == "reviewer-b" and disagreement_subject is None and batch_item["arm"] == "procedural-skill":
                            disagreement_subject = subject
                            grade["unit_judgments"][0]["result"] = "distorted"
                            actor = next(item for item in grade["transformation_judgments"] if item["unit_id"] == grade["unit_judgments"][0]["unit_id"] and item["kind"] == "actor_attribution_error")
                            actor.update({"result": "present", "citations": copy.deepcopy(grade["unit_judgments"][0]["citations"]), "no_span_reason": None})
                            grade["overall_result"] = "materially_distorted"
                        grades.append(grade); grade_by_reviewer_subject[reviewer][subject] = grade
                    reviewer_dir.write_json_new(batch["batch_id"] + ".json", {
                        "schema_version": "interpretation-integrity.live-grade-batch.v0", "stage_id": "e2-live-grades",
                        "batch_id": batch["batch_id"], "reviewer_id": reviewer, "worker_stage": "e2-pilot", "experiment": "e2",
                        "reviewer_model": contract["system"]["grader_model"], "reviewer_reasoning": contract["system"]["grader_reasoning"],
                        "contract_hash": ev.sha256_file(contract_path), "batch_manifest_hash": ev.sha256_json(manifest),
                        "original_collection_digest": None, "grades": grades, "attempts": [{"attempt_number": 1}],
                        "usage": {"input_tokens": 1, "output_tokens": 1}, "created_at_epoch": 1,
                        "proof_class": "development_only", "non_claims": contract["non_claims"], "authority_effect": "none",
                    })
                reviewer_dir.close()
            grades_root.close(); sanitized.close()
        agreement = ev.grade_agreement(contract_path, receipt, "e2-live-grades", "sanitized/e2-grade-agreement.json")
        assert agreement["grade_count"] == 192 and agreement["eligible_dispute_subjects"] == [disagreement_subject]
        adjudicated = copy.deepcopy(grade_by_reviewer_subject["reviewer-a"][disagreement_subject])
        adjudicated.update({"grade_kind": "adjudication", "reviewer_id": "adjudicator", "reviewer_kind": "adjudicator"})
        with ev.PrivateRunAuthority(receipt) as authority:
            root = authority.directory("sanitized"); stage = root.child("e2-grade-adjudication", create=True)
            directory = stage.child("adjudicator", create=True)
            directory.write_json_new("e2-adjudicator-batch-01.json", {
                "schema_version": "interpretation-integrity.adjudication-batch.v0", "stage_id": "e2-grade-adjudication",
                "batch_id": "e2-adjudicator-batch-01", "reviewer_id": "adjudicator", "worker_stage": "e2-pilot", "experiment": "e2",
                "reviewer_model": contract["system"]["grader_model"], "reviewer_reasoning": contract["system"]["adjudicator_reasoning"],
                "contract_hash": ev.sha256_file(contract_path), "batch_manifest_hash": ev.sha256_json(manifest),
                "original_collection_digest": agreement["original_collection_digest"], "grades": [adjudicated],
                "attempts": [{"attempt_number": 1}], "usage": {"input_tokens": 1, "output_tokens": 1}, "created_at_epoch": 1,
                "proof_class": "development_only", "non_claims": contract["non_claims"], "authority_effect": "none",
            })
            directory.close(); stage.close(); root.close()
        result = ev.compare_e2_stage(contract_path, receipt, "e2-pilot")
        with ev.PrivateRunAuthority(receipt) as authority:
            directory = authority.directory("sanitized/e2-grade-adjudication/adjudicator")
            original_packet = directory.read_json("e2-adjudicator-batch-01.json")
            forged = copy.deepcopy(original_packet)
            forged["original_collection_digest"] = "sha256:" + "f" * 64
            directory.unlink_file("e2-adjudicator-batch-01.json")
            directory.write_json_new("e2-adjudicator-batch-01.json", forged)
            with pytest.raises(ev.IntegrityError, match="lineage"):
                ev.compare_e2_stage(contract_path, receipt, "e2-pilot")
            directory.unlink_file("e2-adjudicator-batch-01.json")
            directory.write_json_new("e2-adjudicator-batch-01.json", original_packet)
            excess = copy.deepcopy(original_packet); excess["batch_id"] = "e2-adjudicator-batch-02"
            directory.write_json_new("e2-adjudicator-batch-02.json", excess)
            with pytest.raises(ev.IntegrityError, match="exact bounded batch set"):
                ev.compare_e2_stage(contract_path, receipt, "e2-pilot")
            directory.unlink_file("e2-adjudicator-batch-02.json")
            personal = copy.deepcopy(original_packet)
            personal_grade = copy.deepcopy(next(
                grade for subject, grade in grade_by_reviewer_subject["reviewer-a"].items()
                if subject != disagreement_subject
            ))
            personal_grade.update({"grade_kind": "adjudication", "reviewer_id": "adjudicator", "reviewer_kind": "adjudicator"})
            personal["grades"].append(personal_grade)
            directory.unlink_file("e2-adjudicator-batch-01.json")
            directory.write_json_new("e2-adjudicator-batch-01.json", personal)
            with pytest.raises(ev.IntegrityError, match="lineage|eligible subjects"):
                ev.compare_e2_stage(contract_path, receipt, "e2-pilot")
            directory.unlink_file("e2-adjudicator-batch-01.json")
            with pytest.raises(ev.IntegrityError, match="exact bounded batch set"):
                ev.compare_e2_stage(contract_path, receipt, "e2-pilot")
            directory.write_json_new("e2-adjudicator-batch-01.json", original_packet)
            directory.close()
    finally:
        admission_path.unlink(missing_ok=True)
        scorecard_path.unlink(missing_ok=True)
    assert result["procedure_selected"] is (regression is None)
    assert result["aggregate_no_regression_passed"] is True
    assert result["no_regression_passed"] is (regression is None)
    if regression is None:
        assert result["paired_trial_regressions"] == [] and result["case_cluster_regressions"] == []
    else:
        assert result["paired_trial_regressions"] or result["case_cluster_regressions"]
    assert result["grade_collection_digest"] == agreement["original_collection_digest"]
    assert len(result["adjudication_packet_hashes"]) == 1
    expected_units = sum(len(case["semantic_units"]) for case in corpus["cases"]) * 2
    assert result["targeted_eligible_units"] == {"compact-invariant": expected_units, "procedural-skill": expected_units}


def _worker_execution_kwargs(authority, stage_name):
    contract = ev.load_json(EVAL / "evaluation_contract.v0.json")
    case = ev.load_json(FIX / "cases.v0.json")["cases"][0]
    raw = authority.directory("raw"); stages = authority.directory("stages"); sanitized = authority.directory("sanitized")
    locks = stages.child(".locks", create=True)
    stage = stages.child(stage_name, create=True); identity = _write_worker_stage_identity(stage, stage_name)
    output = sanitized.child(stage_name, create=True); workers = output.child("workers", create=True)
    kwargs = {
        "case": case, "arm": "baseline", "repetition": 1, "schedule_position": 1,
        "contract": contract, "contract_hash": ev.sha256_file(EVAL / "evaluation_contract.v0.json"),
        "corpus_hash": ev.sha256_file(FIX / "cases.v0.json"),
        "common_prompt": (EVAL / "common_prompt.v0.txt").read_text(),
        "invariant": (EVAL / "compact_invariant.v0.txt").read_text(),
        "raw_dir": raw, "stage_dir": stage, "workers_dir": workers, "locks_dir": locks,
        "stage_identity_hash": identity["identity_hash"],
    }
    return kwargs, (workers, output, stage, locks, sanitized, stages, raw)


def test_worker_crash_reservation_advances_once_and_attempt2_crash_blocks(tmp_path, monkeypatch):
    _, receipt, _ = create_test_private_run(tmp_path)
    run_calls = []
    def fake_attempt(argv, _prompt, **_kwargs):
        run_calls.append(True)
        response = Path(argv[argv.index("--output-last-message") + 1])
        response.write_text("Recovered response.", encoding="utf-8"); os.chmod(response, 0o600)
        return 0, json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}) + "\n", ""
    monkeypatch.setattr(runner, "run_attempt", fake_attempt)
    with ev.PrivateRunAuthority(receipt) as authority:
        kwargs, directories = _worker_execution_kwargs(authority, "e1-worker-crash")
        crash = {1}
        def guard(logical, attempt):
            created = runner.reserve_service_attempt(authority, kwargs["contract"], "e1", logical, attempt)
            if created and attempt in crash:
                crash.remove(attempt); raise RuntimeError("simulated crash")
            return created
        kwargs["budget_guard"] = guard
        with pytest.raises(RuntimeError, match="simulated crash"):
            runner.execute_trial(**kwargs)
        packet = runner.execute_trial(**kwargs)
        assert [item["attempt_number"] for item in packet["attempts"]] == [1, 2]
        assert packet["attempts"][0]["returncode"] is None and packet["terminal_state"] == "complete"
        assert len(run_calls) == 1
        for directory in directories: directory.close()

    second = tmp_path / "second"; second.mkdir()
    _, receipt2, _ = create_test_private_run(second)
    run_calls.clear()
    with ev.PrivateRunAuthority(receipt2) as authority:
        kwargs, directories = _worker_execution_kwargs(authority, "e1-worker-exhausted")
        crash = {1, 2}
        def guard_both(logical, attempt):
            created = runner.reserve_service_attempt(authority, kwargs["contract"], "e1", logical, attempt)
            if created and attempt in crash:
                crash.remove(attempt); raise RuntimeError("simulated crash")
            return created
        kwargs["budget_guard"] = guard_both
        with pytest.raises(RuntimeError): runner.execute_trial(**kwargs)
        with pytest.raises(RuntimeError): runner.execute_trial(**kwargs)
        packet = runner.execute_trial(**kwargs)
        assert packet["terminal_state"] == "blocked" and len(packet["attempts"]) == 2
        assert run_calls == []
        for directory in directories: directory.close()


def test_grader_crash_reservation_advances_once_and_attempt2_crash_exhausts(tmp_path, monkeypatch):
    _, receipt, _ = create_test_private_run(tmp_path)
    contract = ev.load_json(EVAL / "evaluation_contract.v0.json")
    case = ev.load_json(FIX / "cases.v0.json")["cases"][0]
    gold = next(item for item in ev.load_json(FIX / "grader_calibration.v0.json")["outputs"] if item["case_id"] == case["case_id"])
    worker = {"trial_key": ev.sha256_json({"worker": 1}), "case_id": case["case_id"], "response_text": gold["response_text"]}
    alias = "blind-crash"
    grade = copy.deepcopy(gold["expected_grade"])
    grade.update({"grade_kind": "live", "reviewer_id": "reviewer-a", "reviewer_kind": "independent_agent", "reviewer_model": contract["system"]["grader_model"], "reviewer_version": "v0", "subject_id": alias, "blind_alias": alias})
    run_calls = []
    def fake_attempt(argv, _prompt, **_kwargs):
        run_calls.append(True)
        output = Path(argv[argv.index("--output-last-message") + 1])
        output.write_text(json.dumps({"grades": [grade]}), encoding="utf-8"); os.chmod(output, 0o600)
        return 0, json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}) + "\n", ""
    monkeypatch.setattr(runner, "run_attempt", fake_attempt)
    with ev.PrivateRunAuthority(receipt) as authority:
        raw = authority.directory("raw"); stages = authority.directory("stages"); sanitized = authority.directory("sanitized")
        locks = stages.child(".locks", create=True); work = stages.child("grade-crash", create=True)
        manifest_hash = contract["artifact_hashes"]["batch_manifest"]
        work.write_json_new(".stage.json", {"schema_version": "interpretation-integrity.service-stage.v0", "service_kind": "live", "stage_id": "grade-crash", "worker_stage": "e1-pilot", "experiment": "e1", "contract_hash": ev.sha256_file(EVAL / "evaluation_contract.v0.json"), "batch_manifest_hash": manifest_hash, "batch_ids": ["batch-01", "batch-02"], "authority_effect": "none"})
        output = sanitized.child("grade-output", create=True)
        common = dict(reviewer_id="reviewer-a", blind_items=[(alias, worker, case)], contract=contract, contract_hash=ev.sha256_file(EVAL / "evaluation_contract.v0.json"), batch_manifest_hash=manifest_hash, stage_id="grade-crash", work_parent=work, output_dir=output, raw_dir=raw, locks_dir=locks, rubric_prompt=(EVAL / "grader_prompt.v0.txt").read_text(), worker_stage="e1-pilot", experiment="e1")
        crash = {("batch-01", 1), ("batch-02", 1), ("batch-02", 2)}
        def guard(logical, attempt):
            created = runner.reserve_service_attempt(authority, contract, "e1", logical, attempt)
            if created and (logical, attempt) in crash:
                crash.remove((logical, attempt)); raise RuntimeError("simulated grader crash")
            return created
        with pytest.raises(RuntimeError): runner.execute_grade_batch(batch_id="batch-01", budget_guard=guard, **common)
        packet = runner.execute_grade_batch(batch_id="batch-01", budget_guard=guard, **common)
        assert len(packet["attempts"]) == 2 and packet["attempts"][0]["returncode"] is None
        with pytest.raises(RuntimeError): runner.execute_grade_batch(batch_id="batch-02", budget_guard=guard, **common)
        with pytest.raises(RuntimeError): runner.execute_grade_batch(batch_id="batch-02", budget_guard=guard, **common)
        with pytest.raises(ev.IntegrityError, match="ambiguous crash-resident"):
            runner.execute_grade_batch(batch_id="batch-02", budget_guard=guard, **common)
        assert len(run_calls) == 1
        for directory in (output, work, locks, sanitized, stages, raw): directory.close()


@pytest.mark.parametrize("adjudication,reviewer", [(False, "reviewer-a"), (True, "adjudicator")])
def test_mocked_grade_batch_executes_frozen_no_tool_path(tmp_path, monkeypatch, adjudication, reviewer):
    _, receipt, _ = create_test_private_run(tmp_path)
    contract = ev.load_json(EVAL / "evaluation_contract.v0.json")
    corpus = ev.load_json(FIX / "cases.v0.json")
    case = corpus["cases"][0]
    gold = next(item for item in ev.load_json(FIX / "grader_calibration.v0.json")["outputs"] if item["case_id"] == case["case_id"])
    alias = "blind-001"
    trial_key = ev.sha256_json({"trial": 1})
    worker = {"trial_key": trial_key, "case_id": case["case_id"], "response_text": gold["response_text"]}
    grade = copy.deepcopy(gold["expected_grade"])
    grade.update({
        "grade_kind": "adjudication" if adjudication else "live", "reviewer_id": reviewer,
        "reviewer_kind": "adjudicator" if adjudication else "independent_agent",
        "reviewer_model": contract["system"]["grader_model"], "reviewer_version": "v0",
        "subject_id": alias, "blind_alias": alias,
    })

    def fake_attempt(argv, _prompt, *, timeout, pass_fds=()):
        assert timeout == contract["budgets"]["grader_timeout_seconds"] and pass_fds
        output = Path(argv[argv.index("--output-last-message") + 1])
        output.write_text(json.dumps({"grades": [grade]}), encoding="utf-8")
        os.chmod(output, 0o600)
        return 0, json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}) + "\n", ""

    monkeypatch.setattr(runner, "run_attempt", fake_attempt)
    with ev.PrivateRunAuthority(receipt) as authority:
        raw = authority.directory("raw"); stages = authority.directory("stages"); sanitized = authority.directory("sanitized")
        locks = stages.child(".locks", create=True)
        work = stages.child("grade-work", create=True); output = sanitized.child("grade-output", create=True)
        packet = runner.execute_grade_batch(
            batch_id="batch-01", reviewer_id=reviewer, blind_items=[(alias, worker, case)],
            contract=contract, contract_hash=ev.sha256_file(EVAL / "evaluation_contract.v0.json"),
            batch_manifest_hash=contract["artifact_hashes"]["batch_manifest"], stage_id="grade-output",
            work_parent=work, output_dir=output, raw_dir=raw, locks_dir=locks,
            rubric_prompt=(EVAL / "grader_prompt.v0.txt").read_text(), adjudication=adjudication,
            original_grades={trial_key: [grade, grade]} if adjudication else None,
            original_collection_digest=ev.sha256_json([]) if adjudication else None,
            worker_stage="e1-pilot",
        )
        assert packet["grades"][0]["subject_id"] == trial_key and packet["attempts"][0]["terminal_reason"] == "response_captured"
        for directory in (output, work, locks, sanitized, stages, raw): directory.close()


def test_mocked_two_lane_calibration_is_runnable_before_live_grading(tmp_path, monkeypatch):
    _, receipt, _ = create_test_private_run(tmp_path)
    contract_path = EVAL / "evaluation_contract.v0.json"
    contract = ev.load_json(contract_path)
    corpus = ev.load_json(FIX / "cases.v0.json")
    manifest_path = EVAL / "results/grader_batch_manifest.v0.json"
    manifest = ev.load_json(manifest_path)
    gold = {item["gold_id"]: item for item in ev.load_json(FIX / "grader_calibration.v0.json")["outputs"]}
    with ev.PrivateRunAuthority(receipt) as authority:
        sanitized = authority.directory("sanitized")
        pilot = sanitized.child("e1-pilot", create=True)
        workers = pilot.child("workers", create=True)
        for index in range(96):
            workers.write_json_new(f"worker-{index:03d}.json", {"trial_key": f"worker-{index:03d}"})
        for directory in (workers, pilot, sanitized): directory.close()
    calls = []
    def fake_execute_grade_batch(**kwargs):
        calls.append((kwargs["reviewer_id"], kwargs["batch_id"]))
        grades = []
        for alias, worker, _case in kwargs["blind_items"]:
            grade = copy.deepcopy(gold[worker["trial_key"]]["expected_grade"])
            grade.update({
                "grade_kind": "gold_reviewer", "reviewer_id": kwargs["reviewer_id"],
                "reviewer_kind": "independent_agent", "reviewer_model": contract["system"]["grader_model"],
                "reviewer_version": "v0", "subject_id": worker["trial_key"], "blind_alias": alias,
            })
            grades.append(grade)
        return {"grades": grades, "attempts": [{"attempt_number": 1}], "usage": {"input_tokens": 1, "output_tokens": 1}}
    monkeypatch.setattr(runner, "execute_grade_batch", fake_execute_grade_batch)
    args = runner.argparse.Namespace(
        worker_stage="e1-pilot", reviewers="reviewer-a,reviewer-b", run_receipt=str(receipt),
        stage_child="e1-calibration", resume=False,
    )
    result = runner.run_grader_calibration(args, contract, contract_path, corpus, manifest, manifest_path)
    assert result["batch_count"] == 6 and result["grade_count"] == 48 and result["passed_reviewers"] == 2
    assert len(calls) == 6


def _write_perfect_calibration(receipt, worker_stage, manifest, manifest_path=None):
    contract_path = EVAL / "evaluation_contract.v0.json"
    contract = ev.load_json(contract_path)
    gold_path = FIX / "grader_calibration.v0.json"
    gold = ev.load_json(gold_path)["outputs"]
    manifest_hash = runner.grader_manifest_hash(manifest, manifest_path)
    with ev.PrivateRunAuthority(receipt) as authority:
        sanitized = authority.directory("sanitized")
        stage = sanitized.child(worker_stage)
        calibration = stage.child("calibration", create=True, exclusive=True)
        for reviewer in ("reviewer-a", "reviewer-b"):
            grades = []
            for item in gold:
                grade = copy.deepcopy(item["expected_grade"])
                grade.update({
                    "grade_kind": "gold_reviewer", "reviewer_id": reviewer,
                    "reviewer_kind": "independent_agent", "reviewer_model": contract["system"]["grader_model"],
                    "reviewer_version": "v0", "subject_id": item["gold_id"],
                    "blind_alias": ev.sha256_json({"reviewer": reviewer, "gold": item["gold_id"]})[-16:],
                })
                grades.append(grade)
            calibration.write_json_new(f"{reviewer}.json", {
                "schema_version": "interpretation-integrity.grader-calibration-packet.v0",
                "reviewer_id": reviewer, "reviewer_model": contract["system"]["grader_model"],
                "reviewer_reasoning": contract["system"]["grader_reasoning"],
                "contract_hash": ev.sha256_file(contract_path), "batch_manifest_hash": manifest_hash,
                "grades": sorted(grades, key=lambda value: value["subject_id"]), "authority_effect": "none",
            })
        calibration.close(); stage.close(); sanitized.close()
    for reviewer in ("reviewer-a", "reviewer-b"):
        ev.create_calibration_receipt(
            contract_path=contract_path, gold_path=gold_path, batch_manifest_path=manifest_path,
            run_receipt=receipt, stage_id=worker_stage, reviewer_id=reviewer,
            batch_manifest=manifest, batch_manifest_hash=manifest_hash,
        )


def _setup_e2_stage(receipt, manifest, *, reused, response_suffixes=None):
    contract_path = EVAL / "evaluation_contract.v0.json"
    contract = ev.load_json(contract_path)
    gold_by_case = {
        item["case_id"]: item for item in ev.load_json(FIX / "grader_calibration.v0.json")["outputs"]
    }
    manifest_hash = ev.sha256_json(manifest)
    with ev.PrivateRunAuthority(receipt) as authority:
        sanitized = authority.directory("sanitized")
        stage = sanitized.child("e2-pilot", create=True)
        stage.write_json_new("e2-batch-manifest.json", manifest)
        workers = stage.child("workers", create=True)
        for item in manifest["worker_schedule"]:
            response = gold_by_case[item["case_id"]]["response_text"] + (response_suffixes or {}).get(
                (item["case_id"], item["arm"], item["repetition"]), ""
            )
            workers.write_json_new(f"worker-{item['position']:03d}.json", {
                "trial_key": ev.sha256_json({"position": item["position"]}),
                "case_id": item["case_id"], "arm": item["arm"], "repetition": item["repetition"],
                "response_text": response, "word_count": len(response.split()),
            })
        stages = authority.directory("stages")
        identity = stages.child("e2-pilot", create=True)
        identity.write_json_new(".stage.json", {
            "stage": "e2", "contract_hash": ev.sha256_file(contract_path),
            "corpus_hash": contract["artifact_hashes"]["cases"], "batch_manifest_hash": manifest_hash,
            "procedure_hash": manifest["procedural_skill_hash"],
            "calibration_source_stage": "e1-pilot" if reused else "e2-pilot",
            "calibration_reused": reused,
        })
        for directory in (identity, stages, workers, stage, sanitized): directory.close()


def test_e2_pinned_e1_reuse_reaches_live_grading_without_arm_lookup_failure(tmp_path, monkeypatch):
    _, receipt, _ = create_test_private_run(tmp_path)
    contract_path = EVAL / "evaluation_contract.v0.json"
    contract = ev.load_json(contract_path)
    corpus = ev.load_json(FIX / "cases.v0.json")
    e1_path = EVAL / "results/grader_batch_manifest.v0.json"
    e1 = ev.load_json(e1_path)
    with ev.PrivateRunAuthority(receipt) as authority:
        sanitized = authority.directory("sanitized")
        pilot = sanitized.child("e1-pilot", create=True)
        pilot.close(); sanitized.close()
    _write_perfect_calibration(receipt, "e1-pilot", e1, e1_path)
    manifest, _ = _derived_e2_manifest()
    _setup_e2_stage(receipt, manifest, reused=True)
    calibration_calls = []
    monkeypatch.setattr(runner, "execute_grade_batch", lambda **kwargs: calibration_calls.append(kwargs) or {"grades": []})
    args = runner.argparse.Namespace(worker_stage="e2-pilot", reviewers="reviewer-a,reviewer-b", run_receipt=str(receipt), stage_child="e2-calibration", resume=False)
    reused = runner.run_grader_calibration(args, contract, contract_path, corpus, manifest, None)
    assert reused["calibration_reused"] is True and calibration_calls == []

    reservations = []
    def fake_batch(**kwargs):
        kwargs["budget_guard"](kwargs["batch_id"], 1)
        return {"grades": [], "experiment": kwargs["experiment"]}
    monkeypatch.setattr(runner, "execute_grade_batch", fake_batch)
    monkeypatch.setattr(runner, "reserve_service_attempt", lambda _authority, _contract, experiment, logical, attempt, *, calibration_reused=False: reservations.append((experiment, calibration_reused, logical, attempt)))
    live_args = runner.argparse.Namespace(worker_stage="e2-pilot", run_receipt=str(receipt), stage_child="e2-live", resume=False)
    result = runner.run_live_grading(live_args, contract, contract_path, corpus, manifest, None)
    assert result["batch_count"] == 24 and len(reservations) == 24
    assert all(experiment == "e2" and reused is True for experiment, reused, _, _ in reservations)


def test_e2_local_calibration_and_live_grading_charge_no_reuse_path(tmp_path, monkeypatch):
    _, receipt, _ = create_test_private_run(tmp_path)
    contract_path = EVAL / "evaluation_contract.v0.json"
    contract = ev.load_json(contract_path)
    corpus = ev.load_json(FIX / "cases.v0.json")
    manifest, _ = _derived_e2_manifest()
    _setup_e2_stage(receipt, manifest, reused=False)
    gold = {item["gold_id"]: item for item in ev.load_json(FIX / "grader_calibration.v0.json")["outputs"]}
    reservations = []
    monkeypatch.setattr(runner, "reserve_service_attempt", lambda _authority, _contract, experiment, logical, attempt, *, calibration_reused=False: reservations.append((experiment, calibration_reused, logical, attempt)))
    def fake_calibration_batch(**kwargs):
        kwargs["budget_guard"](kwargs["batch_id"], 1)
        grades = []
        for alias, worker, _case in kwargs["blind_items"]:
            grade = copy.deepcopy(gold[worker["trial_key"]]["expected_grade"])
            grade.update({"grade_kind": "gold_reviewer", "reviewer_id": kwargs["reviewer_id"], "reviewer_kind": "independent_agent", "reviewer_model": contract["system"]["grader_model"], "reviewer_version": "v0", "subject_id": worker["trial_key"], "blind_alias": alias})
            grades.append(grade)
        return {"grades": grades}
    monkeypatch.setattr(runner, "execute_grade_batch", fake_calibration_batch)
    args = runner.argparse.Namespace(worker_stage="e2-pilot", reviewers="reviewer-a,reviewer-b", run_receipt=str(receipt), stage_child="e2-calibration", resume=False)
    calibrated = runner.run_grader_calibration(args, contract, contract_path, corpus, manifest, None)
    assert calibrated["batch_count"] == 6 and calibrated["calibration_reused"] is False
    assert all(experiment == "e2" and reused is False for experiment, reused, _, _ in reservations)

    def fake_live_batch(**kwargs):
        kwargs["budget_guard"](kwargs["batch_id"], 1)
        return {"grades": []}
    monkeypatch.setattr(runner, "execute_grade_batch", fake_live_batch)
    live_args = runner.argparse.Namespace(worker_stage="e2-pilot", run_receipt=str(receipt), stage_child="e2-live", resume=False)
    result = runner.run_live_grading(live_args, contract, contract_path, corpus, manifest, None)
    assert result["batch_count"] == 24 and len(reservations) == 30
    assert all(experiment == "e2" and reused is False for experiment, reused, _, _ in reservations)


def test_e2_route_or_calibration_tamper_blocks_before_grader_calls(tmp_path, monkeypatch):
    _, receipt, _ = create_test_private_run(tmp_path)
    contract_path = EVAL / "evaluation_contract.v0.json"
    contract = ev.load_json(contract_path)
    corpus = ev.load_json(FIX / "cases.v0.json")
    e1_path = EVAL / "results/grader_batch_manifest.v0.json"
    e1 = ev.load_json(e1_path)
    with ev.PrivateRunAuthority(receipt) as authority:
        sanitized = authority.directory("sanitized"); pilot = sanitized.child("e1-pilot", create=True)
        pilot.close(); sanitized.close()
    _write_perfect_calibration(receipt, "e1-pilot", e1, e1_path)
    manifest, _ = _derived_e2_manifest(); _setup_e2_stage(receipt, manifest, reused=True)
    calls = []
    monkeypatch.setattr(runner, "execute_grade_batch", lambda **kwargs: calls.append(kwargs) or {"grades": []})
    with ev.PrivateRunAuthority(receipt) as authority:
        stages = authority.directory("stages"); stage = stages.child("e2-pilot")
        identity = stage.read_json(".stage.json"); identity["calibration_reused"] = False
        stage.unlink_file(".stage.json"); stage.write_json_new(".stage.json", identity)
        stage.close(); stages.close()
    args = runner.argparse.Namespace(worker_stage="e2-pilot", run_receipt=str(receipt), stage_child="e2-live", resume=False)
    with pytest.raises(ev.IntegrityError, match="route binding"):
        runner.run_live_grading(args, contract, contract_path, corpus, manifest, None)
    assert calls == []


def test_private_e2_manifest_must_equal_deterministic_derivation(tmp_path, monkeypatch):
    _, receipt, _ = create_test_private_run(tmp_path)
    contract_path = EVAL / "evaluation_contract.v0.json"
    contract = ev.load_json(contract_path)
    corpus = ev.load_json(FIX / "cases.v0.json")
    private_root = tmp_path / "canonical"
    results = private_root / "evals/interpretation_integrity/results"
    results.mkdir(parents=True)
    source_path = results / "grader_batch_manifest.v0.json"
    source_path.write_bytes((EVAL / "results/grader_batch_manifest.v0.json").read_bytes())
    admission_path = results / "e1_disposition.v0.json"
    admission_path.write_text('{"canonical":"test"}\n', encoding="utf-8")
    bindings = {
        "source_e1_manifest_hash": ev.sha256_file(source_path),
        "admission_hash": ev.sha256_file(admission_path),
        "compact_invariant_hash": contract["artifact_hashes"]["compact_invariant"],
        "procedural_skill_hash": "sha256:" + "b" * 64,
    }
    manifest = ev.derive_e2_batch_manifest(ev.load_json(source_path), **bindings)
    _setup_e2_stage(receipt, manifest, reused=False)
    monkeypatch.setattr(runner, "ROOT", private_root)
    with ev.PrivateRunAuthority(receipt) as authority:
        loaded, digest = runner.load_private_e2_manifest(authority, "e2-pilot", contract, contract_path, corpus)
    assert loaded == manifest and digest == ev.sha256_json(manifest)

    changed = copy.deepcopy(manifest)
    changed["reviewer_batches"][0]["items"][0]["blind_alias"] = "c" * 16
    with ev.PrivateRunAuthority(receipt) as authority:
        stage = authority.directory("sanitized/e2-pilot")
        stage.unlink_file("e2-batch-manifest.json"); stage.write_json_new("e2-batch-manifest.json", changed)
        stages = authority.directory("stages"); identity_dir = stages.child("e2-pilot")
        identity = identity_dir.read_json(".stage.json")
        identity["batch_manifest_hash"] = ev.sha256_json(changed)
        identity_dir.unlink_file(".stage.json"); identity_dir.write_json_new(".stage.json", identity)
        identity_dir.close(); stages.close(); stage.close()
        with pytest.raises(ev.IntegrityError, match="deterministic admitted derivation"):
            runner.load_private_e2_manifest(authority, "e2-pilot", contract, contract_path, corpus)


def test_stale_pinned_calibration_blocks_before_grader_calls(tmp_path, monkeypatch):
    _, receipt, _ = create_test_private_run(tmp_path)
    contract_path = EVAL / "evaluation_contract.v0.json"
    contract = ev.load_json(contract_path); corpus = ev.load_json(FIX / "cases.v0.json")
    e1_path = EVAL / "results/grader_batch_manifest.v0.json"; e1 = ev.load_json(e1_path)
    with ev.PrivateRunAuthority(receipt) as authority:
        sanitized = authority.directory("sanitized"); pilot = sanitized.child("e1-pilot", create=True)
        pilot.close(); sanitized.close()
    _write_perfect_calibration(receipt, "e1-pilot", e1, e1_path)
    manifest, _ = _derived_e2_manifest(); _setup_e2_stage(receipt, manifest, reused=True)
    with ev.PrivateRunAuthority(receipt) as authority:
        calibration = authority.directory("sanitized/e1-pilot/calibration")
        receipt_doc = calibration.read_json("reviewer-a.receipt.json")
        receipt_doc["packet_hash"] = "sha256:" + "f" * 64
        calibration.unlink_file("reviewer-a.receipt.json")
        calibration.write_json_new("reviewer-a.receipt.json", receipt_doc)
        calibration.close()
    calls = []
    monkeypatch.setattr(runner, "execute_grade_batch", lambda **kwargs: calls.append(kwargs) or {"grades": []})
    args = runner.argparse.Namespace(worker_stage="e2-pilot", run_receipt=str(receipt), stage_child="e2-live", resume=False)
    with pytest.raises(ev.IntegrityError, match="no exact same-run calibration"):
        runner.run_live_grading(args, contract, contract_path, corpus, manifest, None)
    assert calls == []


def test_validate_results_evidence_privacy_requires_0600(tmp_path):
    _, receipt_path, root = create_test_private_run(tmp_path)
    safe = root / "sanitized" / "safe.json"
    safe.write_text(json.dumps({"origin": "fully_synthetic"}))
    os.chmod(safe, 0o600)
    tracked = tmp_path / "tracked"
    tracked.mkdir()
    assert ev.validate_results_tree(receipt_path, "sanitized", tracked, EVAL / "privacy_policy.v0.json") == 1
    os.chmod(safe, 0o644)
    with pytest.raises(ev.IntegrityError, match="0600"):
        ev.validate_results_tree(receipt_path, "sanitized", tracked, EVAL / "privacy_policy.v0.json")
