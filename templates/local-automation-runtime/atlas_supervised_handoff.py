"""Contract, persistence, and replay helpers for supervised local role handoffs.

The supervisor performs host dispatch explicitly in the app. This module
validates and persists role reservations/results without launching inference.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
import copy
import pathlib
import shutil
import subprocess
import time
from dataclasses import asdict, is_dataclass
from typing import Any

import atlas_local_sizing
import atlas_work_items
import atlas_workflows
import atlas_delta_review


PROTOCOL_VERSION = 1
TERMINAL_RESULT_STATUSES = {"complete", "failed", "blocked", "incomplete"}
_HEX_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BINDING_FIELDS = {
    "protocol_version", "handoff_id", "work_item_id", "operation_id", "supervisor_id",
    "claim_fingerprint", "run_id", "template_id", "rework_count", "context_hash",
    "contract_hash", "checkout", "revision", "generation", "prior_run_snapshot_hash",
    "role_id", "role_assignment", "packet_hash", "artifact_generation", "binding_hash",
}
_CAPTURE_MAX_BYTES = 65536
_CAPTURE_MAX_DEPTH = 32
_CAPTURE_MAX_NODES = 20000
_CAPTURE_METADATA_MAX_DEPTH = 48
_CAPTURE_METADATA_MAX_NODES = 25000


class HandoffRefusal(ValueError):
    """Raised when supplied handoff or import data fails a frozen fence."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _capture_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def _capture_constant(_value: str) -> None:
    raise ValueError("nonfinite")


def _capture_float(value: str) -> float:
    parsed = float(value)
    if not __import__("math").isfinite(parsed):
        raise ValueError("nonfinite")
    return parsed


