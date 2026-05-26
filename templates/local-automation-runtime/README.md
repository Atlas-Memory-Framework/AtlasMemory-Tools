# Local Automation Runtime Template

This template is the host-side local Codex automation lane for GitHub issue-to-PR automation.

It provides:

- issue queueing from `status:ready` to `agent:ready`
- local Codex worker execution in isolated per-job worktrees
- draft PR publishing
- unattended reconcile, dependency promotion, dispatch, review, local/deployed validation, repair, finalize, and merge supervision
- bounded shift supervision with a wall-clock budget, one supervisor lock, heartbeat/status files, and handoff notes
- finalizer gates for required checks, duplicate PRs, mergeability, and issue dependencies
- one-command plan projection and queueing via `atlas-agent-plan-queue`
- one end-of-cycle summary from `run_e2e_chain.sh`

## Quick Start

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m playwright install chromium
cp config.env.example config.env
cp repos.example.txt repos.txt
cp config/required-checks.example.json required-checks.json
cp config/local-validation.example.json local-validation.json
cp projects.example.txt projects.txt
./check_runtime.sh
./build_codex_image.sh
python3 -m unittest tests.test_local_agent_autonomy
```

Edit `repos.txt` with one `OWNER/REPO` target per line. The runtime clones or fetches those repos under
`AGENT_REPOS`, defaulting to `./repos`.
Set `ATLAS_TOOLS_ROOT` in `config.env` when using `atlas-agent-plan-queue`; it must point at the
AtlasMemory-Tools checkout that contains `skills/plan-to-issues/scripts/plan_to_issues.py`.

Add another target repo to `repos.txt`; create another runtime only when you need separate secrets/auth, host
isolation, or intentional concurrent lanes.

Project an approved plan into one-point manifest leaf issues and preview queue eligibility:

```bash
./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --strategy leaf-issues --dry-run
```

Apply issues and queue eligible work:

```bash
./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --strategy leaf-issues --apply --queue --publish
```

Run the bounded local lane:

```bash
./run_e2e_chain.sh --apply --review --review-apply --require-review-approval --merge --close-issues --cycles 3
```

Without the review flags, the bounded script is useful for supervised local progression but does not enforce
the same review-approval gate as the unattended finalizer path.

Run the full unattended loop:

```bash
./atlas-agent-unattended --publish --apply --merge --close-issues --review-apply --cycles 3 --dispatch-max-per-repo 2 --post-cycle-summary
```

The unattended loop first reconciles stale lifecycle labels and Project epic status, promotes dependency-gated one-point stories whose upstream issues/PRs and manual gates are complete, then dispatches issue workers, reviews local-agent PRs, runs local/deployed validation where configured, repairs PRs labeled `agent:needs-repair`, and finalizes only PRs with `agent:review-approved`.

Run a longer but still bounded shift by wrapping one-cycle unattended runs:

```bash
./atlas-agent-shift --cycles 12 --max-minutes 480 --sleep-seconds 300 --publish --apply --review-apply --post-cycle-summary
```

`atlas-agent-shift` holds one runtime-wide supervisor lock, runs `atlas-agent-unattended --cycles 1` repeatedly, updates `jobs/atlas-agent-shift-heartbeat.json`, writes a per-shift status JSON under `jobs/`, and writes a markdown handoff under `jobs/` on exit. Use it when the lane is already stable and the operator needs durable resume state across a long window. The unattended cycle performs GitHub issue reconciliation every cycle and keeps GitHub Project reconciliation out of the default hot path; use `--project-reconcile-every N` for checkpoint Project syncs. On `atlas-agent-shift`, that interval is counted across shift cycles. The shift wrapper adds wall-clock limits and restartable evidence, not broader mutation authority.

`agent:done` is reserved for resolved/closed work. A published draft PR leaves the linked issue marked `agent:pr-open` until the finalizer merges and closes it.

The default stage order is `reconcile -> decompose -> workstream-review -> dependency-promote -> dispatch -> review -> semantic-review -> review -> local-validate -> review -> semantic-review -> review -> deployed-validate -> review -> semantic-review -> review -> repair -> review -> semantic-review -> review -> finalize -> summary`. The default is local-first: GitHub Project sync is advisory and runs only when `project-reconcile` is explicitly included in `--stages` or `--project-reconcile-every N` is set. The decompose stage marks one-point issues with `agent:one-point` and prevents larger point estimates from reaching dispatch until they are split. The dependency promotion stage is dry-run by default and applies body, label, and Project field updates when `--apply`, `--review-apply`, or `--dependency-promote-apply` is used. Use `--decompose-create-subissues` when you want the planning Codex profile to create one-point child issues for oversized parents.

Parallelism is stage-specific. `--dispatch-max-per-repo` replaces the older broad `--max-per-repo` lane count while keeping `--max-per-repo` as a compatibility default. Semantic review, repair, and local validation run independent targets in parallel by default up to their `--*-max` target count; use `--semantic-review-concurrency`, `--repair-concurrency`, and `--local-validate-concurrency` to cap active processes lower than the target count. Deployed validation remains conservative with `--deployed-validate-concurrency 1` unless the configured target environments are safe to share.

Dispatch workers use runtime-global write-scope locks by default. Issues with disjoint `## Write Scope` paths can run concurrently on the same repo/base branch; overlapping paths, schema/migration siblings, and unknown or repo-wide scopes wait for a later cycle. Use `--no-write-scope-locks` only for a manually supervised run.

