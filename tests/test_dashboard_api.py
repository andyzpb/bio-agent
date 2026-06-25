from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
from datetime import datetime

import pytest
from fastapi.testclient import TestClient as _RawTestClient

from bootstrap.dashboard_api import (
    DashboardChatMultiplexer,
    _sse_payload,
    create_dashboard_app as _create_dashboard_app,
)
from agent.lifecycle.types import AfterStepCtx
from plugins.default_memory.engine import DefaultMemoryEngine
from bus.event_bus import EventBus
from bus.events import OutboundMessage
from bus.events_lifecycle import (
    StreamDeltaReady,
    ToolCallApprovalRequired,
    ToolCallCompleted,
    ToolCallStarted,
)
from bus.queue import MessageBus
from memory2.store import MemoryStore2
from proactive_v2.state import ProactiveStateStore
from session.store import SessionStore


class _TrackedTestClient(_RawTestClient):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._is_closed = False

    def close(self) -> None:
        if self._is_closed:
            return
        self._is_closed = True
        super().close()

    def __del__(self) -> None:
        if not self._is_closed:
            try:
                self.close()
            except Exception:
                pass


TestClient = _TrackedTestClient


class _DashboardMemoryAdmin:
    def __init__(self, workspace) -> None:
        self._store = MemoryStore2(workspace / "memory" / "memory2.db")

    def describe(self):
        return DefaultMemoryEngine.DESCRIPTOR

    def keyword_match_procedures(self, action_tokens: list[str]):
        return self._store.keyword_match_procedures(action_tokens)

    def list_events_by_time_range(self, time_start, time_end, *, limit: int = 200):
        return self._store.list_events_by_time_range(time_start, time_end, limit=limit)

    def list_items_for_dashboard(self, **kwargs):
        return self._store.list_items_for_dashboard(**kwargs)

    def get_item_for_dashboard(self, item_id: str, *, include_embedding: bool = False):
        return self._store.get_item_for_dashboard(
            item_id, include_embedding=include_embedding
        )

    def update_item_for_dashboard(self, item_id: str, **kwargs):
        return self._store.update_item_for_dashboard(item_id, **kwargs)

    def delete_item(self, item_id: str) -> bool:
        return self._store.delete_item(item_id)

    def delete_items_batch(self, ids: list[str]) -> int:
        return self._store.delete_items_batch(ids)

    def find_similar_items_for_dashboard(self, item_id: str, **kwargs):
        return self._store.find_similar_items_for_dashboard(item_id, **kwargs)

    def close(self) -> None:
        self._store.close()


def create_dashboard_app(tmp_path, **kwargs):
    kwargs.setdefault("memory_admin", _DashboardMemoryAdmin(tmp_path))
    return _create_dashboard_app(tmp_path, **kwargs)


class _ManualConsolidator:
    def __init__(self, *, result: bool = True, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, bool, bool]] = []

    async def trigger_memory_consolidation(
        self,
        session_key: str,
        *,
        archive_all: bool = False,
        force: bool = False,
    ) -> bool:
        self.calls.append((session_key, archive_all, force))
        if self.error is not None:
            raise self.error
        return self.result


class _FakeToolRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, name: str, args: dict):
        self.calls.append((name, dict(args)))
        if name == "watch_research_topic":
            return {
                "watch_id": "watch-test123",
                "topic": args.get("topic") or "Microglia AD",
                "description": args.get("description"),
                "include_keywords": args.get("include_keywords") or [],
                "exclude_keywords": [],
                "preferred_methods": [],
                "min_relevance_score": args.get("min_relevance_score", 0.7),
                "schedule": args.get("schedule") or "daily",
                "enabled": True,
                "created_at": "2026-06-16T00:00:00+00:00",
                "updated_at": "2026-06-16T00:00:00+00:00",
                "last_checked_at": None,
                "next_check_at": "2026-06-17T00:00:00+00:00",
            }
        if name == "delete_research_watch_topic":
            return {"deleted": True, "watch_id": args.get("watch_id")}
        return {"ok": True, "name": name, "args": dict(args)}

    def has_tool(self, name: str) -> bool:
        return True


class _RequireApprovedHook:
    event = "pre_tool_use"
    name = "require-approved"

    def matches(self, ctx) -> bool:
        return ctx.request.tool_name in {
            "watch_research_topic",
            "delete_research_watch_topic",
        }

    async def run(self, ctx):
        from agent.tool_hooks.types import HookOutcome

        if ctx.request.approved and ctx.request.approval_id:
            return HookOutcome()
        return HookOutcome(
            decision="deny",
            requires_confirmation=True,
            confirmation={"approval_id": "hook-approval"},
            reason="requires approval",
        )


class _ManualMemoryOptimizer:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        block: bool = False,
    ) -> None:
        self.error = error
        self.block = block
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self._running = False
        self.raise_busy = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def optimize(self) -> None:
        if self.raise_busy:
            from proactive_v2.memory_optimizer import MemoryOptimizerBusy

            raise MemoryOptimizerBusy("busy")
        self._running = True
        self.calls += 1
        self.started.set()
        try:
            if self.block:
                await asyncio.to_thread(self.release.wait, 1.0)
            if self.error is not None:
                raise self.error
        finally:
            self._running = False


class _FakeBus(MessageBus):
    def __init__(self) -> None:
        super().__init__()
        self.inbound_items = []

    async def publish_inbound(self, msg):
        self.inbound_items.append(msg)
        await super().publish_inbound(msg)


