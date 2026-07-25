# Continuous Runtime Notes

## Loop Engineering Pattern

The current practical pattern is bounded automation plus isolated workspaces plus reusable skills/connectors plus independent review. Treat "continuous" as repeated explicit cycles with budgets and stop gates, not as unrestricted background mutation.

Core pieces:

- Automation or supervisor: wakes up and chooses the next bounded action.
- Queue: local work-item JSON, GitHub issue labels, plan leaves, PR review threads, or CI failures.
- Isolation: worktrees, job checkouts, or separate runtime directories.
- Skills/plugins/connectors: reusable workflow and external context.
- Subagents/reviewers: use sparingly for parallel exploration, validation, or review.
- Evidence: exact commands, changed files, run IDs, handoff packets, logs, and validation results.

## AtlasMemory-Tools

Source repo: `/home/mat/Desktop/AtlasMemory-Workspace/AtlasMemory-Tools`

Useful surfaces:

- `templates/local-automation-runtime/atlas-agent-orchestrator --atlas-work-items`: local JSON work-item lane without GitHub issue, PR, or Project mutation.
- `templates/local-automation-runtime/atlas-agent-unattended`: bounded issue-to-PR cycles.
- `templates/local-automation-runtime/atlas-agent-shift`: longer bounded shift with lock, heartbeat, status JSON, and exit handoff.
- `templates/local-automation-runtime/config/role-commands.codex.example.json`: Codex role command map that prepares prompts and fails closed until execution is explicitly enabled.

Start new lanes in this order:

1. Verify source repo if possible.
2. Install the runtime into a separate operational directory.
3. Configure `config.env`, `repos.txt`, validation files, and runtime-local `codex-home/`.
4. Run dry-run/local fake execution.
5. Enable one real item with `--max-items 1`.
6. Only later consider PR publishing or merge/finalize flags.

## Event Analysis Engine

Source repo: `/home/mat/Desktop/Event-Analysis-Engine`

Relevant transferable ideas:

- Run manifests, claimed paths, execution packages, launch packets, handoff packets, and consolidation.
- `scripts/worker_launcher_lib.py`: launcher backends including `none`, `dry_run`, `test_stub`, `codex_session`, and `atlas_session`.
- `scripts/run_event.py --auto-spawn`: concrete auto-spawn entrypoint.
- `docs/PARALLEL_WORK_PROTOCOL.md`: file-scope ownership rules.

Do not import Event Analysis Engine UI experiments as Atlas product direction. Treat them as negative lessons or projection examples only.

## Atlas

Source repo: `/home/mat/Desktop/atlas`

Required first command before routing:

```bash
.venv/bin/python atlas/cli/atlas brief
```

Current safe loop proof shape:

```text
brief -> DB readiness -> loop1 dogfood-workpacket -> runtime evidence/read-model -> brief -> stop or repeat
```

This proves a bounded operator-invoked WorkPacket proof loop only. It does not prove a general scheduler, unattended authority, source ingestion, broad apply, external effects, or P1 readiness.

## Stop Gates

Stop the loop when any of these occur:

- Dirty or unexpected worktree state in a touched repo.
- Missing database, token, secret, container, or network prerequisite.
- Queue item lacks owner, write scope, validation command, or authority boundary.
- Validation fails or cannot be run.
- Review requests changes.
- Runtime would need broader authority than granted.
- Max cycles, max items, max minutes, token budget, or cost budget is reached.
- The next action requires a human decision.
