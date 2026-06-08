#!/usr/bin/env python3
"""Validate a JSON worker proposal for local-plan-agent-runtime."""
import argparse
import hashlib
import json
import re
from pathlib import Path

FORBIDDEN_STATUS_RE = re.compile(
    r"\b(Status|CurrentStage|StructuralStatus|SubstanceStatus|ProjectionApproval|DispatchApproval|ApprovedForProjection|ApprovedForDispatch|Approved|Gate Results|PlanReadiness|PlanningReviewsComplete|HumanReadabilityReview)\b",
    re.IGNORECASE,
)
PROTECTED_SECTION_RE = re.compile(r"\b(Plan State|Gate Results|Planning Reviews|Decision Log)\b", re.IGNORECASE)
SEVERITIES = {"critical", "high", "medium", "low"}
PATCH_TYPES = {"section-replacement", "section-insert", "decision-log-entry", "no-patch"}
REQUIRED_TOP = ["agent_id", "persona", "source_plan_path", "source_plan_sha256", "scope", "summary", "findings", "patches", "human_decisions", "blocked_items"]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc}") from exc


def validate(proposal, section_index, *, check_canonical=True):
    errors = []
    for key in REQUIRED_TOP:
        if key not in proposal:
            errors.append(f"missing top-level field: {key}")

    expected_hash = section_index.get("plan_sha256")
    if proposal.get("source_plan_sha256") != expected_hash:
        errors.append("source_plan_sha256 does not match section index")

    expected_path = str(Path(section_index.get("plan_path", "")).resolve())
    proposal_path = proposal.get("source_plan_path")
    if proposal_path and str(Path(proposal_path).resolve()) != expected_path:
        errors.append("source_plan_path does not match section index plan_path")

    if check_canonical and expected_path:
        plan = Path(expected_path)
        if plan.exists() and plan.is_file():
            current_hash = sha256_text(plan.read_text(encoding="utf-8"))
            if current_hash != expected_hash:
                errors.append("canonical plan content changed since snapshot")

    sections_by_id = {s.get("section_id"): s for s in section_index.get("sections", [])}
    headings = {}
    for section in section_index.get("sections", []):
        headings.setdefault(section.get("heading"), []).append(section)

    finding_ids = set()
    decision_findings = set()
    for i, finding in enumerate(proposal.get("findings", [])):
        fid = finding.get("id")
        if not fid:
            errors.append(f"finding {i} missing id")
        else:
            finding_ids.add(fid)
        if finding.get("severity") not in SEVERITIES:
            errors.append(f"finding {fid or i} has invalid severity")
        section_id = finding.get("section_id")
        section_heading = finding.get("section")
        if not section_id:
            errors.append(f"finding {fid or i} missing section_id")
        elif section_id not in sections_by_id:
            errors.append(f"finding {fid or i} references unknown section_id {section_id}")
        if section_heading and section_heading not in headings:
            errors.append(f"finding {fid or i} references unknown section heading {section_heading}")
        if not finding.get("concrete_issue"):
            errors.append(f"finding {fid or i} missing concrete_issue")
        if not finding.get("why_it_matters"):
            errors.append(f"finding {fid or i} missing why_it_matters")
        if not isinstance(finding.get("evidence"), list) or not finding.get("evidence"):
            errors.append(f"finding {fid or i} needs non-empty evidence list")
        if finding.get("requires_user_decision"):
            decision_findings.add(fid)
            opts = finding.get("decision_options") or {}
            if not all(opts.get(k) for k in ["A", "B", "C"]):
                errors.append(f"finding {fid or i} requires A/B/C decision_options")

    for i, patch in enumerate(proposal.get("patches", [])):
        pid = patch.get("id") or f"patch {i}"
        patch_type = patch.get("patch_type")
        if patch_type not in PATCH_TYPES:
            errors.append(f"{pid} has invalid patch_type")
        linked = patch.get("finding_ids", [])
        if patch_type != "no-patch" and not linked:
            errors.append(f"{pid} must link to finding_ids")
        for fid in linked:
            if fid not in finding_ids:
                errors.append(f"{pid} links unknown finding id {fid}")
        if any(fid in decision_findings for fid in linked) and patch_type != "no-patch":
            errors.append(f"{pid} links to a finding requiring user decision and must be no-patch")

        target_id = patch.get("target_section_id")
        target_heading = patch.get("target_section")
        if patch_type in {"section-replacement", "section-insert"}:
            if not target_id:
                errors.append(f"{pid} missing target_section_id")
            elif target_id not in sections_by_id:
                errors.append(f"{pid} target_section_id not found in section index: {target_id}")
            else:
                section = sections_by_id[target_id]
                if patch.get("target_section_sha256") != section.get("sha256"):
                    errors.append(f"{pid} target_section_sha256 is stale or missing")
                if target_heading and target_heading != section.get("heading"):
                    errors.append(f"{pid} target_section does not match target_section_id heading")
                if PROTECTED_SECTION_RE.search(section.get("heading", "")):
                    errors.append(f"{pid} targets protected status/review/decision section")
        replacement = patch.get("replacement_text", "") or ""
        if patch_type not in {"no-patch", "decision-log-entry"} and not replacement.strip():
            errors.append(f"{pid} missing replacement_text")
        if replacement and FORBIDDEN_STATUS_RE.search(replacement):
            errors.append(f"{pid} appears to modify status/gate/approval fields")

    for i, decision in enumerate(proposal.get("human_decisions", [])):
        opts = decision.get("options", {})
        if not all(k in opts and opts[k] for k in ["A", "B", "C"]):
            errors.append(f"human_decision {decision.get('id', i)} must include A/B/C options")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal_json")
    parser.add_argument("--section-index", required=True)
    parser.add_argument("--allow-canonical-changed", action="store_true")
    args = parser.parse_args()

    proposal = load_json(args.proposal_json)
    section_index = load_json(args.section_index)
    errors = validate(proposal, section_index, check_canonical=not args.allow_canonical_changed)
    result = {"proposal": str(Path(args.proposal_json).resolve()), "valid": not errors, "errors": errors}
    print(json.dumps(result, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
