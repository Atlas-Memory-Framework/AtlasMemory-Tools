# Interpretation-integrity development harness

This harness validates evaluation contracts, synthetic fixtures, execution traces
and private review artifacts. Integrating its source does not establish scientific
efficacy, approve private data, qualify a provider, install a runtime or grant
execution authority. Its artifacts retain `authority_effect: none` and
`atlas_native_capability: false` where those fields are part of the contract.

The [evaluation plan](../plans/interpretation-integrity-evaluation.plan.md) records
the intended experiment and its outstanding human and evidence gates. Independent
fixture/gold review, private reconstruction review, the E0 freeze and later E1–E3
evidence remain separate work. Before a future E0 run, review and refresh the
plan's old source baseline; do not expand its owned-change allowlist to claim
unrelated Azure implementation changes as evaluation-owned evidence.

## Execution evidence

Worker and grader success requires a complete terminal event with nonnegative,
integer input/output token measurements. Exit zero and an output file alone do
not establish successful execution. Failed or timed-out calls retain their
available partial usage and normal bounded retry behavior; missing usage is not
invented to make success pass.

Grader batches use a stable subject ordering. Each dispatched retry starts with
its exact previous grader-output file removed, so a later call cannot reuse
stale grades if it produces no new output. This does not remove unrelated files
or erase prior attempt evidence.

## Private source boundary

Both private source readers require an explicit `--source-root`:

- `interpretation_integrity_private_intake.py validate` uses it with
  `--source-file`, `--selection-file`, `--run-receipt` and `--receipt-name`.
- `interpretation_integrity_eval.py prepare-private-reconstruction` uses it with
  `--source`, `--selection`, `--derivation-manifest`, `--assignment`,
  `--run-receipt` and `--output-name`.

Python callers supply the corresponding `source_root=Path(...)` keyword. The
root must be narrower than the current operating-system account's home and the
selected source must be a `.jsonl` descendant. Changing `HOME` cannot change that
identity. Explicit roots within the account's `.codex/sessions` are supported;
credential locations and other hidden locations are excluded.

The reader holds directory descriptors from the approved root to the source,
rejects symlinks, unsafe ownership/write permissions and hard links, and checks
the source size before reading (64 MiB maximum). Selection/run-receipt checks
remain required. This source-root argument supplies a filesystem boundary; it
does not attest human consent or satisfy the experiment's private-data gates.

Private reconstruction validation uses the repository's canonical packet,
assignment and review schemas. Caller-supplied permissive schemas cannot replace
those checks. Required leakage checks, typed boolean coverage, screening,
independence and expiry checks must all be satisfied before a review receipt is
accepted. Private command errors omit input values and content.

## Verification

`python3 -B scripts/verify_repo.py` retains the repository and Azure runtime gates
and runs the two interpretation-integrity pytest modules. Its pytest availability
check uses the same Python interpreter as the test invocation. If that interpreter
lacks pytest, the gate fails explicitly; it does not silently skip these tests.

The GitHub Verify workflow supplies the declared test dependencies on Python 3.12.
The merge review used synthetic/direct production-path checks locally and the
actual pytest suite in GitHub CI because the host lacked pytest. No real source
sessions, private datasets or model/provider trials were used by that review.