def _seed_workspace(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    store.create_session(
        key="telegram:100",
        metadata={"title": "alpha room"},
        last_consolidated=2,
        last_user_at="2026-04-19T10:00:00+08:00",
    )
    store.create_session(
        key="cli:local",
        metadata={"title": "beta room"},
        last_proactive_at="2026-04-19T09:00:00+08:00",
    )
    store.insert_message(
        "telegram:100",
        role="user",
        content="你好，今晚睡觉了吗",
        ts="2026-04-19T10:01:00+08:00",
        seq=0,
        extra={"pinned": True},
    )
    store.insert_message(
        "telegram:100",
        role="assistant",
        content="还没睡呢",
        ts="2026-04-19T10:02:00+08:00",
        seq=1,
        tool_chain=[{"text": "reply", "calls": []}],
        extra={"source": "test"},
    )
    store.insert_message(
        "cli:local",
        role="user",
        content="hello from cli",
        ts="2026-04-19T09:01:00+08:00",
        seq=0,
    )
    store.close()

    memory_store = MemoryStore2(tmp_path / "memory" / "memory2.db", vec_dim=2)
    memory_store.upsert_item(
        memory_type="preference",
        summary="喜欢奶茶，少糖去冰",
        embedding=[1.0, 0.0],
        source_ref="telegram:100:pref",
        extra={"scope_channel": "telegram", "scope_chat_id": "100"},
        happened_at="2026-04-19T10:03:00+08:00",
        emotional_weight=6,
    )
    memory_store.upsert_item(
        memory_type="event",
        summary="昨晚和朋友去散步",
        embedding=[0.9, 0.1],
        source_ref="telegram:100:event",
        extra={"scope_channel": "telegram", "scope_chat_id": "100"},
        happened_at="2026-04-18T20:00:00+08:00",
    )
    memory_store.upsert_item(
        memory_type="profile",
        summary="常驻上海",
        embedding=None,
        source_ref="cli:local:profile",
        extra={"scope_channel": "cli", "scope_chat_id": "local"},
    )
    memory_store.close()

    proactive_store = ProactiveStateStore(tmp_path / "proactive.db")
    proactive_store.mark_items_seen(
        [
            ("mcp:feed:event-1", "feed-1"),
            ("mcp:feed:event-2", "feed-2"),
            ("rss:news", "rss-1"),
        ],
        now=datetime.fromisoformat("2026-04-19T02:00:00+00:00"),
    )
    proactive_store.mark_delivery(
        "telegram:100",
        "delivery-a",
        now=datetime.fromisoformat("2026-04-19T02:05:00+00:00"),
    )
    proactive_store.mark_delivery(
        "cli:local",
        "delivery-b",
        now=datetime.fromisoformat("2026-04-19T02:06:00+00:00"),
    )
    proactive_store.mark_rejection_cooldown(
        [("mcp:feed:event-3", "feed-3")],
        hours=24,
        now=datetime.fromisoformat("2026-04-19T02:10:00+00:00"),
    )
    proactive_store.mark_semantic_items(
        [
            {
                "source_key": "rss:news",
                "item_id": "rss-1",
                "text": "今天有新游戏资讯",
            },
            {
                "source_key": "mcp:feed",
                "item_id": "feed-2",
                "text": "用户昨天提到过奶茶",
            },
        ],
        now=datetime.fromisoformat("2026-04-19T02:20:00+00:00"),
    )
    proactive_store.mark_bg_context_main_send(
        now=datetime.fromisoformat("2026-04-19T02:30:00+00:00")
    )
    proactive_store.mark_context_only_send(
        "telegram:100",
        now=datetime.fromisoformat("2026-04-19T02:31:00+00:00"),
    )
    proactive_store.mark_drift_run(
        "telegram:100",
        now=datetime.fromisoformat("2026-04-19T02:32:00+00:00"),
    )
    proactive_store.close()

    conn = sqlite3.connect(tmp_path / "proactive.db")
    conn.execute(
        """
        INSERT INTO tick_log(
            tick_id, session_key, started_at, finished_at, gate_exit,
            terminal_action, skip_reason, steps_taken, alert_count,
            content_count, context_count, interesting_ids, discarded_ids,
            cited_ids, drift_entered, final_message
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "tick-1",
            "telegram:100",
            "2026-04-19T02:40:00+00:00",
            "2026-04-19T02:40:05+00:00",
            None,
            "reply",
            None,
            3,
            1,
            2,
            1,
            '["mcp:feed:feed-1"]',
            '["rss:news:rss-9"]',
            '["mcp:feed:feed-1"]',
            0,
            "记得早点休息",
        ),
    )
    conn.execute(
        """
        INSERT INTO tick_log(
            tick_id, session_key, started_at, finished_at, gate_exit,
            terminal_action, skip_reason, steps_taken, alert_count,
            content_count, context_count, interesting_ids, discarded_ids,
            cited_ids, drift_entered, final_message
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "tick-2",
            "cli:local",
            "2026-04-19T03:00:00+00:00",
            "2026-04-19T03:00:01+00:00",
            "busy",
            "skip",
            "busy",
            0,
            0,
            0,
            0,
            "[]",
            "[]",
            "[]",
            1,
            None,
        ),
    )
    conn.execute(
        """
        INSERT INTO tick_step_log(
            tick_id, step_index, phase, tool_name, tool_call_id, tool_args_json,
            tool_result_text, terminal_action_after, skip_reason_after,
            interesting_ids_after, discarded_ids_after, cited_ids_after,
            final_message_after
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "tick-1",
            1,
            "loop",
            "message_push",
            "call-1",
            '{"message":"记得早点休息","evidence":["mcp:feed:feed-1"]}',
            '{"ok": true}',
            None,
            "",
            '["mcp:feed:feed-1"]',
            "[]",
            "[]",
            "",
        ),
    )
    conn.execute(
        """
        INSERT INTO tick_step_log(
            tick_id, step_index, phase, tool_name, tool_call_id, tool_args_json,
            tool_result_text, terminal_action_after, skip_reason_after,
            interesting_ids_after, discarded_ids_after, cited_ids_after,
            final_message_after
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "tick-1",
            2,
            "loop",
            "finish_turn",
            "call-2",
            '{"decision":"reply"}',
            '{"ok": true}',
            "reply",
            "",
            '["mcp:feed:feed-1"]',
            "[]",
            '["mcp:feed:feed-1"]',
            "记得早点休息",
        ),
    )
    conn.commit()
    conn.close()


def test_list_sessions_with_filters(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(create_dashboard_app(tmp_path)) as client:
        resp = client.get(
            "/api/dashboard/sessions",
            params={"q": "alpha", "channel": "telegram"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["total"] == 1
        assert payload["items"][0]["key"] == "telegram:100"
        assert payload["items"][0]["message_count"] == 2

        messages_resp = client.get(
            "/api/dashboard/messages",
            params={"sort_by": "seq", "sort_order": "asc"},
        )
        assert messages_resp.status_code == 200
        assert messages_resp.json()["items"][0]["seq"] == 0


def test_dashboard_chat_status_disabled_without_full_runtime(tmp_path) -> None:
    with TestClient(create_dashboard_app(tmp_path)) as client:
        status = client.get("/api/dashboard/chat/status")
        post = client.post(
            "/api/dashboard/chat/messages",
            json={"content": "hello"},
        )

    assert status.status_code == 200
    assert status.json()["enabled"] is False
    assert "full runtime" in status.json()["reason"]
    assert post.status_code == 503


def test_dashboard_chat_status_reports_session_cursor_when_enabled(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=bus, event_bus=event_bus)
    ) as client:
        status = client.get(
            "/api/dashboard/chat/status",
            params={"session_key": "dashboard:default"},
        )

    assert status.status_code == 200
    payload = status.json()
    assert payload["enabled"] is True
    assert payload["session_key"] == "dashboard:default"
    assert payload["latest_seq"] == 0
    assert payload["active"] is False
    assert payload["replay_limit"] >= 100


def test_dashboard_chat_status_requires_event_bus(tmp_path) -> None:
    bus = _FakeBus()
    with TestClient(create_dashboard_app(tmp_path, message_bus=bus)) as client:
        status = client.get("/api/dashboard/chat/status")
        post = client.post(
            "/api/dashboard/chat/messages",
            json={"content": "hello"},
        )

    assert status.status_code == 200
    assert status.json()["enabled"] is False
    assert post.status_code == 503
    assert bus.inbound_items == []


def test_dashboard_chat_post_publishes_inbound_to_runtime_bus(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=bus, event_bus=event_bus)
    ) as client:
        resp = client.post(
            "/api/dashboard/chat/messages",
            json={"content": "hello from dashboard"},
        )

    assert resp.status_code == 202
    assert resp.json()["accepted"] is True
    assert resp.json()["session_key"] == "dashboard:default"
    assert len(bus.inbound_items) == 1
    item = bus.inbound_items[0]
    assert item.channel == "dashboard"
    assert item.sender == "dashboard-user"
    assert item.chat_id == "default"
    assert item.content == "hello from dashboard"
    assert item.session_key == "dashboard:default"
    assert item.metadata["source"] == "dashboard_chat"


def test_dashboard_chat_create_session_returns_friendly_placeholder(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=bus, event_bus=event_bus)
    ) as client:
        resp = client.post("/api/dashboard/chat/sessions", json={})

    assert resp.status_code == 201
    payload = resp.json()
    assert payload["key"].startswith("dashboard:")
    assert payload["message_count"] == 0
    assert payload["metadata"] == {
        "title": "New chat",
        "title_source": "placeholder",
        "created_from": "dashboard_chat",
    }


def test_dashboard_chat_commands_manifest_includes_biomed(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            biomed_revision_provider=object(),
            biomed_revision_model="test-model",
        )
    ) as client:
        response = client.get("/api/dashboard/chat/commands")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "dashboard-chat-commands-v1"
    command = payload["commands"][0]
    assert command["prefix"] == "/biomed"
    assert command["status"]["llm_provider"]["status"] == "configured"
    workflows = {item["name"]: item for item in command["workflows"]}
    assert workflows["audit"]["contract"]["tool_name"] == "answer_with_audit"
    assert workflows["audit"]["contract"]["source_policy"] == "live_opt_in"
    assert workflows["pilot-report"]["contract"]["tool_name"] == "export_evidence_report"
    assert workflows["pilot-report"]["contract"]["requires_confirmation"] is False
    assert workflows["template run"]["contract"]["tool_name"] == "run_saved_tool_chain_template"
    assert "/biomed pilot-report biomed-run-... --format markdown" in command["examples"]


def test_dashboard_chat_biomed_status_reports_disabled_pubmed_and_missing_llm(
    tmp_path,
) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=bus, event_bus=event_bus)
    ) as client:
        response = client.get("/api/dashboard/chat/commands/biomed/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["llm_provider"]["status"] == "missing"
    assert payload["pubmed"]["status"] == "disabled"
    assert payload["pubmed"]["allow_live_pubmed_tools"] is False
    assert "allow_live_pubmed_tools" in payload["pubmed"]["message"]
    assert "api_key" not in response.text.lower()


def test_dashboard_chat_biomed_parse_audit_preview_expands_llm_flags(
    tmp_path,
) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            biomed_revision_provider=object(),
            biomed_revision_model="test-model",
        )
    ) as client:
        response = client.post(
            "/api/dashboard/chat/commands/parse",
            json={
                "session_key": "dashboard:default",
                "content": '/biomed audit "microglia Alzheimer disease" --source mock --papers 10 --llm all --support-refute',
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["can_send"] is True
    assert payload["action"] == "audit"
    assert payload["tool_name"] == "answer_with_audit"
    assert payload["arguments"]["max_papers"] == 10
    assert payload["arguments"]["use_llm_planner"] is True
    assert payload["arguments"]["use_llm_claim_logic"] is True
    assert payload["arguments"]["execute_support_refute"] is True
    assert "Run a research-only Biomedical Evidence audited answer workflow" in payload["final_prompt"]


def test_dashboard_chat_biomed_parse_audit_includes_cockpit_plan_preview(
    tmp_path,
) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            biomed_revision_provider=object(),
            biomed_revision_model="test-model",
        )
    ) as client:
        response = client.post(
            "/api/dashboard/chat/commands/parse",
            json={
                "session_key": "dashboard:default",
                "content": '/biomed audit "microglia Alzheimer disease" --source mock --papers 10 --llm all --support-refute',
            },
        )

    assert response.status_code == 200
    payload = response.json()
    plan = payload["plan_preview"]
    assert plan["kind"] == "biomed_audit"
    assert plan["question"] == "microglia Alzheimer disease"
    assert plan["source"] == "mock"
    assert plan["paper_count"] == 10
    assert plan["llm_mode"] == "all"
    assert plan["policy"]["research_only"] is True
    assert plan["policy"]["memory_is_evidence"] is False
    assert "retrieval" in plan["phases"]
    assert "audit" in plan["phases"]
    assert "Run Evidence Review" in plan["expected_artifacts"]
    assert "latency_seconds" in plan["observability_fields"]


