# Azure supervisor validation — September 9, 2026

The local implementation connects fresh intake, readable approval requests and
existing bounded Azure operations. See the [operating guide](azure-supervisor.md)
and [implementation plan](azure-supervisor-plan-2026-09-09.md). No unattended
promotion follows from the offline results below.

## Reviewed implementation

- `atlas_supervisor.py` coordinates bounded observation, exact operation grants,
  material progress, durable intent and restart reconciliation. It prepares
  sanitized revision-tested dependency proposals without applying them.
- `atlas_intake.py` binds real native revisions and declared source evidence;
  incomplete definitions remain drafts with concrete questions.
- `atlas_approval.py` prepares text/HTML requests, exact signing exports and
  verified response imports. A protected external issuer adapter handles human
  authentication separately. Reopening a decision requires reconciled evidence.
- `AzureWorker.verify_prepared_evidence` rechecks the actual candidate, command
  receipts, acceptance files and independent role artifacts on resume and
  publication. Current remote PR/ref evidence determines whether a PR is open.
- The explicit command wrapper exposes these operations and suppresses their
  effects under dry-run. Copy/sync guards preserve supervisor and inbox state.

Four implementation owners cross-reviewed the slices. Regressions fixed before
delivery include overwritten conflict identities, human requests bound to an
unfilled draft, stale prepared artifacts, publication using the draft revision,
stale remote PR projections, redirected issuer ancestry, lost decision flags in
generated commands and missing approval revision metadata in operation journals.

## Verification

After the live URL compatibility correction, direct runtime discovery passed
**848 tests** in 82.894 seconds:

```bash
python3 -B -m unittest discover -s templates/local-automation-runtime/tests
python3 -B scripts/verify_repo.py
```

`scripts/verify_repo.py` passed its 109 repository tests, 55 plan-to-issues tests,
full 848 runtime tests, adapter/harness checks and whitespace validation. Logs:
`/tmp/atlas-supervisor-runtime-tests-20260909-guid-final.log` and
`/tmp/atlas-supervisor-verify-repo-20260909-guid-final.log`.

Final delivered-checkout verification also passed **109 repository, 55
plan-to-issues and 848 runtime tests**, plus harness and whitespace checks. The
runtime portion took 42.565 seconds; the complete log is
`/tmp/atlas-supervisor-target-verify-20260909-final.log`. Source delivery checks
matched all 365 expected files, with 30 intended changed/new paths and all 335
other original paths preserved; HEAD is unchanged. The preservation receipt is
`/tmp/atlas-supervisor-preservation-final.json`.

The first repository run identified a portable-example placeholder mismatch;
the disabled issuer profile now follows the existing `OWNER` convention. No test
exception or authority relaxation was introduced. Delivered-checkout validation
and the live read-only result are recorded with the pilot receipt below.

New focused coverage includes 48 approval tests, 26 intake tests, 29 supervisor
tests and 19 independent outcome evaluations. The provider and reconciliation
suites pass 40 and 55 tests respectively. All 63 existing Azure Worker tests
also pass. Existing Azure throttling, incomplete/stale reads, dependency,
concurrent-claim, path-conflict, duplicate-publication, revision-conflict and inert
preview coverage remains in the full suite. No browser tests were run.

## Independent outcome and operator-burden evaluation

The final isolated `azure-supervisor-offline-v1` evaluation passed all **19 cases**
in 10.956 seconds, with zero failures or errors and every source pin matching.
Its retained source-bound receipt is
`/tmp/atlas-supervisor-offline-evidence-20260909-dq7dtaio/report.json`.
Azure, model and issuer transports are synthetic. Intake, signature verification,
authority checks, dispatch, worker journals and evidence ingestion use production
code. These are protocol and boundary results, not model-quality, cost or live
performance measurements.

