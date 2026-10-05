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
| 2. HUD + gestures | Done: Three.js panels with bloom, webcam hand tracking, gestures with the 7.1 rules, demo, recorder |
| 3. Connect | Done: WebSocket link (Origin check, first-message token), typing in the HUD, panels from the core, approve/cancel prompt, orb states, provider badge |
| 4. Real tools | Next |
| 5-8 | Not started |

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
scripts/start.sh test   # backend and gesture tests
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

## The HUD

Start the core and the HUD in two terminals, then open http://127.0.0.1:5173:

```sh
scripts/start.sh core
scripts/start.sh hud
```

- Press **/** to type to JARVIS. Answers worth reading open as panels.
- When JARVIS wants to do something risky, like saving a note, a prompt asks first. Approve with
  a thumbs up, a click or **Y**; cancel with a thumbs down or **N**. 30 seconds of silence counts
  as no.
- Press **C** to start the camera, then hold up an open palm for half a second to arm gestures.
- Press **P** to watch a scripted gesture demo.
- Press **?** for every key.
- The mouse also works: drag panels, and double-click to maximize.

Hand tracking runs in the browser with MediaPipe; video never leaves the machine. The first
`npm run dev` downloads the hand model (~8 MB) into `frontend/public/models/`. See
[docs/gestures.md](docs/gestures.md) for the gesture rules, tuning and recording sessions for tests,
and [docs/protocol.md](docs/protocol.md) for the WebSocket messages.

## Layout

```
backend/   main.py (server, /ws), core.py, hud_bridge.py, terminal.py, brain/ (router, providers), tools/ (registry, MCP server, tools), tests/
frontend/  Vite app: src/hud/ (scene, panels, cursor, transcript, confirm, debug, settings), src/gestures/ (tracker, pose, recognizer, arbiter, controller), src/net/socket.js, tests/
scripts/   setup.sh, start.sh
docs/      gestures.md, protocol.md
```
