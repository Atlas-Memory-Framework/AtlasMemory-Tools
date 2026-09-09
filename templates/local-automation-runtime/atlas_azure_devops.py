#!/usr/bin/env python3
"""Credential-free projections and capability-limited Azure DevOps REST access.

No object construction, offline projection, or preview creates runtime state.
Only an actual REST request enters the same-identity, process-shared throttle.
Writes are attempted once: the caller must reconcile their result before retrying.
"""

from __future__ import annotations

import contextlib
import copy
import email.utils
import fcntl
import hashlib
import http.client
import json
import math
import os
import pathlib
import pwd
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


API_VERSION = "7.1"
PREDECESSOR = "System.LinkTypes.Dependency-Reverse"
SUCCESSOR = "System.LinkTypes.Dependency-Forward"
CAPABILITIES = frozenset({"read", "local_execute", "draft_pr", "board_write"})
STATE_CATEGORIES = {
    "To Do": "pending", "New": "pending", "Proposed": "pending",
    "Approved": "pending", "Committed": "active", "Doing": "active",
    "Active": "active", "In Progress": "active", "Resolved": "active",
    "Done": "completed", "Closed": "completed", "Completed": "completed",
    "Removed": "removed", "Cancelled": "removed",
}


def timestamp(now: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_timestamp(value: Any) -> float | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.timestamp() if result.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class AzureError(RuntimeError):
    """Errors deliberately exclude URLs, request bodies, headers and remote text."""


class AzureHTTPError(AzureError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"Azure REST request failed (HTTP {status}).")


class AzureRevisionConflict(AzureHTTPError):
    pass


class AzureUncertainWrite(AzureError):
    def __init__(self, status: int | None = None):
        self.status = status
        super().__init__("Azure write outcome is uncertain; fresh readback reconciliation is required before any retry.")


class AzureReadIncomplete(AzureError):
    pass


def retry_after_seconds(value: Any, now: float) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(str(value).strip())
        if math.isfinite(seconds):
            return max(0.0, seconds)
    except (ValueError, TypeError):
        pass
    try:
        date = email.utils.parsedate_to_datetime(str(value))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return max(0.0, date.timestamp() - now)
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass
class AzureResponse:
    data: Any
    headers: dict[str, str]
    status: int
    observed_at: str
    cache_hit: bool = False


@dataclass
class ReadCollection:
    items: list[dict[str, Any]] = field(default_factory=list)
    complete: bool = True
    blockers: list[str] = field(default_factory=list)
    observed_at: str = ""


class SharedThrottle:
    """One flock serializes reservations and responses, including HTTP 200 delays.

    The lock file itself contains the deadline, avoiding replacement/inode races.
    It contains no URL, credentials, request payload, Board content or identity data.
    A very long server delay is retained; a bounded invocation fails instead of
    capping Retry-After and sending a request too early.
    """

    def __init__(self, runtime_dir: pathlib.Path, *, interval: float = 0.75,
                 max_wait: float = 120.0, clock=time.time, sleep=time.sleep):
        self.runtime_dir = pathlib.Path(runtime_dir)
        self.interval, self.max_wait = float(interval), float(max_wait)
        self.clock, self.sleep = clock, sleep

    def _validate_root(self) -> pathlib.Path:
        root = self.runtime_dir
        identity_home = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        if not root.is_absolute() or not root.is_dir() or root.is_symlink():
            raise AzureError("An explicit existing runtime directory is required.")
        resolved = root.resolve()
        if root != resolved or not resolved.is_relative_to(identity_home) or resolved == identity_home:
            raise AzureError("Runtime directory must resolve within the current identity's home.")
        if resolved.stat().st_uid != os.getuid():
            raise AzureError("Runtime directory must belong to the current identity.")
        return resolved

    @contextlib.contextmanager
    def slot(self):
        root = self._validate_root()
        folder = root / ".azure-api"
        folder.mkdir(mode=0o700, exist_ok=True)
        if folder.is_symlink() or folder.stat().st_uid != os.getuid():
            raise AzureError("Unsafe Azure throttle state directory.")
        fd = os.open(folder / "throttle.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        deadline = self.clock() + self.max_wait
        try:
            if os.fstat(fd).st_uid != os.getuid():
                raise AzureError("Unsafe Azure throttle lock ownership.")
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if self.clock() >= deadline:
                        raise AzureError("Timed out waiting for the shared Azure throttle.")
                    self.sleep(min(0.25, deadline - self.clock()))
            raw = os.read(fd, 4096)
            try:
                state = json.loads(raw) if raw else {}
                not_before = float(state.get("not_before", 0))
                if not math.isfinite(not_before) or not_before < 0:
                    raise ValueError()
            except (TypeError, ValueError, AttributeError):
                raise AzureError("Azure throttle state is invalid; inspection is blocked.") from None
            while not_before > self.clock():
                if not_before > deadline:
                    raise AzureError("Shared Azure Retry-After delay exceeds this invocation's wait budget.")
                self.sleep(min(1.0, not_before - self.clock()))
            pause = [0.0]

            def defer(seconds: float | None) -> None:
                if seconds is not None:
                    pause[0] = max(pause[0], self.clock() + seconds)

            try:
                yield defer
            finally:
                state = {"version": 1, "not_before": max(pause[0], self.clock() + self.interval)}
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, (json.dumps(state, separators=(",", ":")) + "\n").encode())
                os.ftruncate(fd, os.lseek(fd, 0, os.SEEK_CUR))
                os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Even a same-host redirect may lead to a different organization/project.
        return None


def organization_slug(organization: str) -> str:
    value = str(organization).strip()
    if value.startswith("https://"):
        parsed = urllib.parse.urlsplit(value)
        if parsed.netloc.lower() != "dev.azure.com" or parsed.query or parsed.fragment:
            raise AzureError("Azure organization must use https://dev.azure.com.")
        value = parsed.path.strip("/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise AzureError("Invalid Azure organization.")
    return value


def issue_id(organization: str, project: str, value: int | str) -> str:
    try:
        if type(value) is not int and (not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value)):
            raise ValueError()
        number = int(value)
        if isinstance(value, bool) or number <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise AzureError("Invalid Azure work-item identifier.") from None
    return f"azdo:{organization_slug(organization)}:{project}:{number}"


def numeric_issue_id(organization: str, project: str, value: Any) -> int:
    if isinstance(value, str) and value.startswith("azdo:"):
        prefix = f"azdo:{organization_slug(organization)}:{project}:"
        if not value.startswith(prefix):
            raise AzureError("Cross-organization or cross-project work-item reference.")
        value = value[len(prefix):]
    normalized = issue_id(organization, project, value)
    return int(normalized.rsplit(":", 1)[1])


class AzureDevOpsClient:
    def __init__(self, organization: str, project: str, runtime_dir: pathlib.Path,
                 *, headers=None, capabilities=frozenset({"read"}), opener=None,
                 clock=time.time, sleep=time.sleep, cache_seconds: float = 15.0,
                 max_attempts: int = 4, max_backoff: float = 30.0,
                 timeout: float = 30.0, max_pages: int = 100,
                 interval: float = 0.75, max_wait: float = 120.0):
        self.organization = organization_slug(organization)
        self.project = str(project)
        if not self.project or any(c in self.project for c in "/\\:#?\x00"):
            raise AzureError("Invalid Azure project.")
        self.base_url = f"https://dev.azure.com/{self.organization}/{urllib.parse.quote(self.project, safe='')}"
        self.runtime_dir = pathlib.Path(runtime_dir)
        self.capabilities = frozenset(capabilities)
        if not self.capabilities <= CAPABILITIES:
            raise AzureError("Unknown Azure runtime capability.")
        self._headers = dict(headers or {})
        self._opener = opener or urllib.request.build_opener(_NoRedirect())
        self.clock, self.sleep = clock, sleep
        self.cache_seconds, self.max_attempts = cache_seconds, max(1, min(int(max_attempts), 8))
        self.max_backoff, self.timeout, self.max_pages = max_backoff, timeout, max_pages
        self.throttle = SharedThrottle(runtime_dir, interval=interval, max_wait=max_wait, clock=clock, sleep=sleep)
        self._cache: dict[str, tuple[float, AzureResponse]] = {}

    def _url(self, path: str, query: dict | None = None) -> str:
        if not isinstance(path, str) or any(c in path for c in "\r\n\\"):
            raise AzureError("Unsafe Azure REST path.")
        if path.startswith("https://"):
            url = path
        elif path.startswith("/_apis/") or path.startswith("_apis/"):
            url = self.base_url + "/" + path.lstrip("/")
        else:
            raise AzureError("Only the configured Azure project REST namespace is allowed.")
        parsed = urllib.parse.urlsplit(url)
        base = urllib.parse.urlsplit(self.base_url)
        decoded = urllib.parse.unquote(parsed.path)
        if (parsed.scheme != "https" or parsed.netloc.lower() != "dev.azure.com"
                or parsed.username or parsed.password or parsed.fragment
                or not decoded.startswith(urllib.parse.unquote(base.path) + "/_apis/")
                or any(part in {".", ".."} for part in decoded.split("/"))
                or "\\" in decoded or "%" in decoded):
            raise AzureError("Cross-origin or unsafe Azure REST URL rejected.")
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        params.update(query or {})
        params.setdefault("api-version", API_VERSION)
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                                       urllib.parse.urlencode(params, doseq=True), ""))

    def _authorize(self, method: str, url: str, data: Any, capability: str) -> bool:
        path = urllib.parse.unquote(urllib.parse.urlsplit(url).path).split("/_apis/", 1)[1].lower()
        read_post = method == "POST" and path in {"wit/workitemsbatch", "wit/wiql"}
        writing = method != "GET" and not read_post
        needed = capability if writing else "read"
        if needed not in self.capabilities or (not writing and capability != "read"):
            raise AzureError("Azure operation capability was not explicitly granted.")
        if writing:
            board = method == "PATCH" and re.fullmatch(r"wit/workitems/[1-9][0-9]*", path)
            draft = method == "POST" and re.fullmatch(r"git/repositories/[^/]+/pullrequests", path)
            push = method == "POST" and re.fullmatch(r"git/repositories/[^/]+/pushes", path)
            if not ((needed == "board_write" and board) or (needed == "draft_pr" and (draft or push))):
                raise AzureError("Azure mutation is outside the runtime's bounded capabilities.")
            if draft and (not isinstance(data, dict) or data.get("isDraft") is not True
                          or any(key in data for key in ("completionOptions", "autoCompleteSetBy", "mergeOptions", "status"))):
                raise AzureError("Only creation of a draft pull request is permitted.")
            if push:
                refs = data.get("refUpdates") if isinstance(data, dict) else None
                if (not isinstance(refs, list) or len(refs) != 1
                        or not str(refs[0].get("name", "")).startswith("refs/heads/feature/")
                        or refs[0].get("oldObjectId") != "0" * 40
                        or refs[0].get("newObjectId") == "0" * 40):
                    raise AzureError("Only creation of a new feature branch is permitted.")
        return writing

    def request(self, method: str, path: str, **kwargs) -> Any:
        return self.request_response(method, path, **kwargs).data

    def request_response(self, method: str, path: str, *, data=None, query=None,
                         capability: str = "read", fresh: bool = False,
                         headers=None, before_write=None) -> AzureResponse:
        method = method.upper()
        url = self._url(path, query)
        writing = self._authorize(method, url, data, capability)
        if writing and not callable(before_write):
            raise AzureError("Azure mutation requires an action authorization check.")
        cache_key = canonical_digest([method, url, data])
        cached = self._cache.get(cache_key)
        if not writing and not fresh and cached and self.clock() - cached[0] <= self.cache_seconds:
            result = copy.deepcopy(cached[1])
            result.cache_hit = True
            return result
        body = json.dumps(data, separators=(",", ":")).encode() if data is not None else None
        request_headers = {"Accept": "application/json", **self._headers, **(headers or {})}
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        attempts = 1 if writing else self.max_attempts
        for attempt in range(attempts):
            status, response_headers, raw, network_error = 0, {}, b"", False
            with self.throttle.slot() as defer:
                # A grant can expire or be revoked while this process waits.
                # Authorization failure is not an uncertain remote write.
                if writing:
                    before_write()
                request = urllib.request.Request(url, data=body, method=method, headers=request_headers)
                try:
                    response = self._opener.open(request, timeout=self.timeout) if hasattr(self._opener, "open") else self._opener(request, timeout=self.timeout)
                    with response:
                        status = int(response.status)
                        response_headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
                        raw = response.read(16 * 1024 * 1024 + 1)
                except urllib.error.HTTPError as error:
                    status = int(error.code)
                    response_headers = {str(k).lower(): str(v) for k, v in error.headers.items()} if error.headers else {}
                    error.close()
                except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
                    network_error = True
                delay = retry_after_seconds(response_headers.get("retry-after"), self.clock())
                defer(delay)
                retryable = network_error or status in {408, 429} or 500 <= status < 600
                if retryable and delay is None:
                    defer(min(self.max_backoff, 2 ** attempt))
            if writing:
                self._cache.clear()
            if retryable:
                if writing:
                    raise AzureUncertainWrite(status or None) from None
                if attempt + 1 < attempts:
                    continue
                raise AzureReadIncomplete("Azure read retry budget exhausted.") from None
            if status in {409, 412}:
                raise AzureRevisionConflict(status)
            if not 200 <= status < 300:
                raise AzureHTTPError(status)
            if len(raw) > 16 * 1024 * 1024:
                if writing:
                    raise AzureUncertainWrite(status)
                raise AzureReadIncomplete("Azure response exceeded the bounded read size.")
            length = response_headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) != len(raw)):
                if writing:
                    raise AzureUncertainWrite(status)
                raise AzureReadIncomplete("Azure response length is incomplete or inconsistent.")
            try:
                parsed = json.loads(raw) if raw else {}
            except (ValueError, UnicodeError):
                if writing:
                    raise AzureUncertainWrite(status) from None
                raise AzureReadIncomplete("Azure returned an invalid JSON response.") from None
            result = AzureResponse(parsed, response_headers, status, timestamp(self.clock()))
            if not writing:
                self._cache[cache_key] = (self.clock(), copy.deepcopy(result))
            return result
        raise AzureReadIncomplete("Azure read did not complete.")

    def paged(self, path: str, *, query=None, fresh: bool = False,
              page_size: int = 100, pagination: str = "continuation") -> ReadCollection:
        if not 1 <= page_size <= 1000 or pagination not in {"continuation", "skip"}:
            raise AzureError("Invalid bounded Azure pagination settings.")
        params = dict(query or {})
        params.setdefault("$top", page_size)
        result = ReadCollection(observed_at=timestamp(self.clock()))
        tokens, seen_items = set(), set()
        for _ in range(self.max_pages):
            try:
                response = self.request_response("GET", path, query=params, fresh=fresh)
            except AzureError as error:
                result.complete = False
                result.blockers.append(str(error))
                return result
            value = response.data
            result.observed_at = min(result.observed_at, response.observed_at)
            if not isinstance(value, dict) or not isinstance(value.get("value"), list):
                result.complete = False
                result.blockers.append("Azure paged response is missing its value list.")
                return result
            page = value["value"]
            if (not all(isinstance(item, dict) for item in page)
                    or ("count" in value and value["count"] != len(page))):
                result.complete = False
                result.blockers.append("Azure page count or item shape is inconsistent.")
                return result
            for item in page:
                native_key = next((key for key in ("pullRequestId", "evaluationId", "id", "name") if key in item), None)
                key = canonical_digest([native_key, item[native_key]]) if native_key else canonical_digest(item)
                if key in seen_items:
                    result.complete = False
                    result.blockers.append("Duplicate Azure page item; the snapshot may have changed.")
                    return result
                seen_items.add(key)
                result.items.append(item)
            token = response.headers.get("x-ms-continuationtoken") or value.get("continuationToken")
            if value.get("nextLink") or value.get("@odata.nextLink"):
                result.complete = False
                result.blockers.append("Azure returned an unsupported next-page link; completeness is unknown.")
                return result
            if token:
                if not isinstance(token, (str, int)) or str(token) in tokens or not page:
                    result.complete = False
                    result.blockers.append("Azure continuation token repeated or made no progress.")
                    return result
                tokens.add(str(token))
                params["continuationToken"] = str(token)
            elif pagination == "skip" and len(page) >= int(params["$top"]):
                params.pop("continuationToken", None)
                params["$skip"] = int(params.get("$skip", 0)) + len(page)
            elif len(page) >= int(params["$top"]):
                result.complete = False
                result.blockers.append("Full Azure continuation page has no next token; termination is ambiguous.")
                return result
            else:
                result.observed_at = min(result.observed_at, response.observed_at)
                return result
        result.complete = False
        result.blockers.append("Azure pagination budget exhausted before completeness was established.")
        return result

    def get_work_items(self, ids, *, fresh: bool = False) -> ReadCollection:
        requested = sorted({numeric_issue_id(self.organization, self.project, value) for value in ids})
        result = ReadCollection(observed_at=timestamp(self.clock()))
        for offset in range(0, len(requested), 200):
            batch = requested[offset:offset + 200]
            try:
                response = self.request_response("POST", "_apis/wit/workitemsbatch",
                                                 data={"ids": batch, "$expand": "All", "errorPolicy": "Fail"}, fresh=fresh)
            except AzureError as error:
                result.complete = False
                result.blockers.append(str(error))
                continue
            payload = response.data
            values = payload.get("value") if isinstance(payload, dict) else None
            if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
                result.complete = False
                result.blockers.append("Azure batch response is missing work items.")
                continue
            received = [item.get("id") for item in values]
            if (any(isinstance(value, bool) or not isinstance(value, int) for value in received)
                    or set(received) != set(batch) or len(received) != len(batch)
                    or payload.get("count", len(values)) != len(values)):
                result.complete = False
                result.blockers.append("Azure batch response omitted, duplicated or changed requested IDs.")
            else:
                # Azure omits relations for genuinely unlinked work items, even
                # with All expansion. Normalize only this verified expanded read.
                values = [{**item, "relations": item.get("relations", [])} for item in values]
            result.items.extend(values)
            result.observed_at = min(result.observed_at, response.observed_at)
        return result


