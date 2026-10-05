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
| 4. Real tools | Done: weather, files, system, Calendar and Gmail (after the one-time [Google setup](docs/google-setup.md)), reconnect flow |
| 5. Fallback chain | Done: ChatGPT plan (Codex), local Ollama model, capped paid Claude API, failover |
| 6. Memory | Done: facts, conversation history across restarts, local embeddings for recall, background summaries, remember/recall/forget |
| 7. Voice | Done: "Hey Jarvis" wake word, local speech-to-text and voice, barge-in, spoken yes/no for approvals |
| 8. Polish | Next |

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
scripts/start.sh google # connect Calendar and Gmail (after docs/google-setup.md)
scripts/start.sh test   # backend and gesture tests
```

In the chat, `/status` shows the active provider and how much of your plan's usage windows
are used. Saving a note asks for a typed `y` first, standing in for the HUD's thumbs-up.

## How the brain stays on your subscriptions

JARVIS tries providers in order: your **Claude plan** (`claude -p`), your **ChatGPT plan**
(`codex exec`), a free **local model** (Ollama), and last the **paid Claude API**, capped at
$10 a month by default.

- When a plan reaches its limit, JARVIS waits for the reset time that plan reports and uses the
  next provider meanwhile.
- The plan CLIs never see an API key, and JARVIS refuses either CLI if it's signed in with one,
  so they can't bill per token.
- The CLIs only get JARVIS's tools (over MCP on `127.0.0.1`, with a fresh token each run) plus
  their own web search: no shell, no file edits.

Details, setup for the local model and the paid key, and how to simulate limits are in
[docs/providers.md](docs/providers.md).

Settings are in `backend/config.toml`. Logs and notes are in `~/.jarvis/`.

## What JARVIS can do

| Area | Tools | Asks first |
| --- | --- | --- |
| Time and weather | `get_time`, `get_weather` (Open-Meteo; home is your time zone's city unless `[user] location` is set) | No |
| Calendar | `get_events`, `create_event` | Creating |
| Email | `search_email`, `read_email`, `draft_email`, `send_email` | Sending |
| Notes | `write_note`, `list_notes`, `read_note` | Writing |
| Files | `search_files` (Spotlight), `read_file` (text only), limited to `[tools] file_roots` | No |
| This computer | `system_stats`, `open_app`, `open_url` (http/https only) | No |
| Web | `web_search` (DuckDuckGo; for the local model and paid API; the plan CLIs use their own) | No |
| Memory | `remember`, `recall`, `forget` | Forgetting |
| Screen | `show_panel`, `close_panel` | No |
| Google account | `connect_google` | No |

Calendar and Gmail need a one-time setup of your own Google Cloud project:
[docs/google-setup.md](docs/google-setup.md), then `scripts/start.sh google`.

## Memory

JARVIS remembers across sessions, entirely on your computer (`~/.jarvis/jarvis.db`):

- **Facts** you tell it to keep (`remember`), such as your name, people, preferences. All of them
  go with every request.
- **Every exchange**, so a restart within `resume_hours` (default 6) continues the conversation.
  Older turns of a long session are summarized in the background, on your plans and never the
  paid API.
- **Recall by meaning:**
  - Facts, past exchanges, summaries and notes are embedded with a small local model
    (`BAAI/bge-small-en-v1.5`, 64 MB in `~/.jarvis/models`).
  - The five closest matches from earlier sessions go with each request (similarity 0.65 or
    more).
- **Forgetting:** "forget everything about the dentist" deletes matching facts, exchanges and
  summaries after you approve. Notes are kept.

Recalled memories are part of the request, so they go to whichever provider answers it.

## Voice

The core listens for **"Hey Jarvis"** whenever it runs (`scripts/start.sh core`). Say the wake
word, then your request; JARVIS answers out loud and on the HUD. Everything runs on your computer:

- **Wake word:** openWakeWord's "hey jarvis" model. About 1 ms per 80 ms of audio, so it can
  listen all the time.
- **Speech to text:** faster-whisper `base.en`.
- **Voice:** Piper `en_GB-alan-medium`, sentence by sentence, so it starts talking sooner.
  macOS `say` is the alternative (`[voice] tts = "say"`).
- **Interrupting:** say "Hey Jarvis" while JARVIS is talking to stop it and ask something else.
  Loudness alone can't do this, because the microphone also hears JARVIS's own voice.
- **Approvals:** during a voice request, JARVIS reads out the approval question and listens for
  yes or no. A thumbs-up or a click on the HUD works too; the first answer counts.
- **Mic indicator:** shows what it's doing (`"Hey Jarvis"`, listening, off). Click it to switch
  the microphone off and on.

Measured on this MacBook Air for a simple question: the voice starts about 2.5 s after you stop
talking (0.8 s to decide you've finished, 0.1 s to transcribe, about 1.5 s for the Claude plan
to answer). Requests that use tools take longer.

**First run:**
- The models download into `~/.jarvis/models`: about 200 MB, plus small wake-word files.
- macOS asks to let your terminal use the microphone. If you said no, the Mic indicator shows
  "unavailable". Allow it in **System Settings > Privacy & Security > Microphone**, then restart
  the core.

**Tuning in `[voice]`:**
- `wake_threshold`: raise it if JARVIS wakes by mistake, lower it if it misses you.
- `whisper_model = "small.en"`: more accurate, but slower and about 480 MB.
- `input_device` and `output_device`: pick a microphone and speakers.
- `enabled = false`: no voice at all.

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
backend/   main.py (server, /ws), core.py, hud_bridge.py, terminal.py, brain/ (router, providers, budget), memory/ (store, embeddings), voice/ (loop, engines, audio), tools/ (registry, MCP server, tools), auth/google.py, tests/
frontend/  Vite app: src/hud/ (scene, panels, cursor, transcript, confirm, debug, settings), src/gestures/ (tracker, pose, recognizer, arbiter, controller), src/net/socket.js, tests/
scripts/   setup.sh, start.sh
docs/      providers.md, gestures.md, protocol.md, google-setup.md
```
