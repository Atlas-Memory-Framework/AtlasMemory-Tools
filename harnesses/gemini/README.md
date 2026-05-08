# Gemini Adapter

Installs skills to `.gemini/skills/<name>/` and shared role docs to `.gemini/agents/`.

```bash
python3 scripts/install_harness.py --harness gemini --target /path/to/project
```

Project command or extension metadata can reference these generated skill directories as local project resources.
