# Harness interface validation — 2026-10-29

Result: implemented, installed for the current account, and verified within the
stated boundaries. This is external AtlasMemory-Tools bootstrap/runtime
interface evidence, not Atlas-native implementation evidence or qualification
for unattended production work.

## Delivered

- Shared JSON CLI and dependency-free local stdio MCP server.
- Seven tools: discover, inspect, installation status, prepare, start, wait, cancel.
- Explicit non-secret registration, source fingerprints, bounded evidence reads,
  timestamps, concrete diagnostics, and durable run-id recovery.
- Reversible account setup with private backups and preservation of local edits.
- Inert proposals binding targets, effects, budgets, runtime code, inventory,
  policies, non-secret configuration and secret configuration metadata.
- Detached bounded supervision, overlap locks, client reconnection, cancellation,
  timeout, bounded private output, and asynchronous child reaping.
- Explicit quiet-worker and execution-target controls in the canonical runtime.
- Same-identity `/home` alias and canonical-home validation on Bazzite.

## Verification

`python3 scripts/verify_repo.py` passed:

| Gate | Result |
| --- | --- |
| Repository unittest suite | 227 passed |
| Selected pytest suites | 307 passed |
| Runtime unittest suite | 866 cases, one skipped |
| Total | 1,399 passed, one skipped |
| Generated Codex adapter | Current and verified |
| Codex, Claude and Gemini generated adapter CLI fixtures | Passed |
| Static/release/whitespace gates | Passed |

Independent final integration review found no further actionable findings;
61 current service/MCP tests and 76 subtests passed independently. Earlier review
findings were fixed with regressions: unsafe update recommendations, conflicting
status precedence, unchanged-blocker inspection loops, hidden worker
notifications, execution repository escapes, incomplete code bindings,
unpropagated observation blockers, and supervisor reaping.

MCP Python SDK 2.3.0 initialized the actual account-configured server, listed all
seven tools, and successfully called discovery, inspection, installation status,
and inert preparation. The server negotiated its supported `2025-06-18` protocol.

The unmocked integration canary used production service, proposal, MCP and
lifecycle code against a full canonical runtime fixture under the real identity
home boundary. A fake GitHub CLI allowed read-only list/view operations and
rejected mutations; fake model/container/git/network executables rejected any
invocation. Preparation changed no fixture bytes and invoked no provider.
An actual empty-queue runtime cycle finished, a new MCP connection recovered its
run, and inspection reported terminal evidence with accepted task completion
unverified. This proves the module joins and lifecycle, not issue implementation,
model quality, independent acceptance, or a qualified unattended lane.

Real process fixtures separately verified failure, cancellation and timeout of
worker-plus-grandchild process groups, overlap rejection, restart recovery,
unknown-supervisor handling and bounded output.

## Account installation and remaining production boundaries

The first setup applied 22 changes and preserved 13 locally maintained files.
The final entry-skill refresh applied one additional change. Final status shows
zero missing/stale managed updates and 13 preserved local overrides. Existing
Codex configuration bytes remain an unchanged prefix of the updated file, and
the three unrelated MCP registrations remain present.

Receipts:

- `/var/home/mat/.local/state/atlasmemory-tools/installations/20261029T191949Z-b110214fa5/receipt.json`
- `/var/home/mat/.local/state/atlasmemory-tools/installations/20261029T193238Z-cbab1083a8/receipt.json`

The registered `primary` runtime is
`/var/home/mat/distrobox-homes/atlas-agent/agent-runtime`. Nine checked runtime
paths retained identical inode, modification time, size and ownership metadata
through installation and final read-only inspection. No live interface run
directory was created. No real provider/model/workload/webhook was invoked, and
the installed runtime was not upgraded.

That legacy runtime remains read-only and blocked for the new execution lane:
missing explicit execution capability, old/missing canonical runtime code,
stale active evidence, and truncated status coverage. Its current inventory
targets legacy AtlasMemory repositories; registration does not establish that
it is the correct execution target for another project. Upgrading/configuring
that host and reconciling its evidence require a separate concrete operation
with its existing authority and preservation rules.

The required Atlas briefing command separately fails with missing PyYAML in
Atlas's environment. No Atlas environment repair was performed in this scope.
