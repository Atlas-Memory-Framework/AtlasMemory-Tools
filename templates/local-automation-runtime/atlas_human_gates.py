"""Explicit human handoffs. Preview is pure; satisfaction requires signed evidence.

A human receipt supplies an answer, never worker execution authority. Its issuer
must be the configured owner and its signature binds the exact question, artifact,
candidate, work-item revision, and packet. Waiting creates no files or model calls.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from atlas_authority import AuthorityError, canonical_digest, strict_json_loads, verify_grant


class HumanGateError(ValueError):
    pass


KINDS = frozenset({"input", "approval", "test", "feedback", "taste"})
ACTIONS = frozenset({"local_execute", "draft_pr", "completion", "human_input", "human_test", "human_feedback", "human_taste", "human_approval",
                     "pipeline_run", "pipeline_approve", "pr_approve", "merge", "deploy", "permission_change", "service_connection"})
HEX = re.compile(r"[a-f0-9]{64}\Z")
COMMIT = re.compile(r"[a-f0-9]{40}\Z")
ISSUE = re.compile(r"azdo:[^:\s/]+:[^:\s/]+:[1-9][0-9]*\Z")


def _text(value: Any, label: str, maximum: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise HumanGateError(f"{label} requires bounded nonempty text")
    return value


def validate_gates(gates: Any) -> list[dict[str, Any]]:
    if not isinstance(gates, list) or len(gates) > 32:
        raise HumanGateError("human_gates must be a bounded list")
    ids: set[str] = set()
    fields = {"id", "kind", "owner", "question", "stage", "action", "artifact_sha256",
              "candidate_sha", "issue_id", "issue_revision"}
    for gate in gates:
        if not isinstance(gate, dict) or set(gate) != fields:
            raise HumanGateError("human gate has missing or unsupported fields")
        identifier = _text(gate["id"], "gate id", 80)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier) or identifier in ids:
            raise HumanGateError("human gate IDs must be unique safe identifiers")
        ids.add(identifier)
        if any(not isinstance(gate[key], str) for key in ("kind", "stage", "action")) or gate["kind"] not in KINDS or gate["stage"] not in {"before", "after"} or gate["action"] not in ACTIONS:
            raise HumanGateError("human gate kind, stage or action is unsupported")
        _text(gate["owner"], "gate owner", 240)
        _text(gate["question"], "gate question")
        if not isinstance(gate["artifact_sha256"], str) or not HEX.fullmatch(gate["artifact_sha256"]):
            raise HumanGateError("human gate must identify the exact review artifact")
        if gate["candidate_sha"] is not None and (not isinstance(gate["candidate_sha"], str) or not COMMIT.fullmatch(gate["candidate_sha"])):
            raise HumanGateError("candidate binding must be an exact commit or null before preparation")
        if not isinstance(gate["issue_id"], str) or not ISSUE.fullmatch(gate["issue_id"]):
            raise HumanGateError("human gate issue ID requires its Azure namespace")
        if type(gate["issue_revision"]) is not int or gate["issue_revision"] < 1:
            raise HumanGateError("human gate requires an exact issue revision")
    return gates


def gate_bindings(gate: dict[str, Any], receipt: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Describe what a human must sign; does not manufacture or verify a grant."""
    validate_gates([gate])
    required = {"issue_id", "issue_revision", "worker_packet_sha256", "candidate_sha", "action"}
    if not isinstance(context, dict) or not required.issubset(context) or set(context) - required - {"policy_sha256", "gate_template_sha256"}:
        raise HumanGateError("gate evaluation requires the exact operation context")
    if type(context["issue_revision"]) is not int or context["issue_revision"] < 1:
        raise HumanGateError("gate context revision must be a positive integer")
    if not isinstance(context["worker_packet_sha256"], str) or not HEX.fullmatch(context["worker_packet_sha256"]):
        raise HumanGateError("gate context packet digest is missing")
    if context["candidate_sha"] is not None and (not isinstance(context["candidate_sha"], str) or not COMMIT.fullmatch(context["candidate_sha"])):
        raise HumanGateError("gate context candidate is invalid")
    if gate["issue_id"] != context["issue_id"] or gate["issue_revision"] != context["issue_revision"] or gate["action"] != context["action"]:
        raise HumanGateError("gate no longer describes this issue revision and action")
    if gate["candidate_sha"] != context["candidate_sha"] or (gate["stage"] == "after" and gate["candidate_sha"] is None):
        raise HumanGateError("human testing or acceptance requires the current exact candidate")
    if not isinstance(receipt, dict) or set(receipt) != {"gate_id", "decision", "response", "grant"} or receipt["gate_id"] != gate["id"]:
        raise HumanGateError("receipt requires one exact gate and signed response")
    if not isinstance(receipt["decision"], str) or receipt["decision"] not in {"accepted", "rejected", "feedback"}:
        raise HumanGateError("human receipt decision is invalid")
    _text(receipt["response"], "human response", 16000)
    if not isinstance(receipt["grant"], dict):
        raise HumanGateError("human response requires a signed grant")
    result = {"gate_id": gate["id"], "issue_id": context["issue_id"], "issue_revision": context["issue_revision"],
              "worker_packet_sha256": context["worker_packet_sha256"], "candidate_sha": context["candidate_sha"],
              "artifact_sha256": gate["artifact_sha256"], "gate_sha256": canonical_digest(gate),
              "requested_action": gate["action"], "decision": receipt["decision"],
              "response_sha256": canonical_digest(receipt["response"])}
    for optional in ("policy_sha256", "gate_template_sha256"):
        if optional in context:
            if not isinstance(context[optional], str) or not HEX.fullmatch(context[optional]):
                raise HumanGateError("gate context policy or template digest is invalid")
            result[optional] = context[optional]
    return result


