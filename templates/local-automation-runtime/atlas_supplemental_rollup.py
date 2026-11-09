"""Pure eligibility and byte binding for a future supplemental-rollup adapter.

SECURITY BOUNDARY: disposition is explicitly trusted, source-owned input. This
function does not authenticate caller JSON, consult a registry, verify evidence
bytes, reserve work or authorize execution. A future maintained adapter must
select a genuine independently reviewed source record and verify native facts.
An eligible assessment alone creates no finishing opportunity. This module has
no callers and supplies no deployed finishing API or installed qualification.
"""

import hashlib
import json
import re
import unicodedata


# No real cases or synthetic fixtures are admitted by shipped source.
SOURCE_SUPPLEMENTAL_ROLLUP_CASES_V1 = {}

_DISPOSITION_SCHEMA = "atlas.supplemental-rollup-source-disposition.v1"
_FACTS_SCHEMA = "atlas.supplemental-rollup-facts.v1"
_ASSESSMENT_SCHEMA = "atlas.supplemental-rollup-assessment.v1"
_LIMIT = 16384
_MAX_INT = (1 << 63) - 1
_ROLES = ("implementation", "test-runner", "code-review", "semantic-alignment")
_HELPER_FAILURES = (
    "capture_helper_parse_failure",
    "capture_helper_path_failure",
    "capture_helper_serialization_failure",
)
_BINDING_KEYS = (
    "case_id", "work_item_id", "operator_owner", "worker_thread_id",
    "failed_handoff_id", "failed_invocation_id", "failed_result_sha256",
    "failure_evidence_sha256", "spec_sha256", "context_sha256",
    "contract_sha256", "revision", "source_file_sha256", "prior_result_sha256",
)
_FACT_KEYS = (
    "schema_version", "binding", "failure_kind", "work_item_state",
    "failed_role", "failed_result_status", "handoff_consumed", "rework_count",
    "pending_handoff", "process_uncertainty", "supplemental_count",
    "requested_operator_owner", "requested_worker_thread_id", "prior_roles",
    "goal_review", "started_epoch_seconds", "deadline_epoch_seconds",
)


def _keys(value, expected):
    # Check key types BEFORE comparison: foreign key objects can execute code.
    return (type(value) is dict and len(value) == len(expected)
            and all(type(key) is str for key in value)
            and value.keys() == set(expected))


def _ascii(value, limit):
    return type(value) is str and len(value) <= limit and value.isascii()


def _matches(value, pattern, limit):
    return _ascii(value, limit) and re.fullmatch(pattern, value) is not None


def _digest(value):
    return _matches(value, r"[0-9a-f]{64}", 64)


