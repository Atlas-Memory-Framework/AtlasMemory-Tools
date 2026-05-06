#!/usr/bin/env bash
set -euo pipefail

runtime_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
parallel_dir="$runtime_dir/jobs/parallel-orchestrators"
mkdir -p "$parallel_dir"
max_per_repo="${MAX_PER_REPO:-1}"

common_args=(
  --daemon
  --publish
  --inspect-failed
  --auto-create-missing-base
  --triage-needs-human
  --triage-apply-stale
  --triage-approve-review-before-dispatch
  --triage-teams-preview
  --triage-post-teams
  --auto-queue-label status:ready
  --auto-queue-max 1
  --max-per-repo 1
  --limit 100
)

repo_file="${1:-$runtime_dir/repos.txt}"
pid_file="$parallel_dir/pids.txt"
: > "$pid_file"

while IFS= read -r repo; do
  repo="${repo%%#*}"
  repo="$(printf '%s' "$repo" | xargs)"
  [[ -z "$repo" ]] && continue

  safe_name="${repo//\//__}"
  shard_file="$parallel_dir/$safe_name.repos.txt"
  summary_file="$runtime_dir/jobs/local-needs-human-summary-$safe_name.json"
  for lane in $(seq 1 "$max_per_repo"); do
    log_file="$runtime_dir/logs/orchestrator-$safe_name-lane-$lane-$(date -u +%Y%m%dT%H%M%SZ).log"

    printf '%s\n' "$repo" > "$shard_file"
    (
      cd "$runtime_dir"
      ./atlas-agent-orchestrator \
        "${common_args[@]}" \
        --repos-file "$shard_file" \
        --triage-summary "$summary_file"
    ) > "$log_file" 2>&1 &
    pid=$!
    printf '%s %s %s\n' "$pid" "$repo/lane-$lane" "$log_file" | tee -a "$pid_file"
  done
done < "$repo_file"

echo "Started parallel orchestrators. PID file: $pid_file"
