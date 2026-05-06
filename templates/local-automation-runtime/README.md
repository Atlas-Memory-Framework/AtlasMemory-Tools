# Local Automation Runtime Template

This template is the host-side local Codex automation lane for AtlasMemory-style projects.

It provides:

- issue queueing from `status:ready` to `agent:ready`
- local Codex worker execution in isolated per-job worktrees
- draft PR publishing
- finalizer gates for required checks, duplicate PRs, mergeability, and issue dependencies
- one-command plan projection and queueing via `atlas-agent-plan-queue`
- one end-of-cycle summary from `run_e2e_chain.sh`

## Quick Start

```bash
cp config.env.example config.env
cp repos.example.txt repos.txt
cp config/required-checks.example.json required-checks.json
./build_codex_image.sh
python3 -m unittest tests.test_local_agent_autonomy
```

Project an approved plan into issues and preview queue eligibility:

```bash
./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --dry-run
```

Apply issues and queue eligible work:

```bash
./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --apply --queue --publish
```

Run the bounded local lane:

```bash
./run_e2e_chain.sh --apply --merge --close-issues --cycles 3
```

Use `--post-cycle-summary` to send one Teams notification per cycle. Per-repo triage Teams posts are off by default; use `--post-triage-teams-per-repo` only for debugging.

## Safety

Do not use `--allow-no-checks` broadly. The default finalizer blocks no-check PRs.

Do not commit `config.env`, `codex-home/`, `jobs/`, `logs/`, `repos/`, or `state/`.
