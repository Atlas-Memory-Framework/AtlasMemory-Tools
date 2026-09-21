---
# atlas-tools-generated: source=skills/start-day/SKILL.md manifest=atlas-tools.v1 checksum=sha256:2db09f8e5bf308991b8af2411195f62ecdd671326cf62c3dde5434185b54c47b
# atlas-tools-generated-end
name: start-day
description: Prepare a short starting brief and suggested priorities when the user begins a workday, returns after a break, or asks what to focus on with limited time. Combines current work state with concrete next actions without scheduling or starting tasks.
---

# Start Day

Help the user start useful work within minutes.

## Refresh the relevant state

Use [current-state](../current-state/SKILL.md) to reconstruct work from the existing records and relevant sources. Respect its scope, evidence, and read-only behavior. When records are missing, use available context and clearly state that coverage is provisional; do not require setup before giving a useful starting point.

Use the user's stated time, priorities, deadlines, and constraints. Check a calendar or external task system only when relevant, in scope, and accessible through existing tools. Do not assume calendar access or treat an unchecked source as empty.

## Pick a manageable starting set

Suggest up to three priorities, fewer if the available time or evidence supports fewer. Use real deadlines, dependencies, and user goals to explain ordering. Separate items that need the user from work an agent could perform and work waiting on others.

Make the first action concrete using [action-plan](../action-plan/SKILL.md): who acts, where, and what result finishes the step. Prefer an actionable unblocker when otherwise valuable work is waiting. Do not reactivate deferred work unless its trigger is met or the user changes priorities.

If time is supplied but durations are unknown, choose a bounded first step and label any estimate as tentative. If no time budget is supplied, give an ordered starting set without fabricating a daily schedule. Ask about availability only when it materially changes the recommendation and no useful default exists.

## Deliver one brief

Combine the results into one short response rather than printing separate skill reports:

- Recommended first move and why it matters now.
- Up to three priorities with the relevant task links and completion conditions.
- Decisions, blockers, and waiting items that affect those priorities.
- Checked scope, freshness, and material gaps.

If nothing actionable is established, say so within the checked scope and identify a useful information-gathering step only when needed.

These are suggested priorities, not newly adopted commitments. Starting the day does not itself write records, send reminders, change calendars, dispatch agents, or execute tasks. If the user also asks to save or execute the selected work, continue the authorized portion and use `checkpoint` for recording. This skill runs on request; it does not configure a computer-startup trigger.
