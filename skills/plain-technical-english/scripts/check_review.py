#!/usr/bin/env python3
"""Verify review coverage, source freshness and evidence, not semantic clarity."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

SCHEMA = "plain-technical-english.review.v1"
CRITERIA = (
    "answer-first",
    "actors-actions",
    "conditions-reasons",
    "terms-referents",
    "reasoning-uncertainty",
    "economy-clarity",
    "faithfulness",
)
CONDITIONAL = {"actors-actions", "conditions-reasons", "terms-referents"}


def prepare(data: bytes) -> dict[str, Any]:
    data.decode("utf-8")
    return {
        "schema": SCHEMA,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "reviewer": "",
        "reader_summary": "",
        "criteria": {
            key: {"result": "pending", "reason": "", "evidence": []}
            for key in CRITERIA
        },
    }


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate(data: bytes, record: Any) -> tuple[list[str], list[str]]:
    """Return malformed/stale-record errors and reviewer-recorded failures."""
    lines = data.decode("utf-8").splitlines()
    errors: list[str] = []
    failures: list[str] = []
    if not isinstance(record, dict):
        return ["review must be an object"], []
    if record.get("schema") != SCHEMA:
        errors.append("unsupported review schema")
    if record.get("source_sha256") != hashlib.sha256(data).hexdigest():
        errors.append("review is stale or belongs to different document bytes; review the current text")
    for field in ("reviewer", "reader_summary"):
        if not nonempty(record.get(field)):
            errors.append(f"{field} must be filled by the reviewer")
    criteria = record.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set(CRITERIA):
        errors.append("criteria must contain each rubric ID exactly once and no unknown IDs")
        return errors, failures
    for key in CRITERIA:
        item = criteria[key]
        if not isinstance(item, dict):
            errors.append(f"{key}: assessment must be an object")
            continue
        result = item.get("result")
        allowed = {"pass", "fail"} | ({"not-applicable"} if key in CONDITIONAL else set())
        if not isinstance(result, str) or result not in allowed:
            errors.append(f"{key}: result is pending or invalid")
        if not nonempty(item.get("reason")):
            errors.append(f"{key}: explain the judgment")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{key}: cite at least one exact source excerpt")
        else:
            for entry in evidence:
                if not isinstance(entry, dict):
                    errors.append(f"{key}: evidence must be an object")
                    continue
                line = entry.get("line")
                quote = entry.get("text")
                if type(line) is not int or not 1 <= line <= len(lines):
                    errors.append(f"{key}: evidence line is outside the document")
                elif not nonempty(quote) or "\n" in quote or "\r" in quote or quote not in lines[line - 1]:
                    errors.append(f"{key}: evidence excerpt does not match its source line")
        if result == "fail":
            failures.append(f"{key}: {item.get('reason', '')}")
    return errors, failures


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "check"):
        sub = commands.add_parser(name)
        sub.add_argument("document", type=Path)
        if name == "check":
            sub.add_argument("review", type=Path)
    args = parser.parse_args(argv)
    try:
        data = args.document.read_bytes()
        if args.command == "prepare":
            print(json.dumps(prepare(data), ensure_ascii=False, indent=2))
            return 0
        record = json.loads(args.review.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        errors, failures = validate(data, record)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Review record error: {exc}", file=sys.stderr)
        return 2
    for error in errors:
        print(f"Review record error: {error}", file=sys.stderr)
    for failure in failures:
        print(f"Reviewer finding: {failure}", file=sys.stderr)
    if errors:
        return 2
    if failures:
        return 1
    print("Review record verified for these exact document bytes. Meaning was judged by the reviewer, not this checker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
