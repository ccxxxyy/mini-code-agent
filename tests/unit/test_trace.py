"""Tests for the trace renderer. Trace 渲染器的测试。"""

import pytest
from rich.console import Console

from mini_agent.events.bus import EventBus
from mini_agent.models.events import (
    AgentPhaseChangeEvent,
    LLMRequestEvent,
    LLMResponseEvent,
    PermissionCheckEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    TurnCompleteEvent,
)
from mini_agent.ui.trace import TraceRenderer

pytestmark = pytest.mark.asyncio


def make_renderer() -> tuple[TraceRenderer, Console, EventBus]:
    console = Console(record=True, width=120)
    renderer = TraceRenderer(console)
    bus = EventBus()
    renderer.attach(bus)
    return renderer, console, bus


async def test_disabled_by_default():
    renderer, console, bus = make_renderer()
    assert renderer.enabled is False
    await bus.emit(AgentPhaseChangeEvent(old_phase="idle", new_phase="thinking", iteration=1))
    assert console.export_text().strip() == ""


async def test_phase_change_rendered():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    await bus.emit(
        AgentPhaseChangeEvent(old_phase="thinking", new_phase="tool_calling", iteration=2)
    )
    out = console.export_text()
    assert "trace" in out
    assert "thinking" in out
    assert "tool_calling" in out


async def test_permission_granted_rendered():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    await bus.emit(
        PermissionCheckEvent(
            tool_name="bash",
            scope="command",
            resource="git status",
            decision="granted",
            reason="mode:ask",
        )
    )
    out = console.export_text()
    assert "GRANTED" in out
    assert "git status" in out
    assert "mode:ask" in out


async def test_permission_denied_rendered():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    await bus.emit(
        PermissionCheckEvent(
            tool_name="read_file",
            scope="path",
            resource="~/.ssh/id_rsa",
            decision="denied",
            reason="path_guard:sensitive",
        )
    )
    out = console.export_text()
    assert "DENIED" in out
    assert "path_guard:sensitive" in out


async def test_tool_lifecycle_rendered():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    await bus.emit(
        ToolCallStartEvent(tool_name="read_file", arguments={"file_path": "a.py"}, call_id="c1")
    )
    await bus.emit(
        ToolCallEndEvent(tool_name="read_file", call_id="c1", is_error=False, duration_ms=42.5)
    )
    out = console.export_text()
    assert "read_file" in out
    assert "start" in out
    assert "done" in out
    assert "OK" in out
    assert "42" in out  # 耗时


async def test_tool_error_rendered():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    await bus.emit(ToolCallEndEvent(tool_name="bash", call_id="c1", is_error=True, duration_ms=10))
    assert "FAIL" in console.export_text()


async def test_llm_events_rendered():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    await bus.emit(LLMRequestEvent(message_count=5, tool_count=6))
    await bus.emit(LLMResponseEvent(content="hi", has_tool_calls=True, tokens_used=812))
    out = console.export_text()
    assert "5 msgs" in out
    assert "6 tools" in out
    assert "812 tokens" in out
    assert "tool_calls=true" in out


async def test_turn_complete_rendered():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    await bus.emit(TurnCompleteEvent(iteration_count=3, tools_called=2, tokens_used=2140))
    out = console.export_text()
    assert "complete" in out
    assert "3 iterations" in out
    assert "2140 tokens" in out


async def test_detach_stops_rendering():
    renderer, console, bus = make_renderer()
    renderer.enabled = True
    renderer.detach(bus)
    await bus.emit(TurnCompleteEvent(iteration_count=1, tools_called=0, tokens_used=100))
    assert console.export_text().strip() == ""
