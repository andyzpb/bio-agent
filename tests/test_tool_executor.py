from __future__ import annotations

import asyncio
from typing import Any

from agent.tool_hooks.approval import ToolApprovalBroker
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


def test_tool_executor_approval_required_skips_invoker_and_records_trace() -> None:
    hook = _SpyHook(
        name="approval",
        event="pre_tool_use",
        outcome=HookOutcome(
            decision="approval_required",
            reason="needs confirmation",
            risk="writes_storage",
        ),
    )
    executor = ToolExecutor([hook])
    invoked = False

    async def _forbidden(_tool_name: str, _arguments: dict[str, Any]) -> Any:
        nonlocal invoked
        invoked = True
        return "should not run"

    result = asyncio.run(
        executor.execute(
            ToolExecutionRequest(
                call_id="c1",
                tool_name="dummy",
                arguments={"x": 1},
                source="passive",
                session_key="dashboard:default",
            ),
            _forbidden,
        )
    )

    assert invoked is False
    assert result.status == "approval_required"
    assert result.output == "needs confirmation"
    assert result.reason == "needs confirmation"
    assert result.risk == "writes_storage"
    assert result.approval_id.startswith("approval-")
    assert result.final_arguments == {"x": 1}
    assert result.pre_hook_trace[0].decision == "approval_required"
    assert result.pre_hook_trace[0].reason == "needs confirmation"


def test_tool_executor_preflight_returns_approval_required() -> None:
    hook = _SpyHook(
        name="approval",
        event="pre_tool_use",
        outcome=HookOutcome(
            decision="approval_required",
            updated_input={"x": 2},
            reason="needs confirmation",
        ),
    )
    executor = ToolExecutor([hook])

    result = asyncio.run(
        executor.preflight(
            ToolExecutionRequest(
                call_id="c1",
                tool_name="dummy",
                arguments={"x": 1},
                source="passive",
            )
        )
    )

    assert result.status == "approval_required"
    assert result.final_arguments == {"x": 2}
    assert result.approval_id.startswith("approval-")


def test_tool_executor_execute_approved_runs_invoker_and_post_hooks_once() -> None:
    pre_hook = _SpyHook(
        name="approval",
        event="pre_tool_use",
        outcome=HookOutcome(decision="approval_required", reason="needs confirmation"),
    )
    post_hook = _SpyHook(
        name="post",
        event="post_tool_use",
        outcome=HookOutcome(extra_message="logged"),
    )
    executor = ToolExecutor([pre_hook, post_hook])
    invoked = 0

    async def _invoker(tool_name: str, arguments: dict[str, Any]) -> Any:
        nonlocal invoked
        invoked += 1
        return {"tool": tool_name, "arguments": dict(arguments)}

    async def _run() -> Any:
        request = ToolExecutionRequest(
            call_id="c1",
            tool_name="dummy",
            arguments={"x": 1},
            source="passive",
        )
        preflight = await executor.execute(request, _invoker)
        approved = await executor.execute_approved(
            request,
            preflight.final_arguments,
            _invoker,
            pre_hook_trace=preflight.pre_hook_trace,
        )
        return preflight, approved

    preflight, approved = asyncio.run(_run())

    assert preflight.status == "approval_required"
    assert approved.status == "success"
    assert approved.output == {"tool": "dummy", "arguments": {"x": 1}}
    assert approved.extra_messages == ["logged"]
    assert invoked == 1
    assert len(pre_hook.calls) == 1
    assert len(post_hook.calls) == 1


def test_tool_approval_broker_waits_for_approve_and_clears_pending() -> None:
    async def _run() -> Any:
        broker = ToolApprovalBroker(ttl_seconds=5)
        request = ToolExecutionRequest(
            call_id="c1",
            tool_name="dummy",
            arguments={"token": "secret"},
            source="passive",
            session_key="dashboard:default",
            channel="dashboard",
            chat_id="default",
        )
        pending = await broker.submit(
            approval_id="approval-test",
            request=request,
            final_arguments={"token": "secret"},
            reason="needs confirmation",
            risk="writes_storage",
            output="needs confirmation",
            pre_hook_trace=[],
        )
        waiter = asyncio.create_task(broker.wait_for_resolution(pending.approval_id))
        approve_result = await broker.approve(pending.approval_id)
        wait_result = await waiter
        remaining = await broker.list_pending(session_key="dashboard:default")
        second_approve = await broker.approve(pending.approval_id)
        return approve_result, wait_result, remaining, second_approve

    approve_result, wait_result, remaining, second_approve = asyncio.run(_run())

    assert approve_result.status == "approved"
    assert wait_result.status == "approved"
    assert wait_result.approval is not None
    assert wait_result.approval.final_arguments == {"token": "secret"}
    assert remaining == []
    assert second_approve.status == "missing"


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
