---
# atlas-tools-generated: source=skills/planning-reviews/SKILL.md manifest=atlas-tools.v1 checksum=sha256:6403b9fd4e0b23cabc5597558980e3bfd63268e0e52833bdb1e1d9d6fc48b533
# atlas-tools-generated-end
name: planning-reviews
description: Run required planning-phase reviews, including human readability review, and log dispositions in the current plan artifact. Use after Implementation stage before plan approval.
---

# /planning-reviews

## Purpose
Run planning-phase review passes and update the Planning Reviews section with findings and dispositions. Reviews must judge both structure and meaning: a structurally complete plan still fails if a maintainer or zero-contact implementation agent cannot understand what is being built, why, and how to verify it. Do not write the plan artifact directly.

## Authority contract lens
- Markdown plan artifacts are the authoring write surface.
- Compiled registry YAML, when used, is a derived machine-readable package for validator inputs and projection metadata; it is not independent authoring authority.
- GitHub issues, PRs, and checks are the execution truth.
- GitHub Projects v2, rendered overlays, and runtime-mirror outputs are downstream or derived evidence surfaces only.
- Review packaging must preserve these boundaries; no review may treat markdown as execution-authoritative once `registry-first` is active.
- Authority/projection/dispatch language belongs in execution sections and appendices. If it crowds out the product/system problem or technical narrative, emit a Human Readability finding.

## Finding severity labeling
- If a review point is optional and does not block correct implementation, prefix the finding text with `Non-blocker:` (keep schema and ids unchanged).

## User experience rule (no "go read the plan")
- Any review material the user must act on (findings + dispositions) must be included directly in the chat response (paste the findings list and the disposition items you are asking the user to confirm).
- Do not require the user to open the plan artifact to see what the reviewers wrote.

## Q/A loop (inline)
- The orchestrator runs the Q/A loop inline with the user only for findings that still require human agency after auto-remediation.

## Evidence and specialist review routing (pre-review) (required)
Planning reviewers are plan-only by default, so they can miss repo facts unless the plan records them. Before running the review set, perform a lightweight repo-anchored spot-check and write a short summary into the plan (recommended location: `## Context Snapshot` -> `### Dynamic Review Roster`).

### Scope (keep it fast + deterministic)
- Read the files and components named by `## Context Snapshot`, `## Technical Plan`, and `## Implementation Plan`.
- Identify which review domains are actually in scope: security/privacy, cloud/provider infrastructure, database/migrations, data integrity/concurrency, API/contracts, external effects/governance, cost/operations, UI/operator workflow, domain expertise, and automation/runtime dispatch.
- If infrastructure, hosting, auth, data deletion, external effects, or provider trust boundaries are undecided, record that explicitly and do not require provider-specific gates.
- Optional follow-ons only if the first pass finds risk: auth providers, error handling/logging, secret loading, webhook handlers, migration/delete paths, deployment workflow files, API clients, data models, operator UI flows, and external-effect commands named by the repo.

### Output shape (must be copy/pasteable into the plan)
Return a block like this (do not include secrets):

```md
### Dynamic Review Roster (Refreshed: YYYY-MM-DD)
- Triggered specialist reviews:
  - Review: security/privacy
    - Why triggered:
    - Specialist/persona:
    - Evidence hooks (named gates or source checks):
    - Status:
  - Review: <domain>
    - Why triggered:
    - Specialist/persona:
    - Evidence hooks (named gates or source checks):
    - Status:
- Reviews considered but not triggered:
  - Review: <domain>
    - Why not triggered:
```

### Evidence hooks (required)
For any safety, trust-boundary, data-handling, migration, external-effect, or provider-specific assertion, provide at least one **named gate** or source check that makes the claim executable:
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

## Human Readability Review (required)
Run this review after `TechnicalClarity` and refresh it whenever Problem Definition, Technical Plan intro, Implementation Plan summary, or execution/authority sections materially change.

### Review questions
- Can a new engineer explain what is being built and why after reading only `Problem Definition` and `Technical Plan Intro`?
- Does the rendered HTML, or the markdown if HTML is not generated, read like a product/engineering plan instead of a validator report?
- Are automation, source-of-truth, projection, dispatch, and authority-contract details confined to execution sections/appendices unless they are the actual product/system being changed?
- Does the plan identify the strongest remaining ambiguity, or explicitly state that none remains?

### Rendered HTML check
- Prefer generating/reviewing the plan through `plan-to-html` when that skill/script is available.
- If rendered HTML is unavailable, perform the same reader review over the markdown and record that HTML rendering was not run.

Use the Human readability review schema below.

