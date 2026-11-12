# Workflow harness source inventory

Source commit: `6edb37cdcabf2af2dfcf9626916aad9b1de27acf`

Every root regular file has a disposition and SHA256. Each supported entrypoint lists native argparse subcommands or explicit effect-bearing modes. Literal parser tokens are statically extracted; dynamically generated flags and combinations need implementation contract review. No scripts were executed. This is an entrypoint/mode inventory, not proof of exhaustive flag-combination semantics.

| Lane | Entry point | Native subcommands / effect-bearing modes | Effects upper bound | Existing MCP |
| --- | --- | --- | --- | --- |
| operator-controls | `templates/local-automation-runtime/atlas-agent-admin` | inspect, clean-labels, fix-base, create-base, allow-policy, fix-git-identity | read, local-write-possible, cloud-read-possible, cloud-write-possible | none-direct |
| azure-governed | `templates/local-automation-runtime/atlas-agent-azure-approval` | preview, prepare, reopen, export, import-response, operator-issue | read, local-write-possible, cloud-read-possible, cloud-write-possible | none-direct |
| azure-governed | `templates/local-automation-runtime/atlas-agent-azure-dispatch` | preview, assess, execute, check-handoff-before, check-handoff-after | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | none-direct |
| azure-governed | `templates/local-automation-runtime/atlas-agent-azure-inspect` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | partial aggregate via harness_prepare/start Azure operations |
| azure-governed | `templates/local-automation-runtime/atlas-agent-azure-intake` | preview, live-read | read, local-write-possible, cloud-read-possible, cloud-write-possible | none-direct |
| azure-governed | `templates/local-automation-runtime/atlas-agent-azure-reconcile` | preview, apply | read, local-write-possible, cloud-read-possible, cloud-write-possible | partial aggregate via harness_prepare/start Azure operations |
| azure-governed | `templates/local-automation-runtime/atlas-agent-azure-supervise` | preview, observe, run | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | none-direct |
| azure-governed | `templates/local-automation-runtime/atlas-agent-azure-worker` | preview, execute, publish | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | partial aggregate via harness_prepare/start Azure operations |
| operator-controls | `templates/local-automation-runtime/atlas-agent-cleanup` | preview, apply | read, local-write-possible, deletion-on-apply | none-direct |
| notifications | `templates/local-automation-runtime/atlas-agent-cycle-summary` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible, external-message-possible | none-direct |
| local-workflows | `templates/local-automation-runtime/atlas-agent-delta-review` | freeze, plan-checks, metric, run-checks, acceptance-check | read, local-write-possible | none-direct |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-dependency-promote` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| deployment | `templates/local-automation-runtime/atlas-agent-deploy` | candidate, dev-sequence, functions-code, chainlit | read, local-write-possible, cloud-read-possible, cloud-write-possible, deployment | none-direct |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-deployed-validate` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-finalize` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-issue-decompose` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-local-validate` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| notifications | `templates/local-automation-runtime/atlas-agent-notify` | summary, teams | read, local-write-possible, cloud-read-possible, cloud-write-possible, external-message-possible | none-direct |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-orchestrator` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-plan-queue` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-pr-repair` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-project-reconcile` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-project-sync` | status, flush | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-reconcile` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-review` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| local-workflows | `templates/local-automation-runtime/atlas-agent-role-codex` | preview, execute | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | none-direct |
| local-workflows | `templates/local-automation-runtime/atlas-agent-role-runner` | preview, run | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | none-direct |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-semantic-review` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-shift` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| operator-controls | `templates/local-automation-runtime/atlas-agent-throttle-status` | run | read | none-direct |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-triage` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible, external-message-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-unattended` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible, external-message-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| local-workflows | `templates/local-automation-runtime/atlas-agent-work-item-add` | run | read, local-write-possible | none-direct |
| local-workflows | `templates/local-automation-runtime/atlas-agent-work-item-inspect` | run | read | none-direct |
| local-workflows | `templates/local-automation-runtime/atlas-agent-work-item-requeue-stale` | preview, apply | read, local-write-possible | none-direct |
| local-workflows | `templates/local-automation-runtime/atlas-agent-work-item-rework` | rework | read, local-write-possible | none-direct |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-worker` | once, loop | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-actions | `templates/local-automation-runtime/atlas-agent-workflow` | run, list, watch, view, download | read, local-write-possible, cloud-read-possible, cloud-write-possible | none-direct |
| local-workflows | `templates/local-automation-runtime/atlas-agent-workflow-lint` | run | read | none-direct |
| local-workflows | `templates/local-automation-runtime/atlas-agent-workflow-select` | run | read | none-direct |
| local-workflows | `templates/local-automation-runtime/atlas-agent-workflow-template-add` | add, force-replace | read, local-write-possible | none-direct |
| github-issue-to-pr | `templates/local-automation-runtime/atlas-agent-workstream-review` | run | read, local-write-possible, cloud-read-possible, cloud-write-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| daily | `templates/local-automation-runtime/atlas_local_dev.py` | add, status, prepare, import | read, local-write-possible | none-direct |
| installation | `templates/local-automation-runtime/build_codex_image.sh` | build | read, local-write-possible, child-process-or-model-possible | none-direct |
| installation | `templates/local-automation-runtime/check_runtime.sh` | check | read, local-write-possible | none-direct |
| github-issue-to-pr | `templates/local-automation-runtime/default_branches.sh` | list | read, cloud-read-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/list_issues.sh` | list | read, cloud-read-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-actions | `templates/local-automation-runtime/pause_github_agentic.sh` | disable, enable | read, local-write-possible, cloud-read-possible, cloud-write-possible | none-direct |
| github-issue-to-pr | `templates/local-automation-runtime/run_dry_issue.sh` | dry-worker-with-label-mutations | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/run_e2e_chain.sh` | bounded-chain | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/run_issue_publish.sh` | publish-worker-with-label-mutations | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| github-issue-to-pr | `templates/local-automation-runtime/run_parallel_orchestrators.sh` | launch-daemons | read, local-write-possible, cloud-read-possible, cloud-write-possible, child-process-or-model-possible | some actions reachable through bounded github-cycle; no operation-level parity claim |
| installation | `scripts/runtime_control.py` | status, repos, projects, models, sync, plan-preview, queue, dry-cycle, run-once, shift, review, finalize, azure-inspect, azure-worker, azure-reconcile, azure-dispatch, azure-supervise, azure-intake, azure-approval | read, local-write-possible, cloud-read-possible, cloud-write-possible | none-direct |
| installation | `scripts/harness_service.py` | discover, inspect, installation-status, prepare, start, wait, cancel, remote-repositories, configure-remote | read, local-write-possible, cloud-read-possible, cloud-write-possible | existing-nine-tools; service prepare/start are dynamic parser loop |
| installation | `scripts/harness_remotes.py` | configure, rollback, repositories | read, local-write-possible, cloud-read-possible, cloud-write-possible | configure and repositories direct; rollback missing |
| installation | `scripts/setup_harness_interface.py` | preview, check, apply, rollback-preview, rollback-apply | read, local-write-possible | none-direct |
| daily | `scripts/atlas_daily.py` | status | read | none-direct |
| installation | `scripts/install_harness.py` | install, check | read, local-write-possible | none-direct |
| installation | `scripts/verify_harness.py` | verify | read | none-direct |
| installation | `scripts/verify_repo.py` | verify, static-only, strict-copy | read | none-direct |
| installation | `scripts/harness_mcp.py` | serve-stdio | read, local-write-possible | existing-nine-tools; service prepare/start are dynamic parser loop |

