# Handoff: M1.5 Decomposition Runtime Repair

**Created:** 2026-06-03 13:18 UTC
**Project:** `/run/host/var/home/mat/Desktop/AtlasMemory-Tools`
**Runtime host:** `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime`
**Purpose for next session:** Continue M1.5 by creating/promoting the first one-point `BaselineEvidencePackage v0` child; do not dispatch #751-#754 parents.
**Continues from:** `.codex/handoffs/2026-06-03-0353-m15-semantic-runtime-queue-repair-handoff.md`

## Current State

Live issue checks confirmed #751-#754 are open but blocked/tracking-only, with `decomposition:required` and stale `agent:decomposed` labels. The runtime decomposition stage previously short-circuited these as `already-decomposed`, so unattended automation did not create fresh decomposition work for the 2026-06-03 M1.5 correction.

## Decisions

- **Do not dispatch parents:** #751-#754 remain blocked by open dependencies, manual gates, and tracking-only dispatch recommendations.
- **Treat decomposed + required as stale:** `agent:decomposed` is no longer authoritative when the plan-managed `decomposition:required` label is still present.
- **Scan plan decomposition labels:** unattended decomposition now scans `decomposition:required` in addition to `status:draft` and `agent:decomposition-required`.

## Changed or Important Files

- `templates/local-automation-runtime/atlas-agent-issue-decompose`: added `decomposition:required` awareness and reclassifies stale decomposed parents as `decompose`.
- `templates/local-automation-runtime/atlas-agent-unattended`: default decomposition candidate labels now include `decomposition:required`.
- `templates/local-automation-runtime/tests/test_issue_decompose.py`: added stale-decomposition tests and label inheritance guard.
- `templates/local-automation-runtime/tests/test_unattended_loop.py`: asserts unattended decomposition scans `decomposition:required`.
- `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime/atlas-agent-issue-decompose`: installed repaired script.
- `/run/host/var/home/mat/Desktop/Atlas-Automation-Runtime/atlas-agent-unattended`: installed repaired script.

## Verification

- `PYTHONPATH=templates/local-automation-runtime python3 -m unittest templates.local-automation-runtime.tests.test_issue_decompose templates.local-automation-runtime.tests.test_unattended_loop`: pass, 69 tests.
- `python3 -m py_compile templates/local-automation-runtime/atlas-agent-issue-decompose templates/local-automation-runtime/atlas-agent-unattended`: pass.
- `PYTHONPYCACHEPREFIX=/tmp/atlas-pycache-m15-decompose python3 -m py_compile /run/host/var/home/mat/Desktop/Atlas-Automation-Runtime/atlas-agent-issue-decompose /run/host/var/home/mat/Desktop/Atlas-Automation-Runtime/atlas-agent-unattended`: pass.
- `./check_runtime.sh`: pass for GitHub auth, Podman via host, and Codex home isolation.
- `./atlas-agent-issue-decompose --issue Atlas-Memory-Framework/atlas-memory#751 --dry-run`: pass; action is now `decompose` with reason `stale decomposed label with plan decomposition requirement`.
- `./atlas-agent-unattended --dry-run --cycles 1 --stages decompose --decompose-issue #751..#754`: pass; summary counts `decompose: 4`.
- `./atlas-agent-plan-queue --plan ... --dry-run`: pass; still `queueable_count=0`, `blocked_count=123`.

## Open Questions and Blockers

- [ ] No fresh one-point `BaselineEvidencePackage v0` child exists yet.
- [ ] The current canonical plan has enough product intent for M1.5 direction, but it is scattered; future `$plan` work should add a concise user-intent/operator-desire contract so agents do not optimize for issue churn over Atlas-owned execution cutover proof.
- [ ] #392-#396 are older one-point bootstrap-import children, still blocked and scoped to old parser/import work; they do not satisfy the newer `BaselineEvidencePackage` canary requirement.

## Next Steps

1. Create or draft a one-point child under #751 for `BaselineEvidencePackage v0 contract/fixture canary`.
2. Scope it to read-only source evidence, source checksums, quarantine/redaction class, idempotency/replay, deterministic ordering, and generated fixture expectations.
3. Keep dependencies/manual gates `none` only if the child is contract/fixture-only and does not persist importer records, promote replanned authority, mutate GitHub/Project state, or touch switch-over approval.
4. After the child exists, run a read-only queue/decompose audit and dispatch only that child if it is `points:1`, `status:ready`, dependency-clean, manual-gate-clean, and explicitly approved.

## Context Notes

User is blocked by M1.5 and wants semantic progress, not checkbox completion. The system had enough language to reject parent dispatch, but not enough automation policy to refresh stale decomposition labels. The repaired runtime fixes the latter without loosening dispatch safety.
