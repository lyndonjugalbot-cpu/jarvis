"""Stands in for the `claude` CLI in tests, emitting the stream-json shapes the real CLI sends.

FAKE_CLAUDE_SCENARIO picks the behaviour; FAKE_CLAUDE_LOG (optional) records what it was given.
"""

import json
import os
import sys
import time

scenario = os.environ.get("FAKE_CLAUDE_SCENARIO", "ok")
args = sys.argv[1:]

if args[:2] == ["auth", "status"]:
    print(
        json.dumps(
            {
                "loggedIn": scenario != "logged_out",
                "authMethod": "apiKey" if scenario == "api_key_auth" else "claude.ai",
            }
        )
    )
    sys.exit(0)

if log_path := os.environ.get("FAKE_CLAUDE_LOG"):
    with open(log_path, "a") as f:
        f.write(
            json.dumps(
                {
                    "argv": args,
                    "has_api_key": "ANTHROPIC_API_KEY" in os.environ,
                    "nested_marker": "CLAUDECODE" in os.environ,
                }
            )
            + "\n"
        )


def emit(event: dict) -> None:
    print(json.dumps(event), flush=True)


for n, line in enumerate(sys.stdin, 1):
    content = json.loads(line)["message"]["content"]
    emit(
        {
            "type": "system",
            "subtype": "init",
            "apiKeySource": "ANTHROPIC_API_KEY" if scenario == "api_key_source" else "none",
            "mcp_servers": [
                {"name": "jarvis", "status": "failed" if scenario == "mcp_failed" else "connected"}
            ],
        }
    )
    if scenario == "hang":
        time.sleep(30)
    elif scenario == "crash":
        sys.stderr.write("boom\n")
        sys.exit(1)
    elif scenario == "limit":
        emit(
            {
                "type": "rate_limit_event",
                "rate_limit_info": {
                    "status": "rejected",
                    "resetsAt": 1791160200,
                    "rateLimitType": "five_hour",
                },
            }
        )
        emit(
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "You've hit your limit",
            }
        )
    else:
        emit(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "mcp__jarvis__get_time", "input": {}}]
                },
            }
        )
        emit(
            {
                "type": "rate_limit_event",
                "rate_limit_info": {
                    "status": "allowed",
                    "resetsAt": 1791160200,
                    "unifiedWindows": {"five_hour": {"utilization": 0.25, "resetsAt": 1791160200}},
                },
            }
        )
        emit(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": f"reply {n}: {content}",
            }
        )
