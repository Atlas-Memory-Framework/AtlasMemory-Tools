# Codex Adapter

Installs skills to `.codex/skills/<name>/` and shared role docs to `.codex/agents/`.

```bash
python3 scripts/install_harness.py --harness codex --target /path/to/project
```

For user-global installs, pass your Codex home as `--target` and move the generated `skills/` contents into the configured skill directory if your environment uses a custom path.
