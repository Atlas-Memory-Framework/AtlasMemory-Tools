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

userns_args=("--userns=keep-id")
if [[ "$podman_cmd" == sudo* ]]; then
  userns_args=()
fi

echo
echo "+ $podman_cmd run --rm --network=slirp4netns localhost/codex-agent:latest codex --version"
$podman_cmd run --rm --network=slirp4netns localhost/codex-agent:latest codex --version

echo
tmp_codex_home="$(mktemp -d "$runtime_dir/codex-home-smoke.XXXXXX")"
trap 'rm -rf "$tmp_codex_home"' EXIT
cp -a "$codex_home"/. "$tmp_codex_home"/
chmod -R u+rwX,go-rwx "$tmp_codex_home"

echo "+ $podman_cmd run --rm ${userns_args[*]} --network=slirp4netns -v $tmp_codex_home:/home/agent/.codex:Z localhost/codex-agent:latest bash -lc 'test -r /home/agent/.codex/config.toml && touch /home/agent/.codex/.write-test'"
$podman_cmd run --rm "${userns_args[@]}" --network=slirp4netns \
  -v "$tmp_codex_home:/home/agent/.codex:Z" \
  localhost/codex-agent:latest \
  bash -lc 'test -r /home/agent/.codex/config.toml && touch /home/agent/.codex/.write-test'
