# J.A.R.V.I.S.

A personal AI assistant you talk to and control with hand gestures. The full design is in
[JARVIS_Spec_Sheet.pdf](JARVIS_Spec_Sheet.pdf).

JARVIS answers through the Claude and ChatGPT subscriptions you already pay for. Free services
come next, and a pay-per-use API is only the last resort, with a monthly cap.

## Status

| Phase | State |
| --- | --- |
| 0. Setup | Done: core and HUD each start with one command |
| 1. Brain | Next |
| 2-8 | Not started |

## Requirements

- macOS, [uv](https://docs.astral.sh/uv/) and Node.js (`brew install uv node`)
- Claude Code signed in to a Claude Pro or Max plan (`claude auth login`)
- Codex CLI signed in with ChatGPT, from Phase 5 (`codex login`)

## Setup

```sh
scripts/setup.sh
```

This installs the Python packages into `~/.jarvis/venv` and the HUD packages into
`frontend/node_modules`. Documents syncs to iCloud, so the venv stays outside it and
`node_modules` is marked so iCloud skips it. The script also writes the shared token to
`backend/.env` and `frontend/.env.local` (both gitignored) and checks the CLI sign-ins.

## Run

```sh
scripts/start.sh core   # core server for the HUD (http://127.0.0.1:8765/api/health)
scripts/start.sh hud    # HUD on http://127.0.0.1:5173
scripts/start.sh test   # backend tests
```

Settings are in `backend/config.toml`. Logs go to `~/.jarvis/logs/`.

## Layout

```
backend/   main.py (core server), config.py, events.py, tests/
frontend/  Vite app: index.html, src/main.js, src/styles/hud.css
scripts/   setup.sh, start.sh
```
