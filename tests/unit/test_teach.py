"""Tests for TeachRenderer. 教学模式渲染器测试。"""

from __future__ import annotations

import pytest
from rich.console import Console

from mini_agent.events.bus import EventBus
from mini_agent.models.events import ToolCallStartEvent, TurnCompleteEvent
from mini_agent.ui.teach import TeachRenderer

pytestmark = pytest.mark.asyncio


def make_renderer() -> tuple[TeachRenderer, Console, EventBus]:
    console = Console(record=True, width=120)
    renderer = TeachRenderer(console)
    bus = EventBus()
    renderer.attach(bus)
    return renderer, console, bus


async def test_disabled_by_default():
    renderer, console, bus = make_renderer()
    assert renderer.enabled is False
    await bus.emit(ToolCallStartEvent(tool_name="bash", arguments={"command": "ls"}, call_id="c1"))
    assert console.export_text().strip() == ""


async def test_tool_start_shows_teach_panel():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    await bus.emit(
        ToolCallStartEvent(tool_name="read_file", arguments={"file_path": "a.py"}, call_id="c1")
    )
    out = console.export_text()
    assert "Why this tool" in out
    assert "read_file" in out
    assert "file_path=a.py" in out


async def test_unknown_tool_uses_default():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    await bus.emit(ToolCallStartEvent(tool_name="mcp_custom", arguments={"x": 1}, call_id="c2"))
    out = console.export_text()
    assert "Why this tool" in out
    assert "mcp_custom" in out


async def test_turn_complete_shows_count():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    await bus.emit(ToolCallStartEvent(tool_name="glob", arguments={}, call_id="c3"))
    await bus.emit(ToolCallStartEvent(tool_name="grep", arguments={}, call_id="c4"))
    await bus.emit(TurnCompleteEvent(iteration_count=1, tools_called=2, tokens_used=100))
    out = console.export_text()
    assert "2 tool(s) explained" in out


async def test_detach_stops_rendering():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    await bus.emit(ToolCallStartEvent(tool_name="bash", arguments={}, call_id="c5"))
    assert "bash" in console.export_text()
    renderer.detach(bus)
    await bus.emit(ToolCallStartEvent(tool_name="glob", arguments={}, call_id="c6"))
    assert "glob" not in console.export_text().split("bash")[-1]
