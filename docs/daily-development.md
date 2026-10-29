# Supervised daily development

The parent outcome is repeatable Atlas development through the external Tools harness. The capability is supervised, scoped work from intake through independent acceptance; an individual task is one bounded implementation leaf. This CLI adapts the existing queue and handoff APIs. A human supervisor dispatches every reserved role through the supported in-app host. The CLI never launches models, qualifies provider billing, merges changes, or supplies an unattended Atlas product scheduler.

## Install a pinned runtime

Use an owned, durable state directory outside Git and an explicit runtime directory. The following installs a fresh runtime snapshot without copying credentials or changing an existing installation. Set `TOOLS` to the reviewed Tools checkout and `SOURCE_SHA` to its full commit; review any uncommitted adapter changes separately before installing them. Pin the execution checkout independently in the task. Python and Git must already be installed.

```sh
TOOLS=/absolute/path/to/AtlasMemory-Tools
SOURCE_SHA=REPLACE_WITH_REVIEWED_FULL_TOOLS_COMMIT
PYTHON=python3
RUNTIME="$HOME/.local/share/atlas-daily-runtime/$SOURCE_SHA"
STATE="$HOME/.local/state/atlas-daily-dev"
OWNER=operator:atlas-daily-dev
export TOOLS SOURCE_SHA PYTHON RUNTIME STATE OWNER

test "$(git -C "$TOOLS" rev-parse HEAD)" = "$SOURCE_SHA"
test ! -e "$RUNTIME"
mkdir -p "$RUNTIME"
cp "$TOOLS"/templates/local-automation-runtime/*.py "$RUNTIME/"
cp -R "$TOOLS/templates/local-automation-runtime/team-templates" "$RUNTIME/"
printf '%s\n' "$SOURCE_SHA" > "$RUNTIME/source-revision.txt"

# A helper keeps runtime/state/owner identical across commands.
daily() {
  "$PYTHON" -B "$RUNTIME/atlas_local_dev.py" \
    --runtime-dir "$RUNTIME" --state-dir "$STATE" --owner "$OWNER" "$@"
}
daily status
```

To sync an upgrade, inspect the source diff, choose the newly reviewed source SHA and repeat installation into a **new** runtime directory. Finish or recover pending handoffs with their original runtime before changing versions. Keep old source snapshots and state artifacts. Do not copy over `config.env`, `repos/`, jobs, auth or other operator data in an existing general automation runtime. This supervised adapter needs no provider credentials, database, container or scheduler setup. General runtime setup remains documented in [SETUP.md](../templates/local-automation-runtime/SETUP.md).

The optional global flags `--agent-root /absolute/personas` and `--agent-registry /absolute/registry.json` resolve maintained role personas when the host requires them. Add them to the helper before the subcommand; use the same files throughout a pending handoff. Runtime APIs and team templates always come from `--runtime-dir`. The queue and job artifacts are `$STATE/work-items.json` and `$STATE/jobs`. Retain the same stable owner across restarts.

## Create clean intake and obtain sizing review

An intake file contains task/source fields, `scheduler` and `metadata`; it must omit status, evidence, claim, lifecycle, results, accepted receipts and pending handoffs. Those fields belong to the runtime. Bootstrap task files that already contain lifecycle fields are not clean intake. Source spec/package/plan pins and accepted scheduler/metadata values are preserved verbatim.

This executable example builds the reviewed v2 intake and prints the exact sizing subject for an independent reviewer. Set the checkout, spec and bounded write scope to the real task before review. Preserve the spec bytes and checkout HEAD until the task's supervised roles finish.

```sh
CHECKOUT=/absolute/path/to/task-checkout
SPEC=/absolute/path/to/frozen-task-spec.md
TASK_ID=DAILY-EXAMPLE
export CHECKOUT SPEC TASK_ID

"$PYTHON" -B - <<'PY'
import hashlib, json, os, pathlib, subprocess, sys
sys.path.insert(0, os.environ["RUNTIME"])
import atlas_local_sizing, atlas_work_items
checkout = pathlib.Path(os.environ["CHECKOUT"]).resolve(strict=True)
spec = pathlib.Path(os.environ["SPEC"]).resolve(strict=True)
revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
task = {
    "id": os.environ["TASK_ID"],
    "title": "Add the scoped development adapter",
    "goal": "Provide one supervised CLI for the bounded task described in the frozen specification.",
    "acceptance_criteria": ["The adapter passes its focused lifecycle tests using the maintained APIs."],
    "spec_path": str(spec),
    "spec_hash": "sha256:" + hashlib.sha256(spec.read_bytes()).hexdigest(),
    "scheduler": {
        "execution_repo": str(checkout), "base_branch": revision,
        "workflow_kind": "work-item", "team_template": "work-item-change-lifecycle",
        "write_scope": ["templates/local-automation-runtime/atlas_local_dev.py"],
    },
    "metadata": {"local_execution_v1": {
        "policy_id": "local-reviewed-unit-v2",
        "implementation_model": "gpt-6.1-sol", "review_model": "gpt-6.1-terra",
        "role_purposes": {"implementation": "implementation", "test-runner": "validation",
                          "code-review": "review", "semantic-alignment": "goal-review",
                          "evidence-rollup": "review"},
        "changed_interfaces": ["supervised local development CLI"],
        "unresolved_questions": [], "complexity_flags": [],
        "sizing_review": {"reviewer": "PENDING", "rationale": "PENDING independent review",
                          "subject_sha256": "PENDING"},
    }},
}
pathlib.Path("task-intake.json").write_text(json.dumps(task, indent=2) + "\n")
print(atlas_local_sizing.sizing_subject_sha256(atlas_work_items.work_item_context(task)))
PY
```

