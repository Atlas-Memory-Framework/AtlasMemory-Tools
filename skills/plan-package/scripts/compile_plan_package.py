#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


SCHEMA_VERSION = "plan-package.v0"
HASH_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
LEAF_RE = re.compile(r"^\s*-\s+([A-Za-z0-9_.-]+):\s*(.*?)\s*$")
PLAN_ID_RE = re.compile(r"^PlanId:\s*(.+?)\s*$", re.MULTILINE)


def _load_issue_spec() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "issue-spec" / "scripts" / "validate_issue_spec.py"
    spec = importlib.util.spec_from_file_location("validate_issue_spec", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load issue spec validator from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ISSUE_SPEC = _load_issue_spec()


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"


def text_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def sort_json_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sort_json_keys(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [sort_json_keys(item) for item in value]
    return value


def canonical_json_text(payload: Any) -> str:
    ordered = sort_json_keys(payload)
    return json.dumps(ordered, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def canonical_json_hash(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_text(payload).encode("utf-8")).hexdigest()


def package_hash(registry: dict[str, Any]) -> str:
    preimage = {key: value for key, value in registry.items() if key != "package_hash"}
    return canonical_json_hash(preimage)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def confined_path(root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path escapes package root: {raw_path}")
    root_real = root.resolve()
    resolved = (root_real / path).resolve()
    try:
        resolved.relative_to(root_real)
    except ValueError as exc:
        raise ValueError(f"path escapes package root: {raw_path}") from exc
    return resolved


def relative_to_root(root: Path, path: Path) -> str:
    root_real = root.resolve()
    resolved = path.resolve()
    try:
        return resolved.relative_to(root_real).as_posix()
    except ValueError as exc:
        raise ValueError(f"path escapes package root: {path}") from exc


def plan_id_from_markdown(markdown: str, plan_path: Path) -> str:
    match = PLAN_ID_RE.search(markdown)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return re.sub(r"\.plan$", "", plan_path.stem)


def leaf_blocks(markdown: str) -> list[tuple[str, str, str]]:
    lines = markdown.splitlines()
    blocks: list[tuple[str, str, str]] = []
    in_manifest = False
    current_id: str | None = None
    current_lines: list[str] = []
    current_title = ""
    current_indent = 0

    def flush() -> None:
        nonlocal current_id, current_lines, current_title
        if current_id is not None:
            blocks.append((current_id, current_title, "\n".join(current_lines)))
        current_id = None
        current_lines = []
        current_title = ""

    for line in lines:
        if line.startswith("## "):
            if in_manifest:
                flush()
            in_manifest = line.strip() in {
                "## Automation Issue Manifest",
                "## Automation Issue Manifest ",
            }
            continue
        if not in_manifest:
            continue
        match = LEAF_RE.match(line)
        if match:
            indent = len(line) - len(line.lstrip())
            if current_id is None or indent <= current_indent:
                flush()
                current_id = match.group(1)
                current_title = match.group(2).strip()
                current_indent = indent
                current_lines = [line]
                continue
        if current_id is not None:
            current_lines.append(line)
    if in_manifest:
        flush()
    return blocks


def field_values(value: str) -> list[str]:
    return [item.strip("` ") for item in ISSUE_SPEC.list_values(value) if item.strip("` ").lower() != "none"]


def field_set_values(value: str) -> list[str]:
    return sorted(ISSUE_SPEC.normalized_set(value))


def gate_values(value: str) -> list[str]:
    return sorted(gate for gate in ISSUE_SPEC.gates(value) if gate.lower() != "none")


def first_field(fields: dict[str, str], *names: str) -> str:
    for name in names:
        value = fields.get(name, "").strip()
        if value:
            return value
    return ""


def compile_registry(plan_path: Path, *, root: Path | None = None, package_id: str | None = None) -> dict[str, Any]:
    root = root.resolve() if root else plan_path.resolve().parent
    plan = confined_path(root, relative_to_root(root, plan_path))
    plan_rel = relative_to_root(root, plan)
    plan_markdown = read_text(plan)
    resolved_package_id = package_id or plan_id_from_markdown(plan_markdown, plan)
    source_plan_hash = text_hash(plan_markdown)

    members: dict[str, dict[str, Any]] = {
        plan_rel: {
            "path": plan_rel,
            "kind": "source_plan",
            "hash": source_plan_hash,
            "patchable": False,
        }
    }
    leaves: list[dict[str, Any]] = []
    source_ids: set[str] = set()

    for manifest_leaf_id, title, block in leaf_blocks(plan_markdown):
        manifest_fields = ISSUE_SPEC.parse_fields(block)
        manifest_fields["ManifestLeafId"] = manifest_leaf_id
        manifest_fields["Title"] = title
        spec_path = first_field(manifest_fields, "Spec path", "SpecPath")
        spec_rel: str | None = None
        if spec_path:
            spec_rel = relative_to_root(root, confined_path(root, spec_path))
            spec_markdown = read_text(root / spec_rel)
            validation = ISSUE_SPEC.validate_sidecar(spec_markdown, plan_markdown, manifest_leaf_id)
            if not validation.ok:
                raise ValueError(f"{manifest_leaf_id}: " + "; ".join(validation.errors))

            spec_fields = ISSUE_SPEC.parse_fields(spec_markdown)
            actual_spec_hash = ISSUE_SPEC.canonical_spec_hash(spec_markdown)
            declared_spec_hash = first_field(manifest_fields, "Spec hash", "SpecHash")
            if declared_spec_hash and declared_spec_hash != actual_spec_hash:
                raise ValueError(
                    f"{manifest_leaf_id}: Spec hash mismatch: manifest {declared_spec_hash}, actual {actual_spec_hash}"
                )
        else:
            validation = ISSUE_SPEC.validate_inline_manifest(plan_markdown, manifest_leaf_id)
            if not validation.ok:
                raise ValueError(f"{manifest_leaf_id}: " + "; ".join(validation.errors))

            spec_fields = manifest_fields
            actual_spec_hash = ISSUE_SPEC.canonical_spec_hash(block)

        source_id = first_field(spec_fields, "SourceId", "Spec source id") or f"{resolved_package_id}#{manifest_leaf_id}"
        if source_id in source_ids:
            raise ValueError(f"Duplicate source id: {source_id}")
        source_ids.add(source_id)

        dependencies = field_set_values(first_field(spec_fields, "Dependencies") or first_field(manifest_fields, "Depends on"))
        required_gates = gate_values(first_field(spec_fields, "Required gates") or first_field(manifest_fields, "Required gates"))
        files_in_scope = field_set_values(first_field(spec_fields, "Files in scope") or first_field(manifest_fields, "Files in scope"))
        files_out_of_scope = field_set_values(
            first_field(spec_fields, "Files out of scope") or first_field(manifest_fields, "Files out of scope")
        )
        dispatch_mode = first_field(spec_fields, "Dispatch mode", "Dispatch") or first_field(manifest_fields, "Dispatch mode", "Dispatch")
        validation_steps = field_values(first_field(spec_fields, "Validation") or first_field(manifest_fields, "Validation"))
        acceptance_criteria = field_values(
            first_field(spec_fields, "Acceptance criteria") or first_field(manifest_fields, "Acceptance criteria")
        )

        if spec_rel is not None:
            members[spec_rel] = {
                "path": spec_rel,
                "kind": "issue_spec",
                "hash": actual_spec_hash,
                "patchable": True,
            }
        leaves.append(
            {
                "source_id": source_id,
                "manifest_leaf_id": manifest_leaf_id,
                "spec_path": spec_rel,
                "spec_hash": actual_spec_hash,
                "dependencies": dependencies,
                "required_gates": required_gates,
                "files_in_scope": files_in_scope,
                "files_out_of_scope": files_out_of_scope,
                "dispatch_mode": dispatch_mode,
                "validation": validation_steps,
                "acceptance_criteria": acceptance_criteria,
                "projection_hints": {
                    "mode": "optional-github-issue",
                    "title": f"[{manifest_leaf_id}] {title}".strip(),
                },
                "local_export": {
                    "enabled": dispatch_mode.strip().lower() != "tracking-only",
                    "format": "plan-package-work-item.v0",
                    "source_id": source_id,
                    "spec_path": spec_rel,
                    "spec_hash": actual_spec_hash,
                },
            }
        )

    registry: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "package_id": resolved_package_id,
        "package_hash": "",
        "source_plan": {
            "path": plan_rel,
            "hash": source_plan_hash,
        },
        "members": [members[key] for key in sorted(members)],
        "leaves": sorted(leaves, key=lambda item: item["source_id"]),
    }
    registry["package_hash"] = package_hash(registry)
    return registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile a deterministic Plan Package v0 registry.")
    parser.add_argument("plan", type=Path, help="Selected markdown plan artifact.")
    parser.add_argument("--root", type=Path, help="Package root. Defaults to the plan directory.")
    parser.add_argument("--package-id", help="Override package id. Defaults to PlanId.")
    parser.add_argument("--out", type=Path, help="Write registry JSON to this path instead of stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = compile_registry(args.plan, root=args.root, package_id=args.package_id)
        output = canonical_json_text(registry)
        if args.out:
            args.out.write_text(output, encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(output)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
