#!/usr/bin/env python3
# atlas-tools-generated: source=skills/plan/scripts/validate_plan.py manifest=atlas-tools.v1 checksum=sha256:ebcdcde52d980e34c98d16744840ae73c6b57ee2db0afea678d03808d37fdf7e
# atlas-tools-generated-end
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


TOP_LEVEL_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
SUBSECTION_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
KEY_VALUE_RE = re.compile(r"^(?:-\s*)?([A-Za-z][A-Za-z0-9_ /-]*):\s*(.*?)\s*$")
SOURCE_FACT_RE = re.compile(r"\(source:\s*(file|command|user|issue)\)", re.IGNORECASE)
REVIEWED_HASH_RE = re.compile(r"ReviewedPlanHash:\s*(?:sha256:)?([a-f0-9]{64})\b", re.IGNORECASE)
REFRESHED_AT_RE = re.compile(r"RefreshedAt:\s*([0-9T:\-+.Z]+)")
REFRESHED_DATE_RE = re.compile(r"(?:^|\s|\()Refreshed:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\b", re.IGNORECASE)
LEGACY_REFRESHED_DATE_RE = re.compile(r"\(refreshed\s+([0-9]{4}-[0-9]{2}-[0-9]{2})\)", re.IGNORECASE)
GATE_TOKEN_RE = re.compile(r"\bG(?:-[A-Za-z0-9]+)+\b")
DISALLOWED_DEP_TOKEN_RE = re.compile(
    r"\b(?:G(?:-[A-Za-z0-9]+)+|MP(?:-[A-Z0-9]+|\d+)|DR(?:-[A-Za-z0-9]+)+|A\d+|R\d+)\b",
    re.IGNORECASE,
)
PLACEHOLDER_RE = re.compile(r"(<[^>\n]+>|\.\.\.|\bTBD\b|\bto be decided\b|\bchoose later\b|\bor decide later\b)", re.IGNORECASE)
LEAF_ITEM_RE = re.compile(r"^-\s+([A-Za-z0-9_.-]+):\s*(.*?)\s*$")
DR_HEADING_RE = re.compile(r"^###\s+(DR-[A-Za-z0-9-]+):?.*$", re.MULTILINE)

PLANNING_META_TERMS = (
    "plan",
    "artifact",
    "gate",
    "issue manifest",
    "registry",
    "projection",
    "dispatch",
)

APPROVAL_FIELDS = {
    "Status": {"Approved", "InBuild", "Shipped"},
    "StructuralStatus": {"StructurallyComplete"},
    "SubstanceStatus": {"SubstantivelyReviewed"},
    "ProjectionApproval": {"ApprovedForProjection"},
    "DispatchApproval": {"ApprovedForDispatch"},
    "CurrentStage": {"Build", "Execution"},
}

REQUIRED_REVIEW_BLOCKS = (
    "Zero-Context Review",
    "Implementer Readiness Review",
    "Security/Privacy Review",
    "Dynamic Specialist Review Roster",
    "Human Readability Review",
)

EXECUTABLE_LEAF_WARN_LIMIT = 8
EXECUTABLE_LEAF_FAIL_LIMIT = 12


@dataclass
class GateResult:
    gate: str
    status: str
    messages: list[str]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section_bounds(markdown: str, title: str) -> tuple[int, int] | None:
    matches = list(TOP_LEVEL_RE.finditer(markdown))
    for index, match in enumerate(matches):
        if match.group(1).strip().lower() != title.lower():
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        return match.end(), end
    return None


def section(markdown: str, title: str) -> str:
    bounds = section_bounds(markdown, title)
    if bounds is None:
        return ""
    return markdown[bounds[0] : bounds[1]].strip()


def subsection(section_text: str, title: str) -> str:
    matches = list(SUBSECTION_RE.finditer(section_text))
    for index, match in enumerate(matches):
        if match.group(1).strip().lower() != title.lower():
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section_text)
        return section_text[match.end() : end].strip()
    return ""


def top_level_sections(markdown: str) -> dict[str, str]:
    matches = list(TOP_LEVEL_RE.finditer(markdown))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[title] = markdown[match.end() : end].strip()
    return sections


def remove_section(markdown: str, title: str) -> str:
    bounds = section_bounds(markdown, title)
    if bounds is None:
        return markdown
    header_start = markdown.rfind("##", 0, bounds[0])
    return (markdown[:header_start] + markdown[bounds[1] :]).strip() + "\n"


