#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


FIELD_RE = re.compile(r"^\s*(?:-\s*)?([A-Za-z][A-Za-z0-9 /-]*):\s*(.*?)\s*$")
HEADING_RE = re.compile(r"^\s*(#{2,6})\s+(.+?)\s*$", re.MULTILINE)
LEAF_RE = re.compile(r"^\s*-\s+([A-Za-z0-9_.-]+):\s*(.*?)\s*$")
LEAF_ID_RE = re.compile(r"^[A-Z][A-Z0-9]+-[A-Z0-9]+-\d+$")
PLACEHOLDER_RE = re.compile(r"(<[^>\n]+>|\bTBD\b|\bTODO\b|\.\.\.)", re.IGNORECASE)
PATH_ITEM_RE = re.compile(r"`([^`]+)`")
GATE_RE = re.compile(r"\bG(?:-[A-Za-z0-9]+)+\b")
SPEC_HASH_RE = re.compile(r"^sha256:[a-f0-9]{64}$")

REQUIRED_FIELDS = (
    "SpecId",
    "SourceId",
    "ParentPlanId",
    "ManifestLeafId",
    "Intent",
    "Anti-scope",
    "Files in scope",
    "Files out of scope",
    "Dependencies",
    "Required gates",
    "Validation",
    "Acceptance criteria",
    "Dispatch mode",
    "One PR contract",
    "Open decisions",
)

DEPTH_TRIGGER_TERMS = (
    "testing",
    "data",
    "coverage",
    "fixture-heavy",
    "fixture heavy",
    "runtime",
    "projection",
    "cross-module",
    "cross module",
    "multi-file",
    "multi file",
)

INLINE_REQUIRED_FIELDS = (
    "Files in scope",
    "Files out of scope",
    "Dependencies",
    "Validation",
    "Acceptance criteria",
    "Dispatch mode",
    "One PR contract",
)

FIELD_ALIASES = {
    "Depends on": "Dependencies",
    "Dispatch": "Dispatch mode",
    "One PR contract": "One PR contract",
    "Spec": "Spec",
}

FORBIDDEN_SIDECAR_FIELDS = {
    "Approval state": "approval state",
    "Dispatch readiness": "dispatch readiness",
    "Authority": "authority semantics",
    "Authority semantics": "authority semantics",
    "Leaves": "leaves",
}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_field_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    return FIELD_ALIASES.get(cleaned, cleaned)


def is_placeholder(value: str) -> bool:
    return not value.strip() or bool(PLACEHOLDER_RE.search(value))


def section_spans(markdown: str) -> list[tuple[str, int, int]]:
    matches = list(HEADING_RE.finditer(markdown))
    spans: list[tuple[str, int, int]] = []
    for index, match in enumerate(matches):
        title = normalize_field_name(match.group(2).strip())
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        spans.append((title, match.end(), end))
    return spans


def parse_fields(markdown: str) -> dict[str, str]:
    fields: dict[str, str] = {}

    for title, start, end in section_spans(markdown):
        body = markdown[start:end].strip()
        if title not in fields:
            fields[title] = body

    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        match = FIELD_RE.match(line)
        if not match:
            continue
        name = normalize_field_name(match.group(1))
        value = match.group(2).strip()
        if value:
            fields[name] = value
            continue
        block: list[str] = []
        label_indent = len(line) - len(line.lstrip())
        for follower in lines[index + 1 :]:
            stripped = follower.strip()
            if not stripped:
                if block:
                    break
                continue
            follower_indent = len(follower) - len(follower.lstrip())
            if follower_indent <= label_indent and FIELD_RE.match(follower):
                break
            if follower_indent <= label_indent and re.match(r"^#{1,6}\s+", follower):
                break
            if follower_indent <= label_indent and stripped.startswith("- ") and FIELD_RE.match(stripped):
                break
            if follower_indent > label_indent or stripped.startswith("- "):
                block.append(follower)
                continue
            break
        fields[name] = "\n".join(block).strip()

    return fields


def list_values(value: str) -> list[str]:
    values: list[str] = []
    for raw in value.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        item = stripped[2:].strip() if stripped.startswith("- ") else stripped
        if not item or is_placeholder(item):
            continue
        values.append(item)
    if not values and value.strip() and not is_placeholder(value):
        values.append(value.strip())
    return values


def normalized_set(value: str) -> set[str]:
    entries = set()
    for item in list_values(value):
        for path in PATH_ITEM_RE.findall(item):
            entries.add(path.strip())
        if not PATH_ITEM_RE.search(item):
            entries.add(item.strip("` "))
    return {entry for entry in entries if entry and entry.lower() != "none"}


