"""Tests for per-turn file change tracking. 每轮文件变更跟踪测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.agent_loop import AgentLoop
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk
from mini_agent.models.config import AgentConfig
from mini_agent.models.message import ToolCall
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin.delete_file import DeleteFileTool
from mini_agent.tools.builtin.edit_file import EditFileTool
from mini_agent.tools.builtin.write_file import WriteFileTool

pytestmark = pytest.mark.asyncio


class MockLLM(LLMProvider):
    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="done")
        yield StreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


def make_loop(tmp_path) -> AgentLoop:
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(DeleteFileTool())
    ctx = ToolContext(
        working_dir=tmp_path, session=Session(), event_bus=EventBus(), config=AgentConfig()
    )
    return AgentLoop(
        llm=MockLLM(),
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(),
        tool_context=ctx,
    )


def tc(name: str, args: dict) -> ToolCall:
    return ToolCall(id=name, name=name, arguments=args)


async def test_file_changes_tracked_write_new(tmp_path):
    loop = make_loop(tmp_path)
    path = str(tmp_path / "new.txt")
    await loop._act([tc("write_file", {"file_path": path, "content": "hi"})])

    assert loop._file_changes == {path: "created"}


async def test_file_changes_tracked_edit(tmp_path):
    f = tmp_path / "exist.txt"
    f.write_text("hello", encoding="utf-8")
    loop = make_loop(tmp_path)
    await loop._act([tc("edit_file", {"file_path": str(f), "old_text": "hello", "new_text": "x"})])

    assert loop._file_changes == {str(f): "modified"}


async def test_file_changes_dedup_created_sticks(tmp_path):
    loop = make_loop(tmp_path)
    path = str(tmp_path / "a.txt")
    await loop._act([tc("write_file", {"file_path": path, "content": "hello"})])
    await loop._act([tc("edit_file", {"file_path": path, "old_text": "hello", "new_text": "y"})])

    # create-then-edit still counts as created 先建后改仍算新建
    assert loop._file_changes == {path: "created"}


async def test_file_changes_reset_per_turn(tmp_path):
    loop = make_loop(tmp_path)
    path = str(tmp_path / "b.txt")
    from mini_agent.models.message import Conversation, Message, Role

    conv = Conversation(system_prompt="t")
    conv.append(Message(role=Role.USER, content="hi"))
    await loop._act([tc("write_file", {"file_path": path, "content": "x"})])
    assert loop._file_changes

    # run() resets per-turn state run() 重置每轮状态
    await loop.run(conv)
    assert loop._file_changes == {}
    assert loop.last_turn_file_changes == []


async def test_file_changes_error_not_tracked(tmp_path):
    loop = make_loop(tmp_path)
    missing = str(tmp_path / "missing.txt")
    await loop._act([tc("edit_file", {"file_path": missing, "old_text": "a", "new_text": "b"})])

    assert loop._file_changes == {}


async def test_write_existing_counts_as_modified(tmp_path):
    f = tmp_path / "over.txt"
    f.write_text("old", encoding="utf-8")
    loop = make_loop(tmp_path)
    await loop._act([tc("write_file", {"file_path": str(f), "content": "new"})])

    assert loop._file_changes == {str(f): "modified"}


# --- delete_file ---


async def test_delete_file_tracked(tmp_path):
    f = tmp_path / "doomed.txt"
    f.write_text("bye", encoding="utf-8")
    loop = make_loop(tmp_path)
    await loop._act([tc("delete_file", {"file_path": str(f)})])

    assert not f.exists()
    assert loop._file_changes == {str(f): "deleted"}


async def test_delete_wins_over_created(tmp_path):
    loop = make_loop(tmp_path)
    path = str(tmp_path / "temp.txt")
    await loop._act([tc("write_file", {"file_path": path, "content": "x"})])
    await loop._act([tc("delete_file", {"file_path": path})])

    # delete overrides created 删除覆盖新建
    assert loop._file_changes == {path: "deleted"}


async def test_delete_missing_file_error(tmp_path):
    loop = make_loop(tmp_path)
    results = await loop._act([tc("delete_file", {"file_path": str(tmp_path / "nope.txt")})])

    assert results[0].is_error
    assert loop._file_changes == {}


async def test_delete_directory_refused(tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    loop = make_loop(tmp_path)
    results = await loop._act([tc("delete_file", {"file_path": str(sub)})])

    assert results[0].is_error
    assert "directory" in results[0].output
    assert sub.exists()