## Review freshness + packaging outputs
- Tie review freshness to the current validator/package outputs for the plan state being reviewed.
- If review packaging, validator evidence, or refreshed stamps no longer match the current plan state, treat the review as stale and rerun it.
- In `registry-first`, package contradictions against authority boundaries and validator outputs rather than against a markdown-only planning model.
- For new or refreshed reviews, record both:
  - `RefreshedAt: YYYY-MM-DDTHH:MM:SS`
  - `ReviewedPlanHash: sha256:<hash of current plan content excluding ## Planning Reviews>`
- Date-only `Refreshed: YYYY-MM-DD` is legacy context only; do not use it as the freshness proof for new reviews.

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
When used for Reviews/Approved re-entry, include this block before findings:
- Re-entry audit answers:
  - What is being built:
  - Why now:
  - Repos involved:
  - What changes first:
  - What must not happen:
  - How work is validated:
  - What remains blocked:

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

### Human readability review schema
- Product/system clarity:
  - F-001: ...
- Technical narrative clarity:
  - F-002: ...
- Execution-mechanics leakage:
  - F-003: ...
- Strongest remaining ambiguity:
  - F-004: ...
- Pass/fail readability statement: Pass | Fail

### Dynamic specialist review roster schema
- Triggered specialist review rationale:
  - F-001: ...
- Skipped specialist review rationale:
  - F-002: ...
- Missing or deferred specialist coverage:
  - F-003: ...

### Specialist review schema
- Domain risks and integration gaps:
  - F-001: ...
- Missing validations or operational steps:
  - F-002: ...
- Contradictions with stated invariants or authority boundaries:
  - F-003: ...
- Patch suggestions (point to plan sections):
  - F-004: ...

### Automation readiness review schema
- Manifest gaps:
  - F-001: ...
- Dependency/gate/file-scope risks:
  - F-002: ...
- Dispatch policy risks:
  - F-003: ...
- Pass/fail readiness statement:
  - F-004: ...

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
- Dynamic specialist review roster (required)
- Specialist reviews selected from plan content (conditional)
- Human readability review (required)
- Automation readiness review when `AutomationTarget != none`

## Sub-agent routing
- The orchestrator should spawn each review as a separate sub-agent so each pass is independent and repeatable.
- Combine all findings into the Planning Reviews section before disposition.

## Sub-agent execution (required default)
Unless the user explicitly requests otherwise, run **one sub-agent per review type**:
- Zero-context review: run a reviewer using `/review mode=zero-context`
- Implementer readiness review: run a reviewer using `/review mode=implementer-readiness`
- Expert technical review: run a reviewer using `/review mode=expert-tech` when triggered; otherwise record `N/A` with rationale
- Security/privacy review: run as a dedicated pass (security/privacy rubric below). If using a reviewer agent, treat it as expert-tech strictness but security/privacy scope.
- Dynamic specialist review roster: run a planning-review orchestrator pass that names triggered and skipped specialist reviews with rationale.
- Specialist reviews: run separate passes for triggered domains such as cloud/provider infrastructure, database/migrations, data-integrity/concurrency, API/contracts, external-effects/governance, cost/operations, UI/operator workflow, domain expertise, or automation/runtime dispatch.
- Human readability review: run `/review mode=human-readability`
- Automation readiness review: run `/review mode=automation-readiness` when `AutomationTarget != none`.

Then merge outputs into the plan’s `## Planning Reviews` section, preserving stable `F-xxx` ids per review block and recording `RefreshedAt: YYYY-MM-DDTHH:MM:SS` plus `ReviewedPlanHash: sha256:<hash>` for each required review.

### Automation readiness review (conditional)
- Focus on whether issue projection and unattended execution can be derived from explicit manifest data, not prose inference.
- Fail if workstreams/phases are the only executable projection source.
- Fail if any leaf issue uses a gate, merge point, DR, risk, assumption, or opaque phrase as a dependency.
- Fail if any gate referenced by a leaf issue lacks where/entrypoint/green means in the implementation plan.
- Fail if `agent-ready` issues lack bounded file scope, validation command/evidence, one-PR contract, or dispatch policy.
- Fail if risky areas (secrets/auth/payments/live commerce/webhooks/migrations/infra/deploy/public APIs/data deletion/compliance) are not converted into `manual-review`, `blocked`, spike-first sequencing, or a DR-backed waiver.
- Use this schema:
  - Manifest gaps:
    - F-001: ...
  - Dependency/gate/file-scope risks:
    - F-002: ...
  - Dispatch policy risks:
    - F-003: ...
  - Pass/fail readiness statement:
    - F-004: ...

### Security/privacy review (required)
- Focus on auth boundaries, data handling, privacy/compliance, and sensitive data paths.
- You MUST ground findings in the latest plan state and the Dynamic Review Roster if present.
- Force evidence-driven answers for:
  - Trust boundary enforcement (where enforced; how it fails closed in deployed envs)
  - Bypass paths (direct-to-backend routes; proof they’re blocked)
  - Secret logging risks (API keys, tokens, signed URLs, auth headers)
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
