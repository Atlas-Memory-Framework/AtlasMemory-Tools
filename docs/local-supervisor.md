# Local supervisor source contract

This document records the finite supervisor's private pins, input guard, and receipt contracts. Decoding pins checks declarations without inspecting files or granting execution authority. The private input guard observes declared local paths, Git state, input bytes, and queue contents before the bounded adapter may proceed. No helper discovers credentials or grants live execution authority.

## Pins v1

`_decode_cycle_pins(raw: bytes) -> dict` accepts exactly one strict UTF-8 JSON object. The top level has exactly `schema_version`, `kind`, `queue_path`, `runtime`, `execution_checkouts`, `inputs`, `admitted_item_ids`, `item_closure`, and `template_source`. Version is integer `1` (a Boolean is invalid); kind is `atlas-local-supervisor-pins`. Unknown or missing fields, duplicate JSON object keys, nonfinite numbers, invalid UTF-8, trailing JSON values, and non-object roots raise `ValueError`. The result is a fresh copy with no coercion or normalization.

The nested shapes are exact:

| Object | Fields |
| --- | --- |
| `runtime` | `checkout_path`, `head` |
| execution checkout | `checkout_path`, `head`, `entry_changes` |
| entry change | `path`, `index_sha256`, `worktree_sha256`, `index_state`, `worktree_state` |
| input | `kind`, `path`, `sha256` |
| closure item | `item_id`, `operation_id`, `execution_checkout`, `depends_on`, `immutable_sha256` |
| `template_source` | `mode`, `path`, `candidates` |

Full Git IDs are 40 or 64 lowercase hexadecimal characters. SHA-256 digests are 64 lowercase hexadecimal characters. Absolute paths begin with `/` and cannot be `/` itself or end in `/`. Relative entry paths cannot begin with `/` or `~`. Both forms reject NUL, backslash, glob characters (`*`, `?`, `[` and `]`), colon, empty components, `.` and `..`; relative paths also reject `.git` and descendants. These are lexical checks only; no resolution or symlink test occurs.

Execution checkouts are nonempty and sorted by unique `checkout_path`; the runtime checkout may also be an execution checkout. Each `entry_changes` array is sorted by unique relative path. Entry states use `unchanged|added|modified|deleted|untracked` for the index and `unchanged|modified|deleted|untracked` for the worktree. An unchanged/added/modified index state has an index digest; deleted/untracked has null. Unchanged/modified/untracked worktree state has a worktree digest; deleted has null. An untracked worktree requires an untracked index; an untracked index requires an untracked worktree. A deleted index permits only deleted or untracked worktree state. Changed present entry files must have a matching absolute `entry_file` input under that checkout, and its input digest must equal the declared worktree digest. The decoder checks these declared relationships and does not infer actual HEAD or file state.

Inputs are nonempty and sorted by unique absolute path; digests are valid and unique. Kinds are `plan`, `spec`, `role_command_config`, `team_template`, `registry`, `agent_instruction`, and `entry_file`. Exactly one `role_command_config` input is required. Admitted item IDs are nonempty, nonblank, sorted, and unique. Closure records are nonempty and sorted by unique item ID; operation IDs are unique, dependency arrays are sorted and unique, and every digest/path has the stated syntax. Every admitted ID must be present, every dependency must resolve, and recursive reachability from admitted IDs must equal the complete closure. Cycles and irrelevant extra closure records are refused. Every closure execution checkout must be listed.

`template_source.mode` is `directory` or `file`; candidates are a nonempty sorted unique list of absolute paths. File mode has exactly `[path]` and that is the sole `team_template` input. Directory mode candidates must be immediate children of `path`, end in `.json`, and each must be a declared `team_template` input; every template input must appear in candidates. B1 does not assert directory membership. The private input guard checks the complete candidate set before reading any template bytes and rechecks it at each checkpoint.

`_decode_cycle_pins` performs no file, Git, provider, worker, store, process, network, clock, or credential operations and is used by the explicit bounded branch described below. B4 owns path resolution, actual checkout/input observations, selected-item correspondence, and scope enforcement.

