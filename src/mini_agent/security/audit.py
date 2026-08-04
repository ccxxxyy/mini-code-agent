"""Compliance audit logger -- writes tool calls and permission decisions to JSONL.
合规审计日志——将工具调用和权限判定写入 JSONL 文件。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from mini_agent.models.events import (
    PermissionCheckEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)

if TYPE_CHECKING:
    from mini_agent.events.bus import EventBus


class AuditLogger:
    """EventBus subscriber that writes audit trail to a JSONL file.
    订阅 EventBus 事件并写入 JSONL 审计日志的订阅者。"""

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        self._log_path = log_dir / "audit.jsonl"
        self.enabled: bool = False
        self._entry_count: int = 0

    @property
    def log_path(self) -> Path:
        return self._log_path

    @property
    def entry_count(self) -> int:
        return self._entry_count

    def attach(self, bus: EventBus) -> None:
        bus.on(ToolCallStartEvent, self._on_tool_start)
        bus.on(ToolCallEndEvent, self._on_tool_end)
        bus.on(PermissionCheckEvent, self._on_permission)

    def detach(self, bus: EventBus) -> None:
        bus.off(ToolCallStartEvent, self._on_tool_start)
        bus.off(ToolCallEndEvent, self._on_tool_end)
        bus.off(PermissionCheckEvent, self._on_permission)

    async def _on_tool_start(self, event: ToolCallStartEvent) -> None:
        if not self.enabled:
            return
        self._write(
            {
                "ts": event.timestamp.isoformat(timespec="milliseconds"),
                "event": "tool_start",
                "tool": event.tool_name,
                "call_id": event.call_id,
                "args": event.arguments,
            }
        )

    async def _on_tool_end(self, event: ToolCallEndEvent) -> None:
        if not self.enabled:
            return
        self._write(
            {
                "ts": event.timestamp.isoformat(timespec="milliseconds"),
                "event": "tool_end",
                "tool": event.tool_name,
                "call_id": event.call_id,
                "duration_ms": event.duration_ms,
                "is_error": event.is_error,
            }
        )

    async def _on_permission(self, event: PermissionCheckEvent) -> None:
        if not self.enabled:
            return
        self._write(
            {
                "ts": event.timestamp.isoformat(timespec="milliseconds"),
                "event": "permission",
                "tool": event.tool_name,
                "scope": event.scope,
                "resource": event.resource,
                "decision": event.decision,
                "reason": event.reason,
            }
        )

    def _write(self, record: dict) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._entry_count += 1
