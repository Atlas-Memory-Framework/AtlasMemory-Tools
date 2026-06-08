# Handoff: Codex Subscription Isolation For Local Automation Runtimes

**Created:** 2026-05-29 07:12 UTC
**Project:** `/var/home/mat/Desktop/AtlasMemory-Tools`
**Branch:** `docs-runtime-update`
**Purpose for next session:** implement urgent per-project/per-subscription Codex isolation in AtlasMemory-Tools before Atlas can own provider accounts natively.
**Continues from:** none

## Current State

The user needs Atlas and Instablinds automation to consume separate GPT Pro/Codex subscriptions for billing, data separation, and monthly usage isolation. This is urgent because Instablinds has consumed a large share of the current Codex quota.

Atlas itself does not yet have first-class provider account/subscription records. The immediate fix belongs in AtlasMemory-Tools and the installed runtime configs: every project/runtime must use its own `AGENT_CODEX_HOME`, its own Codex login/profile config, and run metadata that identifies the provider account/subscription boundary.

Repo status at handoff creation:

- `AtlasMemory-Tools` branch: `docs-runtime-update...origin/docs-runtime-update`
- Existing unrelated dirty files were present before this handoff:
  - `docs/source-of-truth.md`
  - `scripts/runtime_control.py`
  - `templates/local-automation-runtime/atlas-agent-project-reconcile`
  - `templates/local-automation-runtime/tests/test_project_reconcile.py`
  - `tests/test_manifest_and_harness.py`
- Do not revert or overwrite those existing changes.

## Decisions

- **Fix in Tools first**: Atlas provider-account support is the target architecture, but subscription isolation is needed now. Tools should enforce safe local runtime boundaries immediately.
- **Codex home is the subscription boundary for now**: each runtime/project gets a separate `AGENT_CODEX_HOME` and Codex login. Do not use shared `/home/mat/.codex` for isolated project automation.
- **Record provider identity as metadata**: Tools should not inspect or expose secrets, but every job should record non-secret identifiers such as provider account label, subscription label, Codex workspace id if configured, and isolation mode.
- **Fail closed when isolation is required**: if `AGENT_CODEX_ISOLATION_REQUIRED=true`, the runtime must fail preflight when `AGENT_CODEX_HOME` points at the user's global home, is missing, has unsafe permissions, or lacks expected Codex config/auth files.
- **Use official Codex config boundaries**: OpenAI Codex config docs say user-level config lives under `$CODEX_HOME/config.toml`, profile files live next to it, and `forced_chatgpt_workspace_id` can restrict ChatGPT logins to a workspace. Project-local `.codex/config.toml` cannot override provider/auth config, so the isolation work must happen at the runtime/user-level Codex home, not project-local config.

## Changed Or Important Files

- `templates/local-automation-runtime/config.env.example`: already defaults `AGENT_CODEX_HOME="$PWD/codex-home"`. Extend with explicit isolation variables and comments.
- `templates/local-automation-runtime/check_runtime.sh`: add a Codex isolation preflight check.
- `templates/local-automation-runtime/atlas_agent_common.py`: central place for config expansion and `codex_home_copy(job_dir)`. Add fail-closed validation and metadata helpers here.
- `templates/local-automation-runtime/atlas-agent-worker`: records job artifacts and calls `common.codex_home_copy(job_dir)`. Add provider/isolation metadata into `job_dir`.
- `templates/local-automation-runtime/atlas-agent-issue-decompose`, `atlas-agent-workstream-review`, `atlas-agent-semantic-review`, `atlas-agent-pr-repair`: also call `codex_home_copy`; make sure isolation validation applies to all Codex stages through the common helper.
- `templates/local-automation-runtime/SETUP.md`: update setup instructions for one Codex home per project/subscription.
- `templates/local-automation-runtime/SECURITY.md`: document that shared `/home/mat/.codex` is unsafe for subscription/project isolation.
- `templates/local-automation-runtime/tests/test_local_agent_autonomy.py`: add tests for fail-closed shared-home behavior, metadata capture, and all Codex stages using the common copy.
- `/var/home/mat/Desktop/Atlas-Automation-Runtime/config.env`: currently has `AGENT_CODEX_HOME="/home/mat/.codex"` and should be changed manually to a runtime-local Codex home after code support lands.
- `/var/home/mat/Desktop/Instablinds2-Automation-Runtime/config.env`: currently has `AGENT_CODEX_HOME="/home/mat/.codex"` even though `codex-home/` exists. Change it manually to the runtime-local home after code support lands.

## Proposed Implementation

