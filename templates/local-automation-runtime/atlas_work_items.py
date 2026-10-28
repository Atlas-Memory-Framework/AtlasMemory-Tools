#!/usr/bin/env python3
"""Local Atlas work-item provider for the automation runtime."""

from __future__ import annotations

import json
import copy
import errno
import hashlib
import os
import pathlib
import re
import secrets
import signal
import socket
import stat
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import atlas_delta_review


READY_STATES = {"ready", "queued"}
ACTIVE_STATES = {"claimed", "running"}
TERMINAL_STATES = {"done", "failed", "cancelled", "superseded"}
NONE_VALUES = {"", "none", "n/a", "na", "-"}
PRIORITY_RANKS = {
    "p0": 0,
    "0": 0,
    "urgent": 0,
    "highest": 0,
    "p1": 1,
    "1": 1,
    "high": 1,
    "p2": 2,
    "2": 2,
    "medium": 2,
    "normal": 2,
    "p3": 3,
    "3": 3,
    "low": 3,
    "lowest": 3,
}

_ATLAS_DAILY_TASK_SCHEMA = "atlas.daily_supervised_handoff.correlation.v1"
_CONTRACTED_WORKFLOW_FILE_LIMIT_BYTES = 4 * 1024 * 1024
_CONTRACTED_WORKER_OUTPUT_LIMIT_BYTES = 64 * 1024 * 1024


def _job_child_name(job_dir: pathlib.Path, path: str | pathlib.Path) -> str:
    root = pathlib.Path(os.path.abspath(job_dir))
    target = pathlib.Path(os.path.abspath(path))
    if target.parent != root or target.name in {"", ".", ".."}:
        raise ValueError("contracted workflow artifacts must be direct children of the held job directory")
    return target.name


def _read_job_file(job_dir_fd: int, name: str, *, limit: int, missing_ok: bool = False) -> bytes | None:
    if pathlib.Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError("job artifact name must be one path component")
    # O_NONBLOCK prevents a child-created FIFO from wedging the supervisor before
    # fstat can reject it. It has no effect on regular-file reads.
    nonblock = getattr(os, "O_NONBLOCK", None)
    if nonblock is None:
        raise OSError(errno.ENOTSUP, "nonblocking job artifact opens are unavailable", name)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nonblock
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError(errno.ENOTSUP, "no-follow job artifact reads are unavailable", name)
    try:
        fd = os.open(name, flags | nofollow, dir_fd=job_dir_fd)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(errno.EINVAL, "job artifact is not a regular file", name)
        raw = bytearray()
        while len(raw) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > limit:
            raise OSError(errno.EFBIG, "job artifact exceeds the byte limit", name)
        return bytes(raw)
    finally:
        os.close(fd)


def _read_job_json(job_dir_fd: int, name: str, *, limit: int = _CONTRACTED_WORKFLOW_FILE_LIMIT_BYTES,
                   missing_ok: bool = False) -> Any:
    raw = _read_job_file(job_dir_fd, name, limit=limit, missing_ok=missing_ok)
    if raw is None:
        return None
    return json.loads(raw.decode("utf-8"))


def _atomic_write_job_file(job_dir_fd: int, name: str, content: bytes) -> None:
    if pathlib.Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError("job artifact name must be one path component")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    temporary = ""
    fd = -1
    for _attempt in range(8):
        temporary = f".{name}.{secrets.token_hex(12)}.tmp"
        try:
            fd = os.open(temporary, flags, 0o600, dir_fd=job_dir_fd)
            break
        except FileExistsError:
            continue
    if fd < 0:
        raise FileExistsError("could not reserve a unique job artifact temporary file")
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, name, src_dir_fd=job_dir_fd, dst_dir_fd=job_dir_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=job_dir_fd)
        except FileNotFoundError:
            pass


def _job_directory_identity(job_dir: pathlib.Path, job_dir_fd: int, job_parent_fd: int,
                            job_parent_identity: tuple[int, int]) -> tuple[int, int] | None:
    try:
        held = os.fstat(job_dir_fd)
        parent = os.fstat(job_parent_fd)
        parent_path = os.stat(job_dir.parent, follow_symlinks=False)
        current = os.stat(job_dir.name, dir_fd=job_parent_fd, follow_symlinks=False)
        if (stat.S_ISDIR(parent_path.st_mode)
                and (parent.st_dev, parent.st_ino) == job_parent_identity
                and (parent_path.st_dev, parent_path.st_ino) == job_parent_identity
                and stat.S_ISDIR(current.st_mode)
                and (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino)):
            return held.st_dev, held.st_ino
    except OSError:
        pass
    return None


def _bounded_atlas_daily_task(value: Any) -> dict[str, Any]:
    """Validate the deliberately opaque, finite-JSON correlation wrapper."""
    seen: set[int] = set()
    nodes = 0
    def visit(node: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 20000 or depth > 32:
            raise ValueError("invalid atlas_daily_task wrapper")
        if node is None or type(node) in (str, bool, int):
            if type(node) is str:
                node.encode("utf-8")
            return
        if type(node) is float:
            if not __import__("math").isfinite(node):
                raise ValueError("invalid atlas_daily_task wrapper")
            return
        if type(node) not in (dict, list):
            raise ValueError("invalid atlas_daily_task wrapper")
        ident = id(node)
        if ident in seen:
            raise ValueError("invalid atlas_daily_task wrapper")
        seen.add(ident)
        if type(node) is dict:
            for key, child in node.items():
                if type(key) is not str:
                    raise ValueError("invalid atlas_daily_task wrapper")
                key.encode("utf-8")
                visit(child, depth + 1)
        else:
            for child in node:
                visit(child, depth + 1)
        seen.remove(ident)
    try:
        visit(value, 0)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
        if len(encoded) > 262144:
            raise ValueError("invalid atlas_daily_task wrapper")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise ValueError("invalid atlas_daily_task wrapper") from None
    if (type(value) is not dict or set(value) != {"schema", "binding_sha256", "work_packet"}
            or value.get("schema") != _ATLAS_DAILY_TASK_SCHEMA
            or type(value.get("binding_sha256")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value["binding_sha256"]) is None
            or type(value.get("work_packet")) is not dict
            or type(value["work_packet"].get("work_packet_id")) is not str
            or not value["work_packet"]["work_packet_id"].strip()):
        raise ValueError("invalid atlas_daily_task wrapper")
    return copy.deepcopy(value)


def now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_rfc3339(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_seconds(value: Any, *, now: datetime | None = None) -> float | None:
    parsed = parse_rfc3339(value)
    if parsed is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - parsed).total_seconds())


def safe_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in value)
    return cleaned.strip("-") or "work-item"


def list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text or text.lower() in NONE_VALUES:
        return []
    return [item.strip() for item in text.replace("\n", ",").split(",") if item.strip()]


def priority_value(value: Any, labels: list[str] | None = None) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("priority:"):
        return raw.split(":", 1)[1]
    if raw:
        return raw
    for label in labels or []:
        lowered = str(label).strip().lower()
        if lowered.startswith("priority:"):
            return lowered.split(":", 1)[1]
    return ""


def priority_rank(value: Any, labels: list[str] | None = None) -> int:
    priority = priority_value(value, labels)
    return PRIORITY_RANKS.get(priority, 99)


def numeric_rank(value: Any, default: int = 999_999) -> int:
    if value is None or value == "":
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


def scheduler_fields(item: dict[str, Any]) -> tuple[str, str, list[str]]:
    scheduler = item.get("scheduler") if isinstance(item.get("scheduler"), dict) else {}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    execution_repo = str(
        scheduler.get("execution_repo") or metadata.get("execution_repo") or item.get("execution_repo") or ""
    )
    base_branch = str(scheduler.get("base_branch") or metadata.get("base_branch") or item.get("base_branch") or "")
    write_scope = list_value(scheduler.get("write_scope") or item.get("write_scope"))
    return execution_repo, base_branch, write_scope


def unknown_or_equal(left: str, right: str) -> bool:
    return not left or not right or left == right


def write_scopes_overlap(left: list[str], right: list[str]) -> bool:
    if not left or not right:
        return True

    def prefix(scope: str) -> str:
        # Globs reserve their entire fixed directory prefix. Ambiguous scopes
        # reserve the repository rather than guessing they are disjoint.
        if not scope or "\\" in scope or scope.startswith("/") or ".." in scope.split("/"):
            return ""
        parts = [part for part in scope.split("/") if part and part != "."]
        fixed = []
        for part in parts:
            if any(char in part for char in "*?[{"):
                break
            fixed.append(part)
        return "/".join(fixed)

    for a in map(prefix, left):
        for b in map(prefix, right):
            if not a or not b or a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                return True
    return False


def _has_azure_repository_origin(execution_repo: str) -> bool:
    """Recognize the remote authority, never Azure text inside another URL.

    This is a legacy-worker exclusion gate, not endpoint authorization. Known
    Azure hosts remain excluded even with unsupported schemes, ports or userinfo;
    the Azure worker separately validates its permitted transport and target.
    """
    try:
        parsed = urlsplit(execution_repo)
        if not parsed.netloc:
            # Git's SCP-style SSH form has no URI authority. A slash before
            # the colon instead identifies a local path, so it cannot match.
            scp = re.fullmatch(r"((?:[^/@:\s]+@)?[^/@:\s]+):(.+)", execution_repo)
            if scp is None:
                return False
            parsed = urlsplit("ssh://" + scp.group(1) + "/" + scp.group(2))
        host = (parsed.hostname or "").lower().removesuffix(".")
    except ValueError:
        return False
    labels = host.split(".")
    return host in {"dev.azure.com", "ssh.dev.azure.com"} or (
        len(labels) > 2
        and labels[-2:] == ["visualstudio", "com"]
        and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels[:-2])
    )