## Receipt v1

`_decode_cycle_receipt(raw: bytes) -> list[dict]` accepts a nonempty UTF-8 JSONL byte sequence. Every line contains exactly one object and ends with LF; blank lines, CRLF, an absent final LF, malformed UTF-8, duplicate JSON keys, nonfinite constants, missing/extra fields, and incorrect types raise `ValueError`. Returned event dictionaries are deep copies. The exact event fields are `schema_version`, `kind`, `queue_path`, `queue_key`, `cycle_id`, `seq`, `event`, `elapsed_seconds`, `prior_event_acknowledged`, `initialization_ack`, `pins_sha256`, `admitted_fingerprints`, `limits`, `counters`, `operation_id`, `source_id`, `claim_key`, `invocation_id`, `effects`, `result_sha256`, `stored_result_sha256`, `controller_reason`, `terminal_outcome`, and `unresolved`.

Each event has schema version `1`, kind `atlas-local-supervisor-event`, and an event from `opened`, `step_started`, `claim_intent`, `claimed`, `claim_not_acquired`, `launch_intent`, `worker_returned`, `result_intent`, `result_acknowledged`, `claim_settled`, `terminal`, or `closed`. Queue paths and stop-file paths use the pins decoder's lexical absolute-path rules. `queue_key` is SHA-256 of the UTF-8 queue path; `cycle_id` is 32 lowercase hex characters; SHA-256 values are 64 lowercase hex. Optional operation/source/invocation IDs are nonblank strings or null. Initialization acknowledgment is exactly `acknowledged`.

`limits` has exactly `max_steps`, `max_claims`, `max_roles`, `role_max`, `cycle_seconds`, `worker_timeout_seconds`, `worker_termination_grace_seconds`, and `stop_file`. The first three integers are positive; `role_max` is 1 through 100. Cycle and worker timeout are finite and positive; termination grace is finite and nonnegative. `counters` has exactly `steps`, `claims_reserved`, `roles_reserved`, and `observed_completed_roles`, all exact nonnegative integers. Counters cannot exceed their configured budgets and observed roles cannot exceed reserved roles. Elapsed time is finite and nonnegative.

`effects` has exactly `claim`, `launch`, and `result`; each has exactly Boolean `attempted` and `ack` from `not_attempted`, `pending`, `acknowledged`, or `unknown`. `not_attempted` requires false, `acknowledged` and `unknown` require true, and `pending` requires false because it records pre-call intent. Hash results and claim keys are lowercase SHA-256 or null. Controller reason and terminal outcome use the exact receipt schema enums; `unresolved` is Boolean.

The first event has sequence zero and null prior acknowledgment. Each later sequence increments by one and its prior acknowledgment equals the preceding sequence. Queue identity, cycle ID, initialization acknowledgment, pins digest, admitted fingerprints, and limits remain identical. Elapsed time and every counter are monotone. These are data-integrity checks only: the decoder does not validate event transition order, infer whether an effect occurred, or decide whether acknowledgment, closure, or restart is safe. It performs no file, Git, clock, provider, worker, store, process, network, or credential operation; B3 owns those lifecycle decisions and B5 supplies the explicit bounded caller.

## Durable journal lifecycle

`_CycleJournal(queue_path, pins, pins_raw_sha256, limits, *, cycle_id, acknowledged_closures)` retains validated copies of the decoded pins and limits. Construction performs no filesystem operation. `pins_raw_sha256` binds the original pins-file bytes supplied by the caller; the journal never substitutes a digest of reserialized pins. The queue path must equal `pins.queue_path`.

`acquire_and_open(open_patch)` initializes state and acknowledges the opened event before returning. The receipt path is `<queue parent>/.atlas-supervisor/<sha256(UTF-8 queue path)>/<cycle_id>.jsonl`; the fixed lock is `controller.lock` in that directory. The queue identity is its canonical path, allowing the existing provider to replace its inode. Every ancestor is opened individually with no-follow directory operations. Starting from the accepted durable queue-parent anchor, each state directory is created or checked, then synced with its parent, including existing directories. Queue, lock and receipt files must be singly linked regular files; symlinks, nonregular files, ambiguous paths, unsupported locks and sync failures refuse. The journal holds a nonblocking exclusive OS lock. It never unlinks or replaces the lock.

