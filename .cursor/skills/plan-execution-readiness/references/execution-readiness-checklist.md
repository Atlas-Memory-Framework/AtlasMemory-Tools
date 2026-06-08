<!-- atlas-tools-generated: source=skills/plan-execution-readiness/references/execution-readiness-checklist.md manifest=atlas-tools.v1 checksum=sha256:d2859bd4a9ab0ad5c7e40535126ba3864de68b09126c3e672b4edfac44b947aa -->
<!-- atlas-tools-generated-end -->
# Execution Readiness Checklist

## Product spine

Check that the plan names the current broken workflow, desired workflow, why the gap matters now, scope, anti-scope, and measurable success criteria.

Fail readiness when product intent is replaced by planning machinery.

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

A plan is not ready if future agents must infer product intent, acceptance criteria are prose-only, dependencies contradict milestone order, file ownership is ambiguous, required gates are unnamed, or human decisions are hidden inside implementation tasks.
