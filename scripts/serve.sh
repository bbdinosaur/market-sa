#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${PORT:-8765}"
HOST="${HOST:-127.0.0.1}"
exec "$ROOT/.venv/bin/python" -m market_sa serve --host "$HOST" --port "$PORT"
