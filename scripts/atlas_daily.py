#!/usr/bin/env python3
"""Read-only discovery of one explicitly configured supervised installation."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MAX_INPUT = 65536


class DailyError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DailyError("arguments", "use [--config /absolute/config.json] status; see docs/daily-development.md")


def read_bytes(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("not a regular file")
            raw = stream.read(MAX_INPUT + 1)
        if not 1 <= len(raw) <= MAX_INPUT:
            raise ValueError("size")
        return raw
    except (OSError, ValueError):
        raise DailyError("input", "selected config or provenance file must be readable, regular and 1 through 65536 bytes; inspect the explicit selection") from None


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


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
            raise ValueError("not an object")
        return value
    except (UnicodeError, ValueError, RecursionError, OverflowError):
        raise DailyError("json", "selected input must be a strict JSON object without duplicate keys or nonfinite numbers") from None


def require_os_encoding(value, field):
    try:
        os.fsencode(value)
    except UnicodeError:
        raise DailyError("selection", field + " must be encodable for filesystem and subprocess use; correct the selected config") from None


def absolute_path(value, field):
    if (type(value) is not str or not value or "\0" in value
            or not Path(value).is_absolute()):
        raise DailyError("selection", field + " must be an explicit absolute path; inspect the selected config")
    require_os_encoding(value, field)
    try:
        return Path(value).resolve()
    except (OSError, RuntimeError, ValueError):
        raise DailyError("selection", field + " cannot be resolved; inspect the selected config") from None


def full_revision(value):
    return type(value) is str and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is not None


def selection(config_path):
    config = strict_object(read_bytes(config_path))
    runtime = absolute_path(config.get("runtime_dir"), "runtime_dir")
    state = absolute_path(config.get("state_dir"), "state_dir")
    owner = config.get("owner")
    if (type(owner) is not str or not owner.strip() or owner != owner.strip()
            or any(ord(char) < 32 for char in owner)):
        raise DailyError("selection", "owner must be a nonblank stable identity without surrounding whitespace or control characters")
    require_os_encoding(owner, "owner")
    if not full_revision(config.get("source_commit")):
        raise DailyError("selection", "source_commit must be a full lowercase source revision")
    if config.get("lane") != "supervised_in_app" or config.get("standalone_enabled") is not False:
        raise DailyError("lane", "select supervised_in_app with standalone_enabled false; this entry grants no unattended authority")
    if (runtime == (ROOT / "templates/local-automation-runtime").resolve()
            or not runtime.is_dir() or not (runtime / "atlas_local_dev.py").is_file()):
        raise DailyError("runtime", "select an existing installed runtime containing atlas_local_dev.py; never execute the source template")
    revisions = []
    for name in ("source-revision.txt", "runtime-source.json"):
        path = runtime / name
        if not os.path.lexists(path):
            continue
        raw = read_bytes(path)
        if name == "source-revision.txt":
            try:
                revision = raw.decode("utf-8").strip()
            except UnicodeError:
                raise DailyError("provenance", "source-revision.txt must contain the full source revision") from None
        else:
            marker = strict_object(raw)
            revision = marker.get("source_commit")
            for field, selected in (("runtime_dir", runtime), ("state_dir", state)):
                if field in marker and absolute_path(marker[field], field) != selected:
                    raise DailyError("provenance", "runtime-source.json " + field + " contradicts the selected config; review selection without rewriting markers")
            for field in ("owner", "lane", "standalone_enabled"):
                if field in marker and (type(marker[field]) is not type(config[field]) or marker[field] != config[field]):
                    raise DailyError("provenance", "runtime-source.json " + field + " contradicts the selected config; review selection without rewriting markers")
        if not full_revision(revision) or revision != config["source_commit"]:
            raise DailyError("provenance", "runtime source marker disagrees with source_commit; select the reviewed installation explicitly")
        revisions.append(name)
    if not revisions:
        raise DailyError("provenance", "selected runtime needs source-revision.txt or runtime-source.json; review its installation provenance")
    return runtime, state, owner, config["source_commit"], revisions


def checkout_identity():
    try:
        head = subprocess.run(["git", "--no-optional-locks", "-C", str(ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "--no-optional-locks", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=normal"],
                               capture_output=True, check=True, timeout=10).stdout != b""
        if not full_revision(head):
            raise ValueError("invalid HEAD")
        return head, dirty
    except (OSError, subprocess.SubprocessError, ValueError):
        raise DailyError("checkout", "cannot read the script checkout HEAD and working tree; run from a Git checkout") from None


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--config", default=str(ROOT / ".atlas-dev.local.json"))
        parser.add_argument("command", nargs="?", choices=("status",), default="status")
        args = parser.parse_args(argv)
        config_path = absolute_path(args.config, "config")
        runtime, state, owner, revision, markers = selection(config_path)
        head, dirty = checkout_identity()
        try:
            native = subprocess.run([sys.executable, "-B", str(runtime / "atlas_local_dev.py"),
                                     "--runtime-dir", str(runtime), "--state-dir", str(state),
                                     "--owner", owner, "status"],
                                    capture_output=True, check=False, timeout=30)
        except (OSError, subprocess.SubprocessError):
            raise DailyError("native_status", "selected installed status could not complete; inspect that runtime without dispatching work") from None
        if native.returncode:
            raise DailyError("native_status", "selected installed status failed (exit " + str(native.returncode) + "); inspect that runtime and queue without retrying dispatch")
        try:
            status = strict_object(native.stdout)
            if (status.get("status") not in {"observed", "uninitialized"}
                    or type(status.get("work_items")) is not list
                    or any(type(row) is not dict for row in status["work_items"])):
                raise ValueError("unexpected status")
        except (DailyError, ValueError, TypeError):
            raise DailyError("native_status", "selected installed status returned malformed status JSON; inspect the selected runtime") from None
        result = {
            "identity": {"config": str(config_path), "runtime_dir": str(runtime),
                         "state_dir": str(state), "owner": owner,
                         "runtime_source_commit": revision, "source_checkout": str(ROOT),
                         "source_checkout_head": head, "source_checkout_dirty": dirty,
                         "candidate_drift": head != revision or dirty,
                         "provenance_markers": markers, "lane": "supervised_in_app",
                         "standalone_enabled": False},
            "qualification_boundary": "Source markers record provenance, not installed-file integrity or host/account/model qualification. The supervisor must verify the exact host and route; supervised status grants no unattended authority.",
            "native_status": status,
        }
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except DailyError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": exc.message}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
