<!-- atlas-tools-generated: source=skills/draft-copy-paste-prompt/examples.md manifest=atlas-tools.v1 checksum=sha256:55b9752dadcc431e5e294bf2204ae7b7d31084385684ea20b0e2f5a6c962b470 -->
<!-- atlas-tools-generated-end -->
# Examples

Use these as starting points and trim them to the smallest useful prompt.

## Handoff / Resume

```text
You are resuming work in /var/home/mat/Desktop/AtlasMemory-Tools. Continue from the latest handoff in .codex/handoffs.

Context:
- The repo is the source of truth for skills, agents, and runtime templates.
- The current task is to update a Codex skill and regenerate the global install.
- Avoid touching unrelated worktree changes.

Please update the requested skill, reinstall the generated harness if needed, and report the files changed plus any verification still pending.
```

## Review / CI Repair

```text
You are reviewing the failing change set in /var/home/mat/Desktop/AtlasMemory-Tools.

Context:
- Focus on the current diffs and the failing verification output.
- Treat unrelated worktree changes as out of scope.

Please identify the highest-severity issues first, explain why they matter, and propose the smallest safe fix. Verify with the most relevant test or check.
```

## Build / Implementation

```text
You are implementing the requested change in /var/home/mat/Desktop/AtlasMemory-Tools.

Context:
- Update the targeted skill source, then regenerate the generated copy.
- Preserve unrelated files and keep the change minimal.

Please make the edit, update any associated metadata, reinstall the generated harness, and report the changed files plus verification results.
```

## Plan / Design

```text
You are helping plan the next step for /var/home/mat/Desktop/AtlasMemory-Tools.

Context:
- The request is to improve an existing prompt-writing skill.
- The main goal is flexibility without losing brevity.

Please identify the simplest design change, the main risks, and the validation needed before publishing the updated skill.
```

## Automation / Local Runtime

```text
You are operating the local automation/runtime workflow for /var/home/mat/Desktop/AtlasMemory-Tools.

Context:
- Follow the repo's source-of-truth and generated-install rules.
- Stop on unclear blockers or when a human approval is required.

Please continue with the next safe automation step, verify the result, and report any blocker that needs operator input.
```
