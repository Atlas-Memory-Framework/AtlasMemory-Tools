# Runtime Operator Notes

This directory is an installed local automation runtime. Treat `config.env`, `repos/`,
`jobs/`, `logs/`, `codex-home/`, validation result files, and webhook/token values as
local operator state. Do not overwrite or delete them during template upgrades.

## GitHub CLI Auth

On this host, `gh` may use the desktop keyring for the GitHub token. Normal Codex
sandboxed commands cannot reliably access the keyring, D-Bus, Podman, or GitHub
network, so sandboxed `gh auth status` can report false failures such as
`token invalid` or `not logged in`.

For any GitHub CLI command that determines runtime readiness or mutates GitHub state,
run it outside the sandbox with an escalated exec command. Do not ask the operator to
re-authenticate unless an escalated `gh auth status` also fails.

Good readiness checks:

```bash
./check_runtime.sh
gh auth status
gh issue list --repo OWNER/REPO --state open --limit 10
```

Expected escalated auth state:

- Authenticated GitHub account with access to the configured runtime repos/projects
- Scopes include: `repo`, `workflow`, `project`, `read:org`

## Operating Guardrail

Use bounded runs first for newly added repositories; start with one issue/PR and verify
review, validation, and finalizer labels before unattended cycles.
