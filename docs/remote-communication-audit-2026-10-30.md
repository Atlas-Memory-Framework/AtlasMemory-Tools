# Remote communication and rate-limit audit

Scope: AtlasMemory-Tools runtime coordination, GitHub comment traffic, and cloud
presentation. This audit concerns external tooling, not Atlas product execution.
The user reported previous API rate limits while GitHub comments carried agent
communications. No original incident log or API-rate receipt was supplied in this
review, so the historical incident's exact cause and request count remain
unverified.

## Findings

The source contains concrete mechanisms that can amplify comment traffic:

- `atlas-agent-worker` fetched issue comments as worker context and posted an
  issue comment for completion, dry-run and failure, despite already writing
  local issue, prompt, result and error artifacts. These are worker-to-operator
  messages that do not need a remote issue-comment transport.
- `atlas-agent-review` fetched PR comments alongside each PR view. It fetched
  the comment thread again before publishing its review, then patched an
  existing review summary even when the body was unchanged. Failed-workflow
  summaries repeated the same pattern for the same head.
- Local/deployed validation and semantic-review compatibility gates use
  current-head comment markers. Removing publication without preserving that
  distinction would leave missing evidence; accepting labels alone would weaken
  the gate. Finalization remains outside the new MCP execution lane.
- Triage and repair can also read comments. Workstream review consumes child
  completion comments. These remain identifiable legacy provider workflows,
  rather than a reason to move local queue messages back into cloud comments.
- `atlas_agent_common.py` already shares GitHub pacing/backoff state across
  processes through `AGENT_JOBS/github-api-throttle`. Pacing reduces bursts but
  does not eliminate repeated calls or make comment communication free.

The maintained local JSON queue, supervised handoff reservations, original role
result bytes, host receipts, workflow rollups and runtime status files already
provide durable coordination. This change does not introduce another message
bus or treat a remote summary as the source of task acceptance.

## Implemented policy

`atlas-agent-unattended --remote-comments POLICY` selects and propagates
`AGENT_REMOTE_COMMENTS` to its children:

| Policy | Comment behavior |
| --- | --- |
| `local` | Keep coordination in local artifacts. Remove comment fields from GH JSON reads, avoid comment-only network reads, reject comment writes before transport/logging, and refuse comment-only acceptance evidence. PR creation, native checks, labels and other selected cloud operations remain available. |
| `cloud-review` | Keep worker issue messages local. Allow deliberately selected PR-facing summaries and cloud review context. Repeated identical successful summaries need no new comment read or write. |
| `legacy` | Preserve existing issue-to-PR compatibility for explicitly selected old installations. |

The CLI default remains `legacy` to preserve existing installation behavior.
The MCP GitHub proposal selects `local` explicitly and does not expose a user
option to silently restore the old communications path. The separate local
supervised lane still owns its own task dispatch and acceptance; a comment-free
GitHub cycle is not a replacement implementation of that lane.

Suppressed writes return a nonzero policy result, not a successful publication.
Known worker messages still write `comment.md` locally. Comment-only reads
provide no evidence and make no API call. PR fields such as head SHA and check
results still come from real cloud reads. Local policy refuses cached or injected
comment marker bodies as acceptance evidence as well as avoiding their fetch.

PR review summaries now carry the observed head SHA. Successful cloud summary
receipts store only a material-body hash and publication time in private local
runtime state. Same-body observations skip the entire fetch/patch path. Existing
identical remote summaries also skip PATCH. Changed head, decision or evidence
can publish a changed summary. Failed-workflow comparison excludes only the
local artifact-path line so an internal directory name does not create another
remote update. Failed publications are not cached as success. This cache reduces
repeated publications; it is not an exactly-once delivery or remote-authentication
claim.

## Evidence and limits

Focused offline tests prove no comment subprocess/API invocation in local mode,
no blocked-body logging, removal of comment fields, preservation of ordinary PR
and check operations, retained local worker results, failed-closed comment-only
gates, identical-summary deduplication, head-change invalidation, failure retry
state, and preserved explicit legacy behavior. Regression checks cover existing
review, unattended, finalizer and local-agent behavior. All provider calls in
these checks are mocked; no real comment or other cloud write was made.

Remote task inspection, PR creation, checks, review context and Board operations
still consume provider APIs. Existing throttle/backoff stays enabled and is not
replaced by this policy. Cloud-review/legacy validation compatibility still uses
remote comment attestations when deliberately selected. Under local policy,
missing native checks or required independent evidence remains a blocker rather
than an inferred pass. Azure and other connectors must retain the same separation:
local task/result coordination, explicit cloud operations, and independent
acceptance.
