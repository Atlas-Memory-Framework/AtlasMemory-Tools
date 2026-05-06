# Security

- Never commit `config.env`; it may contain webhook URLs and account policy.
- Never commit `codex-home/`; it contains local Codex authentication.
- Never commit generated `jobs/`, `logs/`, `repos/`, or `state/`.
- Keep `AGENT_TRUSTED_AUTHORS` narrow.
- High-risk changes are gated by labels such as `agent:allow-workflows`, `agent:allow-infra`, and `agent:allow-large`.
- The finalizer blocks no-check PRs unless `--allow-no-checks` is explicitly used.
- Rotate any webhook URL that was accidentally copied into source control or shared logs.