def reviewed_plan_hash(markdown: str) -> str:
    reviewed_text = remove_section(markdown, "Planning Reviews")
    normalized = "\n".join(line.rstrip() for line in reviewed_text.splitlines()).strip() + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_key_values(section_text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in section_text.splitlines():
        match = KEY_VALUE_RE.match(raw.strip())
        if match:
            values[match.group(1).strip()] = match.group(2).strip()
    return values


def manifest_leaf_blocks(leaves: str) -> list[tuple[str, str]]:
    lines = leaves.splitlines()
    blocks: list[tuple[str, list[str]]] = []
    current_id: str | None = None
    current_lines: list[str] = []
    for line in lines:
        match = LEAF_ITEM_RE.match(line)
        if match:
            if current_id is not None:
                blocks.append((current_id, current_lines))
            current_id = match.group(1).strip()
            current_lines = [line]
            continue
        if current_id is not None:
            current_lines.append(line)
    if current_id is not None:
        blocks.append((current_id, current_lines))
    return [(leaf_id, "\n".join(block_lines)) for leaf_id, block_lines in blocks]


def executable_leaf_ids(leaves: str) -> list[str]:
    ids: list[str] = []
    for leaf_id, block in manifest_leaf_blocks(leaves):
        fields = parse_key_values(block)
        dispatch = fields.get("Dispatch", "").strip().lower()
        if dispatch != "tracking-only":
            ids.append(leaf_id)
    return ids


def split_decision_records(decision_log: str) -> list[tuple[str, str]]:
    matches = list(DR_HEADING_RE.finditer(decision_log))
    records: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(decision_log)
        records.append((match.group(1), decision_log[match.start() : end]))
    return records


def dr_scope_waiver_messages(decision_log: str, executable_count: int) -> list[str]:
    partial_messages: list[str] = []
    for dr_id, record in split_decision_records(decision_log):
        lowered = record.lower()
        if "scope waiver" not in lowered and "executable leaf count" not in lowered:
            continue
        fields = parse_key_values(record)
        messages: list[str] = []
        if not re.search(r"Status:\s*Accepted\b", record, re.IGNORECASE):
            messages.append(f"{dr_id} scope waiver must have Status: Accepted.")

        count_value = fields.get("Executable leaf count") or fields.get("Executable-leaf count")
        if count_value is None:
            messages.append(f"{dr_id} scope waiver missing Executable leaf count: {executable_count}.")
        else:
            count_match = re.search(r"\d+", count_value)
            if not count_match or int(count_match.group(0)) != executable_count:
                messages.append(
                    f"{dr_id} scope waiver executable leaf count must exactly match {executable_count}."
                )

        required_fields = (
            "Rationale for not splitting",
            "Validation risk",
            "Revisit trigger",
        )
        for field in required_fields:
            if not has_label_content(record, field):
                messages.append(f"{dr_id} scope waiver missing {field}.")

        if not messages:
            return []
        partial_messages.extend(messages)

    if partial_messages:
        return partial_messages
    return [
        "Executable leaf count exceeds 12; split into child plans or add an accepted DR-backed scope waiver "
        "with DR id, exact executable leaf count, rationale for not splitting, validation risk, and revisit trigger."
    ]


def parse_dateish(value: str) -> datetime | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
            return datetime.fromisoformat(cleaned)
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def non_placeholder_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        if PLACEHOLDER_RE.search(stripped):
            continue
        lines.append(stripped)
    return lines


def has_label_content(text: str, label: str) -> bool:
    pattern = re.compile(
        rf"^\s*-?\s*{re.escape(label)}(?:\s*\([^)]+\)|\s*/[^:]*)?:\s*(.*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return False
    rest = match.group(1).strip()
    if rest and not PLACEHOLDER_RE.search(rest):
        return True
    following = text[match.end() :].splitlines()[:4]
    return bool(non_placeholder_lines("\n".join(following)))


def has_heading_or_label(text: str, label: str) -> bool:
    if re.search(rf"^#+\s+{re.escape(label)}\s*$", text, re.IGNORECASE | re.MULTILINE):
        return True
    return has_label_content(text, label)


def list_items_under_label(text: str, label: str) -> list[str]:
    lines = text.splitlines()
    result: list[str] = []
    label_re = re.compile(rf"^\s*-?\s*{re.escape(label)}(?:\s*\([^)]+\)|\s*/[^:]*)?:\s*$", re.IGNORECASE)
    for index, line in enumerate(lines):
        if not label_re.match(line.strip()):
            continue
        label_indent = len(line) - len(line.lstrip())
        label_is_bullet = line.lstrip().startswith("-")
        for follower in lines[index + 1 :]:
            stripped = follower.strip()
            if not stripped:
                continue
            follower_indent = len(follower) - len(follower.lstrip())
            if follower_indent < label_indent or (label_is_bullet and follower_indent <= label_indent):
                break
            if follower_indent == label_indent and not stripped.startswith("-"):
                break
            if stripped.startswith("-") and not PLACEHOLDER_RE.search(stripped):
                result.append(stripped)
                continue
            if re.match(r"^-?\s*[A-Za-z][A-Za-z0-9 /-]+:\s*", stripped) and not stripped.startswith("- ["):
                break
        break
    return result


def problem_narrative(problem: str) -> str:
    match = re.search(
        r"Problem narrative:\s*(.*?)(?:^\s*Current broken workflow:|\Z)",
        problem,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def first_paragraphs(text: str, count: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return paragraphs[:count]


def check_problem_definition(markdown: str) -> GateResult:
    problem = section(markdown, "Problem Definition")
    messages: list[str] = []
    if not problem:
        return GateResult("ProblemDefinitionComplete", "Fail", ["Missing ## Problem Definition."])

    narrative = problem_narrative(problem)
    if not non_placeholder_lines(narrative):
        messages.append("Problem narrative is missing or placeholder-only.")
    for paragraph in first_paragraphs(narrative, 2):
        lowered = paragraph.lower()
        leaked = [term for term in PLANNING_META_TERMS if term in lowered]
        if leaked:
            messages.append(
                "Problem narrative first two paragraphs include planning-meta term(s): "
                + ", ".join(sorted(set(leaked)))
                + "."
            )
            break

    for label in ("Current broken workflow", "Desired workflow", "Why this matters / why now"):
        if not has_label_content(problem, label):
            messages.append(f"Missing substantive {label}.")

    facts = [line for line in problem.splitlines() if SOURCE_FACT_RE.search(line)]
    if len(facts) < 3:
        messages.append("Current-state facts need at least 3 sourced facts.")

    if len(list_items_under_label(problem, "Success criteria (measurable)")) < 1:
        messages.append("Missing measurable success criteria.")
    if not has_label_content(problem, "Constraints"):
        messages.append("Missing constraints.")
    if "In scope:" not in problem or "Out of scope:" not in problem:
        messages.append("Scope must include both In scope and Out of scope.")
    if re.search(r"Status:\s*Open\b", problem, re.IGNORECASE):
        messages.append("Open questions remain in Problem Definition.")

    return GateResult("ProblemDefinitionComplete", "Fail" if messages else "Pass", messages)


def high_risk_intent_required(state: dict[str, str]) -> bool:
    return (
        state.get("PlanTier", "Full").lower() == "full"
        or state.get("AutomationTarget", "none") == "unattended-prs"
    )


def blocking_open_intent_loops(intent: str) -> bool:
    entries = re.split(r"^\s*-\s+OL-[A-Za-z0-9-]+:", intent, flags=re.MULTILINE)
    for entry in entries[1:]:
        if not re.search(r"Status:\s*Open\b", entry, re.IGNORECASE):
            continue
        if re.search(r"Blocks:\s*(Problem|Technical|Implementation|Automation)\b", entry, re.IGNORECASE):
            return True
    return False


def check_intent_model(markdown: str, state: dict[str, str]) -> GateResult:
    intent = section(markdown, "Intent Model")
    messages: list[str] = []
    required = high_risk_intent_required(state)
    if not intent:
        messages.append("Missing ## Intent Model.")
        return GateResult("IntentModelComplete", "Fail" if required else "N/A", messages)

    intent_bounds = section_bounds(markdown, "Intent Model")
    problem_bounds = section_bounds(markdown, "Problem Definition")
    if intent_bounds and problem_bounds and intent_bounds[0] > problem_bounds[0]:
        messages.append("Intent Model must appear before Problem Definition.")

    for label in (
        "Latent target",
        "Anti-targets",
        "Expression-state notes",
        "Open Loop Ledger",
        "Intent checksum",
    ):
        if not has_label_content(intent, label):
            messages.append(f"Intent Model missing {label}.")

    if blocking_open_intent_loops(intent):
        messages.append("Blocking open loops remain in Intent Model.")

    if not re.search(r"Failure would look like:\s*(?:\n\s*-\s+\S|.+)", intent, re.IGNORECASE):
        messages.append("Intent checksum must name a likely wrong-but-plausible failure.")

    if messages:
        return GateResult("IntentModelComplete", "Fail" if required else "N/A", messages)
    return GateResult("IntentModelComplete", "Pass", [])


def check_plan_readiness(markdown: str, state: dict[str, str]) -> GateResult:
    implementation = section(markdown, "Implementation Plan")
    messages: list[str] = []
    if not implementation:
        return GateResult("PlanReadiness", "Fail", ["Missing ## Implementation Plan."])

    plan_tier = state.get("PlanTier", "Full")
    if "### File Deltas" not in implementation or not re.search(r"^-\s+.+\s+-\s+.+\s+-\s+.+\s+-\s+.+", implementation, re.MULTILINE):
        messages.append("File Deltas must include path, change type, owner, and rationale.")
    if "### Workstreams + merge points" not in implementation:
        messages.append("Missing Workstreams + merge points.")
    else:
        for label in ("Owner", "Agent type", "Delegate", "Depends on", "Review gates", "Owns files", "Merge point"):
            if not has_heading_or_label(implementation, label):
                messages.append(f"Workstreams are missing {label}.")

    if "### Phases + tasks + exit criteria" not in implementation:
        messages.append("Missing Phases + tasks + exit criteria.")
    else:
        for label in ("Owner(s)", "Depends on", "Exit criteria (evidence)", "Gates (named)"):
            if not has_heading_or_label(implementation, label):
                messages.append(f"Phases are missing {label}.")

    if "### Review gates" not in implementation or not GATE_TOKEN_RE.search(implementation):
        messages.append("Named review gates are missing.")
    for label in ("Where it runs", "Entry point / command", "Green means"):
        if not has_heading_or_label(implementation, label):
            messages.append(f"Gate definitions are missing {label}.")

    if "### Test Matrix" not in implementation or "where it runs" not in implementation.lower():
        messages.append("Test Matrix must include where each check runs.")
    if "### Rollout / Rollback" not in implementation:
        messages.append("Missing Rollout / Rollback.")
    for label in ("Rollback trigger", "Rollback steps"):
        if not has_heading_or_label(implementation, label):
            messages.append(f"Rollout / Rollback missing {label}.")

    if plan_tier.lower() == "full":
        if "### Agent roster" not in implementation:
            messages.append("PlanTier Full requires Agent roster.")
        if "### Delegation Quality Gate" not in implementation:
            messages.append("PlanTier Full requires Delegation Quality Gate.")
        for dq in ("DQ-1", "DQ-2", "DQ-3", "DQ-4"):
            if not re.search(rf"{dq}.*:\s*Pass\b", implementation, re.IGNORECASE):
                messages.append(f"{dq} must be Pass or explicitly waived by Decision Log.")

    return GateResult("PlanReadiness", "Fail" if messages else "Pass", messages)


def check_automation_readiness(markdown: str, state: dict[str, str]) -> GateResult:
    target = state.get("AutomationTarget", "none")
    if target == "none":
        return GateResult("AutomationReadiness", "N/A", [])

    manifest = section(markdown, "Automation Issue Manifest")
    messages: list[str] = []
    if not manifest:
        return GateResult("AutomationReadiness", "Fail", ["Missing ## Automation Issue Manifest."])

    for label in (
        "Automation target",
        "Dispatch strategy",
        "Max concurrent work items",
        "Required labels",
        "Branch policy",
        "PR policy",
        "Merge policy",
        "Failure policy",
        "Human approval required before dispatch",
    ):
        if not has_label_content(manifest, label):
            messages.append(f"Dispatch policy missing {label}.")

    if "### Containers" not in manifest or "tracking-only" not in subsection(manifest, "Containers"):
        messages.append("Containers must exist and be tracking-only.")

    leaves = subsection(manifest, "Leaf issues")
    executable_ids: list[str] = []
    if not leaves:
        messages.append("Missing leaf issues.")
    else:
        executable_ids = executable_leaf_ids(leaves)
        for label in (
            "Type",
            "Parent",
            "Owner",
            "Agent type",
            "Dispatch",
            "Depends on",
            "Parallel group",
            "Blocks",
            "Critical path rank",
            "Merge group",
            "Combine policy",
            "Conflict class",
            "Validation tier",
            "Files in scope",
            "Files out of scope",
            "Required gates",
            "Validation",
            "Acceptance criteria",
            "One PR contract",
            "Source plan sections",
        ):
            if not has_heading_or_label(leaves, label):
                messages.append(f"Leaf issues missing {label}.")
        dependency_lines = list_items_under_label(leaves, "Depends on")
        for item in dependency_lines:
            if DISALLOWED_DEP_TOKEN_RE.search(item) and "structured" not in item.lower():
                messages.append(f"Invalid dependency token in leaf dependency: {item}")
                break

        executable_count = len(executable_ids)
        if executable_count > EXECUTABLE_LEAF_WARN_LIMIT:
            messages.append(
                f"Warning: executable leaf count is {executable_count}, above the recommended budget of "
                f"{EXECUTABLE_LEAF_WARN_LIMIT}; prefer a child-plan split."
            )
        if executable_count > EXECUTABLE_LEAF_FAIL_LIMIT:
            messages.extend(dr_scope_waiver_messages(section(markdown, "Decision Log"), executable_count))

    if "### Manifest validation summary" not in manifest:
        messages.append("Missing Manifest validation summary.")
    else:
        for summary_line in (
            "Dependency graph acyclic",
            "Dependencies resolvable",
            "Gate coverage complete",
            "File-scope conflicts resolved",
            "Acceptance criteria executable",
            "Required metadata complete",
        ):
            if not re.search(rf"{re.escape(summary_line)}:\s*Pass\b", manifest, re.IGNORECASE):
                messages.append(f"Manifest validation summary does not pass {summary_line}.")

    blocking_messages = [message for message in messages if not message.startswith("Warning:")]
    return GateResult("AutomationReadiness", "Fail" if blocking_messages else "Pass", messages)


def normalize_review_title(title: str) -> str:
    return re.sub(r"\s+\((?:required|conditional|required when .*?)\)\s*$", "", title, flags=re.IGNORECASE).strip()


def review_blocks(planning_reviews: str) -> dict[str, str]:
    matches = list(SUBSECTION_RE.finditer(planning_reviews))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = normalize_review_title(match.group(1).strip())
        end = matches[index + 1].start() if index + 1 < len(matches) else len(planning_reviews)
        blocks[title] = planning_reviews[match.end() : end].strip()
    return blocks


def block_has_disposition(block: str) -> bool:
    return "Disposition:" in block and re.search(r"\b(Accept|Reject|Defer):\s*F-\d+", block) is not None


def block_is_na_with_rationale(block: str) -> bool:
    return "N/A" in block and re.search(r"rationale|not triggered|not required", block, re.IGNORECASE) is not None


def block_freshness_message(block: str, expected_hash: str, last_updated: datetime | None) -> str | None:
    hash_match = REVIEWED_HASH_RE.search(block)
    if hash_match:
        actual = hash_match.group(1).lower()
        if actual != expected_hash.lower():
            return f"ReviewedPlanHash mismatch: expected sha256:{expected_hash}."
        return None

    refreshed_at_match = REFRESHED_AT_RE.search(block)
    if refreshed_at_match:
        refreshed_at = parse_dateish(refreshed_at_match.group(1))
        if refreshed_at is None:
            return "RefreshedAt is not parseable."
        if last_updated is not None and refreshed_at < last_updated:
            return "RefreshedAt is older than LastUpdated."
        return None

    if REFRESHED_DATE_RE.search(block) or LEGACY_REFRESHED_DATE_RE.search(block):
        return "Legacy Refreshed date is not enough; add ReviewedPlanHash or timestamp-level RefreshedAt."
    return "Missing freshness marker; add ReviewedPlanHash or RefreshedAt."


def check_planning_reviews(markdown: str, state: dict[str, str]) -> GateResult:
    reviews = section(markdown, "Planning Reviews")
    messages: list[str] = []
    if not reviews:
        return GateResult("PlanningReviewsComplete", "Fail", ["Missing ## Planning Reviews."])

    blocks = review_blocks(reviews)
    required = list(REQUIRED_REVIEW_BLOCKS)
    if state.get("AutomationTarget", "none") != "none":
        required.append("Automation Readiness Review")

    expected_hash = reviewed_plan_hash(markdown)
    last_updated = parse_dateish(state.get("LastUpdated", ""))
    for title in required:
        block = blocks.get(title, "")
        if not block:
            messages.append(f"Missing required review block: {title}.")
            continue
        freshness = block_freshness_message(block, expected_hash, last_updated)
        if freshness:
            messages.append(f"{title}: {freshness}")
        if not block_has_disposition(block):
            messages.append(f"{title}: missing exhaustive disposition entries.")

    expert = blocks.get("Expert Technical Review", "")
    if not expert:
        messages.append("Missing Expert Technical Review block with findings or N/A rationale.")
    elif not block_is_na_with_rationale(expert) and not block_has_disposition(expert):
        messages.append("Expert Technical Review must include dispositions or N/A rationale.")

    human = blocks.get("Human Readability Review", "")
    if human and not re.search(r"Pass/fail readability statement:\s*Pass\b", human, re.IGNORECASE):
        messages.append("Human Readability Review must include a Pass readability statement.")

    return GateResult("PlanningReviewsComplete", "Fail" if messages else "Pass", messages)


def open_question_present(markdown: str) -> bool:
    for section_name in ("Problem Definition", "Context Snapshot", "Technical Plan"):
        if re.search(r"Status:\s*Open\b", section(markdown, section_name), re.IGNORECASE):
            return True
    return False


def check_plan_state_sanity(markdown: str, state: dict[str, str], gates: dict[str, str]) -> GateResult:
    messages: list[str] = []
    approval_claims: list[str] = []
    for field_name, approved_values in APPROVAL_FIELDS.items():
        value = state.get(field_name)
        if value in approved_values:
            approval_claims.append(f"{field_name}: {value}")

    if approval_claims:
        required_gates = [
            "ProblemDefinitionComplete",
            "TechnicalClarity",
            "HumanReadabilityReview",
            "PlanReadiness",
            "PlanningReviewsComplete",
        ]
        if high_risk_intent_required(state):
            required_gates.insert(0, "IntentModelComplete")
        if state.get("AutomationTarget", "none") != "none":
            required_gates.append("AutomationReadiness")
        for gate in required_gates:
            if gates.get(gate) != "Pass":
                messages.append(f"Approval state is set but {gate} is not Pass.")

    if open_question_present(markdown):
        messages.append("Open questions remain while plan state claims readiness or approval.")

    critical = "\n".join(
        section(markdown, name)
        for name in ("Problem Definition", "Technical Plan", "Implementation Plan", "Decision Log")
    )
    if PLACEHOLDER_RE.search(critical):
        messages.append("Critical planning sections contain placeholders or undecided ambiguity markers.")

    return GateResult("PlanStateSanity", "Fail" if messages else "Pass", messages)


def gate_results(markdown: str) -> dict[str, str]:
    gates = parse_key_values(section(markdown, "Gate Results"))
    return {key: value for key, value in gates.items() if value in {"Pass", "Fail", "N/A"}}


def validate(markdown: str) -> list[GateResult]:
    state = parse_key_values(section(markdown, "Plan State"))
    claimed_gates = gate_results(markdown)
    results = [
        check_intent_model(markdown, state),
        check_problem_definition(markdown),
        check_plan_readiness(markdown, state),
        check_automation_readiness(markdown, state),
        check_planning_reviews(markdown, state),
        check_plan_state_sanity(markdown, state, claimed_gates),
    ]
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Atlas plan gate invariants.")
    parser.add_argument("plan", type=Path, nargs="?", help="Markdown plan artifact to validate.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--print-hash", action="store_true", help="Print the current ReviewedPlanHash and exit.")
    args = parser.parse_args()

    if args.plan is None:
        parser.error("plan is required")
    markdown = read_text(args.plan)
    if args.print_hash:
        print(f"sha256:{reviewed_plan_hash(markdown)}")
        return 0

    results = validate(markdown)
    failed = [result for result in results if result.status == "Fail"]
    if args.json:
        print(json.dumps({"plan": str(args.plan), "results": [asdict(result) for result in results]}, indent=2))
    else:
        for result in results:
            print(f"{result.gate}: {result.status}")
            for message in result.messages:
                print(f"  - {message}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
