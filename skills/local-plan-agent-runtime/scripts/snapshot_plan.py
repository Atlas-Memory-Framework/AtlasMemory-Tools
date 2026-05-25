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
        "worker_personas": args.persona,
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
