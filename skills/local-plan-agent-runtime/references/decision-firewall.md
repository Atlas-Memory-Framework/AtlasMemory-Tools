# Decision Firewall

The manager must ask the user before accepting changes involving trust boundary, privacy or retention policy, security posture, local-vs-cloud boundary, deletion or migration policy, user-facing behavior, cost-bearing infrastructure, issue projection approval, autonomous dispatch approval, MVP scope expansion, or fallback behavior for denied or missing evidence.

## Required decision format

Use A/B/C options.

```markdown
Decision needed: <topic>

A. <option>
B. <option>
C. <option>

Recommended: <option> because <reason>.
```

## Firewall rule

If a worker proposal embeds a human-agency decision as implementation text, do not apply it. Convert it into a Decision Log candidate and ask the user.
