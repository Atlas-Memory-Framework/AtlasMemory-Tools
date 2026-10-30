---
# atlas-tools-generated: source=skills/automation-harness/SKILL.md manifest=atlas-tools.v1 checksum=sha256:706fa0cbcb9afe2b7de448296ca2b2ce20f45bd8828cee9f2a8a8226bcd2d14f
# atlas-tools-generated-end
name: automation-harness
description: Find and inspect registered AtlasMemory-Tools automation runtimes, explain blockers and next actions, and check installed harness consistency. Use when operating or troubleshooting this external automation toolkit.
---

# Automation harness

Use the `atlasmemory_tools` MCP server as the first entry point into an installed
AtlasMemory-Tools runtime:

1. Call `harness_discover` to find registered runtimes and available capabilities.
2. Call `harness_inspect` with the selected `runtime_id` to inspect current work,
   evidence freshness, blockers, and next actions.
3. Call `harness_installation_status` when skills or adapters appear out of date.

For execution, call `harness_prepare` with the requested bounded cycle options.
Review its targets, effects, budgets, and blockers. If the requested work already
authorizes those effects and no blocker remains, call `harness_start` with the
same options, proposal id, and a reference to that authorization. A reference
records a decision; it does not create consent. If a material decision is
missing, ask for that decision using the concrete proposal.

Keep the returned run id. Use `harness_wait` and its cursor for changes; use
`harness_cancel` when the user asks to stop. The supervisor survives a client
restart. An exit-zero `stopped` run still needs task validation and independent
review. The named execution lane supports GitHub; Azure retains its existing
explicit provider contracts.

Use an existing registration that matches the requested project/provider. If
none matches, report the concrete registration blocker; do not guess a runtime,
create another runtime, or execute source template scripts.

Inspection and discovery are read-only. A capability is not authorization to
execute work. Preserve existing task authorization and provider-specific gates;
ask only for a missing material decision. Treat stale or missing evidence as
unknown, and distinguish process completion from validated task completion.

If MCP is unavailable in the current session, find the canonical source from
the `mcp_servers.atlasmemory_tools` table in `~/.codex/config.toml`: its `args`
contains the absolute `harness_mcp.py` path and `--registry` path. Read only that
table and do not print unrelated settings. The shared `harness_service.py` CLI
is beside `harness_mcp.py`; pass the configured registry explicitly:

```bash
python3 /resolved/source/scripts/harness_service.py --registry /resolved/registry.json discover
python3 /resolved/source/scripts/harness_service.py --registry /resolved/registry.json inspect RUNTIME_ID
```

Do not repeat inspection when the same stale-evidence blocker is unchanged;
follow its diagnostic action and preserve the old record until reconciliation
has new evidence and authorization.

The resolved source checkout's `docs/harness-interface.md` describes registry
setup, reversible installation, and client configuration. Keep AtlasMemory-Tools
runtime results separate from Atlas-native implementation evidence.
