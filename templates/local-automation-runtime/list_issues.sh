#!/usr/bin/env bash
set -euo pipefail

repos_file="${1:-$HOME/agent-runtime/repos.txt}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is not installed or not on PATH in this environment." >&2
  exit 1
fi

gh auth status >/dev/null

while IFS= read -r repo; do
  [[ -n "${repo:-}" ]] || continue
  [[ "$repo" != \#* ]] || continue
  echo
  echo "## $repo"
  gh issue list \
    --repo "$repo" \
    --state open \
    --limit 20 \
    --json number,title,labels,author,updatedAt \
    --jq '.[] | "#\(.number)\t\(.updatedAt)\t@\(.author.login)\t[\([.labels[].name] | join(","))]\t\(.title)"'
done < "$repos_file"
