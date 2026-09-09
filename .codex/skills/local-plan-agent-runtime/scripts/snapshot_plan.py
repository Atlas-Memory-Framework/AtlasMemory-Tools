#!/usr/bin/env python3
# atlas-tools-generated: source=skills/local-plan-agent-runtime/scripts/snapshot_plan.py manifest=atlas-tools.v1 checksum=sha256:b35cbf6bb92af5d177453620e46e726978fbfa61389de234ed26dcf7be5fd22e
# atlas-tools-generated-end
"""Create an immutable snapshot and section index for a markdown plan."""
import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path

HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
SLUG_RE = re.compile(r"[^a-z0-9]+")
PLAN_STATE_RE = re.compile(r"^##\s+Plan State\s*$", re.MULTILINE)
TOP_LEVEL_RE = re.compile(r"^##\s+.+?\s*$", re.MULTILINE)
KEY_VALUE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_ /-]*):\s*(.*?)\s*$")
PERSONA_RE = re.compile(r"^##\s+([a-z0-9-]+)\s*$", re.MULTILINE)

ALLOWED_PLAN_STATE_KEYS = {
    "PlanFormatVersion",
    "PlanId",
    "PlanGroup",
    "PlanKind",
    "ParentPlan",
    "DependsOnPlans",
    "BlocksPlans",
    "AtomicScope",
    "CampaignMetadataAuthority",
    "Status",
    "StructuralStatus",
    "SubstanceStatus",
    "ProjectionApproval",
    "DispatchApproval",
    "CurrentStage",
    "PlanTier",
    "AutomationTarget",
    "DeliveryMode",
    "ContextMode",
    "LastUpdated",
    "PrimaryOwner",
    "BaseBranch",
    "BaseCommit",
    "TargetBranch",
    "Related",
    "NextRequiredUserAction",
    "BlockingDecision",
    "UnresolvedBlockers",
    "RubberStampSignals",
    "LastGateRun",
    "ArtifactAuthorityMode",
}


def sha256_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "section"


def build_sections(text: str):
    lines = text.splitlines(keepends=True)
    headers = []
    for idx, line in enumerate(lines):
        m = HEADER_RE.match(line.rstrip("\n"))
        if m:
            headers.append({
                "level": len(m.group(1)),
                "title": m.group(2).strip(),
                "heading": f"{m.group(1)} {m.group(2).strip()}",
                "start_line": idx + 1,
                "line_index": idx,
            })
    sections = []
    heading_counts = {}
    for i, header in enumerate(headers):
        end_idx = len(lines)
        for nxt in headers[i + 1:]:
            if nxt["level"] <= header["level"]:
                end_idx = nxt["line_index"]
                break
        body = "".join(lines[header["line_index"]:end_idx])
        heading = header["heading"]
        heading_counts[heading] = heading_counts.get(heading, 0) + 1
        sections.append({
            "section_id": f"S{i + 1:04d}-{slugify(header['title'])}",
            "heading": heading,
            "heading_occurrence": heading_counts[heading],
            "level": header["level"],
            "title": header["title"],
            "start_line": header["start_line"],
            "end_line": end_idx,
            "sha256": sha256_text(body),
        })
    return sections


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid package manifest JSON: {path}: {exc}") from exc


