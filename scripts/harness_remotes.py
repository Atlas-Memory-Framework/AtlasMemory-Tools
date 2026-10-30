#!/usr/bin/env python3
"""Persist non-secret remote registrations without starting cloud operations."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from itertools import islice
from urllib.parse import quote, unquote, urlsplit

sys.dont_write_bytecode = True

from harness_service import HarnessService, HarnessServiceError, MAX_CODE_BYTES
from setup_harness_interface import (Change, SetupError, apply_changes,
                                     canonical_home, digest, owned_path, read_optional,
                                     rollback as rollback_installation)
from atlas_runtime_config import CAPABILITIES, MODEL_CAPABILITIES, RuntimeConfigError, resolve_role_settings

SCHEMA = "atlas-tools.remote-setup.v1"
RUNTIME_SCHEMA = "atlas-tools.remote-runtime.v1"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
MARKER = "harness-source.json"
DISCOVERY_TIMEOUT = 30
MAX_DISCOVERY_BYTES = 262_144


def _error(code: str, message: str) -> HarnessServiceError:
    return HarnessServiceError(code, message)


def _json(data: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    try:
        result = json.loads(data, object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    except (ValueError, UnicodeError, RecursionError):
        raise _error("invalid_remote_state", "The non-secret remote configuration or registry is malformed.") from None
    if not isinstance(result, dict):
        raise _error("invalid_remote_state", "The remote configuration and registry must be JSON objects.")
    return result


def repository_from_url(url: str, base_branch: str | None, repository_name: str | None = None) -> dict[str, str]:
    if not isinstance(url, str) or len(url) > 4096:
        raise _error("invalid_repository_url", "Use an explicit HTTPS Azure DevOps repository URL without credentials.")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc != "dev.azure.com" or
            parts.username or parts.password or parts.query or parts.fragment):
        raise _error("invalid_repository_url", "Use https://dev.azure.com/ORG/PROJECT/_git/REPOSITORY without credentials, ports, query or fragment.")
    segments = parts.path.strip("/").split("/")
    if len(segments) not in {2, 4} or (len(segments) == 4 and segments[2] != "_git") or any(not segment for segment in segments):
        raise _error("invalid_repository_url", "Choose an Azure project URL or a full repository URL.")
    names = [unquote(segment, errors="strict") for segment in segments]
    if repository_name is not None:
        if not isinstance(repository_name, str):
            raise _error("invalid_repository_name", "Select an explicit repository name from the Azure project.")
        if len(names) == 4 and repository_name != names[3]:
            raise _error("repository_conflict", "The selected repository name conflicts with the repository URL.")
        if len(names) == 2:
            names += ["_git", repository_name]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,99}", names[0]):
        raise _error("invalid_repository_url", "The Azure organization name is invalid.")
    for name in ([names[1]] + ([names[3]] if len(names) == 4 else [])):
        if (not name.strip() or name != name.strip() or name in {".", ".."} or
                any(ord(c) < 32 or c in '/\\?#%:"<>|*' for c in name)):
            raise _error("invalid_repository_url", "The Azure project or repository name is unsafe or ambiguous.")
    if base_branch is not None and (not isinstance(base_branch, str) or not base_branch or len(base_branch) > 200 or
            base_branch.startswith("-") or ".." in base_branch or
            any(c.isspace() or ord(c) < 32 for c in base_branch)):
        raise _error("invalid_base_branch", "Choose an explicit safe base branch.")
    canonical = "https://dev.azure.com/" + "/".join(quote(name, safe="-._~") for name in names)
    result = {"organization": names[0], "project": names[1], "url": canonical}
    if len(names) == 4:
        result["name"] = names[3]
    if base_branch is not None:
        result["base_branch"] = base_branch
    return result


class HarnessRemotes:
    def __init__(self, service: HarnessService):
        self.service = service
        self.home = canonical_home(pwd.getpwuid(os.getuid()).pw_dir)
        self.registry = owned_path(service.registry, self.home)
        if self.home.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise _error("unsafe_remote_path", "The current identity home must not be writable by another identity.")

    def _result(self, **values) -> dict:
        return {"schema_version": SCHEMA, "read_only": True, "coordination": "local",
                "cloud_authority": "Configuration grants no cloud-write or worker authorization.", **values}

    def _remove_empty_runtime_directories(self, files: list[dict]) -> None:
        roots = [self.home / item["path"] for item in files
                 if item.get("category") == "remote_runtime" and Path(item["path"]).name == MARKER]
        for marker in roots:
            root = owned_path(marker.parent, self.home)
            directories = {root}
            for item in files:
                if item.get("category") != "remote_runtime":
                    continue
                path = self.home / item["path"]
                directories.update(parent for parent in path.parents if parent == root or root in parent.parents)
            for directory in sorted(directories, key=lambda value: len(value.parts), reverse=True):
                try:
                    owned_path(directory, self.home).rmdir()
                except OSError:
                    pass

    def _sources(self) -> list[tuple[Path, Path, bytes, int]]:
        from harness_execution import canonical_code_files

        source_root = self.service.tools_root / "templates" / "local-automation-runtime"
        result = []
        for name in canonical_code_files(self.service.tools_root):
            path = source_root / name
            if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
                raise _error("unsafe_runtime_source", "Canonical runtime code must be owned regular files.")
            data = path.read_bytes()
            if len(data) > MAX_CODE_BYTES:
                raise _error("unsafe_runtime_source", "A canonical runtime code file exceeds its bounded limit.")
            result.append((path, Path(name), data, 0o555 if path.stat().st_mode & stat.S_IXUSR else 0o444))
        templates = source_root / "team-templates"
        paths = list(islice(templates.rglob("*"), 257))
        if len(paths) > 256:
            raise _error("unsafe_runtime_source", "The canonical template inventory exceeds its bounded limit.")
        for path in sorted(paths):
            if path.is_symlink():
                raise _error("unsafe_runtime_source", "Canonical templates must not contain symlinks.")
            if path.is_file():
                if path.suffix != ".json" or path.stat().st_uid != os.getuid() or path.stat().st_size > 262_144:
                    raise _error("unsafe_runtime_source", "Only bounded owned JSON team templates can be installed.")
                result.append((path, path.relative_to(source_root), path.read_bytes(), 0o444))
        return result

    def _plan(self, remote_id, provider, repository_url, base_branch, runtime_dir, models, repository_name, capabilities, checkout):
        if not isinstance(remote_id, str) or not IDENTIFIER.fullmatch(remote_id):
            raise _error("invalid_remote_id", "Choose a simple remote ID of at most 80 characters.")
        if provider != "azure-devops":
            raise _error("unsupported_remote_provider", "This remote configurator supports azure-devops explicitly.")
        profile = owned_path(self.home / ".config" / "atlasmemory-tools" / "remotes" / (remote_id + ".json"), self.home)
        old_profile = read_optional(profile, self.home)
        saved = _json(old_profile) if old_profile is not None else None
        if saved is not None:
            allowed = {"schema_version", "provider", "runtime_dir", "repository", "capabilities", "models", "sandbox", "approval_policy"}
            if (set(saved) - allowed or saved.get("schema_version") != 1 or saved.get("provider") != provider or
                    not isinstance(saved.get("repository"), dict)):
                raise _error("remote_conflict", "The saved profile has unsupported or invalid settings; preserve it for explicit repair.")
        current_profile_sha256 = "sha256:" + digest(old_profile) if old_profile is not None else None
        before_registry = read_optional(self.registry, self.home)
        data = _json(before_registry) if before_registry is not None else {"version": 1, "runtimes": [], "installations": []}
        if (set(data) - {"version", "runtimes", "installations"} or type(data.get("version")) is not int or
                data["version"] != 1 or not isinstance(data.get("runtimes"), list) or
                not isinstance(data.get("installations", []), list)):
            raise _error("invalid_remote_registry", "The existing registry is invalid; it was left unchanged.")
        ids = set()
        for item in data["runtimes"]:
            if (not isinstance(item, dict) or set(item) - {"id", "provider", "runtime_dir", "config"} or
                    not isinstance(item.get("id"), str) or not IDENTIFIER.fullmatch(item["id"]) or item["id"] in ids or
                    item.get("provider") not in {"github", "azure-devops"} or
                    not isinstance(item.get("runtime_dir"), str) or not Path(item["runtime_dir"]).is_absolute()):
                raise _error("invalid_remote_registry", "The existing registry contains an invalid or duplicate remote.")
            ids.add(item["id"])
        existing = next((item for item in data["runtimes"] if item["id"] == remote_id), None)
        if saved is not None and existing is None:
            raise _error("remote_conflict", "A profile exists without this registration; review its history before adopting it.")
        if saved is None and existing is not None:
            raise _error("remote_conflict", "An existing registration has a missing profile; review its history before repair.")
        selected_url = repository_from_url(repository_url, base_branch, repository_name)
        if saved is not None:
            prior = saved["repository"]
            old_target = repository_from_url(prior.get("url"), prior.get("base_branch"))
            if (set(prior) - {"organization", "project", "name", "url", "base_branch", "checkout"} or
                    any(prior.get(key) != old_target.get(key) for key in ("organization", "project", "name")) or
                    any(selected_url.get(key) != old_target.get(key) for key in ("organization", "project")) or
                    ("name" in selected_url and selected_url["name"] != old_target.get("name"))):
                raise _error("remote_conflict", "This remote ID already selects another Azure target. Choose a new remote ID to retarget; the saved target was preserved.")
            repository_name = selected_url.get("name", old_target.get("name"))
            base_branch = prior.get("base_branch") if base_branch is None else base_branch
            models = saved.get("models") if models is None else models
            capabilities = saved.get("capabilities") if capabilities is None else capabilities
            checkout = prior.get("checkout") if checkout is None else checkout
        repository = repository_from_url(repository_url, base_branch, repository_name)
        required = [key for key in ("name", "base_branch") if key not in repository]
        if required:
            return [], {"status": "needs_selection", "remote_id": remote_id, "provider": provider,
                        "repository": repository, "current_profile_sha256": current_profile_sha256,
                        "required_fields": ["repository_name" if key == "name" else key for key in required],
                        "next_actions": [{"operation": "list_azure_repositories" if "name" in required else "inspect_azure_repository",
                                          "url": repository["url"],
                                          "message": "Select a repository and verify its base branch from current remote metadata; no repository or branch is inferred."}]}
        capabilities = ["read"] if capabilities is None else capabilities
        if (not isinstance(capabilities, list) or not capabilities or
                any(not isinstance(item, str) for item in capabilities) or
                set(capabilities) - CAPABILITIES or len(set(capabilities)) != len(capabilities) or "read" not in capabilities):
            raise _error("invalid_remote_capabilities", "Choose explicit supported capabilities including read; merge and deployment are not supported.")
        if set(capabilities) & MODEL_CAPABILITIES and models is None:
            raise _error("missing_remote_models", "Worker, publication and assessment capabilities require explicit bounded settings for every model role; capabilities still grant no operation authority.")
        if models is not None:
            try:
                resolve_role_settings({"models": models})
            except (RuntimeConfigError, TypeError):
                raise _error("invalid_remote_models", "Explicit models must provide valid bounded settings for every role.") from None
        default_root = self.home / ".local" / "share" / "atlasmemory-tools" / "remotes" / remote_id / "runtime"
        supplied_root = runtime_dir if runtime_dir is not None else existing["runtime_dir"] if existing else default_root
        root = owned_path(Path(supplied_root), self.home)
        managed = runtime_dir is None and root == default_root
        source_root = self.service.tools_root / "templates" / "local-automation-runtime"
        if root == source_root or source_root in root.parents:
            raise _error("source_template", "Choose an installed runtime, never the canonical source template.")
        if root == self.home or (root.exists() and not root.is_dir()):
            raise _error("invalid_runtime", "A remote runtime must be an owned subdirectory of the current identity home.")
        if not managed and not root.is_dir():
            raise _error("invalid_runtime", "An explicitly selected runtime directory must already exist.")
        entry = {"id": remote_id, "provider": provider, "runtime_dir": str(root), "config": str(profile)}
        if existing is not None and existing != entry:
            raise _error("remote_conflict", "This remote ID already selects another runtime or profile; it was left unchanged.")
        if saved is not None and saved.get("runtime_dir") != str(root):
            raise _error("remote_conflict", "The registry and saved runtime selection disagree; preserve them for explicit repair.")
        if checkout is not None:
            if not isinstance(checkout, str):
                raise _error("invalid_remote_checkout", "Choose an explicit owned isolated checkout under this runtime's worktrees directory.")
            workspace = owned_path(Path(checkout), self.home)
            if not workspace.is_dir() or root / "worktrees" not in workspace.parents:
                raise _error("invalid_remote_checkout", "The checkout must already exist below runtime_dir/worktrees; configuration never clones or creates a worktree.")
            repository["checkout"] = str(workspace)
        elif set(capabilities) & {"local_execute", "draft_pr"}:
            return [], {"status": "needs_selection", "remote_id": remote_id, "provider": provider,
                        "repository": repository, "runtime_dir": str(root),
                        "current_profile_sha256": current_profile_sha256, "required_fields": ["checkout"],
                        "next_actions": [{"operation": "prepare_isolated_checkout", "runtime_dir": str(root),
                                          "required_parent": str(root / "worktrees"),
                                          "message": "Select an existing isolated task checkout below this runtime's worktrees directory, then preview the profile update. Configuration does not clone or create worktrees."}]}
        config = {"schema_version": 1, "provider": provider, "runtime_dir": str(root), "repository": repository,
                  "capabilities": sorted(capabilities), "sandbox": "workspace-write", "approval_policy": "on-request"}
        if models is not None:
            config["models"] = models
        profile_changed = old_profile is not None and saved != config
        profile_bytes = old_profile if old_profile is not None and not profile_changed else (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode()
        if existing is None:
            data["runtimes"].append(entry)
        registry_bytes = before_registry if before_registry is not None and _json(before_registry) == data else (json.dumps(data, indent=2) + "\n").encode()
        sources = self._sources()
        files = {relative.as_posix(): "sha256:" + digest(content) for _, relative, content, _ in sources}
        source_fingerprint = "sha256:" + digest(json.dumps(files, sort_keys=True).encode())
        marker = {"schema_version": RUNTIME_SCHEMA, "remote_id": remote_id,
                  "source_fingerprint": source_fingerprint, "files": files}
        changes = []
        created_runtime = managed and not root.exists()
        ready = True
        if managed and root.exists():
            old_marker = read_optional(root / MARKER, self.home)
            if existing is None or old_marker is None:
                raise _error("runtime_conflict", "The managed runtime location already exists without this registration; it was left unchanged.")
            installed = _json(old_marker)
            if installed.get("schema_version") != RUNTIME_SCHEMA or installed.get("remote_id") != remote_id:
                raise _error("runtime_conflict", "The managed runtime source marker does not match this registration.")
            if not isinstance(installed.get("files"), dict):
                raise _error("runtime_conflict", "The installed source marker is invalid.")
            ready = installed.get("source_fingerprint") == source_fingerprint
        for _, relative, content, mode in sources:
            target = owned_path(root / relative, self.home)
            current = read_optional(target, self.home) if root.exists() else None
            if created_runtime:
                changes.append(Change(target, None, content, mode, "remote_runtime", "missing"))
            elif current != content:
                ready = False
        if created_runtime:
            changes.append(Change(root / MARKER, None, (json.dumps(marker, indent=2) + "\n").encode(), 0o444,
                                  "remote_runtime", "missing"))
        if old_profile != profile_bytes:
            changes.append(Change(profile, old_profile, profile_bytes, 0o600, "remote_profile", "missing" if old_profile is None else "updated"))
        if before_registry != registry_bytes:
            changes.append(Change(self.registry, before_registry, registry_bytes, 0o600, "registry", "missing" if before_registry is None else "updated"))
        return changes, {"remote_id": remote_id, "provider": provider, "repository": repository,
                         "runtime_dir": str(root), "profile": str(profile), "registry": str(self.registry),
                         "current_profile_sha256": current_profile_sha256,
                         "requires_expected_profile_sha256": profile_changed, "models": config.get("models", {}),
                         "capabilities": sorted(capabilities), "managed_runtime": managed, "runtime_created": created_runtime,
                         "runtime_code_ready": ready and not created_runtime,
                         "runtime_code_ready_after_apply": ready, "source_fingerprint": source_fingerprint,
                         "auth": "Uses this identity's existing Azure CLI authentication; setup performs no login or token read.",
                         "next_actions": [{"operation": "review_remote_update", "runtime_id": remote_id,
                                           "expected_profile_sha256": current_profile_sha256,
                                           "message": "Review the changed settings and apply with this current profile fingerprint. Existing code and runtime state remain unchanged."}] if profile_changed else [{"operation": "inspect", "runtime_id": remote_id}] if ready else [
                             {"operation": "review_runtime_version", "runtime_id": remote_id,
                              "message": "Registered runtime code differs from this source. Preserve it and explicitly select a reviewed upgrade before cloud operations."}]}

    def configure(self, remote_id: str, provider: str, repository_url: str, base_branch: str | None = None,
                  runtime_dir: str | None = None, apply: bool = False, models: dict | None = None,
                  repository_name: str | None = None, capabilities: list[str] | None = None,
                  expected_profile_sha256: str | None = None, checkout: str | None = None) -> dict:
        if type(apply) is not bool:
            raise _error("invalid_apply", "Apply must be an explicit boolean.")
        if expected_profile_sha256 is not None and (not isinstance(expected_profile_sha256, str) or
                                                    not re.fullmatch(r"sha256:[a-f0-9]{64}", expected_profile_sha256)):
            raise _error("invalid_profile_fingerprint", "Use the exact current_profile_sha256 returned by the configuration preview.")
        def verify_profile(detail):
            current = detail.get("current_profile_sha256")
            if expected_profile_sha256 is not None and expected_profile_sha256 != current:
                raise _error("stale_remote_profile", "The saved profile changed since review; preview again before applying.")
            if detail.get("requires_expected_profile_sha256") and expected_profile_sha256 is None:
                raise _error("profile_update_requires_review", "Changing a saved profile requires the current_profile_sha256 from its reviewed preview.")
        lock_fd = None
        changes = []
        try:
            changes, detail = self._plan(remote_id, provider, repository_url, base_branch, runtime_dir, models, repository_name, capabilities, checkout)
            if detail.get("status") == "needs_selection":
                return self._result(mode="preview", **detail, changed=[], applied=False)
            if apply:
                verify_profile(detail)
                lock = owned_path(self.home / ".config" / "atlasmemory-tools" / "remotes" / ".configure.lock", self.home)
                lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                owned_path(lock, self.home)
                lock_fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise _error("remote_setup_busy", "Another remote configuration operation is active; observe it before retrying.") from None
                changes, detail = self._plan(remote_id, provider, repository_url, base_branch, runtime_dir, models, repository_name, capabilities, checkout)
                if detail.get("status") == "needs_selection":
                    return self._result(mode="preview", **detail, changed=[], applied=False)
                verify_profile(detail)
            result = self._result(mode="apply" if apply else "preview", **detail,
                                  changed=[{"path": str(item.path), "category": item.category,
                                            "status": item.status, "after_sha256": digest(item.after)} for item in changes])
            if apply:
                receipt = apply_changes(changes, self.home)
                result.update(read_only=False, applied=len(changes), receipt=str(receipt) if receipt else None,
                              runtime_code_ready=detail["runtime_code_ready_after_apply"])
            return result
        except (SetupError, RuntimeConfigError, OSError, UnicodeError, ValueError) as exc:
            if apply:
                self._remove_empty_runtime_directories([
                    {"path": str(item.path.relative_to(self.home)), "category": item.category}
                    for item in changes if item.before is None])
            if isinstance(exc, HarnessServiceError):
                raise
            raise _error("remote_setup_failed", "The selected owned remote files could not be configured safely; no auth operation was attempted.") from exc
        finally:
            if lock_fd is not None:
                os.close(lock_fd)

    def _discovery_environment(self) -> dict[str, str]:
        if os.environ.get("HOME") and Path(os.environ["HOME"]).resolve() != self.home:
            raise _error("azure_identity_mismatch", "Azure CLI HOME must match the current passwd identity.")
        config = owned_path(Path(os.environ.get("AZURE_CONFIG_DIR", str(self.home / ".azure"))), self.home)
        if not config.is_dir():
            raise _error("azure_auth_unavailable", "This identity has no selected Azure CLI configuration. Establish its access separately, then retry the read; this tool never logs in.")
        return {**os.environ, "AZURE_CONFIG_DIR": str(config), "AZURE_CORE_COLLECT_TELEMETRY": "false",
                "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no"}

    def _run_discovery(self, argv: list[str], environment: dict[str, str]) -> bytes:
        process = None
        selector = selectors.DefaultSelector()
        output = bytearray()
        deadline = time.monotonic() + DISCOVERY_TIMEOUT
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, env=environment, shell=False,
                                       start_new_session=True, close_fds=True)
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _error("azure_read_timeout", "Azure repository discovery exceeded its bounded wait; verify the existing account route before retrying.")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), min(65_536, MAX_DISCOVERY_BYTES + 1 - len(output)))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(chunk)
                    if len(output) > MAX_DISCOVERY_BYTES:
                        raise _error("azure_read_too_large", "Azure repository discovery exceeded its output bound; select a narrower explicit repository URL.")
            try:
                returncode = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise _error("azure_read_timeout", "Azure repository discovery exceeded its bounded wait.") from None
            if returncode:
                raise _error("azure_read_failed", "Azure repository discovery failed. Verify this identity's existing login and project read access; no login or cloud write was attempted.")
            return bytes(output)
        except OSError:
            raise _error("azure_auth_unavailable", "The current-identity Azure CLI is unavailable; no login or cloud write was attempted.") from None
        finally:
            selector.close()
            if process is not None:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
                if process.stdout is not None:
                    process.stdout.close()

    def repositories(self, project_url: str) -> dict:
        """Read names and default branches through normal same-identity Azure CLI auth."""
        project = repository_from_url(project_url, None)
        if "name" in project:
            raise _error("invalid_project_url", "Repository discovery requires the explicit Azure project URL.")
        environment = self._discovery_environment()
        url = project["url"] + "/_apis/git/repositories?api-version=7.1"
        argv = ["az", "rest", "--method", "get", "--resource", "499b84ac-1321-427f-aa17-267ca6975798",
                "--url", url, "--query", "value[].{name:name,default_branch:defaultBranch,id:id}",
                "--output", "json", "--only-show-errors"]
        content = self._run_discovery(argv, environment)
        try:
            rows = json.loads(content)
        except (ValueError, UnicodeError):
            raise _error("invalid_azure_repository_list", "Azure repository discovery returned an invalid bounded response.") from None
        if not isinstance(rows, list) or len(rows) > 128:
            raise _error("invalid_azure_repository_list", "Azure repository discovery requires at most 128 repository records.")
        repositories, names = [], set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                raise _error("invalid_azure_repository_list", "An Azure repository record is incomplete.")
            branch = row.get("default_branch")
            if branch == "":
                branch = None
            if branch is not None and (not isinstance(branch, str) or not branch.startswith("refs/heads/")):
                raise _error("invalid_azure_repository_list", "A repository default branch is missing or invalid.")
            base = branch.removeprefix("refs/heads/") if branch else None
            repository = repository_from_url(project["url"], base, row["name"])
            if row["name"].casefold() in names:
                raise _error("invalid_azure_repository_list", "Azure repository discovery returned duplicate names.")
            names.add(row["name"].casefold())
            # Construct URLs from the validated requested project and returned
            # name. Azure clone remoteUrl may contain benign userinfo; neither
            # userinfo nor arbitrary remote URLs are returned or persisted.
            repositories.append({"name": repository["name"], "url": repository["url"],
                                 "default_branch": branch, "base_branch": base})
        return self._result(status="observed", project=project, repositories=repositories,
                            selected_repository=None, live_read=True,
                            next_actions=[{"operation": "configure_remote", "requires": ["remote_id", "repository_url", "base_branch"],
                                           "message": "Select a returned repository explicitly before saving its profile."}])

    def rollback(self, receipt: str, apply: bool = False) -> dict:
        try:
            path = owned_path(Path(receipt), self.home)
            payload = _json(read_optional(path, self.home) or b"null")
            result = rollback_installation(path, self.home, apply=apply)
            if apply and not result.get("conflicts") and not result.get("already_rolled_back"):
                # Remove only empty directories created for new files. Local
                # operator data added after installation keeps its directories.
                self._remove_empty_runtime_directories([item for item in payload.get("files", [])
                                                        if item.get("before_sha256") is None])
            return self._result(read_only=not apply, **{key: value for key, value in result.items() if key != "schema_version"})
        except (SetupError, OSError, ValueError) as exc:
            if isinstance(exc, HarnessServiceError):
                raise
            raise _error("remote_rollback_failed", "Remote rollback could not safely restore the selected owned files.") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    configure = sub.add_parser("configure")
    configure.add_argument("--remote-id", required=True)
    configure.add_argument("--provider", default="azure-devops", choices=["azure-devops"])
    configure.add_argument("--repository-url", required=True)
    configure.add_argument("--base-branch")
    configure.add_argument("--repository-name")
    configure.add_argument("--runtime-dir")
    configure.add_argument("--capability", dest="capabilities", action="append")
    configure.add_argument("--models", help="Explicit JSON model settings for every role; contains no credentials.")
    configure.add_argument("--expected-profile-sha256")
    configure.add_argument("--checkout", help="Existing isolated task checkout below the selected runtime/worktrees.")
    configure.add_argument("--apply", action="store_true")
    restore = sub.add_parser("rollback")
    restore.add_argument("--receipt", required=True)
    restore.add_argument("--apply", action="store_true")
    discovery = sub.add_parser("repositories")
    discovery.add_argument("--project-url", required=True)
    args = parser.parse_args(argv)
    try:
        remotes = HarnessRemotes(HarnessService(registry=args.registry))
        if args.command == "repositories":
            result = remotes.repositories(args.project_url)
        elif args.command == "rollback":
            result = remotes.rollback(args.receipt, apply=args.apply)
        else:
            result = remotes.configure(args.remote_id, args.provider, args.repository_url, args.base_branch,
                                       args.runtime_dir, args.apply, models=json.loads(args.models) if args.models else None,
                                       repository_name=args.repository_name, capabilities=args.capabilities,
                                       expected_profile_sha256=args.expected_profile_sha256, checkout=args.checkout)
        print(json.dumps(result, indent=2))
        return 2 if result.get("conflicts") else 0
    except (HarnessServiceError, SetupError, ValueError, OSError) as exc:
        error = exc.as_dict() if isinstance(exc, HarnessServiceError) else {
            "code": "invalid_remote_setup", "message": "Remote setup input or owned paths are invalid; no auth operation was attempted."}
        print(json.dumps({"schema_version": SCHEMA, "error": error, "applied": False}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
