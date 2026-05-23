# Plan-To-HTML Best Practices

Use this reference when changing the renderer behavior or choosing a different conversion engine.

## Practices

- Prefer a specified Markdown dialect over ad hoc assumptions. CommonMark exists to reduce ambiguous Markdown behavior; GitHub Flavored Markdown adds common review-doc features such as tables and task list items.
- For this repo, preserve portability first. The bundled renderer intentionally supports the plan-oriented subset with no package installation. If broader Markdown fidelity becomes necessary, prefer a well-maintained parser or Pandoc and record that dependency.
- Treat markdown input as potentially untrusted. Escape raw HTML by default, avoid generated JavaScript, validate or encode URLs before putting them into attributes, and keep a restrictive Content Security Policy.
- Make review artifacts standalone. Inline local CSS and minimal local JavaScript, and avoid external fonts, remote scripts, CDNs, or image fetches so the file can be attached, archived, or opened offline.
- Use semantic document structure: one main content landmark, a navigation landmark for the table of contents, stable heading IDs, accessible link text, responsive layout, and print-friendly styles.
- Prefer artifact-map views over full-document renders when the user wants quick comprehension: typed lanes, compact nodes, search/filter controls, click-to-focus detail panels, and related-item highlighting.
- Add plan-specific affordances only as derived display: Plan State summary, Gate Results badges, decisions, risks, workstreams, phases, automation leaves, reviews, task checkboxes, code blocks, and source/generation metadata. Never let the HTML become the authoring source.
- Regression-test the risky cases: raw HTML/XSS strings, nested lists, fenced code, checkboxes, duplicate headings, table rendering, dynamic detail rendering, related-item highlighting data, and missing Plan State or Gate Results sections.

## Sources

- CommonMark: https://commonmark.org/
- GitHub Flavored Markdown Spec: https://github.github.com/gfm/
- Python-Markdown Extra and TOC extensions: https://python-markdown.github.io/extensions/extra/ and https://python-markdown.github.io/extensions/toc/
- Pandoc User's Guide, standalone and embedded-resource HTML options: https://pandoc.org/MANUAL.html
- OWASP XSS Prevention Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
