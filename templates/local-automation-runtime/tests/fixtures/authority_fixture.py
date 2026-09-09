"""Synthetic test authority; never import from production runtime code.

OpenSSL creates a disposable test key in memory. Private material is never
printed or written to a filesystem file. Only public trust and signed envelopes
are fixture outputs. No user key, credential, or production trust is accessed.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
from typing import Any


TEST_POLICY = "d" * 64
TEST_NOW = 1_800_000_000
TEST_ACTIONS = ["local_execute", "draft_pr", "board_write", "assess", "human_gate"]
_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "OPENSSL_CONF": "/dev/null",
        "OPENSSL_MODULES": "/nonexistent-atlas-openssl-modules"}


def canonical_bytes(value: Any) -> bytes:
    # Independent fixture serializer: do not let a production hashing regression
    # silently change both the signed test message and its verification oracle.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _run(argv: list[str], *, data: bytes | None = None, descriptors: tuple[int, ...] = ()) -> bytes:
    completed = subprocess.run(["/usr/bin/openssl", *argv], input=data, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, env=_ENV, cwd="/", pass_fds=descriptors,
                               timeout=15, check=False)
    if completed.returncode != 0:
        raise RuntimeError("synthetic in-memory authority fixture failed")
    return completed.stdout


@lru_cache(maxsize=3)
def _ephemeral_material(kind: str = "RSA", bits: int = 2048) -> tuple[bytes, str]:
    if kind == "RSA":
        private = _run(["genpkey", "-algorithm", "RSA", "-pkeyopt", f"rsa_keygen_bits:{bits}"])
    elif kind == "EC":
        private = _run(["genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256"])
    else:
        raise ValueError("unsupported synthetic fixture key type")
    public = _run(["pkey", "-pubout"], data=private).decode("ascii")
    return private, public


def public_key(*, kind: str = "RSA", bits: int = 2048) -> str:
    return _ephemeral_material(kind, bits)[1]


def _sign(message: bytes) -> str:
    descriptor = os.memfd_create("atlas-synthetic-test-signer", flags=os.MFD_CLOEXEC)
    try:
        with os.fdopen(os.dup(descriptor), "wb") as stream:
            stream.write(_ephemeral_material("RSA", 2048)[0])
        os.lseek(descriptor, 0, os.SEEK_SET)
        signature = _run(["dgst", "-sha256", "-sign", f"/proc/self/fd/{descriptor}"],
                         data=message, descriptors=(descriptor,))
        return base64.b64encode(signature).decode("ascii")
    finally:
        os.close(descriptor)


class AuthorityFixture:
    def __init__(self, runtime: Path, *, policy_sha256: str = TEST_POLICY,
                 subject: str = "operator", now: int = TEST_NOW):
        self.runtime = Path(runtime)
        self.now = now
        self.registry = {
            "schema": 1, "runtime_dir": str(self.runtime), "policy_sha256": policy_sha256,
            "issuers": {"test-operator": {"subject": subject, "algorithm": "rsa-sha256",
                        "public_key_pem": public_key(), "actions": list(TEST_ACTIONS), "revoked": False}},
            "revoked_grants": [],
        }
        self.write_trust()

    def write_trust(self) -> None:
        directory = self.runtime / "authority"
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
        path = directory / "trust.json"
        path.write_text(json.dumps(self.registry, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)

    def update_trust(self) -> None:
        path = self.runtime / "authority" / "trust.json"
        path.write_text(json.dumps(self.registry, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def grant(self, action: str, bindings: dict[str, Any], **payload_overrides: Any) -> dict[str, Any]:
        envelope: dict[str, Any] = {
            "schema": 1, "issuer": "test-operator", "algorithm": "rsa-sha256",
            "payload": {"schema": 1, "grant_id": "synthetic-test-grant", "issued_at": self.now - 60,
                        "not_before": self.now - 30, "expires_at": self.now + 3600,
                        "runtime_dir": str(self.runtime), "policy_sha256": self.registry["policy_sha256"],
                        "action": action, "bindings": deepcopy(bindings)},
        }
        envelope["payload"].update(payload_overrides)
        envelope["signature"] = _sign(canonical_bytes(envelope))
        return envelope


def sign_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    signed = deepcopy(envelope)
    signed.pop("signature", None)
    signed["signature"] = _sign(canonical_bytes(signed))
    return signed
