# AtlasMemory Cursor Tools

Reusable Cursor skills, agents, and local automation templates for planning and implementation.

Most of this repo lives in `.cursor/skills/` and `.cursor/agents/`.
The host-side local Codex automation template lives in `templates/local-automation-runtime/`.

## Install

Copy `.cursor/` into the repo where you want to use these tools.

## Quick Start

1. Run `/plan` with your feature idea (1-5 bullets).
2. Keep going with the agent until the plan is complete.
*Note: If context gets compressed, agent may forget the /plan skill and lose SSOT on the plan - just remind it.*
3. Optional: Rerun with /plan for a more thorough analysis, tell it to focus on certain areas (technical, security), or some problem you know about related to the plan.
4. Run `/implement` with plan file to execute the approved implementation plan.
5. Run `/plan-to-issues` when an approved plan should be turned into GitHub-ready issue drafts.

That is the core loop.

## How `/plan` works (simple version)

- `/plan` always works on one plan document (SSOT).
- If you reference a plan file with `@path`, that file is used.
- If you do not reference a plan, `/plan` creates a new one.
- Stages are: Problem -> Feature -> Technical -> Implementation -> Reviews.

For full details, see `.cursor/skills/plan/README.md`.

## Tips and Tricks

- Keep prompts short: goal + constraints is usually enough.
- When resuming work, reference the plan explicitly with `@path`.
- If you change scope significantly, run `/plan` again before `/build`.
- For faster dev-only work, use lighter rigor; for shared/prod work, use fuller reviews.
- Treat review outputs as stale after material plan edits; refresh them.
- If stuck, ask for one focused pass (for example: "security/privacy review only").

## Repo Layout

- `.cursor/skills/`: planning and implementation skills (`plan`, `plan-to-issues`, `implement`, `review`, etc.)
- `.cursor/agents/`: specialist and reviewer agents
- `templates/local-automation-runtime/`: reusable local issue-to-PR automation runtime
- `specs/`: framework and skill specs

## Visual

![AtlasMemory Cursor Skills & Agents](./atlasmemory-cursor-skills-agents.png)
