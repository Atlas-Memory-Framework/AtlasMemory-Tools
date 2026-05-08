---
name: planning-reviews
description: Run required planning-phase reviews and log dispositions in the current plan artifact. Use after Implementation stage before plan approval.
---

# /planning-reviews

## Purpose
Run planning-phase review passes and update the Planning Reviews section with findings and dispositions. Do not write the plan artifact directly.

## Authority contract lens
- Markdown plan artifacts are the authoring write surface.
- Compiled registry YAML is the local planning authority after compile in `registry-first`.
- GitHub issues, PRs, and checks are the execution truth.
- GitHub Projects v2, rendered overlays, and runtime-mirror outputs are downstream or derived evidence surfaces only.
- Review packaging must preserve these boundaries; no review may treat markdown as execution-authoritative once `registry-first` is active.

## Finding severity labeling
- If a review point is optional and does not block correct implementation, prefix the finding text with `Non-blocker:` (keep schema and ids unchanged).

## User experience rule (no "go read the plan")
- Any review material the user must act on (findings + dispositions) must be included directly in the chat response (paste the findings list and the disposition items you are asking the user to confirm).
- Do not require the user to open the plan artifact to see what the reviewers wrote.

## Q/A loop (inline)
- The orchestrator runs the Q/A loop inline with the user only for findings that still require human agency after auto-remediation.

## Repo Security Reality Check (pre-security-review) (required)
Planning security reviewers are plan-only by default, so they can miss repo facts unless the plan records them. Before running the Security/Privacy review, perform a lightweight repo-anchored spot-check and write a short summary into the plan (recommended location: `## Context Snapshot`).

### Scope (keep it fast + deterministic)
- Read this allowlist of “hot” files and extract security-relevant facts:
  - `functions/triggers/internal.py` (internal endpoints auth + any logging of API keys)
  - backend JWT/auth modules (gateway-to-functions defaults and fail-closed behavior)
  - infrastructure deployment modules (deployment wiring for backend JWT requirement and signing key)
  - `infra/1 - bicep/modules/2 - gateway/apim-policies.bicep` (APIM policy fragments: backend-jwt-proof, header projection, routing/bypass)
- Optional follow-ons only if the first pass finds risk:
  - backend API key provider modules
  - `functions/shared/error_handler.py`

### Output shape (must be copy/pasteable into the plan)
Return a block like this (do not include secrets):

```md
### Repo Security Reality Check (Refreshed: YYYY-MM-DD)
- Backend JWT proof:
  - Observed default behavior:
  - Deployed env fail-closed mechanism:
  - Evidence hook (named gate):
- Internal endpoints:
  - Observed auth enforcement points:
  - Observed sensitive logging risks (if any):
  - Evidence hook (named gate):
- APIM header projection / bypass paths:
  - Observed projection/overrides:
  - Bypass risk summary:
  - Evidence hook (named gate):
```

### Evidence hooks (required)
For any trust-boundary assertion (APIM-only, private networking, “headers are trusted”, “fail-closed”), provide at least one **named gate** that makes the claim executable:
- Gate name (`G-SEC-...`)
- Where it runs (CI | Local | Deployed)
- Entrypoint/command or concrete check (not “run smoke tests”)
- Green means (explicit pass condition)

If you cannot provide an evidence hook, emit a finding with `Remediation target: Implementation` and require a Decision boundary or DR-backed Defer with trigger.

## Auto-remediation policy (coherent + enforceable)
- Findings are inputs to a remediation loop before asking the user for A/R/D.
- Tag each finding with a remediation target in the finding text: `Remediation target: <Problem | Feature | Technical | Implementation | Context Snapshot | Decision Log | Unknown>`.
- **Auto-remediation is allowed** only when the finding is purely missing clarity/structure and remediation does not change decisions (e.g., add missing outline, add missing schema description, add missing test matrix shape, clarify a step).
- **Auto-remediation is NOT allowed** when the finding touches policy/compliance/cost/trust boundaries, introduces/changes a decision boundary, or changes the stated data-handling posture. Those must be surfaced to the user for explicit A/R/D.
- If the target is `Unknown` or requires external policy/source/approval, it must be surfaced to the user.
- Deduplicate similar findings across reviews into a single remediation action.
- After remediation, present only: what changed + remaining human-agency findings.
- **Dispositions must still be recorded for every finding**:
  - **Auto-Accept OK** only for non-human-agency findings that were auto-remediated as documentation/structure improvements.
  - **Explicit user A/R/D required** for human-agency findings (policy/compliance/cost/trust boundary, decision boundary, external approval/source, or Unknown target).

## Required response format (post-remediation)
1) **Remediations applied**: 3-7 bullets summarizing what changed in the plan.
2) **Human decisions required (if any)**: list only the remaining finding ids with a 1-line explanation each.
3) **Dispositions needed**: prompt only for the remaining ids (A/R/D), not for auto-remediated items.

