---
# atlas-tools-generated: source=skills/review/SKILL.md manifest=atlas-tools.v1 checksum=sha256:d75492ef13eb95e3fa29d574f11617609e92bdb2f8b4b90eb1fe41e4a92dbf37
# atlas-tools-generated-end
name: review
description: Perform planning-phase document reviews for the current plan artifact. Use when running /review with mode=zero-context, mode=expert-tech, mode=implementer-readiness, or mode=automation-readiness.
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

### mode=automation-readiness
Use when `AutomationTarget != none`. Review whether the plan can be projected into bounded issues or consumed by unattended issue-to-PR automation.

Fail the review for:
- missing `## Automation Issue Manifest`
- no explicit leaf issues separate from workstream/phase containers
- dependencies that are prose, gate ids, merge point ids, decisions, risks, or assumptions instead of resolvable leaf ids or structured blockers
- gates that are referenced by leaf issues but not defined with where/entrypoint/green means
- `agent-ready` issues without bounded file scope, validation command/evidence, one-PR contract, or dispatch mode
- risky areas without spike-first, manual-review, blocked, or DR-backed waiver policy

Return findings using this exact schema (with stable ids):

- Manifest gaps:
  - F-001: ...
- Dependency/gate/file-scope risks:
  - F-002: ...
- Dispatch policy risks:
  - F-003: ...
- Pass/fail readiness statement:
  - F-004: ...

## Output format
Return findings (and optional patch suggestions pointing to plan sections), without applying edits automatically.
Do not include dispositions (Accept/Reject/Defer); the orchestrator/user handles that.