1. Add config keys to `config.env.example`:
   - `AGENT_CODEX_ISOLATION_REQUIRED="true"`
   - `AGENT_PROVIDER_ACCOUNT_ID=""`
   - `AGENT_PROVIDER_ACCOUNT_LABEL=""`
   - `AGENT_PROVIDER_SUBSCRIPTION_LABEL=""`
   - `AGENT_CODEX_WORKSPACE_ID=""`
   - optional `AGENT_ALLOW_SHARED_CODEX_HOME="false"` for emergency override only.

2. Add a common validator in `atlas_agent_common.py`:
   - expands `AGENT_CODEX_HOME`
   - requires the directory to exist
   - requires `config.toml`
   - requires an auth indicator such as `auth.json` or equivalent file without reading token contents
   - checks owner-only permissions where practical
   - rejects `/home/mat/.codex`, `$HOME/.codex`, or symlinks resolving there when isolation is required and shared-home override is false
   - if `AGENT_CODEX_WORKSPACE_ID` is set, verify `config.toml` contains the same `forced_chatgpt_workspace_id`
   - never logs token values or raw auth file contents.

3. Make all Codex runners go through the same validator:
   - implementation worker
   - issue decomposition
   - semantic review
   - workstream review
   - PR repair.

4. Add job metadata:
   - write `job_dir/provider-account.json`
   - include runtime repo, `AGENT_CODEX_HOME` resolved path hash or redacted path, provider account id/label, subscription label, workspace id, isolation required flag, and validation result
   - do not include auth tokens, raw config, or full private auth details.

5. Add a runtime command or preflight script:
   - either extend `check_runtime.sh`
   - or add `atlas-agent-codex-isolation-check`
   - it should be runnable before any unattended run and report pass/fail for the configured runtime.

6. Update installed runtime configs after code lands:
   - Atlas runtime: use `/var/home/mat/Desktop/Atlas-Automation-Runtime/codex-home` or another Atlas-only Codex home, then log in to the intended Atlas subscription.
   - Instablinds runtime: use `/var/home/mat/Desktop/Instablinds2-Automation-Runtime/codex-home`, then log in to the intended Instablinds subscription.
   - Do not copy one runtime's `auth.json` into the other.

## Verification

Suggested tests:

```bash
cd /var/home/mat/Desktop/AtlasMemory-Tools
python3 -m unittest templates.local-automation-runtime.tests.test_local_agent_autonomy
python3 -m unittest tests.test_manifest_and_harness
```

Suggested runtime checks after installing/syncing the template:

```bash
cd /var/home/mat/Desktop/Atlas-Automation-Runtime
./check_runtime.sh

cd /var/home/mat/Desktop/Instablinds2-Automation-Runtime
./check_runtime.sh
```

Manual validation:

- `AGENT_CODEX_HOME` for Atlas and Instablinds resolve to different directories.
- Neither isolated runtime points at `/home/mat/.codex`.
- Each runtime's `codex-home/config.toml` has the intended `forced_chatgpt_workspace_id` if workspace pinning is used.
- Running one dry-run/decompose/review stage writes `provider-account.json` without secrets.

## Open Questions And Blockers

- [ ] Exact ChatGPT workspace ids for the Atlas and Instablinds subscriptions are not known in this handoff. User/operator must provide or configure them if `forced_chatgpt_workspace_id` is used.
- [ ] Whether GitHub auth should also be split now is unresolved. If billing/data separation requires it, add `GH_CONFIG_DIR` or per-runtime `GH_TOKEN` isolation as a follow-up.
- [ ] Existing dirty files in the Tools repo may already touch runtime behavior. Read them before editing adjacent code.
- [ ] Actual Codex login must be performed by the operator inside each runtime-local Codex home. Do not script token copying.

## Next Steps

1. Inspect existing dirty files in `AtlasMemory-Tools` and avoid overwriting unrelated work.
2. Implement the common Codex isolation validator and job metadata writer.
3. Extend `config.env.example`, `SETUP.md`, `SECURITY.md`, and runtime tests.
4. Sync the template into the installed Atlas and Instablinds runtimes.
5. Change the two runtime `config.env` files away from `/home/mat/.codex`.
6. Have the operator log each runtime into the intended Codex/GPT subscription.
7. Run `check_runtime.sh` and a non-mutating dry run in both runtimes.

## Context Notes

- Do not treat project-local `.codex/config.toml` as sufficient for provider/account isolation. Provider/auth config must live in the runtime's user-level Codex home.
- Do not read, print, diff, or commit `auth.json`, token files, `codex-home/`, webhook URLs, or private logs.
- Do not change Atlas product architecture in this Tools task. The Atlas plan will add first-class provider account/subscription records separately.
- Do not make shared-home override easy to use. If present, require an explicit env flag and log a warning into non-secret runtime metadata.
