---
name: current-state
description: Reconstruct active work, blockers, pending decisions, and the next useful action when the user asks where things stand, what is open, or where to resume. Produces an orientation without changing task records or starting work.
---

# Current State

Help the user start or resume work without reconstructing previous conversations. Lead with what needs attention and one concrete next move.

## Establish coverage

- Default to the current project. Use a broader scope only when requested or already established; use its registered project and system links rather than scanning unrelated directories or accounts.
- Read the project's existing work records. For the shared `.work/` convention, read [the work-record contract](../checkpoint/references/work-records.md). Respect an established alternative location or task system.
- If records are absent, reconstruct a provisional view from available conversation, relevant handoffs, plans, and repository state. Say which sources were checked. Missing records do not mean there is no work.
- Inspect only the sources needed to orient the user. Use available read-only tools to check linked tasks, PRs, or runtime status. Do not install integrations, start jobs, or request credentials to fill a coverage gap.

## Reconcile before summarizing

1. Separate active commitments, proposed ideas, decisions, waiting items, and completed work. Deduplicate by authoritative task link or stable local ID.
2. Prefer the current authoritative source over cached summaries. Keep conflicting evidence visible when authority or timing is unclear. Preserve the original observation time for sources that could not be refreshed.
3. Distinguish reported progress from verified completion. A saved runtime path or old heartbeat does not establish that an agent is still running; report its last observed state and time.
4. Identify the next unblocked action. Explain priority using the user's goals, known deadlines, dependencies, or available time; label recommendations and inferred urgency. Do not invent due dates or commitments.

## Present a usable briefing

Keep the initial briefing short enough to act on immediately. Include:

- Scope, checked-at time with timezone, and meaningful coverage gaps.
- The recommended first action, its owner if known, and a direct file or system link.
- Active work and material changes since the last checkpoint, if a comparison is available.
- Decisions requiring the user, blockers, and waiting items with their next check date or trigger when known.
- Stale, conflicting, or unverified information that could change the recommendation.

Group by what the user can do: act, decide, review, or wait. Do not dump the full backlog unless requested. If nothing requires attention, say so within the checked scope.

End with an explicit disposition: what the user needs to do, what the agent can do next, or that no action is needed. Give an exact next move rather than “review the plan.”

This workflow is read-only. If the request also asks to save or update state, use the available `checkpoint` workflow for that part. Otherwise surface corrections in the briefing without silently changing records.
