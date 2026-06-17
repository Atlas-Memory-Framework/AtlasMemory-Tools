# Issue Spec Reference

Use one sidecar per executable Automation Issue Manifest leaf.

```md
# Issue Spec: <short title>

SpecId: <plan-id>-<leaf-id>-spec
SourceId: <plan-id>#<leaf-id>
ParentPlanId: <plan-id>
ManifestLeafId: <leaf-id>
Dispatch mode: manual-review
One PR contract: yes

## Intent
<What this leaf must accomplish and why it exists.>

## Anti-scope
- <Explicitly excluded behavior, files, products, or workflow changes.>

## Files in scope
- `path/to/file.py`

## Files out of scope
- `path/to/other_file.py`

## Dependencies
- none

## Required gates
- G-CI-Example

## Validation
- `python3 -m unittest tests.test_example`

## Acceptance criteria
- <Observable pass/fail outcome.>

## Depth contract
- Required for testing, data, coverage, fixture-heavy, runtime/projection, cross-module, or multi-file leaves.
- Include quantitative coverage or fixture counts when they are part of done.
- Include qualitative stop rules for ambiguity, unsupported dependencies, or manual review.

## Open decisions
- none
```

## Manifest Leaf Pattern

```md
- LEAF-001: Add focused validator
  - Spec path: specs/leaf-001.md
  - Spec hash: sha256:<64 lowercase hex chars>
  - Dispatch: manual-review
  - Depends on:
    - none
  - Files in scope:
    - `skills/example/scripts/validate_example.py`
  - Files out of scope:
    - `skills/plan-to-issues/scripts/plan_to_issues.py`
  - Required gates:
    - G-CI-Example
  - Validation:
    - python3 -m unittest tests.test_example
  - Acceptance criteria:
    - Valid examples pass and malformed examples fail with specific messages.
  - One PR contract: yes
```

## Inline Manifest Pattern

```md
- LEAF-002: Tiny documentation correction
  - Spec: inline
  - Dispatch: manual-review
  - Depends on:
    - none
  - Files in scope:
    - `skills/example/reference.md`
  - Files out of scope:
    - `skills/example/scripts/validate_example.py`
  - Required gates:
    - G-DOCS-Review
  - Validation:
    - manual docs review
  - Acceptance criteria:
    - The reference includes the missing field.
  - One PR contract: yes
```
