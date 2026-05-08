---
name: local-automation-runtime-operate
description: Operate the local automation runtime: queue issues, run bounded or unattended cycles, review/validate/repair/finalize PRs, and summarize outcomes. Use when running issue-to-PR automation after setup.
---

# Local Automation Runtime Operate

## Purpose

Run the local GitHub issue-to-PR lane with explicit bounds, review gates, validation, repair, finalization, and summaries.

## Operator Roles

- Codex operator owns runtime host, secrets, worker execution, validation, repairs, finalization, and merges.
- Gemini operator may own planning, issue quality, semantic review notes, and readiness labels.
- Only one operator may run mutating flags at a time: `--apply`, `--publish`, `--merge`, or `--close-issues`.

## Operating Flow

1. Refresh repo/project state:
   - `./atlas-agent-reconcile --repos-file repos.txt --apply`
   - `./atlas-agent-project-reconcile --projects-file projects.txt --apply`
2. Preview queue eligibility:
   - `./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --dry-run`
3. Queue approved work:
   - `./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --apply --queue`
   - Add `--publish` only when eligible queued issues should immediately open draft PRs.
4. Run a bounded cycle:
   - `./run_e2e_chain.sh --cycles 1`
   - Add mutating flags only after preview looks correct.
5. Run unattended cycles when the lane is stable:
   - `./atlas-agent-unattended --cycles 3 --max-per-repo 2 --review-apply --post-cycle-summary`
6. Review blockers:
   - `./atlas-agent-review --summary review.json`
   - `./atlas-agent-semantic-review OWNER/REPO#PR --apply`
7. Validate and repair:
   - `./atlas-agent-local-validate OWNER/REPO#PR --apply`
   - `./atlas-agent-deployed-validate OWNER/REPO#PR --apply`
   - `./atlas-agent-pr-repair OWNER/REPO#PR`
8. Finalize only when review approves:
   - `./atlas-agent-finalize --required-checks-file required-checks.json --merge --close-issues`

## Guardrails

- Keep cycles bounded with `--cycles`, `--max-per-repo`, and repair/validation max flags.
- Treat no-check PRs as blocked unless local validation and required-check policy explicitly allow them.
- Do not repair failed workflows until `atlas-agent-review --apply` has classified the failure.
- For human-action, secret/config, infra/env, or dependency-blocked workflow classes, stop worker repair and hand the issue to the responsible operator.

## Output

Summarize:

- queued issues
- PRs opened
- review labels/routes
- validation results
- repairs attempted
- merged/closed items
- remaining blockers and owner actions
