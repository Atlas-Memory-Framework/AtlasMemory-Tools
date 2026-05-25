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
