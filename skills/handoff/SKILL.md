---
name: handoff
description: Create, resume from, or update focused handoff notes for AI coding sessions. Use when the user asks to hand off, save state, pause, resume from previous work, switch agents/tools, split out a side task, preserve decisions before context gets stale, or after substantial implementation/debugging/planning work that another fresh agent may need to continue.
---

# Handoff

Create a compact, actionable context transfer so a fresh agent can continue work without re-reading the whole conversation or trusting stale memory.

For a short everyday progress record or task reminder, use the available `checkpoint` skill. Use this skill when a receiving agent needs execution context, verification details, and resume instructions. For orientation without resuming execution, use `current-state` when available.

If the project already has a work index, preserve its stable task IDs and authoritative links. When saving a handoff as part of a requested checkpoint, link it from the corresponding work entry rather than creating an independent task list. A handoff is evidence from its creation time, not proof of current task or runtime status.

## Modes

- **Create**: user asks for a handoff, save state, pause, context transfer, or a side-task prompt.
- **Resume**: user asks to resume from a handoff, load saved context, continue previous work, or references a handoff file.
- **Update**: current work extends an existing handoff and the next agent needs the newest state.

For every **Create** or **Update**, the required user-facing deliverable is a paste-ready prompt for the receiving session. Follow the output and brevity rules in the available `draft-copy-paste-prompt` skill; do not silently substitute a saved handoff note, a status summary, or an offer to draft the prompt later. A durable handoff note is an additional artifact when the user asks to save/preserve state or the work needs a persistent record. When one is created, the prompt must point the next agent to that exact note and its first action. If no note is needed, make the prompt self-contained from inspected project state. Do not create a prompt in **Resume** mode unless the user asks to hand work onward again.

## Create Workflow

1. Identify the receiving session's purpose. If it is unclear and affects scope, ask one concise question; otherwise infer it from the active task.
2. Inspect durable state before writing: current directory, git branch/status, changed files, recent commits when useful, relevant plan/issues/PRs, and files already known to matter.
3. If a persistent record is requested or needed, write the smallest useful handoff:
   - For durable project continuity, save to `.codex/handoffs/YYYY-MM-DD-HHMM-[slug].md`.
   - For a disposable handoff artifact or side quest, use `/tmp/YYYY-MM-DD-HHMM-[slug]-handoff.md` unless the user asks to keep it in the repo.
4. Draft the receiving-session prompt as the primary deliverable. Make it directly pasteable, include the exact repo/path and first concrete action, and link any durable note created above. Follow `draft-copy-paste-prompt`'s output rules; include the prompt in the response rather than only saving it to a file.
5. Redact secrets, tokens, credentials, private keys, and unnecessary personal data from both artifacts.
6. Validate manually: no unresolved placeholders, referenced local files exist, next steps are concrete, and decisions include rationale. Tell the user where any durable note was saved and whether the receiving agent can proceed or is waiting on a dependency.

## Resume Workflow

1. Read the handoff fully before editing.
2. Verify staleness against durable state: current branch, git status, recent commits after the handoff, missing files, and whether blockers/assumptions still hold.
3. If the handoff links a predecessor, read only the older handoff sections needed to resolve ambiguity.
4. Start from the first actionable next step unless the user redirects.
5. If work diverges materially, update the handoff or create a chained successor.
6. If the user asks to transfer the resumed work onward, use the Create/Update requirement above and include a new paste-ready prompt.

## What To Capture

Always include:

- Current goal, phase, and exact stopping point.
- Decisions made and why they were made.
- Files changed or important files to review, with paths and brief purpose.
- Tests/checks run, including failures and what remains unverified.
- Open questions, blockers, and assumptions that may be wrong.
- Immediate next steps, ordered so the first step is obvious.
- User preferences, constraints, or project rules that are not obvious from code.

Include when relevant:

- Dead ends already tried, with enough detail to avoid repetition.
- External artifacts to inspect: issues, PRs, plans, docs, logs, screenshots.
- Suggested skills/tools for the receiving session.
- A "do not do" note for tempting but rejected approaches.

Skip:

- Verbose tool output, pasted diffs, full file contents, and raw conversation history.
- Information already available in a linked plan, issue, PR, or source file.
- Speculation that is not tied to an action or verification step.

## Recommended Structure

```markdown
# Handoff: [specific task]

**Created:** YYYY-MM-DD HH:MM UTC
**Project:** /absolute/project/path
**Branch:** branch-name
**Purpose for next session:** [what the next agent should accomplish]
**Continues from:** [path or none]

## Current State
[Goal, phase, stopping point, and status.]

## Decisions
- **[Decision]**: [rationale and tradeoff]

## Changed or Important Files
- `path/to/file.ext`: [what changed or why to inspect]

## Verification
- [command/check]: [pass/fail/not run and why]

## Open Questions and Blockers
- [ ] [question/blocker, owner or suggested resolution]

## Next Steps
1. [first concrete action]
2. [second concrete action]
3. [third concrete action]

## Context Notes
[Constraints, user preferences, gotchas, rejected approaches.]
```

## Quality Bar

A good handoff is compressed, pointed, and falsifiable. The receiving agent should know what to read, what to trust, what to verify, and what to do first. Prefer durable pointers over duplicated content, and treat the handoff as a working artifact that may go stale.
