---
# atlas-tools-generated: source=skills/action-plan/SKILL.md manifest=atlas-tools.v1 checksum=sha256:824041b8170e68f4cd7e77cffee2a9d165bd46b4901667506421c6276641e0fd
# atlas-tools-generated-end
name: action-plan
description: Turn an agent response, review, or work situation into a short ordered set of concrete next actions when the user asks what to do with it, what happens next, or how to proceed. Clarifies ownership, decisions, locations, and completion criteria without invoking a full technical planning workflow.
---

# Action Plan

Make the next move obvious. Scale the output to the problem: one useful action is sufficient when one action resolves it.

## Interpret the result

- Read the response or artifact the user is referring to. Use available context to resolve it; ask a narrow question only if the missing referent materially changes the answer.
- Explain the practical result in plain language, including what is done and what remains uncertain. Distinguish completed actions, recommendations, actual commitments, and decisions that still belong to the user.
- When existing tasks or saved state matter, use their source links and the [work-record contract](../checkpoint/references/work-records.md). Do not create a parallel backlog. For a local response that needs no tracking, no work records are required.

## Choose the next actions

Order actions by dependencies and the user's priorities. For each actionable step, provide:

- **Who:** the user, this agent, a named owner from evidence, or owner unknown. Do not assign every remaining task to the user.
- **Do what and where:** a concrete action with the relevant file, page, system, or copy-paste instruction when useful. Verify commands against the known environment before recommending them.
- **Done when:** an observable result that closes the step.
- **Depends on:** a blocking decision or prerequisite, only when relevant.

Recommend one first action and explain why it comes first. Keep immediate actions separate from later possibilities. Do not manufacture urgency, estimates, or deadlines; use them only when supplied or clearly labeled as assumptions.

For a decision, name the choice, viable options, recommendation, and consequence. For waiting work, name the dependency and next check trigger. If no action is needed, say so rather than inventing a task.

## Deliver and route

Lead with a short disposition such as “Ready for your review,” “The next step is for the agent,” “Waiting on the linked dependency,” or “No action needed.” Follow with the smallest useful list or table of actions.

Producing an action plan does not itself execute or persist it. If the user has already authorized implementation or recording, continue that work within scope without asking for the same permission again. Use `checkpoint` for requested persistence. Use the available technical planning workflow only when the underlying implementation actually needs it; ordinary next-step clarification must stay lightweight.

For substantial results, make clear what happened, what needs the user's attention (if anything), and exactly how to continue. Do not end with a generic offer or send the user to a document without explaining what they need to do there.
