#!/usr/bin/env python3
"""Local Atlas work-item provider for the automation runtime."""

from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


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
    return bool(set(left) & set(right))


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


def workflow_run_record(result: "OperationResult") -> dict[str, Any] | None:
    evidence = result.evidence if isinstance(result.evidence, dict) else {}
    team_run = evidence.get("team_run")
    if not isinstance(team_run, dict):
        return None
    record: dict[str, Any] = {
        "recorded_at": now_rfc3339(),
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
    if rollup_path:
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
        if not self.path.exists():
            return
        age = time.time() - self.path.stat().st_mtime
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
        )

    def blockers(self, item: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[str]:
        state = item_state(item)
        if state in ACTIVE_STATES:
            return ["already claimed"]
        if state in TERMINAL_STATES:
            return [f"terminal state: {state}"]
        if state not in READY_STATES:
            return [f"not ready: {state or 'missing state'}"]
        scheduler = item.get("scheduler") if isinstance(item.get("scheduler"), dict) else {}
        blockers = [f"blocker: {value}" for value in list_value(scheduler.get("blockers") or item.get("blockers"))]
        for dependency in list_value(scheduler.get("depends_on") or item.get("depends_on")):
            dependency_item = by_id.get(dependency)
            if dependency_item is None:
                blockers.append(f"missing dependency: {dependency}")
            elif item_state(dependency_item) != "done":
                blockers.append(f"open dependency: {dependency}")
        source_id = item_id(item)
        for active_id, active_item in by_id.items():
            if active_id == source_id or item_state(active_item) not in ACTIVE_STATES:
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
        status = result.status if result.status in {"done", "failed", "ready", "queued"} else "failed"

        def apply_result(item: dict[str, Any]) -> dict[str, Any]:
            item["status"] = status
            item["state"] = status
            lifecycle = item.setdefault("lifecycle", {})
            if isinstance(lifecycle, dict):
                lifecycle["state"] = status
                lifecycle["last_result_at"] = now_rfc3339()
                if status in TERMINAL_STATES:
                    lifecycle["completed_at"] = lifecycle["last_result_at"]
                elif status in READY_STATES:
                    lifecycle["requeued_at"] = lifecycle["last_result_at"]
                    lifecycle["requeue_reason"] = "workflow incomplete"
            if status in READY_STATES:
                previous_claim = item.pop("claim", None)
                if previous_claim:
                    item.setdefault("previous_claims", []).append(previous_claim)
            item["result"] = result.to_dict()
            workflow_record = workflow_run_record(result)
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
                event("result", status=status, operation_id=operation.operation_id, evidence=result.to_dict())
            )
            return item

        self.store.update_item(operation.source_id, apply_result)