def evaluate_gates(runtime_dir: Any, gates: Any, receipts: Any, context: dict[str, Any],
                   stage: str = "before", *, now: Any = None) -> dict[str, Any]:
    """Authenticate selected handoffs; do not execute their requested actions.

Call only at an explicitly authorized execution boundary. Ordinary preview must
use validate_gates and display pending gates without invoking this function.
"""
    validate_gates(gates)
    if not isinstance(stage, str) or stage not in {"before", "after"} or not isinstance(context, dict) or not isinstance(context.get("action"), str) or context.get("action") not in ACTIONS:
        raise HumanGateError("gate evaluation needs an explicit action and stage")
    if not isinstance(receipts, list) or len(receipts) > 32:
        raise HumanGateError("human receipts must be a bounded list")
    supplied: dict[str, dict[str, Any]] = {}
    known = {gate["id"] for gate in gates}
    for receipt in receipts:
        if not isinstance(receipt, dict) or not isinstance(receipt.get("gate_id"), str) or receipt["gate_id"] not in known or receipt["gate_id"] in supplied:
            raise HumanGateError("unknown or duplicate human receipt")
        supplied[receipt["gate_id"]] = receipt
    pending, rejected, invalid, verified = [], [], [], []
    for gate in gates:
        if gate["stage"] != stage or gate["action"] != context["action"]:
            continue
        receipt = supplied.get(gate["id"])
        if receipt is None:
            pending.append(gate["id"])
            continue
        try:
            bindings = gate_bindings(gate, receipt, context)
            authenticated = verify_grant(runtime_dir, receipt["grant"], "human_gate", bindings, now=now)
            if authenticated.get("subject") != gate["owner"]:
                raise HumanGateError("verified human receipt issuer is not the required gate owner")
            if receipt["decision"] == "accepted":
                verified.append({"gate_id": gate["id"], "receipt_sha256": canonical_digest(receipt),
                                 "subject": authenticated["subject"]})
            else:
                pending.append(gate["id"])
                if receipt["decision"] == "rejected":
                    rejected.append(gate["id"])
        except (AuthorityError, HumanGateError, OSError, ValueError):
            # Do not expose signed response content, trust contents, or crypto diagnostics.
            pending.append(gate["id"])
            invalid.append(gate["id"])
    return {"satisfied": not pending, "pending": pending, "rejected": rejected, "invalid": invalid,
            "verified": verified, "completion": False}


def bound_human_answers(intake: dict[str, Any], receipts: list[dict[str, Any]],
                       evaluation: dict[str, Any]) -> list[dict[str, str]]:
    """Match authenticated answers to the primary evidence models actually see.

Callers must supply the result of their real evaluate_gates call. This helper
does not turn a supplied evaluation object into authority. Adding or changing an
answer creates a new immutable intake/hash and invalidates prior assessments.
"""
    try:
        validate_gates(intake["human_gates"])
        packet = intake["worker_packet"]
        selected = [gate for gate in intake["human_gates"] if gate["stage"] == "before" and gate["action"] == intake["step"]["action"] and gate["kind"] in {"input", "test", "taste", "feedback"}]
        if not isinstance(receipts, list) or not isinstance(evaluation, dict) or not isinstance(evaluation.get("verified"), list):
            raise HumanGateError("human answers require authenticated gate evaluation")
        result = []
        for gate in selected:
            matching = [receipt for receipt in receipts if isinstance(receipt, dict) and receipt.get("gate_id") == gate["id"]]
            if len(matching) != 1 or matching[0].get("decision") != "accepted":
                raise HumanGateError("required human answer is missing or has not been accepted")
            receipt = matching[0]
            authenticated = [item for item in evaluation["verified"] if isinstance(item, dict) and item.get("gate_id") == gate["id"]]
            if len(authenticated) != 1 or authenticated[0].get("subject") != gate["owner"] or authenticated[0].get("receipt_sha256") != canonical_digest(receipt):
                raise HumanGateError("human answer does not match authenticated owner evidence")
            identifier = "human-answer:" + gate["id"]
            sources = [item for item in intake["evidence"] if isinstance(item, dict) and item.get("id") == identifier]
            if len(sources) != 1:
                raise HumanGateError("authenticated human answer must be included in primary evidence before assessment")
            source = sources[0]
            if source.get("kind") != "issue" or source.get("path") is not None or type(source.get("revision")) is not int or source["revision"] != packet["revision"]:
                raise HumanGateError("human answer evidence belongs to another work-item revision")
            expected = {"gate_id": gate["id"], "response": receipt["response"]}
            if not isinstance(source.get("content"), str) or strict_json_loads(source["content"]) != expected or source.get("sha256") != canonical_digest(expected) or hashlib.sha256(source["content"].encode("utf-8")).hexdigest() != source["sha256"]:
                raise HumanGateError("primary human answer differs from the authenticated response")
            result.append({"gate_id": gate["id"], "owner": gate["owner"], "question": gate["question"],
                           "response": receipt["response"], "evidence_id": identifier})
        return result
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, HumanGateError):
            raise
        raise HumanGateError("human answer evidence is missing, stale or invalid") from exc
