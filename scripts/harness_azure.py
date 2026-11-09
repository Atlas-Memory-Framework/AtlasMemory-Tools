#!/usr/bin/env python3
"""Inert MCP proposals for the maintained Azure runtime entrypoints.

This bridge describes operations and binds local inputs. It does not authenticate,
run subprocesses, issue authority, or replace the adapter's exact signed grants.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import stat
import sys
from typing import Any
from urllib.parse import urlsplit

sys.dont_write_bytecode = True

from harness_service import (HarnessService, HarnessServiceError, MAX_CODE_BYTES,
                             _blocker, _owned_path, _read_bytes, _unique_object, _invalid_constant)

AZURE_OPERATIONS = (
    "azure-inspect", "azure-worker-preview", "azure-worker", "azure-publish",
    "azure-reconcile-preview", "azure-reconcile",
)
PATH_FIELD = {"type": "string", "minLength": 1, "maxLength": 4096}
ID_FIELD = {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 2**31 - 1}, "minItems": 1, "maxItems": 200}


def _options(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": {
        "max_minutes": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
        **properties,
    }, "required": required or [], "additionalProperties": False}


AZURE_OPTION_SCHEMAS = {
    "azure-inspect": _options({
        "ids": ID_FIELD, "build_ids": ID_FIELD, "live_read": {"type": "boolean", "default": False},
        **{key: PATH_FIELD for key in ("snapshot", "expected_manifest", "supplement", "authority")},
    }),
    "azure-worker-preview": _options({"packet": PATH_FIELD, "routing": PATH_FIELD}, ["packet"]),
    "azure-worker": _options({key: PATH_FIELD for key in ("packet", "authorization", "routing")}, ["packet", "authorization"]),
    "azure-publish": _options({key: PATH_FIELD for key in ("packet", "authorization", "routing", "human_receipts")}, ["packet", "authorization"]),
    "azure-reconcile-preview": _options({"packet": PATH_FIELD}, ["packet"]),
    "azure-reconcile": _options({"packet": PATH_FIELD, "authorization": PATH_FIELD}, ["packet", "authorization"]),
}

REQUIRED_CAPABILITIES = {
    "azure-inspect": ["read"],
    "azure-worker-preview": ["read"],
    "azure-worker": ["read", "local_execute"],
    "azure-publish": ["read", "draft_pr"],
    "azure-reconcile-preview": ["read"],
    "azure-reconcile": ["read", "board_write"],
}
PATH_OPTIONS = frozenset({"packet", "authorization", "routing", "human_receipts", "snapshot", "expected_manifest", "supplement", "authority"})
PRIVILEGED = frozenset({"azure-worker", "azure-publish", "azure-reconcile"})
SAFE_BLOCKER_CODES = frozenset({
    "missing-or-invalid-revision", "unknown-board-state", "missing-or-cross-project-work-item",
    "invalid-work-item-project-identity", "invalid-native-relations", "invalid-native-relation",
    "unresolved-native-dependency", "missing-or-stale-observation", "incomplete-source-read",
    "missing-source-items", "invalid-source-work-item", "duplicate-source-work-item",
    "invalid-or-unresolved-source-state", "inconsistent-native-project-identity",
    "unresolved-dependency-closure", "incomplete-reciprocal-native-dependency",
    "inspection-not-executed", "execution-authority-not-established", "missing-dependency-contract",
    "dependency-contract-not-approved", "dependency-contract-incomplete", "missing-execution-authority",
    "missing-or-invalid-versioned-dependency-contract", "invalid-dependency-contract-edge-list",
    "dependency-contract-identifiers-must-be-namespaced", "dependency-contract-identifiers-must-be-canonical",
    "duplicate-dependency-contract-edges", "dependency-contract-is-not-closed",
    "dependency-contract-approval-not-established", "dependency-contract-node-set-mismatch",
    "dependency-supplement-not-explicitly-approved", "dependency-supplement-outside-contract",
    "dependency-supplement-does-not-match-missing-edges", "native-dependency-graph-incomplete",
    "dependency-contract-drift", "cyclic-dependency-graph", "work-item-not-pending",
})


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def validate_options(operation: str, options: dict[str, Any] | None) -> dict[str, Any]:
    if operation not in AZURE_OPTION_SCHEMAS:
        raise HarnessServiceError("unsupported_operation", "Select one maintained Azure operation; arbitrary commands are forbidden.")
    schema = AZURE_OPTION_SCHEMAS[operation]
    if options is None:
        options = {}
    if not isinstance(options, dict) or set(options) - set(schema["properties"]):
        raise HarnessServiceError("invalid_options", "Azure operation options contain unsupported fields.")
    missing = set(schema["required"]) - set(options)
    if missing:
        raise HarnessServiceError("missing_operation_input", "The Azure operation requires its explicit local input files.", {"fields": sorted(missing)})
    values = {"max_minutes": 10, **options}
    if operation == "azure-inspect":
        values.setdefault("live_read", False)
    for key, value in values.items():
        field = schema["properties"][key]
        if field["type"] == "integer":
            valid = type(value) is int and field["minimum"] <= value <= field["maximum"]
        elif field["type"] == "boolean":
            valid = type(value) is bool
        elif field["type"] == "array":
            valid = (isinstance(value, list) and field["minItems"] <= len(value) <= field["maxItems"]
                     and all(type(item) is int and 1 <= item <= 2**31 - 1 for item in value)
                     and len(value) == len(set(value)))
        else:
            valid = isinstance(value, str) and 1 <= len(value) <= 4096 and "\0" not in value
        if not valid:
            raise HarnessServiceError("invalid_options", "An Azure operation option has an invalid type or exceeds its bound.", {"field": key})
    if operation == "azure-inspect" and values.get("snapshot") and values["live_read"]:
        raise HarnessServiceError("invalid_options", "Choose an offline snapshot or an explicit live read, not both.")
    if operation == "azure-inspect" and "build_ids" in values and not values["live_read"]:
        raise HarnessServiceError("invalid_options", "Build timeline IDs apply only to an explicit live read.")
    return values


def _input_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".json":
        raise HarnessServiceError("unsafe_azure_input", "Azure inputs require explicit absolute non-secret JSON paths without traversal.")
    forbidden = {".azure", ".aws", ".ssh", ".git"}
    if forbidden.intersection(path.parts) or re.search(r"credential|secret|access.?token|auth.?token", path.name, re.I) or (path.name == "auth.json" and ".codex" in path.parts):
        raise HarnessServiceError("unsafe_azure_input", "Credential stores and secret-bearing inputs cannot be supplied to the harness bridge.")
    home_alias = Path(pwd.getpwuid(os.getuid()).pw_dir)
    home = home_alias.resolve(strict=True)
    if home_alias == path or home_alias in path.parents:
        path = home / path.relative_to(home_alias)
    roots = (home, Path("/tmp"))
    boundary = next((root for root in roots if root in path.parents), None)
    if boundary is None:
        raise HarnessServiceError("unsafe_azure_input", "Azure inputs must stay within this identity home or its owned temporary work area.")
    resolved = _owned_path(path, boundary=boundary)
    info = resolved.stat()
    if info.st_nlink != 1 or info.st_mode & 0o022:
        raise HarnessServiceError("unsafe_azure_input", "Azure input files must not be linked or writable by another identity.")
    return resolved


class HarnessAzure:
    def __init__(self, service: HarnessService):
        self.service = service

    def _inputs(self, values: dict[str, Any], blockers: list[dict[str, str]]) -> tuple[dict[str, Any], dict[str, str]]:
        documents: dict[str, Any] = {}
        hashes: dict[str, str] = {}
        for key in sorted(PATH_OPTIONS.intersection(values)):
            try:
                path = _input_path(values[key])
                content = _read_bytes(path)
                try:
                    document = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
                except (ValueError, UnicodeError, RecursionError) as exc:
                    raise HarnessServiceError("invalid_json", "The Azure non-secret JSON input is malformed.") from exc
                if not isinstance(document, dict):
                    raise HarnessServiceError("invalid_json", "The Azure non-secret JSON input must be an object.")
                documents[key] = document
                hashes[str(path)] = _digest(content)
                values[key] = str(path)
            except HarnessServiceError as exc:
                blockers.append(_blocker(exc.code, "An Azure operation input is missing, unsafe, too large or malformed.", "Review the explicit " + key + " input; do not supply credentials or substitute another task."))
        return documents, hashes

    def _code(self, root: Path, blockers: list[dict[str, str]]) -> dict[str, str]:
        from harness_execution import canonical_code_files

        bindings = {}
        canonical = self.service.tools_root / "templates" / "local-automation-runtime"
        for name in canonical_code_files(self.service.tools_root):
            try:
                content = _read_bytes(root / name, boundary=root, max_bytes=MAX_CODE_BYTES)
                expected = _read_bytes(canonical / name, boundary=canonical, max_bytes=MAX_CODE_BYTES)
                info = (root / name).stat()
                bindings[name] = _digest(content)
                if info.st_nlink != 1 or info.st_mode & 0o022:
                    blockers.append(_blocker("unsafe_runtime_code_mode", "Azure runtime code has unsafe links or write permissions.", "Review the owned pinned runtime before starting work."))
                if content != expected:
                    blockers.append(_blocker("runtime_script_drift", "Azure runtime code differs from the canonical source.", "Review and explicitly upgrade the installed runtime; preserve its operator state."))
            except HarnessServiceError:
                blockers.append(_blocker("missing_runtime_script", "Required Azure runtime code is missing or unsafe.", "Provision a reviewed runtime snapshot before using this operation."))
        return bindings

    def prepare(self, runtime_id: str, operation: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        from harness_execution import proposal_digest
        from atlas_runtime_config import ROLES, RuntimeConfigError, load_runtime_config

        values = validate_options(operation, options)
        runtime = self.service.get_runtime(runtime_id)
        if runtime["provider"] != "azure-devops":
            raise HarnessServiceError("provider_mismatch", "Azure operations require a registered Azure DevOps runtime.")
        root = Path(runtime["runtime_dir"])
        config_path = _input_path(runtime["config"])
        try:
            config = load_runtime_config(config_path, runtime_dir=root)
        except (RuntimeConfigError, OSError, ValueError, TypeError, RecursionError) as exc:
            raise HarnessServiceError("invalid_config", "The Azure remote configuration changed or became invalid; inspect and prepare again.") from exc
        repository = config.repository
        blockers: list[dict[str, str]] = []
        required = list(REQUIRED_CAPABILITIES[operation])
        for capability in required:
            if capability not in config.capabilities:
                blockers.append(_blocker("missing_capability", "The Azure remote profile does not enable " + capability + ".", "Review the permanent remote profile; capability availability is separate from authorization."))
        documents, input_hashes = self._inputs(values, blockers)
        script_hashes = self._code(root, blockers)
        task_summary: dict[str, Any] = {}

        if operation in {"azure-worker-preview", "azure-worker", "azure-publish"}:
            if set(config.roles) != set(ROLES):
                blockers.append(_blocker("missing_worker_models", "Azure worker operations require explicit settings for all maintained worker roles.", "Configure reviewed worker model/reasoning settings; a read-only remote needs no model settings."))
            if "packet" in documents:
                try:
                    from atlas_azure_worker import digest as packet_digest, validate_packet

                    workspace = validate_packet(config, documents["packet"])
                    task_summary = {key: documents["packet"][key] for key in ("id", "revision", "base_commit", "branch", "write_scope")}
                    task_summary["checkout"] = str(workspace)
                    task_summary["expected_evidence_directory"] = str(workspace / ".atlas-worker" / packet_digest(documents["packet"]))
                except (RuntimeError, RuntimeConfigError, KeyError, TypeError, ValueError):
                    blockers.append(_blocker("invalid_worker_packet", "The Azure worker packet does not match its repository, base, isolated worktree, scope or acceptance contract.", "Prepare a complete reviewed packet for this exact registered remote."))
        elif operation in {"azure-reconcile-preview", "azure-reconcile"} and "packet" in documents:
            try:
                from atlas_azure_reconcile import validate_proposal

                validate_proposal(documents["packet"])
                if documents["packet"].get("organization") != repository["organization"] or documents["packet"].get("project") != repository["project"]:
                    raise ValueError
                task_summary = {"proposal_sha256": proposal_digest(documents["packet"]), "organization": repository["organization"], "project": repository["project"]}
            except (ValueError, RuntimeError, KeyError, TypeError):
                blockers.append(_blocker("invalid_board_proposal", "The reviewed Board proposal is malformed or targets another Azure namespace.", "Prepare an exact Board proposal for the selected organization and project."))

        if operation == "azure-inspect":
            if not values.get("ids") and "expected_manifest" not in documents:
                blockers.append(_blocker("missing_inspection_scope", "Azure inspection needs explicit work-item IDs or a versioned dependency manifest.", "Supply a bounded ids list or the exact expected_manifest input."))
            for key in ("expected_manifest", "supplement", "authority"):
                if key in documents and any(documents[key].get(field) not in (None, repository[field]) for field in ("organization", "project")):
                    blockers.append(_blocker("azure_namespace_mismatch", "An Azure inspection input targets another organization or project.", "Use evidence belonging to the selected remote."))

        public_trust = root / "authority" / "trust.json"
        trust_binding = None
        if operation in PRIVILEGED:
            if public_trust.exists() or public_trust.is_symlink():
                try:
                    trust_binding = _digest(_read_bytes(public_trust, boundary=root))
                except HarnessServiceError:
                    blockers.append(_blocker("unsafe_authority_registry", "The fixed public authority registry is unavailable or unsafe.", "Use the existing operator enrollment workflow; the MCP bridge never creates trust or keys."))
            else:
                blockers.append(_blocker("missing_authority_registry", "The fixed public authority registry has not been enrolled for this runtime.", "Complete the existing operator authority enrollment before cloud writes or model execution."))
        observation = self.service.inspect(runtime_id)
        unresolved = [item for item in observation.get("blockers", []) if item.get("code") != "no_runtime_evidence"]
        blockers.extend(unresolved)

        if operation == "azure-inspect":
            entrypoint = "atlas-agent-azure-inspect"
        elif operation.startswith("azure-reconcile"):
            entrypoint = "atlas-agent-azure-reconcile"
        else:
            entrypoint = "atlas-agent-azure-worker"
        argv = [sys.executable, str(root / entrypoint), "--config", str(config_path), "--runtime-dir", str(root)]
        for key in sorted(PATH_OPTIONS.intersection(values)):
            argv += ["--" + key.replace("_", "-"), values[key]]
        if operation == "azure-inspect":
            if values.get("ids"):
                argv += ["--ids", ",".join(map(str, values["ids"]))]
            if values.get("build_ids"):
                argv += ["--build-ids", ",".join(map(str, values["build_ids"]))]
            argv += ["--live-read"] if values["live_read"] else [] if values.get("snapshot") else ["--dry-run"]
            argv += ["--json"]
        else:
            argv += [{"azure-worker-preview": "--dry-run", "azure-worker": "--execute", "azure-publish": "--publish", "azure-reconcile-preview": "--dry-run", "azure-reconcile": "--apply"}[operation]]
        effects = {
            "provider_read": operation in PRIVILEGED or (operation == "azure-inspect" and values["live_read"]),
            "local_runtime_artifacts": True, "worker_execution": operation == "azure-worker",
            "draft_pr_publication": operation == "azure-publish", "board_updates": operation == "azure-reconcile",
            "agent_coordination": "local", "remote_comments": False, "merge": False,
            "deployment": False, "protected_branch_push": False,
        }
        proposal = {
            "runtime_id": runtime_id, "operation": operation, "provider": "azure-devops", "runtime_dir": str(root),
            "options": values, "argv": argv, "cwd": str(root), "targets": [repository["url"]],
            "remote": {key: repository[key] for key in ("organization", "project", "name", "base_branch")},
            "models": config.report().get("models", {}),
            "task": task_summary, "effects": effects, "required_capabilities": required,
            "budgets": {"max_minutes": values["max_minutes"]},
            "bindings": {"registry_sha256": _digest(_read_bytes(self.service.registry)),
                         "nonsecret_config_sha256": _digest(_read_bytes(config_path)),
                         "input_files": input_hashes, "scripts": script_hashes, "public_trust_sha256": trust_binding},
            "required_authorization": {
                "granted": False, "source": "host_tool_approval",
                "native_signed_grant_required": operation in PRIVILEGED,
                "native_grant_verified": False,
                "message": "A prepared proposal or reference grants no consent. The maintained Azure adapter independently verifies exact signed grants before model execution, draft publication or Board writes.",
            },
            "blockers": blockers,
            "limitations": [
                "Preparation reads bounded non-secret files only; it authenticates no provider and starts no child process.",
                "Live Azure access uses the current identity's existing Azure CLI authentication when the operation is explicitly started.",
                "Signed grant validity, current work-item revisions, dependency evidence and publication candidate evidence are independently rechecked by the maintained adapter before effects.",
                "Process completion is not accepted task completion; local validation and independent review remain required.",
            ],
        }
        digest = proposal_digest(proposal)
        return self.service._envelope(
            status="blocked" if blockers else "prepared", proposal_id=digest, proposal=proposal, blockers=blockers,
            next_actions=observation.get("next_actions", []) if unresolved else
            [{"operation": "resolve_azure_inputs", "runtime_id": runtime_id}] if blockers else
            [{"operation": "authorize_start", "runtime_id": runtime_id, "proposal_id": digest}],
            validation={"status": "unverified", "message": "This is an inert, effect-bound Azure proposal, not provider connectivity or task acceptance evidence."},
        )


def project_result(proposal: dict[str, Any], raw_output: bytes) -> dict[str, Any]:
    """Project bounded adapter JSON without returning logs or untrusted prose."""
    operation = proposal.get("operation")
    result: dict[str, Any] = {"schema_version": "atlas-tools.azure-result.v1",
                              "operation": operation if isinstance(operation, str) and operation in AZURE_OPERATIONS else None,
                              "status": "unavailable", "accepted_progress": False, "completion": False}
    if operation not in AZURE_OPERATIONS or not isinstance(raw_output, bytes) or len(raw_output) > 262_144:
        return {**result, "failure_code": "unavailable_backend_result"}

    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError
            value[key] = item
        return value

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError
        return number

    try:
        body = json.loads(raw_output, object_pairs_hook=pairs, parse_float=finite_float,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        return {**result, "failure_code": "invalid_backend_json"}
    if not isinstance(body, dict):
        return {**result, "failure_code": "invalid_backend_json"}
    if "error" in body or body.get("state") == "blocked" or body.get("mode") == "blocked":
        return {**result, "status": "blocked", "failure_code": "azure_backend_blocked"}
    if operation == "azure-inspect":
        mode = body.get("inspection_mode")
        if not isinstance(mode, str) or mode not in {"dry-run", "offline-snapshot", "live-read-only"}:
            return {**result, "failure_code": "unrecognized_backend_result"}
        result.update(status="observed", inspection_mode=mode)
        for key in ("complete", "dependency_complete"):
            if type(body.get(key)) is bool:
                result[key] = body[key]
        result["board_complete"] = body.get("complete") if type(body.get("complete")) is bool else False
        live_repository_read = mode == "live-read-only" or proposal.get("options", {}).get("live_read") is True
        if live_repository_read:
            try:
                repository = _project_repository_evidence(proposal, body.get("repository_evidence"))
            except (ValueError, TypeError, OverflowError, RecursionError):
                # Complete private measurement also visits discarded fields.
                # A hostile value must never escape as an exception or prose.
                return {"schema_version": "atlas-tools.azure-result.v1", "operation": operation,
                        "status": "unavailable", "accepted_progress": False, "completion": False,
                        "failure_code": "invalid_backend_json"}
            result["repository_evidence"] = repository
            result["repository_checked"] = repository["observed"]
            result["complete"] = result["board_complete"] and repository["complete"]
            result["complete_scope"] = "work_items_and_requested_repository_evidence"
        else:
            result["repository_checked"] = False
            result["complete_scope"] = "work_items_only"
        if type(body.get("eligible_count")) is int and 0 <= body["eligible_count"] <= 100_000:
            result["eligible_count"] = body["eligible_count"]
        remote = proposal.get("remote", {})
        namespace = "azdo:" + str(remote.get("organization", "")) + ":" + str(remote.get("project", "")) + ":"
        items = []
        source_items = body.get("items", [])
        if isinstance(source_items, list):
            result["items_truncated"] = len(source_items) > 32
            for row in source_items[:32]:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not re.fullmatch(re.escape(namespace) + r"[1-9][0-9]*", row["id"]):
                    continue
                item: dict[str, Any] = {"id": row["id"]}
                if type(row.get("revision")) is int and row["revision"] > 0:
                    item["revision"] = row["revision"]
                state = row.get("state")
                if isinstance(state, str) and state.casefold() in {"new", "active", "resolved", "closed", "ready", "done", "blocked", "unknown", "to do", "doing", "committed", "removed", "proposed"}:
                    item["state"] = state
                if type(row.get("eligible")) is bool:
                    item["eligible"] = row["eligible"]
                items.append(item)
        result["items"] = items
        codes = set()
        for value in body.get("blockers", []) if isinstance(body.get("blockers", []), list) else [None]:
            codes.add(value if isinstance(value, str) and value in SAFE_BLOCKER_CODES else "unclassified_backend_blocker")
        result["blocker_codes"] = sorted(codes)
    elif operation.startswith("azure-reconcile"):
        state = body.get("status", body.get("mode"))
        if not isinstance(state, str) or state not in {"preview", "applied", "already_applied", "no_changes", "uncertain_unapplied"}:
            return {**result, "failure_code": "unrecognized_backend_result"}
        result.update(status="observed", backend_state=state)
        packet = body.get("proposal")
        if state == "preview" and isinstance(packet, dict) and isinstance(packet.get("patches"), list):
            result["planned_patch_count"] = len(packet["patches"])
        entries = body.get("items", body.get("entries"))
        if isinstance(entries, list):
            result["observed_entry_count"] = len(entries)
            result["applied_entry_count"] = sum(isinstance(row, dict) and row.get("status") == "applied" for row in entries)
        if type(body.get("proposed_patch_count")) is int and 0 <= body["proposed_patch_count"] <= 100_000:
            result["planned_patch_count"] = body["proposed_patch_count"]
    else:
        state = body.get("state")
        if not isinstance(state, str) or state not in {"preview", "prepared", "pr_open"}:
            return {**result, "failure_code": "unrecognized_backend_result"}
        result.update(status="observed", backend_state=state)
        for key in ("candidate_sha", "base_commit"):
            if isinstance(body.get(key), str) and re.fullmatch(r"[0-9a-f]{40}", body[key]):
                result[key] = body[key]
        for key in ("evidence_sha256", "operation_id"):
            if isinstance(body.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", body[key]):
                result[key] = body[key]
        expected_evidence = proposal.get("task", {}).get("expected_evidence_directory")
        if state == "prepared" and isinstance(expected_evidence, str) and len(expected_evidence) <= 4096:
            expected = Path(expected_evidence)
            root = Path(proposal.get("runtime_dir", "/unavailable"))
            if expected.is_absolute() and ".." not in expected.parts and root in expected.parents:
                result["expected_evidence_directory"] = expected_evidence
        number = body.get("pull_request_id")
        targets = proposal.get("targets")
        target = targets[0] if isinstance(targets, list) and targets else None
        if type(number) is int and 0 < number <= 2**31 - 1 and isinstance(target, str) and len(target) <= 4096:
            parsed = urlsplit(target)
            if parsed.scheme == "https" and parsed.hostname == "dev.azure.com" and not parsed.username and not parsed.query and not parsed.fragment and "/_git/" in parsed.path:
                result["pull_request_id"] = number
                result["pull_request_url"] = target.rstrip("/") + "/pullrequest/" + str(number)
        root = Path(proposal.get("runtime_dir", "/unavailable"))
        for key in ("evidence_dir", "evidence_path"):
            value = body.get(key)
            if isinstance(value, str):
                path = Path(value)
                if path.is_absolute() and ".." not in path.parts and root in path.parents and len(value) <= 4096:
                    result[key] = value
    result["evidence_boundary"] = "Adapter observations and process exit do not establish accepted task progress or independent review."
    return _fit_public_result(result)


def _project_legacy_repository_evidence(proposal: dict[str, Any], evidence: Any) -> dict[str, Any]:
    """Retain typed cloud evidence and explicit projection coverage, never prose."""
    limit = 32
    names = ("base_refs", "pull_requests", "policies", "policy_evaluations", "builds", "timelines")
    result: dict[str, Any] = {"observed": isinstance(evidence, dict), "complete": False,
                              "reported_complete": None, "repository_matches_profile": False,
                              "coverage": {}, "missing_fields": [], "omitted_fields": [],
                              "deployment_authority": False}
    if not isinstance(evidence, dict):
        result["missing_fields"] = ["repository_evidence"]
        result["blocker_codes"] = ["repository_evidence_unavailable"]
        return result
    remote = proposal.get("remote", {})
    configured_name = remote.get("name") if isinstance(remote, dict) else None
    configured_branch = remote.get("base_branch") if isinstance(remote, dict) else None
    repository = evidence.get("repository")
    guid_pattern = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

    def positive(value):
        return type(value) is int and 0 < value <= 2**31 - 1

    def enum(value, choices):
        return isinstance(value, str) and value in choices

    matches = (isinstance(repository, dict) and isinstance(configured_name, str)
               and any(isinstance(repository.get(key), str) and repository[key].casefold() == configured_name.casefold()
                       for key in ("id", "name")))
    if isinstance(configured_name, str) and re.fullmatch(guid_pattern, configured_name):
        matches = isinstance(repository, dict) and isinstance(repository.get("id"), str) and repository["id"].lower() == configured_name.lower()
    result["repository_matches_profile"] = matches
    if not isinstance(repository, dict):
        result["missing_fields"].append("repository")
    elif not matches:
        result["omitted_fields"].append("repository_identity")
    if matches and isinstance(repository.get("id"), str) and re.fullmatch(guid_pattern, repository["id"]):
        result["repository_id"] = repository["id"].lower()
    if type(evidence.get("complete")) is bool:
        result["reported_complete"] = evidence["complete"]
    else:
        result["omitted_fields"].append("complete")
    selected = proposal.get("options", {}).get("build_ids", [])
    explicit_selection = not isinstance(selected, list) or bool(selected)
    selected = sorted({value for value in selected if positive(value)}) if isinstance(selected, list) else []
    selected_ids = set(selected[:limit])
    result["selected_build_ids"] = selected[:limit]
    result["selected_build_ids_truncated"] = len(selected) > limit
    base_name = "refs/heads/" + configured_branch.removeprefix("refs/heads/") if isinstance(configured_branch, str) else None
    rows: dict[str, list[dict[str, Any]]] = {}
    for name in names:
        source = evidence.get(name)
        if not isinstance(source, list):
            result["missing_fields"].append(name)
            result["coverage"][name] = {"reported_count": None, "projected_count": 0, "omitted": False, "truncated": False}
            rows[name] = []
            continue
        relevant = source
        omitted_selection = False
        if explicit_selection and name in {"builds", "timelines"}:
            field = "id" if name == "builds" else "build_id"
            omitted_selection = any(not isinstance(row, dict) or not positive(row.get(field)) for row in source)
            relevant = [row for row in source if isinstance(row, dict) and positive(row.get(field)) and row[field] in selected_ids]
        elif name == "base_refs" and isinstance(base_name, str):
            omitted_selection = any(not isinstance(row, dict) or not isinstance(row.get("name"), str) for row in source)
            relevant = [row for row in source if isinstance(row, dict) and row.get("name") == base_name]
        result["coverage"][name] = {"reported_count": len(source), "scoped_count": len(relevant),
                                     "projected_count": 0, "omitted": omitted_selection, "truncated": len(relevant) > limit}
        rows[name] = relevant[:limit] if matches else []
        if not matches and relevant:
            result["coverage"][name]["omitted"] = True

    def accept(name, row):
        result.setdefault(name, []).append(row)
        result["coverage"][name]["projected_count"] += 1

    def omit(name):
        result["coverage"][name]["omitted"] = True

    for row in rows["base_refs"]:
        if (isinstance(base_name, str) and isinstance(row, dict) and row.get("name") == base_name and
                isinstance(row.get("objectId"), str) and re.fullmatch(r"[0-9a-f]{40}", row["objectId"])):
            accept("base_refs", {"commit_sha": row["objectId"]})
            result["base_commit_sha"] = row["objectId"]
        else:
            omit("base_refs")
    for row in rows["pull_requests"]:
        if isinstance(row, dict) and positive(row.get("pullRequestId")) and enum(row.get("status"), {"active", "abandoned", "completed"}) and type(row.get("isDraft")) is bool:
            accept("pull_requests", {"id": row["pullRequestId"], "status": row["status"], "is_draft": row["isDraft"]})
        else:
            omit("pull_requests")
    pr_ids = {row["id"] for row in result.get("pull_requests", [])}
    for row in rows["policies"]:
        if isinstance(row, dict) and positive(row.get("id")) and type(row.get("isEnabled")) is bool and type(row.get("isBlocking")) is bool:
            accept("policies", {"id": row["id"], "is_enabled": row["isEnabled"], "is_blocking": row["isBlocking"]})
        else:
            omit("policies")
    for row in rows["policy_evaluations"]:
        identifier = row.get("id") if isinstance(row, dict) else None
        if (isinstance(row, dict) and positive(row.get("pull_request_id")) and row["pull_request_id"] in pr_ids and isinstance(identifier, str)
                and re.fullmatch(guid_pattern, identifier)
                and enum(row.get("status"), {"queued", "running", "approved", "rejected", "notApplicable", "broken"})):
            accept("policy_evaluations", {"pull_request_id": row["pull_request_id"], "id": identifier, "status": row["status"]})
        else:
            omit("policy_evaluations")
    for row in rows["builds"]:
        if (isinstance(row, dict) and positive(row.get("id"))
                and enum(row.get("status"), {"none", "inProgress", "completed", "cancelling", "postponed", "notStarted"})
                and (row.get("result") is None or enum(row.get("result"), {"none", "succeeded", "partiallySucceeded", "failed", "canceled"}))):
            summary = {"id": row["id"], "status": row["status"], "result": row.get("result")}
            if isinstance(row.get("sourceVersion"), str) and re.fullmatch(r"[0-9a-f]{40}", row["sourceVersion"]):
                summary["source_commit_sha"] = row["sourceVersion"]
            else:
                omit("builds")
            if row["status"] == "completed" and row.get("result") in {None, "none"}:
                omit("builds")
            accept("builds", summary)
        else:
            omit("builds")
    for row in rows["timelines"]:
        if isinstance(row, dict) and positive(row.get("build_id")) and isinstance(row.get("records"), list):
            records = row["records"]
            recognized = all(isinstance(record, dict) and
                             isinstance(record.get("id"), str) and re.fullmatch(guid_pattern, record["id"]) and
                             enum(record.get("state"), {"pending", "inProgress", "completed"}) and
                             (record.get("result") is None or enum(record.get("result"), {"succeeded", "succeededWithIssues", "failed", "canceled", "skipped", "abandoned"})) and
                             not (record["state"] == "completed" and record.get("result") is None) for record in records)
            accept("timelines", {"build_id": row["build_id"], "record_count": len(records), "states_recognized": recognized})
            if not recognized:
                omit("timelines")
        else:
            omit("timelines")
    for name in names:
        result.setdefault(name, [])
    timeline_scope = evidence.get("timeline_scope")
    if enum(timeline_scope, {"explicit-build-ids", "first-ten-listed-builds"}):
        result["timeline_scope"] = timeline_scope
    else:
        result["omitted_fields"].append("timeline_scope")
    observed_builds = {row["id"] for row in result["builds"]}
    observed_timelines = {row["build_id"] for row in result["timelines"]}
    result["selected_builds_without_metadata"] = sorted(selected_ids - observed_builds)[:limit]
    result["selected_builds_without_timeline"] = sorted(selected_ids - observed_timelines)[:limit]
    codes = set()
    raw_blockers = evidence.get("blockers", [])
    known_codes = {"unknown-or-incomplete-pull-request-state", "unknown-or-incomplete-build-state", "configured-base-ref-not-observed",
                   "pull-request-policy-evidence-budget-exhausted", "pull-request-or-project-identity-missing", "timeline-evidence-budget-exhausted",
                   "selected-build-metadata-unavailable", "selected-build-acquisition-budget-exhausted",
                   "observation-byte-budget-exhausted"}
    for value in raw_blockers if isinstance(raw_blockers, list) else [None]:
        codes.add(value if isinstance(value, str) and value in known_codes else "unclassified_repository_blocker")
    result["blocker_codes"] = sorted(codes)
    result["projection_complete"] = (matches and not result["missing_fields"] and not result["omitted_fields"]
                                     and not any(row["omitted"] or row["truncated"] for row in result["coverage"].values())
                                     and not result["selected_build_ids_truncated"]
                                     and not result["selected_builds_without_metadata"] and not result["selected_builds_without_timeline"]
                                     and "base_commit_sha" in result)
    result["complete"] = result["reported_complete"] is True and result["projection_complete"] and not codes
    return result


_OBSERVATION_CONTRACT = "atlas-tools.azure-observation.v1"
_REPOSITORY_BYTE_LIMIT = 98304
_PUBLIC_BYTE_LIMIT = 196608
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_DIAGNOSTIC_FIELDS = {
    "observation": "contract observed_at repository_id request_ids pr_bindings build_bindings timeline_bindings coverage",
    "pr": "id status is_draft source_commit_sha target_commit_sha merge_commit_sha source_ref_sha256 target_ref_sha256",
    "build": "id status result repository_id definition_id definition_revision source_commit_sha source_ref_sha256 queue_time start_time finish_time",
    "timeline": "build_id records id parent_id parent_resolution type state result attempt identifier_sha256 duplicate_id",
}
_BINDING_CODES = frozenset(prefix + "." + field for prefix, fields in _DIAGNOSTIC_FIELDS.items() for field in fields.split())
_DIAGNOSTIC_KEYS = {"bindings_complete", "binding_missing_fields", "binding_malformed_fields"}
_BUILD_STATES = {"none", "inProgress", "completed", "cancelling", "postponed", "notStarted"}
_BUILD_RESULTS = {"none", "succeeded", "partiallySucceeded", "failed", "canceled"}
_TIMELINE_TYPES = {"Stage", "Phase", "Job", "Task"}
_TIMELINE_STATES = {"pending", "inProgress", "completed"}
_TIMELINE_RESULTS = {"succeeded", "succeededWithIssues", "failed", "canceled", "skipped", "abandoned"}
# Same frozen insertion dates as the accepted selected-build timestamp validator.
_LEAP_DATES = frozenset("1972-06-30 1972-12-31 1973-12-31 1974-12-31 1975-12-31 1976-12-31 1977-12-31 1978-12-31 1979-12-31 1981-06-30 1982-06-30 1983-06-30 1985-06-30 1987-12-31 1989-12-31 1990-12-31 1992-06-30 1993-06-30 1994-06-30 1995-12-31 1997-06-30 1998-12-31 2005-12-31 2008-12-31 2012-06-30 2015-06-30 2016-12-31".split())


def _positive(value):
    return type(value) is int and 1 <= value <= 2147483647


def _count(value):
    return type(value) is int and 0 <= value <= 2147483647


def _hex(value, size):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{" + str(size) + "}", value) is not None


def _guid(value):
    return isinstance(value, str) and _GUID.fullmatch(value) is not None


def _choice(value, choices):
    return isinstance(value, str) and value in choices


def _safe_text(value, maximum):
    if not isinstance(value, str) or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        return False
    try:
        return len(value.encode("utf-8")) <= maximum
    except UnicodeEncodeError:
        return False


def _ref_hash(value):
    if _safe_text(value, 256) and value.startswith("refs/") and len(value) > 5:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    return None


def _timestamp(value):
    if not _safe_text(value, 64) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])", value):
        return False
    try:
        leap = value[17:19] == "60"
        ordinary = value[:17] + "59" + value[19:] if leap else value
        utc = datetime.fromisoformat(ordinary.replace("z", "Z")).astimezone(timezone.utc)
        return not leap or ((utc.hour, utc.minute, utc.second) == (23, 59, 59) and utc.date().isoformat() in _LEAP_DATES)
    except (ValueError, OverflowError):
        return False


class _Binding:
    """Accumulate only fixed codes; supplied malformed data wins over absence."""
    def __init__(self):
        self.missing = set()
        self.malformed = set()

    def field(self, target, key, value, validator, code, required=True, normalize=None):
        if value is None:
            if required:
                self.missing.add(code)
        elif not validator(value):
            self.malformed.add(code)
        else:
            target[key] = normalize(value) if normalize else value

    def diagnostics(self, row, code, prefix=None):
        valid = isinstance(row, dict) and type(row.get("bindings_complete")) is bool
        for key, target in (("binding_missing_fields", self.missing), ("binding_malformed_fields", self.malformed)):
            values = row.get(key) if isinstance(row, dict) else None
            if (not isinstance(values, list) or len(values) > 64
                    or any(not isinstance(v, str) or v not in _BINDING_CODES or (prefix and not v.startswith(prefix + ".")) for v in values)
                    or values != sorted(set(values))):
                valid = False
            else:
                target.update(values)
        if not valid:
            self.malformed.add(code)
        return valid

    def merge(self, other):
        self.missing.update(other.missing)
        self.malformed.update(other.malformed)

    def emit(self, target):
        target.update(binding_missing_fields=sorted(self.missing - self.malformed),
                      binding_malformed_fields=sorted(self.malformed),
                      bindings_complete=not (self.missing or self.malformed))
        return target


def _json_bytes(value, *, pretty=False):
    return len((json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                           **({"indent": 2} if pretty else {})) + "\n").encode("utf-8"))


def _repository_bytes(value):
    return _json_bytes({"repository_evidence": value}, pretty=True)


def _compact_bytes(value):
    return len(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8"))


def _family_index(source, identity, allowed, bound, code, diagnostics):
    """Identical family rows may collapse; conflicts never choose a winner."""
    if not isinstance(source, list):
        diagnostics.missing.add(code)
        return {}
    index = {}
    conflicts = set()
    for row in source:
        if not isinstance(row, dict) or not _positive(row.get(identity)):
            diagnostics.malformed.add(code)
            continue
        number = row[identity]
        if set(row) - allowed or _compact_bytes(row) > bound:
            conflicts.add(number)
        if number in index and index[number] != row:
            conflicts.add(number)
        index[number] = row
    for number in conflicts:
        index[number] = {identity: number, "bindings_complete": False,
                         "binding_missing_fields": [], "binding_malformed_fields": [identity.replace("_id", ".id").replace("pull_request", "pr")]}
    return index


def _project_pr(native):
    b, row = _Binding(), {}
    b.field(row, "id", native.get("pullRequestId"), _positive, "pr.id")
    b.field(row, "status", native.get("status"), lambda v: _choice(v, {"active", "abandoned", "completed"}), "pr.status")
    b.field(row, "is_draft", native.get("isDraft"), lambda v: type(v) is bool, "pr.is_draft")
    for key, source in (("source_commit_sha", "lastMergeSourceCommit"), ("target_commit_sha", "lastMergeTargetCommit"), ("merge_commit_sha", "lastMergeCommit")):
        obj = native.get(source)
        value = obj.get("commitId") if isinstance(obj, dict) else obj
        b.field(row, key, value, lambda v: _hex(v, 40), "pr." + key,
                required=key != "merge_commit_sha" or native.get("status") == "completed")
    for key, source in (("source_ref_sha256", "sourceRefName"), ("target_ref_sha256", "targetRefName")):
        b.field(row, key, native.get(source), lambda v: _ref_hash(v) is not None, "pr." + key, normalize=_ref_hash)
    return b.emit(row)


def _project_build(native, identity, source, timing, repository_id):
    b, row = _Binding(), {"id": native["id"], "status": native["status"], "result": native.get("result")}
    # Supplied native optional data cannot become absence-valid by omission from
    # the before-sanitization transport. Null/absent optional values remain normal.
    for public, raw in (("queue_time", "queueTime"), ("start_time", "startTime"), ("finish_time", "finishTime")):
        value = native.get(raw)
        if value is not None:
            if not _timestamp(value):
                b.malformed.add("build." + public)
            elif not isinstance(timing, dict) or timing.get(public) is None:
                b.missing.add("build." + public)
            elif timing[public] != value:
                b.malformed.add("build." + public)
    families = ((identity, {"repository_id": _guid, "definition_id": _positive, "definition_revision": _positive}),
                (source, {"source_commit_sha": lambda v: _hex(v, 40), "source_ref_sha256": lambda v: _hex(v, 64)}),
                (timing, {"status": lambda v: _choice(v, _BUILD_STATES), "result": lambda v: _choice(v, _BUILD_RESULTS),
                          "queue_time": _timestamp, "start_time": _timestamp, "finish_time": _timestamp}))
    for sidecar, validators in families:
        if sidecar is None:
            b.missing.add("observation.build_bindings")
            sidecar = {}
        else:
            b.diagnostics(sidecar, "build.id", "build")
        for key, validator in validators.items():
            required = key not in {"result", "start_time", "finish_time"}
            if key == "result":
                required = native["status"] == "completed"
                validator = lambda v: _choice(v, _BUILD_RESULTS - ({"none"} if required else set()))
            elif key == "start_time":
                required = native["status"] in {"inProgress", "cancelling", "completed"}
            elif key == "finish_time":
                required = native["status"] == "completed"
            values = {}
            b.field(values, key, sidecar.get(key), validator, "build." + key, required=required,
                    normalize=str.lower if key == "repository_id" else None)
            if key in values:
                value = values[key]
                if key == "repository_id" and value != repository_id:
                    b.malformed.add("build.repository_id")
                elif key in {"status", "result"} and value != native.get(key):
                    b.malformed.add("build." + key)
                elif key == "source_commit_sha" and native.get("sourceVersion") != value:
                    b.malformed.add("build.source_commit_sha")
                elif key == "source_ref_sha256" and native.get("sourceBranch") is not None and _ref_hash(native["sourceBranch"]) != value:
                    b.malformed.add("build.source_ref_sha256")
                elif key.endswith("_time") and native.get({"queue_time": "queueTime", "start_time": "startTime", "finish_time": "finishTime"}[key]) is not None and native[{"queue_time": "queueTime", "start_time": "startTime", "finish_time": "finishTime"}[key]] != value:
                    b.malformed.add("build." + key)
                else:
                    row[key] = value
    # Keep a safe legacy commit even if a missing/contested sidecar cannot bind it.
    if _hex(native.get("sourceVersion"), 40):
        row["source_commit_sha"] = native["sourceVersion"]
    else:
        (b.missing if native.get("sourceVersion") is None else b.malformed).add("build.source_commit_sha")
    if row.get("repository_id") != repository_id or repository_id is None:
        if "build.repository_id" not in b.missing | b.malformed:
            b.missing.add("build.repository_id")
        # Foreign identities cannot attach definition/source/time evidence.
        row = {k: v for k, v in row.items() if k in {"id", "status", "result", "source_commit_sha"}}
    return b.emit(row)


_PARENT_FACT_KEYS = {"schema_version", "build_id", "child_id", "parent_id", "parent_type", "child_occurrences", "parent_occurrences", "resolution", "acyclic", "index_sha256", "native_record_count"}
_TIMELINE_CONTAINER_KEYS = _DIAGNOSTIC_KEYS | {"build_id", "record_count", "returned_record_count", "projected_record_count", "states_recognized", "records_truncated", "records", "native_parent_index_sha256", "parent_validation_facts"}
_TIMELINE_RECORD_KEYS = _DIAGNOSTIC_KEYS | {"id", "parent_id", "type", "state", "result", "attempt", "identifier_sha256"}


def _project_timeline(native, build_bound, producer_coverage):
    """Check retained ancestry independently; omitted ancestry is conditional.

    Exact producer facts are consistency evidence, not authentication of an unseen
    native index. A coherent fabricated fact can pass this boundary. Acceptance
    requires the trusted matching-source reader and original transport evidence.
    """
    b = _Binding()
    summary = {"build_id": native["build_id"], "record_count": 0, "states_recognized": False}
    shape = b.diagnostics(native, "timeline.records", "timeline")
    if set(native) != _TIMELINE_CONTAINER_KEYS:
        b.malformed.add("timeline.records")
        shape = False
    raw_records = native.get("records")
    if not isinstance(raw_records, list):
        b.malformed.add("timeline.records")
        raw_records = []
        shape = False
    for key in ("record_count", "returned_record_count", "projected_record_count"):
        if not _count(native.get(key)):
            b.malformed.add("timeline.records")
            shape = False
    if shape and (native["record_count"] != native["returned_record_count"]
                  or native["projected_record_count"] != len(raw_records)
                  or native["returned_record_count"] < len(raw_records)):
        b.malformed.add("timeline.records")
        shape = False
    if any(type(native.get(key)) is not bool for key in ("states_recognized", "records_truncated")):
        b.malformed.add("timeline.records")
        shape = False
    if not _hex(native.get("native_parent_index_sha256"), 64):
        b.malformed.add("timeline.parent_resolution")
    if not build_bound:
        b.missing.add("timeline.build_id")
    if not shape:
        summary.update(record_count=len(raw_records), records=[], returned_record_count=None,
                       projected_record_count=0, records_truncated=bool(raw_records))
        return b.emit(summary)

    summary.update(record_count=native["record_count"], returned_record_count=native["returned_record_count"],
                   records_truncated=native["records_truncated"] or len(raw_records) > 256 or native["returned_record_count"] > len(raw_records),
                   projected_record_count=0, records=[])
    if native["returned_record_count"] > len(raw_records) and not native["records_truncated"]:
        b.malformed.add("timeline.records")
    producer_omission = (native["records_truncated"] is True and len(raw_records) < native["returned_record_count"]
                         and isinstance(producer_coverage, dict)
                         and any(producer_coverage.get(k) is True for k in ("count_capped", "byte_capped")))
    records, bindings, ids = [], [], {}
    recognized = True
    for position, raw in enumerate(raw_records):
        rb, row = _Binding(), {}
        if not isinstance(raw, dict):
            raw = {}
            rb.malformed.add("timeline.records")
        if set(raw) - _TIMELINE_RECORD_KEYS:
            rb.malformed.add("timeline.records")
        rb.diagnostics(raw, "timeline.records", "timeline")
        rb.field(row, "id", raw.get("id"), _guid, "timeline.id", normalize=str.lower)
        rb.field(row, "type", raw.get("type"), lambda v: _choice(v, _TIMELINE_TYPES), "timeline.type")
        state_valid = _choice(raw.get("state"), _TIMELINE_STATES)
        result_valid = raw.get("result") is None or _choice(raw.get("result"), _TIMELINE_RESULTS)
        recognized = recognized and state_valid and result_valid and not (raw.get("state") == "completed" and raw.get("result") is None)
        if "type" in row:
            rb.field(row, "state", raw.get("state"), lambda v: _choice(v, _TIMELINE_STATES), "timeline.state")
            rb.field(row, "result", raw.get("result"), lambda v: _choice(v, _TIMELINE_RESULTS), "timeline.result", required=raw.get("state") == "completed")
            rb.field(row, "parent_id", raw.get("parent_id"), _guid, "timeline.parent_id", required=row["type"] != "Stage", normalize=str.lower)
            rb.field(row, "attempt", raw.get("attempt"), _positive, "timeline.attempt", required=False)
            rb.field(row, "identifier_sha256", raw.get("identifier_sha256"), lambda v: _hex(v, 64), "timeline.identifier_sha256", required=row["type"] in {"Stage", "Job"})
        else:
            # Unknown native types keep only a safe identity and fixed diagnostics.
            if not state_valid:
                (rb.missing if raw.get("state") is None else rb.malformed).add("timeline.state")
            if not result_valid:
                rb.malformed.add("timeline.result")
            for key, validator in (("parent_id", _guid), ("attempt", _positive), ("identifier_sha256", lambda v: _hex(v, 64))):
                rb.field({}, key, raw.get(key), validator, "timeline." + key, required=False)
        if not build_bound:
            rb.missing.add("timeline.build_id")
        records.append((position, row))
        bindings.append(rb)
        if "id" in row:
            ids.setdefault(row["id"], []).append(position)
    for positions in ids.values():
        if len(positions) > 1:
            for position in positions:
                bindings[position].malformed.add("timeline.duplicate_id")

    facts = native.get("parent_validation_facts")
    fact_index = {}
    if not isinstance(facts, list) or len(facts) > 256:
        b.malformed.add("timeline.parent_resolution")
        facts = []
    fact_order = []
    for fact in facts:
        valid = (isinstance(fact, dict) and set(fact) == _PARENT_FACT_KEYS and _compact_bytes(fact) <= 512
                 and fact.get("schema_version") == "atlas-tools.azure-parent-validation.v1"
                 and _positive(fact.get("build_id")) and _guid(fact.get("child_id"))
                 and fact["child_id"] == fact["child_id"].lower() and _guid(fact.get("parent_id"))
                 and fact["parent_id"] == fact["parent_id"].lower()
                 and (fact.get("parent_type") is None or _choice(fact.get("parent_type"), _TIMELINE_TYPES))
                 and all(_count(fact.get(k)) for k in ("child_occurrences", "parent_occurrences", "native_record_count"))
                 and _choice(fact.get("resolution"), {"resolved", "missing", "ambiguous", "invalid"})
                 and type(fact.get("acyclic")) is bool and _hex(fact.get("index_sha256"), 64))
        if not valid:
            b.malformed.add("timeline.parent_resolution")
            continue
        child = fact["child_id"]
        fact_order.append(child)
        fact_index.setdefault(child, []).append(fact)
        if child not in ids or len(ids[child]) != 1:
            b.malformed.add("timeline.parent_resolution")
        if fact["build_id"] != native["build_id"]:
            b.malformed.add("timeline.build_id")
    needed_order = [row["id"] for _, row in records if "id" in row and ("parent_id" in row or row.get("type") in {"Phase", "Job", "Task"})]
    if fact_order != [child for child in needed_order if child in fact_index]:
        b.malformed.add("timeline.parent_resolution")
    for child, values in fact_index.items():
        if len(values) > 1:
            b.malformed.add("timeline.duplicate_id")
            for position in ids.get(child, []):
                bindings[position].malformed.add("timeline.duplicate_id")

    allowed_parents = {"Stage": _TIMELINE_TYPES, "Phase": {"Stage", "Phase"}, "Job": {"Stage", "Phase"}, "Task": {"Job"}}
    for position, row in records:
        rb = bindings[position]
        child, parent = row.get("id"), row.get("parent_id")
        needs_parent = parent is not None or row.get("type") in {"Phase", "Job", "Task"}
        if not needs_parent:
            continue
        candidates = fact_index.get(child, [])
        if len(candidates) != 1:
            rb.missing.add("timeline.parent_resolution")
            continue
        fact = candidates[0]
        if fact["build_id"] != native["build_id"]:
            rb.malformed.add("timeline.build_id")
        if (child is None or len(ids.get(child, [])) != 1 or parent is None or parent == child
                or fact["parent_id"] != parent or fact["index_sha256"] != native.get("native_parent_index_sha256")
                or fact["native_record_count"] != native["returned_record_count"]
                or fact["child_occurrences"] != 1 or fact["parent_occurrences"] != 1
                or fact["resolution"] != "resolved" or fact["acyclic"] is not True
                or fact["parent_type"] not in allowed_parents.get(row.get("type"), set())):
            rb.malformed.add("timeline.parent_resolution")
        parent_positions = ids.get(parent, [])
        if parent_positions:
            if len(parent_positions) != 1 or records[parent_positions[0]][1].get("type") != fact["parent_type"]:
                rb.malformed.add("timeline.parent_resolution")
        elif not producer_omission:
            rb.missing.add("timeline.parent_resolution")
        # Follow every retained edge, including ancestors whose own facts lie.
        seen, cursor = set(), child
        while cursor in ids and len(ids[cursor]) == 1:
            if cursor in seen:
                rb.malformed.add("timeline.parent_resolution")
                break
            seen.add(cursor)
            cursor = records[ids[cursor][0]][1].get("parent_id")
    # Orphan/conflicting container facts cannot support any typed local claim.
    container_relation_bad = bool(b.malformed & {"timeline.parent_resolution", "timeline.duplicate_id", "timeline.build_id"})
    for position, row in records:
        rb = bindings[position]
        if container_relation_bad:
            rb.malformed.update(b.malformed & {"timeline.parent_resolution", "timeline.duplicate_id", "timeline.build_id"})
        rb.emit(row)
        b.merge(rb)
    records.sort(key=lambda entry: (0, entry[1]["id"], entry[1].get("attempt", 0), entry[0]) if "id" in entry[1] else (1, "", 0, entry[0]))
    summary["records"] = [row for _, row in records[:256]]
    summary["projected_record_count"] = len(summary["records"])
    summary["states_recognized"] = recognized and native["states_recognized"] is True
    if not summary["states_recognized"]:
        b.malformed.add("timeline.records")
    b.emit(summary)
    summary["bindings_complete"] = summary["bindings_complete"] and not summary["records_truncated"]
    return summary


_COVERAGE_KEYS = {"returned_count", "projected_count", "bound_count", "malformed_count", "omitted_count", "upstream_complete", "count_capped", "byte_capped"}
_BUDGET_KEYS = {"reader_bytes", "public_bytes", "reader_byte_limit", "public_byte_limit", "aggregate_truncated", "report_omitted"}
_FAMILIES = ("observation", "pull_requests", "builds", "timelines")


def _minimal_repository_fallback():
    """Exact frozen omission record, with unknown original counts and sizes."""
    return {"observed": True, "complete": False, "reported_complete": None,
            "repository_matches_profile": False, "coverage": {}, "missing_fields": [], "omitted_fields": [],
            "deployment_authority": False, "projection_complete": False,
            "evidence_contract": _OBSERVATION_CONTRACT, "bindings_complete": False,
            "binding_coverage_complete": False, "binding_missing_fields": ["observation.coverage"],
            "binding_malformed_fields": [], "binding_coverage": {
                family: {"returned_count": None, "projected_count": 0, "bound_count": 0, "malformed_count": None,
                         "omitted_count": None, "upstream_complete": False, "count_capped": False, "byte_capped": True}
                for family in _FAMILIES},
            "budget": {"reader_bytes": None, "public_bytes": None, "reader_byte_limit": 98304,
                       "public_byte_limit": 98304, "aggregate_truncated": True, "report_omitted": True},
            "requested_build_ids": [], "request_ids_invalid_count": None, "requested_build_ids_omitted_count": None,
            "selected_build_ids": [], "selected_build_ids_truncated": True,
            **{name: [] for name in ("base_refs", "pull_requests", "policies", "policy_evaluations", "builds", "timelines",
                                    "selected_builds_without_metadata", "selected_builds_without_timeline",
                                    "selected_builds_without_repository", "selected_builds_without_definition", "selected_builds_without_source")},
            "blocker_codes": ["observation-byte-budget-exhausted"]}


def _read_coverage(evidence, diagnostics):
    result = {}
    source = evidence.get("binding_coverage")
    if not isinstance(source, dict) or set(source) != set(_FAMILIES):
        diagnostics.malformed.add("observation.coverage")
        source = {}
    for family in _FAMILIES:
        row = source.get(family)
        valid = (isinstance(row, dict) and set(row) == _COVERAGE_KEYS
                 and all(type(row.get(k)) is bool for k in ("upstream_complete", "count_capped", "byte_capped"))
                 and all(row.get(k) is None or _count(row.get(k)) for k in ("returned_count", "malformed_count", "omitted_count"))
                 and all(_count(row.get(k)) for k in ("projected_count", "bound_count")))
        if valid:
            returned, projected = row["returned_count"], row["projected_count"]
            valid = (row["bound_count"] <= projected
                     and (returned is not None or (row["omitted_count"] is None and not row["upstream_complete"]))
                     and (returned is None or (returned >= projected and row["omitted_count"] == returned - projected
                and (row["malformed_count"] is None or row["malformed_count"] <= returned))))
        if not valid:
            diagnostics.malformed.add("observation.coverage")
            row = {"returned_count": None, "projected_count": 0, "bound_count": 0, "malformed_count": None,
                   "omitted_count": None, "upstream_complete": False, "count_capped": False, "byte_capped": False}
        result[family] = dict(row)
    return result


def _project_repository_evidence(proposal: dict[str, Any], evidence: Any) -> dict[str, Any]:
    result = _project_legacy_repository_evidence(proposal, evidence)
    b = _Binding()
    if not isinstance(evidence, dict):
        b.missing.update({"observation.contract", "observation.coverage"})
        b.emit(result)
        result["binding_coverage_complete"] = False
        return result
    marker = evidence.get("evidence_contract")
    marked = marker == _OBSERVATION_CONTRACT
    if not marked:
        b.missing.add("observation.contract")
    else:
        result["evidence_contract"] = marker
    budget = evidence.get("budget")
    if marked and isinstance(budget, dict) and budget.get("report_omitted") is True:
        return _minimal_repository_fallback()
    selected = proposal.get("options", {}).get("build_ids", [])
    selected_list = selected if isinstance(selected, list) else []
    valid_ids = sorted({value for value in selected_list if _positive(value)})
    requested = valid_ids[:32]
    invalid = sum(not _positive(value) for value in selected_list) + (not isinstance(selected, list))
    omitted = max(0, len(valid_ids) - 32)
    explicit = bool(selected_list) or not isinstance(selected, list)
    scope = "explicit-build-ids" if explicit else "first-ten-listed-builds"
    result.update(requested_build_ids=requested, request_ids_invalid_count=invalid,
                  requested_build_ids_omitted_count=omitted, selected_build_ids=requested,
                  selected_build_ids_truncated=bool(omitted))
    if marked:
        b.diagnostics(evidence, "observation.coverage")
        b.field(result, "observed_at", evidence.get("observed_at"), _timestamp, "observation.observed_at")
        repo = evidence.get("repository")
        resolved = repo.get("id") if isinstance(repo, dict) else None
        b.field({}, "repository_id", resolved, _guid, "observation.repository_id")
        b.field({}, "repository_id", evidence.get("repository_id"), _guid, "observation.repository_id")
        if _guid(resolved) and _guid(evidence.get("repository_id")) and resolved.lower() == evidence["repository_id"].lower() and result["repository_matches_profile"]:
            result["repository_id"] = resolved.lower()
        else:
            b.malformed.add("observation.repository_id")
            result.pop("repository_id", None)
        request_valid = (isinstance(evidence.get("requested_build_ids"), list)
                         and all(_positive(v) for v in evidence["requested_build_ids"])
                         and evidence["requested_build_ids"] == requested
                         and _count(evidence.get("request_ids_invalid_count")) and evidence["request_ids_invalid_count"] == invalid
                         and _count(evidence.get("requested_build_ids_omitted_count")) and evidence["requested_build_ids_omitted_count"] == omitted
                         and evidence.get("timeline_scope") == scope)
        if not request_valid:
            b.malformed.add("observation.request_ids")
        if type(evidence.get("binding_coverage_complete")) is not bool:
            b.malformed.add("observation.coverage")
    else:
        request_valid = False
    coverage = _read_coverage(evidence, b)
    if marked and (coverage["observation"]["returned_count"] != 1 or coverage["observation"]["projected_count"] != 1):
        b.malformed.add("observation.coverage")
    coverage["observation"]["returned_count"] = 1
    if omitted:
        coverage["builds"]["count_capped"] = True
        coverage["timelines"]["count_capped"] = True
    budget_valid = (isinstance(budget, dict) and set(budget) == _BUDGET_KEYS
                    and _positive(budget.get("reader_bytes")) and budget["reader_bytes"] <= 98304
                    and budget["reader_bytes"] == _repository_bytes(evidence)
                    and budget.get("public_bytes") is None
                    and type(budget.get("reader_byte_limit")) is int and budget["reader_byte_limit"] == 98304
                    and type(budget.get("public_byte_limit")) is int and budget["public_byte_limit"] == 98304
                    and type(budget.get("aggregate_truncated")) is bool and type(budget.get("report_omitted")) is bool)
    if not budget_valid:
        b.malformed.add("observation.coverage")
    result["budget"] = {"reader_bytes": budget["reader_bytes"] if budget_valid else None, "public_bytes": 0,
                        "reader_byte_limit": 98304, "public_byte_limit": 98304,
                        "aggregate_truncated": (isinstance(budget, dict) and budget.get("aggregate_truncated") is True)
                                               or any(row["byte_capped"] for row in coverage.values()),
                        "report_omitted": False}
    result["binding_coverage"] = coverage
    # All indexes describe this input only; no other checkout or live lookup is used.
    pr_fields = {"source_commit_sha", "target_commit_sha", "merge_commit_sha", "source_ref_sha256", "target_ref_sha256"}
    pr_index = _family_index(evidence.get("pr_bindings"), "pull_request_id", _DIAGNOSTIC_KEYS | pr_fields | {"pull_request_id"}, 1024, "observation.pr_bindings", b)
    raw_prs = [v for v in evidence.get("pull_requests", []) if isinstance(v, dict)] if isinstance(evidence.get("pull_requests"), list) else []
    derived_prs = {}
    for native in raw_prs:
        projected = _project_pr(native)
        b.missing.update(projected["binding_missing_fields"])
        b.malformed.update(projected["binding_malformed_fields"])
        if _positive(native.get("pullRequestId")):
            derived_prs.setdefault(native["pullRequestId"], []).append(projected)
    if isinstance(evidence.get("pull_requests"), list) and len(raw_prs) != len(evidence["pull_requests"]):
        b.malformed.add("pr.id")
    if coverage["pull_requests"]["malformed_count"] is not None:
        coverage["pull_requests"]["malformed_count"] = max(coverage["pull_requests"]["malformed_count"], sum(bool(_project_pr(native)["binding_malformed_fields"]) for native in raw_prs))
    for row in result.get("pull_requests", []):
        candidates = derived_prs[row["id"]]
        pb = _Binding()
        projected = candidates[0]
        if any(value != projected for value in candidates[1:]):
            pb.malformed.add("pr.id")
            projected = {k: v for k, v in row.items() if k in {"id", "status", "is_draft"}}
        else:
            pb.diagnostics(projected, "pr.id", "pr")
        sidecar = pr_index.get(row["id"])
        if sidecar is not None:
            pb.diagnostics(sidecar, "pr.id", "pr")
            for key in pr_fields:
                if sidecar.get(key) is not None:
                    if not _hex(sidecar[key], 40 if key.endswith("commit_sha") else 64):
                        pb.malformed.add("pr." + key)
                    elif key in projected and sidecar[key] != projected[key]:
                        pb.malformed.add("pr.id")
                    elif key not in projected:
                        # The native observation is authoritative; sidecars cannot fill it.
                        pb.malformed.add("pr." + key)
                elif key in projected:
                    pb.missing.add("pr." + key)
        elif marked:
            b.missing.add("observation.pr_bindings")
        row.update(pb.emit(projected))
        b.merge(pb)
    if set(pr_index) - set(derived_prs):
        b.malformed.add("observation.pr_bindings")

    family_fields = ({"repository_id", "definition_id", "definition_revision"},
                     {"source_commit_sha", "source_ref_sha256"},
                     {"status", "result", "queue_time", "start_time", "finish_time"})
    explicit_names = ("build_bindings", "build_source_bindings", "build_time_bindings")
    if explicit:
        sources = [evidence.get(key) for key in explicit_names]
        if "default_build_bindings" in evidence:
            b.malformed.add("observation.build_bindings")
    else:
        default = evidence.get("default_build_bindings")
        if not isinstance(default, dict) or set(default) != {"repository_definition", "source", "time"}:
            b.missing.add("observation.build_bindings")
            default = {}
        sources = [default.get(key) for key in ("repository_definition", "source", "time")]
        if any(key in evidence for key in explicit_names):
            b.malformed.add("observation.build_bindings")
    if marked and not request_valid:
        sources = [None, None, None]
    indexes = [_family_index(source, "build_id", _DIAGNOSTIC_KEYS | fields | {"build_id"}, 1024 if i == 2 else 512,
                             "observation.build_bindings", b) for i, (source, fields) in enumerate(zip(sources, family_fields))]
    raw_builds = [v for v in evidence.get("builds", []) if isinstance(v, dict)] if isinstance(evidence.get("builds"), list) else []
    build_index = {}
    for native in raw_builds:
        if _positive(native.get("id")):
            build_index.setdefault(native["id"], []).append(native)
        else:
            b.malformed.add("build.id")
    original_builds = evidence.get("builds", []) if isinstance(evidence.get("builds"), list) else []
    if len(raw_builds) != len(original_builds):
        b.malformed.add("build.id")
    selected_defaults = {v["id"] for v in original_builds[:10] if isinstance(v, dict) and _positive(v.get("id"))}
    expected = set(requested) if explicit else selected_defaults
    for index in indexes:
        if set(index) - expected:
            b.malformed.add("observation.build_bindings")
    metadata = {}
    for position, summary in enumerate(result.get("builds", [])):
        number = summary["id"]
        candidates = build_index[number]
        native = next((value for value in candidates if value.get("status") == summary["status"]
                       and value.get("result") == summary["result"]
                       and ("source_commit_sha" not in summary or value.get("sourceVersion") == summary["source_commit_sha"])), candidates[0])
        arguments = [index.get(number) if number in expected else None for index in indexes]
        projected = _project_build(native, *arguments, result.get("repository_id") if marked else None)
        normalized = [_project_build(value, *arguments, result.get("repository_id") if marked else None) for value in candidates]
        if any(value != normalized[0] for value in normalized[1:]):
            projected = {k: v for k, v in summary.items() if k in {"id", "status", "result", "source_commit_sha"}}
            projected.update(bindings_complete=False, binding_missing_fields=[], binding_malformed_fields=["build.id"])
        result["builds"][position] = projected
        metadata[number] = projected
    for native in raw_builds:
        if explicit and (not _positive(native.get("id")) or native["id"] not in expected):
            continue
        for key, validator in (("status", lambda v: _choice(v, _BUILD_STATES)), ("result", lambda v: v is None or _choice(v, _BUILD_RESULTS))):
            if not validator(native.get(key)):
                (b.missing if native.get(key) is None else b.malformed).add("build." + key)
        if native.get("status") == "completed" and native.get("result") in (None, "none"):
            (b.missing if native.get("result") is None else b.malformed).add("build.result")

    typed = evidence.get("timeline_bindings")
    if not isinstance(typed, list):
        b.missing.add("observation.timeline_bindings")
        typed = []
    typed_index = {}
    for container in typed:
        if not isinstance(container, dict) or not _positive(container.get("build_id")):
            b.malformed.add("timeline.build_id")
            continue
        typed_index.setdefault(container["build_id"], []).append(container)
    if set(typed_index) - expected:
        b.malformed.add("observation.timeline_bindings")
    legacy_timelines = {}
    for value in evidence.get("timelines", []) if isinstance(evidence.get("timelines"), list) else []:
        if isinstance(value, dict) and _positive(value.get("build_id")):
            legacy_timelines.setdefault(value["build_id"], []).append(value)
    if marked and (expected - set(typed_index) or expected - set(legacy_timelines)):
        b.missing.update({"observation.timeline_bindings", "timeline.records", "observation.coverage"})
        result["projection_complete"] = result["complete"] = False
    summaries = {v["build_id"]: v for v in result.get("timelines", [])}
    order = [v["build_id"] for v in result.get("timelines", [])]
    # A diagnostic typed container can survive rejection by the legacy state guard.
    order += [number for number in sorted(typed_index) if number not in summaries and number in expected]
    timelines = []
    for number in order[:32]:
        candidates = typed_index.get(number, [])
        if marked and candidates and number in expected:
            container = _project_timeline(candidates[0], bool(metadata.get(number, {}).get("bindings_complete")), coverage["timelines"])
            legacy = legacy_timelines.get(number, [])
            if legacy:
                if not _corroborate_timeline(container, legacy[0], candidates[0]):
                    b.malformed.add("observation.coverage")
                    result["projection_complete"] = result["complete"] = False
            else:
                container["binding_missing_fields"] = sorted(set(container["binding_missing_fields"]) | {"timeline.records"})
                container["bindings_complete"] = False
                b.missing.add("observation.coverage")
            if len(candidates) != 1 or len(legacy) > 1:
                container.update(bindings_complete=False, binding_malformed_fields=sorted(set(container["binding_malformed_fields"]) | {"timeline.build_id"}))
                for record in container.get("records", []):
                    record.update(bindings_complete=False, binding_malformed_fields=sorted(set(record["binding_malformed_fields"]) | {"timeline.build_id"}))
        else:
            container = dict(summaries[number])
            container.update(bindings_complete=False, binding_missing_fields=["observation.timeline_bindings"], binding_malformed_fields=[])
            b.missing.add("observation.timeline_bindings")
        timelines.append(container)
    result["timelines"] = timelines if result["repository_matches_profile"] else []
    if len(typed_index) > 32:
        coverage["timelines"]["count_capped"] = True
    for family in ("pull_requests", "builds", "timelines"):
        values = result.get(family, [])
        for value in values:
            for key, target in (("binding_missing_fields", b.missing), ("binding_malformed_fields", b.malformed)):
                target.update(value.get(key, []))
        raw_count = len(evidence[family]) if isinstance(evidence.get(family), list) else None
        if family == "timelines" and marked and isinstance(evidence.get("timeline_bindings"), list):
            raw_count = max(raw_count or 0, len(evidence["timeline_bindings"]))
        returned = coverage[family]["returned_count"]
        if returned is not None and raw_count is not None and returned < raw_count:
            b.malformed.add("observation.coverage")
            coverage[family]["returned_count"] = None
        if raw_count is None or (returned is not None and coverage[family]["projected_count"] != raw_count):
            b.malformed.add("observation.coverage")
        if family == "timelines":
            if any(v.get("records_truncated") for v in values):
                if any(len(v.get("records", [])) == 256 and (v.get("returned_record_count") or 0) > 256 for v in values):
                    coverage[family]["count_capped"] = True
                if not (coverage[family]["count_capped"] or coverage[family]["byte_capped"]):
                    b.malformed.add("observation.coverage")
        if result.get("coverage", {}).get(family, {}).get("truncated"):
            coverage[family]["count_capped"] = True
    if not marked:
        b.missing.update({"observation.pr_bindings", "observation.build_bindings", "observation.timeline_bindings", "observation.coverage"})
    if invalid or omitted or not request_valid:
        b.missing.add("observation.request_ids")
    b.emit(result)
    # Retain these before global unions are recomputed during deterministic fitting.
    return _fit_repository(result, marked=marked, envelope_valid=not bool((b.missing | b.malformed) & {"observation.contract", "observation.observed_at", "observation.repository_id", "observation.request_ids", "observation.coverage"}))


def _refresh_repository(result, *, marked, envelope_valid):
    coverage = result["binding_coverage"]
    for family in _FAMILIES:
        values = [result] if family == "observation" else result.get(family, [])
        row = coverage[family]
        row["projected_count"] = len(values)
        row["bound_count"] = int(envelope_valid) if family == "observation" else sum(v.get("bindings_complete") is True for v in values)
        malformed = sum(bool(v.get("binding_malformed_fields")) for v in values) if family != "observation" else int(not envelope_valid)
        if row["malformed_count"] is not None:
            row["malformed_count"] = max(row["malformed_count"], malformed)
        returned = row["returned_count"]
        row["omitted_count"] = returned - len(values) if returned is not None and returned >= len(values) else None
        if family != "observation" and family in result.get("coverage", {}):
            result["coverage"][family]["projected_count"] = len(values)
    builds = {row["id"]: row for row in result.get("builds", [])}
    timelines = {row["build_id"]: row for row in result.get("timelines", [])}
    selected = result.get("requested_build_ids", [])

    def family_valid(number, fields):
        value = builds.get(number, {})
        diagnostics = set(value.get("binding_missing_fields", [])) | set(value.get("binding_malformed_fields", []))
        return not diagnostics.intersection({"build.id", *("build." + field for field in fields)})

    for suffix, predicate in (
        ("metadata", lambda v: v in builds),
        ("timeline", lambda v: v in timelines),
        ("repository", lambda v: builds.get(v, {}).get("repository_id") == result.get("repository_id") and result.get("repository_id") is not None and family_valid(v, ("repository_id",))),
        ("definition", lambda v: all(_positive(builds.get(v, {}).get(k)) for k in ("definition_id", "definition_revision")) and family_valid(v, ("definition_id", "definition_revision"))),
        ("source", lambda v: _hex(builds.get(v, {}).get("source_commit_sha"), 40) and _hex(builds.get(v, {}).get("source_ref_sha256"), 64) and family_valid(v, ("source_commit_sha", "source_ref_sha256"))),
    ):
        result["selected_builds_without_" + suffix] = [number for number in selected if not predicate(number)][:32]
    family_missing = any("observation." + field in result["binding_missing_fields"] or "observation." + field in result["binding_malformed_fields"] for field in ("pr_bindings", "build_bindings", "timeline_bindings", "coverage"))
    covered = (marked and envelope_valid and not family_missing
               and not result.get("request_ids_invalid_count") and not result.get("requested_build_ids_omitted_count")
               and all(row["returned_count"] is not None and row["omitted_count"] == 0 and row["upstream_complete"] is True
                       and not row["count_capped"] and not row["byte_capped"] and row["malformed_count"] == 0 for row in coverage.values())
               and not result["selected_builds_without_metadata"] and not result["selected_builds_without_timeline"]
               and not any(v.get("records_truncated") for v in result.get("timelines", []))
               and not result["budget"]["aggregate_truncated"])
    result["binding_coverage_complete"] = bool(covered)
    result["bindings_complete"] = bool(covered and not result["binding_missing_fields"] and not result["binding_malformed_fields"]
                                       and all(row["bound_count"] == row["projected_count"] for row in coverage.values()))
    if marked:
        result["projection_complete"] = bool(result["projection_complete"] and all(row["upstream_complete"] is True and not row["count_capped"] and not row["byte_capped"] and row["omitted_count"] == 0 for row in coverage.values()) and not result["budget"]["aggregate_truncated"])
        result["complete"] = bool(result["complete"] and result["projection_complete"])


def _measure_public_repository(result):
    result["budget"]["public_bytes"] = 0
    for _ in range(7):
        size = _repository_bytes(result)
        if result["budget"]["public_bytes"] == size:
            return size
        result["budget"]["public_bytes"] = size
    return None


def _fit_repository(result, *, marked, envelope_valid):
    """Fit full embedded pretty bytes, removing observations in frozen order."""
    def measure():
        _refresh_repository(result, marked=marked, envelope_valid=envelope_valid)
        return _measure_public_repository(result)

    size = measure()
    if size is None:
        return _minimal_repository_fallback()
    while size > _REPOSITORY_BYTE_LIMIT:
        result["budget"]["aggregate_truncated"] = True
        result["binding_missing_fields"] = sorted(set(result["binding_missing_fields"]) | {"observation.coverage"})
        result["complete"] = result["projection_complete"] = False
        containers = [v for v in result.get("timelines", []) if v.get("records")]
        if containers:
            container = max(enumerate(containers), key=lambda pair: (pair[1]["build_id"], pair[0]))[1]
            container["records"].pop()
            container["projected_record_count"] = len(container["records"])
            container["records_truncated"] = True
            container["bindings_complete"] = False
            result["binding_coverage"]["timelines"]["byte_capped"] = True
        else:
            removed = False
            for family in ("timelines", "policy_evaluations", "policies", "pull_requests", "builds", "base_refs"):
                if result.get(family):
                    result[family].pop()
                    result["coverage"][family]["omitted"] = True
                    if family in result["binding_coverage"]:
                        result["binding_coverage"][family]["byte_capped"] = True
                    else:
                        result["binding_coverage"]["observation"]["byte_capped"] = True
                    if family == "base_refs" and not result[family]:
                        result.pop("base_commit_sha", None)
                    removed = True
                    break
            if not removed:
                return _minimal_repository_fallback()
        size = measure()
        if size is None:
            return _minimal_repository_fallback()
    return result


def _fit_public_result(result):
    if _json_bytes(result) <= _PUBLIC_BYTE_LIMIT:
        return result
    # Exact whole-result omission policy. The remaining allowlist is bounded;
    # no prefix of an oversized JSON document is ever returned.
    result.update(repository_evidence=_minimal_repository_fallback(), items=[], items_truncated=True,
                  complete=False, repository_checked=True)
    return result


def _corroborate_timeline(container, legacy, typed=None):
    """Validate both retained transports and every supplied legacy binding edge."""
    records = legacy.get("records")
    if not isinstance(records, list):
        container["bindings_complete"] = False
        container["binding_malformed_fields"] = sorted(set(container["binding_malformed_fields"]) | {"timeline.records"})
        return False
    typed_records = typed.get("records") if isinstance(typed, dict) else container.get("records", [])
    typed_records = typed_records if isinstance(typed_records, list) else []
    index, typed_index = {}, {}
    for record in records:
        if isinstance(record, dict) and _guid(record.get("id")):
            index.setdefault(record["id"].lower(), []).append(record)
    for record in typed_records:
        if isinstance(record, dict) and _guid(record.get("id")):
            typed_index.setdefault(record["id"].lower(), []).append(record)
    paired = (len(records) == len(typed_records)
              and {key: len(values) for key, values in index.items()} == {key: len(values) for key, values in typed_index.items()})
    if not paired:
        container["bindings_complete"] = False
        container["binding_malformed_fields"] = sorted(set(container["binding_malformed_fields"]) | {"timeline.records"})
        # Retain the known observation lower bound, without inventing a native
        # original count when the two declarations contradict one another.
        container["record_count"] = max(container["record_count"], len(records))
        container["returned_record_count"] = None
        container["records_truncated"] = True
    validators = {"state": lambda v: _choice(v, _TIMELINE_STATES),
                  "result": lambda v: _choice(v, _TIMELINE_RESULTS),
                  "type": lambda v: _choice(v, _TIMELINE_TYPES), "parent_id": _guid, "attempt": _positive}
    native_bindings = {}
    recognized = True
    for native in records:
        nb = _Binding()
        if not isinstance(native, dict) or not _guid(native.get("id")):
            nb.malformed.add("timeline.id")
            container["binding_malformed_fields"] = sorted(set(container["binding_malformed_fields"]) | nb.malformed)
            container["bindings_complete"] = False
            recognized = False
            continue
        identifier = native["id"].lower()
        recognized = recognized and _choice(native.get("state"), _TIMELINE_STATES) and (native.get("result") is None or _choice(native.get("result"), _TIMELINE_RESULTS)) and not (native.get("state") == "completed" and native.get("result") is None)
        counterparts = typed_index.get(identifier, [])
        counterpart = counterparts[0] if len(counterparts) == 1 else {}
        if len(index[identifier]) != 1:
            nb.malformed.add("timeline.duplicate_id")
        for public, raw in (("state", "state"), ("result", "result"), ("type", "type"), ("parent_id", "parentId"), ("attempt", "attempt")):
            value = native.get(raw)
            if value is None:
                if public == "state" or (public == "result" and native.get("state") == "completed"):
                    nb.missing.add("timeline." + public)
                continue
            if not validators[public](value):
                nb.malformed.add("timeline." + public)
                continue
            if public == "parent_id":
                value = value.lower()
            if counterpart.get(public) is None:
                nb.missing.add("timeline." + public)
                if public == "parent_id":
                    nb.missing.add("timeline.parent_resolution")
            elif type(value) is not type(counterpart[public]) or value != counterpart[public]:
                nb.malformed.add("timeline." + public)
        parent = native.get("parentId")
        if _guid(parent) and parent.lower() in index:
            parents = index[parent.lower()]
            if len(parents) != 1:
                nb.malformed.add("timeline.parent_resolution")
            else:
                child_type = native.get("type") if native.get("type") is not None else counterpart.get("type")
                parent_type = parents[0].get("type")
                if parent_type is None and len(typed_index.get(parent.lower(), [])) == 1:
                    parent_type = typed_index[parent.lower()][0].get("type")
                allowed = {"Stage": _TIMELINE_TYPES, "Phase": {"Stage", "Phase"}, "Job": {"Stage", "Phase"}, "Task": {"Job"}}
                if _choice(child_type, _TIMELINE_TYPES) and not _choice(parent_type, allowed[child_type]):
                    nb.malformed.add("timeline.parent_resolution")
        # Follow all visible legacy edges, including edges omitted by a typed
        # root and edges on unmatched records. Hidden capped ancestry remains
        # under the separately checked producer-fact trust boundary.
        seen, cursor = set(), identifier
        while cursor in index and len(index[cursor]) == 1:
            if cursor in seen:
                nb.malformed.add("timeline.parent_resolution")
                break
            seen.add(cursor)
            parent = index[cursor][0].get("parentId")
            if not _guid(parent):
                break
            cursor = parent.lower()
        native_bindings.setdefault(identifier, []).append(nb)
        container["binding_missing_fields"] = sorted(set(container["binding_missing_fields"]) | nb.missing)
        container["binding_malformed_fields"] = sorted(set(container["binding_malformed_fields"]) | nb.malformed)
        if nb.missing or nb.malformed:
            container["bindings_complete"] = False
    container["states_recognized"] = container["states_recognized"] and recognized
    if not recognized:
        container["binding_malformed_fields"] = sorted(set(container["binding_malformed_fields"]) | {"timeline.records"})
    for record in container.get("records", []):
        diagnostics = _Binding()
        diagnostics.diagnostics(record, "timeline.records", "timeline")
        matches = native_bindings.get(record.get("id"), [])
        if not matches:
            diagnostics.missing.add("timeline.id")
        for native_binding in matches:
            diagnostics.merge(native_binding)
        diagnostics.emit(record)
        for key in ("binding_missing_fields", "binding_malformed_fields"):
            container[key] = sorted(set(container[key]) | set(record[key]))
        container["bindings_complete"] = container["bindings_complete"] and record["bindings_complete"]
    malformed = set(container["binding_malformed_fields"])
    container["binding_missing_fields"] = sorted(set(container["binding_missing_fields"]) - malformed)
    return paired
