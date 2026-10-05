"""Stands in for the `codex` CLI in tests, emitting the JSONL shapes `codex exec --json` sends.

FAKE_CODEX_SCENARIO picks the behaviour; FAKE_CODEX_LOG (optional) records what it was given.
"""

import json
import os
import sys

scenario = os.environ.get("FAKE_CODEX_SCENARIO", "ok")
args = sys.argv[1:]

if args[:2] == ["login", "status"]:
    print(
        "Logged in using an API key" if scenario == "api_key_login" else "Logged in using ChatGPT"
    )
    sys.exit(0)

prompt = sys.stdin.read()
if log_path := os.environ.get("FAKE_CODEX_LOG"):
    with open(log_path, "a") as f:
        record = {
            "argv": args,
            "prompt": prompt,
            "has_openai_key": "OPENAI_API_KEY" in os.environ,
            "mcp_token": os.environ.get("JARVIS_MCP_TOKEN", ""),
        }
        f.write(json.dumps(record) + "\n")


def emit(event: dict) -> None:
    print(json.dumps(event), flush=True)


emit({"type": "thread.started", "thread_id": "t1"})
emit(
    {"type": "item.completed", "item": {"id": "i0", "type": "error", "message": "a config warning"}}
)
emit({"type": "turn.started"})
if scenario == "limit":
    emit(
        {
            "type": "turn.failed",
            "error": {"message": "You've hit your usage limit. Try again in 2 hours 30 minutes."},
        }
    )
elif scenario == "crash":
    sys.stderr.write("thread panicked\n")
    sys.exit(2)
else:
    tool_call = {"id": "i1", "type": "mcp_tool_call", "server": "jarvis", "tool": "get_time"}
    last_line = prompt.strip().splitlines()[-1]
    answer = {"id": "i2", "type": "agent_message", "text": f"codex says: {last_line}"}
    emit({"type": "item.completed", "item": tool_call})
    emit({"type": "item.completed", "item": answer})
    emit({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 5}})
