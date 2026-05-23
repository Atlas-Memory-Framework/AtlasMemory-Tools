---
name: handoff
description: Create, resume from, or update focused handoff notes for AI coding sessions. Use when the user asks to hand off, save state, pause, resume from previous work, switch agents/tools, split out a side task, preserve decisions before context gets stale, or after substantial implementation/debugging/planning work that another fresh agent may need to continue.
---

# Handoff

Create a compact, actionable context transfer so a fresh agent can continue work without re-reading the whole conversation or trusting stale memory.

## Modes

- **Create**: user asks for a handoff, save state, pause, context transfer, or a side-task prompt.
- **Resume**: user asks to resume from a handoff, load saved context, continue previous work, or references a handoff file.
- **Update**: current work extends an existing handoff and the next agent needs the newest state.

## Create Workflow

1. Identify the receiving session's purpose. If it is unclear and affects scope, ask one concise question; otherwise infer it from the active task.
2. Inspect durable state before writing: current directory, git branch/status, changed files, recent commits when useful, relevant plan/issues/PRs, and files already known to matter.
3. Write the smallest useful handoff:
   - For durable project continuity, save to `.codex/handoffs/YYYY-MM-DD-HHMM-[slug].md`.
   - For disposable cross-agent prompts or side quests, use `/tmp/YYYY-MM-DD-HHMM-[slug]-handoff.md` unless the user asks to keep it in the repo.
4. Redact secrets, tokens, credentials, private keys, and unnecessary personal data.
5. Validate manually before finalizing: no unresolved placeholders, referenced files exist when local, next steps are concrete, and decisions include rationale.
6. Tell the user the handoff path, what it captures, and the first next action.

## Resume Workflow

1. Read the handoff fully before editing.
2. Verify staleness against durable state: current branch, git status, recent commits after the handoff, missing files, and whether blockers/assumptions still hold.
3. If the handoff links a predecessor, read only the older handoff sections needed to resolve ambiguity.
4. Start from the first actionable next step unless the user redirects.
5. If work diverges materially, update the handoff or create a chained successor.

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
