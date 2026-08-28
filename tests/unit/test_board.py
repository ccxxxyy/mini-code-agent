"""Tests for the SubAgent progress board. SubAgent 进度面板测试。"""

from __future__ import annotations

import asyncio

import pytest
from rich.console import Console

from mini_agent.core.subagent import SubAgentManager
from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig
from mini_agent.tools.base import ToolRegistry
from mini_agent.ui.board import SubAgentBoard
from tests.mocks import MockLLM

pytestmark = pytest.mark.asyncio


def make_manager(tmp_path, delay=0.0) -> SubAgentManager:
    return SubAgentManager(
        llm=MockLLM(delay=delay),
        tool_registry=ToolRegistry(),
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )


# --- active_snapshots ---


async def test_snapshot_empty(tmp_path):
    mgr = make_manager(tmp_path)
    assert mgr.active_snapshots() == []


async def test_snapshot_fields(tmp_path):
    mgr = make_manager(tmp_path, delay=1.0)
    aid = await mgr.spawn("analyze the codebase")
    await asyncio.sleep(0.05)
    snaps = mgr.active_snapshots()
    assert len(snaps) == 1
    s = snaps[0]
    assert s.agent_id == aid
    assert s.task == "analyze the codebase"
    assert s.phase  # some phase string
    assert s.tool_calls >= 0
    assert s.elapsed_seconds > 0
    mgr.cancel_all()


# --- SubAgentBoard.run_while ---


def make_board(tmp_path, delay=0.0) -> tuple[SubAgentBoard, SubAgentManager, Console]:
    console = Console(record=True, width=100, force_terminal=False)
    mgr = make_manager(tmp_path, delay=delay)
    return SubAgentBoard(console, mgr), mgr, console


async def test_run_while_returns_result(tmp_path):
    board, mgr, _ = make_board(tmp_path)

    async def work() -> str:
        await asyncio.sleep(0.05)
        return "the result"

    result = await board.run_while(work())
    assert result == "the result"


async def test_run_while_wraps_agent_wait(tmp_path):
    board, mgr, console = make_board(tmp_path, delay=0.4)
    aid = await mgr.spawn("read the readme file for me")
    result = await board.run_while(mgr.wait(aid, timeout=5))
    assert result.success


async def test_run_while_propagates_exception(tmp_path):
    board, mgr, _ = make_board(tmp_path)

    async def boom():
        await asyncio.sleep(0.05)
        raise ValueError("expected failure")

    with pytest.raises(ValueError, match="expected failure"):
        await board.run_while(boom())


async def test_render_contains_agent_info(tmp_path):
    board, mgr, console = make_board(tmp_path, delay=1.0)
    aid = await mgr.spawn("summarize project architecture")
    await asyncio.sleep(0.05)
    table = board._render()
    console.print(table)
    out = console.export_text()
    assert aid in out
    assert "summarize project" in out
    mgr.cancel_all()


async def test_render_empty_shows_collecting(tmp_path):
    board, mgr, console = make_board(tmp_path)
    console.print(board._render())
    assert "collecting results" in console.export_text()
