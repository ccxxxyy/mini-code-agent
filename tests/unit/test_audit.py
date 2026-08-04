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
from mini_agent.security.audit import GENESIS_HASH, AuditLogger, verify_chain

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


# --- Hash chain 哈希链 ---


async def emit_n(bus: EventBus, n: int) -> None:
    for i in range(n):
        await bus.emit(ToolCallStartEvent(tool_name=f"t{i}", arguments={"i": i}, call_id=f"c{i}"))


async def test_records_carry_hash_chain(tmp_path: Path):
    logger, bus = make_logger(tmp_path)
    logger.enabled = True
    await emit_n(bus, 3)
    lines = [json.loads(x) for x in logger.log_path.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["prev_hash"] == GENESIS_HASH
    assert lines[1]["prev_hash"] == lines[0]["hash"]
    assert lines[2]["prev_hash"] == lines[1]["hash"]


async def test_verify_chain_intact(tmp_path: Path):
    logger, bus = make_logger(tmp_path)
    logger.enabled = True
    await emit_n(bus, 5)
    ok, count, detail = verify_chain(logger.log_path)
    assert ok
    assert count == 5
    assert detail == ""


async def test_verify_detects_content_tampering(tmp_path: Path):
    logger, bus = make_logger(tmp_path)
    logger.enabled = True
    await emit_n(bus, 3)
    # Tamper with line 2's content 篡改第 2 行内容
    lines = logger.log_path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[1])
    entry["tool"] = "hacked"
    lines[1] = json.dumps(entry, ensure_ascii=False)
    logger.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, count, detail = verify_chain(logger.log_path)
    assert not ok
    assert "line 2" in detail


async def test_verify_detects_deleted_line(tmp_path: Path):
    logger, bus = make_logger(tmp_path)
    logger.enabled = True
    await emit_n(bus, 3)
    lines = logger.log_path.read_text(encoding="utf-8").splitlines()
    del lines[1]  # delete the middle record 删除中间一条
    logger.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, count, detail = verify_chain(logger.log_path)
    assert not ok
    assert "broken chain" in detail


async def test_chain_resumes_across_logger_instances(tmp_path: Path):
    # Simulate restart: a new AuditLogger appends to the same file
    # 模拟重启：新的 AuditLogger 追加到同一个文件
    logger1, bus1 = make_logger(tmp_path)
    logger1.enabled = True
    await emit_n(bus1, 2)

    logger2 = AuditLogger(tmp_path)
    bus2 = EventBus()
    logger2.attach(bus2)
    logger2.enabled = True
    await bus2.emit(ToolCallStartEvent(tool_name="after", arguments={}, call_id="c9"))

    ok, count, _ = verify_chain(logger1.log_path)
    assert ok
    assert count == 3


async def test_verify_empty_or_missing_file(tmp_path: Path):
    ok, count, detail = verify_chain(tmp_path / "nonexistent.jsonl")
    assert ok
    assert count == 0


# --- Persistent enabled state 持久化开关状态 ---


async def test_enabled_persists_across_restart(tmp_path: Path):
    logger1 = AuditLogger(tmp_path)
    logger1.set_enabled(True)
    # Simulate restart: new instance reads persisted state 模拟重启：新实例读取持久状态
    logger2 = AuditLogger(tmp_path)
    assert logger2.enabled is True


async def test_disabled_persists_across_restart(tmp_path: Path):
    logger1 = AuditLogger(tmp_path)
    logger1.set_enabled(True)
    logger1.set_enabled(False)
    logger2 = AuditLogger(tmp_path)
    assert logger2.enabled is False


async def test_fresh_dir_defaults_off(tmp_path: Path):
    logger = AuditLogger(tmp_path / "new")
    assert logger.enabled is False
