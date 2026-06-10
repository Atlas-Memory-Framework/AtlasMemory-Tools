<!-- atlas-tools-generated: source=skills/local-plan-agent-runtime/references/reconciliation.md manifest=atlas-tools.v1 checksum=sha256:4362994fab2e3d0951e4df6f506462ca2a0b244520dacacfefa46914c77cf0f9 -->
<!-- atlas-tools-generated-end -->
# Reconciliation

## Disposition states

Use `Accept`, `AcceptWithEdits`, `Reject`, `Defer`, `NeedsUserDecision`, `NeedsRerun`, or `Conflict`.

## Conflict examples

Treat these as conflicts:

- two workers propose incompatible milestone order
- one worker removes scope while another depends on it
- one worker blocks projection while another marks projection ready
- one worker encodes a user decision another flags as undecided
- two patches replace the same section with incompatible intent

## Manager duties

For each finding, record:

```markdown
| Finding | Source persona | Disposition | Reason | User decision needed |
|---|---|---|---|---|
```

## Reconciliation rules

- Prefer cited evidence over confidence.
- Prefer concrete section or file references over broad prose.
- Prefer minimal patches over broad rewrites.
- Merge compatible patches only when intent is unchanged.
- Escalate intent changes to the user.
- Reject validator-only rewrites that do not improve buildability.
- Mark reviews stale after material plan changes.
- Send stale or conflicted sections to targeted rerun when needed.
