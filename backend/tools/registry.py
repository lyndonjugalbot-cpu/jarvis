"""The `@tool` decorator and the registry that runs tools for every model provider.

A tool is a plain async function with type hints and a docstring. `@tool` turns it into a
`ToolSpec` with a JSON schema; `ToolRegistry.run` validates arguments, asks for confirmation
when the tool needs it, and remembers results per turn so a retry on another provider never
runs the same call twice.
"""

import asyncio
import inspect
import json
import logging
import time
import typing
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

log = logging.getLogger(__name__)

Confirmer = Callable[[str], Awaitable[bool]]


class ToolError(Exception):
    """A failure the model should see as a plain message (bad input, missing note, ...)."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    fn: Callable[..., Awaitable[Any]]
    args_model: type[BaseModel]
    confirm: bool = False
    summary: Callable[[dict[str, Any]], str] | None = None

    @property
    def input_schema(self) -> dict[str, Any]:
        return _strip_titles(self.args_model.model_json_schema())

    def describe_action(self, args: dict[str, Any]) -> str:
        if self.summary:
            return self.summary(args)
        shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"Run {self.name}({shown})?"

    async def __call__(self, **kwargs: Any) -> Any:
        return await self.fn(**kwargs)


def tool(
    *,
    confirm: bool = False,
    summary: Callable[[dict[str, Any]], str] | None = None,
    name: str | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], ToolSpec]:
    """Turn an async function into a ToolSpec.

    `confirm=True` means a person must approve every call before it runs.
    """

    def wrap(fn: Callable[..., Awaitable[Any]]) -> ToolSpec:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"tool {fn.__name__} must be an async function")
        return ToolSpec(
            name=name or fn.__name__,
            description=inspect.getdoc(fn) or "",
            fn=fn,
            args_model=_args_model(fn),
            confirm=confirm,
            summary=summary,
        )

    return wrap


def _args_model(fn: Callable[..., Any]) -> type[BaseModel]:
    hints = typing.get_type_hints(fn, include_extras=True)
    fields: dict[str, Any] = {}
    for pname, param in inspect.signature(fn).parameters.items():
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[pname] = (hints.get(pname, Any), default)
    return create_model(f"{fn.__name__}_args", __config__=ConfigDict(extra="forbid"), **fields)


def _strip_titles(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _strip_titles(v) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [_strip_titles(v) for v in schema]
    return schema


@dataclass(frozen=True)
class ToolResult:
    text: str
    is_error: bool = False


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    is_error: bool
    duration_s: float
    reused: bool = False


@dataclass
class _Turn:
    id: str | None = None
    results: dict[tuple[str, str], ToolResult] = field(default_factory=dict)
    calls: list[ToolCall] = field(default_factory=list)


class ToolRegistry:
    def __init__(
        self,
        specs: Iterable[ToolSpec],
        *,
        confirmer: Confirmer | None = None,
        confirm_timeout_s: float = 30.0,
    ) -> None:
        self._specs = {s.name: s for s in specs}
        self._confirmer = confirmer
        self._confirm_timeout_s = confirm_timeout_s
        self._confirm_lock = asyncio.Lock()
        self._turn = _Turn()
        self.active_calls = 0

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def begin_turn(self, turn_id: str) -> None:
        """Start remembering results for a new turn. The same id keeps the existing memory."""
        if turn_id != self._turn.id:
            self._turn = _Turn(id=turn_id)

    @property
    def turn_calls(self) -> list[ToolCall]:
        return list(self._turn.calls)

    async def run(self, name: str, args: dict[str, Any] | None) -> ToolResult:
        self.active_calls += 1
        try:
            return await self._run(name, args or {})
        finally:
            self.active_calls -= 1

    async def _run(self, name: str, args: dict[str, Any]) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult(f"Unknown tool: {name}", is_error=True)
        try:
            clean = spec.args_model.model_validate(args).model_dump()
        except ValidationError as e:
            return ToolResult(f"Invalid arguments for {name}: {e}", is_error=True)

        key = (name, json.dumps(clean, sort_keys=True, default=str))
        turn = self._turn
        if key in turn.results:
            log.info("tool %s reused from earlier in turn %s", name, turn.id)
            turn.calls.append(ToolCall(name, clean, turn.results[key].is_error, 0.0, reused=True))
            return turn.results[key]

        started = time.monotonic()
        if spec.confirm and not await self._confirm(spec.describe_action(clean)):
            result = ToolResult("The user did not approve this action.", is_error=True)
        else:
            result = await self._call(spec, clean)
        duration = time.monotonic() - started
        turn.results[key] = result
        turn.calls.append(ToolCall(name, clean, result.is_error, duration))
        log.info("tool %s args=%s error=%s %.2fs", name, clean, result.is_error, duration)
        return result

    async def _confirm(self, summary: str) -> bool:
        if self._confirmer is None:
            return False
        async with self._confirm_lock:
            try:
                return await asyncio.wait_for(self._confirmer(summary), self._confirm_timeout_s)
            except TimeoutError:
                return False

    async def _call(self, spec: ToolSpec, args: dict[str, Any]) -> ToolResult:
        try:
            value = await spec.fn(**args)
        except ToolError as e:
            return ToolResult(str(e), is_error=True)
        except Exception as e:
            log.exception("tool %s failed", spec.name)
            return ToolResult(f"{spec.name} failed: {type(e).__name__}: {e}", is_error=True)
        if isinstance(value, str):
            return ToolResult(value)
        return ToolResult(json.dumps(value, ensure_ascii=False, default=str))
