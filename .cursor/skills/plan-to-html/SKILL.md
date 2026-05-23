---
# atlas-tools-generated: source=skills/plan-to-html/SKILL.md manifest=atlas-tools.v1 checksum=sha256:15a7f0ff4e7cf00e63759a959a1a03b2a0f9bfadf08224fc5f9e2fae3bd99ffc
# atlas-tools-generated-end
name: plan-to-html
description: Convert markdown planning artifacts into simple interactive HTML artifact maps and optional full-document renders. Use when Codex needs to turn /plan output, implementation plans, automation manifests, or other markdown plans into a visual review artifact with clickable/highlightable context without replacing the markdown authoring source.
---

# Plan To HTML

## Purpose

Render one or more markdown plan artifacts into standalone HTML files for easier human review. The default output is a simplified interactive artifact map: lanes for overview, gates, decisions, risks, workstreams, phases, automation leaves, and reviews; clicking an item highlights related items and opens source context in a detail panel. Treat the HTML as a derived read model only; the markdown plan remains the authoring surface and planning authority.

## Hard Rules

- Do not mutate the source markdown plan.
- Operate on explicitly selected plan paths. If multiple possible plans exist and the user did not identify one, ask for the path.
- Keep generated HTML standalone: inline CSS/JS, no external fonts, no remote scripts, and no required network access.
- Escape raw HTML from the markdown by default. Dynamic behavior must only operate on generated artifact data, not execute source-plan content.
- Use the renderer script instead of rewriting conversion logic in chat.
- If exact GitHub-flavored Markdown fidelity matters more than safe offline review, say so and document the parser dependency or external converter used.

## Quick Start

Render the default interactive artifact map next to the markdown file:

```bash
python skills/plan-to-html/scripts/plan_to_html.py path/to/plan.md
```

Render an artifact map to a specific file:

```bash
python skills/plan-to-html/scripts/plan_to_html.py path/to/plan.md --output artifacts/plan.html
```

Render the full markdown document view instead of the artifact map:

```bash
python skills/plan-to-html/scripts/plan_to_html.py path/to/plan.md --view document --output artifacts/plan-document.html
```

Render several plans into one output directory:

```bash
python skills/plan-to-html/scripts/plan_to_html.py plans/a.md plans/b.md --output-dir artifacts/plans-html
```

## Workflow

1. Resolve the markdown plan path from the user request.
2. Run `skills/plan-to-html/scripts/plan_to_html.py` in the default artifact view.
3. Open the generated HTML and verify that the lanes and detail-panel context make the plan scannable.
4. If the artifact will be shared outside the repo, prefer a clean output directory such as `artifacts/plans-html/` or another user-specified location.
5. Use `--view document` only when the reviewer needs a full markdown render.
6. If the generated page looks structurally wrong, inspect the source markdown for unusual identifiers, headings, nested fenced blocks, or table syntax, then patch the renderer only if the behavior is general to plan artifacts.

## Renderer Notes

- The script uses only Python standard library modules so installed harness copies can run without dependency installation.
- The built-in artifact parser extracts `## Plan State`, `## Gate Results`, `### DR-*` decisions, `R*`/`A*` risks and assumptions, `WS*` workstreams, `Phase *` headings, `G-*` gates, automation leaf issues, and planning review headings.
- The full-document renderer targets the markdown subset used by plan artifacts: headings, nested lists, task checkboxes, fenced code blocks, pipe tables, links, inline code, emphasis, plan key/value lines, and HTML comments.
- In document view, `## Plan State` and `## Gate Results` are extracted into a top summary while also remaining visible in the rendered document body.
- Raw HTML is displayed as text and owner comments are hidden unless `--show-comments` is passed in document view.
- The artifact output includes semantic landmarks, search/filter controls, clickable nodes, related-item highlighting, source context details, responsive layout, and a restrictive Content Security Policy.
- Artifact-map relationships should prefer explicit plan structure such as `Parent`, `Depends on`, `Required gates`, workstream `Gates`, and shared IDs before falling back to token co-occurrence. Keep the default map compact and grouped around execution/workstream clusters so reviewers can understand dependency order without scanning a sparse canvas.

## Validation

Use the root test suite or run the focused tests after changing the renderer:

```bash
python -m unittest tests.test_plan_to_html
python scripts/verify_repo.py --skip-tests
```

## Supporting Files

- Renderer script: `skills/plan-to-html/scripts/plan_to_html.py`
- Best-practices research notes: [references/best-practices.md](references/best-practices.md)
