#!/usr/bin/env python3
"""Sync an installed local automation runtime from the source template."""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "templates" / "local-automation-runtime"

PRESERVE_FILES = {
    "config.env",
    "deployed-validation.json",
    "local-validation.json",
    "projects.txt",
    "repos.txt",
    "required-checks.json",
}

PRESERVE_DIRS = {
    "codex-home",
    "jobs",
    "logs",
    "repo-env",
    "repos",
    "state",
}


def run_capture(args: list[str]) -> str:
    proc = subprocess.run(args, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise SystemExit((proc.stdout or "").strip() or f"command failed: {' '.join(args)}")
    return proc.stdout


def source_template_files() -> list[Path]:
    output = run_capture(["git", "ls-files", "--cached", "--others", "--exclude-standard", "templates/local-automation-runtime"])
    files: list[Path] = []
    for raw in output.splitlines():
        path = Path(raw)
        relative = path.relative_to("templates/local-automation-runtime")
        if relative.parts[0] in PRESERVE_DIRS or relative.as_posix() in PRESERVE_FILES:
            continue
        files.append(relative)
    return sorted(files)


def parse_config_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.exists():
        return keys
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key and key.replace("_", "").isalnum() and not key[0].isdigit():
            keys.add(key)
    return keys


def example_config_lines_for_missing_keys(config_path: Path) -> list[str]:
    existing = parse_config_keys(config_path)
    missing: list[str] = []
    for raw in (TEMPLATE_ROOT / "config.env.example").read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key not in existing:
            missing.append(raw)
    return missing


def make_writable(path: Path) -> None:
    if not path.exists():
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IWUSR)


def copy_file(source: Path, target: Path, *, readonly: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    make_writable(target)
    shutil.copy2(source, target)
    shutil.copymode(source, target)
    if readonly:
        mode = target.stat().st_mode
        if mode & stat.S_IXUSR:
            target.chmod((mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        else:
            target.chmod(mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)


def sync_runtime(runtime_dir: Path, *, apply: bool, migrate_config: bool, readonly: bool) -> int:
    runtime_dir = runtime_dir.expanduser().resolve()
    if not runtime_dir.exists():
        raise SystemExit(f"runtime dir does not exist: {runtime_dir}")
    if not runtime_dir.is_dir():
        raise SystemExit(f"runtime path is not a directory: {runtime_dir}")

    changed: list[str] = []
    missing: list[str] = []
    for relative in source_template_files():
        source = TEMPLATE_ROOT / relative
        target = runtime_dir / relative
        if not target.exists():
            missing.append(relative.as_posix())
        elif not filecmp.cmp(source, target, shallow=False):
            changed.append(relative.as_posix())

    missing_config_lines = example_config_lines_for_missing_keys(runtime_dir / "config.env")

    if not apply:
        if missing:
            print("missing managed files:")
            print("\n".join(f"- {item}" for item in missing))
        if changed:
            print("drifted managed files:")
            print("\n".join(f"- {item}" for item in changed))
        if missing_config_lines:
            print("missing config.env keys:")
            print("\n".join(f"- {line.split('=', 1)[0].strip()}" for line in missing_config_lines))
        if not missing and not changed and not missing_config_lines:
            print(f"{runtime_dir}: runtime is in sync")
        return 1 if missing or changed or missing_config_lines else 0

    for relative in source_template_files():
        copy_file(TEMPLATE_ROOT / relative, runtime_dir / relative, readonly=readonly)

    if migrate_config and missing_config_lines:
        config_path = runtime_dir / "config.env"
        make_writable(config_path)
        existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        suffix = "" if existing.endswith("\n") or not existing else "\n"
        block = "\n# Added by sync_runtime_template.py from config.env.example\n" + "\n".join(missing_config_lines) + "\n"
        config_path.write_text(existing + suffix + block, encoding="utf-8")

    print(f"synced {len(source_template_files())} managed files to {runtime_dir}")
    if migrate_config and missing_config_lines:
        print(f"added {len(missing_config_lines)} missing config.env keys")
    if readonly:
        print("managed runtime files made read-only")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", required=True, help="Installed runtime directory to check or sync.")
    parser.add_argument("--apply", action="store_true", help="Overwrite managed runtime files from the template.")
    parser.add_argument("--migrate-config", action="store_true", help="Append missing config.env keys from config.env.example.")
    parser.add_argument("--readonly", action="store_true", help="Make managed copied files read-only after sync.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return sync_runtime(
        Path(args.runtime_dir),
        apply=args.apply,
        migrate_config=args.migrate_config,
        readonly=args.readonly,
    )


if __name__ == "__main__":
    raise SystemExit(main())