The placeholder review is intentionally unqualified. Give the reviewer the exact intake, printed subject hash, spec and parent outcome/capability linkage. Obtain `sizing-review.json` containing exactly `reviewer`, `rationale` and `subject_sha256`, reflecting the actual independent decision. Sol/high implementation and validation with Terra/high reviews are appropriate only when that review supports them. Install the observed review without changing its fields:

```sh
"$PYTHON" -B - <<'PY'
import json, pathlib
path = pathlib.Path("task-intake.json")
task = json.loads(path.read_text())
task["metadata"]["local_execution_v1"]["sizing_review"] = json.loads(pathlib.Path("sizing-review.json").read_text())
path.write_text(json.dumps(task, indent=2) + "\n")
PY
daily add --task task-intake.json
daily status
```

A changed context requires a fresh sizing review/hash. An existing operator task using `local-luna-unit-v1` remains compatible: its fixed route is Luna/medium for implementation/validation and Sol/high for review. Its contract omits the v2 model/review fields. Neither policy permits unresolved complexity to become coding work silently. Resolve questions, split oversized scope, or obtain an explicit new sizing decision before dispatch. A reviewed stronger model does not expand write/effect authority.

`add` checks substantive goal/criteria, full scheduler SHA, absolute checkout path, qualification for the selected template roles and current scheduler readiness, then appends one ready item with one creation event under the store lock. Duplicate IDs and caller-owned runtime state are refused. Input files must be strict JSON objects of at most 65,536 bytes; duplicate keys and nonfinite numbers are refused. Errors are JSON with exit code 2.

`status` is read-only: it does not create a directory, queue or lock, claim work or reconcile state. It reports scheduler state/readiness/blockers, pending handoff ID, role, owner and next action. An uninitialized queue is an observation, not an error.

Recover a pending handoff through the same invocation before acting on other guidance. A `done` item needs no further action; inspect its retained evidence when needed. For `failed`, `cancelled` or `superseded`, inspect the retained evidence and review an explicit recovery or successor task. These terminal states do not call for another prepare. Draft and blocked items show scheduler prerequisites, including explicit blockers and dependencies, alongside their existing state or execution diagnostics. Resolve those prerequisites and review the item's state before preparing. Displaying them does not change readiness or clear a blocker.

## Prepare, dispatch and import one role

Use the exact full SHA frozen in the intake. The runtime independently verifies the checkout root and current HEAD. Prepare claims only the named eligible item, or resumes the same owner's running claim. Any unresolved store-wide handoff prevents claiming unrelated work. The CLI also extends scheduler readiness inside the maintained claim operation: the provider rechecks the current queue under its existing store lock before writing a claim. A competing preparation that appears after the initial scan therefore leaves the unrelated item ready and unclaimed. Running-item and pending-reservation replay retain the maintained behavior.

```sh
REVISION=$(git -C "$CHECKOUT" rev-parse HEAD)
daily prepare --id "$TASK_ID" --revision "$REVISION" > reservation.json
```

The complete stdout artifact has exactly `status` (`prepared`), `binding`, `packet` and `artifacts`. Its binding contains the model/reasoning assignment and immutable identity hashes. Preserve this whole file. Preparation persists the reservation before writing stdout: if redirection fails or output is lost, repeat the **same** command with the same owner and revision to reexport it. The queue is the sole reservation authority.

Use the supported in-app host to dispatch the exact emitted `packet`, in the bound checkout at the bound SHA and fixed model/reasoning assignment. Keep the actual host invocation ID. The worker must write its original role-result JSON bytes to a regular file; do not copy a reformatted chat response into a substitute result. There is no dispatcher command in this adapter and no fabricated automatic host instruction.

Each packet contains `result_instructions` and a task-bound `result_template`. The reservation's packet hash binds both. The worker fills its emitted template with substantive results, preserving this contract:

