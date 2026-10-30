#!/usr/bin/env python3
"""Inert MCP proposals for the maintained Azure runtime entrypoints.

This bridge describes operations and binds local inputs. It does not authenticate,
run subprocesses, issue authority, or replace the adapter's exact signed grants.
"""
from __future__ import annotations

import hashlib
import json
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
    result: dict[str, Any] = {"schema_version": "atlas-tools.azure-result.v1", "operation": operation,
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

    try:
        body = json.loads(raw_output, object_pairs_hook=pairs,
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
            repository = _project_repository_evidence(proposal, body.get("repository_evidence"))
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
        if state == "prepared" and isinstance(expected_evidence, str):
            expected = Path(expected_evidence)
            root = Path(proposal.get("runtime_dir", "/unavailable"))
            if expected.is_absolute() and ".." not in expected.parts and root in expected.parents:
                result["expected_evidence_directory"] = expected_evidence
        number = body.get("pull_request_id")
        targets = proposal.get("targets")
        target = targets[0] if isinstance(targets, list) and targets else None
        if type(number) is int and 0 < number <= 2**31 - 1 and isinstance(target, str):
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
    return result


def _project_repository_evidence(proposal: dict[str, Any], evidence: Any) -> dict[str, Any]:
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
    result["repository_matches_profile"] = matches
    if not isinstance(repository, dict):
        result["missing_fields"].append("repository")
    elif not matches:
        result["omitted_fields"].append("repository_identity")
    if matches and isinstance(repository.get("id"), str) and re.fullmatch(guid_pattern, repository["id"]):
        result["repository_id"] = repository["id"]
    if type(evidence.get("complete")) is bool:
        result["reported_complete"] = evidence["complete"]
    else:
        result["omitted_fields"].append("complete")
    selected = proposal.get("options", {}).get("build_ids", [])
    selected = selected if isinstance(selected, list) and all(positive(value) for value in selected) else []
    selected_ids = set(selected)
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
        if selected_ids and name in {"builds", "timelines"}:
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
                   "pull-request-policy-evidence-budget-exhausted", "pull-request-or-project-identity-missing", "timeline-evidence-budget-exhausted"}
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