The journal inspects the queue for active claims and unresolved process state and checks every prior receipt while holding the lock. Every already-held closure key for this queue must have its corresponding receipt present, even when no jobs directory marks the missing cycle. Keys for other queues do not require files in this queue’s state directory. A prior receipt must have canonical bytes, valid schema and transitions, matching filename/queue identity, and a settled closed event whose exact line digest is present in the caller's still-held closure map. The exact current cycle’s preinitialized `<cycle_id>.jobs` directory may exist before its new receipt; an older jobs directory without its matching receipt refuses. It then creates the new receipt exclusively. No failed initialization is retried. No provider claim or worker launch belongs to initialization.

`append(patch)` accepts exactly thirteen adapter-owned fields: `event`, `elapsed_seconds`, `counters`, `operation_id`, `source_id`, `claim_key`, `invocation_id`, `effects`, `result_sha256`, `stored_result_sha256`, `controller_reason`, `terminal_outcome`, and `unresolved`. The journal adds exactly eleven fields: `schema_version`, `kind`, `queue_path`, `queue_key`, `cycle_id`, `seq`, `prior_event_acknowledged`, `initialization_ack`, `pins_sha256`, `admitted_fingerprints`, and `limits`. Missing, extra or overlapping ownership, changed held identities/digests, invented observations, inconsistent reservations and illegal transitions refuse before writing.

| Acknowledged event | Permitted next event |
| --- | --- |
| opened, claim_not_acquired, claim_settled | step_started or terminal |
| step_started | claim_intent or terminal |
| claim_intent | claimed, claim_not_acquired or unresolved terminal |
| claimed | launch_intent, no-launch result_intent or unresolved terminal |
| launch_intent | worker_returned, no-launch result_intent or unresolved terminal |
| worker_returned | result_intent or unresolved terminal |
| result_intent | result_acknowledged or unresolved terminal |
| result_acknowledged | claim_settled or unresolved terminal |
| terminal | closed, only with settled effects and no uncertainty |

Reservation checks use the unchanged A1 integer admission rules and the previous acknowledged counters: a new step requires remaining step, claim and role capacity; a claim requires remaining claim and role capacity; a launch reserves exactly `min(role_max, max_roles - roles_reserved)`. Thus a last admitted step can still claim, a last admitted claim can still launch, and a final partial role allowance is retained. A terminal patch with one spent step before guard refusal must also have had that integer capacity. Receipt elapsed is observed after reservation; the journal does not reconstruct earlier cancellation or deadline observations from a later timestamp.

The direct `launch_intent` to `result_intent` edge is the existing pre-worker cancellation/factory-failure exception. It preserves the reserved role allowance, requires launch attempted=false/ack=not_attempted and no invocation identity, and records the adapter's explicit blocked no-launch result. The journal does not inspect or invent original result contents. Accepted provider/worker interfaces and A3 assessments remain responsible for those contents. A no-launch settlement cannot add completed roles.

Each append writes one canonical JSON line, flushes it and syncs the receipt. Exclusive receipt creation also syncs the containing directory before acknowledging opened. Only a successful return acknowledges the event; the next sequence's prior acknowledgment refers to that success. A short write, write/flush/sync failure or invalid append poisons the journal. It performs no repair write or retry and retains the previous acknowledged event separately from any readable tail bytes.

`close(final_patch)` accepts a settled terminal patch once, appends and syncs terminal, then appends and syncs closed with the identical adapter fields except event. Only after both acknowledgments does it return `(queue_key, cycle_id, sha256(exact_closed_line_including_LF))` and place that digest in `acknowledged_closures[(queue_key, cycle_id)]`. Failure issues no witness. The journal does not change final elapsed, counters, assessment or accepted progress. `release()` closes owned descriptors and releases its lock without appending repairs, deleting receipts, requeueing work or signaling a PID.