- The sole root key is `role_results`, containing a list with exactly one record for the reserved `role_id`.
- `status` is `complete`, `blocked` or `failed`. `outputs` maps the exact `must_produce` names to strings, with no extra names. Use a string to describe a file or structured result; do not put lists or objects in output values.
- `evidence` belongs at record level as a list of strings, alongside `outputs`. `notes` is a string and `contract_issues` is a list of strings.
- For an ordinary role, keep `goal_review` null. A goal gate requires an object containing exactly `verdict` (`pass`, `fail` or `inconclusive`), a nonblank `reason` and a nonempty list of nonblank `evidence` strings. The reviewer supplies its own judgment and evidence. The emitted template starts blocked with empty outputs; its goal review starts inconclusive and unfilled. Neither default establishes completion or goal acceptance.

On the currently observed collaboration host, formatting instructions are advisory: its dispatch tool exposes no JSON-schema or response-format enforcement parameter. The importer enforces the result shape, and the workflow separately checks required outputs and goal acceptance. A bare role record, nested nonstring output value or evidence list inside `outputs` is refused. An unexpected string output named `evidence` passes shape parsing but produces a workflow contract issue and blocks completion. This host observation does not qualify other hosts.

Independently observe the completed invocation and save `receipt.json` with exactly the following six string fields, replacing every placeholder with the actual host observation:

```json
{
  "invocation_id": "ACTUAL_HOST_INVOCATION_ID",
  "transport": "supervised_in_app",
  "checkout": "/actual/bound/checkout",
  "revision": "ACTUAL_FULL_BOUND_SHA",
  "model": "ACTUAL_RESERVED_MODEL",
  "reasoning": "ACTUAL_RESERVED_REASONING"
}
```

The receipt is a supervisor correlation record, not cryptographic host authentication. Do not infer it from a new pending task or invent an invocation ID. Import the complete original reservation, complete observed receipt and untouched host result file:

```sh
daily import --reservation reservation.json --host-receipt receipt.json --result original-result.json
daily status
```

Capture validates the live reservation; ingest applies the result through existing handoff APIs. The installed runtime preserves the original bytes and reports accepted artifacts. All result reads, including duplicate replay, are bounded before parsing. Exact accepted replay returns `duplicate` after pending removal, even if checkout HEAD later advances. Changed invocation IDs, result bytes, binding/packet, foreign owners and stale live packets are refused.

If formatting is refused, preserve the failed original file and refusal evidence. Have the same known worker invocation write a separate corrected file, then import that worker-authored file with the original reservation and observed receipt. Retain both attempts. The supervisor must not repair, normalize or replace the worker's bytes. An already accepted result uses exact replay; a later change requires the maintained explicit recovery process. Finish or recover already-bound old packets with their original installed runtime; new source instructions do not rewrite old reservations.

If status becomes ready for another role, repeat prepare/host dispatch/import using a separate saved reservation, receipt and original result for that invocation. Implementation completion alone is not goal acceptance: validation, independent review, semantic acceptance and rollup must run through the maintained lifecycle. A blocked role requires explicit operator investigation; this CLI has no force, cancellation, requeue or merge command.

## Stop and recover

Stop by making no further prepare, dispatch or import calls. Preserve queue/jobs, pinned source/runtime/persona files, original reservation, host invocation ID, observed receipt and result bytes. If a claim exists but no reservation was persisted, the same owner can resume prepare. If a reservation exists, reexport it rather than making another one.

If dispatch completion is uncertain, inspect that **same invocation** in the supported host before taking further action. Recover its original return instead of dispatching a replacement. If import output was lost, submit the same reservation/receipt/result bytes again; the maintained accepted receipt resolves replay. Do not edit queue ownership, checkout pins, artifacts, receipt identity or raw result bytes to bypass a refusal. Keep blocked attempt evidence and use a separately reviewed successor task when the scope or contract must change.

## Focused offline verification

From the pinned Tools checkout, use its current Python environment:

```sh
cd "$TOOLS"
"$PYTHON" -B -m unittest discover -s templates/local-automation-runtime/tests -p test_atlas_local_dev.py
```

Tests install temporary runtime copies and Git checkouts, restart the CLI as real subprocesses, exercise the maintained lifecycle and replay/refusal paths, and install tripwires for sockets, databases and non-Git process execution. They fill the emitted templates with synthetic results through the goal gate, verify exact original-byte retention, and check that refused malformed imports leave queue/job bytes unchanged. They also distinguish a refused nonstring evidence output from an imported unexpected string output that blocks the workflow. A deterministic competing-prepare regression covers the previously reproduced scan/claim race and verifies that the unrelated item stays ready without a claim while the first reservation remains replayable. Synthetic fixture results verify adapter behavior; they do not establish model quality or real task acceptance.
