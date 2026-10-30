# Azure MCP integration and local coordination

Status: Complete for source integration and installed agent instructions

## Authorized outcome

The user requested review of GitHub-comment communication and rate limits,
connection of the existing Azure adapter to MCP, and easy permanent remote
configuration. Local coordination is the default; remote services handle PRs,
Boards and other selected cloud operations. This is external AtlasMemory-Tools
runtime, connector, configuration, authority and validation work. It does not
prove Atlas-native runtime capability or qualify live production execution.

DR-001: The explicit implementation request authorizes the bounded source
changes and isolated tests described here without a separate planning ceremony.
Existing Azure signed-grant checks, provider capabilities, user authorization,
runtime identity rules and the distinct supervised local queue remain controlling.
No remote comment, PR, Board update, model run, credential enrollment or production
worker is authorized merely by connecting the adapter.

DR-002: Azure read-only and Board-only cloud setup require no model choice.
Worker/routing/publication configuration still requires explicit models and
existing route/authority checks. Remote PR/Boards operations are not agent IPC.

DR-003: The shared seven-tool lifecycle will accept named Azure operations,
with strict provider-specific options and fixed argument construction. Preparation
is inert. Start revalidates the exact proposal and required capabilities. Azure
inspection/publish/reconciliation retain their existing child contracts; this
does not route Azure through the GitHub cycle.

## Operating context

Initial working tree includes existing changes to
`skills/automation-harness/SKILL.md`, its generated copy, and
`docs/harness-interface.md`. Preserve them during integration.

`python3 -B scripts/atlas_daily.py status` reports unavailable/missing explicit
selection. Do not infer another installation or enqueue/dispatch daily work.
This task is recorded here as user-authorized source implementation; the daily
lane is not being qualified or claimed as the execution mechanism.

The user supplied a project URL and explicitly required targets to remain tool
inputs. Read-only discovery returned three repository choices; none was selected
or saved. Permanent target selection is an explicit configuration-tool action.
No target is encoded in source or defaults.

## Execution Status

Phase: Validation and publication
Status: complete for implementation and validation

Delegation matrix:

- Communication audit and local/comment policy: communication_audit; common GitHub transport, worker, review, unattended, policy tests and audit report.
- Azure proposal bridge and result projection: azure_mcp_adapter; scripts/harness_azure.py and tests/test_harness_azure.py.
- Persistent remote profiles and read-only configuration: remote_profiles; scripts/harness_remotes.py, tests/test_harness_remotes.py, runtime config and its tests.
- MCP/CLI/lifecycle integration, docs, generated copies, installation and integration evidence: root.

Root edits are integration tasks. Each implementation file has a single owner
until the owner releases it. Independent review follows integration.

## Gates

- Local coordination mode performs zero GitHub comment reads/writes; permitted
  PR/cloud operations remain explicit and review summaries avoid unchanged writes.
- Azure preparation creates no files, calls no provider and launches no worker.
- Real stdio MCP tests cover Azure prepare/start/wait, restart and useful sanitized
  result retrieval with isolated provider/worker fixtures.
- Azure write operations fail without the existing exact signed grants; a
  capability or approval reference is not consent.
- Profile preview is read-only; apply is persistent, reversible and idempotent,
  preserves unrelated registrations and accepts no credential values.
- Existing GitHub and supervised local workflow regressions remain passing.
- Repository verification, generated copies and independent review pass before
  reporting the implementation complete. Live Azure qualification remains distinct.

## Evidence limits

Source call sites can establish unnecessary comment traffic, not the historical
cause of an incident without its logs. Tests establish behavior within their
fixtures; actual Azure access is established only by a successful authorized read
for the selected target. No automatic execution or remote write is inferred.

## Completed gates

The repository verifier passed 1,956 tests with one skipped, including static and
generated-copy checks. Independent review reran 141 affected tests and found no
remaining actionable issue. Actual stdio canaries cover Azure lifecycle and
generic configuration; a standard SDK verified live repository discovery with
the user-entered URL. Account setup refreshed two managed instructions and
preserved 13 overrides. See [validation evidence](azure-mcp-validation-2026-10-30.md).
