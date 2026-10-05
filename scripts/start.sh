#!/usr/bin/env bash
# Start a part of JARVIS:
#   scripts/start.sh chat    terminal chat (Phase 1)
#   scripts/start.sh core    core server for the HUD
#   scripts/start.sh hud     HUD dev server on http://127.0.0.1:5173
#   scripts/start.sh google  connect Calendar and Gmail (see docs/google-setup.md)
#   scripts/start.sh test    backend and gesture tests
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# The Python env stays in ~/.jarvis/venv even when JARVIS_HOME points the data somewhere else.
PY="${JARVIS_VENV:-$HOME/.jarvis/venv}/bin/python"
[ -x "$PY" ] || { echo "Run scripts/setup.sh first." >&2; exit 1; }

case "${1:-}" in
  chat) cd "$ROOT/backend" && exec "$PY" main.py chat ;;
  core) cd "$ROOT/backend" && exec "$PY" main.py serve ;;
  hud) cd "$ROOT/frontend" && exec npm run dev ;;
  google) cd "$ROOT/backend" && exec "$PY" main.py google-login ;;
  test)
    (cd "$ROOT/backend" && "$PY" -m pytest -q "${@:2}")
    cd "$ROOT/frontend" && exec npm test --silent
    ;;
  *)
    echo "Usage: scripts/start.sh chat|core|hud|google|test" >&2
    exit 2
    ;;
esac
