#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TASK_ROOT/engine"
export FUSE_PAPER_ADMIN_TOKEN="${FUSE_PAPER_ADMIN_TOKEN:-$(openssl rand -hex 32)}"
exec go run ./cmd/fuse-engine \
  -config config/paper.json -memory -paper-desk \
  -listen 127.0.0.1:8091 -origin http://127.0.0.1:3100 \
  -oracle wss://api.hyperliquid.xyz/ws "$@"
