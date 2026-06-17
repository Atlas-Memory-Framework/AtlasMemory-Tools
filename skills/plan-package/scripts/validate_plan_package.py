#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from compile_plan_package import (
        HASH_RE,
        SCHEMA_VERSION,
        compile_registry,
        confined_path,
        package_hash,
        text_hash,
    )
except ImportError:  # pragma: no cover - used when imported as a package-like module in tests.
    from .compile_plan_package import (  # type: ignore
        HASH_RE,
        SCHEMA_VERSION,
        compile_registry,
        confined_path,
        package_hash,
        text_hash,
    )


REQUIRED_TOP_LEVEL = ("schema_version", "package_id", "package_hash", "source_plan", "members", "leaves")
REQUIRED_SOURCE_PLAN = ("path", "hash")
REQUIRED_MEMBER = ("path", "kind", "hash", "patchable")
REQUIRED_LEAF = (
    "source_id",
    "manifest_leaf_id",
    "spec_path",
    "spec_hash",
    "dependencies",
    "required_gates",
    "files_in_scope",
    "files_out_of_scope",
    "dispatch_mode",
    "validation",
    "acceptance_criteria",
    "projection_hints",
    "local_export",
)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


def _is_mapping(value: Any) -> bool:
    return isinstance(value, dict)


def _require_fields(mapping: dict[str, Any], fields: tuple[str, ...], prefix: str, errors: list[str]) -> None:
    for field in fields:
        if field not in mapping:
            errors.append(f"Missing required registry field: {prefix}{field}.")


