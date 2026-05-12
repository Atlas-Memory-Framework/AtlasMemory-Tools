# Automation Runtime Operational Layer

This note defines the next AtlasMemory issue-to-PR automation layer. `AtlasMemory-Tools` remains the canonical source for skills, agents, scripts, and runtime templates. Installed runtime directories and downstream harnesses are generated or local state.

## Current Inventory

- Canonical tooling source: `/var/home/mat/Desktop/AtlasMemory-Tools`.
- Local runtime host: `/home/mat/distrobox-homes/atlas-agent/agent-runtime`.
- Runtime-managed repo checkouts: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/repos/*`.
- Disposable job checkouts: `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/checkouts/*`.
- Legacy/manual copy candidate: `/var/home/mat/Desktop/foil boat/atlas-memory`.

The runtime template already includes these operational scripts:

- `atlas-agent-plan-queue`: project an approved plan into GitHub issues, queue eligible work, and optionally run a chain.
- `atlas-agent-orchestrator`: promote `status:ready` issues to `agent:ready`, dispatch Codex workers, publish draft PRs, and triage blocked issues.
- `atlas-agent-worker`: run Codex in an isolated per-job checkout, enforce file/diff limits, commit, push, and open draft PRs.
- `atlas-agent-unattended`: run bounded cycles across reconcile, dispatch, review, validation, repair, finalize, and summary stages.
- `atlas-agent-review`: classify PRs into approval, repair, local validation, deployed/manual validation, semantic review, overlap, or human action.
- `atlas-agent-local-validate`: run configured local validation commands for no-check PRs and write current-head evidence.
- `atlas-agent-deployed-validate`: run configured deployed/manual validation commands and collect workflow artifacts.
- `atlas-agent-semantic-review`: run semantic review and label current-head review state.
- `atlas-agent-pr-repair`: repair an existing PR branch with Codex using checks, failed logs, review comments, and semantic review evidence.
- `atlas-agent-finalize`: leave draft, merge, and close linked issues only after configured gates pass.
- `atlas-agent-workflow`: dispatch, watch, inspect, and download GitHub Actions runs and artifacts.
- `atlas-agent-project-reconcile`: reconcile GitHub Project status with open child work.

## Execution State

Use GitHub as the canonical execution state:

- GitHub Projects v2: portfolio and project UI. The runtime reconciles project status but does not treat local files as the canonical board.
- GitHub issues: executable work items, plan projection targets, and linked PR closure records.
- GitHub labels: queue, type, status, risk, lane, and review state.
- GitHub PRs: implementation evidence, CI state, review discussion, repair target, and finalization unit.

The local runtime owns ephemeral execution state only: logs, job directories, lockfiles, local checkouts, Codex auth, and local validation artifacts.

## Issue And Label Model

Recommended label families:

- Type: `type:epic`, `type:story`, `type:spike`, `type:tracker`.
- Status: `status:draft`, `status:planned`, `status:ready`, `status:blocked`, `status:done`.
- Priority: `priority:p0`, `priority:p1`, `priority:p2`, `priority:p3`.
- Lane: `lane:runtime`, `lane:product`, `lane:infra`, `lane:docs`, `lane:test`.
- Workstream or area: keep existing `workstream:*`, `area:*`, `repo:*`, and `tier:*` labels from plan-to-issues.
- Agent queue: `agent:ready`, `agent:running`, `agent:pr-open`, `agent:failed`, `agent:done`.
- Agent policy: `agent:approved-dispatch`, `agent:allow-workflows`, `agent:allow-infra`, `agent:allow-large`.
- Review and repair: `agent:review-approved`, `agent:needs-repair`, `agent:superseded`, `agent:overlap-queued`, `agent:human-action-required`.
- Validation: `agent:local-validation-required`, `agent:local-validation-passed`, `agent:local-validation-failed`, `agent:manual-validation-required`, `agent:manual-validation-approved`, `agent:deployed-validation-passed`, `agent:deployed-validation-failed`, `agent:semantic-review-required`, `agent:semantic-review-passed`, `agent:semantic-review-failed`.

State transition:

1. Approved plan projects issues as `status:planned` or `status:ready`.
2. `atlas-agent-plan-queue` or `atlas-agent-orchestrator --auto-queue-label status:ready` promotes eligible work to `agent:ready`.
3. Worker claims work with `agent:running`.
4. Published draft PR moves the linked issue to `agent:pr-open`.
5. Review classifies the PR as `agent:review-approved`, `agent:needs-repair`, validation-required, semantic-review-required, overlap-queued, superseded, or human-action-required.
6. Repair loops convert repairable failures back into review.
7. Finalization leaves draft, merges, and closes the linked issue; then `agent:done` is reserved for resolved work.

## Runtime Topology

Start with one local runtime host and bounded parallelism. This is the most controllable model because the current worker reuses one checkout per repo and the runbook already warns not to run multiple workers against the same repo checkout.

Recommended first continuous lane:

```bash
./atlas-agent-unattended --publish --review-apply --apply --cycles 1 --max-per-repo 1 --require-review-approval --post-cycle-summary
```

Use manual bounded cycles first. Then wrap the same command in tmux or a systemd user service after the lane is stable. Scale to a VM/container host only after repo locks, crash recovery, and per-repo concurrency limits are proven locally.

Supervisor requirements:

- Logs under `logs/` per stage, repo, cycle, and lane.
- Job state under `jobs/` and disposable checkouts under `jobs/checkouts/`.
- PID or lock state under `state/`.
- Maximum concurrency as `--max-per-repo` and a global cycle schedule.
- Crash recovery by reconciling stale labels and stale lockfiles before dispatch.
- Pause and kill controls through `pause_github_agentic.sh`, process supervision, and explicit label gates.

## Secrets And Config

Local `config.env` should contain local runtime settings only:

- Agent labels and policy label names.
- Runtime paths.
- Codex image, Codex home, timeout, Podman command.
- Trusted GitHub authors and local commit identity.
- Notification webhook URLs if local notifications are used.

GitHub Actions secrets and vars should contain CI, deployment, cloud, and environment secrets. Repo-level secrets are for repo-specific build/deploy credentials. Org-level secrets are for shared credentials with consistent access policy. The runtime should not copy CI secrets locally; it should use GitHub permissions to push branches, open PRs, inspect checks, rerun failed checks, post comments, and dispatch workflows.

Browserbase secrets belong outside source control:

- `BROWSERBASE_API_KEY`.
- `BROWSERBASE_PROJECT_ID`.
- App base URL.
- Test-user credentials.

## Browserbase And UI Testing

Browserbase is not required for the first single-runtime lane. The existing `local-validation.json`, `deployed-validation.json`, GitHub Actions checks, and artifact collection are enough for backend, docs, schema, and non-browser app gates.

Add Browserbase when Admin UI or Chainlit validation needs real remote browser evidence. The minimal design is:

- Store Browserbase credentials in GitHub Actions secrets for CI and in local `config.env` only if local remote-browser validation is explicitly enabled.
- Add repo-specific UI commands to `local-validation.json` for local preview validation.
- Add CI workflows that upload screenshots, videos, traces, and test reports as GitHub Actions artifacts.
- Use seeded test users and a documented seed/reset command per app.
- Have `atlas-agent-workflow` and `atlas-agent-deployed-validate` collect artifact names and links as PR evidence.

## Review Gates

Finalization requires:

- Local deterministic tests pass when configured.
- GitHub required checks pass.
- Semantic review passes when requested.
- Current-head validation evidence exists for local/deployed/manual validation labels.
- No unresolved requested changes.
- No duplicate active PR for the same issue or overlapping approved PRs.
- Human approval for high-risk changes: workflows, infra, auth/secrets, data deletion/migration, large diffs, or ambiguous product behavior.

Repair loop limits:

- Use `--repair-max` and `--repair-cooldown-hours`.
- Repair only same-repo local-agent PR branches with concrete evidence: failing checks, failed workflow logs, review comments, or semantic review findings.
- Escalate to `agent:human-action-required` for secrets/config failures, non-reproducible environment failures, missing permissions, unsafe scope expansion, or repeated repair failure.

## Duplicate Repo Recommendations

- Keep `/var/home/mat/Desktop/AtlasMemory-Tools` as the canonical tooling source.
- Keep `/home/mat/distrobox-homes/atlas-agent/agent-runtime` as local runtime host, not a Git repo.
- Keep `/home/mat/distrobox-homes/atlas-agent/agent-runtime/repos/*` as active runtime-managed checkouts.
- Treat `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/checkouts/*` as disposable job worktrees/checkouts.
- Treat `/var/home/mat/Desktop/foil boat/atlas-memory` as a legacy/manual copy until its dirty work is reviewed and either promoted through PRs or archived.
- Do not delete duplicate repos until remotes, branches, dirty state, and active worktrees have been reviewed by a human.

## Phase Plan

Phase 1: normalize harness across Atlas repos.
Register active runtime repos in `ssot-projects.local.json`, repair generated harness copies from the canonical tools repo, and install downstream drift hooks.

Phase 2: repo duplicate audit.
Inventory remotes, branches, HEADs, dirty state, active worktrees, and disposable checkouts. Recommend archive, promote, or ignore without deleting anything.

Phase 3: single-runtime continuous lane.
Run bounded manual unattended cycles with `--max-per-repo 1`, collect logs and summaries, then move the same command into tmux or a systemd user service.

Phase 4: project/epic/issue schema.
Finalize label taxonomy, Project v2 fields, epic tracking conventions, and plan-to-issues projection rules. Keep GitHub as canonical state.

Phase 5: Browserbase/UI test integration.
Add Browserbase only for UI workflows that need remote browser evidence. Start with CI artifacts and repo-specific validation commands before adding local remote-browser runs.

Phase 6: multi-worker scaling.
Increase concurrency only after per-repo locks, stale lock cleanup, repair limits, and queue fairness are stable. Prefer one worker lane per repo before multiple workers per repo.
