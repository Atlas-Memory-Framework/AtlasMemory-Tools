#!/usr/bin/env python3
"""Read-only, bounded discovery for registered AtlasMemory-Tools runtimes.

This module deliberately does not load shell configuration, execute commands,
query providers, or infer authorization from runtime capabilities.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import stat
import sys
from typing import Any

sys.dont_write_bytecode = True
TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT / "templates" / "local-automation-runtime"))
from atlas_runtime_config import RuntimeConfigError, load_runtime_config, validate_runtime_path  # noqa: E402
import harnesslib  # noqa: E402

SCHEMA_VERSION = "atlas-tools.harness.v1"
MAX_INPUT_BYTES = 262_144
MAX_CODE_BYTES = 1_048_576
MAX_ARTIFACTS = 32
MAX_DIRECTORY_ENTRIES = 512
STALE_AFTER_SECONDS = 900
RUNTIME_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
PROVIDERS = {"github", "azure-devops"}
HARNESSES = {"codex", "claude", "gemini"}
TERMINAL_STATES = {"complete", "completed", "done", "failed", "cancelled", "canceled", "stopped", "timed_out"}
ACTIVE_STATES = {"running", "starting", "active", "queued", "waiting"}
SAFE_STATES = TERMINAL_STATES | ACTIVE_STATES | {"blocked", "idle", "unknown", "interrupted", "partial"}


class HarnessServiceError(ValueError):
    """A safe, actionable domain failure for CLI and MCP clients."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **({"details": self.details} if self.details else {})}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HarnessServiceError("invalid_json", "Duplicate JSON keys are forbidden.")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise HarnessServiceError("invalid_json", "Nonfinite JSON values are forbidden.")


def _absolute_path(raw: Any, *, label: str) -> Path:
    if not isinstance(raw, (str, Path)) or not str(raw):
        raise HarnessServiceError("invalid_path", f"{label} requires an explicit absolute path.")
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts:
        raise HarnessServiceError("invalid_path", f"{label} requires an absolute path without parent traversal.")
    return path


def _owned_path(path: Path, *, directory: bool = False, boundary: Path | None = None) -> Path:
    """Check every component under boundary before opening known non-secret files."""
    try:
        resolved = path.resolve(strict=True)
        if boundary is not None:
            root = boundary.resolve(strict=True)
            if resolved != root and root not in resolved.parents:
                raise HarnessServiceError("unsafe_path", "The path resolves outside its registered boundary.")
            relative = path.relative_to(boundary)
            current = boundary
            for part in relative.parts:
                current = current / part
                info = current.lstat()
                if stat.S_ISLNK(info.st_mode):
                    raise HarnessServiceError("unsafe_path", "Symlinked runtime artifacts and install files are not inspected.")
                if info.st_uid != os.getuid():
                    raise HarnessServiceError("unsafe_path", "The path must be owned by the current identity.")
        info = resolved.stat()
        if info.st_uid != os.getuid():
            raise HarnessServiceError("unsafe_path", "The path must be owned by the current identity.")
        if directory and not stat.S_ISDIR(info.st_mode):
            raise HarnessServiceError("unsafe_path", "Expected an owned directory.")
        if not directory and not stat.S_ISREG(info.st_mode):
            raise HarnessServiceError("unsafe_path", "Expected an owned regular file.")
        return resolved
    except HarnessServiceError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise HarnessServiceError("unavailable_path", "The registered path is unavailable or unsafe.") from exc


def _read_bytes(path: Path, *, boundary: Path | None = None, max_bytes: int = MAX_INPUT_BYTES) -> bytes:
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CODE_BYTES:
        raise HarnessServiceError("invalid_read_limit", "The internal bounded read limit is invalid.")
    resolved = _owned_path(path, boundary=boundary)
    try:
        # O_NOFOLLOW prevents a last-component symlink race. Directory paths were
        # checked above and no discovered path can leave the registered root.
        fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise HarnessServiceError("unsafe_path", "Expected an owned regular file.")
            if info.st_size > max_bytes:
                raise HarnessServiceError("input_too_large", "The input exceeds the bounded read limit.")
            data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise HarnessServiceError("input_too_large", "The input exceeds the bounded read limit.")
            return data
    except HarnessServiceError:
        raise
    except OSError as exc:
        raise HarnessServiceError("unavailable_path", "The registered file could not be read safely.") from exc


