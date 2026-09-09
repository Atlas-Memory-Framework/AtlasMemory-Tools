"""Verify operator-issued grants using an existing, fixed public trust registry.

This module never provisions trust, signs a grant, reads a private key, or grants
authority from model output. The runtime must live outside worker worktrees. A
caller cannot choose another registry; only runtime/authority/trust.json is read.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import time
from typing import Any


OPENSSL = "/usr/bin/openssl"
MAX_JSON_BYTES = 262_144
MAX_GRANT_SECONDS = 86_400
ACTIONS = frozenset({"local_execute", "draft_pr", "board_write", "assess", "human_gate"})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}\Z")
_PUBLIC_KEY = re.compile(
    r"-----BEGIN PUBLIC KEY-----\n([A-Za-z0-9+/=\n]+)-----END PUBLIC KEY-----\n?\Z"
)


class AuthorityError(ValueError):
    """The requested operation has no verified, current authority."""


def _validate_json(value: Any, *, depth: int = 0, count: list[int] | None = None) -> None:
    if count is None:
        count = [0]
    count[0] += 1
    if depth > 24 or count[0] > 16_384:
        raise AuthorityError("JSON input exceeds the verification complexity limit")
    kind = type(value)
    if kind in (type(None), bool, int):
        if kind is int and abs(value) > 2 ** 63 - 1:
            raise AuthorityError("JSON integers must fit the signed 64-bit range")
        return
    if kind is float:
        if not math.isfinite(value):
            raise AuthorityError("nonfinite JSON numbers are forbidden")
        return
    if kind is str:
        try:
            if len(value.encode("utf-8")) > MAX_JSON_BYTES:
                raise AuthorityError("JSON string exceeds the input limit")
        except UnicodeError as exc:
            raise AuthorityError("JSON strings must be valid UTF-8") from exc
        return
    if kind is list:
        for item in value:
            _validate_json(item, depth=depth + 1, count=count)
        return
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise AuthorityError("JSON object keys must be strings")
            _validate_json(key, depth=depth + 1, count=count)
            _validate_json(item, depth=depth + 1, count=count)
        return
    raise AuthorityError("authority inputs must contain only JSON value types")


def _canonical_bytes(value: Any) -> bytes:
    _validate_json(value)
    try:
        result = json.dumps(value, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise AuthorityError("JSON input cannot be canonicalized") from exc
    if len(result) > MAX_JSON_BYTES:
        raise AuthorityError("canonical JSON exceeds the input limit")
    return result


def canonical_digest(value: Any) -> str:
    """Hash strictly typed, bounded JSON with the shared UTF-8 contract."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def strict_json_loads(value: str | bytes) -> Any:
    """Read JSON without losing evidence of duplicate keys or nonfinite values."""
    if type(value) not in (str, bytes):
        raise AuthorityError("JSON input must be text or bytes")
    if len(value) > MAX_JSON_BYTES:
        raise AuthorityError("JSON input exceeds the input limit")

    def pairs(entries: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in entries:
            if key in result:
                raise AuthorityError("duplicate JSON keys are forbidden")
            result[key] = item
        return result

    def nonfinite(_: str) -> None:
        raise AuthorityError("nonfinite JSON numbers are forbidden")

    try:
        result = json.loads(value, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, AuthorityError):
            raise
        raise AuthorityError("authority input is not valid strict JSON") from exc
    _canonical_bytes(result)
    return result


def _object(value: Any, keys: set[str], description: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise AuthorityError(f"{description} has missing or unsupported fields")
    return value


def _version(value: Any) -> None:
    if type(value) is not int or value != 1:
        raise AuthorityError("unsupported authority schema")


def _identifier(value: Any, description: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        raise AuthorityError(f"{description} is invalid")
    return value


def _hash(value: Any, description: str) -> str:
    if type(value) is not str or not _HEX.fullmatch(value):
        raise AuthorityError(f"{description} must be a canonical SHA-256 digest")
    return value


def _action_list(value: Any) -> list[str]:
    if (type(value) is not list or not value or
            any(type(action) is not str or action not in ACTIONS for action in value) or
            len(set(value)) != len(value)):
        raise AuthorityError("issuer actions must be distinct supported operations")
    return value


def _runtime_directory(raw: str | Path) -> Path:
    """Validate the existing identity-owned root without following symlinks."""
    if not isinstance(raw, (str, Path)) or not str(raw).strip():
        raise AuthorityError("an explicit runtime directory is required")
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts:
        raise AuthorityError("runtime must be an absolute path without traversal")
    try:
        uid = os.getuid()
        if os.geteuid() != uid:
            raise AuthorityError("effective identity does not match runtime identity")
        home = Path(pwd.getpwuid(uid).pw_dir)
        if not home.is_absolute() or path == home or home not in path.parents:
            raise AuthorityError("runtime must be within the current passwd identity")
        relative = path.relative_to(home)
        if any(part in {"worktrees", "assessment-worktrees", ".git"} for part in relative.parts):
            raise AuthorityError("authority cannot reside inside an agent worktree")
        for current in (home, *(home.joinpath(*relative.parts[:n]) for n in range(1, len(relative.parts) + 1))):
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
                raise AuthorityError("runtime ancestry must be owned, non-writable directories without symlinks")
            # Both ordinary checkouts (.git directory) and linked worktrees
            # (.git file) can be agent write roots; do not place trust in either.
            git_marker = current / ".git"
            try:
                git_marker.lstat()
            except FileNotFoundError:
                continue
            raise AuthorityError("authority cannot reside inside a Git checkout or linked Git worktree")
        return path
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        if isinstance(exc, AuthorityError):
            raise
        raise AuthorityError("current-identity runtime is unavailable") from exc


def _read_trust(runtime: Path) -> dict[str, Any]:
    """Open only the fixed registry using descriptor-relative, no-follow reads."""
    descriptors: list[int] = []
    try:
        uid = os.getuid()
        home = Path(pwd.getpwuid(uid).pw_dir)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        directory = os.open(home, flags)
        descriptors.append(directory)
        home_info = os.fstat(directory)
        if home_info.st_uid != uid or not stat.S_ISDIR(home_info.st_mode) or home_info.st_mode & 0o022:
            raise AuthorityError("trust home ancestry must be owned and not group/world writable")
        for part in runtime.relative_to(home).parts + ("authority",):
            directory = os.open(part, flags, dir_fd=directory)
            descriptors.append(directory)
            info = os.fstat(directory)
            if info.st_uid != uid or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
                raise AuthorityError("trust ancestry must be owned and not group/world writable")
        descriptor = os.open("trust.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                             dir_fd=directory)
        descriptors.append(descriptor)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022 or
                info.st_nlink != 1 or info.st_size > MAX_JSON_BYTES):
            raise AuthorityError("trust registry must be one owned, bounded, non-writable public file")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65_536, MAX_JSON_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_JSON_BYTES:
                raise AuthorityError("trust registry exceeds the input limit")
        after = os.fstat(descriptor)
        if (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise AuthorityError("trust registry changed during verification")
        value = strict_json_loads(b"".join(chunks))
        if type(value) is not dict:
            raise AuthorityError("trust registry must be an object")
        return value
    except (OSError, ValueError, KeyError) as exc:
        if isinstance(exc, AuthorityError):
            raise
        raise AuthorityError("fixed public trust registry is unavailable or unsafe") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _der_item(data: bytes, offset: int, expected_tag: int) -> tuple[bytes, int]:
    if offset + 2 > len(data) or data[offset] != expected_tag:
        raise AuthorityError("public verification key is not canonical RSA")
    length = data[offset + 1]
    start = offset + 2
    if length & 0x80:
        count = length & 0x7f
        if count == 0 or count > 4 or start + count > len(data) or data[start] == 0:
            raise AuthorityError("public verification key has invalid DER length")
        length = int.from_bytes(data[start:start + count], "big")
        if length < 128:
            raise AuthorityError("public verification key has nonminimal DER length")
        start += count
    end = start + length
    if end > len(data):
        raise AuthorityError("public verification key is truncated")
    return data[start:end], end


def _positive_integer(data: bytes) -> int:
    if not data or data[0] & 0x80 or (len(data) > 1 and data[0] == 0 and not data[1] & 0x80):
        raise AuthorityError("RSA integer is not positive canonical DER")
    value = int.from_bytes(data, "big")
    if value == 0:
        raise AuthorityError("RSA integer cannot be zero")
    return value


def _rsa_public_key(pem: Any) -> tuple[bytes, int]:
    if type(pem) is not str or len(pem) > 16_384:
        raise AuthorityError("only bounded public RSA verification material is accepted")
    match = _PUBLIC_KEY.fullmatch(pem)
    if not match:
        raise AuthorityError("only a PUBLIC KEY PEM block is accepted")
    try:
        der = base64.b64decode(match[1].replace("\n", ""), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AuthorityError("public key encoding is invalid") from exc
    spki, end = _der_item(der, 0, 0x30)
    if end != len(der):
        raise AuthorityError("public verification key has trailing data")
    algorithm, offset = _der_item(spki, 0, 0x30)
    if algorithm != bytes.fromhex("06092a864886f70d0101010500"):
        raise AuthorityError("public verification key must use RSA encryption OID")
    bits, end = _der_item(spki, offset, 0x03)
    if end != len(spki) or not bits or bits[0] != 0:
        raise AuthorityError("public RSA bit string is invalid")
    numbers, end = _der_item(bits[1:], 0, 0x30)
    if end != len(bits) - 1:
        raise AuthorityError("public RSA key has trailing data")
    modulus, offset = _der_item(numbers, 0, 0x02)
    exponent, end = _der_item(numbers, offset, 0x02)
    if end != len(numbers):
        raise AuthorityError("public RSA key has unsupported fields")
    n, e = _positive_integer(modulus), _positive_integer(exponent)
    if n.bit_length() < 2048 or n.bit_length() > 8192 or not n & 1 or e < 65537 or e > 2 ** 32 - 1 or not e & 1:
        raise AuthorityError("RSA verification key must use 2048-8192 bits and a safe public exponent")
    return pem.encode("ascii"), (n.bit_length() + 7) // 8


def _verify_signature(public_key: bytes, signature: bytes, message: bytes) -> None:
    descriptors: list[int] = []
    try:
        executable = Path(OPENSSL)
        info = executable.lstat()
        system_owner = Path("/").lstat().st_uid
        for parent in executable.parents:
            parent_info = parent.lstat()
            if (not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != system_owner or
                    parent_info.st_mode & 0o022):
                raise AuthorityError("fixed OpenSSL verifier ancestry is unavailable or unsafe")
        # Rootless sandboxes can map the system owner to an overflow UID. Pin
        # ownership to the filesystem root instead of assuming it reports UID 0.
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != system_owner or
                info.st_mode & 0o022 or not info.st_mode & 0o111):
            raise AuthorityError("fixed OpenSSL verifier is unavailable or unsafe")
        if not hasattr(os, "memfd_create"):
            raise AuthorityError("memory-only signature verification is unavailable")
        for name, data in (("atlas-public-key", public_key), ("atlas-signature", signature)):
            descriptor = os.memfd_create(name, flags=os.MFD_CLOEXEC)
            descriptors.append(descriptor)
            with os.fdopen(os.dup(descriptor), "wb") as stream:
                stream.write(data)
            os.lseek(descriptor, 0, os.SEEK_SET)
        completed = subprocess.run(
            [OPENSSL, "dgst", "-sha256", "-verify", f"/proc/self/fd/{descriptors[0]}",
             "-signature", f"/proc/self/fd/{descriptors[1]}"],
            input=message, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd="/", env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                          "OPENSSL_CONF": "/dev/null", "OPENSSL_MODULES": "/nonexistent-atlas-openssl-modules"},
            pass_fds=tuple(descriptors), timeout=5, check=False,
        )
        if completed.returncode != 0:
            raise AuthorityError("grant signature verification failed")
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuthorityError("fixed signature verifier failed or exceeded its time limit") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _now_seconds(now: int | float | datetime | None) -> float:
    if now is None:
        result = time.time()
    elif isinstance(now, datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise AuthorityError("verification time must include a timezone")
        result = now.timestamp()
    elif type(now) in (int, float):
        result = now
    else:
        raise AuthorityError("verification time is invalid")
    if not math.isfinite(result) or result < 0:
        raise AuthorityError("verification time is invalid")
    return result


def verify_grant(
    runtime_dir: str | Path, envelope: dict[str, Any] | str | bytes,
    action: str, bindings: dict[str, Any], *, now: int | float | datetime | None = None,
) -> dict[str, Any]:
    """Return an authenticated receipt only for the exact current operation.

    Trust schema 1 pins runtime_dir and policy_sha256 and contains issuer public
    keys, subjects, supported actions and revocation. Signed envelope schema 1
    covers its schema, issuer, algorithm and payload (all fields but signature).
    Payloads bind exactly one action, runtime, policy, validity window and the
    caller's complete typed bindings. No local approval string is accepted.
    """
    if type(action) is not str or action not in ACTIONS:
        raise AuthorityError("requested action is unsupported")
    if type(bindings) is not dict or not bindings:
        raise AuthorityError("exact nonempty operation bindings are required")
    expected_bytes = _canonical_bytes(bindings)
    bindings = strict_json_loads(expected_bytes)
    if type(envelope) in (str, bytes):
        envelope = strict_json_loads(envelope)
    # Copy by strict canonical JSON so mutable caller objects cannot change later.
    signed = strict_json_loads(_canonical_bytes(envelope))
    signed = _object(signed, {"schema", "issuer", "algorithm", "payload", "signature"}, "grant envelope")
    _version(signed["schema"])
    issuer_id = _identifier(signed["issuer"], "issuer")
    if signed["algorithm"] != "rsa-sha256":
        raise AuthorityError("grant algorithm is unsupported")
    payload = _object(signed["payload"], {"schema", "grant_id", "issued_at", "not_before", "expires_at",
                                               "runtime_dir", "policy_sha256", "action", "bindings"}, "grant payload")
    _version(payload["schema"])
    grant_id = _identifier(payload["grant_id"], "grant ID")
    _hash(payload["policy_sha256"], "grant policy")
    for field in ("issued_at", "not_before", "expires_at"):
        if type(payload[field]) is not int or payload[field] < 0:
            raise AuthorityError("grant times must be nonnegative integer Unix seconds")
    issued, start, expiry = (payload[field] for field in ("issued_at", "not_before", "expires_at"))
    current = _now_seconds(now)
    verification_started = time.monotonic()
    if not issued <= start < expiry or expiry - issued > MAX_GRANT_SECONDS:
        raise AuthorityError("grant validity window is invalid or exceeds 24 hours")
    if current < start or current < issued or current >= expiry:
        raise AuthorityError("grant is not currently valid")
    if type(payload["action"]) is not str or payload["action"] != action:
        raise AuthorityError("grant does not authorize the requested action")
    if type(payload["bindings"]) is not dict or _canonical_bytes(payload["bindings"]) != expected_bytes:
        raise AuthorityError("grant does not match exact typed operation bindings")
    runtime = _runtime_directory(runtime_dir)
    if type(payload["runtime_dir"]) is not str or payload["runtime_dir"] != str(runtime):
        raise AuthorityError("grant runtime does not match the explicit runtime")
    if "runtime_dir" in bindings and (type(bindings["runtime_dir"]) is not str or bindings["runtime_dir"] != str(runtime)):
        raise AuthorityError("operation runtime binding does not match the explicit runtime")
    if "policy_sha256" in bindings and bindings["policy_sha256"] != payload["policy_sha256"]:
        raise AuthorityError("operation policy does not match the grant policy")
    registry = _read_trust(runtime)
    _object(registry, {"schema", "runtime_dir", "policy_sha256", "issuers", "revoked_grants"}, "trust registry")
    _version(registry["schema"])
    if type(registry["runtime_dir"]) is not str or registry["runtime_dir"] != str(runtime):
        raise AuthorityError("trust registry is not scoped to this runtime")
    _hash(registry["policy_sha256"], "trusted policy")
    if registry["policy_sha256"] != payload["policy_sha256"]:
        raise AuthorityError("grant policy is not the operator-trusted policy")
    revoked = registry["revoked_grants"]
    if type(revoked) is not list or len(revoked) > 4096:
        raise AuthorityError("grant revocation list is invalid")
    for revoked_id in revoked:
        _identifier(revoked_id, "revoked grant ID")
    if len(set(revoked)) != len(revoked):
        raise AuthorityError("grant revocation list contains duplicates")
    if grant_id in revoked:
        raise AuthorityError("grant has been revoked")
    issuers = registry["issuers"]
    if type(issuers) is not dict or not issuers or len(issuers) > 64:
        raise AuthorityError("trusted issuer registry is invalid")
    keys: dict[str, tuple[bytes, int]] = {}
    key_subjects: dict[str, str] = {}
    for key, issuer in issuers.items():
        _identifier(key, "trusted issuer ID")
        _object(issuer, {"subject", "algorithm", "public_key_pem", "actions", "revoked"}, "trusted issuer")
        if (type(issuer["subject"]) is not str or not issuer["subject"].strip() or
                len(issuer["subject"]) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in issuer["subject"])):
            raise AuthorityError("trusted issuer subject is invalid")
        if issuer["algorithm"] != "rsa-sha256" or type(issuer["revoked"]) is not bool:
            raise AuthorityError("trusted issuer algorithm or revocation state is invalid")
        _action_list(issuer["actions"])
        keys[key] = _rsa_public_key(issuer["public_key_pem"])
        public_identity = hashlib.sha256(base64.b64decode(
            _PUBLIC_KEY.fullmatch(issuer["public_key_pem"])[1].replace("\n", ""), validate=True)).hexdigest()
        if public_identity in key_subjects and key_subjects[public_identity] != issuer["subject"]:
            raise AuthorityError("one verification key cannot represent distinct human subjects")
        key_subjects[public_identity] = issuer["subject"]
    issuer = issuers.get(issuer_id)
    if issuer is None or issuer["revoked"] or action not in issuer["actions"]:
        raise AuthorityError("issuer is unknown, revoked, or lacks the requested action")
    public_key, key_bytes = keys[issuer_id]
    try:
        if type(signed["signature"]) is not str or len(signed["signature"]) > 2048:
            raise AuthorityError("grant signature encoding is invalid")
        signature = base64.b64decode(signed["signature"], validate=True)
    except (ValueError, binascii.Error) as exc:
        if isinstance(exc, AuthorityError):
            raise
        raise AuthorityError("grant signature encoding is invalid") from exc
    if len(signature) != key_bytes:
        raise AuthorityError("grant signature size does not match the trusted RSA key")
    if base64.b64encode(signature).decode("ascii") != signed["signature"]:
        raise AuthorityError("grant signature must use canonical base64 encoding")
    message = _canonical_bytes({key: value for key, value in signed.items() if key != "signature"})
    _verify_signature(public_key, signature, message)
    # Do not publish a receipt for trust that was rotated/revoked during the
    # bounded verifier subprocess, or a grant that expired while it ran.
    if canonical_digest(_read_trust(runtime)) != canonical_digest(registry):
        raise AuthorityError("operator trust changed during signature verification")
    # Callers usually supply their clock's numeric value. Reusing that frozen
    # number alone would overlook expiry while OpenSSL runs. Monotonic elapsed
    # time protects both injected clocks and real wall clocks moving backwards.
    elapsed = max(0.0, time.monotonic() - verification_started)
    if max(_now_seconds(now), current + elapsed) >= expiry:
        raise AuthorityError("grant expired during signature verification")
    return {
        "schema": 1, "verified": True, "issuer": issuer_id, "subject": issuer["subject"],
        "grant_id": grant_id, "action": action, "runtime_dir": str(runtime),
        "policy_sha256": payload["policy_sha256"], "bindings_sha256": hashlib.sha256(expected_bytes).hexdigest(),
        "grant_sha256": canonical_digest(signed), "trust_sha256": canonical_digest(registry),
        "expires_at": expiry,
    }
