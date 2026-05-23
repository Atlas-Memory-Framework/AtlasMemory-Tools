#!/usr/bin/env python3
# atlas-tools-generated: source=skills/plan-to-html/scripts/plan_to_html.py manifest=atlas-tools.v1 checksum=sha256:f0b091d48b5f81f9c1abb62bb9845e843839f210d7b08e9f9c0c0879410929d3
# atlas-tools-generated-end
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


PLAN_KEYS = (
    "Status",
    "CurrentStage",
    "PlanTier",
    "AutomationTarget",
    "DeliveryMode",
    "ContextMode",
    "LastUpdated",
    "PrimaryOwner",
    "BaseBranch",
    "TargetBranch",
    "NextRequiredUserAction",
    "BlockingDecision",
    "UnresolvedBlockers",
)

SAFE_URL_SCHEMES = {"", "http", "https", "mailto"}


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    anchor: str


@dataclass(frozen=True)
class RenderedPlan:
    title: str
    html_body: str
    headings: list[Heading]
    plan_state: dict[str, str]
    gate_results: dict[str, str]


@dataclass(frozen=True)
class ArtifactItem:
    id: str
    type: str
    lane: str
    title: str
    status: str
    summary: str
    body_markdown: str
    tokens: tuple[str, ...]


class Slugger:
    def __init__(self) -> None:
        self.seen: dict[str, int] = {}

    def slug(self, text: str) -> str:
        raw = re.sub(r"`([^`]*)`", r"\1", text)
        raw = re.sub(r"[*_\[\]()>#]", "", raw).strip().lower()
        raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
        base = raw or "section"
        count = self.seen.get(base, 0)
        self.seen[base] = count + 1
        if count:
            return f"{base}-{count + 1}"
        return base


def strip_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    match = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def section_lines(markdown: str, section_title: str) -> list[str]:
    lines = markdown.splitlines()
    start: int | None = None
    start_level = 0
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        title = match.group(2).strip().strip("#").strip()
        if title.lower() == section_title.lower():
            start = index + 1
            start_level = len(match.group(1))
            break
    if start is None:
        return []
    end = len(lines)
    for index in range(start, len(lines)):
        match = re.match(r"^(#{1,6})\s+", lines[index])
        if match and len(match.group(1)) <= start_level:
            end = index
            break
    return lines[start:end]


def parse_key_values(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("-", "*", "+", "#", "<!--")):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            values[key] = value
    return values


def block_to_text(lines: list[str]) -> str:
    return "\n".join(lines).strip()


