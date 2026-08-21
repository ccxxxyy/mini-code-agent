"""Tests for read-before-edit enforcement.
编辑前必读强制机制测试。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext
from mini_agent.tools.builtin.edit_file import EditFileTool
from mini_agent.tools.builtin.read_file import ReadFileTool
from mini_agent.tools.builtin.write_file import WriteFileTool
from mini_agent.tools.file_state_cache import FileStateCache

pytestmark = pytest.mark.asyncio


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
        file_state=FileStateCache(),
    )


# --- FileStateCache unit ---


def test_check_unread_file_fails(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hi", encoding="utf-8")
    cache = FileStateCache()
    ok, err = cache.check(f)
    assert not ok
    assert "has not been read" in err


def test_check_after_record_ok(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hi", encoding="utf-8")
    cache = FileStateCache()
    cache.record(f)
    ok, err = cache.check(f)
    assert ok
    assert err == ""


def test_check_stale_after_external_change(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hi", encoding="utf-8")
    cache = FileStateCache()
    cache.record(f)
    # simulate external modification with a distinct mtime
    time.sleep(0.01)
    os.utime(f, ns=(time.time_ns(), time.time_ns()))
    f.write_text("changed externally", encoding="utf-8")
    ok, err = cache.check(f)
    assert not ok
    assert "modified since" in err


# --- edit_file gate ---


async def test_edit_requires_read_first(tmp_path):
    f = tmp_path / "e.txt"
    f.write_text("original", encoding="utf-8")
    ctx = _ctx(tmp_path)
    tool = EditFileTool()
    result = await tool.execute(ctx, file_path=str(f), old_text="original", new_text="changed")
    assert result.is_error
    assert "has not been read" in result.output
    # file unchanged 文件未被修改
    assert f.read_text(encoding="utf-8") == "original"


async def test_edit_succeeds_after_read(tmp_path):
    f = tmp_path / "e.txt"
    f.write_text("original", encoding="utf-8")
    ctx = _ctx(tmp_path)

    await ReadFileTool().execute(ctx, file_path=str(f))
    result = await EditFileTool().execute(
        ctx, file_path=str(f), old_text="original", new_text="changed"
    )
    assert not result.is_error
    assert f.read_text(encoding="utf-8") == "changed"


async def test_edit_then_edit_again_ok(tmp_path):
    """After an edit, the cache is refreshed so a second edit passes.
    编辑后缓存刷新，第二次编辑无需重读。"""
    f = tmp_path / "e.txt"
    f.write_text("a", encoding="utf-8")
    ctx = _ctx(tmp_path)

    await ReadFileTool().execute(ctx, file_path=str(f))
    await EditFileTool().execute(ctx, file_path=str(f), old_text="a", new_text="b")
    result = await EditFileTool().execute(ctx, file_path=str(f), old_text="b", new_text="c")
    assert not result.is_error
    assert f.read_text(encoding="utf-8") == "c"


# --- write_file gate ---


async def test_write_new_file_no_read_needed(tmp_path):
    """Creating a new file is exempt from read-before-edit.
    新建文件豁免编辑前必读。"""
    f = tmp_path / "new.txt"
    ctx = _ctx(tmp_path)
    result = await WriteFileTool().execute(ctx, file_path=str(f), content="hello")
    assert not result.is_error
    assert f.read_text(encoding="utf-8") == "hello"


async def test_write_overwrite_requires_read(tmp_path):
    """Overwriting an existing file requires having read it first.
    覆盖已存在文件须先读。"""
    f = tmp_path / "exists.txt"
    f.write_text("old", encoding="utf-8")
    ctx = _ctx(tmp_path)
    result = await WriteFileTool().execute(ctx, file_path=str(f), content="new")
    assert result.is_error
    assert "has not been read" in result.output
    assert f.read_text(encoding="utf-8") == "old"


async def test_write_overwrite_ok_after_read(tmp_path):
    f = tmp_path / "exists.txt"
    f.write_text("old", encoding="utf-8")
    ctx = _ctx(tmp_path)
    await ReadFileTool().execute(ctx, file_path=str(f))
    result = await WriteFileTool().execute(ctx, file_path=str(f), content="new")
    assert not result.is_error
    assert f.read_text(encoding="utf-8") == "new"


async def test_no_file_state_disables_gate(tmp_path):
    """When file_state is None (not wired), edit works without read.
    file_state 为 None 时门禁失效，编辑无需先读（向后兼容）。"""
    ctx = ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
        file_state=None,
    )
    f = tmp_path / "e.txt"
    f.write_text("x", encoding="utf-8")
    result = await EditFileTool().execute(ctx, file_path=str(f), old_text="x", new_text="y")
    assert not result.is_error


# --- enforce_read_before_edit config wiring  配置接线 ---


def test_config_default_enforce_on():
    """The gate defaults to on. 门禁默认开启。"""
    from mini_agent.models.config import ToolConfig

    assert ToolConfig().enforce_read_before_edit is True


async def test_app_wiring_default_on(tmp_path, monkeypatch):
    """Default config wires a FileStateCache into the main tool context.
    默认配置下主 Agent 的 ToolContext 持有 FileStateCache。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    app = Application(ConfigLoader.load())
    assert isinstance(app._tool_context.file_state, FileStateCache)


async def test_app_wiring_off_disables_gate(tmp_path, monkeypatch):
    """enforce_read_before_edit=False → file_state is None → edit needs no read.
    配置关闭 → file_state 为 None → 编辑无需先读。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    config = ConfigLoader.load()
    config.tools.enforce_read_before_edit = False
    app = Application(config)
    assert app._tool_context.file_state is None

    f = tmp_path / "e.txt"
    f.write_text("x", encoding="utf-8")
    result = await EditFileTool().execute(
        app._tool_context, file_path=str(f), old_text="x", new_text="y"
    )
    assert not result.is_error
    assert f.read_text(encoding="utf-8") == "y"


async def test_subagent_wiring_default_on(tmp_path):
    """Each sub-agent gets its own FileStateCache by default.
    默认配置下每个 SubAgent 持有自己的 FileStateCache。"""
    from mini_agent.core.subagent import SubAgent
    from mini_agent.tools.base import ToolRegistry

    agent = SubAgent(
        task="t",
        llm=None,
        tool_registry=ToolRegistry(),
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    assert isinstance(agent._loop._tool_context.file_state, FileStateCache)


async def test_subagent_wiring_off(tmp_path):
    """Config off propagates to sub-agents: no gate.
    配置关闭传导到 SubAgent：无门禁。"""
    from mini_agent.core.subagent import SubAgent
    from mini_agent.tools.base import ToolRegistry

    config = AgentConfig()
    config.tools.enforce_read_before_edit = False
    agent = SubAgent(
        task="t",
        llm=None,
        tool_registry=ToolRegistry(),
        config=config,
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    assert agent._loop._tool_context.file_state is None