def test_dashboard_chat_biomed_parse_blocks_pubmed_when_disabled(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            biomed_revision_provider=object(),
            biomed_revision_model="test-model",
        )
    ) as client:
        response = client.post(
            "/api/dashboard/chat/commands/parse",
            json={
                "session_key": "dashboard:default",
                "content": '/biomed audit "microglia Alzheimer disease" --source pubmed --papers 10',
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["can_send"] is False
    assert payload["missing_requirements"][0]["kind"] == "pubmed"
    assert "allow_live_pubmed_tools" in payload["missing_requirements"][0]["detail"]


def test_dashboard_chat_biomed_parse_blocked_audit_keeps_plan_preview(
    tmp_path,
) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            biomed_revision_provider=object(),
            biomed_revision_model="test-model",
        )
    ) as client:
        response = client.post(
            "/api/dashboard/chat/commands/parse",
            json={
                "session_key": "dashboard:default",
                "content": '/biomed audit "microglia Alzheimer disease" --source pubmed --papers 10',
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["can_send"] is False
    assert payload["plan_preview"]["source"] == "pubmed"
    assert payload["plan_preview"]["readiness"] == "blocked"
    assert payload["plan_preview"]["blocking_requirements"][0]["kind"] == "pubmed"


def test_dashboard_chat_biomed_enable_pubmed_updates_command_policy(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            biomed_revision_provider=object(),
            biomed_revision_model="test-model",
        )
    ) as client:
        enable = client.post(
            "/api/dashboard/chat/messages",
            json={"session_key": "dashboard:default", "content": "/biomed enable pubmed"},
        )
        status = client.get("/api/dashboard/chat/commands/biomed/status")
        preview = client.post(
            "/api/dashboard/chat/commands/parse",
            json={
                "session_key": "dashboard:default",
                "content": '/biomed audit "microglia Alzheimer disease" --source pubmed --papers 10',
            },
        )
        history = client.get("/api/dashboard/chat/history", params={"session_key": "dashboard:default"})

    assert enable.status_code == 202
    assert enable.json()["deterministic_response"] is True
    assert len(bus.inbound_items) == 0
    assert status.json()["pubmed"]["status"] == "enabled"
    assert status.json()["pubmed"]["policy_status"] == "enabled"
    assert preview.json()["can_send"] is True
    assert preview.json()["missing_requirements"] == []
    assert "allow_live_pubmed_tools = true" in (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert history.json()["items"][-1]["content"].startswith("## PubMed enabled")


def test_dashboard_chat_biomed_parse_confirmation_preview_for_write_action(
    tmp_path,
) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=bus, event_bus=event_bus)
    ) as client:
        response = client.post(
            "/api/dashboard/chat/commands/parse",
            json={
                "session_key": "dashboard:default",
                "content": '/biomed project create "Microglia AD" --question "What links microglial activation to AD progression?"',
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["tool_name"] == "create_biomed_project"
    assert payload["confirmation"]["required"] is True
    assert payload["confirmation"]["risk_level"] == "writes_storage"


def test_dashboard_chat_biomed_watch_command_creates_pending_approval(
    tmp_path,
) -> None:
    registry = _FakeToolRegistry()
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            tool_registry=registry,
        )
    ) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        response = client.post(
            "/api/dashboard/chat/messages",
            json={
                "session_key": session_key,
                "content": '/biomed watch create "Microglia AD" --query "microglia Alzheimer disease progression" --schedule weekly',
            },
        )
        history = client.get(
            "/api/dashboard/chat/history",
            params={"session_key": session_key},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["approval_required"] is True
    assert payload["approval_id"]
    pending = history.json()["pending_approvals"]
    assert len(pending) == 1
    assert pending[0]["approval_id"] == payload["approval_id"]
    assert pending[0]["tool_name"] == "watch_research_topic"
    assert pending[0]["final_arguments"]["topic"] == "Microglia AD"
    assert pending[0]["final_arguments"]["schedule"] == "weekly"
    assert pending[0]["final_arguments"]["include_keywords"]
    assert registry.calls == []


def test_dashboard_chat_biomed_watch_delete_command_creates_pending_approval(
    tmp_path,
) -> None:
    registry = _FakeToolRegistry()
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            tool_registry=registry,
        )
    ) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        response = client.post(
            "/api/dashboard/chat/messages",
            json={
                "session_key": session_key,
                "content": "/biomed watch delete watch-test123",
            },
        )
        history = client.get(
            "/api/dashboard/chat/history",
            params={"session_key": session_key},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["approval_required"] is True
    pending = history.json()["pending_approvals"]
    assert pending[0]["tool_name"] == "delete_research_watch_topic"
    assert pending[0]["final_arguments"] == {"watch_id": "watch-test123"}
    assert registry.calls == []


def test_dashboard_chat_natural_language_watch_delete_routes_to_command_approval(
    tmp_path,
) -> None:
    registry = _FakeToolRegistry()
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            tool_registry=registry,
        )
    ) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        response = client.post(
            "/api/dashboard/chat/messages",
            json={
                "session_key": session_key,
                "content": "watch-test123 delete this watch job",
            },
        )
        history = client.get(
            "/api/dashboard/chat/history",
            params={"session_key": session_key},
        )

    assert response.status_code == 202
    assert response.json()["approval_required"] is True
    pending = history.json()["pending_approvals"]
    assert pending[0]["tool_name"] == "delete_research_watch_topic"
    assert pending[0]["final_arguments"] == {"watch_id": "watch-test123"}
    assert registry.calls == []


def test_dashboard_chat_parse_natural_language_watch_delete_uses_biomed_router(
    tmp_path,
) -> None:
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=_FakeBus(),
            event_bus=EventBus(),
            tool_registry=_FakeToolRegistry(),
        )
    ) as client:
        response = client.post(
            "/api/dashboard/chat/commands/parse",
            json={
                "session_key": "dashboard:default",
                "content": "watch-test123 delete this watch job",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "biomed"
    assert payload["action"] == "watch_delete"
    assert payload["tool_name"] == "delete_research_watch_topic"
    assert payload["arguments"] == {"watch_id": "watch-test123"}
    assert payload["confirmation"]["required"] is True


def test_dashboard_chat_command_approval_sse_event_has_executable_id(
    tmp_path,
) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            tool_registry=_FakeToolRegistry(),
        )
    ) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        response = client.post(
            "/api/dashboard/chat/messages",
            json={
                "session_key": session_key,
                "content": "/biomed watch delete watch-test123",
            },
        )
        history = client.get(
            "/api/dashboard/chat/history",
            params={"session_key": session_key},
        )

    assert response.status_code == 202
    approval_id = response.json()["approval_id"]
    pending = history.json()["pending_approvals"]
    assert pending[0]["approval_id"] == approval_id
    assert pending[0]["confirmation"]["approval_id"] == approval_id


def test_dashboard_chat_biomed_parse_review_includes_run_artifacts(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=bus, event_bus=event_bus)
    ) as client:
        response = client.post(
            "/api/dashboard/chat/commands/parse",
            json={
                "session_key": "dashboard:default",
                "content": "/biomed review biomed-run-123abc",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "review"
    assert payload["artifacts"]["run_id"] == "biomed-run-123abc"
    assert payload["artifacts"]["review_url"].endswith("/biomed-run-123abc/evidence-review")
    assert "report_type=pilot" in payload["artifacts"]["pilot_report_json_url"]
    assert payload["artifacts"]["argument_graph_url"].endswith("/biomed-run-123abc/argument-graph")


def test_dashboard_chat_biomed_parse_pilot_report_command(tmp_path) -> None:
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=_FakeBus(), event_bus=EventBus())
    ) as client:
        response = client.post(
            "/api/dashboard/chat/commands/parse",
            json={
                "session_key": "dashboard:default",
                "content": "/biomed pilot-report biomed-run-123abc --format json --baseline-minutes 120 --reviewer-minutes 45",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "pilot_report"
    assert payload["tool_name"] == "export_evidence_report"
    assert payload["can_send"] is True
    assert payload["arguments"]["report_type"] == "pilot"
    assert payload["arguments"]["format"] == "json"
    assert payload["arguments"]["manual_baseline_minutes"] == 120
    assert payload["arguments"]["reviewer_minutes"] == 45
    assert payload["confirmation"] is None
    assert payload["artifacts"]["pilot_report_markdown_url"].endswith("format=markdown")


def test_dashboard_chat_biomed_parse_template_run_command(tmp_path) -> None:
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=_FakeBus(), event_bus=EventBus())
    ) as client:
        response = client.post(
            "/api/dashboard/chat/commands/parse",
            json={
                "session_key": "dashboard:default",
                "content": '/biomed template run biomed-template-reviewer-handoff "microglia Alzheimer disease" --source mock --project project-1',
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "template_run"
    assert payload["tool_name"] == "run_saved_tool_chain_template"
    assert payload["can_send"] is True
    assert payload["arguments"] == {
        "template_id": "biomed-template-reviewer-handoff",
        "question": "microglia Alzheimer disease",
        "source_override": "mock",
        "project_id": "project-1",
    }


def test_dashboard_chat_biomed_parse_export_includes_artifact_urls(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=bus, event_bus=event_bus)
    ) as client:
        response = client.post(
            "/api/dashboard/chat/commands/parse",
            json={
                "session_key": "dashboard:default",
                "content": "/biomed export provenance biomed-run-123abc",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "export_provenance"
    assert payload["artifacts"]["run_id"] == "biomed-run-123abc"
    assert payload["artifacts"]["packet_url"].endswith("/biomed-run-123abc/evidence-review/packet")
    assert payload["artifacts"]["trace_url"].endswith("/biomed-run-123abc/trace")
    assert payload["artifacts"]["provenance_url"].endswith("/biomed-run-123abc/provenance")
    assert payload["artifacts"]["evidence_graph_url"].endswith("/biomed-run-123abc/evidence-graph")


def test_dashboard_chat_biomed_message_routes_command_prompt_through_bus(
    tmp_path,
) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            biomed_revision_provider=object(),
            biomed_revision_model="test-model",
        )
    ) as client:
        response = client.post(
            "/api/dashboard/chat/messages",
            json={
                "session_key": "dashboard:default",
                "content": '/biomed audit "microglia Alzheimer disease" --source mock --papers 10 --llm all',
            },
        )

    assert response.status_code == 202
    assert len(bus.inbound_items) == 1
    inbound = bus.inbound_items[0]
    assert inbound.channel == "dashboard"
    assert inbound.metadata["raw_content"].startswith("/biomed audit")
    assert inbound.metadata["command"]["action"] == "audit"
    assert inbound.content.startswith("Run a research-only Biomedical Evidence")


def test_dashboard_chat_biomed_help_is_deterministic(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            biomed_revision_provider=object(),
            biomed_revision_model="test-model",
        )
    ) as client:
        response = client.post(
            "/api/dashboard/chat/messages",
            json={"session_key": "dashboard:default", "content": "/biomed help"},
        )
        history = client.get("/api/dashboard/chat/history", params={"session_key": "dashboard:default"})

    assert response.status_code == 202
    assert response.json()["command"]["action"] == "help"
    assert response.json()["deterministic_response"] is True
    assert len(bus.inbound_items) == 0
    items = history.json()["items"]
    assert items[-2]["role"] == "user"
    assert items[-1]["role"] == "assistant"
    assert items[-1]["content"].startswith("## /biomed commands")
    assert "Biomedical Evidence is research-only" in items[-1]["content"]


