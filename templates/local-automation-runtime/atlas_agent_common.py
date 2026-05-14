#!/usr/bin/env python3
"""Shared helpers for the local automation runtime."""

from __future__ import annotations

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


def now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run(
    args: list[str],
    cwd: pathlib.Path | str | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
    retries: int = 1,
    backoff_seconds: float = 3.0,
) -> subprocess.CompletedProcess[str]:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, max(retries, 1) + 1):
        print("+ " + " ".join(shlex.quote(arg) for arg in args), flush=True)
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
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
    data = gh_json_or_none(["repo", "view", repo, "--json", "defaultBranchRef"], retries=2)
    branch = ((data or {}).get("defaultBranchRef") or {}).get("name")
    if branch:
        return str(branch)
    fallback = os.environ.get("AGENT_BASE_BRANCH") or cfg.get("AGENT_BASE_BRANCH")
    if fallback:
        return fallback
    raise RuntimeError(
        f"Could not determine default branch for {repo}; set AGENT_BASE_BRANCH or {env_key}."
    )


def repo_dir(repo: str) -> pathlib.Path:
    cfg = read_config()
    base = pathlib.Path(os.path.expandvars(cfg.get("AGENT_REPOS", str(RUNTIME_DIR / "repos"))))
    return base / repo.replace("/", "__")


def jobs_dir() -> pathlib.Path:
    cfg = read_config()
    return pathlib.Path(os.path.expandvars(cfg.get("AGENT_JOBS", str(RUNTIME_DIR / "jobs"))))


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


def dependency_refs_from_body(repo: str, body: str) -> list[tuple[str, int, str]]:
    refs: list[tuple[str, int, str]] = []
    lowered = body.lower()
    if "open dependencies:" not in lowered:
        return refs
    header = r"(?:-\s*)?open dependencies"
    if re.search(rf"(?im)^\s*{header}:\s*`?none`?\s*$", body):
        return refs

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
    lowered = body.lower()
    header = r"(?:-\s*)?open dependencies"
    if "open dependencies:" not in lowered or re.search(rf"(?im)^\s*{header}:\s*`?none`?\s*$", body):
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


def codex_home_copy(job_dir: pathlib.Path) -> pathlib.Path:
    cfg = read_config()
    source = pathlib.Path(os.path.expandvars(cfg["AGENT_CODEX_HOME"]))
    target = pathlib.Path(tempfile.mkdtemp(prefix="codex-home-", dir=job_dir))
    shutil.copytree(source, target, dirs_exist_ok=True)
    for path in [target, *target.rglob("*")]:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    return target


def write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
