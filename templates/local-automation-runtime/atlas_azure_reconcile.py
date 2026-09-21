"""Exact, revision-tested Azure Boards reconciliation; previews are entirely inert.

An operator-authored proposal is not execution authority. Applying it requires
the board_write capability and an independently verified exact signed grant.
Only named operator-owned tags, named predecessor additions and independently
accepted evidence contracts can change. No worker state is a completion signal.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import tempfile
import time
from typing import Any
from urllib.parse import quote

sys.dont_write_bytecode = True

from atlas_runtime_config import RuntimeConfig, load_runtime_config, require_capability, validate_runtime_path
from atlas_authority import AuthorityError, canonical_digest, strict_json_loads, verify_grant
from atlas_azure_devops import AzureError, _relation_id as native_relation_id, verified_project_alias


PREDECESSOR = "System.LinkTypes.Dependency-Reverse"
SUCCESSOR = "System.LinkTypes.Dependency-Forward"
HEX = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,127}\Z")
AUTO_FIELDS = {
    "System.Rev", "System.ChangedDate", "System.ChangedBy", "System.AuthorizedDate",
    "System.AuthorizedAs", "System.Watermark", "Microsoft.VSTS.Common.StateChangeDate",
    "System.RelatedLinkCount", "System.ExternalLinkCount",
    "Microsoft.VSTS.Common.ClosedDate", "Microsoft.VSTS.Common.ClosedBy",
    "Microsoft.VSTS.Common.ResolvedDate", "Microsoft.VSTS.Common.ResolvedBy",
    "System.Tags", "System.State",
}
MAX_ITEMS = 1000


class ReconcileError(ValueError):
    """A sanitized, fail-closed Board reconciliation error."""


def canonical_sha256(value: Any) -> str:
    return canonical_digest(value)


def _keys(value: Any, required: set[str], optional: set[str] | None = None) -> None:
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - (optional or set()):
        raise ReconcileError("missing or unsupported proposal fields")


def _namespace(organization: str, project: str) -> None:
    if not isinstance(organization, str) or not NAME.fullmatch(organization) or not isinstance(project, str) or not NAME.fullmatch(project):
        raise ReconcileError("invalid Azure organization or project")


def issue_id(number: int, organization: str, project: str) -> str:
    if type(number) is not int or number <= 0:
        raise ReconcileError("work item ID must be a positive integer")
    return f"azdo:{organization}:{project}:{number}"


def issue_number(value: Any, organization: str, project: str) -> int:
    prefix = f"azdo:{organization}:{project}:"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ReconcileError("work item ID must retain its configured Azure namespace")
    suffix = value[len(prefix):]
    if not re.fullmatch(r"[1-9][0-9]*", suffix):
        raise ReconcileError("invalid namespaced Azure work item ID")
    return int(suffix)


def _relation_id(url: Any, organization: str, project: str, *, project_alias: str | None = None) -> str:
    try:
        return native_relation_id(organization, project, url, project_alias=project_alias)
    except AzureError as exc:
        raise ReconcileError("dependency endpoint does not establish the configured Azure project") from exc


def _project_alias(raw: Any, organization: str, project: str) -> str | None:
    try:
        return verified_project_alias(raw, organization, project)
    except AzureError as exc:
        raise ReconcileError("work item self URL does not establish the configured project and item identity") from exc


def _validate_project_aliases(items: list[dict[str, Any]], organization: str, project: str) -> None:
    aliases = {_project_alias(raw, organization, project) for raw in items}
    aliases.discard(None)
    if len(aliases) > 1:
        raise ReconcileError("complete work item read contains conflicting verified project identities")


def project_item(raw: dict[str, Any], organization: str, project: str) -> dict[str, Any]:
    """Retain revision/proof metadata without persisting descriptions or identities."""
    if not isinstance(raw, dict) or not isinstance(raw.get("fields"), dict) or not isinstance(raw.get("relations"), list):
        raise ReconcileError("work item read is incomplete; fields and expanded relations are required")
    fields = raw["fields"]
    if type(raw.get("rev")) is not int or raw["rev"] < 1 or not isinstance(fields.get("System.State"), str):
        raise ReconcileError("work item read is missing a valid revision or state")
    if fields.get("System.TeamProject") != project:
        raise ReconcileError("work item read does not establish the configured project")
    project_alias = _project_alias(raw, organization, project)
    tags = fields.get("System.Tags", "")
    if not isinstance(tags, str):
        raise ReconcileError("work item tags are malformed")
    relations = []
    for relation in raw["relations"]:
        if not isinstance(relation, dict) or not isinstance(relation.get("rel"), str) or not isinstance(relation.get("url"), str):
            raise ReconcileError("work item relation read is incomplete")
        kind = {PREDECESSOR: "predecessor", SUCCESSOR: "successor"}.get(relation["rel"], "other")
        relations.append({
            "kind": kind,
            "target": _relation_id(relation["url"], organization, project, project_alias=project_alias) if kind != "other" else None,
            "sha256": canonical_sha256(relation),
        })
    immutable_fields = {key: value for key, value in fields.items() if key not in AUTO_FIELDS}
    # A native GUID is evidence from this item's own URL and exact project
    # field, never an operator-supplied alias. Bind it through fresh readback
    # without adding private raw data or changing the proposal schema.
    immutable_proof = {"fields": immutable_fields, "verified_project_alias": project_alias} if project_alias is not None else immutable_fields
    return {
        "issue_id": issue_id(raw.get("id"), organization, project), "revision": raw["rev"],
        "state": fields["System.State"], "tags": tags,
        "immutable_fields_sha256": canonical_sha256(immutable_proof),
        "relations": sorted(relations, key=lambda row: (row["kind"], row["target"] or "", row["sha256"])),
    }


def _validate_projection(item: Any, organization: str, project: str) -> None:
    _keys(item, {"issue_id", "revision", "state", "tags", "immutable_fields_sha256", "relations"})
    issue_number(item["issue_id"], organization, project)
    if type(item["revision"]) is not int or item["revision"] < 1 or not isinstance(item["state"], str) or not item["state"]:
        raise ReconcileError("invalid snapshot revision or state")
    if not isinstance(item["tags"], str) or not isinstance(item["immutable_fields_sha256"], str) or not HEX.fullmatch(item["immutable_fields_sha256"]):
        raise ReconcileError("invalid sanitized snapshot metadata")
    if not isinstance(item["relations"], list):
        raise ReconcileError("incomplete sanitized relation read")
    for relation in item["relations"]:
        _keys(relation, {"kind", "target", "sha256"})
        if relation["kind"] not in {"predecessor", "successor", "other"} or not isinstance(relation["sha256"], str) or not HEX.fullmatch(relation["sha256"]):
            raise ReconcileError("invalid sanitized relation metadata")
        if relation["kind"] == "other":
            if relation["target"] is not None:
                raise ReconcileError("unrelated relation payload must remain a digest")
        else:
            issue_number(relation["target"], organization, project)


def _edges(items: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
    return {(key, row["target"]) for key, item in items.items() for row in item["relations"] if row["kind"] == "predecessor"}


def _validate_graph(items: dict[str, dict[str, Any]], additions: set[tuple[str, str]] | None = None) -> None:
    for key, item in items.items():
        seen = set()
        for row in item["relations"]:
            if row["kind"] == "other":
                continue
            marker = (row["kind"], row["target"])
            if marker in seen or row["target"] == key:
                raise ReconcileError("duplicate or self-referencing dependency")
            seen.add(marker)
            reciprocal = "successor" if row["kind"] == "predecessor" else "predecessor"
            other = items.get(row["target"])
            if other is None or not any(r["kind"] == reciprocal and r["target"] == key for r in other["relations"]):
                raise ReconcileError("missing dependency endpoint or reciprocal read")
    graph = {key: set() for key in items}
    for target, prerequisite in _edges(items) | (additions or set()):
        if target not in graph or prerequisite not in graph:
            raise ReconcileError("approved dependency endpoint was not completely read")
        graph[target].add(prerequisite)
    pending = {key: len(value) for key, value in graph.items()}
    ready = [key for key, count in pending.items() if not count]
    done = 0
    while ready:
        node = ready.pop()
        done += 1
        for key, dependencies in graph.items():
            if node in dependencies:
                pending[key] -= 1
                if not pending[key]:
                    ready.append(key)
    if done != len(graph):
        raise ReconcileError("dependency graph contains a cycle")


def _tag_list(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(tag, str) or not tag.strip() or tag != tag.strip() or ";" in tag or len(tag) > 128 for tag in value):
        raise ReconcileError("tag changes must contain explicit individual tags")
    if len({tag.casefold() for tag in value}) != len(value):
        raise ReconcileError("duplicate tag declaration")
    return value


def _desired_tags(before: str, change: dict[str, Any]) -> str:
    remove = {tag.casefold() for tag in change["remove_tags"]}
    current = [tag.strip() for tag in before.split(";") if tag.strip()]
    result = [tag for tag in current if tag.casefold() not in remove]
    for tag in change["add_tags"]:
        if tag.casefold() not in {existing.casefold() for existing in result}:
            result.append(tag)
    return before if result == current else "; ".join(result)


def _acceptance(change: dict[str, Any]) -> dict[str, Any] | None:
    transition = change.get("state_transition")
    if transition is None:
        return None
    _keys(transition, {"to_state", "acceptance"})
    if transition["to_state"] not in {"Done", "Closed"}:
        raise ReconcileError("only an explicitly accepted terminal state transition is supported")
    acceptance = transition["acceptance"]
    _keys(acceptance, {"issue_id", "status", "scope", "candidate", "contract_sha256", "required_checks", "evidence", "human_accepted", "release", "human_gate", "human_receipt"})
    if acceptance["issue_id"] != change["issue_id"] or acceptance["status"] != "accepted" or acceptance["human_accepted"] is not True:
        raise ReconcileError("closure requires the issue's explicit human acceptance")
    if acceptance["scope"] != "release" or not isinstance(acceptance["candidate"], str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", acceptance["candidate"]):
        raise ReconcileError("this adapter only closes independently accepted release issues with an exact candidate")
    release = acceptance["release"]
    _keys(release, {"environment", "pipeline_definition_id", "run_id", "source_version", "artifact_sha256", "package_sha256", "assets_sha256", "database_revision"})
    if release["environment"] not in {"Dev", "Staging", "Production"} or release["source_version"] != acceptance["candidate"] or any(type(release[key]) is not int or release[key] <= 0 for key in ("pipeline_definition_id", "run_id")):
        raise ReconcileError("release acceptance must bind the environment and exact pipeline run/source")
    if any(not isinstance(release[key], str) or not HEX.fullmatch(release[key]) for key in ("artifact_sha256", "package_sha256", "assets_sha256")) or not isinstance(release["database_revision"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", release["database_revision"]):
        raise ReconcileError("release acceptance requires immutable artifact, package, assets and database references")
    if not isinstance(acceptance["contract_sha256"], str) or not HEX.fullmatch(acceptance["contract_sha256"]):
        raise ReconcileError("closure requires a versioned acceptance contract")
    checks = acceptance["required_checks"]
    if not isinstance(checks, list) or not checks or any(not isinstance(check, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", check) for check in checks) or len(checks) != len(set(checks)):
        raise ReconcileError("closure requires nonempty named acceptance checks")
    evidence = acceptance["evidence"]
    if not isinstance(evidence, list) or len(evidence) != len(checks):
        raise ReconcileError("closure is missing acceptance evidence")
    evidence_checks = []
    for row in evidence:
        _keys(row, {"check", "path", "sha256"})
        path = row["path"]
        if not isinstance(path, str) or not path.startswith("evidence/") or Path(path).is_absolute() or ".." in Path(path).parts:
            raise ReconcileError("acceptance evidence must be within the explicit runtime evidence directory")
        if not isinstance(row["sha256"], str) or not HEX.fullmatch(row["sha256"]):
            raise ReconcileError("acceptance evidence is missing its immutable hash")
        evidence_checks.append(row["check"])
        if not isinstance(row["check"], str) or row["check"] not in checks:
            raise ReconcileError("acceptance evidence contains an unknown check")
    if set(evidence_checks) != set(checks) or len(set(evidence_checks)) != len(checks):
        raise ReconcileError("acceptance evidence does not cover the exact required checks")
    from atlas_human_gates import validate_gates
    validate_gates([acceptance["human_gate"]])
    gate = acceptance["human_gate"]
    if gate["kind"] not in {"test", "approval"} or gate["stage"] != "before" or gate["action"] != "completion" or gate["issue_id"] != acceptance["issue_id"] or gate["candidate_sha"] != acceptance["candidate"] or gate["artifact_sha256"] != acceptance_contract_sha256(acceptance):
        raise ReconcileError("closure human gate must bind the exact release acceptance contract and candidate")
    if not isinstance(acceptance["human_receipt"], dict):
        raise ReconcileError("closure requires an independent authenticated human acceptance receipt")
    return acceptance


def acceptance_contract_sha256(acceptance: dict[str, Any]) -> str:
    """Avoid circular signature bindings while retaining all release evidence."""
    return canonical_sha256({key: value for key, value in acceptance.items() if key not in {"human_gate", "human_receipt"}})


def _verify_human_acceptance(change: dict[str, Any], runtime_dir: Path, revision: int, now: float) -> None:
    acceptance = _acceptance(change)
    if acceptance is None:
        return
    from atlas_human_gates import evaluate_gates
    result = evaluate_gates(runtime_dir, [acceptance["human_gate"]], [acceptance["human_receipt"]],
                            {"issue_id": change["issue_id"], "issue_revision": revision,
                             "worker_packet_sha256": acceptance_contract_sha256(acceptance),
                             "candidate_sha": acceptance["candidate"], "action": "completion"},
                            stage="before", now=now)
    if result.get("satisfied") is not True:
        raise ReconcileError("closure human testing or acceptance is missing, stale, rejected or unauthenticated")


def _verify_evidence(change: dict[str, Any], runtime_dir: Path) -> None:
    acceptance = _acceptance(change)
    if acceptance is None:
        return
    for row in acceptance["evidence"]:
        try:
            path = (runtime_dir / row["path"]).resolve(strict=True)
            if runtime_dir not in path.parents or path.stat().st_uid != os.getuid() or not path.is_file():
                raise ReconcileError("acceptance evidence crosses the current runtime identity boundary")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != row["sha256"]:
                raise ReconcileError("acceptance evidence hash changed")
            artifact = strict_json_loads(content)
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            raise ReconcileError("acceptance evidence is unavailable or malformed") from exc
        required = {"schema_version": 1, "kind": "acceptance", "issue_id": acceptance["issue_id"], "status": "passed", "scope": acceptance["scope"], "candidate": acceptance["candidate"], "contract_sha256": acceptance["contract_sha256"], "check": row["check"], "acceptance_satisfied": True, "release": acceptance["release"]}
        if not isinstance(artifact, dict) or canonical_sha256({key: artifact.get(key) for key in required}) != canonical_sha256(required):
            raise ReconcileError("artifact does not establish the issue's actual acceptance")
        commands = artifact.get("commands")
        if not isinstance(commands, list) or not commands:
            raise ReconcileError("acceptance artifact is missing executed validation commands")
        for command in commands:
            if not isinstance(command, dict) or command.get("executed") is not True or type(command.get("exit_code")) is not int or command["exit_code"] != 0 or not isinstance(command.get("argv"), list) or not command["argv"] or any(not isinstance(arg, str) or not arg for arg in command["argv"]):
                raise ReconcileError("acceptance artifact has missing or unsuccessful validation")


def _changes(spec: dict[str, Any], baseline: dict[str, dict[str, Any]], organization: str, project: str) -> list[dict[str, Any]]:
    owned = {tag.casefold() for tag in _tag_list(spec["operator_owned_tags"])}
    approved = spec["approved_dependencies"]
    if not isinstance(approved, list):
        raise ReconcileError("approved dependencies must be an exact list")
    allowed_edges = set()
    for edge in approved:
        _keys(edge, {"issue_id", "predecessor"})
        for endpoint in edge.values():
            issue_number(endpoint, organization, project)
        pair = (edge["issue_id"], edge["predecessor"])
        if pair in allowed_edges:
            raise ReconcileError("duplicate approved dependency")
        allowed_edges.add(pair)
    if not isinstance(spec["changes"], list):
        raise ReconcileError("changes must be an explicit list")
    seen = set()
    changes = []
    for raw in spec["changes"]:
        _keys(raw, {"issue_id"}, {"add_tags", "remove_tags", "add_predecessors", "state_transition"})
        key = raw["issue_id"]
        issue_number(key, organization, project)
        if key not in baseline or key in seen:
            raise ReconcileError("changed item is duplicated or missing from the complete read")
        seen.add(key)
        change = {"issue_id": key, "add_tags": raw.get("add_tags", []), "remove_tags": raw.get("remove_tags", []), "add_predecessors": raw.get("add_predecessors", [])}
        added = {tag.casefold() for tag in _tag_list(change["add_tags"])}
        removed = {tag.casefold() for tag in _tag_list(change["remove_tags"])}
        if (added | removed) - owned or added & removed:
            raise ReconcileError("tag operation exceeds exact operator ownership")
        predecessors = change["add_predecessors"]
        if not isinstance(predecessors, list) or any(not isinstance(value, str) for value in predecessors) or len(predecessors) != len(set(predecessors)):
            raise ReconcileError("predecessor additions must be an exact unique list")
        for predecessor in predecessors:
            issue_number(predecessor, organization, project)
            if (key, predecessor) not in allowed_edges or predecessor not in baseline:
                raise ReconcileError("dependency addition lacks exact authorization or a complete endpoint read")
        if "state_transition" in raw:
            change["state_transition"] = deepcopy(raw["state_transition"])
        _acceptance(change)
        changes.append(change)
    requested = {(change["issue_id"], predecessor) for change in changes for predecessor in change["add_predecessors"]}
    if requested != allowed_edges:
        raise ReconcileError("approved dependencies must equal the exact proposed additions")
    _validate_graph(baseline, requested)
    return sorted(changes, key=lambda change: issue_number(change["issue_id"], organization, project))


def _patches(baseline: dict[str, dict[str, Any]], changes: list[dict[str, Any]], organization: str, project: str) -> list[dict[str, Any]]:
    revisions = {key: item["revision"] for key, item in baseline.items()}
    edges = _edges(baseline)
    patches = []
    for change in changes:
        key = change["issue_id"]
        before = baseline[key]
        patch = [{"op": "test", "path": "/rev", "value": revisions[key]}]
        tags = _desired_tags(before["tags"], change)
        if tags != before["tags"]:
            patch.append({"op": "add", "path": "/fields/System.Tags", "value": tags})
        if change.get("state_transition") and change["state_transition"]["to_state"] != before["state"]:
            patch.append({"op": "add", "path": "/fields/System.State", "value": change["state_transition"]["to_state"]})
        for predecessor in change["add_predecessors"]:
            if (key, predecessor) in edges:
                continue
            number = issue_number(predecessor, organization, project)
            patch.append({"op": "add", "path": "/relations/-", "value": {"rel": PREDECESSOR, "url": f"https://dev.azure.com/{quote(organization, safe='')}/{quote(project, safe='')}/_apis/wit/workItems/{number}"}})
            revisions[predecessor] += 1
            edges.add((key, predecessor))
        if len(patch) > 1:
            revisions[key] += 1
            patches.append({"issue_id": key, "json_patch": patch})
    return patches


def _epoch(value: Any) -> float:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone required")
            value = parsed.timestamp()
        except (ValueError, OverflowError) as exc:
            raise ReconcileError("observation time must be an epoch or timezone-aware ISO timestamp") from exc
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ReconcileError("observation time must be finite")
    return float(value)


def _fresh_timestamp(observed_at: Any, maximum: Any, now: float) -> None:
    observed_at = _epoch(observed_at)
    if type(maximum) is not int or not 1 <= maximum <= 3600:
        raise ReconcileError("proposal requires a finite observation time and a 1–3600 second freshness limit")
    if observed_at > now + 5 or now - observed_at > maximum:
        raise ReconcileError("proposal read is stale or from the future; obtain a fresh proposal and authorization")


def build_proposal(snapshot: dict[str, Any], spec: dict[str, Any], organization: str, project: str, *, now: float | None = None) -> dict[str, Any]:
    """Build a sanitized review packet in memory, without client or filesystem writes."""
    _namespace(organization, project)
    _keys(snapshot, {"complete", "observed_at", "items"})
    _keys(spec, {"operator_owned_tags", "approved_dependencies", "changes"}, {"max_age_seconds"})
    if snapshot["complete"] is not True or not isinstance(snapshot["items"], list) or not 1 <= len(snapshot["items"]) <= MAX_ITEMS:
        raise ReconcileError("proposal requires a bounded complete snapshot")
    _validate_project_aliases(snapshot["items"], organization, project)
    baseline = {}
    for raw in snapshot["items"]:
        item = project_item(raw, organization, project)
        if item["issue_id"] in baseline:
            raise ReconcileError("snapshot contains duplicate work items")
        baseline[item["issue_id"]] = item
    changes = _changes(spec, baseline, organization, project)
    proposal = {
        "schema_version": 1, "provider": "azure-devops", "organization": organization, "project": project,
        "complete": True, "observed_at": snapshot["observed_at"], "max_age_seconds": spec.get("max_age_seconds", 900),
        "operator_owned_tags": spec["operator_owned_tags"], "approved_dependencies": spec["approved_dependencies"],
        "baseline": baseline, "changes": changes, "patches": _patches(baseline, changes, organization, project),
        "execution_eligibility": "blocked",
    }
    validate_proposal(proposal, now=now)
    return proposal


def validate_proposal(proposal: dict[str, Any], *, now: float | None = None) -> str:
    _keys(proposal, {"schema_version", "provider", "organization", "project", "complete", "observed_at", "max_age_seconds", "operator_owned_tags", "approved_dependencies", "baseline", "changes", "patches", "execution_eligibility"})
    if type(proposal["schema_version"]) is not int or proposal["schema_version"] != 1 or proposal["provider"] != "azure-devops" or proposal["complete"] is not True or proposal["execution_eligibility"] != "blocked":
        raise ReconcileError("unsupported, incomplete or execution-authorizing Board proposal")
    organization, project = proposal["organization"], proposal["project"]
    _namespace(organization, project)
    _fresh_timestamp(proposal["observed_at"], proposal["max_age_seconds"], time.time() if now is None else now)
    baseline = proposal["baseline"]
    if not isinstance(baseline, dict) or not 1 <= len(baseline) <= MAX_ITEMS:
        raise ReconcileError("proposal lacks a bounded complete baseline")
    for key, item in baseline.items():
        _validate_projection(item, organization, project)
        if key != item["issue_id"]:
            raise ReconcileError("snapshot namespace does not match its item")
    changes = _changes(proposal, baseline, organization, project)
    if changes != proposal["changes"] or _patches(baseline, changes, organization, project) != proposal["patches"]:
        raise ReconcileError("exact patches or normalized changes do not match the reviewed proposal")
    return canonical_sha256(proposal)


def _same(before: dict[str, Any], current: dict[str, Any]) -> bool:
    return canonical_sha256(before) == canonical_sha256(current)


def _check_after(before: dict[str, Any], after: dict[str, Any], change: dict[str, Any]) -> None:
    key = change["issue_id"]
    added = {(key, predecessor) for predecessor in change["add_predecessors"]} - _edges(before)
    if set(before) != set(after):
        raise ReconcileError("post-write endpoint read is incomplete")
    for item_id, old in before.items():
        current = after[item_id]
        expected_revision = old["revision"] + int(item_id == key or any(predecessor == item_id for _, predecessor in added))
        state = change.get("state_transition", {}).get("to_state", old["state"]) if item_id == key else old["state"]
        tags = _desired_tags(old["tags"], change) if item_id == key else old["tags"]
        if current["revision"] != expected_revision or current["immutable_fields_sha256"] != old["immutable_fields_sha256"] or current["state"] != state or current["tags"] != tags:
            raise ReconcileError("revision or preserved human field changed during reconciliation")
        old_relations = Counter(row["sha256"] for row in old["relations"])
        new_relations = Counter(row["sha256"] for row in current["relations"])
        if old_relations - new_relations:
            raise ReconcileError("an existing relation changed during reconciliation")
        extras = new_relations - old_relations
        semantic_extras = Counter((row["kind"], row["target"]) for row in current["relations"] if extras[row["sha256"]])
        expected_extras = Counter()
        for target, prerequisite in added:
            if item_id == target:
                expected_extras[("predecessor", prerequisite)] += 1
            if item_id == prerequisite:
                expected_extras[("successor", target)] += 1
        if semantic_extras != expected_extras:
            raise ReconcileError("post-write relations exceed the approved exact dependency effects")
    _validate_graph(after)


def _read_current(client: Any, proposal: dict[str, Any], clock: Any) -> dict[str, Any]:
    requested_at = clock()
    ids = [issue_number(key, proposal["organization"], proposal["project"]) for key in proposal["baseline"]]
    result = client.get_work_items(ids, fresh=True)
    observed_at = _epoch(result.observed_at)
    if result.complete is not True or getattr(result, "blockers", None) or observed_at < requested_at - 1 or observed_at > clock() + 5 or getattr(result, "cache_hit", False):
        raise ReconcileError("fresh complete work item read could not be established")
    _validate_project_aliases(result.items, proposal["organization"], proposal["project"])
    current = {}
    for raw in result.items:
        item = project_item(raw, proposal["organization"], proposal["project"])
        if item["issue_id"] in current:
            raise ReconcileError("fresh read contains duplicate work items")
        current[item["issue_id"]] = item
    if set(current) != set(proposal["baseline"]):
        raise ReconcileError("fresh read omitted or substituted a dependency endpoint")
    _validate_graph(current)
    return current


def _owned_regular(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ReconcileError("reconciliation journal must be a private file owned by this identity")


@contextmanager
def _journal_lock(runtime_dir: Path):
    directory = runtime_dir / "azure-reconcile"
    if directory.is_symlink():
        raise ReconcileError("reconciliation state directory cannot be a symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_uid != os.getuid() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise ReconcileError("reconciliation state directory must be private and owned by this identity")
    lock_path = directory / ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        _owned_regular(lock_path)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReconcileError("another Board reconciliation owns this runtime; retry inspection after it finishes") from None
        yield directory
    finally:
        os.close(fd)


def _write_journal(path: Path, journal: dict[str, Any]) -> None:
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(journal, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _receipt(proposal: dict[str, Any], packet_hash: str, journal: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "provider": "azure-devops", "packet_sha256": packet_hash, "status": status,
        "execution_eligibility": "blocked", "release_completion_inferred": False,
        "items": [{"issue_id": entry["issue_id"], "status": entry["status"], "revision_before": entry["before"][entry["issue_id"]]["revision"], "revision_after": entry.get("after", {}).get(entry["issue_id"], {}).get("revision")} for entry in journal["entries"]],
        "proposed_patch_count": len(proposal["patches"]),
    }


def authorization_bindings(proposal: dict[str, Any], config: RuntimeConfig, runtime_dir: Path) -> dict[str, Any]:
    """Return the exact Board grant subject without validating or issuing a grant."""
    if not isinstance(config, RuntimeConfig) or config.provider != "azure-devops" or config.runtime_dir != runtime_dir:
        raise ReconcileError("Board apply requires the exact explicit Azure runtime configuration")
    repository = config.repository
    if repository.get("organization") != proposal["organization"] or repository.get("project") != proposal["project"]:
        raise ReconcileError("Board proposal namespace differs from configured repository authority")
    bindings = {"schema_version": 1, "proposal_sha256": canonical_sha256(proposal),
                "organization": proposal["organization"], "project": proposal["project"],
                "repository_url": repository["url"], "runtime_dir": str(runtime_dir),
                "effective_config_sha256": canonical_sha256(config.report())}
    routing = getattr(config, "routing", None)
    if routing is not None:
        # A Board grant never derives authority from a worker routing decision.
        # Its immutable configuration still binds the selected governing policy.
        bindings["policy_sha256"] = canonical_sha256(routing["policy"])
    return bindings


def _authorize(proposal: dict[str, Any], config: RuntimeConfig, runtime: Path,
               authorization: dict[str, Any] | None, *, now: float) -> None:
    try:
        verify_grant(runtime, authorization, "board_write", authorization_bindings(proposal, config, runtime), now=now)
    except AuthorityError as exc:
        raise ReconcileError("verified exact Board authorization is missing or invalid") from exc


def apply_proposal(proposal: dict[str, Any], client: Any, *, runtime_dir: str | Path,
                   authorized_sha256: str | None = None, capabilities: set[str] | frozenset[str],
                   authorization: dict[str, Any] | None = None, config: RuntimeConfig | None = None,
                   clock: Any = time.time) -> dict[str, Any]:
    """Apply serially with a durable intent journal and fresh reciprocal readback.

    An uncertain write is never replayed in the same call. If its complete
    postcondition is observed, it is recorded as verified. If absent, a later
    explicitly authorized invocation may retry after another fresh read and a
    /rev test. Conflicting/divergent results require a new reviewed proposal.
    """
    packet_hash = validate_proposal(proposal, now=clock())
    if "board_write" not in capabilities or "read" not in capabilities or (authorized_sha256 is not None and (not isinstance(authorized_sha256, str) or not HEX.fullmatch(authorized_sha256) or authorized_sha256 != packet_hash)):
        raise ReconcileError("apply requires read and board_write capabilities and any supplied packet SHA-256 must match exactly")
    if client.organization != proposal["organization"] or client.project != proposal["project"]:
        raise ReconcileError("client namespace does not match the exact Board proposal")
    runtime = validate_runtime_path(runtime_dir)
    if not isinstance(config, RuntimeConfig) or frozenset(capabilities) != config.capabilities:
        raise ReconcileError("Board apply requires its exact runtime configuration and capabilities")
    def authorize_write() -> None:
        validate_proposal(proposal, now=clock())
        _authorize(proposal, config, runtime, authorization, now=clock())
        for change in proposal["changes"]:
            _verify_human_acceptance(change, runtime, proposal["baseline"][change["issue_id"]]["revision"], clock())
    authorize_write()
    for change in proposal["changes"]:
        _verify_evidence(change, runtime)
    from atlas_azure_devops import AzureRevisionConflict, AzureUncertainWrite

    changes = {change["issue_id"]: change for change in proposal["changes"]}
    authorize_write()
    with _journal_lock(runtime) as directory:
        authorize_write()
        path = directory / f"{packet_hash}.json"
        journal = {"schema_version": 1, "packet_sha256": packet_hash, "entries": []}
        if path.exists() or path.is_symlink():
            _owned_regular(path)
            try:
                journal = strict_json_loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ReconcileError("reconciliation journal is unreadable") from exc
        _keys(journal, {"schema_version", "packet_sha256", "entries"})
        if type(journal["schema_version"]) is not int or journal["schema_version"] != 1 or journal["packet_sha256"] != packet_hash or not isinstance(journal["entries"], list) or len(journal["entries"]) > len(proposal["patches"]):
            raise ReconcileError("reconciliation journal does not match this exact proposal")
        expected = proposal["baseline"]
        for index, entry in enumerate(journal["entries"]):
            _keys(entry, {"issue_id", "before", "json_patch", "status"}, {"after"})
            planned = proposal["patches"][index]
            if entry["issue_id"] != planned["issue_id"] or entry["json_patch"] != planned["json_patch"] or not _same(entry["before"], expected):
                raise ReconcileError("journal intent does not match the reviewed serial patches")
            if entry["status"] == "verified":
                if not isinstance(entry.get("after"), dict):
                    raise ReconcileError("journal lacks verified reciprocal readback")
                for item in entry["after"].values():
                    _validate_projection(item, proposal["organization"], proposal["project"])
                _check_after(expected, entry["after"], changes[entry["issue_id"]])
                expected = entry["after"]
            elif entry["status"] in {"pending", "uncertain_unapplied"} and index == len(journal["entries"]) - 1:
                current = _read_current(client, proposal, clock)
                if not _same(expected, current):
                    _check_after(expected, current, changes[entry["issue_id"]])
                    entry.update(status="verified", after=current)
                    expected = current
                    authorize_write()
                    _write_journal(path, journal)
                else:
                    journal["entries"].pop()
                break
            else:
                raise ReconcileError("conflicted or invalid journal requires a new reviewed proposal")
        current = _read_current(client, proposal, clock)
        if not _same(expected, current):
            raise ReconcileError("proposal or receipt is stale; human edits and unrelated revisions are preserved")
        resumed = bool(journal["entries"])
        new_writes = 0
        for planned in proposal["patches"][len(journal["entries"]):]:
            validate_proposal(proposal, now=clock())
            current = _read_current(client, proposal, clock)
            if not _same(expected, current) or current[planned["issue_id"]]["revision"] != planned["json_patch"][0]["value"]:
                raise ReconcileError("revision changed before serial patch; no blind replay is permitted")
            change = changes[planned["issue_id"]]
            _verify_evidence(change, runtime)
            # Batched/throttled reads and evidence hashing may outlast the plan.
            validate_proposal(proposal, now=clock())
            authorize_write()
            entry = {**deepcopy(planned), "before": current, "status": "pending"}
            journal["entries"].append(entry)
            _write_journal(path, journal)
            number = issue_number(planned["issue_id"], proposal["organization"], proposal["project"])
            uncertain = False
            try:
                new_writes += 1
                authorize_write()
                client.request_response("PATCH", f"_apis/wit/workitems/{number}", data=planned["json_patch"], query={"api-version": "7.1"}, capability="board_write", fresh=True, headers={"Content-Type": "application/json-patch+json"}, before_write=authorize_write)
            except AzureRevisionConflict:
                # Fresh read also covers reciprocals. A conflict never authorizes replay.
                entry["status"] = "conflict"
                _write_journal(path, journal)
                _read_current(client, proposal, clock)
                raise ReconcileError("Azure revision conflict; inspect and approve a new proposal") from None
            except AzureUncertainWrite:
                uncertain = True
            after = _read_current(client, proposal, clock)
            if uncertain and _same(current, after):
                entry["status"] = "uncertain_unapplied"
                _write_journal(path, journal)
                return _receipt(proposal, packet_hash, journal, "uncertain_unapplied")
            try:
                _check_after(current, after, change)
            except ReconcileError:
                entry["status"] = "conflict"
                _write_journal(path, journal)
                raise
            entry.update(status="verified", after=after)
            _write_journal(path, journal)
            expected = after
        authorize_write()
        return _receipt(proposal, packet_hash, journal, "already_applied" if resumed and not new_writes else "applied" if proposal["patches"] else "no_changes")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview exact Azure Board patches; applying requires separate exact authorization.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--runtime-dir")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--packet", help="Previously reviewed sanitized proposal JSON")
    source.add_argument("--snapshot", help="Complete local expanded work item snapshot JSON; paired with --changes")
    parser.add_argument("--changes", help="Operator-authored exact tags/dependencies/acceptance changes JSON")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorization", help="Signed exact board_write grant from a trusted issuer")
    parser.add_argument("--authorize-packet-sha256", help="Optional proposal hash matching check; grants no permission")
    parser.add_argument("--dry-run", action="store_true", help="Explicit inert preview (the default)")
    return parser


def _read_local_json(raw: str) -> Any:
    identity_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    supplied = Path(raw).absolute()
    roots = (identity_home, Path("/tmp"))
    if not any(root in supplied.parents for root in roots):
        raise ReconcileError("local proposal inputs must remain within this identity or its owned temporary files")
    path = supplied.resolve(strict=True)
    if not any(root in path.parents for root in roots) or path.stat().st_uid != os.getuid() or not path.is_file():
        raise ReconcileError("local proposal input resolves outside this identity")
    return strict_json_loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.apply and args.dry_run or args.apply and not args.authorization or not args.apply and (args.authorize_packet_sha256 or args.authorization):
            raise ReconcileError("apply and a signed authorization must be supplied together; dry-run cannot apply")
        if bool(args.snapshot) != bool(args.changes):
            raise ReconcileError("--snapshot and --changes are required together")
        config = load_runtime_config(args.config, runtime_dir=args.runtime_dir, require_runtime=args.apply)
        if config.provider != "azure-devops":
            raise ReconcileError("Azure reconciliation requires an explicit azure-devops provider")
        repository = config.repository
        if args.packet:
            proposal = _read_local_json(args.packet)
        else:
            proposal = build_proposal(_read_local_json(args.snapshot), _read_local_json(args.changes), repository["organization"], repository["project"])
        packet_hash = validate_proposal(proposal)
        if proposal["organization"] != repository["organization"] or proposal["project"] != repository["project"]:
            raise ReconcileError("proposal does not match the configured Azure repository namespace")
        if not args.apply:
            print(json.dumps({"mode": "preview", "packet_sha256": packet_hash, "proposal": proposal, "configuration": config.report()}, sort_keys=True))
            return 0
        require_capability(config, "read")
        require_capability(config, "board_write")
        if args.authorize_packet_sha256 is not None and args.authorize_packet_sha256 != packet_hash:
            raise ReconcileError("the supplied packet SHA-256 does not match the exact proposal")
        authorization = _read_local_json(args.authorization)
        _authorize(proposal, config, config.runtime_dir, authorization, now=time.time())
        from atlas_azure_devops import AzureDevOpsClient, azure_cli_headers
        client = AzureDevOpsClient(repository["organization"], repository["project"], config.runtime_dir, capabilities=config.capabilities, headers=azure_cli_headers())
        receipt = apply_proposal(proposal, client, runtime_dir=config.runtime_dir, authorized_sha256=args.authorize_packet_sha256,
                                 capabilities=config.capabilities, config=config, authorization=authorization)
        print(json.dumps(receipt, sort_keys=True))
        return 0 if receipt["status"] in {"applied", "already_applied", "no_changes"} else 2
    except (ReconcileError, ValueError, TypeError, OSError, AzureError) as exc:
        # Exception strings from transport/JSON parsers can contain remote bodies.
        message = str(exc) if isinstance(exc, ReconcileError) else "configuration, proposal or local evidence is unavailable or invalid"
        print(json.dumps({"mode": "blocked", "reason": message, "execution_eligibility": "blocked"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
