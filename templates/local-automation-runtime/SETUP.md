# Setup

1. Install GitHub CLI and authenticate:

   ```bash
   gh auth login
   gh auth refresh -s project
   gh auth status
   ```

2. Copy and edit runtime config:

   ```bash
   cp config.env.example config.env
   cp repos.example.txt repos.txt
   cp config/required-checks.example.json required-checks.json
   cp config/local-validation.example.json local-validation.json
   cp projects.example.txt projects.txt
   ```

   `repos.txt` is the repo inventory for this runtime. Multiple product repos can share one runtime; create a
   separate runtime only for separate secrets/auth, host/container isolation, or independent concurrent lanes.
   Set `ATLAS_TOOLS_ROOT` to the AtlasMemory-Tools checkout when plan projection/queueing should be available.

3. Prepare Codex auth under `codex-home/` for the worker container.

   Treat `AGENT_CODEX_HOME` as the Codex/GPT subscription boundary. Each runtime that must use a
   separate project, provider account, or subscription should keep its own runtime-local `codex-home/`
   and should be logged in separately by the operator. Do not point isolated automation at a shared
   user home such as `/home/mat/.codex`; `AGENT_CODEX_ISOLATION_REQUIRED=true` rejects that by default.

   Optional provider metadata fields in `config.env` are written to each job's non-secret
   `provider-account.json` artifact:

   ```bash
   AGENT_PROVIDER_ACCOUNT_ID=""
   AGENT_PROVIDER_ACCOUNT_LABEL="Atlas"
   AGENT_PROVIDER_SUBSCRIPTION_LABEL="GPT Pro Atlas"
   AGENT_CODEX_WORKSPACE_ID=""
   ```

   If `AGENT_CODEX_WORKSPACE_ID` is set, add the matching `forced_chatgpt_workspace_id` to
   `codex-home/config.toml`. Keep `AGENT_ALLOW_SHARED_CODEX_HOME=false` except for supervised
   emergency runs where shared billing/data coupling is intentional.

4. Build the local Codex image:

   ```bash
   ./build_codex_image.sh
   ```

5. Validate:

   ```bash
   python3 -m pip install -r requirements-dev.txt
   python3 -m playwright install chromium
   ./check_runtime.sh
   python3 -m unittest tests.test_local_agent_autonomy
   ./atlas-agent-finalize --required-checks-file required-checks.json
   ```

6. Start with dry runs, then use `--apply` only after the target repo labels/check names are configured.

The unattended loop runs `reconcile -> decompose -> workstream-review -> dependency-promote -> dispatch -> review -> semantic-review -> review -> local-validate -> review -> semantic-review -> review -> deployed-validate -> review -> semantic-review -> review -> repair -> review -> semantic-review -> review -> finalize -> summary -> cleanup`. The reconcile stage removes stale `agent:done` from open issues, marks linked open PRs as `agent:pr-open`, and requeues otherwise eligible issues. GitHub Project reconciliation is kept out of the default hot path; use `--project-reconcile-every N` for checkpoint syncs or add `project-reconcile` to `--stages` for a supervised inline repair. The decompose stage marks `points:1` issues as `agent:one-point` and keeps larger issues out of dispatch until they are split. The dependency promotion stage promotes one-point stories only after issue body and Project dependency refs resolve to closed issues or merged PRs; it is dry-run unless `--apply`, `--review-apply`, or `--dependency-promote-apply` is used. Use `local-validation.json` for repositories that do not emit GitHub PR checks; local validation may approve/readify no-check PRs, but unattended merge remains blocked until GitHub checks exist or `required-checks.json` explicitly allows a path-scoped no-checks policy.

For higher throughput, prefer explicit per-stage limits: `--dispatch-max-per-repo`, `--semantic-review-concurrency`, `--local-validate-concurrency`, `--repair-concurrency`, and `--deployed-validate-concurrency`. Deployed validation defaults to one active target because hosted validation may share mutable environments. Dispatch write-scope locks are enabled by default and use each issue's `## Write Scope` plus repo/base branch to avoid concurrent overlapping edits.

For a long operator window, prefer `atlas-agent-shift` over asking an agent chat session to supervise indefinitely:

```bash
./atlas-agent-shift --cycles 12 --max-minutes 480 --sleep-seconds 300 --publish --apply --review-apply --post-cycle-summary
```

The shift wrapper runs one unattended cycle at a time, keeps a runtime-wide supervisor lock, updates a heartbeat/status file under `jobs/`, and writes a markdown handoff on exit. Keep the cycle count and wall-clock budget explicit. If `--project-reconcile-every N` is set on `atlas-agent-shift`, the interval is counted across shift cycles.

Keep `AGENT_GITHUB_THROTTLE=true` in `config.env` for unattended runs. The shared throttle coordinates GitHub CLI calls across parallel runtime processes and records temporary backoff state under `jobs/github-api-throttle/` after GitHub rate-limit responses. Run `./atlas-agent-throttle-status` to inspect that state without making another GitHub request.

Keep `AGENT_CLEANUP_MODE=dry-run` until a preview looks right. `./atlas-agent-cleanup --measure-size --summary jobs/cleanup-preview.json` shows stale per-job worktrees, copied Codex homes, old job artifacts, logs, and imported template backups. Use `./atlas-agent-cleanup --apply --max-delete N` for bounded manual cleanup, or `atlas-agent-unattended --cleanup-mode apply ...` for live cleanup at the end of each unattended cycle.

Project reconcile checkpoints and dependency promotion `--project-mode` scans read up to `AGENT_PROJECT_ITEM_LIMIT` Project cards, default `500`. Increase it if the Project has more active cards or the logs report that the scanned item limit was reached.
Runtime stages leave Project fields untouched by default. Set `AGENT_PROJECT_STATE_UPDATES=true` only for supervised direct updates, or set `AGENT_PROJECT_STATE_UPDATE_MODE=queue` and use `./atlas-agent-project-sync status|flush` to inspect/apply queued updates later. Decomposed child issues inherit parent/plan metadata such as gates, validation scope, risk context, and priority.

For deployed/manual validation gates, copy `config/deployed-validation.example.json` to `deployed-validation.json` only after the target repo has chosen hosted/deployed validation. Configure `workflows`, `commands`, and optional `env`. Passing deployed validation applies `agent:manual-validation-approved`; the review stage will convert that into `agent:review-approved` if all other gates are clear.
Validation labels require matching current-head evidence comments: include the validation marker, `Head: <sha>`,
and passing `Result:` so review/finalize can prove the label belongs to the current PR head.

For repo-specific runtime-only env, place files under `repo-env/<OWNER__REPO>/`. Worker and validation
worktrees receive those overlays with restrictive file permissions.