def azure_cli_headers() -> dict[str, str]:
    """Use normal current-identity Azure CLI auth; never log its captured output."""
    identity_home = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    if os.environ.get("HOME") and pathlib.Path(os.environ["HOME"]).resolve() != identity_home:
        raise AzureError("Azure authentication HOME must match the current passwd identity.")
    config_path = pathlib.Path(os.environ.get("AZURE_CONFIG_DIR", str(identity_home / ".azure")))
    if not config_path.is_absolute() or not config_path.is_relative_to(identity_home):
        raise AzureError("Azure CLI configuration must remain within the current identity.")
    resolved_config = config_path.resolve()
    if not resolved_config.is_relative_to(identity_home) or resolved_config == identity_home:
        raise AzureError("Azure CLI configuration resolves outside the current identity.")
    if resolved_config.exists() and resolved_config.stat().st_uid != os.getuid():
        raise AzureError("Azure CLI configuration must be owned by the current identity.")
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token", "--resource", "499b84ac-1321-427f-aa17-267ca6975798",
             "--query", "accessToken", "--output", "tsv", "--only-show-errors"],
            capture_output=True, text=True, timeout=30, check=False,
            env={**os.environ, "HOME": str(identity_home), "AZURE_CONFIG_DIR": str(resolved_config),
                 "AZURE_CORE_COLLECT_TELEMETRY": "false"})
    except (OSError, subprocess.TimeoutExpired):
        raise AzureError("Current-identity Azure CLI authentication is unavailable.") from None
    token = result.stdout.strip()
    if result.returncode or not token or any(c.isspace() for c in token):
        raise AzureError("Current-identity Azure CLI authentication is unavailable.")
    return {"Authorization": "Bearer " + token}


