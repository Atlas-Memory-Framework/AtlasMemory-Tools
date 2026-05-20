---
name: local-automation-runtime-operate
description: "Operate the local automation runtime: queue issues, run bounded or unattended cycles, review/validate/repair/finalize PRs, and summarize outcomes. Use when running issue-to-PR automation after setup."
---

# Local Automation Runtime Operate

## Purpose

Run the local GitHub issue-to-PR lane with explicit bounds, review gates, validation, repair, finalization, and summaries.
Use `repos.txt` to add target repos; use another runtime only for isolation, secrets separation, or intentional concurrent lanes.
Run these commands from an installed runtime directory. Do not operate from `templates/local-automation-runtime/`
inside the tools repository; that path is source material and direct execution will create runtime state in the
template tree.

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
3. Audit manual/dependency-gated items before queue approval:
   - Use `project-queue-audit` for items with `Manual`, `review-before-dispatch`, dependency, or blocker state.
   - Do not approve dispatch if issue body runtime fields and Project fields disagree.
4. Queue approved work:
   - `./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --apply --queue`
   - Add `--publish` only when eligible queued issues should immediately open draft PRs.
5. Run a bounded cycle:
   - `./run_e2e_chain.sh --cycles 1`
   - Add mutating flags only after preview looks correct.
6. Run unattended cycles when the lane is stable:
   - `./atlas-agent-unattended --cycles 3 --max-per-repo 2 --review-apply --post-cycle-summary`
7. Review blockers:
   - `./atlas-agent-review --summary review.json`
   - `./atlas-agent-semantic-review OWNER/REPO#PR --apply`
8. Validate and repair:
   - `./atlas-agent-local-validate OWNER/REPO#PR --apply`
   - `./atlas-agent-deployed-validate OWNER/REPO#PR --apply`
   - `./atlas-agent-pr-repair OWNER/REPO#PR`
9. Finalize only when review approves:
   - `./atlas-agent-finalize --required-checks-file required-checks.json --merge --close-issues`

## Guardrails

- Keep cycles bounded with `--cycles`, `--max-per-repo`, and repair/validation max flags.
- Treat `Open dependencies:` and `Manual gates remaining:` as the runtime dispatch contract; Project fields are advisory unless they match the issue body.
- Keep unattended dispatch one-point only. Larger `points:N` issues must be decomposed or explicitly handled outside unattended dispatch.
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