| Trial | Observed result |
| --- | --- |
| Direct bounded baseline | Prepared candidate, five synthetic model calls, separate assessment/execution grants |
| Supervisor with the same task | Same prepared candidate and five calls; two review cards and two total revisions |
| Unchanged authority wait | One card, one revision, zero model calls; stops after two unchanged observations |
| Human answer | Verified answer enters both routing contexts and worker context; no repeated input after a two-day prepared-candidate wait |
| Lost child return | Durable candidate or Board receipt is reconciled before another operation |
| Changed scope, revision, source or evidence | Old authority/progress cannot substitute for current proof |
| Remote PR abandoned, missing or changed | Observation blocks; no repeated publication or model calls |
| Exit zero without acceptance | No prepared candidate or completion claim |
| Observed native GUID format | Actual provider/supervisor/reconciler code reads the synthetic 37-node graph as 53 native / 18 missing, prepares exactly 18 unapproved additions, and starts no child |

One earlier evaluation run overlapped both full test gates. Its positive setup
for `test_missing_independent_review_cannot_remain_a_prepared_candidate` stopped
before implementation with `fixed signature verifier failed or exceeded its
time limit` (the verifier limit is five seconds). That generic error does not
establish whether verification failed or timed out; resource contention is an
inference. The worker claim was blocked, the supervisor uncertain, and completion
false. The failed receipt is retained at
`/tmp/atlas-supervisor-offline-evidence-20260909-u6r18o0m/report.json`.
On the unchanged isolated rerun, that case passed in 1.0058 seconds: it reached
prepared state, removed the review artifact as intended, and correctly blocked
resume. No timeout, authority or source change was made to obtain the pass. The
overlap failure remains a qualification concern; run heavyweight local gates
sequentially and investigate verifier reliability before unattended promotion.

Disposition: **defer unattended operation**. A real qualified one-item worker
canary is still required. The local clock budget is admission/between-operation
enforcement; synchronous child transports keep their own timeouts and may finish
after the outer deadline. Observed token budgets are not hard token/dollar caps.
Models and grants retain the existing routing policy; original worker defaults
remain Astra/max. No real model was dispatched by these tests.

## Delivery and live pilot

The initial 26-file source delivery was applied to the requested AtlasMemory-Tools
checkout with per-file before/after hashes, mode checks and an unchanged HEAD
(`0a571a5b94dfa6ea53a7ea032b4d300b5002f8bf`). Existing dirty source work was
preserved. Delivered-checkout `scripts/verify_repo.py` passed 109 repository,
55 plan-to-issues and 831 runtime tests; its log is
`/tmp/atlas-supervisor-target-verify-20260909.log`.

The read-only pilot uses
`/home/instablinds-admin/.local/state/atlas-azure-pilot-20260909`, with exactly
read capability, one cycle, one selected item and no queued child actions. This
is local evidence state, not a runtime installation or background process.

The first ancestry check stopped before authentication because the account's
home contained an empty `.git` directory. Metadata inspection confirmed it had
no entries or repository objects. A narrowly reviewed, reversible repair renamed
that exact empty directory to
`/home/instablinds-admin/.git.empty-marker-backup-20260909`. No repository,
credential, permission or runtime safety rule was changed. The empty backup is
retained; any rollback must first confirm it is still empty and `.git` absent.

### Live compatibility finding

The initial observation read all 37 expected work items with consistent native
revisions. Its dependency interpretation was invalid: Azure returned native
URLs containing the project's GUID, while the parser recognized organization-
scoped and project-name URLs. Consequently the initial receipt's zero-native /
71-missing result is **not Board drift evidence** and must not be applied.

Sanitized readback of work items 18, 21 and 97 established that both their own
URLs and native relation URLs use project GUID
`6fb87f10-7d68-41ad-88ae-7ec8cfce0699`, matching the Website repository's project
metadata. The compatibility repair shares strict URL parsing between inspection
and reconciliation, verifies the GUID from each item's self identity, pins it in
reconciliation proof, rejects mismatches and completes both directions of the
bounded native closure. Regression tests precede the repeated observation.

### Corrected live observation

The five-file compatibility correction was delivered with exact before/after
hashes after the full gates passed. At **2026-09-09 13:36:39 UTC**, the repeated
read observed **37 items, 53 native dependency edges, 18 missing edges and zero
unexpected edges**. Native read completeness is true, with no read blockers;
dependency completeness is false and **eligible count is zero**. Contract
approval and execution authority remain unestablished.

The supervisor prepared an **unapproved proposal with 18 relation additions
across 11 revision-tested patches**. All existing 53 links and human-owned fields
remain intact. No approval cards were issued because the intake has no named
owner or runnable action; its missing fields and questions are recorded instead.

