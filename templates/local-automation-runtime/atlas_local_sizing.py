"""Deterministic, opt-in local work sizing and fixed role routing.

File scope uses a conservative path rule: paths need an extension, except the
conventional extensionless files and explicitly maintained extensionless paths
listed below. The helper does not inspect a checkout to guess whether a path
names a file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any


POLICY_ID = "local-luna-unit-v1"
POLICY_VERSION = 1
CONTRACT_FIELDS = {
    "policy_id",
    "role_purposes",
    "changed_interfaces",
    "unresolved_questions",
    "complexity_flags",
}
PURPOSES = {"implementation", "validation", "decomposition", "review", "goal-review"}
COMPLEXITY_FLAGS = {
    "security_or_authority",
    "migration",
    "new_dependency_or_service",
    "cross_component_protocol",
}
EXTENSIONLESS_FILES = {"Makefile", "LICENSE", "Dockerfile"}
MAINTAINED_EXTENSIONLESS_PATHS = {
    "templates/local-automation-runtime/atlas-agent-orchestrator",
}
FIXED_PURPOSES = {
    "implementation": "implementation",
    "test-runner": "validation",
    "local-validation": "validation",
    "deployed-validation": "validation",
    "test-planning": "decomposition",
    "validation": "decomposition",
    "architecture": "decomposition",
    "auth": "decomposition",
    "security": "decomposition",
    "data-models": "decomposition",
    "data-contracts": "decomposition",
    "scaling": "decomposition",
    "runtime-operations": "decomposition",
    "product-semantics": "decomposition",
    "code-review": "review",
    "security-review": "review",
    "evidence-rollup": "review",
    "review-rollup": "review",
    "validation-rollup": "review",
    "rollup-editor": "review",
    "semantic-alignment": "goal-review",
    "semantic-review": "goal-review",
    "goal-review": "goal-review",
}

_SUPERVISOR_ROLES = tuple(
    MappingProxyType(record)
    for record in (
        {"role_id": "implementation", "purpose": "implementation", "goal_gate": False},
        {"role_id": "test-runner", "purpose": "validation", "goal_gate": False},
        {"role_id": "code-review", "purpose": "review", "goal_gate": False},
        {"role_id": "semantic-alignment", "purpose": "goal-review", "goal_gate": True},
        {"role_id": "evidence-rollup", "purpose": "review", "goal_gate": False},
    )
)
_SUPERVISOR_EVIDENCE = (
    MappingProxyType({
        "artifact": "supervisor-cycle-binding-v2/scoped-amendment-review.json",
        "sha256": "24f69c656f5947c647adf54623a5d5954db0d23c540a0dfea0273609bde76637",
    }),
    MappingProxyType({
        "artifact": "supervisor-cycle-binding-v2/goal-amendment-review.json",
        "sha256": "254da6221e325d64c52c2f3db247aaf1badd49e934fb81d129f2c25de630b5cf",
    }),
    MappingProxyType({
        "artifact": "supervisor-cycle-binding-v2/integration-packets.json",
        "sha256": "889d9a366fc67927c212079d63cb6bcbbc701d3475d3aad5145a648939d053b3",
    }),
    MappingProxyType({
        "artifact": "team-templates/work-item-change-lifecycle.json",
        "sha256": "bc09a362694d095028aa81498ba7a989051944a1a6505144783cfa019253912a",
    }),
)
_SUPERVISOR_PACKAGE_HASH = "58a1d25dc05ca1acdf42c62bb5e5aeb67add2e2a4a9c2f8cfcfc4ee032c15a66"
_SUPERVISOR_FOUNDATION = "6312a26a149a2c1d5d929a6846db6608757a45ea"
_SUPERVISOR_ROUTING_REVISION = "supervisor-stronger-source-v1"
_SUPERVISOR_AMENDMENT_SHA256 = "e89402513a3eb784df37a2cef48fcc7ae62bb00ca919560134e15b3c1cad288b"

# Exact whole-context hashes from the accepted provider.project projections.
# These entries only admit the known complexity disposition; they do not grant
# effect authority or change the fixed routes.
REVIEWED_SUPERVISOR_PACKETS_V1 = MappingProxyType({
    "DU-01-02/A3": MappingProxyType({
        "context_sha256": "9ede9fb812796f6d1a7e7f6e8a0978535df32dc4c8ff4c2b8305a91993887e7c",
        "package_hash": _SUPERVISOR_PACKAGE_HASH,
        "complexity_flags": ("cross_component_protocol",),
        "roles": _SUPERVISOR_ROLES,
        "foundation_source_commit": _SUPERVISOR_FOUNDATION,
        "review_evidence": _SUPERVISOR_EVIDENCE,
    }),
    "DU-01-02/B3": MappingProxyType({
        "context_sha256": "e8923d12f68b8da12ff3d50ae5fa2f7984d1f56f5bebef2459107e41d5f66f53",
        "package_hash": _SUPERVISOR_PACKAGE_HASH,
        "complexity_flags": ("cross_component_protocol", "security_or_authority"),
        "roles": _SUPERVISOR_ROLES,
        "foundation_source_commit": _SUPERVISOR_FOUNDATION,
        "review_evidence": _SUPERVISOR_EVIDENCE,
    }),
    "DU-01-02/B4": MappingProxyType({
        "context_sha256": "9328abc5fc9391576f8355b352ee48d4e28903ae456d2791d2989866652ddab0",
        "package_hash": _SUPERVISOR_PACKAGE_HASH,
        "complexity_flags": ("security_or_authority",),
        "roles": _SUPERVISOR_ROLES,
        "foundation_source_commit": _SUPERVISOR_FOUNDATION,
        "review_evidence": _SUPERVISOR_EVIDENCE,
    }),
    "DU-01-02/B5": MappingProxyType({
        "context_sha256": "be9ceaae81454785c853e1ad372d3fae2475c6a500e4c591351fca8bd2996c51",
        "package_hash": _SUPERVISOR_PACKAGE_HASH,
        "complexity_flags": ("cross_component_protocol", "security_or_authority"),
        "roles": _SUPERVISOR_ROLES,
        "foundation_source_commit": _SUPERVISOR_FOUNDATION,
        "review_evidence": _SUPERVISOR_EVIDENCE,
    }),
})


def _reviewed_supervisor_packet(context: dict[str, Any]) -> tuple[Any, bool]:
    package_id = context.get("package_id")
    if not isinstance(package_id, str):
        return None, False
    packet = REVIEWED_SUPERVISOR_PACKETS_V1.get(package_id)
    if packet is None:
        return None, False
    try:
        encoded = json.dumps(
            context, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return packet, False
    context_digest = hashlib.sha256(encoded).hexdigest()
    contract = context.get("local_execution_v1")
    expected_purposes = {
        role["role_id"]: role["purpose"] for role in packet["roles"]
    }
    exact = (
        context_digest == packet["context_sha256"]
        and context.get("package_hash") == packet["package_hash"]
        and isinstance(contract, dict)
        and contract.get("complexity_flags") == list(packet["complexity_flags"])
        and contract.get("role_purposes") == expected_purposes
    )
    return packet, exact


def _strings(value: Any, field: str, reasons: list[str]) -> list[str] | None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        reasons.append(f"{field} must be a list of strings")
        return None
    values = [item.strip() for item in value]
    if any(not item for item in values):
        reasons.append(f"{field} cannot contain blank strings")
    if len(set(values)) != len(values):
        reasons.append(f"{field} cannot contain duplicates")
    return values


def _file_path(value: str) -> bool:
    if value != value.strip() or not value or "\\" in value or value.startswith(("/", "~")):
        return False
    if any(char in value for char in "*?[]{}") or ":" in value:
        return False
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    file_path = PurePosixPath(value)
    return (
        bool(file_path.suffix)
        or file_path.name in EXTENSIONLESS_FILES
        or value in MAINTAINED_EXTENSIONLESS_PATHS
    )


def _role_records(
    roles: list[dict[str, Any]] | None,
    reasons: list[str],
    *,
    strict_aliases: bool = False,
) -> list[dict[str, Any]]:
    if roles is None:
        return []
    if not isinstance(roles, list):
        reasons.append("roles must be a list of role objects")
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for role in roles:
        if not isinstance(role, dict):
            reasons.append("each role must be an object")
            continue
        # Preserve the longstanding key-presence precedence for ordinary work:
        # a present role_id wins even when its value is None or conflicts with id.
        role_id = role.get("role_id", role.get("id"))
        if strict_aliases and "role_id" in role and "id" in role and role["role_id"] != role["id"]:
            reasons.append("role_id and id aliases must agree")
            continue
        if not isinstance(role_id, str) or not role_id.strip():
            reasons.append("each role must have a nonblank role_id or id")
            continue
        original_role_id = role_id
        role_id = role_id.strip()
        if role_id in seen:
            reasons.append(f"duplicate selected role: {role_id}")
            continue
        seen.add(role_id)
        gate = role.get("goal_gate", False)
        if not isinstance(gate, bool):
            reasons.append(f"role {role_id} goal_gate must be boolean")
        records.append({"role_id": role_id, "goal_gate": gate is True,
                         "raw_role_id": original_role_id,
                         "goal_gate_present": "goal_gate" in role})
    return records


def qualify(context: dict[str, Any], roles: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Qualify an opt-in bounded coding packet and assign its fixed model routes."""
    reasons: list[str] = []
    contract = context.get("local_execution_v1") if isinstance(context, dict) else None
    known_packet = (
        REVIEWED_SUPERVISOR_PACKETS_V1.get(context.get("package_id"))
        if isinstance(context, dict) and isinstance(context.get("package_id"), str)
        else None
    )
    if isinstance(context, dict) and "local_execution_v1" not in context and known_packet is None:
        return {
            "status": "legacy", "policy_id": None, "policy_version": POLICY_VERSION,
            "reasons": [], "assignments": {},
            "observed_counts": _empty_counts(),
        }
    if not isinstance(contract, dict):
        return _blocked(["local_execution_v1 must be an object"], contract)

    reviewed_packet, reviewed_match = _reviewed_supervisor_packet(context)
    if known_packet is not None and not reviewed_match:
        return _blocked(["reviewed supervisor packet context does not match its frozen metadata"], contract)
    if reviewed_packet is not None and not reviewed_match:
        reasons.append("reviewed supervisor packet context does not match its frozen metadata")

    unknown = sorted((str(key) for key in set(contract).difference(CONTRACT_FIELDS)))
    missing = sorted(CONTRACT_FIELDS.difference(contract))
    if unknown:
        reasons.append("unknown local_execution_v1 field(s): " + ", ".join(str(key) for key in unknown))
    if missing:
        reasons.append("missing local_execution_v1 field(s): " + ", ".join(missing))
    if contract.get("policy_id") != POLICY_ID or not isinstance(contract.get("policy_id"), str):
        reasons.append(f"unsupported policy_id; expected {POLICY_ID}")

    raw_purposes = contract.get("role_purposes")
    if not isinstance(raw_purposes, dict) or any(
        not isinstance(role_id, str) or not role_id.strip() or not isinstance(purpose, str)
        for role_id, purpose in raw_purposes.items()
    ):
        reasons.append("role_purposes must map nonblank role IDs to purpose strings")
        role_purposes: dict[str, str] = {}
    else:
        role_purposes = {role_id.strip(): purpose for role_id, purpose in raw_purposes.items()}
        if any(purpose not in PURPOSES for purpose in role_purposes.values()):
            reasons.append("role_purposes contains an unknown purpose")
    records = _role_records(roles, reasons, strict_aliases=reviewed_match)
    if roles is None:
        if reviewed_match:
            records = [
                {"role_id": role["role_id"], "goal_gate": role["goal_gate"]}
                for role in reviewed_packet["roles"]
            ]
        else:
            records = [{"role_id": role_id, "goal_gate": False} for role_id in role_purposes]
    elif reviewed_match:
        admitted_roles = {
            (role["role_id"], role["goal_gate"])
            for role in reviewed_packet["roles"]
        }
        if any(
            (record["role_id"], record["goal_gate"]) not in admitted_roles
            or record["raw_role_id"] != record["role_id"]
            or not record["goal_gate_present"]
            for record in records
        ):
            reasons.append("selected roles must be an exact subset of the reviewed supervisor packet roles")
        expected_alias_roles = {r["role_id"] for r in reviewed_packet["roles"]}
        if set(role_purposes) != expected_alias_roles:
            reasons.append("reviewed supervisor packet must retain all five role purposes")
    if not records:
        reasons.append("at least one selected role is required")

    assignments: dict[str, dict[str, str]] = {}
    coding_count = 0
    for record in records:
        role_id = record["role_id"]
        purpose = role_purposes.get(role_id)
        if purpose is None:
            reasons.append(f"role {role_id} has no explicit purpose")
            continue
        if purpose not in PURPOSES:
            reasons.append(f"role {role_id} has unknown purpose")
            continue
        fixed = FIXED_PURPOSES.get(role_id)
        if record["goal_gate"]:
            if fixed and fixed != "goal-review":
                reasons.append(f"role {role_id} cannot be relabeled as a goal gate")
            fixed = "goal-review"
        if fixed and purpose != fixed:
            reasons.append(f"role {role_id} purpose must be {fixed}")
            continue
        if purpose in {"implementation", "validation"}:
            coding_count += 1
            if reviewed_match:
                model, reasoning = "gpt-6.1-sol", "high"
                route_reason = "exact reviewed supervisor packet uses its bounded stronger source route"
            else:
                model, reasoning = "gpt-6-luna", "medium"
                route_reason = "bounded coding or validation work uses the fixed local unit route"
        else:
            model, reasoning = "gpt-6.1-sol", "high"
            route_reason = (
                "decomposition must produce smaller packets without promoting coding"
                if purpose == "decomposition"
                else "review work uses the fixed reasoning route"
            )
        assignments[role_id] = {
            "purpose": purpose, "model": model, "reasoning": reasoning, "reason": route_reason,
        }

    scope = context.get("write_scope") if isinstance(context, dict) else None
    criteria = context.get("acceptance_criteria") if isinstance(context, dict) else None
    interfaces = _strings(contract.get("changed_interfaces"), "changed_interfaces", reasons)
    questions = _strings(contract.get("unresolved_questions"), "unresolved_questions", reasons)
    flags = _strings(contract.get("complexity_flags"), "complexity_flags", reasons)
    paths = _strings(scope, "write_scope", reasons) if scope is not None else None
    criteria_values = _strings(criteria, "acceptance_criteria", reasons) if criteria is not None else None
    coding_validation_needed = coding_count > 0 or reviewed_match
    if coding_validation_needed and scope is None:
        reasons.append("write_scope must explicitly name repository-relative files")
    if coding_validation_needed and criteria is None:
        reasons.append("acceptance_criteria must be explicit")
    if flags is not None and any(flag not in COMPLEXITY_FLAGS for flag in flags):
        reasons.append("complexity_flags contains an unknown flag")
    if coding_validation_needed:
        if paths is not None:
            invalid_paths = [path for path in paths if not _file_path(path)]
            if invalid_paths:
                reasons.append("write_scope entries must be explicit repository-relative file paths: " + ", ".join(invalid_paths))
            if len(paths) < 1:
                reasons.append("coding roles require at least one scoped file")
        if criteria_values is not None:
            substantive = [
                value for value in criteria_values
                if len(value) >= 12 and value.lower() not in {"done", "complete", "tbd", "n/a", "none"}
            ]
            if len(substantive) != len(criteria_values):
                reasons.append("acceptance_criteria must be substantive, nonblank statements")
            if len(criteria_values) < 1:
                reasons.append("coding roles require at least one acceptance criterion")

    # Validate complete reviewed-packet budgets before any caller subset projection.
    full_packet_coding_count = 2 if reviewed_match else coding_count
    full_packet_coding = reviewed_match
    counts = {
        "roles": len(records), "coding_or_validation_roles": coding_count,
        "write_scope_files": len(paths) if paths is not None else None,
        "acceptance_criteria": len(criteria_values) if criteria_values is not None else None,
        "changed_interfaces": len(interfaces) if interfaces is not None else None,
        "unresolved_questions": len(questions) if questions is not None else None,
        "complexity_flags": len(flags) if flags is not None else None,
    }
    if reasons:
        return {"status": "blocked", "policy_id": POLICY_ID if contract.get("policy_id") == POLICY_ID else None, "policy_version": POLICY_VERSION,
                "reasons": reasons, "assignments": {}, "observed_counts": counts}

    budget_coding = full_packet_coding or coding_count > 0
    oversized = budget_coding and bool(paths is not None and len(paths) > 4)
    oversized = oversized or budget_coding and bool(criteria_values is not None and len(criteria_values) > 3)
    oversized = oversized or budget_coding and bool(interfaces is not None and len(interfaces) > 1)
    needs_decomposition = (coding_count > 0 or full_packet_coding) and bool(questions or (flags and not reviewed_match))
    if oversized:
        status = "split_required"
        reasons.append("bounded scope exceeds the local unit policy")
    elif needs_decomposition:
        status = "decomposition_required"
        reasons.append("resolve open questions or complexity before coding or validation")
    else:
        status = "qualified"
        if coding_count == 0 and any(purpose == "decomposition" for purpose in role_purposes.values()):
            reasons.append("decomposition-only assignments must produce smaller packets and stay at decomposition scope")
    permitted = assignments if status == "qualified" else {
        role_id: route for role_id, route in assignments.items() if route["purpose"] == "decomposition"
    } if status == "decomposition_required" else {}
    result = {"status": status, "policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
              "reasons": reasons, "assignments": permitted,
              "observed_counts": counts}
    if status == "qualified" and reviewed_match:
        result["reviewed_supervisor_admission"] = {
            "package_id": context["package_id"],
            "context_sha256": reviewed_packet["context_sha256"],
            "package_hash": reviewed_packet["package_hash"],
            "foundation_source_commit": reviewed_packet["foundation_source_commit"],
            "review_evidence": [dict(evidence) for evidence in reviewed_packet["review_evidence"]],
            "routing_revision": _SUPERVISOR_ROUTING_REVISION,
            "routing_amendment_sha256": _SUPERVISOR_AMENDMENT_SHA256,
            "selected_route": "gpt-6.1-sol/high for implementation and validation",
            "full_packet_counts": {
                "roles": 5, "coding_or_validation_roles": full_packet_coding_count,
                "write_scope_files": len(paths) if paths is not None else None,
                "acceptance_criteria": len(criteria_values) if criteria_values is not None else None,
                "changed_interfaces": len(interfaces) if interfaces is not None else None,
                "unresolved_questions": len(questions) if questions is not None else None,
                "complexity_flags": len(flags) if flags is not None else None,
            },
        }
    return result


