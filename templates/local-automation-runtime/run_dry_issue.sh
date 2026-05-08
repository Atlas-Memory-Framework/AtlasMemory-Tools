#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 OWNER/REPO ISSUE_NUMBER" >&2
  exit 2
fi

repo="$1"
issue="$2"

base="$(gh repo view "$repo" --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null || true)"
base="${base:-${AGENT_BASE_BRANCH:-main}}"

for label_color in \
  "agent:ready 0E8A16" \
  "agent:running FBCA04" \
  "agent:done 5319E7" \
  "agent:failed B60205" \
  "agent:allow-workflows C5DEF5" \
  "agent:allow-infra C5DEF5" \
  "agent:allow-large C5DEF5"
do
  label="${label_color% *}"
  color="${label_color#* }"
  gh label create "$label" --repo "$repo" --color "$color" >/dev/null 2>&1 || true
done

tmp_env="$(mktemp)"
sed \
  -e "s|^AGENT_REPO=.*|AGENT_REPO=\"$repo\"|" \
  -e "s|^AGENT_BASE_BRANCH=.*|AGENT_BASE_BRANCH=\"$base\"|" \
  "$HOME/agent-runtime/config.env" > "$tmp_env"

echo "Queueing $repo#$issue with default base $base for local dry run"
echo "Issue body Base branch metadata takes precedence when present."
gh issue edit "$issue" --repo "$repo" --remove-label "agent:done" >/dev/null 2>&1 || true
gh issue edit "$issue" --repo "$repo" --remove-label "agent:failed" >/dev/null 2>&1 || true
gh issue edit "$issue" --repo "$repo" --add-label "agent:ready"

set -a
source "$tmp_env"
set +a
rm -f "$tmp_env"

"$HOME/.local/bin/atlas-agent-worker" --once --issue "$issue"
