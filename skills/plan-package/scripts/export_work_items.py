#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

try:
    from compile_plan_package import HASH_RE, canonical_json_text, package_hash
    from validate_plan_package import REQUIRED_LEAF
except ImportError:  # pragma: no cover - used when imported by path in tests.
    def _load_neighbor(name: str) -> ModuleType:
        path = Path(__file__).resolve().with_name(f"{name}.py")
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {name} from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    _compile = sys.modules.get("compile_plan_package") or _load_neighbor("compile_plan_package")
    _validate = sys.modules.get("validate_plan_package") or _load_neighbor("validate_plan_package")
    HASH_RE = _compile.HASH_RE
    canonical_json_text = _compile.canonical_json_text
    package_hash = _compile.package_hash
    REQUIRED_LEAF = _validate.REQUIRED_LEAF


WORK_ITEM_SCHEMA_VERSION = "plan-package-work-items.v0"
WORK_ITEM_FORMAT = "plan-package-work-item.v0"
SCOPE_BUDGET_WARN_AT = 8
SCOPE_BUDGET_FAIL_ABOVE = 12


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array.")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    values = _require_list(value, label)
    result: list[str] = []
    for index, item in enumerate(values):
        if not isinstance(item, str):
            raise ValueError(f"{label}[{index}] must be a string.")
        if item.strip():
            result.append(item.strip())
    return result


def _require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise ValueError(f"{label} must be sha256:<64 lowercase hex chars>.")
    return value


def _validate_compiled_registry(registry: dict[str, Any]) -> None:
    for field in ("schema_version", "package_id", "package_hash", "source_plan", "members", "leaves"):
        if field not in registry:
            raise ValueError(f"Missing required registry field: {field}.")
    _require_hash(registry["package_hash"], "package_hash")
    actual_package_hash = package_hash(registry)
    if registry["package_hash"] != actual_package_hash:
        raise ValueError(f"Package hash mismatch: registry {registry['package_hash']}, actual {actual_package_hash}.")

    source_ids: set[str] = set()
    leaves = _require_list(registry["leaves"], "leaves")
    for index, raw_leaf in enumerate(leaves):
        leaf = _require_mapping(raw_leaf, f"leaves[{index}]")
        for field in REQUIRED_LEAF:
            if field not in leaf:
                raise ValueError(f"Missing required registry leaf field: leaves[{index}].{field}.")
        source_id = leaf.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError(f"leaves[{index}].source_id must be a non-empty string.")
        if source_id in source_ids:
            raise ValueError(f"Duplicate source id: {source_id}.")
        source_ids.add(source_id)
        _require_hash(leaf.get("spec_hash"), f"leaves[{index}].spec_hash")
        _require_mapping(leaf.get("local_export"), f"leaves[{index}].local_export")
        for field in (
            "dependencies",
            "required_gates",
            "files_in_scope",
            "files_out_of_scope",
            "validation",
            "acceptance_criteria",
        ):
            _string_list(leaf.get(field), f"leaves[{index}].{field}")


def _scope_budget_status(leaves: list[dict[str, Any]]) -> dict[str, Any]:
    executable_count = sum(1 for leaf in leaves if _local_export_enabled(leaf))
    if executable_count > SCOPE_BUDGET_FAIL_ABOVE:
        status = "fail"
    elif executable_count > SCOPE_BUDGET_WARN_AT:
        status = "warn"
    else:
        status = "pass"
    return {
        "status": status,
        "executable_leaf_count": executable_count,
        "warn_at": SCOPE_BUDGET_WARN_AT,
        "fail_above": SCOPE_BUDGET_FAIL_ABOVE,
    }


def _local_export_enabled(leaf: dict[str, Any]) -> bool:
    local_export = leaf.get("local_export")
    if not isinstance(local_export, dict):
        return False
    return local_export.get("enabled", True) is not False


