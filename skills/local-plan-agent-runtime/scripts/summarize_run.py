#!/usr/bin/env python3
"""Summarize validated JSON proposal files for a local plan agent runtime run."""
import argparse
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("validate_proposal", THIS_DIR / "validate_proposal.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, str(exc)


def markdown_cell(value) -> str:
    text = str(value or "").replace("\n", " ").replace("\r", " ")
    text = text.replace("|", "\\|")
    return text.strip()


def safe_output_path(run_dir: Path, output_arg: str | None) -> Path:
    if output_arg is None:
        return run_dir / "run-report.md"
    output = Path(output_arg).resolve()
    if output != run_dir and run_dir not in output.parents:
        raise SystemExit(f"output path must be inside run directory: {run_dir}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--output", default=None)
    parser.add_argument("--allow-canonical-changed", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    proposals_dir = run_dir / "proposals"
    section_index_path = run_dir / "section-index.json"
    if not section_index_path.is_file():
        raise SystemExit(f"missing section index: {section_index_path}")
    section_index = json.loads(section_index_path.read_text(encoding="utf-8"))

    rows = []
    by_section = defaultdict(list)
    errors = []
    for path in sorted(proposals_dir.glob("*.json")):
        proposal, error = load(path)
        if error:
            errors.append((path.name, error))
            continue
        validation_errors = validator.validate(proposal, section_index, check_canonical=not args.allow_canonical_changed)
        if validation_errors:
            errors.append((path.name, "; ".join(validation_errors)))
            continue
        persona = proposal.get("persona", path.stem)
        for finding in proposal.get("findings", []):
            rows.append({
                "persona": persona,
                "id": finding.get("id", ""),
                "severity": finding.get("severity", ""),
                "section": finding.get("section") or finding.get("section_id", ""),
                "issue": finding.get("concrete_issue", ""),
                "user_decision": bool(finding.get("requires_user_decision")),
            })
        for patch in proposal.get("patches", []):
            target = patch.get("target_section_id") or patch.get("target_section", "")
            if target and patch.get("patch_type") != "no-patch":
                by_section[target].append(f"{persona}:{patch.get('id', '')}")

    lines = ["# Local Plan Agent Runtime Run Report", ""]
    if errors:
        lines.extend(["## Rejected or malformed proposal files", ""])
        for name, error in errors:
            lines.append(f"- `{markdown_cell(name)}`: {markdown_cell(error)}")
        lines.append("")
    lines.extend(["## Findings", "", "| Severity | Finding | Persona | Section | User decision | Issue |", "|---|---|---|---|---|---|"])
    for row in rows:
        lines.append(f"| {markdown_cell(row['severity'])} | {markdown_cell(row['id'])} | {markdown_cell(row['persona'])} | {markdown_cell(row['section'])} | {markdown_cell(row['user_decision'])} | {markdown_cell(row['issue'])} |")
    lines.append("")
    lines.extend(["## Mechanical patch conflict hints", ""])
    conflict_count = 0
    for section, patches in sorted(by_section.items()):
        if len(patches) > 1:
            conflict_count += 1
            lines.append(f"- `{markdown_cell(section)}` has multiple proposed patches: {markdown_cell(', '.join(patches))}")
    if conflict_count == 0:
        lines.append("- None detected by target section count.")
    lines.append("- Semantic conflicts still require manager review against `references/reconciliation.md`.")
    lines.append("")
    lines.extend(["## Disposition table template", "", "| Finding | Source persona | Disposition | Reason | User decision needed |", "|---|---|---|---|---|"])
    for row in rows:
        lines.append(f"| {markdown_cell(row['id'])} | {markdown_cell(row['persona'])} | Pending |  | {markdown_cell(row['user_decision'])} |")
    text = "\n".join(lines) + "\n"
    output = safe_output_path(run_dir, args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(json.dumps({"report": str(output), "findings": len(rows), "potential_conflicts": conflict_count, "rejected_or_malformed": len(errors)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