## Non-entrypoint dispositions

- `templates/local-automation-runtime/.gitignore`: configuration-documentation-or-data
- `templates/local-automation-runtime/AGENTS.md`: configuration-documentation-or-data
- `templates/local-automation-runtime/README.md`: configuration-documentation-or-data
- `templates/local-automation-runtime/SECURITY.md`: configuration-documentation-or-data
- `templates/local-automation-runtime/SETUP.md`: configuration-documentation-or-data
- `templates/local-automation-runtime/atlas-agent-role-fake-codex`: test-double-not-production-operator
- `templates/local-automation-runtime/atlas_agent_common.py`: imported-runtime-library
- `templates/local-automation-runtime/atlas_approval.py`: operator-module-alias-of-wrapper
- `templates/local-automation-runtime/atlas_authority.py`: imported-runtime-library
- `templates/local-automation-runtime/atlas_azure_devops.py`: imported-runtime-library
- `templates/local-automation-runtime/atlas_azure_reconcile.py`: operator-module-alias-of-wrapper
- `templates/local-automation-runtime/atlas_azure_worker.py`: operator-module-alias-of-wrapper
- `templates/local-automation-runtime/atlas_delta_review.py`: imported-runtime-library
- `templates/local-automation-runtime/atlas_dispatch.py`: operator-module-alias-of-wrapper
- `templates/local-automation-runtime/atlas_human_gates.py`: imported-runtime-library
- `templates/local-automation-runtime/atlas_intake.py`: operator-module-alias-of-wrapper
- `templates/local-automation-runtime/atlas_local_sizing.py`: imported-runtime-library
- `templates/local-automation-runtime/atlas_routing.py`: imported-runtime-library
- `templates/local-automation-runtime/atlas_runtime_config.py`: imported-runtime-library
- `templates/local-automation-runtime/atlas_supervised_handoff.py`: imported-runtime-library
- `templates/local-automation-runtime/atlas_supervisor.py`: operator-module-alias-of-wrapper
- `templates/local-automation-runtime/atlas_work_items.py`: imported-runtime-library
- `templates/local-automation-runtime/atlas_workflows.py`: imported-runtime-library
- `templates/local-automation-runtime/config.env`: configuration-documentation-or-data
- `templates/local-automation-runtime/config.env.example`: configuration-documentation-or-data
- `templates/local-automation-runtime/local-validation.json`: configuration-documentation-or-data
- `templates/local-automation-runtime/projects.example.txt`: configuration-documentation-or-data
- `templates/local-automation-runtime/projects.txt`: configuration-documentation-or-data
- `templates/local-automation-runtime/repos.example.txt`: configuration-documentation-or-data
- `templates/local-automation-runtime/repos.txt`: configuration-documentation-or-data
- `templates/local-automation-runtime/required-checks.json`: configuration-documentation-or-data
- `templates/local-automation-runtime/requirements-dev.txt`: configuration-documentation-or-data

## Completeness and qualification limits

All regular root files in templates/local-automation-runtime plus nine explicitly selected operator/interface scripts. Recursive tests/examples/config/team-templates are dependencies or fixtures, not silently discarded executable roots. Imported modules with __main__ are wrapper aliases.

Remaining lane order is descriptive only; user authorized daily first and all maintained scope, not this document as dispatch policy.

- Effects are conservative per-entrypoint upper bounds; individual modes can be read-only. Classify exact effects in final contracts.
- Tests, examples, team templates and config inputs are not operator entrypoints but remain validation/dependency evidence.
- `run_dry_issue.sh` creates/edits GitHub labels despite its name.
- `run_parallel_orchestrators.sh` launches daemon work with publish and Teams-related defaults.
- `pause_github_agentic.sh` changes hosted workflow enablement.
- Native CLI exposure does not establish authorization or safe bounded MCP exposure.
