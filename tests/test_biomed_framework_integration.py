from __future__ import annotations

import json
import shutil
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent.lifecycle.types import BeforeTurnCtx, PreToolCtx, PromptRenderCtx
from agent.plugins.config import PluginConfig
from agent.plugins.context import PluginContext, PluginKVStore
from agent.plugins.manager import PluginManager
from agent.plugins.registry import plugin_registry
from agent.tool_hooks.base import ToolHook
from agent.tool_hooks.executor import ToolExecutor
from agent.tool_hooks.types import HookContext, HookOutcome, ToolExecutionRequest
from agent.tools.registry import ToolRegistry
from agent.lifecycle.types import TurnState
from bus.event_bus import EventBus
from bus.events import InboundMessage
from plugins.biomed_evidence.guardrails import clinical_refusal
from plugins.biomed_evidence.plugin import BiomedEvidencePlugin
from plugins.biomed_evidence.schemas import BiomedProjectCreateRequest


@pytest.fixture(autouse=True)
def _clean_plugin_registry() -> Generator[None, None, None]:
    plugin_registry._handlers._handlers.clear()
    plugin_registry._classes.clear()
    plugin_registry._instances.clear()
    yield
    plugin_registry._handlers._handlers.clear()
    plugin_registry._classes.clear()
    plugin_registry._instances.clear()


