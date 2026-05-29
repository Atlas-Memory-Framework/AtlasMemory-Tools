#!/usr/bin/env python3
"""Shared helpers for the local automation runtime."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from typing import Any


RUNTIME_DIR = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = RUNTIME_DIR / "config.env"
NONE_FIELD_VALUES = {"", "none", "n/a", "na", "-"}
CODEX_AUTH_INDICATOR_NAMES = ("auth.json", "credentials.json", "session.json")
POINT_FIELD_RE = re.compile(
    r"(?im)^\s*(?:-\s*)?(?:suggested\s+points|story\s+points|points):\s*`?(\d+)`?\s*$"
)


def now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def duration_ms(start_time: float, end_time: float | None = None) -> int:
    finish = time.monotonic() if end_time is None else end_time
    return max(0, int(round((finish - start_time) * 1000)))


def config_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name) or read_config().get(name)
    if raw is None:
        return default
    return str(raw).strip().strip('"').strip("'").lower() not in {"0", "false", "no", "off"}


def config_value(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        raw = read_config().get(name)
    if raw is None:
        return default
    return str(raw).strip().strip('"').strip("'")


def config_float(name: str, default: float) -> float:
    raw = os.environ.get(name) or read_config().get(name)
    if raw is None:
        return default
    try:
        return float(str(raw).strip().strip('"').strip("'"))
    except ValueError:
        return default


def config_int(name: str, default: int) -> int:
    raw = os.environ.get(name) or read_config().get(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip().strip('"').strip("'"))
    except ValueError:
        return default


def gh_command_parts(args: list[str]) -> list[str] | None:
    if not args or args[0] != "gh":
        return None
    return args[1:]


def gh_shell_command_parts(command: str) -> list[str] | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts or parts[0] != "gh":
        return None
    return parts[1:]


def gh_command_is_mutating(parts: list[str]) -> bool:
    if not parts:
        return False
    if parts[0] == "api":
        if "graphql" in parts and any("mutation" in part.lower() for part in parts):
            return True
        for index, part in enumerate(parts):
            if part in {"-X", "--method"} and index + 1 < len(parts):
                return parts[index + 1].upper() in {"POST", "PATCH", "PUT", "DELETE"}
        return False
    mutating_prefixes = (
        ("issue", "edit"),
        ("issue", "comment"),
        ("issue", "close"),
        ("issue", "reopen"),
        ("label", "create"),
        ("pr", "comment"),
        ("pr", "create"),
        ("pr", "merge"),
        ("pr", "ready"),
        ("project", "item-add"),
        ("workflow", "run"),
        ("run", "rerun"),
    )
    return any(tuple(parts[: len(prefix)]) == prefix for prefix in mutating_prefixes)


def gh_command_is_graphql_heavy(parts: list[str]) -> bool:
    if not parts:
        return False
    if parts[0] == "project":
        return True
    if parts[:2] == ["api", "graphql"]:
        return True
    return "--json" in parts and parts[0] in {"issue", "pr", "repo", "run"}


def gh_command_is_project(parts: list[str]) -> bool:
    return bool(parts and parts[0] == "project")


def gh_command_interval(parts: list[str]) -> float:
    if not config_bool("AGENT_GITHUB_THROTTLE", True):
        return 0.0
    if gh_command_is_project(parts):
        return config_float("AGENT_GITHUB_PROJECT_INTERVAL_SECONDS", 5.0)
    if gh_command_is_mutating(parts):
        return config_float("AGENT_GITHUB_MUTATION_INTERVAL_SECONDS", 2.0)
    if gh_command_is_graphql_heavy(parts):
        return config_float("AGENT_GITHUB_GRAPHQL_INTERVAL_SECONDS", 2.0)
    return config_float("AGENT_GITHUB_MIN_INTERVAL_SECONDS", 0.75)


def github_throttle_paths() -> tuple[pathlib.Path, pathlib.Path]:
    root = jobs_dir() / "github-api-throttle"
    return root / "state.json", root / "state.lock"


def pid_is_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def json_lock_is_stale(path: pathlib.Path, stale_seconds: float) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    if age > stale_seconds:
        return True
    payload = read_json_file(path)
    pid = payload.get("pid")
    return pid is not None and not pid_is_alive(pid)


def github_throttle_status(stale_seconds: float = 120.0) -> dict[str, Any]:
    state_path, lock_path = github_throttle_paths()
    state = read_json_file(state_path)
    now = time.time()
    lock_state: dict[str, Any] = {
        "path": str(lock_path),
        "exists": lock_path.exists(),
        "stale": False,
        "age_seconds": None,
    }
    if lock_path.exists():
        age = max(0.0, now - lock_path.stat().st_mtime)
        payload = read_json_file(lock_path)
        lock_state.update(
            {
                "age_seconds": age,
                "stale": age > stale_seconds
                or (payload.get("pid") is not None and not pid_is_alive(payload.get("pid"))),
                "payload": payload,
            }
        )
    pause_until = float(state.get("pause_until") or 0)
    next_allowed_at = float(state.get("next_allowed_at") or 0)
    return {
        "state_path": str(state_path),
        "exists": state_path.exists(),
        "pause_until": pause_until or None,
        "pause_remaining_seconds": max(0.0, pause_until - now) if pause_until else 0.0,
        "next_allowed_at": next_allowed_at or None,
        "next_allowed_remaining_seconds": max(0.0, next_allowed_at - now) if next_allowed_at else 0.0,
        "stale_lock": lock_state,
        "last_command": state.get("last_command"),
        "last_rate_limit_command": state.get("last_rate_limit_command"),
        "last_rate_limit_at": state.get("last_rate_limit_at"),
        "updated_at": state.get("updated_at"),
    }


def acquire_json_lock(path: pathlib.Path, stale_seconds: float = 120.0, wait_seconds: float = 300.0) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + wait_seconds
    while True:
        if json_lock_is_stale(path, stale_seconds):
            path.unlink(missing_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if time.time() >= deadline:
                raise RuntimeError(f"Timed out waiting for lock: {path}")
            time.sleep(0.25)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "created_at": now_id()}) + "\n")
        return path


def read_json_file(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def project_targets(path: str | pathlib.Path | None = None) -> list[tuple[str, int]]:
    source = pathlib.Path(path) if path else RUNTIME_DIR / "projects.txt"
    if not source.exists():
        return []
    targets: list[tuple[str, int]] = []
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "/" in line:
            owner, number = line.rsplit("/", 1)
        else:
            parts = line.split()
            if len(parts) != 2:
                continue
            owner, number = parts
        try:
            targets.append((owner.strip(), int(number.strip())))
        except ValueError:
            continue
    return targets


def project_sync_dir() -> pathlib.Path:
    return jobs_dir() / "project-sync"


def project_sync_queue_path() -> pathlib.Path:
    return project_sync_dir() / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"


def project_state_update_mode() -> str:
    raw = os.environ.get("AGENT_PROJECT_STATE_UPDATE_MODE") or read_config().get("AGENT_PROJECT_STATE_UPDATE_MODE")
    legacy = os.environ.get("AGENT_PROJECT_STATE_UPDATES") or read_config().get("AGENT_PROJECT_STATE_UPDATES")
    value = str(raw or legacy or "direct").strip().strip('"').strip("'").lower()
    if value in {"queue", "queued", "dirty", "jsonl"}:
        return "queue"
    return "direct"


def append_project_sync_update(
    repo: str,
    number: int,
    fields: dict[str, str],
    *,
    projects_file: str | pathlib.Path | None = None,
    source: str = "update_issue_project_fields",
) -> list[pathlib.Path]:
    updates = {name: value for name, value in fields.items() if value}
    if not updates:
        return []
    targets = project_targets(projects_file)
    if not targets:
        return []
    queue_path = project_sync_queue_path()
    lock = acquire_json_lock(project_sync_dir() / "append.lock")
    written: list[pathlib.Path] = []
    try:
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        with queue_path.open("a", encoding="utf-8") as handle:
            for owner, project_number in targets:
                record = {
                    "version": 1,
                    "kind": "project_field_update",
                    "created_at": now_id(),
                    "repo": repo,
                    "number": int(number),
                    "project_owner": owner,
                    "project_number": int(project_number),
                    "fields": updates,
                    "source": source,
                }
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                written.append(queue_path)
    finally:
        lock.unlink(missing_ok=True)
    return written


def iter_project_sync_records(paths: list[pathlib.Path] | None = None) -> list[tuple[pathlib.Path, int, dict[str, Any]]]:
    candidates = paths or sorted(project_sync_dir().glob("*.jsonl"))
    records: list[tuple[pathlib.Path, int, dict[str, Any]]] = []
    for path in candidates:
        if not path.exists():
            continue
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"kind": "invalid", "raw": line}
            records.append((path, line_number, payload if isinstance(payload, dict) else {"kind": "invalid"}))
    return records


def project_info(owner: str, project_number: int) -> dict[str, Any] | None:
    projects = gh_json_or_none(
        ["project", "list", "--owner", owner, "--format", "json", "--limit", "100"],
        retries=2,
    )
    for project in (projects or {}).get("projects") or []:
        if int(project.get("number") or 0) == project_number:
            return project
    return None


def project_fields(owner: str, project_number: int) -> list[dict[str, Any]]:
    payload = gh_json_or_none(
        ["project", "field-list", str(project_number), "--owner", owner, "--format", "json", "--limit", "100"],
        retries=2,
    )
    return (payload or {}).get("fields") or []


def project_items(owner: str, project_number: int, limit: int | None = None) -> list[dict[str, Any]]:
    item_limit = limit if limit is not None else config_int("AGENT_PROJECT_ITEM_LIMIT", 500)
    payload = gh_json_or_none(
        [
            "project",
            "item-list",
            str(project_number),
            "--owner",
            owner,
            "--format",
            "json",
            "--limit",
            str(item_limit),
        ],
        retries=2,
    )
    return (payload or {}).get("items") or []


def read_project_snapshot(path: pathlib.Path | str) -> dict[str, Any]:
    snapshot_path = pathlib.Path(path)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {"items": payload}
    if not isinstance(payload, dict):
        raise ValueError(f"Project snapshot must be a JSON object or item list: {snapshot_path}")
    return payload


def project_snapshot_items(path: pathlib.Path | str, owner: str | None = None, project_number: int | None = None) -> list[dict[str, Any]]:
    payload = read_project_snapshot(path)
    project = payload.get("project") or {}
    if owner and project.get("owner") and str(project.get("owner")) != owner:
        return []
    if project_number is not None and project.get("number") and int(project.get("number") or 0) != int(project_number):
        return []
    return list(payload.get("items") or [])


def project_snapshot_fields(path: pathlib.Path | str) -> list[dict[str, Any]]:
    payload = read_project_snapshot(path)
    return list(payload.get("fields") or (payload.get("project") or {}).get("fields") or [])


def issue_project_item(items: list[dict[str, Any]], repo: str, number: int) -> dict[str, Any] | None:
    for item in items:
        content = item.get("content") or {}
        if str(content.get("repository") or "") == repo and int(content.get("number") or 0) == int(number):
            return item
    return None


def project_field_value_args(field: dict[str, Any], value: str) -> list[str] | None:
    options = {str(option.get("name")): str(option.get("id")) for option in field.get("options") or []}
    if options:
        option_id = options.get(value)
        if not option_id:
            return None
        return ["--single-select-option-id", option_id]
    return ["--text", value]


def update_issue_project_fields(
    repo: str,
    number: int,
    fields: dict[str, str],
    *,
    projects_file: str | pathlib.Path | None = None,
) -> None:
    if projects_file is None and not config_bool("AGENT_PROJECT_STATE_UPDATES", False):
        return
    updates = {name: value for name, value in fields.items() if value}
    if not updates:
        return
    if project_state_update_mode() == "queue":
        append_project_sync_update(repo, number, updates, projects_file=projects_file)
        return
    for owner, project_number in project_targets(projects_file):
        try:
            info = project_info(owner, project_number)
            if not info:
                continue
            field_configs = {str(field.get("name")): field for field in project_fields(owner, project_number)}
            item = issue_project_item(project_items(owner, project_number), repo, number)
            if not item:
                continue
            for name, value in updates.items():
                field = field_configs.get(name)
                if not field:
                    continue
                value_args = project_field_value_args(field, value)
                if not value_args:
                    continue
                run(
                    [
                        "gh",
                        "project",
                        "item-edit",
                        "--id",
                        str(item["id"]),
                        "--project-id",
                        str(info["id"]),
                        "--field-id",
                        str(field["id"]),
                        *value_args,
                    ],
                    check=False,
                    retries=2,
                )
        except Exception as exc:
            print(f"Project state update skipped for {repo}#{number} in {owner}/{project_number}: {exc}", flush=True)


def update_issue_automation_state(
    repo: str,
    number: int,
    automation_state: str,
    *,
    status: str | None = None,
    projects_file: str | pathlib.Path | None = None,
) -> None:
    fields = {"AutomationState": automation_state}
    if status:
        fields["Status"] = status
    update_issue_project_fields(repo, number, fields, projects_file=projects_file)


def label_cache_path(repo: str) -> pathlib.Path:
    return jobs_dir() / "label-cache" / f"{safe_repo_name(repo)}.json"


def ensure_labels_cached(repo: str, labels: dict[str, str]) -> None:
    if not labels:
        return
    cache_path = label_cache_path(repo)
    lock = acquire_json_lock(cache_path.with_suffix(".lock"))
    try:
        cache = read_json_file(cache_path)
        ensured = cache.get("labels") if isinstance(cache.get("labels"), dict) else {}
        changed = False
        for label, color in labels.items():
            if ensured.get(label) == color:
                continue
            proc = run(["gh", "label", "create", label, "--repo", repo, "--color", color], check=False)
            output = getattr(proc, "stdout", "") or ""
            returncode = getattr(proc, "returncode", 0)
            if returncode == 0 or "already exists" in output.lower():
                ensured[label] = color
                changed = True
        if changed:
            cache.update({"repo": repo, "labels": ensured, "updated_at": now_id()})
            write_json(cache_path, cache)
    finally:
        lock.unlink(missing_ok=True)


def github_throttle_before(parts: list[str] | None) -> None:
    if not parts:
        return
    interval = gh_command_interval(parts)
    if interval <= 0:
        return
    state_path, lock_path = github_throttle_paths()
    lock = acquire_json_lock(lock_path)
    try:
        state = read_json_file(state_path)
        now = time.time()
        pause_until = float(state.get("pause_until") or 0)
        next_allowed = float(state.get("next_allowed_at") or 0)
        wait_until = max(pause_until, next_allowed)
        if wait_until > now:
            wait = wait_until - now
            print(f"GitHub API throttle: waiting {wait:.1f}s", flush=True)
            time.sleep(wait)
            now = time.time()
        state.update(
            {
                "next_allowed_at": now + interval,
                "last_command": "gh " + " ".join(parts[:4]),
                "updated_at": now_id(),
            }
        )
        write_json(state_path, state)
    finally:
        lock.unlink(missing_ok=True)


def is_github_rate_limit_error(output: str) -> bool:
    lowered = (output or "").lower()
    return "rate limit" in lowered or "secondary rate" in lowered or "api rate limit already exceeded" in lowered


def github_throttle_after(parts: list[str] | None, output: str, returncode: int) -> None:
    if not parts or returncode == 0 or not is_github_rate_limit_error(output):
        return
    pause = config_float("AGENT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS", 900.0)
    state_path, lock_path = github_throttle_paths()
    lock = acquire_json_lock(lock_path)
    try:
        state = read_json_file(state_path)
        pause_until = max(float(state.get("pause_until") or 0), time.time() + pause)
        state.update(
            {
                "pause_until": pause_until,
                "last_rate_limit_at": now_id(),
                "last_rate_limit_command": "gh " + " ".join(parts[:6]),
            }
        )
        write_json(state_path, state)
        print(f"GitHub API throttle: rate limit detected; pausing future gh calls for {pause:.0f}s", flush=True)
    finally:
        lock.unlink(missing_ok=True)


def github_throttle_shell_command(command: str) -> list[str] | None:
    parts = gh_shell_command_parts(command)
    github_throttle_before(parts)
    return parts


def run(
    args: list[str],
    cwd: pathlib.Path | str | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
    retries: int = 1,
    backoff_seconds: float = 3.0,
) -> subprocess.CompletedProcess[str]:
    if args[:1] == ["git"]:
        env = git_env(env)
    gh_parts = gh_command_parts(args)
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, max(retries, 1) + 1):
        print("+ " + " ".join(shlex.quote(arg) for arg in args), flush=True)
        github_throttle_before(gh_parts)
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        github_throttle_after(gh_parts, proc.stdout or "", proc.returncode)
        if proc.returncode == 0:
            return proc
        last = proc
        if check and attempt < retries and args[:1] == ["gh"] and is_transient_github_error(proc.stdout or ""):
            wait = backoff_seconds * attempt
            print(f"GitHub CLI transient failure; retrying in {wait:.0f}s", flush=True)
            time.sleep(wait)
            continue
        break
    assert last is not None
    if check and last.returncode != 0:
        raise RuntimeError(
            "Command failed: "
            + " ".join(shlex.quote(arg) for arg in args)
            + "\n"
            + (last.stdout or "")
        )
    return last


def git_env(env: dict[str, str] | None = None) -> dict[str, str] | None:
    gh_path = shutil.which("gh")
    if not gh_path:
        return env
    result = os.environ.copy() if env is None else dict(env)
    result["GIT_CONFIG_GLOBAL"] = "/dev/null"
    result["GIT_CONFIG_COUNT"] = "4"
    result["GIT_CONFIG_KEY_0"] = "credential.helper"
    result["GIT_CONFIG_VALUE_0"] = ""
    result["GIT_CONFIG_KEY_1"] = "credential.https://github.com.helper"
    result["GIT_CONFIG_VALUE_1"] = ""
    result["GIT_CONFIG_KEY_2"] = "credential.helper"
    result["GIT_CONFIG_VALUE_2"] = f"!{gh_path} auth git-credential"
    result["GIT_CONFIG_KEY_3"] = "credential.https://github.com.helper"
    result["GIT_CONFIG_VALUE_3"] = f"!{gh_path} auth git-credential"
    return result


def is_transient_github_error(output: str) -> bool:
    markers = (
        "HTTP 502",
        "HTTP 503",
        "HTTP 504",
        "couldn't respond to your request in time",
        "connection reset",
        "connection refused",
        "connection timed out",
        "TLS handshake timeout",
        "temporary failure",
        "try again",
    )
    lowered = output.lower()
    return any(marker.lower() in lowered for marker in markers)


def gh_json(args: list[str], retries: int = 3, backoff_seconds: float = 5.0) -> Any:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, retries + 1):
        proc = run(["gh", *args], check=False)
        if proc.returncode == 0:
            text = proc.stdout.strip()
            return json.loads(text) if text else None
        last = proc
        if attempt < retries and is_transient_github_error(proc.stdout or ""):
            wait = backoff_seconds * attempt
            print(f"GitHub CLI transient failure; retrying in {wait:.0f}s", flush=True)
            time.sleep(wait)
            continue
        break
    assert last is not None
    raise RuntimeError(
        "Command failed after retries: "
        + " ".join(shlex.quote(arg) for arg in ["gh", *args])
        + "\n"
        + (last.stdout or "")
    )


def gh_json_or_none(args: list[str], retries: int = 3) -> Any | None:
    try:
        return gh_json(args, retries=retries)
    except RuntimeError as exc:
        print(str(exc), flush=True)
        return None


def read_config(path: pathlib.Path = CONFIG_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key.strip()] = os.path.expandvars(value)
    return values


def trusted_authors() -> set[str]:
    raw = os.environ.get("AGENT_TRUSTED_AUTHORS") or read_config().get(
        "AGENT_TRUSTED_AUTHORS",
        "",
    )
    return {author.strip() for author in raw.split(",") if author.strip()}


def git_identity() -> tuple[str, str]:
    cfg = read_config()
    name = os.environ.get("AGENT_GIT_USER_NAME") or cfg.get("AGENT_GIT_USER_NAME") or "Local Automation Agent"
    email = os.environ.get("AGENT_GIT_USER_EMAIL") or cfg.get("AGENT_GIT_USER_EMAIL") or "local-automation-agent@users.noreply.github.com"
    return name, email


def ensure_git_identity(repo_path: pathlib.Path) -> None:
    name, email = git_identity()
    run(["git", "config", "user.name", name], cwd=repo_path)
    run(["git", "config", "user.email", email], cwd=repo_path)


def env_for_repo(repo: str, base_branch: str | None = None) -> dict[str, str]:
    cfg = read_config()
    env = os.environ.copy()
    env.update(cfg)
    env["AGENT_REPO"] = repo
    env["AGENT_BASE_BRANCH"] = base_branch or default_base_branch(repo)
    for key in ("AGENT_HOME", "AGENT_REPOS", "AGENT_JOBS", "AGENT_LOGS", "AGENT_CODEX_HOME"):
        if key in env:
            env[key] = os.path.expandvars(env[key])
    return env


def default_base_branch(repo: str) -> str:
    cfg = read_config()
    env_key = "AGENT_BASE_BRANCH_" + re.sub(r"[^A-Za-z0-9]+", "_", repo).strip("_").upper()
    configured = os.environ.get(env_key) or cfg.get(env_key)
    if configured:
        return configured
    fallback = os.environ.get("AGENT_BASE_BRANCH") or cfg.get("AGENT_BASE_BRANCH")
    if fallback:
        return fallback
    data = gh_json_or_none(["repo", "view", repo, "--json", "defaultBranchRef"], retries=2)
    branch = ((data or {}).get("defaultBranchRef") or {}).get("name")
    if branch:
        return str(branch)
    raise RuntimeError(
        f"Could not determine default branch for {repo}; set AGENT_BASE_BRANCH or {env_key}."
    )


def repo_dir(repo: str) -> pathlib.Path:
    cfg = read_config()
    base = pathlib.Path(os.path.expandvars(os.environ.get("AGENT_REPOS") or cfg.get("AGENT_REPOS", str(RUNTIME_DIR / "repos"))))
    return base / repo.replace("/", "__")


def safe_repo_name(repo: str) -> str:
    return repo.replace("/", "__")


def repo_env_overlay_dir(repo: str) -> pathlib.Path:
    cfg = read_config()
    raw_base = os.environ.get("AGENT_REPO_ENV_OVERLAY_DIR") or cfg.get(
        "AGENT_REPO_ENV_OVERLAY_DIR",
        str(RUNTIME_DIR / "repo-env"),
    )
    return pathlib.Path(os.path.expandvars(raw_base)).expanduser() / safe_repo_name(repo)


def apply_repo_env_overlay(repo: str, worktree: pathlib.Path) -> list[str]:
    overlay = repo_env_overlay_dir(repo)
    if not overlay.exists():
        return []
    copied: list[str] = []
    for source in sorted(overlay.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(overlay)
        target = worktree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        os.chmod(target, 0o600)
        copied.append(relative.as_posix())
    return copied


def jobs_dir() -> pathlib.Path:
    cfg = read_config()
    return pathlib.Path(os.path.expandvars(os.environ.get("AGENT_JOBS") or cfg.get("AGENT_JOBS", str(RUNTIME_DIR / "jobs"))))


def logs_dir() -> pathlib.Path:
    cfg = read_config()
    return pathlib.Path(os.path.expandvars(os.environ.get("AGENT_LOGS") or cfg.get("AGENT_LOGS", str(RUNTIME_DIR / "logs"))))


def local_worker() -> pathlib.Path:
    runtime_worker = RUNTIME_DIR / "atlas-agent-worker"
    if runtime_worker.exists():
        return runtime_worker
    candidate = pathlib.Path.home() / ".local/bin/atlas-agent-worker"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"atlas-agent-worker not found at {candidate}")


def required_checks_config(path: pathlib.Path | str | None = None) -> dict[str, list[str]]:
    configured = os.environ.get("AGENT_REQUIRED_CHECKS_FILE") or read_config().get("AGENT_REQUIRED_CHECKS_FILE")
    config_path = pathlib.Path(path or configured or RUNTIME_DIR / "required-checks.json")
    if not config_path.exists():
        return {}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Required checks config must be a JSON object: {config_path}")
    result: dict[str, list[str]] = {}
    for repo, checks in data.items():
        if isinstance(checks, list):
            result[str(repo)] = [str(check).strip() for check in checks if str(check).strip()]
        elif isinstance(checks, dict):
            required = checks.get("required") or checks.get("checks") or []
            if isinstance(required, list):
                result[str(repo)] = [str(check).strip() for check in required if str(check).strip()]
    return result


def required_checks_for_repo(repo: str, path: pathlib.Path | str | None = None) -> list[str]:
    return required_checks_config(path).get(repo, [])


def required_checks_entry(repo: str, path: pathlib.Path | str | None = None) -> dict[str, Any]:
    configured = os.environ.get("AGENT_REQUIRED_CHECKS_FILE") or read_config().get("AGENT_REQUIRED_CHECKS_FILE")
    config_path = pathlib.Path(path or configured or RUNTIME_DIR / "required-checks.json")
    if not config_path.exists():
        return {}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    raw = data.get(repo) or data.get("*") or {}
    if isinstance(raw, list):
        return {"required": raw}
    if isinstance(raw, dict):
        return raw
    return {}


def no_checks_policy_for_repo(repo: str, path: pathlib.Path | str | None = None) -> dict[str, Any]:
    entry = required_checks_entry(repo, path)
    raw = entry.get("no_checks") or entry.get("no_checks_expected") or {}
    return raw if isinstance(raw, dict) else {}


def body_field_values(body: str, field: str) -> list[str]:
    values: list[str] = []
    pattern = re.compile(rf"^(?P<indent>\s*)[-*]?\s*{re.escape(field)}:\s*(?P<value>.*?)\s*$", re.IGNORECASE)
    lines = body.splitlines()
    for idx, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        value = match.group("value").strip().strip("`").strip()
        if value:
            values.append(value)
            continue
        parent_indent = len(match.group("indent"))
        for child in lines[idx + 1 :]:
            if not child.strip():
                break
            child_indent = len(child) - len(child.lstrip())
            stripped = child.strip()
            if stripped.startswith("#"):
                break
            if stripped.startswith("-"):
                if child_indent <= parent_indent and re.match(r"^[-*]\s*[A-Za-z][A-Za-z ]+:", stripped):
                    break
                item = stripped.lstrip("-").strip().strip("`").strip()
                if item:
                    values.append(item)
                continue
            if child_indent <= parent_indent:
                break
    return values


def has_body_field(body: str, field: str) -> bool:
    return bool(body_field_values(body, field))


def has_nonempty_body_field(body: str, field: str) -> bool:
    return any(value.lower() not in NONE_FIELD_VALUES for value in body_field_values(body, field))


def markdown_section_items(body: str, heading: str) -> list[str]:
    pattern = rf"(?ims)^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, body)
    if not match:
        return []
    items: list[str] = []
    in_fence = False
    saw_item = False
    for raw in match.group("body").splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not line:
            if saw_item:
                break
            continue
        if line.startswith("-"):
            item = line.lstrip("-").strip().strip("`").strip()
            if item and item.lower() not in NONE_FIELD_VALUES:
                items.append(item)
                saw_item = True
            continue
        if saw_item:
            break
    return items


def issue_point_values(issue: dict[str, Any]) -> list[int]:
    values: list[int] = []
    for label in sorted(label_names(issue)):
        if not label.startswith("points:"):
            continue
        try:
            values.append(int(label.split(":", 1)[1]))
        except ValueError:
            continue
    for match in POINT_FIELD_RE.finditer(str(issue.get("body") or "")):
        values.append(int(match.group(1)))

    unique: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def issue_points(issue: dict[str, Any]) -> int | None:
    values = issue_point_values(issue)
    return values[0] if len(values) == 1 else None


def issue_point_blockers(issue: dict[str, Any], *, require_one_point: bool) -> list[str]:
    if not require_one_point:
        return []
    labels = label_names(issue)
    values = issue_point_values(issue)
    if len(values) > 1:
        joined = ", ".join(f"points:{value}" for value in sorted(values))
        return [f"conflicting point metadata ({joined})"]
    if values:
        points = values[0]
        if points > 1:
            return [f"points:{points} requires decomposition before dispatch"]
        if points < 1:
            return [f"invalid points:{points}"]
        return []
    if "agent:one-point" in labels:
        return []
    return ["missing one-point metadata"]


def issue_execution_metadata_blockers(issue: dict[str, Any], *, require_one_point: bool = False) -> list[str]:
    body = str(issue.get("body") or "")
    lowered = body.lower()
    labels = label_names(issue)
    reasons: list[str] = []

    if "dispatch mode: `blocked`" in lowered or "dispatch mode: blocked" in lowered:
        reasons.append("blocked dispatch mode")
    if (
        ("dispatch mode: `manual-review`" in lowered or "dispatch mode: manual-review" in lowered)
        and "agent:approved-dispatch" not in labels
    ):
        reasons.append("manual-review dispatch mode requires explicit queueing")
    if "issue ready: `false`" in lowered or "issue ready: false" in lowered:
        reasons.append("issue ready false")

    if has_nonempty_body_field(body, "Open dependencies"):
        reasons.append("open dependencies")
    elif not has_body_field(body, "Open dependencies") and markdown_section_items(body, "Dependencies"):
        reasons.append("dependencies section without Open dependencies field")

    if has_nonempty_body_field(body, "Manual gates remaining"):
        reasons.append("manual gates remaining")
    elif not has_body_field(body, "Manual gates remaining") and markdown_section_items(
        body,
        "Deployed / Manual Validation Requirements",
    ):
        reasons.append("manual validation requirements without Manual gates remaining field")

    if markdown_section_items(body, "Blockers"):
        reasons.append("blockers section")
    if markdown_section_items(body, "Dispatch Guardrails"):
        reasons.append("dispatch guardrails")
    if has_nonempty_body_field(body, "Automation blockers"):
        reasons.append("automation blockers")

    reasons.extend(issue_point_blockers(issue, require_one_point=require_one_point))
    return reasons


def dependency_refs_from_body(repo: str, body: str) -> list[tuple[str, int, str]]:
    refs: list[tuple[str, int, str]] = []
    lowered = body.lower()
    if not has_nonempty_body_field(body, "Open dependencies"):
        return refs
    header = r"(?:-\s*)?open dependencies"

    match = re.search(rf"(?ims)^\s*{header}:\s*(.*?)(?:\n\s*\n|\n\s*(?:-\s*)?[A-Z][A-Za-z ]+:\s*|$)", body)
    block = match.group(1) if match else body
    for owner, name, kind, number in re.findall(
        r"github\.com/([^/\s]+)/([^/\s]+)/(issues|pull)/(\d+)",
        block,
    ):
        refs.append((f"{owner}/{name}", int(number), "pr" if kind == "pull" else "issue"))
    for owner, name, number in re.findall(r"\b([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#(\d+)\b", block):
        refs.append((f"{owner}/{name}", int(number), "issue"))
    for number in re.findall(r"(?<![\w/])#(\d+)\b", block):
        refs.append((repo, int(number), "issue"))

    seen: set[tuple[str, int, str]] = set()
    unique: list[tuple[str, int, str]] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


def issue_dependency_blockers(repo: str, issue: dict[str, Any]) -> list[str]:
    body = str(issue.get("body") or "")
    if not has_nonempty_body_field(body, "Open dependencies"):
        return []
    refs = dependency_refs_from_body(repo, body)
    if not refs:
        return ["open dependencies listed but no issue/PR refs were parsed"]
    blockers: list[str] = []
    for dep_repo, number, kind in refs:
        if kind == "pr":
            dep = gh_json_or_none(["pr", "view", str(number), "--repo", dep_repo, "--json", "state,merged,url"], retries=2)
            if not dep:
                blockers.append(f"{dep_repo} PR #{number} could not be verified")
            elif not dep.get("merged"):
                blockers.append(f"{dep_repo} PR #{number} is not merged")
            continue
        dep = gh_json_or_none(["issue", "view", str(number), "--repo", dep_repo, "--json", "state,url"], retries=2)
        if not dep:
            blockers.append(f"{dep_repo} issue #{number} could not be verified")
        elif str(dep.get("state") or "").upper() != "CLOSED":
            blockers.append(f"{dep_repo} issue #{number} is not closed")
    return blockers


def ensure_repo(repo: str) -> pathlib.Path:
    path = repo_dir(repo)
    if path.exists():
        run(["git", "fetch", "--all", "--prune"], cwd=path)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", f"https://github.com/{repo}.git", str(path)])
    return path


def issue_ref_parts(ref: str) -> tuple[str, int]:
    if "#" not in ref:
        raise ValueError("Issue ref must look like OWNER/REPO#123")
    repo, number = ref.rsplit("#", 1)
    return repo, int(number)


def pr_ref_parts(ref: str) -> tuple[str, int]:
    if "#" not in ref:
        raise ValueError("PR ref must look like OWNER/REPO#123")
    repo, number = ref.rsplit("#", 1)
    return repo, int(number)


def label_names(item: dict[str, Any]) -> set[str]:
    return {label["name"] for label in item.get("labels", [])}


def issue_body_base_branch(issue: dict[str, Any]) -> str | None:
    body = issue.get("body") or ""
    for pattern in (
        r"(?im)^\s*-\s*Base branch:\s*`([^`]+)`\s*$",
        r"(?im)^\s*Base branch:\s*`([^`]+)`\s*$",
    ):
        match = re.search(pattern, body)
        if match:
            return match.group(1).strip()
    return None


def _first_nonempty_field_value(body: str, *fields: str) -> str | None:
    for field in fields:
        for value in body_field_values(body, field):
            cleaned = str(value).strip().strip("`").strip()
            if cleaned and cleaned.lower() not in NONE_FIELD_VALUES:
                return cleaned
    return None


def issue_body_execution_repo(issue: dict[str, Any]) -> str | None:
    body = str(issue.get("body") or "")
    value = _first_nonempty_field_value(body, "Execution repo", "ExecutionRepo")
    if not value:
        return None
    return value.split(",", 1)[0].strip()


def linked_issue_ref(pr: dict[str, Any], default_repo: str) -> tuple[str, int] | None:
    body = str(pr.get("body") or "")
    combined = body + "\n" + str(pr.get("headRefName") or "")
    patterns = (
        r"(?im)^\s*Closes\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)\s*$",
        r"(?im)^\s*Closes\s+#(\d+)\s*$",
        r"(?im)^\s*-\s*Issue:\s+https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/(\d+)\s*$",
        r"(?im)^\s*Automated local Codex agent run for #(\d+)\.",
        r"agent/issue-(\d+)/",
    )
    for pattern in patterns:
        match = re.search(pattern, combined)
        if not match:
            continue
        if len(match.groups()) == 2:
            return match.group(1), int(match.group(2))
        return default_repo, int(match.group(1))
    return None


def linked_issue_number(pr: dict[str, Any], default_repo: str) -> int | None:
    ref = linked_issue_ref(pr, default_repo)
    return ref[1] if ref else None


def replace_issue_body_base(body: str, new_base: str) -> str:
    replacement = f"- Base branch: `{new_base}`"
    pattern = r"(?im)^\s*-\s*Base branch:\s*`[^`]+`\s*$"
    if re.search(pattern, body):
        return re.sub(pattern, replacement, body, count=1)
    return body.rstrip() + "\n" + replacement + "\n"


def remote_branch_exists(repo_path: pathlib.Path, branch: str) -> bool:
    proc = run(
        ["git", "rev-parse", "--verify", "--quiet", f"origin/{branch}"],
        cwd=repo_path,
        check=False,
    )
    return proc.returncode == 0


def podman_cmd() -> list[str]:
    cfg = read_config()
    configured = cfg.get("AGENT_PODMAN_CMD", "").strip()
    if configured:
        return shlex.split(configured)
    if shutil.which("podman"):
        return ["podman"]
    if shutil.which("distrobox-host-exec"):
        return ["distrobox-host-exec", "podman"]
    raise RuntimeError("Missing podman and distrobox-host-exec")


def podman_userns_args() -> list[str]:
    cmd = podman_cmd()
    if cmd and cmd[0] == "sudo":
        return []
    return ["--userns=keep-id"]


def codex_image() -> str:
    return read_config().get("AGENT_CODEX_IMAGE", "localhost/codex-agent:latest")


def codex_profile_args(kind: str) -> list[str]:
    cfg = read_config()
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", kind).strip("_").upper()
    args: list[str] = []
    profile = os.environ.get(f"AGENT_CODEX_{normalized}_PROFILE") or cfg.get(
        f"AGENT_CODEX_{normalized}_PROFILE",
        "",
    )
    model = os.environ.get(f"AGENT_CODEX_{normalized}_MODEL") or cfg.get(
        f"AGENT_CODEX_{normalized}_MODEL",
        "",
    )
    extra = os.environ.get(f"AGENT_CODEX_{normalized}_EXTRA_ARGS") or cfg.get(
        f"AGENT_CODEX_{normalized}_EXTRA_ARGS",
        "",
    )
    if profile:
        args.extend(["--profile", profile])
    if model:
        args.extend(["--model", model])
    if extra:
        args.extend(shlex.split(extra))
    return args


def codex_profile_shell_args(kind: str) -> str:
    return " ".join(shlex.quote(arg) for arg in codex_profile_args(kind))


def _path_is_relative_to(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _resolve_path(path: pathlib.Path) -> pathlib.Path:
    return path.expanduser().resolve(strict=False)


def configured_codex_home_path() -> pathlib.Path | None:
    raw_source = config_value("AGENT_CODEX_HOME")
    if not raw_source:
        return None
    return pathlib.Path(os.path.expandvars(raw_source)).expanduser()


def _path_fingerprint(path: pathlib.Path) -> str:
    return hashlib.sha256(str(_resolve_path(path)).encode("utf-8")).hexdigest()[:16]


def _redact_path(path: pathlib.Path) -> str:
    resolved = _resolve_path(path)
    runtime_dir = _resolve_path(RUNTIME_DIR)
    if resolved == runtime_dir or _path_is_relative_to(resolved, runtime_dir):
        return "$RUNTIME_DIR/" + str(resolved.relative_to(runtime_dir))

    homes: list[pathlib.Path] = []
    for raw_home in (os.environ.get("HOME"), str(pathlib.Path.home())):
        if raw_home:
            homes.append(_resolve_path(pathlib.Path(raw_home)))
    for home in homes:
        if resolved == home:
            return "$HOME"
        if _path_is_relative_to(resolved, home):
            return "$HOME/" + str(resolved.relative_to(home))

    return f"<external-codex-home:{_path_fingerprint(resolved)}>"


def _shared_codex_home_candidates() -> set[pathlib.Path]:
    candidates: set[pathlib.Path] = set()
    for raw_home in (os.environ.get("HOME"), str(pathlib.Path.home())):
        if raw_home:
            candidates.add(_resolve_path(pathlib.Path(raw_home) / ".codex"))
    # Some hosts expose the same home through /home and /var/home. Keep this
    # explicit because these runtime templates are commonly operated on that host.
    candidates.add(_resolve_path(pathlib.Path("/home/mat/.codex")))
    candidates.add(_resolve_path(pathlib.Path("/var/home/mat/.codex")))
    return candidates


def _is_shared_codex_home(path: pathlib.Path) -> bool:
    resolved = _resolve_path(path)
    for candidate in _shared_codex_home_candidates():
        if resolved == candidate or _path_is_relative_to(resolved, candidate):
            return True
    return False


def _owner_only(path: pathlib.Path) -> bool:
    try:
        return (path.stat().st_mode & 0o077) == 0
    except OSError:
        return False


def _codex_auth_indicator(source: pathlib.Path) -> pathlib.Path | None:
    for name in CODEX_AUTH_INDICATOR_NAMES:
        candidate = source / name
        if candidate.is_file():
            return candidate
    return None


def _iter_config_values(data: Any, key: str) -> list[str]:
    values: list[str] = []
    if isinstance(data, dict):
        for item_key, item_value in data.items():
            if item_key == key and item_value is not None:
                values.append(str(item_value).strip())
            values.extend(_iter_config_values(item_value, key))
    elif isinstance(data, list):
        for item in data:
            values.extend(_iter_config_values(item, key))
    return [value for value in values if value]


def _codex_config_workspace_ids(config_path: pathlib.Path) -> list[str]:
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return []

    values: list[str] = []
    try:
        import tomllib

        values = _iter_config_values(tomllib.loads(text), "forced_chatgpt_workspace_id")
    except Exception:
        values = []

    if values:
        return values

    pattern = re.compile(
        r"(?m)^\s*forced_chatgpt_workspace_id\s*=\s*['\"]?([^'\"\s#]+)['\"]?\s*(?:#.*)?$"
    )
    return [match.group(1).strip() for match in pattern.finditer(text) if match.group(1).strip()]


def validate_codex_home() -> dict[str, Any]:
    isolation_required = config_bool("AGENT_CODEX_ISOLATION_REQUIRED", True)
    allow_shared_home = config_bool("AGENT_ALLOW_SHARED_CODEX_HOME", False)
    workspace_id = config_value("AGENT_CODEX_WORKSPACE_ID")
    source = configured_codex_home_path()
    errors: list[str] = []
    warnings: list[str] = []
    codex_home: dict[str, Any] = {
        "configured": source is not None,
        "exists": False,
        "redacted_path": None,
        "path_sha256": None,
        "shared_global_home": False,
    }
    workspace: dict[str, Any] = {
        "expected": workspace_id or None,
        "configured": [],
        "matched": None if not workspace_id else False,
    }

    if source is None:
        errors.append("AGENT_CODEX_HOME is not configured")
        return {
            "ok": False,
            "isolation_required": isolation_required,
            "shared_home_allowed": allow_shared_home,
            "codex_home": codex_home,
            "auth_indicator": None,
            "workspace": workspace,
            "errors": errors,
            "warnings": warnings,
        }

    codex_home.update(
        {
            "exists": source.exists(),
            "redacted_path": _redact_path(source),
            "path_sha256": _path_fingerprint(source),
            "shared_global_home": _is_shared_codex_home(source),
        }
    )

    if codex_home["shared_global_home"]:
        if isolation_required and not allow_shared_home:
            errors.append(
                "AGENT_CODEX_HOME resolves to a shared/global Codex home; configure a runtime-local "
                "codex-home or set AGENT_ALLOW_SHARED_CODEX_HOME=true for an emergency override"
            )
        elif allow_shared_home:
            warnings.append("AGENT_ALLOW_SHARED_CODEX_HOME=true allows a shared/global Codex home")

    if not source.exists():
        errors.append("AGENT_CODEX_HOME does not exist")
    elif not source.is_dir():
        errors.append("AGENT_CODEX_HOME is not a directory")

    config_path = source / "config.toml"
    auth_indicator = _codex_auth_indicator(source) if source.exists() and source.is_dir() else None
    auth_name = auth_indicator.name if auth_indicator else None

    if source.exists() and source.is_dir() and isolation_required and not _owner_only(source):
        errors.append("AGENT_CODEX_HOME directory permissions allow group/other access")

    if config_path.exists():
        if isolation_required and not _owner_only(config_path):
            errors.append("config.toml permissions allow group/other access")
    elif isolation_required:
        errors.append("AGENT_CODEX_HOME is missing config.toml")

    if auth_indicator:
        if isolation_required and not _owner_only(auth_indicator):
            errors.append(f"{auth_indicator.name} permissions allow group/other access")
    elif isolation_required:
        errors.append(
            "AGENT_CODEX_HOME is missing a Codex auth indicator such as auth.json, credentials.json, or session.json"
        )

    if workspace_id:
        if config_path.exists():
            configured_workspace_ids = _codex_config_workspace_ids(config_path)
            workspace["configured"] = configured_workspace_ids
            workspace["matched"] = workspace_id in configured_workspace_ids
            if workspace_id not in configured_workspace_ids:
                errors.append("config.toml forced_chatgpt_workspace_id does not match AGENT_CODEX_WORKSPACE_ID")
        else:
            errors.append("AGENT_CODEX_WORKSPACE_ID is set but config.toml is unavailable")

    return {
        "ok": not errors,
        "isolation_required": isolation_required,
        "shared_home_allowed": allow_shared_home,
        "codex_home": codex_home,
        "auth_indicator": auth_name,
        "workspace": workspace,
        "errors": errors,
        "warnings": warnings,
    }


def codex_provider_metadata(validation: dict[str, Any] | None = None) -> dict[str, Any]:
    if validation is None:
        validation = validate_codex_home()
    return {
        "schema": "atlas-agent-provider-account.v1",
        "created_at": now_rfc3339(),
        "runtime": {
            "repo": config_value("AGENT_REPO") or None,
            "base_branch": config_value("AGENT_BASE_BRANCH") or None,
            "runtime_dir": "$RUNTIME_DIR",
        },
        "provider": {
            "kind": "openai-codex",
            "account_id": config_value("AGENT_PROVIDER_ACCOUNT_ID") or None,
            "account_label": config_value("AGENT_PROVIDER_ACCOUNT_LABEL") or None,
            "subscription_label": config_value("AGENT_PROVIDER_SUBSCRIPTION_LABEL") or None,
        },
        "codex": {
            "workspace_id": config_value("AGENT_CODEX_WORKSPACE_ID") or None,
            "home": validation.get("codex_home", {}),
            "auth_indicator": validation.get("auth_indicator"),
            "isolation_required": validation.get("isolation_required"),
            "shared_home_allowed": validation.get("shared_home_allowed"),
            "validation": {
                "ok": validation.get("ok"),
                "errors": validation.get("errors", []),
                "warnings": validation.get("warnings", []),
                "workspace": validation.get("workspace", {}),
            },
        },
    }


def write_codex_provider_metadata(
    job_dir: pathlib.Path,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = codex_provider_metadata(validation)
    write_json(job_dir / "provider-account.json", metadata)
    return metadata


def _codex_validation_error_message(validation: dict[str, Any]) -> str:
    prefix = (
        "Codex home isolation validation failed"
        if validation.get("isolation_required")
        else "Codex home validation failed"
    )
    details = "; ".join(validation.get("errors") or ["unknown error"])
    return f"{prefix}: {details}"


def codex_home_copy(job_dir: pathlib.Path) -> pathlib.Path:
    validation = validate_codex_home()
    write_codex_provider_metadata(job_dir, validation)
    if not validation["ok"]:
        raise RuntimeError(_codex_validation_error_message(validation))
    source = configured_codex_home_path()
    if source is None:
        raise RuntimeError("AGENT_CODEX_HOME is not configured.")
    target = pathlib.Path(tempfile.mkdtemp(prefix="codex-home-", dir=job_dir))
    shutil.copytree(source, target, dirs_exist_ok=True)
    for path in [target, *target.rglob("*")]:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    return target


def write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
