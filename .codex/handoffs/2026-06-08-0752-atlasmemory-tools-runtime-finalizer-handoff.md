# Handoff: Port runtime finalizer check-run fallback to AtlasMemory-Tools

**Created:** 2026-06-08 07:52 UTC
**Project:** /home/mat/Desktop/AtlasMemory-Tools
**Branch:** docs-runtime-update
**Purpose for next session:** Port the installed runtime finalizer patch back to the AtlasMemory-Tools template source, test it, commit it, push it, and open/merge the appropriate PR if needed.
**Continues from:** /home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/20260608T074608Z-atlas-runtime-operator-handoff.md

## Current State

The Atlas issue-to-PR runtime completed a 12+ hour repo-only no-Projects operation from the installed runtime at `/home/mat/distrobox-homes/atlas-agent/agent-runtime`.

During that operation, the installed runtime was patched locally so `atlas-agent-finalize` could merge PRs whose GitHub PR `statusCheckRollup` was empty while required workflow check runs existed on the commit SHA. This fixed the real queue and allowed PRs #992-#998 in `Atlas-Memory-Framework/atlas-memory` to merge and close issues #830-#836.

That installed runtime directory is not a git checkout. The source repo is `AtlasMemory-Tools` at `/home/mat/Desktop/AtlasMemory-Tools`, remote `https://github.com/Atlas-Memory-Framework/AtlasMemory-Tools.git`, branch `docs-runtime-update`. Current `git status --short --branch` reported clean:

```text
## docs-runtime-update...origin/docs-runtime-update
```

The template source does not yet contain the installed runtime patch.

## Decisions

- **Port from installed runtime, do not commit runtime state**: `jobs/`, `logs/`, local runtime config, and operator handoffs are local state. The code change belongs in `AtlasMemory-Tools/templates/local-automation-runtime/`.
- **Preserve required checks policy**: Do not add a no-checks bypass or weaken `required-checks.json`. The chosen fix is to read commit check runs when PR rollup is empty.
- **Keep no-Projects behavior separate**: The runtime operation deliberately did not use GitHub Projects. This handoff is only for source-porting the finalizer fix and its test.

## Changed Or Important Files

- Installed runtime patched file:
  - `/home/mat/distrobox-homes/atlas-agent/agent-runtime/atlas-agent-finalize`
- Installed runtime patched test:
  - `/home/mat/distrobox-homes/atlas-agent/agent-runtime/tests/test_finalizer_review_gate.py`
- Template source file to update:
  - `/home/mat/Desktop/AtlasMemory-Tools/templates/local-automation-runtime/atlas-agent-finalize`
- Template test file to update:
  - `/home/mat/Desktop/AtlasMemory-Tools/templates/local-automation-runtime/tests/test_finalizer_review_gate.py`
- Runtime operation handoff:
  - `/home/mat/distrobox-homes/atlas-agent/agent-runtime/jobs/20260608T074608Z-atlas-runtime-operator-handoff.md`

## Exact Patch To Port

In the installed runtime, `check_rollup_state` now accepts `repo`:

```python
def check_rollup_state(repo: str, pr: dict[str, Any], required_checks: list[str] | None = None) -> tuple[str, list[str]]:
    checks = pr.get("statusCheckRollup") or []
    if not checks:
        if required_checks:
            checks = common.commit_check_runs(repo, str(pr.get("headRefOid") or ""))
        if not checks:
            return "none", []
```

The installed runtime already had a later fallback for missing required checks:

```python
for check in common.commit_check_runs(repo, str(pr.get("headRefOid") or "")):
```

The source template currently differs:

```text
/home/mat/Desktop/AtlasMemory-Tools/templates/local-automation-runtime/atlas-agent-finalize:
164:def check_rollup_state(pr: dict[str, Any], required_checks: list[str] | None = None) -> tuple[str, list[str]]:
166:    if not checks:
```

Also port the installed test:

```python
def test_empty_rollup_uses_commit_check_runs_for_required_checks(self) -> None:
    original = self.finalize.common.commit_check_runs
    self.finalize.common.commit_check_runs = lambda _repo, _head_sha: [
        {"name": "ci", "status": "completed", "conclusion": "success"}
    ]
    try:
        decision = self.finalize.decide(
            "owner/repo",
            green_pr(labels=["reviewed"], statusCheckRollup=[]),
            allow_no_checks=False,
            merge=True,
            required_check_names=["ci"],
            check_dependencies=False,
            require_review_label="reviewed",
        )
    finally:
        self.finalize.common.commit_check_runs = original

    self.assertEqual(decision.action, "merge")
    self.assertEqual(decision.reasons, [])
```

The template test currently lacks that test; `rg` only found:

```text
172:    def test_local_validation_does_not_override_required_github_checks(self) -> None:
186:    def test_deployed_validation_does_not_override_required_github_checks(self) -> None:
```

## Verification Already Run

- Installed runtime test command:

```bash
python3 -m unittest tests.test_finalizer_review_gate
```

Result: 11 tests passed. The test suite printed expected handled `gh api` connection failures for fake repos, but final result was `OK`.

## Open Questions And Blockers

- [ ] Confirm whether `docs-runtime-update` is the right branch for this runtime source patch, or whether to create a focused branch from it.
- [ ] Confirm whether AtlasMemory-Tools has a preferred test command beyond the targeted finalizer unit test.
- [ ] Network/GitHub push may require escalated `gh` or `git push` commands depending on the host auth/keyring behavior.

## Next Steps

1. In `/home/mat/Desktop/AtlasMemory-Tools`, re-check `git status --short --branch` and confirm no new user changes.
2. Port the installed runtime edits into `templates/local-automation-runtime/atlas-agent-finalize` and `templates/local-automation-runtime/tests/test_finalizer_review_gate.py`.
3. Run the focused test from `templates/local-automation-runtime`:

```bash
python3 -m unittest tests.test_finalizer_review_gate
```

4. If available, run the broader runtime template tests that are relevant to finalizer behavior.
5. Commit with a focused message, push to GitHub, and open/merge a PR according to the repo’s normal workflow.

## Context Notes

- Do not copy operator state from the installed runtime into the source repo.
- Do not add or commit `jobs/`, `logs/`, tokens, local config, runtime caches, or handoff artifacts unless explicitly requested.
- The PRs that motivated this fix were already merged in `Atlas-Memory-Framework/atlas-memory`: #992-#998.
- The final runtime queue ended empty: no open PRs, no open `agent:ready`, no open `agent:failed`.
