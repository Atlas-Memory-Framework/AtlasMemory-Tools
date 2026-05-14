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

3. Prepare Codex auth under `codex-home/` for the worker container.

4. Build the local Codex image:

   ```bash
   ./build_codex_image.sh
   ```

5. Validate:

   ```bash
   python3 -m unittest tests.test_local_agent_autonomy
   ./atlas-agent-finalize --required-checks-file required-checks.json
   ```

6. Start with dry runs, then use `--apply` only after the target repo labels/check names are configured.

The unattended loop runs `reconcile -> project-reconcile -> decompose -> dispatch -> review -> semantic-review -> local-validate -> review -> deployed-validate -> review -> repair -> review -> finalize -> summary`. The reconcile stage removes stale `agent:done` from open issues, marks linked open PRs as `agent:pr-open`, and requeues otherwise eligible issues. The project-reconcile stage demotes Project epics marked Done while child issues are still open. The decompose stage marks `points:1` issues as `agent:one-point` and keeps larger issues out of dispatch until they are split. Use `local-validation.json` for repositories that do not emit GitHub PR checks; local validation may approve/readify no-check PRs, but unattended merge remains blocked until GitHub checks exist or `required-checks.json` explicitly allows a path-scoped no-checks policy.

For deployed/manual validation gates, copy `config/deployed-validation.example.json` to `deployed-validation.json` only after the target repo has chosen hosted/deployed validation. Configure `workflows`, `commands`, and optional `env`. Passing deployed validation applies `agent:manual-validation-approved`; the review stage will convert that into `agent:review-approved` if all other gates are clear.