A later cycle in the same process may use its still-held closure map. A new process starts with an empty map and refuses even a well-formed closed receipt: readable bytes cannot prove that the previous process observed the last sync return. Truncated, malformed, unclosed or mismatched history also refuses. Ordinary v1 startup does not recover old history. The opt-in v2 path described below independently revalidates selected settled evidence without reconstructing an old closure acknowledgment. Ordinary bounded mode uses this private v1 journal; local synthetic filesystem tests establish source behavior, not live admission, inference, queue-store crash durability or hostile-writer isolation.


## Private input guard

`_observe_cycle_inputs(pins, frozen, checkpoint, operation)` observes declared local inputs and returns exactly `changed`, `reason`, `head_changed`, and `trusted_expectation`. A healthy frame has `changed=false`, null reason and no changed HEAD. Refusals have reason `input_changed` or `out_of_scope_change` and no new expectation. Entry and `before_step` take no operation and return no expectation. `before_claim`, `after_claim`, and `after_worker` take an admitted `OperationState.to_dict()` snapshot and return a fresh complete A2 expectation on success. Worker-returned envelopes never supply that expectation.

The caller holds exactly five context fields: `pins_path`, `pins_raw_sha256`, `cycle_id`, `source_snapshot`, and `progress_by_item`. The guard checks this shape and the 32 lowercase hexadecimal cycle ID at every checkpoint. It checks the exact original pins-file bytes, separately from decoded JSON. Entry requires a null snapshot and an empty shared progress map. It builds and validates all observations locally before installing the complete snapshot and progress map. A failed or repeated entry does not partially initialize or replace either value.

The write-once snapshot contains exactly `input_digests`, `template_candidates`, `runtime_head`, `execution_heads`, `entry_changes`, `immutable_inputs`, and `expected_static`. Later checkpoints compare current observations with that snapshot. Each progress record contains exactly `run_id` and sorted `completed_roles`. The guard initializes these records from fresh or validated declared resume evidence; only the accepted adapter advances them after acknowledged result settlement and its agreeing fresh queue read. Later guard calls compare resume evidence with this held progress and never replace it.

### Declared files and worker selectors

Before reading any template content, the guard checks the complete immediate JSON candidate name set and opens every candidate with no-follow ancestor and regular-file checks. A new, missing, linked, directory, or other nonregular candidate refuses before template selection. This barrier repeats at each checkpoint and includes unselected candidates. Every declared input must have its pinned raw-byte SHA-256. Files must have canonical lexical paths, no symbolic-link ancestor, and a singly linked regular target. Referenced plan/spec paths and hashes must agree with their declarations. The guard reads no ambient runtime configuration or credentials.

`_cycle_guard_selectors` derives the worker's config, template source, optional registry, and agent root from these declarations. There must be exactly one command config and at most one registry. Actual registry resolution takes precedence over local Markdown fallback. A nonempty registry source must already be an absolute declared instruction path; relative sources and unresolved URIs refuse. Registry-shadowed Markdown references do not choose a local root. Unresolved relative file references must have exactly one common root obtained from complete suffix matches against declared instruction paths. Absolute fallback references must be declared individually; when they are the only local fallbacks, the canonical queue parent is the required non-null resolver sentinel. It grants no permission to read other files in that directory. With no local fallback, the derived root is null.

Instruction contents are read only after selector admission, and the guard then exercises the unchanged resolver against the admitted files. The bounded composition uses this same derivation and rejects conflicting CLI selectors before constructing the worker.

### Git state and immutable queue inputs

Runtime and execution checkout paths must be their actual Git roots, with full pinned HEAD values. Runtime implementation files under `templates/local-automation-runtime` must be clean and regular. Unrelated runtime files may be dirty while its full HEAD remains pinned. Execution entry changes must match the declared index/worktree states and raw-byte digests exactly, including staged additions, deletions and untracked files. Unresolved index entries and nonregular changed files refuse. Renames are checked as separate deletion and addition paths.

