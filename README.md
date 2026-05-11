# AtlasMemory Tools

Harness-neutral planning, implementation, GitHub issue projection, and local automation runtime tools.

Canonical source lives at the repository root:

- `skills/`: reusable skills for planning, implementation, review, issue projection, and runtime operation
- `agents/`: shared role documents for implementers and reviewers
- `templates/local-automation-runtime/`: reusable local issue-to-PR automation runtime
- `manifests/atlas-tools.v1.json`: inventory of supported harness adapters, skills, agents, and templates

The `.cursor/` directory is kept for compatibility as generated output. Do not edit harness copies directly; update `skills/` or `agents/`, then regenerate.

## Install

Generate harness files into a target repository:

```bash
python3 scripts/install_harness.py --harness cursor --target /path/to/project
python3 scripts/install_harness.py --harness codex --target /path/to/project
python3 scripts/install_harness.py --harness gemini --target /path/to/project
python3 scripts/install_harness.py --harness claude --target /path/to/project
```

Verify generated files have not drifted:

```bash
python3 scripts/verify_harness.py --target /path/to/project
```

Enforce the local source-of-truth relationship across registered project copies:

```bash
cp ssot-projects.example.json ssot-projects.local.json
python3 scripts/enforce_local_ssot.py --registry ssot-projects.local.json --install-hooks
python3 scripts/enforce_local_ssot.py --registry ssot-projects.local.json --repair
```

See `docs/source-of-truth.md` for the install, update, contribution, and local hook workflow.

## Verify

Run the repository-level release/copy gates before publishing or copying this toolkit:

```bash
python3 scripts/verify_repo.py
```

For a raw filesystem copy, either copy from git/tracked files only or first run the strict local-artifact gate:

```bash
python3 scripts/verify_repo.py --skip-tests --strict-copy
```

## Quick Start

1. Use `plan` with a feature idea or existing plan file.
2. Use `implement` with the approved plan.
3. Use `plan-to-issues` when approved work should be projected into GitHub issues.
4. Use `local-automation-runtime-setup`, `local-automation-runtime-operate`, and `local-automation-runtime-upgrade` for local automation runtime lifecycle work.

For full planning details, see `skills/plan/README.md`.

## Examples

- `examples/generic/`: placeholder-safe defaults for new projects
- `examples/atlasmemory/`: AtlasMemory-specific runtime examples and branch/check/project names

## Visual

![AtlasMemory Skills & Agents](./atlasmemory-cursor-skills-agents.png)
