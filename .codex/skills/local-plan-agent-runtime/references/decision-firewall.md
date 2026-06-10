<!-- atlas-tools-generated: source=skills/local-plan-agent-runtime/references/decision-firewall.md manifest=atlas-tools.v1 checksum=sha256:2a42751751f80915eb4584f16e0d11d63392a2622228317f2192380c8f874db3 -->
<!-- atlas-tools-generated-end -->
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
