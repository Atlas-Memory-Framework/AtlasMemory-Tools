---
# atlas-tools-generated: source=skills/checkpoint/SKILL.md manifest=atlas-tools.v1 checksum=sha256:80bba9b8a014abc2ff7f174fbaf39b663f915b9beefc43cf59b983e3ba7cdd88
# atlas-tools-generated-end
name: checkpoint
description: Save or update durable work state when the user asks to record progress, remember an open item, log a decision, track where work is happening, or wrap up a session. Maintains a work index, change log, and systems map with source links and concrete resume actions.
---

# Checkpoint

Preserve enough state that the next session can identify unfinished commitments and continue without rereading the conversation.

## Locate the record

Read [the work-record contract](references/work-records.md) before writing. Reuse established records and task authorities. If no local convention exists, use `.work/index.md`, `.work/log.md`, and `.work/systems.md` in the current project. A request to save a checkpoint authorizes these local records; do not add an approval step for ordinary reversible recording.

For first use, adapt the [index](assets/index.md), [log](assets/log.md), and [systems map](assets/systems.md) templates. Create only missing files; never copy a blank template over existing work. Remove template comments and generated adapter headers from live records. Fill scope and timestamps from actual context and mark unknown information explicitly.

## Capture changes

1. Inspect the relevant conversation and durable evidence: existing entries, task links, files, repository status, verification results, and known work systems. A checkpoint covers this session's known work unless the user asks for a broader reconciliation.
2. Update existing entries by canonical link or stable ID. Record newly authorized commitments separately from suggested ideas. Preserve unrelated entries, ownership, deferrals, and unresolved blockers. Record decisions with their reason and source.
3. For each unfinished commitment, capture its next concrete action and where to perform it. For waiting work, identify what or whom it is waiting on and the follow-up date or event if known. Leave unknown owners and dates unknown.
4. Add or refresh systems actually used for the work: purpose, project, location, authoritative information, access method, and last check. Store references, never credentials. A system's presence in this map does not mean it is accessible or active now.
5. Append a dated log entry describing meaningful changes, evidence, decisions, and the stopping point. Update the index and systems map to match the evidence. A repeated checkpoint with no new information should not create duplicate tasks or events; a new verification can be logged as such.
6. Re-read the touched records and verify consistency, links, IDs, and preservation of other work. If another writer changed the files since inspection, merge its changes before writing. If recording partially fails, identify exactly which files were saved and what remains inconsistent; do not report a complete checkpoint.

## Boundaries

- A local record does not update GitHub, a board, a runtime, or another external system. Keep its authoritative status separate from local notes; use existing authorization and tools for any separately requested external update.
- Completion needs evidence appropriate to the task. Preserve “user reports complete” as a sourced claim when it is not independently checked; do not silently turn it into verified completion.
- Do not start, stop, commit, publish, send messages, or schedule work merely because a checkpoint mentions it.
- Use `handoff` when the user needs a detailed transfer to another agent. Link that handoff from the work entry and keep a single task identity rather than maintaining another independent backlog.

## Report the result

Link the saved records. Briefly say what changed, what remains open, and the first resume action with its owner and location. Make the disposition explicit: user action, agent continuation, waiting, or no action needed. Separate any unsaved or unverified state from successfully recorded state.
