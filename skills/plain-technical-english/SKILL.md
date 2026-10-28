---
name: plain-technical-english
description: Write and review newly created or materially changed Markdown and user-facing technical reports for understandable meaning, explicit actions, and faithful reasoning. Use before delivering plans, reviews, grilling questions, progress updates, or final reports; retain required output schemas and exact evidence.
---

# Plain Technical English

Make the work understandable to the user without losing the facts needed to assess it. Apply this check to new or materially changed prose and to the report sent with it. Do not bulk-rewrite historical Markdown.

## User's rule (verbatim)

> Use plain, direct technical English. State the answer first, then explain it. Make clear who does what, under which conditions, and why. Use the same term for the same thing. Explain necessary technical terms instead of replacing them with vague words. Preserve important reasoning, qualifications, and uncertainty. Remove filler, repeated conclusions, and unnecessary introductions. Do not confuse brevity with clarity.

## Before delivering prose

Read the actual draft as a reader who has not followed the agent's investigation. State its answer in one sentence, then explain the action, owner, relevant conditions, reason, and remaining uncertainty from the text alone. For descriptive writing, explain the behavior or finding instead of inventing an action. If you cannot do this, identify the exact missing relationship and revise it from verified context. Do not invent owners, decisions, facts, approval, or certainty to make a sentence sound complete.

Use the rubric below to check meaning. A familiar word can still be vague; a necessary technical term can be precise and helpful. Sentence length, reading-age scores, word counts, passive voice, and jargon lists cannot establish a pass or failure. Keep a longer explanation when it preserves a causal link, tradeoff, limitation, or useful example.

| Criterion ID | Reader test | Material failure |
| --- | --- | --- |
| `answer-first` | Does the opening give the answer, result, recommendation, or current blocker before process history? | The user must infer the result from activity or framework labels. Required document frontmatter/headings need not be reordered. |
| `actors-actions` | Can the reader identify who or what acts, the action, and its target when action is involved? | “It is handled” hides an owner or target needed to act. For descriptive text with no action, explain why this criterion is not applicable. |
| `conditions-reasons` | Does the text explain when behavior applies and why the action or conclusion follows? | A missing trigger, prerequisite, or causal link changes the reader's decision. Do not demand irrelevant conditions for a simple fact. |
| `terms-referents` | Do repeated terms identify the same thing, pronouns have clear referents, and necessary unfamiliar terms have enough explanation? | Synonyms hide different components or a framework term substitutes for behavior. Do not ban precise terms, code identifiers, or established names. |
| `reasoning-uncertainty` | Are material evidence, assumptions, tradeoffs, qualifications, and unknowns preserved and distinguishable? | A test becomes a claim of deployment, a local artifact becomes durable storage, or an unresolved assumption becomes a fact. |
| `economy-clarity` | Does each passage help the reader understand or decide, without filler or repeated conclusions? | Repetition obscures the action, or compression removes the explanation needed to understand it. This is not a length quota. |
| `faithfulness` | Does the prose preserve the source meaning and all protected content? | A rewrite changes a constraint, evidence, exact quote, command, schema, API name, or code while claiming only to improve writing. |

A semantic review passes when every applicable criterion passes and the reader can explain the result without guessing a material fact. For each failure, cite the passage, explain what the reader cannot determine and why it matters, and propose a bounded correction. Do not fail an otherwise clear document for optional style preferences. Explicit uncertainty can pass; use an existing blocker or decision process when the unknown blocks execution.

## Preserve contracts and evidence

Review prose around code, commands, identifiers, schemas, logs, exact quotes, citations, and evidence. Do not mechanically rewrite those protected spans. If an example is misleading or evidence needs correction, report that as a separate technical issue with its source; do not quietly alter it in a writing pass. Keep required plan/review headings, field names, finding IDs, and output formats. Place the explanation inside their existing prose fields.

For planning, extend the existing `HumanReadabilityReview` and `/review mode=human-readability`; do not create a parallel approval gate. The reviewer returns findings; the existing owner applies accepted edits. For grilling, make each question's decision, recommended answer, alternative, and consequence understandable without adding questions or overriding the interview's read-only boundary.

For a short progress update or final answer, perform the reader test directly before sending. A separate review file is unnecessary. For a substantial Markdown deliverable or a saved report where review evidence is useful, use the record workflow below. Read [examples](references/examples.md) when calibrating a review or a rewrite.

## Optional machine-checked review record

The checker verifies a review record, not writing quality. It reads files without rewriting them. It makes no provider or database calls.

1. Finish the draft, then run `python3 <skill-dir>/scripts/check_review.py prepare <document.md> > <review.json>` with a separate review path. The command prints a pending record to standard output. Never redirect it into the document.
2. A reviewing agent or person reads the draft and fills `reviewer`, `reader_summary`, and every criterion's `result`, `reason`, and `evidence`. Use `pass`, `fail`, or, for the conditional criteria only, `not-applicable`. Each evidence entry has a one-based `line` and an exact single-line `text` excerpt from the document. Reasons must explain the judgment, not repeat the criterion name. Reviewer names are attribution, not authenticated identity.
3. Run `python3 <skill-dir>/scripts/check_review.py check <document.md> <review.json>`. Exit 0 means the record covers the rubric, its cited excerpts exist, the document hash matches, and the reviewer recorded no failures. Exit 1 means the reviewer recorded a failure; exit 2 means the record is missing, pending, invalid, or stale. A filled record can still contain poor judgment; an agent must assess its reasoning.
4. After a material edit, review the revised text again and prepare a new record. Never update only the hash to carry an old pass forward. Reuse existing independent review roles when they are available; this skill does not authorize spawning workers or external actions.

Use this workflow alongside existing plan review evidence; it does not set plan approval, dispatch approval, or deployment status. No hook intercepts every chat message or Markdown write. Workflow instructions enforce the semantic review; the CLI enforces record coverage, source freshness, and evidence anchors only when invoked.