_PROJECT_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def _work_item_endpoint(organization: str, url: Any) -> tuple[str | None, int]:
    """Parse an identity reference; this never follows a supplied URL."""
    if (not isinstance(url, str) or not url or len(url) > 2048
            or any(character.isspace() or ord(character) < 32 for character in url)
            or any(character in url for character in ("\\", "?", "#"))):
        raise AzureError("Invalid native work-item URL.")
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc.lower() != "dev.azure.com":
            raise ValueError()
        encoded = parsed.path.split("/")
        if encoded[0] or len(encoded) not in {6, 7}:
            raise ValueError()
        parts = []
        for part in encoded[1:]:
            if re.search(r"%(?![0-9a-fA-F]{2})", part):
                raise ValueError()
            decoded = urllib.parse.unquote(part, errors="strict")
            if (not decoded or decoded in {".", ".."} or "/" in decoded or "\\" in decoded
                    or any(ord(character) < 32 or ord(character) == 127 for character in decoded)):
                raise ValueError()
            parts.append(decoded)
        if (parts[0] != organization_slug(organization)
                or [part.lower() for part in parts[-4:-1]] != ["_apis", "wit", "workitems"]
                or not re.fullmatch(r"[1-9][0-9]*", parts[-1]) or encoded[-1] != parts[-1]):
            raise ValueError()
        return (parts[1] if len(parts) == 6 else None), int(parts[-1])
    except (ValueError, UnicodeError):
        raise AzureError("Native work-item URL is outside the configured Azure namespace.") from None