async def _make_plugin(
    tmp_path: Path,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[BiomedEvidencePlugin, EventBus]:
    bus = EventBus()
    plugin = BiomedEvidencePlugin()
    plugin.context = PluginContext(
        event_bus=bus,
        tool_registry=None,
        plugin_id="biomed_evidence",
        plugin_dir=tmp_path,
        kv_store=PluginKVStore(tmp_path / ".kv.json"),
        config=PluginConfig(config or {}),
        workspace=tmp_path,
    )
    await plugin.initialize()
    return plugin, bus


class _BiomedGuardHook(ToolHook):
    name = "biomed"
    event = "pre_tool_use"

    def __init__(self, plugin: BiomedEvidencePlugin) -> None:
        self._plugin = plugin

    def matches(self, _ctx: HookContext) -> bool:
        return True

    async def run(self, ctx: HookContext) -> HookOutcome:
        outcome = await self._plugin.guard_biomedical_tool(
            PreToolCtx(
                session_key=ctx.request.session_key,
                channel=ctx.request.channel,
                chat_id=ctx.request.chat_id,
                tool_name=ctx.request.tool_name,
                arguments=dict(ctx.current_arguments),
                call_id=ctx.request.call_id,
                source=ctx.request.source,
                request_text=ctx.request.request_text,
            )
        )
        return outcome or HookOutcome()


@pytest.mark.asyncio
async def test_biomed_pre_tool_guard_denies_clinical_tool_call(
    tmp_path: Path,
) -> None:
    plugin, bus = await _make_plugin(tmp_path)
    try:
        outcome = await plugin.guard_biomedical_tool(
            PreToolCtx(
                session_key="test",
                channel="cli",
                chat_id="local",
                tool_name="answer_with_audit",
                arguments={
                    "question": "What dose should my mother take for Alzheimer disease?"
                },
                source="passive",
                request_text=(
                    "What dose should my mother take for Alzheimer disease?"
                ),
            )
        )
    finally:
        await plugin.terminate()
        await bus.aclose()

    assert outcome is not None
    assert outcome.decision == "deny"
    assert "clinical_or_patient_specific_boundary" in outcome.reason


@pytest.mark.asyncio
async def test_biomed_pre_tool_guard_applies_config_defaults_caps_and_kv(
    tmp_path: Path,
) -> None:
    plugin, bus = await _make_plugin(
        tmp_path,
        config={
            "default_source": "mock",
            "max_answer_papers": 3,
            "default_use_llm_planner": True,
            "default_use_llm_claim_logic": True,
            "default_export_logic_facts": True,
        },
    )
    try:
        outcome = await plugin.guard_biomedical_tool(
            PreToolCtx(
                session_key="test",
                channel="cli",
                chat_id="local",
                tool_name="answer_with_audit",
                arguments={
                    "question": (
                        "What recent evidence links microglial activation to "
                        "Alzheimer disease progression?"
                    ),
                    "max_papers": 50,
                },
                source="passive",
            )
        )
        assert outcome is not None
        assert outcome.updated_input is not None
        updated = outcome.updated_input
        assert updated["source"] == "mock"
        assert updated["max_papers"] == 3
        assert updated["use_llm_planner"] is True
        assert updated["use_llm_claim_logic"] is True
        assert updated["export_logic_facts"] is True
        assert "capped max_papers from 50 to 3" in outcome.reason
        assert plugin.context.kv_store.get("last_source") == "mock"
        assert plugin.context.kv_store.get("last_llm_options")[
            "use_llm_claim_logic"
        ] is True
    finally:
        await plugin.terminate()
        await bus.aclose()


@pytest.mark.asyncio
async def test_biomed_pre_tool_guard_denies_live_pubmed_when_config_disabled(
    tmp_path: Path,
) -> None:
    plugin, bus = await _make_plugin(
        tmp_path,
        config={"allow_live_pubmed_tools": False},
    )
    try:
        outcome = await plugin.guard_biomedical_tool(
            PreToolCtx(
                session_key="test",
                channel="cli",
                chat_id="local",
                tool_name="search_biomedical_literature",
                arguments={"query": "microglia Alzheimer", "source": "pubmed"},
                source="passive",
            )
        )
    finally:
        await plugin.terminate()
        await bus.aclose()

    assert outcome is not None
    assert outcome.decision == "deny"
    assert "live PubMed tool calls are disabled" in outcome.reason


@pytest.mark.asyncio
async def test_biomed_before_turn_clinical_guard_aborts_before_context_prepare(
    tmp_path: Path,
) -> None:
    plugin, bus = await _make_plugin(tmp_path)
    try:
        module = plugin.before_turn_modules()[0]
        frame = SimpleNamespace(
            input=TurnState(
                msg=InboundMessage(
                    channel="dashboard",
                    sender="user",
                    chat_id="default",
                    content="What dose should my mother take for Alzheimer disease?",
                ),
                session_key="dashboard:default",
                dispatch_outbound=True,
            ),
            slots={"session:session": SimpleNamespace(messages=["old"])},
        )
        await module.run(frame)
        ctx = frame.slots["session:ctx"]
    finally:
        await plugin.terminate()
        await bus.aclose()

    assert isinstance(ctx, BeforeTurnCtx)
    assert ctx.abort is True
    assert ctx.abort_reply == clinical_refusal()
    assert ctx.retrieved_memory_block == ""
    assert ctx.history_messages == ()
    assert ctx.extra_metadata["clinical_boundary_before_memory"] is True
    assert (
        ctx.extra_metadata["biomed_evidence_clinical_boundary"][
            "before_context_prepare"
        ]
        is True
    )


@pytest.mark.asyncio
async def test_biomed_dashboard_chat_sensitive_tool_requires_confirmation_guard(
    tmp_path: Path,
) -> None:
    plugin, bus = await _make_plugin(tmp_path)
    try:
        outcome = await plugin.guard_biomedical_tool(
            PreToolCtx(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
                tool_name="record_run_review_decision",
                arguments={
                    "run_id": "run-1",
                    "decision": "supported",
                },
                source="passive",
                request_text="Please save this review decision.",
            )
        )
    finally:
        await plugin.terminate()
        await bus.aclose()

    assert outcome is not None
    assert outcome.decision == "deny"
    assert "biomed_evidence_confirmation_required" in outcome.reason
    assert "requires_confirmation=true" in outcome.reason


@pytest.mark.asyncio
async def test_biomed_sensitive_chat_tool_executor_denies_without_invoker(
    tmp_path: Path,
) -> None:
    plugin, bus = await _make_plugin(tmp_path)
    invoked = False
    try:
        executor = ToolExecutor([_BiomedGuardHook(plugin)])

        async def _invoker(_name: str, _args: dict[str, Any]) -> str:
            nonlocal invoked
            invoked = True
            return "ran"

        result = await executor.execute(
            ToolExecutionRequest(
                call_id="call-1",
                tool_name="export_project_to_obsidian",
                arguments={"project_id": "project-1"},
                source="passive",
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
            ),
            _invoker,
        )
    finally:
        await plugin.terminate()
        await bus.aclose()

    assert invoked is False
    assert result.status == "denied"
    assert "export_project_to_obsidian" in result.output
    assert "requires_confirmation=true" in result.output


@pytest.mark.asyncio
async def test_biomed_pre_tool_guard_applies_search_literature_policy(
    tmp_path: Path,
) -> None:
    plugin, bus = await _make_plugin(
        tmp_path,
        config={
            "default_source": "mock",
            "max_search_results": 2,
        },
    )
    try:
        outcome = await plugin.guard_biomedical_tool(
            PreToolCtx(
                session_key="test",
                channel="cli",
                chat_id="local",
                tool_name="search_literature",
                arguments={
                    "query": "microglia Alzheimer disease progression",
                    "max_results": 50,
                },
                source="passive",
                request_text="Find papers on microglia and Alzheimer disease.",
            )
        )
    finally:
        await plugin.terminate()
        await bus.aclose()

    assert outcome is not None
    assert outcome.updated_input is not None
    assert outcome.updated_input["source"] == "mock"
    assert outcome.updated_input["max_results"] == 2
    assert outcome.updated_input["require_abstract"] is True
    assert "applied default biomedical source: mock" in outcome.reason
    assert "capped max_results from 50 to 2" in outcome.reason
    assert "require_abstract=true" in outcome.reason


@pytest.mark.asyncio
async def test_biomed_pre_tool_guard_validates_project_id(
    tmp_path: Path,
) -> None:
    plugin, bus = await _make_plugin(tmp_path)
    try:
        outcome = await plugin.guard_biomedical_tool(
            PreToolCtx(
                session_key="test",
                channel="cli",
                chat_id="local",
                tool_name="answer_with_audit",
                arguments={
                    "question": "What evidence links microglia to Alzheimer disease?",
                    "project_id": "missing-project",
                },
                source="passive",
            )
        )
    finally:
        await plugin.terminate()
        await bus.aclose()

    assert outcome is not None
    assert outcome.decision == "deny"
    assert "project_not_found" in outcome.reason


@pytest.mark.asyncio
async def test_biomed_prompt_module_injects_research_boundary_and_project_context(
    tmp_path: Path,
) -> None:
    plugin, bus = await _make_plugin(tmp_path)
    try:
        project = plugin._service.create_project(
            BiomedProjectCreateRequest(
                name="Microglia AD review",
                research_question="How does microglial activation relate to AD progression?",
                include_keywords=["microglia", "Alzheimer"],
                exclude_keywords=["clinical dosage"],
                preferred_methods=["longitudinal"],
            )
        )
        plugin.context.kv_store.set("active_project_id", project.project_id)
        ctx = PromptRenderCtx(
            session_key="test",
            channel="cli",
            chat_id="local",
            content="What evidence links microglial activation to Alzheimer disease?",
            media=None,
            timestamp=datetime.now(),
            history=[],
            skill_names=[],
            retrieved_memory_block="",
            disabled_sections=set(),
            turn_injection_prompt="",
        )
        frame = SimpleNamespace(slots={"prompt:ctx": ctx})
        module = plugin.prompt_render_modules()[0]
        await module.run(frame)
    finally:
        await plugin.terminate()
        await bus.aclose()

    sections = ctx.system_sections_bottom
    assert len(sections) == 1
    content = sections[0].content
    assert "research-only" in content
    assert "never cite them as biomedical evidence" in content
    assert "Microglia AD review" in content
    assert project.project_id in content


@pytest.mark.asyncio
async def test_biomed_plugin_manager_loads_config_and_hook_executes(
    tmp_path: Path,
) -> None:
    source = Path(__file__).parents[1] / "plugins" / "biomed_evidence"
    plugin_root = tmp_path / "plugins"
    shutil.copytree(source, plugin_root / "biomed_evidence")
    bus = EventBus()
    tools = ToolRegistry()
    manager = PluginManager(
        plugin_dirs=[plugin_root],
        event_bus=bus,
        tool_registry=tools,
        workspace=tmp_path / "workspace",
    )
    try:
        await manager.load_all()
        instance = next(iter(plugin_registry._instances.values()))
        assert instance.context.config is not None
        assert instance.context.config.default_source == "mock"
        assert instance.context.config.allow_live_pubmed_tools is False

        executor = ToolExecutor(manager.tool_hooks)

        async def fake_invoker(name: str, args: dict[str, Any]) -> str:
            return json.dumps({"name": name, "args": args})

        result = await executor.execute(
            ToolExecutionRequest(
                call_id="c1",
                tool_name="answer_with_audit",
                arguments={
                    "question": "What dose should my mother take for Alzheimer disease?"
                },
                source="passive",
                session_key="test",
                request_text=(
                    "What dose should my mother take for Alzheimer disease?"
                ),
            ),
            fake_invoker,
        )
    finally:
        await manager.terminate_all()
        await bus.aclose()

    assert result.status == "denied"
    assert "clinical_or_patient_specific_boundary" in str(result.output)
    assert any(
        item.hook_name.endswith(":guard_biomedical_tool") and item.matched
        for item in result.pre_hook_trace
    )
