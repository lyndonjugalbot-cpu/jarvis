#!/usr/bin/env bash
# One-time setup, safe to re-run: Python env, HUD packages, the shared token, sign-in checks.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="${JARVIS_HOME:-$HOME/.jarvis}"
# Documents syncs to iCloud, which makes big dependency folders slow. The Python env lives in
# $STATE, and node_modules is marked so iCloud skips it.
export UV_PROJECT_ENVIRONMENT="$STATE/venv"

need() { command -v "$1" >/dev/null || { echo "Missing $1. Install it with: $2" >&2; exit 1; }; }
need uv "brew install uv"
need npm "brew install node"
mkdir -p "$STATE"

echo "==> Python packages ($UV_PROJECT_ENVIRONMENT)"
(cd "$ROOT/backend" && uv sync)

echo "==> HUD packages"
mkdir -p "$ROOT/frontend/node_modules"
xattr -w 'com.apple.fileprovider.ignore#P' 1 "$ROOT/frontend/node_modules" 2>/dev/null || true
(cd "$ROOT/frontend" && npm install)

echo "==> Shared token (backend/.env and frontend/.env.local)"
ENV_FILE="$ROOT/backend/.env"
[ -f "$ENV_FILE" ] || cp "$ROOT/backend/.env.example" "$ENV_FILE"
TOKEN="$(sed -n 's/^JARVIS_TOKEN=//p' "$ENV_FILE")"
if [ -z "$TOKEN" ]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  if grep -q '^JARVIS_TOKEN=' "$ENV_FILE"; then
    sed -i '' "s/^JARVIS_TOKEN=.*/JARVIS_TOKEN=$TOKEN/" "$ENV_FILE"
  else
    printf 'JARVIS_TOKEN=%s\n' "$TOKEN" >>"$ENV_FILE"
  fi
fi
printf 'VITE_JARVIS_TOKEN=%s\n' "$TOKEN" >"$ROOT/frontend/.env.local"
chmod 600 "$ENV_FILE" "$ROOT/frontend/.env.local"

echo "==> Model sign-ins"
if command -v claude >/dev/null; then
  if env -u ANTHROPIC_API_KEY claude auth status --json 2>/dev/null | python3 -c '
import json, sys
s = json.load(sys.stdin)
sys.exit(0 if s.get("loggedIn") and s.get("authMethod") == "claude.ai" else 1)'; then
    echo "Claude CLI: signed in to a Claude plan"
  else
    echo "Claude CLI: not signed in to a Claude plan. Run: claude auth login"
  fi
else
  echo "Claude CLI not found. Install Claude Code first: https://claude.com/claude-code"
fi
if command -v codex >/dev/null; then
  echo "Codex CLI: $(codex login status 2>&1 | head -1)"
else
  echo "Codex CLI not found (needed from Phase 5): brew install codex"
fi

echo "Done. Next: scripts/start.sh chat"
