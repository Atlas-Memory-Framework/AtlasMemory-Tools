---
# atlas-tools-generated: source=skills/project-queue-audit/SKILL.md manifest=atlas-tools.v1 checksum=sha256:75336e5abaa513167fd40c3a57b360f46376ee1f115ea604c6b4bfe7c8bbb31e
# atlas-tools-generated-end
name: project-queue-audit
description: Audit GitHub Project and issue queue safety before local automation dispatch. Use before adding agent:approved-dispatch or agent:ready, when reconciling Project fields with issue body runtime markers, or when checking dependency-gated queue items.
---

# Project Queue Audit

## Purpose

Audit GitHub Project and issue queue state before local automation dispatch. The goal is to prove that
an issue is manual, dependency-gated, blocked, or safe to approve before any worker receives it.

Use this skill when:

- reviewing `needs-human`, `review-before-dispatch`, `status:ready`, or dependency-gated issues
- deciding whether to add `agent:approved-dispatch` or `agent:ready`
- comparing GitHub Project fields against issue body runtime markers
- checking whether dependency blockers are actually closed

## Authority

- The issue body is the runtime contract for local automation.
- GitHub Project fields are an operator view, not planning truth. They must agree with the issue body and labels before dispatch.
- Labels are dispatch signals, not proof of safety.
- Do not recommend dispatch when body markers, Project fields, labels, or dependency state disagree.
- The reconciler may hydrate or repair Project fields, but it must make body markers, labels, and Project fields agree before any issue is approved for dispatch.

## Required Inputs

Collect or infer:

- target repo, issue numbers, and optional Project URL
- issue body, labels, author, state, linked PRs, and current comments if needed
- Project fields: `AutomationState`, `DispatchMode`, `DispatchRecommendation`, `IssueReady`,
  `DependsOn`, `AutomationBlockers`, `BlockerType`, `BlockerReason`, `ReviewGates`, `Validation`,
  `WriteScope`, `OnePRContract`, `Priority`, `Size`, `SourceId`, and linked pull requests
- dependency issue/PR states for every dependency ref in `Open dependencies:` or Project `DependsOn`

Use dry-read commands first. Do not mutate labels until the audit passes and the user asked for an
apply action.

## Classification

Classify each issue into exactly one queue state:

- `Manual`: human review, manual validation, tracking-only work, unsupported risk, oversized scope,
  or `DispatchMode=manual-review|tracking-only`.
- `Dependency-gated`: otherwise dispatchable work with explicit dependency refs that are not all
  closed or merged.
- `Blocked`: missing/unsafe metadata, opaque dependency text, manual blockers, Project/body
  disagreement, untrusted author, tracker/epic item, active PR conflict, or stale unsafe agent labels.
- `Ready`: bounded implementation work whose dependencies are closed, manual gates are clear,
  Project fields match the issue body, and dispatch approval is allowed.

If multiple states apply, choose the safest state in this order: `Blocked`, `Dependency-gated`,
`Manual`, `Ready`.

## Audit Flow

1. Read the issue body and labels.
2. Read Project field values for the same item when a Project is provided.
3. Check unsafe body projection patterns:
   - fail if the issue has `## Dependencies` but no `Open dependencies:` marker
   - fail if generated runtime markers are absent from the issue body but present only in Project fields
   - fail if `SourceId` / manifest leaf id / workstream id is missing from a projected executable issue body
   - fail if `Open dependencies:` exists and is neither `none` nor parseable issue/PR refs
   - fail if dependency text contains only plan tokens, gates, merge points, decisions, risks,
     assumptions, or opaque prose
   - fail if generated `Open dependencies:` says `none` while `## Dependencies`, Project `DependsOn`,
     required gates, or body blocker text still names unresolved blockers
   - fail if `Manual gates remaining:` is non-empty, omitted from a generated executable issue, or says
     `none` while manual/deployed validation blockers remain in the body or Project fields
4. Compare body markers to Project fields:
   - `Open dependencies:` must match `DependsOn` or the Project must explicitly explain why it is empty
   - body `SourceId` must match Project `SourceId`; duplicate `SourceId` values across open issues or
     Project rows are blockers
   - body `Points` and `points:*` labels must match Project `Size`
   - body/label priority must match Project `Priority`
   - non-empty blockers must map to `AutomationBlockers`, `BlockerType`, `BlockerReason`, or
     `AutomationState=Blocked|Human Action|Waiting`
   - `DispatchMode` and `DispatchRecommendation` must agree with labels and body risk notes
   - `AutomationState=Ready`, `IssueReady=true`, `agent:ready`, or `status:ready` must not coexist
     with non-empty dependency/manual-gate markers or `Points` / `Size` greater than `1`
   - Project-only rows without a matching GitHub issue body source marker are blockers, not queue items
5. Verify dependencies:
   - issue refs must be closed
   - PR refs must be merged
   - unverifiable refs are blockers
   - cross-repo refs must include `OWNER/REPO#N` or full GitHub URLs
6. Check dispatch boundaries:
   - one concrete story/task/spike, not an epic or tracker
   - `WriteScope`, validation evidence/commands, and acceptance criteria are present
   - `OnePRContract=Yes` for unattended dispatch unless the operator explicitly waives it
   - no active PR, running agent label, or stale failure state conflicts with a new dispatch
7. Decide the queue state and required operator action.

## Approval Policy

Recommend adding `agent:approved-dispatch` and `agent:ready` only when all are true:

- classification is `Ready`
- projected issue body includes stable source markers and runtime markers; none are Project-only
- `Priority`, `SourceId`, and `Size` are present and consistent across issue body, labels, and Project fields
- no duplicate `SourceId` exists in the audited repo/Project set
- `Points` / `Size` is `1`
- dependencies are `none` or verified closed/merged
- `Manual gates remaining:` is `none` or absent
- no unsafe `## Dependencies` projection remains without `Open dependencies:`
- Project fields and issue body agree on dispatch mode, blockers, and automation state
- the issue is not an epic, tracker, tracking-only item, untrusted-author item, or active/running item
- the user explicitly requested an apply action

For `review-before-dispatch` items, add `agent:approved-dispatch` only after the same audit passes.
Then add `agent:ready` as the queue signal. If the audit fails, remove or recommend removing stale
`agent:ready`, `agent:running`, or `agent:failed` labels that would mislead the local lane.

## Suggested Commands

Read issue state:

```bash
gh issue view NUMBER --repo OWNER/REPO --json number,title,state,author,labels,body,url
```

Verify dependency refs:

```bash
gh issue view NUMBER --repo OWNER/REPO --json state,url
gh pr view NUMBER --repo OWNER/REPO --json state,merged,url
```

Apply approval only after a passing audit:

```bash
gh issue edit NUMBER --repo OWNER/REPO --add-label agent:approved-dispatch
gh issue edit NUMBER --repo OWNER/REPO --add-label agent:ready
```

## Output

Report a compact table or bullets with:

- issue ref and title
- classification: `Manual`, `Dependency-gated`, `Blocked`, or `Ready`
- evidence: body markers, Project field agreements/disagreements, dependency verification result
- unsafe projection patterns found
- post-sync hard failures: missing `Priority`, duplicate `SourceId`, multi-point ready state,
  Project-only row, or `Size` mismatch
- recommended action
- labels to add or remove, clearly separating dry-run recommendations from applied changes

When applying changes, report every label mutation and the reason it was allowed.
