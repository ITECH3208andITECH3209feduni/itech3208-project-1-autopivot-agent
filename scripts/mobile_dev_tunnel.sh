#!/usr/bin/env bash
# Run this ON YOUR MAC, not on the pod.
#
#   bash scripts/mobile_dev_tunnel.sh root@<pod-ip> <ssh-port>
#
# Forwards this Mac's own port 8000 to the RunPod pod's port 8000 over SSH.
# This is the whole trick: `lib/api/api_client.dart`'s defaultBaseUrl()
# already returns http://localhost:8000 on iOS, unconditionally, because the
# iOS Simulator shares this Mac's own network stack rather than having one of
# its own — unlike a physical device, or Android's emulator, which needs the
# 10.0.2.2 alias instead. So once this tunnel is up, the real app just works
# with no URL to find, copy or paste anywhere, on either side.
#
# Why this exists alongside the tunnel/proxy URLs runpod_up.sh prints: those
# both need something outside your control — the cloudflared URL regenerates
# every restart, and the stable proxy URL needs a RunPod dashboard setting
# neither of us can flip from a script. This needs neither. It does need the
# pod's SSH connection details, fetched fresh each time from RunPod's own
# console (pod → Connect → "SSH over exposed TCP" — not the ssh.runpod.io
# proxy variant, which does not support port forwarding at all).
#
# Only reaches the Simulator, because only the Simulator shares this Mac's
# loopback interface. A physical iPhone is its own device on its own network
# and needs a different setup — not this script.

set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: bash scripts/mobile_dev_tunnel.sh <user@pod-ip> <ssh-port> [identity-file]" >&2
  echo "  Get these from: RunPod console → your pod → Connect → \"SSH over exposed TCP\"" >&2
  exit 1
fi

HOST="$1"
PORT="$2"
IDENTITY="${3:-$HOME/.ssh/id_ed25519}"

[ -f "$IDENTITY" ] || {
  echo "No identity file at $IDENTITY — pass the right one as a third argument," >&2
  echo "or check which key RunPod has on file for this pod." >&2
  exit 1
}

echo "Forwarding localhost:8000 → ${HOST}:8000 via SSH on port $PORT."
echo "Leave this running for the whole testing session — closing it drops the app's connection."
echo "In another terminal: cd mobile && flutter run -d \"iPhone 17\""
echo

exec ssh -N -L 8000:127.0.0.1:8000 "$HOST" -p "$PORT" -i "$IDENTITY"