def is_relative_to(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def resolve_package_path(package_root: Path, relative_path: str, *, label: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise SystemExit(f"{label} must be a relative package path")
    resolved = (package_root / relative_path).resolve()
    if not is_relative_to(resolved, package_root):
        raise SystemExit(f"{label} escapes package root: {relative_path}")
    return resolved


def validate_declared_hash(path: Path, expected_hash: str | None, label: str) -> str:
    text = path.read_text(encoding="utf-8")
    actual_hash = sha256_text(text)
    if expected_hash and expected_hash != actual_hash:
        raise SystemExit(f"{label} hash mismatch: expected {expected_hash}, got {actual_hash}")
    return actual_hash


def normalized_manifest_members(manifest: dict) -> list[dict]:
    raw_members = manifest.get("members")
    if raw_members is None:
        raw_members = manifest.get("files")
    if not isinstance(raw_members, list) or not raw_members:
        raise SystemExit("package manifest must include non-empty members[] or files[]")
    members = []
    seen = set()
    for index, item in enumerate(raw_members):
        if not isinstance(item, dict):
            raise SystemExit(f"package member {index} must be an object")
        rel_path = item.get("path")
        if not isinstance(rel_path, str) or not rel_path:
            raise SystemExit(f"package member {index} missing path")
        if rel_path in seen:
            raise SystemExit(f"duplicate package member path: {rel_path}")
        seen.add(rel_path)
        members.append({
            "path": rel_path,
            "kind": item.get("kind", ""),
            "hash": item.get("hash") or item.get("sha256") or "",
            "patchable": bool(item.get("patchable", True)),
        })
    return members


def source_plan_manifest_path(manifest: dict) -> str:
    source_plan = manifest.get("source_plan") or {}
    if not isinstance(source_plan, dict):
        raise SystemExit("package manifest source_plan must be an object")
    path = source_plan.get("path")
    if not isinstance(path, str) or not path:
        raise SystemExit("package manifest must include source_plan.path")
    return path


def package_sha256(package_files: list[dict]) -> str:
    payload = [
        {
            "path": item["path"],
            "sha256": item["sha256"],
            "kind": item.get("kind", ""),
            "patchable": bool(item.get("patchable", True)),
        }
        for item in sorted(package_files, key=lambda value: value["path"])
    ]
    return sha256_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def snapshot_package(plan: Path, manifest_path: Path, run_dir: Path) -> tuple[dict, dict, str]:
    package_root = manifest_path.parent.resolve()
    if not is_relative_to(plan, package_root):
        raise SystemExit(f"selected plan is outside package root: {plan}")
    if not manifest_path.is_file():
        raise SystemExit(f"package manifest not found: {manifest_path}")

    manifest = read_json(manifest_path)
    declared_plan = resolve_package_path(package_root, source_plan_manifest_path(manifest), label="source_plan.path")
    if declared_plan != plan:
        raise SystemExit("package manifest source_plan.path does not match selected plan")

    members = normalized_manifest_members(manifest)
    plan_rel = str(plan.relative_to(package_root))
    if plan_rel not in {member["path"] for member in members}:
        members.append({
            "path": plan_rel,
            "kind": "plan",
            "hash": (manifest.get("source_plan") or {}).get("hash", ""),
            "patchable": True,
        })

    package_snapshot = run_dir / "package.snapshot"
    package_snapshot.mkdir(exist_ok=False)
    package_files = []
    sections = []
    for file_index, member in enumerate(sorted(members, key=lambda value: value["path"]), start=1):
        source = resolve_package_path(package_root, member["path"], label=f"package member {member['path']}")
        if not source.is_file():
            raise SystemExit(f"package member is not a file: {member['path']}")
        if source.is_symlink():
            raise SystemExit(f"package member must not be a symlink: {member['path']}")
        file_hash = validate_declared_hash(source, member.get("hash") or None, f"package member {member['path']}")
        snapshot_path = package_snapshot / member["path"]
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, snapshot_path)
        file_id = f"F{file_index:04d}"
        text = source.read_text(encoding="utf-8")
        file_sections = build_sections(text)
        for section in file_sections:
            section["section_id"] = f"{file_id}:{section['section_id']}"
            section["file_id"] = file_id
            section["file_path"] = member["path"]
            section["patchable"] = bool(member.get("patchable", True))
        sections.extend(file_sections)
        package_files.append({
            "file_id": file_id,
            "path": member["path"],
            "kind": member.get("kind", ""),
            "sha256": file_hash,
            "patchable": bool(member.get("patchable", True)),
            "snapshot_path": str(snapshot_path),
        })

    package_hash = package_sha256(package_files)
    package_index = {
        "package_mode": True,
        "package_root": str(package_root),
        "package_manifest_path": str(manifest_path),
        "package_snapshot_path": str(package_snapshot),
        "source_package_sha256": package_hash,
        "plan_path": str(plan),
        "snapshot_path": str(package_snapshot / plan_rel),
        "plan_sha256": next(item["sha256"] for item in package_files if item["path"] == plan_rel),
        "package_files": package_files,
        "sections": sections,
    }
    package_manifest = {
        "package_mode": True,
        "package_manifest_path": str(manifest_path),
        "package_root": str(package_root),
        "package_snapshot_path": str(package_snapshot),
        "source_package_sha256": package_hash,
        "package_files": package_files,
    }
    return package_index, package_manifest, package_hash


def parse_plan_state(text: str):
    match = PLAN_STATE_RE.search(text)
    if not match:
        return {}
    next_match = TOP_LEVEL_RE.search(text, match.end())
    end = next_match.start() if next_match else len(text)
    state_text = text[match.end():end]
    state = {}
    in_fence = False
    for raw in state_text.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        kv = KEY_VALUE_RE.match(line)
        if kv:
            key = kv.group(1).strip()
            if key not in ALLOWED_PLAN_STATE_KEYS:
                continue
            if key in state:
                raise SystemExit(f"duplicate Plan State key: {key}")
            state[key] = kv.group(2).strip()
    return state


def available_personas() -> set[str]:
    personas_path = Path(__file__).resolve().parents[1] / "references" / "personas.md"
    text = personas_path.read_text(encoding="utf-8")
    return set(PERSONA_RE.findall(text))


def build_persona_records(personas: list[str], triggers: list[str], scopes: list[str]):
    allowed = available_personas()
    unknown = [persona for persona in personas if persona not in allowed]
    if unknown:
        valid = ", ".join(sorted(allowed))
        raise SystemExit(f"unknown persona(s): {', '.join(unknown)}. Expected one of: {valid}")
    if triggers and len(triggers) != len(personas):
        raise SystemExit("--persona-trigger must be repeated exactly once per --persona when supplied")
    if scopes and len(scopes) != len(personas):
        raise SystemExit("--persona-scope must be repeated exactly once per --persona when supplied")
    return [
        {
            "id": persona,
            "trigger": triggers[index] if triggers else "",
            "scope": scopes[index] if scopes else "",
        }
        for index, persona in enumerate(personas)
    ]


def ensure_fresh_run_dir(run_dir: Path) -> None:
    if run_dir.exists() and any(run_dir.iterdir()):
        raise SystemExit(f"run directory already exists and is not empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan_path", help="Path to the canonical markdown plan")
    parser.add_argument("--run-dir", default=None, help="Fresh directory for run artifacts")
    parser.add_argument("--out", default=None, help="Fresh directory for run artifacts; package-mode preferred spelling")
    parser.add_argument("--package-manifest", default=None, help="Package manifest JSON for package-mode snapshots")
    parser.add_argument("--mode", default="dry-run", choices=["dry-run", "patch-through-plan"])
    parser.add_argument("--persona", action="append", default=[], help="Authorized worker persona; repeatable")
    parser.add_argument("--persona-trigger", action="append", default=[], help="Reason the corresponding persona was selected; repeat in --persona order")
    parser.add_argument("--persona-scope", action="append", default=[], help="Bounded scope for the corresponding persona; repeat in --persona order")
    parser.add_argument("--decision-policy", default="decision-firewall-required")
    parser.add_argument("--user-approved-patch-through-plan", action="store_true", help="Required with --mode patch-through-plan")
    args = parser.parse_args()

    if not args.run_dir and not args.out:
        raise SystemExit("one of --run-dir or --out is required")
    if args.run_dir and args.out and Path(args.run_dir).resolve() != Path(args.out).resolve():
        raise SystemExit("--run-dir and --out must refer to the same directory when both are supplied")

    if args.mode == "patch-through-plan" and not args.user_approved_patch_through_plan:
        raise SystemExit("patch-through-plan mode requires --user-approved-patch-through-plan")

    plan = Path(args.plan_path).resolve()
    if not plan.exists():
        raise SystemExit(f"plan not found: {plan}")
    if not plan.is_file():
        raise SystemExit(f"plan is not a file: {plan}")

    text = plan.read_text(encoding="utf-8")
    plan_hash = sha256_text(text)
    plan_state = parse_plan_state(text)
    persona_records = build_persona_records(args.persona, args.persona_trigger, args.persona_scope)
    run_dir = Path(args.out or args.run_dir).resolve()
    ensure_fresh_run_dir(run_dir)
    for name in ["tasks", "proposals"]:
        (run_dir / name).mkdir(exist_ok=False)

    package_manifest = None
    package_hash = ""
    if args.package_manifest:
        manifest_path = Path(args.package_manifest).resolve()
        section_index, package_manifest, package_hash = snapshot_package(plan, manifest_path, run_dir)
        sections = section_index["sections"]
        duplicate_headings = sorted({s["heading"] for s in sections if sum(1 for x in sections if x["heading"] == s["heading"]) > 1})
        section_index["duplicate_headings"] = duplicate_headings
        snapshot_path = section_index["snapshot_path"]
    else:
        snapshot = run_dir / "plan.snapshot.md"
        shutil.copyfile(plan, snapshot)
        sections = build_sections(text)
        duplicate_headings = sorted({s["heading"] for s in sections if sum(1 for x in sections if x["heading"] == s["heading"]) > 1})
        section_index = {
            "package_mode": False,
            "plan_path": str(plan),
            "snapshot_path": str(snapshot),
            "plan_sha256": plan_hash,
            "duplicate_headings": duplicate_headings,
            "sections": sections,
        }
        snapshot_path = str(snapshot)
    (run_dir / "section-index.json").write_text(json.dumps(section_index, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "run_created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": args.mode,
        "user_approved_patch_through_plan": bool(args.user_approved_patch_through_plan),
        "canonical_plan_path": str(plan),
        "snapshot_path": snapshot_path,
        "plan_sha256": plan_hash,
        "package_mode": bool(args.package_manifest),
        "source_package_sha256": package_hash,
        "plan_state": plan_state,
        "plan_id": plan_state.get("PlanId", ""),
        "plan_group": plan_state.get("PlanGroup", ""),
        "parent_plan": plan_state.get("ParentPlan", ""),
        "depends_on_plans": plan_state.get("DependsOnPlans", ""),
        "atomic_scope": plan_state.get("AtomicScope", ""),
        "worker_personas": args.persona,
        "worker_persona_records": persona_records,
        "decision_policy": args.decision_policy,
        "forbidden_actions": [
            "edit_canonical_plan",
            "flip_gates_or_approval_state",
            "approve_projection_or_dispatch",
            "invent_user_decisions",
        ],
    }
    if package_manifest:
        manifest.update(package_manifest)
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "run_dir": str(run_dir),
        "plan_sha256": plan_hash,
        "source_package_sha256": package_hash,
        "sections": len(sections),
        "duplicate_headings": duplicate_headings,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