def verified_project_alias(raw: dict, organization: str, project: str) -> str | None:
    """Bind Azure's project GUID to a fetched row's exact project and self ID.

    A relation URL alone cannot establish this alias. Expanded rows may omit a
    self URL for legacy organization/name references; GUID references then fail
    closed. Callers must reject conflicting aliases across the fetched closure.
    """
    if not isinstance(raw, dict):
        raise AzureError("Invalid work-item identity evidence.")
    if "url" not in raw:
        return None
    fields = raw.get("fields")
    if (not isinstance(fields, dict) or fields.get("System.TeamProject") != project
            or type(raw.get("id")) is not int or raw["id"] < 1):
        raise AzureError("Work-item self URL does not establish the configured project.")
    alias, number = _work_item_endpoint(organization, raw["url"])
    if number != raw["id"]:
        raise AzureError("Work-item self URL identifies a different item.")
    if alias is None or alias == project:
        return None
    if not _PROJECT_GUID.fullmatch(alias):
        raise AzureError("Work-item self URL identifies another project.")
    return alias.lower()


def _relation_id(organization: str, project: str, url: Any, *, project_alias: str | None = None) -> str:
    reference, number = _work_item_endpoint(organization, url)
    if reference is None or reference == project:
        return issue_id(organization, project, number)
    if (isinstance(project_alias, str) and _PROJECT_GUID.fullmatch(project_alias)
            and _PROJECT_GUID.fullmatch(reference) and reference.lower() == project_alias.lower()):
        return issue_id(organization, project, number)
    raise AzureError("Unresolved or cross-project native dependency reference.")


