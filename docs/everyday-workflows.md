# Everyday Workflows

Use these skills to preserve unfinished work across sessions and make the next action clear.

| When | Request | Result |
| --- | --- | --- |
| Starting the day | `$start-day` I have an hour. What should I focus on? | Up to three suggested priorities, one first action, and the blockers or gaps that matter. |
| Returning to work | `$current-state` What is open in this project, and where should I start? | A short briefing with source links, freshness, coverage gaps, and the first useful action. |
| Saving at any point | `$checkpoint` Save what changed, what is still open, and where to resume. | Updated work index, a dated change log, and known work systems. |
| Finishing or switching context | `$wrap-up` I'm done for now. Save where we are. | One checkpoint, remaining work, relevant ongoing jobs, and the first action for next time. |
| Receiving a confusing answer | `$action-plan` What do I do with this response? | Ordered actions identifying who acts, where, and what counts as done. |
| Remembering an item | `$track-work` Record that the navigation review is waiting for preview access. | An update to the existing item or a new local commitment when needed. |
| Finding where work happens | `$systems-map` Which systems own this project's tasks and execution? | A map of work locations, authority, access routes, and last observations. |
| Recording another work system | `$systems-map` Record this board as the task authority for this project. | A saved map entry with its purpose, location, authority, and known access method. |
| Reviewing loose ends | `$review-open-loops` What commitments or follow-ups are slipping through the cracks? | Evidence-backed findings with proposed actions, decisions, deferrals, or closure. |
| Understanding a choice | `$decision-brief` Explain these options and recommend what I should choose. | The actual decision, viable options, tradeoffs, recommendation, and consequences. |

The skills are registered in the toolkit manifest and included by the existing harness installer. Install them as part of the toolkit so their shared references are available. No new dependencies or services are required.

## Where work is saved

An existing user-selected or project-documented location wins. Otherwise `checkpoint` creates these project-local records when invoked:

```text
.work/
  index.md     Open and closed work, owners, next actions, and evidence
  log.md       Dated changes, decisions, and stopping points
  systems.md   Where work lives, what each system owns, and last observations
```

The canonical format is [the work-record contract](../skills/checkpoint/references/work-records.md). Starter assets ship with `checkpoint`; live records belong to the target project, outside the installed skills. Saving a record does not commit or publish it.

Existing issue trackers remain authoritative for their tasks. The local index holds their links and observed status, with timestamps. Work with no existing task can be tracked locally. Agent suggestions stay proposals until adopted. Unknown ownership, dates, and access remain explicit.

`current-state` and `start-day` read available evidence without changing records or starting work. `action-plan` and `decision-brief` propose next steps or choices without automatically saving or executing them. `review-open-loops` is read-only unless cleanup is requested; unresolved choices stay pending even during cleanup.

`track-work` and `systems-map` inspect by default and save when a change is requested. `checkpoint` and `wrap-up` save the session's known state. All writers reuse the checkpoint procedure; a combined workflow makes one coherent record update rather than duplicating tasks and events. A request that already authorizes recording or execution can combine those operations without another confirmation step.

For a lightweight daily routine, use `$start-day` when returning, `$track-work` to capture or update a particular item, and `$wrap-up` when stopping. Run `$review-open-loops` when you want a broader review. These are manual entry points; invoking them does not configure a schedule.

## What a useful response contains

The everyday skills and handoff workflow make these points explicit in substantial results:

- What happened or what is currently known.
- What needs the user's attention, if anything.
- The next action, its owner, its location, and the expected result.
- Anything unverified or inaccessible that could change that action.

For example: “The export fix is recorded as accepted in the task snapshot. Your navigation review is waiting for preview access. Next, have the preview owner provide a working link; the review can start once you can open it.”

This response convention is part of these skill instructions; installing them does not rewrite every unrelated agent's global response policy.

## Scope and limits

The default scope is the current project. A requested multi-project view uses an existing registry or supplied project links, within the current business identity. Missing or inaccessible sources appear as coverage gaps. An old heartbeat or saved agent session is not evidence that work is still running.

For a detailed transfer to another agent, use `handoff` and link it from the relevant work entry. The existing technical `plan` workflow remains appropriate for implementation design; `action-plan` handles everyday next-step clarity.

All nine everyday skills ship through the manifest: `current-state`, `checkpoint`, `action-plan`, `track-work`, `systems-map`, `start-day`, `wrap-up`, `review-open-loops`, and `decision-brief`. There is no automatic computer-startup trigger, cross-system synchronization, or background scheduling. A saved follow-up date does not create a notification, and a decision recommendation does not adopt or execute that option.
