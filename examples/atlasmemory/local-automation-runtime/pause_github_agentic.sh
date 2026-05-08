#!/usr/bin/env bash
set -euo pipefail

mode="${1:-disable}"
case "$mode" in
  disable|enable) ;;
  *)
    echo "Usage: $0 [disable|enable]" >&2
    exit 2
    ;;
esac

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is not installed or not on PATH in this environment." >&2
  exit 1
fi

gh auth status >/dev/null

set_workflow() {
  local repo="$1"
  local workflow="$2"
  if gh workflow view "$workflow" --repo "$repo" >/dev/null 2>&1; then
    echo "$mode $repo $workflow"
    gh workflow "$mode" "$workflow" --repo "$repo"
  else
    echo "skip missing $repo $workflow"
  fi
}

control_repo="Atlas-Memory-Framework/Atlas-Memory-Azure"
control_workflows=(
  agentic-issue-dispatch.yml
  agentic-issue-reconcile.yml
  agentic-issue-signal.yml
  agentic-issue-signal-smoke.yml
  agentic-pr-signal.yml
  agentic-pr-signal-smoke.yml
  agentic-pr-repair.yml
  agentic-project-orchestrator.yml
  planning-pilot-orchestrator.yml
  agentic-repair-controller.yml
  agentic-automerge.yml
)

for workflow in "${control_workflows[@]}"; do
  set_workflow "$control_repo" "$workflow"
done

forwarder_repos=(
  Atlas-Memory-Framework/atlas-memory
  Atlas-Memory-Framework/Atlas-Memory-Admin-UI
  Atlas-Memory-Framework/Atlas-Memory-Chainlit
)

for repo in "${forwarder_repos[@]}"; do
  set_workflow "$repo" agentic-forward-to-control-plane.yml
done
