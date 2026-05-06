#!/usr/bin/env bash
set -euo pipefail

runtime_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
codex_home="${AGENT_CODEX_HOME:-$runtime_dir/codex-home}"

podman_cmd="${AGENT_PODMAN_CMD:-}"
if [[ -z "$podman_cmd" ]]; then
  if command -v podman >/dev/null 2>&1; then
    podman_cmd="podman"
  elif command -v distrobox-host-exec >/dev/null 2>&1; then
    podman_cmd="distrobox-host-exec podman"
  else
    echo "Neither podman nor distrobox-host-exec is available." >&2
    exit 1
  fi
fi

echo "+ $podman_cmd build -t localhost/codex-agent:latest $runtime_dir/container"
$podman_cmd build -t localhost/codex-agent:latest "$runtime_dir/container"

echo
echo "+ $podman_cmd run --rm localhost/codex-agent:latest codex --version"
$podman_cmd run --rm localhost/codex-agent:latest codex --version

echo
echo "+ $podman_cmd run --rm --userns=keep-id -v $codex_home:/home/agent/.codex:ro,Z localhost/codex-agent:latest test -r /home/agent/.codex/config.toml"
$podman_cmd run --rm --userns=keep-id \
  -v "$codex_home:/home/agent/.codex:ro,Z" \
  localhost/codex-agent:latest \
  test -r /home/agent/.codex/config.toml
