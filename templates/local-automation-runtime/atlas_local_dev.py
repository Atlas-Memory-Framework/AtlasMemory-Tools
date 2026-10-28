#!/usr/bin/env python3
"""Supervised queue adapter; dispatch remains an explicit operator action."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import stat
import sys

# Even status must not create interpreter caches in the installed runtime.
sys.dont_write_bytecode = True
MAX_INPUT = 65536
TASK_FIELDS = {
    "id", "title", "goal", "acceptance_criteria", "scheduler", "metadata",
    "validation", "labels", "description", "body", "objective", "task",
    "spec_path", "spec_hash", "source_id", "dispatch_mode", "required_gates",
    "files_out_of_scope", "manifest_leaf_id", "package_id", "package_hash",
}
RUNTIME_FIELDS = {
    "status", "state", "evidence", "claim", "lifecycle", "result", "pending",
    "accepted", "supervised_handoff_v1", "previous_attempts", "process_uncertainty",
    "operation_id", "last_generation",
}
RECEIPT_FIELDS = {"invocation_id", "transport", "checkout", "revision", "model", "reasoning"}


class CLIError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


class OutputError(Exception):
    pass


def emit(value):
    try:
        print(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False), flush=True)
    except OSError:
        raise OutputError from None


def error_exit(code, message):
    try:
        emit({"error": {"code": code, "message": message}})
    except OutputError:
        pass
    return 2


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CLIError("arguments", message)


def bounded_read(path):
    """Bound the actual opened stream, including files growing after open/stat."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise CLIError("invalid_input", "input must be a regular file")
            raw = stream.read(MAX_INPUT + 1)
        if not 1 <= len(raw) <= MAX_INPUT:
            raise CLIError("invalid_input", "input must contain 1 through 65536 bytes")
        return raw
    except OSError:
        raise CLIError("invalid_input", "input file cannot be read") from None


def unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def reject_constant(value):
    raise ValueError("nonfinite number")


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite number")
    return number


def strict_object(raw):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                           parse_constant=reject_constant, parse_float=finite_float)
        if type(value) is not dict:
            raise ValueError("expected object")
        return value
    except (UnicodeError, ValueError, RecursionError, OverflowError):
        raise CLIError("invalid_json", "input must be a bounded strict JSON object") from None


def load_object(path):
    return strict_object(bounded_read(path))


def full_revision(value):
    return (type(value) is str and len(value) in (40, 64)
            and all(char in "0123456789abcdef" for char in value))


def runtime_api(args):
    try:
        runtime = Path(args.runtime_dir).expanduser().resolve(strict=True)
    except OSError:
        raise CLIError("runtime", "explicit installed runtime is unavailable") from None
    names = ("atlas_work_items", "atlas_supervised_handoff", "atlas_local_sizing",
             "atlas_workflows", "atlas_delta_review")
    if not runtime.is_dir() or any(not (runtime / (name + ".py")).is_file() for name in names):
        raise CLIError("runtime", "explicit runtime must contain the maintained API modules")
    sys.path.insert(0, str(runtime))
    try:
        modules = [importlib.import_module(name) for name in names]
        if any(Path(module.__file__).resolve().parent != runtime for module in modules):
            raise ValueError("API imported outside selected runtime")
    except Exception:
        raise CLIError("runtime", "maintained APIs could not be loaded from explicit runtime") from None
    wi, handoff, sizing, workflows = modules[:4]
    state = Path(args.state_dir).expanduser().absolute()
    store = wi.AtlasWorkItemStore(state / "work-items.json")
    provider = pending_aware_provider(wi, store, args.owner)
    worker = wi.LocalCommandOperationWorker(
        command=None, jobs_dir=state / "jobs", templates_dir=runtime / "team-templates",
        agent_root=args.agent_root, agent_registry_path=args.agent_registry,
    )
    return wi, handoff, sizing, workflows, store, provider, worker


def pending_aware_provider(wi, store, owner):
    """Extend readiness; leave locking and claim transitions to the installed API."""
    class PendingAwareProvider(wi.AtlasWorkItemOperationProvider):
        def project(self, item, by_id=None):
            operation = super().project(item, by_id)
            # claim() calls self.project with fresh by_id while holding store.lock.
            # The earlier CLI scan alone cannot fence a competing preparation.
            # Already-running projections stay unchanged for owned pending replay.
            if operation.ready and by_id is not None and any(
                    handoff_state(candidate).get("pending") is not None
                    for candidate in by_id.values()):
                return replace(operation, ready=False, blockers=[
                    *operation.blockers, "store-wide supervised handoff pending",
                ])
            return operation

    return PendingAwareProvider(store, claimed_by=owner)


def by_id(wi, payload):
    return {wi.item_id(item): item for item in payload["work_items"]}


def handoff_state(item):
    value = item.get("supervised_handoff_v1")
    return value if isinstance(value, dict) else {}


