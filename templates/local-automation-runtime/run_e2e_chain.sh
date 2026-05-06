#!/usr/bin/env bash
set -euo pipefail

runtime_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chain_id="$(date -u +%Y%m%dT%H%M%SZ)"
chain_dir="$runtime_dir/jobs/e2e-chain-$chain_id"
mkdir -p "$chain_dir" "$runtime_dir/logs"

apply=false
merge=false
close_issues=false
allow_no_checks=false
cycles=1
repo_file="$runtime_dir/repos.txt"
max_per_repo=1
required_checks_file="$runtime_dir/required-checks.json"
post_cycle_summary=false
post_triage_teams_per_repo=false
review=false
review_apply=false
require_review_approval=false
review_label="agent:review-approved"

usage() {
  cat <<'EOF'
Usage: ./run_e2e_chain.sh [options]

Runs one bounded end-to-end pass:
  1. build issues in parallel, one orchestrator per repo
  2. optionally review/classify local-agent PRs
  3. finalize local-agent PRs
  4. optionally merge and close linked issues

Options:
  --apply             Apply finalizer actions. Without this, finalizer is dry-run.
  --merge             Merge eligible PRs during finalization.
  --close-issues      Close linked issues after successful merges.
  --allow-no-checks   Allow finalizing PRs with no reported checks.
  --cycles N          Repeat build+finalize N times. Default: 1.
  --repos-file PATH   Repo list to shard. Default: repos.txt.
  --max-per-repo N    Max issues each repo orchestrator may process per cycle. Default: 1.
  --required-checks-file PATH
                      Repo-to-required-checks JSON for finalization.
  --post-cycle-summary
                      Post one Teams summary after each cycle.
  --post-triage-teams-per-repo
                      Restore old noisy per-repo triage Teams posts for debugging.
  --review            Run atlas-agent-review before finalization.
  --review-apply      Apply review labels/comments. Implies --review.
  --require-review-approval
                      Finalizer requires agent:review-approved before ready/merge.
  --review-label NAME Review approval label required by finalizer.
                      Default: agent:review-approved.
  -h, --help          Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      apply=true
      shift
      ;;
    --merge)
      merge=true
      shift
      ;;
    --close-issues)
      close_issues=true
      shift
      ;;
    --allow-no-checks)
      allow_no_checks=true
      shift
      ;;
    --cycles)
      cycles="${2:?--cycles requires a value}"
      shift 2
      ;;
    --repos-file)
      repo_file="${2:?--repos-file requires a value}"
      shift 2
      ;;
    --max-per-repo)
      max_per_repo="${2:?--max-per-repo requires a value}"
      shift 2
      ;;
    --required-checks-file)
      required_checks_file="${2:?--required-checks-file requires a value}"
      shift 2
      ;;
    --post-cycle-summary)
      post_cycle_summary=true
      shift
      ;;
    --post-triage-teams-per-repo)
      post_triage_teams_per_repo=true
      shift
      ;;
    --review)
      review=true
      shift
      ;;
    --review-apply)
      review=true
      review_apply=true
      shift
      ;;
    --require-review-approval)
      require_review_approval=true
      shift
      ;;
    --review-label)
      review_label="${2:?--review-label requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "$cycles" =~ ^[0-9]+$ ]] || [[ "$cycles" -lt 1 ]]; then
  echo "--cycles must be a positive integer" >&2
  exit 2
fi
if ! [[ "$max_per_repo" =~ ^[0-9]+$ ]] || [[ "$max_per_repo" -lt 1 ]]; then
  echo "--max-per-repo must be a positive integer" >&2
  exit 2
fi