def _blocked(reasons: list[str], contract: Any) -> dict[str, Any]:
    policy = contract.get("policy_id") if isinstance(contract, dict) else None
    return {"status": "blocked", "policy_id": POLICY_ID if policy == POLICY_ID else None,
            "policy_version": POLICY_VERSION, "reasons": reasons, "assignments": {},
            "observed_counts": _empty_counts()}


def _empty_counts() -> dict[str, int | None]:
    return {
        "roles": 0, "coding_or_validation_roles": 0, "write_scope_files": None,
        "acceptance_criteria": None, "changed_interfaces": None,
        "unresolved_questions": None, "complexity_flags": None,
    }


def assignment_for_task(task: dict[str, Any]) -> dict[str, str]:
    """Return one role's fixed route from its work-item context or raise."""
    if not isinstance(task, dict):
        raise ValueError("role task must be an object")
    role_id = task.get("role_id", task.get("id"))
    context = task.get("work_item_context", task)
    if not isinstance(role_id, str) or not isinstance(context, dict):
        raise ValueError("role task must include a role_id and work_item_context object")
    whole_packet = qualify(context)
    whole_route = whole_packet.get("assignments", {}).get(role_id)
    if whole_packet.get("status") not in {"qualified", "decomposition_required"} or whole_route is None:
        detail = "; ".join(whole_packet.get("reasons") or []) or whole_packet.get("status", "unqualified")
        raise ValueError(f"role {role_id} has no qualified local assignment: {detail}")
    result = qualify(context, roles=[task])
    assignment = result.get("assignments", {}).get(role_id)
    if result.get("status") != "qualified" or assignment is None:
        detail = "; ".join(result.get("reasons") or []) or result.get("status", "unqualified")
        raise ValueError(f"role {role_id} has no qualified local assignment: {detail}")
    return dict(assignment)