def _read_json(path: Path, *, boundary: Path | None = None) -> dict[str, Any]:
    try:
        value = json.loads(_read_bytes(path, boundary=boundary), object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise HarnessServiceError("invalid_json", "The non-secret JSON input is malformed.") from exc
    if not isinstance(value, dict):
        raise HarnessServiceError("invalid_json", "The non-secret JSON input must be an object.")
    return value


def _blocker(code: str, message: str, action: str) -> dict[str, str]:
    return {"code": code, "message": message, "next_action": action}


class HarnessService:
    def __init__(self, registry: Path | None = None, tools_root: Path | None = None):
        home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        self.registry = _absolute_path(registry or home / ".config" / "atlasmemory-tools" / "harness.json", label="Registry")
        self.tools_root = (tools_root or TOOLS_ROOT).resolve()

    def _envelope(self, **payload: Any) -> dict[str, Any]:
        manifest = _read_json(self.tools_root / "manifests" / "atlas-tools.v1.json")
        fingerprint = hashlib.sha256()
        for relative in (
            "manifests/atlas-tools.v1.json", "scripts/harness_service.py", "scripts/harnesslib.py",
            "scripts/runtime_control.py", "scripts/harness_mcp.py", "scripts/harness_execution.py",
            "scripts/harness_runs.py", "scripts/setup_harness_interface.py",
            "scripts/harness_azure.py", "scripts/harness_remotes.py",
        ):
            path = self.tools_root / relative
            if path.is_file():
                fingerprint.update(relative.encode())
                fingerprint.update(_read_bytes(path))
        return {
            "schema_version": SCHEMA_VERSION,
            "tool_version": manifest.get("version", "unknown"),
            "source_fingerprint": "sha256:" + fingerprint.hexdigest(),
            "observed_at": _iso(_now()),
            "read_only": True,
            **payload,
        }

    def _registry(self) -> dict[str, Any]:
        raw = _read_json(self.registry)
        if set(raw) - {"version", "runtimes", "installations"} or type(raw.get("version")) is not int or raw["version"] != 1:
            raise HarnessServiceError("invalid_registry", "Registry requires version 1 and only runtimes/installations fields.")
        runtimes, installations = raw.get("runtimes"), raw.get("installations", [])
        if not isinstance(runtimes, list) or len(runtimes) > 128 or not isinstance(installations, list) or len(installations) > 128:
            raise HarnessServiceError("invalid_registry", "Registry runtimes and installations must be bounded lists.")
        ids: set[str] = set()
        for entry in runtimes:
            if not isinstance(entry, dict) or set(entry) - {"id", "provider", "runtime_dir", "config"}:
                raise HarnessServiceError("invalid_registry", "Runtime entries contain unsupported fields.")
            identifier = entry.get("id")
            if not isinstance(identifier, str) or not RUNTIME_ID.fullmatch(identifier) or identifier in ids:
                raise HarnessServiceError("invalid_registry", "Runtime IDs must be unique safe identifiers.")
            ids.add(identifier)
            if not isinstance(entry.get("provider"), str) or entry["provider"] not in PROVIDERS:
                raise HarnessServiceError("invalid_registry", "Every runtime requires an explicit supported provider.")
            _absolute_path(entry.get("runtime_dir"), label="Runtime")
            if "config" in entry:
                config = _absolute_path(entry["config"], label="Non-secret config")
                if config.suffix.lower() != ".json" or config.name == "config.env":
                    raise HarnessServiceError("invalid_registry", "Only explicit non-secret JSON runtime configuration is supported.")
        for entry in installations:
            if not isinstance(entry, dict) or set(entry) != {"target", "harness"} or not isinstance(entry.get("harness"), str) or entry["harness"] not in HARNESSES:
                raise HarnessServiceError("invalid_registry", "Installation entries require target and supported harness.")
            _absolute_path(entry["target"], label="Installation")
        return raw

    def get_runtime(self, runtime_id: str) -> dict[str, Any]:
        """Return validated metadata; callers still need separate effect authorization."""
        if not isinstance(runtime_id, str) or not RUNTIME_ID.fullmatch(runtime_id):
            raise HarnessServiceError("invalid_runtime_id", "Use an explicit registered runtime ID.")
        entry = next((entry for entry in self._registry()["runtimes"] if entry["id"] == runtime_id), None)
        if entry is None:
            raise HarnessServiceError("unknown_runtime", "The runtime ID is not registered; call discover first.")
        try:
            supplied = Path(entry["runtime_dir"])
            identity_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
            if supplied == identity_home or identity_home in supplied.parents:
                supplied = identity_home.resolve(strict=True) / supplied.relative_to(identity_home)
            root = validate_runtime_path(supplied)
        except RuntimeConfigError as exc:
            raise HarnessServiceError("invalid_runtime", "Runtime must be an existing owned directory inside the current identity home.") from exc
        template = self.tools_root / "templates" / "local-automation-runtime"
        if root == template or template in root.parents:
            raise HarnessServiceError("source_template", "Register an installed runtime, never the canonical source template.")
        result = {**entry, "runtime_dir": str(root)}
        if entry.get("config"):
            config_path = _absolute_path(entry["config"], label="Non-secret config")
            _read_json(config_path)
            try:
                config = load_runtime_config(config_path, runtime_dir=root)
            except RuntimeConfigError as exc:
                raise HarnessServiceError("invalid_config", "The runtime's explicit non-secret configuration failed provider or capability validation.") from exc
            if config.provider != entry["provider"]:
                raise HarnessServiceError("provider_mismatch", "Registry and runtime configuration providers disagree.")
            result["configuration"] = config.report()
        elif entry["provider"] == "azure-devops":
            raise HarnessServiceError("missing_config", "Azure runtimes require an explicit non-secret JSON provider configuration.")
        return result

    def discover(self) -> dict[str, Any]:
        try:
            registry = self._registry()
        except HarnessServiceError as exc:
            return self._envelope(
                registry=str(self.registry), runtimes=[], installations=[],
                blockers=[_blocker(exc.code, exc.message, "Create or repair the explicit registry, then call discover again.")],
                next_actions=[{"operation": "configure_registry", "registry": str(self.registry)}],
            )
        runtimes = []
        for entry in registry["runtimes"]:
            summary: dict[str, Any] = {"id": entry["id"], "provider": entry["provider"], "runtime_dir": entry["runtime_dir"]}
            try:
                resolved = self.get_runtime(entry["id"])
                summary.update(available=True, capabilities=resolved.get("configuration", {}).get("capabilities", ["read"]), blockers=[])
                if entry["provider"] == "azure-devops":
                    from harness_azure import AZURE_OPERATIONS

                    summary["supported_operations"] = list(AZURE_OPERATIONS)
                    summary["remote"] = resolved["configuration"]["repository"]
                else:
                    summary["supported_operations"] = ["github-cycle"]
            except HarnessServiceError as exc:
                summary.update(available=False, capabilities=[], blockers=[_blocker(exc.code, exc.message, "Repair this registration or runtime configuration.")])
            recent = self._interface_runs(entry["id"])
            if recent["runs"] or recent["blockers"]:
                summary["interface_runs"] = recent
            runtimes.append(summary)
        installations = []
        for entry in registry.get("installations", []):
            try:
                report = self.installation_status(entry["target"], entry["harness"])
                installations.append({key: report[key] for key in ("target", "harness", "status", "counts", "next_actions")})
            except HarnessServiceError as exc:
                installations.append({**entry, "status": "blocked", "error": exc.as_dict()})
        return self._envelope(
            registry=str(self.registry), runtimes=runtimes, installations=installations, blockers=[],
            next_actions=[{"operation": "inspect", "runtime_id": entry["id"]} for entry in runtimes if entry["available"]],
            authority="Capabilities describe configuration; they do not authorize execution or provider writes.",
        )

    def _runtime_artifacts(self, root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        artifacts: list[dict[str, Any]] = []
        blockers: list[dict[str, str]] = []
        jobs = root / "jobs"
        if not jobs.exists():
            return artifacts, blockers
        try:
            _owned_path(jobs, directory=True, boundary=root)
            entries = []
            scanned = 0
            with os.scandir(jobs) as iterator:
                for entry in iterator:
                    scanned += 1
                    if scanned > MAX_DIRECTORY_ENTRIES:
                        blockers.append(_blocker("inspection_truncated", "Runtime jobs inventory exceeds the bounded inspection limit.", "Inspect the runtime's own detailed status before dispatch."))
                        break
                    name = entry.name
                    if name == "atlas-agent-shift-heartbeat.json" or re.fullmatch(r"shift-[A-Za-z0-9_.-]+-status\.json", name):
                        entries.append(jobs / name)
            for path in sorted(entries, key=lambda item: item.name, reverse=True)[:MAX_ARTIFACTS]:
                try:
                    data = _read_json(path, boundary=root)
                    state = data.get("state", data.get("status", "unknown"))
                    state = state if isinstance(state, str) and state in SAFE_STATES else "unknown"
                    updated = data.get("updated_at", data.get("finished_at", data.get("started_at")))
                    age = None
                    if isinstance(updated, str):
                        try:
                            parsed = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                            if parsed.tzinfo is not None:
                                age = (_now() - parsed.astimezone(timezone.utc)).total_seconds()
                        except ValueError:
                            pass
                    fresh = age is not None and -60 <= age <= STALE_AFTER_SECONDS
                    identifier = data.get("shift_id")
                    if not isinstance(identifier, str) or not RUNTIME_ID.fullmatch(identifier):
                        identifier = None
                    summary: dict[str, Any] = {
                        "path": str(path), "kind": "heartbeat" if "heartbeat" in path.name else "shift_status",
                        "state": state, "updated_at": updated if age is not None else None,
                        "fresh": fresh, "age_seconds": round(age, 1) if age is not None else None,
                        "shift_id": identifier,
                    }
                    if identifier:
                        handoff = jobs / f"shift-{identifier}-handoff.md"
                        if handoff.exists() or handoff.is_symlink():
                            try:
                                _owned_path(handoff, boundary=root)
                                summary["handoff_path"] = str(handoff)
                            except HarnessServiceError:
                                blockers.append(_blocker("unsafe_handoff", "The shift handoff path is unavailable or unsafe.", "Inspect the handoff ownership and path locally."))
                    for key in ("cycles_completed", "cycle_limit", "last_returncode"):
                        if type(data.get(key)) is int:
                            summary[key] = data[key]
                    # Never echo commands, free-text logs, handoff bodies, env, or
                    # arbitrary fields from runtime artifacts.
                    artifacts.append(summary)
                except HarnessServiceError as exc:
                    blockers.append(_blocker(exc.code, exc.message, "Repair or inspect this runtime status artifact locally."))
            if len(entries) > MAX_ARTIFACTS:
                blockers.append(_blocker("inspection_truncated", "Only the bounded recent status subset was inspected.", "Inspect the runtime's own detailed status before dispatch."))
        except HarnessServiceError as exc:
            blockers.append(_blocker(exc.code, exc.message, "Repair runtime jobs ownership or path boundaries."))
        return artifacts, blockers

    def _current_observations(self, artifacts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Project latest state per known shift while retaining every evidence row.

        An observation without an identity cannot supersede another file, and
        an undated or future-dated terminal row cannot establish chronology.
        """
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in artifacts:
            key = ("shift", item["shift_id"]) if item["shift_id"] else ("path", item["path"])
            groups.setdefault(key, []).append(item)
        current: list[dict[str, Any]] = []
        blockers: list[dict[str, str]] = []
        for group in groups.values():
            dated = [item for item in group if item["updated_at"] is not None and item["age_seconds"] >= -60 and item["state"] in ACTIVE_STATES | TERMINAL_STATES]
            undated_active = [item for item in group if item["state"] in ACTIVE_STATES and item not in dated]
            current.extend(undated_active)
            if not dated:
                continue
            timestamps = {item["path"]: datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00")) for item in dated}
            latest_time = max(timestamps.values())
            latest = [item for item in dated if timestamps[item["path"]] == latest_time]
            aliases = {"complete": "completed", "done": "completed", "canceled": "cancelled"}
            states = {aliases.get(item["state"], item["state"]) for item in latest}
            if len(states) > 1:
                blockers.append(_blocker("contradictory_runtime_evidence", "Equal-time observations for the same shift disagree about its state.", "Reconcile the conflicting runtime records before starting another run."))
                current.extend(item for item in latest if item["state"] in ACTIVE_STATES)
            elif latest[0]["state"] in ACTIVE_STATES:
                # Prefer a status record for its richer counters when a matching
                # heartbeat records the same state at the same instant.
                current.append(next((item for item in latest if item["kind"] == "shift_status"), latest[0]))
        current = list({item["path"]: item for item in current}.values())
        for item in current:
            if not item["fresh"]:
                blockers.append(_blocker("stale_active_evidence", "An active runtime record has stale or missing heartbeat evidence.", "Reconcile the runtime record before starting another run."))
        return current, blockers

    def _runtime_diagnostic(self, runtime_id: str, root: Path, artifacts: list[dict[str, Any]], blockers: list[dict[str, str]]) -> dict[str, Any]:
        """Name the next missing observation without inspecting host processes."""
        lock = root / "jobs" / "atlas-agent-shift.lock"
        lock_observation: dict[str, Any] = {"path": str(lock), "present": False, "process_liveness": "not_observed"}
        if lock.exists() or lock.is_symlink():
            try:
                data = _read_json(lock, boundary=root)
                lock_observation["present"] = True
                if type(data.get("pid")) is int and 0 < data["pid"] <= 2**31 - 1:
                    lock_observation["pid"] = data["pid"]
                created = data.get("created_at")
                if isinstance(created, str) and re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", created):
                    lock_observation["created_at"] = created
            except HarnessServiceError as exc:
                lock_observation.update(present=True, error=exc.as_dict())
        paths = sorted({item["path"] for item in artifacts} | {item["handoff_path"] for item in artifacts if item.get("handoff_path")})
        codes = sorted({item["code"] for item in blockers})
        return {
            "operation": "review_runtime_evidence", "runtime_id": runtime_id,
            "read_only": True, "requires_authorization": False,
            "reason": "Existing observations cannot resolve runtime liveness or full status coverage; repeating inspect without new evidence will not resolve this blocker.",
            "blocker_codes": codes, "evidence_paths": paths,
            "expected_artifact_paths": [str(root / "jobs" / "atlas-agent-shift-heartbeat.json"), str(lock)],
            "lock_observation": lock_observation,
            "coverage": {
                "inventory_directory": str(root / "jobs"), "limited": "inspection_truncated" in codes,
                "max_directory_entries": MAX_DIRECTORY_ENTRIES, "max_status_artifacts": MAX_ARTIFACTS,
                "limitation": "Only known heartbeat/status artifacts within the bounded jobs inventory were inspected; newer or omitted records may exist.",
            },
            "expected_new_evidence": [
                "A newer heartbeat or terminal status for the same shift identity, or a bounded review of conflicting equal-time records.",
                "If the owned shift lock names a PID, verify only that process's identity and start time against the lock; a status saying running does not prove a process is alive.",
                "If coverage is truncated, obtain a bounded inventory of relevant shift-status filenames in this runtime jobs directory; omit logs, credentials, environment files, and unrelated host processes.",
            ],
            "resume_when": "Call inspect again after new status, identity, or coverage evidence is available. Preserve stale files until an authorized reconciliation is chosen.",
        }

    def _interface_runs(self, runtime_id: str) -> dict[str, Any]:
        """Recover private run IDs without creating state or requiring valid provider config."""
        state = self.registry.parent / "runs"
        if not state.exists() and not state.is_symlink():
            return {"runs": [], "truncated": False, "blockers": []}
        try:
            from harness_runs import HarnessRuns

            recent = HarnessRuns(self).recent(runtime_id)
            return {key: recent[key] for key in ("runs", "truncated", "blockers")}
        except (HarnessServiceError, OSError):
            return {"runs": [], "truncated": False, "blockers": [
                _blocker("unavailable_interface_runs", "Private interface run records are unsafe or unavailable.", "Preserve the private run state and review its owned paths before starting work."),
            ]}

    def inspect(self, runtime_id: str) -> dict[str, Any]:
        runtime = self.get_runtime(runtime_id)
        root = Path(runtime["runtime_dir"])
        artifacts, blockers = self._runtime_artifacts(root)
        configuration = runtime.get("configuration", {})
        capabilities = configuration.get("capabilities", ["read"])
        current, observation_blockers = self._current_observations(artifacts)
        blockers.extend(observation_blockers)
        if not artifacts:
            blockers.append(_blocker("no_runtime_evidence", "No supported runtime status or heartbeat evidence was found.", "Use an explicit provider inspection or prepare a bounded run; do not infer idle or completed work."))
        if any(item["fresh"] for item in current):
            blockers.append(_blocker("active_run", "Fresh runtime evidence reports an active shift.", "Observe the existing shift before starting overlapping work."))
        next_actions = [{"operation": "inspect", "runtime_id": runtime_id, "reason": "Observe or reconcile existing runtime evidence."}]
        diagnostic_codes = {"stale_active_evidence", "inspection_truncated", "contradictory_runtime_evidence"}
        if any(blocker["code"] in diagnostic_codes for blocker in blockers):
            next_actions = [self._runtime_diagnostic(runtime_id, root, artifacts, blockers)]
        elif not current:
            next_actions = [{"operation": "prepare", "runtime_id": runtime_id, "reason": "Prepare a bounded proposal; execution requires separate authorization."}]
        interface_runs = self._interface_runs(runtime_id)
        blockers.extend(interface_runs["blockers"])
        pending = [run for run in interface_runs["runs"] if run["status"] in {"starting", "running", "unknown"}]
        if pending:
            blockers.append(_blocker("interface_run_active", "An interface run is active or unreconciled.", "Observe the durable run before starting overlapping work."))
            next_actions = [
                {"operation": "wait", "run_id": run["run_id"], "cursor": run["cursor"]}
                if run["status"] != "unknown" else {"operation": "reconcile_run", "run_id": run["run_id"]}
                for run in pending
            ] + [action for action in next_actions if action["operation"] != "prepare"]
        return self._envelope(
            runtime={key: runtime[key] for key in ("id", "provider", "runtime_dir")},
            capabilities=capabilities, models=configuration.get("models", {}),
            current_work=current, evidence=artifacts, blockers=blockers, next_actions=next_actions,
            interface_runs=interface_runs,
            coverage={"provider_live_read": False, "config_env_read": False, "supported_artifact_count": len(artifacts), "stale_after_seconds": STALE_AFTER_SECONDS},
            validation={"status": "unverified", "message": "Local status records do not establish accepted task completion or current provider state."},
            authority="Read-only observation. No execution, provider mutation, or authorization was performed.",
        )

    def installation_status(self, target: str, harness: str = "codex") -> dict[str, Any]:
        if harness not in HARNESSES:
            raise HarnessServiceError("unsupported_harness", "Choose codex, claude, or gemini.")
        target_path = _absolute_path(target, label="Installation")
        target_path = _owned_path(target_path, directory=True)
        manifest = _read_json(self.tools_root / "manifests" / "atlas-tools.v1.json")
        adapter = manifest.get("adapters", {}).get(harness)
        if not adapter:
            raise HarnessServiceError("unsupported_harness", "The canonical manifest does not register this harness adapter.")
        planned: list[tuple[Path, Path]] = []
        for entry in manifest.get("skills", []):
            source_dir = self.tools_root / entry["path"]
            for source in sorted(source_dir.rglob("*")):
                if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
                    planned.append((source, target_path / adapter["skills_path"] / entry["name"] / source.relative_to(source_dir)))
        for entry in manifest.get("agents", []):
            source = self.tools_root / entry["path"]
            planned.append((source, target_path / adapter["agents_path"] / source.name))
        counts = {"current": 0, "missing": 0, "stale": 0, "modified": 0, "unsafe": 0}
        differences = []
        for source, destination in planned:
            relative = source.relative_to(self.tools_root).as_posix()
            state = "current"
            if not destination.exists() and not destination.is_symlink():
                state = "missing"
            else:
                try:
                    content = _read_bytes(destination, boundary=target_path)
                    source_bytes = _read_bytes(source, boundary=self.tools_root)
                    if source.suffix == ".json":
                        state = "current" if content == source_bytes else "modified"
                    else:
                        metadata, body = harnesslib.strip_generated_header(content)
                        checksum = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
                        if not metadata or metadata.get("source") != relative:
                            state = "modified"
                        elif metadata.get("checksum") != checksum:
                            # A body matching the recorded previous checksum is
                            # a clean older generated copy, not a local edit.
                            prior_checksum = "sha256:" + hashlib.sha256(body).hexdigest()
                            state = "stale" if prior_checksum == metadata.get("checksum") else "modified"
                        elif body != source_bytes:
                            state = "modified"
                except HarnessServiceError:
                    state = "unsafe"
            counts[state] += 1
            if state != "current" and len(differences) < 50:
                differences.append({"path": str(destination), "source": relative, "status": state})
        status = "current" if not any(counts[key] for key in ("missing", "stale", "modified", "unsafe")) else "drifted"
        next_actions: list[dict[str, Any]] = []
        if status != "current":
            if counts["modified"] and not any(counts[key] for key in ("missing", "stale", "unsafe")):
                next_actions.append({
                    "operation": "retain_local_overrides", "read_only": True, "requires_authorization": False,
                    "message": "Only locally modified copies remain. Preserve these overrides; do not rerun setup solely to remove this difference. Their intent has not been inferred from content.",
                })
            elif counts["unsafe"] or (harness != "codex" and counts["modified"]):
                next_actions.append({
                    "operation": "resolve_installation_conflicts", "requires_authorization": False,
                    "message": "Resolve unsafe paths and preserve locally modified files before updating. No overwrite command is recommended while these conflicts remain.",
                })
            elif harness == "codex":
                command = [sys.executable, str(self.tools_root / "scripts" / "setup_harness_interface.py"), "--home", str(target_path)]
                if counts["modified"]:
                    command.append("--preserve-local")
                next_actions.append({
                    "operation": "preview_installation_update", "argv": command, "command": shlex.join(command),
                    "read_only": True, "requires_authorization": False, "apply_requires_authorization": True,
                    "message": "Preview the safe setup changes. Locally modified files are preserved; unsafe paths or configuration conflicts block setup. Apply only after reviewing the preview.",
                })
            else:
                command = [sys.executable, str(self.tools_root / "scripts" / "install_harness.py"), "--harness", harness, "--target", str(target_path), "--check"]
                next_actions.append({
                    "operation": "preview_installation_update", "argv": command, "command": shlex.join(command),
                    "read_only": True, "requires_authorization": False, "apply_requires_authorization": True,
                    "message": "Preview missing or clean older managed copies. Preserve local changes and resolve unsafe paths before any explicit update.",
                })
        return self._envelope(
            target=str(target_path), harness=harness, status=status, counts=counts,
            actionable_update_count=counts["missing"] + counts["stale"], local_override_count=counts["modified"],
            differences=differences, differences_truncated=sum(counts[key] for key in ("missing", "stale", "modified", "unsafe")) > len(differences),
            next_actions=next_actions,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover")
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("runtime_id")
    installation = sub.add_parser("installation-status")
    installation.add_argument("--target", required=True)
    installation.add_argument("--harness", default="codex", choices=sorted(HARNESSES))
    for command in ("prepare", "start"):
        operation_parser = sub.add_parser(command)
        operation_parser.add_argument("runtime_id")
        operation_parser.add_argument("--operation", help="Named GitHub or Azure operation; defaults to the registered provider's read entry.")
        operation_parser.add_argument("--options-file", type=Path, help="Non-secret JSON options for the named operation, validated before execution.")
        operation_parser.add_argument("--max-minutes", type=int)
        operation_parser.add_argument("--cycles", type=int)
        operation_parser.add_argument("--max-per-repo", type=int)
        for option in ("publish", "apply", "review-apply"):
            operation_parser.add_argument("--" + option, action=argparse.BooleanOptionalAction, default=None)
        if command == "start":
            operation_parser.add_argument("--proposal-id", required=True)
            operation_parser.add_argument("--authorization-ref", required=True)
    wait_parser = sub.add_parser("wait")
    wait_parser.add_argument("run_id")
    wait_parser.add_argument("--cursor", type=int)
    wait_parser.add_argument("--timeout-seconds", type=int, default=0)
    cancel_parser = sub.add_parser("cancel")
    cancel_parser.add_argument("run_id")
    repositories_parser = sub.add_parser("remote-repositories")
    repositories_parser.add_argument("project_url")
    remote_parser = sub.add_parser("configure-remote")
    remote_parser.add_argument("--remote-id", required=True)
    remote_parser.add_argument("--provider", required=True, choices=["azure-devops"])
    remote_parser.add_argument("--repository-url", required=True)
    remote_parser.add_argument("--repository-name")
    remote_parser.add_argument("--base-branch")
    remote_parser.add_argument("--runtime-dir")
    remote_parser.add_argument("--checkout")
    remote_parser.add_argument("--expected-profile-sha256")
    remote_parser.add_argument("--models-file", type=Path)
    remote_parser.add_argument("--capability", action="append", dest="capabilities")
    remote_parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    service = HarnessService(registry=args.registry)
    try:
        if args.command == "discover":
            result = service.discover()
        elif args.command == "inspect":
            result = service.inspect(args.runtime_id)
        elif args.command == "installation-status":
            result = service.installation_status(args.target, args.harness)
        elif args.command in {"prepare", "start"}:
            options = _read_json(args.options_file) if args.options_file else {}
            flag_options = {
                name: getattr(args, name) for name in
                ("max_minutes", "cycles", "max_per_repo", "publish", "apply", "review_apply")
                if getattr(args, name) is not None
            }
            if set(options).intersection(flag_options):
                raise HarnessServiceError("conflicting_options", "Specify an option once, in the JSON file or as a command-line flag.")
            options.update(flag_options)
            if args.command == "prepare":
                from harness_execution import HarnessExecution

                result = HarnessExecution(service).prepare(args.runtime_id, operation=args.operation, options=options)
            else:
                from harness_runs import HarnessRuns

                result = HarnessRuns(service).start(args.runtime_id, args.proposal_id, options, args.authorization_ref, operation=args.operation)
        elif args.command in {"remote-repositories", "configure-remote"}:
            from harness_remotes import HarnessRemotes

            remotes = HarnessRemotes(service)
            if args.command == "remote-repositories":
                result = remotes.repositories(args.project_url)
            else:
                result = remotes.configure(
                    remote_id=args.remote_id, provider=args.provider, repository_url=args.repository_url,
                    repository_name=args.repository_name, base_branch=args.base_branch, runtime_dir=args.runtime_dir,
                    models=_read_json(args.models_file) if args.models_file else None,
                    capabilities=args.capabilities, apply=args.apply, checkout=args.checkout,
                    expected_profile_sha256=args.expected_profile_sha256,
                )
        else:
            from harness_runs import HarnessRuns

            runs = HarnessRuns(service)
            result = runs.wait(args.run_id, args.cursor, args.timeout_seconds) if args.command == "wait" else runs.cancel(args.run_id)
        print(json.dumps(result, indent=2))
        return 2 if result.get("status") in {"error", "blocked"} else 0
    except HarnessServiceError as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "read_only": args.command not in {"start", "cancel", "configure-remote"}, "error": exc.as_dict()}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