def gates(value: str) -> set[str]:
    found = set(GATE_RE.findall(value))
    if found:
        return found
    return normalized_set(value)


def canonical_spec_hash(markdown: str) -> str:
    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def field_has_content(fields: dict[str, str], name: str) -> bool:
    value = fields.get(name, "")
    if is_placeholder(value):
        return False
    return bool(list_values(value))


def parse_manifest_leaf(markdown: str, leaf_id: str | None = None) -> dict[str, str]:
    lines = markdown.splitlines()
    start = None
    parsed_leaf_id = leaf_id
    base_indent = 0

    for index, line in enumerate(lines):
        match = LEAF_RE.match(line)
        if not match:
            continue
        if leaf_id is not None and match.group(1) != leaf_id:
            continue
        start = index
        parsed_leaf_id = match.group(1)
        base_indent = len(line) - len(line.lstrip())
        break

    if start is None:
        return {}

    block = [lines[start]]
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            block.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent and LEAF_RE.match(line):
            break
        block.append(line)

    fields = parse_fields("\n".join(block))
    if parsed_leaf_id:
        fields["ManifestLeafId"] = parsed_leaf_id
    title_match = LEAF_RE.match(lines[start])
    if title_match and title_match.group(2).strip():
        fields["Title"] = title_match.group(2).strip()
    return fields


def source_id_candidates(parent_plan_id: str, manifest_leaf_id: str) -> set[str]:
    return {
        f"{parent_plan_id}#{manifest_leaf_id}",
        f"{parent_plan_id}:{manifest_leaf_id}",
    }


def sidecar_needs_depth_contract(fields: dict[str, str], manifest: dict[str, str]) -> bool:
    haystack = "\n".join(
        value for key, value in {**manifest, **fields}.items() if key not in {"Depth contract"}
    ).lower()
    if any(term in haystack for term in DEPTH_TRIGGER_TERMS):
        return True
    files_in_scope = normalized_set(fields.get("Files in scope", ""))
    if len(files_in_scope) > 1:
        return True
    return any(path.startswith("tests/") or "/tests/" in path or path.endswith("_test.py") for path in files_in_scope)


def check_required_fields(fields: dict[str, str], errors: list[str]) -> None:
    for field in REQUIRED_FIELDS:
        if not field_has_content(fields, field):
            errors.append(f"Missing required field: {field}.")


def check_source_alignment(fields: dict[str, str], manifest: dict[str, str], errors: list[str]) -> None:
    parent_plan_id = fields.get("ParentPlanId", "").strip()
    manifest_leaf_id = fields.get("ManifestLeafId", "").strip()
    source_id = fields.get("SourceId", "").strip()
    if not parent_plan_id or not manifest_leaf_id or not source_id:
        return

    if source_id not in source_id_candidates(parent_plan_id, manifest_leaf_id):
        errors.append(
            "SourceId must align with ParentPlanId and ManifestLeafId "
            f"(expected one of: {', '.join(sorted(source_id_candidates(parent_plan_id, manifest_leaf_id)))})."
        )

    manifest_leaf = manifest.get("ManifestLeafId", "").strip()
    if manifest_leaf and manifest_leaf != manifest_leaf_id:
        errors.append(
            f"ManifestLeafId mismatch: sidecar declares {manifest_leaf_id}, manifest leaf is {manifest_leaf}."
        )
    manifest_source_id = manifest.get("Spec source id", "").strip()
    if manifest_source_id and manifest_source_id != source_id:
        errors.append(
            f"Spec source id mismatch: manifest {manifest_source_id}, sidecar SourceId {source_id}."
        )


def check_subset(
    sidecar_fields: dict[str, str],
    manifest_fields: dict[str, str],
    field: str,
    sidecar_values: set[str],
    manifest_values: set[str],
    errors: list[str],
) -> None:
    if not sidecar_values:
        return
    if not manifest_fields.get(field, "").strip() and manifest_values == set():
        errors.append(f"Sidecar cannot introduce {field}; the manifest leaf does not declare it.")
        return
    extras = sidecar_values - manifest_values
    if extras:
        errors.append(f"Sidecar cannot introduce {field}: {', '.join(sorted(extras))}.")


