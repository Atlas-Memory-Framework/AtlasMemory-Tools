# Local Automation Runtime Template

This template is the host-side local Codex automation lane for GitHub issue-to-PR automation.

It provides:

- issue queueing from `status:ready` to `agent:ready`
- local Codex worker execution in isolated per-job worktrees
- draft PR publishing
- unattended reconcile, dispatch, review, local/deployed validation, repair, finalize, and merge supervision
- finalizer gates for required checks, duplicate PRs, mergeability, and issue dependencies
- one-command plan projection and queueing via `atlas-agent-plan-queue`
- one end-of-cycle summary from `run_e2e_chain.sh`

## Quick Start

```bash
cp config.env.example config.env
cp repos.example.txt repos.txt
cp config/required-checks.example.json required-checks.json
cp config/local-validation.example.json local-validation.json
cp projects.example.txt projects.txt
./build_codex_image.sh
python3 -m unittest tests.test_local_agent_autonomy
```

Edit `repos.txt` with one `OWNER/REPO` target per line. The runtime clones or fetches those repos under
`AGENT_REPOS`, defaulting to `./repos`.

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
./run_e2e_chain.sh --apply --merge --close-issues --cycles 3
```

Run the full unattended loop:

```bash
./atlas-agent-unattended --publish --apply --merge --close-issues --review-apply --cycles 3 --max-per-repo 2 --post-cycle-summary
```

The unattended loop first reconciles stale lifecycle labels and Project epic status, then dispatches issue workers, reviews local-agent PRs, runs local/deployed validation where configured, repairs PRs labeled `agent:needs-repair`, and finalizes only PRs with `agent:review-approved`.

`agent:done` is reserved for resolved/closed work. A published draft PR leaves the linked issue marked `agent:pr-open` until the finalizer merges and closes it.

The default stage order is `reconcile -> project-reconcile -> decompose -> dispatch -> review -> semantic-review -> local-validate -> review -> deployed-validate -> review -> repair -> review -> finalize -> summary`. The decompose stage marks one-point issues with `agent:one-point` and prevents larger point estimates from reaching dispatch until they are split. Use `--decompose-create-subissues` when you want the planning Codex profile to create one-point child issues for oversized parents.

PRs with no GitHub checks and no configured required checks are labeled `agent:local-validation-required`; `atlas-agent-local-validate --apply` runs the configured local commands and swaps that label to `agent:local-validation-passed` or `agent:local-validation-failed`. If a repository has required checks configured, local or deployed validation does not replace missing GitHub check reports.

To reconcile more than one GitHub Project, put targets in `projects.txt` as `OWNER/NUMBER`, one per line, then run `atlas-agent-unattended --projects-file projects.txt ...`. The Project board must use a `Status` field with `Todo`, `In Progress`, and `Done`.

Local validation is a fallback for repositories that do not publish PR checks. It can allow review approval and can move a draft PR to ready, but unattended merge still requires GitHub checks unless `required-checks.json` explicitly marks a path-scoped no-checks policy such as docs-only changes with a required `agent:no-checks-expected` label.

Optional deployed/manual validation:

```bash
cp config/deployed-validation.example.json deployed-validation.json
```

Use this only after the target repo has chosen hosted/deployed validation. Configure an object with `workflows`, `commands`, and optional `env`; `atlas-agent-deployed-validate --apply` dispatches workflows, runs commands, records artifact names, and applies `agent:manual-validation-approved` when they pass. Review will then allow `agent:review-approved` when all other blockers are clear.

Use `--post-cycle-summary` to send one Teams notification per cycle. Per-repo triage Teams posts are off by default; use `--post-triage-teams-per-repo` only for debugging.

## Safety

Do not use `--allow-no-checks` broadly. The default finalizer blocks no-check PRs.

Do not commit `config.env`, `codex-home/`, `jobs/`, `logs/`, `repos/`, or `state/`.
