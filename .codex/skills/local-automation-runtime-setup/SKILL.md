---
# atlas-tools-generated: source=skills/local-automation-runtime-setup/SKILL.md manifest=atlas-tools.v1 checksum=sha256:abe79d78fea9920751b56a8c5a8b4a7d00ed77ee945327a6bdd54ca0c115e628
# atlas-tools-generated-end
name: local-automation-runtime-setup
description: Install and validate the local automation runtime template for GitHub issue-to-PR automation. Use when setting up a runtime host, preparing config.env, checking gh/Codex/container prerequisites, or running initial smoke tests.
---

# Local Automation Runtime Setup

## Purpose

Install `templates/local-automation-runtime/` into a target runtime directory and prove the host is ready before any mutating automation runs.

## Inputs

- target runtime path
- target GitHub repo(s), written as `OWNER/REPO`
- trusted GitHub author login(s)
- Codex auth home path for worker containers
- optional GitHub Project targets (`OWNER/PROJECT_NUMBER`)

## Setup Flow

1. From the tools repo, verify the source before copying:
   - `python3 scripts/verify_repo.py`
   - For raw filesystem copies, also run `python3 scripts/verify_repo.py --skip-tests --strict-copy`, or copy from git/tracked files only.
2. Copy the template to the target runtime path. This is the installed runtime directory, not the target project repo.
3. Create local config from placeholders:
   - `cp config.env.example config.env`
   - `cp repos.example.txt repos.txt`
   - `cp projects.example.txt projects.txt`
   - `cp config/required-checks.example.json required-checks.json`
   - `cp config/local-validation.example.json local-validation.json`
   - Put target GitHub repos in `repos.txt`, one `OWNER/REPO` per line. The runtime clones them under `repos/`.
   - Do not set up one runtime per repo by default.
   - Copy `config/deployed-validation.example.json` to `deployed-validation.json` only after the target repo has chosen hosted/deployed validation.
4. Fill `config.env` with local-only values:
   - `AGENT_REPO`
   - `AGENT_TRUSTED_AUTHORS`
   - `AGENT_CODEX_HOME`
   - optional per-repo `AGENT_BASE_BRANCH_<OWNER_REPO>`
5. Validate GitHub CLI:
   - `gh auth status`
   - `gh auth refresh -s project`
   - `gh repo view OWNER/REPO --json defaultBranchRef`
6. Validate Codex/container prerequisites:
   - `./check_runtime.sh`
   - `./build_codex_image.sh`
7. Run smoke tests:
   - `python3 -m unittest discover tests`
   - `./atlas-agent-plan-queue --plan ../path/to/plan.md --repo OWNER/REPO --dry-run` when a plan exists

## Safety

- Do not commit `config.env`, `codex-home/`, `jobs/`, `logs/`, `repos/`, or `state/`.
- Keep `AGENT_TRUSTED_AUTHORS` narrow.
- Start with dry runs and avoid `--apply`, `--publish`, `--merge`, and `--close-issues` until labels, checks, and branch routing are verified.
- If multiple operators share the runtime, appoint exactly one mutating operator before setup is used for live automation.

## Output

Report:

- runtime path
- repos configured
- GitHub auth state
- Codex/container readiness
- smoke-test results
- any missing secrets, labels, project permissions, or branch metadata