def first_meaningful_line(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        return re.sub(r"^[-*+]\s+", "", stripped)
    return ""


def subsection_lines(lines: list[str], title: str, level: int = 3) -> list[str]:
    start: int | None = None
    prefix = "#" * level
    for index, line in enumerate(lines):
        match = re.match(rf"^{re.escape(prefix)}\s+(.+?)\s*$", line)
        if match and match.group(1).strip().lower() == title.lower():
            start = index + 1
            break
    if start is None:
        return []
    end = len(lines)
    for index in range(start, len(lines)):
        if re.match(rf"^#{{1,{level}}}\s+", lines[index]):
            end = index
            break
    return lines[start:end]


def split_heading_items(lines: list[str], level: int, pattern: str) -> list[tuple[str, str, list[str]]]:
    items: list[tuple[str, str, list[str]]] = []
    current_id = ""
    current_title = ""
    current: list[str] = []
    heading_re = re.compile(rf"^{'#' * level}\s+(.+?)\s*$")
    id_re = re.compile(pattern)
    for line in lines:
        heading = heading_re.match(line)
        if heading:
            if current_id:
                items.append((current_id, current_title, current))
            current_title = heading.group(1).strip()
            id_match = id_re.search(current_title)
            current_id = id_match.group(1) if id_match else current_title
            current = []
            continue
        if current_id:
            current.append(line)
    if current_id:
        items.append((current_id, current_title, current))
    return items


def split_bullet_items(lines: list[str], pattern: str) -> list[tuple[str, str, list[str]]]:
    items: list[tuple[str, str, list[str]]] = []
    current_id = ""
    current_title = ""
    current: list[str] = []
    item_re = re.compile(pattern)
    for line in lines:
        match = item_re.match(line)
        if match:
            if current_id:
                items.append((current_id, current_title, current))
            current_id = match.group(1)
            current_title = line.strip()[2:].strip()
            current = [line]
            continue
        if current_id:
            current.append(line)
    if current_id:
        items.append((current_id, current_title, current))
    return items


TOKEN_RE = re.compile(r"\b(?:DR-\d+|R\d+|A\d+|G-[A-Za-z0-9_-]+|WS\d+[A-Za-z0-9_-]*|[A-Z]{2,}\d*-[A-Z0-9_-]+)\b")


def extract_tokens(*parts: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for part in parts:
        for token in TOKEN_RE.findall(part):
            seen[token] = None
    return tuple(seen)


def item_id(prefix: str, value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or prefix
    return f"{prefix}-{slug}"


def markdown_excerpt(markdown: str, limit: int = 170) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", markdown)
    text = re.sub(r"<!--.*?-->", "", text)
    text = re.sub(r"[*_#>\[\]()`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def field_value(markdown: str, field: str) -> str:
    match = re.search(rf"^\s*-\s+{re.escape(field)}:\s*(.+?)\s*$", markdown, re.MULTILINE)
    return match.group(1).strip() if match else ""


def field_values(markdown: str, field: str) -> tuple[str, ...]:
    def clean(value: str) -> str:
        return re.sub(r"^[-*+]\s+", "", value.strip()).rstrip(".")

    value = field_value(markdown, field)
    values: list[str] = []
    if value and value.lower() not in {"none", "n/a", "na"}:
        values.extend(clean(part) for part in re.split(r",|\band\b", value) if clean(part))

    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if not re.match(rf"^\s*-\s+{re.escape(field)}:\s*$", line):
            continue
        base_indent = len(line) - len(line.lstrip())
        for child in lines[index + 1 :]:
            if not child.strip():
                continue
            child_indent = len(child) - len(child.lstrip())
            if child_indent <= base_indent:
                break
            child_match = re.match(r"^\s*-\s+(.+?)\s*$", child)
            if child_match:
                candidate = clean(child_match.group(1))
                if candidate.lower() not in {"none", "n/a", "na"}:
                    values.append(candidate)
    seen: dict[str, None] = {}
    for item in values:
        seen[item] = None
    return tuple(seen)


def first_ws_key(*parts: str) -> str:
    for part in parts:
        match = re.search(r"\b(WS\d+)\b", part)
        if match:
            return match.group(1)
    return ""


def escape_attr(value: str) -> str:
    return html.escape(value, quote=True)


def escape_text(value: str) -> str:
    return html.escape(value, quote=False)


def is_safe_url(url: str) -> bool:
    stripped = url.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered.startswith(("javascript:", "vbscript:", "data:")):
        return False
    try:
        scheme = urlsplit(stripped).scheme.lower()
    except ValueError:
        return False
    return scheme in SAFE_URL_SCHEMES


def render_text_styles(text: str) -> str:
    escaped = escape_text(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", escaped)
    return escaped


def render_inline_no_code(text: str) -> str:
    image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

    def render_links(raw: str) -> str:
        parts: list[str] = []
        pos = 0
        for match in link_pattern.finditer(raw):
            parts.append(render_text_styles(raw[pos : match.start()]))
            label = match.group(1)
            url = match.group(2)
            if is_safe_url(url):
                parts.append(f'<a href="{escape_attr(url)}">{render_text_styles(label)}</a>')
            else:
                parts.append(render_text_styles(match.group(0)))
            pos = match.end()
        parts.append(render_text_styles(raw[pos:]))
        return "".join(parts)

    text = image_pattern.sub(lambda m: f"Image: {m.group(1)} ({m.group(2)})", text)
    return render_links(text)


def render_inline(text: str) -> str:
    code_pattern = re.compile(r"(`+)(.+?)\1")
    parts: list[str] = []
    pos = 0
    for match in code_pattern.finditer(text):
        parts.append(render_inline_no_code(text[pos : match.start()]))
        parts.append(f"<code>{escape_text(match.group(2))}</code>")
        pos = match.end()
    parts.append(render_inline_no_code(text[pos:]))
    return "".join(parts)


def render_task_prefix(text: str) -> tuple[str, str]:
    match = re.match(r"^\[([ xX])\]\s+(.*)$", text)
    if not match:
        return "", text
    checked = match.group(1).lower() == "x"
    label = "completed task" if checked else "open task"
    checkbox = (
        f'<input class="task-checkbox" type="checkbox" disabled '
        f'aria-label="{label}"{" checked" if checked else ""}> '
    )
    return checkbox, match.group(2)


def split_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in stripped:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def is_table_delimiter(line: str) -> bool:
    cells = split_table_row(line)
    if len(cells) < 2:
        return False
    return all(re.match(r"^:?-{3,}:?$", cell.strip()) for cell in cells)


def is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return "|" in lines[index] and is_table_delimiter(lines[index + 1])


def render_table(rows: list[str]) -> str:
    headers = split_table_row(rows[0])
    aligns = split_table_row(rows[1])
    body_rows = [split_table_row(row) for row in rows[2:]]
    align_classes = []
    for align in aligns:
        if align.startswith(":") and align.endswith(":"):
            align_classes.append("center")
        elif align.endswith(":"):
            align_classes.append("right")
        else:
            align_classes.append("left")
    output = ['<div class="table-wrap"><table>']
    output.append("<thead><tr>")
    for index, cell in enumerate(headers):
        klass = align_classes[index] if index < len(align_classes) else "left"
        output.append(f'<th class="align-{klass}">{render_inline(cell)}</th>')
    output.append("</tr></thead><tbody>")
    for row in body_rows:
        output.append("<tr>")
        for index, cell in enumerate(row):
            klass = align_classes[index] if index < len(align_classes) else "left"
            output.append(f'<td class="align-{klass}">{render_inline(cell)}</td>')
        output.append("</tr>")
    output.append("</tbody></table></div>")
    return "".join(output)


class MarkdownRenderer:
    def __init__(self, *, show_comments: bool = False) -> None:
        self.show_comments = show_comments
        self.slugger = Slugger()
        self.headings: list[Heading] = []
        self.out: list[str] = []
        self.paragraph: list[str] = []
        self.list_stack: list[tuple[int, str]] = []

    def render(self, markdown: str) -> tuple[str, list[Heading]]:
        lines = markdown.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()

            if not stripped:
                self.flush_paragraph()
                self.close_lists()
                index += 1
                continue

            if self.is_html_comment(stripped):
                self.flush_paragraph()
                if self.show_comments:
                    self.out.append(f'<p class="html-comment">{escape_text(stripped)}</p>')
                index += 1
                continue

            fence_match = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
            if fence_match:
                self.flush_paragraph()
                fence = fence_match.group(1)
                language = fence_match.group(2).strip().split()[0] if fence_match.group(2).strip() else ""
                code_lines: list[str] = []
                index += 1
                while index < len(lines):
                    if re.match(rf"^\s*{re.escape(fence)}\s*$", lines[index]):
                        break
                    code_lines.append(lines[index])
                    index += 1
                code = escape_text("\n".join(code_lines))
                lang_attr = f' class="language-{escape_attr(language)}"' if language else ""
                self.out.append(f"<pre><code{lang_attr}>{code}</code></pre>")
                index += 1
                continue

            heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
            if heading_match:
                self.flush_paragraph()
                self.close_lists()
                level = len(heading_match.group(1))
                text = heading_match.group(2).strip()
                anchor = self.slugger.slug(text)
                self.headings.append(Heading(level=level, text=text, anchor=anchor))
                self.out.append(
                    f'<h{level} id="{escape_attr(anchor)}">'
                    f'{render_inline(text)}'
                    f'<a class="heading-anchor" href="#{escape_attr(anchor)}" aria-label="Link to section">#</a>'
                    f"</h{level}>"
                )
                index += 1
                continue

            if is_table_start(lines, index):
                self.flush_paragraph()
                self.close_lists()
                table_rows = [lines[index], lines[index + 1]]
                index += 2
                while index < len(lines) and "|" in lines[index].strip() and lines[index].strip():
                    table_rows.append(lines[index])
                    index += 1
                self.out.append(render_table(table_rows))
                continue

            list_match = re.match(r"^(\s*)([-+*]|\d+[.)])\s+(.*)$", line)
            if list_match:
                self.flush_paragraph()
                indent = self.indent_width(list_match.group(1))
                marker = list_match.group(2)
                tag = "ol" if re.match(r"\d", marker) else "ul"
                self.open_list_item(indent, tag, list_match.group(3))
                index += 1
                continue

            if self.list_stack and self.indent_width(line) > self.list_stack[-1][0]:
                self.out.append("<br>" + render_inline(stripped))
                index += 1
                continue

            self.close_lists()
            if self.is_key_value_line(stripped):
                self.flush_paragraph()
                key, value = stripped.split(":", 1)
                self.out.append(
                    '<p class="kv-line">'
                    f"<strong>{escape_text(key.strip())}:</strong> {render_inline(value.strip())}"
                    "</p>"
                )
            else:
                self.paragraph.append(stripped)
            index += 1

        self.flush_paragraph()
        self.close_lists()
        return "\n".join(self.out), self.headings

    @staticmethod
    def indent_width(value: str) -> int:
        return len(value.replace("\t", "    "))

    @staticmethod
    def is_html_comment(stripped: str) -> bool:
        return stripped.startswith("<!--") and stripped.endswith("-->")

    @staticmethod
    def is_key_value_line(stripped: str) -> bool:
        if stripped.startswith(("-", "*", "+")) or ":" not in stripped:
            return False
        key, value = stripped.split(":", 1)
        return bool(key.strip()) and bool(value.strip()) and len(key.strip()) <= 80

    def flush_paragraph(self) -> None:
        if not self.paragraph:
            return
        text = " ".join(self.paragraph).strip()
        if text:
            self.out.append(f"<p>{render_inline(text)}</p>")
        self.paragraph = []

    def open_list_item(self, indent: int, tag: str, text: str) -> None:
        while self.list_stack and indent < self.list_stack[-1][0]:
            self.close_one_list()

        if self.list_stack and indent == self.list_stack[-1][0]:
            current_indent, current_tag = self.list_stack[-1]
            if current_tag != tag:
                self.close_one_list()
                self.out.append(f"<{tag}>")
                self.list_stack.append((indent, tag))
            else:
                self.out.append("</li>")
        elif not self.list_stack or indent > self.list_stack[-1][0]:
            self.out.append(f"<{tag}>")
            self.list_stack.append((indent, tag))

        prefix, rest = render_task_prefix(text.strip())
        self.out.append(f"<li>{prefix}{render_inline(rest)}")

    def close_one_list(self) -> None:
        if not self.list_stack:
            return
        _, tag = self.list_stack.pop()
        self.out.append(f"</li></{tag}>")

    def close_lists(self) -> None:
        while self.list_stack:
            self.close_one_list()


def extract_title(markdown: str, source_path: Path | None, override: str | None) -> str:
    if override:
        return override
    for line in markdown.splitlines():
        match = re.match(r"^#\s+(.+?)\s*#*\s*$", line)
        if match:
            return match.group(1).strip()
    if source_path:
        return source_path.stem.replace("-", " ").replace("_", " ").title()
    return "Plan"


def render_toc(headings: list[Heading]) -> str:
    if not headings:
        return '<p class="toc-empty">No headings found.</p>'
    items: list[str] = ['<ol class="toc-list">']
    for heading in headings:
        depth = min(max(heading.level, 1), 6)
        items.append(
            f'<li class="toc-level-{depth}">'
            f'<a href="#{escape_attr(heading.anchor)}">{escape_text(heading.text)}</a>'
            "</li>"
        )
    items.append("</ol>")
    return "\n".join(items)


def badge_class(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "pass" or normalized in {"approved", "shipped", "complete"}:
        return "pass"
    if normalized == "fail" or normalized in {"blocked", "open"}:
        return "fail"
    if normalized in {"n/a", "na", "none"}:
        return "na"
    if normalized in {"draft", "planned", "inbuild", "in build", "revisit"}:
        return "warn"
    return "info"


def render_summary(plan_state: dict[str, str], gate_results: dict[str, str]) -> str:
    if not plan_state and not gate_results:
        return ""

    parts = ['<section class="summary-panel" aria-labelledby="summary-title">']
    parts.append('<h2 id="summary-title">Plan Summary</h2>')

    visible_keys = [key for key in PLAN_KEYS if key in plan_state]
    if visible_keys:
        parts.append('<dl class="summary-grid">')
        for key in visible_keys:
            value = plan_state[key]
            klass = badge_class(value) if key in {"Status", "CurrentStage", "BlockingDecision"} else "plain"
            parts.append(
                "<div>"
                f"<dt>{escape_text(key)}</dt>"
                f'<dd><span class="summary-value summary-{klass}">{render_inline(value)}</span></dd>'
                "</div>"
            )
        parts.append("</dl>")

    if gate_results:
        parts.append('<h3 class="summary-subtitle">Gate Results</h3>')
        parts.append('<div class="gate-grid">')
        for key, value in gate_results.items():
            klass = badge_class(value)
            parts.append(
                f'<div class="gate-card gate-{klass}">'
                f"<span>{escape_text(key)}</span>"
                f"<strong>{escape_text(value)}</strong>"
                "</div>"
            )
        parts.append("</div>")

    parts.append("</section>")
    return "\n".join(parts)


def build_artifact_items(markdown: str) -> list[ArtifactItem]:
    plan_state_lines = section_lines(markdown, "Plan State")
    gate_lines = section_lines(markdown, "Gate Results")
    decision_lines = section_lines(markdown, "Decision Log")
    risk_lines = section_lines(markdown, "Risks / Assumptions / Tests")
    implementation_lines = section_lines(markdown, "Implementation Plan")
    automation_lines = section_lines(markdown, "Automation Issue Manifest")
    review_lines = section_lines(markdown, "Planning Reviews")
    technical_lines = section_lines(markdown, "Technical Plan")
    problem_lines = section_lines(markdown, "Problem Definition")

    items: list[ArtifactItem] = []
    plan_state = parse_key_values(plan_state_lines)
    gate_results = parse_key_values(gate_lines)

    if plan_state:
        status = plan_state.get("Status", "")
        state_body = "\n".join(f"{key}: {value}" for key, value in plan_state.items())
        summary = ", ".join(
            value
            for key, value in plan_state.items()
            if key in {"Status", "CurrentStage", "PlanTier", "AutomationTarget"} and value
        )
        items.append(
            ArtifactItem(
                id="overview-plan-state",
                type="overview",
                lane="Overview",
                title="Plan state",
                status=status,
                summary=summary,
                body_markdown=state_body,
                tokens=extract_tokens(state_body),
            )
        )

    if problem_lines:
        body = block_to_text(problem_lines)
        items.append(
            ArtifactItem(
                id="overview-problem",
                type="overview",
                lane="Overview",
                title="Problem definition",
                status="",
                summary=markdown_excerpt(body),
                body_markdown=body,
                tokens=extract_tokens(body),
            )
        )

    if technical_lines:
        body = block_to_text(technical_lines)
        items.append(
            ArtifactItem(
                id="overview-technical",
                type="overview",
                lane="Overview",
                title="Technical plan",
                status="",
                summary=markdown_excerpt(body),
                body_markdown=body,
                tokens=extract_tokens(body),
            )
        )

    for gate, status in gate_results.items():
        body = f"{gate}: {status}"
        items.append(
            ArtifactItem(
                id=item_id("gate", gate),
                type="gate",
                lane="Gates",
                title=gate,
                status=status,
                summary=status,
                body_markdown=body,
                tokens=extract_tokens(gate, body) + (gate,),
            )
        )

    for decision_id, title, lines in split_heading_items(decision_lines, 3, r"\b(DR-\d+)\b"):
        body = f"### {title}\n" + block_to_text(lines)
        status_match = re.search(r"^- Status:\s*(.+)$", body, re.MULTILINE)
        status = status_match.group(1).strip() if status_match else ""
        items.append(
            ArtifactItem(
                id=item_id("decision", decision_id),
                type="decision",
                lane="Decisions",
                title=title,
                status=status,
                summary=markdown_excerpt(body),
                body_markdown=body,
                tokens=(decision_id,) + extract_tokens(body),
            )
        )

    for risk_id, title, lines in split_bullet_items(risk_lines, r"^-\s+((?:R|A)\d+)\b.*"):
        body = block_to_text(lines)
        status_match = re.search(r"Status:\s*([^\n]+)", body)
        status = status_match.group(1).strip() if status_match else ""
        kind = "risk" if risk_id.startswith("R") else "assumption"
        items.append(
            ArtifactItem(
                id=item_id(kind, risk_id),
                type=kind,
                lane="Risks",
                title=title,
                status=status,
                summary=markdown_excerpt(body),
                body_markdown=body,
                tokens=(risk_id,) + extract_tokens(body),
            )
        )

    workstream_lines = subsection_lines(implementation_lines, "Workstreams + merge points")
    if not workstream_lines:
        workstream_lines = implementation_lines
    for workstream_id, title, lines in split_bullet_items(workstream_lines, r"^-\s+(WS\d+[A-Za-z0-9_-]*)\b.*"):
        body = block_to_text(lines)
        status_match = re.search(r"Dispatch:\s*([^\n]+)|Delegate:\s*([^\n]+)", body)
        status = next((group.strip() for group in status_match.groups() if group), "") if status_match else ""
        items.append(
            ArtifactItem(
                id=item_id("workstream", workstream_id),
                type="workstream",
                lane="Workstreams",
                title=title,
                status=status,
                summary=markdown_excerpt(body),
                body_markdown=body,
                tokens=(workstream_id,) + extract_tokens(body),
            )
        )

    for phase_id, title, lines in split_heading_items(implementation_lines, 4, r"\b(Phase\s+\d+)\b"):
        body = f"#### {title}\n" + block_to_text(lines)
        items.append(
            ArtifactItem(
                id=item_id("phase", phase_id),
                type="phase",
                lane="Phases",
                title=title,
                status="",
                summary=markdown_excerpt(body),
                body_markdown=body,
                tokens=extract_tokens(title, body),
            )
        )

    gate_def_lines = subsection_lines(implementation_lines, "Review gates (named + definitions)")
    for gate_id, title, lines in split_bullet_items(gate_def_lines, r"^-\s+(G-[A-Za-z0-9_-]+)\b.*"):
        if any(item.title == gate_id for item in items):
            continue
        body = block_to_text(lines)
        items.append(
            ArtifactItem(
                id=item_id("gate", gate_id),
                type="gate",
                lane="Gates",
                title=title,
                status="defined",
                summary=markdown_excerpt(body),
                body_markdown=body,
                tokens=(gate_id,) + extract_tokens(body),
            )
        )

    leaf_lines = subsection_lines(automation_lines, "Leaf issues")
    for leaf_id, title, lines in split_bullet_items(leaf_lines, r"^-\s+([A-Z0-9]+(?:-[A-Z0-9]+)+)\b.*"):
        body = block_to_text(lines)
        dispatch_match = re.search(r"Dispatch:\s*([^\n]+)", body)
        status = dispatch_match.group(1).strip() if dispatch_match else ""
        items.append(
            ArtifactItem(
                id=item_id("leaf", leaf_id),
                type="leaf",
                lane="Automation",
                title=title,
                status=status,
                summary=markdown_excerpt(body),
                body_markdown=body,
                tokens=(leaf_id,) + extract_tokens(body),
            )
        )

    for review_id, title, lines in split_heading_items(review_lines, 3, r"^(.+)$"):
        body = f"### {title}\n" + block_to_text(lines)
        readiness = ""
        match = re.search(r"Pass/fail readiness statement:\s*([^\n]+)", body)
        if match:
            readiness = match.group(1).strip()
        items.append(
            ArtifactItem(
                id=item_id("review", title),
                type="review",
                lane="Reviews",
                title=title,
                status=readiness,
                summary=markdown_excerpt(body),
                body_markdown=body,
                tokens=extract_tokens(body),
            )
        )

    return items


def render_item_detail(markdown: str) -> str:
    renderer = MarkdownRenderer(show_comments=False)
    detail, _ = renderer.render(markdown)
    return detail


def artifact_json(items: list[ArtifactItem]) -> str:
    primary_tokens_by_item: dict[str, set[str]] = {}
    token_to_items: dict[str, list[str]] = {}
    for item in items:
        primary_tokens_by_item[item.id] = set(item.tokens)
        for token in item.tokens:
            token_to_items.setdefault(token, []).append(item.id)

    workstream_titles: dict[str, str] = {}
    gate_to_workstreams: dict[str, list[str]] = {}
    for item in items:
        if item.type != "workstream":
            continue
        ws_key = first_ws_key(*item.tokens, item.title)
        if not ws_key:
            continue
        workstream_titles[ws_key] = item.title
        for gate in field_values(item.body_markdown, "Gates"):
            gate_to_workstreams.setdefault(gate, []).append(ws_key)

    def ids_for_ref(ref: str) -> list[str]:
        refs = [ref]
        ws_key = first_ws_key(ref)
        if ws_key:
            refs.append(ws_key)
        refs.extend(extract_tokens(ref))
        found: list[str] = []
        seen: set[str] = set()
        for token in refs:
            for target_id in token_to_items.get(token, []):
                if target_id not in seen:
                    seen.add(target_id)
                    found.append(target_id)
        return found

    def cluster_for(item: ArtifactItem) -> tuple[str, str]:
        if item.type == "overview":
            return ("overview", "Overview")
        if item.type == "review":
            return ("review", "Reviews")
        if item.type == "workstream":
            ws_key = first_ws_key(*item.tokens, item.title)
            return (ws_key or item.id, item.title)
        if item.type == "leaf":
            parent = field_value(item.body_markdown, "Parent")
            ws_key = first_ws_key(parent, item.title)
            if ws_key:
                return (ws_key, workstream_titles.get(ws_key, ws_key))
        if item.type == "gate":
            gate_refs = gate_to_workstreams.get(item.title) or gate_to_workstreams.get(next(iter(item.tokens), ""))
            if gate_refs:
                ws_key = gate_refs[0]
                return (ws_key, workstream_titles.get(ws_key, ws_key))
            return ("gates", "Gates")
        return (item.lane.lower(), item.lane)

    data = []
    for item in items:
        explicit_related: list[str] = []
        for field in ("Parent", "Depends on", "Required gates", "Gates"):
            for ref in field_values(item.body_markdown, field):
                explicit_related.extend(ids_for_ref(ref))

        related: list[str] = []
        seen_related: set[str] = set()
        for target_id in explicit_related:
            if target_id != item.id and target_id not in seen_related:
                seen_related.add(target_id)
                related.append(target_id)

        cluster_key, cluster_label = cluster_for(item)
        data.append(
            {
                "id": item.id,
                "type": item.type,
                "lane": item.lane,
                "layer": artifact_layer_for(item.lane),
                "cluster": cluster_key,
                "clusterLabel": cluster_label,
                "title": item.title,
                "status": item.status,
                "statusClass": badge_class(item.status),
                "summary": item.summary,
                "tokens": list(item.tokens),
                "parents": list(field_values(item.body_markdown, "Parent")),
                "dependencies": list(field_values(item.body_markdown, "Depends on")),
                "gates": list(field_values(item.body_markdown, "Required gates") or field_values(item.body_markdown, "Gates")),
                "related": related,
                "detailHtml": render_item_detail(item.body_markdown),
            }
        )
    ids = {item["id"] for item in data}
    for item in data:
        for related_id in list(item["related"]):
            if related_id not in ids:
                continue
            reverse = next((candidate for candidate in data if candidate["id"] == related_id), None)
            if reverse is not None and item["id"] not in reverse["related"]:
                reverse["related"].append(item["id"])

    gate_id_by_title = {item["title"]: item["id"] for item in data if item["type"] == "gate"}
    review_gate_aliases = (
        ("human readability", "HumanReadabilityReview"),
        ("expert technical", "TechnicalClarity"),
        ("implementer readiness", "PlanReadiness"),
        ("automation readiness", "AutomationReadiness"),
        ("zero-context", "FeatureClarity"),
    )
    planning_reviews_gate = gate_id_by_title.get("PlanningReviewsComplete")
    for item in data:
        if item["type"] != "review":
            continue
        related_review_gates = [planning_reviews_gate] if planning_reviews_gate else []
        normalized_title = item["title"].lower()
        for phrase, gate_title in review_gate_aliases:
            gate_id = gate_id_by_title.get(gate_title)
            if phrase in normalized_title and gate_id:
                related_review_gates.append(gate_id)
        for gate_id in related_review_gates:
            if gate_id and gate_id not in item["related"]:
                item["related"].append(gate_id)
            gate = next((candidate for candidate in data if candidate["id"] == gate_id), None)
            if gate is not None and item["id"] not in gate["related"]:
                gate["related"].append(item["id"])

    fallback_gate_targets = {
        "ProblemDefinitionComplete": "overview-problem",
        "TechnicalClarity": "overview-technical",
        "PlanStateSanity": "overview-plan-state",
        "FeatureClarity": "overview-problem",
    }
    for item in data:
        if item["type"] != "gate" or item["related"]:
            continue
        fallback_id = fallback_gate_targets.get(item["title"], "overview-plan-state")
        if fallback_id in ids:
            item["related"].append(fallback_id)
            overview = next((candidate for candidate in data if candidate["id"] == fallback_id), None)
            if overview is not None and item["id"] not in overview["related"]:
                overview["related"].append(item["id"])

    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


ARTIFACT_LAYER_ORDER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("plan", "Plan", ("Overview",)),
    ("governance", "Governance", ("Gates", "Decisions", "Risks")),
    ("delivery", "Delivery", ("Workstreams", "Phases")),
    ("automation", "Automation", ("Automation",)),
    ("review", "Review", ("Reviews",)),
)


def artifact_layer_for(lane: str) -> str:
    for layer_key, _, lanes in ARTIFACT_LAYER_ORDER:
        if lane in lanes:
            return layer_key
    return "context"


def render_artifact_cards(items: list[ArtifactItem]) -> str:
    return """
    <div class="graph-stage">
      <div class="tree-view" role="tree" aria-label="Plan branch view"></div>
      <div class="graph-viewport" tabindex="0" aria-label="Zoomable plan graph">
        <div class="graph-world">
          <div class="layer-bands" aria-hidden="true"></div>
          <svg class="graph-edges" aria-hidden="true">
            <defs>
              <marker id="edge-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z"></path>
              </marker>
            </defs>
            <g class="edge-root"></g>
          </svg>
          <div class="graph-nodes" role="list"></div>
        </div>
      </div>
      <p class="graph-status" aria-live="polite"></p>
    </div>
    """


def convert_plan_artifact(
    markdown: str,
    *,
    source_path: Path | None = None,
    title_override: str | None = None,
) -> str:
    _, body_markdown = strip_frontmatter(markdown)
    title = extract_title(body_markdown, source_path, title_override)
    plan_state = parse_key_values(section_lines(body_markdown, "Plan State"))
    items = build_artifact_items(body_markdown)
    return render_artifact_document(title, items, plan_state, source_path=source_path)


def render_artifact_document(
    title_raw: str,
    items: list[ArtifactItem],
    plan_state: dict[str, str],
    *,
    source_path: Path | None,
) -> str:
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    source_label = str(source_path) if source_path else "stdin"
    title = escape_text(title_raw)
    cards = render_artifact_cards(items)
    data = artifact_json(items)
    status = plan_state.get("Status", "unknown")
    stage = plan_state.get("CurrentStage", "unknown")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{title} Artifact Map</title>
<style>
{CSS}
{ARTIFACT_CSS}
</style>
</head>
<body class="artifact-view">
<a class="skip-link" href="#artifact-map">Skip to map</a>
<header class="page-header artifact-header">
  <div>
    <p class="eyebrow">Plan Artifact Map</p>
    <h1>{title}</h1>
    <p class="artifact-subhead">Status: <strong>{escape_text(status)}</strong> &middot; Stage: <strong>{escape_text(stage)}</strong></p>
  </div>
  <dl class="artifact-meta" aria-label="Artifact metadata">
    <div><dt>Source</dt><dd>{escape_text(source_label)}</dd></div>
    <div><dt>Generated</dt><dd>{escape_text(generated)}</dd></div>
  </dl>
</header>
<main class="artifact-shell" id="artifact-map">
  <section class="artifact-controls" aria-label="Artifact controls">
    <label for="artifact-search">Search</label>
    <input id="artifact-search" type="search" placeholder="Find gates, decisions, workstreams, risks...">
    <div class="control-groups">
      <div class="filter-row" role="group" aria-label="Artifact view">
        <button type="button" class="filter-chip is-active" data-view-mode="tree">Tree</button>
        <button type="button" class="filter-chip" data-view-mode="graph">Graph</button>
      </div>
      <div class="filter-row" role="group" aria-label="Filter artifacts by type">
        <button type="button" class="filter-chip is-active" data-filter="all">All</button>
        <button type="button" class="filter-chip" data-filter="gate">Gates</button>
        <button type="button" class="filter-chip" data-filter="decision">Decisions</button>
        <button type="button" class="filter-chip" data-filter="risk">Risks</button>
        <button type="button" class="filter-chip" data-filter="workstream">Workstreams</button>
        <button type="button" class="filter-chip" data-filter="leaf">Leaves</button>
      </div>
      <div class="filter-row layer-filters" role="group" aria-label="Filter artifacts by flow layer">
        <button type="button" class="filter-chip is-active" data-layer-filter="all">All layers</button>
        <button type="button" class="filter-chip" data-layer-filter="plan">Plan</button>
        <button type="button" class="filter-chip" data-layer-filter="governance">Governance</button>
        <button type="button" class="filter-chip" data-layer-filter="delivery">Delivery</button>
        <button type="button" class="filter-chip" data-layer-filter="automation">Automation</button>
        <button type="button" class="filter-chip" data-layer-filter="review">Review</button>
      </div>
      <div class="filter-row" role="group" aria-label="Graph edges">
        <button type="button" class="filter-chip" data-edge-mode="none">No lines</button>
        <button type="button" class="filter-chip is-active" data-edge-mode="selected">Focus lines</button>
        <button type="button" class="filter-chip" data-edge-mode="all">All edges</button>
      </div>
      <div class="graph-tools" role="group" aria-label="Graph zoom controls">
        <button type="button" class="icon-button" data-zoom-action="out" aria-label="Zoom out">-</button>
        <button type="button" class="icon-button" data-zoom-action="in" aria-label="Zoom in">+</button>
        <button type="button" class="tool-button" data-zoom-action="fit-width">Fit width</button>
        <button type="button" class="tool-button" data-zoom-action="fit-all">Fit all</button>
        <button type="button" class="tool-button" data-zoom-action="reset">100%</button>
      </div>
    </div>
  </section>
  <section class="artifact-map" aria-label="Interactive plan artifact map">
    {cards}
  </section>
  <aside class="detail-panel" aria-live="polite" aria-label="Selected artifact details">
    <div class="detail-empty">
      <p class="eyebrow">Selection</p>
      <h2>Pick an artifact</h2>
      <p>Click any item to highlight related plan objects and read the source context here.</p>
    </div>
  </aside>
</main>
<script type="application/json" id="artifact-data">{data}</script>
<script>
{ARTIFACT_JS}
</script>
</body>
</html>
"""


def convert_plan_markdown(
    markdown: str,
    *,
    source_path: Path | None = None,
    title_override: str | None = None,
    show_comments: bool = False,
    include_summary: bool = True,
) -> str:
    _, body_markdown = strip_frontmatter(markdown)
    title = extract_title(body_markdown, source_path, title_override)
    plan_state = parse_key_values(section_lines(body_markdown, "Plan State"))
    gate_results = parse_key_values(section_lines(body_markdown, "Gate Results"))
    renderer = MarkdownRenderer(show_comments=show_comments)
    html_body, headings = renderer.render(body_markdown)
    rendered = RenderedPlan(
        title=title,
        html_body=html_body,
        headings=headings,
        plan_state=plan_state,
        gate_results=gate_results,
    )
    return render_document(rendered, source_path=source_path, include_summary=include_summary)


def render_document(rendered: RenderedPlan, *, source_path: Path | None, include_summary: bool) -> str:
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    source_label = str(source_path) if source_path else "stdin"
    summary = render_summary(rendered.plan_state, rendered.gate_results) if include_summary else ""
    title = escape_text(rendered.title)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{title}</title>
<style>
{CSS}
</style>
</head>
<body>
<a class="skip-link" href="#plan-content">Skip to content</a>
<header class="page-header">
  <div>
    <p class="eyebrow">Plan Review Artifact</p>
    <h1>{title}</h1>
  </div>
  <dl class="artifact-meta" aria-label="Artifact metadata">
    <div><dt>Source</dt><dd>{escape_text(source_label)}</dd></div>
    <div><dt>Generated</dt><dd>{escape_text(generated)}</dd></div>
  </dl>
</header>
<div class="page-shell">
  <nav class="toc" aria-label="Plan sections">
    <h2>Sections</h2>
    {render_toc(rendered.headings)}
  </nav>
  <main id="plan-content" class="content" tabindex="-1">
    {summary}
    <article class="markdown-body">
{rendered.html_body}
    </article>
  </main>
</div>
</body>
</html>
"""


CSS = r"""
:root {
  color-scheme: light;
  --bg: #f6f8fb;
  --surface: #ffffff;
  --ink: #1f2937;
  --muted: #5f6b7a;
  --line: #d9e0ea;
  --accent: #2457c5;
  --accent-soft: #e8f0ff;
  --pass: #15803d;
  --pass-bg: #eaf7ef;
  --fail: #b42318;
  --fail-bg: #fff0ed;
  --warn: #a16207;
  --warn-bg: #fff7db;
  --na: #64748b;
  --na-bg: #edf2f7;
  --code-bg: #111827;
  --code-ink: #f8fafc;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  line-height: 1.55;
}

a {
  color: var(--accent);
  text-decoration-thickness: 0.08em;
  text-underline-offset: 0.14em;
}

.skip-link {
  left: 1rem;
  padding: 0.65rem 0.9rem;
  position: absolute;
  top: -4rem;
  z-index: 10;
  background: var(--ink);
  color: white;
  border-radius: 0.35rem;
}

.skip-link:focus {
  top: 1rem;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 2rem;
  align-items: flex-end;
  padding: 2rem clamp(1rem, 4vw, 3rem);
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}

.page-header h1 {
  margin: 0;
  font-size: clamp(1.65rem, 3vw, 2.6rem);
  line-height: 1.12;
  letter-spacing: 0;
}

.eyebrow {
  margin: 0 0 0.4rem;
  color: var(--muted);
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
}

.artifact-meta {
  display: grid;
  gap: 0.55rem;
  min-width: min(28rem, 100%);
  margin: 0;
  color: var(--muted);
  font-size: 0.85rem;
}

.artifact-meta div,
.summary-grid div {
  min-width: 0;
}

.artifact-meta dt,
.summary-grid dt {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
}

.artifact-meta dd,
.summary-grid dd {
  margin: 0.1rem 0 0;
  overflow-wrap: anywhere;
}

.page-shell {
  display: grid;
  grid-template-columns: minmax(14rem, 19rem) minmax(0, 1fr);
  gap: 1.5rem;
  max-width: 96rem;
  margin: 0 auto;
  padding: 1.5rem clamp(1rem, 4vw, 3rem) 4rem;
}

.toc {
  align-self: start;
  position: sticky;
  top: 1rem;
  max-height: calc(100vh - 2rem);
  overflow: auto;
  padding: 1rem;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 0.5rem;
}

.toc h2 {
  margin: 0 0 0.75rem;
  font-size: 0.9rem;
}

.toc-list {
  list-style: none;
  margin: 0;
  padding: 0;
  font-size: 0.88rem;
}

.toc-list li {
  margin: 0.2rem 0;
}

.toc-list a {
  display: block;
  padding: 0.25rem 0.2rem;
  border-radius: 0.25rem;
  color: var(--ink);
  text-decoration: none;
}

.toc-list a:hover,
.toc-list a:focus {
  background: var(--accent-soft);
  color: var(--accent);
}

.toc-level-3 { padding-left: 0.8rem; }
.toc-level-4 { padding-left: 1.6rem; }
.toc-level-5,
.toc-level-6 { padding-left: 2.4rem; }

.content {
  min-width: 0;
}

.summary-panel,
.markdown-body {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 0.5rem;
}

.summary-panel {
  margin-bottom: 1rem;
  padding: 1.2rem;
}

.summary-panel h2,
.summary-panel h3 {
  margin-top: 0;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
  gap: 0.85rem 1rem;
  margin: 0;
}

.summary-value {
  display: inline-block;
  max-width: 100%;
  border-radius: 0.35rem;
  padding: 0.12rem 0;
}

.summary-pass { color: var(--pass); font-weight: 700; }
.summary-fail { color: var(--fail); font-weight: 700; }
.summary-warn { color: var(--warn); font-weight: 700; }
.summary-na { color: var(--na); font-weight: 700; }

.summary-subtitle {
  padding-top: 1rem;
  border-top: 1px solid var(--line);
}

.gate-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
  gap: 0.65rem;
}

.gate-card {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: center;
  padding: 0.7rem 0.8rem;
  border: 1px solid var(--line);
  border-radius: 0.45rem;
  font-size: 0.88rem;
}

.gate-card span {
  overflow-wrap: anywhere;
}

.gate-pass { background: var(--pass-bg); color: var(--pass); border-color: #bfe8cb; }
.gate-fail { background: var(--fail-bg); color: var(--fail); border-color: #ffd1c8; }
.gate-warn { background: var(--warn-bg); color: var(--warn); border-color: #f6dfa1; }
.gate-na { background: var(--na-bg); color: var(--na); border-color: #d5dee9; }
.gate-info { background: var(--accent-soft); color: var(--accent); border-color: #c8d8ff; }

.markdown-body {
  padding: clamp(1rem, 3vw, 2rem);
  overflow: hidden;
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  color: #111827;
  line-height: 1.22;
  letter-spacing: 0;
}

.markdown-body h1 {
  margin-top: 0;
  font-size: 2rem;
}

.markdown-body h2 {
  margin-top: 2.3rem;
  padding-top: 1rem;
  border-top: 1px solid var(--line);
  font-size: 1.45rem;
}

.markdown-body h3 {
  margin-top: 1.6rem;
  font-size: 1.15rem;
}

.heading-anchor {
  margin-left: 0.45rem;
  opacity: 0;
  color: var(--muted);
  text-decoration: none;
  font-size: 0.8em;
}

h1:hover .heading-anchor,
h2:hover .heading-anchor,
h3:hover .heading-anchor,
h4:hover .heading-anchor,
h5:hover .heading-anchor,
h6:hover .heading-anchor,
.heading-anchor:focus {
  opacity: 1;
}

.markdown-body p,
.markdown-body ul,
.markdown-body ol,
.markdown-body pre,
.markdown-body table {
  margin-top: 0.75rem;
  margin-bottom: 0.75rem;
}

.markdown-body ul,
.markdown-body ol {
  padding-left: 1.45rem;
}

.markdown-body li + li {
  margin-top: 0.25rem;
}

.kv-line {
  margin: 0.32rem 0;
}

code {
  padding: 0.08rem 0.28rem;
  border-radius: 0.25rem;
  background: #eef2f7;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  font-size: 0.92em;
}

pre {
  overflow: auto;
  padding: 1rem;
  border-radius: 0.45rem;
  background: var(--code-bg);
  color: var(--code-ink);
}

pre code {
  padding: 0;
  background: transparent;
  color: inherit;
}

.table-wrap {
  overflow-x: auto;
  margin: 1rem 0;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.92rem;
}

th,
td {
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--line);
  vertical-align: top;
}

th {
  background: #eef3fa;
  text-align: left;
}

.align-right { text-align: right; }
.align-center { text-align: center; }
.align-left { text-align: left; }

.task-checkbox {
  width: 1rem;
  height: 1rem;
  margin: 0 0.35rem 0 0;
  vertical-align: -0.15rem;
}

.html-comment {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
}

:target {
  scroll-margin-top: 1rem;
  outline: 2px solid var(--accent);
  outline-offset: 0.25rem;
}

@media (max-width: 860px) {
  .page-header {
    display: block;
  }

  .artifact-meta {
    margin-top: 1rem;
  }

  .page-shell {
    display: block;
  }

  .toc {
    position: static;
    max-height: none;
    margin-bottom: 1rem;
  }
}

@media print {
  body {
    background: white;
  }

  .toc,
  .skip-link,
  .heading-anchor {
    display: none;
  }

  .page-header,
  .page-shell {
    padding: 0;
  }

  .page-shell {
    display: block;
    max-width: none;
  }

  .summary-panel,
  .markdown-body {
    border: 0;
  }
}
"""


ARTIFACT_CSS = r"""
.artifact-view {
  min-height: 100vh;
  background: #f4f6f8;
}

.artifact-header {
  align-items: center;
  padding-block: 1.15rem;
}

.artifact-subhead {
  margin: 0.55rem 0 0;
  color: var(--muted);
}

.artifact-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) clamp(20rem, 22vw, 31rem);
  grid-template-rows: auto minmax(0, 1fr);
  grid-template-areas:
    "controls details"
    "map details";
  gap: 0.75rem;
  width: 100%;
  min-height: calc(100vh - 7rem);
  margin: 0;
  padding: 0.75rem clamp(0.75rem, 1.4vw, 1.5rem) 1rem;
}

.artifact-controls {
  grid-area: controls;
  display: grid;
  grid-template-columns: auto minmax(14rem, 1fr);
  gap: 0.55rem 0.7rem;
  align-items: center;
  min-width: 0;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  background: var(--surface);
}

.artifact-controls label {
  font-size: 0.78rem;
  font-weight: 800;
  color: var(--muted);
  text-transform: uppercase;
}

.artifact-controls input {
  width: 100%;
  min-height: 2.1rem;
  border: 1px solid var(--line);
  border-radius: 0.35rem;
  padding: 0.28rem 0.55rem;
  font: inherit;
  font-size: 0.86rem;
}

.control-groups {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.9rem;
  align-items: center;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}

.filter-chip {
  min-height: 1.75rem;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0.2rem 0.48rem;
  background: white;
  color: var(--ink);
  font: inherit;
  font-size: 0.74rem;
  cursor: pointer;
}

.filter-chip.is-active,
.filter-chip:focus {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.graph-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-left: auto;
}

.icon-button,
.tool-button {
  min-height: 1.75rem;
  border: 1px solid var(--line);
  border-radius: 0.35rem;
  background: #fff;
  color: var(--ink);
  font: inherit;
  font-size: 0.74rem;
  cursor: pointer;
}

.icon-button {
  width: 1.85rem;
  padding: 0;
  font-weight: 800;
}

.tool-button {
  padding: 0.2rem 0.48rem;
}

.icon-button:hover,
.icon-button:focus,
.tool-button:hover,
.tool-button:focus {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.artifact-map {
  grid-area: map;
  position: relative;
  min-height: min(74rem, calc(100vh - 12rem));
  overflow: auto;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 0.55rem;
  background: #f8fafc;
}

.graph-stage,
.graph-viewport {
  position: relative;
  width: 100%;
  min-height: inherit;
}

.tree-view {
  display: grid;
  gap: 1rem;
  padding: 0.9rem;
}

.tree-view.is-hidden,
.graph-viewport.is-hidden {
  display: none;
}

.tree-section {
  min-width: 0;
}

.tree-section-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: end;
  margin: 0 0 0.55rem;
  padding: 0 0.1rem;
}

.tree-section-header h2 {
  margin: 0;
  color: #111827;
  font-size: 0.95rem;
  line-height: 1.2;
}

.tree-section-header p {
  margin: 0.18rem 0 0;
  color: #64748b;
  font-size: 0.76rem;
}

.tree-section-count {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 0.14rem 0.45rem;
  background: #e2e8f0;
  color: #475569;
  font-size: 0.7rem;
  font-weight: 800;
}

.orientation-grid,
.register-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
  gap: 0.65rem;
}

.stream-list {
  display: grid;
  gap: 0.75rem;
}

.stream-panel {
  display: grid;
  grid-template-columns: minmax(14rem, 17rem) minmax(0, 1fr);
  gap: 0.85rem;
  align-items: stretch;
  padding: 0.75rem;
  border: 1px solid #d5deea;
  border-radius: 0.55rem;
  background: #ffffff;
  box-shadow: 0 0.24rem 0.7rem rgba(15, 23, 42, 0.045);
}

.tree-stem {
  position: relative;
  padding: 0.7rem;
  border: 1px solid #c7d2e1;
  border-left: 0.3rem solid var(--accent);
  border-radius: 0.45rem;
  background: #f8fafc;
}

.tree-stem button,
.tree-node {
  width: 100%;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.tree-stem strong,
.tree-node strong {
  display: block;
  overflow-wrap: anywhere;
  font-size: 0.86rem;
  line-height: 1.22;
}

.tree-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-top: 0.45rem;
}

.tree-pill {
  border-radius: 999px;
  padding: 0.12rem 0.38rem;
  background: #eef2f7;
  color: #64748b;
  font-size: 0.66rem;
  font-weight: 800;
}

.tree-branches {
  display: grid;
  gap: 0.65rem;
  min-width: 0;
}

.branch-group {
  min-width: 0;
}

.branch-group h3 {
  margin: 0 0 0.35rem;
  color: #475569;
  font-size: 0.72rem;
  line-height: 1.2;
  text-transform: uppercase;
}

.branch-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  gap: 0.5rem;
}

.tree-branch {
  position: relative;
  min-width: 0;
  padding: 0.65rem 0.7rem;
  border: 1px solid #dbe3ee;
  border-left: 0.22rem solid #94a3b8;
  border-radius: 0.45rem;
  background: #fff;
  box-shadow: 0 0.22rem 0.65rem rgba(15, 23, 42, 0.04);
}

.tree-branch::before {
  content: none;
}

.tree-node {
  display: grid;
  gap: 0.28rem;
}

.tree-branch.is-selected,
.tree-stem.is-selected {
  outline: 2px solid rgba(36, 87, 197, 0.25);
  border-color: var(--accent);
}

.tree-branch.is-related,
.tree-stem.is-related {
  background: #f0fdfa;
  border-color: #0f766e;
}

.tree-branch.is-dim,
.tree-stem.is-dim {
  opacity: 0.62;
}

.orientation-card {
  border-left-width: 0.3rem;
  min-height: 8rem;
}

.tree-branch.node-gate { border-left-color: var(--pass); }
.tree-branch.node-leaf { border-left-color: var(--accent); }
.tree-branch.node-decision { border-left-color: #7c3aed; }
.tree-branch.node-risk,
.tree-branch.node-assumption { border-left-color: var(--warn); }
.tree-branch.node-review { border-left-color: #0f766e; }

@media (max-width: 1180px) {
  .stream-panel {
    grid-template-columns: 1fr;
  }
}

.graph-viewport {
  height: 100%;
  inset: 0;
  overflow: hidden;
  background:
    linear-gradient(rgba(148, 163, 184, 0.12) 1px, transparent 1px) 0 0 / 3rem 3rem,
    linear-gradient(90deg, rgba(148, 163, 184, 0.12) 1px, transparent 1px) 0 0 / 3rem 3rem,
    #f8fafc;
  cursor: grab;
  touch-action: none;
}

.graph-viewport.is-panning {
  cursor: grabbing;
}

.graph-world {
  position: absolute;
  top: 0;
  left: 0;
  transform-origin: 0 0;
  will-change: transform;
}

.layer-bands,
.graph-edges,
.graph-nodes {
  position: absolute;
  inset: 0;
}

.layer-band {
  position: absolute;
  border: 1px solid #dbe3ee;
  border-radius: 0.65rem;
  background: rgba(255, 255, 255, 0.68);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
}

.layer-band h2 {
  margin: 0;
  padding: 0.55rem 0.65rem;
  border-bottom: 1px solid #e4eaf2;
  color: #475569;
  font-size: 0.78rem;
  letter-spacing: 0;
  text-transform: uppercase;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.layer-count {
  float: right;
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: none;
}

.graph-edges {
  overflow: visible;
  pointer-events: none;
}

.graph-edges marker path {
  fill: #8aa4d6;
}

.edge {
  fill: none;
  stroke: #64748b;
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-linejoin: round;
  marker-end: url(#edge-arrow);
  opacity: 0.28;
}

.edge.is-active {
  stroke: #2457c5;
  stroke-width: 2.8;
  opacity: 0.95;
}

.edge.is-muted {
  opacity: 0.08;
}

.graph-node {
  position: absolute;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 0.2rem;
  height: 4.5rem;
  overflow: hidden;
  padding: 0.44rem 0.52rem;
  border: 1px solid var(--line);
  border-left: 0.24rem solid var(--accent);
  border-radius: 0.45rem;
  background: white;
  color: var(--ink);
  text-align: left;
  font: inherit;
  cursor: pointer;
  box-shadow: 0 0.3rem 0.8rem rgba(15, 23, 42, 0.05);
  transition: border-color 120ms ease, box-shadow 120ms ease, opacity 120ms ease, transform 120ms ease;
}

.graph-node:hover,
.graph-node:focus {
  border-color: var(--accent);
  box-shadow: 0 0.3rem 0.8rem rgba(31, 41, 55, 0.08);
  transform: translateY(-1px);
}

.graph-node.is-selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(36, 87, 197, 0.16), 0 0.45rem 1rem rgba(31, 41, 55, 0.10);
}

.graph-node.is-related {
  border-color: #0f766e;
  background: #f0fdfa;
}

.graph-node.is-dim {
  opacity: 0.55;
}

.node-topline,
.node-footer {
  display: flex;
  justify-content: space-between;
  gap: 0.45rem;
  align-items: center;
}

.node-type {
  width: fit-content;
  border-radius: 999px;
  padding: 0.06rem 0.34rem;
  background: #eef2f7;
  color: var(--muted);
  font-size: 0.62rem;
  font-weight: 800;
  text-transform: uppercase;
}

.node-status {
  overflow: hidden;
  max-width: 8.5rem;
  color: var(--muted);
  font-size: 0.66rem;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.graph-node strong {
  display: -webkit-box;
  overflow-wrap: anywhere;
  overflow: hidden;
  font-size: 0.78rem;
  line-height: 1.18;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.node-summary {
  display: -webkit-box;
  overflow: hidden;
  color: #64748b;
  font-size: 0.68rem;
  line-height: 1.2;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
}

.node-footer {
  margin-top: auto;
  color: var(--muted);
  font-size: 0.66rem;
  overflow: hidden;
}

.status-pass { border-left-color: var(--pass); }
.status-fail { border-left-color: var(--fail); }
.status-warn { border-left-color: var(--warn); }
.status-na { border-left-color: var(--na); }
.status-info { border-left-color: var(--accent); }

.graph-status {
  position: absolute;
  right: 0.65rem;
  bottom: 0.45rem;
  z-index: 5;
  margin: 0;
  border-radius: 999px;
  padding: 0.18rem 0.5rem;
  background: rgba(255, 255, 255, 0.9);
  color: #64748b;
  font-size: 0.7rem;
  font-weight: 700;
  box-shadow: 0 0.2rem 0.8rem rgba(15, 23, 42, 0.08);
}

.detail-panel {
  grid-area: details;
  position: sticky;
  top: 0.75rem;
  max-height: calc(100vh - 1.5rem);
  overflow: auto;
  padding: 0.9rem;
  border: 1px solid var(--line);
  border-radius: 0.55rem;
  background: white;
}

.detail-panel h2 {
  margin: 0.15rem 0 0.5rem;
  font-size: 1.1rem;
  line-height: 1.2;
}

.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 0.8rem;
}

.detail-pill {
  border-radius: 999px;
  padding: 0.16rem 0.45rem;
  background: #eef2f7;
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 700;
}

.related-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin: 0.75rem 0 1rem;
}

.related-list button {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0.22rem 0.5rem;
  background: white;
  color: var(--accent);
  font: inherit;
  font-size: 0.75rem;
  cursor: pointer;
}

.detail-body {
  padding-top: 0.75rem;
  border-top: 1px solid var(--line);
  font-size: 0.86rem;
}

.detail-body h3,
.detail-body h4 {
  margin-top: 1rem;
}

.detail-body ul,
.detail-body ol {
  padding-left: 1.25rem;
}

@media (max-width: 980px) {
  .artifact-shell {
    display: block;
    min-height: 0;
  }

  .artifact-controls {
    grid-template-columns: 1fr;
  }

  .detail-panel {
    position: static;
    max-height: none;
    margin-top: 1rem;
  }

  .artifact-map {
    min-height: 32rem;
  }

  .graph-tools {
    margin-left: 0;
  }
}
"""


ARTIFACT_JS = r"""
const artifactData = JSON.parse(document.getElementById("artifact-data").textContent);
const byId = new Map(artifactData.map((item) => [item.id, item]));
const detail = document.querySelector(".detail-panel");
const treeView = document.querySelector(".tree-view");
const viewport = document.querySelector(".graph-viewport");
const world = document.querySelector(".graph-world");
const bandsLayer = document.querySelector(".layer-bands");
const nodesLayer = document.querySelector(".graph-nodes");
const edgeSvg = document.querySelector(".graph-edges");
const edgeRoot = document.querySelector(".edge-root");
const graphStatus = document.querySelector(".graph-status");
const search = document.getElementById("artifact-search");
const laneRank = new Map([
  ["Overview", 0],
  ["Gates", 1],
  ["Decisions", 2],
  ["Risks", 3],
  ["Workstreams", 4],
  ["Phases", 5],
  ["Automation", 6],
  ["Reviews", 7],
]);
const nodeElements = new Map();
const treeElements = new Map();
const nodePositions = new Map();
let visibleItems = [];
let graphSize = { width: 1200, height: 800 };
let transform = { x: 0, y: 0, k: 1 };
let activeType = "all";
let activeLayer = "all";
let activeView = "tree";
let edgeMode = "selected";
let selectedId = null;
let layoutFrame = 0;
let panning = null;

function tokenSet(item) {
  return new Set(item.tokens || []);
}

function relationIds(item) {
  const ids = new Set(item.related || []);
  return ids;
}

function renderDetail(item) {
  const related = relationIds(item);
  const relatedButtons = Array.from(related)
    .map((id) => byId.get(id))
    .filter(Boolean)
    .slice(0, 18)
    .map((other) => `<button type="button" data-related-id="${other.id}">${escapeHtml(other.title)}</button>`)
    .join("");
  const tokens = (item.tokens || []).slice(0, 12).map((token) => `<span class="detail-pill">${escapeHtml(token)}</span>`).join("");
  detail.innerHTML = `
    <p class="eyebrow">${escapeHtml(item.lane)} / ${escapeHtml(item.type)}</p>
    <h2>${escapeHtml(item.title)}</h2>
    <div class="detail-meta">
      <span class="detail-pill">${escapeHtml(item.status || "context")}</span>
      ${tokens}
    </div>
    ${relatedButtons ? `<h3>Related</h3><div class="related-list">${relatedButtons}</div>` : ""}
    <div class="detail-body">${item.detailHtml}</div>
  `;
  detail.querySelectorAll("[data-related-id]").forEach((button) => {
    button.addEventListener("click", () => {
      revealNode(button.dataset.relatedId);
      selectNode(button.dataset.relatedId, { center: true });
    });
  });
}

function renderEmptyDetail() {
  detail.innerHTML = `
    <div class="detail-empty">
      <p class="eyebrow">Selection</p>
      <h2>Pick an artifact</h2>
      <p>Select a node to see its source context and explicit related nodes.</p>
    </div>
  `;
}

function selectNode(id, options = {}) {
  const item = byId.get(id);
  if (!item) return;
  selectedId = id;
  const related = relationIds(item);
  const hasRelated = related.size > 0;
  nodeElements.forEach((node, cardId) => {
    node.classList.toggle("is-selected", cardId === id);
    node.classList.toggle("is-related", related.has(cardId));
    node.classList.toggle("is-dim", hasRelated && cardId !== id && !related.has(cardId));
  });
  treeElements.forEach((node, cardId) => {
    node.classList.toggle("is-selected", cardId === id);
    node.classList.toggle("is-related", related.has(cardId));
    node.classList.toggle("is-dim", hasRelated && cardId !== id && !related.has(cardId));
  });
  renderDetail(item);
  if (options.center && activeView === "graph") centerNode(id);
  drawEdges();
}

function clearSelectionIfHidden() {
  if (!selectedId) return;
  if (!visibleItems.some((item) => item.id === selectedId)) {
    selectedId = null;
    renderEmptyDetail();
  }
}

function defaultSelectionId() {
  const visibleIds = new Set(visibleItems.map((item) => item.id));
  let best = null;
  let bestScore = -1;
  for (const item of visibleItems) {
    const relatedScore = Array.from(relationIds(item)).filter((id) => visibleIds.has(id)).length;
    const tokenScore = (item.tokens || []).length;
    const laneBonus = item.id === "overview-technical" ? 4 : 0;
    const score = relatedScore * 4 + tokenScore + laneBonus;
    if (score > bestScore) {
      best = item.id;
      bestScore = score;
    }
  }
  return best;
}

function filteredItems() {
  const query = (search.value || "").trim().toLowerCase();
  return artifactData.filter((item) => {
    const matchesType = activeType === "all" || item.type === activeType;
    const matchesLayer = activeLayer === "all" || item.layer === activeLayer;
    const haystack = `${item.title} ${item.status} ${item.summary} ${(item.tokens || []).join(" ")}`.toLowerCase();
    const matchesSearch = !query || haystack.includes(query);
  return matchesType && matchesLayer && matchesSearch;
  });
}

function clusterRank(key) {
  if (key === "overview") return -20;
  const ws = /^WS(\d+)/.exec(key || "");
  if (ws) return Number(ws[1]);
  if (key === "gates") return 900;
  if (key === "review") return 1000;
  return 800;
}

function itemRank(item) {
  const typeOrder = new Map([
    ["overview", 0],
    ["workstream", 1],
    ["leaf", 2],
    ["gate", 3],
    ["phase", 4],
    ["decision", 5],
    ["risk", 6],
    ["assumption", 7],
    ["review", 8],
  ]);
  return typeOrder.get(item.type) ?? 50;
}

function clusteredItems(items) {
  const clusters = new Map();
  for (const item of items) {
    const key = item.cluster || item.lane;
    if (!clusters.has(key)) {
      clusters.set(key, { key, label: item.clusterLabel || key, items: [] });
    }
    clusters.get(key).items.push(item);
  }
  return Array.from(clusters.values())
    .map((cluster) => ({
      ...cluster,
      items: cluster.items.sort((left, right) => {
        const rankDelta = itemRank(left) - itemRank(right);
        if (rankDelta) return rankDelta;
        const laneDelta = (laneRank.get(left.lane) ?? 99) - (laneRank.get(right.lane) ?? 99);
        if (laneDelta) return laneDelta;
        return left.title.localeCompare(right.title);
      }),
    }))
    .sort((left, right) => {
      const rankDelta = clusterRank(left.key) - clusterRank(right.key);
      if (rankDelta) return rankDelta;
      return left.label.localeCompare(right.label);
    });
}

function branchMeta(item) {
  const parts = [];
  if ((item.parents || []).length) parts.push(`parent ${item.parents[0]}`);
  if ((item.dependencies || []).length) parts.push(`${item.dependencies.length} deps`);
  if ((item.gates || []).length) parts.push(`${item.gates.length} gates`);
  const links = relationIds(item).size;
  if (links) parts.push(`${links} links`);
  return parts;
}

function treeCard(item, className = "tree-branch") {
  const meta = branchMeta(item).map((part) => `<span class="tree-pill">${escapeHtml(part)}</span>`).join("");
  return `
    <div class="${className} node-${escapeHtml(item.type)} status-${escapeHtml(item.statusClass || "info")}" data-tree-shell="${escapeHtml(item.id)}">
      <button type="button" class="tree-node" data-tree-id="${escapeHtml(item.id)}">
        <span class="node-topline">
          <span class="node-type">${escapeHtml(item.type)}</span>
          <span class="node-status">${escapeHtml(item.status || "context")}</span>
        </span>
        <strong>${escapeHtml(item.title)}</strong>
        ${item.summary ? `<span class="node-summary">${escapeHtml(item.summary)}</span>` : ""}
        ${meta ? `<span class="tree-meta">${meta}</span>` : ""}
      </button>
    </div>
  `;
}

function treeSection(title, subtitle, bodyHtml, count) {
  if (!bodyHtml) return "";
  return `
    <section class="tree-section">
      <div class="tree-section-header">
        <div>
          <h2>${escapeHtml(title)}</h2>
          ${subtitle ? `<p>${escapeHtml(subtitle)}</p>` : ""}
        </div>
        <span class="tree-section-count">${count}</span>
      </div>
      ${bodyHtml}
    </section>
  `;
}

function branchGroup(title, items) {
  if (!items.length) return "";
  return `
    <div class="branch-group">
      <h3>${escapeHtml(title)}</h3>
      <div class="branch-grid">${items.map((item) => treeCard(item)).join("")}</div>
    </div>
  `;
}

function streamPanel(cluster) {
  const stem = cluster.items.find((item) => item.type === "workstream");
  const branches = cluster.items.filter((item) => item.id !== stem?.id);
  const leaves = branches.filter((item) => item.type === "leaf");
  const gates = branches.filter((item) => item.type === "gate");
  const phases = branches.filter((item) => item.type === "phase");
  const other = branches.filter((item) => !["leaf", "gate", "phase"].includes(item.type));
  const stemMeta = stem ? branchMeta(stem).map((part) => `<span class="tree-pill">${escapeHtml(part)}</span>`).join("") : "";
  const stemBody = stem ? `
    <button type="button" data-tree-id="${escapeHtml(stem.id)}">
      <span class="node-type">${escapeHtml(cluster.key)}</span>
      <strong>${escapeHtml(stem.title)}</strong>
      ${stem.summary ? `<span class="node-summary">${escapeHtml(stem.summary)}</span>` : ""}
      ${stemMeta ? `<span class="tree-meta">${stemMeta}</span>` : ""}
    </button>
  ` : `
    <span class="node-type">${escapeHtml(cluster.key)}</span>
    <strong>${escapeHtml(cluster.label)}</strong>
    <span class="node-summary">Filtered stream context</span>
  `;
  return `
    <section class="stream-panel" data-cluster="${escapeHtml(cluster.key)}">
      <div class="tree-stem" ${stem ? `data-tree-shell="${escapeHtml(stem.id)}"` : ""}>${stemBody}</div>
      <div class="tree-branches">
        ${branchGroup("Implementation leaves", leaves)}
        ${branchGroup("Gates", gates)}
        ${branchGroup("Phases", phases)}
        ${branchGroup("Other linked items", other)}
      </div>
    </section>
  `;
}

function renderTree() {
  const items = filteredItems();
  visibleItems = items;
  clearSelectionIfHidden();
  treeElements.clear();
  const clusters = clusteredItems(items);
  const overview = items.filter((item) => item.type === "overview");
  const workstreams = clusters.filter((cluster) => /^WS\d+/.test(cluster.key));
  const decisions = items.filter((item) => item.type === "decision");
  const risks = items.filter((item) => item.type === "risk" || item.type === "assumption");
  const reviews = items.filter((item) => item.type === "review");
  const orphanGates = items.filter((item) => item.type === "gate" && !/^WS\d+/.test(item.cluster || ""));
  const other = items.filter((item) => {
    if (item.type === "overview" || item.type === "decision" || item.type === "risk" || item.type === "assumption" || item.type === "review") return false;
    if (item.type === "gate" && !/^WS\d+/.test(item.cluster || "")) return false;
    if (/^WS\d+/.test(item.cluster || "")) return false;
    return true;
  });

  const sections = [
    treeSection(
      "Plan orientation",
      "State, problem, and technical framing stand apart from execution work.",
      overview.length ? `<div class="orientation-grid">${overview.map((item) => treeCard(item, "tree-branch orientation-card")).join("")}</div>` : "",
      overview.length
    ),
    treeSection(
      "Execution streams",
      "Workstreams own their implementation leaves and gates.",
      workstreams.length ? `<div class="stream-list">${workstreams.map((cluster) => streamPanel(cluster)).join("")}</div>` : "",
      workstreams.length
    ),
    treeSection(
      "Decision ledger",
      "Architectural decisions govern the whole plan instead of belonging to one stream.",
      decisions.length ? `<div class="register-grid">${decisions.map((item) => treeCard(item)).join("")}</div>` : "",
      decisions.length
    ),
    treeSection(
      "Risk register",
      "Risks and assumptions are cross-cutting checks on the plan.",
      risks.length ? `<div class="register-grid">${risks.map((item) => treeCard(item)).join("")}</div>` : "",
      risks.length
    ),
    treeSection(
      "Review evidence",
      "Reviews validate the plan as a whole and connect back to review gates.",
      reviews.length ? `<div class="register-grid">${reviews.map((item) => treeCard(item)).join("")}</div>` : "",
      reviews.length
    ),
    treeSection(
      "Global gates",
      "Gates without a specific workstream relationship remain plan-level controls.",
      orphanGates.length ? `<div class="register-grid">${orphanGates.map((item) => treeCard(item)).join("")}</div>` : "",
      orphanGates.length
    ),
    treeSection(
      "Other artifacts",
      "Additional filtered artifacts that do not fit the main plan tree.",
      other.length ? `<div class="register-grid">${other.map((item) => treeCard(item)).join("")}</div>` : "",
      other.length
    ),
  ].filter(Boolean);

  treeView.innerHTML = sections.join("") || `<div class="detail-empty"><h2>No matching artifacts</h2></div>`;
  treeView.querySelectorAll("[data-tree-id]").forEach((button) => {
    const id = button.dataset.treeId;
    const shell = button.closest("[data-tree-shell]") || button;
    treeElements.set(id, shell);
    button.addEventListener("click", () => selectNode(id));
  });
  if (!selectedId && visibleItems.length) {
    selectedId = defaultSelectionId();
    const selected = byId.get(selectedId);
    if (selected) renderDetail(selected);
  }
  if (selectedId) selectNode(selectedId);
  updateStatus();
}

function applyFilters() {
  if (activeView === "tree") {
    renderTree();
  } else {
    scheduleLayout({ fit: "width" });
  }
}

function revealNode(id) {
  if (visibleItems.some((item) => item.id === id)) return;
  activeType = "all";
  activeLayer = "all";
  search.value = "";
  setActiveFilter("[data-filter]", "all");
  setActiveFilter("[data-layer-filter]", "all");
  applyFilters();
}

function setActiveFilter(selector, value) {
  document.querySelectorAll(selector).forEach((button) => {
    const buttonValue = button.dataset.filter || button.dataset.layerFilter || button.dataset.edgeMode || button.dataset.viewMode || "all";
    button.classList.toggle("is-active", buttonValue === value);
  });
}

function sortedGroupItems(items, groupKey) {
  return items
    .filter((item) => item.lane === groupKey)
    .sort((left, right) => {
      const laneDelta = (laneRank.get(left.lane) ?? 99) - (laneRank.get(right.lane) ?? 99);
      if (laneDelta) return laneDelta;
      return left.title.localeCompare(right.title);
    });
}

function layoutGraph(options = {}) {
  visibleItems = filteredItems();
  clearSelectionIfHidden();
  nodeElements.clear();
  nodePositions.clear();
  nodesLayer.innerHTML = "";
  bandsLayer.innerHTML = "";

  const visibleByLayer = clusteredItems(visibleItems);

  const viewportWidth = Math.max(640, viewport.clientWidth || 1200);
  const layerCount = Math.max(1, visibleByLayer.length);
  const nodeWidth = viewportWidth >= 1500 ? 300 : 276;
  const gapX = 24;
  const gapRow = 26;
  const nodeHeight = 72;
  const gapY = 12;
  const headerHeight = 48;
  const left = 32;
  const layerPad = 12;
  const columnsPerRow = Math.max(1, Math.min(4, Math.floor((viewportWidth - left * 2 + gapX) / (nodeWidth + gapX))));
  const rows = [];
  for (let index = 0; index < visibleByLayer.length; index += columnsPerRow) {
    rows.push(visibleByLayer.slice(index, index + columnsPerRow));
  }
  const rowHeights = rows.map((row) => {
    const maxItems = Math.max(1, ...row.map((layer) => layer.items.length));
    return headerHeight + maxItems * (nodeHeight + gapY) + 28;
  });
  const height = Math.max(620, 18 + rowHeights.reduce((sum, value) => sum + value, 0) + gapRow * Math.max(0, rows.length - 1) + 20);
  const activeColumns = Math.min(columnsPerRow, layerCount);
  const width = Math.max(720, left * 2 + activeColumns * nodeWidth + Math.max(0, activeColumns - 1) * gapX);

  graphSize = { width, height };
  world.style.width = `${width}px`;
  world.style.height = `${height}px`;
  edgeSvg.setAttribute("width", width);
  edgeSvg.setAttribute("height", height);
  edgeSvg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  let rowTop = 18;
  rows.forEach((row, rowIndex) => {
    row.forEach((layer, columnIndex) => {
    const x = left + columnIndex * (nodeWidth + gapX);
    const clusterHeight = rowHeights[rowIndex];
    const band = document.createElement("section");
    band.className = `layer-band lane-${layer.key.toLowerCase()}`;
    band.style.left = `${x - layerPad}px`;
    band.style.top = `${rowTop}px`;
    band.style.width = `${nodeWidth + layerPad * 2}px`;
    band.style.height = `${clusterHeight}px`;
    band.innerHTML = `<h2>${escapeHtml(layer.label)} <span class="layer-count">${layer.items.length}</span></h2>`;
    bandsLayer.appendChild(band);

    layer.items.forEach((item, index) => {
      const y = rowTop + headerHeight + index * (nodeHeight + gapY);
      nodePositions.set(item.id, { x, y, width: nodeWidth, height: nodeHeight });
      const node = document.createElement("button");
      node.type = "button";
      node.className = `graph-node node-${item.type} status-${item.statusClass || "info"}`;
      node.style.left = `${x}px`;
      node.style.top = `${y}px`;
      node.style.width = `${nodeWidth}px`;
      node.style.height = `${nodeHeight}px`;
      node.dataset.nodeId = item.id;
      node.dataset.type = item.type;
      node.dataset.layer = item.layer;
      node.dataset.lane = item.lane;
      const dependencyCount = (item.dependencies || []).length;
      const gateCount = (item.gates || []).length;
      const parentText = (item.parents || [])[0] || "";
      const relationMeta = [
        parentText ? `parent ${escapeHtml(parentText)}` : "",
        dependencyCount ? `${dependencyCount} deps` : "",
        gateCount ? `${gateCount} gates` : "",
      ].filter(Boolean).join(" | ");
      node.innerHTML = `
        <span class="node-topline">
          <span class="node-type">${escapeHtml(item.type)}</span>
          <span class="node-status">${escapeHtml(item.status || "context")}</span>
        </span>
        <strong>${escapeHtml(item.title)}</strong>
        <span class="node-summary">${relationMeta || escapeHtml(item.summary || "")}</span>
        <span class="node-footer"><span>${escapeHtml(item.lane)}</span><span>${relationIds(item).size} links</span></span>
      `;
      node.addEventListener("click", () => selectNode(item.id));
      nodeElements.set(item.id, node);
      nodesLayer.appendChild(node);
    });
  });
    rowTop += rowHeights[rowIndex] + gapRow;
  });

  if (!selectedId && visibleItems.length) {
    selectedId = defaultSelectionId();
    const selected = byId.get(selectedId);
    if (selected) renderDetail(selected);
  }

  if (selectedId && byId.has(selectedId)) {
    const item = byId.get(selectedId);
    const related = relationIds(item);
    const hasRelated = related.size > 0;
    nodeElements.forEach((node, id) => {
      node.classList.toggle("is-selected", id === selectedId);
      node.classList.toggle("is-related", related.has(id));
      node.classList.toggle("is-dim", hasRelated && id !== selectedId && !related.has(id));
    });
  }

  if (options.fit === "all") {
    fitAll();
  } else if (options.fit === "none") {
    applyTransform();
  } else {
    fitWidth();
  }
  drawEdges();
  updateStatus();
}

function scheduleLayout(options = {}) {
  if (layoutFrame) window.cancelAnimationFrame(layoutFrame);
  layoutFrame = window.requestAnimationFrame(() => {
    layoutFrame = 0;
    layoutGraph(options);
  });
}

function edgePairs() {
  if (edgeMode === "none") return [];
  const pairs = [];
  const seen = new Set();
  const visibleIds = new Set(visibleItems.map((item) => item.id));
  for (const item of visibleItems) {
    for (const relatedId of relationIds(item)) {
      if (!visibleIds.has(relatedId)) continue;
      if (edgeMode === "selected" && (!selectedId || (item.id !== selectedId && relatedId !== selectedId))) continue;
      const key = [item.id, relatedId].sort().join("::");
      if (seen.has(key)) continue;
      seen.add(key);
      const source = byId.get(item.id);
      const target = byId.get(relatedId);
      const sourceRank = laneRank.get(source?.lane || "") ?? 99;
      const targetRank = laneRank.get(target?.lane || "") ?? 99;
      const forward = sourceRank <= targetRank;
      pairs.push({ sourceId: forward ? item.id : relatedId, targetId: forward ? relatedId : item.id });
    }
  }
  return pairs;
}

function edgePath(sourceId, targetId) {
  const source = nodePositions.get(sourceId);
  const target = nodePositions.get(targetId);
  if (!source || !target) return "";
  const sourceCenter = source.x + source.width / 2;
  const targetCenter = target.x + target.width / 2;
  const direction = sourceCenter <= targetCenter ? 1 : -1;
  const sameColumn = Math.abs(sourceCenter - targetCenter) < 8;
  const startX = sameColumn ? source.x + source.width : source.x + (direction > 0 ? source.width : 0);
  const startY = source.y + source.height / 2;
  const endX = sameColumn ? target.x + target.width : target.x + (direction > 0 ? 0 : target.width);
  const endY = target.y + target.height / 2;
  const bend = sameColumn ? 44 : Math.max(42, Math.abs(endX - startX) * 0.38);
  const c1X = startX + bend * direction;
  const c2X = endX - bend * direction;
  return `M ${startX.toFixed(1)} ${startY.toFixed(1)} C ${c1X.toFixed(1)} ${startY.toFixed(1)}, ${c2X.toFixed(1)} ${endY.toFixed(1)}, ${endX.toFixed(1)} ${endY.toFixed(1)}`;
}

function drawEdges() {
  const paths = edgePairs().map((pair) => {
    const active = selectedId && (pair.sourceId === selectedId || pair.targetId === selectedId);
    const klass = active ? "edge is-active" : "edge";
    const d = edgePath(pair.sourceId, pair.targetId);
    return d ? `<path class="${klass}" d="${d}"></path>` : "";
  });
  edgeRoot.innerHTML = paths.join("");
}

function applyTransform() {
  transform.k = Math.max(0.18, Math.min(2.4, transform.k));
  world.style.transform = `translate(${transform.x}px, ${transform.y}px) scale(${transform.k})`;
  updateStatus();
}

function updateStatus() {
  if (!graphStatus) return;
  const edgeCount = edgePairs().length;
  const zoomText = activeView === "graph" ? ` | ${Math.round(transform.k * 100)}%` : "";
  graphStatus.textContent = `${visibleItems.length} nodes | ${edgeCount} edges${zoomText}`;
}

function fitWidth() {
  const viewportWidth = viewport.clientWidth || 1000;
  const nextZoom = Math.min(1.15, Math.max(0.24, (viewportWidth - 42) / graphSize.width));
  transform = {
    k: nextZoom,
    x: Math.round((viewportWidth - graphSize.width * nextZoom) / 2),
    y: 24,
  };
  applyTransform();
}

function fitAll() {
  const viewportWidth = viewport.clientWidth || 1000;
  const viewportHeight = viewport.clientHeight || 700;
  const nextZoom = Math.min(
    1.15,
    Math.max(0.12, Math.min((viewportWidth - 42) / graphSize.width, (viewportHeight - 42) / graphSize.height))
  );
  transform = {
    k: nextZoom,
    x: Math.round((viewportWidth - graphSize.width * nextZoom) / 2),
    y: Math.round((viewportHeight - graphSize.height * nextZoom) / 2),
  };
  applyTransform();
}

function resetZoom() {
  const viewportWidth = viewport.clientWidth || 1000;
  transform = {
    k: 1,
    x: Math.round((viewportWidth - graphSize.width) / 2),
    y: 24,
  };
  applyTransform();
}

function zoomAt(nextZoom, clientX, clientY) {
  const rect = viewport.getBoundingClientRect();
  const px = clientX - rect.left;
  const py = clientY - rect.top;
  const worldX = (px - transform.x) / transform.k;
  const worldY = (py - transform.y) / transform.k;
  transform.k = Math.max(0.18, Math.min(2.4, nextZoom));
  transform.x = px - worldX * transform.k;
  transform.y = py - worldY * transform.k;
  applyTransform();
}

function centerNode(id) {
  const pos = nodePositions.get(id);
  if (!pos) return;
  const viewportWidth = viewport.clientWidth || 1000;
  const viewportHeight = viewport.clientHeight || 700;
  transform.x = viewportWidth / 2 - (pos.x + pos.width / 2) * transform.k;
  transform.y = viewportHeight / 2 - (pos.y + pos.height / 2) * transform.k;
  applyTransform();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setViewMode(mode) {
  activeView = mode === "graph" ? "graph" : "tree";
  setActiveFilter("[data-view-mode]", activeView);
  treeView.classList.toggle("is-hidden", activeView !== "tree");
  viewport.classList.toggle("is-hidden", activeView !== "graph");
  if (activeView === "tree") {
    renderTree();
  } else {
    scheduleLayout({ fit: "width" });
  }
}

document.querySelectorAll("[data-view-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    setViewMode(button.dataset.viewMode || "tree");
  });
});

document.querySelectorAll("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    activeType = button.dataset.filter || "all";
    setActiveFilter("[data-filter]", activeType);
    applyFilters();
  });
});

document.querySelectorAll("[data-layer-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    activeLayer = button.dataset.layerFilter || "all";
    setActiveFilter("[data-layer-filter]", activeLayer);
    applyFilters();
  });
});

document.querySelectorAll("[data-edge-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    edgeMode = button.dataset.edgeMode || "selected";
    setActiveFilter("[data-edge-mode]", edgeMode);
    drawEdges();
    updateStatus();
  });
});

document.querySelectorAll("[data-zoom-action]").forEach((button) => {
  button.addEventListener("click", () => {
    const action = button.dataset.zoomAction;
    if (action === "in") zoomAt(transform.k * 1.22, viewport.clientWidth / 2, viewport.clientHeight / 2);
    if (action === "out") zoomAt(transform.k / 1.22, viewport.clientWidth / 2, viewport.clientHeight / 2);
    if (action === "fit-width") fitWidth();
    if (action === "fit-all") fitAll();
    if (action === "reset") resetZoom();
    drawEdges();
  });
});

search.addEventListener("input", applyFilters);
viewport.addEventListener("wheel", (event) => {
  event.preventDefault();
  const nextZoom = transform.k * Math.exp(-event.deltaY * 0.001);
  zoomAt(nextZoom, event.clientX, event.clientY);
  drawEdges();
}, { passive: false });

viewport.addEventListener("pointerdown", (event) => {
  if (event.target.closest(".graph-node")) return;
  panning = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, startX: transform.x, startY: transform.y };
  viewport.classList.add("is-panning");
  viewport.setPointerCapture(event.pointerId);
});

viewport.addEventListener("pointermove", (event) => {
  if (!panning || panning.pointerId !== event.pointerId) return;
  transform.x = panning.startX + event.clientX - panning.x;
  transform.y = panning.startY + event.clientY - panning.y;
  applyTransform();
});

function endPan(event) {
  if (!panning || panning.pointerId !== event.pointerId) return;
  panning = null;
  viewport.classList.remove("is-panning");
}

viewport.addEventListener("pointerup", endPan);
viewport.addEventListener("pointercancel", endPan);
window.addEventListener("resize", () => {
  if (activeView === "tree") {
    renderTree();
  } else {
    scheduleLayout({ fit: "width" });
  }
});

renderEmptyDetail();
setViewMode("tree");
"""


def output_path_for(plan: Path, *, output: Path | None, output_dir: Path | None) -> Path:
    if output:
        return output
    if output_dir:
        return output_dir / f"{plan.stem}.html"
    return plan.with_suffix(".html")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render markdown plan artifacts to standalone HTML.")
    parser.add_argument("plans", nargs="+", help="Markdown plan path(s) to render.")
    parser.add_argument("--output", "-o", help="Output HTML path. Only valid with one input plan.")
    parser.add_argument("--output-dir", help="Directory for generated HTML files.")
    parser.add_argument("--title", help="Override the HTML title. Only valid with one input plan.")
    parser.add_argument(
        "--view",
        choices=("artifact", "document"),
        default="artifact",
        help="Render an interactive artifact map (default) or the full markdown document.",
    )
    parser.add_argument("--stdout", action="store_true", help="Write one rendered HTML document to stdout.")
    parser.add_argument("--show-comments", action="store_true", help="Render HTML comments as escaped text.")
    parser.add_argument("--no-summary", action="store_true", help="Do not render the extracted plan summary panel.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    plans = [Path(raw).expanduser() for raw in args.plans]
    output = Path(args.output).expanduser() if args.output else None
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else None

    if args.stdout and (len(plans) != 1 or output or output_dir):
        print("--stdout requires exactly one input and no --output/--output-dir", file=sys.stderr)
        return 2
    if output and len(plans) != 1:
        print("--output is only valid with exactly one input plan", file=sys.stderr)
        return 2
    if args.title and len(plans) != 1:
        print("--title is only valid with exactly one input plan", file=sys.stderr)
        return 2

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
    elif output:
        output.parent.mkdir(parents=True, exist_ok=True)

    for plan in plans:
        if not plan.is_file():
            print(f"missing plan: {plan}", file=sys.stderr)
            return 1
        markdown = plan.read_text(encoding="utf-8")
        if args.view == "document":
            rendered = convert_plan_markdown(
                markdown,
                source_path=plan,
                title_override=args.title,
                show_comments=args.show_comments,
                include_summary=not args.no_summary,
            )
        else:
            rendered = convert_plan_artifact(markdown, source_path=plan, title_override=args.title)
        if args.stdout:
            print(rendered, end="")
            continue
        destination = output_path_for(plan, output=output, output_dir=output_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        print(f"wrote {destination}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