def test_dashboard_chat_biomed_status_is_deterministic(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            biomed_revision_provider=object(),
            biomed_revision_model="test-model",
        )
    ) as client:
        response = client.post(
            "/api/dashboard/chat/messages",
            json={"session_key": "dashboard:default", "content": "/biomed status"},
        )
        history = client.get(
            "/api/dashboard/chat/history",
            params={"session_key": "dashboard:default"},
        )

    assert response.status_code == 202
    assert response.json()["command"]["action"] == "status"
    assert response.json()["deterministic_response"] is True
    assert len(bus.inbound_items) == 0
    items = history.json()["items"]
    assert items[-1]["content"].startswith("## Biomedical Evidence status")
    assert items[-1]["extra"]["command"]["action"] == "status"


def test_dashboard_chat_biomed_review_history_preserves_artifact_metadata(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(
            tmp_path,
            message_bus=bus,
            event_bus=event_bus,
            biomed_revision_provider=object(),
            biomed_revision_model="test-model",
        )
    ) as client:
        response = client.post(
            "/api/dashboard/chat/messages",
            json={
                "session_key": "dashboard:default",
                "content": "/biomed review biomed-run-123abc",
            },
        )

    assert response.status_code == 202
    assert len(bus.inbound_items) == 1
    command = bus.inbound_items[0].metadata["command"]
    assert command["artifacts"]["run_id"] == "biomed-run-123abc"
    assert command["artifacts"]["review_url"].endswith("/biomed-run-123abc/evidence-review")
    assert command["artifacts"]["pilot_report_json_url"].endswith("format=json")


@pytest.mark.asyncio
async def test_dashboard_chat_outbound_adds_artifacts_from_run_id_text(tmp_path) -> None:
    mux = DashboardChatMultiplexer(bus=None, event_bus=None)
    queue = await mux.subscribe("dashboard:default")
    try:
        await mux._on_outbound(
            OutboundMessage(
                channel="dashboard",
                chat_id="default",
                content="Run complete: biomed-run-abc123",
                metadata={"session_key_override": "dashboard:default"},
            )
        )
        assistant_event, assistant_payload = await queue.get()
    finally:
        await mux.unsubscribe("dashboard:default", queue)

    assert assistant_event == "assistant_message"
    assert assistant_payload["metadata"]["artifacts"]["run_id"] == "biomed-run-abc123"


@pytest.mark.asyncio
async def test_dashboard_chat_tool_completed_adds_nested_run_artifacts(tmp_path) -> None:
    mux = DashboardChatMultiplexer(bus=None, event_bus=None)
    queue = await mux.subscribe("dashboard:default")
    try:
        await mux._on_tool_completed(
            ToolCallCompleted(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
                iteration=1,
                call_id="call-1",
                tool_name="answer_with_audit",
                arguments={},
                final_arguments={},
                status="success",
                result_preview='{"answer_result":{"run_id":"biomed-run-abc123"}}',
            )
        )
        event, payload = await queue.get()
    finally:
        await mux.unsubscribe("dashboard:default", queue)

    assert event == "tool_completed"
    assert payload["metadata"]["artifacts"]["run_id"] == "biomed-run-abc123"
    assert payload["metadata"]["artifacts"]["pilot_report_json_url"].endswith("format=json")


def test_dashboard_chat_first_message_updates_placeholder_title(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=bus, event_bus=event_bus)
    ) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        resp = client.post(
            "/api/dashboard/chat/messages",
            json={
                "content": "Please help me review microglia activation in Alzheimer disease progression",
                "session_key": session_key,
            },
        )
        session = client.get(f"/api/dashboard/sessions/{session_key}")

    assert resp.status_code == 202
    assert session.status_code == 200
    metadata = session.json()["metadata"]
    assert metadata["title"] == "review microglia activation in Alzheimer disease"
    assert metadata["title_source"] == "auto_first_user"


def test_dashboard_chat_first_message_does_not_overwrite_user_title(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=bus, event_bus=event_bus)
    ) as client:
        create = client.post("/api/dashboard/chat/sessions", json={"title": "Custom title"})
        session_key = create.json()["key"]
        patch = client.patch(
            f"/api/dashboard/sessions/{session_key}",
            json={
                "metadata": {
                    "title": "User title",
                    "title_source": "user",
                    "created_from": "dashboard_chat",
                }
            },
        )
        resp = client.post(
            "/api/dashboard/chat/messages",
            json={"content": "rename me from this prompt", "session_key": session_key},
        )
        session = client.get(f"/api/dashboard/sessions/{session_key}")

    assert patch.status_code == 200
    assert resp.status_code == 202
    assert session.json()["metadata"]["title"] == "User title"
    assert session.json()["metadata"]["title_source"] == "user"


def test_dashboard_chat_post_accepts_custom_dashboard_session(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=bus, event_bus=event_bus)
    ) as client:
        resp = client.post(
            "/api/dashboard/chat/messages",
            json={"content": "hello", "session_key": "dashboard:project-alpha"},
        )

    assert resp.status_code == 202
    assert resp.json()["session_key"] == "dashboard:project-alpha"
    assert resp.json()["chat_id"] == "project-alpha"
    assert bus.inbound_items[0].session_key == "dashboard:project-alpha"


def test_dashboard_chat_validates_payload(tmp_path) -> None:
    bus = _FakeBus()
    event_bus = EventBus()
    with TestClient(
        create_dashboard_app(tmp_path, message_bus=bus, event_bus=event_bus)
    ) as client:
        empty = client.post(
            "/api/dashboard/chat/messages",
            json={"content": "   "},
        )
        wrong_session = client.post(
            "/api/dashboard/chat/messages",
            json={"content": "hello", "session_key": "telegram:100"},
        )
        too_long = client.post(
            "/api/dashboard/chat/messages",
            json={"content": "x" * 16001},
        )

    assert empty.status_code == 400
    assert wrong_session.status_code == 400
    assert too_long.status_code == 400
    assert bus.inbound_items == []


@pytest.mark.asyncio
async def test_dashboard_chat_approval_event_persists_to_history(tmp_path) -> None:
    mux_store = SessionStore(tmp_path / "sessions.db")
    mux_store.create_session(key="dashboard:default", metadata={})
    mux = DashboardChatMultiplexer(bus=None, event_bus=None, store=mux_store)
    try:
        await mux._on_tool_approval_required(
            ToolCallApprovalRequired(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
                iteration=1,
                call_id="call-1",
                tool_name="record_run_review_decision",
                arguments={"run_id": "run-1"},
                final_arguments={"run_id": "run-1", "decision": "accept"},
                reason="requires confirmation",
                confirmation={"approval_id": "approval-1"},
            )
        )
        meta = mux_store.get_session_meta("dashboard:default")
    finally:
        mux_store.close()

    pending = meta["metadata"]["pending_approvals"]
    assert pending["approval-1"]["status"] == "pending"
    assert pending["approval-1"]["tool_name"] == "record_run_review_decision"


@pytest.mark.asyncio
async def test_dashboard_chat_tool_completed_approval_required_persists_to_history(tmp_path) -> None:
    mux_store = SessionStore(tmp_path / "sessions.db")
    mux_store.create_session(key="dashboard:default", metadata={})
    mux = DashboardChatMultiplexer(bus=None, event_bus=None, store=mux_store)
    try:
        await mux._on_tool_completed(
            ToolCallCompleted(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
                iteration=1,
                call_id="call-1",
                tool_name="watch_research_topic",
                arguments={"topic": "Microglia AD"},
                final_arguments={"topic": "Microglia AD", "schedule": "daily"},
                status="approval_required",
                result_preview="This action requires confirmation in Dashboard Chat. Approval ID: approval-1",
            )
        )
        meta = mux_store.get_session_meta("dashboard:default")
    finally:
        mux_store.close()

    pending = meta["metadata"]["pending_approvals"]
    assert pending["approval-1"]["status"] == "pending"
    assert pending["approval-1"]["tool_name"] == "watch_research_topic"
    assert pending["approval-1"]["final_arguments"]["schedule"] == "daily"


