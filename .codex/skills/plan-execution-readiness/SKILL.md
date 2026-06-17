---
# atlas-tools-generated: source=skills/plan-execution-readiness/SKILL.md manifest=atlas-tools.v1 checksum=sha256:4bcc31283aebf529609e62f90a5dc8880a845ed5e466547395a6466b93c00701
# atlas-tools-generated-end
name: plan-execution-readiness
description: Critically review markdown planning artifacts as plans, not handoff documents. Use when the user asks whether a plan is ready, what is missing or silently ignored, whether agents will build the intended system, or wants a zero-context execution-readiness review before approval, projection, dispatch, or implementation.
---

# Plan Execution Readiness

## Purpose

Review a markdown plan artifact as the source of truth for intended work. Identify contradictions, missing decisions, weak validation, hidden coupling, scope drift, false readiness claims, and places where future agents would invent behavior.

This skill is read-only by default. It does not patch plans, flip gates, create issues, approve projection, approve dispatch, or produce implementation handoff notes.

## Relationship to `$plan`

Use this skill to produce findings and recommended remediations.

Use `$plan` to apply accepted changes to the selected authoring artifact, update decision logs, run validators, and change plan state.

If the user asks to modify the plan, route findings into `$plan`; do not directly edit the plan under this skill.

## Reference files

Load only the needed reference:

- `references/execution-readiness-checklist.md`: use for the core review checklist.
- `references/finding-schema.md`: use when structured findings or runtime proposal packets are requested.

## Workflow

1. Identify the selected markdown plan artifact.
2. Treat existing approval, readiness, or gate-pass claims as untrusted until verified from plan content.
3. Read the plan for product intent first: intent model, problem, desired workflow, scope, anti-scope, success criteria.
4. Review technical and implementation sections for buildability: sequencing, dependencies, file ownership, contracts, gates, rollback, and verification.
5. Review automation sections only as downstream execution mechanics, not as a substitute for product clarity.
6. Identify silent assumptions and places where implementation agents would have to guess.
7. Separate findings into direct contradictions, missing decisions, underspecified implementation behavior, validation gaps, scope creep, and stale or false readiness claims.
8. Recommend concrete `$plan` remediations by section.
9. Mark user-agency items explicitly when a decision must come from the user.

## Review posture

Be skeptical and concrete. Prefer actionable findings over broad critique.

Ask:

- Will agents build the intended product from this?
- What would they build incorrectly?
- What decision has been hidden inside prose?
- What required behavior lacks executable validation?
- What milestone or dependency order is wrong?
- What scope has drifted beyond the MVP?
- What readiness claim is unsupported?
- Does `## Intent Model` preserve the user's latent target before problem framing?
- Does the technical plan over-literalize, genericize, or flatten the user's idea?
- What plausible wrong implementation would pass the written tasks or tests?

## Required review dimensions

Always check:

- Intent alignment: latent target, anti-targets, expression-state gaps, open loops, and intent checksum.
- Product spine: current workflow, desired workflow, why now, success criteria.
- Milestone separation: core/API/CLI versus UI, local-first versus cloud, MVP versus later expansion.
- Sequencing: canaries, dependencies, merge points, and blocked work.
- Contract boundaries: API/DTO/schema versioning, cross-repo compatibility, generated fixtures.
- Reproducibility: bootstrap, reset, seed, migration/replay, idempotent restart.
- Integrity: concurrency, idempotency, retries, dead-letter behavior, rollback semantics.
- Evidence and trust: required evidence types, deny/warn behavior, redaction, auditability.
- Validation: named gates, commands or concrete evidence, local/CI/deployed location.
- Automation readiness: projection/dispatch policy, dependency graph, one-PR contract, human approval.
- Human readability: whether a new engineer can explain what is being built and why.

## Intent alignment checks

Fail readiness when:

- `## Intent Model` is missing for `PlanTier: Full` or `AutomationTarget: unattended-prs`.
- The Problem Definition contradicts, genericizes, or omits the latent target.
- Anti-targets are absent from constraints, scope, invariants, acceptance criteria, or tests where they matter.
- Expression-state gaps remain open and block Problem, Technical, Implementation, or Automation.
- Success criteria measure only task completion rather than the latent target.
- A zero-context implementer could build a wrong-but-plausible version that passes the written gates.

## Output expectations

Return findings first, ordered by severity.

Use this shape:

```markdown
## Findings

### F-001: <short title>
- Severity: Critical | High | Medium | Low
- Section: <plan section>
- Issue: <concrete problem>
- Why it matters: <implementation or product risk>
- Evidence: <quoted heading, plan fact, or missing required field>
- Recommended `$plan` remediation: <specific section change>
- Requires user decision: Yes | No
- Decision options if needed: A / B / C
- Intent gap type: lexical-gap | concept-gap | referent-gap | scope-gap | acceptance-gap | negative-constraint | hidden-assumption | plan-output-gap | none

## Recommended `$plan` patches

- `<Section>`: <bounded remediation summary>

## Rejected or deferred concerns

- <concern>: <why not applicable or why deferred>

## Remaining user decisions

- <decision>: A/B/C options, with recommended default if defensible
```

## Hard boundaries

Do not edit files, create new plan artifacts, generate handoff documents, mark gates passed, approve projection, approve dispatch, mutate GitHub issues/projects/PRs/queues, or let review findings silently rewrite product intent.

When intent is ambiguous, create a decision boundary instead of inventing the answer.
