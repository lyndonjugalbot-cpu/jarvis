#!/usr/bin/env bash
# Start JARVIS:
#   scripts/start.sh             everything: the core serves the HUD at http://127.0.0.1:8765
#                                (rebuilt when its source changed) and opens it in the browser
#   scripts/start.sh chat        terminal chat
#   scripts/start.sh core        core server only (for HUD development)
#   scripts/start.sh hud         HUD dev server with live reload on http://127.0.0.1:5173
#   scripts/start.sh google      connect Calendar and Gmail (see docs/google-setup.md)
#   scripts/start.sh clear-logs  delete the log files in ~/.jarvis/logs
#   scripts/start.sh test        backend and gesture tests
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# The Python env stays in ~/.jarvis/venv even when JARVIS_HOME points the data somewhere else.
PY="${JARVIS_VENV:-$HOME/.jarvis/venv}/bin/python"
# Keep compiled Python files out of the iCloud-synced checkout (writing them there is slow).
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-$HOME/.jarvis/pycache}"
[ -x "$PY" ] || { echo "Run scripts/setup.sh first." >&2; exit 1; }

build_hud_if_stale() {
  local dist="$ROOT/frontend/dist/index.html"
  if [ ! -f "$dist" ] || [ -n "$(find "$ROOT/frontend/src" "$ROOT/frontend/index.html" "$ROOT/frontend/.env.local" -newer "$dist" -print -quit 2>/dev/null)" ]; then
    echo "Building the HUD..."
    (cd "$ROOT/frontend" && npm run build --silent)
    xattr -w 'com.apple.fileprovider.ignore#P' 1 "$ROOT/frontend/dist" 2>/dev/null || true
  fi
}

open_when_ready() {
  local url="http://127.0.0.1:${JARVIS_PORT:-8765}"
  for _ in $(seq 1 120); do
    if curl -sf "$url/api/health" >/dev/null 2>&1; then
      open "$url" 2>/dev/null || echo "JARVIS is ready at $url"
      return
    fi
    sleep 0.5
  done
}

case "${1:-all}" in
  all)
    build_hud_if_stale
    open_when_ready &
    cd "$ROOT/backend" && exec "$PY" main.py serve
    ;;
  chat) cd "$ROOT/backend" && exec "$PY" main.py chat ;;
  core) cd "$ROOT/backend" && exec "$PY" main.py serve ;;
  hud) cd "$ROOT/frontend" && exec npm run dev ;;
  google) cd "$ROOT/backend" && exec "$PY" main.py google-login ;;
  clear-logs) cd "$ROOT/backend" && exec "$PY" main.py clear-logs ;;
  test)
    (cd "$ROOT/backend" && "$PY" -m pytest -q "${@:2}")
    cd "$ROOT/frontend" && exec npm test --silent
    ;;
  *)
    echo "Usage: scripts/start.sh [all|chat|core|hud|google|clear-logs|test]" >&2
    exit 2
    ;;
esac
