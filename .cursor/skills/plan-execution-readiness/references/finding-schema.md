<!-- atlas-tools-generated: source=skills/plan-execution-readiness/references/finding-schema.md manifest=atlas-tools.v1 checksum=sha256:1dff467e49a30dd637ae92b5c52f6a99f4df24c132c570698e405e81ecec3316 -->
<!-- atlas-tools-generated-end -->
# Finding Schema

Use this shape for structured plan execution-readiness findings.

```markdown
### F-<number>: <short title>
- Severity: Critical | High | Medium | Low
- Section: <plan section>
- Issue: <concrete problem>
- Why it matters: <implementation or product risk>
- Evidence: <heading, plan fact, repo fact, or missing required field>
- Recommended remediation: <specific plan change>
- Requires user decision: Yes | No
- Decision options: A / B / C when needed
```

Severity guidance:

- Critical: agents will build the wrong system, corrupt authority, or bypass explicit user approval.
- High: agents will stall, invent behavior, or merge incompatible work.
- Medium: likely quality, validation, or sequencing weakness.
- Low: clarity improvement that does not change execution behavior.
