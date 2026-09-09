"""Readable local approval requests, verified import, and a protected issuer bridge.

Previews are pure. Preparing a card/export is a local write, never approval.
Only an explicitly invoked operator adapter may contact its configured issuer;
the signed response is always checked by the existing authority verifier.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import html
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
from typing import Any

from atlas_authority import (ACTIONS, AuthorityError, canonical_digest, strict_json_loads,
                             verify_grant, _runtime_directory, _read_trust)
from atlas_human_gates import gate_bindings, validate_gates
from atlas_runtime_config import load_runtime_config, validate_input_path


MAX_BYTES = 262_144
MAX_HISTORY = 32
ACCEPTED_OPERATION = "Approve the exact requested operation."
HEX = re.compile(r"[a-f0-9]{64}\Z")
ISSUE = re.compile(r"azdo:([^:\s/]+):([^:\s/]+):[1-9][0-9]*\Z")
URL = re.compile(r"https://dev\.azure\.com/([^/?#:@\s%]+)/([^/?#:@\s%]+)/_git/[^/?#:@\s%]+\Z")
ISSUER_FLAG = "--atlas-approval-stdio-v1"


class ApprovalError(ValueError):
    pass


def _copy(value: Any) -> Any:
    return strict_json_loads(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))


def _text(value: Any, field: str, maximum: int = 4000) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ApprovalError(f"{field} must be bounded nonempty text")
    return value


def _sha(value: Any, field: str) -> str:
    if type(value) is not str or not HEX.fullmatch(value):
        raise ApprovalError(f"{field} requires a canonical SHA-256 digest")
    return value


def _now(value: Any = None) -> int:
    result = time.time() if value is None else value
    if type(result) not in (int, float) or not 0 <= result <= 2 ** 53:
        raise ApprovalError("request time must be a finite nonnegative epoch")
    return int(result)


def validate_request(request: Any) -> dict[str, Any]:
    value = _copy(request)
    required = {"schema_version", "repository_url", "issue_id", "issue_revision", "action", "owner", "question",
                "artifact_sha256", "policy_sha256", "bindings"}
    optional = {"step_id", "human_gate", "details", "artifact_path"}
    if type(value) is not dict or not required.issubset(value) or set(value) - required - optional:
        raise ApprovalError("approval request has missing or unsupported fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ApprovalError("unsupported approval request schema")
    repository = URL.fullmatch(value["repository_url"]) if type(value["repository_url"]) is str else None
    issue = ISSUE.fullmatch(value["issue_id"]) if type(value["issue_id"]) is str else None
    if repository is None or issue is None or repository.groups()[:2] != issue.groups():
        raise ApprovalError("request repository and native Azure issue namespace must match")
    if type(value["issue_revision"]) is not int or value["issue_revision"] < 1:
        raise ApprovalError("request needs the exact positive issue revision")
    if type(value["action"]) is not str or value["action"] not in ACTIONS:
        raise ApprovalError("request action is outside the supported authority boundary")
    _text(value["owner"], "request owner", 256)
    _text(value["question"], "review question", 16000)
    _sha(value["artifact_sha256"], "review artifact")
    _sha(value["policy_sha256"], "governing policy")
    value.setdefault("step_id", value["action"])
    _text(value["step_id"], "logical step", 120)
    if "details" in value and type(value["details"]) is not dict:
        raise ApprovalError("readable review details must be a JSON object")
    if "artifact_path" in value:
        _text(value["artifact_path"], "artifact reference", 2000)
    if value["action"] == "human_gate":
        subject = value.get("human_gate")
        if type(subject) is not dict or set(subject) != {"gate", "context"} or value["bindings"] is not None:
            raise ApprovalError("human request requires one exact gate/context and response-derived bindings")
        validate_gates([subject["gate"]])
        gate = subject["gate"]
        for key, expected in (("issue_id", value["issue_id"]), ("issue_revision", value["issue_revision"]),
                              ("owner", value["owner"]), ("question", value["question"]), ("artifact_sha256", value["artifact_sha256"])):
            if type(gate.get(key)) is not type(expected) or gate[key] != expected:
                raise ApprovalError("human request must preserve the original gate subject")
        probe = {"gate_id": gate["id"], "decision": "accepted", "response": "Response pending.", "grant": {}}
        bindings = gate_bindings(gate, probe, subject["context"])
        if bindings.get("policy_sha256") != value["policy_sha256"]:
            raise ApprovalError("human context must bind the request's governing policy")
    else:
        if "human_gate" in value or type(value["bindings"]) is not dict or not value["bindings"]:
            raise ApprovalError("operation request requires exact nonempty operation bindings")
        bindings = value["bindings"]
        for field, expected in (("repository_url", value["repository_url"]), ("policy_sha256", value["policy_sha256"]),
                                ("issue_id", value["issue_id"]), ("issue_revision", value["issue_revision"])):
            if field in bindings and (type(bindings[field]) is not type(expected) or bindings[field] != expected):
                raise ApprovalError("operation bindings contradict the readable request")
    canonical_digest(value)
    return value


def make_request(**fields: Any) -> dict[str, Any]:
    return validate_request({"schema_version": 1, **fields})


def request_identity(request: dict[str, Any]) -> tuple[str, str]:
    request = validate_request(request)
    subject = {key: request[key] for key in ("repository_url", "issue_id", "action", "step_id")}
    if request["action"] == "human_gate":
        subject["gate_id"] = request["human_gate"]["gate"]["id"]
    return canonical_digest(subject), canonical_digest(request)


def render_review(card: dict[str, Any]) -> tuple[str, str]:
    request = card["request"]
    lines = ["Approval request", "", request["question"], "", f"Owner: {request['owner']}",
             f"Repository: {request['repository_url']}", f"Issue: {request['issue_id']} (revision {request['issue_revision']})",
             f"Action: {request['action']}", f"Request revision: {card['revision']}",
             f"Material digest: {card['material_sha256']}", f"Policy: {request['policy_sha256']}",
             f"Review artifact SHA-256: {request['artifact_sha256']}"]
    if request.get("artifact_path"):
        lines.append("Review artifact: " + request["artifact_path"])
    lines += ["", "Reading this card or choosing a local option grants no authority.",
              "The configured external issuer must authenticate the owner and approve the exact subject.",
              "", "Review details:", json.dumps(request.get("details", {}), sort_keys=True, indent=2, ensure_ascii=False),
              "", "Exact operation subject:", json.dumps(request.get("human_gate") or request["bindings"], sort_keys=True, indent=2, ensure_ascii=False)]
    text = "\n".join(lines) + "\n"
    document = ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
                "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
                "<meta name=\"referrer\" content=\"no-referrer\"><title>Review an exact Azure operation</title>"
                "<style>body{font:16px system-ui;max-width:900px;margin:3rem auto;padding:0 1rem;color:#182230}"
                "pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.5}</style>"
                "<h1>Review an exact Azure operation</h1><pre>" + html.escape(text, quote=True) + "</pre></html>")
    return text, document


def _safe_file(path: Path, runtime: Path) -> None:
    if path == runtime or runtime not in path.parents:
        raise ApprovalError("approval path leaves the explicit runtime")
    for current in reversed(path.parents):
        if current == runtime or runtime in current.parents:
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ApprovalError("approval ancestry must be owned, protected directories without symlinks")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022 or info.st_nlink != 1 or info.st_size > MAX_BYTES:
        raise ApprovalError("approval input must be a bounded protected regular file")


def _read(path: Path, runtime: Path) -> dict[str, Any]:
    _safe_file(path, runtime)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_nlink != 1:
            raise ApprovalError("approval file changed before reading")
        raw = os.read(descriptor, MAX_BYTES + 1)
    finally:
        os.close(descriptor)
    result = strict_json_loads(raw)
    if type(result) is not dict:
        raise ApprovalError("approval document must be a JSON object")
    return result


def _atomic(path: Path, value: dict[str, Any] | str, runtime: Path) -> None:
    raw = value.encode("utf-8") if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ApprovalError("approval artifact exceeds the bounded size")
    if path.exists() or path.is_symlink():
        _safe_file(path, runtime)
    temporary = path.with_name(path.name + ".tmp-" + os.urandom(8).hex())
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


class ApprovalInbox:
    def __init__(self, runtime_dir: str | Path):
        self.runtime = Path(runtime_dir)
        self.root = self.runtime / "approval-inbox"

    def preview(self, request: dict[str, Any]) -> dict[str, Any]:
        request = validate_request(request)
        identifier, material = request_identity(request)
        card = {"schema_version": 1, "request_id": identifier, "revision": None, "material_sha256": material,
                "request": request, "status": "preview", "inert": True, "effects": [], "completion": False}
        card["review_text"], _ = render_review(card)
        return card

    @contextmanager
    def _locked(self):
        _runtime_directory(self.runtime)
        if not self.root.exists() and not self.root.is_symlink():
            self.root.mkdir(mode=0o700)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ApprovalError("approval inbox must be an owned protected directory")
        lock = self.root / "inbox.lock"
        if lock.exists() or lock.is_symlink():
            _safe_file(lock, self.runtime)
        descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022 or info.st_nlink != 1:
                raise ApprovalError("approval lock is unsafe")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ApprovalError("another approval operation holds the inbox") from exc
            yield
        finally:
            os.close(descriptor)

    def _card(self, identifier: str) -> dict[str, Any] | None:
        _sha(identifier, "request ID")
        _runtime_directory(self.runtime)
        path = self.root / (identifier + ".json")
        if not path.exists() and not path.is_symlink():
            return None
        card = _read(path, self.runtime)
        required = {"schema_version", "request_id", "revision", "material_sha256", "request", "created_at", "updated_at", "response", "history"}
        if set(card) != required or type(card["schema_version"]) is not int or card["schema_version"] != 1:
            raise ApprovalError("stored approval card has an unsupported schema")
        expected_id, material = request_identity(card["request"])
        if expected_id != identifier or card["request_id"] != identifier or card["material_sha256"] != material:
            raise ApprovalError("stored request subject was altered")
        if type(card["revision"]) is not int or not 1 <= card["revision"] <= 1_000_000 or type(card["history"]) is not list or len(card["history"]) > MAX_HISTORY:
            raise ApprovalError("stored request revision/history is invalid")
        for field in ("created_at", "updated_at"):
            if type(card[field]) is not int or card[field] < 0:
                raise ApprovalError("stored request timestamp is invalid")
        return card

    def request(self, identifier: str) -> dict[str, Any]:
        card = self._card(identifier)
        if card is None:
            raise ApprovalError("approval request is not present")
        return _copy(card["request"])

    def _grant_id(self, card: dict[str, Any]) -> str:
        return "approval-" + card["material_sha256"] + "-r" + str(card["revision"])

    def _report(self, card: dict[str, Any], *, status: str = "pending") -> dict[str, Any]:
        result = _copy(card)
        result.pop("response", None)
        result.update(status=status, completion=False, grant_id=self._grant_id(card),
                      artifacts={kind: str(self.root / (card["request_id"] + suffix)) for kind, suffix in
                                 (("request", ".json"), ("html", ".html"), ("text", ".txt"))})
        return result

    def prepare(self, request: dict[str, Any], *, now: Any = None) -> dict[str, Any]:
        request = validate_request(request)
        identifier, material = request_identity(request)
        with self._locked():
            previous = self._card(identifier)
            if previous and previous["material_sha256"] == material:
                card = previous
            else:
                history = list(previous["history"]) if previous else []
                if previous:
                    history.append({"revision": previous["revision"], "material_sha256": previous["material_sha256"],
                                    "response_sha256": canonical_digest(previous["response"]) if previous["response"] else None})
                if len(history) > MAX_HISTORY:
                    raise ApprovalError("request revision history needs operator archival")
                card = {"schema_version": 1, "request_id": identifier, "revision": previous["revision"] + 1 if previous else 1,
                        "material_sha256": material, "request": request, "created_at": _now(now), "updated_at": _now(now),
                        "response": None, "history": history}
                _atomic(self.root / (identifier + ".json"), card, self.runtime)
            text, document = render_review(card)
            # A repeated unchanged observation does not rewrite its artifacts.
            for suffix, content in ((".txt", text), (".html", document)):
                path = self.root / (identifier + suffix)
                if path.exists() or path.is_symlink():
                    _safe_file(path, self.runtime)
                    if path.read_text(encoding="utf-8") == content:
                        continue
                _atomic(path, content, self.runtime)
            return self._report(card)

    def _current(self, request: dict[str, Any]) -> dict[str, Any]:
        identifier, material = request_identity(request)
        card = self._card(identifier)
        if card is None:
            raise ApprovalError("prepare the readable request before exporting or importing approval")
        if card["material_sha256"] != material:
            raise ApprovalError("request has been superseded by materially changed bindings")
        return card

    def reopen(self, request: dict[str, Any], *, now: Any = None) -> dict[str, Any]:
        """Explicit operator renewal after a reconciled response, never automatic retry.

        A previously imported expired response establishes issuer reconciliation,
        not current execution authority. Verify it at its recorded import time
        against current trust (including revocations), then retire it and require
        a newly signed grant for the new readable revision.
        """
        with self._locked():
            previous = self._current(request)
            response = previous["response"]
            if response is None:
                raise ApprovalError("reconcile a signed issuer response before reopening this request")
            self._verify_response(previous, response, now=previous["updated_at"])
            intent = self.root / (previous["request_id"] + ".issuer-intent.json")
            if intent.exists() or intent.is_symlink():
                attempted = _read(intent, self.runtime)
                exported = self.export_request(request, decision=response["decision"], response_text=response["response"])
                if attempted.get("export_sha256") != canonical_digest(exported):
                    raise ApprovalError("the latest issuer attempt is still uncertain; reconcile its exact response")
            history = [*previous["history"], {"revision": previous["revision"], "material_sha256": previous["material_sha256"],
                                            "response_sha256": canonical_digest(response)}]
            if len(history) > MAX_HISTORY:
                raise ApprovalError("request revision history needs operator archival")
            card = {**previous, "revision": previous["revision"] + 1, "response": None, "history": history,
                    "created_at": _now(now), "updated_at": _now(now)}
            _atomic(self.root / (card["request_id"] + ".json"), card, self.runtime)
            text, document = render_review(card)
            for suffix, content in ((".txt", text), (".html", document)):
                _atomic(self.root / (card["request_id"] + suffix), content, self.runtime)
            return self._report(card)

    def export_request(self, request: dict[str, Any], *, decision: str = "accepted", response_text: str | None = None,
                       write: bool = False) -> dict[str, Any]:
        card = self._current(request)
        request = card["request"]
        if type(decision) is not str or decision not in {"accepted", "rejected", "feedback"}:
            raise ApprovalError("review decision must be accepted, rejected or feedback")
        if request["action"] == "human_gate":
            response = _text(response_text, "human response", 16000)
            subject = request["human_gate"]
            receipt = {"gate_id": subject["gate"]["id"], "decision": decision, "response": response, "grant": {}}
            action = "human_gate"
            bindings = gate_bindings(subject["gate"], receipt, subject["context"])
        elif decision == "accepted":
            if response_text is not None and response_text != ACCEPTED_OPERATION:
                raise ApprovalError("operation approval uses the exact displayed subject; feedback needs its own decision")
            response, action, bindings = ACCEPTED_OPERATION, request["action"], request["bindings"]
        else:
            response = _text(response_text, "review feedback", 16000)
            action = "human_gate"
            bindings = {"request_id": card["request_id"], "request_revision": card["revision"],
                        "request_material_sha256": card["material_sha256"], "requested_action": request["action"],
                        "operation_bindings_sha256": canonical_digest(request["bindings"]),
                        "decision": decision, "response_sha256": canonical_digest(response),
                        "policy_sha256": request["policy_sha256"]}
        result = {"schema_version": 1, "request_id": card["request_id"], "request_revision": card["revision"],
                  "material_sha256": card["material_sha256"], "owner": request["owner"], "review": request,
                  "decision": decision, "response": response,
                  "signing_subject": {"grant_id": self._grant_id(card), "runtime_dir": str(self.runtime),
                                      "policy_sha256": request["policy_sha256"], "action": action, "bindings": bindings},
                  "authority": "unsigned request; external authenticated issuer consent is required"}
        if write:
            with self._locked():
                if self._current(request)["revision"] != card["revision"]:
                    raise ApprovalError("request changed during review export")
                _atomic(self.root / (card["request_id"] + ".export.json"), result, self.runtime)
        return result

    def _verify_response(self, card: dict[str, Any], response: Any, *, now: Any = None) -> dict[str, Any]:
        response = _copy(response)
        required = {"schema_version", "request_id", "request_revision", "material_sha256", "decision", "response", "grant"}
        if type(response) is not dict or set(response) != required or type(response["schema_version"]) is not int or response["schema_version"] != 1:
            raise ApprovalError("issuer response has missing or unsupported fields")
        expected = {"request_id": card["request_id"], "request_revision": card["revision"], "material_sha256": card["material_sha256"]}
        if any(type(response[key]) is not type(value) or response[key] != value for key, value in expected.items()):
            raise ApprovalError("issuer response belongs to a superseded request revision")
        exported = self.export_request(card["request"], decision=response["decision"], response_text=response["response"])
        subject = exported["signing_subject"]
        grant = response["grant"]
        if type(grant) is not dict or type(grant.get("payload")) is not dict or grant["payload"].get("grant_id") != subject["grant_id"]:
            raise ApprovalError("signed grant does not bind this exact readable request revision")
        receipt = verify_grant(self.runtime, grant, subject["action"], subject["bindings"], now=now)
        if receipt["subject"] != card["request"]["owner"] or receipt["policy_sha256"] != card["request"]["policy_sha256"]:
            raise ApprovalError("verified issuer subject or policy differs from the required owner")
        result = {"status": response["decision"], **expected, "verified": True, "completion": False}
        if card["request"]["action"] == "human_gate":
            result["human_receipt"] = {"gate_id": card["request"]["human_gate"]["gate"]["id"],
                                       "decision": response["decision"], "response": response["response"], "grant": grant}
        elif response["decision"] == "accepted":
            result["grant"] = grant
        result["response_sha256"] = canonical_digest(response)
        result["verified_subject"] = receipt["subject"]
        return result

    def find_response(self, request: dict[str, Any], *, now: Any = None) -> dict[str, Any]:
        identifier, material = request_identity(request)
        card = self._card(identifier)
        if card is None:
            return {"status": "pending", "request_id": identifier, "verified": False, "completion": False}
        if card["material_sha256"] != material:
            return {"status": "superseded", "request_id": identifier, "revision": card["revision"], "verified": False, "completion": False}
        if card["response"] is None:
            return {"status": "pending", "request_id": identifier, "revision": card["revision"], "verified": False, "completion": False}
        try:
            return self._verify_response(card, card["response"], now=now)
        except (AuthorityError, ApprovalError, ValueError, OSError):
            return {"status": "invalid", "request_id": identifier, "revision": card["revision"], "verified": False, "completion": False}

    def import_response(self, request: dict[str, Any], response: dict[str, Any], *, now: Any = None) -> dict[str, Any]:
        # Verify before creating a lock or any import state.
        card = self._current(request)
        result = self._verify_response(card, response, now=now)
        with self._locked():
            current = self._current(request)
            if current["revision"] != card["revision"]:
                raise ApprovalError("request changed during response verification")
            result = self._verify_response(current, response, now=now)
            if current["response"] is not None:
                if canonical_digest(current["response"]) == canonical_digest(response):
                    return {**result, "duplicate": True}
                if (current["response"].get("decision"), current["response"].get("response")) != (response["decision"], response["response"]):
                    raise ApprovalError("conflicting response requires a new reviewed request revision")
            current.update(response=_copy(response), updated_at=_now(now))
            _atomic(self.root / (current["request_id"] + ".json"), current, self.runtime)
            return {**result, "duplicate": False}

    def issuer_status(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            profile = _issuer_profile(self.runtime, self._current(request)["request"])
            if request["action"] not in profile["actions"]:
                raise ApprovalError("issuer is not enrolled for this operation")
            return {"ready": True, "issuer": profile["issuer"], "executable_sha256": profile["executable_sha256"]}
        except (ApprovalError, AuthorityError, OSError, ValueError):
            return {"ready": False, "reason": "operator must enroll a protected external issuer profile and public trust"}

    def operator_issue(self, request: dict[str, Any], *, decision: str = "accepted", response_text: str | None = None,
                       now: Any = None) -> dict[str, Any]:
        """Explicit operator entry only; never called by supervisor or preview."""
        exported = self.export_request(request, decision=decision, response_text=response_text)
        profile = _issuer_profile(self.runtime, exported["review"])
        if exported["signing_subject"]["action"] not in profile["actions"]:
            raise ApprovalError("enrolled issuer lacks the requested response action")
        with self._locked():
            card = self._current(request)
            if card["revision"] != exported["request_revision"]:
                raise ApprovalError("request changed before issuer invocation")
            if card["response"] is not None:
                raise ApprovalError("issuer request was already attempted or answered; explicitly reopen the reconciled review")
            intent = self.root / (card["request_id"] + ".issuer-intent.json")
            if intent.exists() or intent.is_symlink():
                previous = _read(intent, self.runtime)
                if previous.get("request_revision") == card["revision"]:
                    raise ApprovalError("issuer request was already attempted; import/reconcile its response before retrying")
            _atomic(intent, {"schema_version": 1, "export_sha256": canonical_digest(exported),
                             "request_id": card["request_id"], "request_revision": card["revision"], "state": "attempted"}, self.runtime)
        # The external adapter owns authentication and consent. This runtime
        # sends a non-secret review subject and accepts only signed JSON back.
        response = _invoke_issuer(profile, exported)
        return self.import_response(request, response, now=now)


def _issuer_profile(runtime: Path, request: dict[str, Any]) -> dict[str, Any]:
    _runtime_directory(runtime)
    profile = _read(runtime / "authority" / "issuer.json", runtime)
    fields = {"schema_version", "enabled", "issuer", "executable", "executable_sha256", "timeout_seconds", "actions"}
    if set(profile) != fields or type(profile["schema_version"]) is not int or profile["schema_version"] != 1 or profile["enabled"] is not True:
        raise ApprovalError("external issuer profile is disabled or malformed")
    if type(profile["timeout_seconds"]) is not int or not 1 <= profile["timeout_seconds"] <= 60:
        raise ApprovalError("issuer timeout must be explicitly bounded to at most 60 seconds")
    if type(profile["actions"]) is not list or not profile["actions"] or any(type(action) is not str or action not in ACTIONS for action in profile["actions"]) or len(set(profile["actions"])) != len(profile["actions"]):
        raise ApprovalError("issuer actions must be explicit supported operations")
    _sha(profile["executable_sha256"], "issuer executable pin")
    _text(profile["issuer"], "issuer ID", 128)
    _text(profile["executable"], "issuer executable", 2000)
    executable = Path(profile["executable"])
    if not executable.is_absolute() or ".." in executable.parts or any(part in {"worktrees", ".git"} for part in executable.parts):
        raise ApprovalError("issuer executable must be an absolute protected path outside worktrees")
    identity_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    system_owner = Path("/").lstat().st_uid
    inside_home = identity_home in executable.parents
    if inside_home:
        _runtime_directory(executable.parent)
        ancestry = [path for path in (executable, *executable.parents) if path == identity_home or identity_home in path.parents]
    else:
        # Never inspect an executable inside another identity's home.
        if executable.parts[:2] == ("/", "home") or executable.parts[:2] == ("/", "root"):
            raise ApprovalError("issuer executable belongs to another identity")
        ancestry = (executable, *executable.parents)
    # Reject a parent symlink before inspecting any descendant that it could
    # redirect into another identity's directory.
    for path in reversed(ancestry):
        info = path.lstat()
        expected = stat.S_ISREG if path == executable else stat.S_ISDIR
        expected_owner = os.getuid() if inside_home else system_owner
        if not expected(info.st_mode) or info.st_uid != expected_owner or info.st_mode & 0o022:
            raise ApprovalError("issuer executable ancestry is unsafe or writable by another identity")
        if path != executable:
            try:
                (path / ".git").lstat()
            except FileNotFoundError:
                pass
            else:
                raise ApprovalError("issuer executable cannot reside in a source checkout")
    info = executable.stat()
    if not info.st_mode & 0o111 or info.st_size > 32 * 1024 * 1024 or info.st_nlink != 1:
        raise ApprovalError("issuer executable must be a bounded protected executable file")
    if hashlib.sha256(executable.read_bytes()).hexdigest() != profile["executable_sha256"]:
        raise ApprovalError("issuer executable differs from the operator-enrolled pin")
    trust = _read_trust(runtime)
    issuer = trust.get("issuers", {}).get(profile["issuer"]) if type(trust.get("issuers")) is dict else None
    if (trust.get("runtime_dir") != str(runtime) or trust.get("policy_sha256") != request["policy_sha256"] or
            type(issuer) is not dict or issuer.get("revoked") is not False or issuer.get("subject") != request["owner"] or
            any(action not in issuer.get("actions", []) for action in profile["actions"])):
        raise ApprovalError("issuer profile is not enrolled for the requested owner, runtime, policy and actions")
    return profile


def _invoke_issuer(profile: dict[str, Any], exported: dict[str, Any]) -> dict[str, Any]:
    """Bounded stdio protocol; no shell, inherited credentials, or raw diagnostics."""
    executable = Path(profile["executable"])
    descriptor = os.open(executable, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    process = None
    selector = selectors.DefaultSelector()
    try:
        info = os.fstat(descriptor)
        identity_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        expected_owner = os.getuid() if identity_home in executable.parents else Path("/").lstat().st_uid
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != expected_owner or info.st_mode & 0o022 or
                not info.st_mode & 0o111 or info.st_nlink != 1 or info.st_size > 32 * 1024 * 1024):
            raise ApprovalError("issuer executable changed before invocation")
        content = os.read(descriptor, 32 * 1024 * 1024 + 1)
        if hashlib.sha256(content).hexdigest() != profile["executable_sha256"]:
            raise ApprovalError("issuer executable pin changed before invocation")
        os.lseek(descriptor, 0, os.SEEK_SET)
        process = subprocess.Popen([f"/proc/self/fd/{descriptor}", ISSUER_FLAG], executable=f"/proc/self/fd/{descriptor}",
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "PYTHONNOUSERSITE": "1"},
                                   cwd="/", pass_fds=(descriptor,), start_new_session=True)
        message = json.dumps(exported, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE)
        selector.register(process.stdout, selectors.EVENT_READ)
        sent, output, eof = 0, bytearray(), False
        deadline = time.monotonic() + profile["timeout_seconds"]
        while not eof or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ApprovalError("issuer adapter timed out; reconcile the uncertain request")
            for key, _ in selector.select(min(remaining, 0.1)):
                if key.fileobj is process.stdin:
                    try:
                        sent += os.write(process.stdin.fileno(), message[sent:sent + 65536])
                    except BrokenPipeError:
                        raise ApprovalError("issuer adapter closed its request channel") from None
                    if sent == len(message):
                        selector.unregister(process.stdin)
                        process.stdin.close()
                else:
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        selector.unregister(process.stdout)
                        eof = True
                    output.extend(chunk)
                    if len(output) > MAX_BYTES:
                        raise ApprovalError("issuer returned excessive output; reconcile the uncertain request")
        if process.returncode != 0:
            raise ApprovalError("issuer adapter failed; no response was accepted")
        result = strict_json_loads(bytes(output))
        if type(result) is not dict:
            raise ApprovalError("issuer response must be a signed JSON object")
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        raise ApprovalError("protected issuer adapter could not complete") from exc
    finally:
        selector.close()
        if process is not None:
            # A parent that exits while descendants retain stdout must not leave
            # an unbounded background issuer invocation behind.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        os.close(descriptor)


def read_input(path: str | Path) -> dict[str, Any]:
    source = validate_input_path(path)
    if source.stat().st_size > MAX_BYTES:
        raise ApprovalError("approval input exceeds its size limit")
    value = strict_json_loads(source.read_bytes())
    if type(value) is not dict:
        raise ApprovalError("approval input must be a JSON object")
    return value


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--runtime-dir", required=True)
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--request")
    subject.add_argument("--request-id")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--reopen", action="store_true")
    mode.add_argument("--export", action="store_true")
    mode.add_argument("--import-response")
    mode.add_argument("--operator-issue", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--decision", choices=("accepted", "rejected", "feedback"), default="accepted")
    response = parser.add_mutually_exclusive_group()
    response.add_argument("--response-text")
    response.add_argument("--response-file")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        config = load_runtime_config(args.config, runtime_dir=args.runtime_dir)
        if config.provider != "azure-devops":
            raise ApprovalError("Azure approval requires an explicit Azure provider")
        inbox = ApprovalInbox(config.runtime_dir)
        request = read_input(args.request) if args.request else inbox.request(args.request_id)
        request = validate_request(request)
        if request["repository_url"] != config.repository["url"]:
            raise ApprovalError("request repository differs from the explicit provider configuration")
        if not any((args.prepare, args.reopen, args.export, args.import_response, args.operator_issue)):
            result = inbox.preview(request)
        elif args.prepare:
            result = inbox.prepare(request)
        elif args.reopen:
            result = inbox.reopen(request)
        elif args.import_response:
            result = inbox.import_response(request, read_input(args.import_response))
        else:
            response = args.response_text
            if args.response_file:
                source = validate_input_path(args.response_file)
                if source.stat().st_size > 16000:
                    raise ApprovalError("human response exceeds the plain-text limit")
                response = source.read_text(encoding="utf-8")
            if args.operator_issue:
                result = inbox.operator_issue(request, decision=args.decision, response_text=response)
            else:
                result = inbox.export_request(request, decision=args.decision, response_text=response, write=True)
        identifier = result.get("request_id")
        if identifier:
            base = [str(Path(__file__).with_name("atlas-agent-azure-approval")), "--config", config.source,
                    "--runtime-dir", str(config.runtime_dir), "--request-id", identifier]
            response_file = str(inbox.root / (identifier + ".answer.txt"))
            decision_args = ["--decision", args.decision] if args.decision != "accepted" else []
            if args.response_file:
                answer_args = ["--response-file", args.response_file]
            elif args.response_text is not None:
                answer_args = ["--response-text", args.response_text]
            else:
                answer_args = ["--response-file", response_file] if request["action"] == "human_gate" or args.decision != "accepted" else []
            result["operator_commands"] = {
                "export": [*base, "--export", *decision_args, *answer_args],
                "import": [*base, "--import-response", str(inbox.root / (identifier + ".response.json"))],
                "request_external_approval": [*base, "--operator-issue", *decision_args, *answer_args],
                "reopen_after_reconciled_response": [*base, "--reopen"],
            }
            if answer_args and answer_args[0] == "--response-file":
                result["plain_text_answer_file"] = answer_args[1]
        print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        print(json.dumps({"error": "approval request, protected issuer or signed response failed validation", "completion": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
