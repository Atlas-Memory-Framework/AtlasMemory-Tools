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

The account installation persists across chats and reboots. Codex starts the
registered stdio MCP server when it connects; no always-running service or login
task is installed. The registration points directly to this source checkout,
so keep it at the registered path. After moving the checkout or updating the
canonical skills, rerun the same setup command, review its preview, then apply
it with `--preserve-local` if local overrides should remain. Start a new client
session after a source update to load the new server code. Another account,
machine, or MCP client needs its own registration.

The supervised daily-development lane uses its separate explicit selection in
`.atlas-dev.local.json` and its pinned runtime. Follow
[daily development](daily-development.md) for that lane; this MCP registration
does not select it, upgrade its runtime, or grant its execution authority.
After shared discovery, an operator may select an existing supervised installation
explicitly with the read-only daily status wrapper when the repository operating
instructions direct that lane:

```bash
python3 -B scripts/atlas_daily.py --config /absolute/operator-selection.json status
```

No MCP runtime registration or new provider adapter is required for the local JSON
queue. Its maintained `daily add`, `prepare`, host dispatch, `import` and `status`
sequence retains separate ownership, sizing, route, budget and independent-review
gates. Missing or contradictory local selection remains a blocker. The
provider-cycle registration requirement below applies to provider cycles;
`harness_start` does not execute the supervised local lane.

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
| `harness_remote_repositories` | Lists repository and branch choices for an entered Azure project URL |
| `harness_configure_remote` | Previews or explicitly saves a named, non-secret remote configuration |

The GitHub cycle options are `max_minutes` (1–30, default 10), `cycles` (1–3,
default 1), `max_per_repo` (1–2, default 1), and boolean `publish`, `apply`, and
`review_apply` (all false by default). The default cycle requests provider reads
and local artifacts. Publication and repair require their explicit effects.
The fixed lane excludes finalization, deployed validation, cleanup, and outbound
notifications, and constrains dispatch to the declared repository inventory.
Project-configured validation commands in an `apply` proposal retain their
existing review and authority requirements.

Agent coordination stays in local queues, handoffs, results and run records.
The MCP GitHub cycle selects `--remote-comments local`: no worker issue-comment
messages, comment polling or comment writes. Explicit PR/cloud operations remain
available. Direct legacy CLI operations keep their compatibility default;
`cloud-review` deliberately permits PR-facing review summaries and skips unchanged
publications. A suppressed comment is not successful publication or accepted
validation evidence. See the [communication audit](remote-communication-audit-2026-10-30.md).

## Named Azure remotes

Every target is supplied by the caller. There is no default organization,
project, repository or base branch. For an Azure project URL, first call:

```json
{"project_url": "https://dev.azure.com/ORG/PROJECT"}
```

Pass that to `harness_remote_repositories`. It uses existing current-account
Azure CLI access to return choices and observed default branches. It does not
log in, save a profile, or choose a repository. The configured Azure adapter
never uses GitHub as a fallback.

Preview the chosen remote with `harness_configure_remote`:

```json
{
  "remote_id": "chosen-name",
  "provider": "azure-devops",
  "repository_url": "https://dev.azure.com/ORG/PROJECT",
  "repository_name": "REPOSITORY_FROM_DISCOVERY",
  "base_branch": "BRANCH_FROM_DISCOVERY",
  "apply": false
}
```

Repeat the reviewed request with `apply: true` to save it. A project-only request
returns `needs_selection` and creates no files even if apply was requested. Remote
profiles are private non-secret configuration under
`~/.config/atlasmemory-tools/remotes/`; named registrations live in the shared
registry. If no existing runtime is supplied, setup installs finite adapter code
under `~/.local/share/atlasmemory-tools/remotes/NAME/runtime`. It never copies
credentials or overwrites another runtime's jobs, configuration or worktrees.
Private receipts support guarded rollback through `scripts/harness_remotes.py`.

Read-only and Board-only profiles need no model configuration. Worker, routing
and publication capabilities require reviewed model settings; all privileged
effects retain their existing native authority checks. A profile grants no
consent. Azure worker operations also require their exact existing isolated
checkout and task packet.

To change a saved profile, preview the new same-target settings, retain the
returned `current_profile_sha256`, and repeat the reviewed request with that
value in `expected_profile_sha256` and `apply: true`. The update backs up the old
profile and refuses a stale hash. Omitted optional settings retain their saved
values. A different organization/project/repository needs a different named
profile. `checkout` selects an already existing isolated worktree under that
runtime's `worktrees/`; configuration never creates or clones it implicitly.

Use the shared lifecycle with an explicit Azure operation:

```json
{
  "runtime_id": "chosen-name",
  "operation": "azure-inspect",
  "options": {"ids": [123], "live_read": true, "max_minutes": 5}
}
```

`harness_prepare` binds the exact configuration, code and input evidence without
provider calls. `harness_start` repeats the operation/options and proposal id,
then uses the existing Azure CLI adapter. `harness_wait` exposes a bounded,
sanitized `operation_result`, including separate Boards and repository coverage;
raw logs, credentials and unknown backend fields are not returned. Process exit
does not establish task acceptance.

Other named operations are `azure-worker-preview`, `azure-worker`,
`azure-publish`, `azure-reconcile-preview` and `azure-reconcile`. Worker and
reconciliation options name the exact local JSON packet and, for effects, signed
authorization inputs. The maintained adapter verifies the signatures and fresh
native state before model execution, draft publication or Board updates. Missing
grants, capabilities, models, scope or evidence remain concrete blockers.

## Existing runtime boundaries

The GitHub cycle requires the registered non-secret provider configuration to enable
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