## Review freshness + packaging outputs
- Tie review freshness to the current validator/package outputs for the plan state being reviewed.
- If review packaging, validator evidence, or refreshed stamps no longer match the current plan state, treat the review as stale and rerun it.
- In `registry-first`, package contradictions against authority boundaries and validator outputs rather than against a markdown-only planning model.

## Finding Closure Protocol (required)
- After remediation, rewrite the original finding line while keeping the same `F-xxx` id:
  - Use `(Resolved)` prefix when remediated: `F-012: (Resolved) <original finding summary> ...`
  - Or use `Non-blocker:` when it is explicitly non-blocking and will not be remediated: `F-013: Non-blocker: <...>`
- The plan should not look “still broken” after remediation; resolved items must be visibly marked.
- In the assistant chat response, paste:
  - remediations applied
  - remaining human-agency findings (if any)
  - only ask A/R/D for those remaining

## Review schema (must be used verbatim)
Each review must be written into the plan artifact using this exact structure so that validators and follow-on agents can reliably parse it.

## Invocation note
This skill is typically invoked by `/plan` during the Reviews stage. Users can run it directly for debugging, but normal workflow is `/plan` only.

### Common rules
- Reviewers only see the current plan artifact (zero-context with respect to repo/chat).
- Findings must be broken into the required headings for the review type.
- Each discrete finding MUST have a stable id (`F-001`, `F-002`, ...).
- Dispositions MUST reference finding ids and must be exhaustive: every finding is Accept, Reject, or Defer.
- Accept requires: (1) a `DR-xxx` entry and (2) a patch to the relevant plan section(s).
- Defer requires: (1) a `DR-xxx` entry and (2) a trigger for revisit.
- Findings may be auto-remediated per policy above, but dispositions must still be recorded. Explicit user agency is required only for human-agency findings.

### Zero-context review schema
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

### Expert technical review schema
- Technical risks and integration gaps:
  - F-001: ...
- Missing validations or operational steps:
  - F-002: ...
- Contradictions with stated invariants or authority boundaries:
  - F-003: ...
- Patch suggestions (point to plan sections):
  - F-004: ...

### Implementer readiness review schema
- Top 5 gotchas:
  - F-001: ...
- Evidence needed to prevent each gotcha:
  - F-002: ...
- Pass/fail readiness statement:
  - F-003: ...

### Disposition schema (required for each review)
- Disposition:
  - Accept: F-001 -> DR-xxx
  - Reject: F-002 -> rationale
  - Defer:  F-003 -> DR-xxx + trigger

## Required reviews
- Zero-context review (doc-reviewer-zero-context)
- Implementer readiness review (doc-reviewer-implementer)
- Expert technical review if triggered (doc-reviewer-expert-tech) or mark N/A with rationale
- Security/privacy review (required)

## Sub-agent routing
- The orchestrator should spawn each review as a separate sub-agent so each pass is independent and repeatable.
- Combine all findings into the Planning Reviews section before disposition.

## Sub-agent execution (required default)
Unless the user explicitly requests otherwise, run **one sub-agent per review type**:
- Zero-context review: run a reviewer using `/review mode=zero-context`
- Implementer readiness review: run a reviewer using `/review mode=implementer-readiness`
- Expert technical review: run a reviewer using `/review mode=expert-tech` when triggered; otherwise record `N/A` with rationale
- Security/privacy review: run as a dedicated pass (security/privacy rubric below). If using a reviewer agent, treat it as expert-tech strictness but security/privacy scope.

Then merge outputs into the plan’s `## Planning Reviews` section, preserving stable `F-xxx` ids per review block and recording `Refreshed: YYYY-MM-DD` for each required review.

### Security/privacy review (required)
- Focus on auth boundaries, data handling, privacy/compliance, and sensitive data paths.
- You MUST ground findings in the latest plan state (and the Repo Security Reality Check block, if present).
- Force evidence-driven answers for:
  - Trust boundary enforcement (where enforced; how it fails closed in deployed envs)
  - Bypass paths (direct-to-backend routes; proof they’re blocked)
  - Secret logging risks (API keys, tokens, SAS URLs, auth headers)
  - Regression gates/tests that keep security assertions true (CI vs deployed)
- If the plan asserts a security posture without an evidence hook (named gate/test + where it runs + command/entrypoint + green means), emit a finding:
  - `Remediation target: Implementation`
- If the claim requires a policy/compliance/trust-boundary decision, emit a human-agency finding:
  - `Remediation target: Decision Log`
- Findings should be short and action-oriented.
- Use this schema:
  - Security/privacy risks:
    - F-001: ...
  - Missing validations or mitigations:
    - F-002: ...
  - Patch suggestions (point to sections):
    - F-003: ...

## Disposition rule
- Each finding becomes Accept / Reject / Defer, and must use the Disposition schema above.
- Accept requires a DR entry and a patch to the relevant section.
- Findings may be auto-remediated per policy above, but dispositions must still be recorded.

## Gate
PlanningReviewsComplete passes only when required reviews are done and dispositions are logged.
