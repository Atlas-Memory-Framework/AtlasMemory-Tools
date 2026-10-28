# Task scoping guide

Scope work so an implementer can deliver an intended outcome and a reviewer can tell whether it works. A small file list or a collection of finished tickets is not enough. Use the level of detail the work needs; do not force an arbitrary length or number of tasks.

## From vision to executable work

- **Vision:** Preserve the user's broader intent and anti-targets in the existing Intent Model. Do not treat an entire vision as one executable task or attempt to define every future capability.
- **Project or outcome:** Identify a specific change in a user or system workflow, why it matters, and evidence that would show it happened. Record the current and desired workflows in the Problem Definition.
- **Capability:** Identify what the system must be able to do to achieve that outcome, including important invariants and interfaces with other components or services. Develop the approach and decisions in the Technical Plan.
- **Bounded change:** Define a coherent piece of implementation with its behavior, boundaries, dependencies, failure cases, and verification in the Implementation Plan and, when applicable, the Automation Issue Manifest. Connect it back to the outcome and capability.
- **Discovery:** When a decision or behavior needed for implementation is unknown, bound an investigation by its question, evidence, and resulting decision. Put dependent implementation after that decision. A completed investigation is evidence for a decision, not proof that the product outcome has been delivered.

Carry relevant settled decisions forward; do not reopen them without new evidence or a real conflict. Record unresolved questions and their owners or blockers using the existing plan conventions. Use the existing gates and dispatch policy; this guide adds no schema or approval stage.

## Example: one slice of a broad vision

Suppose the vision is for Atlas to help people retain useful context across work. One representative trace could be:

1. **Outcome:** A person resuming a task can recover relevant prior context.
2. **Capability:** The system can find context relevant to that task and present it for use.
3. **Bounded discovery:** Identify where the relevant context currently lives and evaluate retrieval against representative resumption examples. Record the evidence and decide the next implementation boundary.
4. **Outcome evidence:** After implementation, an owner tests the integrated retrieval and presentation workflow against agreed examples. Until then, the outcome remains unproven.

This is one possible slice, not a definition of all Atlas. The actual outcome, sources, and acceptance examples must come from the user's intent and available evidence.

A weak version says: “Create storage, add an API, and update the interface. Each ticket passed its unit tests, so the vision is complete.” These small tickets do not say what makes context relevant, how components connect, or whether a person can actually resume work. Link the work to the outcome and identify the owner and evidence for the combined workflow.

## Probe apparent clarity

In a hypothetical checkout integration, a website sends an order code and price to Shopify, which handles checkout, payment and customer details and returns confirmation to the website. Even that compact description leaves questions: which system has price authority, how is confirmation verified, and what happens on retries, replay, or failure? Resolve consequential unknowns with evidence before dependent wiring, and validate the agreed end-to-end behavior. This is an illustration, not a claim about current Shopify APIs, a request for Shopify work, or a new Atlas requirement.

Ask for a plausible counterexample: what wrong implementation could satisfy the written tickets and isolated tests while missing the outcome? Turn material answers into decisions, invariants, acceptance evidence, or bounded discovery. Identify who owns integration evidence and any blocker if it cannot yet be produced.

## Choose a model to fit the work

Use Luna by default for clear, bounded tasks. Use Sol or Terra for sizing, review, or a coherent implementation when reasoning difficulty, uncertainty, coupling, or risk warrants it. A task touching few files can still be hard, such as a concurrency or recovery protocol; do not size it by file count alone or split it automatically if that would obscure shared invariants. Conversely, routine code changes do not require escalation merely because they are implementation work.

## Reviewer checklist

For each task or discovery, check:

- Can you trace it from the user's vision through an outcome and capability to this bounded work?
- Are the intended behavior, invariants, relevant interfaces, boundaries, and failure cases clear enough to act without guessing?
- Are consequential unknowns resolved or assigned to a bounded discovery before dependent implementation? Are settled decisions preserved?
- What plausible wrong result could pass the stated checks? Would the acceptance evidence catch it?
- Who owns evidence that the integrated work achieves the outcome, and what remains unverified or blocked?
- Does the model fit the actual reasoning and coupling, with Luna as the default and Sol or Terra available for genuinely harder work?

Boolean gates, required fields, and matching hashes can check structure and freshness. They cannot establish semantic clarity or prove that the intended outcome works; apply judgment to the content and evidence as well.

See [problem definition](../skills/problem-definition/SKILL.md), [automation decomposition](../skills/automation-decomposition/SKILL.md), and [plan execution readiness](../skills/plan-execution-readiness/SKILL.md) for the existing contracts and review workflow.
