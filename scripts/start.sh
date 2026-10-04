#!/usr/bin/env bash
# Start a part of JARVIS:
#   scripts/start.sh core    core server for the HUD
#   scripts/start.sh hud     HUD dev server on http://127.0.0.1:5173
#   scripts/start.sh test    backend tests (extra args go to pytest)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="${JARVIS_HOME:-$HOME/.jarvis}"
PY="$STATE/venv/bin/python"
[ -x "$PY" ] || { echo "Run scripts/setup.sh first." >&2; exit 1; }

case "${1:-}" in
  core) cd "$ROOT/backend" && exec "$PY" main.py serve ;;
  hud) cd "$ROOT/frontend" && exec npm run dev ;;
  test) cd "$ROOT/backend" && exec "$PY" -m pytest "${@:2}" ;;
  *)
    echo "Usage: scripts/start.sh core|hud|test" >&2
    exit 2
    ;;
esac