def normalize_work_item(raw: dict, organization: str, project: str, *, state_categories=None) -> dict:
    states = state_categories or STATE_CATEGORIES
    blockers = []
    ident = issue_id(organization, project, raw.get("id"))
    fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
    revision = raw.get("rev")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        blockers.append("missing-or-invalid-revision")
    state = fields.get("System.State")
    category = states.get(state, "unknown") if isinstance(state, str) else "unknown"
    if category not in {"pending", "active", "completed", "removed"}:
        category = "unknown"
        blockers.append("unknown-board-state")
    if fields.get("System.TeamProject") != project:
        blockers.append("missing-or-cross-project-work-item")
    try:
        project_alias = verified_project_alias(raw, organization, project)
    except AzureError:
        project_alias = None
        blockers.append("invalid-work-item-project-identity")
    relations = raw.get("relations")
    predecessors, successors = set(), set()
    if not isinstance(relations, list):
        blockers.append("invalid-native-relations")
        relations = []
    for relation in relations:
        if not isinstance(relation, dict):
            blockers.append("invalid-native-relation")
            continue
        if relation.get("rel") not in {PREDECESSOR, SUCCESSOR}:
            continue
        try:
            target = _relation_id(organization, project, relation.get("url"), project_alias=project_alias)
            (predecessors if relation["rel"] == PREDECESSOR else successors).add(target)
        except AzureError:
            blockers.append("unresolved-native-dependency")
    return {"id": ident, "work_item_id": raw["id"], "revision": revision,
            "state": state if category != "unknown" else None, "state_category": category,
            "dependencies": sorted(predecessors), "native_dependencies": sorted(predecessors),
            "native_successors": sorted(successors), "blockers": sorted(set(blockers)), "eligible": False}


def _contract_graph(manifest: Any, organization: str, project: str) -> dict[str, set[str]]:
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
            or manifest.get("organization") != organization or manifest.get("project") != project
            or not isinstance(manifest.get("dependencies"), dict) or not manifest["dependencies"]):
        raise AzureError("missing-or-invalid-versioned-dependency-contract")
    graph = {}
    for key, dependencies in manifest["dependencies"].items():
        if not isinstance(dependencies, list):
            raise AzureError("invalid-dependency-contract-edge-list")
        ident = issue_id(organization, project, numeric_issue_id(organization, project, key))
        if key != ident or any(not isinstance(value, str) or not value.startswith("azdo:") for value in dependencies):
            raise AzureError("dependency-contract-identifiers-must-be-namespaced")
        graph[ident] = {issue_id(organization, project, numeric_issue_id(organization, project, value)) for value in dependencies}
        if graph[ident] != set(dependencies):
            raise AzureError("dependency-contract-identifiers-must-be-canonical")
        if len(graph[ident]) != len(dependencies):
            raise AzureError("duplicate-dependency-contract-edges")
    return graph


