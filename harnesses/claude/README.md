# Claude Adapter

Installs skills to `.claude/skills/<name>/` and shared role docs to `.claude/agents/`.

```bash
python3 scripts/install_harness.py --harness claude --target /path/to/project
```

Claude Code expects each skill under `.claude/skills/<name>/SKILL.md`; supporting files are copied beside each `SKILL.md`.
