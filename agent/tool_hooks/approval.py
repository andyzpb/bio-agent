from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from agent.tool_hooks.types import HookTraceItem, ToolExecutionRequest

ApprovalStatus = Literal["pending", "approved", "rejected", "expired", "missing"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _empty_pre_trace() -> list[HookTraceItem]:
    return []


@dataclass
class PendingToolApproval:
    approval_id: str
    request: ToolExecutionRequest
    final_arguments: dict[str, Any]
    reason: str
    risk: str
    output: Any
    pre_hook_trace: list[HookTraceItem] = field(default_factory=_empty_pre_trace)
    created_at: datetime = field(default_factory=_utcnow)
    expires_at: datetime | None = None
    resolved_at: datetime | None = None
    status: ApprovalStatus = "pending"

    def public_payload(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "status": self.status,
            "session_key": self.request.session_key,
            "channel": self.request.channel,
            "chat_id": self.request.chat_id,
            "call_id": self.request.call_id,
            "tool_name": self.request.tool_name,
            "arguments": dict(self.request.arguments),
            "final_arguments": dict(self.final_arguments),
            "reason": self.reason,
            "risk": self.risk,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass(frozen=True)
class ApprovalResolution:
    approval_id: str
    status: ApprovalStatus
    approval: PendingToolApproval | None = None
    message: str = ""


class ToolApprovalBroker:
    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        self._ttl = max(1.0, float(ttl_seconds))
        self._pending: dict[str, PendingToolApproval] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiters: dict[str, asyncio.Future[ApprovalStatus]] = {}
        self._lock = asyncio.Lock()

    async def submit(
        self,
        *,
        approval_id: str,
        request: ToolExecutionRequest,
        final_arguments: dict[str, Any],
        reason: str,
        risk: str,
        output: Any,
        pre_hook_trace: list[HookTraceItem],
    ) -> PendingToolApproval:
        now = _utcnow()
        approval = PendingToolApproval(
            approval_id=approval_id,
            request=request,
            final_arguments=dict(final_arguments),
            reason=reason,
            risk=risk,
            output=output,
            pre_hook_trace=list(pre_hook_trace),
            created_at=now,
            expires_at=now + timedelta(seconds=self._ttl),
        )
        async with self._lock:
            self._expire_locked(now)
            existing = self._pending.get(approval_id)
            if existing is not None and existing.status == "pending":
                return existing
            self._pending[approval_id] = approval
            self._locks.setdefault(approval_id, asyncio.Lock())
            self._waiters.setdefault(
                approval_id,
                asyncio.get_running_loop().create_future(),
            )
            return approval

    async def wait_for_resolution(self, approval_id: str) -> ApprovalResolution:
        async with self._lock:
            approval = self._pending.get(approval_id)
            if approval is None:
                return ApprovalResolution(
                    approval_id=approval_id,
                    status="missing",
                    message="approval not found",
                )
            waiter = self._waiters.setdefault(
                approval_id,
                asyncio.get_running_loop().create_future(),
            )
            timeout = self._ttl
            if approval.expires_at is not None:
                timeout = max(0.0, (approval.expires_at - _utcnow()).total_seconds())
        try:
            status = await asyncio.wait_for(waiter, timeout=timeout)
        except asyncio.TimeoutError:
            await self._expire_one(approval_id)
            status = "expired"
        async with self._lock:
            resolved = approval
            if resolved.status == "pending":
                resolved.status = status
                resolved.resolved_at = _utcnow()
            if resolved.status != "pending":
                self._pending.pop(approval_id, None)
                self._locks.pop(approval_id, None)
                self._waiters.pop(approval_id, None)
        return ApprovalResolution(
            approval_id=approval_id,
            status=status,
            approval=resolved,
        )

    async def list_pending(
        self,
        *,
        session_key: str = "",
    ) -> list[PendingToolApproval]:
        async with self._lock:
            self._expire_locked(_utcnow())
            approvals = [
                item
                for item in self._pending.values()
                if item.status == "pending"
                and (not session_key or item.request.session_key == session_key)
            ]
        return sorted(approvals, key=lambda item: item.created_at)

    async def approve(self, approval_id: str) -> ApprovalResolution:
        return await self._resolve(approval_id, "approved")

    async def reject(self, approval_id: str) -> ApprovalResolution:
        return await self._resolve(approval_id, "rejected")

    async def _resolve(
        self,
        approval_id: str,
        status: Literal["approved", "rejected"],
    ) -> ApprovalResolution:
        lock = await self._approval_lock(approval_id)
        async with lock:
            async with self._lock:
                self._expire_locked(_utcnow())
                approval = self._pending.get(approval_id)
                if approval is None:
                    return ApprovalResolution(
                        approval_id=approval_id,
                        status="missing",
                        message="approval not found",
                    )
                if approval.status != "pending":
                    return ApprovalResolution(
                        approval_id=approval_id,
                        status=approval.status,
                        approval=approval,
                        message=f"approval already {approval.status}",
                    )
                approval.status = status
                approval.resolved_at = _utcnow()
                waiter = self._waiters.get(approval_id)
                if waiter is not None and not waiter.done():
                    waiter.set_result(status)
                return ApprovalResolution(
                    approval_id=approval_id,
                    status=status,
                    approval=approval,
                )

    async def _approval_lock(self, approval_id: str) -> asyncio.Lock:
        async with self._lock:
            return self._locks.setdefault(approval_id, asyncio.Lock())

    def _expire_locked(self, now: datetime) -> None:
        expired: list[str] = []
        for approval_id, approval in self._pending.items():
            if approval.expires_at is not None and approval.expires_at <= now:
                approval.status = "expired"
                approval.resolved_at = now
                expired.append(approval_id)
        for approval_id in expired:
            self._pending.pop(approval_id, None)
            self._locks.pop(approval_id, None)
            waiter = self._waiters.pop(approval_id, None)
            if waiter is not None and not waiter.done():
                waiter.set_result("expired")

    async def _expire_one(self, approval_id: str) -> None:
        async with self._lock:
            approval = self._pending.get(approval_id)
            if approval is None or approval.status != "pending":
                return
            now = _utcnow()
            approval.status = "expired"
            approval.resolved_at = now
            self._pending.pop(approval_id, None)
            self._locks.pop(approval_id, None)
            waiter = self._waiters.pop(approval_id, None)
            if waiter is not None and not waiter.done():
                waiter.set_result("expired")
