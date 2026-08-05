"""Compliance audit logger -- tamper-evident JSONL via hash chaining.
合规审计日志——通过哈希链实现防篡改的 JSONL。

Each record carries hash = sha256(prev_hash + canonical_record). Editing or
deleting any line breaks every hash after it, so integrity is verifiable.
每条记录携带 hash = sha256(前条哈希 + 规范化记录)。篡改或删除任何一行都会
破坏其后所有哈希，完整性可验证。"""

from __future__ import annotations

import asyncio
import hashlib
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

GENESIS_HASH = "0" * 64


def _record_hash(prev_hash: str, record: dict) -> str:
    """Hash of a record chained to its predecessor. 与前条链接的记录哈希。"""
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def verify_chain(log_path: Path) -> tuple[bool, int, str]:
    """Replay the log and verify the hash chain.
    重放日志并校验哈希链。

    Returns (ok, verified_count, error_detail).
    """
    if not log_path.is_file():
        return True, 0, ""
    prev_hash = GENESIS_HASH
    count = 0
    for lineno, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return False, count, f"line {lineno}: invalid JSON"
        stored_hash = entry.pop("hash", None)
        stored_prev = entry.pop("prev_hash", None)
        if stored_prev != prev_hash:
            return False, count, f"line {lineno}: broken chain (prev_hash mismatch)"
        if _record_hash(prev_hash, entry) != stored_hash:
            return False, count, f"line {lineno}: content tampered (hash mismatch)"
        prev_hash = stored_hash
        count += 1
    return True, count, ""


class AuditLogger:
    """EventBus subscriber that writes audit trail to a JSONL file.
    订阅 EventBus 事件并写入 JSONL 审计日志的订阅者。"""

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        self._log_path = log_dir / "audit.jsonl"
        self._state_path = log_dir / ".audit_on"
        # Audit state persists across restarts: on stays on until /audit off
        # 审计状态跨重启持久：开启后一直生效，直到显式关闭
        self.enabled: bool = self._state_path.is_file()
        self._entry_count: int = 0
        self._last_hash: str | None = None  # lazy: read from file on first write 首写时从文件恢复
        # Protects hash chain integrity under parallel tool execution
        # 在并行工具执行时保护哈希链完整性
        self._write_lock = asyncio.Lock()

    def set_enabled(self, value: bool) -> None:
        """Toggle audit and persist the state to disk. 切换审计并持久化状态。"""
        self.enabled = value
        self._log_dir.mkdir(parents=True, exist_ok=True)
        if value:
            self._state_path.touch()
        elif self._state_path.is_file():
            self._state_path.unlink()

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
        async with self._write_lock:
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
        async with self._write_lock:
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
        async with self._write_lock:
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
        prev = self._resume_last_hash()
        record_hash = _record_hash(prev, record)
        chained = {**record, "prev_hash": prev, "hash": record_hash}
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(chained, ensure_ascii=False) + "\n")
        self._last_hash = record_hash
        self._entry_count += 1

    def _resume_last_hash(self) -> str:
        """Resume the chain from the existing log file (once per process).
        从已有日志文件恢复链尾哈希（每进程一次）。"""
        if self._last_hash is not None:
            return self._last_hash
        self._last_hash = GENESIS_HASH
        if self._log_path.is_file():
            for line in reversed(self._log_path.read_text(encoding="utf-8").splitlines()):
                if line.strip():
                    try:
                        self._last_hash = json.loads(line).get("hash", GENESIS_HASH)
                    except json.JSONDecodeError:
                        pass
                    break
        return self._last_hash
