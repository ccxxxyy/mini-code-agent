"""Tests for the SyntheticOutput structured output tool (B17).
SyntheticOutput 结构化输出工具测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mini_agent.core.subagent import SubAgentResult, _extract_structured_output
from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig
from mini_agent.models.message import Conversation, Message, Role, ToolCall
from mini_agent.models.permissions import ToolCategory
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext
from mini_agent.tools.builtin.synthetic_output import SyntheticOutputTool

pytestmark = pytest.mark.asyncio


# --- tool basics ---


def test_category_is_read():
    tool = SyntheticOutputTool()
    assert tool.category is ToolCategory.READ


def test_schema_accepts_arbitrary_keys():
    tool = SyntheticOutputTool()
    schema = tool.schema.to_json_schema()
    params = schema["function"]["parameters"]
    assert params["type"] == "object"
    assert params.get("additionalProperties") is True


async def test_execute_returns_json(tmp_path: Path):
    tool = SyntheticOutputTool()
    ctx = ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
    )
    result = await tool.execute(ctx, passed=True, failures=[], score=0.95)
    assert not result.is_error
    data = json.loads(result.output)
    assert data == {"passed": True, "failures": [], "score": 0.95}


async def test_execute_empty_args(tmp_path: Path):
    tool = SyntheticOutputTool()
    ctx = ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
    )
    result = await tool.execute(ctx)
    assert json.loads(result.output) == {}


async def test_execute_nested_structure(tmp_path: Path):
    tool = SyntheticOutputTool()
    ctx = ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
    )
    result = await tool.execute(
        ctx, verdict={"pass": False, "failures": [{"file": "a.py", "line": 10}]}
    )
    data = json.loads(result.output)
    assert data["verdict"]["pass"] is False
    assert len(data["verdict"]["failures"]) == 1


# --- _extract_structured_output ---


def test_extract_from_conversation():
    conv = Conversation(system_prompt="test")
    conv.append(Message(role=Role.USER, content="verify this"))
    conv.append(
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(id="c1", name="read_file", arguments={"file_path": "x.py"}),
            ],
        )
    )
    conv.append(
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    id="c2",
                    name="synthetic_output",
                    arguments={"pass": True, "score": 1.0},
                ),
            ],
        )
    )
    conv.append(Message(role=Role.ASSISTANT, content="PASS"))
    result = _extract_structured_output(conv)
    assert result == {"pass": True, "score": 1.0}


def test_extract_takes_last_call():
    conv = Conversation(system_prompt="test")
    conv.append(
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(id="c1", name="synthetic_output", arguments={"pass": False}),
            ],
        )
    )
    conv.append(
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(id="c2", name="synthetic_output", arguments={"pass": True}),
            ],
        )
    )
    result = _extract_structured_output(conv)
    assert result == {"pass": True}


def test_extract_returns_none_when_absent():
    conv = Conversation(system_prompt="test")
    conv.append(Message(role=Role.USER, content="hello"))
    conv.append(Message(role=Role.ASSISTANT, content="hi"))
    assert _extract_structured_output(conv) is None


# --- SubAgentResult.structured_output ---


def test_result_default_none():
    r = SubAgentResult(agent_id="a1", task="test", success=True, output="done")
    assert r.structured_output is None


def test_result_with_structured():
    data = {"pass": True, "failures": []}
    r = SubAgentResult(
        agent_id="a1",
        task="test",
        success=True,
        output="PASS",
        structured_output=data,
    )
    assert r.structured_output == data


# --- format functions ---


def test_format_agent_result_includes_structured():
    from mini_agent.extensions.builtin_commands import _format_agent_result

    r = SubAgentResult(
        agent_id="a1",
        task="verify X",
        success=True,
        output="PASS",
        structured_output={"pass": True, "details": "all good"},
    )
    formatted = _format_agent_result(r)
    assert "```json" in formatted
    assert '"pass": true' in formatted
    assert '"details": "all good"' in formatted


def test_format_agent_result_no_structured():
    from mini_agent.extensions.builtin_commands import _format_agent_result

    r = SubAgentResult(
        agent_id="a1",
        task="do something",
        success=True,
        output="done",
    )
    formatted = _format_agent_result(r)
    assert "```json" not in formatted
    assert "done" in formatted
