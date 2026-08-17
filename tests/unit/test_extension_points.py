"""Tests for three extension points (#4, #12, #13).
三个扩展点的接入测试。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mini_agent.events.bus import EventBus
from mini_agent.models.events import LLMRequestEvent, UserMessageEvent
from mini_agent.security.audit import AuditLogger
from mini_agent.ui.trace import TraceRenderer

pytestmark = pytest.mark.asyncio


# --- #4: ProviderRegistry.list_providers() in /model ---


async def test_model_command_shows_providers():
    """No-arg /model should include provider names from list_providers()."""
    from mini_agent.llm.registry import ProviderRegistry

    providers = ProviderRegistry.list_providers()
    assert "openai" in providers
    assert "anthropic" in providers


async def test_model_command_handler_output_contains_providers():
    """The /model handler with no args should output available providers."""
    from mini_agent.extensions.builtin_commands import _make_model

    app = MagicMock()
    app.config.llm.model = "test-model"
    app.config.llm.provider = "openai"
    app.config.llm_profiles = {}

    handler = _make_model(app)
    result = await handler("", None)
    assert "openai" in result
    assert "anthropic" in result
    assert "openai-responses" in result


# --- #12: UserMessageEvent.is_slash_command ---


async def test_user_message_event_slash_command_field():
    """UserMessageEvent should carry is_slash_command correctly."""
    e1 = UserMessageEvent(content="/help", is_slash_command=True)
    assert e1.is_slash_command is True

    e2 = UserMessageEvent(content="hello")
    assert e2.is_slash_command is False


async def test_audit_logger_records_user_message(tmp_path: Path):
    """AuditLogger should record UserMessageEvent with is_slash_command."""
    logger = AuditLogger(tmp_path)
    bus = EventBus()
    logger.attach(bus)
    logger.enabled = True

    await bus.emit(UserMessageEvent(content="/help", is_slash_command=True))
    assert logger.log_path.exists()
    lines = logger.log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "user_message"
    assert record["is_slash_command"] is True
    assert "/help" in record["content"]


async def test_audit_logger_records_normal_message(tmp_path: Path):
    """AuditLogger should record normal user messages with is_slash_command=False."""
    logger = AuditLogger(tmp_path)
    bus = EventBus()
    logger.attach(bus)
    logger.enabled = True

    await bus.emit(UserMessageEvent(content="hello world", is_slash_command=False))
    lines = logger.log_path.read_text(encoding="utf-8").strip().split("\n")
    record = json.loads(lines[0])
    assert record["event"] == "user_message"
    assert record["is_slash_command"] is False


async def test_audit_logger_truncates_long_content(tmp_path: Path):
    """AuditLogger should truncate user message content to 200 chars."""
    logger = AuditLogger(tmp_path)
    bus = EventBus()
    logger.attach(bus)
    logger.enabled = True

    long_msg = "x" * 500
    await bus.emit(UserMessageEvent(content=long_msg))
    lines = logger.log_path.read_text(encoding="utf-8").strip().split("\n")
    record = json.loads(lines[0])
    assert len(record["content"]) == 200


async def test_trace_renders_user_message():
    """TraceRenderer should render user messages with slash tag."""
    from rich.console import Console

    console = Console(record=True, width=120)
    renderer = TraceRenderer(console)
    bus = EventBus()
    renderer.attach(bus)
    renderer.enabled = True

    await bus.emit(UserMessageEvent(content="/help", is_slash_command=True))
    out = console.export_text()
    assert "user" in out
    assert "/help" in out
    assert "[slash]" in out


async def test_trace_renders_normal_user_message():
    """TraceRenderer should render normal user messages without slash tag."""
    from rich.console import Console

    console = Console(record=True, width=120)
    renderer = TraceRenderer(console)
    bus = EventBus()
    renderer.attach(bus)
    renderer.enabled = True

    await bus.emit(UserMessageEvent(content="hello world"))
    out = console.export_text()
    assert "user" in out
    assert "hello world" in out
    assert "[slash]" not in out


# --- #13: LLMRequestEvent.estimated_tokens ---


async def test_llm_request_event_estimated_tokens():
    """LLMRequestEvent should carry estimated_tokens."""
    e = LLMRequestEvent(message_count=5, tool_count=3, estimated_tokens=12000)
    assert e.estimated_tokens == 12000


async def test_trace_renders_estimated_tokens():
    """TraceRenderer should show estimated_tokens in LLM request line."""
    from rich.console import Console

    console = Console(record=True, width=120)
    renderer = TraceRenderer(console)
    bus = EventBus()
    renderer.attach(bus)
    renderer.enabled = True

    await bus.emit(LLMRequestEvent(message_count=5, tool_count=3, estimated_tokens=12345))
    out = console.export_text()
    assert "5 msgs" in out
    assert "3 tools" in out
    assert "~12345 tok" in out


async def test_trace_hides_zero_estimated_tokens():
    """TraceRenderer should not show token count when estimated_tokens is 0."""
    from rich.console import Console

    console = Console(record=True, width=120)
    renderer = TraceRenderer(console)
    bus = EventBus()
    renderer.attach(bus)
    renderer.enabled = True

    await bus.emit(LLMRequestEvent(message_count=3, tool_count=2, estimated_tokens=0))
    out = console.export_text()
    assert "3 msgs" in out
    assert "tok" not in out
