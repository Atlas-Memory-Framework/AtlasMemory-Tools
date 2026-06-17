# Plan Package Reference

Plan Package v0 is a derived local registry for a selected markdown plan plus issue-spec sidecars. It does not replace the selected plan as the authoring artifact, and it does not make package directories the default. The package registry exists so local validation, local work-item export, optional GitHub issue export, and package-mode review can share one deterministic source map.

## Authority

- The selected markdown plan remains the authoring authority for manifest leaves, dispatch mode, dependencies, scope, gates, and acceptance criteria.
- Issue specs are governed attachments. A sidecar may deepen a leaf, but it cannot introduce scope, dependencies, gates, dispatch changes, approval state, or new leaves not declared by the manifest.
- The compiled registry is derived metadata. It is safe to regenerate and should be validated before use.
- GitHub issues and Projects are optional export surfaces. Plan Package v0 does not require GitHub Project fields for local package validation or local work-item execution.

## Registry Shape

The compiler writes canonical JSON using sorted keys, two-space indentation, `\n` line endings, and a trailing newline. `package_hash` is `sha256` of the same canonical JSON after omitting the `package_hash` field.

Required top-level fields:

- `schema_version`: `plan-package.v0`
- `package_id`: normally the plan `PlanId`
- `package_hash`: deterministic hash of the registry preimage
- `source_plan.path`
- `source_plan.hash`
- `members[]`
- `leaves[]`

Each member records:

- `path`
- `kind`
- `hash`
- `patchable`

Each leaf records:

- `source_id`
- `manifest_leaf_id`
- `spec_path`
- `spec_hash`
- `dependencies`
- `required_gates`
- `files_in_scope`
- `files_out_of_scope`
- `dispatch_mode`
- `validation`
- `acceptance_criteria`
- `projection_hints`
- `local_export`

## CLI

Compile:

```sh
python3 skills/plan-package/scripts/compile_plan_package.py plans/example.plan.md --root . --out package.registry.json
```

Validate:

```sh
python3 skills/plan-package/scripts/validate_plan_package.py package.registry.json --root .
```

The validator rejects missing package members, malformed hashes, hash mismatches, path escapes, duplicate source ids, missing required registry fields, and dependency mismatches. It also recompiles the selected source plan and sidecars to catch stale or hand-edited registry data.
