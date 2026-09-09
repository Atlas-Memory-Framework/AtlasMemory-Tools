"""Assemble an honest, bounded Azure intake from declared source and Board facts.

This module does not choose task commands, infer approvals, authenticate, execute
models, or write state. A structurally valid intake can still be blocked by its
native dependency graph, missing human decisions, or separate execution grants.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any

from atlas_authority import AuthorityError, canonical_digest, strict_json_loads
from atlas_azure_devops import AzureError, AzureBoardsProvider, AzureDevOpsClient, azure_cli_headers
from atlas_azure_worker import WorkerBlocked, validate_command
from atlas_dispatch import (DispatchBlocked, MAX_CONTEXT_FILES, MAX_FILE_BYTES, MAX_INPUT_BYTES,
                            _safe_relative, collect_context)
from atlas_human_gates import HumanGateError, validate_gates
from atlas_routing import RoutingError, decide_route, validate_intake, validate_policy
from atlas_runtime_config import (RuntimeConfig, RuntimeConfigError, load_runtime_config,
                                  require_capability, validate_input_path, validate_runtime_path)


class IntakeError(ValueError):
    """Untrusted input cannot be assembled within the declared boundary."""


def _text(value: Any, label: str, maximum=4000) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or len(value) > maximum:
        raise IntakeError(label + " requires bounded nonempty text")
    return value


def _canonical_text(value: Any) -> str:
    canonical_digest(value)  # Enforce shared type/size limits before serialization.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _copy(value: Any) -> Any:
    return strict_json_loads(_canonical_text(value))


def read_json(path: str | Path) -> dict[str, Any]:
    source = validate_input_path(path)
    if source.stat().st_size > 250_000:
        raise IntakeError("input exceeds the bounded JSON limit")
    value = strict_json_loads(source.read_bytes())
    if not isinstance(value, dict):
        raise IntakeError("input must be a JSON object")
    return value


def _time(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise IntakeError("observation time must be a finite epoch timestamp")
    return float(value)


def _snapshot_time(snapshot: dict[str, Any]) -> float | None:
    try:
        value = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
        return value.timestamp() if value.tzinfo is not None else None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _without_observations(value: Any) -> Any:
    """Ignore only transport observations, never dates inside source text."""
    if isinstance(value, dict):
        return {key: _without_observations(item) for key, item in value.items() if key != "observed_at"}
    if isinstance(value, list):
        return [_without_observations(item) for item in value]
    return value


def material_fingerprint(config: RuntimeConfig, policy: dict[str, Any], definition: dict[str, Any],
                         snapshot: dict[str, Any] | None, evidence: list[dict[str, Any]]) -> str:
    sources = [{key: item[key] for key in ("id", "kind", "path", "sha256", "revision")}
               for item in evidence if item["kind"] != "dependencies"]
    return canonical_digest({"configuration": config.report(), "policy": policy, "definition": definition,
                             "snapshot": _without_observations(snapshot), "sources": sources})


def _source(identifier: str, kind: str, content: str, path: str | None, observed: float, revision: int | None):
    return {"id": identifier, "kind": kind, "content": content, "path": path,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "observed_at": observed, "revision": revision}


def _owned_source(path: Path, root: Path, *, directory: bool = False) -> None:
    """Check parents before the leaf, so an unsafe parent is never traversed."""
    if path != root and root not in path.parents:
        raise DispatchBlocked("primary source escapes its explicit repository root")
    current = root
    components = [root, *(root.joinpath(*path.relative_to(root).parts[:index])
                           for index in range(1, len(path.relative_to(root).parts) + 1))]
    for current in components:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
            raise DispatchBlocked("primary source ancestry must be owned and contain no symlinks")
        if current != path and not stat.S_ISDIR(info.st_mode):
            raise DispatchBlocked("primary source ancestor is not a directory")
    if directory and not stat.S_ISDIR(info.st_mode):
        raise DispatchBlocked("primary source directory is unavailable")


def _definition(value: Any) -> dict[str, Any]:
    allowed = {"schema_version", "worker_packet", "step", "sources", "affected_paths", "points",
               "human_gates", "human_answers", "attempts", "budget", "owner"}
    if not isinstance(value, dict) or set(value) - allowed or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise IntakeError("definition requires schema_version 1 and supported explicit fields")
    if not isinstance(value.get("worker_packet"), dict):
        raise IntakeError("definition requires an explicit draft worker packet")
    if "sources" in value and (not isinstance(value["sources"], list) or len(value["sources"]) > MAX_CONTEXT_FILES):
        raise IntakeError("declared primary sources exceed the file budget")
    if "human_answers" in value and (not isinstance(value["human_answers"], list) or len(value["human_answers"]) > 32):
        raise IntakeError("human answers require a bounded explicit list")
    return _copy(value)


def _declared_sources(definition, context_root: Path, observed: float):
    evidence, ids, paths, unavailable = [], set(), set(), []
    for entry in definition.get("sources", []):
        if not isinstance(entry, dict) or set(entry) != {"id", "kind", "path"}:
            raise IntakeError("source declaration requires exactly id, kind and path")
        identifier = _text(entry["id"], "source ID", 120)
        if identifier in ids or identifier in {"issue", "dependencies"} or identifier.startswith("human-answer:"):
            raise IntakeError("declared source ID is duplicated or reserved")
        if entry["kind"] not in {"file", "file_missing", "instructions", "tests"}:
            raise IntakeError("source kind must describe file, absence, instructions or tests")
        relative = _safe_relative(entry["path"])
        path = relative.as_posix()
        if path in paths:
            raise IntakeError("the same primary file must not be declared more than once")
        ids.add(identifier)
        paths.add(path)
        target = context_root.joinpath(*relative.parts)
        if entry["kind"] == "file_missing":
            try:
                _owned_source(target.parent, context_root, directory=True)
            except FileNotFoundError:
                unavailable.append(path)
                continue
            try:
                target.lstat()
                present = True
            except FileNotFoundError:
                present = False
            if present:
                raise IntakeError("declared missing file now exists; refresh the definition")
            content = ""
        else:
            try:
                _owned_source(target, context_root)
            except FileNotFoundError:
                unavailable.append(path)
                continue
            if not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
                raise IntakeError("declared source is unavailable or exceeds the bounded text limit")
            try:
                content = target.read_bytes().decode("utf-8")
            except UnicodeDecodeError as exc:
                raise IntakeError("declared source must be UTF-8 text") from exc
        evidence.append(_source(identifier, entry["kind"], content, path, observed, None))
    return evidence, unavailable


def _intake_material(intake):
    value = deepcopy(intake)
    value["readiness"].pop("observed_at", None)
    value["readiness"].pop("source_sha256", None)
    for source in value["evidence"]:
        source.pop("observed_at", None)
        if source["kind"] == "dependencies":
            snapshot = _without_observations(strict_json_loads(source["content"]))
            source["content"] = _canonical_text(snapshot)
            source["sha256"] = canonical_digest(snapshot)
    return value


def _required_instructions(root: Path, affected_paths: list[str]) -> list[str]:
    parents = {root}
    for raw in affected_paths:
        relative = _safe_relative(raw)
        cursor = root.joinpath(*relative.parts).parent
        while cursor == root or root in cursor.parents:
            parents.add(cursor)
            if cursor == root:
                break
            cursor = cursor.parent
    required = []
    for parent in sorted(parents):
        try:
            _owned_source(parent, root, directory=True)
            path = parent / "AGENTS.md"
            _owned_source(path, root)
        except FileNotFoundError:
            continue
        required.append(path.relative_to(root).as_posix())
    return sorted(required)


def _snapshot_item(config, snapshot, identifier):
    if snapshot is None:
        return None
    if not isinstance(snapshot, dict) or type(snapshot.get("complete")) is not bool or type(snapshot.get("dependency_complete")) is not bool:
        raise IntakeError("snapshot requires explicit complete and dependency_complete booleans")
    if not isinstance(snapshot.get("items"), list) or not isinstance(snapshot.get("blockers"), list):
        raise IntakeError("snapshot requires normalized item records and blockers")
    for field, expected in (("provider", "azure-devops"), ("organization", config.repository["organization"]), ("project", config.repository["project"])):
        if field in snapshot and snapshot[field] != expected:
            raise IntakeError("snapshot targets a different provider or namespace")
    namespace = f"azdo:{config.repository['organization']}:{config.repository['project']}:"
    found, ids = None, set()
    for item in snapshot["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not re.fullmatch(re.escape(namespace) + r"[1-9][0-9]*", item["id"]):
            raise IntakeError("snapshot item must preserve its exact Azure namespace")
        if item["id"] in ids:
            raise IntakeError("snapshot contains duplicate work-item records")
        ids.add(item["id"])
        if type(item.get("eligible")) is not bool or not isinstance(item.get("blockers"), list):
            raise IntakeError("snapshot item eligibility must be explicit normalized evidence")
        for name in ("dependencies", "native_dependencies", "native_successors"):
            if name in item and (not isinstance(item[name], list) or any(not isinstance(dep, str) or not re.fullmatch(re.escape(namespace) + r"[1-9][0-9]*", dep) for dep in item[name])):
                raise IntakeError("native dependency IDs are invalid or cross namespaces")
        if item["id"] == identifier:
            found = item
    return found


def build_intake(config: RuntimeConfig, policy: dict[str, Any], definition: dict[str, Any],
                 snapshot: dict[str, Any] | None, *, context_root: str | Path,
                 previous: dict[str, Any] | None = None, now: float | None = None) -> dict[str, Any]:
    """Return a valid-but-possibly-blocked intake or an actionable truthful draft.

    Packet revision, commands, gate templates and existing answers are never
    silently rebound. Reuse preserves the *entire* old exact intake and snapshot
    only when newly read material is unchanged and both observations are fresh.
    """
    timestamp = _time(time.time() if now is None else now)
    validate_policy(policy)
    definition = _definition(definition)
    snapshot = _copy(snapshot) if snapshot is not None else None
    if config.provider != "azure-devops" or policy["repository_url"] != config.repository.get("url"):
        raise IntakeError("intake requires matching explicit Azure configuration and policy")
    root = validate_runtime_path(context_root)
    packet = deepcopy(definition["worker_packet"])
    identifier = packet.get("id")
    namespace = f"azdo:{config.repository['organization']}:{config.repository['project']}:"
    if not isinstance(identifier, str) or not re.fullmatch(re.escape(namespace) + r"[1-9][0-9]*", identifier):
        raise IntakeError("draft packet must select one exact namespaced Azure work item")
    for field, expected in (("repository_url", config.repository["url"]), ("base_branch", config.repository["base_branch"]), ("schema_version", 1)):
        if field in packet and (type(packet[field]) is not type(expected) or packet[field] != expected):
            raise IntakeError("draft packet conflicts with configured repository or schema")
        packet.setdefault(field, expected)
    owner = definition.get("owner")
    missing, questions, blockers = [], [], []
    def require(field, question):
        if field not in missing:
            missing.append(field)
            questions.append({"field": field, "owner": owner if isinstance(owner, str) and owner.strip() else None, "question": question})
    if not isinstance(owner, str) or not owner.strip():
        require("owner", "Who owns the scope and acceptance decisions for this work item?")
    else:
        _text(owner, "intake owner", 240)
    selected = _snapshot_item(config, snapshot, identifier)
    observed = _snapshot_time(snapshot) if snapshot else None
    age_limit = min(300, policy["limits"]["evidence_max_age_seconds"])
    if observed is None:
        require("snapshot.observed_at", "Refresh the complete normalized Azure dependency inspection before routing.")
    elif not 0 <= timestamp - observed <= age_limit:
        blockers.append("snapshot-is-stale-or-future-dated")
    revision = selected.get("revision") if selected else None
    if type(revision) is not int or revision < 1:
        require("snapshot.issue_revision", "Read the selected native work item and its current revision within the full dependency inspection.")
    elif "revision" in packet and (type(packet["revision"]) is not int or packet["revision"] != revision):
        require("worker_packet.revision", "The Board revision changed; review the updated task and explicitly rebind its packet and gates.")
    else:
        packet.setdefault("revision", revision)
    for name, question in (("task", "What precise behavior should this bounded task implement?"),
                           ("base_commit", "Which exact reviewed base commit anchors this task?"),
                           ("branch", "Which isolated feature branch will hold the local candidate?"),
                           ("write_scope", "Which exact files or directory scopes may the worker change?"),
                           ("commands", "Which reviewed acceptance commands should run, with argv and time limits?"),
                           ("acceptance", "Which candidate-bound evidence must each acceptance command produce?"),
                           ("role_timeout_seconds", "What bounded timeout applies to each worker role?")):
        if not packet.get(name):
            require("worker_packet." + name, question)
    for command in packet.get("commands", []) if isinstance(packet.get("commands"), list) else []:
        try:
            validate_command(command.get("argv") if isinstance(command, dict) else None)
        except WorkerBlocked:
            require("worker_packet.commands", "Replace unsafe or unavailable command definitions with explicit reviewed bounded argv.")
    paths = definition.get("affected_paths")
    if not isinstance(paths, list) or not paths:
        paths = []
        require("affected_paths", "Which concrete source paths are affected and need primary evidence?")
    if len(paths) > 200 or any(not isinstance(path, str) for path in paths):
        raise IntakeError("affected paths require a bounded list of repository-relative paths")
    for path in paths:
        _safe_relative(path)
    evidence, unavailable_sources = _declared_sources(definition, root, timestamp)
    for path in unavailable_sources:
        require("sources.unavailable:" + path, "Refresh the declaration for unavailable primary source " + path + ".")
    declared_instructions = {item["path"] for item in evidence if item["kind"] == "instructions"}
    required_instructions = _required_instructions(root, paths)
    for path in required_instructions:
        if path not in declared_instructions:
            require("sources.instructions:" + path, "Declare the applicable " + path + " as primary instruction evidence.")
    if not declared_instructions:
        require("sources.instructions", "Declare the applicable repository instruction files for this task.")
    covered = {item["path"] for item in evidence if item["kind"] in {"file", "file_missing"}}
    for path in paths:
        if path not in covered:
            require("sources.file:" + path, "Declare current content or explicit absence evidence for " + path + ".")
    if not any(item["kind"] == "tests" for item in evidence):
        require("sources.tests", "Declare the actual test or acceptance implementation to substantiate the verification plan.")
    gates = deepcopy(definition.get("human_gates", []))
    try:
        validate_gates(gates)
        if any(gate["issue_id"] != identifier or gate["issue_revision"] != revision for gate in gates):
            require("human_gates", "Review changed issue revisions and supply newly bound human gate templates; existing approvals cannot be carried forward.")
    except HumanGateError:
        require("human_gates", "Each human step needs an explicit owner, question, action, exact artifact and issue/candidate binding.")
    if selected is not None and type(revision) is int:
        evidence.insert(0, _source("issue", "issue", _canonical_text(selected), None, observed, revision))
    if snapshot is not None and observed is not None:
        evidence.insert(1 if evidence else 0, _source("dependencies", "dependencies", _canonical_text(snapshot), None, observed, revision if type(revision) is int else None))
    answers = definition.get("human_answers", [])
    answer_ids = set()
    for answer in answers:
        if not isinstance(answer, dict) or set(answer) != {"gate_id", "response"} or answer["gate_id"] in answer_ids:
            raise IntakeError("human answer requires one unique gate ID and explicit response")
        answer_ids.add(answer["gate_id"])
        if answer["gate_id"] not in {gate.get("id") for gate in gates if isinstance(gate, dict)}:
            raise IntakeError("human answer has no declared gate")
        _text(answer["response"], "human answer", 16000)
        evidence.append(_source("human-answer:" + answer["gate_id"], "issue", _canonical_text(answer), None, timestamp, revision if type(revision) is int else None))
    for name, question in (("step", "What action and bounded step kind should this item perform?"),
                           ("budget", "What model-call and observed-token budgets apply to this item?")):
        if not isinstance(definition.get(name), dict) or not definition[name]:
            require(name, question)
    clear = bool(snapshot and selected and snapshot["complete"] and snapshot["dependency_complete"] and not snapshot["blockers"] and selected["eligible"] and not selected["blockers"])
    annotated_authority = packet.get("inspection_authority", {})
    if not isinstance(annotated_authority, dict):
        annotated_authority = {}
    execution_annotation = clear and annotated_authority.get("execution_authorized") is True and isinstance(annotated_authority.get("approval_record"), str) and bool(annotated_authority["approval_record"].strip())
    readiness = {"issue_revision": revision, "observed_at": observed, "complete": snapshot["complete"] if snapshot else False,
        "dependency_complete": snapshot["dependency_complete"] if snapshot else False,
        "dependencies_satisfied": clear, "execution_authority_established": bool(execution_annotation),
        "source_sha256": canonical_digest(snapshot) if snapshot else None}
    intake = {"schema_version": 1, "worker_packet": packet, "step": deepcopy(definition.get("step")),
        "evidence": evidence, "readiness": readiness, "affected_paths": paths, "points": definition.get("points"),
        "human_gates": gates, "attempts": deepcopy(definition.get("attempts", [])), "budget": deepcopy(definition.get("budget"))}
    try:
        collect_context(intake, root)
    except (DispatchBlocked, OSError):
        require("sources.context_bounds", "Reduce or correct declared primary evidence to fit the existing non-secret dispatcher context boundary.")
    if not missing:
        try:
            validate_intake(intake)
        except RoutingError as exc:
            require("intake.validation", "Resolve the bounded intake validation requirement: " + str(exc))
    material = material_fingerprint(config, policy, definition, snapshot, evidence)
    decision = decide_route(intake, policy, now=timestamp) if not missing else None
    if decision:
        blockers.extend(decision["blockers"])
    elif snapshot:
        blockers.extend(snapshot["blockers"])
        if selected:
            blockers.extend(selected["blockers"])
    report = {"schema_version": 1, "state": "draft" if missing else "blocked" if blockers else "ready_for_routing",
        "valid": not missing, "completion": False, "execution_authorized": False, "effects": [], "reused": False,
        "owner": owner if isinstance(owner, str) else None, "issue_id": identifier, "issue_revision": revision,
        "material_fingerprint": material, "definition_sha256": canonical_digest(definition),
        "policy_sha256": canonical_digest(policy), "effective_config_sha256": canonical_digest(config.report()),
        "context_root": str(root), "observed_at": timestamp, "missing_fields": missing, "human_questions": questions,
        "blockers": sorted(set(blockers)), "instruction_coverage": {"required": required_instructions, "declared": sorted(declared_instructions)},
        "intake": intake if not missing else None, "snapshot": snapshot,
        "intake_sha256": canonical_digest(intake) if not missing else None,
        "snapshot_sha256": canonical_digest(snapshot) if snapshot else None, "decision": decision,
        "draft": {"worker_packet": packet, "step": definition.get("step"), "missing_fields": missing} if missing else None,
        "native_dependencies": deepcopy(selected.get("native_dependencies", selected.get("dependencies", []))) if selected else [],
        "current_observation": {"observed_at": observed, "snapshot_sha256": canonical_digest(snapshot) if snapshot else None},
        "authority_note": "Inspection annotations and intake assembly grant no execution authority; signed operation grants remain separate."}
    if (previous and report["valid"] and observed is not None and 0 <= timestamp - observed <= age_limit
            and previous.get("material_fingerprint") == material and previous.get("valid") is True):
        old_intake, old_snapshot = previous.get("intake"), previous.get("snapshot")
        try:
            validate_intake(old_intake)
            old_time = _snapshot_time(old_snapshot)
            if old_time is None or not 0 <= timestamp - old_time <= age_limit:
                return report
            if canonical_digest(old_intake) != previous.get("intake_sha256") or canonical_digest(old_snapshot) != previous.get("snapshot_sha256"):
                return report
            if material_fingerprint(config, policy, definition, old_snapshot, old_intake["evidence"]) != material:
                return report
            if canonical_digest(_intake_material(old_intake)) != canonical_digest(_intake_material(intake)):
                return report
            collect_context(old_intake, root)
            old_decision = decide_route(old_intake, policy, now=timestamp)
            if canonical_digest(old_decision["blockers"]) != canonical_digest(decision["blockers"]) or canonical_digest(old_snapshot) != old_intake["readiness"]["source_sha256"]:
                return report
            # Exact old packet/evidence/snapshot stays paired; the new read is
            # reported separately and cannot silently change grant bindings.
            report.update(intake=deepcopy(old_intake), snapshot=deepcopy(old_snapshot),
                          intake_sha256=previous["intake_sha256"], snapshot_sha256=previous["snapshot_sha256"],
                          decision=old_decision, reused=True)
        except (ValueError, TypeError, KeyError, OSError, DispatchBlocked):
            pass  # Invalid previous state never prevents a truthful fresh draft.
    return report


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "runtime-dir", "policy", "definition", "context-root"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--snapshot", help="Explicit normalized Azure inspector JSON; no live access by default.")
    parser.add_argument("--previous", help="Prior intake report for exact still-fresh material reuse.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Inert local assembly, also the default.")
    mode.add_argument("--live-read", action="store_true", help="Explicit fresh read-only Azure closure inspection; never executes models or writes Board state.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        config = load_runtime_config(args.config, runtime_dir=args.runtime_dir)
        policy, definition = read_json(args.policy), read_json(args.definition)
        previous = read_json(args.previous) if args.previous else None
        if args.live_read and args.snapshot:
            raise IntakeError("live read and supplied snapshot cannot be combined")
        snapshot = read_json(args.snapshot) if args.snapshot else None
        if args.live_read:
            # Validate the explicit local definition and source boundary before
            # any credential or network access; a truthful missing-fields draft
            # remains a supported live read-only pilot outcome.
            build_intake(config, policy, definition, None, context_root=args.context_root)
            require_capability(config, "read")
            packet = definition["worker_packet"]
            client = AzureDevOpsClient(config.repository["organization"], config.repository["project"], config.runtime_dir,
                                       headers=azure_cli_headers(), capabilities={"read"})
            snapshot = AzureBoardsProvider(client).inspect([packet["id"]], expected_manifest=packet.get("expected_manifest"),
                supplement=packet.get("supplement"), authority=packet.get("inspection_authority"), fresh=True)
        report = build_intake(config, policy, definition, snapshot, context_root=args.context_root, previous=previous)
        report["mode"] = "live-read-only" if args.live_read else "preview"
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    except (IntakeError, RuntimeConfigError, RoutingError, HumanGateError, AuthorityError, AzureError, WorkerBlocked, DispatchBlocked) as exc:
        print(json.dumps({"state": "blocked", "completion": False, "execution_authorized": False, "error": str(exc)}), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print(json.dumps({"state": "blocked", "completion": False, "execution_authorized": False,
                          "error": "intake source, snapshot or definition failed bounded validation"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
