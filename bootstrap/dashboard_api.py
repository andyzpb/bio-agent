from __future__ import annotations

import asyncio
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path, PureWindowsPath
import importlib.util
import logging
import json
import re
import sqlite3
import sys
import threading
import secrets
import hashlib
import os
import shutil
from datetime import timedelta
from types import ModuleType
from typing import Any, Protocol, cast

import subprocess

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.lifecycle.types import AfterStepCtx
from agent.memory import MemoryStore
from agent.tool_hooks import ToolExecutionRequest, ToolExecutor
from bus.event_bus import EventBus
from bus.events import InboundMessage, OutboundMessage
from bus.events_lifecycle import (
    StreamDeltaReady,
    ToolCallApprovalRequired,
    ToolCallCompleted,
    ToolCallStarted,
    TurnStarted,
)
from bus.queue import MessageBus
from proactive_v2.memory_optimizer import MemoryOptimizerBusy
from proactive_v2.state import ProactiveStateStore
from core.common.timekit import utcnow
from core.memory.engine import MemoryAdminApi
from session.store import SessionStore

logger = logging.getLogger(__name__)

_DASHBOARD_ACCESS_PREFIXES = ("/api/dashboard", "/assets", "/plugins/")
_DASHBOARD_CHAT_CHANNEL = "dashboard"
_DASHBOARD_CHAT_DEFAULT_SESSION = "dashboard:default"
_DASHBOARD_CHAT_MAX_CONTENT_CHARS = 16000
_DASHBOARD_CHAT_MAX_SESSION_CHARS = 160
_DASHBOARD_CHAT_DISABLED_REASON = (
    "Dashboard Chat requires the full runtime. Start with python main.py, "
    "not python main.py dashboard."
)
_DASHBOARD_CHAT_REDACTED = "[redacted]"
_DASHBOARD_CHAT_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "id_token",
    "idtoken",
    "token",
    "secret",
    "password",
    "client_secret",
    "clientsecret",
    "raw_prompt",
    "prompt",
    "raw_provider_response",
    "provider_response",
}
_DASHBOARD_CHAT_SECRET_PATTERNS = (
    re.compile(
        r"\b(api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|token|authorization|secret|client[_-]?secret|password)\s*[:=]\s*[^,\s;]+",
        re.IGNORECASE,
    ),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
)
_DASHBOARD_CHAT_MAX_STRING_FIELD_CHARS = 4000
_DASHBOARD_CHAT_MAX_COLLECTION_ITEMS = 24
_DASHBOARD_CHAT_MAX_SANITIZE_DEPTH = 6
_DASHBOARD_CHAT_REPLAY_LIMIT = 400
_DASHBOARD_CHAT_APPROVALS_META_KEY = "pending_approvals"
_BIOMED_RUN_ID_RE = re.compile(r"\bbiomed-run-[A-Za-z0-9_-]+\b")
_BIOMED_WATCH_ID_RE = re.compile(r"\bwatch-[A-Za-z0-9_-]+\b")


def _is_plugin_disabled(plugin_dir: Path) -> bool:
    return (plugin_dir / "plugin.disabled").exists()


def _is_dashboard_access_record(record: logging.LogRecord) -> bool:
    args = record.args
    if not isinstance(args, tuple) or len(args) < 3:
        return False
    path = args[2]
    if not isinstance(path, str):
        return False
    return path == "/" or any(
        path.startswith(prefix) for prefix in _DASHBOARD_ACCESS_PREFIXES
    )


# dashboard 会频繁轮询，访问日志只在 debug 模式保留。
class _DashboardAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not _is_dashboard_access_record(record):
            return True
        debug_enabled = logging.getLogger().isEnabledFor(
            logging.DEBUG
        ) or logging.getLogger("uvicorn.access").isEnabledFor(logging.DEBUG)
        if not debug_enabled:
            return False
        record.levelno = logging.DEBUG
        record.levelname = "DEBUG"
        return True


def _install_dashboard_access_log_filter() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if any(
        isinstance(filter_, _DashboardAccessLogFilter)
        for filter_ in access_logger.filters
    ):
        return
    access_logger.addFilter(_DashboardAccessLogFilter())


class SessionUpdatePayload(BaseModel):
    metadata: dict[str, Any] | None = None
    last_consolidated: int | None = None
    last_user_at: str | None = None
    last_proactive_at: str | None = None


class SessionBatchDeletePayload(BaseModel):
    keys: list[str]
    cascade: bool = True


class SessionConsolidatePayload(BaseModel):
    archive_all: bool = False
    force: bool = True


class MessageUpdatePayload(BaseModel):
    role: str | None = None
    content: str | None = None
    tool_chain: Any | None = None
    extra: dict[str, Any] | None = None
    ts: str | None = None


class MessageBatchDeletePayload(BaseModel):
    ids: list[str]


class MemoryUpdatePayload(BaseModel):
    status: str | None = None
    extra_json: dict[str, Any] | None = None
    source_ref: str | None = None
    happened_at: str | None = None
    emotional_weight: int | None = None


class MemoryBatchDeletePayload(BaseModel):
    ids: list[str]


class ProactiveDeletePayload(BaseModel):
    source_key: str | None = None
    item_ids: list[str] | None = None


class ChatMessagePayload(BaseModel):
    content: str
    session_key: str | None = None


class ChatSessionCreatePayload(BaseModel):
    title: str | None = None


class ChatApprovalDecisionPayload(BaseModel):
    decision: str = "approve"


class ChatCommandParsePayload(BaseModel):
    content: str
    session_key: str | None = None


class ManualConsolidator(Protocol):
    async def trigger_memory_consolidation(
        self,
        session_key: str,
        *,
        archive_all: bool = False,
        force: bool = False,
    ) -> bool: ...


class ManualMemoryOptimizer(Protocol):
    @property
    def is_running(self) -> bool: ...

    async def optimize(self) -> None: ...


def _validate_dashboard_chat_session(session_key: str | None) -> str:
    key = str(session_key or _DASHBOARD_CHAT_DEFAULT_SESSION).strip()
    if not key:
        raise HTTPException(status_code=400, detail="session_key 不能为空")
    if len(key) > _DASHBOARD_CHAT_MAX_SESSION_CHARS:
        raise HTTPException(status_code=400, detail="session_key 过长")
    if not key.startswith(f"{_DASHBOARD_CHAT_CHANNEL}:"):
        raise HTTPException(
            status_code=400,
            detail="session_key 必须以 dashboard: 开头",
        )
    if any(ch in key for ch in "\r\n\t"):
        raise HTTPException(status_code=400, detail="session_key 含非法字符")
    return key


def _validate_dashboard_chat_content(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="content 不能为空")
    if len(text) > _DASHBOARD_CHAT_MAX_CONTENT_CHARS:
        raise HTTPException(status_code=400, detail="content 过长")
    return text


def _dashboard_chat_id(session_key: str) -> str:
    if ":" not in session_key:
        return session_key
    return session_key.split(":", 1)[1] or "default"