class LocalCommandOperationWorker:
    def __init__(
        self,
        command: list[str] | None,
        *,
        jobs_dir: str | pathlib.Path,
        templates_dir: str | pathlib.Path | None = None,
        agent_registry_path: str | pathlib.Path | None = None,
        agent_root: str | pathlib.Path | None = None,
    ):
        self.command = command
        self.jobs_dir = pathlib.Path(jobs_dir)
        self.templates_dir = pathlib.Path(templates_dir) if templates_dir else None
        self.agent_registry_path = pathlib.Path(agent_registry_path) if agent_registry_path else None
        self.agent_root = pathlib.Path(agent_root) if agent_root else None

    def load_agent_registry(self) -> Any:
        if self.agent_registry_path is None or not self.agent_registry_path.exists():
            return None
        import atlas_workflows

        return atlas_workflows.load_agent_registry(self.agent_registry_path)

    def run(self, operation: OperationState, store_path: pathlib.Path) -> OperationResult:
        job_id = now_rfc3339().replace(":", "").replace(".", "")
        job_dir = self.jobs_dir / f"atlas-work-item-{safe_id(operation.source_id)}-{job_id}"
        job_dir.mkdir(parents=True, exist_ok=True)
        operation_path = job_dir / "operation.json"
        operation_path.write_text(json.dumps(operation.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        workflow_evidence = self.write_workflow_artifacts(operation, job_dir, job_id, store_path)
        role_results_path = job_dir / "team-role-results.json"
        if not self.command:
            return OperationResult(
                status="done",
                returncode=0,
                summary="No local work-item command configured; claim recorded.",
                evidence={
                    "job_dir": str(job_dir),
                    "operation_path": str(operation_path),
                    "mode": "claim-only",
                    **workflow_evidence,
                },
            )

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
        proc = subprocess.run(
            self.command,
            cwd=str(job_dir),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        output_path = job_dir / "worker-output.txt"
        output_path.write_text(proc.stdout or "", encoding="utf-8")
        workflow_evidence = self.apply_workflow_role_results(workflow_evidence, role_results_path)
        status = "done" if proc.returncode == 0 else "failed"
        if workflow_evidence.get("team_run_status") == "running":
            if workflow_evidence.get("completed_roles"):
                status = "ready"
                workflow_evidence["workflow_continuation"] = {
                    "reason": "required workflow outputs remain incomplete",
                    "next_status": "ready",
                }
            else:
                status = "failed"
                workflow_evidence["workflow_incomplete"] = {
                    "reason": "required workflow outputs remain incomplete and no role completed",
                    "next_status": "failed",
                }
        return OperationResult(
            status=status,
            returncode=proc.returncode,
            summary=(proc.stdout or "").strip().splitlines()[-1] if (proc.stdout or "").strip() else "worker exited",
            evidence={
                "job_dir": str(job_dir),
                "operation_path": str(operation_path),
                "output_path": str(output_path),
                "duration_ms": duration_ms,
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
        previous_run = self.load_resumable_team_run(store_path, operation.source_id, template.id)
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
        )
        return {
            "team_template": template.id,
            "workflow_kind": template.workflow_kind,
            "workflow_resumed": previous_run is not None,
            "team_roles": [role.id for role in template.roles],
            "missing_outputs": missing_outputs,
            "team_run_path": str(run_path),
            "team_rollup_path": str(rollup_path),
            "team_role_tasks_path": str(role_tasks_path),
            "team_run_status": team_run.status,
            "team_run": atlas_workflows.team_run_summary(template, team_run),
            "workflow_selection": atlas_workflows.compact_template_selection_report(selection_report),
            "agent_registry_path": str(self.agent_registry_path) if self.agent_registry_path else "",
            "agent_root": str(self.agent_root) if self.agent_root else "",
        }

    def load_resumable_team_run(
        self,
        store_path: pathlib.Path,
        source_id: str,
        template_id: str,
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
                if team_run.get("template_id") != template_id or team_run.get("status") == "complete":
                    continue
                artifacts = run.get("artifacts") if isinstance(run.get("artifacts"), dict) else {}
                run_path = artifacts.get("team_run_path")
                if not run_path:
                    continue
                source = pathlib.Path(str(run_path))
                if not source.exists():
                    continue
                loaded = atlas_workflows.load_team_run(source)
                if loaded.template_id == template_id:
                    return loaded
        except Exception:
            return None
        return None

    def apply_workflow_role_results(
        self,
        workflow_evidence: dict[str, Any],
        role_results_path: pathlib.Path,
    ) -> dict[str, Any]:
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
                )
            updated = dict(workflow_evidence)
            updated["team_role_results_path"] = str(role_results_path)
            updated["team_run_status"] = team_run.status
            updated["missing_outputs"] = team_run.missing_outputs(template)
            updated["attempted_roles"] = [role.id for role in template.roles if role.id in team_run.role_results]
            updated["completed_roles"] = [
                role.id
                for role in template.roles
                if role.id in team_run.role_results and team_run.role_results[role.id].status == "complete"
            ]
            updated["team_run"] = atlas_workflows.team_run_summary(template, team_run)
            return updated
        except Exception as exc:
            updated = dict(workflow_evidence)
            updated["workflow_result_error"] = str(exc)
            updated["team_role_results_path"] = str(role_results_path)
            return updated


def run_worker_daemon_once(
    provider: AtlasWorkItemOperationProvider,
    worker: LocalCommandOperationWorker,
    *,
    limit: int = 1,
) -> int:
    processed = 0
    for operation in provider.ready_operations(limit=limit):
        claimed = provider.claim(operation)
        if claimed is None:
            continue
        result = worker.run(claimed, provider.store.path)
        provider.record_result(claimed, result)
        processed += 1
        if processed >= limit:
            break
    return processed