def project_snapshot(snapshot: dict, *, organization: str, project: str,
                     expected_manifest=None, supplement=None, authority=None,
                     max_age_seconds: float = 300.0, clock=time.time,
                     state_categories=None) -> dict:
    """Pure read-only graph projection; caller flags cannot assert completeness."""
    organization = organization_slug(organization)
    authority = authority if isinstance(authority, dict) else {}
    blockers, items, by_id, project_aliases = [], [], {}, set()
    observed = parse_timestamp(snapshot.get("observed_at"))
    if observed is None or not -5 <= clock() - observed <= max_age_seconds:
        blockers.append("missing-or-stale-observation")
    if snapshot.get("complete") is not True:
        blockers.append("incomplete-source-read")
    raw_items = snapshot.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raw_items = []
        blockers.append("missing-source-items")
    for raw in raw_items:
        try:
            item = normalize_work_item(raw, organization, project, state_categories=state_categories)
        except (AzureError, AttributeError):
            blockers.append("invalid-source-work-item")
            continue
        if item["id"] in by_id:
            blockers.append("duplicate-source-work-item")
            continue
        by_id[item["id"]] = item
        items.append(item)
        try:
            alias = verified_project_alias(raw, organization, project)
            if alias is not None:
                project_aliases.add(alias)
        except AzureError:
            pass  # normalize_work_item retained this invalid identity as a blocker.
        if item["blockers"]:
            blockers.append("invalid-or-unresolved-source-state")
    if len(project_aliases) > 1:
        blockers.append("inconsistent-native-project-identity")
    graph = {ident: set(item["dependencies"]) for ident, item in by_id.items()}
    for ident, deps in graph.items():
        native_successors = set(by_id[ident]["native_successors"])
        if not (deps | native_successors) <= by_id.keys():
            blockers.append("unresolved-dependency-closure")
        for dep in deps & by_id.keys():
            if ident not in by_id[dep]["native_successors"]:
                blockers.append("incomplete-reciprocal-native-dependency")
        for successor in native_successors & by_id.keys():
            if ident not in by_id[successor]["native_dependencies"]:
                blockers.append("incomplete-reciprocal-native-dependency")
    dependency_blockers = []
    try:
        expected = _contract_graph(expected_manifest, organization, project)
        if not set().union(*expected.values()) <= expected.keys():
            raise AzureError("dependency-contract-is-not-closed")
        if (authority.get("dependency_contract_sha256") != canonical_digest(expected_manifest)
                or not str(authority.get("approval_record", "")).strip()):
            dependency_blockers.append("dependency-contract-approval-not-established")
        if set(expected) != set(graph):
            dependency_blockers.append("dependency-contract-node-set-mismatch")
        if supplement is not None:
            extra = _contract_graph(supplement, organization, project)
            if (authority.get("dependency_supplement_sha256") != canonical_digest(supplement)
                    or not str(authority.get("supplement_approval_record", "")).strip()):
                dependency_blockers.append("dependency-supplement-not-explicitly-approved")
            elif not set(extra) <= set(expected):
                dependency_blockers.append("dependency-supplement-outside-contract")
            else:
                for ident, deps in extra.items():
                    if not deps <= expected[ident] or deps & graph.get(ident, set()):
                        dependency_blockers.append("dependency-supplement-does-not-match-missing-edges")
                    graph.setdefault(ident, set()).update(deps)
        missing = sorted([ident, dep] for ident, deps in expected.items() for dep in deps - graph.get(ident, set()))
        unexpected = sorted([ident, dep] for ident, deps in graph.items() for dep in deps - expected.get(ident, set()))
        if missing:
            dependency_blockers.append("native-dependency-graph-incomplete")
        if unexpected:
            dependency_blockers.append("dependency-contract-drift")
    except AzureError as error:
        expected, missing, unexpected = {}, [], []
        dependency_blockers.append(str(error))
    degree = {ident: len(deps & graph.keys()) for ident, deps in graph.items()}
    successors = {ident: set() for ident in graph}
    for ident, deps in graph.items():
        for dep in deps & graph.keys():
            successors[dep].add(ident)
    ready, visited = [ident for ident, count in degree.items() if count == 0], 0
    while ready:
        ident = ready.pop()
        visited += 1
        for child in successors[ident]:
            degree[child] -= 1
            if degree[child] == 0:
                ready.append(child)
    if visited != len(graph):
        blockers.append("cyclic-dependency-graph")
    complete = not blockers
    dependency_complete = complete and not dependency_blockers
    blockers.extend(dependency_blockers)
    if authority.get("execution_authorized") is not True or not str(authority.get("approval_record", "")).strip():
        blockers.append("execution-authority-not-established")
    for item in items:
        item["dependencies"] = sorted(graph.get(item["id"], ()))
        item["blockers"].extend(blockers)
        for dep in item["dependencies"]:
            if by_id.get(dep, {}).get("state_category") != "completed":
                item["blockers"].append("dependency-not-completed:" + dep)
        if item["state_category"] != "pending":
            item["blockers"].append("work-item-not-pending")
        item["blockers"] = sorted(set(item["blockers"]))
        item["eligible"] = not item["blockers"]
    return {"provider": "azure-devops", "organization": organization, "project": project,
            "complete": complete, "dependency_complete": dependency_complete,
            "observed_at": snapshot.get("observed_at"), "items": sorted(items, key=lambda item: item["work_item_id"]),
            "blockers": sorted(set(blockers)), "graph_digest": canonical_digest({key: sorted(value) for key, value in graph.items()}),
            "missing_dependency_edges": missing, "unexpected_dependency_edges": unexpected,
            "expected_dependency_count": sum(map(len, expected.values())),
            "native_dependency_count": sum(len(item["native_dependencies"]) for item in items),
            "eligible_count": sum(item["eligible"] for item in items)}