def _dashboard_chat_title_from_prompt(content: str) -> str:
    text = re.sub(r"```.*?```", " ", str(content or ""), flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_>#|~-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .,:;!?")
    text = re.sub(
        r"^(please\s+help\s+me|please|pls|can you|could you|would you|help me|help|帮我|请帮我|请你|麻烦你)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip(" .,:;!?")
    if not text:
        return "Untitled chat"
    if len(text) <= 48:
        return text
    clipped = text[:49]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.strip(" .,:;!?") or text[:48].strip() or "Untitled chat"


def _dashboard_chat_placeholder_metadata(title: str | None = None) -> dict[str, Any]:
    clean_title = str(title or "").strip()[:80] or "New chat"
    return {
        "title": clean_title,
        "title_source": "placeholder",
        "created_from": "dashboard_chat",
    }


def _dashboard_chat_pending_approvals(meta: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(meta or {}).get(_DASHBOARD_CHAT_APPROVALS_META_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


def _store_dashboard_chat_pending_approval(
    store: SessionStore,
    *,
    session_key: str,
    approval: dict[str, Any],
) -> None:
    approval_id = str(approval.get("approval_id") or "").strip()
    if not approval_id:
        return
    meta = store.get_session_meta(session_key)
    metadata = dict((meta or {}).get("metadata") or {})
    pending = _dashboard_chat_pending_approvals(metadata)
    pending[approval_id] = {
        **approval,
        "status": "pending",
        "created_at": approval.get("created_at") or utcnow().isoformat(),
    }
    metadata[_DASHBOARD_CHAT_APPROVALS_META_KEY] = pending
    store.update_session(session_key, metadata=metadata)


def _dashboard_chat_command_approval_id(
    session_key: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    seed = json.dumps(
        {
            "session_key": session_key,
            "tool_name": tool_name,
            "arguments": arguments,
            "nonce": secrets.token_hex(8),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _ensure_dashboard_chat_session_title(
    store: SessionStore,
    session_key: str,
    content: str,
) -> None:
    meta = store.get_session_meta(session_key)
    if meta is None:
        store.create_session(
            key=session_key,
            metadata=_dashboard_chat_placeholder_metadata(),
        )
        meta = store.get_session_meta(session_key)
    metadata = dict((meta or {}).get("metadata") or {})
    title = str(metadata.get("title") or "").strip()
    title_source = str(metadata.get("title_source") or "").strip()
    if title_source not in {"", "placeholder"} and title:
        return
    metadata.update(
        {
            "title": _dashboard_chat_title_from_prompt(content),
            "title_source": "auto_first_user",
            "created_from": metadata.get("created_from") or "dashboard_chat",
        }
    )
    store.update_session(session_key, metadata=metadata)


def _sse_payload(event: str, data: dict[str, Any]) -> str:
    # One data line avoids browser-specific multiline reconstruction edge cases.
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def _redact_dashboard_chat_string(value: str) -> str:
    redacted = value
    for pattern in _DASHBOARD_CHAT_SECRET_PATTERNS:
        redacted = pattern.sub(_DASHBOARD_CHAT_REDACTED, redacted)
    if len(redacted) > _DASHBOARD_CHAT_MAX_STRING_FIELD_CHARS:
        return redacted[:_DASHBOARD_CHAT_MAX_STRING_FIELD_CHARS].rstrip() + "..."
    return redacted


def _sanitize_dashboard_chat_value(value: Any, *, depth: int = 0) -> Any:
    if depth > _DASHBOARD_CHAT_MAX_SANITIZE_DEPTH:
        return "[max-depth]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:_DASHBOARD_CHAT_MAX_COLLECTION_ITEMS]:
            str_key = str(key)
            normalized_key = str_key.lower().replace("-", "_")
            if normalized_key in _DASHBOARD_CHAT_SENSITIVE_KEYS:
                result[str_key] = _DASHBOARD_CHAT_REDACTED
            else:
                result[str_key] = _sanitize_dashboard_chat_value(
                    item,
                    depth=depth + 1,
                )
        if len(value) > _DASHBOARD_CHAT_MAX_COLLECTION_ITEMS:
            result["_truncated"] = len(value) - _DASHBOARD_CHAT_MAX_COLLECTION_ITEMS
        return result
    if isinstance(value, (list, tuple)):
        items = [
            _sanitize_dashboard_chat_value(item, depth=depth + 1)
            for item in list(value)[:_DASHBOARD_CHAT_MAX_COLLECTION_ITEMS]
        ]
        if len(value) > _DASHBOARD_CHAT_MAX_COLLECTION_ITEMS:
            items.append({
                "_truncated": len(value) - _DASHBOARD_CHAT_MAX_COLLECTION_ITEMS
            })
        return items
    if isinstance(value, str):
        return _redact_dashboard_chat_string(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _redact_dashboard_chat_string(str(value))


def _biomed_artifacts_for_run(run_id: str) -> dict[str, str]:
    clean = str(run_id or "").strip()
    if not clean:
        return {}
    return {
        "run_id": clean,
        "review_url": f"/api/biomed/answer-runs/{clean}/evidence-review",
        "packet_url": f"/api/biomed/answer-runs/{clean}/evidence-review/packet",
        "trace_url": f"/api/biomed/answer-runs/{clean}/trace",
        "provenance_url": f"/api/biomed/answer-runs/{clean}/provenance",
        "pilot_report_markdown_url": f"/api/biomed/export?run_id={clean}&report_type=pilot&format=markdown",
        "pilot_report_json_url": f"/api/biomed/export?run_id={clean}&report_type=pilot&format=json",
        "argument_graph_url": f"/api/biomed/answer-runs/{clean}/argument-graph",
        "evidence_graph_url": f"/api/biomed/answer-runs/{clean}/evidence-graph",
    }


def _biomed_artifacts_for_watch(watch_id: str) -> dict[str, str]:
    clean = str(watch_id or "").strip()
    if not clean:
        return {}
    return {
        "watch_id": clean,
        "watch_url": f"/api/biomed/watch/{clean}",
        "watch_check_url": f"/api/biomed/watch/{clean}/check",
        "watch_drift_url": f"/api/biomed/watch/{clean}/drift",
    }


def _biomed_artifacts_from_text(text: str) -> dict[str, str]:
    clean = str(text or "")
    run_match = _BIOMED_RUN_ID_RE.search(clean)
    if run_match:
        return _biomed_artifacts_for_run(run_match.group(0))
    watch_match = _BIOMED_WATCH_ID_RE.search(clean)
    if watch_match:
        return _biomed_artifacts_for_watch(watch_match.group(0))
    return {}


def _json_dict_from_tool_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _biomed_run_id_from_mapping(value: dict[str, Any]) -> str:
    for key in ("run_id",):
        if run_id := str(value.get(key) or "").strip():
            return run_id
    for key in ("ids", "answer_result", "audited_answer"):
        nested = value.get(key)
        if isinstance(nested, dict):
            if run_id := _biomed_run_id_from_mapping(nested):
                return run_id
    return ""


def _biomed_artifacts_from_tool_result(tool_name: str, result: Any) -> dict[str, str]:
    parsed = _json_dict_from_tool_result(result)
    if tool_name == "watch_research_topic":
        return _biomed_artifacts_for_watch(str(parsed.get("watch_id") or ""))
    if run_id := _biomed_run_id_from_mapping(parsed):
        return _biomed_artifacts_for_run(run_id)
    return _biomed_artifacts_from_text(str(result))


def _biomed_watch_schedule_interval(schedule: str) -> str:
    normalized = str(schedule or "").strip().lower()
    if normalized == "daily":
        return "1d"
    if normalized == "weekly":
        return "7d"
    return ""


async def _register_biomed_watch_framework_schedule(
    *,
    tool_registry: Any,
    watch: dict[str, Any],
    session_key: str,
) -> dict[str, Any]:
    watch_id = str(watch.get("watch_id") or "").strip()
    schedule = str(watch.get("schedule") or "").strip().lower()
    interval = _biomed_watch_schedule_interval(schedule)
    if not watch_id or not interval:
        return {
            "status": "skipped",
            "reason": "manual_or_missing_schedule",
        }
    if hasattr(tool_registry, "has_tool") and not tool_registry.has_tool("schedule"):
        return {
            "status": "unavailable",
            "reason": "schedule_tool_unavailable",
        }
    topic = str(watch.get("topic") or watch_id).strip()
    prompt = (
        f"Run Biomedical Evidence research watch {watch_id} ({topic}). "
        "Call check_research_watch_topic with source=pubmed when live PubMed is enabled; "
        "otherwise use source=mock. Summarize new pushed papers, skipped papers, "
        "uncertainty, and next review actions in Dashboard Chat."
    )
    result = await tool_registry.execute(
        "schedule",
        {
            "tier": "soft",
            "trigger": "every",
            "when": interval,
            "prompt": prompt,
            "channel": _DASHBOARD_CHAT_CHANNEL,
            "chat_id": _dashboard_chat_id(session_key),
            "name": f"biomed-watch:{watch_id}",
        },
    )
    return {
        "status": "registered",
        "name": f"biomed-watch:{watch_id}",
        "interval": interval,
        "result": _preview_text(_redact_dashboard_chat_string(str(result)), 500),
    }


async def _cancel_biomed_watch_framework_schedule(
    *,
    tool_registry: Any,
    watch_id: str,
) -> dict[str, Any]:
    clean = str(watch_id or "").strip()
    if not clean:
        return {"status": "skipped", "reason": "missing_watch_id"}
    if hasattr(tool_registry, "has_tool") and not tool_registry.has_tool("cancel_schedule"):
        return {
            "status": "unavailable",
            "reason": "cancel_schedule_tool_unavailable",
        }
    result = await tool_registry.execute(
        "cancel_schedule",
        {"name": f"biomed-watch:{clean}"},
    )
    return {
        "status": "requested",
        "name": f"biomed-watch:{clean}",
        "result": _preview_text(_redact_dashboard_chat_string(str(result)), 500),
    }


def _approval_schedule_markdown(schedule: dict[str, Any] | None) -> str:
    if not schedule:
        return ""
    status = str(schedule.get("status") or "").strip()
    if status == "registered":
        return (
            "\n\n**Framework schedule**\n\n"
            "| Field | Value |\n"
            "|---|---|\n"
            f"| Status | Registered |\n"
            f"| Job | `{schedule.get('name')}` |\n"
            f"| Interval | `{schedule.get('interval')}` |\n"
        )
    if status == "requested":
        return (
            "\n\n**Framework schedule**\n\n"
            "| Field | Value |\n"
            "|---|---|\n"
            f"| Status | Cancellation requested |\n"
            f"| Job | `{schedule.get('name')}` |\n"
        )
    if status == "skipped":
        return "\n\n**Framework schedule:** skipped because this watch is manual or has no schedule."
    if status:
        return f"\n\n**Framework schedule:** not registered ({schedule.get('reason') or status})."
    return ""


def _dashboard_chat_approval_success_markdown(
    *,
    tool_name: str,
    result: Any,
    final_arguments: dict[str, Any],
    framework_schedule: dict[str, Any] | None,
) -> str:
    parsed = _json_dict_from_tool_result(result)
    if tool_name == "watch_research_topic" and parsed.get("watch_id"):
        rows = [
            ("Watch ID", f"`{parsed.get('watch_id')}`"),
            ("Topic", str(parsed.get("topic") or "")),
            ("Schedule", str(parsed.get("schedule") or "")),
            ("Enabled", "Yes" if parsed.get("enabled", True) else "No"),
            ("Next check", str(parsed.get("next_check_at") or "Not scheduled")),
        ]
        return (
            "## Research watch created\n\n"
            + "| Field | Value |\n|---|---|\n"
            + "\n".join(f"| {label} | {value} |" for label, value in rows)
            + _approval_schedule_markdown(framework_schedule)
        )
    if tool_name == "delete_research_watch_topic":
        watch_id = str(
            final_arguments.get("watch_id") or parsed.get("watch_id") or ""
        ).strip()
        deleted = parsed.get("deleted")
        status = "Deleted" if deleted is True else "Delete requested"
        return (
            "## Research watch deleted\n\n"
            "| Field | Value |\n"
            "|---|---|\n"
            f"| Watch ID | `{watch_id}` |\n"
            f"| Status | {status} |\n"
            + _approval_schedule_markdown(framework_schedule)
        )
    return (
        f"## Approved action completed\n\n"
        f"Tool: `{tool_name}`\n\n"
        f"{_preview_text(_redact_dashboard_chat_string(str(result)), 1200)}"
    )



def _dashboard_chat_history_item(row: dict[str, Any]) -> dict[str, Any]:
    reserved = {
        "id",
        "session_key",
        "seq",
        "role",
        "content",
        "timestamp",
        "ts",
        "tool_chain",
        "extra",
    }
    extra = dict(row.get("extra") or {}) if isinstance(row.get("extra"), dict) else {}
    for key, value in row.items():
        if key not in reserved:
            extra[key] = value
    return {
        "id": row.get("id"),
        "session_key": row.get("session_key"),
        "seq": row.get("seq"),
        "role": row.get("role"),
        "content": row.get("content"),
        "tool_chain": None,
        "extra": _sanitize_dashboard_chat_value(extra),
        "ts": row.get("ts") or row.get("timestamp"),
    }


def _dashboard_chat_pending_approval_from_history(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("status") != "approval_required":
        return None
    approval_id = str(row.get("approval_id") or "").strip()
    if not approval_id:
        confirmation = row.get("confirmation")
        if isinstance(confirmation, dict):
            approval_id = str(confirmation.get("approval_id") or "").strip()
    if not approval_id:
        return None
    return {
        "approval_id": approval_id,
        "status": "pending",
        "tool_name": row.get("tool_name"),
        "call_id": row.get("call_id"),
        "iteration": row.get("iteration"),
        "arguments": row.get("arguments"),
        "final_arguments": row.get("final_arguments"),
        "reason": row.get("detail") or row.get("label") or "Approval required",
        "confirmation": row.get("confirmation") if isinstance(row.get("confirmation"), dict) else {"approval_id": approval_id},
        "created_at": row.get("ts") or row.get("timestamp") or utcnow().isoformat(),
    }


class DashboardChatMultiplexer:
    """Fan out dashboard-channel agent events to active SSE clients."""

    def __init__(
        self,
        *,
        bus: MessageBus | None,
        event_bus: EventBus | None,
        store: SessionStore | None = None,
    ) -> None:
        self._bus = bus
        self._event_bus = event_bus
        self._store = store
        self._queues: dict[str, set[asyncio.Queue[tuple[str, dict[str, Any]]]]] = {}
        self._seq_by_session: dict[str, int] = {}
        self._history_by_session: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self._active_sessions: set[str] = set()
        self._lock = asyncio.Lock()
        self._started = False

    @property
    def enabled(self) -> bool:
        return self._bus is not None and self._event_bus is not None

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self._bus is not None:
            self._bus.subscribe_outbound(_DASHBOARD_CHAT_CHANNEL, self._on_outbound)
        if self._event_bus is not None:
            self._event_bus.on(TurnStarted, self._on_turn_started)
            self._event_bus.on(StreamDeltaReady, self._on_stream_delta)
            self._event_bus.on(ToolCallStarted, self._on_tool_started)
            self._event_bus.on(ToolCallCompleted, self._on_tool_completed)
            self._event_bus.on(ToolCallApprovalRequired, self._on_tool_approval_required)
            self._event_bus.on(AfterStepCtx, self._on_after_step)

    async def subscribe(
        self,
        session_key: str,
        *,
        since_seq: int | None = None,
    ) -> asyncio.Queue[tuple[str, dict[str, Any]]]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(
            maxsize=_DASHBOARD_CHAT_REPLAY_LIMIT + 200
        )
        async with self._lock:
            self._queues.setdefault(session_key, set()).add(queue)
            replay = []
            if since_seq is not None:
                replay = [
                    (event, dict(payload))
                    for event, payload in self._history_by_session.get(session_key, [])
                    if int(payload.get("seq") or 0) > since_seq
                ]
            for event, payload in replay:
                queue.put_nowait((event, payload))
        return queue

    async def unsubscribe(
        self,
        session_key: str,
        queue: asyncio.Queue[tuple[str, dict[str, Any]]],
    ) -> None:
        async with self._lock:
            queues = self._queues.get(session_key)
            if queues is None:
                return
            queues.discard(queue)
            if not queues:
                self._queues.pop(session_key, None)

    async def publish_user_message_accepted(
        self,
        *,
        session_key: str,
        content: str,
    ) -> None:
        await self._publish(
            session_key,
            "user_message_accepted",
            {
                "session_key": session_key,
                "kind": "system",
                "label": "Message accepted",
                "content_preview": _preview_text(content, 240),
                "detail": _preview_text(content, 240),
            },
        )

    async def publish_error(
        self,
        *,
        session_key: str,
        message: str,
    ) -> None:
        await self._publish(
            session_key,
            "error",
            {
                "session_key": session_key,
                "kind": "error",
                "label": "Error",
                "message": _redact_dashboard_chat_string(message),
                "detail": _redact_dashboard_chat_string(message),
            },
        )

    async def _on_outbound(self, msg: OutboundMessage) -> None:
        if msg.channel != _DASHBOARD_CHAT_CHANNEL:
            return
        session_key = _session_key_from_outbound(msg)
        metadata = dict(msg.metadata or {})
        artifacts = _biomed_artifacts_from_text(msg.content)
        if artifacts and "artifacts" not in metadata:
            metadata["artifacts"] = artifacts
        await self._publish(
            session_key,
            "assistant_message",
            {
                "session_key": session_key,
                "chat_id": msg.chat_id,
                "content": msg.content,
                "thinking": msg.thinking,
                "media": list(msg.media or []),
                "kind": "assistant",
                "label": "Assistant",
                "metadata": _sanitize_dashboard_chat_value(metadata),
            },
        )
        await self._publish(
            session_key,
            "done",
            {
                "session_key": session_key,
                "chat_id": msg.chat_id,
                "kind": "system",
                "label": "Done",
            },
        )

    async def _on_turn_started(self, event: TurnStarted) -> None:
        if event.channel != _DASHBOARD_CHAT_CHANNEL:
            return
        await self._publish(
            event.session_key,
            "turn_started",
            {
                "session_key": event.session_key,
                "kind": "system",
                "label": "Agent started",
                "detail": _preview_text(event.content, 240),
            },
        )

    async def _on_stream_delta(self, event: StreamDeltaReady) -> None:
        if event.channel != _DASHBOARD_CHAT_CHANNEL:
            return
        if not event.content_delta and not event.thinking_delta:
            return
        await self._publish(
            event.session_key,
            "assistant_delta",
            {
                "session_key": event.session_key,
                "content_delta": event.content_delta,
                "thinking_delta": event.thinking_delta,
                "kind": "assistant",
                "label": "Assistant streaming",
            },
        )

    async def _on_tool_started(self, event: ToolCallStarted) -> None:
        if event.channel != _DASHBOARD_CHAT_CHANNEL:
            return
        await self._publish(
            event.session_key,
            "tool_started",
            {
                "session_key": event.session_key,
                "kind": "tool",
                "label": f"Tool started: {event.tool_name}",
                "tool_name": event.tool_name,
                "iteration": event.iteration,
                "call_id": event.call_id,
                "arguments": _sanitize_dashboard_chat_value(dict(event.arguments)),
            },
        )

    async def _on_tool_completed(self, event: ToolCallCompleted) -> None:
        if event.channel != _DASHBOARD_CHAT_CHANNEL:
            return
        approval_id = ""
        if event.status == "approval_required":
            match = re.search(r"\bApproval ID:\s*([A-Za-z0-9_-]+)\b", event.result_preview)
            if match:
                approval_id = match.group(1)
            if self._store is not None and approval_id:
                _store_dashboard_chat_pending_approval(
                    self._store,
                    session_key=event.session_key,
                    approval={
                        "approval_id": approval_id,
                        "tool_name": event.tool_name,
                        "call_id": event.call_id,
                        "iteration": event.iteration,
                        "arguments": event.arguments,
                        "final_arguments": event.final_arguments,
                        "reason": event.result_preview,
                        "confirmation": {
                            "approval_id": approval_id,
                            "session_key": event.session_key,
                            "chat_id": event.chat_id,
                            "channel": event.channel,
                        },
                        "created_at": utcnow().isoformat(),
                    },
                )
        await self._publish(
            event.session_key,
            "tool_completed",
            {
                "session_key": event.session_key,
                "kind": "tool",
                "label": f"Tool completed: {event.tool_name}",
                "tool_name": event.tool_name,
                "iteration": event.iteration,
                "call_id": event.call_id,
                "status": event.status,
                "approval_id": approval_id,
                "detail": _preview_text(
                    _redact_dashboard_chat_string(event.result_preview),
                    360,
                ),
                "arguments": _sanitize_dashboard_chat_value(dict(event.arguments)),
                "final_arguments": _sanitize_dashboard_chat_value(
                    dict(event.final_arguments)
                ),
                "metadata": {
                    "artifacts": _biomed_artifacts_from_tool_result(
                        event.tool_name,
                        event.result_preview,
                    )
                },
            },
        )

    async def _on_tool_approval_required(
        self,
        event: ToolCallApprovalRequired,
    ) -> None:
        if event.channel != _DASHBOARD_CHAT_CHANNEL:
            return
        approval_id = str(event.confirmation.get("approval_id") or "").strip()
        if self._store is not None and approval_id:
            _store_dashboard_chat_pending_approval(
                self._store,
                session_key=event.session_key,
                approval={
                    "approval_id": approval_id,
                    "tool_name": event.tool_name,
                    "call_id": event.call_id,
                    "iteration": event.iteration,
                    "arguments": event.arguments,
                    "final_arguments": event.final_arguments,
                    "reason": event.reason,
                    "confirmation": event.confirmation,
                    "created_at": utcnow().isoformat(),
                },
            )
        await self._publish(
            event.session_key,
            "tool_approval_required",
            {
                "session_key": event.session_key,
                "kind": "approval",
                "label": f"Approval required: {event.tool_name}",
                "approval_id": approval_id,
                "tool_name": event.tool_name,
                "iteration": event.iteration,
                "call_id": event.call_id,
                "status": "pending",
                "detail": _preview_text(
                    _redact_dashboard_chat_string(event.reason),
                    360,
                ),
                "arguments": _sanitize_dashboard_chat_value(dict(event.arguments)),
                "final_arguments": _sanitize_dashboard_chat_value(
                    dict(event.final_arguments)
                ),
                "confirmation": _sanitize_dashboard_chat_value(
                    dict(event.confirmation or {})
                ),
            },
        )

    async def _on_after_step(self, event: AfterStepCtx) -> None:
        if event.channel != _DASHBOARD_CHAT_CHANNEL:
            return
        if event.tools_called:
            label = "Tools called: " + ", ".join(event.tools_called)
            detail = _preview_text(event.partial_reply, 240)
        else:
            label = "Assistant response ready"
            detail = _preview_text(event.partial_reply, 240)
        await self._publish(
            event.session_key,
            "step",
            {
                "session_key": event.session_key,
                "kind": "system",
                "label": label,
                "detail": detail,
                "iteration": event.iteration,
                "has_more": event.has_more,
                "tools_used_so_far": list(event.tools_used_so_far),
            },
        )

    async def _publish(
        self,
        session_key: str,
        event: str,
        payload: dict[str, Any],
    ) -> None:
        async with self._lock:
            seq = self._seq_by_session.get(session_key, 0) + 1
            self._seq_by_session[session_key] = seq
            payload = {"event": event, "seq": seq, **payload}
            if event in {"user_message_accepted", "turn_started"}:
                self._active_sessions.add(session_key)
            history = self._history_by_session.setdefault(session_key, [])
            history.append((event, dict(payload)))
            if len(history) > _DASHBOARD_CHAT_REPLAY_LIMIT:
                del history[: len(history) - _DASHBOARD_CHAT_REPLAY_LIMIT]
            queues = list(self._queues.get(session_key, set()))
            if event in {"done", "error"}:
                self._active_sessions.discard(session_key)
        if not queues:
            return
        for queue in queues:
            try:
                queue.put_nowait((event, payload))
            except asyncio.QueueFull:
                try:
                    _ = queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait((event, payload))
                except asyncio.QueueFull:
                    logger.warning("dashboard chat SSE queue full: %s", session_key)

    async def latest_seq(self, session_key: str) -> int:
        async with self._lock:
            return self._seq_by_session.get(session_key, 0)

    async def is_active(self, session_key: str) -> bool:
        async with self._lock:
            return session_key in self._active_sessions


def _session_key_from_outbound(msg: OutboundMessage) -> str:
    raw = str((msg.metadata or {}).get("session_key_override") or "").strip()
    if raw.startswith(f"{_DASHBOARD_CHAT_CHANNEL}:"):
        return raw
    chat_id = str(msg.chat_id or "default").strip() or "default"
    return f"{_DASHBOARD_CHAT_CHANNEL}:{chat_id}"


class ProactiveDashboardReader:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def get_overview(self) -> dict[str, Any]:
        counts = {
            "seen_items": self._count("seen_items"),
            "deliveries": self._count("deliveries"),
            "rejection_cooldown": self._count("rejection_cooldown"),
            "semantic_items": self._count("semantic_items"),
            "kv_state": self._count("kv_state"),
            "session_state": self._count("session_state"),
            "context_only_timestamps": self._count("context_only_timestamps"),
            "tick_logs": self._count("tick_log"),
            "tick_steps": self._count("tick_step_log"),
        }
        with self._lock:
            recent_tick = self._db.execute("""
                SELECT tick_id, session_key, started_at, finished_at, gate_exit,
                       terminal_action, skip_reason, steps_taken, drift_entered
                FROM tick_log
                ORDER BY started_at DESC
                LIMIT 1
                """).fetchone()
            last_send_at = self._db.execute("""
                SELECT sent_at
                FROM deliveries
                ORDER BY sent_at DESC
                LIMIT 1
                """).fetchone()
            result_counts_rows = self._db.execute("""
                SELECT COALESCE(terminal_action, gate_exit, 'unknown') AS bucket, COUNT(*) AS total
                FROM tick_log
                GROUP BY COALESCE(terminal_action, gate_exit, 'unknown')
                """).fetchall()
            flow_counts_rows = self._db.execute("""
                SELECT CASE WHEN drift_entered = 1 THEN 'drift' ELSE 'proactive' END AS bucket,
                       COUNT(*) AS total
                FROM tick_log
                GROUP BY CASE WHEN drift_entered = 1 THEN 'drift' ELSE 'proactive' END
                """).fetchall()
        result_counts = {
            str(row["bucket"]): int(row["total"]) for row in result_counts_rows
        }
        flow_counts = {
            str(row["bucket"]): int(row["total"]) for row in flow_counts_rows
        }
        return {
            "counts": counts,
            "result_counts": result_counts,
            "flow_counts": flow_counts,
            "last_tick_at": (
                recent_tick["started_at"] if recent_tick is not None else None
            ),
            "last_send_at": (
                last_send_at["sent_at"] if last_send_at is not None else None
            ),
            "last_skip_reason": (
                recent_tick["skip_reason"]
                if recent_tick is not None and recent_tick["terminal_action"] != "reply"
                else None
            ),
            "recent_tick": (
                self._row_to_tick_log(recent_tick) if recent_tick is not None else None
            ),
        }

    def list_deliveries(
        self,
        *,
        session_key: str = "",
        sent_from: str = "",
        sent_to: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = self._build_filters(
            ("session_key = ?", session_key),
            ("sent_at >= ?", sent_from),
            ("sent_at <= ?", sent_to),
        )
        return self._list_rows(
            table="deliveries",
            where=where,
            params=params,
            order_by="sent_at DESC, session_key ASC, delivery_key ASC",
            page=page,
            page_size=page_size,
            columns="session_key, delivery_key, sent_at",
        )

    def list_seen_items(
        self,
        *,
        source_key: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = self._build_filters(("source_key = ?", source_key))
        return self._list_rows(
            table="seen_items",
            where=where,
            params=params,
            order_by="seen_at DESC, source_key ASC, item_id ASC",
            page=page,
            page_size=page_size,
            columns="source_key, item_id, seen_at",
        )

    def list_rejection_cooldown(
        self,
        *,
        source_key: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = self._build_filters(("source_key = ?", source_key))
        return self._list_rows(
            table="rejection_cooldown",
            where=where,
            params=params,
            order_by="rejected_at DESC, source_key ASC, item_id ASC",
            page=page,
            page_size=page_size,
            columns="source_key, item_id, rejected_at",
        )

    def list_semantic_items(
        self,
        *,
        window_hours: int = 168,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        cutoff = (utcnow() - timedelta(hours=max(window_hours, 1))).isoformat()
        where, params = self._build_filters(("ts >= ?", cutoff))
        return self._list_rows(
            table="semantic_items",
            where=where,
            params=params,
            order_by="ts DESC, id DESC",
            page=page,
            page_size=page_size,
            columns="id, source_key, item_id, text, ts",
        )

    def list_tick_logs(
        self,
        *,
        session_key: str = "",
        terminal_action: str = "",
        gate_exit: str = "",
        flow: str = "",
        started_from: str = "",
        started_to: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "started_at",
        sort_order: str = "desc",
    ) -> tuple[list[dict[str, Any]], int]:
        drift_only = ""
        if flow == "drift":
            drift_only = "1"
        elif flow == "proactive":
            drift_only = "0"
        safe_sort_by = (
            sort_by
            if sort_by
            in {
                "session_key",
                "started_at",
                "finished_at",
                "terminal_action",
                "gate_exit",
                "steps_taken",
                "alert_count",
                "content_count",
                "context_count",
                "drift_entered",
            }
            else "started_at"
        )
        safe_sort_order = "ASC" if str(sort_order).lower() == "asc" else "DESC"
        where, params = self._build_filters(
            ("session_key = ?", session_key),
            ("terminal_action = ?", terminal_action),
            ("gate_exit = ?", gate_exit),
            ("drift_entered = ?", drift_only),
            ("started_at >= ?", started_from),
            ("started_at <= ?", started_to),
        )
        items, total = self._list_rows(
            table="tick_log",
            where=where,
            params=params,
            order_by=f"{safe_sort_by} {safe_sort_order}, id DESC",
            page=page,
            page_size=page_size,
            columns=(
                "tick_id, session_key, started_at, finished_at, gate_exit, "
                "terminal_action, skip_reason, steps_taken, alert_count, "
                "content_count, context_count, interesting_ids, discarded_ids, "
                "cited_ids, drift_entered, final_message"
            ),
            row_mapper=self._row_to_tick_log,
        )
        return items, total

    def get_tick_log(self, tick_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                """
                SELECT tick_id, session_key, started_at, finished_at, gate_exit,
                       terminal_action, skip_reason, steps_taken, alert_count,
                       content_count, context_count, interesting_ids, discarded_ids,
                       cited_ids, drift_entered, final_message
                FROM tick_log
                WHERE tick_id = ?
                """,
                (tick_id,),
            ).fetchone()
        return self._row_to_tick_log(row) if row is not None else None

    def list_tick_steps(self, tick_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT step_index, phase, tool_name, tool_call_id, tool_args_json,
                       tool_result_text, terminal_action_after, skip_reason_after,
                       interesting_ids_after, discarded_ids_after, cited_ids_after,
                       final_message_after
                FROM tick_step_log
                WHERE tick_id = ?
                ORDER BY step_index ASC, id ASC
                """,
                (tick_id,),
            ).fetchall()
        return [self._row_to_tick_step(row) for row in rows]

    def delete_seen_items(
        self,
        *,
        source_key: str = "",
        item_ids: list[str] | None = None,
    ) -> int:
        return self._delete_rows("seen_items", source_key=source_key, item_ids=item_ids)

    def delete_rejection_cooldown(
        self,
        *,
        source_key: str = "",
        item_ids: list[str] | None = None,
    ) -> int:
        return self._delete_rows(
            "rejection_cooldown",
            source_key=source_key,
            item_ids=item_ids,
        )

    def _delete_rows(
        self,
        table: str,
        *,
        source_key: str = "",
        item_ids: list[str] | None = None,
    ) -> int:
        if not source_key and not item_ids:
            raise ValueError("至少提供 source_key 或 item_ids")
        clauses: list[str] = []
        params: list[Any] = []
        if source_key:
            clauses.append("source_key = ?")
            params.append(source_key)
        if item_ids:
            placeholders = ", ".join("?" for _ in item_ids)
            clauses.append(f"item_id IN ({placeholders})")
            params.extend(item_ids)
        where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            result = self._db.execute(
                f"DELETE FROM {table}{where_sql}",
                tuple(params),
            )
            self._db.commit()
        return int(result.rowcount or 0)

    def _list_rows(
        self,
        *,
        table: str,
        where: str,
        params: tuple[Any, ...],
        order_by: str,
        page: int,
        page_size: int,
        columns: str,
        row_mapper=None,
    ) -> tuple[list[dict[str, Any]], int]:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 200))
        offset = (safe_page - 1) * safe_size
        with self._lock:
            total_row = self._db.execute(
                f"SELECT COUNT(*) FROM {table}{where}",
                params,
            ).fetchone()
            rows = self._db.execute(
                f"""
                SELECT {columns}
                FROM {table}{where}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                (*params, safe_size, offset),
            ).fetchall()
        total = int(total_row[0]) if total_row is not None else 0
        mapper = row_mapper or self._row_to_dict
        return [mapper(row) for row in rows], total

    def _build_filters(self, *filters: tuple[str, Any]) -> tuple[str, tuple[Any, ...]]:
        clauses: list[str] = []
        params: list[Any] = []
        for clause, value in filters:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            clauses.append(clause)
            params.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, tuple(params)

    def _count(self, table: str) -> int:
        with self._lock:
            row = self._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row is not None else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    @staticmethod
    def _decode_json_list(raw: Any) -> list[str]:
        text = str(raw or "").strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except Exception:
            return []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    def _row_to_tick_log(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = self._row_to_dict(row)
        payload["interesting_ids"] = self._decode_json_list(
            payload.get("interesting_ids")
        )
        payload["discarded_ids"] = self._decode_json_list(payload.get("discarded_ids"))
        payload["cited_ids"] = self._decode_json_list(payload.get("cited_ids"))
        payload["drift_entered"] = bool(payload.get("drift_entered"))
        return payload

    def _row_to_tick_step(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = self._row_to_dict(row)
        payload["tool_args"] = self._decode_json_object(
            payload.pop("tool_args_json", "")
        )
        payload["interesting_ids_after"] = self._decode_json_list(
            payload.get("interesting_ids_after")
        )
        payload["discarded_ids_after"] = self._decode_json_list(
            payload.get("discarded_ids_after")
        )
        payload["cited_ids_after"] = self._decode_json_list(
            payload.get("cited_ids_after")
        )
        return payload

    @staticmethod
    def _decode_json_object(raw: Any) -> dict[str, Any]:
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}


_pending_plugins: list[tuple[Path, Path]] = []
_pending_plugins_lock = threading.Lock()


def _esbuild_command(project_root: Path) -> list[str] | None:
    bin_name = "esbuild.cmd" if os.name == "nt" else "esbuild"
    local_bin = project_root / "node_modules" / ".bin" / bin_name
    if local_bin.exists():
        return [str(local_bin)]
    if os.name == "nt":
        cmd_bin = shutil.which("cmd.exe") or shutil.which("cmd")
        npx_bin = shutil.which("npx.cmd") or shutil.which("npx")
        if cmd_bin and npx_bin:
            return [cmd_bin, "/d", "/s", "/c", "npx", "--yes", "esbuild"]
        return None
    npx_bin = shutil.which("npx")
    if npx_bin:
        return [npx_bin, "--yes", "esbuild"]
    return None


def _build_plugin_panels_js(project_root: Path, plugin_dir: Path) -> None:
    esbuild_cmd: list[str] | None = None
    for ts_path in sorted(plugin_dir.glob("dashboard_panel*.ts")):
        js_path = ts_path.with_suffix(".js")
        if js_path.exists() and js_path.stat().st_mtime >= ts_path.stat().st_mtime:
            continue
        if esbuild_cmd is None:
            esbuild_cmd = _esbuild_command(project_root)
        if esbuild_cmd is None:
            with _pending_plugins_lock:
                _pending_plugins.append((project_root, plugin_dir))
            return
        _run_esbuild(esbuild_cmd, ts_path, js_path, f"{plugin_dir.name}/{ts_path.stem}")


def _run_esbuild(cmd: list[str], ts_path: Path, js_path: Path, name: str) -> None:
    try:
        result = subprocess.run(
            [
                *cmd,
                str(ts_path),
                f"--outfile={js_path}",
                "--bundle=false",
                "--platform=browser",
                "--target=es2020",
                "--format=iife",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info("插件面板已编译: %s", name)
        else:
            logger.warning("插件面板编译失败 (%s):\n%s", name, result.stderr)
    except Exception as exc:
        logger.warning("插件面板编译异常 (%s): %s", name, exc)


def _resolve_plugin_dir(plugins_root: Path, plugin_id: str) -> Path:
    if not plugin_id or "/" in plugin_id or "\\" in plugin_id:
        raise HTTPException(status_code=400, detail="invalid plugin id")
    win_path = PureWindowsPath(plugin_id)
    if Path(plugin_id).is_absolute() or win_path.drive or win_path.root:
        raise HTTPException(status_code=400, detail="invalid plugin id")
    plugin_dir = (plugins_root / plugin_id).resolve()
    root = plugins_root.resolve()
    if plugin_dir.parent != root:
        raise HTTPException(status_code=400, detail="invalid plugin id")
    return plugin_dir


async def _compile_pending_plugins_async() -> None:
    with _pending_plugins_lock:
        if not _pending_plugins:
            return
        pending = _pending_plugins.copy()
        _pending_plugins.clear()
    first_root = pending[0][0]

    logger.info("正在安装前端构建工具 (npx esbuild)...")
    esbuild_cmd = _esbuild_command(first_root)
    if esbuild_cmd is None:
        logger.warning("esbuild unavailable: neither local install nor npx was found")
        return
    proc = await asyncio.create_subprocess_exec(
        *esbuild_cmd,
        "--version",
        cwd=str(first_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(
            "npx esbuild 不可用 (%d)，插件面板未编译:\n%s",
            proc.returncode,
            stderr.decode("utf-8", errors="replace")[:500],
        )
        return
    version = stdout.decode("utf-8", errors="replace").strip()
    logger.info("npx esbuild 就绪 (%s)，开始编译插件面板...", version)
    for root, pdir in pending:
        for ts_path in sorted(pdir.glob("dashboard_panel*.ts")):
            js_path = ts_path.with_suffix(".js")
            if not (js_path.exists() and js_path.stat().st_mtime >= ts_path.stat().st_mtime):
                _run_esbuild(esbuild_cmd, ts_path, js_path, f"{pdir.name}/{ts_path.stem}")


def _load_plugin_dashboard(app: FastAPI, plugin_dir: Path, workspace: Path) -> list[object]:
    try:
        mod = _load_plugin_dashboard_module(plugin_dir)
        if hasattr(mod, "register"):
            result = mod.register(app, plugin_dir, workspace)
            logger.info("插件 dashboard 已挂载: %s", plugin_dir.name)
            return _dashboard_closeables(result)
    except Exception as e:
        logger.warning("插件 dashboard 挂载失败 (%s): %s", plugin_dir.name, e)
    return []


def _plugin_dashboard_enabled(app: FastAPI, plugin_dir: Path) -> bool:
    dash_path = plugin_dir / "dashboard.py"
    if not dash_path.exists():
        return False
    try:
        mod = _load_plugin_dashboard_module(plugin_dir)
    except Exception as e:
        logger.warning("插件 dashboard 检查失败 (%s): %s", plugin_dir.name, e)
        return False
    enabled = getattr(mod, "plugin_enabled", None)
    if not callable(enabled):
        return True
    return bool(enabled(app))


def _load_plugin_dashboard_module(plugin_dir: Path) -> ModuleType:
    dash_path = plugin_dir / "dashboard.py"
    module_name = f"akasic_dashboard_plugin_{plugin_dir.name}"
    spec = importlib.util.spec_from_file_location(module_name, dash_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {dash_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _dashboard_closeables(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        items = cast(list[object], value)
        return [
            item
            for item in items
            if _is_dashboard_closeable(item)
        ]
    if _is_dashboard_closeable(value):
        return [value]
    return []


def _is_dashboard_closeable(value: object) -> bool:
    return callable(getattr(value, "close", None))


def _close_dashboard_value(value: object) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        _ = close()


def _preview_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


_BIOMED_LLM_FLAGS = (
    "use_llm_planner",
    "use_llm_extractor",
    "use_llm_synthesis",
    "use_llm_verifier",
    "use_llm_revision",
    "use_llm_claim_logic",
)


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _live_config_path(workspace: Path) -> Path:
    env_path = os.environ.get("AKASHIC_CONFIG")
    if env_path:
        return Path(env_path)
    return workspace / "config.toml"


def _read_biomed_config(workspace: Path, plugin_dir: Path) -> dict[str, Any]:
    schema = _safe_read_json(plugin_dir / "_conf_schema.json")
    defaults = {
        key: value.get("default")
        for key, value in schema.items()
        if isinstance(value, dict) and "default" in value
    }
    config = dict(defaults)
    config_path = _live_config_path(workspace)
    if not config_path.exists():
        return config
    try:
        import tomllib

        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return config
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return config
    biomed = plugins.get("biomed_evidence")
    if isinstance(biomed, dict):
        config.update(biomed)
    return config


def _write_biomed_bool_config(workspace: Path, key: str, value: bool) -> dict[str, Any]:
    if key != "allow_live_pubmed_tools":
        raise ValueError("Unsupported Biomedical Evidence config key.")
    config_path = _live_config_path(workspace)
    section_header = "[plugins.biomed_evidence]"
    new_line = f"{key} = {'true' if value else 'false'}"
    if not config_path.exists():
        config_path.write_text(f"{section_header}\n{new_line}\n", encoding="utf-8")
        return {"path": str(config_path), "created": True, "updated": True}
    text = config_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start = -1
    section_end = len(lines)
    for index, line in enumerate(lines):
        if line.strip() == section_header:
            section_start = index
            continue
        if section_start >= 0 and index > section_start and re.match(r"^\s*\[[^\]]+\]\s*$", line):
            section_end = index
            break
    if section_start < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([section_header, new_line])
    else:
        key_index = -1
        for index in range(section_start + 1, section_end):
            if re.match(rf"^\s*{re.escape(key)}\s*=", lines[index]):
                key_index = index
                break
        if key_index >= 0:
            lines[key_index] = new_line
        else:
            lines.insert(section_end, new_line)
    suffix = "\n" if text.endswith("\n") else ""
    if not suffix:
        suffix = "\n"
    config_path.write_text("\n".join(lines).rstrip() + suffix, encoding="utf-8")
    return {"path": str(config_path), "created": False, "updated": True}


def _bool_config(config: dict[str, Any], key: str, default: bool = False) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int_config(config: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(config.get(key, default))
    except Exception:
        return default


def _str_config(config: dict[str, Any], key: str, default: str = "") -> str:
    value = config.get(key, default)
    return str(value if value is not None else default)


def _provider_status(provider: Any | None, model: str) -> dict[str, Any]:
    configured = provider is not None
    return {
        "status": "configured" if configured else "missing",
        "model": model if configured and model else "",
        "features": {
            "planning": configured,
            "extraction": configured,
            "synthesis": configured,
            "verifier": configured,
            "revision": configured,
            "claim_logic": configured,
        },
        "missing_effect": (
            ""
            if configured
            else "LLM planning, extraction, synthesis, verifier, revision, and claim logic will use deterministic fallbacks or be unavailable."
        ),
    }


def _biomed_readiness(
    *,
    workspace: Path,
    plugin_dir: Path,
    provider: Any | None,
    model: str,
) -> dict[str, Any]:
    config = _read_biomed_config(workspace, plugin_dir)
    live_pubmed = _bool_config(config, "allow_live_pubmed_tools", False)
    return {
        "command": "/biomed",
        "llm_provider": _provider_status(provider, model),
        "pubmed": {
            "status": "enabled" if live_pubmed else "disabled",
            "policy_status": "enabled" if live_pubmed else "disabled",
            "network_status": "unchecked",
            "allow_live_pubmed_tools": live_pubmed,
            "message": (
                "Live PubMed command execution is allowed by allow_live_pubmed_tools. Network reachability is checked when you run a live PubMed command."
                if live_pubmed
                else "Live PubMed command execution is blocked by allow_live_pubmed_tools=false. This policy gate is separate from raw network reachability."
            ),
        },
        "source": {
            "default_source": _str_config(config, "default_source", "mock") or "mock",
            "live_pubmed_opt_in": live_pubmed,
        },
        "limits": {
            "max_papers": _int_config(config, "max_answer_papers", 10),
            "max_tool_steps": _int_config(config, "max_tool_steps", 20),
            "max_llm_calls": _int_config(config, "max_llm_calls", 6),
        },
        "exports": {
            "obsidian": _bool_config(config, "enable_obsidian_export", False),
            "provenance": _bool_config(config, "enable_provenance_export", False),
        },
        "confirmation": {
            "required_for": _biomed_confirmation_tools(),
        },
        "config_path": str(_live_config_path(workspace)),
    }


def _biomed_confirmation_tools() -> list[str]:
    try:
        from plugins.biomed_evidence.tool_contracts import list_release_tool_contracts
    except Exception:
        return []
    return [
        item.tool_name
        for item in list_release_tool_contracts()
        if bool(getattr(item, "requires_confirmation", False))
    ]


def _biomed_tool_contract_map() -> dict[str, dict[str, Any]]:
    try:
        from plugins.biomed_evidence.tool_contracts import list_release_tool_contracts
    except Exception:
        return {}
    return {
        item.tool_name: item.model_dump(mode="json")
        for item in list_release_tool_contracts()
    }


def _biomed_workflow_templates(workspace: Path, provider: Any | None, model: str) -> list[dict[str, Any]]:
    try:
        from plugins.biomed_evidence.service import BiomedEvidenceService

        service = BiomedEvidenceService(
            workspace,
            revision_provider=provider,
            revision_model=model,
        )
        try:
            payload = service.list_workflow_templates().model_dump(mode="json")
        finally:
            close = getattr(service, "close", None)
            if callable(close):
                close()
        items = payload.get("items")
        return items if isinstance(items, list) else []
    except Exception:
        return []


def _chat_command_manifest(
    *,
    workspace: Path,
    plugin_dir: Path,
    provider: Any | None,
    model: str,
) -> dict[str, Any]:
    contracts = _biomed_tool_contract_map()
    readiness = _biomed_readiness(
        workspace=workspace,
        plugin_dir=plugin_dir,
        provider=provider,
        model=model,
    )
    templates = _biomed_workflow_templates(workspace, provider, model)
    return {
        "schema_version": "dashboard-chat-commands-v1",
        "commands": [
            {
                "prefix": "/biomed",
                "plugin_id": "biomed_evidence",
                "display_name": "Biomedical Evidence",
                "description": "Run research-only biomedical literature workflows with source policy, LLM readiness, and confirmations visible before execution.",
                "status": readiness,
                "examples": [
                    "/biomed status",
                    "/biomed enable pubmed",
                    "/biomed check pubmed",
                    "/biomed audit \"microglial activation Alzheimer disease progression\" --source pubmed --papers 10 --llm all --support-refute",
                    "/biomed literature \"TREM2 microglia Alzheimer\" --source pubmed --papers 10",
                    "/biomed review biomed-run-...",
                    "/biomed pilot-report biomed-run-... --format markdown",
                    "/biomed export provenance biomed-run-...",
                    "/biomed template run biomed-template-reviewer-handoff \"TREM2 microglia Alzheimer\" --source mock",
                    "/biomed project create \"Microglia AD\" --question \"What links microglial activation to AD progression?\"",
                    "/biomed watch create \"Microglia AD\" --query \"microglia Alzheimer disease progression\"",
                    "/biomed watch delete watch-...",
                ],
                "options": {
                    "source": ["mock", "pubmed"],
                    "papers": {"type": "integer", "default": readiness["limits"]["max_papers"]},
                    "llm": ["off", "all"],
                    "support-refute": {"type": "boolean"},
                    "project": {"type": "string"},
                    "run_id": {"type": "string"},
                    "watch_id": {"type": "string"},
                },
                "workflows": [
                    {
                        "name": "status",
                        "label": "Provider and source status",
                        "risk_level": "read_only",
                        "requires_confirmation": False,
                    },
                    {
                        "name": "enable pubmed",
                        "label": "Enable live PubMed command policy",
                        "risk_level": "configuration_write",
                        "requires_confirmation": True,
                    },
                    {
                        "name": "audit",
                        "label": "Full evidence audit",
                        "tool_name": "answer_with_audit",
                        "contract": contracts.get("answer_with_audit", {}),
                    },
                    {
                        "name": "literature",
                        "label": "Literature retrieval",
                        "tool_name": "search_literature",
                        "contract": contracts.get("search_literature", {}),
                    },
                    {
                        "name": "watch delete",
                        "label": "Delete research watch",
                        "tool_name": "delete_research_watch_topic",
                        "contract": contracts.get("delete_research_watch_topic", {}),
                    },
                    {
                        "name": "review",
                        "label": "Run evidence review",
                        "tool_name": "get_run_evidence_review",
                        "contract": contracts.get("get_run_evidence_review", {}),
                    },
                    {
                        "name": "pilot-report",
                        "label": "Pilot Report export",
                        "tool_name": "export_evidence_report",
                        "contract": contracts.get("export_evidence_report", {}),
                    },
                    {
                        "name": "template run",
                        "label": "Run workflow template",
                        "tool_name": "run_saved_tool_chain_template",
                        "contract": contracts.get("run_saved_tool_chain_template", {}),
                    },
                    {
                        "name": "export provenance",
                        "label": "Provenance export",
                        "tool_name": "export_provenance_graph",
                        "contract": contracts.get("export_provenance_graph", {}),
                    },
                ],
                "templates": templates,
            }
        ],
    }


def _parse_flags(tokens: list[str]) -> tuple[list[str], dict[str, Any]]:
    positional: list[str] = []
    flags: dict[str, Any] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--") or token == "--":
            positional.append(token)
            index += 1
            continue
        key = token[2:].strip().replace("-", "_")
        next_value = tokens[index + 1] if index + 1 < len(tokens) else None
        if next_value is None or next_value.startswith("--"):
            flags[key] = True
            index += 1
            continue
        flags[key] = next_value
        index += 2
    return positional, flags


def _flag_int(flags: dict[str, Any], *keys: str, default: int) -> int:
    for key in keys:
        if key not in flags:
            continue
        try:
            return max(1, int(flags[key]))
        except Exception:
            return default
    return default


def _flag_float(flags: dict[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        if key not in flags:
            continue
        try:
            return float(flags[key])
        except Exception:
            return default
    return default


def _flag_str(flags: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = flags.get(key)
        if value is not None and value is not True:
            return str(value).strip()
    return default


def _missing_for_source(source: str, readiness: dict[str, Any]) -> list[dict[str, str]]:
    if source == "pubmed" and readiness["pubmed"]["status"] != "enabled":
        return [
            {
                "kind": "pubmed",
                "label": "Live PubMed disabled",
                "detail": "Set allow_live_pubmed_tools=true in the Biomedical Evidence plugin config, then restart the full runtime.",
            }
        ]
    return []


def _missing_for_llm(flags: dict[str, Any], readiness: dict[str, Any]) -> list[dict[str, str]]:
    if str(flags.get("llm") or "").lower() != "all":
        return []
    if readiness["llm_provider"]["status"] == "configured":
        return []
    return [
        {
            "kind": "llm",
            "label": "LLM provider missing",
            "detail": "LLM planning, extraction, synthesis, verifier, revision, and claim logic require a configured provider.",
        }
    ]


def _confirmation_preview(tool_name: str, contracts: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if tool_name == "configure_biomed_pubmed_policy":
        return {
            "required": True,
            "tool_name": tool_name,
            "risk_level": "configuration_write",
            "side_effects": ["Updates the active config.toml for the Biomedical Evidence plugin."],
            "source_policy": "no_source",
            "reason": "This changes Biomedical Evidence runtime policy and requires explicit confirmation.",
        }
    contract = contracts.get(tool_name) or {}
    if not contract.get("requires_confirmation"):
        return None
    return {
        "required": True,
        "tool_name": tool_name,
        "risk_level": contract.get("risk_level", "read_only"),
        "side_effects": contract.get("side_effects", []),
        "source_policy": contract.get("source_policy", "no_source"),
        "reason": "This Biomedical Evidence action requires confirmation before execution.",
    }


def _biomed_prompt_for_preview(action: str, args: dict[str, Any]) -> str:
    if action == "status":
        return "Show Biomedical Evidence provider, source, confirmation, and export readiness. Keep the answer concise."
    if action == "help":
        return "Show available /biomed commands with one-line examples and explain research-only boundaries."
    if action == "check_pubmed":
        return (
            "Check live PubMed readiness using Biomedical Evidence tools. "
            f"Query: {args.get('query') or 'microglia Alzheimer disease'}."
        )
    if action == "enable_pubmed":
        return (
            "Enable live PubMed command execution for Biomedical Evidence by setting "
            "allow_live_pubmed_tools=true in the active config.toml."
        )
    if action == "audit":
        llm_text = " with all configured LLM-assisted stages" if args.get("llm") == "all" else ""
        support_refute = " Execute support and refute retrieval." if args.get("execute_support_refute") else ""
        return (
            "Run a research-only Biomedical Evidence audited answer workflow"
            f"{llm_text}. Question: {args.get('question')}. "
            f"Source: {args.get('source')}. Papers: {args.get('max_papers')}.{support_refute}"
        )
    if action == "literature":
        return (
            "Run controlled Biomedical Evidence literature retrieval only. "
            f"Query: {args.get('query')}. Source: {args.get('source')}. Papers: {args.get('max_results')}."
        )
    if action == "review":
        return f"Open and summarize the Run Evidence Review for {args.get('run_id')}."
    if action == "pilot_report":
        return (
            "Export the Biomedical Evidence Pilot Report for "
            f"{args.get('run_id')} as {args.get('format', 'markdown')}."
        )
    if action == "template_run":
        return (
            "Run Biomedical Evidence workflow template "
            f"{args.get('template_id')}. Question: {args.get('question')}. "
            f"Source override: {args.get('source_override') or 'template default'}."
        )
    if action == "export_provenance":
        return f"Export or prepare the provenance graph for Biomedical Evidence run {args.get('run_id')}."
    if action == "project_create":
        return (
            "Create a Biomedical Evidence project after confirmation. "
            f"Name: {args.get('name')}. Research question: {args.get('question')}."
        )
    if action == "watch_create":
        return (
            "Create a Biomedical Evidence research watch after confirmation. "
            f"Topic: {args.get('topic')}. Query: {args.get('description') or args.get('query')}."
        )
    if action == "watch_delete":
        return (
            "Delete a Biomedical Evidence research watch after confirmation and "
            f"cancel its framework schedule. Watch ID: {args.get('watch_id')}."
        )
    return "Handle this Biomedical Evidence command."


def _deterministic_dashboard_chat_command(content: str) -> str:
    text = str(content or "").strip()
    if text.startswith("/"):
        return text
    lowered = text.lower()
    watch_match = _BIOMED_WATCH_ID_RE.search(text)
    if watch_match and re.search(
        r"\b(delete|remove|cancel|stop|disable)\b",
        text,
        re.IGNORECASE,
    ):
        return f"/biomed watch delete {watch_match.group(0)}"
    run_match = _BIOMED_RUN_ID_RE.search(text)
    if run_match and re.search(r"\b(pilot|roi|handoff|report)\b", text, re.IGNORECASE):
        return f"/biomed pilot-report {run_match.group(0)}"
    if run_match and re.search(r"\b(provenance|graph|export)\b", text, re.IGNORECASE):
        return f"/biomed export provenance {run_match.group(0)}"
    if run_match and re.search(r"\b(review|packet|trace|open|inspect)\b", text, re.IGNORECASE):
        return f"/biomed review {run_match.group(0)}"
    if re.search(r"\b(biomed|biomedical|pubmed|llm provider)\b", lowered):
        if re.search(r"\b(status|readiness|ready|configured|configuration)\b", lowered):
            return "/biomed status"
        if re.search(r"\b(enable|turn on|allow|activate)\b", lowered) and "pubmed" in lowered:
            return "/biomed enable pubmed"
        if re.search(r"\b(check|test|verify|smoke)\b", lowered) and "pubmed" in lowered:
            return "/biomed check pubmed"
    if "watch" in lowered and re.search(r"\b(create|add|monitor|track)\b", lowered):
        topic_match = re.search(
            r"\btopic\s*:\s*([^.;\n]+)",
            text,
            re.IGNORECASE,
        )
        query_match = re.search(
            r"\b(query|question)\s*:\s*([^.;\n]+)",
            text,
            re.IGNORECASE,
        )
        quoted = re.findall(r'"([^"]+)"', text)
        topic = (topic_match.group(1).strip() if topic_match else "")
        query = (query_match.group(2).strip() if query_match else "")
        if not topic and quoted:
            topic = quoted[0].strip()
        if not query and len(quoted) > 1:
            query = quoted[1].strip()
        if topic and query:
            return f'/biomed watch create "{topic}" --query "{query}"'
    if re.search(r"\b(pubmed|literature|papers?|论文|文献)\b", lowered):
        quoted = re.findall(r'"([^"]+)"', text)
        papers_match = re.search(r"\b(\d{1,2})\s*(papers?|篇|篇论文|results?)\b", lowered)
        papers = papers_match.group(1) if papers_match else "10"
        source = "pubmed" if "pubmed" in lowered else "mock"
        if re.search(r"\b(audit|review|evidence review|full audit|调研|审查)\b", lowered) and quoted:
            llm = " --llm all" if re.search(r"\b(llm|all stages|full)\b", lowered) else ""
            support_refute = " --support-refute" if re.search(r"\b(refute|contradict|support-refute|反驳)\b", lowered) else ""
            return f'/biomed audit "{quoted[0].strip()}" --source {source} --papers {papers}{llm}{support_refute}'
        if re.search(r"\b(search|literature|retrieve|find|检索)\b", lowered) and quoted:
            return f'/biomed literature "{quoted[0].strip()}" --source {source} --papers {papers}'
    return text


def _safe_json_object_from_text(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if not clean:
        return {}
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        parsed = json.loads(clean)
    except Exception:
        match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            return {}
    return parsed if isinstance(parsed, dict) else {}


async def _llm_dashboard_chat_command_or_none(
    *,
    content: str,
    provider: Any | None,
    model: str,
) -> str:
    if provider is None or not model:
        return ""
    text = str(content or "").strip()
    if not text or text.startswith("/"):
        return ""
    if not re.search(
        r"\b(biomed|biomedical|pubmed|literature|evidence|paper|papers|audit|review|watch|provenance|microglia|alzheimer|claim|claims)\b|biomed-run-|watch-",
        text,
        re.IGNORECASE,
    ):
        return ""
    try:
        response = await provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You route Dashboard Chat user requests to Biomedical Evidence slash commands. "
                        "Return one JSON object only with keys: command, confidence, reason. "
                        "Use an empty command when the request is not clearly a Biomedical Evidence workflow. "
                        "Allowed command forms: /biomed status; /biomed enable pubmed; /biomed check pubmed; "
                        "/biomed audit \"question\" --source mock|pubmed --papers N [--llm all] [--support-refute]; "
                        "/biomed literature \"query\" --source mock|pubmed --papers N; "
                        "/biomed review biomed-run-...; /biomed pilot-report biomed-run-... [--format json|markdown]; "
                        "/biomed export provenance biomed-run-...; "
                        "/biomed template run template-id \"question\" [--source mock|pubmed] [--project project-id]; "
                        "/biomed watch create \"topic\" --query \"query\" [--schedule daily|weekly|manual]; "
                        "/biomed watch delete watch-.... Never invent run IDs or watch IDs."
                    ),
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
            tools=[],
            model=model,
            max_tokens=220,
            tool_choice="none",
            disable_thinking=True,
        )
    except Exception:
        return ""
    payload = _safe_json_object_from_text(getattr(response, "content", ""))
    command = str(payload.get("command") or "").strip()
    try:
        confidence = float(payload.get("confidence") or 0)
    except Exception:
        confidence = 0
    if confidence < 0.65 or not command.startswith("/biomed"):
        return ""
    return command


async def _normalize_dashboard_chat_command(
    *,
    content: str,
    provider: Any | None,
    model: str,
) -> str:
    deterministic = _deterministic_dashboard_chat_command(content)
    if deterministic != str(content or "").strip():
        return deterministic
    llm_command = await _llm_dashboard_chat_command_or_none(
        content=content,
        provider=provider,
        model=model,
    )
    return llm_command or deterministic


def _biomed_keywords_from_query(query: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(query or "")).strip(" .,:;!?\"'")
    raw = re.split(r"[,;/]|\band\b|\bor\b", text, flags=re.IGNORECASE)
    keywords: list[str] = []
    if text:
        keywords.append(text)
    words = [word for word in re.split(r"\s+", text) if len(word.strip(" .,:;!?\"'")) >= 3]
    raw.extend(words)
    for item in raw:
        clean = re.sub(r"\s+", " ", item).strip(" .,:;!?\"'")
        if len(clean) < 3:
            continue
        if clean.lower() in {"the", "with", "for", "from", "into"}:
            continue
        if clean not in keywords:
            keywords.append(clean)
    return keywords[:12]


def _biomed_help_markdown(readiness: dict[str, Any]) -> str:
    pubmed = readiness["pubmed"]["status"]
    llm = readiness["llm_provider"]["status"]
    return "\n".join(
        [
            "## /biomed commands",
            "",
            f"Status: PubMed **{pubmed}** · LLM **{llm}**",
            "",
            "| Command | What it does |",
            "|---|---|",
            "| `/biomed status` | Show provider, PubMed, export, and confirmation readiness. |",
            "| `/biomed enable pubmed` | Enable live PubMed command execution in the active config. |",
            "| `/biomed check pubmed` | Check whether live PubMed access is ready. |",
            "| `/biomed audit \"question\" --source mock --papers 10` | Run a deterministic evidence audit using mock literature. |",
            "| `/biomed audit \"question\" --source pubmed --papers 10 --llm all --support-refute` | Run a live PubMed audit with all configured LLM stages. |",
            "| `/biomed literature \"query\" --source pubmed --papers 10` | Retrieve literature only, without answer synthesis. |",
            "| `/biomed review <run_id>` | Open a saved Run Evidence Review. |",
            "| `/biomed pilot-report <run_id> --format markdown` | Export the team Pilot Report handoff. |",
            "| `/biomed export provenance <run_id>` | Prepare provenance export when enabled. |",
            "| `/biomed template run <template_id> \"question\" --source mock` | Run a saved or built-in workflow template. |",
            "| `/biomed project create \"name\" --question \"...\"` | Create a project after confirmation. |",
            "| `/biomed watch create \"topic\" --query \"...\"` | Create a research watch after confirmation. |",
            "| `/biomed watch delete <watch_id>` | Delete a research watch and cancel its framework schedule after confirmation. |",
            "",
            "Biomedical Evidence is research-only. It will not diagnose, recommend treatment, interpret private records, or answer patient-specific medical questions.",
        ]
    )


def _biomed_status_markdown(readiness: dict[str, Any]) -> str:
    return "\n".join(
        [
            "## Biomedical Evidence status",
            "",
            "| Capability | Status |",
            "|---|---|",
            f"| LLM provider | {readiness['llm_provider']['status']} {readiness['llm_provider'].get('model') or ''} |",
            f"| PubMed command policy | {readiness['pubmed']['policy_status']} |",
            f"| PubMed network | {readiness['pubmed']['network_status']} |",
            f"| Default source | {readiness['source']['default_source']} |",
            f"| Obsidian export | {'enabled' if readiness['exports'].get('obsidian') else 'disabled'} |",
            f"| Provenance export | {'enabled' if readiness['exports'].get('provenance') else 'disabled'} |",
            f"| Confirmation-gated tools | {len(readiness['confirmation']['required_for'])} |",
            "",
            readiness["pubmed"].get("message", ""),
            readiness["llm_provider"].get("missing_effect", ""),
        ]
    ).strip()


def _biomed_pubmed_enabled_markdown(readiness: dict[str, Any], result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "## PubMed enabled",
            "",
            "`allow_live_pubmed_tools` is now set to `true` for Biomedical Evidence.",
            "",
            "| Capability | Status |",
            "|---|---|",
            f"| PubMed command policy | {readiness['pubmed']['policy_status']} |",
            f"| PubMed network | {readiness['pubmed']['network_status']} |",
            f"| Config | `{result.get('path', '')}` |",
            "",
            "You can now run `/biomed check pubmed` or a PubMed-backed `/biomed audit ... --source pubmed` command.",
        ]
    )


def _parse_biomed_command(
    content: str,
    *,
    readiness: dict[str, Any],
    contracts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    raw = str(content or "").strip()
    if not raw.startswith("/biomed"):
        return {
            "ok": False,
            "command": "",
            "action": "",
            "errors": ["Command must start with /biomed."],
            "missing_requirements": [],
            "can_send": False,
        }
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        return {
            "ok": False,
            "command": "/biomed",
            "action": "",
            "errors": [f"Invalid command syntax: {exc}"],
            "missing_requirements": [],
            "can_send": False,
        }
    if not tokens or tokens[0] != "/biomed":
        return {
            "ok": False,
            "command": "/biomed",
            "action": "",
            "errors": ["Unknown command prefix."],
            "missing_requirements": [],
            "can_send": False,
        }
    action_tokens, flags = _parse_flags(tokens[1:])
    action = action_tokens[0].lower() if action_tokens else "help"
    args: dict[str, Any] = {}
    errors: list[str] = []
    missing: list[dict[str, str]] = []
    tool_name = ""
    normalized_action = action
    source = _flag_str(flags, "source", default=readiness["source"]["default_source"] or "mock")
    if source not in {"mock", "pubmed"}:
        errors.append("Source must be mock or pubmed.")
    if action in {"status", "help"}:
        normalized_action = action
    elif action == "enable" and len(action_tokens) > 1 and action_tokens[1].lower() == "pubmed":
        normalized_action = "enable_pubmed"
        tool_name = "configure_biomed_pubmed_policy"
        args = {
            "allow_live_pubmed_tools": True,
            "config_path": readiness.get("config_path", ""),
        }
    elif action == "check" and len(action_tokens) > 1 and action_tokens[1].lower() == "pubmed":
        normalized_action = "check_pubmed"
        tool_name = "check_literature_access"
        args = {
            "query": _flag_str(flags, "query", default="microglia Alzheimer disease"),
            "source": "pubmed",
            "max_results": _flag_int(flags, "papers", "max_results", default=3),
        }
        missing.extend(_missing_for_source("pubmed", readiness))
    elif action == "audit":
        question = action_tokens[1] if len(action_tokens) > 1 else ""
        if not question:
            errors.append("Audit requires a quoted question.")
        papers = _flag_int(flags, "papers", "max_papers", default=readiness["limits"]["max_papers"])
        llm = str(flags.get("llm") or "off").lower()
        if llm not in {"off", "all"}:
            errors.append("LLM must be off or all.")
        normalized_action = "audit"
        tool_name = "answer_with_audit"
        args = {
            "question": question,
            "source": source,
            "max_papers": papers,
            "llm": llm,
            "execute_support_refute": bool(flags.get("support_refute")),
            **({flag: True for flag in _BIOMED_LLM_FLAGS} if llm == "all" else {}),
        }
        project_id = _flag_str(flags, "project", "project_id", default="")
        if project_id:
            args["project_id"] = project_id
        missing.extend(_missing_for_source(source, readiness))
        missing.extend(_missing_for_llm(flags, readiness))
    elif action == "literature":
        query = action_tokens[1] if len(action_tokens) > 1 else ""
        if not query:
            errors.append("Literature search requires a quoted query.")
        normalized_action = "literature"
        tool_name = "search_literature"
        args = {
            "query": query,
            "source": source,
            "max_results": _flag_int(flags, "papers", "max_results", default=readiness["limits"]["max_papers"]),
        }
        missing.extend(_missing_for_source(source, readiness))
    elif action == "review":
        run_id = action_tokens[1] if len(action_tokens) > 1 else ""
        if not run_id:
            errors.append("Review requires a run id.")
        normalized_action = "review"
        tool_name = "get_run_evidence_review"
        args = {"run_id": run_id}
    elif action in {"pilot-report", "pilot_report"}:
        run_id = action_tokens[1] if len(action_tokens) > 1 else ""
        report_format = _flag_str(flags, "format", default="markdown") or "markdown"
        if not run_id:
            errors.append("Pilot Report requires a run id.")
        if report_format not in {"markdown", "json"}:
            errors.append("Pilot Report format must be markdown or json.")
        normalized_action = "pilot_report"
        tool_name = "export_evidence_report"
        args = {
            "run_id": run_id,
            "report_type": "pilot",
            "format": report_format,
        }
        for flag_name, arg_name in (
            ("baseline_minutes", "manual_baseline_minutes"),
            ("manual_baseline_minutes", "manual_baseline_minutes"),
            ("reviewer_minutes", "reviewer_minutes"),
        ):
            if flag_name in flags:
                try:
                    args[arg_name] = float(flags[flag_name])
                except Exception:
                    errors.append(f"{flag_name.replace('_', '-')} must be numeric.")
    elif action == "export" and len(action_tokens) > 2 and action_tokens[1].lower() == "provenance":
        run_id = action_tokens[2]
        normalized_action = "export_provenance"
        tool_name = "export_provenance_graph"
        args = {"run_id": run_id}
        if not readiness["exports"]["provenance"]:
            missing.append({
                "kind": "export",
                "label": "Provenance export disabled",
                "detail": "Set enable_provenance_export=true before using provenance export from chat.",
            })
    elif action == "template" and len(action_tokens) > 1 and action_tokens[1].lower() == "run":
        template_id = action_tokens[2] if len(action_tokens) > 2 else ""
        question = action_tokens[3] if len(action_tokens) > 3 else ""
        if not template_id:
            errors.append("Template run requires a template id.")
        if not question:
            errors.append("Template run requires a quoted question.")
        normalized_action = "template_run"
        tool_name = "run_saved_tool_chain_template"
        args = {"template_id": template_id, "question": question}
        if "source" in flags:
            args["source_override"] = source
            missing.extend(_missing_for_source(source, readiness))
        project_id = _flag_str(flags, "project", "project_id", default="")
        if project_id:
            args["project_id"] = project_id
        if "papers" in flags or "max_papers" in flags:
            args["max_papers_override"] = _flag_int(
                flags,
                "papers",
                "max_papers",
                default=readiness["limits"]["max_papers"],
            )
    elif action == "project" and len(action_tokens) > 2 and action_tokens[1].lower() == "create":
        name = action_tokens[2]
        question = _flag_str(flags, "question", default="")
        if not question:
            errors.append("Project creation requires --question.")
        normalized_action = "project_create"
        tool_name = "create_biomed_project"
        args = {"name": name, "research_question": question}
    elif action == "watch" and len(action_tokens) > 2 and action_tokens[1].lower() == "create":
        topic = action_tokens[2]
        query = _flag_str(flags, "query", default="")
        if not query:
            errors.append("Watch creation requires --query.")
        normalized_action = "watch_create"
        tool_name = "watch_research_topic"
        args = {
            "topic": topic,
            "description": query,
            "include_keywords": _biomed_keywords_from_query(query),
            "schedule": _flag_str(flags, "schedule", default="daily") or "daily",
            "min_relevance_score": _flag_float(flags, "min_relevance_score", "min-relevance", "threshold", default=0.7),
        }
        if args["schedule"] not in {"daily", "weekly", "manual"}:
            errors.append("Watch schedule must be daily, weekly, or manual.")
    elif action == "watch" and len(action_tokens) > 2 and action_tokens[1].lower() in {"delete", "remove"}:
        watch_id = action_tokens[2]
        if not watch_id:
            errors.append("Watch deletion requires a watch id.")
        normalized_action = "watch_delete"
        tool_name = "delete_research_watch_topic"
        args = {"watch_id": watch_id}
    else:
        errors.append("Unknown /biomed command. Try /biomed help.")
    confirmation = _confirmation_preview(tool_name, contracts) if tool_name else None
    final_prompt = _biomed_prompt_for_preview(normalized_action, args)
    artifacts = _biomed_artifacts_for_run(str(args.get("run_id") or ""))
    if not artifacts:
        artifacts = _biomed_artifacts_from_text(final_prompt)
    deterministic_response = ""
    if normalized_action == "help":
        deterministic_response = _biomed_help_markdown(readiness)
    elif normalized_action == "status":
        deterministic_response = _biomed_status_markdown(readiness)
    return {
        "ok": not errors,
        "command": "/biomed",
        "action": normalized_action,
        "tool_name": tool_name,
        "arguments": args,
        "flags": flags,
        "missing_requirements": missing,
        "confirmation": confirmation,
        "final_prompt": final_prompt,
        "artifacts": artifacts or None,
        "deterministic_response": deterministic_response,
        "can_send": not errors and not missing,
        "errors": errors,
    }


def create_dashboard_app(
    workspace: Path,
    *,
    manual_consolidator: ManualConsolidator | None = None,
    manual_memory_optimizer: ManualMemoryOptimizer | None = None,
    memory_admin: MemoryAdminApi,
    memory_store: MemoryStore | None = None,
    message_bus: MessageBus | None = None,
    event_bus: EventBus | None = None,
    tool_registry: Any | None = None,
    tool_hooks: list[Any] | None = None,
    biomed_revision_provider: Any | None = None,
    biomed_revision_model: str = "",
) -> FastAPI:
    workspace.mkdir(parents=True, exist_ok=True)
    store = SessionStore(workspace / "sessions.db")
    proactive_reader: ProactiveDashboardReader | None = None
    optimizer_task: asyncio.Task[None] | None = None
    optimizer_last_status = "idle"
    optimizer_last_error: str | None = None
    plugin_closeables: list[object] = []
    project_root = Path(__file__).resolve().parent.parent
    plugins_root = project_root / "plugins"
    static_dir = project_root / "static" / "dashboard"
    chat_mux = DashboardChatMultiplexer(
        bus=message_bus,
        event_bus=event_bus,
        store=store,
    )
    approval_tool_executor = ToolExecutor(tool_hooks or [])

    def get_proactive_reader() -> ProactiveDashboardReader:
        nonlocal proactive_reader
        if proactive_reader is None:
            ProactiveStateStore(workspace / "proactive.db").close()
            proactive_reader = ProactiveDashboardReader(workspace / "proactive.db")
        return proactive_reader

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        chat_mux.start()
        compile_task = asyncio.create_task(_compile_pending_plugins_async())
        try:
            yield
        finally:
            _ = compile_task.cancel()
            try:
                await compile_task
            except asyncio.CancelledError:
                pass
            store.close()
            _close_dashboard_value(memory_admin)
            for closeable in reversed(plugin_closeables):
                _close_dashboard_value(closeable)
            if proactive_reader is not None:
                get_proactive_reader().close()

    app = FastAPI(title="Akashic Dashboard API", lifespan=lifespan)
    app.state.memory_admin = memory_admin
    app.state.memory_store = memory_store or MemoryStore(workspace)
    app.state.biomed_revision_provider = biomed_revision_provider
    app.state.biomed_revision_model = biomed_revision_model
    app.state.dashboard_chat = chat_mux
    app.mount("/assets", StaticFiles(directory=static_dir), name="dashboard-assets")

    # Compile TypeScript plugin panels and mount plugin routes
    if plugins_root.is_dir():
        for _plugin_dir in sorted(plugins_root.iterdir()):
            if not _plugin_dir.is_dir():
                continue
            if _is_plugin_disabled(_plugin_dir):
                continue
            if not _plugin_dashboard_enabled(app, _plugin_dir):
                continue
            _build_plugin_panels_js(project_root, _plugin_dir)
            if (_plugin_dir / "dashboard.py").exists():
                plugin_closeables.extend(
                    _load_plugin_dashboard(app, _plugin_dir, workspace)
                )

    @app.get("/")
    def dashboard_index() -> Response:
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        app_v = str(int((static_dir / "app.js").stat().st_mtime_ns))
        css_v = str(int((static_dir / "styles.css").stat().st_mtime_ns))
        html = re.sub(r'(/assets/styles\.css)(\?[^"]*)?', rf'\1?v={css_v}', html)
        html = re.sub(r'(/assets/app\.js)(\?[^"]*)?', rf'\1?v={app_v}', html)
        return Response(content=html, media_type="text/html")

    @app.get("/api/dashboard/plugins")
    def list_dashboard_plugins() -> list[dict[str, Any]]:
        if not plugins_root.is_dir():
            return []
        result: list[dict[str, Any]] = []
        for plugin_dir in sorted(plugins_root.iterdir()):
            if not plugin_dir.is_dir() or _is_plugin_disabled(plugin_dir):
                continue
            if not _plugin_dashboard_enabled(app, plugin_dir):
                continue
            _build_plugin_panels_js(project_root, plugin_dir)
            panels: list[dict[str, Any]] = []
            for js_path in sorted(plugin_dir.glob("dashboard_panel*.js")):
                css_path = js_path.with_suffix(".css")
                panels.append({
                    "name": js_path.stem,
                    "js_version": str(js_path.stat().st_mtime_ns),
                    "has_css": css_path.exists(),
                })
            if panels:
                result.append({"id": plugin_dir.name, "panels": panels})
        return result

    @app.get("/api/dashboard/chat/status")
    async def get_chat_status(
        session_key: str = _DASHBOARD_CHAT_DEFAULT_SESSION,
    ) -> dict[str, Any]:
        clean_session_key = _validate_dashboard_chat_session(session_key)
        return {
            "enabled": chat_mux.enabled,
            "reason": "" if chat_mux.enabled else _DASHBOARD_CHAT_DISABLED_REASON,
            "default_session_key": _DASHBOARD_CHAT_DEFAULT_SESSION,
            "streaming": chat_mux.enabled,
            "session_key": clean_session_key,
            "latest_seq": await chat_mux.latest_seq(clean_session_key),
            "active": await chat_mux.is_active(clean_session_key),
            "replay_limit": _DASHBOARD_CHAT_REPLAY_LIMIT,
        }

    @app.get("/api/dashboard/chat/commands")
    def list_chat_commands() -> dict[str, Any]:
        biomed_dir = plugins_root / "biomed_evidence"
        commands = _chat_command_manifest(
            workspace=workspace,
            plugin_dir=biomed_dir,
            provider=biomed_revision_provider,
            model=biomed_revision_model,
        )
        commands["enabled"] = chat_mux.enabled
        commands["reason"] = "" if chat_mux.enabled else _DASHBOARD_CHAT_DISABLED_REASON
        return commands

    @app.get("/api/dashboard/chat/commands/biomed/status")
    def get_biomed_command_status() -> dict[str, Any]:
        return _biomed_readiness(
            workspace=workspace,
            plugin_dir=plugins_root / "biomed_evidence",
            provider=biomed_revision_provider,
            model=biomed_revision_model,
        )

    @app.post("/api/dashboard/chat/commands/parse")
    async def parse_chat_command(payload: ChatCommandParsePayload) -> dict[str, Any]:
        session_key = _validate_dashboard_chat_session(payload.session_key)
        content = _validate_dashboard_chat_content(payload.content)
        routed_content = await _normalize_dashboard_chat_command(
            content=content,
            provider=biomed_revision_provider,
            model=biomed_revision_model,
        )
        readiness = _biomed_readiness(
            workspace=workspace,
            plugin_dir=plugins_root / "biomed_evidence",
            provider=biomed_revision_provider,
            model=biomed_revision_model,
        )
        contracts = _biomed_tool_contract_map()
        if routed_content.strip().startswith("/biomed"):
            parsed = _parse_biomed_command(
                routed_content,
                readiness=readiness,
                contracts=contracts,
            )
            return {
                "session_key": session_key,
                "kind": "biomed",
                "readiness": readiness,
                "routed_from": content if routed_content != content else "",
                **parsed,
            }
        return {
            "session_key": session_key,
            "kind": "message",
            "ok": True,
            "command": "",
            "action": "",
            "tool_name": "",
            "arguments": {},
            "missing_requirements": [],
            "confirmation": None,
            "final_prompt": content,
            "can_send": True,
            "errors": [],
        }

    @app.post("/api/dashboard/chat/sessions", status_code=201)
    def create_chat_session(payload: ChatSessionCreatePayload | None = None) -> dict[str, Any]:
        if not chat_mux.enabled:
            raise HTTPException(status_code=503, detail=_DASHBOARD_CHAT_DISABLED_REASON)
        suffix = secrets.token_hex(4)
        session_key = f"{_DASHBOARD_CHAT_CHANNEL}:{suffix}"
        metadata = _dashboard_chat_placeholder_metadata(payload.title if payload is not None else None)
        meta = store.create_session(key=session_key, metadata=metadata)
        meta["message_count"] = store.count_messages(session_key)
        return meta

    @app.get("/api/dashboard/chat/history")
    def get_chat_history(
        session_key: str = _DASHBOARD_CHAT_DEFAULT_SESSION,
        page_size: int = 80,
    ) -> dict[str, Any]:
        clean_session_key = _validate_dashboard_chat_session(session_key)
        meta = store.get_session_meta(clean_session_key)
        metadata = dict((meta or {}).get("metadata") or {})
        items, total = store.list_messages_for_dashboard(
            session_key=clean_session_key,
            page=1,
            page_size=max(1, min(page_size, 200)),
            sort_by="seq",
            sort_order="asc",
        )
        pending_approvals = _dashboard_chat_pending_approvals(metadata)
        for item in items:
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            restored = _dashboard_chat_pending_approval_from_history({
                **dict(extra or {}),
                **{key: value for key, value in item.items() if key not in {"extra"}},
            })
            if restored:
                approval_id = str(restored.get("approval_id") or "").strip()
                if approval_id and approval_id not in pending_approvals:
                    pending_approvals[approval_id] = restored
        return {
            "items": [_dashboard_chat_history_item(item) for item in items],
            "total": total,
            "page": 1,
            "page_size": max(1, min(page_size, 200)),
            "session_key": clean_session_key,
            "pending_approvals": [
                approval
                for approval in pending_approvals.values()
                if str(approval.get("status") or "pending") == "pending"
            ],
        }

    @app.post("/api/dashboard/chat/messages", status_code=202)
    async def post_chat_message(payload: ChatMessagePayload) -> dict[str, Any]:
        if not chat_mux.enabled or message_bus is None:
            raise HTTPException(
                status_code=503,
                detail=_DASHBOARD_CHAT_DISABLED_REASON,
        )
        session_key = _validate_dashboard_chat_session(payload.session_key)
        content = _validate_dashboard_chat_content(payload.content)
        routed_content = await _normalize_dashboard_chat_command(
            content=content,
            provider=biomed_revision_provider,
            model=biomed_revision_model,
        )
        effective_content = content
        command_preview: dict[str, Any] | None = None
        if routed_content.startswith("/biomed"):
            command_preview = _parse_biomed_command(
                routed_content,
                readiness=_biomed_readiness(
                    workspace=workspace,
                    plugin_dir=plugins_root / "biomed_evidence",
                    provider=biomed_revision_provider,
                    model=biomed_revision_model,
                ),
                contracts=_biomed_tool_contract_map(),
            )
            if command_preview.get("errors"):
                raise HTTPException(
                    status_code=400,
                    detail="; ".join(str(item) for item in command_preview["errors"]),
                )
            if command_preview.get("action") == "enable_pubmed":
                result = _write_biomed_bool_config(
                    workspace,
                    "allow_live_pubmed_tools",
                    True,
                )
                fresh_readiness = _biomed_readiness(
                    workspace=workspace,
                    plugin_dir=plugins_root / "biomed_evidence",
                    provider=biomed_revision_provider,
                    model=biomed_revision_model,
                )
                command_preview["readiness"] = fresh_readiness
                deterministic_response = _biomed_pubmed_enabled_markdown(
                    fresh_readiness,
                    result,
                )
            else:
                deterministic_response = str(command_preview.get("deterministic_response") or "").strip()
            if deterministic_response:
                chat_id = _dashboard_chat_id(session_key)
                _ensure_dashboard_chat_session_title(store, session_key, content)
                now = utcnow().isoformat()
                user_seq = store.next_seq(session_key)
                store.insert_message(
                    session_key,
                    role="user",
                    content=content,
                    ts=now,
                    seq=user_seq,
                    extra={
                        "command": command_preview,
                        "routed_command": routed_content
                        if routed_content != content
                        else "",
                        "source": "dashboard_chat_command",
                    },
                )
                await chat_mux.publish_user_message_accepted(
                    session_key=session_key,
                    content=content,
                )
                seq = store.next_seq(session_key)
                store.insert_message(
                    session_key,
                    role="assistant",
                    content=deterministic_response,
                    ts=utcnow().isoformat(),
                    seq=seq,
                    extra={
                        "command": command_preview,
                        "source": "dashboard_chat_command",
                    },
                )
                await chat_mux._on_outbound(
                    OutboundMessage(
                        channel=_DASHBOARD_CHAT_CHANNEL,
                        chat_id=chat_id,
                        content=deterministic_response,
                        metadata={
                            "session_key_override": session_key,
                            "source": "dashboard_chat_command",
                            "command": command_preview,
                            "routed_command": routed_content
                            if routed_content != content
                            else "",
                            "command_action": command_preview.get("action"),
                            "artifacts": command_preview.get("artifacts") or None,
                        },
                    )
                )
                return {
                    "accepted": True,
                    "session_key": session_key,
                    "chat_id": chat_id,
                    "command": command_preview,
                    "deterministic_response": True,
                }
            if command_preview.get("missing_requirements"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Command requirements are not satisfied.",
                        "missing_requirements": command_preview["missing_requirements"],
                    },
                )
            if command_preview.get("confirmation"):
                chat_id = _dashboard_chat_id(session_key)
                _ensure_dashboard_chat_session_title(store, session_key, content)
                now = utcnow().isoformat()
                user_seq = store.next_seq(session_key)
                store.insert_message(
                    session_key,
                    role="user",
                    content=content,
                    ts=now,
                    seq=user_seq,
                    extra={
                        "command": command_preview,
                        "source": "dashboard_chat_command",
                        "routed_command": routed_content
                        if routed_content != content
                        else "",
                    },
                )
                await chat_mux.publish_user_message_accepted(
                    session_key=session_key,
                    content=content,
                )
                tool_name = str(command_preview.get("tool_name") or "").strip()
                final_arguments = dict(command_preview.get("arguments") or {})
                approval_id = _dashboard_chat_command_approval_id(
                    session_key,
                    tool_name,
                    final_arguments,
                )
                confirmation = {
                    **dict(command_preview.get("confirmation") or {}),
                    "approval_id": approval_id,
                    "session_key": session_key,
                    "chat_id": chat_id,
                    "channel": _DASHBOARD_CHAT_CHANNEL,
                }
                reason = str(
                    (command_preview.get("confirmation") or {}).get("reason")
                    or "This Biomedical Evidence action requires confirmation before execution."
                )
                _store_dashboard_chat_pending_approval(
                    store,
                    session_key=session_key,
                    approval={
                        "approval_id": approval_id,
                        "tool_name": tool_name,
                        "call_id": f"command:{approval_id}",
                        "iteration": 1,
                        "arguments": final_arguments,
                        "final_arguments": final_arguments,
                        "reason": reason,
                        "confirmation": confirmation,
                        "command": command_preview,
                        "created_at": utcnow().isoformat(),
                    },
                )
                assistant_content = (
                    f"Approval required for `{tool_name}`.\n\n"
                    "Review the action below, then approve it to run."
                )
                seq = store.next_seq(session_key)
                store.insert_message(
                    session_key,
                    role="assistant",
                    content=assistant_content,
                    ts=utcnow().isoformat(),
                    seq=seq,
                    extra={
                        "command": command_preview,
                        "source": "dashboard_chat_command",
                    },
                )
                await chat_mux._on_outbound(
                    OutboundMessage(
                        channel=_DASHBOARD_CHAT_CHANNEL,
                        chat_id=chat_id,
                        content=assistant_content,
                        metadata={
                            "session_key_override": session_key,
                            "source": "dashboard_chat_command",
                            "command": command_preview,
                            "routed_command": routed_content
                            if routed_content != content
                            else "",
                            "command_action": command_preview.get("action"),
                        },
                    )
                )
                await chat_mux._on_tool_approval_required(
                    ToolCallApprovalRequired(
                        session_key=session_key,
                        channel=_DASHBOARD_CHAT_CHANNEL,
                        chat_id=chat_id,
                        iteration=1,
                        call_id=f"command:{approval_id}",
                        tool_name=tool_name,
                        arguments=final_arguments,
                        final_arguments=final_arguments,
                        reason=reason,
                        confirmation=confirmation,
                    )
                )
                return {
                    "accepted": True,
                    "session_key": session_key,
                    "chat_id": chat_id,
                    "command": command_preview,
                    "approval_required": True,
                    "approval_id": approval_id,
                }
            effective_content = str(command_preview.get("final_prompt") or routed_content)
        chat_id = _dashboard_chat_id(session_key)
        _ensure_dashboard_chat_session_title(store, session_key, content)
        metadata = {
            "session_key_override": session_key,
            "source": "dashboard_chat",
        }
        if command_preview:
            metadata["command"] = command_preview
            metadata["raw_content"] = content
        inbound = InboundMessage(
            channel=_DASHBOARD_CHAT_CHANNEL,
            sender="dashboard-user",
            chat_id=chat_id,
            content=effective_content,
            metadata=metadata,
        )
        try:
            await message_bus.publish_inbound(inbound)
            await chat_mux.publish_user_message_accepted(
                session_key=session_key,
                content=content,
            )
        except Exception as exc:
            await chat_mux.publish_error(session_key=session_key, message=str(exc))
            raise
        return {
            "accepted": True,
            "session_key": session_key,
            "chat_id": chat_id,
        }

    @app.post("/api/dashboard/chat/approvals/{approval_id}")
    async def decide_chat_approval(
        approval_id: str,
        payload: ChatApprovalDecisionPayload | None = None,
        session_key: str = _DASHBOARD_CHAT_DEFAULT_SESSION,
    ) -> dict[str, Any]:
        clean_session_key = _validate_dashboard_chat_session(session_key)
        clean_approval_id = str(approval_id or "").strip()
        if not clean_approval_id:
            raise HTTPException(status_code=400, detail="approval_id is required")
        meta = store.get_session_meta(clean_session_key)
        if meta is None:
            raise HTTPException(status_code=404, detail="session not found")
        metadata = dict(meta.get("metadata") or {})
        pending = _dashboard_chat_pending_approvals(metadata)
        approval = dict(pending.get(clean_approval_id) or {})
        if not approval:
            raise HTTPException(status_code=404, detail="approval not found")
        if str(approval.get("status") or "pending") != "pending":
            raise HTTPException(status_code=409, detail="approval already handled")
        decision = str((payload.decision if payload is not None else "approve") or "").lower()
        if decision not in {"approve", "reject"}:
            raise HTTPException(status_code=400, detail="decision must be approve or reject")
        if decision == "reject":
            approval["status"] = "rejected"
            approval["resolved_at"] = utcnow().isoformat()
            pending[clean_approval_id] = approval
            metadata[_DASHBOARD_CHAT_APPROVALS_META_KEY] = pending
            store.update_session(clean_session_key, metadata=metadata)
            await chat_mux.publish_error(
                session_key=clean_session_key,
                message=f"Approval rejected: {approval.get('tool_name')}",
            )
            return {
                "approved": False,
                "approval_id": clean_approval_id,
                "status": "rejected",
            }
        if tool_registry is None:
            raise HTTPException(
                status_code=503,
                detail="Tool execution is unavailable in this dashboard runtime.",
            )
        tool_name = str(approval.get("tool_name") or "").strip()
        final_arguments = approval.get("final_arguments")
        if not tool_name or not isinstance(final_arguments, dict):
            raise HTTPException(status_code=409, detail="approval payload is invalid")
        try:
            exec_result = await approval_tool_executor.execute(
                ToolExecutionRequest(
                    call_id=f"dashboard-approval:{clean_approval_id}",
                    tool_name=tool_name,
                    arguments=dict(final_arguments),
                    source="passive",
                    session_key=clean_session_key,
                    channel=_DASHBOARD_CHAT_CHANNEL,
                    chat_id=_dashboard_chat_id(clean_session_key),
                    request_text=f"Approved Dashboard Chat action {clean_approval_id}.",
                    approval_id=clean_approval_id,
                    approved=True,
                ),
                tool_registry.execute,
            )
        except Exception as exc:
            approval["status"] = "failed"
            approval["resolved_at"] = utcnow().isoformat()
            approval["error"] = str(exc)
            pending[clean_approval_id] = approval
            metadata[_DASHBOARD_CHAT_APPROVALS_META_KEY] = pending
            store.update_session(clean_session_key, metadata=metadata)
            await chat_mux.publish_error(
                session_key=clean_session_key,
                message=f"Approved tool failed: {tool_name}: {exc}",
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if exec_result.status != "success":
            approval["status"] = "failed"
            approval["resolved_at"] = utcnow().isoformat()
            approval["error"] = str(exec_result.output)
            pending[clean_approval_id] = approval
            metadata[_DASHBOARD_CHAT_APPROVALS_META_KEY] = pending
            store.update_session(clean_session_key, metadata=metadata)
            await chat_mux.publish_error(
                session_key=clean_session_key,
                message=f"Approved tool did not run: {tool_name}: {exec_result.output}",
            )
            raise HTTPException(status_code=409, detail=str(exec_result.output))
        result = exec_result.output
        text = str(result)
        artifacts = _biomed_artifacts_from_tool_result(tool_name, result)
        watch_schedule: dict[str, Any] | None = None
        if tool_name == "watch_research_topic" and tool_registry is not None:
            watch_payload = _json_dict_from_tool_result(result)
            try:
                watch_schedule = await _register_biomed_watch_framework_schedule(
                    tool_registry=tool_registry,
                    watch=watch_payload,
                    session_key=clean_session_key,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to register framework schedule for biomed watch: %s",
                    exc,
                    exc_info=True,
                )
                watch_schedule = {
                    "status": "failed",
                    "reason": str(exc),
                }
        elif tool_name == "delete_research_watch_topic" and tool_registry is not None:
            deleted_watch_id = str(
                dict(final_arguments).get("watch_id")
                or _json_dict_from_tool_result(result).get("watch_id")
                or ""
            ).strip()
            try:
                watch_schedule = await _cancel_biomed_watch_framework_schedule(
                    tool_registry=tool_registry,
                    watch_id=deleted_watch_id,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to cancel framework schedule for biomed watch: %s",
                    exc,
                    exc_info=True,
                )
                watch_schedule = {
                    "status": "failed",
                    "reason": str(exc),
                }
        approval["status"] = "approved"
        approval["resolved_at"] = utcnow().isoformat()
        approval["result_preview"] = _preview_text(
            _redact_dashboard_chat_string(text),
            1200,
        )
        if artifacts:
            approval["artifacts"] = artifacts
        if watch_schedule is not None:
            approval["framework_schedule"] = _sanitize_dashboard_chat_value(
                watch_schedule
            )
        pending[clean_approval_id] = approval
        metadata[_DASHBOARD_CHAT_APPROVALS_META_KEY] = pending
        store.update_session(clean_session_key, metadata=metadata)
        seq = store.next_seq(clean_session_key)
        assistant_markdown = _dashboard_chat_approval_success_markdown(
            tool_name=tool_name,
            result=result,
            final_arguments=dict(final_arguments),
            framework_schedule=watch_schedule,
        )
        row = store.insert_message(
            clean_session_key,
            role="assistant",
            content=assistant_markdown,
            ts=utcnow().isoformat(),
            seq=seq,
            extra={
                "approval_id": clean_approval_id,
                "tool_name": tool_name,
                "source": "dashboard_chat_approval",
                "artifacts": artifacts,
                "framework_schedule": _sanitize_dashboard_chat_value(
                    watch_schedule or {}
                ),
            },
        )
        await chat_mux._on_outbound(
            OutboundMessage(
                channel=_DASHBOARD_CHAT_CHANNEL,
                chat_id=_dashboard_chat_id(clean_session_key),
                content=str(row["content"]),
                metadata={
                    "session_key_override": clean_session_key,
                    "artifacts": artifacts,
                    "framework_schedule": _sanitize_dashboard_chat_value(
                        watch_schedule or {}
                    ),
                },
            )
        )
        return {
            "approved": True,
            "approval_id": clean_approval_id,
            "status": "approved",
            "tool_name": tool_name,
            "result_preview": approval["result_preview"],
            "artifacts": artifacts,
            "framework_schedule": _sanitize_dashboard_chat_value(
                watch_schedule or {}
            ),
        }

    @app.get("/api/dashboard/chat/stream")
    async def stream_chat_events(
        request: Request,
        session_key: str = _DASHBOARD_CHAT_DEFAULT_SESSION,
        since_seq: int | None = Query(default=None, ge=0),
    ) -> StreamingResponse:
        if not chat_mux.enabled:
            raise HTTPException(
                status_code=503,
                detail=_DASHBOARD_CHAT_DISABLED_REASON,
            )
        clean_session_key = _validate_dashboard_chat_session(session_key)

        async def event_stream() -> AsyncIterator[str]:
            queue = await chat_mux.subscribe(
                clean_session_key,
                since_seq=since_seq,
            )
            try:
                yield _sse_payload(
                    "connected",
                    {
                        "event": "connected",
                        "seq": await chat_mux.latest_seq(clean_session_key),
                        "session_key": clean_session_key,
                        "kind": "system",
                        "label": "Connected",
                        "latest_seq": await chat_mux.latest_seq(clean_session_key),
                        "replay_from_seq": since_seq,
                    },
                )
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event, data = await asyncio.wait_for(
                            queue.get(),
                            timeout=15.0,
                        )
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield _sse_payload(event, data)
            finally:
                await chat_mux.unsubscribe(clean_session_key, queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/plugins/{plugin_id}/{panel_name}.js")
    def get_plugin_panel_js(plugin_id: str, panel_name: str) -> FileResponse:
        if not panel_name.startswith("dashboard_panel"):
            raise HTTPException(status_code=404, detail="plugin panel not found")
        plugin_dir = _resolve_plugin_dir(plugins_root, plugin_id)
        if _is_plugin_disabled(plugin_dir) or not _plugin_dashboard_enabled(app, plugin_dir):
            raise HTTPException(status_code=404, detail="plugin panel not found")
        _build_plugin_panels_js(project_root, plugin_dir)
        js_path = plugin_dir / f"{panel_name}.js"
        if not js_path.exists():
            raise HTTPException(status_code=404, detail="plugin panel not found")
        return FileResponse(js_path, media_type="application/javascript")

    @app.get("/plugins/{plugin_id}/{panel_name}.css")
    def get_plugin_panel_css(plugin_id: str, panel_name: str) -> FileResponse:
        if not panel_name.startswith("dashboard_panel"):
            raise HTTPException(status_code=404, detail="plugin panel css not found")
        plugin_dir = _resolve_plugin_dir(plugins_root, plugin_id)
        if _is_plugin_disabled(plugin_dir) or not _plugin_dashboard_enabled(app, plugin_dir):
            raise HTTPException(status_code=404, detail="plugin panel css not found")
        css_path = plugin_dir / f"{panel_name}.css"
        if not css_path.exists():
            raise HTTPException(status_code=404, detail="plugin panel css not found")
        return FileResponse(css_path, media_type="text/css")

    @app.get("/api/dashboard/sessions")
    def list_sessions(
        q: str = "",
        channel: str = "",
        updated_from: str = "",
        updated_to: str = "",
        has_proactive: bool | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        items, total = store.list_sessions_for_dashboard(
            q=q,
            channel=channel,
            updated_from=updated_from,
            updated_to=updated_to,
            has_proactive=has_proactive,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.get("/api/dashboard/sessions/{session_key:path}/messages")
    def list_session_messages(
        session_key: str,
        q: str = "",
        role: str = "",
        page: int = 1,
        page_size: int = 25,
        sort_by: str = "ts",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        if not store.session_exists(session_key):
            raise HTTPException(status_code=404, detail="session 不存在")
        items, total = store.list_messages_for_dashboard(
            session_key=session_key,
            q=q,
            role=role,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.post("/api/dashboard/sessions/{session_key:path}/consolidate")
    async def consolidate_session(
        session_key: str,
        payload: SessionConsolidatePayload | None = None,
    ) -> dict[str, Any]:
        archive_all = bool(payload.archive_all) if payload is not None else False
        force = bool(payload.force) if payload is not None else True
        if manual_consolidator is None:
            raise HTTPException(status_code=503, detail="manual consolidation 未启用")
        if not store.session_exists(session_key):
            raise HTTPException(status_code=404, detail="session 不存在")
        logger.info(
            "Manual memory consolidation requested: session=%s archive_all=%s force=%s",
            session_key,
            archive_all,
            force,
        )
        try:
            triggered = await manual_consolidator.trigger_memory_consolidation(
                session_key,
                archive_all=archive_all,
                force=force,
            )
        except TimeoutError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        meta = store.get_session_meta(session_key) or {"key": session_key}
        meta["message_count"] = store.count_messages(session_key)
        logger.info(
            "Manual memory consolidation response: session=%s triggered=%s last_consolidated=%s message_count=%s",
            session_key,
            triggered,
            meta.get("last_consolidated"),
            meta.get("message_count"),
        )
        return {
            "session_key": session_key,
            "archive_all": archive_all,
            "force": force,
            "triggered": triggered,
            "session": meta,
        }

    async def _run_memory_optimizer() -> None:
        nonlocal optimizer_last_error, optimizer_last_status
        assert manual_memory_optimizer is not None
        optimizer_last_status = "running"
        optimizer_last_error = None
        try:
            await manual_memory_optimizer.optimize()
            optimizer_last_status = "succeeded"
        except MemoryOptimizerBusy:
            optimizer_last_status = "skipped"
            logger.info("manual memory optimizer skipped because it is already running")
        except asyncio.CancelledError:
            optimizer_last_status = "failed"
            optimizer_last_error = "memory optimizer 已取消"
            raise
        except Exception as exc:
            optimizer_last_status = "failed"
            optimizer_last_error = str(exc)
            logger.exception("manual memory optimizer failed: %s", exc)

    @app.get("/api/dashboard/memory/engine-info")
    def get_memory_engine_info() -> dict[str, Any]:
        desc = memory_admin.describe()
        return {"name": desc.name}

    @app.get("/api/dashboard/memory/optimizer")
    async def get_memory_optimizer_status() -> dict[str, Any]:
        running = bool(
            manual_memory_optimizer is not None
            and (
                (optimizer_task is not None and not optimizer_task.done())
                or manual_memory_optimizer.is_running
            )
        )
        return {
            "enabled": manual_memory_optimizer is not None,
            "running": running,
            "last_status": "running" if running else optimizer_last_status,
            "last_error": optimizer_last_error,
        }

    @app.post("/api/dashboard/memory/optimize", status_code=202)
    async def trigger_memory_optimizer() -> dict[str, Any]:
        nonlocal optimizer_last_error, optimizer_last_status, optimizer_task
        if manual_memory_optimizer is None:
            raise HTTPException(status_code=503, detail="memory optimizer 未启用")
        if (
            optimizer_task is not None and not optimizer_task.done()
        ) or manual_memory_optimizer.is_running:
            raise HTTPException(status_code=409, detail="memory optimizer 正在运行")
        logger.info("Manual memory optimizer triggered via dashboard")
        optimizer_last_status = "running"
        optimizer_last_error = None
        optimizer_task = asyncio.create_task(
            _run_memory_optimizer(),
            name="manual_memory_optimizer",
        )
        return {"status": "started", "message": "Memory optimizer started"}

    @app.post("/api/dashboard/sessions/batch-delete")
    def delete_sessions_batch(payload: SessionBatchDeletePayload) -> dict[str, Any]:
        try:
            deleted_count = store.delete_sessions_batch(
                payload.keys,
                cascade=payload.cascade,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"deleted_count": deleted_count}

    @app.get("/api/dashboard/sessions/{session_key:path}")
    def get_session(session_key: str) -> dict[str, Any]:
        meta = store.get_session_meta(session_key)
        if meta is None:
            raise HTTPException(status_code=404, detail="session 不存在")
        meta["message_count"] = store.count_messages(session_key)
        return meta

    @app.patch("/api/dashboard/sessions/{session_key:path}")
    def update_session(
        session_key: str,
        payload: SessionUpdatePayload,
    ) -> dict[str, Any]:
        meta = store.update_session(
            session_key,
            metadata=payload.metadata,
            last_consolidated=payload.last_consolidated,
            last_user_at=payload.last_user_at,
            last_proactive_at=payload.last_proactive_at,
        )
        if meta is None:
            raise HTTPException(status_code=404, detail="session 不存在")
        meta["message_count"] = store.count_messages(session_key)
        return meta

    @app.delete("/api/dashboard/sessions/{session_key:path}")
    def delete_session(
        session_key: str,
        cascade: bool = Query(default=True),
    ) -> dict[str, Any]:
        try:
            deleted = store.delete_session(session_key, cascade=cascade)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="session 不存在")
        return {"deleted": True, "session_key": session_key}

    @app.get("/api/dashboard/messages")
    def list_messages(
        session_key: str | None = None,
        q: str = "",
        role: str = "",
        page: int = 1,
        page_size: int = 25,
        sort_by: str = "ts",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        items, total = store.list_messages_for_dashboard(
            session_key=session_key,
            q=q,
            role=role,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.get("/api/dashboard/messages/{message_id:path}")
    def get_message(message_id: str) -> dict[str, Any]:
        message = store.get_message(message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="message 不存在")
        return message

    @app.patch("/api/dashboard/messages/{message_id:path}")
    def update_message(
        message_id: str,
        payload: MessageUpdatePayload,
    ) -> dict[str, Any]:
        message = store.update_message(
            message_id,
            role=payload.role,
            content=payload.content,
            tool_chain=payload.tool_chain,
            extra=payload.extra,
            ts=payload.ts,
        )
        if message is None:
            raise HTTPException(status_code=404, detail="message 不存在")
        return message

    @app.delete("/api/dashboard/messages/{message_id:path}")
    def delete_message(message_id: str) -> dict[str, Any]:
        deleted = store.delete_message(message_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="message 不存在")
        return {"deleted": True, "id": message_id}

    @app.post("/api/dashboard/messages/batch-delete")
    def delete_messages_batch(payload: MessageBatchDeletePayload) -> dict[str, Any]:
        deleted_count = store.delete_messages_batch(payload.ids)
        return {"deleted_count": deleted_count}

    @app.get("/api/dashboard/memories")
    def list_memories(
        q: str = "",
        memory_type: str = "",
        status: str = "",
        source_ref: str = "",
        scope_channel: str = "",
        scope_chat_id: str = "",
        has_embedding: bool | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        items, total = memory_admin.list_items_for_dashboard(
            q=q,
            memory_type=memory_type,
            status=status,
            source_ref=source_ref,
            scope_channel=scope_channel,
            scope_chat_id=scope_chat_id,
            has_embedding=has_embedding,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
            "vec_enabled": True,
            "vec_dim": 0,
        }

    @app.get("/api/dashboard/memories/{memory_id:path}/similar")
    def list_similar_memories(
        memory_id: str,
        top_k: int = 8,
        memory_type: str = "",
        score_threshold: float = 0.0,
        include_superseded: bool = False,
    ) -> dict[str, Any]:
        try:
            items = memory_admin.find_similar_items_for_dashboard(
                memory_id,
                top_k=top_k,
                memory_type=memory_type,
                score_threshold=score_threshold,
                include_superseded=include_superseded,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="memory 不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "items": items,
            "total": len(items),
            "source_id": memory_id,
        }

    @app.get("/api/dashboard/memories/{memory_id:path}")
    def get_memory(
        memory_id: str,
        include_embedding: bool = False,
    ) -> dict[str, Any]:
        item = memory_admin.get_item_for_dashboard(
            memory_id,
            include_embedding=include_embedding,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="memory 不存在")
        return item

    @app.patch("/api/dashboard/memories/{memory_id:path}")
    def update_memory(
        memory_id: str,
        payload: MemoryUpdatePayload,
    ) -> dict[str, Any]:
        try:
            item = memory_admin.update_item_for_dashboard(
                memory_id,
                status=payload.status,
                extra_json=payload.extra_json,
                source_ref=payload.source_ref,
                happened_at=payload.happened_at,
                emotional_weight=payload.emotional_weight,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if item is None:
            raise HTTPException(status_code=404, detail="memory 不存在")
        return item

    @app.delete("/api/dashboard/memories/{memory_id:path}")
    def delete_memory(memory_id: str) -> dict[str, Any]:
        deleted = memory_admin.delete_item(memory_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="memory 不存在")
        return {"deleted": True, "id": memory_id}

    @app.post("/api/dashboard/memories/batch-delete")
    def delete_memories_batch(payload: MemoryBatchDeletePayload) -> dict[str, Any]:
        deleted_count = memory_admin.delete_items_batch(payload.ids)
        return {"deleted_count": deleted_count}

    @app.get("/api/dashboard/proactive/overview")
    def get_proactive_overview() -> dict[str, Any]:
        return get_proactive_reader().get_overview()

    @app.get("/api/dashboard/proactive/deliveries")
    def list_proactive_deliveries(
        session_key: str = "",
        sent_from: str = "",
        sent_to: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        items, total = get_proactive_reader().list_deliveries(
            session_key=session_key,
            sent_from=sent_from,
            sent_to=sent_to,
            page=page,
            page_size=page_size,
        )
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.get("/api/dashboard/proactive/seen_items")
    def list_proactive_seen_items(
        source_key: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        items, total = get_proactive_reader().list_seen_items(
            source_key=source_key,
            page=page,
            page_size=page_size,
        )
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.get("/api/dashboard/proactive/rejection_cooldown")
    def list_proactive_rejection_cooldown(
        source_key: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        items, total = get_proactive_reader().list_rejection_cooldown(
            source_key=source_key,
            page=page,
            page_size=page_size,
        )
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.get("/api/dashboard/proactive/semantic_items")
    def list_proactive_semantic_items(
        page: int = 1,
        page_size: int = 50,
        window_hours: int = 168,
    ) -> dict[str, Any]:
        items, total = get_proactive_reader().list_semantic_items(
            page=page,
            page_size=page_size,
            window_hours=window_hours,
        )
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
            "window_hours": max(1, window_hours),
        }

    @app.get("/api/dashboard/proactive/tick_logs")
    def list_proactive_tick_logs(
        session_key: str = "",
        terminal_action: str = "",
        gate_exit: str = "",
        flow: str = Query(default="", pattern="^(|drift|proactive)$"),
        started_from: str = "",
        started_to: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "started_at",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        items, total = get_proactive_reader().list_tick_logs(
            session_key=session_key,
            terminal_action=terminal_action,
            gate_exit=gate_exit,
            flow=flow,
            started_from=started_from,
            started_to=started_to,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return {
            "items": items,
            "total": total,
            "page": max(1, page),
            "page_size": max(1, min(page_size, 200)),
        }

    @app.get("/api/dashboard/proactive/tick_logs/{tick_id}")
    def get_proactive_tick_log(tick_id: str) -> dict[str, Any]:
        item = get_proactive_reader().get_tick_log(tick_id)
        if item is None:
            raise HTTPException(status_code=404, detail="tick 不存在")
        return item

    @app.get("/api/dashboard/proactive/tick_logs/{tick_id}/steps")
    def list_proactive_tick_steps(tick_id: str) -> dict[str, Any]:
        item = get_proactive_reader().get_tick_log(tick_id)
        if item is None:
            raise HTTPException(status_code=404, detail="tick 不存在")
        steps = get_proactive_reader().list_tick_steps(tick_id)
        return {
            "items": steps,
            "total": len(steps),
            "tick_id": tick_id,
        }

    @app.delete("/api/dashboard/proactive/seen_items/batch")
    def delete_proactive_seen_items(payload: ProactiveDeletePayload) -> dict[str, Any]:
        try:
            deleted_count = get_proactive_reader().delete_seen_items(
                source_key=str(payload.source_key or "").strip(),
                item_ids=payload.item_ids,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"deleted_count": deleted_count}

    @app.delete("/api/dashboard/proactive/rejection_cooldown/batch")
    def delete_proactive_rejection_cooldown(
        payload: ProactiveDeletePayload,
    ) -> dict[str, Any]:
        try:
            deleted_count = get_proactive_reader().delete_rejection_cooldown(
                source_key=str(payload.source_key or "").strip(),
                item_ids=payload.item_ids,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"deleted_count": deleted_count}

    return app


def run_dashboard_api(
    *,
    workspace: Path,
    host: str = "0.0.0.0",
    port: int = 2236,
    manual_consolidator: ManualConsolidator | None = None,
    manual_memory_optimizer: ManualMemoryOptimizer | None = None,
    memory_admin: MemoryAdminApi,
    memory_store: MemoryStore | None = None,
    message_bus: MessageBus | None = None,
    event_bus: EventBus | None = None,
    biomed_revision_provider: Any | None = None,
    biomed_revision_model: str = "",
) -> None:
    server = uvicorn.Server(
        _build_dashboard_uvicorn_config(
            workspace=workspace,
            host=host,
            port=port,
            manual_consolidator=manual_consolidator,
            manual_memory_optimizer=manual_memory_optimizer,
            memory_admin=memory_admin,
            memory_store=memory_store,
            message_bus=message_bus,
            event_bus=event_bus,
            biomed_revision_provider=biomed_revision_provider,
            biomed_revision_model=biomed_revision_model,
        )
    )
    server.run()


def _build_dashboard_uvicorn_config(
    *,
    workspace: Path,
    host: str,
    port: int,
    manual_consolidator: ManualConsolidator | None,
    manual_memory_optimizer: ManualMemoryOptimizer | None = None,
    memory_admin: MemoryAdminApi,
    memory_store: MemoryStore | None = None,
    message_bus: MessageBus | None = None,
    event_bus: EventBus | None = None,
    tool_registry: Any | None = None,
    tool_hooks: list[Any] | None = None,
    biomed_revision_provider: Any | None = None,
    biomed_revision_model: str = "",
) -> uvicorn.Config:
    config = uvicorn.Config(
        create_dashboard_app(
            workspace,
            manual_consolidator=manual_consolidator,
            manual_memory_optimizer=manual_memory_optimizer,
            memory_admin=memory_admin,
            memory_store=memory_store,
            message_bus=message_bus,
            event_bus=event_bus,
            tool_registry=tool_registry,
            tool_hooks=tool_hooks,
            biomed_revision_provider=biomed_revision_provider,
            biomed_revision_model=biomed_revision_model,
        ),
        host=host,
        port=port,
        log_level="info",
    )
    _install_dashboard_access_log_filter()
    return config


def build_dashboard_server(
    *,
    workspace: Path,
    host: str = "0.0.0.0",
    port: int = 2236,
    manual_consolidator: ManualConsolidator | None = None,
    manual_memory_optimizer: ManualMemoryOptimizer | None = None,
    memory_admin: MemoryAdminApi,
    memory_store: MemoryStore | None = None,
    message_bus: MessageBus | None = None,
    event_bus: EventBus | None = None,
    tool_registry: Any | None = None,
    tool_hooks: list[Any] | None = None,
    biomed_revision_provider: Any | None = None,
    biomed_revision_model: str = "",
) -> uvicorn.Server:
    config = _build_dashboard_uvicorn_config(
        workspace=workspace,
        host=host,
        port=port,
        manual_consolidator=manual_consolidator,
        manual_memory_optimizer=manual_memory_optimizer,
        memory_admin=memory_admin,
        memory_store=memory_store,
        message_bus=message_bus,
        event_bus=event_bus,
        tool_registry=tool_registry,
        tool_hooks=tool_hooks,
        biomed_revision_provider=biomed_revision_provider,
        biomed_revision_model=biomed_revision_model,
    )
    return uvicorn.Server(config)
