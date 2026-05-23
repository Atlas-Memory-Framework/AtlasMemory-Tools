# Security

- Never commit `config.env`; it may contain webhook URLs and account policy.
- Never commit `codex-home/`; it contains local Codex authentication.
- Never commit `repo-env/`; it contains local repo-specific environment overlays.
- Never commit generated `jobs/`, `logs/`, `repos/`, or `state/`.
- Keep `AGENT_TRUSTED_AUTHORS` narrow.
- High-risk changes are gated by labels such as `agent:allow-workflows`, `agent:allow-infra`, and `agent:allow-large`.
- The finalizer blocks no-check PRs unless `--allow-no-checks` is explicitly used, or `required-checks.json`
  defines a path-scoped no-checks policy and the PR carries the required `agent:no-checks-expected` label.
- Rotate any webhook URL that was accidentally copied into source control or shared logs.