def _uuid(value):
    return _matches(value, r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", 36)


def _owner(value):
    return _matches(value, r"[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,255}", 256)


def _integer(value):
    return type(value) is int and 0 <= value <= _MAX_INT


def _path(value):
    return (_ascii(value, 256) and bool(value)
            and all(32 <= ord(char) < 127 for char in value)
            and "\\" not in value
            and all(part not in ("", ".", "..") for part in value.split("/")))


def _digest_map(value, keys):
    return _keys(value, keys) and all(_digest(item) for item in value.values())


def _binding(value):
    if not _keys(value, _BINDING_KEYS):
        return False
    if not (_matches(value["case_id"], r"[A-Z][A-Z0-9_-]{0,95}", 96)
            and _matches(value["work_item_id"], r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}", 128)
            and _owner(value["operator_owner"])
            and all(_uuid(value[key]) for key in
                    ("worker_thread_id", "failed_handoff_id", "failed_invocation_id"))
            and all(_digest(value[key]) for key in
                    ("failed_result_sha256", "failure_evidence_sha256", "spec_sha256",
                     "context_sha256", "contract_sha256"))
            and _matches(value["revision"], r"([0-9a-f]{40}|[0-9a-f]{64})", 64)
            and _digest_map(value["prior_result_sha256"], _ROLES)):
        return False
    files = value["source_file_sha256"]
    return (type(files) is dict and 1 <= len(files) <= 4
            and all(_path(key) and _digest(item) for key, item in files.items()))


def _issue(value):
    if type(value) is not str or not 1 <= len(value) <= 256:
        return False
    # Reject surrogate code points as well as Unicode control characters.
    if any(unicodedata.category(char) in ("Cc", "Cs") for char in value):
        return False
    return len(value.encode("utf-8")) <= 256


def _prior_roles(value):
    if not _keys(value, _ROLES):
        return False
    for role in value.values():
        if not (_keys(role, ("status", "outputs_complete", "contract_issues"))
                and _ascii(role["status"], 32)
                and type(role["outputs_complete"]) is bool):
            return False
        issues = role["contract_issues"]
        if not (type(issues) is list and len(issues) <= 16
                and all(_issue(issue) for issue in issues)):
            return False
    return True


def _goal(value):
    return (_keys(value, ("verdict", "reason_nonempty", "evidence_nonempty",
                          "context_sha256", "contract_sha256"))
            and _ascii(value["verdict"], 32)
            and type(value["reason_nonempty"]) is bool
            and type(value["evidence_nonempty"]) is bool
            and _digest(value["context_sha256"])
            and _digest(value["contract_sha256"]))


def _facts(value):
    return (_keys(value, _FACT_KEYS)
            and type(value["schema_version"]) is str
            and value["schema_version"] == _FACTS_SCHEMA
            and _binding(value["binding"])
            and _ascii(value["failure_kind"], 64)
            and all(_ascii(value[key], 32) for key in
                    ("work_item_state", "failed_role", "failed_result_status"))
            and all(type(value[key]) is bool for key in
                    ("handoff_consumed", "pending_handoff", "process_uncertainty"))
            and all(_integer(value[key]) for key in
                    ("rework_count", "supplemental_count", "started_epoch_seconds",
                     "deadline_epoch_seconds"))
            and _owner(value["requested_operator_owner"])
            and _uuid(value["requested_worker_thread_id"])
            and _prior_roles(value["prior_roles"])
            and _goal(value["goal_review"]))


def _disposition(value):
    return (_keys(value, ("schema_version", "binding", "failure_kind", "review_evidence_sha256"))
            and type(value["schema_version"]) is str
            and value["schema_version"] == _DISPOSITION_SCHEMA
            and _binding(value["binding"])
            and _ascii(value["failure_kind"], 64)
            and _digest_map(value["review_evidence_sha256"], ("code", "security", "protocol", "goal")))


def _canonical(value):
    # Called only after fixed-depth validation of every bounded component. No
    # arbitrary graph traversal, foreign methods or cyclic serialization occurs.
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    return encoded if len(encoded) <= _LIMIT else None


def assess_supplemental_rollup(facts, disposition, *, now_epoch_seconds):
    """Assess trusted-source disposition against bounded facts; perform no I/O.

    None, an empty dict or an unrecognized schema denotes an unknown source
    disposition. Recognized but malformed records are invalid_disposition.
    The empty shipped registry is deliberately not an admission mechanism.
    """
    reasons = []
    facts_bytes = _canonical(facts) if _facts(facts) else None
    disposition_valid = _disposition(disposition)
    if disposition_valid:
        disposition_valid = _canonical(disposition) is not None
    if not disposition_valid:
        unknown = (disposition is None or (type(disposition) is dict and not disposition))
        if (type(disposition) is dict
                and all(type(key) is str for key in disposition)
                and type(disposition.get("schema_version")) is str
                and disposition["schema_version"] != _DISPOSITION_SCHEMA):
            unknown = True
        reasons.append("unknown_case" if unknown else "invalid_disposition")
    if facts_bytes is None:
        reasons.append("invalid_facts")
    case_id = disposition["binding"]["case_id"] if disposition_valid else None
    facts_sha256 = hashlib.sha256(facts_bytes).hexdigest() if facts_bytes is not None else None

    if not reasons:
        binding = facts["binding"]
        goal = facts["goal_review"]
        conditions = (
            (binding == disposition["binding"], "binding_mismatch"),
            (facts["work_item_state"] == "blocked", "wrong_item_state"),
            (facts["failed_role"] == "evidence-rollup", "wrong_failed_role"),
            (facts["failed_result_status"] == "blocked", "wrong_failed_result_status"),
            (facts["handoff_consumed"], "unconsumed_handoff"),
            (facts["rework_count"] == 1, "rework_count_mismatch"),
            (not facts["pending_handoff"], "pending_handoff"),
            (not facts["process_uncertainty"], "process_uncertainty"),
            (facts["supplemental_count"] == 0, "supplemental_already_used"),
            (facts["requested_operator_owner"] == disposition["binding"]["operator_owner"]
             and facts["requested_worker_thread_id"] == disposition["binding"]["worker_thread_id"],
             "owner_mismatch"),
            (facts["failure_kind"] in _HELPER_FAILURES
             and facts["failure_kind"] == disposition["failure_kind"], "not_helper_failure"),
            (all(role["status"] == "complete" and role["outputs_complete"]
                 and not role["contract_issues"] for role in facts["prior_roles"].values()),
             "prior_roles_not_complete"),
            (goal["verdict"] == "pass" and goal["reason_nonempty"] and goal["evidence_nonempty"],
             "goal_not_pass"),
            (goal["context_sha256"] == binding["context_sha256"]
             and goal["contract_sha256"] == binding["contract_sha256"], "goal_binding_mismatch"),
            (_integer(now_epoch_seconds)
             and facts["started_epoch_seconds"] <= now_epoch_seconds < facts["deadline_epoch_seconds"]
             and 0 < facts["deadline_epoch_seconds"] - facts["started_epoch_seconds"] <= 900,
             "budget_invalid_or_expired"),
        )
        reasons.extend(reason for passed, reason in conditions if not passed)
    return {"schema_version": _ASSESSMENT_SCHEMA,
            "status": "refused" if reasons else "eligible",
            "reason_codes": sorted(set(reasons)),
            "facts_sha256": facts_sha256, "case_id": case_id}
