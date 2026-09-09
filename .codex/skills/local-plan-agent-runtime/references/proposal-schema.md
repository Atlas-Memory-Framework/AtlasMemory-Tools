<!-- atlas-tools-generated: source=skills/local-plan-agent-runtime/references/proposal-schema.md manifest=atlas-tools.v1 checksum=sha256:045997c46c0642ba4630614094ca3c49c5c7519810de09fdd32e0dd3a45953d0 -->
<!-- atlas-tools-generated-end -->
# Proposal Schema

Machine-checked runtime proposals must be JSON. Markdown or YAML notes may be used as raw human notes, but they are not accepted as validated worker proposals and must not be summarized as authoritative runtime output.

Required top-level fields:

```json
{
  "agent_id": "",
  "persona": "",
  "source_plan_path": "",
  "source_plan_sha256": "",
  "source_package_sha256": "",
  "scope": [""],
  "summary": "",
  "findings": [],
  "patches": [],
  "human_decisions": [],
  "blocked_items": []
}
```

`source_package_sha256` is required for package-mode snapshots and omitted for legacy single-plan snapshots. Use the value from `section-index.json`.

Finding object:

```json
{
  "id": "F-001",
  "severity": "critical",
  "section_id": "S0001-technical-plan",
  "section": "## Technical Plan",
  "concrete_issue": "",
  "why_it_matters": "",
  "evidence": [""],
  "proposed_remediation": "",
  "intent_gap_type": "lexical-gap | concept-gap | referent-gap | scope-gap | acceptance-gap | negative-constraint | hidden-assumption | plan-output-gap | none",
  "requires_user_decision": false,
  "decision_options": {"A": "", "B": "", "C": ""}
}
```

`intent_gap_type` is optional for backward compatibility. Omit it or use `none` for ordinary technical, sequencing, validation, or automation findings.

Patch object:

```json
{
  "id": "P-001",
  "finding_ids": ["F-001"],
  "target_section_id": "S0001-technical-plan",
  "target_section": "## Technical Plan",
  "target_section_sha256": "",
  "patch_type": "section-replacement",
  "rationale": "",
  "replacement_text": ""
}
```

Patch rules:

- Prefer minimal bounded section replacements.
- Do not modify status, gate, approval, projection, dispatch, review, or decision-log fields.
- Do not target `Plan State`, `Gate Results`, `Planning Reviews`, or `Decision Log` sections from worker proposals.
- In package mode, do not target sections from package documents whose `patchable` flag is `false`.
- Link every patch to one or more findings.
- Use `no-patch` when the finding should be dispositioned but not applied.
- If a finding requires a user decision, linked patches must use `no-patch`; the manager must convert the issue into a decision boundary.
- Include both section IDs and section hashes from `section-index.json`; headings alone are ambiguous when duplicated.
