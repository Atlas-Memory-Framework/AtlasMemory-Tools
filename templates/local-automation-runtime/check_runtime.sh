#!/usr/bin/env bash
set -u

runtime_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$runtime_dir" || exit 1

echo "HOME=$HOME"
echo "PWD=$PWD"
echo

for cmd in gh git python3 node npm playwright codex podman distrobox-host-exec; do
  if command -v "$cmd" >/dev/null 2>&1; then
    printf '%-20s %s\n' "$cmd" "$(command -v "$cmd")"
  else
    printf '%-20s %s\n' "$cmd" "MISSING"
  fi
done

echo
gh auth status 2>&1 || true

echo
if command -v podman >/dev/null 2>&1; then
  podman --version || true
elif command -v distrobox-host-exec >/dev/null 2>&1; then
  distrobox-host-exec podman --version || true
fi

echo
echo "Codex isolation preflight:"
codex_preflight_status=0
PYTHONPATH="$runtime_dir${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY' || codex_preflight_status=$?
import sys

import atlas_agent_common as common

metadata = common.codex_provider_metadata()
codex = metadata["codex"]
home = codex["home"]
validation = codex["validation"]

print(f"isolation_required={codex['isolation_required']}")
print(f"shared_home_allowed={codex['shared_home_allowed']}")
print(f"codex_home={home.get('redacted_path') or 'not configured'}")
print(f"codex_home_sha256={home.get('path_sha256') or 'not configured'}")
if codex.get("workspace_id"):
    workspace = validation.get("workspace") or {}
    print(f"workspace_pinned={bool(workspace.get('matched'))}")
if codex.get("auth_indicator"):
    print(f"auth_indicator={codex['auth_indicator']}")
for warning in validation.get("warnings") or []:
    print(f"WARN: {warning}")
if not validation.get("ok"):
    for error in validation.get("errors") or []:
        print(f"FAIL: {error}")
    sys.exit(1)
print("PASS: Codex home isolation check")
PY

exit "$codex_preflight_status"