Git observations use local plumbing with ambient Git configuration variables removed, system/global config disabled, optional locks disabled, and no external diff, textconv, hooks, fsmonitor or lazy fetching. Worktree comparisons use `hash-object --no-filters`, so repository clean filters cannot execute and line-ending conversion cannot hide raw-byte drift. Ignored untracked files remain changes. A later change must name an exact admitted file scope; a file scope never admits descendants or a substituted directory/link. A missing planned file can be created at its exact path. Changes outside the admitted scopes stop the cycle. A worker commit changes HEAD even when its changed paths remain in scope, so it stops later launches.

The immutable fingerprint uses accepted provider projection and bounded context precedence for every admitted item and its complete dependency closure. It includes source/operation identity, title, repositories, branch, canonical set-valued scope/dependencies, effective scheduling/workflow inputs, and source instructions including initial rework instructions. It preserves ordered prompt and validation content. Lifecycle, claim/result/evidence records, workflow progress, counters and current `rework_count` do not alter this fingerprint. Current rework instructions are recomputed rather than replaced with an old value. New queue items never join the held admission; duplicate identities and missing or changed closure items refuse. The provider still owns readiness and dependency acceptance.

### Resume path admission and accepted progress

Resume selection follows the worker's reversed `workflow_runs` order. For a required goal workflow, a newer dictionary record with the wrong template, contract or rework value refuses before an older record can be considered. These metadata checks and path admission precede any selected artifact read, including generic declared-file hashing. Entry resume artifacts must be exact declared `entry_file` inputs. A complete, fully validated baseline can be returned for the adapter to skip without a claim or worker launch.

After entry, the only initially undeclared resume read is exactly `<queue parent>/.atlas-supervisor/<sha256(canonical queue path)>/<cycle_id>.jobs/atlas-work-item-<safe_id(source_id)>-<32 lowercase hex invocation UUID>/team-run.json`. It also requires a held non-null accepted run for that source. The guard checks components before probing the target, then no-follow ancestry, regular-file identity, actual loaded TeamRun identity, stored summary agreement, trusted outputs, dependency closure, optional review shape and passing goal evidence. It compares the resulting run ID and satisfying roles with the adapter's held progress. Missing files, foreign cycles, lookalike roots, traversal, malformed or foreign identities and conflicting progress refuse. A `safe_id` collision grants no item identity: the loaded work-item ID must still agree.

Every invocation may move the artifact to a new UUID directory while the resumed logical run ID stays fixed. The directory UUID is therefore not compared to the persistent run-ID suffix. The canonical worker constructs its artifact paths under its assigned root; actual artifact preparation, result application and provider rollup recording are tested with temporary files and no process/model invocation.

The bounded composition is responsible for generating and separately holding the cycle ID, checking that held identity before every callback, and initializing the exact jobs root exclusively under the journal lock after opened and before the first readiness observation. Direct guard calls consume trusted caller inputs; they do not authenticate a caller-supplied cycle as platform authority. This guard does not initialize a jobs root, claim work, launch a process, record results, repair receipts, recover a prior cycle or signal a PID.

If a post-worker check detects source, input, HEAD or scope drift, its frame supplies no replacement trust. The accepted adapter retains the original held expectation and exact original result for one settlement attempt, records the separate drift assessment, and stops. The observations detect accidental drift under cooperative ownership; they do not provide atomic isolation against a hostile concurrent writer or strengthen the existing queue store's crash durability.

Focused tests use temporary local Git repositories, the actual five-role template, accepted resolver and workflow artifact functions, and real local provider/journal composition. They cover fresh and declared resume entry, five moving invocation paths through pending goal, passing goal and evidence rollup, complete-baseline skipping, all guard checkpoints, raw pins/read-set drift, selector ambiguity, scope/HEAD changes and ownership-before-read refusals. These source controls do not establish live inference admission or native Atlas retention. The bounded constructor and closure composition are described and tested below.


## Explicit bounded entry

`atlas-agent-orchestrator --atlas-bounded` composes one finite local cycle. The branch runs immediately after argument parsing and returns before legacy queue, remote, daemon, triage or publication startup. Ordinary invocations keep their existing behavior. Every bound and input below is mandatory, including `--atlas-role-max` even when its value is the legacy default 100:

```bash
./atlas-agent-orchestrator --atlas-bounded \
  --atlas-work-items /absolute/queue.json \
  --atlas-role-command-config /absolute/commands.json \
  --atlas-cycle-pins /absolute/pins.json \
  --atlas-max-steps 5 --atlas-max-claims 5 --atlas-max-roles 5 \
  --atlas-role-max 1 --atlas-cycle-seconds 120 \
  --atlas-worker-timeout-seconds 30 \
  --atlas-worker-termination-grace-seconds 1 \
  --atlas-stop-file /absolute/existing-parent/stop
```

`--once` is optional. Optional `--team-templates`, `--agent-registry` and `--agent-root` must exactly equal the selectors derived from declared files; they cannot select extra inputs. Both `--option value` and `--option=value` work. Duplicate, abbreviated, missing or non-whitelisted options refuse in bounded mode, even when an explicitly supplied forbidden option equals its legacy default. Bounded-only options without bounded mode also refuse, including argparse abbreviations. Raw commands, daemon/sleep, dry-run, remote, triage, deployment and publication options cannot enter this branch.

The pinned runtime checkout must contain the actual executing canonical `templates/local-automation-runtime/atlas-agent-orchestrator`, canonical role runner and imported runtime helpers. A copied or renamed driver and mismatched helper roots refuse. The existing input guard checks that checkout's pinned HEAD and clean runtime implementation files. Every admitted work item must have an explicit, ordinarily qualified `local_execution_v1` contract for all selected roles; missing, null, malformed or blocked contracts cannot fall back to ambient model settings. This does not promote an ordinary work item to the supervisor's exact reviewed Sol route.

The entry takes its monotonic clock anchor before pins and source preflight. All later work charges that same clock. One internal UUID binds the adapter, journal and frozen guard context. Its jobs root is exactly `<queue parent>/.atlas-supervisor/<queue hash>/<cycle>.jobs`; no option, environment value or pins field can supply another cycle or root. The bound guard compares the original cycle, queue and pins identities before each observation. In ordinary v1 mode, it creates the root exclusively at the first `before_step` callback, after the journal has acknowledged opened under its OS lock and before readiness or claim. It syncs the new directory and its parent, then checks the same directory identity at later callbacks. A lock loser creates no jobs orphan. Collision, replacement or initialization failure refuses without adoption, deletion or retry.

The factory constructs only the canonical `LocalCommandOperationWorker` with the pinned command config, derived selectors, exact reducer allowance, owned root and explicit timeout/grace. The adapter supplies its existing cancellation token. The canonical worker creates workflow artifacts inside that root; the unchanged provider records its exact result and reads the corresponding owned rollup. A later invocation may move the artifact path while retaining the logical run ID. No wrapper changes the returned result or grants authority from a returned path.

SIGINT and SIGTERM only latch cancellation, and every successfully replaced handler is restored on every exit, including partial installation failure. A present stop-file name latches stop without reading its contents or following its target. A missing name means continue only when its canonical existing parent can be opened and inspected; missing, linked or unreadable parents and inspection errors latch refusal. Deadlines prevent another launch but do not promise a hard total return time: an owned worker may still require termination and an already-held result still requires one settlement attempt. Errors and lost acknowledgments retain uncertainty; they never trigger an automatic retry or effect replay.

The command prints the adapter's finite JSON outcome. A resolved completion, budget stop or cancellation can exit zero; an input refusal, blocked/failed result or unresolved outcome exits two. An ordinary v1 CLI process has an empty closure map and refuses prior receipt history, including apparently closed bytes. The explicit v2 selection below is required for recovery. Neither mode supplies a force, cleanup or requeue option.

Synthetic source tests exercise the actual provider/store, guard, journal, worker artifact/resume/rollup functions and worker process supervision. Their controlled finite Python role fixtures replace only the inference launch; temporary source-location seams bind their clean fixture checkouts. Those tests do not establish live model execution, network/database admission, hostile-writer isolation, native retention or stronger queue-store crash durability. Actual model CLI inference has not been run for this change.