run_build_cycle() {
  local cycle="$1"
  local pid_file="$chain_dir/build-cycle-$cycle.pids"
  local result_file="$chain_dir/build-cycle-$cycle.results.tsv"
  : > "$pid_file"
  : > "$result_file"

  while IFS= read -r repo; do
    repo="${repo%%#*}"
    repo="$(printf '%s' "$repo" | xargs)"
    [[ -z "$repo" ]] && continue

    local safe_name="${repo//\//__}"
    local shard_file="$chain_dir/$safe_name.repos.txt"
    local summary_file="$chain_dir/local-needs-human-summary-$safe_name-cycle-$cycle.json"
    printf '%s\n' "$repo" > "$shard_file"
    for lane in $(seq 1 "$max_per_repo"); do
      local log_file="$runtime_dir/logs/e2e-chain-$chain_id-$safe_name-cycle-$cycle-lane-$lane.log"
      local triage_args=()
      if $post_triage_teams_per_repo; then
        triage_args+=(--triage-teams-preview --triage-post-teams)
      fi
      (
        cd "$runtime_dir"
        ./atlas-agent-orchestrator \
          --once \
          --publish \
          --inspect-failed \
          --auto-create-missing-base \
          --triage-needs-human \
          --triage-apply-stale \
          --triage-approve-review-before-dispatch \
          --triage-summary "$summary_file" \
          "${triage_args[@]}" \
          --auto-queue-label status:ready \
          --auto-queue-max 1 \
          --max-per-repo 1 \
          --limit 100 \
          --repos-file "$shard_file"
      ) > "$log_file" 2>&1 &
      printf '%s %s %s\n' "$!" "$repo/lane-$lane" "$log_file" | tee -a "$pid_file"
    done
  done < "$repo_file"

  local failed=0
  while read -r pid repo log_file; do
    [[ -z "${pid:-}" ]] && continue
    if wait "$pid"; then
      echo "BUILD OK $repo :: $log_file"
      printf 'ok\t%s\t%s\n' "$repo" "$log_file" >> "$result_file"
    else
      failed=1
      echo "BUILD FAILED $repo :: $log_file" >&2
      printf 'failed\t%s\t%s\n' "$repo" "$log_file" >> "$result_file"
    fi
  done < "$pid_file"
  return "$failed"
}

run_review_cycle() {
  local cycle="$1"
  local log_file="$runtime_dir/logs/e2e-chain-$chain_id-review-cycle-$cycle.log"
  local summary_file="$chain_dir/review-cycle-$cycle.json"
  local args=(--repos-file "$repo_file" --required-checks-file "$required_checks_file" --summary "$summary_file")
  if $review_apply; then
    args+=(--apply)
  fi

  (
    cd "$runtime_dir"
    ./atlas-agent-review "${args[@]}"
  ) | tee "$log_file"
}

run_finalize_cycle() {
  local cycle="$1"
  local log_file="$runtime_dir/logs/e2e-chain-$chain_id-finalize-cycle-$cycle.log"
  local summary_file="$chain_dir/finalize-cycle-$cycle.json"
  local args=()
  if $apply; then
    args+=(--apply)
  fi
  if $merge; then
    args+=(--merge)
  fi
  if $close_issues; then
    args+=(--close-issues)
  fi
  if $allow_no_checks; then
    args+=(--allow-no-checks)
  fi
  if $require_review_approval; then
    args+=(--require-review-label "$review_label")
  fi

  (
    cd "$runtime_dir"
    ./atlas-agent-finalize "${args[@]}" --required-checks-file "$required_checks_file" --summary "$summary_file"
  ) | tee "$log_file"
}

run_cycle_summary() {
  local cycle="$1"
  local output_file="$chain_dir/cycle-$cycle-summary.json"
  local args=(--chain-dir "$chain_dir" --cycle "$cycle" --output "$output_file")
  if $post_cycle_summary; then
    args+=(--post-teams)
  fi
  (
    cd "$runtime_dir"
    ./atlas-agent-cycle-summary "${args[@]}"
  )
}

for cycle in $(seq 1 "$cycles"); do
  echo "=== E2E cycle $cycle/$cycles: parallel build ==="
  run_build_cycle "$cycle"
  if $review; then
    echo "=== E2E cycle $cycle/$cycles: review ==="
    run_review_cycle "$cycle"
  fi
  echo "=== E2E cycle $cycle/$cycles: finalize ==="
  run_finalize_cycle "$cycle"
  echo "=== E2E cycle $cycle/$cycles: summary ==="
  run_cycle_summary "$cycle"
done

echo "E2E chain complete. Logs are under $runtime_dir/logs; chain state is $chain_dir"
