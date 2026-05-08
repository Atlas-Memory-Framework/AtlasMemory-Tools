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

runtime_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$runtime_dir/config.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$runtime_dir/config.env"
  set +a
fi

control_repo="${AGENT_CONTROL_REPO:-}"
control_workflows_csv="${AGENT_CONTROL_WORKFLOWS:-agentic-issue-dispatch.yml,agentic-issue-reconcile.yml,agentic-pr-repair.yml,agentic-automerge.yml}"
forwarder_repos_csv="${AGENT_FORWARDER_REPOS:-}"
forwarder_workflow="${AGENT_FORWARDER_WORKFLOW:-agentic-forward-to-control-plane.yml}"

if [[ -z "$control_repo" ]]; then
  echo "Set AGENT_CONTROL_REPO in config.env before enabling/disabling hosted workflows." >&2
  exit 2
fi

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

IFS=',' read -r -a control_workflows <<< "$control_workflows_csv"
for workflow in "${control_workflows[@]}"; do
  workflow="${workflow#"${workflow%%[![:space:]]*}"}"
  workflow="${workflow%"${workflow##*[![:space:]]}"}"
  [[ -n "$workflow" ]] || continue
  set_workflow "$control_repo" "$workflow"
done

IFS=',' read -r -a forwarder_repos <<< "$forwarder_repos_csv"
for repo in "${forwarder_repos[@]}"; do
  repo="${repo#"${repo%%[![:space:]]*}"}"
  repo="${repo%"${repo##*[![:space:]]}"}"
  [[ -n "$repo" ]] || continue
  set_workflow "$repo" "$forwarder_workflow"
done