## Opt-in same-boot recovery

Add `--atlas-recoverable` to the full bounded invocation to create a v2 cycle. To inspect or continue that exact cycle, repeat the original explicit inputs and bounds and add `--atlas-resume-cycle <cycle_id>`:

```bash
./atlas-agent-orchestrator --atlas-bounded --atlas-recoverable \
  --atlas-resume-cycle 0123456789abcdef0123456789abcdef \
  --atlas-work-items /absolute/queue.json \
  --atlas-role-command-config /absolute/commands.json \
  --atlas-cycle-pins /absolute/pins.json \
  --atlas-max-steps 8 --atlas-max-claims 8 --atlas-max-roles 8 \
  --atlas-role-max 1 --atlas-cycle-seconds 120 \
  --atlas-worker-timeout-seconds 30 \
  --atlas-worker-termination-grace-seconds 1 \
  --atlas-stop-file /absolute/existing-parent/stop
```

Use the selected cycle's actual 32-character lowercase hexadecimal ID and its original values. Both recovery flags require bounded mode; resume also requires `--atlas-recoverable`. All original inputs and bounds remain mandatory. Duplicate, abbreviated, mixed and default-valued forbidden options refuse before effects. A resume failure never creates a replacement cycle. Existing v1 receipts are not migrated or resumed.

### Original authority and clock

V2 retains the original pins-file bytes and canonical path, admitted dependency closure, input digests, template candidates, runtime/execution HEADs, entry-change arrays, scopes, role contracts, accepted workflow run and progress. No resume step repins the source or adopts a new queue item. The original step/claim/role reservations and observed-role total remain spent; fully validated complete baseline roles cost no new claim or role reservation.

Each cycle records `origin = {boot_id, entry_monotonic, pins_path}`. The boot UUID comes from Linux `/proc/sys/kernel/random/boot_id`; no caller override or clock fallback exists. Every new coordinator charges current monotonic time against the original anchor, including downtime and recovery preflight. Different boots, backward/nonfinite clocks and changed bounds, timeout, grace or stop path refuse. The original saved pins pathname is compared before reading the selected pins file, so an equal-byte copy at another path cannot substitute for it.

Current stop presence and stop-inspection errors still prevent continuation. A saved cancellation or terminal disposition cannot be cleared by removing the stop file. SIGINT/SIGTERM remain cooperative latches; a volatile signal that was never durably recorded cannot be promised to survive abrupt process death.

### Custody and a fresh acknowledgment

Resume opens existing canonical ancestors, lock, receipt and jobs directory only. It creates nothing and retains the same no-follow descriptors and nonblocking controller lock across pins binding, source validation and admission. Files must remain singly linked regular files, directory identities must agree and the exact raw prefix must remain unchanged. Missing, torn, malformed, v1, sibling or identity-mismatching history refuses without repair, truncation or fallback to an earlier capsule.

Held storage is inspection custody. It does not grant execution authority or reconstruct historical acknowledgment. Before continuation, the guard independently binds the saved static snapshot to original pins, checks current source and scope, loaded workflow outputs/dependencies/goal evidence and accepted progress, and compares each item's latest settled result, relevant claim, canonical invocation artifacts and resolved process marker. Active claims or unresolved process state anywhere in the current queue forbid writable admission. Inspection itself may retain such evidence. Historical PIDs are never signaled, adopted or treated as proof of termination.

Only successful `recovery_admitted` append/flush/sync return in this process admits a fresh epoch. Its prior acknowledgment is null, `old_tail_acknowledgment` is `unknown`, and `revalidated_prefix_sha256` binds all exact preceding receipt bytes. Ordinary rows retain that epoch and normal preceding sequence acknowledgments. A loaded admission row supplies no local acknowledgment. The private immutable seed is installed and consumed once only after current admission succeeds; it restores the original guard maps, counters, done IDs, cancellation, substantive identities/effects and actually admitted elapsed before another reservation.

### V2 records and settled boundaries

