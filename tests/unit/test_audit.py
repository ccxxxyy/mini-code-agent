"""Tests for AuditLogger. 合规审计日志测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mini_agent.events.bus import EventBus
from mini_agent.models.events import (
    PermissionCheckEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from mini_agent.security.audit import AuditLogger

pytestmark = pytest.mark.asyncio


def make_logger(tmp_path: Path) -> tuple[AuditLogger, EventBus]:
    logger = AuditLogger(tmp_path)
    bus = EventBus()
    logger.attach(bus)
    return logger, bus


async def test_disabled_by_default(tmp_path: Path):
    logger, _ = make_logger(tmp_path)
    assert logger.enabled is False


async def test_disabled_no_write(tmp_path: Path):
    logger, bus = make_logger(tmp_path)
    await bus.emit(ToolCallStartEvent(tool_name="bash", arguments={"command": "ls"}, call_id="c1"))
    assert not logger.log_path.exists()
    assert logger.entry_count == 0


async def test_writes_tool_start_event(tmp_path: Path):
    logger, bus = make_logger(tmp_path)
    logger.enabled = True
    await bus.emit(
        ToolCallStartEvent(tool_name="read_file", arguments={"path": "a.py"}, call_id="c2")
    )
    assert logger.log_path.exists()
    lines = logger.log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "tool_start"
    assert record["tool"] == "read_file"
    assert record["args"] == {"path": "a.py"}
    assert "ts" in record


async def test_writes_tool_end_event(tmp_path: Path):
    logger, bus = make_logger(tmp_path)
    logger.enabled = True
    await bus.emit(ToolCallEndEvent(tool_name="bash", call_id="c3", duration_ms=42, is_error=False))
    lines = logger.log_path.read_text(encoding="utf-8").strip().split("\n")
    record = json.loads(lines[0])
    assert record["event"] == "tool_end"
    assert record["duration_ms"] == 42
    assert record["is_error"] is False


async def test_writes_permission_event(tmp_path: Path):
    logger, bus = make_logger(tmp_path)
    logger.enabled = True
    await bus.emit(
        PermissionCheckEvent(
            tool_name="bash",
            scope="command",
            resource="git status",
            decision="granted",
            reason="mode:ask",
        )
    )
    lines = logger.log_path.read_text(encoding="utf-8").strip().split("\n")
    record = json.loads(lines[0])
    assert record["event"] == "permission"
    assert record["decision"] == "granted"
    assert record["reason"] == "mode:ask"


async def test_entry_count_increments(tmp_path: Path):
    logger, bus = make_logger(tmp_path)
    logger.enabled = True
    await bus.emit(ToolCallStartEvent(tool_name="a", arguments={}, call_id="c4"))
    await bus.emit(ToolCallEndEvent(tool_name="a", call_id="c4", duration_ms=1, is_error=False))
    assert logger.entry_count == 2


async def test_detach_stops_writing(tmp_path: Path):
    logger, bus = make_logger(tmp_path)
    logger.enabled = True
    await bus.emit(ToolCallStartEvent(tool_name="a", arguments={}, call_id="c5"))
    assert logger.entry_count == 1
    logger.detach(bus)
    await bus.emit(ToolCallStartEvent(tool_name="b", arguments={}, call_id="c6"))
    assert logger.entry_count == 1
