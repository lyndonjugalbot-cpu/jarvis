# J.A.R.V.I.S.

A personal AI assistant you talk to and control with hand gestures. The full design is in
[JARVIS_Spec_Sheet.pdf](JARVIS_Spec_Sheet.pdf).

JARVIS answers through the Claude and ChatGPT subscriptions you already pay for. Free services
come next, and a pay-per-use API is only the last resort, with a monthly cap.

## Status

| Phase | State |
| --- | --- |
| 0. Setup | Done: core and HUD each start with one command |
| 1. Brain | Done: terminal chat on the Claude plan, tool registry, MCP tool server, time, web search, notes |
| 2. HUD + gestures | Next |
| 3-8 | Not started |

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
scripts/start.sh chat   # talk to JARVIS in the terminal
scripts/start.sh core   # core server for the HUD (http://127.0.0.1:8765/api/health)
scripts/start.sh hud    # HUD on http://127.0.0.1:5173
scripts/start.sh test   # backend tests
```

In the chat, `/status` shows the active provider and how much of your plan's usage windows
are used. Saving a note asks for a typed `y` first, standing in for the HUD's thumbs-up.

## How the brain stays on your subscription

- The core runs the official `claude` CLI headless (`claude -p`), signed in to your plan. It
  removes `ANTHROPIC_*` variables from the CLI's environment and refuses any CLI session that
  reports an API key, so this path can't bill the API.
- JARVIS's own tools are served over MCP on `127.0.0.1` with a fresh token each run. The CLI
  gets only those tools plus web search and web fetch: no shell, no file edits.
- When a plan's limit is reached, the router waits for the reset time the CLI reports and
  moves to the next provider. Phase 5 adds the ChatGPT plan, a local model and the capped
  paid API.

Settings are in `backend/config.toml`. Logs and notes are in `~/.jarvis/`.

## Layout

```
backend/   main.py, core.py, terminal.py, brain/ (router, providers), tools/ (registry, MCP server, tools), tests/
frontend/  Vite app: index.html, src/main.js, src/styles/hud.css
scripts/   setup.sh, start.sh
```
