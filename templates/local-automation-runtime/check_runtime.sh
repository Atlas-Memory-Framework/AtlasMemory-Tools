#!/usr/bin/env bash
set -u

echo "HOME=$HOME"
echo "PWD=$PWD"
echo

for cmd in gh git python3 node npm codex podman distrobox-host-exec; do
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