| Issue | Missing predecessor IDs proposed for review |
| --- | --- |
| 44 | 63 |
| 45 | 18 |
| 46 | 18, 44, 45 |
| 51 | 46, 140 |
| 54 | 52 |
| 62 | 61 |
| 63 | 62 |
| 97 | 16 |
| 134 | 18, 45, 54 |
| 135 | 52, 134 |
| 141 | 132, 135 |

Every ID above belongs to `azdo:Instablinds:Instablinds`; the proposal retains
fully namespaced IDs. These are proposed prerequisites, not completion claims
or newly authorized writes. A later apply requires fresh revisions, review of
the exact proposal, and its own verified signed Board grant.

The protected pilot directory retains:

- `pilot-receipt-retry.json`: corrected observation and effective configuration.
- `supervisor-observation-retry.json`: bounded controller result and proposal path.
- `intake-report-retry.json`: real revision, declared source evidence and questions.
- `board-snapshot-retry.json`: normalized current native graph.
- `repository-ref-evidence-retry.json`: fresh complete 73-head-ref read.
- `.azure-supervisor/proposal-1c00dd3a7862f4f6e9f34dc6d1195b06a9ecf301157bc855a6aa87f68294e9c0.json`:
  exact sanitized proposal; canonical JSON SHA-256
  `1c00dd3a7862f4f6e9f34dc6d1195b06a9ecf301157bc855a6aa87f68294e9c0`.

The initial receipt is preserved for diagnosis and superseded only for its
dependency interpretation. The successful observation used no real model calls,
worker dispatches, issuer invocation, server writes or installation. Planning,
implementation, review and repair remain explicitly `gpt-6-astra` / `max` in
the pilot configuration. Actual model transport and worker availability remain
unqualified until a separately authorized canary.

### Repository and intake decisions

The Website repository identity is
`5e0a59cc-2cd4-4bc1-a779-a7e2387242a0`. A complete listing returned 73 head refs,
including `main` at `13d7654cb556f99bfafde95e7bec9dd0401d4e76` and no `develop`.
The current Website policy and runtime configuration expect `develop`; neither
was silently changed. A reviewed decision must establish the intended base and
integration authority before a worker can be qualified.

The broader repository inspection remains explicitly incomplete: it enumerated
90 PRs and reached the bounded 50-PR policy-evaluation budget. This is a read
coverage limitation, not an approval failure on any particular PR. A later
candidate needs current evidence for its exact PR and branch. No workflow or
deployment was started, approved or inferred from those reads.

The selected real intake is `azdo:Instablinds:Instablinds:21`, native revision 4.
Its declared inputs include the Website agent policy and asset-verifier source
and tests. Ownership, base commit, work branch, bounded write scope, commands and
acceptance remain unresolved. The intake honestly stays a draft; file existence
does not establish what change should be made or what evidence accepts it.

Live model assessment, worker dispatch, PR publication, Board changes,
installation and issuer enrollment remain separate authorizations. The user
retains the immediate staging blocker and all excluded release actions.

## Develop task-branch compatibility candidate

SR-02 adds `develop-*` task branches to the Azure DevOps adapter without
widening protected refs or publication authority. The shared validator accepts
only `feature/<nonempty>` and `develop-<nonempty>`. Existing safe-ref checks
still reject `main`, `develop`, empty suffixes, traversal, colons/refspecs,
double separators, hidden path components and `.lock` endings.

Both the REST push boundary and worker push command use the shared validator.
Pushes remain absent-ref compare-and-swap creations; existing-ref update or
deletion, uncertain-write retry, non-draft PR creation and protected-branch
publication remain blocked.

The isolated `fix/develop-task-branches` candidate passed:

- `python3 -m unittest discover -s templates/local-automation-runtime/tests -p 'test_azure_devops.py'`: 41 tests.
- `python3 -m unittest discover -s templates/local-automation-runtime/tests -p 'test_azure_worker.py'`: 63 tests.
- `python3 -m unittest discover -s templates/local-automation-runtime/tests`: 854 tests.
- `git diff --check`.

No runtime was installed, issuer enrolled, grant created, Website ref published
or Azure DevOps item changed by this validation.
