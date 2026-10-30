# Agent interface for the automation harness

The harness interface gives agents one entry point into registered
AtlasMemory-Tools runtimes. A shared Python service powers a JSON CLI and a local
stdio MCP server. It does not install another runtime or replace provider
authorization rules. It is external bootstrap tooling, not Atlas-native runtime
capability evidence.

## Setup

Python 3.11 or later is required. The read-only interface has no third-party
Python dependencies. Run from the canonical AtlasMemory-Tools checkout:

```bash
python3 scripts/setup_harness_interface.py
```

The default is a preview. Inspect its missing, stale, and modified-file report,
then apply the same setup with `--apply`. Setup adds the `atlasmemory_tools` MCP
server to this account's Codex configuration and updates managed generated skills
and agent definitions. Unrelated configuration and skills are preserved. Changed
files receive backups and a receipt; manually modified managed files are
conflicts rather than silently overwritten. Add `--preserve-local` to install
the interface and safe updates while retaining those files. Installation status
continues to report retained overrides as modified, not as current canonical
copies.

Register an existing runtime explicitly:

```bash
python3 scripts/setup_harness_interface.py \
  --runtime-id primary --provider github \
  --runtime-dir /absolute/path/to/existing-runtime
```

Add `--apply` to write the previewed changes. Registration does not launch work.
Use `--runtime-config` for a non-secret provider configuration when needed.
Never point this at `config.env` or an authentication file.

The registry defaults to `~/.config/atlasmemory-tools/harness.json`:

```json
{
  "version": 1,
  "runtimes": [
    {
      "id": "primary",
      "provider": "github",
      "runtime_dir": "/absolute/path/to/existing-runtime"
    }
  ],
  "installations": [
    {"target": "/absolute/path/to/account-home", "harness": "codex"}
  ]
}
```

Only registered owned runtimes are inspected. There is no recursive host scan,
credential read, configuration sourcing, child dispatch, or network access in
discovery/inspection. Source runtime templates are not installed runtimes.

## Agent use

Start a new client session after setup if its tool catalog has not refreshed.
Call `harness_discover`, then `harness_inspect` with the selected runtime id.
Use `harness_installation_status` to compare a target installation with canonical
generated sources. Read responses include observation time and evidence
boundaries; unknown or stale runtime evidence is not a completion claim.

The additional tools are:

| Tool | Effect |
| --- | --- |
| `harness_prepare` | Inert proposal with targets, effects, budgets, input bindings, and blockers |
| `harness_start` | Starts the approved bounded GitHub cycle and returns a durable run id |
| `harness_wait` | Reads compact status, optionally waiting up to 30 seconds for a cursor change |
| `harness_cancel` | Requests shutdown of the supervisor's own worker process group |

The execution options are `max_minutes` (1–30, default 10), `cycles` (1–3,
default 1), `max_per_repo` (1–2, default 1), and boolean `publish`, `apply`, and
`review_apply` (all false by default). The default cycle requests provider reads
and local artifacts. Publication and repair require their explicit effects.
The fixed lane excludes finalization, deployed validation, cleanup, and outbound
notifications, and constrains dispatch to the declared repository inventory.
Project-configured validation commands in an `apply` proposal retain their
existing review and authority requirements.

Execution requires the registered non-secret provider configuration to enable
`local_execute`, plus `draft_pr` for publication. These capabilities describe
availability; the host-approved tool call must already be authorized for the
proposal's effects. `authorization_ref` records the authorization source and is
not a grant. Preparation blocks drifting runtime code, unsafe/missing policies,
stale active evidence, and changed inputs. Review and explicitly upgrade old
runtime code before using this new execution lane; setup never upgrades runtime
hosts automatically.

The legacy GitHub runtime still resolves worker settings from its own runtime
configuration and environment. JSON model settings are not an override for that
legacy lane. The interface does not read `config.env` or credentials; preparation
binds that file's metadata for drift detection.

Runs persist privately beside the registry under `runs/`, independently of the
MCP process. Each runtime permits one active or unreconciled interface run. A
hard wall-clock budget bounds the supervisor; cancellation targets only its own
worker process group and preserves partial evidence. External effects already
performed are not rolled back. Process exit zero reports `stopped`, with accepted
task completion unverified. A missing supervisor reports `unknown` and keeps the
overlap lock until explicit reconciliation.

The same service is available without MCP. If the canonical source location is
unknown, parse only the `mcp_servers.atlasmemory_tools` table in
`~/.codex/config.toml`; its `args` identifies the server script and registry. The
CLI script is in the same directory as the server script:

```bash
python3 scripts/harness_service.py discover
python3 scripts/harness_service.py inspect primary
python3 scripts/harness_service.py installation-status --target /absolute/path/to/home
python3 scripts/harness_service.py prepare primary --max-minutes 5
python3 scripts/harness_service.py start primary --max-minutes 5 --proposal-id sha256:PROPOSAL --authorization-ref AUTHORIZATION_REFERENCE
python3 scripts/harness_service.py wait RUN_ID --timeout-seconds 30
python3 scripts/harness_service.py cancel RUN_ID
```

For another MCP-capable client, configure a local stdio server with an absolute
Python executable and arguments pointing to
`/absolute/path/to/AtlasMemory-Tools/scripts/harness_mcp.py --registry
/absolute/path/to/harness.json`. Setup writes Codex configuration only; other
clients can use the same server and registry through their own configuration.

## Rollback and diagnosis

Use `python3 scripts/setup_harness_interface.py --rollback RECEIPT` to preview
restoration, then add `--apply`. Rollback refuses to overwrite files changed
after installation. Keep the source checkout available at its registered path;
the MCP adapter imports the canonical service rather than another copied runtime.

Protocol messages use stdout; diagnostics use stderr. A successful MCP handshake
establishes tool connectivity only. Read-only fixtures and actual installed
runtime observations are separate from end-to-end work execution qualification.

See the [implementation validation report](harness-interface-validation-2026-10-29.md)
for tested behavior, installed-account receipts, and the registered legacy
runtime's unresolved readiness boundaries.
