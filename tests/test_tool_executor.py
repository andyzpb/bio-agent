from __future__ import annotations

import asyncio
from typing import Any

from agent.tool_hooks.base import ToolHook
from agent.tool_hooks.executor import ToolExecutor
from agent.tool_hooks.types import HookContext, HookOutcome, ToolExecutionRequest


class _SpyHook(ToolHook):
    def __init__(
        self,
        *,
        name: str,
        event: str,
        matched: bool = True,
        outcome: HookOutcome | None = None,
    ) -> None:
        self.name = name
        self.event = event
        self._matched = matched
        self._outcome = outcome or HookOutcome()
        self.calls: list[HookContext] = []
        self._match_error: Exception | None = None
        self._run_error: Exception | None = None

    def matches(self, ctx: HookContext) -> bool:
        if self._match_error is not None:
            raise self._match_error
        return self._matched

    async def run(self, ctx: HookContext) -> HookOutcome:
        if self._run_error is not None:
            raise self._run_error
        self.calls.append(ctx)
        return self._outcome


async def _invoke(tool_name: str, arguments: dict[str, Any]) -> Any:
    return {"tool": tool_name, "arguments": dict(arguments)}


def test_tool_executor_pre_hook_can_update_arguments() -> None:
    hook = _SpyHook(
        name="rewrite",
        event="pre_tool_use",
        outcome=HookOutcome(updated_input={"x": 2}),
    )
    executor = ToolExecutor([hook])

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(
                call_id="c1",
                tool_name="dummy",
                arguments={"x": 1},
                source="passive",
            ),
            _invoke,
        )
    )

    assert result.status == "success"
    assert result.final_arguments == {"x": 2}
    assert result.output == {"tool": "dummy", "arguments": {"x": 2}}
    assert hook.calls[0].request.arguments == {"x": 1}


def test_tool_executor_denied_is_not_error() -> None:
    hook = _SpyHook(
        name="deny",
        event="pre_tool_use",
        outcome=HookOutcome(decision="deny", reason="blocked"),
    )
    executor = ToolExecutor([hook])

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(
                call_id="c1",
                tool_name="dummy",
                arguments={"x": 1},
                source="passive",
            ),
            _invoke,
        )
    )

    assert result.status == "denied"
    assert result.output == "blocked"


def test_tool_executor_can_return_approval_required_without_invoking_tool() -> None:
    hook = _SpyHook(
        name="approve",
        event="pre_tool_use",
        outcome=HookOutcome(
            decision="deny",
            reason="needs confirmation",
            requires_confirmation=True,
            confirmation={"tool_name": "dummy", "risk_level": "writes_storage"},
        ),
    )
    invoked = False
    executor = ToolExecutor([hook])

    async def _should_not_run(
        _tool_name: str,
        _arguments: dict[str, Any],
    ) -> Any:
        nonlocal invoked
        invoked = True
        return "ran"

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(
                call_id="c1",
                tool_name="dummy",
                arguments={"x": 1},
                source="passive",
            ),
            _should_not_run,
        )
    )

    assert invoked is False
    assert result.status == "approval_required"
    assert result.output == "needs confirmation"
    assert result.final_arguments == {"x": 1}
    assert result.confirmation["risk_level"] == "writes_storage"


def test_tool_executor_post_hook_only_adds_extra_message() -> None:
    hook = _SpyHook(
        name="post",
        event="post_tool_use",
        outcome=HookOutcome(extra_message="hint"),
    )
    executor = ToolExecutor([hook])

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(
                call_id="c1",
                tool_name="dummy",
                arguments={"x": 1},
                source="passive",
            ),
            _invoke,
        )
    )

    assert result.status == "success"
    assert result.output == {"tool": "dummy", "arguments": {"x": 1}}
    assert result.extra_messages == ["hint"]


def test_tool_executor_post_error_hook_cannot_swallow_error() -> None:
    hook = _SpyHook(
        name="post_error",
        event="post_tool_error",
        outcome=HookOutcome(extra_message="logged"),
    )
    executor = ToolExecutor([hook])

    async def _broken(_tool_name: str, _arguments: dict[str, Any]) -> Any:
        raise RuntimeError("boom")

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(
                call_id="c1",
                tool_name="dummy",
                arguments={},
                source="passive",
            ),
            _broken,
        )
    )

    assert result.status == "error"
    assert result.output == "工具执行出错: boom"
    assert result.extra_messages == ["logged"]


def test_tool_executor_hook_exception_becomes_controlled_error() -> None:
    hook = _SpyHook(name="boom_hook", event="pre_tool_use")
    hook._run_error = RuntimeError("hook boom")
    executor = ToolExecutor([hook])

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(
                call_id="c1",
                tool_name="dummy",
                arguments={"x": 1},
                source="passive",
            ),
            _invoke,
        )
    )

    assert result.status == "error"
    assert "boom_hook" in result.output
    assert "hook boom" in result.output


def test_tool_executor_post_tool_use_hook_failure_does_not_pollute_success() -> None:
    hook = _SpyHook(name="boom_hook", event="post_tool_use")
    hook._run_error = RuntimeError("post hook boom")
    executor = ToolExecutor([hook])

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(
                call_id="c1",
                tool_name="dummy",
                arguments={"x": 1},
                source="passive",
            ),
            _invoke,
        )
    )

    assert result.status == "success"
    assert result.output == {"tool": "dummy", "arguments": {"x": 1}}
    assert result.post_hook_trace[-1].reason == "hook failed: post hook boom"
