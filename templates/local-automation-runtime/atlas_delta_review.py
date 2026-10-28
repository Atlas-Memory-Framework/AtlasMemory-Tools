"""Frozen-delta advisory review and ordered checks for the local pilot."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
LANE_ORDER = {"code": 0, "environment": 1, "test": 2}
_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
UNSUPPORTED_CAPABILITY_EXIT = 77  # POSIX EX_UNAVAILABLE; timeouts are not capability evidence.


class DeltaReviewError(ValueError):
    pass


def _git(root: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise DeltaReviewError(proc.stderr.decode("utf-8", "replace").strip() or "git command failed")
    return proc.stdout


def _head(root: Path) -> str:
    return _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()


def _require_clean(root: Path) -> None:
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise DeltaReviewError("candidate checkout must be clean")


def _changed_paths(root: Path, base: str, candidate: str) -> list[str]:
    raw = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z", "--find-renames", base, candidate)
    fields = raw.split(b"\0")
    paths: set[str] = set()
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index].decode("ascii", "strict")
        index += 1
        count = 2 if status.startswith(("R", "C")) else 1
        if index + count > len(fields):
            raise DeltaReviewError("Git returned an incomplete path inventory")
        for raw_path in fields[index:index + count]:
            paths.add(raw_path.decode("utf-8", "strict"))
        index += count
    if not paths:
        raise DeltaReviewError("delta has no changed paths")
    return sorted(paths)


def _diff_bytes(root: Path, base: str, candidate: str) -> bytes:
    # No textconv, external diff, color, or rename heuristics: the binary patch
    # deterministically represents changed blob bytes and full object ids.
    return _git(
        root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--binary",
        "--full-index",
        "--no-color",
        base,
        candidate,
        "--",
    )


def freeze_delta(root: str | Path, base: str, candidate: str) -> dict:
    """Bind a clean committed candidate to its base, both rename paths and raw diff."""
    repo = Path(root).resolve()
    _require_clean(repo)
    base_oid = _git(repo, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
    candidate_oid = _git(repo, "rev-parse", "--verify", f"{candidate}^{{commit}}").decode().strip()
    paths = _changed_paths(repo, base_oid, candidate_oid)
    diff = _diff_bytes(repo, base_oid, candidate_oid)
    return {
        "schema_version": SCHEMA_VERSION,
        "base_revision": base_oid,
        "candidate_revision": candidate_oid,
        "changed_paths": paths,
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _binding(snapshot: dict) -> dict:
    required = {"schema_version", "base_revision", "candidate_revision", "changed_paths", "diff_sha256", "created_at"}
    if type(snapshot) is not dict or set(snapshot) != required:
        raise DeltaReviewError("snapshot has missing or extra fields")
    if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != SCHEMA_VERSION:
        raise DeltaReviewError("unsupported snapshot schema")
    for key in ("base_revision", "candidate_revision", "diff_sha256"):
        if type(snapshot[key]) is not str or not _SHA_RE.fullmatch(snapshot[key]):
            raise DeltaReviewError(f"{key} must be a lowercase Git/SHA-256 digest")
    _timestamp(snapshot["created_at"])
    paths = snapshot["changed_paths"]
    if type(paths) is not list or not paths or any(type(path) is not str or not path for path in paths):
        raise DeltaReviewError("changed_paths must be a nonempty list of paths")
    if paths != sorted(set(paths)):
        raise DeltaReviewError("changed_paths must be unique and sorted")
    return {key: snapshot[key] for key in ("base_revision", "candidate_revision", "changed_paths", "diff_sha256")}


def _require_current_snapshot(root: str | Path, snapshot: dict) -> tuple[Path, dict]:
    repo = Path(root).resolve()
    binding = _binding(snapshot)
    _require_clean(repo)
    if _head(repo) != binding["candidate_revision"]:
        raise DeltaReviewError("snapshot candidate is not the current HEAD")
    current = freeze_delta(repo, binding["base_revision"], binding["candidate_revision"])
    if _binding(current) != binding:
        raise DeltaReviewError("snapshot no longer matches its committed delta")
    return repo, binding


def validate_review(root: str | Path, snapshot: dict, review: dict) -> dict:
    """Separate valid evidence from eligibility for the pilot acceptance gate."""
    _, binding = _require_current_snapshot(root, snapshot)
    required = {"snapshot", "reviewer", "reviewed_at", "findings", "disposition"}
    if type(review) is not dict or set(review) != required:
        raise DeltaReviewError("review evidence is missing or has extra fields")
    if review["snapshot"] != binding:
        raise DeltaReviewError("review evidence is stale or bound to a different delta")
    if type(review["reviewer"]) is not str or not review["reviewer"].strip():
        raise DeltaReviewError("reviewer must identify the human or tool that supplied the evidence")
    reviewed_at = _timestamp(review["reviewed_at"])
    if reviewed_at < _timestamp(snapshot["created_at"]):
        raise DeltaReviewError("review timestamp precedes the frozen snapshot")
    findings = review["findings"]
    disposition = review["disposition"]
    if type(findings) is not list or any(type(item) is not str or not item.strip() for item in findings):
        raise DeltaReviewError("findings must be a list of nonempty strings")
    if type(disposition) is not str or disposition not in {"clear", "findings", "inconclusive"}:
        raise DeltaReviewError("unknown advisory disposition")
    if disposition == "clear" and findings:
        raise DeltaReviewError("clear disposition cannot include findings")
    eligible = disposition == "clear" and not findings
    return {
        "evidence_valid": True,
        "acceptance_eligible": eligible,
        "advisory_only": True,
        "disposition": disposition,
        "finding_count": len(findings),
        "reason": None if eligible else ("review_inconclusive" if disposition == "inconclusive" else "review_has_findings"),
    }


def validate_check_plan(checks: list[dict]) -> list[dict]:
    """Return the canonical required-check plan used by both runner and gate."""
    normalized = ordered_checks(checks)
    if not normalized:
        raise DeltaReviewError("pilot acceptance requires a nonempty check plan")
    return normalized


def validate_pilot_acceptance(
    root: str | Path, snapshot: dict, review: dict, check_plan: list[dict], checks_result: dict,
) -> dict:
    """Fail closed unless the exact frozen plan and its results pass."""
    repo, binding = _require_current_snapshot(root, snapshot)
    review_status = validate_review(repo, snapshot, review)
    plan = validate_check_plan(check_plan)
    if not {"code", "environment", "test"}.issubset({check["lane"] for check in plan}):
        raise DeltaReviewError("required check plan must include code, environment and test lanes")
    if type(checks_result) is not dict or set(checks_result) != {"snapshot", "results", "passed", "execution_source"}:
        raise DeltaReviewError("same-snapshot check results are missing or malformed")
    if checks_result["snapshot"] != binding:
        raise DeltaReviewError("check results are stale or bound to a different delta")
    results = checks_result["results"]
    if type(results) is not list or checks_result["passed"] is not True or checks_result["execution_source"] != "local_operator_pilot":
        raise DeltaReviewError("checks have not passed in the local pilot")
    if len(results) != len(plan):
        raise DeltaReviewError("check results do not exactly cover the required plan")
    prior_end = _timestamp(snapshot["created_at"])
    for expected, item in zip(plan, results):
        if type(item) is not dict or set(item) != {
            "id", "lane", "argv", "timeout_seconds", "capability", "started_at", "ended_at",
            "returncode", "timed_out", "status", "output",
        }:
            raise DeltaReviewError("check result fields are missing or extra")
        actual = {key: item[key] for key in ("id", "lane", "argv", "timeout_seconds", "capability")}
        if actual != {key: expected.get(key) for key in ("id", "lane", "argv", "timeout_seconds", "capability")}:
            raise DeltaReviewError("check result does not match the frozen command plan")
        if (type(item["id"]) is not str or type(item["lane"]) is not str
                or type(item["argv"]) is not list or any(type(arg) is not str for arg in item["argv"])
                or type(item["timeout_seconds"]) is not int or type(item["returncode"]) is not int
                or type(item["timed_out"]) is not bool or type(item["status"]) is not str
                or type(item["output"]) is not str or item["status"] != "passed"):
            raise DeltaReviewError("check result has invalid terminal field types or did not pass")
        if item["capability"] is not None and type(item["capability"]) is not str:
            raise DeltaReviewError("check capability must be a string or null")
        started, ended = _timestamp(item["started_at"]), _timestamp(item["ended_at"])
        if started < prior_end or ended < started or item["returncode"] != 0 or item["timed_out"] is not False:
            raise DeltaReviewError("check result chronology or terminal status is invalid")
        prior_end = ended
    eligible = review_status["acceptance_eligible"]
    return {
        "pilot_acceptance_eligible": eligible,
        "evidence_valid": True,
        "checks_passed": True,
        "review_disposition": review_status["disposition"],
        "reason": review_status["reason"],
        "advisory_only": True,
        "next_step": "continue existing supervised acceptance" if eligible else "stop and resolve review findings",
    }


def pilot_task_enabled(item: dict) -> bool:
    """Treat a present pilot marker as enabled unless explicitly disabled."""
    metadata = item.get("metadata") if type(item) is dict and type(item.get("metadata")) is dict else {}
    if "atlas_delta_review_pilot_v1" not in metadata:
        return False
    pilot = metadata["atlas_delta_review_pilot_v1"]
    return not (type(pilot) is dict and pilot.get("enabled") is False)


def validate_pilot_task_completion(item: dict, *, expected_checkout: str) -> dict:
    """Validate task-owned pilot evidence at any maintained terminal write path."""
    metadata = item.get("metadata") if type(item) is dict and type(item.get("metadata")) is dict else {}
    if "atlas_delta_review_pilot_v1" not in metadata:
        return {"pilot_enabled": False, "eligible": True}
    pilot = metadata["atlas_delta_review_pilot_v1"]
    if type(pilot) is dict and pilot.get("enabled") is False:
        return {"pilot_enabled": False, "eligible": True}
    required_fields = {"enabled", "repository_root", "required_checks", "evidence"}
    if type(pilot) is not dict or set(pilot) != required_fields or pilot.get("enabled") is not True:
        raise DeltaReviewError("trusted delta-review pilot metadata is missing or malformed")
    if type(pilot["repository_root"]) is not str or not pilot["repository_root"]:
        raise DeltaReviewError("trusted pilot repository root is invalid")
    if type(expected_checkout) is not str or not expected_checkout:
        raise DeltaReviewError("supervised checkout is unavailable for pilot acceptance")
    if Path(pilot["repository_root"]).resolve(strict=True) != Path(expected_checkout).resolve(strict=True):
        raise DeltaReviewError("pilot snapshot repository differs from the supervised checkout")
    plan = validate_check_plan(pilot["required_checks"])
    if plan != pilot["required_checks"]:
        raise DeltaReviewError("required check plan is not normalized")
    evidence_refs = pilot["evidence"]
    names = {"snapshot", "review", "checks"}
    if type(evidence_refs) is not dict or set(evidence_refs) != names:
        raise DeltaReviewError("pilot evidence references are incomplete")
    loaded = {}
    for name, reference in evidence_refs.items():
        if type(reference) is not dict or set(reference) != {"path", "sha256"}:
            raise DeltaReviewError(f"{name} evidence reference is malformed")
        if (type(reference["path"]) is not str or not reference["path"]
                or type(reference["sha256"]) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", reference["sha256"])):
            raise DeltaReviewError(f"{name} evidence reference is invalid")
        evidence_path = Path(reference["path"]).resolve(strict=True)
        raw = evidence_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            raise DeltaReviewError(f"{name} evidence changed after it was recorded")
        loaded[name] = json.loads(raw)
    verdict = validate_pilot_acceptance(
        pilot["repository_root"], loaded["snapshot"], loaded["review"], plan, loaded["checks"],
    )
    if verdict.get("pilot_acceptance_eligible") is not True:
        raise DeltaReviewError("pilot review is not clear for acceptance")
    return {"pilot_enabled": True, "eligible": True, "snapshot": loaded["snapshot"]["candidate_revision"]}


def ordered_checks(checks: list[dict]) -> list[dict]:
    """Validate and order declared argv checks: code, environment, then tests."""
    if type(checks) is not list:
        raise DeltaReviewError("checks must be a list")
    seen: set[str] = set()
    normalized = []
    for check in checks:
        if type(check) is not dict or not {"id", "lane", "argv"}.issubset(check) or set(check).difference({"id", "lane", "argv", "timeout_seconds", "capability"}):
            raise DeltaReviewError("each check requires id, lane and argv, with only optional timeout_seconds/capability")
        check_id, lane, argv = check["id"], check["lane"], check["argv"]
        if type(check_id) is not str or not check_id.strip() or check_id in seen:
            raise DeltaReviewError("check ids must be nonempty and unique")
        if type(lane) is not str or lane not in LANE_ORDER:
            raise DeltaReviewError("check lane is invalid")
        if type(argv) is not list or not argv or type(argv[0]) is not str or not argv[0] or any(type(arg) is not str for arg in argv):
            raise DeltaReviewError("argv must be a nonempty list of strings")
        timeout = check.get("timeout_seconds", 30)
        if type(timeout) is not int or timeout < 1 or timeout > 300:
            raise DeltaReviewError("timeout_seconds must be between 1 and 300")
        capability = check.get("capability")
        if lane == "environment" and (type(capability) is not str or not capability.strip()):
            raise DeltaReviewError("environment checks must name the capability they probe")
        if lane != "environment" and capability is not None:
            raise DeltaReviewError("only environment checks may name a capability")
        seen.add(check_id)
        normalized.append({"id": check_id, "lane": lane, "argv": list(argv), "timeout_seconds": timeout, **({"capability": capability} if capability is not None else {})})
    return sorted(normalized, key=lambda item: (LANE_ORDER[item["lane"]], item["id"]))


def classify_failure(lane: str, *, capability_supported: bool | None = None) -> str:
    if type(lane) is not str or lane not in LANE_ORDER:
        raise DeltaReviewError("unknown validation lane")
    if lane == "environment" and capability_supported is False:
        return "environment_blocked"
    return {"code": "code_failure", "environment": "environment_failure", "test": "test_failure"}[lane]


def run_ordered_checks(root: str | Path, snapshot: dict, checks: list[dict]) -> dict:
    """Run the explicit pilot checks in order, stopping on the first failure."""
    repo, binding = _require_current_snapshot(root, snapshot)
    results = []
    for check in ordered_checks(checks):
        _require_current_snapshot(repo, snapshot)
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            proc = subprocess.run(check["argv"], cwd=repo, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=check["timeout_seconds"], check=False)
            returncode = proc.returncode
            output = proc.stdout or ""
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            returncode = None
            raw_output = exc.stdout or b""
            output = raw_output.decode("utf-8", "replace") if isinstance(raw_output, bytes) else raw_output
            timed_out = True
        ended_at = datetime.now(timezone.utc).isoformat()
        _require_current_snapshot(repo, snapshot)
        ok = not timed_out and returncode == 0
        result = {
            "id": check["id"],
            "lane": check["lane"],
            "argv": check["argv"],
            "timeout_seconds": check["timeout_seconds"],
            "capability": check.get("capability"),
            "started_at": started_at,
            "ended_at": ended_at,
            "returncode": returncode,
            "timed_out": timed_out,
            "status": "passed" if ok else "failed",
            "output": output,
        }
        if not ok:
            unsupported = check["lane"] == "environment" and not timed_out and returncode == UNSUPPORTED_CAPABILITY_EXIT
            result["failure_class"] = classify_failure(check["lane"], capability_supported=False if unsupported else None)
            if unsupported:
                result["unsupported_capability"] = check["capability"]
            elif check["lane"] == "environment":
                result["failure_class"] = "environment_failure"
        results.append(result)
        if not ok:
            break
    return {"snapshot": binding, "results": results, "passed": bool(results) and all(item["status"] == "passed" for item in results), "execution_source": "local_operator_pilot"}


def _timestamp(value: str) -> datetime:
    if type(value) is not str:
        raise DeltaReviewError("timestamps must be ISO-8601 strings")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeltaReviewError("timestamps must be ISO-8601 strings") from exc
    if parsed.tzinfo is None:
        raise DeltaReviewError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def new_metrics(snapshot: dict, started_at: str | None = None) -> dict:
    binding = _binding(snapshot)
    started = started_at or datetime.now(timezone.utc).isoformat()
    if _timestamp(started) < _timestamp(snapshot["created_at"]):
        raise DeltaReviewError("metrics start precedes the frozen snapshot")
    return {"snapshot": binding, "started_at": started, "events": [], "first_useful_finding_at": None, "first_useful_finding_seconds": None, "rework_count": 0, "accepted_at": None, "total_acceptance_seconds": None, "source": "operator-reported"}


def record_metric_event(metrics: dict, event: str, snapshot: dict, occurred_at: str | None = None) -> dict:
    """Record delta-bound operator-reported timing; reject impossible chronology."""
    required = {"snapshot", "started_at", "events", "first_useful_finding_at", "first_useful_finding_seconds", "rework_count", "accepted_at", "total_acceptance_seconds", "source"}
    if type(metrics) is not dict or set(metrics) != required or metrics["source"] != "operator-reported":
        raise DeltaReviewError("metrics are malformed or lack operator-reported provenance")
    if metrics["snapshot"] != _binding(snapshot):
        raise DeltaReviewError("metrics belong to a different delta snapshot")
    if type(metrics["rework_count"]) is not int or metrics["rework_count"] < 0:
        raise DeltaReviewError("rework_count must be a nonnegative integer")
    if event not in {"useful_finding", "rework", "accepted"}:
        raise DeltaReviewError("unknown metric event")
    started = _timestamp(metrics["started_at"])
    events = metrics["events"]
    if type(events) is not list:
        raise DeltaReviewError("metrics events must be a list")
    prior = started
    accepted_seen = False
    for item in events:
        if type(item) is not dict or set(item) != {"event", "occurred_at"} or item["event"] not in {"useful_finding", "rework", "accepted"}:
            raise DeltaReviewError("metrics contain an invalid event")
        at = _timestamp(item["occurred_at"])
        if at < prior:
            raise DeltaReviewError("metric event chronology moves backwards")
        if accepted_seen:
            raise DeltaReviewError("metric event follows acceptance")
        accepted_seen = item["event"] == "accepted"
        prior = at
    finding_events = [item for item in events if item["event"] == "useful_finding"]
    acceptance_events = [item for item in events if item["event"] == "accepted"]
    if metrics["rework_count"] != sum(item["event"] == "rework" for item in events):
        raise DeltaReviewError("rework counter does not match its event history")
    expected_first_at = finding_events[0]["occurred_at"] if finding_events else None
    expected_first_seconds = (_timestamp(expected_first_at) - started).total_seconds() if expected_first_at else None
    expected_accepted_at = acceptance_events[0]["occurred_at"] if acceptance_events else None
    expected_total = (_timestamp(expected_accepted_at) - started).total_seconds() if expected_accepted_at else None
    if metrics["first_useful_finding_at"] != expected_first_at or metrics["first_useful_finding_seconds"] != expected_first_seconds:
        raise DeltaReviewError("first-finding metrics do not match their event history")
    if metrics["accepted_at"] != expected_accepted_at or metrics["total_acceptance_seconds"] != expected_total:
        raise DeltaReviewError("acceptance metrics do not match their event history")
    timestamp = occurred_at or datetime.now(timezone.utc).isoformat()
    moment = _timestamp(timestamp)
    if moment < prior:
        raise DeltaReviewError("metric event chronology moves backwards")
    if accepted_seen:
        raise DeltaReviewError("metric event follows acceptance")
    result = dict(metrics)
    result["events"] = [dict(item) for item in events] + [{"event": event, "occurred_at": timestamp}]
    prior_findings = finding_events
    if event == "useful_finding" and not prior_findings:
        result["first_useful_finding_at"] = timestamp
        result["first_useful_finding_seconds"] = (moment - started).total_seconds()
    if event == "rework":
        result["rework_count"] += 1
    if event == "accepted":
        result["accepted_at"] = timestamp
        result["total_acceptance_seconds"] = (moment - started).total_seconds()
    return result


def write_json(path: str | Path, value: dict) -> None:
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
