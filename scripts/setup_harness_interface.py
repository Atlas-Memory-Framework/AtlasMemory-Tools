#!/usr/bin/env python3
"""Preview or install the account-local AtlasMemory Tools MCP interface safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

from harnesslib import REPO_ROOT, load_manifest, planned_files, render_generated, strip_generated_header


SCHEMA = "atlas-tools.setup.v1"
SERVER_NAME = "atlasmemory_tools"
BEGIN = "# atlasmemory-tools MCP begin sha256:"
END = "# atlasmemory-tools MCP end"
MAX_FILE_BYTES = 8 * 1024 * 1024


class SetupError(ValueError):
    """An actionable setup conflict, without configuration contents."""


@dataclass
class Change:
    path: Path
    before: bytes | None
    after: bytes
    mode: int
    category: str
    status: str


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_home(raw: str | Path) -> Path:
    # Bazzite uses /home -> /var/home. Establish that identity alias once; all
    # paths beneath the resulting home are checked without following symlinks.
    home = Path(raw).expanduser().resolve(strict=True)
    info = home.stat()
    if not home.is_dir() or info.st_uid != os.getuid():
        raise SetupError("home must be an existing directory owned by the current user")
    return home


def owned_path(path: Path, home: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise SetupError("setup paths must be absolute and remain inside the selected home")
    try:
        inside = path.relative_to(home)
    except ValueError:
        # Accept the platform's /home alias, but never resolve a path inside
        # the selected home before checking its individual components.
        alias_home = Path.home()
        if alias_home != home and alias_home.resolve() == home:
            try:
                inside = path.relative_to(alias_home)
            except ValueError:
                raise SetupError("setup paths must remain inside the selected home") from None
            path = home / inside
        else:
            raise SetupError("setup paths must remain inside the selected home") from None
    current = home
    for index, part in enumerate(inside.parts):
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise SetupError(f"refusing symlink in setup path: {current}")
        if info.st_uid != os.getuid():
            raise SetupError(f"setup path is not owned by the current user: {current}")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise SetupError(f"setup path is writable by another identity: {current}")
        if index < len(inside.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise SetupError(f"setup parent is not a directory: {current}")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise SetupError(f"refusing hard-linked setup file: {current}")
    return path


def read_optional(path: Path, home: Path) -> bytes | None:
    path = owned_path(path, home)
    if not path.exists():
        return None
    if not path.is_file():
        raise SetupError(f"expected a regular setup file: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise SetupError(f"setup file exceeds {MAX_FILE_BYTES} bytes: {path}")
    return path.read_bytes()


def server_configuration(registry: Path) -> dict:
    return {
        "command": str(Path(sys.executable).absolute()),
        "args": [str(REPO_ROOT / "scripts" / "harness_mcp.py"), "--registry", str(registry)],
        "enabled": True,
        "default_tools_approval_mode": "writes",
    }


def render_server(configuration: dict) -> str:
    # JSON string escaping is also valid TOML basic-string escaping here.
    body = (
        "[mcp_servers.atlasmemory_tools]\n"
        f"command = {json.dumps(configuration['command'])}\n"
        f"args = {json.dumps(configuration['args'])}\n"
        "enabled = true\n"
        'default_tools_approval_mode = "writes"\n'
    )
    return BEGIN + digest(body.encode()) + "\n" + body + END + "\n"


def merge_codex_config(before: bytes | None, configuration: dict) -> bytes:
    try:
        text = (before or b"").decode("utf-8")
        parsed = tomllib.loads(text)
    except (UnicodeError, tomllib.TOMLDecodeError):
        raise SetupError("existing Codex config is not valid UTF-8 TOML; left unchanged") from None
    servers = parsed.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise SetupError("Codex mcp_servers configuration is not a table; left unchanged")
    markers = list(re.finditer(r"(?m)^" + re.escape(BEGIN) + r"([0-9a-f]{64})\n", text))
    if text.count(BEGIN) != len(markers) or len(markers) > 1 or text.count(END) != len(markers):
        raise SetupError("ambiguous managed MCP section; left unchanged")
    block = render_server(configuration)
    if markers:
        match = markers[0]
        end = text.find(END, match.end())
        if end < 0 or not text.startswith(END + "\n", end):
            raise SetupError("invalid managed MCP section terminator; left unchanged")
        body = text[match.end():end]
        if digest(body.encode()) != match.group(1):
            raise SetupError("managed MCP section was edited locally; left unchanged")
        try:
            managed_parsed = tomllib.loads(body)
        except tomllib.TOMLDecodeError:
            raise SetupError("managed MCP section is invalid; left unchanged") from None
        if set(managed_parsed) != {"mcp_servers"} or set(managed_parsed["mcp_servers"]) != {SERVER_NAME}:
            raise SetupError("managed MCP section contains unrelated settings; left unchanged")
        result = text[:match.start()] + block + text[end + len(END) + 1:]
    elif SERVER_NAME in servers:
        if servers[SERVER_NAME] == configuration:
            return before or b""
        raise SetupError("an unmanaged atlasmemory_tools MCP server already exists; left unchanged")
    else:
        separator = "" if not text or text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n"
        result = text + separator + block
    try:
        updated = tomllib.loads(result)
    except tomllib.TOMLDecodeError:
        raise SetupError("MCP registration conflicts with existing TOML definitions; left unchanged") from None
    if updated.get("mcp_servers", {}).get(SERVER_NAME) != configuration:
        raise SetupError("MCP registration did not produce the expected server configuration")
    # No serialization of the original file: all unrelated bytes stay intact.
    return result.encode()


def registry_configuration(before: bytes | None, home: Path, runtime_dir: str | None,
                           provider: str | None, runtime_id: str | None,
                           runtime_config: str | None) -> bytes:
    try:
        data = json.loads(before) if before is not None else {"version": 1, "runtimes": [], "installations": []}
    except (ValueError, UnicodeError):
        raise SetupError("existing harness registry is invalid JSON; left unchanged") from None
    if not isinstance(data, dict) or data.get("version") != 1:
        raise SetupError("harness registry must be a version 1 object")
    runtimes, installations = data.setdefault("runtimes", []), data.setdefault("installations", [])
    if not isinstance(runtimes, list) or not isinstance(installations, list):
        raise SetupError("harness registry runtimes and installations must be lists")
    ids: set[str] = set()
    for entry in runtimes:
        if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or
                not entry["id"] or entry["id"] in ids or
                entry.get("provider") not in {"github", "azure-devops"} or
                not isinstance(entry.get("runtime_dir"), str) or
                not Path(entry["runtime_dir"]).is_absolute()):
            raise SetupError("harness registry contains invalid or duplicate runtime entries")
        ids.add(entry["id"])
    for entry in installations:
        if (not isinstance(entry, dict) or not isinstance(entry.get("target"), str) or
                not Path(entry["target"]).is_absolute() or
                entry.get("harness") not in {"codex", "claude", "gemini"}):
            raise SetupError("harness registry contains an invalid installation entry")
    if runtime_dir is not None:
        if provider is None or runtime_id is None or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", runtime_id):
            raise SetupError("--runtime-dir requires --provider and a simple --runtime-id")
        path = owned_path(Path(runtime_dir).expanduser(), home)
        if not path.is_dir():
            raise SetupError("--runtime-dir must name an existing owned runtime directory")
        template = REPO_ROOT / "templates" / "local-automation-runtime"
        if path == template or template in path.parents:
            raise SetupError("the canonical runtime template cannot be registered as an installed runtime")
        entry = {"id": runtime_id, "provider": provider, "runtime_dir": str(path)}
        if runtime_config:
            config_path = owned_path(Path(runtime_config).expanduser(), home)
            if not config_path.is_file() or config_path.name == "config.env":
                raise SetupError("--runtime-config must name an existing non-secret JSON configuration")
            entry["config"] = str(config_path)
        existing = next((item for item in runtimes if item["id"] == runtime_id), None)
        if existing is not None and existing != entry:
            raise SetupError("runtime id already names different configuration; left unchanged")
        if existing is None:
            runtimes.append(entry)
    elif provider is not None or runtime_id is not None or runtime_config is not None:
        raise SetupError("runtime registration options require --runtime-dir")
    installation = {"target": str(home), "harness": "codex"}
    if installation not in installations:
        installations.append(installation)
    rendered = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()
    # Keep existing formatting if content is already equivalent.
    return before if before is not None and json.loads(before) == data else rendered


def plan_setup(home: Path, registry: Path, *, runtime_dir: str | None = None,
               provider: str | None = None, runtime_id: str | None = None,
               runtime_config: str | None = None, skills_only: bool = False) -> tuple[list[Change], list[dict]]:
    changes: list[Change] = []
    conflicts: list[dict] = []
    manifest = load_manifest()
    for item in planned_files("codex", home, manifest):
        relative_source = item.source.relative_to(REPO_ROOT).as_posix()
        target = owned_path(item.target, home)
        before = read_optional(target, home)
        after = render_generated(relative_source, str(manifest["version"]))
        if before == after:
            continue
        if before is not None:
            try:
                metadata, body = strip_generated_header(before)
            except UnicodeError:
                metadata, body = None, b""
            if (metadata is None or metadata.get("source") != relative_source or
                    metadata.get("checksum") != "sha256:" + digest(body)):
                conflicts.append({"path": str(target), "category": "generated", "reason": "modified or unmanaged file preserved"})
                continue
        changes.append(Change(target, before, after, stat.S_IMODE(item.source.stat().st_mode),
                              "generated", "missing" if before is None else "stale"))
    if not skills_only:
        config = owned_path(home / ".codex" / "config.toml", home)
        for target, category, prepare in (
            (registry, "registry", lambda old: registry_configuration(old, home, runtime_dir, provider, runtime_id, runtime_config)),
            (config, "mcp_config", lambda old: merge_codex_config(old, server_configuration(registry))),
        ):
            try:
                before = read_optional(target, home)
                after = prepare(before)
                if before != after:
                    changes.append(Change(target, before, after, 0o600, category, "missing" if before is None else "stale"))
            except SetupError as exc:
                conflicts.append({"path": str(target), "category": category, "reason": str(exc)})
    return changes, conflicts


def atomic_write(path: Path, data: bytes, mode: int, home: Path) -> None:
    owned_path(path, home)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    owned_path(path, home)
    fd, temporary = tempfile.mkstemp(prefix=".atlas-tools-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_changes(changes: list[Change], home: Path, *, preserved: list[dict] | None = None) -> Path | None:
    if not changes:
        return None
    # Validate all inputs before producing any backups or writes.
    for change in changes:
        if read_optional(change.path, home) != change.before:
            raise SetupError(f"file changed since preview: {change.path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
    backup_root = owned_path(home / ".local" / "state" / "atlasmemory-tools" / "installations" / stamp, home)
    backup_root.mkdir(parents=True, mode=0o700)
    records = []
    for index, change in enumerate(changes):
        old_mode = stat.S_IMODE(change.path.stat().st_mode) if change.before is not None else None
        backup = f"{index:04d}.before" if change.before is not None else None
        if backup:
            atomic_write(backup_root / backup, change.before, 0o600, home)
        records.append({"path": str(change.path.relative_to(home)), "backup": backup,
                        "before_sha256": digest(change.before) if change.before is not None else None,
                        "after_sha256": digest(change.after), "before_mode": old_mode,
                        "after_mode": change.mode, "category": change.category})
    receipt = backup_root / "receipt.json"
    payload = {"schema_version": SCHEMA, "home": str(home), "status": "prepared", "files": records,
               "preserved": preserved or []}
    atomic_write(receipt, (json.dumps(payload, indent=2) + "\n").encode(), 0o600, home)
    applied: list[tuple[Change, dict]] = []
    try:
        for change, record in zip(changes, records):
            if read_optional(change.path, home) != change.before:
                raise SetupError(f"file changed during installation: {change.path}")
            atomic_write(change.path, change.after, change.mode, home)
            applied.append((change, record))
    except Exception:
        for change, record in reversed(applied):
            if read_optional(change.path, home) != change.after:
                continue
            if change.before is None:
                change.path.unlink()
            else:
                atomic_write(change.path, change.before, record["before_mode"], home)
        payload["status"] = "failed_rolled_back"
        atomic_write(receipt, (json.dumps(payload, indent=2) + "\n").encode(), 0o600, home)
        raise
    payload["status"] = "applied"
    atomic_write(receipt, (json.dumps(payload, indent=2) + "\n").encode(), 0o600, home)
    return receipt


def rollback(receipt: Path, home: Path, *, apply: bool) -> dict:
    receipt = owned_path(receipt, home)
    try:
        payload = json.loads(read_optional(receipt, home) or b"null")
    except (ValueError, UnicodeError):
        raise SetupError("rollback receipt is invalid") from None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA or payload.get("home") != str(home):
        raise SetupError("rollback receipt does not match this home and setup schema")
    if payload.get("status") == "rolled_back":
        return {"schema_version": SCHEMA, "mode": "rollback", "changed": [], "conflicts": [], "already_rolled_back": True}
    if payload.get("status") != "applied" or not isinstance(payload.get("files"), list):
        raise SetupError("rollback requires an applied installation receipt")
    candidates, conflicts = [], []
    for entry in payload["files"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or Path(entry["path"]).is_absolute():
            raise SetupError("invalid rollback file entry")
        target = owned_path(home / entry["path"], home)
        current = read_optional(target, home)
        if current is None or digest(current) != entry.get("after_sha256"):
            conflicts.append({"path": str(target), "reason": "file changed after installation; preserved"})
            continue
        backup = entry.get("backup")
        before = None
        mode = entry.get("before_mode")
        if backup is not None:
            if not isinstance(backup, str) or Path(backup).name != backup:
                raise SetupError("invalid rollback backup reference")
            before = read_optional(receipt.parent / backup, home)
            if before is None or digest(before) != entry.get("before_sha256") or not isinstance(mode, int) or mode & ~0o777:
                raise SetupError("rollback backup is missing or does not match its fingerprint")
        elif entry.get("before_sha256") is not None:
            raise SetupError("rollback receipt has inconsistent backup metadata")
        candidates.append((target, before, mode))
    # Rollback is all-or-nothing when a user edited any installed file.
    if apply and not conflicts:
        for target, before, mode in reversed(candidates):
            if before is None:
                target.unlink()
            else:
                atomic_write(target, before, mode, home)
        payload["status"] = "rolled_back"
        atomic_write(receipt, (json.dumps(payload, indent=2) + "\n").encode(), 0o600, home)
    return {"schema_version": SCHEMA, "mode": "rollback_apply" if apply else "rollback_preview",
            "changed": [str(target) for target, _, _ in candidates] if not conflicts else [],
            "conflicts": conflicts, "receipt": str(receipt)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=str(Path.home()), help="Existing current-user home to update; defaults to this account.")
    parser.add_argument("--registry", help="Non-secret registry path; defaults to HOME/.config/atlasmemory-tools/harness.json.")
    parser.add_argument("--runtime-dir", help="Explicit existing runtime directory to register.")
    parser.add_argument("--provider", choices=("github", "azure-devops"))
    parser.add_argument("--runtime-id")
    parser.add_argument("--runtime-config", help="Optional non-secret provider JSON configuration.")
    parser.add_argument("--skills-only", action="store_true", help="Refresh managed skills and agents without touching MCP configuration or registry.")
    parser.add_argument("--preserve-local", action="store_true", help="Explicitly preserve locally edited/unmanaged skills while installing safe updates; configuration conflicts still block installation.")
    parser.add_argument("--rollback", help="Installation receipt to restore; defaults to preview.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Apply the reviewed changes and save private backups.")
    mode.add_argument("--check", action="store_true", help="Read-only consistency check; exit 1 when changes are needed.")
    args = parser.parse_args(argv)
    try:
        home = canonical_home(args.home)
        if args.rollback:
            result = rollback(Path(args.rollback).expanduser(), home, apply=args.apply)
        else:
            registry = owned_path(Path(args.registry).expanduser() if args.registry else home / ".config" / "atlasmemory-tools" / "harness.json", home)
            changes, conflicts = plan_setup(home, registry, runtime_dir=args.runtime_dir, provider=args.provider,
                                            runtime_id=args.runtime_id, runtime_config=args.runtime_config, skills_only=args.skills_only)
            preserved = [item for item in conflicts if item.get("category") == "generated"] if args.preserve_local else []
            if args.preserve_local:
                conflicts = [item for item in conflicts if item.get("category") != "generated"]
            result = {"schema_version": SCHEMA, "mode": "apply" if args.apply else "check" if args.check else "preview",
                      "home": str(home), "registry": str(registry), "read_only": not args.apply,
                      "changed": [{"path": str(c.path), "category": c.category, "status": c.status,
                                   "before_sha256": digest(c.before) if c.before is not None else None,
                                   "after_sha256": digest(c.after)} for c in changes], "conflicts": conflicts,
                      "preserved": preserved,
                      "consistency": "local_changes_preserved" if preserved else "conflicts" if conflicts else "updates_needed" if changes else "current"}
            if args.apply and not conflicts:
                receipt = apply_changes(changes, home, preserved=preserved)
                result["receipt"] = str(receipt) if receipt else None
                result["applied"] = len(changes)
                if not preserved:
                    result["consistency"] = "current"
        print(json.dumps(result, indent=2))
        return 2 if result.get("conflicts") else 1 if args.check and (result.get("changed") or result.get("preserved")) else 0
    except (SetupError, OSError, ValueError) as exc:
        # Never echo config contents or parser excerpts, which may contain secrets.
        message = str(exc) if isinstance(exc, SetupError) else "setup could not read or update the selected owned files"
        print(json.dumps({"schema_version": SCHEMA, "error": message, "applied": False}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