def test_dashboard_chat_history_restores_approval_from_tool_completed(tmp_path) -> None:
    app = create_dashboard_app(
        tmp_path,
        message_bus=_FakeBus(),
        event_bus=EventBus(),
        tool_registry=_FakeToolRegistry(),
    )
    with TestClient(app) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        session = SessionStore(tmp_path / "sessions.db")
        try:
            session.insert_message(
                session_key,
                role="assistant",
                content="This action requires confirmation in Dashboard Chat. Approval ID: approval-1",
                ts="2026-06-16T12:00:00+02:00",
                seq=0,
                extra={
                    "status": "approval_required",
                    "approval_id": "approval-1",
                    "tool_name": "watch_research_topic",
                    "call_id": "call-1",
                    "iteration": 1,
                    "arguments": {"topic": "Microglia AD"},
                    "final_arguments": {"topic": "Microglia AD"},
                    "confirmation": {"approval_id": "approval-1"},
                },
            )
        finally:
            session.close()
        history = client.get(
            "/api/dashboard/chat/history",
            params={"session_key": session_key},
        )

    payload = history.json()
    assert payload["pending_approvals"][0]["approval_id"] == "approval-1"
    assert payload["pending_approvals"][0]["tool_name"] == "watch_research_topic"


def test_dashboard_chat_approval_endpoint_executes_confirmed_tool(tmp_path) -> None:
    registry = _FakeToolRegistry()
    app = create_dashboard_app(
        tmp_path,
        message_bus=_FakeBus(),
        event_bus=EventBus(),
        tool_registry=registry,
    )
    with TestClient(app) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        session = SessionStore(tmp_path / "sessions.db")
        try:
            session.update_session(
                session_key,
                metadata={
                    "title": "Approval test",
                    "pending_approvals": {
                        "approval-1": {
                            "approval_id": "approval-1",
                            "status": "pending",
                            "tool_name": "record_run_review_decision",
                            "final_arguments": {
                                "run_id": "run-1",
                                "decision": "accept",
                            },
                        }
                    },
                },
            )
        finally:
            session.close()
        response = client.post(
            "/api/dashboard/chat/approvals/approval-1",
            params={"session_key": session_key},
            json={"decision": "approve"},
        )
        history = client.get(
            "/api/dashboard/chat/history",
            params={"session_key": session_key},
        )

    assert response.status_code == 200


def test_dashboard_chat_approval_endpoint_rejects_without_execution_and_blocks_duplicates(tmp_path) -> None:
    registry = _FakeToolRegistry()
    app = create_dashboard_app(
        tmp_path,
        message_bus=_FakeBus(),
        event_bus=EventBus(),
        tool_registry=registry,
    )
    with TestClient(app) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        session = SessionStore(tmp_path / "sessions.db")
        try:
            session.update_session(
                session_key,
                metadata={
                    "pending_approvals": {
                        "approval-1": {
                            "approval_id": "approval-1",
                            "status": "pending",
                            "tool_name": "record_run_review_decision",
                            "final_arguments": {"run_id": "run-1", "decision": "accept"},
                        }
                    },
                },
            )
        finally:
            session.close()
        rejected = client.post(
            "/api/dashboard/chat/approvals/approval-1",
            params={"session_key": session_key},
            json={"decision": "reject"},
        )
        duplicate = client.post(
            "/api/dashboard/chat/approvals/approval-1",
            params={"session_key": session_key},
            json={"decision": "approve"},
        )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert duplicate.status_code == 409
    assert registry.calls == []


def test_dashboard_chat_approval_endpoint_marks_tool_call_approved(tmp_path) -> None:
    registry = _FakeToolRegistry()
    app = create_dashboard_app(
        tmp_path,
        message_bus=_FakeBus(),
        event_bus=EventBus(),
        tool_registry=registry,
        tool_hooks=[_RequireApprovedHook()],
    )
    with TestClient(app) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        session = SessionStore(tmp_path / "sessions.db")
        try:
            session.update_session(
                session_key,
                metadata={
                    "title": "Approval test",
                    "pending_approvals": {
                        "approval-1": {
                            "approval_id": "approval-1",
                            "status": "pending",
                            "tool_name": "watch_research_topic",
                            "final_arguments": {
                                "topic": "Microglia AD",
                                "description": "microglia Alzheimer disease progression",
                            },
                        }
                    },
                },
            )
        finally:
            session.close()
        response = client.post(
            "/api/dashboard/chat/approvals/approval-1",
            params={"session_key": session_key},
            json={"decision": "approve"},
        )

    assert response.status_code == 200
    assert registry.calls[0] == (
        "watch_research_topic",
        {
            "topic": "Microglia AD",
            "description": "microglia Alzheimer disease progression",
        },
    )
    assert registry.calls[1][0] == "schedule"
    assert registry.calls[1][1]["name"] == "biomed-watch:watch-test123"
    assert registry.calls[1][1]["trigger"] == "every"
    assert registry.calls[1][1]["when"] == "1d"