def _check_capture_json(
    value: Any, *, max_depth: int = _CAPTURE_MAX_DEPTH,
    max_nodes: int = _CAPTURE_MAX_NODES,
) -> None:
    nodes = 0
    def visit(node: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise ValueError("bounds")
        if node is None or type(node) in (str, bool, int):
            if type(node) is str:
                node.encode("utf-8")
            return
        if type(node) is float:
            if not __import__("math").isfinite(node):
                raise ValueError("nonfinite")
            return
        if type(node) is list:
            for child in node:
                visit(child, depth + 1)
            return
        if type(node) is dict:
            for key, child in node.items():
                if type(key) is not str:
                    raise ValueError("key")
                key.encode("utf-8")
                visit(child, depth + 1)
            return
        raise ValueError("type")
    visit(value, 0)


def capture_host_return(
    provider: Any, worker: Any, *, expected_reservation: dict[str, Any],
    host_receipt: dict[str, Any], dispatched_packet_sha256: str,
    result_bytes: bytes, prior_capture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Correlate original candidate bytes with the exact live pending reservation.

    The caller supplies independently held reservation and host observation. This
    is a bounded correlation record, not host authentication or result import.
    """
    owner = _require_worker(provider, worker)
    if type(expected_reservation) is not dict or not isinstance(expected_reservation.get("binding"), dict) or type(expected_reservation.get("packet")) is not dict:
        raise HandoffRefusal("reservation", "expected reservation is malformed")
    expected_binding = _validate_binding(expected_reservation["binding"])
    if expected_binding["supervisor_id"] != owner or sha256_json(expected_reservation["packet"]) != expected_binding["packet_hash"]:
        raise HandoffRefusal("reservation", "expected reservation does not match its owner or packet")
    if dispatched_packet_sha256 != expected_binding["packet_hash"] or not isinstance(dispatched_packet_sha256, str) or not _SHA256.fullmatch(dispatched_packet_sha256):
        raise HandoffRefusal("packet", "observed dispatched packet hash does not match reservation")
    if type(result_bytes) is not bytes or not 1 <= len(result_bytes) <= _CAPTURE_MAX_BYTES:
        raise HandoffRefusal("result_json", "original host result bytes are outside the accepted bounds")
    try:
        parsed = json.loads(result_bytes.decode("utf-8"), object_pairs_hook=_capture_pairs,
                            parse_constant=_capture_constant, parse_float=_capture_float)
        if type(parsed) is not dict:
            raise ValueError("object")
        _check_capture_json(parsed)
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError):
        raise HandoffRefusal("result_json", "original host result is not bounded strict JSON") from None
    receipt_fields = {"invocation_id", "transport", "checkout", "revision", "model", "reasoning"}
    if type(host_receipt) is not dict or set(host_receipt) != receipt_fields or any(type(v) is not str for v in host_receipt.values()):
        raise HandoffRefusal("host_receipt", "observed host receipt is malformed")
    if not host_receipt["invocation_id"].strip() or host_receipt["transport"] != "supervised_in_app":
        raise HandoffRefusal("host_receipt", "observed host receipt is malformed")
    if (host_receipt["checkout"] != expected_binding["checkout"] or host_receipt["revision"] != expected_binding["revision"]
            or host_receipt["model"] != expected_binding["role_assignment"].get("model")
            or host_receipt["reasoning"] != expected_binding["role_assignment"].get("reasoning")):
        raise HandoffRefusal("host_receipt", "observed host receipt does not match reservation")
    # Re-read and revalidate the exact pending item while holding the maintained queue lock.
    with provider.store.lock():
        payload = provider.store.load()
        item = _item(payload, expected_binding["work_item_id"])
        pending = _state(item).get("pending")
        if type(pending) is not dict or pending.get("binding") != expected_reservation["binding"] or pending.get("packet") != expected_reservation["packet"]:
            raise HandoffRefusal("pending", "exact expected reservation is not currently pending")
        _assert_global_pending(payload, source_id=expected_binding["work_item_id"], expected_pending=pending)
        current = _validate_pending_return(provider, worker, item, pending, owner=owner,
                                           expected_revision=expected_binding["revision"])
        if current["binding"] != expected_reservation["binding"] or current["packet"] != expected_reservation["packet"]:
            raise HandoffRefusal("stale_binding", "current reservation differs from expected reservation")
    binding_copy = copy.deepcopy(current["binding"])
    reservation = {"binding": copy.deepcopy(current["binding"]), "packet": copy.deepcopy(current["packet"]),
                   "artifacts": copy.deepcopy(current["artifacts"])}
    receipt_copy = copy.deepcopy(host_receipt)
    digest = hashlib.sha256(result_bytes).hexdigest()
    observation = {"host_receipt": receipt_copy, "packet_sha256": dispatched_packet_sha256,
                   "result_bytes": bytes(result_bytes)}
    envelope = {"binding": binding_copy, "host_receipt": copy.deepcopy(host_receipt), "result_sha256": digest}
    capture = {"status": "captured", "expected_reservation": reservation,
               "host_observation": observation, "envelope": envelope, "result_bytes": bytes(result_bytes)}
    _validate_capture_metadata(capture)
    if prior_capture is not None:
        try:
            _validate_prior_capture(prior_capture)
        except (HandoffRefusal, KeyError, AttributeError, TypeError, ValueError, RecursionError, OverflowError):
            raise HandoffRefusal("prior_capture", "prior capture is malformed") from None
        if not _captures_equal(prior_capture, capture):
            raise HandoffRefusal("replay_conflict", "prior capture conflicts with current host return")
    return capture


def _capture_metadata(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("shape")
    result = {key: part for key, part in value.items() if key not in {"result_bytes", "host_observation"}}
    observation = value.get("host_observation")
    if type(observation) is not dict:
        raise ValueError("observation")
    result["host_observation"] = {key: part for key, part in observation.items() if key != "result_bytes"}
    return result


def _validate_capture_metadata(value: Any) -> None:
    _check_capture_json(_capture_metadata(value), max_depth=_CAPTURE_METADATA_MAX_DEPTH,
                        max_nodes=_CAPTURE_METADATA_MAX_NODES)


def _validate_prior_capture(value: Any) -> None:
    """Validate every sealed field before replay comparison (Python bool/int equality is loose)."""
    if type(value) is not dict or set(value) != {"status", "expected_reservation", "host_observation", "envelope", "result_bytes"}:
        raise ValueError("shape")
    _validate_capture_metadata(value)
    if type(value["status"]) is not str or value["status"] != "captured":
        raise ValueError("status")
    reservation = value["expected_reservation"]
    if type(reservation) is not dict or set(reservation) != {"binding", "packet", "artifacts"}:
        raise ValueError("reservation")
    binding = reservation["binding"]
    _validate_binding(binding)
    if type(reservation["packet"]) is not dict or sha256_json(reservation["packet"]) != binding["packet_hash"]:
        raise ValueError("packet")
    artifacts = reservation["artifacts"]
    if type(artifacts) is not dict or set(artifacts) != {"team_role_tasks_path", "team_run_path", "team_rollup_path"}:
        raise ValueError("artifacts")
    if any(type(path) is not str or not path for path in artifacts.values()):
        raise ValueError("artifacts")

    observation = value["host_observation"]
    if type(observation) is not dict or set(observation) != {"host_receipt", "packet_sha256", "result_bytes"}:
        raise ValueError("observation")
    receipt = observation["host_receipt"]
    fields = {"invocation_id", "transport", "checkout", "revision", "model", "reasoning"}
    if type(receipt) is not dict or set(receipt) != fields or any(type(part) is not str for part in receipt.values()):
        raise ValueError("receipt")
    if (not receipt["invocation_id"].strip() or receipt["transport"] != "supervised_in_app"
            or receipt["checkout"] != binding["checkout"] or receipt["revision"] != binding["revision"]
            or receipt["model"] != binding["role_assignment"].get("model")
            or receipt["reasoning"] != binding["role_assignment"].get("reasoning")):
        raise ValueError("receipt")
    if type(observation["packet_sha256"]) is not str or not _SHA256.fullmatch(observation["packet_sha256"]):
        raise ValueError("packet digest")
    if observation["packet_sha256"] != binding["packet_hash"]:
        raise ValueError("packet digest")

    envelope = value["envelope"]
    if type(envelope) is not dict or set(envelope) != {"binding", "host_receipt", "result_sha256"}:
        raise ValueError("envelope")
    _validate_binding(envelope["binding"])
    if (canonical_json(envelope["binding"]) != canonical_json(binding)
            or canonical_json(envelope["host_receipt"]) != canonical_json(receipt)):
        raise ValueError("envelope mismatch")
    raw = value["result_bytes"]
    observed_raw = observation["result_bytes"]
    if type(raw) is not bytes or type(observed_raw) is not bytes or raw != observed_raw:
        raise ValueError("raw bytes")
    if not 1 <= len(raw) <= _CAPTURE_MAX_BYTES:
        raise ValueError("raw bounds")
    parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_capture_pairs,
                        parse_constant=_capture_constant, parse_float=_capture_float)
    if type(parsed) is not dict:
        raise ValueError("raw object")
    _check_capture_json(parsed)
    digest = hashlib.sha256(raw).hexdigest()
    if type(envelope["result_sha256"]) is not str or envelope["result_sha256"] != digest:
        raise ValueError("raw digest")


def _captures_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare ordinary JSON fields canonically and custody bytes byte-for-byte."""
    return (left["result_bytes"] == right["result_bytes"]
            and left["host_observation"]["result_bytes"] == right["host_observation"]["result_bytes"]
            and canonical_json(_capture_metadata(left)) == canonical_json(_capture_metadata(right)))


def canonical_json(value: Any) -> bytes:
    """Encode JSON-compatible protocol data deterministically."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HandoffRefusal("malformed", "handoff data must be finite JSON-compatible values") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _object_dict(value: Any, name: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    method = getattr(value, "to_dict", None)
    if callable(method):
        result = method()
        if isinstance(result, dict):
            return result
    raise HandoffRefusal("malformed", f"{name} must be an object or workflow model")


def _nonblank(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HandoffRefusal("malformed", f"{name} must be a nonblank string")
    return value.strip()


def _template_and_run(template: Any, run: Any) -> tuple[atlas_workflows.TeamTemplate, atlas_workflows.TeamRun]:
    try:
        template_value = template if isinstance(template, atlas_workflows.TeamTemplate) else atlas_workflows.TeamTemplate.from_dict(_object_dict(template, "template"))
        run_value = run if isinstance(run, atlas_workflows.TeamRun) else atlas_workflows.TeamRun.from_dict(_object_dict(run, "run"))
    except (KeyError, TypeError, ValueError) as exc:
        raise HandoffRefusal("malformed", f"invalid workflow template or run: {exc}") from exc
    errors = template_value.validate()
    if errors:
        raise HandoffRefusal("contract", "; ".join(errors))
    return template_value, run_value


def _context_sizing(context: dict[str, Any], template: atlas_workflows.TeamTemplate) -> tuple[dict[str, Any], dict[str, Any]]:
    records = [{"role_id": role.id, "goal_gate": role.goal_gate} for role in template.roles]
    qualification = atlas_local_sizing.qualify(context, roles=records)
    if qualification.get("status") != "qualified":
        reason = "; ".join(qualification.get("reasons") or []) or str(qualification.get("status"))
        raise HandoffRefusal("sizing", f"workflow does not have qualified local sizing: {reason}")
    contract_hash = sha256_json({
        "template": template.to_dict(),
        "context": context,
        "qualification": qualification,
    })
    return qualification, {"context_hash": sha256_json(context), "contract_hash": contract_hash}


def _eligible_role(template: atlas_workflows.TeamTemplate, run: atlas_workflows.TeamRun) -> atlas_workflows.TeamRole:
    if run.status != "running":
        raise HandoffRefusal("run_state", f"workflow run is not eligible for another role: {run.status}")
    roles_by_id = {role.id: role for role in template.roles}
    for role_id, result in run.role_results.items():
        if role_id not in roles_by_id:
            raise HandoffRefusal("contract", f"workflow run contains unknown role result: {role_id}")
        if not isinstance(result, atlas_workflows.TeamRunRoleResult) or result.role_id != role_id:
            raise HandoffRefusal("role_identity", f"workflow result identity does not match role key: {role_id}")
    # Re-run maintained normalization and dependency checks against a deep copy.
    # Stored `running` status and precomputed contract_issues are not authority:
    # validators must derive whether every attempted result still satisfies its
    # current role contract before anything downstream can become eligible.
    normalized_run = copy.deepcopy(run)
    try:
        atlas_workflows.apply_role_results(template=template, run=normalized_run, results=[])
    except (KeyError, TypeError, ValueError) as exc:
        raise HandoffRefusal("contract", f"workflow run results are malformed: {exc}") from exc
    if normalized_run.status != "running":
        raise HandoffRefusal("run_state", f"normalized workflow run is not eligible for another role: {normalized_run.status}")
    for role_id, result in normalized_run.role_results.items():
        role = roles_by_id[role_id]
        if not atlas_workflows.role_result_satisfies_outputs(role, result):
            raise HandoffRefusal("contract", f"attempted role result does not satisfy its workflow contract: {role_id}")
    ordered_ids = [role_id for phase in template.role_phases() for role_id in phase]
    for role_id in ordered_ids:
        role = roles_by_id[role_id]
        if role_id in run.role_results:
            continue
        if atlas_workflows.role_dependency_blockers(role, run, roles_by_id):
            continue
        return role
    raise HandoffRefusal("no_eligible_role", "workflow has no unattempted dependency-satisfied role")


def prepare_role_handoff(
    *,
    item: dict[str, Any],
    claim: dict[str, Any],
    supervisor_id: str,
    context: dict[str, Any],
    template: Any,
    run: Any,
    checkout: str,
    revision: str,
    generation: int,
    handoff_id: str,
    prior_run_snapshot_hash: str,
    packet_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one deterministic eligible packet and its immutable identity binding.

    The caller supplies independently observed revision/checkout and a fresh
    opaque handoff ID. This helper does not inspect files, execute commands, or
    mutate its inputs.
    """
    if not isinstance(item, dict) or not isinstance(claim, dict) or not isinstance(context, dict):
        raise HandoffRefusal("malformed", "item, claim, and context must be objects")
    source_id = item.get("id") or item.get("work_item_id") or item.get("source_id")
    source_id = _nonblank(source_id, "work item ID")
    owner = _nonblank(supervisor_id, "supervisor ID")
    lifecycle = item.get("lifecycle") if isinstance(item.get("lifecycle"), dict) else {}
    item_state = lifecycle.get("state") or item.get("state") or item.get("status")
    if not isinstance(item_state, str) or item_state.strip().lower() != "running":
        raise HandoffRefusal("item_state", "work item must already be active")
    if item.get("claim") != claim or claim.get("claimed_by") != owner:
        raise HandoffRefusal("claim_owner", "claim does not belong to this supervisor")
    if not isinstance(claim.get("claimed_at"), str) or not claim["claimed_at"].strip():
        raise HandoffRefusal("claim", "claim timestamp is missing")
    if isinstance(claim.get("pid"), bool) or not isinstance(claim.get("pid"), int):
        raise HandoffRefusal("claim", "claim process identity is malformed")
    checkout_value = _nonblank(checkout, "checkout identity")
    revision_value = _nonblank(revision, "repository revision")
    if not _HEX_REVISION.fullmatch(revision_value):
        raise HandoffRefusal("revision", "repository revision must be a full hexadecimal Git object ID")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise HandoffRefusal("generation", "generation must be a positive integer")
    handoff_value = _nonblank(handoff_id, "handoff ID")
    try:
        if str(uuid.UUID(handoff_value)) != handoff_value:
            raise ValueError("noncanonical UUID")
    except (ValueError, AttributeError) as exc:
        raise HandoffRefusal("handoff_id", "handoff ID must be a canonical UUID") from exc
    if not _SHA256.fullmatch(prior_run_snapshot_hash):
        raise HandoffRefusal("snapshot", "prior run snapshot hash must be lowercase SHA256")

    template_value, run_value = _template_and_run(template, run)
    if run_value.work_item_id != source_id:
        raise HandoffRefusal("run_identity", "workflow run belongs to a different work item")
    if run_value.template_id != template_value.id:
        raise HandoffRefusal("run_identity", "workflow run uses a different template")
    qualification, hashes = _context_sizing(context, template_value)
    role = _eligible_role(template_value, run_value)
    packets = atlas_workflows.role_task_packets(template_value, run_value, work_item_context=context)
    generated_packet = next((value for value in packets if value.get("role_id") == role.id), None)
    if not isinstance(generated_packet, dict):
        raise HandoffRefusal("packet", "selected role packet is unavailable")
    packet = packet_override if packet_override is not None else generated_packet
    if not isinstance(packet, dict) or packet.get("role_id") != role.id:
        raise HandoffRefusal("packet", "selected packet does not match eligible role")
    if packet_override is not None:
        base = {key: value for key, value in generated_packet.items() if key != "agent_definition"}
        override_base = {key: value for key, value in packet.items() if key != "agent_definition"}
        if override_base != base:
            raise HandoffRefusal("packet", "selected packet differs from the maintained workflow packet")
    assignment = qualification.get("assignments", {}).get(role.id)
    try:
        fixed_assignment = atlas_local_sizing.assignment_for_task(packet)
    except (KeyError, TypeError, ValueError) as exc:
        raise HandoffRefusal("sizing", f"selected role has no fixed assignment: {exc}") from exc
    if assignment != fixed_assignment:
        raise HandoffRefusal("sizing", "selected role assignment differs from qualified template sizing")

    rework_count = lifecycle.get("rework_count", 0)
    if isinstance(rework_count, bool) or not isinstance(rework_count, int) or rework_count < 0:
        raise HandoffRefusal("rework", "work item rework count is malformed")
    binding = {
        "protocol_version": PROTOCOL_VERSION,
        "handoff_id": handoff_value,
        "work_item_id": source_id,
        "operation_id": item.get("operation_id") or f"atlas-work-item:{source_id}",
        "supervisor_id": owner,
        "claim_fingerprint": sha256_json(claim),
        "run_id": run_value.id,
        "template_id": template_value.id,
        "rework_count": rework_count,
        "context_hash": hashes["context_hash"],
        "contract_hash": hashes["contract_hash"],
        "checkout": checkout_value,
        "revision": revision_value,
        "generation": generation,
        "prior_run_snapshot_hash": prior_run_snapshot_hash,
        "role_id": role.id,
        "role_assignment": fixed_assignment,
        "packet_hash": sha256_json(packet),
        "artifact_generation": sha256_json({"source_id": source_id, "generation": generation,
                                             "handoff_id": handoff_value}),
    }
    binding["binding_hash"] = sha256_json(binding)
    return {"binding": binding, "packet": packet}


def _parse_terminal_role_result(result_bytes: bytes, binding: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result_bytes, bytes):
        raise HandoffRefusal("malformed", "original role result must be supplied as bytes")
    try:
        root = json.loads(result_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffRefusal("result_json", "original role result is not valid JSON") from exc
    if not isinstance(root, dict) or set(root) != {"role_results"}:
        raise HandoffRefusal("result_shape", "role result envelope must contain only role_results")
    records = root.get("role_results")
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise HandoffRefusal("result_shape", "exactly one role result is required")
    result = records[0]
    allowed = {"role_id", "status", "outputs", "evidence", "notes", "contract_issues", "goal_review"}
    if set(result).difference(allowed):
        raise HandoffRefusal("result_shape", "role result contains unsupported fields")
    if result.get("role_id") != binding.get("role_id"):
        raise HandoffRefusal("role", "role result does not match the reserved role")
    status = result.get("status")
    if not isinstance(status, str) or status not in TERMINAL_RESULT_STATUSES:
        raise HandoffRefusal("result_status", "role result must have one terminal attempt status")
    outputs = result.get("outputs", {})
    evidence = result.get("evidence", [])
    issues = result.get("contract_issues", [])
    notes = result.get("notes", "")
    if not isinstance(outputs, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in outputs.items()):
        raise HandoffRefusal("result_shape", "role outputs must map strings to strings")
    if not isinstance(evidence, list) or any(not isinstance(value, str) for value in evidence):
        raise HandoffRefusal("result_shape", "role evidence must be a list of strings")
    if not isinstance(issues, list) or any(not isinstance(value, str) for value in issues):
        raise HandoffRefusal("result_shape", "role contract issues must be a list of strings")
    if not isinstance(notes, str):
        raise HandoffRefusal("result_shape", "role notes must be a string")
    return result


def _validate_binding(binding: Any) -> dict[str, Any]:
    if not isinstance(binding, dict):
        raise HandoffRefusal("binding", "handoff binding must be an object")
    if set(binding) != _BINDING_FIELDS:
        raise HandoffRefusal("binding", "handoff binding has missing or unsupported fields")
    supplied_hash = binding.get("binding_hash")
    body = {key: value for key, value in binding.items() if key != "binding_hash"}
    if type(supplied_hash) is not str or not _SHA256.fullmatch(supplied_hash) or sha256_json(body) != supplied_hash:
        raise HandoffRefusal("binding", "handoff binding hash is invalid")
    if type(body.get("protocol_version")) is not int or body.get("protocol_version") != PROTOCOL_VERSION:
        raise HandoffRefusal("binding", "unsupported handoff protocol version")
    for key in ("claim_fingerprint", "context_hash", "contract_hash", "prior_run_snapshot_hash", "packet_hash"):
        if type(body.get(key)) is not str or not _SHA256.fullmatch(body[key]):
            raise HandoffRefusal("binding", f"handoff binding {key} is malformed")
    for key in ("handoff_id", "work_item_id", "operation_id", "supervisor_id", "run_id", "template_id", "checkout", "role_id", "artifact_generation"):
        if type(body.get(key)) is not str:
            raise HandoffRefusal("binding", f"handoff binding {key} is malformed")
        _nonblank(body.get(key), f"handoff binding {key}")
    if type(body.get("revision")) is not str or not _HEX_REVISION.fullmatch(body["revision"]):
        raise HandoffRefusal("binding", "handoff binding revision is malformed")
    for key in ("generation", "rework_count"):
        value = body.get(key)
        if type(value) is not int or value < (1 if key == "generation" else 0):
            raise HandoffRefusal("binding", f"handoff binding {key} is malformed")
    assignment = body.get("role_assignment")
    if (type(assignment) is not dict or set(assignment) != {"model", "purpose", "reason", "reasoning"}
            or any(type(value) is not str for value in assignment.values())):
        raise HandoffRefusal("binding", "handoff binding role assignment is malformed")
    return body


def classify_role_result_import(
    *,
    envelope: dict[str, Any],
    result_bytes: bytes,
    expected_binding: dict[str, Any],
    expected_packet: dict[str, Any],
    accepted_receipts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify one role-result import as accepted/duplicate or refuse it.

    The host receipt is a supervisor correlation record, not cryptographic
    worker authentication. No file or external state is read or modified.
    """
    if not isinstance(envelope, dict):
        raise HandoffRefusal("envelope", "import envelope must be an object")
    required = {"binding", "host_receipt", "result_sha256"}
    if set(envelope) != required:
        raise HandoffRefusal("envelope", "import envelope has missing or unsupported fields")
    binding_body = _validate_binding(envelope.get("binding"))
    expected_body = _validate_binding(expected_binding)
    handoff_id = binding_body.get("handoff_id")
    digest = hashlib.sha256(result_bytes).hexdigest() if isinstance(result_bytes, bytes) else None
    receipt = envelope.get("host_receipt")
    if not isinstance(receipt, dict):
        raise HandoffRefusal("host_receipt", "supervisor host receipt must be an object")
    receipt_fields = {"invocation_id", "transport", "checkout", "revision", "model", "reasoning"}
    if set(receipt) != receipt_fields:
        raise HandoffRefusal("host_receipt", "supervisor host receipt has missing or unsupported fields")
    receipts = accepted_receipts if isinstance(accepted_receipts, dict) else {}
    prior = receipts.get(handoff_id)
    if prior is not None:
        if not isinstance(prior, dict):
            raise HandoffRefusal("replay_conflict", "stored accepted receipt is malformed")
        same = (
            prior.get("binding") == envelope.get("binding")
            and prior.get("host_receipt") == receipt
            and prior.get("result_sha256") == digest
            and envelope.get("result_sha256") == digest
        )
        if same:
            return {"status": "duplicate", "handoff_id": handoff_id,
                    "receipt": prior.get("acknowledgement", prior)}
        raise HandoffRefusal("replay_conflict", "handoff ID already has a different accepted result")

    if binding_body != expected_body:
        raise HandoffRefusal("stale_binding", "import binding does not match the current reservation")
    if envelope.get("result_sha256") != digest or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise HandoffRefusal("result_hash", "original result bytes do not match the envelope hash")
    packet = expected_packet
    if not isinstance(packet, dict) or sha256_json(packet) != binding_body.get("packet_hash"):
        raise HandoffRefusal("packet", "current selected packet does not match the binding")
    if receipt.get("transport") != "supervised_in_app":
        raise HandoffRefusal("host_receipt", "host receipt transport must be supervised_in_app")
    _nonblank(receipt.get("invocation_id"), "host invocation ID")
    if receipt.get("checkout") != binding_body.get("checkout") or receipt.get("revision") != binding_body.get("revision"):
        raise HandoffRefusal("host_receipt", "host receipt checkout or revision does not match the binding")
    assignment = binding_body.get("role_assignment")
    if not isinstance(assignment, dict):
        raise HandoffRefusal("binding", "role assignment is missing from binding")
    for key in ("model", "reasoning"):
        if receipt.get(key) != assignment.get(key):
            raise HandoffRefusal("host_receipt", f"host receipt {key} does not match the fixed assignment")
    result = _parse_terminal_role_result(result_bytes, binding_body)
    return {"status": "accepted", "handoff_id": handoff_id,
            "binding": envelope["binding"], "host_receipt": receipt,
            "result_sha256": digest, "role_result": result}


def _item(payload: dict[str, Any], source_id: str) -> dict[str, Any]:
    matches = [value for value in payload.get("work_items", [])
               if isinstance(value, dict) and atlas_work_items.item_id(value) == source_id]
    if len(matches) != 1:
        raise HandoffRefusal("item", "work item is missing or ambiguous")
    return matches[0]


def _observe(operation: Any, expected_revision: str) -> tuple[str, str]:
    configured = getattr(operation, "execution_repo", None)
    if not isinstance(configured, str) or not configured.strip():
        raise HandoffRefusal("checkout", "an explicit configured execution checkout is required")
    checkout = pathlib.Path(configured.strip()).expanduser().resolve()
    if not checkout.is_dir() or checkout.as_uri().startswith("file://") is False:
        raise HandoffRefusal("checkout", "configured execution checkout is unavailable")
    def git(*args: str) -> str:
        try:
            result = subprocess.run(["git", "--no-optional-locks", "-C", str(checkout), *args],
                capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HandoffRefusal("checkout", "bounded local Git identity read failed") from exc
        if result.returncode != 0:
            raise HandoffRefusal("checkout", "configured path is not a readable Git checkout")
        return result.stdout.strip()
    root = pathlib.Path(git("rev-parse", "--show-toplevel")).resolve()
    revision = git("rev-parse", "--verify", "HEAD")
    if root != checkout or not _HEX_REVISION.fullmatch(revision) or revision != expected_revision:
        raise HandoffRefusal("revision", "checkout root or full HEAD differs from the requested baseline")
    return str(root), revision


def _require_worker(provider: Any, worker: Any) -> str:
    owner = _nonblank(getattr(provider, "claimed_by", None), "stable supervisor ID")
    if getattr(worker, "command", None) is not None:
        raise HandoffRefusal("worker", "supervised handoff requires worker.command=None")
    if not isinstance(getattr(worker, "jobs_dir", None), pathlib.Path) or worker.templates_dir is None:
        raise HandoffRefusal("worker", "worker jobs and template roots are required")
    return owner


def _state(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("supervised_handoff_v1")
    return copy.deepcopy(value) if isinstance(value, dict) else {"last_generation": 0, "accepted": {}}


def _source_hash(item: dict[str, Any]) -> str:
    value = copy.deepcopy(item)
    value.pop("supervised_handoff_v1", None)
    return sha256_json(value)


def _artifact_hashes(paths: dict[str, str]) -> dict[str, str]:
    result = {}
    for key, value in paths.items():
        path = pathlib.Path(value)
        result[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _assert_global_pending(payload: dict[str, Any], *, source_id: str,
                           expected_pending: dict[str, Any] | None = None) -> None:
    """Enforce the serial protocol, allowing only this exact reservation."""
    for candidate in payload.get("work_items", []):
        if not isinstance(candidate, dict):
            continue
        pending = _state(candidate).get("pending")
        if pending is None:
            continue
        if (atlas_work_items.item_id(candidate) == source_id and expected_pending is not None
                and sha256_json(pending) == sha256_json(expected_pending)):
            continue
        raise HandoffRefusal("pending", "another unresolved handoff violates the store-wide serial reservation")


def _verified_prior_run(item: dict[str, Any], jobs_root: pathlib.Path) -> tuple[str, str | None]:
    runs = item.get("workflow_runs") if isinstance(item.get("workflow_runs"), list) else []
    if not runs:
        return hashlib.sha256(b"").hexdigest(), None
    latest = runs[-1]
    artifacts = latest.get("artifacts") if isinstance(latest, dict) and isinstance(latest.get("artifacts"), dict) else {}
    run_path_value = artifacts.get("team_run_path")
    if not isinstance(run_path_value, str):
        raise HandoffRefusal("run_owner", "existing workflow run has no adapter-owned artifact reference")
    run_path = pathlib.Path(run_path_value).resolve()
    try:
        run_path.relative_to(jobs_root.resolve())
    except ValueError as exc:
        raise HandoffRefusal("run_owner", "existing workflow run is outside the configured jobs root") from exc
    actual = hashlib.sha256(run_path.read_bytes()).hexdigest()
    state = _state(item)
    for record in state.get("accepted", {}).values():
        acknowledgement = record.get("acknowledgement", {}) if isinstance(record, dict) else {}
        if (acknowledgement.get("artifacts", {}).get("team_run_path") == str(run_path)
                and acknowledgement.get("artifact_hashes", {}).get("team_run_path") == actual):
            return actual, str(run_path)
    raise HandoffRefusal("run_owner", "existing workflow run is not a verified adapter-owned generation")


def _validate_pending_return(provider: Any, worker: Any, item: dict[str, Any], pending: dict[str, Any],
                             *, owner: str, expected_revision: str) -> dict[str, Any]:
    """Revalidate a durable reservation before returning it to a supervisor."""
    binding = _validate_binding(pending.get("binding"))
    if binding["supervisor_id"] != owner or binding["work_item_id"] != atlas_work_items.item_id(item):
        raise HandoffRefusal("claim_owner", "pending handoff belongs to a different supervisor or work item")
    claim = item.get("claim")
    if (atlas_work_items.item_state(item) != "running" or not isinstance(claim, dict)
            or claim.get("claimed_by") != owner
            or sha256_json(claim) != binding["claim_fingerprint"]):
        raise HandoffRefusal("claim_owner", "pending handoff no longer has its exact active claim")
    if _source_hash(item) != pending.get("source_item_hash"):
        raise HandoffRefusal("stale", "work item context changed after handoff preparation")
    state_without_pending = _state(item)
    state_without_pending.pop("pending", None)
    if sha256_json(state_without_pending) != pending.get("prior_state_hash"):
        raise HandoffRefusal("stale", "supervised handoff receipt state changed after preparation")
    operation = provider.project(item)
    checkout, revision = _observe(operation, expected_revision)
    if checkout != binding["checkout"] or revision != binding["revision"]:
        raise HandoffRefusal("revision", "pending handoff checkout or HEAD differs from its binding")
    if _artifact_hashes(pending.get("artifacts", {})) != pending.get("artifact_hashes"):
        raise HandoffRefusal("artifact", "reserved workflow artifact bytes changed")
    evidence = pending.get("workflow_evidence")
    if not isinstance(evidence, dict):
        raise HandoffRefusal("artifact", "reserved workflow evidence is malformed")
    templates = atlas_workflows.load_team_templates(worker.templates_dir)
    template = next((candidate for candidate in templates if candidate.id == binding["template_id"]), None)
    if template is None:
        raise HandoffRefusal("contract", "reserved workflow template is unavailable")
    context = operation.work_item_context
    _, hashes = _context_sizing(context, template)
    if hashes["context_hash"] != binding["context_hash"] or hashes["contract_hash"] != binding["contract_hash"]:
        raise HandoffRefusal("contract", "current workflow context or contract differs from the reservation")
    run_path = pathlib.Path(pending["artifacts"]["team_run_path"])
    run = atlas_workflows.load_team_run(run_path)
    if run.id != binding["run_id"] or run.work_item_id != binding["work_item_id"] or run.template_id != binding["template_id"]:
        raise HandoffRefusal("run_identity", "reserved workflow run identity changed")
    prior_hash, _ = _verified_prior_run(item, worker.jobs_dir)
    if prior_hash != binding["prior_run_snapshot_hash"]:
        raise HandoffRefusal("run_identity", "prior workflow generation changed after reservation")
    packet_doc = json.loads(pathlib.Path(pending["artifacts"]["team_role_tasks_path"]).read_text(encoding="utf-8"))
    tasks = packet_doc.get("tasks") if isinstance(packet_doc, dict) else None
    packet = next((value for value in tasks or [] if isinstance(value, dict) and value.get("role_id") == binding["role_id"]), None)
    if packet != pending.get("packet") or sha256_json(packet) != binding["packet_hash"]:
        raise HandoffRefusal("packet", "reserved role packet identity changed")
    current_packets = atlas_workflows.role_task_packets(template, run,
        registry=worker.load_agent_registry(), agent_root=worker.agent_root,
        work_item_context=context)
    current_packet = next((value for value in current_packets if value.get("role_id") == binding["role_id"]), None)
    if current_packet != packet:
        raise HandoffRefusal("packet", "current template or registry packet differs from the reservation")
    recomputed = prepare_role_handoff(item=item, claim=claim, supervisor_id=owner,
        context=context, template=template, run=run, checkout=checkout, revision=revision,
        generation=binding["generation"], handoff_id=binding["handoff_id"],
        prior_run_snapshot_hash=prior_hash, packet_override=current_packet)
    if recomputed["binding"] != pending["binding"] or recomputed["packet"] != packet:
        raise HandoffRefusal("binding", "current workflow state no longer matches the reserved binding")
    return {"status": "prepared", "binding": copy.deepcopy(pending["binding"]),
            "packet": copy.deepcopy(packet), "artifacts": copy.deepcopy(pending["artifacts"])}


def _validate_delta_review_pilot_completion(item: dict[str, Any], *, expected_checkout: str) -> None:
    """Apply the optional trusted-metadata pilot gate before final completion."""
    try:
        atlas_delta_review.validate_pilot_task_completion(item, expected_checkout=expected_checkout)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HandoffRefusal("pilot_acceptance", f"delta-review pilot acceptance failed: {exc}") from exc


def prepare_handoff(provider: Any, worker: Any, *, source_id: str, expected_revision: str) -> dict[str, Any]:
    """Persist one owned role reservation before the supervisor dispatches it."""
    owner = _require_worker(provider, worker)
    payload = provider.store.load()
    item = _item(payload, source_id)
    state = _state(item)
    captured_state_hash = sha256_json(state)
    pending = copy.deepcopy(state.get("pending"))
    if pending is not None:
        _assert_global_pending(payload, source_id=source_id, expected_pending=pending)
        return _validate_pending_return(provider, worker, item, pending, owner=owner,
                                        expected_revision=expected_revision)
    _assert_global_pending(payload, source_id=source_id)
    claim = item.get("claim")
    if atlas_work_items.item_state(item) != "running" or not isinstance(claim, dict) or claim.get("claimed_by") != owner:
        raise HandoffRefusal("claim_owner", "item must have an active claim owned by this supervisor")
    operation = provider.project(item, {atlas_work_items.item_id(v): v for v in payload["work_items"]})
    checkout, revision = _observe(operation, expected_revision)
    prior_hash, prior_path = _verified_prior_run(item, worker.jobs_dir)
    state = _state(item)
    generation = int(state.get("last_generation", 0)) + 1
    handoff_id = str(uuid.uuid4())
    gen = sha256_json({"id": source_id, "generation": generation, "nonce": handoff_id})
    job_dir = worker.jobs_dir.resolve() / ("supervised-" + gen[:32])
    job_dir.mkdir(parents=True, exist_ok=False)
    private_store_path = job_dir / "queue.json"
    private_store_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    try:
        evidence = worker.write_workflow_artifacts(operation, job_dir, gen[:16], private_store_path)
        if evidence.get("workflow_error") or not evidence.get("team_run_path"):
            raise HandoffRefusal("workflow", evidence.get("workflow_error", "workflow artifacts unavailable"))
        template = next(t for t in atlas_workflows.load_team_templates(worker.templates_dir) if t.id == evidence["team_template"])
        run = atlas_workflows.load_team_run(evidence["team_run_path"])
        packet_document = json.loads(pathlib.Path(evidence["team_role_tasks_path"]).read_text())
        packet_list = packet_document.get("tasks", []) if isinstance(packet_document, dict) else []
        eligible_role = _eligible_role(template, run)
        packet = next((p for p in packet_list if isinstance(p, dict)
                       and p.get("role_id") == eligible_role.id), None)
        if packet is None:
            raise HandoffRefusal("packet", "maintained eligible role packet is unavailable")
        prepared = prepare_role_handoff(item=item, claim=claim, supervisor_id=owner,
            context=operation.work_item_context, template=template, run=run, checkout=checkout,
            revision=revision, generation=generation, handoff_id=handoff_id,
            prior_run_snapshot_hash=prior_hash, packet_override=packet)
        paths = {key: evidence[key] for key in ("team_run_path", "team_rollup_path", "team_role_tasks_path")}
        hashes = _artifact_hashes(paths)
        state.update(last_generation=generation)
        pending_record = {**prepared, "state": "pending", "artifacts": paths, "artifact_hashes": hashes,
            "workflow_evidence": evidence, "source_item_hash": _source_hash(item),
            "prior_state_hash": sha256_json(state)}
        state["pending"] = pending_record
    finally:
        private_store_path.unlink(missing_ok=True)
        private_store_path.with_suffix(private_store_path.suffix + ".lock").unlink(missing_ok=True)
    with provider.store.lock():
        latest = provider.store.load()
        current = _item(latest, source_id)
        current_state = _state(current)
        if current_state.get("pending"):
            found = current_state["pending"]
            _assert_global_pending(latest, source_id=source_id, expected_pending=found)
            return _validate_pending_return(provider, worker, current, found, owner=owner,
                                            expected_revision=expected_revision)
        _assert_global_pending(latest, source_id=source_id)
        if (_source_hash(current) != pending_record["source_item_hash"]
                or sha256_json(_state(current)) != captured_state_hash):
            raise HandoffRefusal("stale", "work item changed while staging the reservation")
        staged_current = copy.deepcopy(current)
        staged_current["supervised_handoff_v1"] = state
        _validate_pending_return(provider, worker, staged_current, pending_record, owner=owner,
                                 expected_revision=expected_revision)
        current["supervised_handoff_v1"] = state
        provider.store.save(latest)
    return {"status": "prepared", "binding": prepared["binding"], "packet": prepared["packet"], "artifacts": paths}


def ingest_handoff(provider: Any, worker: Any, *, envelope: dict[str, Any], result_bytes: bytes) -> dict[str, Any]:
    """Apply a single bound role result to private copies, then publish once."""
    owner = _require_worker(provider, worker)
    if not isinstance(envelope, dict) or not isinstance(envelope.get("binding"), dict):
        raise HandoffRefusal("envelope", "import envelope must contain a binding")
    binding = _validate_binding(envelope["binding"])
    if owner != binding["supervisor_id"]:
        raise HandoffRefusal("claim_owner", "accepted replay must be presented by the original supervisor")
    source_id = binding["work_item_id"]
    payload = provider.store.load()
    item = _item(payload, source_id)
    state = _state(item)
    accepted = state.get("accepted", {})
    # Duplicate detection deliberately precedes checkout observation and staging.
    if binding["handoff_id"] in accepted:
        duplicate = classify_role_result_import(envelope=envelope, result_bytes=result_bytes,
            expected_binding=accepted[binding["handoff_id"]].get("binding"), expected_packet={},
            accepted_receipts=accepted)
        return duplicate
    pending = copy.deepcopy(state.get("pending"))
    if not isinstance(pending, dict) or pending.get("binding") != envelope["binding"]:
        raise HandoffRefusal("pending", "exact handoff is not pending")
    _assert_global_pending(payload, source_id=source_id, expected_pending=pending)
    state_without_pending = copy.deepcopy(state)
    state_without_pending.pop("pending", None)
    if sha256_json(state_without_pending) != pending.get("prior_state_hash"):
        raise HandoffRefusal("stale", "supervised handoff receipt state changed after preparation")
    _validate_pending_return(provider, worker, item, pending, owner=owner,
                             expected_revision=binding["revision"])
    operation = provider.project(item)
    packet = pending["packet"]
    classified = classify_role_result_import(envelope=envelope, result_bytes=result_bytes,
        expected_binding=pending["binding"], expected_packet=packet, accepted_receipts=accepted)
    generation = pathlib.Path(worker.jobs_dir).resolve() / ("supervised-import-" + uuid.uuid4().hex)
    generation.mkdir(parents=True, exist_ok=False)
    paths = {}
    for key, source in pending["artifacts"].items():
        dest = generation / pathlib.Path(source).name
        shutil.copyfile(source, dest)
        paths[key] = str(dest)
    raw_path = generation / "original-role-results.json"
    raw_path.write_bytes(result_bytes)
    evidence = dict(pending["workflow_evidence"])
    evidence.update(paths)
    evidence["team_run_path"] = paths["team_run_path"]
    evidence["team_rollup_path"] = paths["team_rollup_path"]
    evidence["team_role_tasks_path"] = paths["team_role_tasks_path"]
    updated = worker.apply_workflow_role_results(evidence, raw_path)
    run_status = updated.get("team_run_status")
    if run_status == "complete" and updated.get("goal_acceptance", {}).get("verdict") == "pass":
        _validate_delta_review_pilot_completion(item, expected_checkout=binding["checkout"])
    if updated.get("workflow_result_error") or run_status == "blocked":
        status = "blocked"
    elif run_status == "complete" and updated.get("goal_acceptance", {}).get("verdict") == "pass":
        status = "done"
    elif run_status == "running":
        status = "ready"
    else:
        status = "blocked"
    result = atlas_work_items.OperationResult(status=status, returncode=0 if status in {"ready", "done"} else 1,
        summary=f"Supervised in-app role {binding['role_id']} imported as {classified['role_result']['status']}.",
        evidence={**updated, "supervised_handoff": {"binding": binding, "host_receipt": envelope["host_receipt"],
            "result_sha256": classified["result_sha256"], "original_result_path": str(raw_path)}})
    private_path = generation / "private-queue.json"
    private_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    private_provider = atlas_work_items.AtlasWorkItemOperationProvider(atlas_work_items.AtlasWorkItemStore(private_path), claimed_by=owner)
    private_provider.record_result(operation, result)
    staged = _item(private_provider.store.load(), source_id)
    staged_state = _state(item)
    published_hashes = _artifact_hashes(paths)
    published_result_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    if published_result_hash != classified["result_sha256"]:
        raise HandoffRefusal("result_hash", "preserved original result bytes changed during staging")
    acknowledgement = {"status": "accepted", "handoff_id": binding["handoff_id"], "work_item_id": source_id,
        "result_sha256": classified["result_sha256"], "item_status": status, "artifacts": paths,
        "artifact_hashes": published_hashes, "original_result_path": str(raw_path),
        "original_result_sha256": published_result_hash}
    staged_state.setdefault("accepted", {})[binding["handoff_id"]] = {"binding": envelope["binding"],
        "host_receipt": envelope["host_receipt"], "result_sha256": classified["result_sha256"],
        "acknowledgement": acknowledgement, "generation": binding["generation"]}
    staged_state["last_generation"] = max(int(staged_state.get("last_generation", 0)), binding["generation"])
    staged_state.pop("pending", None)
    staged["supervised_handoff_v1"] = staged_state
    private_path.unlink(missing_ok=True)
    private_path.with_suffix(private_path.suffix + ".lock").unlink(missing_ok=True)
    with provider.store.lock():
        latest = provider.store.load()
        current = _item(latest, source_id)
        live = _state(current)
        dupe = live.get("accepted", {}).get(binding["handoff_id"])
        if dupe is not None:
            if owner != binding["supervisor_id"]:
                raise HandoffRefusal("claim_owner", "accepted replay must be presented by the original supervisor")
            return classify_role_result_import(envelope=envelope, result_bytes=result_bytes,
                expected_binding=dupe.get("binding"), expected_packet={},
                accepted_receipts={binding["handoff_id"]: dupe})
        _assert_global_pending(latest, source_id=source_id, expected_pending=pending)
        live_pending = live.get("pending")
        if not isinstance(live_pending, dict) or sha256_json(live_pending) != sha256_json(pending):
            raise HandoffRefusal("stale", "queue changed before result publication")
        _validate_pending_return(provider, worker, current, live_pending, owner=owner,
                                 expected_revision=binding["revision"])
        if status == "done":
            _validate_delta_review_pilot_completion(current, expected_checkout=binding["checkout"])
        if _artifact_hashes(paths) != published_hashes:
            raise HandoffRefusal("artifact", "newly staged publication artifacts changed before queue commit")
        current_result_bytes = raw_path.read_bytes()
        if (hashlib.sha256(current_result_bytes).hexdigest() != published_result_hash
                or current_result_bytes != result_bytes):
            raise HandoffRefusal("result_hash", "preserved original result bytes changed before queue commit")
        index = next(i for i, value in enumerate(latest["work_items"]) if atlas_work_items.item_id(value) == source_id)
        latest["work_items"][index] = staged
        provider.store.save(latest)
    return acknowledgement
