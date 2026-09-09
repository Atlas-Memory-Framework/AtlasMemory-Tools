# Azure runtime implementation validation

Local implementation of RUNTIME-A–D was authorized for AtlasMemory-Tools,
starting from `0a571a5b94dfa6ea53a7ea032b4d300b5002f8bf`. The requested
Website target is `https://dev.azure.com/Instablinds/Instablinds/_git/Website`.
The user retains the immediate staging blocker. This receipt advances no Board,
runtime installation, dispatch, publication, or release acceptance gate.

The subsequent [dispatch governance validation](azure-dispatch-governance-validation-2026-09-08.md)
records the separately approved model routing, human handoff and signed-authority
update. The test counts below describe the original RUNTIME-A–D slice.

The [operating contract](azure-devops-runtime.md) maps the four review slices to
their files, command boundaries, configuration, and separate authorization
requirements. Implementation owners reviewed transport/inspection, worker,
reconciliation, and configuration independently. Cross-reviews reproduced and
fixed pagination ambiguity, raw report text, configuration authorization drift,
duplicate native issue claims, and typed acceptance-evidence mismatches.

## Local validation

- Original runtime baseline: 376 tests passed.
- Legacy queue regressions were observed failing before their fixes: missing
  commands, successful exits without acceptance evidence, Azure routing bypass,
  and directory/glob conflicts. The updated local queue tests pass.
- Final runtime unittest discovery: 507 tests passed, including 131 added
  regression scenarios across the legacy queue and Azure slices.
- `python3 -B scripts/verify_repo.py`: passed. Its repository suite passed 107
  tests; runtime discovery, plan-to-issues checks, static/copy gates, executable
  checks, committed harness freshness, temporary adapter generation, and
  whitespace checks passed. Temporary adapter generation is a disposable test,
  not runtime installation.
- The installed Codex CLI reports `0.153.4`. Read-only help probes succeeded for
  the generated `codex exec` and validator `codex sandbox` command shapes.
  The explicit Website configuration resolves planning, implementation, review,
  and repair to `gpt-6-astra` / `max`, with workspace-write and on-request
  approvals. No model call or validator sandbox canary was dispatched.

The repository gates also caught a missing entrypoint executable bit and a
product-specific example in the reusable placeholder directory. Both were
corrected without weakening those gates; Website settings now live under
`examples/instablinds/`, and the reusable Azure example contains placeholders.

Final validation in the requested checkout also exposed legacy test fixtures
that wrote caches or temporary skills into the source tree, plus an unmocked
GitHub batch read. Those fixtures now use disposable state directories and an
explicit batch response. The checks run inside the workspace-write sandbox
without needing write access to this sibling checkout or live API calls.

## Authority and remaining qualification

The checked-in expected graph retains 37 namespaced issues and 71 edges.
The existing applied Board receipt covers 53 links on 21 rollout issues across
27 endpoints; the other 18 prerequisites remain outside that authorization.
The fixture is explicitly unapproved, and the example enables reads only.
Eligibility remains blocked until dependency completeness and exact execution
authority are established.

Live Azure authentication/readback, runtime installation and rollback rehearsal,
actual model/validator execution, draft PR publication, and Board mutation were
not performed. Their exact capabilities and approvals remain separate. Merges,
protected-branch pushes, deployments, permission changes, and service-connection
use are outside this implementation. No Website files, environment files, or
credentials were changed; no source changes were committed or published.
