# AtlasMemory-Tools development

This repository owns shared development instructions and the external automation
harness. Its runs are evidence about these tools, not proof of Atlas product
capabilities.

## Start and resume

Read `git status --short`, the relevant canonical skills, and
`docs/local-harness-operating-instruction.md`. If `.atlas-dev.local.json` exists,
read its explicit runtime, state and owner locations and inspect the existing
queue before creating another task. The configuration is local operator state;
do not publish it. Never execute live jobs from the source template directory.

Use `docs/daily-development.md` for the supervised add, status, prepare and import
commands. Keep one persistent work-item identity through implementation, tests,
review and handoff. A prepared packet or imported result alone is not completion.

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
