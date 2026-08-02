#!/usr/bin/env python3
"""Bounded, receipt-rooted runner for interpretation-integrity trials.

Service execution is explicit: importing this module or constructing packets has
no external effect.  Every invocation uses a fresh receipt-derived directory and
persists raw provider output only below the ignored private run root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import interpretation_integrity_eval as integrity


ROOT = Path(__file__).resolve().parents[1]


def serialized_conversation(case: Mapping[str, Any]) -> str:
    visible = {
        "case_id": case["case_id"],
        "conversation": [
            {"actor": turn["actor"], "role": turn["role"], "text": turn["text"]}
            for turn in case["conversation"]
        ],
        "target_turn_id": case["target_turn_id"],
    }
    return json.dumps(visible, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_prompt(case: Mapping[str, Any], arm: str, common_prompt: str, invariant: str, procedure: str = "") -> str:
    if arm not in {"baseline", "compact-invariant", "procedural-skill"}:
        raise integrity.IntegrityError(f"unsupported worker arm: {arm}")
    intervention = "" if arm == "baseline" else (procedure if arm == "procedural-skill" else invariant).rstrip("\n") + "\n\n"
    return common_prompt.rstrip("\n") + "\n\n" + intervention + serialized_conversation(case) + "\n"


def common_envelope(prompt: str, invariant: str) -> str:
    marker = invariant.rstrip("\n") + "\n\n"
    return prompt.replace(marker, "", 1)


def assert_single_variable_pair(baseline: str, variant: str, invariant: str) -> None:
    marker = invariant.rstrip("\n") + "\n\n"
    if marker not in variant or marker in baseline or common_envelope(variant, invariant) != baseline:
        raise integrity.IntegrityError("paired prompts differ by more than the compact invariant")


def build_worker_argv(*, trial_dir: Path, response_file: Path, model: str = "gpt-5.6-terra") -> list[str]:
    return [
        "codex", "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules",
        "--strict-config", "--skip-git-repo-check", "--sandbox", "read-only",
        "-c", 'approval_policy="never"',
        "-c", 'shell_environment_policy.inherit="none"',
        "-c", 'model_reasoning_effort="medium"',
        "--model", model, "--cd", str(trial_dir), "--output-last-message", str(response_file), "-",
    ]


def validate_worker_argv(argv: Sequence[str], trial_dir: Path, response_file: Path) -> None:
    if list(argv) != build_worker_argv(trial_dir=trial_dir, response_file=response_file):
        raise integrity.IntegrityError("worker argv drifted from frozen service matrix")


def walk_trace(value: Any, location: str = "$"):
    yield location, value
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from walk_trace(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_trace(child, f"{location}[{index}]")


def classify_trace(lines: Sequence[Mapping[str, Any]]) -> list[str]:
    allowed_events = {"thread.started", "turn.started", "turn.completed", "item.started", "item.updated", "item.completed"}
    allowed_items = {"agent_message", "reasoning", "todo_list"}
    tool_kinds = {
        "tool_call", "function_call", "dynamic_tool", "dynamic_tool_call", "command_execution",
        "mcp", "mcp_call", "mcp_tool", "mcp_tool_call", "web_search", "web_search_call",
    }
    file_kinds = {
        "file_change", "file_read", "file_write", "path_access", "filesystem_access",
        "read_file", "write_file", "apply_patch",
    }
    violations: list[str] = []
    for item in lines:
        event_type = item.get("type")
        if not isinstance(event_type, str) or event_type not in allowed_events | {"error"}:
            violations.append("malformed_trace")
        nested_item = item.get("item")
        if event_type and event_type.startswith("item."):
            if not isinstance(nested_item, Mapping) or nested_item.get("type") not in allowed_items | tool_kinds | file_kinds | {"approval_request"}:
                violations.append("malformed_trace")
        for location, value in walk_trace(item):
            if not isinstance(value, Mapping):
                continue
            kind = str(value.get("type", "")).lower().replace("-", "_")
            name = str(value.get("name", "")).lower().replace("-", "_")
            event = str(value.get("event", "")).lower().replace("-", "_")
            vocabulary = {kind, name, event}
            if any(candidate in tool_kinds or any(token in candidate for token in tool_kinds) for candidate in vocabulary):
                violations.append("tool_call")
            if any("approval" in candidate for candidate in vocabulary) or "approval_id" in value:
                violations.append("approval_request")
            if any(candidate in file_kinds or any(token in candidate for token in file_kinds) for candidate in vocabulary):
                violations.append("undeclared_file_access")
            if kind == "error" and value.get("error_kind") not in {"provider_timeout", "provider_transport"}:
                violations.append("provider_error")
    return sorted(set(violations))


def trace_usage(lines: Sequence[Mapping[str, Any]]) -> Mapping[str, int]:
    totals = {"input_tokens": 0, "output_tokens": 0}
    for item in lines:
        for _, value in walk_trace(item):
            if not isinstance(value, Mapping):
                continue
            for key in totals:
                amount = value.get(key)
                if isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0:
                    totals[key] = max(totals[key], amount)
    return totals


def instruction_inventory(lines: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Extract only content-free loaded instruction/skill identities from a trace."""
    identities: set[str] = set()
    watched = {"instruction_files", "instructions", "loaded_instructions", "skills", "loaded_skills", "skill_paths"}
    for item in lines:
        for location, value in walk_trace(item):
            if not isinstance(value, Mapping):
                continue
            for key, child in value.items():
                if key.lower() not in watched:
                    continue
                if isinstance(child, str):
                    identities.add(f"{key}:{child}")
                elif isinstance(child, list) and all(isinstance(entry, str) for entry in child):
                    identities.update(f"{key}:{entry}" for entry in child)
                else:
                    raise integrity.IntegrityError(f"malformed instruction inventory at {location}.{key}")
    ordered = sorted(identities)
    return {"count": len(ordered), "digest": integrity.sha256_json(ordered)}