class AzureBoardsProvider:
    def __init__(self, client: AzureDevOpsClient, *, state_categories=None, max_items: int = 2000):
        self.client, self.state_categories, self.max_items = client, state_categories, max_items

    def inspect(self, ids, *, expected_manifest=None, supplement=None, authority=None,
                max_age_seconds: float = 300.0, fresh: bool = True) -> dict:
        client = self.client
        pending = {numeric_issue_id(client.organization, client.project, value) for value in ids}
        if isinstance(expected_manifest, dict):
            try:
                pending.update(numeric_issue_id(client.organization, client.project, value)
                               for value in _contract_graph(expected_manifest, client.organization, client.project))
            except AzureError:
                pass  # The pure projector records the invalid contract as a blocker.
        found, read_blockers = {}, []
        observed = timestamp(client.clock())
        while pending:
            if len(found) + len(pending) > self.max_items:
                read_blockers.append("dependency-closure-budget-exhausted")
                break
            batch = client.get_work_items(pending, fresh=fresh)
            observed = min(observed, batch.observed_at or observed)
            if not batch.complete:
                read_blockers.extend(batch.blockers or ["incomplete-source-read"])
                break
            pending = set()
            for raw in batch.items:
                try:
                    normalized = normalize_work_item(raw, client.organization, client.project, state_categories=self.state_categories)
                except AzureError:
                    read_blockers.append("invalid-source-work-item")
                    continue
                found[raw["id"]] = raw
                # Global WIT IDs do not establish project membership. Do not
                # follow onward references from a row outside this project.
                if "missing-or-cross-project-work-item" in normalized["blockers"]:
                    continue
                for dep in set(normalized["native_dependencies"]) | set(normalized["native_successors"]):
                    dep_id = numeric_issue_id(client.organization, client.project, dep)
                    if dep_id not in found:
                        pending.add(dep_id)
            pending -= found.keys()
        # Re-read all revisions after closure expansion. A mixed/stale graph can
        # never become eligible just because every individual request succeeded.
        if found and not read_blockers:
            recheck = client.get_work_items(found, fresh=True)
            if (not recheck.complete or {item.get("id"): item.get("rev") for item in recheck.items}
                    != {key: item.get("rev") for key, item in found.items()}):
                read_blockers.append("revision-changed-during-inspection")
            else:
                try:
                    def identity(rows):
                        return {row["id"]: (row.get("fields", {}).get("System.TeamProject"),
                                            verified_project_alias(row, client.organization, client.project)) for row in rows}
                    if identity(recheck.items) != identity(found.values()):
                        read_blockers.append("project-identity-changed-during-inspection")
                except (AzureError, AttributeError, KeyError, TypeError):
                    read_blockers.append("invalid-project-identity-during-inspection")
        snapshot = {"items": list(found.values()), "observed_at": observed, "complete": not read_blockers}
        report = project_snapshot(snapshot, organization=client.organization, project=client.project,
                                  expected_manifest=expected_manifest, supplement=supplement, authority=authority,
                                  max_age_seconds=max_age_seconds, clock=client.clock, state_categories=self.state_categories)
        report["read_blockers"] = read_blockers
        return report

    def repository_evidence(self, repository: str, *, base_branch: str = "refs/heads/develop",
                            build_ids=(), fresh: bool = True) -> dict:
        """Inspect source-control and pipeline evidence; never qualify deployment."""
        name = urllib.parse.quote(repository, safe="")
        client, blockers = self.client, []
        try:
            repository_data = client.request("GET", f"_apis/git/repositories/{name}", fresh=fresh)
            if not isinstance(repository_data, dict) or not repository_data.get("id"):
                raise AzureReadIncomplete("Repository evidence is missing its identity.")
        except AzureError as error:
            return {"complete": False, "blockers": [str(error)]}
        repo_id = urllib.parse.quote(str(repository_data["id"]), safe="")
        refs = client.paged(f"_apis/git/repositories/{repo_id}/refs",
                            query={"filter": base_branch.removeprefix("refs/")}, fresh=fresh)
        prs = client.paged(f"_apis/git/repositories/{repo_id}/pullrequests",
                           query={"searchCriteria.status": "all"}, fresh=fresh, pagination="skip")
        policies = client.paged("_apis/git/policy/configurations", query={"repositoryId": repository_data["id"],
                                                                         "refName": base_branch}, fresh=fresh)
        builds = client.paged("_apis/build/builds", query={"repositoryId": repository_data["id"],
                                                         "repositoryType": "TfsGit", "branchName": base_branch}, fresh=fresh)
        for collection in (refs, prs, policies, builds):
            if not collection.complete:
                blockers.extend(collection.blockers)
        for pr in prs.items:
            if (pr.get("status") not in {"active", "abandoned", "completed"} or type(pr.get("isDraft")) is not bool
                    or not all(isinstance(pr.get(key), str) and pr[key].startswith("refs/") for key in ("sourceRefName", "targetRefName"))):
                blockers.append("unknown-or-incomplete-pull-request-state")
        for build in builds.items:
            state, result = build.get("status"), build.get("result")
            if (state not in {"none", "inProgress", "completed", "cancelling", "postponed", "notStarted"}
                    or result not in {None, "none", "succeeded", "partiallySucceeded", "failed", "canceled"}
                    or (state == "completed" and result in {None, "none"})
                    or not build.get("sourceVersion")):
                blockers.append("unknown-or-incomplete-build-state")
        if not any(item.get("name") == base_branch and item.get("objectId") for item in refs.items):
            blockers.append("configured-base-ref-not-observed")
        evaluations = []
        project_data = repository_data.get("project") or {}
        if len(prs.items) > 50:
            blockers.append("pull-request-policy-evidence-budget-exhausted")
        for pr in prs.items[:50]:
            if not pr.get("pullRequestId") or not project_data.get("id"):
                blockers.append("pull-request-or-project-identity-missing")
                continue
            artifact = f"vstfs:///CodeReview/CodeReviewId/{project_data['id']}/{pr['pullRequestId']}"
            checks = client.paged("_apis/policy/evaluations", query={"artifactId": artifact, "api-version": "7.1-preview.1"},
                                  fresh=fresh, pagination="skip")
            evaluations.extend({"pull_request_id": pr["pullRequestId"], "id": item.get("evaluationId"),
                                "status": item.get("status")} for item in checks.items)
            if not checks.complete:
                blockers.extend(checks.blockers)
        timelines = []
        selected = set(build_ids) or {item["id"] for item in builds.items[:10] if isinstance(item.get("id"), int)}
        if len(selected) > 50:
            blockers.append("timeline-evidence-budget-exhausted")
            selected = set(sorted(selected)[:50])
        for build_id in sorted(selected):
            try:
                build_id = numeric_issue_id(client.organization, client.project, build_id)
                timeline = client.request("GET", f"_apis/build/builds/{build_id}/timeline", fresh=fresh)
                records = timeline.get("records") if isinstance(timeline, dict) else None
                if not isinstance(records, list) or not all(isinstance(record, dict) and record.get("id") for record in records):
                    raise AzureReadIncomplete("Timeline records are missing.")
                for record in records:
                    state, result = record.get("state"), record.get("result")
                    if (state not in {"pending", "inProgress", "completed"}
                            or result not in {None, "succeeded", "succeededWithIssues", "failed", "canceled", "skipped", "abandoned"}
                            or (state == "completed" and result is None)):
                        raise AzureReadIncomplete("Timeline state is unknown or incomplete.")
                timelines.append({"build_id": build_id, "records": [
                    {key: record.get(key) for key in ("id", "parentId", "type", "state", "result", "startTime", "finishTime", "errorCount", "warningCount")}
                    for record in records]})
            except AzureError as error:
                blockers.append(str(error))
        return {"complete": not blockers, "blockers": sorted(set(blockers)), "observed_at": timestamp(client.clock()),
                "repository": {key: repository_data.get(key) for key in ("id", "name", "defaultBranch", "webUrl")},
                "base_refs": [{key: item.get(key) for key in ("name", "objectId")} for item in refs.items],
                "pull_requests": [{**{key: item.get(key) for key in ("pullRequestId", "status", "isDraft", "sourceRefName", "targetRefName")},
                                   **{key: {"commitId": item[key].get("commitId")} for key in ("lastMergeSourceCommit", "lastMergeTargetCommit", "lastMergeCommit") if isinstance(item.get(key), dict)}}
                                  for item in prs.items],
                "policies": [_policy_summary(item) for item in policies.items],
                "policy_evaluations": evaluations,
                "builds": [{key: item.get(key) for key in ("id", "buildNumber", "status", "result", "sourceBranch", "sourceVersion", "queueTime", "startTime", "finishTime")}
                           for item in builds.items], "timelines": timelines,
                "timeline_scope": "explicit-build-ids" if build_ids else "first-ten-listed-builds",
                "deployment_authority": False}


def _policy_summary(item: dict) -> dict:
    settings = item.get("settings") if isinstance(item.get("settings"), dict) else {}
    kind = item.get("type") if isinstance(item.get("type"), dict) else {}
    result = {key: item.get(key) for key in ("id", "revision", "isEnabled", "isBlocking")}
    result["type"] = {"id": kind.get("id")}
    result["settings"] = {key: settings[key] for key in (
        "minimumApproverCount", "creatorVoteCounts", "allowDownvotes", "resetOnSourcePush",
        "requireVoteOnLastIteration", "buildDefinitionId", "validDuration", "manualQueueOnly",
        "queueOnSourceUpdateOnly") if isinstance(settings.get(key), (int, bool))}
    scopes = settings.get("scope")
    result["scope"] = [{key: scope.get(key) for key in ("repositoryId", "refName", "matchKind")}
                       for scope in scopes if isinstance(scope, dict)] if isinstance(scopes, list) else []
    return result
