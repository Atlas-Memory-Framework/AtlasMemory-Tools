<!-- atlas-tools-generated: source=skills/local-plan-agent-runtime/references/personas.md manifest=atlas-tools.v1 checksum=sha256:706bb87580294e5b0adea2ed6fd23b834bf6b2ada57a803ff5b8098154f4d9a6 -->
<!-- atlas-tools-generated-end -->
# Personas

## critical-plan-reviewer

Stress-test the plan for false confidence, missing assumptions, overfitting, hidden scope, prompt-injection risk, and validator gaming.

## product-spine-reviewer

Check whether the problem, desired workflow, success criteria, and implementation slices still describe one coherent product.

## intent-reconciliation-reviewer

Check whether the plan preserves the user's latent target, anti-targets, expression-state gaps, open-loop ledger, and intent checksum. Identify wrong-but-plausible interpretations that could pass written tasks while missing the user's intended outcome.

## architecture-sequencing-reviewer

Find ordering errors, circular dependencies, wrong milestone boundaries, and canaries blocked by later layers.

## cli-ui-layering-reviewer

Check that CLI/core/API proof is separated from UI proof and that UI depends on stable backend contracts.

## contract-api-boundary-reviewer

Review DTOs, API versions, generated fixtures, cross-repo compatibility, and deprecation expectations.

## data-integrity-concurrency-reviewer

Review idempotency, duplicate submissions, append-only ordering, retry semantics, dead-letter states, rollback, and race behavior.

## evidence-trust-policy-reviewer

Review evidence sufficiency, trusted transitions, redaction, citation requirements, audit/export proof, and deny/warn behavior.

## automation-readiness-reviewer

Review automation manifest safety, issue projection readiness, dispatch blockers, file-scope conflicts, and one-PR contracts.

## human-readability-reviewer

Check whether a new engineer can explain what is being built, why now, what changes first, and what remains blocked.

## security-privacy-reviewer

Review authentication boundaries, authorization behavior, secrets handling, sensitive data flows, privacy/compliance implications, redaction, logging, and regression gates that keep security assertions true.

## cloud-provider-infra-reviewer

Review hosting, IAM, networking, deployment, environment configuration, provider-specific bypass paths, managed-service assumptions, and deployed validation gates. Use only when cloud/provider infrastructure is actually in scope.

## database-migration-reviewer

Review schema migrations, data backfills, rollback/restore behavior, transactional boundaries, compatibility windows, idempotency, and cutover/fallback plans.

## external-effects-governance-reviewer

Review commands or workflows that can affect real systems: deployments, payments, customer messages, issue tracker writes, production jobs, data deletion, and self-modification. Check approval, outbox/effect-result records, compensation, auditability, and blast-radius controls.

## cost-ops-reviewer

Review cost-bearing infrastructure, operational burden, monitoring, alerts, quotas, rate limits, runbooks, ownership, and ongoing maintenance expectations.

## ux-operator-workflow-reviewer

Review whether the plan improves the operator workflow, routes the right decisions to humans, avoids dashboard noise, and keeps UI/TUI work dependent on stable backend contracts.

## domain-expert-reviewer

Review domain-specific correctness, terminology, acceptance evidence, fixtures, and risks for the plan's stated domain. The orchestrator must name the domain and provide the domain-specific scope.
