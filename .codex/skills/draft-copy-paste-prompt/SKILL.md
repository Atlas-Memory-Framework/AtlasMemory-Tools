---
# atlas-tools-generated: source=skills/draft-copy-paste-prompt/SKILL.md manifest=atlas-tools.v1 checksum=sha256:bf346bf614ab8b9ff053dd652f5efa4065b4c3716d64cde62c4ee72c453fb988
# atlas-tools-generated-end
name: draft-copy-paste-prompt
description: Draft concise copy-paste prompts for another Codex or agent session. Use when the user wants a short prompt they can paste into a fresh session to resume work, continue a handoff, review, build, fix CI, run local automation, or handle another scoped task.
---

# Draft Copy-Paste Prompt

## Goal

Draft a prompt the user can paste directly into another session. Optimize for clarity, brevity, and correct continuation from the current context. Adapt the prompt shape to the scenario instead of forcing one format everywhere.

## Use the prompt chooser

- If the user already named the scenario, match it directly.
- If not, infer the scenario from the most recent task context.
- If the target is still unclear, ask one short clarifying question.
- If the user wants example wording, read [examples.md](examples.md).

## Workflow

1. Identify the target action: resume, handoff, plan, review, build, fix CI, run local automation, or another specific task.
2. Extract only the context the receiving agent needs: repo or project, branch or PR if known, plan or handoff file, current state, constraints, and next concrete action.
3. State assumptions explicitly when context is missing. Do not invent file names, PR numbers, issue IDs, branches, or statuses.
4. Pick the best prompt shape for the task:
   - `handoff` for resume/continue/transfer work
   - `review` for critique, CI, or issue/PR diagnosis
   - `build` for implementation or repair work
   - `plan` for roadmap or design work
   - `automation` for local runtime, queue, or dispatch work
   - `custom` when the user has already defined a format
5. Draft the prompt in one fenced block so the user can copy it directly.
6. Keep it short by default: usually 3-8 sentences or 5-10 compact bullets. Expand only when the task is risky or the user asked for a detailed prompt.

## Prompt Shape

Use the closest matching structure below unless the user asks for a different format.

```text
You are working in <repo/path or project>. <One-sentence objective.>

Context:
- <Only essential current state>
- <Relevant files, branches, PRs, issues, plans, or handoff notes>
- <Important constraints or decisions>

Please <next concrete action>. Verify with <tests/checks if known>, and report what changed plus any blockers.
```

For very short requests, use a single paragraph instead of bullets.

### Handoff / Resume

Use when the user wants a continuation or context transfer.

```text
You are resuming work in <repo/path or project>. Continue from <handoff/plan/PR/issue reference>.

Context:
- <What is already true>
- <What has changed recently>
- <What is blocked or risky>

Please pick up from <next concrete action> and keep the result aligned with the existing decisions. Report the first blockers, then the next action.
```

### Review / CI Repair

Use when the user wants a review, debugging, or test-failure analysis.

```text
You are reviewing <repo/path or PR/branch>. Focus on the current failure or change set.

Context:
- <Relevant diffs, failing checks, logs, or comments>
- <Known constraints>

Please identify the highest-severity issues first, explain why they matter, and propose the smallest safe fix. Verify with <commands/tests> if available.
```

### Build / Implementation

Use when the user wants code, docs, or config changes made.

```text
You are implementing <task> in <repo/path or project>.

Context:
- <Relevant files and boundaries>
- <Current behavior>
- <Important constraints>

Please make the minimal correct change, update tests if needed, and report the files changed plus any remaining risks.
```

### Plan / Design

Use when the user wants a proposal, roadmap, or structured design prompt.

```text
You are helping plan <goal> in <repo/path or project>.

Context:
- <What exists now>
- <What should change>
- <Hard constraints>

Please identify the key decisions, risks, validation steps, and open questions. Keep the result decision-oriented and actionable.
```

### Automation / Local Runtime

Use when the user wants to operate a local agent loop, queue, or runtime.

```text
You are operating <runtime/workflow> in <repo/path or project>.

Context:
- <Current queue/state>
- <Relevant configs, jobs, or run artifacts>
- <Safety boundaries>

Please continue with the next safe automation step, stop on blockers, and report any actions that would require human approval.
```

## Content Rules

- Prefer imperative, task-oriented wording over explanation.
- Preserve the user's intended workflow. Do not turn a handoff prompt into a plan prompt unless asked.
- Include exact paths and command names when already known from the conversation or workspace.
- Include safety boundaries for automation: respect dependencies, do not merge, publish, or delete unless explicitly instructed, and stop on unclear blockers.
- If the prompt is for a fresh agent, include where to read first, such as a handoff note, plan artifact, issue body, PR comments, or failing check logs.
- If the user says "copy paste prompt" without a target, infer the target from the most recent task context.
- If the target is still ambiguous after inference, ask one short clarifying question instead of inventing a scenario.

## Output

Return only a brief lead-in plus the fenced prompt. Avoid long explanation after the prompt unless the user asks for rationale.
