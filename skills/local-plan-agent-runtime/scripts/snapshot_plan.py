#!/usr/bin/env python3
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
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    parser.add_argument("--run-dir", required=True, help="Fresh directory for run artifacts")
    parser.add_argument("--mode", default="dry-run", choices=["dry-run", "patch-through-plan"])
    parser.add_argument("--persona", action="append", default=[], help="Authorized worker persona; repeatable")
    parser.add_argument("--persona-trigger", action="append", default=[], help="Reason the corresponding persona was selected; repeat in --persona order")
    parser.add_argument("--persona-scope", action="append", default=[], help="Bounded scope for the corresponding persona; repeat in --persona order")
    parser.add_argument("--decision-policy", default="decision-firewall-required")
    parser.add_argument("--user-approved-patch-through-plan", action="store_true", help="Required with --mode patch-through-plan")
    args = parser.parse_args()

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
    run_dir = Path(args.run_dir).resolve()
    ensure_fresh_run_dir(run_dir)
    for name in ["tasks", "proposals"]:
        (run_dir / name).mkdir(exist_ok=False)

    snapshot = run_dir / "plan.snapshot.md"
    shutil.copyfile(plan, snapshot)
    sections = build_sections(text)
    duplicate_headings = sorted({s["heading"] for s in sections if sum(1 for x in sections if x["heading"] == s["heading"]) > 1})
    section_index = {
        "plan_path": str(plan),
        "snapshot_path": str(snapshot),
        "plan_sha256": plan_hash,
        "duplicate_headings": duplicate_headings,
        "sections": sections,
    }
    (run_dir / "section-index.json").write_text(json.dumps(section_index, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "run_created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": args.mode,
        "user_approved_patch_through_plan": bool(args.user_approved_patch_through_plan),
        "canonical_plan_path": str(plan),
        "snapshot_path": str(snapshot),
        "plan_sha256": plan_hash,
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
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "plan_sha256": plan_hash, "sections": len(sections), "duplicate_headings": duplicate_headings}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