def validate_task(task, wi, sizing, workflows, worker):
    if not task or set(task) - TASK_FIELDS:
        raise CLIError("task_shape", "task contains unsupported or runtime-owned fields")
    for field in ("id", "title", "goal"):
        if type(task.get(field)) is not str or not task[field].strip():
            raise CLIError("task_content", "id, title and substantive goal are required")
    if len(task["goal"].strip()) < 12:
        raise CLIError("task_content", "goal must describe a substantive outcome")
    criteria = task.get("acceptance_criteria")
    if type(criteria) is not list or not criteria or any(type(c) is not str or not c.strip() for c in criteria):
        raise CLIError("task_content", "acceptance_criteria must be a nonempty string list")
    scheduler, metadata = task.get("scheduler"), task.get("metadata")
    if type(scheduler) is not dict or type(metadata) is not dict:
        raise CLIError("task_qualification", "scheduler and metadata objects are required")
    if any(set(container) & RUNTIME_FIELDS for container in (scheduler, metadata)):
        raise CLIError("task_shape", "scheduler and metadata cannot supply runtime-owned fields")
    if not full_revision(scheduler.get("base_branch")):
        raise CLIError("task_qualification", "scheduler.base_branch must pin a full lowercase Git SHA")
    if type(scheduler.get("execution_repo")) is not str or not Path(scheduler["execution_repo"]).is_absolute():
        raise CLIError("task_qualification", "scheduler.execution_repo must name an absolute checkout")
    if type(metadata.get("local_execution_v1")) is not dict:
        raise CLIError("task_qualification", "local_execution_v1 qualification is required")
    requested = scheduler.get("team_template") or metadata.get("team_template")
    if not requested or not (scheduler.get("workflow_kind") or metadata.get("workflow_kind")):
        raise CLIError("task_qualification", "workflow kind and team template selection are required")
    templates = workflows.load_team_templates(worker.templates_dir)
    selected = workflows.select_team_template_for_work_item(templates, task)
    if selected is None or selected.id != requested:
        raise CLIError("task_qualification", "requested team template is unavailable or incompatible")
    if workflows.validate_template_agent_refs(
            selected, registry=worker.load_agent_registry(), agent_root=worker.agent_root):
        raise CLIError("task_qualification", "selected template has unresolved agent references")
    gates = [role for role in selected.roles if role.goal_gate]
    needed = {role.id for role in selected.roles if role.id in {"implementation", "test-runner"}}
    if len(gates) != 1 or gates[0].id in needed or not needed.issubset(set(gates[0].consumes)):
        raise CLIError("task_qualification", "selected template requires one independent evidence-consuming goal gate")
    roles = [{"role_id": role.id, "goal_gate": role.goal_gate} for role in selected.roles]
    qualification = sizing.qualify(wi.work_item_context(task), roles=roles)
    if qualification["status"] != "qualified":
        raise CLIError("task_qualification", "local_execution_v1 is not qualified for selected roles")


def do_add(args, api):
    wi, handoff, sizing, workflows, store, provider, worker = api
    task = load_object(args.task)
    validate_task(task, wi, sizing, workflows, worker)
    # Only the adapter-owned initialization is added; source metadata/pins stay verbatim.
    item = dict(task)
    item.update(status="ready", lifecycle={"state": "ready", "rework_count": 0},
                evidence=[wi.event("create", status="ready", operation_id=f"atlas-work-item:{task['id']}")])
    # Readiness is rechecked under the append lock against the current queue.
    with store.lock():
        payload = store.load()
        items = by_id(wi, payload)
        if task["id"] in items:
            raise CLIError("duplicate", "work item already exists")
        operation = provider.project(item, {**items, task["id"]: item})
        if not operation.ready:
            raise CLIError("task_blocked", "task is not ready under current scheduler projection")
        payload["work_items"].append(item)
        store.save(payload)
    emit({"status": "added", "id": task["id"]})


def do_status(args, api):
    wi, handoff, sizing, workflows, store, provider, worker = api
    if not store.path.exists():
        emit({"status": "uninitialized", "work_items": [], "next_action": "add a task"})
        return
    payload = store.load()
    items = by_id(wi, payload)
    rows = []
    for item in payload["work_items"]:
        operation = provider.project(item, items)
        pending = handoff_state(item).get("pending")
        binding = pending.get("binding", {}) if isinstance(pending, dict) else {}
        rows.append({
            "id": operation.source_id, "title": operation.title, "state": operation.state,
            "ready": operation.ready, "blockers": operation.blockers,
            "pending_handoff_id": binding.get("handoff_id"), "pending_role": binding.get("role_id"),
            "pending_owner": binding.get("supervisor_id"),
            "next_action": ("recover same invocation/import result" if pending else
                            "prepare" if operation.ready else "inspect blockers"),
        })
    emit({"status": "observed", "work_items": rows})


