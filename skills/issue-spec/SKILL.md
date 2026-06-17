---
name: issue-spec
description: Author and validate Plan Package v0 issue spec sidecars for one executable Automation Issue Manifest leaf.
---

# Issue Spec

## Purpose

Use this skill when an executable manifest leaf needs more detail than the global plan should carry.
The sidecar is a governed attachment to one manifest leaf, not a replacement authority.

## Authority Rules

- The selected markdown plan and its Automation Issue Manifest remain the v0 authoring authority.
- One issue spec sidecar maps to exactly one manifest leaf.
- Sidecars may refine implementation detail, validation evidence, and stop rules.
- Sidecars cannot introduce or override leaves, files, gates, dependencies, dispatch readiness,
  approval state, or authority semantics absent from the markdown manifest.
- GitHub issues stay concise execution cards; do not copy the full sidecar body into an issue.

## Required Fields

Every sidecar must include:

- `SpecId`
- `SourceId`
- `ParentPlanId`
- `ManifestLeafId`
- `Intent`
- `Anti-scope`
- `Files in scope`
- `Files out of scope`
- `Dependencies`
- `Required gates`
- `Validation`
- `Acceptance criteria`
- `Dispatch mode`
- `One PR contract`
- `Open decisions`

Use `none` only when the manifest also declares `none` for that field.

## Depth Contract

Add `Depth contract` when the leaf involves testing, data, coverage, fixtures, runtime behavior,
projection, cross-module behavior, or more than one file. The contract should state quantitative and
qualitative completion rules, not just repeat the acceptance criteria.

## Inline Specs

`Spec: inline` is allowed only for tiny leaves whose manifest entry is self-contained with file scope,
dependencies, validation, acceptance criteria, dispatch mode, and one-PR contract. If any of those are
missing, create a sidecar instead.

## Validation

Run:

```bash
python3 skills/issue-spec/scripts/validate_issue_spec.py path/to/spec.md --manifest path/to/plan.md --leaf-id LEAF-ID
```

For an inline manifest leaf:

```bash
python3 skills/issue-spec/scripts/validate_issue_spec.py --inline-manifest --manifest path/to/plan.md --leaf-id LEAF-ID
```

The validator is deterministic and local-only. It checks required fields, source alignment, depth
contract triggers, inline manifest completeness, and sidecar authority against the manifest leaf.
