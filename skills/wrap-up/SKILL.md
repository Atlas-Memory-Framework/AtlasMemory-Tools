---
name: wrap-up
description: Close a work session by saving progress, unresolved items, decisions, and a clear restart point when the user says they are done for now, switching tasks, or ending the day. Uses the existing checkpoint records and identifies any ongoing work that still needs attention.
---

# Wrap Up

Leave a dependable stopping point so the user can return without reconstructing the session.

## Account for the session

Use the conversation, current artifacts, existing records, and relevant checks to identify what changed, what was completed, what remains unfinished, and what decisions were actually made. Preserve proposals as proposals and distinguish reported completion from verification.

Check known agents or jobs only when they are relevant to stopping. Report whether they are running, stopped, completed, or unverified, with the observation time and source. A session ending does not prove background work has stopped. Do not scan for unrelated processes.

## Save one checkpoint

Apply [checkpoint](../checkpoint/SKILL.md), including [its shared record contract](../checkpoint/references/work-records.md), to update the work index, append meaningful changes, and record known systems. “Wrap up this session” authorizes that local save. Preserve unrelated tasks and prior history; repeated wrap-ups without changes should not duplicate entries.

Capture the exact stopping point and one first resume action, with owner, location, and completion condition. For unfinished work, keep blockers, waiting dependencies, known follow-up triggers, and relevant uncommitted changes visible. Do not imply that a checkpoint is a commit, remote backup, or published result.

When the user is transferring work to another agent and execution details are needed, also use the available `handoff` skill and link the result from the existing work entry. An ordinary end-of-day save does not require another handoff document.

## Close clearly

Give a short response with links to the saved records, material progress, remaining open work, any ongoing jobs needing attention, and the first action for next time. Separate successfully saved state from any partial failure or unverified state.

Do not automatically stop jobs, merge changes, commit, publish, or send messages. If the user explicitly requests such an action, handle it within the existing authorization and relevant workflow. If known ongoing work may require a decision before the user leaves, explain that concrete decision rather than silently taking it. Saving the session does not schedule tomorrow's work or change an active goal's status on its own.
