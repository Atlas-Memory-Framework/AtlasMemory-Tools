---
name: local-automation-runtime-upgrade
description: Upgrade an installed local automation runtime from the template while preserving local secrets, state, repos, jobs, and operator configuration. Use when refreshing scripts/config examples or migrating runtime behavior.
---

# Local Automation Runtime Upgrade

## Purpose

Compare an installed runtime with `templates/local-automation-runtime/`, update template-managed files, preserve local-only state, and validate the upgraded runtime.

## Preserve

Never overwrite without an explicit backup:

- `config.env`
- `codex-home/`
- `jobs/`
- `logs/`
- `repos/`
- `state/`
- local validation result files
- local secrets or webhook URLs

## Upgrade Flow

1. Record current state:
   - `git status --short` in any checked-out repos
   - current `config.env` keys, without printing secrets
   - current runtime script checksum summary
2. From the tools repo, run `python3 scripts/verify_repo.py` before copying template-managed files.
3. Compare template-managed files against `templates/local-automation-runtime/`.
4. Copy updated scripts, docs, tests, and example configs.
5. Keep local configs, but diff examples:
   - `config.env.example`
   - `repos.example.txt`
   - `projects.example.txt`
   - `config/*.example.json`
6. Migrate new config keys into `config.env` with placeholder values.
7. Rebuild or refresh runtime image when container files changed:
   - `./build_codex_image.sh`
8. Run validation:
   - `python3 -m unittest discover tests`
   - `./check_runtime.sh`
   - a dry-run plan queue or one bounded non-mutating cycle

## Safety

- Do not run mutating automation during an upgrade.
- Do not delete runtime state unless the operator explicitly asks.
- If a generated harness copy is installed alongside the runtime, run `python3 scripts/verify_harness.py --target <project>` after the upgrade.
- Before raw-copying the tools repo itself, run `python3 scripts/verify_repo.py --skip-tests --strict-copy` or copy from git/tracked files only.

## Output

Report:

- files updated
- config keys added or changed
- files intentionally preserved
- tests/smokes run
- required follow-up actions before mutating operation resumes