`_decode_cycle_receipt_v2` strictly validates the complete canonical history, data domains, transitions and capsule lineage. V2 keeps every v1 field and adds exactly `controller_epoch`, `origin`, `recovery_state`, `revalidated_prefix_sha256` and `old_tail_acknowledgment`. The exact capsule has seven fields: `source_snapshot`, `progress_by_item`, `done_ids`, `cancellation`, `jobs_identity`, `disposition` and `settlement`. At initial readiness, settlement is null. At a settled claim it retains the exact original result and claim, trusted pre-result expectation and actual assessment. Terminal state keeps the full last accepted capsule; closed must preserve the terminal capsule exactly. A completed terminal requires every admitted item in `done_ids`, each with its complete validated role set.

Fresh v2 startup acknowledges opened, checks stop/deadline, creates/syncs the journal-owned jobs directory and publishes `recovery_ready` with the original installed snapshot and actual root identity. Later guards verify that held identity, even when the latest row has no capsule. Before each next-step guard, `step_reserved` durably publishes the proposed charge; only its successful return installs that charge. `step_started` resets identities/effects without a second charge. Ordinary v1 ordering stays unchanged.

For claim settlement, the adapter computes candidate progress and done IDs before publishing `claim_settled`. Its successful append is acceptance; only then does the adapter install that complete candidate, before a late stop/deadline check. No-launch settlement adds no roles or invented invocation. A failed or lost return poisons that object: no retry, continuation or witness follows. A later explicit coordinator may independently revalidate complete canonical safe bytes that landed, while retaining unknown old acknowledgment. Incomplete/unsafe bytes remain refused. This is process recovery on the same boot, not a host power-loss durability guarantee.

| Exact newest frontier | Recovery behavior |
| --- | --- |
| `recovery_ready`, complete `claim_settled` with continue/done disposition, `recovery_admitted` | Eligible for full current validation and a fresh local epoch acknowledgment. |
| Settled `terminal`/`closed`, or a halt disposition | Full current validation and read-only reporting; no writable admission or old witness. |
| `opened`, `step_reserved`, `step_started`, `claim_not_acquired` | Unsupported frontier; explicit reconciliation required, with saved counters. |
| Claim/launch/result intent, `claimed`, `worker_returned`, `result_acknowledged`, unresolved terminal | Unsafe frontier; reconciliation required even if a later result or artifact appears. |

A surviving worker or descendant may still produce effects after controller loss. A released controller lock or exited worker leader does not prove group termination. Recovery never requeues a held claim, replays a role, settles an ambiguous result from its apparent artifact, or clears uncertainty by repeated inspection.

### Reports and source qualification

V2 JSON adds `recovery` to the ordinary finite result. It reports cycle/epoch, frontier/sequence/prefix, original origin/limits, saved counters and explicit status. Missing unreadable history has unknown counters/time rather than a fabricated fresh budget. `report_only` requires independently validated current evidence. Terminal inspection leaves receipt, queue, results and artifacts byte-identical, appends no observation and returns `closure_witness: null`.

When the adapter has released custody, `evidence_source: controller_memory_after_release` labels retained memory, with `validated: false`. It is not a fresh disk check or grant of recovery authority. `local_recovery_admitted` records only this process's successful epoch return; historical acknowledgment stays unknown. Independently validated read-only reports use `held_existing_history`. Unsafe or unresolved execution reports reconciliation explicitly.

Focused tests execute separate coordinator A/B/C processes with the actual CLI, guard, journal, store/provider and worker artifact pipeline. Only the canonical inference launch is replaced by finite Python role producers and temporary source-location binding. Fsynced markers outside jobs and the execution checkout count each role independently, without deduplication. Trials cover settled interruption before volatile installation, one logical run across five invocation directories, a complete baseline plus pending item, byte-identical terminal observation, applied-claim/result lost acknowledgments, live orphan/descendant ambiguity and lock contenders. Cleanup uses owned handles or freshly adopted unreaped fixture children under a test-only subreaper, with finite deadlines and reap evidence. These tests do not establish live model execution, arbitrary scheduling, native retention, hostile-writer isolation or stronger queue-store crash durability.