def check_manifest_authority(fields: dict[str, str], manifest: dict[str, str], errors: list[str]) -> None:
    if not manifest:
        return

    check_subset(
        fields,
        manifest,
        "Files in scope",
        normalized_set(fields.get("Files in scope", "")),
        normalized_set(manifest.get("Files in scope", "")),
        errors,
    )
    check_subset(
        fields,
        manifest,
        "Files out of scope",
        normalized_set(fields.get("Files out of scope", "")),
        normalized_set(manifest.get("Files out of scope", "")),
        errors,
    )
    check_subset(
        fields,
        manifest,
        "Dependencies",
        normalized_set(fields.get("Dependencies", "")),
        normalized_set(manifest.get("Dependencies", "")),
        errors,
    )
    check_subset(
        fields,
        manifest,
        "Required gates",
        gates(fields.get("Required gates", "")),
        gates(manifest.get("Required gates", "")),
        errors,
    )

    sidecar_dispatch = fields.get("Dispatch mode", "").strip()
    manifest_dispatch = manifest.get("Dispatch mode", "").strip()
    if sidecar_dispatch and manifest_dispatch and sidecar_dispatch != manifest_dispatch:
        errors.append(
            f"Sidecar cannot override dispatch mode: sidecar {sidecar_dispatch}, manifest {manifest_dispatch}."
        )

    manifest_hash = manifest.get("Spec hash", "").strip()
    if manifest_hash:
        if not SPEC_HASH_RE.fullmatch(manifest_hash):
            errors.append("Manifest Spec hash must use sha256:<64 lowercase hex chars>.")
            return
        actual_hash = canonical_spec_hash(fields.get("__raw_markdown__", ""))
        if manifest_hash != actual_hash:
            errors.append(f"Spec hash mismatch: manifest {manifest_hash}, actual {actual_hash}.")


def check_forbidden_fields(fields: dict[str, str], errors: list[str]) -> None:
    for field, description in FORBIDDEN_SIDECAR_FIELDS.items():
        if field in fields and field_has_content(fields, field):
            errors.append(f"Sidecar cannot introduce or override {description}: {field}.")
    for field in fields:
        if LEAF_ID_RE.fullmatch(field):
            errors.append(f"Sidecar cannot introduce or override leaves: {field}.")


def validate_sidecar(markdown: str, manifest_markdown: str | None = None, leaf_id: str | None = None) -> ValidationResult:
    fields = parse_fields(markdown)
    fields["__raw_markdown__"] = markdown
    manifest = parse_manifest_leaf(manifest_markdown, leaf_id) if manifest_markdown else {}
    errors: list[str] = []

    check_required_fields(fields, errors)
    check_forbidden_fields(fields, errors)
    check_source_alignment(fields, manifest, errors)
    check_manifest_authority(fields, manifest, errors)

    if sidecar_needs_depth_contract(fields, manifest) and not field_has_content(fields, "Depth contract"):
        errors.append(
            "Missing required field: Depth contract is required for testing/data/coverage/"
            "fixture-heavy/runtime/projection/cross-module/multi-file leaves."
        )

    return ValidationResult(ok=not errors, errors=errors)


def validate_inline_manifest(manifest_markdown: str, leaf_id: str | None = None) -> ValidationResult:
    fields = parse_manifest_leaf(manifest_markdown, leaf_id)
    errors: list[str] = []

    if not fields:
        return ValidationResult(ok=False, errors=["Manifest leaf not found."])

    if fields.get("Spec", "").strip().lower() != "inline":
        errors.append("Inline manifest acceptance requires `Spec: inline`.")

    for field in INLINE_REQUIRED_FIELDS:
        if not field_has_content(fields, field):
            errors.append(f"Inline manifest is missing required field: {field}.")

    if sidecar_needs_depth_contract({}, fields) and not field_has_content(fields, "Depth contract"):
        errors.append(
            "Inline manifest is missing required field: Depth contract for testing/data/coverage/"
            "fixture-heavy/runtime/projection/cross-module/multi-file leaves."
        )

    return ValidationResult(ok=not errors, errors=errors)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Plan Package v0 issue spec sidecars.")
    parser.add_argument("spec", nargs="?", type=Path, help="Issue spec sidecar markdown path.")
    parser.add_argument("--manifest", type=Path, help="Plan or manifest markdown used for authority checks.")
    parser.add_argument("--leaf-id", help="Manifest leaf id to validate against.")
    parser.add_argument("--inline-manifest", action="store_true", help="Validate a manifest leaf with `Spec: inline`.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.inline_manifest:
        if args.manifest is None:
            raise SystemExit("--inline-manifest requires --manifest")
        result = validate_inline_manifest(read_text(args.manifest), args.leaf_id)
    else:
        if args.spec is None:
            raise SystemExit("spec path is required unless --inline-manifest is used")
        manifest_text = read_text(args.manifest) if args.manifest else None
        result = validate_sidecar(read_text(args.spec), manifest_text, args.leaf_id)

    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    elif result.ok:
        print("issue spec validation passed")
    else:
        for error in result.errors:
            print(error, file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
