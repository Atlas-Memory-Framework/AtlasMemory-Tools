---
# atlas-tools-generated: source=skills/automation-harness/SKILL.md manifest=atlas-tools.v1 checksum=sha256:10c2bf0cedb822384e6c717c354dc1a37b25dde875f9dc01e84bb1f9eba90ee2
# atlas-tools-generated-end
name: automation-harness
description: Configure named remotes and inspect or operate AtlasMemory-Tools runtimes through MCP, with local coordination and explicit cloud operations. Use when operating or troubleshooting this external automation toolkit.
---

# Automation harness

Use the `atlasmemory_tools` MCP server as the first entry point into an installed
AtlasMemory-Tools runtime:

1. Call `harness_discover` to find registered runtimes and available capabilities.
2. Call `harness_inspect` with the selected `runtime_id` to inspect current work,
   evidence freshness, blockers, and next actions.
3. Call `harness_installation_status` when skills or adapters appear out of date.

When a user supplies a new remote, pass that URL as a tool argument. Use
`harness_remote_repositories` for an Azure project URL, then present its repository
and observed branch choices. Do not infer a repository from its project name,
reuse an unrelated registration, or put the user's target in source/defaults.
`harness_configure_remote` previews a named profile; explicit `apply: true` saves
it for future chats. Default read access requires no model choice or credential
values. Worker access needs explicit models, capabilities and an isolated checkout;
cloud writes retain the existing signed grants and user authorization.

For a registered provider operation, call `harness_prepare` with its operation
and bounded options. Supported Azure operations are `azure-inspect`,
`azure-worker-preview`, `azure-worker`, `azure-publish`,
`azure-reconcile-preview`, and `azure-reconcile`. GitHub uses `github-cycle`.
Review its targets, effects, budgets, and blockers. If the requested work already
authorizes those effects and no blocker remains, call `harness_start` with the
same operation, options, proposal id, and a reference to that authorization. A reference
records a decision; it does not create consent. If a material decision is
missing, ask for that decision using the concrete proposal.

Keep the returned run id. Use `harness_wait` and its cursor for changes; use
`harness_cancel` when the user asks to stop. The supervisor survives a client
restart. An exit-zero `stopped` run still needs task validation and independent
review. Read Azure results from the sanitized `operation_result` in the returned
run. Native signed-grant verification remains the Azure adapter's authority boundary.

Keep agent messages, reservations, results, cursors and heartbeats in local
state. GitHub comments and Azure discussions are cloud presentation, not an
agent message bus. The MCP GitHub cycle explicitly selects local comment policy.
Explicit cloud-review summaries may publish material changes with deduplication;
legacy comment-based acceptance must not be silently treated as local evidence.

For a provider cycle, use an existing registration that matches the requested
project/provider. If none matches, report the concrete registration blocker.
Do not guess a runtime, create another runtime, or execute source template scripts.

The supervised local JSON-queue lane is separate from provider cycles. After
shared discovery, use this lane only when the resolved source checkout's
`AGENTS.md`, `docs/local-harness-operating-instruction.md` and
`docs/daily-development.md` direct it for the requested work, and the accountable
operator supplies an explicit selection for an existing installed runtime. No
MCP runtime registration or new provider adapter is required for that documented
lane. An unrelated GitHub registration does not select or authorize it.

Read the selected lane without changing it:

```bash
python3 -B /resolved/source/scripts/atlas_daily.py --config /absolute/operator-selection.json status
```

Preserve the selected runtime/state/owner/source pin, standalone disabled,
pending reservations and all existing task history. Missing or contradictory
selection remains a blocker; do not discover a substitute or infer an upgrade
from candidate drift. Status establishes neither installed-file integrity nor
host/account/model qualification.

For authorized local work, follow the source guide's `daily add`, `daily prepare`,
exact in-app host dispatch, `daily import` and `daily status` sequence using that
same selection. Check scope ownership, fresh task-bound sizing, the exact host
model/reasoning route and budgets before adding or preparing work. Recover any
pending handoff with its original invocation/runtime before unrelated work.
Keep authentic worker result bytes and observed host receipts; require objective
validation and independent goal acceptance. The status wrapper never dispatches
models, and this route grants no unattended, provider-write or merge authority.
Do not claim that `harness_start` ran or accepted a local JSON-queue task.

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