def is_azure_operation(source_id: str, metadata: dict[str, Any], execution_repo: str = "") -> bool:
    provider = str(metadata.get("provider", "")).lower().replace("_", "-")
    return (
        source_id.lower().startswith(("azdo:", "azure:"))
        or provider in {"azure-devops", "azure"}
        or _has_azure_repository_origin(execution_repo)
    )


def active_scope_conflict(item: dict[str, Any], active_item: dict[str, Any]) -> bool:
    execution_repo, base_branch, write_scope = scheduler_fields(item)
    active_repo, active_base, active_scope = scheduler_fields(active_item)
    return (
        unknown_or_equal(execution_repo, active_repo)
        and unknown_or_equal(base_branch, active_base)
        and write_scopes_overlap(write_scope, active_scope)
    )


def item_state(item: dict[str, Any]) -> str:
    lifecycle = item.get("lifecycle") if isinstance(item.get("lifecycle"), dict) else {}
    raw = lifecycle.get("state") or item.get("state") or item.get("status") or ""
    return str(raw or "").strip().lower()


def item_id(item: dict[str, Any]) -> str:
    raw = item.get("id") or item.get("work_item_id") or item.get("source_id")
    if not raw:
        raise ValueError("Atlas work item is missing an id")
    return str(raw)


def event(
    event_type: str,
    *,
    status: str | None = None,
    operation_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": event_type, "at": now_rfc3339()}
    if status:
        payload["status"] = status
    if operation_id:
        payload["operation_id"] = operation_id
    if evidence:
        payload["evidence"] = evidence
    return payload


def work_item_context(item: dict[str, Any]) -> dict[str, Any]:
    source_id = item_id(item)
    scheduler = item.get("scheduler") if isinstance(item.get("scheduler"), dict) else {}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    # Keep prompt context explicit and bounded. Work-item records also carry
    # claims, lifecycle, results, evidence, and arbitrary integration metadata;
    # none of those belong in a role task packet.
    context: dict[str, Any] = {"title": str(item.get("title") or source_id)}
    if "atlas_daily_task" in metadata:
        context["atlas_daily_task"] = _bounded_atlas_daily_task(metadata["atlas_daily_task"])
    for key in ("description", "body", "goal", "objective", "task"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            context[key] = value.strip()
    for key in ("depends_on", "write_scope", "validation"):
        values = list_value(scheduler.get(key) or item.get(key))
        if values:
            context[key] = values
    for key in ("execution_repo", "base_branch"):
        value = scheduler.get(key) or metadata.get(key) or item.get(key)
        if isinstance(value, str) and value.strip():
            if key == "execution_repo":
                try:
                    parsed = urlsplit(value.strip())
                except ValueError:
                    continue
                # Checkout identity belongs in prompts; remote URL userinfo
                # does not. Preserve the scheduler's original value separately.
                if parsed.netloc:
                    value = parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[-1]).geturl()
            context[key] = value.strip()
    for key in ("spec_path", "spec_hash", "source_id", "dispatch_mode"):
        value = item.get(key) or metadata.get(key)
        if isinstance(value, str) and value.strip():
            context[key] = value.strip()
    for key in ("required_gates", "files_out_of_scope", "acceptance_criteria"):
        values = list_value(metadata.get(key) or item.get(key))
        if values:
            context[key] = values
    source_plan = metadata.get("source_plan")
    if isinstance(source_plan, dict):
        plan_context = {
            key: source_plan[key]
            for key in ("path", "hash")
            if isinstance(source_plan.get(key), str) and source_plan[key].strip()
        }
        if plan_context:
            context["source_plan"] = plan_context
    for key in ("manifest_leaf_id", "package_id", "package_hash"):
        value = metadata.get(key) or item.get(key)
        if isinstance(value, str) and value.strip():
            context[key] = value.strip()
    if "local_execution_v1" in metadata:
        contract = metadata["local_execution_v1"]
        allowed = {"policy_id", "role_purposes", "changed_interfaces", "unresolved_questions", "complexity_flags"}
        if isinstance(contract, dict) and not set(contract).difference(allowed):
            context["local_execution_v1"] = dict(contract)
        else:
            # Carry an invalid marker, never arbitrary provider/credential fields.
            # It must remain present so an invalid request cannot become legacy.
            context["local_execution_v1"] = {"invalid_contract": True}
    context["workflow_request"] = {
        key: scheduler.get(key) or metadata.get(key) or item.get(key)
        for key in ("workflow_kind", "team_template", "required_outputs")
        if scheduler.get(key) or metadata.get(key) or item.get(key)
    }
    prior = item.get("previous_attempts")
    if isinstance(prior, list) and prior and isinstance(prior[-1], dict):
        attempt = prior[-1]
        previous_result = attempt.get("result") if isinstance(attempt.get("result"), dict) else {}
        previous_evidence = previous_result.get("evidence") if isinstance(previous_result.get("evidence"), dict) else {}
        review = previous_evidence.get("goal_acceptance")
        context["rework"] = {"reason": attempt.get("reason"), "evidence": attempt.get("evidence"),
            "prior_goal_review": {key: review.get(key) for key in ("verdict", "reason", "evidence")} if isinstance(review, dict) else None}
    return context


def content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def requires_goal_review(item: dict[str, Any]) -> bool:
    scheduler = item.get("scheduler") if isinstance(item.get("scheduler"), dict) else {}
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    kind = scheduler.get("workflow_kind") or metadata.get("workflow_kind") or item.get("workflow_kind")
    template = scheduler.get("team_template") or metadata.get("team_template") or item.get("team_template")
    return kind in {"work-item", "review"} or template in {"work-item-change-lifecycle", "review-evidence-gate"}


def accepted_dependency(item: dict[str, Any]) -> bool:
    if item_state(item) != "done":
        return False
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    if not requires_goal_review(item) and not evidence.get("goal_review_required"):
        return True
    acceptance = evidence.get("goal_acceptance") or {}
    import atlas_workflows
    review = {key: acceptance.get(key) for key in ("verdict", "reason", "evidence")} if isinstance(acceptance, dict) else None
    return (isinstance(acceptance, dict) and acceptance.get("verdict") == "pass"
            and not atlas_workflows.goal_review_issues(review)
            and acceptance.get("context_hash") == content_hash(work_item_context(item))
            and result.get("status") == "done" and result.get("returncode") == 0)


def workflow_run_record(result: "OperationResult", *, allow_path_fallback: bool = True) -> dict[str, Any] | None:
    evidence = result.evidence if isinstance(result.evidence, dict) else {}
    team_run = evidence.get("team_run")
    if not isinstance(team_run, dict):
        return None
    record: dict[str, Any] = {
        "recorded_at": now_rfc3339(),
        "contract_hash": evidence.get("contract_hash"),
        "rework_count": evidence.get("rework_count", 0),
        "goal_acceptance": evidence.get("goal_acceptance"),
        "status": team_run.get("status"),
        "team_run": team_run,
        "workflow_selection": evidence.get("workflow_selection") if isinstance(evidence.get("workflow_selection"), dict) else {},
        "artifacts": {
            "team_run_path": evidence.get("team_run_path"),
            "team_rollup_path": evidence.get("team_rollup_path"),
            "team_role_tasks_path": evidence.get("team_role_tasks_path"),
            "team_role_results_path": evidence.get("team_role_results_path"),
        },
    }
    rollup_path = evidence.get("team_rollup_path")
    if isinstance(evidence.get("team_rollup_markdown"), str):
        record["team_rollup_markdown"] = evidence["team_rollup_markdown"][:20000]
    elif rollup_path and allow_path_fallback:
        try:
            record["team_rollup_markdown"] = pathlib.Path(str(rollup_path)).read_text(encoding="utf-8")[:20000]
        except OSError:
            record["team_rollup_read_error"] = str(rollup_path)
    return record


@dataclass(frozen=True)
class OperationState:
    operation_id: str
    source_type: str
    source_id: str
    title: str
    state: str
    ready: bool
    blockers: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    target_repo: str = ""
    execution_repo: str = ""
    base_branch: str = ""
    write_scope: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    work_item_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OperationResult:
    status: str
    returncode: int
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PilotTaskRequiresSupervisedHandoff(ValueError):
    """Raised when the ordinary worker is asked to process a pilot task."""


class AtlasWorkItemStore:
    """Small JSON-backed store for bootstrapping Atlas-owned local work items."""

    def __init__(self, path: str | pathlib.Path):
        self.path = pathlib.Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "work_items": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid Atlas work-item store JSON: {self.path}") from exc
        if isinstance(payload, list):
            return {"version": 1, "work_items": payload}
        if not isinstance(payload, dict):
            raise ValueError("Atlas work-item store must be a JSON object or list")
        if "work_items" not in payload and "items" in payload:
            payload["work_items"] = payload["items"]
        payload.setdefault("version", 1)
        payload.setdefault("work_items", [])
        if isinstance(payload["work_items"], dict):
            payload["work_items"] = [
                {"id": key, **value} if isinstance(value, dict) else {"id": key, "value": value}
                for key, value in payload["work_items"].items()
            ]
        if not isinstance(payload["work_items"], list):
            raise ValueError("Atlas work-item store field work_items must be a list or object")
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def update_item(self, source_id: str, updater: Any) -> dict[str, Any] | None:
        with self.lock():
            payload = self.load()
            for item in payload["work_items"]:
                if item_id(item) != source_id:
                    continue
                updated = updater(item)
                self.save(payload)
                return updated
        return None

    def lock(self) -> "_StoreLock":
        return _StoreLock(self.lock_path)


class _StoreLock:
    def __init__(self, path: pathlib.Path):
        self.path = path

    def __enter__(self) -> "_StoreLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + 30
        while True:
            self._remove_stale_lock()
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                if time.time() >= deadline:
                    raise RuntimeError(f"Timed out waiting for Atlas work-item store lock: {self.path}")
                time.sleep(0.1)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"pid": os.getpid(), "created_at": now_rfc3339()}) + "\n")
            return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.path.unlink(missing_ok=True)

    def _remove_stale_lock(self) -> None:
        try:
            lock_stat = self.path.stat()
        except FileNotFoundError:
            return
        age = time.time() - lock_stat.st_mtime
        if age > 300:
            self.path.unlink(missing_ok=True)
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(payload.get("pid"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            self.path.unlink(missing_ok=True)
        except PermissionError:
            return


class AtlasWorkItemOperationProvider:
    def __init__(self, store: AtlasWorkItemStore, *, claimed_by: str | None = None):
        self.store = store
        self.claimed_by = claimed_by or f"{socket.gethostname()}:{os.getpid()}"

    def ready_operations(self, limit: int | None = None) -> list[OperationState]:
        states = [operation for operation in self.operation_states() if operation.ready]
        states.sort(key=self.ready_sort_key)
        return states[:limit] if limit is not None else states

    def ready_sort_key(self, operation: OperationState) -> tuple[int, int, str]:
        return (
            priority_rank(operation.metadata.get("priority"), operation.labels),
            numeric_rank(operation.metadata.get("critical_path_rank")),
            operation.source_id,
        )

    def operation_states(self, limit: int | None = None) -> list[OperationState]:
        payload = self.store.load()
        states: list[OperationState] = []
        by_id = {item_id(item): item for item in payload.get("work_items", [])}
        for item in payload.get("work_items", []):
            operation = self.project(item, by_id)
            states.append(operation)
            if limit is not None and len(states) >= limit:
                break
        return states

    def project(self, item: dict[str, Any], by_id: dict[str, dict[str, Any]] | None = None) -> OperationState:
        source_id = item_id(item)
        state = item_state(item)
        scheduler = item.get("scheduler") if isinstance(item.get("scheduler"), dict) else {}
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        context = work_item_context(item)
        labels = list_value(item.get("labels"))
        blockers = self.blockers(item, by_id or {})
        ready = state in READY_STATES and not blockers
        operation_id = str(item.get("operation_id") or f"atlas-work-item:{source_id}")
        return OperationState(
            operation_id=operation_id,
            source_type="atlas_work_item",
            source_id=source_id,
            title=str(item.get("title") or source_id),
            state=state,
            ready=ready,
            blockers=blockers,
            labels=labels,
            target_repo=str(scheduler.get("target_repo") or metadata.get("target_repo") or item.get("target_repo") or ""),
            execution_repo=str(
                scheduler.get("execution_repo") or metadata.get("execution_repo") or item.get("execution_repo") or ""
            ),
            base_branch=str(scheduler.get("base_branch") or metadata.get("base_branch") or item.get("base_branch") or ""),
            write_scope=list_value(scheduler.get("write_scope") or item.get("write_scope")),
            metadata={
                "priority": scheduler.get("priority") or metadata.get("priority") or item.get("priority"),
                "rework_count": (item.get("lifecycle") if isinstance(item.get("lifecycle"), dict) else {}).get("rework_count", 0),
                "parallel_group": scheduler.get("parallel_group"),
                "critical_path_rank": scheduler.get("critical_path_rank"),
                "combine_policy": scheduler.get("combine_policy"),
                "validation_tier": scheduler.get("validation_tier"),
                "workflow_kind": scheduler.get("workflow_kind") or metadata.get("workflow_kind") or item.get("workflow_kind"),
                "team_template": scheduler.get("team_template") or metadata.get("team_template") or item.get("team_template"),
                "required_outputs": list_value(
                    scheduler.get("required_outputs") or metadata.get("required_outputs") or item.get("required_outputs")
                ),
            },
            work_item_context=context,
        )

    def blockers(self, item: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[str]:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        execution_repo, _, _ = scheduler_fields(item)
        if is_azure_operation(item_id(item), {**item, **metadata}, execution_repo):
            return ["Azure records require the Azure worker and its authority gates"]
        uncertainty = item.get("process_uncertainty")
        if isinstance(uncertainty, dict) and uncertainty.get("status") == "unresolved":
            return ["unresolved worker process uncertainty: " + str(uncertainty.get("invocation_id") or "identity unavailable")]
        state = item_state(item)
        if state in ACTIVE_STATES:
            return ["already claimed"]
        if state in TERMINAL_STATES:
            return [f"terminal state: {state}"]
        if state == "blocked":
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            result_status = result.get("status")
            if isinstance(result_status, str) and result_status in {"blocked", "failed"}:
                evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
                diagnostics: list[str] = []
                acceptance = evidence.get("goal_acceptance")
                if isinstance(acceptance, dict):
                    verdict = acceptance.get("verdict")
                    if not isinstance(verdict, str) or verdict not in {"pass", "fail", "inconclusive", "missing"}:
                        verdict = "inconclusive"
                    reason = acceptance.get("reason")
                    if isinstance(reason, str) and reason.strip():
                        diagnostics.append(f"goal review {verdict}: {reason.strip()[:300]}")
                    else:
                        diagnostics.append(f"goal review {verdict}: reason unavailable")
                elif result_status == "blocked":
                    diagnostics.append("goal review missing: goal review not available")
                for key in ("workflow_result_error", "workflow_error"):
                    detail = evidence.get(key)
                    if isinstance(detail, str) and detail.strip():
                        diagnostics.append(f"{key.replace('_', ' ')}: {detail.strip()[:300]}")
                summary = result.get("summary")
                if isinstance(summary, str) and summary.strip():
                    diagnostics.append(f"execution {result_status}: {summary.strip()[:300]}")
                if diagnostics:
                    return diagnostics
                return [f"execution {result_status}: details unavailable"]
            return [f"not ready: {state}"]
        if state not in READY_STATES:
            return [f"not ready: {state or 'missing state'}"]
        scheduler = item.get("scheduler") if isinstance(item.get("scheduler"), dict) else {}
        blockers = [f"blocker: {value}" for value in list_value(scheduler.get("blockers") or item.get("blockers"))]
        if "local_execution_v1" in metadata:
            import atlas_local_sizing
            qualification = atlas_local_sizing.qualify(work_item_context(item))
            if qualification["status"] != "qualified":
                blockers.append("local sizing: " + qualification["status"] + ": " + "; ".join(qualification.get("reasons") or []))
            else:
                checkout = pathlib.Path(execution_repo)
                if checkout.is_dir() and any((checkout / path).is_dir() for path in work_item_context(item).get("write_scope", [])):
                    blockers.append("local sizing: explicit write paths include a directory; split into exact files")
        for dependency in list_value(scheduler.get("depends_on") or item.get("depends_on")):
            dependency_item = by_id.get(dependency)
            if dependency_item is None:
                blockers.append(f"missing dependency: {dependency}")
            elif not accepted_dependency(dependency_item):
                blockers.append(f"open dependency: {dependency}")
        source_id = item_id(item)
        for active_id, active_item in by_id.items():
            uncertainty = active_item.get("process_uncertainty")
            unresolved_process = isinstance(uncertainty, dict) and uncertainty.get("status") == "unresolved"
            if active_id == source_id or (item_state(active_item) not in ACTIVE_STATES and not unresolved_process):
                continue
            if active_scope_conflict(item, active_item):
                blockers.append(f"active scope conflict: {active_id}")
        return blockers

    def claim(self, operation: OperationState) -> OperationState | None:
        claimed_at = now_rfc3339()
        claim_evidence = {
            "claimed_by": self.claimed_by,
            "claimed_at": claimed_at,
            "pid": os.getpid(),
            "operation": operation.to_dict(),
        }
        with self.store.lock():
            payload = self.store.load()
            items = payload.get("work_items", [])
            by_id = {item_id(item): item for item in items}
            item = by_id.get(operation.source_id)
            if item is None:
                return None
            current = self.project(item, by_id)
            if not current.ready:
                return None
            item["status"] = "running"
            item["state"] = "running"
            lifecycle = item.setdefault("lifecycle", {})
            if isinstance(lifecycle, dict):
                lifecycle["state"] = "running"
                lifecycle["claimed_at"] = claimed_at
            item["claim"] = claim_evidence
            item.setdefault("evidence", []).append(
                event("claim", status="running", operation_id=operation.operation_id, evidence=claim_evidence)
            )
            self.store.save(payload)
            return self.project(item, by_id)

    def requeue_stale_claims(
        self,
        *,
        stale_seconds: float,
        requeued_by: str | None = None,
        now: datetime | None = None,
        apply: bool = False,
    ) -> list[dict[str, Any]]:
        current = now or datetime.now(timezone.utc)
        actor = requeued_by or self.claimed_by
        with self.store.lock():
            payload = self.store.load()
            candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for item in payload.get("work_items", []):
                state = item_state(item)
                if state not in ACTIVE_STATES:
                    continue
                lifecycle = item.get("lifecycle") if isinstance(item.get("lifecycle"), dict) else {}
                claim = item.get("claim") if isinstance(item.get("claim"), dict) else {}
                uncertainty = item.get("process_uncertainty")
                if isinstance(uncertainty, dict) and uncertainty.get("status") == "unresolved":
                    continue
                claimed_at = lifecycle.get("claimed_at") or claim.get("claimed_at")
                age = age_seconds(claimed_at, now=current)
                if age is None or age < stale_seconds:
                    continue
                evidence = {
                    "source_id": item_id(item),
                    "previous_state": state,
                    "claimed_at": claimed_at,
                    "age_seconds": int(age),
                    "stale_seconds": int(stale_seconds),
                    "requeued_by": actor,
                    "previous_claim": claim,
                }
                candidates.append((item, evidence))
            if not apply:
                return [evidence for _, evidence in candidates]
            for item, evidence in candidates:
                item["status"] = "ready"
                item["state"] = "ready"
                lifecycle = item.setdefault("lifecycle", {})
                if isinstance(lifecycle, dict):
                    lifecycle["state"] = "ready"
                    lifecycle["requeued_at"] = now_rfc3339()
                    lifecycle["requeue_reason"] = "stale claim"
                previous_claim = item.pop("claim", None)
                if previous_claim:
                    item.setdefault("previous_claims", []).append(previous_claim)
                item.setdefault("evidence", []).append(
                    event("requeue", status="ready", evidence=evidence)
                )
            self.store.save(payload)
            return [evidence for _, evidence in candidates]

    def record_result(self, operation: OperationState, result: OperationResult) -> None:
        status = result.status if result.status in {"done", "failed", "ready", "queued", "blocked"} else "failed"

        def apply_result(item: dict[str, Any]) -> dict[str, Any]:
            if status == "done" and atlas_delta_review.pilot_task_enabled(item):
                current_execution_repo, _, _ = scheduler_fields(item)
                if operation.execution_repo != current_execution_repo:
                    raise ValueError("work-item execution repository changed since operation projection")
                atlas_delta_review.validate_pilot_task_completion(
                    item, expected_checkout=current_execution_repo
                )
            uncertainty = item.get("process_uncertainty")
            result_to_store = result.to_dict()
            completed_invocation = (
                isinstance(uncertainty, dict) and uncertainty.get("status") == "unresolved"
                and result_to_store.get("evidence", {}).get("process_invocation_id") == uncertainty.get("invocation_id")
                and result_to_store.get("evidence", {}).get("invocation_completed") is True
                and result_to_store.get("evidence", {}).get("termination_proved") is True
            )
            unresolved = isinstance(uncertainty, dict) and uncertainty.get("status") == "unresolved" and not completed_invocation
            effective_status = "blocked" if unresolved else status
            if unresolved:
                result_to_store["status"] = "blocked"
                result_to_store["summary"] = "Worker result cannot clear unresolved process uncertainty"
                result_to_store["evidence"] = {**result_to_store.get("evidence", {}), "process_uncertainty": uncertainty}
            item["status"] = effective_status
            item["state"] = effective_status
            lifecycle = item.setdefault("lifecycle", {})
            if isinstance(lifecycle, dict):
                lifecycle["state"] = effective_status
                lifecycle["last_result_at"] = now_rfc3339()
                if effective_status in TERMINAL_STATES:
                    lifecycle["completed_at"] = lifecycle["last_result_at"]
                elif effective_status in READY_STATES:
                    lifecycle["requeued_at"] = lifecycle["last_result_at"]
                    lifecycle["requeue_reason"] = "workflow incomplete"
            if effective_status in READY_STATES:
                previous_claim = item.pop("claim", None)
                if previous_claim:
                    item.setdefault("previous_claims", []).append(previous_claim)
            item["result"] = result_to_store
            if completed_invocation:
                item["process_uncertainty"] = {**uncertainty, "status": "resolved", "resolved_at": now_rfc3339()}
            workflow_record = workflow_run_record(
                result, allow_path_fallback="local_execution_v1" not in operation.work_item_context,
            )
            if workflow_record:
                workflow_record["operation_id"] = operation.operation_id
                runs = item.setdefault("workflow_runs", [])
                if isinstance(runs, list):
                    run_id = (workflow_record.get("team_run") or {}).get("run_id")
                    runs[:] = [
                        run
                        for run in runs
                        if not (
                            isinstance(run, dict)
                            and isinstance(run.get("team_run"), dict)
                            and run["team_run"].get("run_id") == run_id
                        )
                    ]
                    runs.append(workflow_record)
            item.setdefault("evidence", []).append(
                event("result", status=effective_status, operation_id=operation.operation_id, evidence=result_to_store)
            )
            return item

        self.store.update_item(operation.source_id, apply_result)

    def requeue_for_rework(self, source_id: str, *, reason: str, evidence: list[str]) -> dict[str, Any]:
        """Permit one explicit, evidenced rework; never recycle acceptance automatically."""
        if not isinstance(reason, str) or not reason.strip() or not isinstance(evidence, list) or not evidence or any(
            not isinstance(value, str) or not value.strip() for value in evidence
        ):
            raise ValueError("rework requires a nonempty reason and evidence list")

        def rework(item: dict[str, Any]) -> dict[str, Any]:
            uncertainty = item.get("process_uncertainty")
            if isinstance(uncertainty, dict) and uncertainty.get("status") == "unresolved":
                raise ValueError("unresolved process uncertainty cannot be explicitly reworked")
            if item_state(item) != "blocked":
                raise ValueError("only blocked items can be reworked")
            lifecycle = item.setdefault("lifecycle", {})
            if lifecycle.get("rework_count", 0) != 0:
                raise ValueError("rework budget exhausted (one explicit rework maximum)")
            item.setdefault("previous_attempts", []).append({
                "result": item.pop("result", None), "workflow_runs": item.pop("workflow_runs", []),
                "reason": reason.strip(), "evidence": evidence, "at": now_rfc3339(),
            })
            claim = item.pop("claim", None)
            if claim:
                item.setdefault("previous_claims", []).append(claim)
            lifecycle.update(state="ready", rework_count=1, requeue_reason=reason.strip())
            lifecycle.pop("completed_at", None)
            item.update(status="ready", state="ready")
            item.setdefault("evidence", []).append(event("explicit-rework", status="ready", evidence={
                "reason": reason.strip(), "evidence": evidence, "rework_count": 1,
            }))
            return item

        updated = self.store.update_item(source_id, rework)
        if updated is None:
            raise ValueError(f"unknown work item: {source_id}")
        return updated


class LocalCommandOperationWorker:
    def __init__(
        self,
        command: list[str] | None,
        *,
        jobs_dir: str | pathlib.Path,
        templates_dir: str | pathlib.Path | None = None,
        agent_registry_path: str | pathlib.Path | None = None,
        agent_root: str | pathlib.Path | None = None,
        timeout_seconds: float = 900,
        termination_grace_seconds: float = 1.0,
        cancellation_poll_seconds: float = 0.1,
    ):
        if not isinstance(timeout_seconds, (int, float)) or not __import__("math").isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if not isinstance(termination_grace_seconds, (int, float)) or not __import__("math").isfinite(termination_grace_seconds) or termination_grace_seconds < 0:
            raise ValueError("termination_grace_seconds must be finite and nonnegative")
        if not isinstance(cancellation_poll_seconds, (int, float)) or not __import__("math").isfinite(cancellation_poll_seconds) or cancellation_poll_seconds <= 0:
            raise ValueError("cancellation_poll_seconds must be finite and positive")
        self.command = command
        self.jobs_dir = pathlib.Path(jobs_dir)
        self.templates_dir = pathlib.Path(templates_dir) if templates_dir else None
        self.agent_registry_path = pathlib.Path(agent_registry_path) if agent_registry_path else None
        self.agent_root = pathlib.Path(agent_root) if agent_root else None
        self.timeout_seconds = float(timeout_seconds)
        self.termination_grace_seconds = float(termination_grace_seconds)
        self.cancellation_poll_seconds = float(cancellation_poll_seconds)

    @staticmethod
    def _process_group_exists(pgid: int) -> bool:
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    @staticmethod
    def _process_group_has_descendants(pgid: int) -> bool | None:
        proc_root = pathlib.Path("/proc")
        if not proc_root.is_dir():
            return None
        unknown = False
        try:
            for stat_path in proc_root.glob("[0-9]*/stat"):
                try:
                    raw = stat_path.read_text(encoding="ascii")
                    fields = raw[raw.rfind(")") + 2:].split()
                    if len(fields) > 2 and int(fields[2]) == pgid and int(stat_path.parent.name) != pgid:
                        return True
                except PermissionError:
                    unknown = True
                except (FileNotFoundError, ProcessLookupError):
                    continue
                except (OSError, ValueError):
                    unknown = True
        except OSError:
            return None
        return None if unknown else False

    @staticmethod
    def _holds_unreaped_child(proc: subprocess.Popen[bytes]) -> bool:
        """Require a current waitable-child witness before signaling its group."""
        try:
            observed = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            return observed is None or getattr(observed, "si_pid", proc.pid) == proc.pid
        except BaseException:
            return False

    def _stop_process_group(self, proc: subprocess.Popen[bytes], *, leader_exited: bool = False) -> bool:
        """Stop only the process group created and held by this invocation."""
        pgid = proc.pid
        if not self._holds_unreaped_child(proc):
            self._last_shutdown = {"term_sent": False, "kill_sent": False, "leader_reaped": False,
                "group_status": "custody_lost"}
            return False
        has_descendants = self._process_group_has_descendants(pgid)
        term_sent = False
        kill_sent = False
        if leader_exited and has_descendants is False:
            # A live group leader is itself sufficient to anchor the group ID.
            try:
                proc.wait(timeout=max(0.1, self.termination_grace_seconds))
                self._last_shutdown = {"term_sent": False, "kill_sent": False, "leader_reaped": True,
                    "group_status": "no_descendants_observed"}
                return True
            except subprocess.TimeoutExpired:
                pass
        if self._process_group_exists(pgid):
            if not self._holds_unreaped_child(proc):
                self._last_shutdown = {"term_sent": False, "kill_sent": False, "leader_reaped": False,
                    "group_status": "custody_lost"}
                return False
            try:
                os.killpg(pgid, signal.SIGTERM)
                term_sent = True
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + self.termination_grace_seconds
            while time.monotonic() < deadline and self._process_group_exists(pgid):
                time.sleep(min(self.cancellation_poll_seconds, max(0, deadline - time.monotonic())))
            if self._process_group_exists(pgid):
                if not self._holds_unreaped_child(proc):
                    self._last_shutdown = {"term_sent": term_sent, "kill_sent": False, "leader_reaped": False,
                        "group_status": "custody_lost"}
                    return False
                try:
                    os.killpg(pgid, signal.SIGKILL)
                    kill_sent = True
                except ProcessLookupError:
                    pass
        try:
            proc.wait(timeout=max(0.1, self.termination_grace_seconds))
        except subprocess.TimeoutExpired:
            if not self._holds_unreaped_child(proc):
                self._last_shutdown = {"term_sent": term_sent, "kill_sent": False, "leader_reaped": False,
                    "group_status": "custody_lost"}
                return False
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._last_shutdown = {"term_sent": term_sent, "kill_sent": kill_sent, "leader_reaped": False,
                    "group_status": "leader_wait_timeout"}
                return False
        deadline = time.monotonic() + max(0.1, self.termination_grace_seconds)
        while time.monotonic() < deadline and self._process_group_exists(pgid):
            time.sleep(min(self.cancellation_poll_seconds, max(0, deadline - time.monotonic())))
        remaining = self._process_group_exists(pgid)
        self._last_shutdown = {"term_sent": term_sent, "kill_sent": kill_sent, "leader_reaped": proc.returncode is not None,
            "group_status": "present" if remaining else "absent"}
        return not remaining

    def load_agent_registry(self) -> Any:
        if self.agent_registry_path is None or not self.agent_registry_path.exists():
            return None
        import atlas_workflows

        return atlas_workflows.load_agent_registry(self.agent_registry_path)

    def run(self, operation: OperationState, store_path: pathlib.Path, *, cancel_event: Any = None) -> OperationResult:
        self._last_shutdown = {"term_sent": False, "kill_sent": False, "leader_reaped": False,
            "group_status": "not_started"}
        if is_azure_operation(operation.source_id, operation.metadata, operation.execution_repo):
            return OperationResult(
                status="failed", returncode=2,
                summary="Azure records require the Azure worker and its authority gates",
            )
        if "local_execution_v1" in operation.work_item_context:
            expected_runner = pathlib.Path(__file__).resolve().parent / "atlas-agent-role-runner"
            valid_runner = bool(self.command and pathlib.Path(self.command[0]).resolve() == expected_runner
                and len(self.command) == 5 and self.command[1] == "--command-config"
                and self.command[3] == "--max-roles" and self.command[4].isdigit()
                and 1 <= int(self.command[4]) <= 100)
            if not valid_runner:
                return OperationResult(status="blocked", returncode=2,
                    summary="Contracted local work requires canonical runner arguments; packet or raw command bypass is forbidden")
        job_id = uuid.uuid4().hex
        job_dir = self.jobs_dir / f"atlas-work-item-{safe_id(operation.source_id)}-{job_id}"
        job_dir.mkdir(parents=True, exist_ok=True)
        operation_path = job_dir / "operation.json"
        operation_path.write_text(json.dumps(operation.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        workflow_evidence = self.write_workflow_artifacts(operation, job_dir, job_id, store_path)
        role_results_path = job_dir / "team-role-results.json"
        if workflow_evidence.get("workflow_error"):
            return OperationResult(status="blocked", returncode=2,
                summary="Local workflow blocked: " + str(workflow_evidence["workflow_error"]),
                evidence={"job_dir": str(job_dir), "operation_path": str(operation_path), **workflow_evidence})
        if not self.command:
            return OperationResult(
                status="failed",
                returncode=2,
                summary="No local work-item command configured; execution and acceptance are missing.",
                evidence={
                    "job_dir": str(job_dir),
                    "operation_path": str(operation_path),
                    "mode": "missing-command",
                    **workflow_evidence,
                },
            )

        if cancel_event is not None and cancel_event.is_set():
            return OperationResult(status="blocked", returncode=125,
                summary="Local work cancelled before process start", evidence={"job_dir": str(job_dir), "operation_path": str(operation_path), "cancelled_before_start": True, **workflow_evidence})

        env = os.environ.copy()
        env.update(
            {
                "ATLAS_WORK_ITEM_ID": operation.source_id,
                "ATLAS_OPERATION_ID": operation.operation_id,
                "ATLAS_WORK_ITEM_STORE": str(store_path),
                "ATLAS_OPERATION_FILE": str(operation_path),
                "ATLAS_JOB_DIR": str(job_dir),
                "ATLAS_TEAM_ROLE_RESULTS_FILE": str(role_results_path),
            }
        )
        if workflow_evidence.get("team_run_path"):
            env["ATLAS_TEAM_RUN_FILE"] = str(workflow_evidence["team_run_path"])
        if workflow_evidence.get("team_rollup_path"):
            env["ATLAS_TEAM_ROLLUP_FILE"] = str(workflow_evidence["team_rollup_path"])
        if workflow_evidence.get("team_role_tasks_path"):
            env["ATLAS_TEAM_ROLE_TASKS_FILE"] = str(workflow_evidence["team_role_tasks_path"])
        if workflow_evidence.get("team_template"):
            env["ATLAS_TEAM_TEMPLATE"] = str(workflow_evidence["team_template"])
        start = time.monotonic()
        invocation = {
            "status": "unresolved", "invocation_id": job_id,
            "command_sha256": hashlib.sha256(json.dumps(self.command).encode("utf-8")).hexdigest(),
            "started_at": now_rfc3339(), "job_dir": str(job_dir),
        }
        store = AtlasWorkItemStore(store_path)
        def mark_uncertain(item: dict[str, Any]) -> dict[str, Any]:
            existing = item.get("process_uncertainty")
            if isinstance(existing, dict) and existing.get("status") == "unresolved":
                raise RuntimeError("another worker invocation remains unresolved")
            item["process_uncertainty"] = dict(invocation)
            return item
        try:
            if store.update_item(operation.source_id, mark_uncertain) is None:
                return OperationResult(status="blocked", returncode=2, summary="Work item disappeared before process start; no child started")
        except Exception as exc:
            return OperationResult(status="blocked", returncode=2, summary="Could not durably record invocation uncertainty; no child started", evidence={"error": str(exc)})
        if cancel_event is not None and cancel_event.is_set():
            store.update_item(operation.source_id, lambda item: item["process_uncertainty"].update(status="resolved", resolved_at=now_rfc3339(), cancelled_before_start=True) or item)
            return OperationResult(status="blocked", returncode=125,
                summary="Local work cancelled before process start", evidence={"job_dir": str(job_dir), "operation_path": str(operation_path), "cancelled_before_start": True, **workflow_evidence})
        output_path = job_dir / "worker-output.txt"
        contracted_local = "local_execution_v1" in operation.work_item_context
        job_dir_fd: int | None = None
        job_parent_fd: int | None = None
        job_dir_identity: tuple[int, int] | None = None
        job_parent_identity: tuple[int, int] | None = None
        if contracted_local:
            nofollow = getattr(os, "O_NOFOLLOW", None)
            if nofollow is None:
                return OperationResult(status="blocked", returncode=2,
                    summary="Contracted workflow cannot pin job-directory identity on this platform",
                    evidence={"job_dir": str(job_dir), "invocation_completed": False})
            try:
                directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow | getattr(os, "O_CLOEXEC", 0)
                job_parent_fd = os.open(job_dir.parent, directory_flags)
                parent_info = os.fstat(job_parent_fd)
                if not stat.S_ISDIR(parent_info.st_mode):
                    raise OSError(errno.ENOTDIR, "job parent is not a directory")
                job_parent_identity = (parent_info.st_dev, parent_info.st_ino)
                job_dir_fd = os.open(job_dir.name, directory_flags, dir_fd=job_parent_fd)
                job_info = os.fstat(job_dir_fd)
            except OSError as exc:
                if job_dir_fd is not None:
                    os.close(job_dir_fd)
                    job_dir_fd = None
                if job_parent_fd is not None:
                    os.close(job_parent_fd)
                    job_parent_fd = None
                return OperationResult(status="blocked", returncode=2,
                    summary="Contracted workflow could not hold its job-directory identity",
                    evidence={"job_dir": str(job_dir), "invocation_completed": False,
                              "job_directory_error": str(exc)})
            if not stat.S_ISDIR(job_info.st_mode):
                os.close(job_dir_fd)
                job_dir_fd = None
                os.close(job_parent_fd)
                job_parent_fd = None
                return OperationResult(status="blocked", returncode=2,
                    summary="Contracted workflow job path is not a directory",
                    evidence={"job_dir": str(job_dir), "invocation_completed": False})
            job_dir_identity = (job_info.st_dev, job_info.st_ino)
            if _job_directory_identity(job_dir, job_dir_fd, job_parent_fd, job_parent_identity) != job_dir_identity:
                os.close(job_dir_fd)
                os.close(job_parent_fd)
                return OperationResult(status="blocked", returncode=2,
                    summary="Contracted job-directory parent identity changed before launch",
                    evidence={"job_dir": str(job_dir), "invocation_completed": False,
                              "job_directory_identity_changed": True})
        proc = None
        try:
            if job_dir_fd is not None:
                output_fd = os.open("worker-output.txt", os.O_RDWR | os.O_CREAT | os.O_TRUNC |
                                    getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                                    0o600, dir_fd=job_dir_fd)
                output_handle_context = os.fdopen(output_fd, "w+b")
            else:
                output_handle_context = output_path.open("w+b")
            with output_handle_context as output_handle:
                proc = subprocess.Popen(
                    self.command,
                    cwd=str(job_dir),
                    env=env,
                    start_new_session=True,
                    stdout=output_handle,
                    stderr=subprocess.STDOUT,
                )
                invocation.update(pid=proc.pid, pgid=proc.pid)
                result = self._finish_started_process(
                    proc, job_id=job_id, job_dir=job_dir, operation_path=operation_path,
                    role_results_path=role_results_path, output_path=output_path,
                    workflow_evidence=workflow_evidence, start=start, cancel_event=cancel_event,
                    job_dir_fd=job_dir_fd, job_dir_identity=job_dir_identity, output_handle=output_handle,
                    job_parent_fd=job_parent_fd, job_parent_identity=job_parent_identity,
                )
            return result
        except BaseException as exc:
            if proc is None:
                # The launch call's acknowledgment is ambiguous. Keep the durable
                # invocation marker and never infer a PID to signal.
                return OperationResult(status="blocked", returncode=127,
                    summary="Process launch outcome is uncertain; item remains blocked pending operator inspection.",
                    evidence={"job_dir": str(job_dir), "operation_path": str(operation_path),
                        "output_path": str(output_path), "process_invocation_id": job_id,
                        "launch_error": repr(exc), "invocation_completed": False})

            shutdown_error = ""
            if proc.returncode is None and self._holds_unreaped_child(proc):
                try:
                    self._stop_process_group(proc)
                except BaseException as cleanup_exc:
                    shutdown_error = repr(cleanup_exc)
            elif proc.returncode is None:
                prior = dict(getattr(self, "_last_shutdown", {}))
                self._last_shutdown = {**prior, "group_status": "custody_lost"}
            try:
                if job_dir_fd is not None:
                    output = _read_job_file(job_dir_fd, "worker-output.txt", limit=_CONTRACTED_WORKER_OUTPUT_LIMIT_BYTES) or b""
                else:
                    output = output_path.read_bytes()
            except OSError:
                output = b""
            try:
                returncode = proc.returncode if proc.returncode is not None else 124
            except BaseException:
                returncode = 124
            return OperationResult(status="blocked", returncode=returncode,
                summary="Local worker supervision was interrupted; process uncertainty remains unresolved.",
                evidence={"job_dir": str(job_dir), "operation_path": str(operation_path),
                    "output_path": str(output_path), "partial_output_bytes": len(output),
                    "process_invocation_id": job_id, "process_pid": proc.pid, "process_pgid": proc.pid,
                    "termination_proved": getattr(self, "_last_shutdown", {}).get("group_status") in
                        {"absent", "no_descendants_observed"},
                    "invocation_completed": False,
                    "process_shutdown": getattr(self, "_last_shutdown", {}),
                    "supervisor_error": repr(exc), "cleanup_error": shutdown_error})
        finally:
            if job_dir_fd is not None:
                os.close(job_dir_fd)
            if job_parent_fd is not None:
                os.close(job_parent_fd)

    def _finish_started_process(
        self, proc: subprocess.Popen[bytes], *, job_id: str, job_dir: pathlib.Path,
        operation_path: pathlib.Path, role_results_path: pathlib.Path, output_path: pathlib.Path,
        workflow_evidence: dict[str, Any], start: float, cancel_event: Any,
        job_dir_fd: int | None = None, job_dir_identity: tuple[int, int] | None = None,
        job_parent_fd: int | None = None, job_parent_identity: tuple[int, int] | None = None,
        output_handle: Any = None,
    ) -> OperationResult:
        deadline = start + self.timeout_seconds
        cancelled = False
        timed_out = False
        output = b""
        output_overflow = False
        child_exited = False
        termination_proved = False
        poll_error: BaseException | None = None
        custody_lost = False
        try:
            while not child_exited:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                try:
                    child_exited = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
                except ChildProcessError:
                    custody_lost = True
                    self._last_shutdown = {"term_sent": False, "kill_sent": False, "leader_reaped": False,
                        "group_status": "custody_lost"}
                    break
                if child_exited:
                    break
                time.sleep(min(self.cancellation_poll_seconds, max(0, deadline - time.monotonic())))
            # Keep the direct child unreaped while cleaning its group, so the group ID
            # remains tied to this invocation and cannot be reused for an unrelated PID.
            if not custody_lost:
                termination_proved = self._stop_process_group(proc, leader_exited=child_exited)
        except ChildProcessError as exc:
            custody_lost = True
            self._last_shutdown = {**dict(getattr(self, "_last_shutdown", {})),
                "group_status": "custody_lost", "cleanup_error": repr(exc)}
        except BaseException as exc:
            poll_error = exc
            emergency_kill_sent = False
            if self._holds_unreaped_child(proc):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                    emergency_kill_sent = True
                except BaseException:
                    pass
            else:
                custody_lost = True
                prior_shutdown = dict(getattr(self, "_last_shutdown", {}))
            try:
                if not custody_lost:
                    proc.wait(timeout=1.0)
                    termination_proved = not self._process_group_exists(proc.pid)
            except BaseException:
                termination_proved = False
            if custody_lost:
                self._last_shutdown = {**prior_shutdown, "group_status": "custody_lost"}
            else:
                self._last_shutdown = {"term_sent": False, "kill_sent": emergency_kill_sent,
                    "leader_reaped": proc.returncode is not None,
                    "group_status": "absent" if termination_proved else "unknown"}
        if output_handle is not None:
            output_handle.flush()
            output_handle.seek(0)
            if job_dir_fd is not None:
                bounded = output_handle.read(_CONTRACTED_WORKER_OUTPUT_LIMIT_BYTES + 1)
                output_overflow = len(bounded) > _CONTRACTED_WORKER_OUTPUT_LIMIT_BYTES
                output = bounded[:_CONTRACTED_WORKER_OUTPUT_LIMIT_BYTES]
            else:
                output = output_handle.read()
        else:
            output = output_path.read_bytes()
        duration_ms = int((time.monotonic() - start) * 1000)
        decoded_output = output.decode("utf-8", errors="replace")
        if job_dir_fd is None:
            workflow_evidence = self.apply_workflow_role_results(workflow_evidence, role_results_path)
        if custody_lost:
            return OperationResult(status="blocked", returncode=124,
                summary="Worker child custody was lost; no further process-group signal is allowed.",
                evidence={"job_dir": str(job_dir), "operation_path": str(operation_path), "output_path": str(output_path),
                    "duration_ms": duration_ms, "process_invocation_id": job_id, "process_pid": proc.pid,
                    "process_pgid": proc.pid, "termination_proved": False,
                    "invocation_completed": False, "process_shutdown": getattr(self, "_last_shutdown", {
                    "term_sent": False, "kill_sent": False, "leader_reaped": False, "group_status": "custody_lost"}),
                    **workflow_evidence})
        if cancelled or timed_out or not termination_proved or poll_error is not None:
            reason = "cancelled" if cancelled else "timed out" if timed_out else "supervisor interrupted" if poll_error else "process group shutdown could not be proved"
            return OperationResult(status="blocked", returncode=proc.returncode if proc.returncode is not None else 124,
                summary=f"Local worker {reason}; process uncertainty remains unresolved.",
                evidence={"job_dir": str(job_dir), "operation_path": str(operation_path), "output_path": str(output_path),
                    "duration_ms": duration_ms, "process_invocation_id": job_id, "termination_proved": termination_proved,
                    "process_pid": proc.pid, "process_pgid": proc.pid,
                    "cancelled": cancelled, "timed_out": timed_out, "supervisor_error": repr(poll_error) if poll_error else "",
                    "invocation_completed": False, "process_shutdown": getattr(self, "_last_shutdown", {}), **workflow_evidence})
        if job_dir_fd is not None:
            if (job_dir_identity is None or job_parent_fd is None or job_parent_identity is None
                    or _job_directory_identity(job_dir, job_dir_fd, job_parent_fd, job_parent_identity) != job_dir_identity):
                return OperationResult(status="blocked", returncode=proc.returncode if proc.returncode is not None else 124,
                    summary="Contracted job-directory identity changed; aggregate results were refused.",
                    evidence={"job_dir": str(job_dir), "operation_path": str(operation_path),
                        "output_path": str(output_path), "duration_ms": duration_ms,
                        "process_invocation_id": job_id, "process_pid": proc.pid, "process_pgid": proc.pid,
                        "termination_proved": True, "invocation_completed": False,
                        "job_directory_identity_changed": True,
                        "process_shutdown": getattr(self, "_last_shutdown", {})})
            workflow_evidence = self.apply_workflow_role_results(
                workflow_evidence, role_results_path, job_dir_fd=job_dir_fd, job_dir=job_dir,
                job_parent_fd=job_parent_fd, job_parent_identity=job_parent_identity,
            )
        status = "done" if proc.returncode == 0 else "failed"
        acceptance_missing = workflow_evidence.get("team_run_status") != "complete"
        if acceptance_missing or output_overflow:
            status = "failed"
        if workflow_evidence.get("team_run_status") == "blocked" or workflow_evidence.get("workflow_result_error"):
            status = "blocked"
        elif workflow_evidence.get("team_run_status") == "running":
            new_completed = set(workflow_evidence.get("completed_roles") or []) - set(workflow_evidence.get("completed_roles_before") or [])
            if new_completed:
                status = "ready"
                workflow_evidence["workflow_continuation"] = {
                    "reason": "required workflow outputs remain incomplete",
                    "next_status": "ready",
                }
            else:
                status = "blocked"
                workflow_evidence["workflow_incomplete"] = {
                    "reason": "required workflow outputs remain incomplete and no new role completed",
                    "next_status": "blocked",
                }
        if workflow_evidence.get("goal_review_required") and status == "done":
            if (workflow_evidence.get("goal_acceptance") or {}).get("verdict") != "pass":
                status = "blocked"
        if output_overflow:
            status = "failed"
        return OperationResult(
            status=status,
            returncode=proc.returncode,
            summary=(
                f"Contracted worker output exceeded the {_CONTRACTED_WORKER_OUTPUT_LIMIT_BYTES}-byte limit"
                if output_overflow else
                "Worker exited without complete acceptance evidence"
                if acceptance_missing else
                (decoded_output.strip().splitlines()[-1] if decoded_output.strip() else "worker exited")
            ),
            evidence={
                "job_dir": str(job_dir),
                "operation_path": str(operation_path),
                "output_path": str(output_path),
                "duration_ms": duration_ms,
                "process_invocation_id": job_id,
                "process_pid": proc.pid,
                "process_pgid": proc.pid,
                "termination_proved": True,
                "invocation_completed": True,
                "output_limit_exceeded": output_overflow,
                "process_shutdown": getattr(self, "_last_shutdown", {}),
                **workflow_evidence,
            },
        )

    def write_workflow_artifacts(
        self,
        operation: OperationState,
        job_dir: pathlib.Path,
        job_id: str,
        store_path: pathlib.Path,
    ) -> dict[str, Any]:
        if self.templates_dir is None or not self.templates_dir.exists():
            return {}
        workflow_kind = operation.metadata.get("workflow_kind")
        template_id = operation.metadata.get("team_template")
        required_outputs = operation.metadata.get("required_outputs") or []
        if not workflow_kind and not template_id:
            return {}
        try:
            import atlas_workflows

            templates = atlas_workflows.load_team_templates(self.templates_dir)
            registry = self.load_agent_registry()
            work_item = {
                "id": operation.source_id,
                "title": operation.title,
                "scheduler": {
                    "workflow_kind": workflow_kind,
                    "team_template": template_id,
                    "required_outputs": required_outputs,
                },
            }
            selection_report = atlas_workflows.template_selection_report(
                templates,
                atlas_workflows.work_item_workflow_request(work_item),
            )
            template = atlas_workflows.select_team_template_for_work_item(templates, work_item)
        except Exception as exc:
            return {"workflow_error": str(exc)}
        if template is None:
            return {
                "workflow_request": {
                    "workflow_kind": workflow_kind,
                    "team_template": template_id,
                    "required_outputs": required_outputs,
                },
                "workflow_selection": atlas_workflows.compact_template_selection_report(selection_report),
                "workflow_error": "no matching team template",
            }
        sizing: dict[str, Any] = {}
        if "local_execution_v1" in operation.work_item_context:
            import atlas_local_sizing
            sizing = atlas_local_sizing.qualify(operation.work_item_context,
                roles=[{"role_id": role.id, "goal_gate": role.goal_gate} for role in template.roles])
            if sizing["status"] != "qualified":
                return {"workflow_error": "local sizing: " + sizing["status"] + ": " + "; ".join(sizing.get("reasons") or []),
                        "local_sizing": sizing}
            if not any(role.goal_gate for role in template.roles):
                return {"workflow_error": "model-sized workflows require an independent goal gate", "local_sizing": sizing}
        gates = [role for role in template.roles if role.goal_gate]
        goal_required = template.workflow_kind in {"work-item", "review"} or workflow_kind in {"work-item", "review"} or bool(gates)
        if goal_required:
            if len(gates) != 1:
                return {"workflow_error": "goal-reviewed workflows require exactly one independent goal gate", "goal_review_required": True}
            gate = gates[0]
            needed = {role.id for role in template.roles if role.id in {"implementation", "test-runner"}}
            if gate.id in needed or not needed.issubset(set(gate.consumes)):
                return {"workflow_error": "goal gate must consume implementation and test evidence independently", "goal_review_required": True}
            context = operation.work_item_context
            if not any(context.get(key) for key in ("goal", "objective", "description", "body", "task")) or not context.get("acceptance_criteria"):
                return {"workflow_error": "goal review requires substantive goal/task and acceptance criteria", "goal_review_required": True}
        contract_payload = {"context": operation.work_item_context, "template": template.to_dict()}
        if sizing:
            contract_payload["local_sizing"] = sizing
        fingerprint = content_hash(contract_payload)
        rework_count = operation.metadata.get("rework_count", 0)
        try:
            previous_run = self.load_resumable_team_run(store_path, operation.source_id, template.id,
                contract_hash=fingerprint, rework_count=rework_count, required=goal_required)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            return {"workflow_error": str(exc), "goal_review_required": goal_required, "contract_hash": fingerprint}
        team_run = previous_run or atlas_workflows.TeamRun.start(
            run_id=f"{safe_id(operation.source_id)}-{job_id}",
            template=template,
            work_item_id=operation.source_id,
        )
        team_run.refresh_status(template)
        missing_outputs = team_run.missing_outputs(template)
        run_path = job_dir / "team-run.json"
        rollup_path = job_dir / "team-rollup.md"
        role_tasks_path = job_dir / "team-role-tasks.json"
        run_path.write_text(json.dumps(team_run.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        rollup_path.write_text(team_run.rollup_markdown(template), encoding="utf-8")
        atlas_workflows.write_role_task_packets(
            role_tasks_path,
            template,
            team_run,
            registry=registry,
            agent_root=self.agent_root,
            work_item_context=operation.work_item_context,
        )
        return {
            "team_template": template.id,
            "workflow_kind": template.workflow_kind,
            "local_sizing": sizing,
            "contract_hash": fingerprint,
            "rework_count": rework_count,
            "goal_review_required": goal_required,
            "goal_acceptance": self.goal_acceptance(template, team_run, operation.work_item_context, fingerprint),
            "completed_roles_before": [role.id for role in template.roles
                if atlas_workflows.role_result_satisfies_outputs(role, team_run.role_results.get(role.id))],
            "workflow_resumed": previous_run is not None,
            "team_roles": [role.id for role in template.roles],
            "missing_outputs": missing_outputs,
            "team_run_path": str(run_path),
            "team_rollup_path": str(rollup_path),
            "team_role_tasks_path": str(role_tasks_path),
            "team_run_status": team_run.status,
            "team_run": atlas_workflows.team_run_summary(template, team_run),
            "workflow_selection": atlas_workflows.compact_template_selection_report(selection_report),
            "work_item_context": operation.work_item_context,
            "agent_registry_path": str(self.agent_registry_path) if self.agent_registry_path else "",
            "agent_root": str(self.agent_root) if self.agent_root else "",
        }

    def load_resumable_team_run(
        self,
        store_path: pathlib.Path,
        source_id: str,
        template_id: str,
        *, contract_hash: str | None = None, rework_count: int = 0, required: bool = False,
    ) -> Any:
        try:
            import atlas_workflows

            payload = AtlasWorkItemStore(store_path).load()
            item = next(
                (candidate for candidate in payload.get("work_items", []) if item_id(candidate) == source_id),
                None,
            )
            if item is None:
                return None
            runs = item.get("workflow_runs") if isinstance(item.get("workflow_runs"), list) else []
            for run in reversed(runs):
                if not isinstance(run, dict):
                    continue
                team_run = run.get("team_run") if isinstance(run.get("team_run"), dict) else {}
                if required and (team_run.get("template_id") != template_id or run.get("contract_hash") != contract_hash
                                 or run.get("rework_count", 0) != rework_count):
                    raise ValueError("workflow contract changed or legacy run unbound; explicit replan/rework required")
                if team_run.get("template_id") != template_id or team_run.get("status") == "complete":
                    if required:
                        raise ValueError("completed workflow cannot be redispatched; create new scoped work")
                    continue
                artifacts = run.get("artifacts") if isinstance(run.get("artifacts"), dict) else {}
                run_path = artifacts.get("team_run_path")
                if not run_path:
                    if required:
                        raise ValueError("resumable workflow artifact reference is missing")
                    continue
                source = pathlib.Path(str(run_path))
                if not source.exists():
                    if required:
                        raise ValueError("resumable workflow artifact is missing")
                    continue
                loaded = atlas_workflows.load_team_run(source)
                if required and (loaded.work_item_id != source_id or loaded.template_id != template_id):
                    raise ValueError("resumable workflow identity mismatch")
                if loaded.template_id == template_id:
                    return loaded
        except Exception:
            if required:
                raise
            return None
        return None

    @staticmethod
    def goal_acceptance(template: Any, run: Any, context: dict[str, Any], fingerprint: str) -> dict[str, Any]:
        import atlas_workflows
        gates = [role for role in template.roles if role.goal_gate]
        result = run.role_results.get(gates[0].id) if len(gates) == 1 else None
        review = result.goal_review if result is not None else None
        valid = not atlas_workflows.goal_review_issues(review)
        verdict = review["verdict"] if valid else "missing" if review is None else "inconclusive"
        if verdict == "pass" and not atlas_workflows.role_result_satisfies_outputs(gates[0], result):
            verdict = "inconclusive"
        return {"verdict": verdict, "reason": review.get("reason") if isinstance(review, dict) else "goal review not available",
                "evidence": review.get("evidence") if isinstance(review, dict) else [],
                "role_id": gates[0].id if len(gates) == 1 else None,
                "context_hash": content_hash(context), "contract_hash": fingerprint}

    def apply_workflow_role_results(
        self,
        workflow_evidence: dict[str, Any],
        role_results_path: pathlib.Path,
        *, job_dir_fd: int | None = None, job_dir: pathlib.Path | None = None,
        job_parent_fd: int | None = None, job_parent_identity: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        if job_dir_fd is not None:
            if job_dir is None:
                raise ValueError("held job directory path is required for contracted workflow results")
            return self._apply_workflow_role_results_anchored(
                workflow_evidence, role_results_path, job_dir_fd, job_dir,
                job_parent_fd, job_parent_identity,
            )
        if not workflow_evidence.get("team_run_path") or not role_results_path.exists():
            return workflow_evidence
        try:
            import atlas_workflows

            templates = atlas_workflows.load_team_templates(self.templates_dir) if self.templates_dir else []
            registry = self.load_agent_registry()
            template = next(
                (item for item in templates if item.id == workflow_evidence.get("team_template")),
                None,
            )
            if template is None:
                raise ValueError(f"team template {workflow_evidence.get('team_template')} is no longer available")
            team_run = atlas_workflows.load_team_run(workflow_evidence["team_run_path"])
            results = atlas_workflows.load_role_results(role_results_path)
            atlas_workflows.apply_role_results(template=template, run=team_run, results=results)
            atlas_workflows.save_team_run(workflow_evidence["team_run_path"], team_run)
            atlas_workflows.write_team_rollup(workflow_evidence["team_rollup_path"], team_run, template)
            if workflow_evidence.get("team_role_tasks_path"):
                atlas_workflows.write_role_task_packets(
                    workflow_evidence["team_role_tasks_path"],
                    template,
                    team_run,
                    registry=registry,
                    agent_root=self.agent_root,
                    work_item_context=workflow_evidence.get("work_item_context") or {},
                )
            updated = dict(workflow_evidence)
            updated["team_role_results_path"] = str(role_results_path)
            updated["team_run_status"] = team_run.status
            updated["missing_outputs"] = team_run.missing_outputs(template)
            updated["attempted_roles"] = [role.id for role in template.roles if role.id in team_run.role_results]
            updated["completed_roles"] = [
                role.id
                for role in template.roles
                if atlas_workflows.role_result_satisfies_outputs(role, team_run.role_results.get(role.id))
            ]
            updated["team_run"] = atlas_workflows.team_run_summary(template, team_run)
            # Retain the producer's rollup in the result. Contracted result
            # recording deliberately cannot reopen a child-writable pathname.
            updated["team_rollup_markdown"] = team_run.rollup_markdown(template)
            updated["goal_acceptance"] = self.goal_acceptance(template, team_run,
                workflow_evidence.get("work_item_context") or {}, workflow_evidence.get("contract_hash") or "")
            return updated
        except Exception as exc:
            updated = dict(workflow_evidence)
            updated["workflow_result_error"] = str(exc)
            updated["team_role_results_path"] = str(role_results_path)
            return updated

    def _apply_workflow_role_results_anchored(
        self,
        workflow_evidence: dict[str, Any],
        role_results_path: pathlib.Path,
        job_dir_fd: int,
        job_dir: pathlib.Path,
        job_parent_fd: int | None,
        job_parent_identity: tuple[int, int] | None,
    ) -> dict[str, Any]:
        if not workflow_evidence.get("team_run_path"):
            return workflow_evidence
        try:
            if (job_parent_fd is None or job_parent_identity is None
                    or _job_directory_identity(job_dir, job_dir_fd, job_parent_fd, job_parent_identity) is None):
                raise ValueError("contracted job-directory or parent identity changed before aggregate publication")
            role_results_name = _job_child_name(job_dir, role_results_path)
            results_payload = _read_job_json(job_dir_fd, role_results_name, missing_ok=True)
            if results_payload is None:
                return workflow_evidence
            import atlas_workflows

            templates = atlas_workflows.load_team_templates(self.templates_dir) if self.templates_dir else []
            registry = self.load_agent_registry()
            template = next(
                (item for item in templates if item.id == workflow_evidence.get("team_template")),
                None,
            )
            if template is None:
                raise ValueError(f"team template {workflow_evidence.get('team_template')} is no longer available")
            run_name = _job_child_name(job_dir, workflow_evidence["team_run_path"])
            rollup_name = _job_child_name(job_dir, workflow_evidence["team_rollup_path"])
            task_packets_name = (
                _job_child_name(job_dir, workflow_evidence["team_role_tasks_path"])
                if workflow_evidence.get("team_role_tasks_path") else None
            )
            team_run = atlas_workflows.TeamRun.from_dict(_read_job_json(job_dir_fd, run_name))
            results = atlas_workflows.role_results_from_payload(results_payload)
            atlas_workflows.apply_role_results(template=template, run=team_run, results=results)
            _atomic_write_job_file(
                job_dir_fd, run_name,
                (json.dumps(team_run.to_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8"),
            )
            rollup_markdown = team_run.rollup_markdown(template)
            _atomic_write_job_file(job_dir_fd, rollup_name, rollup_markdown.encode("utf-8"))
            if task_packets_name:
                packets = atlas_workflows.role_task_packets(
                    template, team_run, registry=registry, agent_root=self.agent_root,
                    work_item_context=workflow_evidence.get("work_item_context") or {},
                )
                _atomic_write_job_file(
                    job_dir_fd, task_packets_name,
                    (json.dumps({"tasks": packets}, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                )
            if _job_directory_identity(job_dir, job_dir_fd, job_parent_fd, job_parent_identity) is None:
                raise ValueError("contracted job-directory or parent identity changed during aggregate publication")
            updated = dict(workflow_evidence)
            updated["team_role_results_path"] = str(role_results_path)
            updated["team_run_status"] = team_run.status
            updated["missing_outputs"] = team_run.missing_outputs(template)
            updated["attempted_roles"] = [role.id for role in template.roles if role.id in team_run.role_results]
            updated["completed_roles"] = [
                role.id for role in template.roles
                if atlas_workflows.role_result_satisfies_outputs(role, team_run.role_results.get(role.id))
            ]
            updated["team_run"] = atlas_workflows.team_run_summary(template, team_run)
            updated["team_rollup_markdown"] = rollup_markdown
            updated["goal_acceptance"] = self.goal_acceptance(
                template, team_run, workflow_evidence.get("work_item_context") or {},
                str(workflow_evidence.get("contract_hash") or ""),
            )
            return updated
        except Exception as exc:
            return {**workflow_evidence, "workflow_result_error": str(exc),
                    "team_role_results_path": str(role_results_path)}


def run_worker_daemon_once(
    provider: AtlasWorkItemOperationProvider,
    worker: LocalCommandOperationWorker,
    *,
    limit: int = 1,
) -> int:
    processed = 0
    for operation in provider.ready_operations(limit=limit):
        stored_item = next((item for item in provider.store.load().get("work_items", [])
                            if item_id(item) == operation.source_id), None)
        if isinstance(stored_item, dict) and atlas_delta_review.pilot_task_enabled(stored_item):
            raise PilotTaskRequiresSupervisedHandoff(
                f"pilot-enabled work item {operation.source_id} requires supervised in-app handoff"
            )
        claimed = provider.claim(operation)
        if claimed is None:
            continue
        result = worker.run(claimed, provider.store.path)
        provider.record_result(claimed, result)
        processed += 1
        item = next((item for item in provider.store.load().get("work_items", []) if item_id(item) == claimed.source_id), None)
        uncertainty = item.get("process_uncertainty") if isinstance(item, dict) else None
        if isinstance(uncertainty, dict) and uncertainty.get("status") == "unresolved":
            break
        if processed >= limit:
            break
    return processed
