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
REVIEWED_POLICY_ID = "local-reviewed-unit-v2"
SOURCE_REVIEWED_POLICY_ID = "local-source-reviewed-unit-v3"
REVIEWED_FIELDS = {"implementation_model", "review_model", "sizing_review"}
IMPLEMENTATION_MODELS = {"gpt-6-luna": "medium", "gpt-6.1-sol": "high", "gpt-6.1-terra": "high"}
REVIEW_MODELS = {"gpt-6.1-sol": "high", "gpt-6.1-terra": "high"}
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


# Source-owned dispositions, never loaded from intake, environment or a task path.
# Each entry freezes the complete reviewed semantics. Only checkout path/revision
# and the fresh sizing review may vary; their full values remain bound by the
# ordinary sizing subject and are verified again by the supervised handoff.
# No record admits new effects, grants build approval or changes a runtime route.
# Evidence paths resolve in the reviewed engineering workspace, not in the runtime.
_ENGINEERING_UNIT_REVIEWS_V3 = (
    MappingProxyType({
        "artifact": ".automation/atlasmemory-tools/dispatch-remediation/security/semantic-review.json",
        "sha256": "1baf495a05a922612d8ec7f78dcad8eac7e8900342d454ad2f9042c98bc2e80b",
    }),
    MappingProxyType({
        "artifact": ".automation/atlasmemory-tools/dispatch-remediation/goal-review/semantic-dispositions-19.json",
        "sha256": "c83b1c272cd180627358ee5d37c4ba5db31a84f75061d0e7b5a48cbea030a98e",
    }),
    MappingProxyType({
        "artifact": ".automation/atlasmemory-tools/dispatch-remediation/security/final-context-attestation.json",
        "sha256": "02763e1231463ca5f83483058d9b26c9f1e3f60ab4e2502a09b73ad38d636a88",
    }),
    MappingProxyType({
        "artifact": ".automation/atlasmemory-tools/dispatch-remediation/goal-review/final-context-attestation.json",
        "sha256": "f11c84d3d1ada8494e1a2c3f7edcd8d5197723aba5099fade03546698572d175",
    }),
)
SOURCE_REVIEWED_UNITS_V3 = MappingProxyType({
    "engineering-mp12/M12-B01": MappingProxyType({
        "semantic_context_sha256": "526b7c12ae8567c008d9ffdc6341bfe2038d9ab69a248e9b538367f5efd23f59",
        "complexity_flags": ('new_dependency_or_service',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-B03": MappingProxyType({
        "semantic_context_sha256": "2c114c9f928cbf01b0a94018a2fb8a5ad9b690749df86e49aad57e059501ef46",
        "complexity_flags": ('security_or_authority',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-B04": MappingProxyType({
        "semantic_context_sha256": "93ab734e1c7ecbeb6d51216a0898568af34cc67bc5c162110a661e25a0bf8d93",
        "complexity_flags": ('cross_component_protocol',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-B06": MappingProxyType({
        "semantic_context_sha256": "101fadd2a1530cd63a2008b0fff610c7ae12896a92bdbedb3286f78d9909f9c4",
        "complexity_flags": ('cross_component_protocol',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-C03": MappingProxyType({
        "semantic_context_sha256": "eb6b390f1375c2017a5bb05c43ebb515201a3eab2ef552e5f770fa0edb720a0d",
        "complexity_flags": ('security_or_authority',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-C04": MappingProxyType({
        "semantic_context_sha256": "de42402e9554f709a66238ea5dc523b4907bf2d93a6f6206b2430d5c8b8d0b3e",
        "complexity_flags": ('cross_component_protocol',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-C08": MappingProxyType({
        "semantic_context_sha256": "043bcf13169ae2594cb403ee98258fdbf8fe471225f475d163c344603c7ba1e3",
        "complexity_flags": ('cross_component_protocol',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-C06": MappingProxyType({
        "semantic_context_sha256": "da9720cc54a8abe2d652ff61cc99c30c1d47a0895cba9e91a5639d26143cc2bc",
        "complexity_flags": ('security_or_authority',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-P01": MappingProxyType({
        "semantic_context_sha256": "dff16d84ef9f326e0a99fedc588c58d4ffb139c7d23b74d0a83c686cb2503c65",
        "complexity_flags": ('migration',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-P02": MappingProxyType({
        "semantic_context_sha256": "68b21799647a17d17862ad74f150bdde65922e4a6c2dfe5c18d247721beadbbf",
        "complexity_flags": ('migration',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-P03": MappingProxyType({
        "semantic_context_sha256": "b5c4cbe7390dea2f3fb674e61873398012cc453c19b695a33126a2b3ab9cf934",
        "complexity_flags": ('security_or_authority',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-P06": MappingProxyType({
        "semantic_context_sha256": "acd0425b60bd5179257024318baf4dae51d25236ff7aa9bd62663193dff48673",
        "complexity_flags": ('security_or_authority',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-P07": MappingProxyType({
        "semantic_context_sha256": "dcbe1a6fda3d1a8c887e3d699d42285afba8155307c486a7d375c7658b728299",
        "complexity_flags": ('security_or_authority',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-P08": MappingProxyType({
        "semantic_context_sha256": "8bdb1c3ed9cc1bc9288d36220baa47eab468c2b17357ecfe916e7a88cb7834ac",
        "complexity_flags": ('migration',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-E01": MappingProxyType({
        "semantic_context_sha256": "571f18e30ad07fdf6b1c6bb5c7033f8ada49cd0bda52c432524c67df7eefa2fd",
        "complexity_flags": ('security_or_authority',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-E02": MappingProxyType({
        "semantic_context_sha256": "58db003e6894760dffafcc7611bec9eaa4d399c82768065354768fb8ffdae9fa",
        "complexity_flags": ('cross_component_protocol',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-E03": MappingProxyType({
        "semantic_context_sha256": "b3f0a04d151a617e2ebc74edd2ee037fa8cfec6f8c4aa9130983d831058fc058",
        "complexity_flags": ('cross_component_protocol',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-Q01": MappingProxyType({
        "semantic_context_sha256": "ea8f280ab2e145632f7f961adccd6232d49f4dfe61fc60feab11371c1b5f1153",
        "complexity_flags": ('cross_component_protocol',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
    "engineering-mp12/M12-B05": MappingProxyType({
        "semantic_context_sha256": "47c4f956e23c58cbc3900a97dcf1b80bbdd6b880a6993b4fe31f5a63a00e3d18",
        "complexity_flags": ('cross_component_protocol',),
        "review_evidence": _ENGINEERING_UNIT_REVIEWS_V3,
    }),
})



# A separately reviewed, source-owned bounded repair disposition. This does not
# remove history from semantic_subject_sha256 or from the fresh sizing subject.
SOURCE_REVIEWED_REWORK_V1 = MappingProxyType({
    "max_reworks": 1,
    "review_evidence": (
        MappingProxyType({"artifact": ".automation/atlasmemory-tools/launch-readiness/security/source-rework-design-review.json",
                          "sha256": "cc085626ea16eff8d1e7aaae733a1ac7f646b244780f8674f885d01d8dd32d1c"}),
        MappingProxyType({"artifact": ".automation/atlasmemory-tools/launch-readiness/goal-review/source-rework-design-review.json",
                          "sha256": "e0c9cea96db9c8ab3f30339174e53ee1ead32ec8e75ac0b21e30ccf0e9b50119"}),
    ),
})


def _digest_string(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _source_reviewed_rework(context: dict[str, Any], record: Any) -> bool:
    """Validate the maintained projection's proof before comparing base semantics.

    qualify is a pure predicate, not receipt authentication. work_item_context
    constructs the receipt from native accepted history; clean intake cannot
    supply that history. The actual complete attempt remains in the packet and
    in its full-context sizing review.
    """
    attempt = context.get("rework")
    if (SOURCE_REVIEWED_REWORK_V1["max_reworks"] != 1 or not isinstance(attempt, dict)
            or set(attempt) != {"reason", "evidence", "prior_goal_review", "native_rework_receipt"}):
        return False
    review = attempt.get("prior_goal_review")
    receipt = attempt.get("native_rework_receipt")
    if (not isinstance(attempt["reason"], str) or not attempt["reason"].strip()
            or not isinstance(attempt["evidence"], list) or not attempt["evidence"]
            or any(not isinstance(x, str) or not x.strip() for x in attempt["evidence"])
            or not isinstance(review, dict) or set(review) != {"verdict", "reason", "evidence"}
            or not isinstance(review["verdict"], str) or review["verdict"] not in {"fail", "inconclusive"}
            or not isinstance(review["reason"], str) or not review["reason"].strip()
            or not isinstance(review["evidence"], list) or not review["evidence"]
            or any(not isinstance(x, str) or not x.strip() for x in review["evidence"])):
        return False
    fields = {"schema", "work_item_id", "rework_count", "prior_handoff_id",
              "prior_result_sha256", "prior_context_sha256", "prior_goal_context_sha256", "prior_semantic_sha256",
              "prior_handoff_contract_sha256", "prior_goal_contract_sha256"}
    if (not isinstance(receipt, dict) or set(receipt) != fields
            or receipt["schema"] != "source-reviewed-native-rework.v1"
            or type(receipt["rework_count"]) is not int or receipt["rework_count"] != 1
            or receipt["work_item_id"] != context.get("work_item_id")
            or not isinstance(receipt["prior_handoff_id"], str) or not receipt["prior_handoff_id"].strip()
            or any(not _digest_string(receipt[field]) for field in fields if field.endswith("sha256"))
            or receipt["prior_semantic_sha256"] != record["semantic_context_sha256"]):
        return False
    base = dict(context)
    base.pop("rework")  # Only the audited native envelope, never arbitrary fields.
    return semantic_subject_sha256(base) == record["semantic_context_sha256"]


def semantic_subject_sha256(context: dict[str, Any]) -> str:
    """Hash complete semantics, excluding only late-bound execution identity/review."""
    if not isinstance(context, dict) or not isinstance(context.get("local_execution_v1"), dict):
        raise ValueError("work-item context and local_execution_v1 must be objects")
    subject = dict(context)
    subject.pop("execution_repo", None)
    subject.pop("base_branch", None)
    contract = dict(context["local_execution_v1"])
    contract.pop("sizing_review", None)
    subject["local_execution_v1"] = contract
    try:
        encoded = json.dumps(subject, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("work-item context must be canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _source_reviewed_unit(context: dict[str, Any]) -> tuple[Any, bool]:
    package_id = context.get("package_id")
    record = SOURCE_REVIEWED_UNITS_V3.get(package_id) if isinstance(package_id, str) else None
    if record is None:
        return None, False
    try:
        exact = (semantic_subject_sha256(context) == record["semantic_context_sha256"]
                 if "rework" not in context else _source_reviewed_rework(context, record))
    except ValueError:
        return record, False
    contract = context.get("local_execution_v1")
    path, revision = context.get("execution_repo"), context.get("base_branch")
    full_revision = (isinstance(revision, str) and len(revision) in (40, 64)
                     and all(char in "0123456789abcdef" for char in revision))
    # No filesystem discovery here. Actual checkout root and HEAD are checked
    # independently by prepare_handoff before a role can be dispatched.
    absolute_path = (isinstance(path, str) and path.startswith("/") and not path.startswith("//")
                     and not any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in path)
                     and str(PurePosixPath(path)) == path
                     and ".." not in PurePosixPath(path).parts)
    exact = (exact and full_revision and absolute_path
             and contract.get("complexity_flags") == list(record["complexity_flags"])
             and contract.get("role_purposes") == {
                 role["role_id"]: role["purpose"] for role in _SUPERVISOR_ROLES})
    return record, exact


def sizing_subject_sha256(context: dict[str, Any]) -> str:
    """Hash the complete context except sizing_review; this is not a signature."""
    if not isinstance(context, dict) or not isinstance(context.get("local_execution_v1"), dict):
        raise ValueError("work-item context and local_execution_v1 must be objects")
    subject = dict(context)
    contract = dict(context["local_execution_v1"])
    contract.pop("sizing_review", None)
    subject["local_execution_v1"] = contract
    try:
        encoded = json.dumps(subject, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("work-item context must be canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _validate_sizing_review(context: dict[str, Any], contract: dict[str, Any],
                            reasons: list[str]) -> None:
    for field, models in (("implementation_model", IMPLEMENTATION_MODELS),
                          ("review_model", REVIEW_MODELS)):
        value = contract.get(field)
        if not isinstance(value, str) or value not in models:
            reasons.append(f"{field} must select a supported model")
    review = contract.get("sizing_review")
    if not isinstance(review, dict) or set(review) != {"reviewer", "rationale", "subject_sha256"}:
        reasons.append("sizing_review must contain exactly reviewer, rationale, and subject_sha256")
        return
    for field in ("reviewer", "rationale"):
        value = review[field]
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"sizing_review {field} must be a nonblank string")
        elif field == "rationale" and len(value.strip()) < 12:
            reasons.append("sizing_review rationale must describe the task-specific sizing decision")
    try:
        digest = sizing_subject_sha256(context)
    except ValueError:
        reasons.append("sizing_review subject must be canonical JSON")
        return
    if not isinstance(review["subject_sha256"], str) or review["subject_sha256"] != digest:
        reasons.append("sizing_review subject_sha256 does not match the work-item context")


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

    policy = contract.get("policy_id")
    is_v3 = policy == SOURCE_REVIEWED_POLICY_ID
    is_v2 = isinstance(policy, str) and policy in {REVIEWED_POLICY_ID, SOURCE_REVIEWED_POLICY_ID}
    source_record, source_match = _source_reviewed_unit(context) if is_v3 else (None, False)
    if is_v3 and not source_match:
        reasons.append("source-reviewed unit does not match frozen semantics and execution identity")
    fields = CONTRACT_FIELDS | REVIEWED_FIELDS if is_v2 else CONTRACT_FIELDS
    unknown = sorted((str(key) for key in set(contract).difference(fields)))
    missing = sorted(fields.difference(contract))
    if unknown:
        reasons.append("unknown local_execution_v1 field(s): " + ", ".join(str(key) for key in unknown))
    if missing:
        reasons.append("missing local_execution_v1 field(s): " + ", ".join(missing))
    if not isinstance(policy, str) or policy not in {POLICY_ID, REVIEWED_POLICY_ID, SOURCE_REVIEWED_POLICY_ID}:
        reasons.append(f"unsupported policy_id; expected {POLICY_ID}, {REVIEWED_POLICY_ID} or {SOURCE_REVIEWED_POLICY_ID}")
    if is_v2:
        _validate_sizing_review(context, contract, reasons)

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
    records = _role_records(roles, reasons, strict_aliases=reviewed_match or is_v3)
    if roles is None:
        if is_v3:
            records = [{"role_id": role["role_id"], "goal_gate": role["goal_gate"]}
                       for role in _SUPERVISOR_ROLES]
        elif reviewed_match:
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
    if is_v3 and roles is not None:
        admitted_roles = {(role["role_id"], role["goal_gate"]) for role in _SUPERVISOR_ROLES}
        if any((record["role_id"], record["goal_gate"]) not in admitted_roles
               or record["raw_role_id"] != record["role_id"]
               or not record["goal_gate_present"] for record in records):
            reasons.append("selected roles must be an exact subset of the source-reviewed unit roles")
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
            elif is_v2:
                model = contract.get("implementation_model")
                reasoning = IMPLEMENTATION_MODELS.get(model, "") if isinstance(model, str) else ""
                route_reason = "bounded coding or validation work uses the reviewed implementation route"
            else:
                model, reasoning = "gpt-6-luna", "medium"
                route_reason = "bounded coding or validation work uses the fixed local unit route"
        else:
            model = contract.get("review_model") if is_v2 else "gpt-6.1-sol"
            reasoning = REVIEW_MODELS.get(model, "") if isinstance(model, str) else ""
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
    v2_full_coding = is_v2 and any(p in {"implementation", "validation"} for p in role_purposes.values())
    coding_validation_needed = coding_count > 0 or reviewed_match or v2_full_coding
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
    full_packet_coding = reviewed_match or v2_full_coding
    counts = {
        "roles": len(records), "coding_or_validation_roles": coding_count,
        "write_scope_files": len(paths) if paths is not None else None,
        "acceptance_criteria": len(criteria_values) if criteria_values is not None else None,
        "changed_interfaces": len(interfaces) if interfaces is not None else None,
        "unresolved_questions": len(questions) if questions is not None else None,
        "complexity_flags": len(flags) if flags is not None else None,
    }
    if reasons:
        return {"status": "blocked", "policy_id": policy if isinstance(policy, str) and policy in (POLICY_ID, REVIEWED_POLICY_ID, SOURCE_REVIEWED_POLICY_ID) else None, "policy_version": 3 if is_v3 else 2 if is_v2 else POLICY_VERSION,
                "reasons": reasons, "assignments": {}, "observed_counts": counts}

    budget_coding = full_packet_coding or coding_count > 0
    oversized = budget_coding and bool(paths is not None and len(paths) > 4)
    oversized = oversized or budget_coding and bool(criteria_values is not None and len(criteria_values) > 3)
    oversized = oversized or budget_coding and bool(interfaces is not None and len(interfaces) > 1)
    needs_decomposition = (coding_count > 0 or full_packet_coding) and bool(questions or (flags and not (reviewed_match or source_match)))
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
    result = {"status": status, "policy_id": policy, "policy_version": 3 if is_v3 else 2 if is_v2 else POLICY_VERSION,
              "reasons": reasons, "assignments": permitted,
              "observed_counts": counts}
    if status == "qualified" and source_match:
        result["source_reviewed_admission"] = {
            "package_id": context["package_id"],
            "semantic_context_sha256": source_record["semantic_context_sha256"],
            "sizing_subject_sha256": sizing_subject_sha256(context),
            "complexity_flags": list(source_record["complexity_flags"]),
            "review_evidence": [dict(evidence) for evidence in source_record["review_evidence"]],
            "authority": "Sizing disposition only; existing effect and dispatch controls still apply.",
        }
        if "rework" in context:
            result["source_reviewed_admission"]["bounded_rework"] = {
                "attempt_semantic_sha256": semantic_subject_sha256(context),
                "native_rework_receipt": dict(context["rework"]["native_rework_receipt"]),
                "review_evidence": [dict(e) for e in SOURCE_REVIEWED_REWORK_V1["review_evidence"]],
            }
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
    permitted_decomposition = (result.get("status") == "decomposition_required"
                               and assignment is not None
                               and assignment.get("purpose") == "decomposition")
    if (result.get("status") != "qualified" and not permitted_decomposition) or assignment is None:
        detail = "; ".join(result.get("reasons") or []) or result.get("status", "unqualified")
        raise ValueError(f"role {role_id} has no qualified local assignment: {detail}")
    return dict(assignment)