def _validate_hash(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        errors.append(f"Malformed hash for {label}: expected sha256:<64 lowercase hex chars>.")


def _validate_path(root: Path, raw_path: Any, label: str, errors: list[str]) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        errors.append(f"{label} must be a non-empty relative path.")
        return None
    try:
        return confined_path(root, raw_path)
    except ValueError as exc:
        errors.append(str(exc))
        return None


def _validate_member_files(root: Path, registry: dict[str, Any], errors: list[str]) -> None:
    source_plan = registry.get("source_plan", {})
    required_paths = {source_plan.get("path")} if isinstance(source_plan, dict) else set()
    for leaf in registry.get("leaves", []):
        if isinstance(leaf, dict):
            required_paths.add(leaf.get("spec_path"))
    required_paths = {path for path in required_paths if isinstance(path, str)}

    member_paths: set[str] = set()
    for index, member in enumerate(registry.get("members", [])):
        if not isinstance(member, dict):
            errors.append(f"members[{index}] must be an object.")
            continue
        _require_fields(member, REQUIRED_MEMBER, f"members[{index}].", errors)
        path = member.get("path")
        resolved = _validate_path(root, path, f"members[{index}].path", errors)
        if isinstance(path, str):
            if path in member_paths:
                errors.append(f"Duplicate package member path: {path}.")
            member_paths.add(path)
        _validate_hash(member.get("hash"), f"members[{index}].hash", errors)
        if "patchable" in member and not isinstance(member.get("patchable"), bool):
            errors.append(f"members[{index}].patchable must be boolean.")
        if resolved is not None:
            if not resolved.exists():
                errors.append(f"Missing package member: {path}.")
            elif isinstance(member.get("hash"), str) and HASH_RE.fullmatch(member["hash"]):
                actual = text_hash(resolved.read_text(encoding="utf-8"))
                if member["hash"] != actual:
                    errors.append(f"Hash mismatch for member {path}: registry {member['hash']}, actual {actual}.")

    for required_path in sorted(required_paths):
        if required_path not in member_paths:
            errors.append(f"Missing package member record: {required_path}.")


def _validate_leaves(registry: dict[str, Any], errors: list[str]) -> None:
    leaves = registry.get("leaves")
    if not isinstance(leaves, list):
        errors.append("leaves must be an array.")
        return

    source_ids: set[str] = set()
    manifest_ids: set[str] = set()
    for index, leaf in enumerate(leaves):
        if not isinstance(leaf, dict):
            errors.append(f"leaves[{index}] must be an object.")
            continue
        _require_fields(leaf, REQUIRED_LEAF, f"leaves[{index}].", errors)
        source_id = leaf.get("source_id")
        manifest_leaf_id = leaf.get("manifest_leaf_id")
        if isinstance(source_id, str):
            if source_id in source_ids:
                errors.append(f"Duplicate source id: {source_id}.")
            source_ids.add(source_id)
        if isinstance(manifest_leaf_id, str):
            manifest_ids.add(manifest_leaf_id)
        _validate_hash(leaf.get("spec_hash"), f"leaves[{index}].spec_hash", errors)
        for field in (
            "dependencies",
            "required_gates",
            "files_in_scope",
            "files_out_of_scope",
            "validation",
            "acceptance_criteria",
        ):
            if field in leaf and not isinstance(leaf.get(field), list):
                errors.append(f"leaves[{index}].{field} must be an array.")
        for field in ("projection_hints", "local_export"):
            if field in leaf and not isinstance(leaf.get(field), dict):
                errors.append(f"leaves[{index}].{field} must be an object.")

    known_dependencies = source_ids | manifest_ids
    for index, leaf in enumerate(leaves):
        if not isinstance(leaf, dict) or not isinstance(leaf.get("dependencies"), list):
            continue
        for dependency in leaf["dependencies"]:
            if not isinstance(dependency, str):
                errors.append(f"leaves[{index}].dependencies entries must be strings.")
                continue
            if dependency.lower() != "none" and dependency not in known_dependencies:
                errors.append(f"Dependency mismatch for {leaf.get('source_id', index)}: unknown dependency {dependency}.")


def validate_registry(registry: dict[str, Any], *, root: Path) -> ValidationResult:
    root = root.resolve()
    errors: list[str] = []
    _require_fields(registry, REQUIRED_TOP_LEVEL, "", errors)

    if registry.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}.")
    _validate_hash(registry.get("package_hash"), "package_hash", errors)
    if isinstance(registry.get("package_hash"), str) and HASH_RE.fullmatch(registry["package_hash"]):
        actual_package_hash = package_hash(registry)
        if registry["package_hash"] != actual_package_hash:
            errors.append(
                f"Package hash mismatch: registry {registry['package_hash']}, actual {actual_package_hash}."
            )

    source_plan = registry.get("source_plan")
    if not isinstance(source_plan, dict):
        errors.append("source_plan must be an object.")
    else:
        _require_fields(source_plan, REQUIRED_SOURCE_PLAN, "source_plan.", errors)
        plan_path = _validate_path(root, source_plan.get("path"), "source_plan.path", errors)
        _validate_hash(source_plan.get("hash"), "source_plan.hash", errors)
        if plan_path is not None:
            if not plan_path.exists():
                errors.append(f"Missing source plan: {source_plan.get('path')}.")
            elif isinstance(source_plan.get("hash"), str) and HASH_RE.fullmatch(source_plan["hash"]):
                actual = text_hash(plan_path.read_text(encoding="utf-8"))
                if source_plan["hash"] != actual:
                    errors.append(
                        f"Hash mismatch for source_plan.path: registry {source_plan['hash']}, actual {actual}."
                    )

    if not isinstance(registry.get("members"), list):
        errors.append("members must be an array.")
    else:
        _validate_member_files(root, registry, errors)

    _validate_leaves(registry, errors)

    if isinstance(source_plan, dict) and isinstance(source_plan.get("path"), str):
        try:
            compiled = compile_registry(root / source_plan["path"], root=root, package_id=registry.get("package_id"))
        except Exception as exc:
            errors.append(f"Could not recompile registry: {exc}")
        else:
            compiled_by_source = {leaf["source_id"]: leaf for leaf in compiled["leaves"]}
            for leaf in registry.get("leaves", []):
                if not isinstance(leaf, dict) or not isinstance(leaf.get("source_id"), str):
                    continue
                compiled_leaf = compiled_by_source.get(leaf["source_id"])
                if compiled_leaf is None:
                    errors.append(f"Registry leaf is not present in source plan/specs: {leaf['source_id']}.")
                    continue
                for field in ("spec_hash", "dependencies"):
                    if leaf.get(field) != compiled_leaf.get(field):
                        errors.append(
                            f"Dependency/spec mismatch for {leaf['source_id']}: field {field} "
                            f"is {leaf.get(field)!r}, expected {compiled_leaf.get(field)!r}."
                        )

    return ValidationResult(ok=not errors, errors=errors)


def validate_registry_file(path: Path, *, root: Path | None = None) -> ValidationResult:
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ValidationResult(ok=False, errors=[f"Invalid JSON: {exc}."])
    if not isinstance(registry, dict):
        return ValidationResult(ok=False, errors=["Registry JSON must be an object."])
    return validate_registry(registry, root=(root or path.parent))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a Plan Package v0 registry.")
    parser.add_argument("registry", type=Path, help="Compiled package registry JSON.")
    parser.add_argument("--root", type=Path, help="Package root. Defaults to the registry directory.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation result.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_registry_file(args.registry, root=args.root)
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    elif result.ok:
        print("plan package validation passed")
    else:
        for error in result.errors:
            print(error, file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
