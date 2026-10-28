<!-- atlas-tools-generated: source=skills/plain-technical-english/references/examples.md manifest=atlas-tools.v1 checksum=sha256:baced4d37d395b35c9a31538da284d4cc1c7bb95af26d28fca4d09aea906bb0c -->
<!-- atlas-tools-generated-end -->
# Review examples

These examples show differences in meaning. They are not word substitutions to apply automatically.

## Name the result and storage boundary

Before:

“The durability lane is qualified at the evidence surface, pending substrate assimilation.”

After:

“The worker result is saved in a local JSON file. Atlas has not imported it into its database. The result-storage worker must implement that import before we can claim Atlas retains worker results.”

Why: The revision identifies what exists, where it exists, who acts next, and what claim remains unsupported. Use this wording only if those facts and that owner are verified.

## Preserve the condition and its reason

Before:

“Dispatch proceeds when the approval envelope resolves.”

After:

“The coordinator starts the worker after it finds approval for this work item and the current plan version. If either is missing, it leaves the work item blocked. This prevents an old approval from authorizing changed work.”

Why: The revision explains the trigger, action, failure behavior, and reason. If the actual implementation checks different conditions, describe those conditions instead.

## Explain a necessary technical term

Before:

“Make delivery idempotent across the replay boundary.”

After:

“The importer must be idempotent: importing the same worker result twice must create only one Atlas record. The coordinator may retry after a timeout even when the first import succeeded, so the importer uses the result ID to detect duplicates.”

Why: “Idempotent” is useful. Removing it would lose the standard name for the behavior. The explanation connects that behavior to a real retry case.

## Brevity can hide the entire problem

Before:

“Done. Stored. Safe.”

After:

“The backup archive is complete on this machine. No remote copy has been verified. The recovery worker must upload the archive and compare its checksum before reporting a remote backup.”

Why: Three short words do not explain location, evidence, responsibility, or the remaining condition. The longer passage does. It must not imply that an upload happened without evidence.

## Keep uncertainty and test scope

Before:

“The test passed, so unattended dispatch works.”

After:

“The fixture test passed: the coordinator selected the next eligible work item. We have not tested a real worker launch. The runtime worker must run that test before we can say unattended dispatch works.”

Why: The revision preserves exactly what was tested and what remains unproven. A writing review cannot promote a fixture result into a production claim.

## A longer technical explanation can pass

“The importer writes the Atlas record and its result ID in one Postgres transaction, meaning both writes succeed or neither does. If the coordinator times out after the transaction commits, it can retry with the same result ID. The importer then returns the existing record instead of creating a duplicate. This handles a lost response without requiring the coordinator to know whether the first request committed.”

Why: This paragraph explains an actor, target, condition, causal chain, and necessary term. Do not shorten it merely to meet a sentence-length score. Confirm the database behavior against implementation evidence before using it as a factual report.

## Keep protected spans intact

Suppose a report contains a code identifier `source_sha256`, the exact command `python3 check_review.py check report.md review.json`, or this quoted error:

> lease nonce must be hexadecimal

Explain what they mean in surrounding prose. Do not rename the field, edit the command, or improve the quoted error as part of a readability pass. Changing the original source requires a separately justified technical change.
