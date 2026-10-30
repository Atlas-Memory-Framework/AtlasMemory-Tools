# AtlasMemory-Tools development

This repository owns shared development instructions and the external automation
harness. Its runs are evidence about these tools, not proof of Atlas product
capabilities.

## Start and resume

Read `git status --short`, the relevant canonical skills, and
`docs/local-harness-operating-instruction.md`. For the supervised daily lane, run
`python3 -B scripts/atlas_daily.py status` and follow `docs/daily-development.md`
before creating another task. The read-only entry selects `.atlas-dev.local.json`
relative to the resolved script checkout, including through a symlink, rather
than the current directory. To select another config explicitly, use
`python3 -B scripts/atlas_daily.py --config /absolute/path/.atlas-dev.local.json status`.
Missing or contradictory selection is an error; do not guess another installation.
The configuration is local operator state; do not publish it. Never execute live
jobs from the source template directory.

Use `docs/daily-development.md` for the supervised add, status, prepare and import
commands. Keep one persistent work-item identity through implementation, tests,
review and handoff. A prepared packet or imported result alone is not completion.
The entry supports status only; mutations use the guide's existing `daily` helper
with runtime/state/owner taken from the same explicit config. Recover any pending
handoff through the same invocation before other work. Checkout HEAD and candidate
drift are reported separately from the runtime source pin. Markers record source
provenance, not installed-file integrity or host/account/model qualification.
The supervisor verifies the exact host and route before dispatch. This lane grants
no unattended or merge authority; do not route it into general issue-to-PR commands.

## Scope before implementation

Use the existing planning workflow to connect the intended outcome to the
capability needed and this task's specific contribution. Preserve the broader
intent and anti-targets. Define changed behavior, non-goals, dependencies, source
pins, failure behavior and evidence that would reject a plausible wrong result.
If a decision is unresolved, make the next bounded task resolve that uncertainty;
do not hide it in an implementation assumption. Name the integration evidence
that will show the child tasks collectively achieve their parent outcome.

Choose models by reasoning difficulty and coupling, not file count alone. Luna
is the default for clear bounded work. Use Sol or Terra for sizing, independent
review, and coherent difficult implementation when justified. A stronger model
does not resolve an unclear objective or grant a broader write scope. Keep the
actual routing policy and task-bound sizing evidence in the work item.

## Execute and close

For eligible approved work, use the configured local queue and its maintained
handoff APIs. Keep implementation and goal review independent. Use the actual
reserved assignment, original result bytes and observed host receipt; never
construct a passing result on a worker's behalf. Retain blocked attempts and
link explicit repairs or successors. Do not redispatch an uncertain invocation.

Run the affected checks and the repository verifier before release. Preserve
generated adapter freshness and runtime-local configuration/state during sync.
Record the accepted source version, runtime version, validation, review, queue
state and next action at exit. Qualify the exact lane before longer or unattended
operation; a supervised canary grants no unattended authority.
