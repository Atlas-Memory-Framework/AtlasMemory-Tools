# Proposal Schema

Machine-checked runtime proposals must be JSON. Markdown or YAML notes may be used as raw human notes, but they are not accepted as validated worker proposals and must not be summarized as authoritative runtime output.

Required top-level fields:

```json
{
  "agent_id": "",
  "persona": "",
  "source_plan_path": "",
  "source_plan_sha256": "",
  "scope": [""],
  "summary": "",
  "findings": [],
  "patches": [],
  "human_decisions": [],
  "blocked_items": []
}
```

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
  "requires_user_decision": false,
  "decision_options": {"A": "", "B": "", "C": ""}
}
```

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
- Link every patch to one or more findings.
- Use `no-patch` when the finding should be dispositioned but not applied.
- If a finding requires a user decision, linked patches must use `no-patch`; the manager must convert the issue into a decision boundary.
- Include both section IDs and section hashes from `section-index.json`; headings alone are ambiguous when duplicated.
