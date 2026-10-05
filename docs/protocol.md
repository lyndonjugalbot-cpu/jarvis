# HUD <-> core protocol

The HUD and the core talk over one WebSocket at `/ws`. In development the HUD reaches it
through the Vite proxy (`ws://127.0.0.1:5173/ws` -> `ws://127.0.0.1:8765/ws`). A built HUD is
served by the core itself.

Every message is JSON: `{ "type": string, "payload": object, "id": string }`.

## Connecting

1. **Origin check.** The core only listens on 127.0.0.1. It refuses (close code 4403) any
   connection whose `Origin` isn't one of:
   - `hud_origins` in `backend/config.toml` (the Vite dev server, by default);
   - the core's own address.

   This stops other websites open in the browser from connecting.
2. **Token in the first message.** Browsers can't put custom headers on a WebSocket, and tokens
   in URLs end up in logs. So the HUD's first message is
   `{ "type": "auth", "payload": { "token": "..." } }`. With no valid auth message within 2
   seconds, the core closes the connection with code 4401.

   The token is `JARVIS_TOKEN` in `backend/.env`, matched by `VITE_JARVIS_TOKEN` in
   `frontend/.env.local`. `scripts/setup.sh` writes both.
3. The core answers `auth_ok`, then sends the current `provider` and `state`.

If the connection drops, the HUD reconnects with backoff (0.5 s, doubling up to 5 s).

## HUD -> core

| type | payload | meaning |
| --- | --- | --- |
| `auth` | `{ "token": "..." }` | Must be the first message |
| `user_text` | `{ "text": "open my calendar" }` | A typed request; requests run one at a time |
| `confirm` | `{ "actionId": "a7", "approved": true }` | Answer to a `confirm_request`; the first HUD to answer decides |
| `gesture_event` | `{ "gesture": "swipe_right", "panelId": "p12" }` | Logged now, used as context later |
| `connect_google` | `{}` | Run Google's browser sign-in on the core's computer |
| `mic` | `{ "on": true }` | Switch the core's microphone on or off |

## Core -> HUD

| type | payload | meaning |
| --- | --- | --- |
| `auth_ok` | `{ "session": "3fa1c2d0" }` | Connected |
| `state` | `{ "state": "idle" \| "thinking" \| "listening" \| "speaking" }` | Drives the orb |
| `transcript` | `{ "role": "user" \| "jarvis", "text": "...", "provider", "tools", "seconds" }` | Conversation lines; `provider`, `tools` and `seconds` come with JARVIS's replies |
| `show_panel` | `{ "panel": { "id", "type", "title", "data" } }` | Open a panel, or update the one with that id |
| `update_panel` | `{ "panelId": "p12", "data": ... }` | Replace a panel's content |
| `close_panel` | `{ "panelId": "p12" }` | Close a panel |
| `confirm_request` | `{ "actionId": "a7", "summary": "Save a note titled \"Groceries\"?" }` | A risky tool is waiting for approval |
| `confirm_done` | `{ "actionId": "a7", "approved": false }` | Answered, timed out (30 s counts as no), or answered on another HUD; close the prompt |
| `provider` | `{ "active", "label", "paid", "coolingDown": [...], "order": [...] }` | Which model provider is answering, for the status bar |
| `mic` | `{ "state": "off" \| "starting" \| "wake" \| "listening" \| "unavailable", "message": "..." }` | The microphone's state, for the Mic indicator |
| `auth_needed` | `{ "service": "google", "message": "..." }` | Access was lost; the HUD shows a Connect button |
| `auth_done` | `{ "service": "google", "ok": true, "message": "..." }` | How the sign-in went |
| `error` | `{ "message": "..." }` | A friendly error to show |

`confirm_done` isn't in the spec's message table. It was added so every open HUD closes its
prompt when the request is settled.

## Panel types

The `show_panel` tool currently supports two types: `text` (a string; line breaks are kept)
and `list` (an array of short strings). Calendar, chart, image and web panels come in later
phases.
