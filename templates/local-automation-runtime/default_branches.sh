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
  branch="$(gh repo view "$repo" --json defaultBranchRef --jq .defaultBranchRef.name)"
  printf '%s\t%s\n' "$repo" "$branch"
done < "$repos_file"
