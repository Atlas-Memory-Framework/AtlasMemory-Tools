# Execution Readiness Checklist

## Intent alignment

Check that `## Intent Model` names the latent target, anti-targets, expression-state gaps, open loops, and intent checksum before problem framing.

For `PlanTier: Full` or `AutomationTarget: unattended-prs`, fail readiness when the section is missing, placeholder-only, or has open loops blocking Problem, Technical, Implementation, or Automation.

Ask what wrong-but-plausible implementation could pass the written tasks or tests. If the answer is not represented in anti-targets, constraints, success criteria, or gates, flag the plan.

## Product spine

Check that the plan names the current broken workflow, desired workflow, why the gap matters now, scope, anti-scope, and measurable success criteria.

Fail readiness when product intent is replaced by planning machinery or when the Problem Definition flattens the latent target from `## Intent Model`.

## Milestone separation

Check whether the plan separates:

- Core behavior from UI behavior
- CLI/API proof from frontend proof
- Local-first MVP from cloud or managed-service expansion
- Product-critical path from optional polish

Flag any canary or acceptance test that depends on a later layer.

## Bootstrap and reproducibility

Require explicit answers for fresh setup, clean reset, seed fixture, migration/replay, idempotent second start, and local verification entrypoint.

## Contract hardening

Check for versioned API/DTO contracts, backend/UI compatibility tests, generated or pinned fixtures, schema migration ownership, and deprecation expectations.

## Integrity and concurrency

Check duplicate submission behavior, idempotency keys, optimistic concurrency or locking policy, append-only sequence monotonicity, retry semantics, dead-letter states, and partial rollback behavior.

## Evidence and trust

Check required evidence types per trusted state transition, reject or warn behavior for insufficient evidence, redaction rules, citation/source rules, audit/export proof, and machine-enforced policy.

## Failure-mode testing

Require gates for provider timeout, tool failure, malformed tool output, store unavailable, partial run failure, retrieval miss, policy denial, and export failure.

## Observability

Check logs or metrics around depth and budget violations, policy denies, evidence denials, provider or tool failures, retry exhaustion, export failures, and cross-repo contract drift.

## Agent-buildability

A plan is not ready if future agents must infer product intent, acceptance criteria are prose-only, dependencies contradict milestone order, file ownership is ambiguous, required gates are unnamed, human decisions are hidden inside implementation tasks, or an unresolved intent open loop blocks execution.