def test_dashboard_chat_approval_response_includes_watch_artifacts_and_schedule(
    tmp_path,
) -> None:
    registry = _FakeToolRegistry()
    app = create_dashboard_app(
        tmp_path,
        message_bus=_FakeBus(),
        event_bus=EventBus(),
        tool_registry=registry,
        tool_hooks=[_RequireApprovedHook()],
    )
    with TestClient(app) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        session = SessionStore(tmp_path / "sessions.db")
        try:
            session.update_session(
                session_key,
                metadata={
                    "title": "Watch approval test",
                    "pending_approvals": {
                        "approval-1": {
                            "approval_id": "approval-1",
                            "status": "pending",
                            "tool_name": "watch_research_topic",
                            "final_arguments": {
                                "topic": "Microglia AD",
                                "description": "microglia Alzheimer disease progression",
                                "schedule": "weekly",
                            },
                        }
                    },
                },
            )
        finally:
            session.close()
        response = client.post(
            "/api/dashboard/chat/approvals/approval-1",
            params={"session_key": session_key},
            json={"decision": "approve"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifacts"]["watch_id"] == "watch-test123"
    assert payload["framework_schedule"]["status"] == "registered"
    assert payload["framework_schedule"]["name"] == "biomed-watch:watch-test123"
    assert payload["framework_schedule"]["interval"] == "7d"


def test_dashboard_chat_approval_delete_watch_cancels_framework_schedule(
    tmp_path,
) -> None:
    registry = _FakeToolRegistry()
    app = create_dashboard_app(
        tmp_path,
        message_bus=_FakeBus(),
        event_bus=EventBus(),
        tool_registry=registry,
        tool_hooks=[_RequireApprovedHook()],
    )
    with TestClient(app) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        session = SessionStore(tmp_path / "sessions.db")
        try:
            session.update_session(
                session_key,
                metadata={
                    "title": "Watch delete approval test",
                    "pending_approvals": {
                        "approval-1": {
                            "approval_id": "approval-1",
                            "status": "pending",
                            "tool_name": "delete_research_watch_topic",
                            "final_arguments": {"watch_id": "watch-test123"},
                        }
                    },
                },
            )
        finally:
            session.close()
        response = client.post(
            "/api/dashboard/chat/approvals/approval-1",
            params={"session_key": session_key},
            json={"decision": "approve"},
        )

    assert response.status_code == 200
    assert registry.calls[0] == (
        "delete_research_watch_topic",
        {"watch_id": "watch-test123"},
    )
    assert registry.calls[1] == (
        "cancel_schedule",
        {"name": "biomed-watch:watch-test123"},
    )
    payload = response.json()
    assert payload["framework_schedule"]["status"] == "requested"
    assert payload["framework_schedule"]["name"] == "biomed-watch:watch-test123"


def test_dashboard_chat_history_returns_pending_approval_id(tmp_path) -> None:
    app = create_dashboard_app(
        tmp_path,
        message_bus=_FakeBus(),
        event_bus=EventBus(),
        tool_registry=_FakeToolRegistry(),
    )
    with TestClient(app) as client:
        create = client.post("/api/dashboard/chat/sessions", json={})
        session_key = create.json()["key"]
        session = SessionStore(tmp_path / "sessions.db")
        try:
            session.update_session(
                session_key,
                metadata={
                    "title": "Approval history",
                    "pending_approvals": {
                        "approval-1": {
                            "approval_id": "approval-1",
                            "status": "pending",
                            "tool_name": "watch_research_topic",
                            "confirmation": {"approval_id": "approval-1"},
                            "final_arguments": {"topic": "Microglia AD"},
                        }
                    },
                },
            )
        finally:
            session.close()
        history = client.get(
            "/api/dashboard/chat/history",
            params={"session_key": session_key},
        )

    assert history.status_code == 200
    payload = history.json()
    assert payload["pending_approvals"][0]["approval_id"] == "approval-1"
    assert payload["pending_approvals"][0]["confirmation"]["approval_id"] == "approval-1"


@pytest.mark.asyncio
async def test_dashboard_chat_multiplexer_fans_out_by_session() -> None:
    mux = DashboardChatMultiplexer(bus=None, event_bus=None)
    first = await mux.subscribe("dashboard:default")
    second = await mux.subscribe("dashboard:other")
    try:
        await mux._on_outbound(
            OutboundMessage(
                channel="dashboard",
                chat_id="default",
                content="hello back",
            )
        )
        event, payload = await asyncio.wait_for(first.get(), timeout=1.0)
    finally:
        await mux.unsubscribe("dashboard:default", first)
        await mux.unsubscribe("dashboard:other", second)

    assert event == "assistant_message"
    assert payload["content"] == "hello back"
    assert payload["session_key"] == "dashboard:default"
    assert second.empty()


def test_dashboard_chat_stream_connected_event_payload() -> None:
    payload = _sse_payload(
        "connected",
        {"event": "connected", "session_key": "dashboard:default"},
    )

    assert payload.startswith("event: connected\ndata: ")
    assert '"session_key":"dashboard:default"' in payload
    assert payload.endswith("\n\n")


@pytest.mark.asyncio
async def test_dashboard_chat_multiplexer_replays_events_after_cursor() -> None:
    mux = DashboardChatMultiplexer(bus=None, event_bus=None)
    await mux.publish_user_message_accepted(
        session_key="dashboard:default",
        content="first",
    )
    await mux.publish_user_message_accepted(
        session_key="dashboard:default",
        content="second",
    )

    queue = await mux.subscribe("dashboard:default", since_seq=1)
    try:
        event, payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    finally:
        await mux.unsubscribe("dashboard:default", queue)

    assert event == "user_message_accepted"
    assert payload["seq"] == 2
    assert payload["content_preview"] == "second"
    assert await mux.latest_seq("dashboard:default") == 2


@pytest.mark.asyncio
async def test_dashboard_chat_multiplexer_keeps_replay_after_done() -> None:
    mux = DashboardChatMultiplexer(bus=None, event_bus=None)
    await mux.publish_user_message_accepted(
        session_key="dashboard:default",
        content="first",
    )
    assert await mux.is_active("dashboard:default") is True
    await mux._on_outbound(
        OutboundMessage(
            channel="dashboard",
            chat_id="default",
            content="final",
        )
    )
    assert await mux.is_active("dashboard:default") is False

    queue = await mux.subscribe("dashboard:default", since_seq=1)
    try:
        event, payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    finally:
        await mux.unsubscribe("dashboard:default", queue)

    assert event == "assistant_message"
    assert payload["content"] == "final"
    assert payload["seq"] == 2


def test_dashboard_chat_history_redacts_sensitive_fields(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    store.create_session(key="dashboard:default")
    store.insert_message(
        "dashboard:default",
        role="assistant",
        content="safe answer",
        ts="2026-04-19T10:02:00+08:00",
        seq=0,
        tool_chain=[{"raw_prompt": "do not leak"}],
        extra={"api_key": "secret", "nested": {"authorization": "Bearer abc123456"}},
    )
    store.close()

    with TestClient(create_dashboard_app(tmp_path)) as client:
        resp = client.get(
            "/api/dashboard/chat/history",
            params={"session_key": "dashboard:default"},
        )

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["content"] == "safe answer"
    assert item["tool_chain"] is None
    assert item["extra"]["api_key"] == "[redacted]"
    assert item["extra"]["nested"]["authorization"] == "[redacted]"


@pytest.mark.asyncio
async def test_dashboard_chat_multiplexer_maps_lifecycle_events_and_redacts() -> None:
    mux = DashboardChatMultiplexer(bus=None, event_bus=None)
    queue = await mux.subscribe("dashboard:default")
    try:
        await mux._on_stream_delta(
            StreamDeltaReady(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
            )
        )
        assert queue.empty()

        await mux._on_stream_delta(
            StreamDeltaReady(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
                content_delta="hello",
            )
        )
        delta_event, delta_payload = await asyncio.wait_for(queue.get(), timeout=1.0)

        await mux._on_tool_started(
            ToolCallStarted(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
                iteration=1,
                call_id="call-1",
                tool_name="search_literature",
                arguments={"query": "microglia", "api_key": "secret"},
            )
        )
        tool_event, tool_payload = await asyncio.wait_for(queue.get(), timeout=1.0)

        await mux._on_after_step(
            AfterStepCtx(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
                iteration=1,
                context_tokens_estimate=100,
                tools_called=("search_literature",),
                partial_reply="working",
                tools_used_so_far=("search_literature",),
                tool_chain_partial=(),
                partial_thinking=None,
                has_more=False,
            )
        )
        step_event, step_payload = await asyncio.wait_for(queue.get(), timeout=1.0)

        await mux._on_tool_completed(
            ToolCallCompleted(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
                iteration=1,
                call_id="call-2",
                tool_name="record_run_review_decision",
                arguments={"api_key": "secret"},
                final_arguments={"decision": "supported", "token": "secret"},
                status="success",
                result_preview="completed with token=abc123456 redacted",
            )
        )
        completed_event, completed_payload = await asyncio.wait_for(
            queue.get(),
            timeout=1.0,
        )
    finally:
        await mux.unsubscribe("dashboard:default", queue)

    assert delta_event == "assistant_delta"
    assert delta_payload["kind"] == "assistant"
    assert delta_payload["content_delta"] == "hello"
    assert tool_event == "tool_started"
    assert tool_payload["kind"] == "tool"
    assert tool_payload["arguments"]["api_key"] == "[redacted]"
    assert step_event == "step"
    assert step_payload["kind"] == "system"
    assert step_payload["has_more"] is False
    assert completed_event == "tool_completed"
    assert completed_payload["kind"] == "tool"
    assert completed_payload["status"] == "success"
    assert completed_payload["arguments"]["api_key"] == "[redacted]"
    assert completed_payload["final_arguments"]["token"] == "[redacted]"
    assert "[redacted]" in completed_payload["detail"]


@pytest.mark.asyncio
async def test_dashboard_chat_tool_events_include_cockpit_phase_metadata(
    tmp_path,
) -> None:
    mux = DashboardChatMultiplexer(bus=None, event_bus=None)
    queue = await mux.subscribe("dashboard:default")
    try:
        await mux._on_tool_started(
            ToolCallStarted(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
                iteration=1,
                call_id="call-1",
                tool_name="search_literature",
                arguments={"query": "microglia"},
            )
        )
        started_event, started_payload = await asyncio.wait_for(queue.get(), timeout=1.0)

        await mux._on_tool_completed(
            ToolCallCompleted(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
                iteration=1,
                call_id="call-1",
                tool_name="answer_with_audit",
                arguments={},
                final_arguments={},
                status="success",
                result_preview='{"answer_result":{"run_id":"biomed-run-abc123"}}',
            )
        )
        completed_event, completed_payload = await asyncio.wait_for(
            queue.get(), timeout=1.0
        )
    finally:
        await mux.unsubscribe("dashboard:default", queue)

    assert started_event == "tool_started"
    assert started_payload["cockpit_phase"] == "retrieval"
    assert started_payload["cockpit_status"] == "running"
    assert completed_event == "tool_completed"
    assert completed_payload["cockpit_phase"] == "done"
    assert completed_payload["cockpit_status"] == "completed"
    assert completed_payload["metadata"]["artifacts"]["run_id"] == "biomed-run-abc123"


@pytest.mark.asyncio
async def test_dashboard_chat_tool_failure_includes_recovery_guidance(
    tmp_path,
) -> None:
    mux = DashboardChatMultiplexer(bus=None, event_bus=None)
    queue = await mux.subscribe("dashboard:default")
    try:
        await mux._on_tool_completed(
            ToolCallCompleted(
                session_key="dashboard:default",
                channel="dashboard",
                chat_id="default",
                iteration=1,
                call_id="call-1",
                tool_name="search_literature",
                arguments={"source": "pubmed"},
                final_arguments={"source": "pubmed"},
                status="error",
                result_preview="Live PubMed disabled by source policy.",
            )
        )
        event, payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    finally:
        await mux.unsubscribe("dashboard:default", queue)

    assert event == "tool_completed"
    assert payload["cockpit_phase"] == "retrieval"
    assert payload["cockpit_status"] == "failed"
    assert payload["recovery"]["retryable"] is False
    assert payload["recovery"]["action"] == "enable_pubmed"
    assert "PubMed" in payload["recovery"]["label"]


def test_update_and_delete_session(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(create_dashboard_app(tmp_path)) as client:
        patch_resp = client.patch(
            "/api/dashboard/sessions/telegram:100",
            json={"metadata": {"title": "patched"}, "last_consolidated": 9},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["metadata"]["title"] == "patched"
        assert patch_resp.json()["last_consolidated"] == 9

        delete_resp = client.delete("/api/dashboard/sessions/telegram:100")
        assert delete_resp.status_code == 200

        get_resp = client.get("/api/dashboard/sessions/telegram:100")
        assert get_resp.status_code == 404


def test_manual_consolidate_session_uses_runtime_entrypoint(tmp_path) -> None:
    _seed_workspace(tmp_path)
    consolidator = _ManualConsolidator(result=True)
    with TestClient(
        create_dashboard_app(tmp_path, manual_consolidator=consolidator)
    ) as client:
        resp = client.post(
            "/api/dashboard/sessions/telegram:100/consolidate",
            json={"archive_all": True},
        )

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["triggered"] is True
        assert payload["archive_all"] is True
        assert payload["force"] is True
        assert payload["session"]["key"] == "telegram:100"
        assert consolidator.calls == [("telegram:100", True, True)]


def test_manual_consolidate_session_requires_existing_session(tmp_path) -> None:
    _seed_workspace(tmp_path)
    consolidator = _ManualConsolidator(result=True)
    with TestClient(
        create_dashboard_app(tmp_path, manual_consolidator=consolidator)
    ) as client:
        resp = client.post("/api/dashboard/sessions/missing/consolidate", json={})

        assert resp.status_code == 404
        assert consolidator.calls == []


def test_manual_consolidate_session_reports_unavailable_runtime(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(create_dashboard_app(tmp_path)) as client:
        resp = client.post("/api/dashboard/sessions/telegram:100/consolidate", json={})

        assert resp.status_code == 503


def test_manual_consolidate_session_reports_concurrency_timeout(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(
        create_dashboard_app(
            tmp_path,
            manual_consolidator=_ManualConsolidator(error=TimeoutError("busy")),
        )
    ) as client:
        resp = client.post("/api/dashboard/sessions/telegram:100/consolidate", json={})

        assert resp.status_code == 409
        assert resp.json()["detail"] == "busy"


def test_manual_memory_optimizer_uses_runtime_entrypoint(tmp_path) -> None:
    optimizer = _ManualMemoryOptimizer()
    with TestClient(
        create_dashboard_app(tmp_path, manual_memory_optimizer=optimizer)
    ) as client:
        resp = client.post("/api/dashboard/memory/optimize")

    assert resp.status_code == 202
    assert resp.json()["status"] == "started"
    assert optimizer.started.wait(1.0)
    assert optimizer.calls == 1


def test_manual_memory_optimizer_reports_unavailable_runtime(tmp_path) -> None:
    with TestClient(create_dashboard_app(tmp_path)) as client:
        status_resp = client.get("/api/dashboard/memory/optimizer")
        resp = client.post("/api/dashboard/memory/optimize")

        assert status_resp.status_code == 200
        assert status_resp.json()["enabled"] is False
        assert resp.status_code == 503


def test_manual_memory_optimizer_reports_busy_runtime(tmp_path) -> None:
    optimizer = _ManualMemoryOptimizer(block=True)
    with TestClient(
        create_dashboard_app(tmp_path, manual_memory_optimizer=optimizer)
    ) as client:
        first_resp = client.post("/api/dashboard/memory/optimize")
        assert first_resp.status_code == 202
        assert optimizer.started.wait(1.0)
        status_resp = client.get("/api/dashboard/memory/optimizer")

        busy_resp = client.post("/api/dashboard/memory/optimize")
        optimizer.release.set()

    assert status_resp.status_code == 200
    assert status_resp.json()["enabled"] is True
    assert status_resp.json()["running"] is True
    assert status_resp.json()["last_status"] == "running"
    assert busy_resp.status_code == 409
    assert optimizer.calls == 1


def test_manual_memory_optimizer_skips_when_backend_reports_busy(tmp_path) -> None:
    optimizer = _ManualMemoryOptimizer()
    optimizer.raise_busy = True
    with TestClient(
        create_dashboard_app(tmp_path, manual_memory_optimizer=optimizer)
    ) as client:
        start_resp = client.post("/api/dashboard/memory/optimize")
        status_resp = client.get("/api/dashboard/memory/optimizer")

    assert start_resp.status_code == 202
    assert status_resp.status_code == 200
    assert status_resp.json()["running"] is False
    assert status_resp.json()["last_status"] == "skipped"


def test_list_update_and_batch_delete_messages(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(create_dashboard_app(tmp_path)) as client:
        list_resp = client.get(
            "/api/dashboard/sessions/telegram:100/messages",
            params={"q": "睡", "role": "assistant"},
        )
        assert list_resp.status_code == 200
        payload = list_resp.json()
        assert payload["total"] == 1
        message_id = payload["items"][0]["id"]

        patch_resp = client.patch(
            f"/api/dashboard/messages/{message_id}",
            json={"content": "已经睡了", "extra": {"edited": True}},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["content"] == "已经睡了"
        assert patch_resp.json()["edited"] is True

        batch_resp = client.post(
            "/api/dashboard/messages/batch-delete",
            json={"ids": [message_id, "cli:local:0"]},
        )
        assert batch_resp.status_code == 200
        assert batch_resp.json()["deleted_count"] == 2

        remain_resp = client.get(
            "/api/dashboard/messages", params={"session_key": "telegram:100"}
        )
        assert remain_resp.status_code == 200
        assert remain_resp.json()["total"] == 1


def test_list_memory_items_with_filters(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(create_dashboard_app(tmp_path)) as client:
        resp = client.get(
            "/api/dashboard/memories",
            params={
                "q": "奶茶",
                "memory_type": "preference",
                "scope_channel": "telegram",
                "has_embedding": "true",
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["total"] == 1
        assert payload["items"][0]["memory_type"] == "preference"
        assert payload["items"][0]["scope_chat_id"] == "100"
        assert payload["items"][0]["has_embedding"] is True

        status_resp = client.get(
            "/api/dashboard/memories",
            params={
                "memory_type": "profile",
                "status": "active",
                "page_size": 1,
            },
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["total"] == 1
        assert status_resp.json()["items"][0]["memory_type"] == "profile"


def test_list_memory_items_sorts_by_created_at_desc(tmp_path) -> None:
    _seed_workspace(tmp_path)
    conn = sqlite3.connect(tmp_path / "memory" / "memory2.db")
    try:
        conn.execute(
            "UPDATE memory_items SET created_at=? WHERE source_ref=?",
            ("2026-04-19T10:00:00+08:00", "telegram:100:pref"),
        )
        conn.execute(
            "UPDATE memory_items SET created_at=? WHERE source_ref=?",
            ("2026-04-19T11:00:00+08:00", "telegram:100:event"),
        )
        conn.execute(
            "UPDATE memory_items SET created_at=? WHERE source_ref=?",
            ("2026-04-19T12:00:00+08:00", "cli:local:profile"),
        )
        conn.commit()
    finally:
        conn.close()
    with TestClient(create_dashboard_app(tmp_path)) as client:
        resp = client.get(
            "/api/dashboard/memories",
            params={"sort_by": "created_at", "sort_order": "desc"},
        )

        assert resp.status_code == 200
        assert [item["source_ref"] for item in resp.json()["items"]] == [
            "cli:local:profile",
            "telegram:100:event",
            "telegram:100:pref",
        ]


def test_list_memory_items_default_sort_is_created_at_desc(tmp_path) -> None:
    _seed_workspace(tmp_path)
    conn = sqlite3.connect(tmp_path / "memory" / "memory2.db")
    try:
        conn.execute(
            "UPDATE memory_items SET created_at=?, updated_at=? WHERE source_ref=?",
            (
                "2026-04-19T10:00:00+08:00",
                "2026-04-19T13:00:00+08:00",
                "telegram:100:pref",
            ),
        )
        conn.execute(
            "UPDATE memory_items SET created_at=?, updated_at=? WHERE source_ref=?",
            (
                "2026-04-19T11:00:00+08:00",
                "2026-04-19T12:00:00+08:00",
                "telegram:100:event",
            ),
        )
        conn.execute(
            "UPDATE memory_items SET created_at=?, updated_at=? WHERE source_ref=?",
            (
                "2026-04-19T12:00:00+08:00",
                "2026-04-19T11:00:00+08:00",
                "cli:local:profile",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    with TestClient(create_dashboard_app(tmp_path)) as client:
        resp = client.get("/api/dashboard/memories")

        assert resp.status_code == 200
        assert resp.json()["items"][0]["source_ref"] == "cli:local:profile"


def test_get_update_and_delete_memory(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(create_dashboard_app(tmp_path)) as client:
        list_resp = client.get("/api/dashboard/memories", params={"q": "奶茶"})
        memory_id = list_resp.json()["items"][0]["id"]

        get_resp = client.get(
            f"/api/dashboard/memories/{memory_id}",
            params={"include_embedding": "true"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["embedding_dim"] == 2

        patch_resp = client.patch(
            f"/api/dashboard/memories/{memory_id}",
            json={
                "status": "superseded",
                "source_ref": "telegram:100:pref:patched",
                "emotional_weight": 9,
                "extra_json": {"scope_channel": "telegram", "scope_chat_id": "100"},
            },
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "superseded"
        assert patch_resp.json()["emotional_weight"] == 9
        assert patch_resp.json()["source_ref"] == "telegram:100:pref:patched"

        delete_resp = client.delete(f"/api/dashboard/memories/{memory_id}")
        assert delete_resp.status_code == 200

        missing_resp = client.get(f"/api/dashboard/memories/{memory_id}")
        assert missing_resp.status_code == 404


def test_memory_similar_and_batch_delete(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(create_dashboard_app(tmp_path)) as client:
        list_resp = client.get(
            "/api/dashboard/memories", params={"scope_channel": "telegram"}
        )
        items = list_resp.json()["items"]
        pref = next(item for item in items if item["memory_type"] == "preference")
        event = next(item for item in items if item["memory_type"] == "event")

        similar_resp = client.get(f"/api/dashboard/memories/{pref['id']}/similar")
        assert similar_resp.status_code == 200
        assert similar_resp.json()["total"] >= 1
        assert similar_resp.json()["items"][0]["id"] == event["id"]

        batch_resp = client.post(
            "/api/dashboard/memories/batch-delete",
            json={"ids": [pref["id"], event["id"]]},
        )
        assert batch_resp.status_code == 200
        assert batch_resp.json()["deleted_count"] == 2


def test_memory_dashboard_filters_survive_parallel_requests(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(create_dashboard_app(tmp_path)) as client:

        def _fetch(memory_type: str) -> tuple[int, dict]:
            resp = client.get(
                "/api/dashboard/memories",
                params={
                    "status": "active",
                    "memory_type": memory_type,
                    "page_size": 1,
                    "sort_by": "updated_at",
                    "sort_order": "desc",
                },
            )
            return resp.status_code, resp.json()

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(
                executor.map(_fetch, ["procedure", "preference", "profile", "event"])
            )

        for status_code, payload in results:
            assert status_code == 200
            assert "total" in payload


def test_proactive_dashboard_endpoints(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(create_dashboard_app(tmp_path)) as client:
        overview_resp = client.get("/api/dashboard/proactive/overview")
        assert overview_resp.status_code == 200
        overview = overview_resp.json()
        assert overview["counts"]["seen_items"] == 3
        assert overview["counts"]["deliveries"] == 2
        assert overview["counts"]["tick_logs"] == 2
        assert overview["flow_counts"]["drift"] == 1
        assert overview["flow_counts"]["proactive"] == 1
        assert overview["last_tick_at"] == "2026-04-19T03:00:00+00:00"
        assert overview["last_send_at"] == "2026-04-19T02:06:00+00:00"
        assert overview["last_skip_reason"] == "busy"

        deliveries_resp = client.get(
            "/api/dashboard/proactive/deliveries",
            params={"session_key": "telegram:100"},
        )
        assert deliveries_resp.status_code == 200
        assert deliveries_resp.json()["total"] == 1
        assert deliveries_resp.json()["items"][0]["delivery_key"] == "delivery-a"

        seen_resp = client.get(
            "/api/dashboard/proactive/seen_items",
            params={"source_key": "mcp:feed"},
        )
        assert seen_resp.status_code == 200
        assert seen_resp.json()["total"] == 2

        semantic_resp = client.get(
            "/api/dashboard/proactive/semantic_items",
            params={"window_hours": 100000},
        )
        assert semantic_resp.status_code == 200
        assert semantic_resp.json()["total"] == 2

        tick_logs_resp = client.get(
            "/api/dashboard/proactive/tick_logs",
            params={"terminal_action": "skip"},
        )
        assert tick_logs_resp.status_code == 200
        assert tick_logs_resp.json()["total"] == 1
        assert tick_logs_resp.json()["items"][0]["tick_id"] == "tick-2"

        drift_logs_resp = client.get(
            "/api/dashboard/proactive/tick_logs",
            params={"flow": "drift"},
        )
        assert drift_logs_resp.status_code == 200
        assert drift_logs_resp.json()["total"] == 1
        assert drift_logs_resp.json()["items"][0]["tick_id"] == "tick-2"

        proactive_sorted_resp = client.get(
            "/api/dashboard/proactive/tick_logs",
            params={"sort_by": "started_at", "sort_order": "asc"},
        )
        assert proactive_sorted_resp.status_code == 200
        assert proactive_sorted_resp.json()["items"][0]["tick_id"] == "tick-1"

        tick_detail_resp = client.get("/api/dashboard/proactive/tick_logs/tick-1")
        assert tick_detail_resp.status_code == 200
        assert tick_detail_resp.json()["interesting_ids"] == ["mcp:feed:feed-1"]
        assert tick_detail_resp.json()["final_message"] == "记得早点休息"

        tick_steps_resp = client.get("/api/dashboard/proactive/tick_logs/tick-1/steps")
        assert tick_steps_resp.status_code == 200
        assert tick_steps_resp.json()["total"] == 2
        assert tick_steps_resp.json()["items"][0]["tool_name"] == "message_push"
        assert (
            tick_steps_resp.json()["items"][0]["tool_args"]["message"] == "记得早点休息"
        )
        assert tick_steps_resp.json()["items"][1]["terminal_action_after"] == "reply"


def test_status_commands_kvcache_dashboard_uses_workspace_observe(tmp_path) -> None:
    _seed_workspace(tmp_path)
    observe_dir = tmp_path / "observe"
    observe_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(observe_dir / "observe.db")
    try:
        conn.execute("""
            CREATE TABLE turns(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                source TEXT NOT NULL,
                session_key TEXT NOT NULL,
                user_msg TEXT,
                llm_output TEXT NOT NULL DEFAULT '',
                react_cache_prompt_tokens INTEGER,
                react_cache_hit_tokens INTEGER
            )
            """)
        conn.execute(
            """
            INSERT INTO turns(
                ts, source, session_key, user_msg, llm_output,
                react_cache_prompt_tokens, react_cache_hit_tokens
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-04-19T03:20:00+00:00",
                "agent",
                "telegram:100",
                "again",
                "ok",
                300,
                260,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    with TestClient(create_dashboard_app(tmp_path)) as client:
        overview = client.get("/api/dashboard/status-commands/kvcache/overview")
        turns = client.get("/api/dashboard/status-commands/kvcache/turns")

        assert overview.status_code == 200
        assert overview.json()["tracked_turn_count"] == 1
        assert overview.json()["hit_rate"] == 260 / 300
        assert turns.status_code == 200
        payload = turns.json()
        assert payload["total"] == 1
        assert payload["items"][0]["session_key"] == "telegram:100"
        assert payload["items"][0]["user_preview"] == "again"


def test_proactive_dashboard_batch_delete(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(create_dashboard_app(tmp_path)) as client:
        seen_delete_resp = client.request(
            "DELETE",
            "/api/dashboard/proactive/seen_items/batch",
            json={"source_key": "mcp:feed", "item_ids": ["feed-1"]},
        )
        assert seen_delete_resp.status_code == 200
        assert seen_delete_resp.json()["deleted_count"] == 1

        seen_resp = client.get(
            "/api/dashboard/proactive/seen_items",
            params={"source_key": "mcp:feed"},
        )
        assert seen_resp.json()["total"] == 1

        cooldown_delete_resp = client.request(
            "DELETE",
            "/api/dashboard/proactive/rejection_cooldown/batch",
            json={"source_key": "mcp:feed", "item_ids": ["feed-3"]},
        )
        assert cooldown_delete_resp.status_code == 200
        assert cooldown_delete_resp.json()["deleted_count"] == 1

        cooldown_resp = client.get(
            "/api/dashboard/proactive/rejection_cooldown",
            params={"source_key": "mcp:feed"},
        )
        assert cooldown_resp.status_code == 200
        assert cooldown_resp.json()["total"] == 0


def test_proactive_dashboard_batch_delete_rejects_empty_payload(tmp_path) -> None:
    _seed_workspace(tmp_path)
    with TestClient(create_dashboard_app(tmp_path)) as client:
        seen_delete_resp = client.request(
            "DELETE",
            "/api/dashboard/proactive/seen_items/batch",
            json={},
        )
        assert seen_delete_resp.status_code == 400
        assert seen_delete_resp.json()["detail"] == "至少提供 source_key 或 item_ids"

        cooldown_delete_resp = client.request(
            "DELETE",
            "/api/dashboard/proactive/rejection_cooldown/batch",
            json={},
        )
        assert cooldown_delete_resp.status_code == 400
        assert (
            cooldown_delete_resp.json()["detail"] == "至少提供 source_key 或 item_ids"
        )


def test_plugin_asset_paths_reject_cross_platform_traversal(tmp_path) -> None:
    with TestClient(create_dashboard_app(tmp_path)) as client:
        for path in (
            "/plugins/..%5Csecret/dashboard_panel.js",
            "/plugins/C:%5Csecret/dashboard_panel.js",
            "/plugins/%5C%5Cserver%5Cshare/dashboard_panel.css",
        ):
            response = client.get(path)
            assert response.status_code == 400

        assert client.get("/plugins/missing/dashboard_panel.js").status_code == 404


def test_biomed_dashboard_api_smoke_path(tmp_path) -> None:
    with TestClient(create_dashboard_app(tmp_path)) as client:
        plugins = client.get("/api/dashboard/plugins")
        assert plugins.status_code == 200
        assert any(item["id"] == "biomed_evidence" for item in plugins.json())

        panel = client.get("/plugins/biomed_evidence/dashboard_panel.js")
        assert panel.status_code == 200
        assert "Biomedical" in panel.text
        assert "Trace" in panel.text

        search = client.get(
            "/api/biomed/search",
            params={"query": "microglia", "source": "mock"},
        )
        assert search.status_code == 200
        assert search.json()["items"]

        plan = client.post(
            "/api/biomed/plan",
            json={
                "question": "What evidence links microglia to Alzheimer's disease?",
                "source": "mock",
                "max_results": 5,
            },
        )
        assert plan.status_code == 200
        assert plan.json()["validation"]["valid"] is True

        answer = client.post(
            "/api/biomed/answer",
            json={
                "question": "What evidence links microglia to Alzheimer's disease?",
                "source": "mock",
                "max_papers": 5,
            },
        )
        assert answer.status_code == 200
        assert answer.json()["citations"]

        audited = client.post(
            "/api/biomed/answer/audited",
            json={
                "question": "What evidence links microglia to Alzheimer's disease?",
                "source": "mock",
                "max_papers": 5,
                "use_llm_planner": True,
                "execute_support_refute": True,
            },
        )
        assert audited.status_code == 200
        assert audited.json()["trace"]
        assert audited.json()["answer_result"]["retrieval_bundle"]["executed_multi_query"] is True
        assert len(audited.json()["trace"]) == 11

        graph = client.get("/api/biomed/graph", params={"topic": "microglia"})
        assert graph.status_code == 200
        assert graph.json()["nodes"]


def test_memory_engine_plugins_only_expose_active_engine_panels(tmp_path) -> None:
    with TestClient(create_dashboard_app(tmp_path)) as client:
        plugins = client.get("/api/dashboard/plugins").json()
        memory_plugins = {
            item["id"]: [panel["name"] for panel in item["panels"]]
            for item in plugins
            if item["id"] in {"default_memory", "cross_memory"}
        }
        assert memory_plugins == {
            "default_memory": ["dashboard_panel", "dashboard_panel_inspector"]
        }
        assert client.get("/plugins/default_memory/dashboard_panel_inspector.js").status_code == 200
        assert client.get("/plugins/cross_memory/dashboard_panel_inspector.js").status_code == 404
