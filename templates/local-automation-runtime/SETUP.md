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

The unattended loop runs `reconcile -> project-reconcile -> decompose -> project-reconcile -> workstream-review -> dependency-promote -> dispatch -> review -> semantic-review -> review -> local-validate -> review -> semantic-review -> review -> deployed-validate -> review -> semantic-review -> review -> repair -> review -> semantic-review -> review -> finalize -> project-reconcile -> summary`. The reconcile stage removes stale `agent:done` from open issues, marks linked open PRs as `agent:pr-open`, and requeues otherwise eligible issues. The project-reconcile stage demotes Project epics marked Done while child issues are still open. The decompose stage marks `points:1` issues as `agent:one-point` and keeps larger issues out of dispatch until they are split. The dependency promotion stage promotes one-point stories only after issue body and Project dependency refs resolve to closed issues or merged PRs; it is dry-run unless `--apply`, `--review-apply`, or `--dependency-promote-apply` is used. Use `local-validation.json` for repositories that do not emit GitHub PR checks; local validation may approve/readify no-check PRs, but unattended merge remains blocked until GitHub checks exist or `required-checks.json` explicitly allows a path-scoped no-checks policy.

For higher throughput, prefer explicit per-stage limits: `--dispatch-max-per-repo`, `--semantic-review-concurrency`, `--local-validate-concurrency`, `--repair-concurrency`, and `--deployed-validate-concurrency`. Deployed validation defaults to one active target because hosted validation may share mutable environments. Dispatch write-scope locks are enabled by default and use each issue's `## Write Scope` plus repo/base branch to avoid concurrent overlapping edits.

Keep `AGENT_GITHUB_THROTTLE=true` in `config.env` for unattended runs. The shared throttle coordinates GitHub CLI calls across parallel runtime processes and records temporary backoff state under `jobs/github-api-throttle/` after GitHub rate-limit responses.

Project reconcile and dependency promotion scan up to `AGENT_PROJECT_ITEM_LIMIT` Project cards, default `500`. Increase it if the Project has more active cards or the logs report that the scanned item limit was reached.
Runtime stages update Project `AutomationState` directly for queued, running, PR open, failed, and done items
when Project metadata is available. Decomposed child issues inherit parent/plan metadata such as gates,
validation scope, risk context, and priority.

For deployed/manual validation gates, copy `config/deployed-validation.example.json` to `deployed-validation.json` only after the target repo has chosen hosted/deployed validation. Configure `workflows`, `commands`, and optional `env`. Passing deployed validation applies `agent:manual-validation-approved`; the review stage will convert that into `agent:review-approved` if all other gates are clear.
Validation labels require matching current-head evidence comments: include the validation marker, `Head: <sha>`,
and passing `Result:` so review/finalize can prove the label belongs to the current PR head.

For repo-specific runtime-only env, place files under `repo-env/<OWNER__REPO>/`. Worker and validation
worktrees receive those overlays with restrictive file permissions.
