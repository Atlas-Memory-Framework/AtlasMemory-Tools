---
name: plan-to-issues
description: Sync or materialize GitHub issues and optional project tracking from the current plan artifact. Use when the user asks to create or update issues from a plan, wants a dry-run issue breakdown, or wants to project workstreams into a GitHub Project without replacing planning authority.
---

# Plan To Issues

## Purpose

Project the current plan artifact into GitHub tracking objects without replacing the markdown plan as the authoring surface or the compiled registry as planning authority where `registry-first` is active.

Use this skill for:

- creating an epic and child issues from one plan
- previewing a leaf-issue, workstream, or phase mapping before any GitHub writes
- updating existing issue bodies or labels to match the current plan
- preparing GitHub Project tracking for approved or stabilizing plans

## Hard Rules

- The markdown plan remains the authoring write surface. In `registry-first`, the compiled registry remains the local planning SSOT. Issues are a downstream execution projection.
- Operate on exactly one plan artifact per run.
- If the user referenced a plan via `@path` in the latest message, that plan wins.
- Echo the selection in chat as `AuthoringArtifact = <path>` before doing any plan-to-issues work.
- Default to dry-run. Only mutate GitHub when the user explicitly asks to apply or sync.
- Do not close or delete issues unless the user explicitly asks for pruning.
- Do not silently choose a repo or project. If unclear, ask.
- GitHub Projects v2 is execution UI/signal only. Board membership or field state must not be treated as planning input.
- If issues are added to multiple projects, distinguish the designated execution project from any advisory memberships and report that distinction back to the user.

## Inputs

Collect or infer these inputs before proceeding:

- plan path
- target GitHub repo for the issues
- optional GitHub Project name or identifier
- strategy: `workstreams`, `phases`, or `leaf-issues`
- mode: `dry-run` or `apply`

If the user wants Project tracking but has no existing Project URL, use `github-project` first to create or verify one, then pass its output as `--project-url`.

If the plan is still unstable, prefer `dry-run` and keep tracking metadata in `draft` mode.

Recommended plan metadata for stable projection:

- frontmatter `tracking.epicRepo`
- per-workstream `Issue ready: true|false`
- per-workstream `Target repo: <repo>[, <repo>...]`
- per-workstream `Blocked by: <workstream / merge point / gate refs>`
- per-workstream `Highest tier: T0..T6`
- per-workstream `Points: 1|2|3|5|8|13`
- per-workstream `Deployed closeout only: true|false`

## Projection Model

Default mapping:

- one plan -> one epic
- one Automation Issue Manifest leaf issue -> one story/task/spike (preferred when present)
- one workstream -> one story (legacy/fallback)
- one unresolved decision or bounded research item -> one spike
- named gates stay inside issue acceptance criteria unless they are standalone work

Use the plan's existing identifiers wherever possible:

- workstreams like `WS4-A`
- decisions like `DR-001`
- gates like `G-WS4-Contract`

## Execution Steps

1. Resolve the selected markdown authoring artifact.
2. Resolve lifecycle mode (`legacy-plan`, `migration-bridge`, `registry-first`).
3. Read the plan frontmatter and `## Implementation Plan`.
4. In `registry-first`, prefer compiled registry metadata for stable ids, execution repo, and routing; use markdown only as the amendment record and narrative context.
5. Decide whether the issue strategy is `leaf-issues`, `workstreams`, or `phases`. Prefer `leaf-issues` when `## Automation Issue Manifest` exists.
6. Run the parser script in dry-run first:
   - `python skills/plan-to-issues/scripts/plan_to_issues.py --plan "<path>" --repo "<owner/repo>" --strategy leaf-issues --dry-run`
   - If the user provides a GitHub Project URL, prefer `--project-url "<https://github.com/orgs/<owner>/projects/<number>>"` over manually splitting owner and number.
7. Review the preview:
   - epic title/body
   - child issue titles
   - labels
   - points
   - dependencies
   - blockers, merge points, named gates, repo-boundary hints, and deployed/manual validation requirements
