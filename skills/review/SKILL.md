---
name: review
description: Perform planning-phase document reviews for the current plan artifact. Use when running /review with mode=zero-context, mode=expert-tech, mode=implementer-readiness, mode=human-readability, or mode=automation-readiness.
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

## Human meaning standard
- A plan can be structurally complete and still fail review if it does not explain the real product/system problem, why the work exists now, or how future implementers can verify the result.
- Product/problem and technical narrative sections should not read like validator output. Authority, projection, dispatch, and source-of-truth mechanics should be confined to execution sections/appendices unless those mechanics are the actual system being changed.
- Treat "future agents can ask the user" as false. Flag any implementation-critical ambiguity that would require user interaction later.

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

When the plan being updated is already at `CurrentStage: Reviews` or any approved/complete status, treat this pass as a re-entry audit. Do not trust existing pass claims. Add a compact `Re-entry audit answers` block before findings and answer each item from the plan text:

- What is being built:
- Why now:
- Repos involved:
- What changes first:
- What must not happen:
- How work is validated:
- What remains blocked:

If any answer is missing, generic, contradictory, or only describes planning machinery, emit a finding that points to the section that must be patched before pass/approval state can be preserved.

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

### mode=human-readability
Review whether a maintainer can understand the real work without knowing the planning framework. Prefer reviewing rendered HTML if available; otherwise review the markdown directly and say HTML was not run.

Fail the review for:
- first Problem Definition paragraphs that describe creating/updating a plan rather than a real product/system failure or opportunity
- missing current broken workflow, desired workflow, why-now, or concrete current-state facts
- Technical Plan intro that jumps straight to execution/projection mechanics without explaining what changes and why
- authority-contract, registry, projection, dispatch, or issue-manifest language leaking into product/problem narrative sections
- vague implementation intent that would make a zero-contact build agent ask what the user wanted

Return findings using this exact schema (with stable ids):

- Product/system clarity:
  - F-001: ...
- Technical narrative clarity:
  - F-002: ...
- Execution-mechanics leakage:
  - F-003: ...
- Strongest remaining ambiguity:
  - F-004: ...
- Pass/fail readability statement:
  - F-005: ...

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