Automation-ready decomposition should make parallelism explicit instead of relying only on inferred locks. Leaf issues should carry dependency and scheduling metadata such as `Depends on`, `Blocks`, `Parallel group`, `Critical path rank`, `Merge group`, `Combine policy`, `Conflict class`, `Write Scope`, and `Validation tier`. Treat missing or unknown metadata as a reason to narrow dispatch, not a reason to widen it.

Keep PRs separate by default. A one-point issue should normally produce one draft PR; use an explicit integration issue or `Merge group` when several green PRs need a planned rollup. Combining unrelated implementation PRs early makes repair routing and finalization less reliable.

GitHub CLI calls are paced through a runtime-wide throttle file under `jobs/github-api-throttle/`. Keep `AGENT_GITHUB_THROTTLE=true` when running multiple lanes so Project v2 GraphQL scans, `--json` issue/PR reads, and label/comment mutations do not stampede one token. The default pacing is conservative, and `AGENT_GITHUB_RATE_LIMIT_BACKOFF_SECONDS` stops later stages from hammering GitHub after a rate-limit response. Use `./atlas-agent-throttle-status` to inspect cooldown and stale-lock state without calling GitHub.

Workstream review runs before dependency promotion in the default unattended loop. It reads items labeled
`agent:workstream-review-required`, can write feedback files/summaries, and applies
`agent:workstream-review-passed`, `agent:workstream-review-failed`, `agent:workstream-needs-human`, or
`agent:workstream-followup` according to the operator flags and review outcome.

Workstream completion requires a review bundle, not just merged PRs. Before marking a workstream done, record
semantic review status, garbage collection results, documentation changes or a docs-not-needed rationale,
validation evidence, and downstream readiness. Garbage collection includes stale followups, obsolete config,
generated junk, duplicate source-of-truth, and abandoned automation artifacts or branches when they are safe to
remove. Documentation updates are mandatory unless the closure record explains why no docs are affected.

PRs with no GitHub checks and no configured required checks are labeled `agent:local-validation-required`; `atlas-agent-local-validate --apply` runs the configured local commands and swaps that label to `agent:local-validation-passed` or `agent:local-validation-failed`. `local-validation.json` may use the legacy `repo -> [commands]` form or a structured object with `install_commands`/`setup_commands` followed by targeted `commands`. If a repository has required checks configured, local or deployed validation does not replace missing GitHub check reports.

Worker publication also has a pre-PR evidence gate. The implementation agent must leave a `Tests` or `Verification` section with exact commands and results before the worker publishes a draft PR. If tests are intentionally not run, the issue must carry an explicit validation waiver reason or controlled waiver label. Configure `pre-commit run --all-files`, targeted test commands, and build commands in `local-validation.json`; repository hooks may be disabled in worker worktrees, so important checks must be commands, not only hooks.

To reconcile more than one GitHub Project, put targets in `projects.txt` as `OWNER/NUMBER`, one per line, then run `atlas-agent-unattended --projects-file projects.txt --project-reconcile-every 3 ...` or run `atlas-agent-project-reconcile --projects-file projects.txt --apply` as a separate checkpoint. The Project board must use a `Status` field with `Todo`, `In Progress`, and `Done`. Project lifecycle scans read up to `AGENT_PROJECT_ITEM_LIMIT` cards, default `500`; raise that value if the reconcile log says the scanned item limit was reached or new cards are not moving.
Runtime stages do not update Project fields by default. Set `AGENT_PROJECT_STATE_UPDATES=true` only for supervised direct Project writes, or set `AGENT_PROJECT_STATE_UPDATE_MODE=queue` to append desired field updates under `jobs/project-sync/*.jsonl`. Use `./atlas-agent-project-sync status` offline and `./atlas-agent-project-sync flush` when you want to apply queued Project updates. Priority is inherited from the plan/parent issue during decomposition and can be backfilled by reconcile tooling.

Local validation is a fallback for repositories that do not publish PR checks. It can allow review approval and can move a draft PR to ready, but unattended merge still requires GitHub checks unless `required-checks.json` explicitly marks a path-scoped no-checks policy such as docs-only changes with a required `agent:no-checks-expected` label.
Validation labels alone are not sufficient for review approval. The review/finalizer path expects current-head
evidence comments with a recognized validation marker, `Head: <sha>`, and passing `Result:` for local,
deployed, and semantic validation gates.

Playwright is part of the shared dev dependency set so runtime validation can later add browser-backed checks without each target repo inventing its own install path.

Optional deployed/manual validation:

```bash
cp config/deployed-validation.example.json deployed-validation.json
```

Use this only after the target repo has chosen hosted/deployed validation. Configure an object with `workflows`, `commands`, and optional `env`; `atlas-agent-deployed-validate --apply` dispatches workflows, runs commands, records artifact names, applies `agent:manual-validation-approved` and `agent:deployed-validation-passed` when they pass, and removes failed/required validation labels. Review will then allow `agent:review-approved` when all other blockers are clear.

Repo-specific environment overlays live under `repo-env/<OWNER__REPO>/`. Files in that directory are copied
into worker and validation worktrees with mode `0600`; use it for local secrets or environment fragments that
must never be committed to a product repo.

Use `--post-cycle-summary` to send one Teams notification per cycle. Per-repo triage Teams posts are off by default; use `--post-triage-teams-per-repo` only for debugging.

## Safety

Do not use `--allow-no-checks` broadly. The default finalizer blocks no-check PRs unless an explicit
`required-checks.json` path policy and the `agent:no-checks-expected` label allow that PR shape.

Do not commit `config.env`, `codex-home/`, `repo-env/`, `jobs/`, `logs/`, `repos/`, or `state/`.