8. If the user explicitly approves apply mode, run:
   - `python skills/plan-to-issues/scripts/plan_to_issues.py --plan "<path>" --repo "<owner/repo>" --apply`
9. For the local Codex automation lane, use the installed runtime, not the source template:
   - `python scripts/runtime_control.py queue --plan "<path>" --repo "<owner/repo>" --max-queue 1 --yes`
   - Set `ATLAS_RUNTIME_DIR` or pass `--runtime-dir "<runtime-path>"` before the subcommand when the target runtime is not the default Atlas runtime.
   - Do not run `templates/local-automation-runtime/atlas-agent-*` directly; those files are source material and direct execution writes `jobs/`, `repos/`, and local config into the template tree.
   - Add `--publish` only when eligible queued issues should immediately run local workers and publish draft PRs.
10. If a project is provided, add the created issues to the project using `gh` after issue creation.
11. Report the created or updated issues back to the user.

## Parser Notes

- Workstream extraction prefers bullet workstreams under `### Workstreams + merge points` when that block defines at least one workstream; otherwise it falls back to `### WS* ...` headings.
- `--strategy leaf-issues` consumes the canonical `### Automation Issue Manifest` section and projects its executable leaves instead of workstream or phase buckets. `## Automation Issue Manifest` -> `### Leaf issues` is also accepted as a compatibility alias.
- Manifest leaves should be bullets shaped as `- LEAF-001: Short executable title` with nested metadata for `Dispatch`, `Points`, `Target repo`, `Files in scope`, `Validation`, `Depends on`, `External blockers`, `Manual blockers`, and `Required gates`.
- For unattended local automation, prefer one-point manifest leaves (`Points: 1`). Larger leaves should stay tracking/manual until decomposed into one-point child issues.
- Manifest leaf issues emit automation metadata in dry-run JSON and issue bodies: `dispatch_mode`, `write_scope`, `validation_commands`, dependencies, gates, repo/base-branch routing, and dispatch guardrails.
- Generated executable issues must include runtime execution-state fields: `Open dependencies:` and `Manual gates remaining:`. These are the local automation dispatch contract; `## Dependencies` and Project fields are human/operator context.
- `Dispatch: agent-ready` with `Points` greater than `1` is not unattended-ready. Treat it as tracking/manual until decomposed, even if other metadata looks queueable.
- Leaf dependencies may be GitHub issue refs or sibling manifest leaf ids. Opaque text, merge points, gate ids, decisions, assumptions, and risks are treated as guardrails and force `tracking-only` dispatch until converted into explicit issue refs or runnable leaf ids.
- Cross-walk subsections whose titles contain `->` (for example `### WS2 -> WS3 -> WS4 Status Mapping`) are not treated as workstreams even if they match a loose `WS*` prefix.
- `WS3` plans use local `G-WS3-*` / `ws3_*` validation messaging for children and epic closeout text; generic deployed workflow parity gates are not injected onto the WS3 epic solely because the plan key matches the epic scope.
- Dry-run output includes a stability summary so you can see whether the plan is ready for issue creation or still needs draft-only tracking.

## Idempotency

- Prefer stable plan identifiers over title matching.
- If the plan includes `tracking:` metadata or per-item issue references, reuse them.
- If there is no stable mapping yet, create once and then patch the plan or a sidecar mapping on explicit user approval.

## Guardrails

- Use `gh` for GitHub mutations.
- Never write to GitHub in ask-only situations.
- Keep issue bodies concise and link back to the plan instead of copying the entire plan.
- For unstable plans, create draft-like tracking only; avoid mass rewrites of titles or issue bodies.
- If the plan and existing issues disagree on scope or ownership, stop and ask the user which source to trust.

## Supporting Files

- Tracking conventions and examples: [reference.md](reference.md)
- Human workflow notes: [README.md](README.md)
- Parser and sync script: `skills/plan-to-issues/scripts/plan_to_issues.py`
