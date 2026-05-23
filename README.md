# AtlasMemory Tools

![AtlasMemory Tools architecture](./docs/atlasmemory-tools-overview.svg)

AtlasMemory Tools is the canonical planning, issue projection, GitHub Project, and local issue-to-PR automation toolkit used by AtlasMemory-style repos.

It owns four surfaces:

- `skills/`: workflow contracts for planning, review, implementation, issue projection, runtime setup/operation/upgrade, handoffs, and HTML plan review artifacts
- `agents/`: reusable role rubrics for implementation, code review, docs review, data contracts, infra, processing, and testing
- `templates/local-automation-runtime/`: reusable local automation host for GitHub issue-to-PR execution
- `manifests/atlas-tools.v1.json`: supported harness adapters, canonical skills, agents, templates, and generated-copy inventory

The repo also carries shared `scripts/`, `docs/`, `tests/`, `examples/`, and committed generated `.cursor/` compatibility files.

## Mental Model

- This repo is the source of truth for shared instructions, scripts, Project schema helpers, and runtime templates.
- Generated harness files in downstream repos are install artifacts. Do not edit downstream `.codex/**`, `.cursor/**`, `.claude/**`, `.gemini/**`, or generated `AGENTS.md` copies as policy.
- An installed local automation runtime is operational state: local config, auth, logs, jobs, checkouts, locks, and validation artifacts.
- GitHub issues and PRs are execution truth. GitHub Projects are the portfolio/automation signal layer. Markdown plans remain the authoring surface until projection.
- Adding a target product repo usually means adding one line to a runtime `repos.txt`, not creating another runtime.

The checked-in `.cursor/` directory is retained as a generated compatibility copy. Update `skills/` or `agents/`, then regenerate and verify.

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
python3 -m pip install -r requirements-dev.txt
python3 scripts/verify_repo.py
```

For a raw filesystem copy, either copy from git/tracked files only or first run the strict local-artifact gate:

```bash
python3 scripts/verify_repo.py --skip-tests --strict-copy
```

Runtime template tests live under `templates/local-automation-runtime/tests` and are included in `scripts/verify_repo.py`.
The verifier also checks committed harness freshness, adapter CLI generation, executable bits, JSON and Python syntax, placeholder leaks, and trailing whitespace.
`--strict-copy` is intentionally noisy in a dirty local tree; runtime-local files such as `config.env`, `repos.txt`, `projects.txt`, validation JSON, `.venv/`, caches, and generated job state must be excluded from raw copies.

## Quick Start

1. Use `plan` with a feature idea or existing plan file.
2. Use `review` / planning review skills until planning gates pass.
3. Use `github-project` when the work needs the standard execution Project board.
4. Use `plan-to-issues` when approved work should become GitHub issues and Project items.
5. Use `plan-to-html` when a markdown plan should be rendered into a standalone review artifact.
6. Use `implement` for approved plan execution.
7. Use `handoff` before pausing, resuming, or moving work between agents.
8. Use `local-automation-runtime-setup`, `local-automation-runtime-operate`, and `local-automation-runtime-upgrade` for runtime lifecycle work.

For full planning details, see `skills/plan/README.md`.

## Local Automation Runtime

The runtime template now supports the full unattended loop:

```text
reconcile -> project-reconcile -> decompose -> workstream-review -> dependency-promote ->
dispatch -> review -> semantic-review -> local/deployed validation -> repair -> finalize -> summary
```

Current runtime behavior includes:

- per-stage concurrency controls such as `--dispatch-max-per-repo`, `--semantic-review-concurrency`, `--local-validate-concurrency`, `--repair-concurrency`, and `--deployed-validate-concurrency`
- repo/base/write-scope locks so disjoint one-point issues can run in parallel while overlapping scopes wait
- shared GitHub CLI throttling under `jobs/github-api-throttle/` to avoid GraphQL and secondary rate limits
- Project item scans controlled by `AGENT_PROJECT_ITEM_LIMIT`, default `500`
- direct Project `AutomationState` updates for `Queued`, `Running`, `PR Open`, `Failed`, and `Done`
- decomposition metadata inheritance so child issues retain plan key, parent epic, gates, risk, validation scope, and priority context

See `templates/local-automation-runtime/README.md` and `templates/local-automation-runtime/SETUP.md`.

## Documentation Map

- `docs/source-of-truth.md`: canonical source and generated-copy workflow
- `docs/automation-runtime-operational-layer.md`: operational model for runtime hosts and GitHub state
- `docs/github-project-template-views.md`: standard Project fields and view expectations
- `skills/plan/README.md`: human-facing `/plan` workflow
- `skills/plan-to-issues/README.md`: issue and Project projection workflow

## Examples

- `examples/generic/`: placeholder-safe runtime defaults for new projects
- `examples/atlasmemory/`: AtlasMemory-specific runtime examples with real org/project/check names
