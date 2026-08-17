"""Tests for extension point wiring (#4/#12/#13 from P76, #2/#6/#11/#14 from P77).
扩展点接入的测试（P76: #4/#12/#13, P77: #2/#6/#11/#14）。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mini_agent.events.bus import EventBus
from mini_agent.models.config import SecurityConfig, ToolConfig
from mini_agent.models.events import LLMRequestEvent, UserMessageEvent
from mini_agent.security.audit import AuditLogger
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager
from mini_agent.ui.trace import TraceRenderer

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════
# P76: #4 ProviderRegistry.list_providers() in /model
# ═══════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════
# P76: #12 UserMessageEvent.is_slash_command
# ═══════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════
# P76: #13 LLMRequestEvent.estimated_tokens
# ═══════════════════════════════════════════════════════════════


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


# --- #2 ToolRegistry.filter() in team.py ---


async def test_team_non_writer_uses_registry_filter(tmp_path):
    """Non-writer steps are filtered via ToolRegistry.filter(denied=...)."""
    from mini_agent.tools.base import ToolRegistry
    from mini_agent.tools.builtin import EditFileTool, ReadFileTool, WriteFileTool

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())

    filtered = registry.filter(denied=["write_file", "edit_file"])
    names = {t.schema.name for t in filtered}
    assert "read_file" in names
    assert "write_file" not in names
    assert "edit_file" not in names


async def test_registry_filter_allowed_and_denied():
    """filter() with both allowed and denied narrows correctly."""
    from mini_agent.tools.base import ToolRegistry
    from mini_agent.tools.builtin import EditFileTool, GlobTool, ReadFileTool, WriteFileTool

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(GlobTool())

    filtered = registry.filter(
        allowed=["read_file", "write_file", "glob"],
        denied=["write_file"],
    )
    names = {t.schema.name for t in filtered}
    assert names == {"read_file", "glob"}


# --- #6 Plan.is_complete in team.py ---


async def test_plan_is_complete_governs_team_loop():
    """Plan.is_complete transitions from False to True as steps complete."""
    from mini_agent.core.planner import Plan, PlanStep

    plan = Plan(
        task="test",
        steps=[
            PlanStep(index=0, description="step 0"),
            PlanStep(index=1, description="step 1"),
        ],
    )
    assert not plan.is_complete

    plan.steps[0].status = "completed"
    assert not plan.is_complete

    plan.steps[1].status = "failed"
    assert plan.is_complete


async def test_team_uses_plan_is_complete(tmp_path):
    """AgentTeam.start() terminates when plan.is_complete becomes True."""
    from collections.abc import AsyncIterator
    from typing import Any

    from mini_agent.core.planner import Planner
    from mini_agent.core.subagent import SubAgentManager
    from mini_agent.core.team import AgentTeam, TeamConfig, TeamMember
    from mini_agent.events.bus import EventBus
    from mini_agent.llm.base import LLMProvider, StreamChunk
    from mini_agent.models.config import AgentConfig
    from mini_agent.tools.base import ToolRegistry
    from mini_agent.tools.builtin import ReadFileTool

    class MockLLM(LLMProvider):
        def __init__(self):
            self._calls = 0

        async def stream(self, messages, tools=None, **kw: Any) -> AsyncIterator[StreamChunk]:
            self._calls += 1
            text = '[{"description":"a"},{"description":"b"}]' if self._calls == 1 else "done"
            yield StreamChunk(delta=text)
            yield StreamChunk(finish_reason="stop")

        def count_tokens(self, text: str) -> int:
            return len(text) // 4

        @property
        def context_window(self) -> int:
            return 128_000

    llm = MockLLM()
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    manager = SubAgentManager(
        llm=llm,
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    team = AgentTeam(
        config=TeamConfig(name="t", members=[TeamMember(name="w", role="dev")]),
        planner=Planner(llm),
        subagent_manager=manager,
    )
    report = await team.start("task")
    assert report.plan.is_complete
    assert all(s.status in ("completed", "failed") for s in report.plan.steps)


# --- #11 SessionMetadata.tags ---


def test_session_tags_default_empty():
    from mini_agent.models.session import SessionMetadata

    meta = SessionMetadata()
    assert meta.tags == []


def test_session_tags_append_and_remove():
    from mini_agent.models.session import SessionMetadata

    meta = SessionMetadata()
    meta.tags.append("debug")
    meta.tags.append("refactor")
    assert meta.tags == ["debug", "refactor"]
    meta.tags.remove("debug")
    assert meta.tags == ["refactor"]


async def test_session_tags_serialization(tmp_path):
    """Tags survive save/load round-trip."""
    from mini_agent.memory.session_store import SessionStore
    from mini_agent.models.session import Session

    store = SessionStore(tmp_path / "sessions")
    session = Session()
    session.metadata.tags = ["bug-fix", "urgent"]
    await store.save(session)

    loaded = await store.load(session.metadata.session_id)
    assert loaded is not None
    assert loaded.metadata.tags == ["bug-fix", "urgent"]


async def test_session_list_includes_tags(tmp_path):
    """list_sessions() returns tags for filtering."""
    from mini_agent.memory.session_store import SessionStore
    from mini_agent.models.session import Session

    store = SessionStore(tmp_path / "sessions")
    s1 = Session()
    s1.metadata.tags = ["feature"]
    await store.save(s1)

    sessions = await store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["tags"] == ["feature"]


# --- #14 PermissionRequest.tool_name ---


async def test_check_path_passes_tool_name(tmp_path):
    """check_path() propagates tool_name to the PermissionRequest."""
    from mini_agent.models.permissions import PermissionRequest

    captured: list[PermissionRequest] = []
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    guard = PathGuard(
        tool_config=ToolConfig(),
        security_config=SecurityConfig(),
        project_dir=project_dir,
    )

    original_rules = PermissionManager._check_rules_only

    async def spy_rules(self, request):
        captured.append(request)
        return await original_rules(self, request)

    pm = PermissionManager(
        config=SecurityConfig(permission_mode="allow"),
        path_guard=guard,
    )
    pm._check_rules_only = lambda req: spy_rules(pm, req)

    outside_path = tmp_path / "outside" / "data.txt"
    await pm.check_path(outside_path, "read", tool_name="read_file")

    assert len(captured) == 1
    assert captured[0].tool_name == "read_file"


async def test_check_command_sets_tool_name_bash():
    """check_command() always sets tool_name='bash'."""
    from mini_agent.models.permissions import PermissionRequest

    guard = PathGuard(
        tool_config=ToolConfig(),
        security_config=SecurityConfig(),
        project_dir=Path("/tmp/test"),
    )
    pm = PermissionManager(
        config=SecurityConfig(permission_mode="allow"),
        path_guard=guard,
    )

    captured: list[PermissionRequest] = []
    original = pm._check_rules_only

    async def spy(request):
        captured.append(request)
        return await original(request)

    pm._check_rules_only = spy
    await pm.check_command("ls -la")
    assert len(captured) == 1
    assert captured[0].tool_name == "bash"
