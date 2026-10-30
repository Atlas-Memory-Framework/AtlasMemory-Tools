#!/usr/bin/env python3
"""Durable, bounded execution of effect-bound harness proposals.

Only the registered prepare implementation supplies executable arguments. Host
tool approval remains the authority boundary; authorization_ref records its
provenance and is never interpreted as a grant on its own.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pwd
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from harness_service import HarnessService, HarnessServiceError, RUNTIME_ID


RUN_SCHEMA = "atlas-tools.harness-run.v1"
RUN_ID = re.compile(r"run-[a-f0-9]{32}\Z")
REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@#-]{0,159}\Z")
TERMINAL = {"stopped", "failed", "timed_out", "cancelled"}
MAX_JSON_BYTES = 262_144
MAX_LOG_BYTES = 262_144
MAX_WAIT_SECONDS = 30
MAX_WALL_SECONDS = 1800
MAX_RECENT_ENTRIES = 128
TERMINATION_GRACE_SECONDS = 2.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _error(code: str, message: str, **details: Any) -> HarnessServiceError:
    return HarnessServiceError(code, message, details or None)


def _checked(path: Path, boundary: Path, *, required: bool = False) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise _error("unsafe_run_state", "Run state requires an absolute owned path without traversal.")
    try:
        relative = path.relative_to(boundary)
    except ValueError:
        raise _error("unsafe_run_state", "Run state must remain inside its configured boundary.") from None
    current = boundary
    components = [current]
    for part in relative.parts:
        current /= part
        components.append(current)
    for current in components:
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
            raise _error("unsafe_run_state", "Run state paths must be owned and may not contain symlinks.")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise _error("unsafe_run_state", "Run state paths may not be writable by another identity.")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise _error("unsafe_run_state", "Hard-linked run state is forbidden.")
        if current != path and not stat.S_ISDIR(info.st_mode):
            raise _error("unsafe_run_state", "Run state parents must be directories.")
    if required and not path.exists():
        raise _error("unknown_run", "No durable state exists for this run ID.")
    return path


def _read(path: Path, boundary: Path) -> dict[str, Any]:
    _checked(path, boundary, required=True)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > MAX_JSON_BYTES:
            raise _error("unsafe_run_state", "Run state must be a bounded owned regular file.")
        data = handle.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise _error("unsafe_run_state", "Run state exceeds its bounded read limit.")
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        raise _error("invalid_run_state", "The durable run record is malformed; reconcile it explicitly.") from None
    if not isinstance(value, dict):
        raise _error("invalid_run_state", "The durable run record must be an object.")
    return value


def _atomic(path: Path, value: dict[str, Any], boundary: Path) -> None:
    _checked(path, boundary)
    data = (json.dumps(value, sort_keys=True) + "\n").encode()
    if len(data) > MAX_JSON_BYTES:
        raise _error("invalid_run_state", "The durable run record would exceed its size budget.")
    fd, temporary = tempfile.mkstemp(prefix=".harness-run-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _process_identity(pid: int) -> dict[str, int] | None:
    """Linux process birth identity; a reused PID never proves liveness."""
    try:
        path = Path("/proc") / str(pid) / "stat"
        if path.stat().st_uid != os.getuid():
            return None
        fields = path.read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return {"pid": pid, "start_ticks": int(fields[19])}
    except (OSError, ValueError, IndexError):
        return None


def _identity_alive(identity: Any) -> bool:
    return (isinstance(identity, dict) and type(identity.get("pid")) is int and
            type(identity.get("start_ticks")) is int and
            _process_identity(identity["pid"]) == identity)


def _valid_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise _error("invalid_run_id", "Use the durable run ID returned by harness_start.")


class HarnessRuns:
    def __init__(self, service: HarnessService, state_dir: Path | None = None):
        self.service = service
        home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        raw = Path(state_dir) if state_dir is not None else service.registry.parent / "runs"
        if not raw.is_absolute() or ".." in raw.parts:
            raise _error("unsafe_run_state", "The run-state directory must be an explicit absolute path.")
        if state_dir is None:
            identity_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
            if raw == identity_home or identity_home in raw.parents:
                raw = home / raw.relative_to(identity_home)
            self.boundary = home
            if raw == home or home not in raw.parents:
                raise _error("unsafe_run_state", "Production run state must remain inside the current identity home.")
        else:
            # Explicit injected state roots support isolated qualification. They
            # are constructor-only, never an MCP argument, and remain owned.
            parent = raw
            while not parent.exists() and parent != parent.parent:
                parent = parent.parent
            self.boundary = parent
        if raw.resolve(strict=False) != raw:
            raise _error("unsafe_run_state", "Run-state ancestors may not contain symlinks.")
        self.state_dir = _checked(raw, self.boundary)
        self._supervisors: dict[str, subprocess.Popen] = {}
        self._supervisors_lock = threading.Lock()

    def _reap_supervisors(self) -> None:
        # These are handles created by this client, never PIDs supplied in
        # stored state. Reap completed children without stopping durable runs.
        with self._supervisors_lock:
            for run_id, supervisor in list(self._supervisors.items()):
                if supervisor.poll() is not None:
                    del self._supervisors[run_id]

    def _wait_supervisor(self, run_id: str, supervisor: subprocess.Popen) -> None:
        try:
            supervisor.wait()
        finally:
            with self._supervisors_lock:
                if self._supervisors.get(run_id) is supervisor:
                    del self._supervisors[run_id]

    def _retain_supervisor(self, run_id: str, supervisor: subprocess.Popen) -> None:
        # The daemon holds the handle (and this owner) until it reaps the child,
        # including when no client ever observes the run again. It does not
        # interrupt the detached supervisor when the MCP client exits.
        with self._supervisors_lock:
            self._supervisors[run_id] = supervisor
        threading.Thread(target=self._wait_supervisor, args=(run_id, supervisor),
                         name="harness-reaper-" + run_id[-8:], daemon=True).start()

    def _root(self, *, create: bool = False) -> Path:
        _checked(self.state_dir, self.boundary)
        if create:
            self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            _checked(self.state_dir, self.boundary)
        return self.state_dir

    def _record(self, run_id: str) -> dict[str, Any]:
        _valid_run_id(run_id)
        root = self._root()
        data = _read(root / run_id / "status.json", self.boundary)
        if (data.get("schema_version") != RUN_SCHEMA or data.get("run_id") != run_id or
                type(data.get("cursor")) is not int or data["cursor"] < 1 or
                not isinstance(data.get("runtime_id"), str) or not RUNTIME_ID.fullmatch(data["runtime_id"]) or
                not isinstance(data.get("proposal_id"), str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", data["proposal_id"]) or
                not isinstance(data.get("status"), str) or
                data.get("status") not in TERMINAL | {"starting", "running"}):
            raise _error("invalid_run_state", "Run identity or lifecycle metadata is invalid; reconcile explicitly.")
        for key in ("created_at", "updated_at", "started_at", "ended_at"):
            if key not in data and key not in {"created_at", "updated_at"}:
                continue
            value = data.get(key)
            try:
                if not isinstance(value, str) or len(value) > 40 or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                    raise ValueError
            except ValueError:
                raise _error("invalid_run_state", "Run timestamp metadata is invalid; reconcile explicitly.") from None
        if "process_exit_code" in data and data["process_exit_code"] is not None and type(data["process_exit_code"]) is not int:
            raise _error("invalid_run_state", "Run process result metadata is invalid; reconcile explicitly.")
        for key in ("output_bytes", "stored_output_bytes"):
            if key in data and (type(data[key]) is not int or not 0 <= data[key] <= 2**63):
                raise _error("invalid_run_state", "Run output metadata is invalid; reconcile explicitly.")
        if "elapsed_seconds" in data and (type(data["elapsed_seconds"]) not in {int, float} or
                                           not 0 <= data["elapsed_seconds"] <= 86400 or
                                           not math.isfinite(data["elapsed_seconds"])):
            raise _error("invalid_run_state", "Run duration metadata is invalid; reconcile explicitly.")
        if "output_truncated" in data and type(data["output_truncated"]) is not bool:
            raise _error("invalid_run_state", "Run output metadata is invalid; reconcile explicitly.")
        return data

    def _view(self, data: dict[str, Any]) -> dict[str, Any]:
        fields = ("run_id", "runtime_id", "proposal_id", "status", "cursor", "created_at", "started_at", "ended_at",
                  "updated_at", "process_exit_code", "elapsed_seconds", "output_bytes", "stored_output_bytes", "output_truncated")
        view = {key: data[key] for key in fields if key in data}
        view.update(accepted_progress=False, completion=False,
                    evidence_boundary="Process exit is execution evidence only; validate and independently review task results.")
        alive = _identity_alive(data.get("supervisor"))
        view["supervisor_alive"] = alive
        marker = _checked(self.state_dir / data["run_id"] / "cancel.json", self.boundary)
        view["cancellation_requested"] = marker.exists()
        if data["status"] not in TERMINAL:
            try:
                age = time.time() - datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")).timestamp()
            except (KeyError, TypeError, ValueError):
                age = 6.0
            if not alive and (data.get("supervisor") is not None or age > 5):
                view.update(status="unknown", recorded_status=data["status"],
                            blockers=[{"code": "supervisor_unavailable", "message": "Supervisor liveness is unproven; preserve the run and reconcile before another start."}])
        view["next_actions"] = ([{"operation": "inspect", "runtime_id": data["runtime_id"]},
                                 {"operation": "validate_and_review_results", "run_id": data["run_id"]}]
                                if data["status"] in TERMINAL else
                                [{"operation": "reconcile_run", "run_id": data["run_id"]}] if view["status"] == "unknown" else
                                [{"operation": "wait", "run_id": data["run_id"], "cursor": data["cursor"]}])
        proposal = data.get("proposal", {})
        if isinstance(proposal, dict) and proposal.get("provider") == "azure-devops":
            view["operation"] = proposal.get("operation")
            if data["status"] in TERMINAL:
                from harness_azure import project_result
                from harness_service import _read_bytes

                try:
                    output = _checked(self.state_dir / data["run_id"] / "worker-output.log", self.boundary, required=True)
                    raw = _read_bytes(output, boundary=self.state_dir / data["run_id"])
                    view["operation_result"] = project_result(proposal, raw) if not data.get("output_truncated") else {
                        "status": "unavailable", "reason": "bounded_output_truncated", "accepted_progress": False, "completion": False,
                    }
                except (HarnessServiceError, OSError, ValueError, TypeError):
                    view["operation_result"] = {
                        "status": "unavailable", "reason": "structured_result_unavailable", "accepted_progress": False, "completion": False,
                    }
        return view

    def start(self, runtime_id: str, proposal_id: str, options: dict | None = None,
              authorization_ref: str | None = None, operation: str | None = None) -> dict[str, Any]:
        from harness_execution import HarnessExecution

        self._reap_supervisors()
        if not isinstance(authorization_ref, str) or not REFERENCE.fullmatch(authorization_ref):
            raise _error("missing_authorization_reference", "Start requires a bounded host-tool approval provenance reference; the reference itself grants no authority.")
        prepared = HarnessExecution(self.service).prepare(runtime_id, operation=operation, options=options)
        if prepared.get("proposal_id") != proposal_id:
            raise _error("stale_proposal", "The proposal changed; prepare again and review its current effects before starting.")
        proposal = prepared.get("proposal", {})
        if prepared.get("status") != "prepared" or proposal.get("blockers"):
            raise _error("proposal_blocked", "The prepared operation has unresolved blockers; no worker was launched.")
        runtime = self.service.get_runtime(runtime_id)
        capabilities = runtime.get("configuration", {}).get("capabilities", [])
        required = proposal.get("required_capabilities", ["local_execute"])
        if not isinstance(required, list) or not required or any(capability not in capabilities for capability in required):
            raise _error("execution_disabled", "The registered runtime lacks the capabilities required by this operation.")
        from harness_azure import AZURE_OPERATIONS

        supported = {"github-cycle", *AZURE_OPERATIONS}
        if (proposal.get("operation") not in supported or proposal.get("runtime_id") != runtime_id or
                (operation is not None and proposal.get("operation") != operation) or
                proposal.get("provider") != runtime.get("provider", proposal.get("provider")) or
                proposal.get("cwd") != runtime["runtime_dir"]):
            raise _error("invalid_proposal", "Only a named effect-bound operation for the registered provider may be started.")
        argv = proposal.get("argv")
        if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in argv):
            raise _error("invalid_proposal", "The prepared operation did not supply valid bounded arguments.")
        minutes = proposal.get("budgets", {}).get("max_minutes")
        if type(minutes) is not int or not 1 <= minutes <= 30:
            raise _error("invalid_proposal", "A start requires an explicit one-to-thirty-minute wall-clock budget.")
        root = self._root(create=True)
        runtime_lock = _checked(root / f"{runtime_id}.lock", self.boundary)
        run_id = "run-" + uuid.uuid4().hex
        try:
            fd = os.open(runtime_lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            raise _error("runtime_busy", "This runtime has an active or unreconciled run; inspect it before starting another.") from None
        with os.fdopen(fd, "w") as handle:
            handle.write(run_id + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        job = _checked(root / run_id, self.boundary)
        try:
            job.mkdir(mode=0o700)
            stamp = _now()
            record = {"schema_version": RUN_SCHEMA, "run_id": run_id, "runtime_id": runtime_id,
                      "proposal_id": proposal_id, "proposal": proposal, "authorization_ref": authorization_ref,
                      "authorization_source": "host_tool_approval_required", "status": "starting", "cursor": 1,
                      "created_at": stamp, "updated_at": stamp, "supervisor": None,
                      "accepted_progress": False, "completion": False}
            _atomic(job / "status.json", record, self.boundary)
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            supervisor = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--supervise", str(root), run_id],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, start_new_session=True, env=environment)
        except Exception:
            # No worker can have been launched before the detached supervisor.
            # Preserve initial state for audit if creation partially succeeded.
            if runtime_lock.exists() and runtime_lock.read_text().strip() == run_id:
                runtime_lock.unlink()
            if (job / "status.json").exists():
                record.update(status="failed", ended_at=_now(), updated_at=_now(), cursor=record["cursor"] + 1,
                              failure_code="supervisor_launch_failed", process_exit_code=None)
                _atomic(job / "status.json", record, self.boundary)
            raise _error("supervisor_launch_failed", "The supervisor could not start; no worker was launched.") from None
        self._retain_supervisor(run_id, supervisor)
        return self.service._envelope(read_only=False, run_id=run_id, run=self._view(record),
                                      authorization_note="The host-approved tool call authorizes this effect-bound operation; a reference string alone does not.")

    def recent(self, runtime_id: str, limit: int = 8) -> dict[str, Any]:
        """Recover compact observations without knowing a previous run ID."""
        if not isinstance(runtime_id, str) or not RUNTIME_ID.fullmatch(runtime_id):
            raise _error("invalid_runtime_id", "Use an explicit registered runtime ID.")
        if type(limit) is not int or not 1 <= limit <= 32:
            raise _error("invalid_run_limit", "Recent-run limit must be an integer between one and thirty-two.")
        root = self._root()
        if not root.exists():
            return self.service._envelope(runtime_id=runtime_id, runs=[], truncated=False,
                                          scanned_entries=0, blockers=[])
        _checked(root, self.boundary, required=True)
        runs, blockers = [], []
        scanned = 0
        truncated = False
        # os.scandir is consumed incrementally. Never materialize an unbounded
        # job history or follow discovered directory links.
        with os.scandir(root) as entries:
            for entry in entries:
                if scanned >= MAX_RECENT_ENTRIES:
                    truncated = True
                    break
                scanned += 1
                if not RUN_ID.fullmatch(entry.name):
                    continue
                try:
                    data = self._record(entry.name)
                    if data.get("runtime_id") == runtime_id:
                        runs.append(self._view(data))
                except (HarnessServiceError, OSError):
                    # Report only known generated IDs and a fixed error. No
                    # discovered filenames, JSON contents, or log text escape.
                    blockers.append({"code": "unavailable_run_record", "run_id": entry.name,
                                     "message": "A run record is unavailable, unsafe or malformed; preserve it for explicit reconciliation."})
        runs.sort(key=lambda item: (datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")).timestamp(),
                                   item["run_id"]), reverse=True)
        truncated = truncated or len(runs) > limit
        return self.service._envelope(runtime_id=runtime_id, runs=runs[:limit], truncated=truncated,
                                      scanned_entries=scanned, blockers=blockers)

    def wait(self, run_id: str, cursor: int | None = None, timeout_seconds: float = 0) -> dict[str, Any]:
        self._reap_supervisors()
        if cursor is not None and (type(cursor) is not int or cursor < 0):
            raise _error("invalid_cursor", "Cursor must be the nonnegative integer returned by a prior observation.")
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or
                not 0 <= timeout_seconds <= MAX_WAIT_SECONDS):
            raise _error("invalid_wait", "Wait timeout must be between zero and thirty seconds.")
        deadline = time.monotonic() + timeout_seconds
        while True:
            data = self._record(run_id)
            view = self._view(data)
            changed = cursor is None or data["cursor"] != cursor
            if changed or view["status"] in TERMINAL | {"unknown"} or time.monotonic() >= deadline:
                return self.service._envelope(run_id=run_id, run=view, changed=changed, cursor=data["cursor"])
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))

    def cancel(self, run_id: str) -> dict[str, Any]:
        self._reap_supervisors()
        data = self._record(run_id)
        if data["status"] in TERMINAL:
            return self.service._envelope(read_only=False, run_id=run_id, run=self._view(data),
                                          cancellation_requested=False, already_terminal=True)
        marker = self.state_dir / run_id / "cancel.json"
        _checked(marker, self.boundary)
        if not marker.exists():
            _atomic(marker, {"run_id": run_id, "requested_at": _now()}, self.boundary)
        return self.service._envelope(read_only=False, run_id=run_id, run=self._view(data), cancellation_requested=True)


def _peek_exited(child: subprocess.Popen) -> bool:
    # WNOWAIT retains the child's PID until group cleanup, so it cannot be
    # recycled into an unrelated process group before TERM/KILL.
    result = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    return result is not None


def _signal_group(child: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(child.pid, sig)
    except ProcessLookupError:
        pass


def _run_worker(job: Path, proposal: dict[str, Any], *, wall_seconds: float | None = None) -> dict[str, Any]:
    """Supervisor-only worker loop; wall_seconds is private fixture injection."""
    minutes = proposal.get("budgets", {}).get("max_minutes")
    if type(minutes) is not int or not 1 <= minutes <= 30:
        raise _error("invalid_proposal", "Supervisor refused an invalid wall-clock budget.")
    seconds = min(minutes * 60, MAX_WALL_SECONDS) if wall_seconds is None else min(wall_seconds, MAX_WALL_SECONDS)
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        raise _error("invalid_proposal", "Supervisor refused an invalid execution duration.")
    _checked(job / "worker-output.log", job)
    output_fd = os.open(job / "worker-output.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    started = time.monotonic()
    observed = stored = 0
    reason: str | None = None
    termination_at: float | None = None
    child: subprocess.Popen | None = None
    try:
        child = subprocess.Popen(proposal["argv"], cwd=proposal["cwd"], shell=False,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 start_new_session=True, close_fds=True)
        assert child.stdout is not None
        os.set_blocking(child.stdout.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ)
        try:
            while True:
                for key, _ in selector.select(0.05):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    observed += len(chunk)
                    allowed = min(len(chunk), max(0, MAX_LOG_BYTES - stored))
                    if allowed:
                        os.write(output_fd, chunk[:allowed])
                        stored += allowed
                now = time.monotonic()
                exited = _peek_exited(child)
                if reason is None:
                    if (job / "cancel.json").exists():
                        reason = "cancelled"
                    elif now - started >= seconds:
                        reason = "timed_out"
                    elif exited:
                        reason = "process_exited"
                    if reason:
                        _signal_group(child, signal.SIGTERM)
                        termination_at = now
                if reason is not None:
                    grace = 0.1 if reason == "process_exited" else TERMINATION_GRACE_SECONDS
                    if now - termination_at >= grace:
                        _signal_group(child, signal.SIGKILL)
                        break
            exit_code = child.wait(timeout=5)
            # Drain remaining buffered bytes without waiting for a descendant.
            while True:
                try:
                    chunk = os.read(child.stdout.fileno(), 65536)
                except BlockingIOError:
                    break
                if not chunk:
                    break
                observed += len(chunk)
                allowed = min(len(chunk), max(0, MAX_LOG_BYTES - stored))
                if allowed:
                    os.write(output_fd, chunk[:allowed])
                    stored += allowed
        finally:
            selector.close()
            child.stdout.close()
        status = reason if reason in {"cancelled", "timed_out"} else "stopped" if exit_code == 0 else "failed"
        return {"status": status, "process_exit_code": exit_code, "elapsed_seconds": round(time.monotonic() - started, 3),
                "output_bytes": observed, "stored_output_bytes": stored, "output_truncated": observed > stored}
    except Exception:
        if child is not None:
            _signal_group(child, signal.SIGKILL)
            try:
                child.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return {"status": "failed", "process_exit_code": None, "elapsed_seconds": round(time.monotonic() - started, 3),
                "output_bytes": observed, "stored_output_bytes": stored, "output_truncated": observed > stored,
                "failure_code": "worker_launch_or_supervision_failed"}
    finally:
        os.close(output_fd)


def _supervise(root: Path, run_id: str) -> int:
    from harness_execution import proposal_digest

    _valid_run_id(run_id)
    # The parent already validated its selected boundary before spawning. A
    # detached supervisor revalidates owned private state before any execution.
    if root.resolve(strict=True) != root:
        raise _error("unsafe_run_state", "Supervisor state ancestors may not contain symlinks.")
    root = _checked(root, root, required=True)
    job = _checked(root / run_id, root, required=True)
    path = job / "status.json"
    record = _read(path, root)
    if record.get("schema_version") != RUN_SCHEMA or record.get("run_id") != run_id or record.get("status") != "starting":
        return 2
    if not isinstance(record.get("proposal"), dict) or proposal_digest(record["proposal"]) != record.get("proposal_id"):
        return 2
    lock = _checked(root / f"{record['runtime_id']}.lock", root, required=True)
    if lock.read_text().strip() != run_id:
        return 2
    terminal_written = False
    try:
        if (job / "cancel.json").exists():
            outcome = {"status": "cancelled", "process_exit_code": None, "elapsed_seconds": 0.0,
                       "output_bytes": 0, "stored_output_bytes": 0, "output_truncated": False}
        else:
            record.update(status="running", started_at=_now(), updated_at=_now(),
                          supervisor=_process_identity(os.getpid()), cursor=record["cursor"] + 1)
            _atomic(path, record, root)
            outcome = _run_worker(job, record["proposal"])
        record.update(**outcome, ended_at=_now(), updated_at=_now(), cursor=record["cursor"] + 1,
                      accepted_progress=False, completion=False)
        _atomic(path, record, root)
        terminal_written = True
        return 0
    finally:
        # Never reclaim an unknown lock or act on a caller-supplied PID.
        if terminal_written and lock.exists() and lock.read_text().strip() == run_id:
            lock.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supervise", metavar="STATE_ROOT", help=argparse.SUPPRESS)
    parser.add_argument("run_id", nargs="?")
    args = parser.parse_args(argv)
    if args.supervise is None or args.run_id is None:
        parser.error("this module is a supervisor helper; use the harness MCP tools")
    try:
        return _supervise(Path(args.supervise), args.run_id)
    except Exception:
        # No exception text, worker output, credentials, or config is returned.
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