def _work_item_for_leaf(
    leaf: dict[str, Any],
    *,
    package_id: str,
    package_hash_value: str,
    source_plan: dict[str, Any],
    scope_budget: dict[str, Any],
) -> dict[str, Any]:
    source_id = str(leaf["source_id"])
    spec_hash = str(leaf["spec_hash"])
    dependencies = _string_list(leaf["dependencies"], f"{source_id}.dependencies")
    write_scope = _string_list(leaf["files_in_scope"], f"{source_id}.files_in_scope")
    validation = _string_list(leaf["validation"], f"{source_id}.validation")
    required_gates = _string_list(leaf["required_gates"], f"{source_id}.required_gates")
    files_out_of_scope = _string_list(leaf["files_out_of_scope"], f"{source_id}.files_out_of_scope")
    acceptance_criteria = _string_list(leaf["acceptance_criteria"], f"{source_id}.acceptance_criteria")
    local_export = _require_mapping(leaf["local_export"], f"{source_id}.local_export")
    dispatch_mode = str(leaf.get("dispatch_mode") or "").strip()
    projection_hints = leaf.get("projection_hints") if isinstance(leaf.get("projection_hints"), dict) else {}
    title = str(projection_hints.get("title") or leaf.get("manifest_leaf_id") or source_id).strip()

    metadata = {
        "source_kind": "plan-package",
        "package_id": package_id,
        "package_hash": package_hash_value,
        "source_plan": source_plan,
        "manifest_leaf_id": leaf.get("manifest_leaf_id"),
        "spec_path": leaf.get("spec_path"),
        "spec_hash": spec_hash,
        "dispatch_mode": dispatch_mode,
        "required_gates": required_gates,
        "files_out_of_scope": files_out_of_scope,
        "acceptance_criteria": acceptance_criteria,
        "scope_budget": scope_budget,
        "local_export_format": local_export.get("format") or WORK_ITEM_FORMAT,
    }

    return {
        "id": source_id,
        "SourceId": source_id,
        "SpecHash": spec_hash,
        "PackageId": package_id,
        "PackageHash": package_hash_value,
        "status": "ready",
        "state": "ready",
        "operation_id": f"atlas-work-item:{source_id}",
        "title": title,
        "source_id": source_id,
        "spec_path": leaf.get("spec_path"),
        "spec_hash": spec_hash,
        "depends_on": dependencies,
        "write_scope": write_scope,
        "validation": validation,
        "dispatch_mode": dispatch_mode,
        "scope_budget_status": scope_budget["status"],
        "scheduler": {
            "depends_on": dependencies,
            "write_scope": write_scope,
            "validation": validation,
            "dispatch_mode": dispatch_mode,
            "scope_budget_status": scope_budget["status"],
        },
        "metadata": metadata,
        "evidence": [
            {
                "type": "plan-package-export",
                "status": "ready",
                "evidence": {
                    "source_id": source_id,
                    "package_id": package_id,
                    "package_hash": package_hash_value,
                    "spec_hash": spec_hash,
                    "format": WORK_ITEM_FORMAT,
                },
            }
        ],
    }


def export_work_items(registry: dict[str, Any]) -> dict[str, Any]:
    _validate_compiled_registry(registry)
    leaves = [leaf for leaf in registry["leaves"] if isinstance(leaf, dict)]
    exportable_leaves = [leaf for leaf in leaves if _local_export_enabled(leaf)]
    scope_budget = _scope_budget_status(leaves)
    package_id = str(registry["package_id"])
    package_hash_value = str(registry["package_hash"])
    source_plan = _require_mapping(registry["source_plan"], "source_plan")
    work_items = [
        _work_item_for_leaf(
            leaf,
            package_id=package_id,
            package_hash_value=package_hash_value,
            source_plan=source_plan,
            scope_budget=scope_budget,
        )
        for leaf in exportable_leaves
    ]
    return {
        "version": 1,
        "schema_version": WORK_ITEM_SCHEMA_VERSION,
        "source": {
            "kind": "plan-package",
            "package_id": package_id,
            "package_hash": package_hash_value,
            "source_plan": source_plan,
            "scope_budget": scope_budget,
        },
        "work_items": work_items,
    }


def export_work_items_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid package registry JSON: {exc}.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Package registry JSON must be an object.")
    return export_work_items(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export local work-item records from compiled Plan Package v0 metadata.")
    parser.add_argument("registry", type=Path, help="Compiled package registry JSON.")
    parser.add_argument("--out", type=Path, help="Write local work-item store JSON to this path instead of stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = canonical_json_text(export_work_items_file(args.registry))
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
