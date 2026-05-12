# Source Of Truth Workflow

AtlasMemory-Tools is the source of truth for shared skills, agents, and local automation runtime templates.
Generated harness files in application repositories are install artifacts.

## What Is Editable

Edit these files in this repository:

- `skills/**`
- `agents/**`
- `templates/local-automation-runtime/**`
- `manifests/atlas-tools.v1.json`
- `scripts/**`
- `docs/**`

Do not edit generated downstream copies as the normal workflow:

- `.codex/skills/**`
- `.codex/agents/**`
- `.cursor/skills/**`
- `.cursor/agents/**`
- `.gemini/skills/**`
- `.gemini/agents/**`
- `.claude/skills/**`
- `.claude/agents/**`

Generated skill and agent files contain an `atlas-tools-generated` header with the canonical source path,
manifest version, and source checksum. `scripts/verify_harness.py` uses that header to detect drift.

## Install Into A Project

From this repository:

```bash
python3 scripts/install_harness.py --harness codex --target /path/to/project
python3 scripts/verify_harness.py --target /path/to/project
```

Supported harnesses are listed in `manifests/atlas-tools.v1.json`.

Use `--check` to preview what would change without writing files:

```bash
python3 scripts/install_harness.py --harness codex --target /path/to/project --check
```

## Enforce Locally

Create a local registry from the example:

```bash
cp ssot-projects.example.json ssot-projects.local.json
```

Edit `ssot-projects.local.json`:

```json
{
  "projects": [
    {
      "path": "/absolute/path/to/project",
      "harnesses": ["codex"]
    }
  ]
}
```

Check all registered projects:

```bash
python3 scripts/enforce_local_ssot.py --registry ssot-projects.local.json
```

Rewrite generated downstream files from this source of truth:

```bash
python3 scripts/enforce_local_ssot.py --registry ssot-projects.local.json --repair
```

Install local pre-commit hooks into all registered downstream projects:

```bash
python3 scripts/enforce_local_ssot.py --registry ssot-projects.local.json --install-hooks
```

Install this repository's pre-commit verifier:

```bash
python3 scripts/enforce_local_ssot.py --install-canonical-hook
```

The downstream hook runs `scripts/verify_harness.py --target <project-root>` and blocks commits when generated
skills or agents drift from this repository.

The canonical hook runs `scripts/verify_repo.py` and blocks commits here when release gates fail.

## Update Downstream Projects

Pull or merge changes into this repository, then run:

```bash
python3 scripts/enforce_local_ssot.py --registry ssot-projects.local.json --repair
```

Commit the resulting generated files in each downstream project only when that project intentionally vendors
the generated harness files.

## Contribute Changes Back

When a downstream generated copy was edited by mistake:

1. Compare the generated file with its `source=` header.
2. Move the intended change into the matching file under `skills/` or `agents/` in this repository.
3. Run `python3 scripts/verify_repo.py`.
4. Commit the source change here.
5. Run `python3 scripts/enforce_local_ssot.py --registry ssot-projects.local.json --repair`.

For collaborators, use a branch or fork of this repository and open a pull request. Raw downstream edits are
treated as drift unless they are promoted into this repository.

## Local Automation Runtime Template

The runtime template under `templates/local-automation-runtime/` is also source material, but installed runtime
directories have local configuration and state. An installed runtime directory is not a target source repository;
it is the local host that stores config, auth, logs, jobs, and managed checkouts.

The installed runtime's `repos.txt` is the inventory of repositories the runtime operates on. Runtime-managed
clones live under `repos/`, using names such as `OWNER__REPO`. Preserve local-only files and directories such as
`config.env`, `repos.txt`, `repos/`, `jobs/`, `logs/`, `state/`, and `codex-home/`.

Use the runtime setup and upgrade skills for operational changes:

- `skills/local-automation-runtime-setup/SKILL.md`
- `skills/local-automation-runtime-upgrade/SKILL.md`
