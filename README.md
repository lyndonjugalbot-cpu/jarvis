# J.A.R.V.I.S.

A personal AI assistant you talk to and control with hand gestures. The full design is in
[JARVIS_Spec_Sheet.pdf](JARVIS_Spec_Sheet.pdf).

JARVIS answers through the Claude and ChatGPT subscriptions you already pay for. Free services
come next, and a pay-per-use API is only the last resort, with a monthly cap.

## Quick start

```sh
scripts/setup.sh    # once: packages, token, sign-in checks
scripts/start.sh    # starts JARVIS and opens the HUD at http://127.0.0.1:8765
```

Then say **"Hey Jarvis"**, press **/** to type, or press **C** to control it with your hands.

## Status

All eight phases of the spec's roadmap are built:

| Phase | What's there |
| --- | --- |
| 0. Setup | One-command start, setup script, shared token |
| 1. Brain | Claude plan through `claude -p`, tool registry, MCP tool server |
| 2. HUD and gestures | Three.js panels with bloom, MediaPipe hand tracking, gestures with the look-alike rules |
| 3. Connect | WebSocket link (Origin check, first-message token), panels from the core, approve/cancel prompt |
| 4. Real tools | Weather, files, system, Calendar and Gmail (after the [Google setup](docs/google-setup.md)) |
| 5. Fallback chain | ChatGPT plan, local Ollama model, paid Claude API with a monthly cap |
| 6. Memory | Facts, history across restarts, local-embedding recall, summaries, forget |
| 7. Voice | "Hey Jarvis", local speech-to-text and voice, barge-in, spoken approvals |
| 8. Polish | Calendar, chart and image panels, interface sounds, HUD settings, an uncluttered HUD |

### Measured against the spec's targets (section 10)

| Area | Target | Measured on this MacBook Air |
| --- | --- | --- |
| Gesture latency | under 100 ms | Engine: 2 µs per frame. The cursor follows each camera frame (33 ms at 30 fps, plus MediaPipe). Gestures wait 4 frames on purpose, to avoid accidental triggers. Not yet checked with a real camera. |
| Tracking frame rate | at least 25 fps | Shown live in the Gestures indicator, amber below 20 fps |
| Voice response | under 3 s for simple requests | About 2.5 s from the end of speech to the start of the reply (warm Claude CLI) |
| Wake word | under 1 false trigger per hour | Not measured yet; tune `wake_threshold` |
| Resource use | core idle under 500 MB; HUD 60 fps with 6 panels | HUD 60 fps with 6 panels. Core 340 MB without voice, about 770 MB with the voice models loaded (Whisper is about 260 MB). The Claude CLI is a separate process, about 290 MB. |
| Reliability | auto-reconnect; failures give a friendly spoken error | The HUD reconnects with backoff. Provider and tool failures come back as plain-language replies, spoken during voice requests. |

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
scripts/start.sh        # everything: the core serves the HUD and opens it in your browser
scripts/start.sh chat   # talk to JARVIS in the terminal
scripts/start.sh core   # core server only (http://127.0.0.1:8765), for HUD development
scripts/start.sh hud    # HUD dev server with live reload on http://127.0.0.1:5173
scripts/start.sh google # connect Calendar and Gmail (after docs/google-setup.md)
scripts/start.sh clear-logs  # delete the logs in ~/.jarvis/logs
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
| Screen | `show_panel`, `close_panel`, `show_model`, `close_model` | No |
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

`scripts/start.sh` opens it at http://127.0.0.1:8765. For HUD development, run `scripts/start.sh core` and
`scripts/start.sh hud` and open http://127.0.0.1:5173 instead.

The layout follows a dashboard concept: a status bar (gestures, frame rate, mic, core,
brain, clock); the panel slot and this computer's telemetry on the left; the conversation, the
hologram stage and the input bar in the middle; and on the right a globe marking home, system
status, the microphone's waveform, a history chart (CPU, or hand tracking while the camera is on)
and which modules are ready.

- **Panels:** text, lists, calendar agendas, bar and line charts, images and file results. They
  open in the slot on the left, two at a time; the one you looked at least recently moves to the
  dock. Drag one out to leave it floating; drop it back on the slot to dock it again.
- **Holographic models:** ask JARVIS to "show me a jet engine" (or a drone, or an arc reactor),
  or press **O**. Spread two pinched hands to break it into its parts and squeeze to put it back;
  pinch-drag to turn it; pinch a part for a description, and then ask JARVIS about "this part".
  Drop your own `.glb` files into `~/.jarvis/holograms` and ask for them by name. See
  [docs/gestures.md](docs/gestures.md#on-a-holographic-model).
- **Hologram:** the figure on the stage is `~/.jarvis/avatar.png` (any PNG with a transparent
  background; it isn't in the repo). Without one, an orb stands in. It reacts to listening,
  thinking and speaking, and the words beside it light up to match.
- **Settings (S):** interface sounds, the welcome panels, and every gesture threshold.

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
backend/   main.py (server, /ws), core.py, dashboard.py, hud_bridge.py, terminal.py, brain/ (router, providers, budget), memory/ (store, embeddings), voice/ (loop, engines, audio), tools/ (registry, MCP server, tools), auth/google.py, tests/
frontend/  Vite app: src/hud/ (scene, layout, frame, panels, hologram, model-view, holograms/, globe, widgets, conversation, cursor, confirm, debug, settings), src/gestures/ (tracker, pose, recognizer, arbiter, controller), src/net/socket.js, tests/
scripts/   setup.sh, start.sh
docs/      providers.md, gestures.md, protocol.md, google-setup.md
```