def do_prepare(args, api):
    wi, handoff, sizing, workflows, store, provider, worker = api
    if not store.path.exists():
        raise CLIError("state", "state is uninitialized")
    if not full_revision(args.revision):
        raise CLIError("revision", "revision must be a full lowercase Git SHA")
    payload = store.load()
    items = by_id(wi, payload)
    item = items.get(args.id)
    if item is None:
        raise CLIError("missing", "work item not found")
    operation = provider.project(item, items)
    if item.get("scheduler", {}).get("base_branch") != args.revision:
        raise CLIError("revision", "revision differs from frozen scheduler.base_branch")
    pending = []
    for candidate in payload["work_items"]:
        reservation = handoff_state(candidate).get("pending")
        if reservation is not None:
            pending.append((wi.item_id(candidate), reservation))
    if pending:
        if (len(pending) != 1 or pending[0][0] != args.id
                or pending[0][1].get("binding", {}).get("supervisor_id") != args.owner):
            raise CLIError("pending_conflict", "another handoff is pending store-wide")
    elif operation.ready:
        if provider.claim(operation) is None:
            raise CLIError("claim", "work item is no longer eligible")
    elif (wi.item_state(item) != "running" or not isinstance(item.get("claim"), dict)
          or item["claim"].get("claimed_by") != args.owner):
        raise CLIError("claim", "item is not eligible or this supervisor's running claim")
    # This maintained API independently verifies checkout root/HEAD and pending ownership.
    emit(handoff.prepare_handoff(provider, worker, source_id=args.id, expected_revision=args.revision))


def do_import(args, api):
    wi, handoff, sizing, workflows, store, provider, worker = api
    reservation = load_object(args.reservation)
    receipt = load_object(args.host_receipt)
    raw = bounded_read(args.result)
    strict_object(raw)  # Enforce strict JSON on both first import and accepted replay.
    if (set(reservation) != {"status", "binding", "packet", "artifacts"}
            or reservation.get("status") != "prepared"
            or any(type(reservation.get(key)) is not dict for key in ("binding", "packet", "artifacts"))):
        raise CLIError("reservation", "complete four-field prepared reservation is required")
    if (set(receipt) != RECEIPT_FIELDS or any(type(v) is not str or not v.strip() for v in receipt.values())
            or receipt.get("transport") != "supervised_in_app"):
        raise CLIError("host_receipt", "complete independently observed supervised host receipt is required")
    binding = reservation["binding"]
    if handoff.sha256_json(reservation["packet"]) != binding.get("packet_hash"):
        raise CLIError("reservation", "reservation packet differs from original binding")
    payload = store.load()
    item = by_id(wi, payload).get(binding.get("work_item_id"), {})
    state = handoff_state(item)
    # Artifacts are part of the emitted reservation, even though capture binds packet/binding.
    pending = state.get("pending")
    if isinstance(pending, dict) and pending.get("binding") == binding:
        if pending.get("artifacts") != reservation["artifacts"]:
            raise CLIError("reservation", "reservation artifacts differ from pending reservation")
    envelope = {"binding": binding, "host_receipt": receipt,
                "result_sha256": hashlib.sha256(raw).hexdigest()}
    if binding.get("handoff_id") in state.get("accepted", {}):
        result = handoff.ingest_handoff(provider, worker, envelope=envelope, result_bytes=raw)
    else:
        captured = handoff.capture_host_return(
            provider, worker, expected_reservation=reservation, host_receipt=receipt,
            dispatched_packet_sha256=binding.get("packet_hash"), result_bytes=raw,
        )
        result = handoff.ingest_handoff(provider, worker, envelope=captured["envelope"],
                                        result_bytes=captured["result_bytes"])
    emit(result)


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--owner", default="operator:atlas-daily-dev")
    parser.add_argument("--agent-root")
    parser.add_argument("--agent-registry")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add")
    add.add_argument("--task", required=True)
    add.set_defaults(run=do_add)
    status = commands.add_parser("status")
    status.set_defaults(run=do_status)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--id", required=True)
    prepare.add_argument("--revision", required=True)
    prepare.set_defaults(run=do_prepare)
    ingest = commands.add_parser("import")
    ingest.add_argument("--reservation", required=True)
    ingest.add_argument("--host-receipt", required=True)
    ingest.add_argument("--result", required=True)
    ingest.set_defaults(run=do_import)
    try:
        args = parser.parse_args(argv)
        if not args.owner.strip():
            raise CLIError("owner", "supervisor owner cannot be blank")
        args.run(args, runtime_api(args))
        return 0
    except CLIError as exc:
        return error_exit(exc.code, exc.message)
    except OutputError:
        # Persistence precedes stdout. Re-run prepare to recover the same reservation.
        return 2
    except Exception as exc:
        # API refusals carry safe codes; do not echo arbitrary input or local payloads.
        return error_exit(getattr(exc, "code", "runtime_refusal"),
                          "installed runtime refused the operation")


if __name__ == "__main__":
    raise SystemExit(main())
