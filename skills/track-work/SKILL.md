---
name: track-work
description: Capture, find, update, defer, or close tasks and follow-ups when the user asks to track work or remember a commitment. Maintains existing task identities and distinguishes ideas from commitments; use checkpoint for a whole-session progress record.
---

# Track Work

Make a commitment retrievable and actionable without creating a competing task list.

## Find the item

Read [the shared work-record contract](../checkpoint/references/work-records.md). Resolve the project's existing index and task authorities before making changes. Match an existing item by canonical link or stable ID, then by outcome and context; a renamed task keeps its identity. Ask only when multiple plausible targets would cause the wrong update.

For a request to list or find work, report the matching entries and coverage without writing. For an explicit capture or update request, maintain the local index and log using [checkpoint](../checkpoint/SKILL.md), which also provides templates for first use. A bare invocation with no task or change should show known work and the most useful next move rather than inventing an item.

## Apply the requested change

- **Capture:** record the intended outcome, known owner, authority, status, source, and concrete next action. “Track this task” establishes a commitment; “save this idea” establishes a proposal. Neither authorizes executing it. Keep dates and ownership unknown unless established.
- **Update:** change the matching entry and record why. Preserve unrelated fields, decisions, and work. When a local item gains an external task, attach its canonical link to the same local ID.
- **Wait or block:** record the dependency and the next check date or event when known. A follow-up date is a recorded intention, not a scheduled notification or permission to contact anyone.
- **Defer:** retain the item, reason, and revisit trigger if known. Deferral is not cancellation.
- **Close or cancel:** retain history and the basis for the disposition. Attribute a user-reported completion to the user unless independently verified. For external tasks, distinguish a local completion report from the external task's current status; closing the local record does not close the issue.

Do not infer closure from silence, age, disappearance from one query, or another task's completion. Do not turn recommendations into commitments without adoption. An identical repeated request should not create another task or log event.

## Return something usable

For a mutation, link the saved entry and briefly state the change, remaining blocker, and exact next action with its owner. For a list, separate actionable work, waiting work, and proposals when that helps the user choose.

State whether an external system was actually updated or only the local record changed. External edits and task execution require authorization for those actions; existing authorization remains valid and should not be requested again. Report partial saves or unverified status explicitly.
