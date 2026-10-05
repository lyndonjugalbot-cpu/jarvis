# Model providers and cost

JARVIS asks one model provider at a time, in the order set in `backend/config.toml`
(`[providers] order`). The first available provider answers:

| # | Provider | How it runs | Cost |
| --- | --- | --- | --- |
| 1 | `claude_plan`: Claude plan (Pro/Max) | The official `claude` CLI, headless, one warm process | Included in your plan |
| 2 | `codex_plan`: ChatGPT plan (Plus/Pro) | The official `codex exec`, one process per request | Included in your plan |
| 3 | `local`: Ollama | A model on your own computer, through JARVIS's tool loop | Free, private, works offline |
| 4 | `paid_api`: Claude API | The `anthropic` SDK, JARVIS's tool loop, monthly cap | Pay per token, capped |

The status bar shows which provider answered. The paid tier adds an amber **PAID** badge with
this month's spend. Each answer in the transcript names the provider, and paid answers show
their cost.

## When a provider runs out

- **Usage limit:** the provider waits until the reset time it reported (Claude's
  `rate_limit_event`, or Codex's "try again in..." message), or 15 minutes if it didn't say.
  Meanwhile the request goes to the next provider.
- **Signed out or not set up:** skipped, and checked again in 15 minutes.
- **Any other error:** one retry, then the next provider.
- **Context:** JARVIS keeps the conversation itself. A provider taking over mid-conversation is
  given the recent turns, and a tool that already ran is not run again.

To try the chain without using up a plan, simulate limits when starting:

```sh
JARVIS_SIMULATE_LIMIT=claude_plan scripts/start.sh chat
JARVIS_SIMULATE_LIMIT=claude_plan,codex_plan scripts/start.sh core
```

## 1 and 2: your subscriptions

Both CLIs must be signed in to your plans: `claude auth login`, and `codex login` with ChatGPT.
JARVIS removes `ANTHROPIC_*` and `OPENAI_API_KEY`-style variables from their environment. It
refuses to use either CLI if it reports an API-key login, so neither can turn into
pay-per-token billing. Also turn off any pay-as-you-go overage on both plans; a plan limit
should be a clean stop.

What the CLIs can do:

- **Claude:** JARVIS's tools (over MCP, with a fresh token each run), plus web search and web fetch.
- **Codex:** the same tools, plus web search. Its shell tool is disabled, it runs in a read-only
  sandbox in an empty folder, and your own Codex config isn't loaded.

Neither CLI can run commands or change files except through JARVIS's tools, and JARVIS still
asks you before anything risky.

Your Claude Pro plan's usage windows are shared with your own Claude Code use. In the terminal
chat, `/status` shows how much of each window is used.

## 3: the local model

1. Install and start Ollama (https://ollama.com, or `brew install ollama && ollama serve`).
2. Pull a model that can call tools, once:

   ```sh
   ollama pull qwen3:8b   # about 5 GB on disk; needs about 8 GB of free memory to run
   ```

3. To use a different model, change `[providers.local] model`.

Until a model is pulled, JARVIS skips this provider. Local answers are slower and less capable
than the plans, but cost nothing and never leave your computer. The local model and the paid
API use JARVIS's free `web_search` tool (DuckDuckGo) for current information.

## 4: the paid Claude API

Only used when everything above is unavailable.

1. Create an API key at https://console.anthropic.com and add it to `backend/.env`:
   `ANTHROPIC_API_KEY=...`.
2. In the Console, set a monthly spend limit equal to `monthly_cap_usd` (default $10) as a hard
   backstop.

Settings in `[providers.paid_api]`:

- **`fallback`:**
  - `auto` (default) uses it whenever needed.
  - `ask` asks for approval once a day (Y, a click, or a thumbs up).
  - `off` never uses it.
- **`monthly_cap_usd`:** the cap.
  - Before every API call, JARVIS checks that the worst case still fits under the cap: the
    request's estimated size plus a full `max_tokens` answer, priced 25% high in case a
    refusal fallback model runs. Spend can therefore stop short of the cap but never pass it.
  - JARVIS warns at 80%. At 100% it switches the tier off until the 1st of next month.
- **`model`, `effort`:** default `claude-opus-5-5` at `low` effort, for quick, inexpensive
  answers.
  - Set `effort = "medium"` or `"high"` for harder questions.
  - If you change the model, update `input_usd_per_mtok` and `output_usd_per_mtok` too.
- **Refusal fallbacks:** requests include Anthropic's server-side refusal fallback
  (`fallbacks="default"`). If the model declines, a fallback model can still answer in the same
  call.

Spend is recorded per month in `~/.jarvis/jarvis.db`.