def parse_jsonl(data: str) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for index, line in enumerate(data.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(
                line,
                object_pairs_hook=integrity._reject_duplicate_keys,
                parse_constant=integrity._reject_json_constant,
            )
        except (json.JSONDecodeError, integrity.IntegrityError) as exc:
            raise integrity.IntegrityError(f"malformed worker trace line {index}") from exc
        if not isinstance(item, dict):
            raise integrity.IntegrityError(f"worker trace line {index} is not an object")
        records.append(item)
    if not records:
        raise integrity.IntegrityError("empty worker trace")
    return records


def validate_and_select_schedule(
    manifest: Mapping[str, Any],
    corpus: Mapping[str, Any],
    *,
    max_cases: int,
    repetitions: int,
    arms: Sequence[str],
) -> list[Mapping[str, Any]]:
    integrity.validate_batch_manifest(manifest, corpus)
    corpus_order = [case["case_id"] for case in corpus["cases"]]
    selected_cases = set(corpus_order[:max_cases])
    selected = [
        item for item in manifest["worker_schedule"]
        if item["case_id"] in selected_cases and item["repetition"] <= repetitions and item["arm"] in arms
    ]
    selected.sort(key=lambda item: item["position"])
    expected = {
        (case_id, arm, repetition)
        for case_id in selected_cases
        for arm in arms
        for repetition in range(1, repetitions + 1)
    }
    actual = {(item["case_id"], item["arm"], item["repetition"]) for item in selected}
    if len(selected) != len(expected) or actual != expected:
        raise integrity.IntegrityError("selected execution does not match the frozen worker schedule")
    by_pair: dict[tuple[str, int], list[str]] = {}
    for item in selected:
        by_pair.setdefault((item["case_id"], item["repetition"]), []).append(item["arm"])
    if any(sorted(order) != sorted(arms) for order in by_pair.values()):
        raise integrity.IntegrityError("frozen schedule does not contain one of each arm per pair")
    return selected


def validate_and_select_e2_schedule(
    manifest: Mapping[str, Any],
    corpus: Mapping[str, Any],
    *,
    source_e1_manifest_hash: str,
    admission_hash: str,
    compact_invariant_hash: str,
    procedural_skill_hash: str,
    max_cases: int,
    repetitions: int,
) -> list[Mapping[str, Any]]:
    """Validate a derived E2 manifest and select its frozen worker schedule."""
    integrity.validate_e2_batch_manifest(
        manifest, corpus,
        source_e1_manifest_hash=source_e1_manifest_hash,
        admission_hash=admission_hash,
        compact_invariant_hash=compact_invariant_hash,
        procedural_skill_hash=procedural_skill_hash,
    )
    reverse = {"compact-invariant": "baseline", "procedural-skill": "compact-invariant"}
    e1_projection = {
        **manifest,
        "schema_version": "interpretation-integrity.grader-batches.v0",
        "worker_schedule": [{**item, "arm": reverse[item["arm"]]} for item in manifest["worker_schedule"]],
        "reviewer_batches": [
            {**batch, "items": [{**item, "arm": reverse[item["arm"]]} for item in batch["items"]]}
            for batch in manifest["reviewer_batches"]
        ],
    }
    selected = validate_and_select_schedule(
        e1_projection, corpus, max_cases=max_cases, repetitions=repetitions,
        arms=["baseline", "compact-invariant"],
    )
    forward = {"baseline": "compact-invariant", "compact-invariant": "procedural-skill"}
    return [{**item, "arm": forward[item["arm"]]} for item in selected]


def persist_e2_batch_manifest(
    sanitized_stage: integrity.HeldPrivateDirectory,
    manifest: Mapping[str, Any],
    *,
    resume: bool,
) -> None:
    """Persist once before E2 output, or verify the exact immutable resume binding."""
    name = "e2-batch-manifest.json"
    if resume:
        if sanitized_stage.read_json(name) != manifest:
            raise integrity.IntegrityError("resume E2 manifest binding mismatch")
        return
    sanitized_stage.write_json_new(name, manifest)


def grader_manifest_hash(manifest: Mapping[str, Any], manifest_path: Path | None) -> str:
    if manifest.get("schema_version") == "interpretation-integrity.grader-batches.e2.v0":
        return integrity.sha256_json(manifest)
    if manifest_path is None:
        raise integrity.IntegrityError("tracked E1 grader manifest path is required")
    return integrity.sha256_file(manifest_path)


def load_private_e2_manifest(
    authority: integrity.PrivateRunAuthority, worker_stage: str,
    contract: Mapping[str, Any], contract_path: Path, corpus: Mapping[str, Any],
) -> tuple[Mapping[str, Any], str]:
    if not worker_stage.startswith("e2"):
        raise integrity.IntegrityError("private E2 manifest requires an E2 worker stage")
    stage = authority.directory(f"sanitized/{worker_stage}")
    try:
        manifest = stage.read_json("e2-batch-manifest.json")
    finally:
        stage.close()
    stages = authority.directory("stages")
    try:
        identity_dir = stages.child(worker_stage)
        try:
            identity = identity_dir.read_json(".stage.json")
        finally:
            identity_dir.close()
    finally:
        stages.close()
    canonical_admission = ROOT / "evals/interpretation_integrity/results/e1_disposition.v0.json"
    source_manifest_path = ROOT / "evals/interpretation_integrity/results/grader_batch_manifest.v0.json"
    expected = {
        "source_e1_manifest_hash": contract["artifact_hashes"]["batch_manifest"],
        "admission_hash": integrity.sha256_file(canonical_admission),
        "compact_invariant_hash": contract["artifact_hashes"]["compact_invariant"],
        "procedural_skill_hash": identity.get("procedure_hash"),
    }
    integrity.validate_e2_batch_manifest(manifest, corpus, **expected)
    if integrity.sha256_file(source_manifest_path) != contract["artifact_hashes"]["batch_manifest"]:
        raise integrity.IntegrityError("frozen E1 manifest lineage is stale")
    derived = integrity.derive_e2_batch_manifest(
        integrity.load_json(source_manifest_path), **expected,
    )
    if manifest != derived:
        raise integrity.IntegrityError("private E2 manifest is not the deterministic admitted derivation")
    digest = integrity.sha256_json(manifest)
    expected_identity = {
        "stage": "e2", "contract_hash": integrity.sha256_file(contract_path),
        "corpus_hash": contract["artifact_hashes"]["cases"], "batch_manifest_hash": digest,
        "procedure_hash": manifest["procedural_skill_hash"],
    }
    if any(identity.get(key) != value for key, value in expected_identity.items()):
        raise integrity.IntegrityError("private E2 manifest does not bind the worker stage identity")
    return manifest, digest


def read_e2_calibration_route(
    authority: integrity.PrivateRunAuthority, worker_stage: str,
) -> Mapping[str, Any]:
    stages = authority.directory("stages")
    try:
        stage = stages.child(worker_stage)
        try:
            identity = stage.read_json(".stage.json")
        finally:
            stage.close()
    finally:
        stages.close()
    source = identity.get("calibration_source_stage")
    reused = identity.get("calibration_reused")
    if source not in {"e1-pilot", worker_stage} or reused is not (source == "e1-pilot"):
        raise integrity.IntegrityError("E2 calibration route binding is missing or invalid")
    return {"source_stage": source, "reused": reused}


def resolve_e2_calibration_route(
    authority: integrity.PrivateRunAuthority, contract: Mapping[str, Any], contract_path: Path,
) -> Mapping[str, Any]:
    """Pin E1 reuse when exact; absent E1 evidence selects E2-local, stale evidence blocks."""
    try:
        directory = authority.directory("sanitized/e1-pilot/calibration")
    except integrity.IntegrityError:
        return {"source_stage": None, "reused": False}
    directory.close()
    try:
        evidence = integrity.validate_calibration_evidence(
            authority, contract, contract_path, worker_stage="e2-route-resolution",
            batch_manifest_hash="sha256:" + "0" * 64, expected_source_stage="e1-pilot",
        )
    except integrity.IntegrityError as exc:
        raise integrity.IntegrityError("present E1 calibration is stale; E2 route cannot be selected") from exc
    return {"source_stage": evidence["source_stage"], "reused": True}


def deterministic_word_count(text: str) -> int:
    return len(re.findall(r"\S+", text, flags=re.UNICODE))


def validate_pair_start_skew(packets: Sequence[Mapping[str, Any]], *, max_seconds: int = 900) -> None:
    paired: dict[tuple[str, int], list[int]] = {}
    for packet in packets:
        paired.setdefault((packet["case_id"], packet["repetition"]), []).append(packet["started_at_epoch_ms"])
    for key, starts in paired.items():
        if len(starts) != 2 or max(starts) - min(starts) > max_seconds * 1000:
            raise integrity.IntegrityError(f"pair start skew exceeded for {key[0]} repetition {key[1]}")


def validate_budget_snapshot(
    snapshot: Mapping[str, Any], budgets: Mapping[str, Any], *, stage: str,
    calibration_reused: bool = False,
) -> None:
    if stage.startswith("e1"):
        logical_cap = budgets["e1_logical_invocations"]
        attempt_cap = budgets["e1_max_service_attempts"]
    elif stage.startswith("e2"):
        suffix = "with_reuse" if calibration_reused else "no_reuse"
        logical_cap = budgets[f"e2_logical_invocations_{suffix}"]
        attempt_cap = budgets[f"e2_max_service_attempts_{suffix}"]
    else:
        logical_cap = budgets["e3_logical_invocations"]
        attempt_cap = budgets["e3_max_service_attempts"]
    limits = {
        "logical_invocations": logical_cap,
        "service_attempts": attempt_cap,
        "input_tokens": budgets["input_tokens"],
        "output_tokens": budgets["output_tokens"],
        "wall_seconds": budgets["wall_seconds"],
        "max_concurrent_attempts": budgets["max_concurrent_attempts"],
    }
    for key, maximum in limits.items():
        value = snapshot.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 or value > maximum:
            raise integrity.IntegrityError(f"budget exhausted or invalid: {key}")


def run_attempt(argv: Sequence[str], prompt: str, *, timeout: int, pass_fds: Sequence[int] = ()) -> tuple[int, str, str]:
    environment = {"PATH": os.environ.get("PATH", "")}
    try:
        result = subprocess.run(
            list(argv), input=prompt, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, env=environment, check=False, pass_fds=tuple(pass_fds), umask=0o077,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        return 124, stdout, "provider_timeout"
    return result.returncode, result.stdout, result.stderr


def open_recoverable_work(
    parent: integrity.HeldPrivateDirectory, name: str, identity: Mapping[str, Any], *, output_name: str,
) -> tuple[integrity.HeldPrivateDirectory, bool]:
    """Open exact crash-resident work or create a descriptor-bound identity once."""
    if name in parent.names():
        work = parent.child(name)
        try:
            if work.read_json(".work.json") != identity:
                raise integrity.IntegrityError("crash-resident work identity mismatch")
            if any(entry not in {".work.json", output_name} for entry in work.names()):
                raise integrity.IntegrityError("crash-resident work contains an unexpected entry")
        except Exception:
            work.close()
            raise
        return work, True
    work = parent.child(name, create=True, exclusive=True)
    work.write_json_new(".work.json", identity)
    return work, False


def ambiguous_consumed_worker_attempt(trial_key: str, attempt_number: int, reason: str) -> Mapping[str, Any]:
    return {
        "attempt_number": attempt_number,
        "attempt_key": integrity.stable_attempt_key(trial_key, attempt_number, reason),
        "reason": reason, "returncode": None, "violation_codes": [],
        "terminal_reason": "provider_transport", "usage": {"input_tokens": 0, "output_tokens": 0},
        "instruction_inventory": {"count": 0, "digest": integrity.sha256_json([])},
    }


def execute_trial(
    *,
    case: Mapping[str, Any],
    arm: str,
    repetition: int,
    schedule_position: int,
    contract: Mapping[str, Any],
    contract_hash: str,
    corpus_hash: str,
    common_prompt: str,
    invariant: str,
    raw_dir: integrity.HeldPrivateDirectory,
    stage_dir: integrity.HeldPrivateDirectory,
    workers_dir: integrity.HeldPrivateDirectory,
    locks_dir: integrity.HeldPrivateDirectory,
    stage_identity_hash: str,
    procedure_text: str = "",
    budget_guard: Callable[[str, int], None] | None = None,
) -> Mapping[str, Any]:
    arm_contract = next((item for item in contract["arms"] if item["arm_id"] == arm), None)
    if arm == "procedural-skill" and procedure_text:
        arm_contract = {"arm_id": arm, "version": "e2-procedure-v0", "intervention_hash": integrity.sha256_bytes(procedure_text.encode("utf-8"))}
    if arm_contract is None:
        raise integrity.IntegrityError("arm is not frozen in the evaluation contract")
    trial_key = integrity.stable_trial_key(
        contract_hash,
        case["case_id"],
        arm,
        arm_contract["version"] + (":" + arm_contract["intervention_hash"] if arm == "procedural-skill" else ""),
        repetition,
        str(case.get("case_version", "v0")),
    )
    trial_name = "trial-" + trial_key.removeprefix("sha256:")[:24]
    packet_name = f"{trial_name}.json"
    with integrity.trial_lock_at(locks_dir, f"{trial_name}.lock"):
        if packet_name in stage_dir.names():
            packet = stage_dir.read_json(packet_name)
            integrity.validate_run_state(packet)
            integrity.validate_document(packet, ROOT / "evals/interpretation_integrity/run_state.schema.json")
            expected_identity = {
                "trial_key": trial_key,
                "case_id": case["case_id"],
                "arm": arm,
                "repetition": repetition,
                "schedule_position": schedule_position,
                "contract_hash": contract_hash,
                "corpus_hash": corpus_hash,
                "stage_identity_hash": stage_identity_hash,
            }
            if any(packet.get(key) != value for key, value in expected_identity.items()):
                raise integrity.IntegrityError("terminal packet identity drift on resume")
            return packet
        configuration_hash = integrity.sha256_json(build_worker_argv(
            trial_dir=Path("{trial-dir}"), response_file=Path("{trial-dir}/response.txt"),
            model=contract["system"]["worker_model"],
        ))
        prompt = build_prompt(case, arm, common_prompt, invariant, procedure_text)
        work_identity = {
            "schema_version": "interpretation-integrity.worker-work.v0", "work_kind": "worker",
            "trial_name": trial_name, "logical_key": trial_key, "stage_identity_hash": stage_identity_hash,
            "contract_hash": contract_hash, "corpus_hash": corpus_hash, "case_id": case["case_id"],
            "arm": arm, "repetition": repetition, "schedule_position": schedule_position,
            "configuration_hash": configuration_hash,
            "prompt_hash": integrity.sha256_bytes(prompt.encode("utf-8")), "attempt_ceiling": 2,
            "authority_effect": "none",
        }
        trial_dir, _resuming_work = open_recoverable_work(
            stage_dir, trial_name, work_identity, output_name="response.txt",
        )
        service_root = Path(f"/proc/self/fd/{trial_dir.fd}")
        response_file = service_root / "response.txt"
        argv = build_worker_argv(
            trial_dir=service_root, response_file=response_file, model=contract["system"]["worker_model"],
        )
        attempts: list[dict[str, Any]] = []
        terminal_state = "failed"
        terminal_reason = "provider_failure"
        started = time.monotonic()
        started_epoch_ms = int(time.time() * 1000)
        final_response = ""
        final_inventory = {"count": 0, "digest": integrity.sha256_json([])}
        total_usage = {"input_tokens": 0, "output_tokens": 0}
        for attempt_number in (1, 2):
            reason = "initial" if attempt_number == 1 else terminal_reason
            reservation_created = True if budget_guard is None else budget_guard(trial_key, attempt_number) is not False
            if not reservation_created:
                attempts.append(ambiguous_consumed_worker_attempt(trial_key, attempt_number, reason))
                terminal_reason = "provider_transport"
                if attempt_number == 2:
                    terminal_state = "blocked"
                continue
            trace_name = f"{trial_name}.attempt-{attempt_number}.jsonl"
            if "response.txt" in trial_dir.names():
                trial_dir.unlink_file("response.txt")
            returncode, stdout, stderr = run_attempt(
                argv, prompt, timeout=contract["budgets"]["worker_timeout_seconds"], pass_fds=[trial_dir.fd],
            )
            raw_dir.write_bytes_new(trace_name, stdout.encode("utf-8", "strict"))
            try:
                records = parse_jsonl(stdout)
                violations = classify_trace(records)
                usage = trace_usage(records)
                inventory = instruction_inventory(records)
            except integrity.IntegrityError:
                records, violations = [], ["malformed_trace"]
                usage = {"input_tokens": 0, "output_tokens": 0}
                inventory = {"count": 0, "digest": integrity.sha256_json([])}
            for key in total_usage:
                total_usage[key] += usage[key]
            attempt = {
                "attempt_number": attempt_number,
                "attempt_key": integrity.stable_attempt_key(trial_key, attempt_number, reason),
                "reason": reason,
                "returncode": returncode,
                "violation_codes": violations,
                "terminal_reason": "response_captured" if returncode == 0 and not violations else (
                    "provider_timeout" if returncode == 124 else "provider_transport"
                ),
                "usage": usage,
                "instruction_inventory": inventory,
            }
            attempts.append(attempt)
            if violations:
                terminal_state, terminal_reason = "invalid", violations[0]
                break
            if returncode == 0 and "response.txt" in trial_dir.names():
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open("response.txt", flags, dir_fd=trial_dir.fd)
                try:
                    response_item = os.fstat(descriptor)
                    if not stat.S_ISREG(response_item.st_mode) or response_item.st_uid != os.getuid():
                        raise integrity.IntegrityError("worker response is not an owned regular file")
                    os.fchmod(descriptor, 0o600)
                    response = integrity.read_descriptor_bytes(descriptor).decode("utf-8", "strict")
                finally:
                    os.close(descriptor)
                integrity.require_nfc_text(response, "response_text")
                if deterministic_word_count(response) > contract["budgets"]["response_words"]:
                    terminal_state, terminal_reason = "invalid", "response_word_budget"
                    attempt["violation_codes"] = sorted(set(attempt["violation_codes"] + ["budget_exhaustion"]))
                    break
                final_response = response
                final_inventory = inventory
                terminal_state, terminal_reason = "complete", "response_captured"
                break
            retryable_trace = any(
                value.get("error_kind") in {"provider_timeout", "provider_transport"}
                for record in records for _, value in walk_trace(record) if isinstance(value, Mapping)
            )
            terminal_reason = "provider_timeout" if returncode == 124 else "provider_transport" if retryable_trace else "provider_failure"
            attempt["terminal_reason"] = terminal_reason
            if terminal_reason not in {"provider_timeout", "provider_transport"}:
                terminal_state = "failed"
                break
            if attempt_number == 2:
                terminal_state = "blocked"
        packet = {
            "schema_version": "interpretation-integrity.run-state.v0",
            "trial_key": trial_key,
            "case_id": case["case_id"],
            "arm": arm,
            "repetition": repetition,
            "schedule_position": schedule_position,
            "pair_key": integrity.sha256_json({"contract_hash": contract_hash, "case_id": case["case_id"], "repetition": repetition}),
            "contract_hash": contract_hash,
            "corpus_hash": corpus_hash,
            "common_prompt_hash": integrity.sha256_bytes(common_prompt.encode("utf-8")),
            "intervention_hash": arm_contract["intervention_hash"],
            "stage_identity_hash": stage_identity_hash,
            "worker_model": contract["system"]["worker_model"],
            "worker_reasoning": contract["system"]["worker_reasoning"],
            "configuration_hash": configuration_hash,
            "instruction_inventory": final_inventory,
            "started_at_epoch_ms": started_epoch_ms,
            "finished_at_epoch_ms": int(time.time() * 1000),
            "usage": total_usage,
            "attempts": attempts,
            "terminal_state": terminal_state,
            "terminal_reason": terminal_reason,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "opaque_artifact_id": hashlib.sha256((trial_key + ":artifacts").encode()).hexdigest()[:24],
            "excluded_inventory_before_digest": None,
            "excluded_inventory_after_digest": None,
            "proof_class": "development_only",
            "non_claims": contract["non_claims"],
            "authority_effect": "none",
        }
        integrity.validate_run_state(packet)
        integrity.validate_document(packet, ROOT / "evals/interpretation_integrity/run_state.schema.json")
        stage_dir.write_json_new(packet_name, packet)
        if terminal_state == "complete":
            worker = {
                "schema_version": "interpretation-integrity.worker-output.v0",
                "trial_key": trial_key,
                "case_id": case["case_id"],
                "arm": arm,
                "repetition": repetition,
                "schedule_position": schedule_position,
                "contract_hash": contract_hash,
                "corpus_hash": corpus_hash,
                "response_text": final_response,
                "word_count": deterministic_word_count(final_response),
                "instruction_inventory": final_inventory,
                "usage": total_usage,
                "proof_class": "development_only",
                "non_claims": contract["non_claims"],
                "authority_effect": "none",
            }
            integrity.validate_document(worker, ROOT / "evals/interpretation_integrity/worker_output.schema.json")
            workers_dir.write_json_new(f"{trial_name}.json", worker)
        trial_dir.close()
        return packet


def build_grader_argv(*, work_dir: Path, response_file: Path, model: str, reasoning: str) -> list[str]:
    return [
        "codex", "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules",
        "--strict-config", "--skip-git-repo-check", "--sandbox", "read-only",
        "-c", 'approval_policy="never"', "-c", 'shell_environment_policy.inherit="none"',
        "-c", f'model_reasoning_effort="{reasoning}"', "--model", model,
        "--cd", str(work_dir), "--output-last-message", str(response_file), "-",
    ]


def _grade_prompt(
    *, reviewer_id: str, batch_id: str, items: Sequence[tuple[str, Mapping[str, Any], Mapping[str, Any]]],
    rubric_prompt: str, adjudication: bool, original_grades: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    calibration: bool = False,
) -> str:
    visible = []
    for blind_alias, worker, case in items:
        entry = {
            "blind_alias": blind_alias,
            "case": {"conversation": case["conversation"], "target_turn_id": case["target_turn_id"], "semantic_units": case["semantic_units"]},
            "response_text": worker["response_text"],
        }
        if original_grades is not None:
            entry["original_judgments"] = [integrity.substantive_grade(value) for value in original_grades[worker["trial_key"]]]
        visible.append(entry)
    grade_kind = "adjudication" if adjudication else "gold_reviewer" if calibration else "live"
    instruction = (
        "Return one JSON object with exactly a grades array. Each grade must satisfy the frozen semantic-grade schema, "
        f"use reviewer_id {reviewer_id!r}, grade_kind {grade_kind!r}, and use each blind_alias as subject_id."
    )
    return rubric_prompt.rstrip("\n") + "\n\n" + instruction + "\n\n" + json.dumps(
        {"batch_id": batch_id, "items": visible}, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ) + "\n"


def execute_grade_batch(
    *, batch_id: str, reviewer_id: str, blind_items: Sequence[tuple[str, Mapping[str, Any], Mapping[str, Any]]],
    contract: Mapping[str, Any], contract_hash: str, batch_manifest_hash: str,
    stage_id: str, work_parent: integrity.HeldPrivateDirectory, output_dir: integrity.HeldPrivateDirectory,
    raw_dir: integrity.HeldPrivateDirectory, locks_dir: integrity.HeldPrivateDirectory,
    rubric_prompt: str, adjudication: bool = False,
    original_grades: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    original_collection_digest: str | None = None,
    worker_stage: str | None = None,
    calibration: bool = False,
    experiment: str | None = None,
    budget_guard: Callable[[str, int], None] | None = None,
) -> Mapping[str, Any]:
    output_name = batch_id + ".json"
    with integrity.trial_lock_at(locks_dir, batch_id + ".lock"):
        if output_name in output_dir.names():
            packet = output_dir.read_json(output_name)
            if packet.get("batch_id") != batch_id or packet.get("reviewer_id") != reviewer_id or packet.get("stage_id") != stage_id:
                raise integrity.IntegrityError("grade batch resume identity mismatch")
            return packet
        grade_kind = "adjudication" if adjudication else "gold_reviewer" if calibration else "live"
        subject_digest = integrity.sha256_json(sorted(
            {"blind_alias": alias, "trial_key": worker["trial_key"], "case_id": case["case_id"]}
            for alias, worker, case in blind_items
        ))
        work_identity = {
            "schema_version": "interpretation-integrity.grader-work.v0", "work_kind": "grader",
            "batch_id": batch_id, "stage_id": stage_id, "reviewer_id": reviewer_id,
            "grade_kind": grade_kind, "worker_stage": worker_stage, "experiment": experiment,
            "contract_hash": contract_hash, "batch_manifest_hash": batch_manifest_hash,
            "original_collection_digest": original_collection_digest, "subject_digest": subject_digest,
            "attempt_ceiling": 2, "authority_effect": "none",
        }
        work, _resuming_work = open_recoverable_work(
            work_parent, batch_id, work_identity, output_name="grades.json",
        )
        service_root = Path(f"/proc/self/fd/{work.fd}")
        response_path = service_root / "grades.json"
        reasoning = contract["system"]["adjudicator_reasoning" if adjudication else "grader_reasoning"]
        argv = build_grader_argv(
            work_dir=service_root, response_file=response_path,
            model=contract["system"]["grader_model"], reasoning=reasoning,
        )
        prompt = _grade_prompt(
            reviewer_id=reviewer_id, batch_id=batch_id, items=blind_items,
            rubric_prompt=rubric_prompt, adjudication=adjudication, original_grades=original_grades,
            calibration=calibration,
        )
        attempts: list[Mapping[str, Any]] = []
        grades: list[Mapping[str, Any]] | None = None
        total_usage = {"input_tokens": 0, "output_tokens": 0}
        for attempt_number in (1, 2):
            reason = "initial" if attempt_number == 1 else attempts[-1]["terminal_reason"]
            reservation_created = True if budget_guard is None else budget_guard(batch_id, attempt_number) is not False
            if not reservation_created:
                attempts.append({
                    "attempt_number": attempt_number, "reason": reason, "returncode": None,
                    "terminal_reason": "provider_transport", "violation_codes": [],
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                })
                if attempt_number == 2:
                    raise integrity.IntegrityError("grader batch exhausted after ambiguous crash-resident attempts")
                continue
            returncode, stdout, _stderr = run_attempt(
                argv, prompt, timeout=contract["budgets"]["grader_timeout_seconds"], pass_fds=[work.fd],
            )
            raw_dir.write_bytes_new(f"{stage_id}.{batch_id}.attempt-{attempt_number}.jsonl", stdout.encode("utf-8", "strict"))
            try:
                trace = parse_jsonl(stdout)
                violations = classify_trace(trace)
                usage = trace_usage(trace)
            except integrity.IntegrityError:
                trace, violations, usage = [], ["malformed_trace"], {"input_tokens": 0, "output_tokens": 0}
            for key in total_usage:
                total_usage[key] += usage[key]
            retry_reason = "provider_timeout" if returncode == 124 else "provider_transport"
            attempts.append({
                "attempt_number": attempt_number, "reason": reason, "returncode": returncode,
                "terminal_reason": "response_captured" if returncode == 0 and not violations else retry_reason,
                "violation_codes": violations, "usage": usage,
            })
            if violations:
                raise integrity.IntegrityError("grade trace crossed the frozen no-tool boundary")
            if returncode == 0 and "grades.json" in work.names():
                response = work.read_json("grades.json")
                if set(response) != {"grades"} or not isinstance(response["grades"], list):
                    raise integrity.IntegrityError("grader response envelope rejected")
                grades = response["grades"]
                break
            retryable = returncode == 124 or any(
                value.get("error_kind") in {"provider_timeout", "provider_transport"}
                for record in trace for _, value in walk_trace(record) if isinstance(value, Mapping)
            )
            if not retryable or attempt_number == 2:
                raise integrity.IntegrityError("grader batch exhausted its bounded retry policy")
        assert grades is not None
        expected = {alias: (worker, case) for alias, worker, case in blind_items}
        normalized: list[Mapping[str, Any]] = []
        if len(grades) != len(expected):
            raise integrity.IntegrityError("grader batch output count mismatch")
        for grade in grades:
            alias = grade.get("subject_id")
            if alias not in expected:
                raise integrity.IntegrityError("grader returned an unknown or duplicate blind alias")
            worker, case = expected.pop(alias)
            grade = {**grade, "subject_id": worker["trial_key"], "blind_alias": alias}
            integrity.validate_semantic_grade(grade, worker["response_text"], ROOT / "evals/interpretation_integrity/semantic_grade.schema.json")
            if grade["grade_kind"] != grade_kind or grade["reviewer_id"] != reviewer_id or grade["case_id"] != case["case_id"]:
                raise integrity.IntegrityError("grader semantic identity mismatch")
            normalized.append(grade)
        if expected:
            raise integrity.IntegrityError("grader omitted blind aliases")
        packet = {
            "schema_version": "interpretation-integrity.adjudication-batch.v0" if adjudication else "interpretation-integrity.calibration-batch.v0" if calibration else "interpretation-integrity.live-grade-batch.v0",
            "stage_id": stage_id, "batch_id": batch_id, "reviewer_id": reviewer_id,
            "worker_stage": worker_stage,
            "experiment": experiment,
            "reviewer_model": contract["system"]["grader_model"], "reviewer_reasoning": reasoning,
            "contract_hash": contract_hash, "batch_manifest_hash": batch_manifest_hash,
            "original_collection_digest": original_collection_digest,
            "grades": normalized, "attempts": attempts, "usage": total_usage,
            "created_at_epoch": int(time.time()), "proof_class": "development_only",
            "non_claims": contract["non_claims"], "authority_effect": "none",
        }
        output_dir.write_json_new(output_name, packet)
        work.close()
        return packet


def _json_packets(directory: integrity.HeldPrivateDirectory) -> list[Mapping[str, Any]]:
    packets = []
    for name in directory.names():
        if name.endswith(".json") and not name.startswith("."):
            packets.append(directory.read_json(name))
    return packets


TRIAL_NAME_RE = re.compile(r"^trial-[0-9a-f]{24}$")


def validate_stage_work_inventory(
    work: integrity.HeldPrivateDirectory, name: str, stage_identity: Mapping[str, Any], stage_name: str,
) -> None:
    identity = work.read_json(".work.json")
    kind = identity.get("work_kind")
    output_name = "response.txt" if kind == "worker" else "grades.json" if kind == "grader" else None
    if output_name is None or any(entry not in {".work.json", output_name} for entry in work.names()):
        raise integrity.IntegrityError("malformed stage work inventory")
    if kind == "worker":
        logical = identity.get("logical_key")
        if (
            identity.get("schema_version") != "interpretation-integrity.worker-work.v0"
            or name != identity.get("trial_name")
            or not isinstance(logical, str) or name != "trial-" + logical.removeprefix("sha256:")[:24]
            or identity.get("stage_identity_hash") != stage_identity.get("identity_hash")
            or identity.get("contract_hash") != stage_identity.get("contract_hash")
            or identity.get("corpus_hash") != stage_identity.get("corpus_hash")
            or identity.get("attempt_ceiling") != 2 or identity.get("authority_effect") != "none"
        ):
            raise integrity.IntegrityError("malformed worker work identity")
    elif (
        identity.get("schema_version") != "interpretation-integrity.grader-work.v0"
        or name != identity.get("batch_id") or stage_name != identity.get("stage_id")
        or name not in stage_identity.get("batch_ids", [])
        or identity.get("contract_hash") != stage_identity.get("contract_hash")
        or identity.get("batch_manifest_hash") != stage_identity.get("batch_manifest_hash")
        or identity.get("attempt_ceiling") != 2 or identity.get("authority_effect") != "none"
    ):
        raise integrity.IntegrityError("malformed grader work identity")


def cumulative_service_snapshot(
    authority: integrity.PrivateRunAuthority, experiment: str,
) -> Mapping[str, int]:
    if experiment not in {"e1", "e2"}:
        raise integrity.IntegrityError("unsupported cumulative budget experiment")
    packets: list[Mapping[str, Any]] = []
    reservations: list[Mapping[str, Any]] = []
    stages = authority.directory("stages")
    try:
        try:
            budget_root = stages.child(".budget")
        except integrity.IntegrityError:
            budget_root = None
        if budget_root is not None:
            try:
                try:
                    experiment_dir = budget_root.child(experiment)
                except integrity.IntegrityError:
                    experiment_dir = None
                if experiment_dir is not None:
                    try:
                        for name in experiment_dir.names():
                            if not name.endswith(".json"):
                                raise integrity.IntegrityError("malformed durable budget journal")
                            document = experiment_dir.read_json(name)
                            if not isinstance(document, Mapping):
                                raise integrity.IntegrityError("malformed durable budget reservation")
                            expected_name = integrity.sha256_json({
                                "logical_key": document.get("logical_key"),
                                "attempt": document.get("attempt_number"),
                            }).removeprefix("sha256:") + ".json"
                            if (
                                set(document) != {
                                    "schema_version", "experiment", "logical_key", "attempt_number",
                                    "reserved_at_epoch", "authority_effect",
                                }
                                or document.get("schema_version") != "interpretation-integrity.service-attempt-reservation.v0"
                                or document.get("experiment") != experiment
                                or not isinstance(document.get("logical_key"), str)
                                or not document.get("logical_key")
                                or document.get("attempt_number") not in {1, 2}
                                or not isinstance(document.get("reserved_at_epoch"), int)
                                or isinstance(document.get("reserved_at_epoch"), bool)
                                or not (0 < document.get("reserved_at_epoch") <= int(time.time()) + 1)
                                or document.get("authority_effect") != "none"
                                or name != expected_name
                            ):
                                raise integrity.IntegrityError("malformed durable budget reservation")
                            reservations.append(document)
                    finally:
                        experiment_dir.close()
            finally:
                budget_root.close()
        for stage_name in stages.names():
            if stage_name in {".budget", ".locks"}:
                continue
            if stage_name.startswith("."):
                raise integrity.IntegrityError("malformed hidden stage budget evidence")
            try:
                stage_dir = stages.child(stage_name)
            except integrity.IntegrityError as exc:
                raise integrity.IntegrityError("malformed stage budget evidence") from exc
            try:
                identity = stage_dir.read_json(".stage.json")
                if not isinstance(identity, Mapping):
                    raise integrity.IntegrityError("malformed stage identity")
                if identity.get("stage") in {"e1", "e2"}:
                    bound_stage = identity["stage"]
                    payload = {key: value for key, value in identity.items() if key not in {"identity_hash", "created_at_epoch"}}
                    if (
                        identity.get("stage_child") != stage_name
                        or identity.get("identity_hash") != integrity.sha256_json(payload)
                        or not isinstance(identity.get("created_at_epoch"), int)
                    ):
                        raise integrity.IntegrityError("malformed worker stage identity")
                    allowed_batches = None
                elif identity.get("schema_version") in {
                    "interpretation-integrity.grade-stage.v0", "interpretation-integrity.service-stage.v0",
                }:
                    bound_stage = identity.get("experiment")
                    allowed_batches = identity.get("batch_ids")
                    if (
                        bound_stage not in {"e1", "e2"} or identity.get("stage_id") != stage_name
                        or not isinstance(allowed_batches, list) or not allowed_batches
                        or len(allowed_batches) != len(set(allowed_batches))
                    ):
                        raise integrity.IntegrityError("malformed grader stage identity")
                else:
                    raise integrity.IntegrityError("malformed stage experiment binding")
                for name in stage_dir.names():
                    item = os.stat(name, dir_fd=stage_dir.fd, follow_symlinks=False)
                    if stat.S_ISLNK(item.st_mode) or not (stat.S_ISREG(item.st_mode) or stat.S_ISDIR(item.st_mode)):
                        raise integrity.IntegrityError("malformed stage budget evidence")
                    if stat.S_ISDIR(item.st_mode):
                        if (allowed_batches is None and not TRIAL_NAME_RE.fullmatch(name)) or (
                            allowed_batches is not None and name not in allowed_batches
                        ):
                            raise integrity.IntegrityError("unexpected stage work directory")
                        work = stage_dir.child(name)
                        try:
                            validate_stage_work_inventory(work, name, identity, stage_name)
                        finally:
                            work.close()
                    elif name != ".stage.json":
                        if allowed_batches is not None or not re.fullmatch(r"trial-[0-9a-f]{24}\.json", name):
                            raise integrity.IntegrityError("malformed stage budget evidence")
                        packet = stage_dir.read_json(name)
                        if name != "trial-" + str(packet.get("trial_key", "")).removeprefix("sha256:")[:24] + ".json":
                            raise integrity.IntegrityError("terminal trial filename identity mismatch")
                        if bound_stage == experiment:
                            packets.append(packet)
            except integrity.IntegrityError as exc:
                raise integrity.IntegrityError("malformed stage budget evidence") from exc
            finally:
                stage_dir.close()
    finally:
        stages.close()

    service_schemas = {
        "interpretation-integrity.live-grade-batch.v0",
        "interpretation-integrity.adjudication-batch.v0",
        "interpretation-integrity.calibration-batch.v0",
    }
    def collect(directory: integrity.HeldPrivateDirectory) -> None:
        for name in directory.names():
            item = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
            if stat.S_ISLNK(item.st_mode):
                raise integrity.IntegrityError("budget evidence tree contains a symlink")
            if stat.S_ISDIR(item.st_mode):
                child = directory.child(name)
                try:
                    collect(child)
                finally:
                    child.close()
            elif stat.S_ISREG(item.st_mode) and name.endswith(".json"):
                document = directory.read_json(name)
                if not isinstance(document, Mapping):
                    raise integrity.IntegrityError("malformed sanitized budget evidence")
                if document.get("schema_version") not in service_schemas:
                    continue
                bound_experiment = document.get("experiment")
                if bound_experiment is None:
                    bound_experiment = "e2" if str(document.get("worker_stage", "")).startswith("e2") else "e1"
                if bound_experiment == experiment:
                    packets.append(document)
            elif not stat.S_ISREG(item.st_mode):
                raise integrity.IntegrityError("budget evidence tree contains a special file")
    sanitized = authority.directory("sanitized")
    try:
        collect(sanitized)
    finally:
        sanitized.close()
    reservation_attempts: set[tuple[str, int]] = set()
    logical_keys: set[str] = set()
    earliest = []
    for document in reservations:
        attempt = (document["logical_key"], document["attempt_number"])
        if attempt in reservation_attempts:
            raise integrity.IntegrityError("duplicate durable budget reservation")
        reservation_attempts.add(attempt)
        logical_keys.add(document["logical_key"])
        earliest.append(document["reserved_at_epoch"])

    packet_attempts: set[tuple[str, int]] = set()
    packet_logical_keys: set[str] = set()
    input_tokens = output_tokens = 0
    current_epoch = int(time.time())
    for packet in packets:
        if not isinstance(packet, Mapping):
            raise integrity.IntegrityError("malformed completed budget packet")
        schema = packet.get("schema_version")
        logical_key = packet.get("trial_key") if schema == "interpretation-integrity.run-state.v0" else packet.get("batch_id")
        attempts = packet.get("attempts")
        usage = packet.get("usage")
        created = packet.get("started_at_epoch_ms") if schema == "interpretation-integrity.run-state.v0" else packet.get("created_at_epoch")
        if (
            schema not in service_schemas | {"interpretation-integrity.run-state.v0"}
            or not isinstance(logical_key, str) or not logical_key
            or logical_key in packet_logical_keys
            or not isinstance(attempts, list) or not 1 <= len(attempts) <= 2
            or not isinstance(usage, Mapping)
            or any(not isinstance(usage.get(key), int) or isinstance(usage.get(key), bool) or usage.get(key) < 0 for key in ("input_tokens", "output_tokens"))
            or not isinstance(created, int) or isinstance(created, bool) or created < 0
        ):
            raise integrity.IntegrityError("malformed completed budget packet")
        created_epoch = created // 1000 if schema == "interpretation-integrity.run-state.v0" else created
        if not (0 < created_epoch <= current_epoch + 1):
            raise integrity.IntegrityError("malformed completed budget packet timestamp")
        packet_logical_keys.add(logical_key)
        logical_keys.add(logical_key)
        earliest.append(created_epoch)
        input_tokens += usage["input_tokens"]
        output_tokens += usage["output_tokens"]
        for index, attempt in enumerate(attempts, 1):
            if not isinstance(attempt, Mapping) or attempt.get("attempt_number") != index:
                raise integrity.IntegrityError("malformed completed budget packet")
            packet_attempts.add((logical_key, index))
    return {
        "logical_invocations": len(logical_keys),
        "service_attempts": len(reservation_attempts | packet_attempts),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "wall_seconds": max(0, int(time.time()) - min(earliest)) if earliest else 0,
        "max_concurrent_attempts": 1,
    }


def reserve_service_attempt(
    authority: integrity.PrivateRunAuthority, contract: Mapping[str, Any], experiment: str,
    logical_key: str, attempt_number: int, *, calibration_reused: bool = False,
) -> bool:
    stages = authority.directory("stages")
    budget_root = stages.child(".budget", create=True)
    experiment_dir = budget_root.child(experiment, create=True)
    reservation_name = integrity.sha256_json({"logical_key": logical_key, "attempt": attempt_number}).removeprefix("sha256:") + ".json"
    try:
        with integrity.trial_lock_at(budget_root, f"{experiment}.lock"):
            snapshot = dict(cumulative_service_snapshot(authority, experiment))
            names = experiment_dir.names()
            if reservation_name in names:
                existing = experiment_dir.read_json(reservation_name)
                if (
                    existing.get("schema_version") != "interpretation-integrity.service-attempt-reservation.v0"
                    or existing.get("experiment") != experiment
                    or existing.get("logical_key") != logical_key
                    or existing.get("attempt_number") != attempt_number
                    or existing.get("authority_effect") != "none"
                ):
                    raise integrity.IntegrityError("existing service reservation identity mismatch")
                return False
            existing_logical = logical_key in {
                experiment_dir.read_json(name).get("logical_key") for name in names
            }
            snapshot["logical_invocations"] += int(not existing_logical)
            snapshot["service_attempts"] += 1
            validate_budget_snapshot(snapshot, contract["budgets"], stage=experiment, calibration_reused=calibration_reused)
            experiment_dir.write_json_new(reservation_name, {
                "schema_version": "interpretation-integrity.service-attempt-reservation.v0",
                "experiment": experiment, "logical_key": logical_key, "attempt_number": attempt_number,
                "reserved_at_epoch": int(time.time()), "authority_effect": "none",
            })
            return True
    finally:
        for directory in (experiment_dir, budget_root, stages):
            directory.close()


def _same_run_calibration_available(
    authority: integrity.PrivateRunAuthority, contract_path: Path,
) -> bool:
    try:
        contract = integrity.load_json(contract_path)
        evidence = integrity.validate_calibration_evidence(
            authority, contract, contract_path, worker_stage="e2-reuse-proof",
            batch_manifest_hash="sha256:" + "0" * 64,
        )
        return evidence["reused"] is True and evidence["source_stage"] == "e1-pilot"
    except (integrity.IntegrityError, KeyError):
        return False


def run_live_grading(
    args: argparse.Namespace, contract: Mapping[str, Any], contract_path: Path,
    corpus: Mapping[str, Any], manifest: Mapping[str, Any], manifest_path: Path | None,
) -> Mapping[str, Any]:
    if args.worker_stage is None:
        raise integrity.IntegrityError("live grading requires a worker stage")
    with integrity.PrivateRunAuthority(Path(args.run_receipt)) as authority:
        manifest_hash = grader_manifest_hash(manifest, manifest_path)
        experiment = "e2" if args.worker_stage.startswith("e2") else "e1"
        route = read_e2_calibration_route(authority, args.worker_stage) if experiment == "e2" else {
            "source_stage": args.worker_stage, "reused": False,
        }
        calibration = integrity.validate_calibration_evidence(
            authority, contract, contract_path, worker_stage=args.worker_stage,
            batch_manifest_hash=manifest_hash, expected_source_stage=route["source_stage"],
        )
        if calibration["reused"] is not route["reused"]:
            raise integrity.IntegrityError("calibration evidence does not match the pinned E2 route")
        worker_dir = authority.directory(f"sanitized/{args.worker_stage}/workers")
        workers = _json_packets(worker_dir)
        if len(workers) != contract["development_design"]["worker_outputs"]:
            raise integrity.IntegrityError("live grading requires the complete worker collection")
        by_trial = {(item["case_id"], item["arm"], item["repetition"]): item for item in workers}
        if len(by_trial) != len(workers):
            raise integrity.IntegrityError("duplicate worker logical identity")
        stages = authority.directory("stages")
        sanitized = authority.directory("sanitized")
        raw = authority.directory("raw")
        locks = stages.child(".locks", create=True)
        work_stage = stages.child(args.stage_child, create=not args.resume, exclusive=not args.resume)
        output_stage = sanitized.child(args.stage_child, create=not args.resume, exclusive=not args.resume)
        identity = {
            "schema_version": "interpretation-integrity.grade-stage.v0", "stage_id": args.stage_child,
            "worker_stage": args.worker_stage, "contract_hash": integrity.sha256_file(contract_path),
            "batch_manifest_hash": manifest_hash,
            "experiment": experiment,
            "batch_ids": sorted(batch["batch_id"] for batch in manifest["reviewer_batches"]),
            "reviewers": ["reviewer-a", "reviewer-b"], "authority_effect": "none",
        }
        if args.resume:
            if work_stage.read_json(".stage.json") != identity:
                raise integrity.IntegrityError("live-grade resume identity mismatch")
        else:
            work_stage.write_json_new(".stage.json", identity)
        rubric_prompt = (ROOT / "evals/interpretation_integrity/grader_prompt.v0.txt").read_text(encoding="utf-8")
        cases = {item["case_id"]: item for item in corpus["cases"]}
        packets: list[Mapping[str, Any]] = []
        started = time.monotonic()
        for reviewer in ("reviewer-a", "reviewer-b"):
            reviewer_dir = output_stage.child(reviewer, create=not args.resume)
            for batch in [value for value in manifest["reviewer_batches"] if value["reviewer_alias"] == reviewer]:
                blind_items = []
                for item in batch["items"]:
                    worker = by_trial.get((item["case_id"], item["arm"], item["repetition"]))
                    if worker is None:
                        raise integrity.IntegrityError("grader batch references missing worker output")
                    blind_items.append((item["blind_alias"], worker, cases[item["case_id"]]))
                packets.append(execute_grade_batch(
                    batch_id=batch["batch_id"], reviewer_id=reviewer, blind_items=blind_items,
                    contract=contract, contract_hash=integrity.sha256_file(contract_path),
                    batch_manifest_hash=manifest_hash, stage_id=args.stage_child,
                    work_parent=work_stage, output_dir=reviewer_dir, raw_dir=raw, locks_dir=locks,
                    rubric_prompt=rubric_prompt, worker_stage=args.worker_stage, experiment=experiment,
                    budget_guard=lambda logical, attempt: reserve_service_attempt(
                        authority, contract, experiment, logical, attempt,
                        calibration_reused=experiment == "e2" and calibration["reused"],
                    ),
                ))
            reviewer_dir.close()
        for directory in (output_stage, work_stage, locks, raw, sanitized, stages, worker_dir):
            directory.close()
        return {"stage": "grade-live", "batch_count": len(packets), "grade_count": sum(len(value["grades"]) for value in packets), "authority_effect": "none"}


def run_grader_calibration(
    args: argparse.Namespace, contract: Mapping[str, Any], contract_path: Path,
    corpus: Mapping[str, Any], manifest: Mapping[str, Any], manifest_path: Path | None,
) -> Mapping[str, Any]:
    if args.reviewers != "reviewer-a,reviewer-b" or not args.worker_stage:
        raise integrity.IntegrityError("calibration requires a frozen worker lane and two reviewer identities")
    experiment = "e2" if args.worker_stage.startswith("e2") else "e1"
    if experiment == "e1" and args.worker_stage != "e1-pilot":
        raise integrity.IntegrityError("E1 calibration requires the frozen E1 pilot lane")
    manifest_hash = grader_manifest_hash(manifest, manifest_path)
    if experiment == "e2":
        with integrity.PrivateRunAuthority(Path(args.run_receipt)) as authority:
            route = read_e2_calibration_route(authority, args.worker_stage)
            try:
                existing = authority.directory(f"sanitized/{route['source_stage']}/calibration")
            except integrity.IntegrityError:
                existing = None
            else:
                existing.close()
            if route["reused"] and existing is None:
                raise integrity.IntegrityError("pinned E1 calibration reuse evidence is missing")
            try:
                evidence = integrity.validate_calibration_evidence(
                    authority, contract, contract_path, worker_stage=args.worker_stage,
                    batch_manifest_hash=manifest_hash, expected_source_stage=route["source_stage"],
                )
            except integrity.IntegrityError:
                if existing is not None:
                    raise
                evidence = None
        if evidence is not None:
            if evidence["reused"] is not route["reused"]:
                raise integrity.IntegrityError("calibration evidence does not match the pinned E2 route")
            return {
                "stage": "calibrate-graders", "batch_count": 0, "grade_count": 0,
                "passed_reviewers": 2, "calibration_reused": evidence["reused"],
                "calibration_source_stage": evidence["source_stage"], "authority_effect": "none",
            }
    gold_path = ROOT / "tests/fixtures/interpretation_integrity/grader_calibration.v0.json"
    gold = integrity.load_json(gold_path)
    integrity.validate_gold(gold)
    by_gold = {item["gold_id"]: item for item in gold["outputs"]}
    cases = {item["case_id"]: item for item in corpus["cases"]}
    with integrity.PrivateRunAuthority(Path(args.run_receipt)) as authority:
        worker_dir = authority.directory(f"sanitized/{args.worker_stage}/workers")
        if len(_json_packets(worker_dir)) != contract["development_design"]["worker_outputs"]:
            raise integrity.IntegrityError("calibration requires the complete worker collection")
        stages, sanitized, raw = authority.directory("stages"), authority.directory("sanitized"), authority.directory("raw")
        locks = stages.child(".locks", create=True)
        work_stage = stages.child(args.stage_child, create=not args.resume, exclusive=not args.resume)
        batch_stage = sanitized.child(args.stage_child, create=not args.resume, exclusive=not args.resume)
        pilot_stage = sanitized.child(args.worker_stage)
        calibration_dir = pilot_stage.child("calibration", create=not args.resume)
        work_identity = {
            "schema_version": "interpretation-integrity.service-stage.v0", "service_kind": "calibration",
            "stage_id": args.stage_child, "worker_stage": args.worker_stage, "experiment": experiment,
            "contract_hash": integrity.sha256_file(contract_path), "batch_manifest_hash": manifest_hash,
            "batch_ids": sorted(batch["batch_id"] for batch in manifest["gold_batches"]),
            "authority_effect": "none",
        }
        if args.resume:
            if work_stage.read_json(".stage.json") != work_identity:
                raise integrity.IntegrityError("calibration resume stage identity mismatch")
        else:
            work_stage.write_json_new(".stage.json", work_identity)
        rubric_prompt = (ROOT / "evals/interpretation_integrity/grader_prompt.v0.txt").read_text(encoding="utf-8")
        packets: list[Mapping[str, Any]] = []
        for reviewer in ("reviewer-a", "reviewer-b"):
            reviewer_dir = batch_stage.child(reviewer, create=not args.resume)
            reviewer_grades: list[Mapping[str, Any]] = []
            for batch in [value for value in manifest["gold_batches"] if value["reviewer_alias"] == reviewer]:
                blind_items = []
                for gold_id in batch["gold_ids"]:
                    item = by_gold[gold_id]
                    worker = {"trial_key": gold_id, "case_id": item["case_id"], "response_text": item["response_text"]}
                    alias = integrity.sha256_json({"batch": batch["batch_id"], "gold_id": gold_id})[-16:]
                    blind_items.append((alias, worker, cases[item["case_id"]]))
                packet = execute_grade_batch(
                    batch_id=batch["batch_id"], reviewer_id=reviewer, blind_items=blind_items,
                    contract=contract, contract_hash=integrity.sha256_file(contract_path),
                    batch_manifest_hash=manifest_hash, stage_id=args.stage_child,
                    work_parent=work_stage, output_dir=reviewer_dir, raw_dir=raw, locks_dir=locks,
                    rubric_prompt=rubric_prompt, worker_stage=args.worker_stage, calibration=True,
                    experiment=experiment,
                    budget_guard=lambda logical, attempt: reserve_service_attempt(
                        authority, contract, experiment, logical, attempt, calibration_reused=False,
                    ),
                )
                packets.append(packet); reviewer_grades.extend(packet["grades"])
            aggregate = {
                "schema_version": "interpretation-integrity.grader-calibration-packet.v0",
                "reviewer_id": reviewer, "reviewer_model": contract["system"]["grader_model"],
                "reviewer_reasoning": contract["system"]["grader_reasoning"],
                "contract_hash": integrity.sha256_file(contract_path),
                "batch_manifest_hash": manifest_hash,
                "grades": sorted(reviewer_grades, key=lambda value: value["subject_id"]),
                "authority_effect": "none",
            }
            aggregate_name = f"{reviewer}.json"
            if aggregate_name in calibration_dir.names():
                if calibration_dir.read_json(aggregate_name) != aggregate:
                    raise integrity.IntegrityError("calibration aggregate resume identity mismatch")
            else:
                calibration_dir.write_json_new(aggregate_name, aggregate)
            reviewer_dir.close()
        for directory in (calibration_dir, pilot_stage, batch_stage, work_stage, locks, raw, sanitized, stages, worker_dir):
            directory.close()
    receipts = [
        integrity.create_calibration_receipt(
            contract_path=contract_path, gold_path=gold_path, batch_manifest_path=manifest_path,
            run_receipt=Path(args.run_receipt), stage_id=args.worker_stage, reviewer_id=reviewer,
            persist=not args.resume, batch_manifest=manifest, batch_manifest_hash=manifest_hash,
        )
        for reviewer in ("reviewer-a", "reviewer-b")
    ]
    return {
        "stage": "calibrate-graders", "batch_count": len(packets),
        "grade_count": sum(len(packet["grades"]) for packet in packets),
        "passed_reviewers": sum(receipt["passed"] for receipt in receipts),
        "calibration_reused": False, "calibration_source_stage": args.worker_stage,
        "authority_effect": "none",
    }


def run_grade_adjudication(
    args: argparse.Namespace, contract: Mapping[str, Any], contract_path: Path,
    corpus: Mapping[str, Any], manifest: Mapping[str, Any], manifest_path: Path | None,
) -> Mapping[str, Any]:
    with integrity.PrivateRunAuthority(Path(args.run_receipt)) as authority:
        agreement_path = Path(args.agreement_name)
        pure = Path(agreement_path)
        parent_rel, leaf = pure.parent.as_posix(), pure.name
        agreement_dir = authority.directory(parent_rel)
        unvalidated_agreement = agreement_dir.read_json(leaf)
        agreement = integrity.validate_existing_grade_agreement(
            contract_path, Path(args.run_receipt), unvalidated_agreement.get("grade_stage", ""),
            args.agreement_name,
        )
        if agreement["eligible_dispute_count"] > contract["budgets"]["max_live_adjudicated_outputs"]:
            raise integrity.IntegrityError("adjudication dispute ceiling exceeded")
        grade_stage = agreement["grade_stage"]
        grades_root = authority.directory(f"sanitized/{grade_stage}")
        original: dict[str, list[Mapping[str, Any]]] = {}
        for reviewer in agreement["reviewer_ids"]:
            reviewer_dir = grades_root.child(reviewer)
            for packet in _json_packets(reviewer_dir):
                for grade in packet["grades"]:
                    original.setdefault(grade["subject_id"], []).append(grade)
            reviewer_dir.close()
        worker_stage = agreement["worker_stage"]
        manifest_hash = grader_manifest_hash(manifest, manifest_path)
        if agreement["batch_manifest_hash"] != manifest_hash:
            raise integrity.IntegrityError("adjudication manifest does not match the validated agreement")
        worker_dir = authority.directory(f"sanitized/{worker_stage}/workers")
        workers = {item["trial_key"]: item for item in _json_packets(worker_dir)}
        cases = {item["case_id"]: item for item in corpus["cases"]}
        eligible = agreement["eligible_dispute_subjects"]
        if any(subject not in workers or len(original.get(subject, [])) != 2 for subject in eligible):
            raise integrity.IntegrityError("adjudication does not bind complete original evidence")
        stages, sanitized, raw = authority.directory("stages"), authority.directory("sanitized"), authority.directory("raw")
        locks = stages.child(".locks", create=True)
        work_stage = stages.child(args.stage_child, create=not args.resume, exclusive=not args.resume)
        output_stage = sanitized.child(args.stage_child, create=not args.resume, exclusive=not args.resume)
        output_dir = output_stage.child("adjudicator", create=not args.resume)
        rubric_prompt = (ROOT / "evals/interpretation_integrity/grader_prompt.v0.txt").read_text(encoding="utf-8")
        packets = []
        experiment = "e2" if worker_stage.startswith("e2") else "e1"
        adjudication_batch_ids = [
            f"{experiment}-adjudicator-batch-{index // 8 + 1:02d}" for index in range(0, len(eligible), 8)
        ]
        work_identity = {
            "schema_version": "interpretation-integrity.service-stage.v0", "service_kind": "adjudication",
            "stage_id": args.stage_child, "worker_stage": worker_stage, "experiment": experiment,
            "contract_hash": integrity.sha256_file(contract_path), "batch_manifest_hash": manifest_hash,
            "batch_ids": adjudication_batch_ids, "authority_effect": "none",
        }
        if args.resume:
            if work_stage.read_json(".stage.json") != work_identity:
                raise integrity.IntegrityError("adjudication resume stage identity mismatch")
        else:
            work_stage.write_json_new(".stage.json", work_identity)
        for batch_index in range(0, len(eligible), 8):
            subjects = eligible[batch_index:batch_index + 8]
            batch_id = f"{experiment}-adjudicator-batch-{batch_index // 8 + 1:02d}"
            blind_items = [
                (integrity.sha256_json({"stage": args.stage_child, "subject": subject})[-16:], workers[subject], cases[workers[subject]["case_id"]])
                for subject in subjects
            ]
            packets.append(execute_grade_batch(
                batch_id=batch_id, reviewer_id="adjudicator", blind_items=blind_items,
                contract=contract, contract_hash=integrity.sha256_file(contract_path),
                batch_manifest_hash=manifest_hash, stage_id=args.stage_child,
                work_parent=work_stage, output_dir=output_dir, raw_dir=raw, locks_dir=locks,
                rubric_prompt=rubric_prompt, adjudication=True, original_grades=original,
                original_collection_digest=agreement["original_collection_digest"],
                worker_stage=worker_stage, experiment=experiment,
                budget_guard=lambda logical, attempt: reserve_service_attempt(
                    authority, contract, experiment, logical, attempt,
                    calibration_reused=experiment == "e2" and agreement["calibration_reused"],
                ),
            ))
        for directory in (output_dir, output_stage, work_stage, locks, raw, sanitized, stages, worker_dir, grades_root, agreement_dir):
            directory.close()
        return {"stage": "adjudicate-grades", "batch_count": len(packets), "grade_count": sum(len(value["grades"]) for value in packets), "authority_effect": "none"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--stage", choices=["e1", "e2", "e3", "calibrate-graders", "grade-live", "adjudicate-grades"], required=True)
    parser.add_argument("--arms")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--run-receipt", required=True)
    parser.add_argument("--stage-child", required=True)
    parser.add_argument("--cases", default="tests/fixtures/interpretation_integrity/cases.v0.json")
    parser.add_argument("--admission")
    parser.add_argument("--procedure-source")
    parser.add_argument("--procedure-mode")
    parser.add_argument("--observability-preflight", type=int)
    parser.add_argument("--create-disposable-codex-home", action="store_true")
    parser.add_argument("--create-disposable-install-target", action="store_true")
    parser.add_argument("--install-from-source")
    parser.add_argument("--harness")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--batch-manifest")
    parser.add_argument("--worker-stage")
    parser.add_argument("--reviewers")
    parser.add_argument("--agreement-name")
    parser.add_argument("--max-batches", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        contract_path = Path(args.contract)
        contract = integrity.load_json(contract_path)
        integrity.validate_document(contract, ROOT / "evals/interpretation_integrity/evaluation_contract.schema.json")
        if contract_path.resolve() != (ROOT / "evals/interpretation_integrity/evaluation_contract.v0.json").resolve():
            raise integrity.IntegrityError("runner accepts only the repository-owned frozen contract")
        corpus = integrity.load_json(args.cases)
        integrity.validate_cases(corpus, ROOT / "evals/interpretation_integrity/case.schema.json")
        integrity.validate_fixture_balance(corpus)
        if contract["artifact_hashes"]["cases"] != integrity.sha256_file(Path(args.cases)):
            raise integrity.IntegrityError("runner corpus hash does not match the frozen contract")
        for key, path in {
            "case_schema": ROOT / "evals/interpretation_integrity/case.schema.json",
            "common_prompt": ROOT / "evals/interpretation_integrity/common_prompt.v0.txt",
            "compact_invariant": ROOT / "evals/interpretation_integrity/compact_invariant.v0.txt",
            "evaluation_contract_schema": ROOT / "evals/interpretation_integrity/evaluation_contract.schema.json",
            "e2_grader_batch_manifest_schema": ROOT / "evals/interpretation_integrity/e2_grader_batch_manifest.schema.json",
        }.items():
            if contract["artifact_hashes"][key] != integrity.sha256_file(path):
                raise integrity.IntegrityError(f"runner artifact hash drift: {key}")
        receipt_path = Path(args.run_receipt)
        run_root = integrity.resolve_run_root(receipt_path)
        integrity.validate_canonical_paid_service_authority(contract_path, receipt_path)
        if args.stage in {"calibrate-graders", "grade-live", "adjudicate-grades"}:
            if args.stage == "adjudicate-grades":
                pure = Path(args.agreement_name or "")
                if pure.is_absolute() or len(pure.parts) < 2:
                    raise integrity.IntegrityError("adjudication requires a private agreement receipt")
                with integrity.PrivateRunAuthority(receipt_path) as authority:
                    agreement_dir = authority.directory(pure.parent.as_posix())
                    agreement_preview = agreement_dir.read_json(pure.name); agreement_dir.close()
                args.worker_stage = agreement_preview.get("worker_stage")
            use_private_e2 = (
                isinstance(args.worker_stage, str) and args.worker_stage.startswith("e2")
            )
            if use_private_e2:
                with integrity.PrivateRunAuthority(receipt_path) as authority:
                    manifest, manifest_hash = load_private_e2_manifest(
                        authority, args.worker_stage, contract, contract_path, corpus,
                    )
                    route = read_e2_calibration_route(authority, args.worker_stage)
                args.runtime_calibration_source_stage = route["source_stage"]
                manifest_path = None
            else:
                manifest_path = Path(args.batch_manifest or ROOT / "evals/interpretation_integrity/results/grader_batch_manifest.v0.json")
                manifest = integrity.load_json(manifest_path)
                integrity.validate_batch_manifest(manifest, corpus)
                manifest_hash = integrity.sha256_file(manifest_path)
                if contract["artifact_hashes"]["batch_manifest"] != manifest_hash:
                    raise integrity.IntegrityError("grading batch manifest drifted")
            args.runtime_manifest_hash = manifest_hash
            if args.stage != "calibrate-graders":
                integrity.validate_grading_runner_preconditions(args, contract, run_root)
            if args.stage == "calibrate-graders":
                result = run_grader_calibration(args, contract, contract_path, corpus, manifest, manifest_path)
            elif args.stage == "grade-live":
                result = run_live_grading(args, contract, contract_path, corpus, manifest, manifest_path)
            else:
                result = run_grade_adjudication(args, contract, contract_path, corpus, manifest, manifest_path)
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.stage == "e3":
            integrity.validate_e3_runner_preconditions(args, contract, run_root)
            raise integrity.IntegrityError("E3 is operationally blocked until an admitted generated skill and disposable authentication boundary exist")
        if args.max_cases is None or args.repetitions is None:
            raise integrity.IntegrityError("worker stages require --max-cases and --repetitions")
        if not (1 <= args.max_cases <= 24) or not (1 <= args.repetitions <= 2):
            raise integrity.IntegrityError("requested trial count exceeds frozen worker budget")
        if args.stage == "e1":
            arms = ["baseline", "compact-invariant"]
            if args.arms != ",".join(arms):
                raise integrity.IntegrityError("E1 arms must be baseline,compact-invariant")
        else:
            arms = ["compact-invariant", "procedural-skill"]
            if args.arms != ",".join(arms) or args.procedure_mode != "prompt-injection-no-tools":
                raise integrity.IntegrityError("E2 must compare compact-invariant,procedural-skill with prompt-injection-no-tools")
            if not args.admission:
                raise integrity.IntegrityError("E2 is not admitted by the frozen E1 disposition")
            e2_disposition = integrity.validate_canonical_e2_admission(contract_path, Path(args.admission))
            if not args.procedure_source:
                raise integrity.IntegrityError("E2 requires a frozen procedure source")
        procedure_text = ""
        if args.stage == "e2":
            procedure_path = Path(args.procedure_source)
            descriptor = integrity.open_regular_nofollow(procedure_path)
            try:
                procedure_text = integrity.read_descriptor_bytes(descriptor).decode("utf-8", "strict")
            finally:
                os.close(descriptor)
            integrity.require_nfc_text(procedure_text, "E2 procedure")
            if not procedure_text.strip():
                raise integrity.IntegrityError("E2 procedure source is empty")
        manifest_path = Path(args.batch_manifest or ROOT / "evals/interpretation_integrity/results/grader_batch_manifest.v0.json")
        source_manifest = integrity.load_json(manifest_path)
        integrity.validate_batch_manifest(source_manifest, corpus)
        if contract["artifact_hashes"]["batch_manifest"] != integrity.sha256_file(manifest_path):
            raise integrity.IntegrityError("worker schedule hash does not match the frozen contract")
        manifest = source_manifest
        manifest_hash = integrity.sha256_file(manifest_path)
        if args.stage == "e1":
            schedule = validate_and_select_schedule(
                manifest, corpus, max_cases=args.max_cases, repetitions=args.repetitions, arms=arms,
            )
        else:
            procedure_hash = integrity.sha256_bytes(procedure_text.encode("utf-8"))
            manifest = integrity.derive_e2_batch_manifest(
                source_manifest, source_e1_manifest_hash=integrity.sha256_file(manifest_path),
                admission_hash=integrity.sha256_file(Path(args.admission)),
                compact_invariant_hash=contract["artifact_hashes"]["compact_invariant"],
                procedural_skill_hash=procedure_hash,
            )
            manifest_hash = integrity.sha256_json(manifest)
            schedule = validate_and_select_e2_schedule(
                manifest, corpus, source_e1_manifest_hash=integrity.sha256_file(manifest_path),
                admission_hash=integrity.sha256_file(Path(args.admission)),
                compact_invariant_hash=contract["artifact_hashes"]["compact_invariant"],
                procedural_skill_hash=procedure_hash, max_cases=args.max_cases,
                repetitions=args.repetitions,
            )
        calibration_route = {"source_stage": None, "reused": False}
        if args.stage == "e2":
            with integrity.PrivateRunAuthority(receipt_path) as authority:
                calibration_route = dict(resolve_e2_calibration_route(authority, contract, contract_path))
            if calibration_route["source_stage"] is None:
                calibration_route["source_stage"] = args.stage_child
        identity_payload = {
            "stage": args.stage,
            "stage_child": args.stage_child,
            "contract_hash": integrity.sha256_file(contract_path),
            "corpus_hash": integrity.sha256_file(Path(args.cases)),
            "batch_manifest_hash": manifest_hash,
            "schedule_digest": integrity.sha256_json(schedule),
            "arms": arms,
            "max_cases": args.max_cases,
            "repetitions": args.repetitions,
            "worker_model": contract["system"]["worker_model"],
            "worker_reasoning": contract["system"]["worker_reasoning"],
            "procedure_hash": integrity.sha256_bytes(procedure_text.encode("utf-8")) if procedure_text else None,
            "calibration_source_stage": calibration_route["source_stage"],
            "calibration_reused": calibration_route["reused"],
            "authority_effect": "none",
        }
        stage_identity = {
            **identity_payload,
            "identity_hash": integrity.sha256_json(identity_payload),
            "created_at_epoch": int(time.time()),
        }
        with integrity.PrivateRunAuthority(receipt_path) as authority:
            raw_dir = authority.directory("raw")
            stages_dir = authority.directory("stages")
            sanitized_dir = authority.directory("sanitized")
            locks_dir = stages_dir.child(".locks", create=True)
            if args.resume:
                stage_dir = stages_dir.child(args.stage_child)
                sanitized_stage = sanitized_dir.child(args.stage_child)
                workers_dir = sanitized_stage.child("workers")
                existing_identity = stage_dir.read_json(".stage.json")
                if existing_identity.get("identity_hash") != stage_identity["identity_hash"] or any(
                    existing_identity.get(key) != value for key, value in identity_payload.items()
                ):
                    raise integrity.IntegrityError("resume stage identity mismatch")
                stage_identity = existing_identity
                if any(name.startswith(".") and name.endswith(".tmp") for name in stage_dir.names() + sanitized_stage.names() + workers_dir.names()):
                    raise integrity.IntegrityError("resume found an unquarantined partial write")
            else:
                stage_dir = stages_dir.child(args.stage_child, create=True, exclusive=True)
                sanitized_stage = sanitized_dir.child(args.stage_child, create=True, exclusive=True)
                workers_dir = sanitized_stage.child("workers", create=True, exclusive=True)
                stage_dir.write_json_new(".stage.json", stage_identity)
                if args.stage == "e2":
                    persist_e2_batch_manifest(sanitized_stage, manifest, resume=False)
            if args.stage == "e2" and args.resume:
                persist_e2_batch_manifest(sanitized_stage, manifest, resume=True)
            common = (ROOT / "evals/interpretation_integrity/common_prompt.v0.txt").read_text(encoding="utf-8")
            invariant = (ROOT / "evals/interpretation_integrity/compact_invariant.v0.txt").read_text(encoding="utf-8")
            by_case = {case["case_id"]: case for case in corpus["cases"]}
            packets: list[Mapping[str, Any]] = []
            for item in schedule:
                case = by_case[item["case_id"]]
                if args.stage == "e1":
                    baseline = build_prompt(case, "baseline", common, invariant)
                    variant = build_prompt(case, "compact-invariant", common, invariant)
                    assert_single_variable_pair(baseline, variant, invariant)
                packets.append(execute_trial(
                    case=case, arm=item["arm"], repetition=item["repetition"],
                    schedule_position=item["position"], contract=contract,
                    contract_hash=integrity.sha256_file(contract_path),
                    corpus_hash=integrity.sha256_file(Path(args.cases)), common_prompt=common,
                    invariant=invariant, raw_dir=raw_dir, stage_dir=stage_dir, workers_dir=workers_dir,
                    locks_dir=locks_dir, stage_identity_hash=stage_identity["identity_hash"], procedure_text=procedure_text,
                    budget_guard=lambda logical, attempt: reserve_service_attempt(
                        authority, contract, args.stage, logical, attempt,
                        calibration_reused=args.stage == "e2" and stage_identity["calibration_reused"],
                    ),
                ))
            validate_pair_start_skew(packets)
            for key in {(packet["case_id"], packet["repetition"]) for packet in packets}:
                pair = [packet for packet in packets if (packet["case_id"], packet["repetition"]) == key]
                if len(pair) == 2 and pair[0]["instruction_inventory"] != pair[1]["instruction_inventory"]:
                    raise integrity.IntegrityError("unexpected instruction inventory drift across paired arms")
            states = dict(Counter(packet["terminal_state"] for packet in packets))
            for directory in (workers_dir, sanitized_stage, stage_dir, locks_dir, sanitized_dir, stages_dir, raw_dir):
                directory.close()
        print(json.dumps({"stage": args.stage, "attempted": len(packets), "terminal_states": states, "authority_effect": "none"}, sort_keys=True))
        return 0 if states.get("complete", 0) == len(packets) else 2
    except integrity.IntegrityError as exc:
        print(f"interpretation-integrity runner error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
