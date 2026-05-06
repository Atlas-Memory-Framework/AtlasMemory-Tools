---
name: review
description: Perform planning-phase document reviews for the current plan artifact. Use when running /review with mode=zero-context, mode=expert-tech, or mode=implementer-readiness.
---

# /review

## Scope
Default scope is the current plan artifact. Review against the artifact authority contract recorded in the plan; do not invent external authority or treat markdown as execution-authoritative in `registry-first`.

## Authority contract lens
- Markdown plan artifacts are the authoring write surface.
- Compiled registry YAML is the local planning authority after compile in `registry-first`.
- GitHub issues, PRs, and checks are the execution truth.
- GitHub Projects v2, rendered overlays, and runtime-mirror outputs are derived or downstream surfaces unless the plan explicitly narrows a more specific evidence scope.

## Plan tier awareness (Lite vs Full)
Read `PlanTier` in the plan's Plan State and calibrate strictness:
- `PlanTier: Lite`: optimize for shipping speed. Focus findings on true blockers, high-risk gaps, contradictions, and missing decisions/tests/rollback. Avoid "polish-only" asks (wordsmithing, exhaustive alternatives, overly detailed breakdowns) unless they prevent correct implementation.
- `PlanTier: Full`: engineering-grade completeness. It is acceptable to call out missing detail that could cause rework, incorrectness, operational risk, or unclear parallelization/merge points.

## Finding severity labeling
- If a finding is optional and does not block correct implementation, prefix the finding text with `Non-blocker:` (keep the schema and ids unchanged).

## User experience rule (no "go read the plan")
- When pointing to a problem, include the minimum necessary excerpt in the chat response (copy the relevant line(s) or subsection) so the user can evaluate the finding without opening the plan file.
- Patch suggestions should cite the section name and quote the line(s) they refer to when practical.

## Modes and outputs
### mode=zero-context
Return findings using this exact schema (with stable ids):

- Missing context:
  - F-001: ...
- Contradictions:
  - F-002: ...
- Unclear decisions:
  - F-003: ...
- Risks and edge cases:
  - F-004: ...
- What I would screw up implementing tomorrow:
  - F-005: ...

### mode=expert-tech
- Triggered by infra/deploy, auth/identity, data contracts/versioning, concurrency/perf correctness, regulatory/compliance, or high-stakes customer impact
- Focus on technical correctness, integration risks, and operational gaps
Return findings using this exact schema (with stable ids):

- Technical risks and integration gaps:
  - F-001: ...
- Missing validations or operational steps:
  - F-002: ...
- Contradictions with stated invariants or authority boundaries:
  - F-003: ...
- Patch suggestions (point to plan sections):
  - F-004: ...

### mode=implementer-readiness
Return findings using this exact schema (with stable ids):

- Top 5 gotchas:
  - F-001: ...
- Evidence needed to prevent each gotcha:
  - F-002: ...
- Pass/fail readiness statement:
  - F-003: ...

## Output format
Return findings (and optional patch suggestions pointing to plan sections), without applying edits automatically.
Do not include dispositions (Accept/Reject/Defer); the orchestrator/user handles that.
