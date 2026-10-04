import asyncio
import json
from typing import Annotated

from pydantic import Field

from tools.registry import ToolError, ToolRegistry, tool


def make_tools(log: list):
    @tool()
    async def add(a: int, b: Annotated[int, Field(description="second number")] = 2) -> int:
        """Add two numbers."""
        log.append(("add", a, b))
        return a + b

    @tool(confirm=True, summary=lambda args: f"Delete {args['what']}?")
    async def delete(what: str) -> str:
        """Delete something."""
        log.append(("delete", what))
        return f"deleted {what}"

    @tool()
    async def broken() -> str:
        """Always fails."""
        raise ToolError("nothing to see")

    return [add, delete, broken]


def approve(answer: bool, asked: list | None = None):
    async def confirmer(summary: str) -> bool:
        if asked is not None:
            asked.append(summary)
        return answer

    return confirmer


def test_schema_comes_from_type_hints_and_docstring():
    add = make_tools([])[0]
    assert add.description == "Add two numbers."
    assert add.input_schema == {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer", "default": 2, "description": "second number"},
        },
        "required": ["a"],
        "additionalProperties": False,
    }


async def test_runs_and_returns_json():
    registry = ToolRegistry(make_tools([]))
    result = await registry.run("add", {"a": 1})
    assert (result.text, result.is_error) == ("3", False)


async def test_bad_arguments_and_unknown_tools_are_errors():
    registry = ToolRegistry(make_tools([]))
    assert (await registry.run("add", {"a": "x"})).is_error
    assert (await registry.run("add", {"a": 1, "extra": 1})).is_error
    assert (await registry.run("nope", {})).is_error


async def test_tool_error_message_reaches_the_model():
    result = await ToolRegistry(make_tools([])).run("broken", {})
    assert (result.text, result.is_error) == ("nothing to see", True)


async def test_confirmed_tool_runs_only_when_approved():
    log, asked = [], []
    yes = ToolRegistry(make_tools(log), confirmer=approve(True, asked))
    assert (await yes.run("delete", {"what": "x"})).text == "deleted x"
    assert asked == ["Delete x?"]

    no = ToolRegistry(make_tools(log), confirmer=approve(False))
    result = await no.run("delete", {"what": "y"})
    assert result.is_error and "not approve" in result.text
    assert log == [("delete", "x")]


async def test_no_confirmer_means_no():
    log = []
    assert (await ToolRegistry(make_tools(log)).run("delete", {"what": "x"})).is_error
    assert log == []


async def test_confirmation_times_out_as_no():
    async def slow(summary: str) -> bool:
        await asyncio.sleep(5)
        return True

    log = []
    registry = ToolRegistry(make_tools(log), confirmer=slow, confirm_timeout_s=0.05)
    assert (await registry.run("delete", {"what": "x"})).is_error
    assert log == []


async def test_same_call_in_a_turn_runs_once():
    log, asked = [], []
    registry = ToolRegistry(make_tools(log), confirmer=approve(True, asked))
    registry.begin_turn("t1")
    await registry.run("delete", {"what": "x"})
    registry.begin_turn("t1")  # e.g. the router retrying the turn on another provider
    again = await registry.run("delete", {"what": "x"})
    assert again.text == "deleted x"
    assert log == [("delete", "x")] and len(asked) == 1
    assert [c.reused for c in registry.turn_calls] == [False, True]

    registry.begin_turn("t2")
    await registry.run("delete", {"what": "x"})
    assert len(log) == 2 and len(asked) == 2


async def test_results_are_json_text():
    @tool()
    async def info() -> dict:
        """Info."""
        return {"ok": True}

    assert json.loads((await ToolRegistry([info]).run("info", {})).text) == {"ok": True}
