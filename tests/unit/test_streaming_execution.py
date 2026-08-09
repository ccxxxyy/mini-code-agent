"""Tests for streaming tool execution (P38).
流式工具执行的测试。"""

import asyncio
import json
from pathlib import Path

import pytest

from mini_agent.core.agent_loop import AgentLoop, IncrementalAssembler
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import StreamChunk, ToolCallDelta
from mini_agent.models.config import AgentConfig, SecurityConfig, ToolConfig
from mini_agent.models.message import Conversation
from mini_agent.models.session import Session
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin import ReadFileTool
from tests.unit.test_agent_loop import MockLLM, text_response, tool_call_response

pytestmark = pytest.mark.asyncio


def tcd(index, id=None, name=None, args=""):
    return ToolCallDelta(index=index, id=id, name=name, arguments_delta=args)


# --- IncrementalAssembler ---


async def test_assembler_single_call_completes_on_finish():
    a = IncrementalAssembler()
    assert a.feed(StreamChunk(tool_call_deltas=[tcd(0, "c1", "read_file", '{"file_')])) == []
    assert a.feed(StreamChunk(tool_call_deltas=[tcd(0, args='path": "a.txt"}')])) == []
    done = a.feed(StreamChunk(finish_reason="tool_calls"))
    assert len(done) == 1
    assert done[0].id == "c1"
    assert done[0].arguments == {"file_path": "a.txt"}


async def test_assembler_index_advance_flushes_previous():
    a = IncrementalAssembler()
    a.feed(StreamChunk(tool_call_deltas=[tcd(0, "c1", "glob", '{"pattern": "*.py"}')]))
    # index 1 opens -> index 0 is complete
    done = a.feed(StreamChunk(tool_call_deltas=[tcd(1, "c2", "grep", '{"pat')]))
    assert len(done) == 1
    assert done[0].id == "c1"
    assert done[0].arguments == {"pattern": "*.py"}
    # finish flushes index 1 (only once for index 0)
    done = a.feed(
        StreamChunk(tool_call_deltas=[tcd(1, args='tern": "x"}')], finish_reason="tool_calls")
    )
    assert len(done) == 1
    assert done[0].id == "c2"


async def test_assembler_multi_index_single_chunk():
    a = IncrementalAssembler()
    done = a.feed(
        StreamChunk(
            tool_call_deltas=[
                tcd(0, "c1", "glob", '{"pattern": "*.py"}'),
                tcd(1, "c2", "grep", '{"pattern": "TODO"}'),
            ],
            finish_reason="tool_calls",
        )
    )
    assert [d.id for d in done] == ["c1", "c2"]


# --- would_ask peek ---


def make_pm(tmp_path, mode="ask"):
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    guard = PathGuard(
        tool_config=ToolConfig(), security_config=SecurityConfig(), project_dir=project
    )
    pm = PermissionManager(
        config=SecurityConfig(permission_mode=mode), path_guard=guard, confirm_callback=None
    )
    return pm, project


async def test_would_ask_dangerous_command(tmp_path):
    pm, _ = make_pm(tmp_path)
    assert pm.would_ask("bash", {"command": "git push origin main"})
    assert pm.would_ask("bash", {"command": "rm -rf ./build"})
    assert not pm.would_ask("bash", {"command": "echo hello"})
    assert not pm.would_ask("bash", {"command": "git status"})


async def test_would_ask_paths(tmp_path):
    pm, project = make_pm(tmp_path)
    assert not pm.would_ask("read_file", {"file_path": str(project / "a.py")})
    outside = tmp_path / "outside" / "b.txt"
    assert pm.would_ask("read_file", {"file_path": str(outside)})
    # Sensitive path resolves to DENY without prompting 敏感路径直接 DENY 不弹窗
    assert not pm.would_ask("read_file", {"file_path": str(Path.home() / ".ssh" / "id_rsa")})


async def test_would_ask_unrestricted_tool(tmp_path):
    pm, _ = make_pm(tmp_path)
    assert not pm.would_ask("spawn_agents", {"tasks": ["x"]})


async def test_would_ask_session_grant_resolves(tmp_path):
    from mini_agent.models.permissions import PermissionScope

    pm, _ = make_pm(tmp_path)
    assert pm.would_ask("bash", {"command": "git push origin main"})
    pm.grant_session_permission(PermissionScope.COMMAND, "git push origin main")
    assert not pm.would_ask("bash", {"command": "git push origin main"})


# --- Integration: tools start before stream ends ---


async def test_streaming_tool_starts_before_stream_end(tmp_path):
    """Tool #1 must start executing while the stream is still delivering."""
    work = tmp_path / "work"
    work.mkdir()
    f1 = work / "a.txt"
    f1.write_text("data1", encoding="utf-8")
    f2 = work / "b.txt"
    f2.write_text("data2", encoding="utf-8")

    started_during_stream = []

    class TwoPhaseStreamLLM(MockLLM):
        """Yields tool #1, then checks if it started, then yields tool #2."""

        def __init__(self, scripts, loop_ref):
            super().__init__(scripts)
            self.loop_ref = loop_ref

        async def stream(self, messages, tools=None, **kwargs):
            if self._call_count == 0:
                self._call_count += 1
                # Tool call 0 complete (index advance signal via chunk split)
                yield StreamChunk(
                    tool_call_deltas=[tcd(0, "c1", "read_file", json.dumps({"file_path": str(f1)}))]
                )
                # Opening index 1 flushes index 0 -> task submitted
                yield StreamChunk(
                    tool_call_deltas=[tcd(1, "c2", "read_file", json.dumps({"file_path": str(f2)}))]
                )
                # Give the event loop a tick so the submitted task can start
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                started_during_stream.append(len(self.loop_ref[0]._streaming_tasks))
                yield StreamChunk(finish_reason="tool_calls")
            else:
                for c in text_response("done"):
                    yield c

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    ctx = ToolContext(
        working_dir=work, session=Session(), event_bus=EventBus(), config=AgentConfig()
    )
    loop_ref: list = [None]
    llm = TwoPhaseStreamLLM([], loop_ref)
    loop = AgentLoop(
        llm=llm,
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(),
        tool_context=ctx,
    )
    loop_ref[0] = loop

    conv = Conversation()
    result = await loop.run(conv)

    # At least tool c1 was submitted mid-stream 至少 c1 在流式期间已提交
    assert started_during_stream and started_during_stream[0] >= 1
    assert result == "done"
    tool_msgs = [m for m in conv.messages if m.tool_result]
    assert len(tool_msgs) == 2
    # Result order preserved 结果顺序保持
    assert tool_msgs[0].tool_result.call_id == "c1"
    assert tool_msgs[1].tool_result.call_id == "c2"


async def test_streaming_disabled_falls_back(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    f = work / "x.txt"
    f.write_text("data", encoding="utf-8")

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    config = AgentConfig(streaming_tool_execution=False)
    ctx = ToolContext(working_dir=work, session=Session(), event_bus=EventBus(), config=config)
    loop = AgentLoop(
        llm=MockLLM([tool_call_response("read_file", {"file_path": str(f)}), text_response("ok")]),
        tool_registry=registry,
        event_bus=EventBus(),
        config=config,
        tool_context=ctx,
    )
    conv = Conversation()
    result = await loop.run(conv)
    assert result == "ok"
    assert loop._streaming_tasks == {}


async def test_ask_tool_deferred_not_streamed(tmp_path):
    """A dangerous bash command must NOT execute during streaming."""
    work = tmp_path / "proj"
    work.mkdir()

    guard = PathGuard(tool_config=ToolConfig(), security_config=SecurityConfig(), project_dir=work)
    asked = []

    async def confirm(prompt):
        asked.append(prompt)
        return False  # deny

    pm = PermissionManager(
        config=SecurityConfig(permission_mode="ask"), path_guard=guard, confirm_callback=confirm
    )

    from mini_agent.tools.builtin import BashTool

    registry = ToolRegistry()
    registry.register(BashTool())
    config = AgentConfig()
    ctx = ToolContext(working_dir=work, session=Session(), event_bus=EventBus(), config=config)
    loop = AgentLoop(
        llm=MockLLM(
            [
                tool_call_response("bash", {"command": "git push origin main"}),
                text_response("done"),
            ]
        ),
        tool_registry=registry,
        event_bus=EventBus(),
        config=config,
        tool_context=ctx,
        permission_manager=pm,
    )
    conv = Conversation()
    await loop.run(conv)

    # Confirmation happened in _act (post-stream), user denied -> error result
    # 确认发生在 _act（流结束后），用户拒绝 -> 错误结果
    assert len(asked) == 1
    tool_msgs = [m for m in conv.messages if m.tool_result]
    assert tool_msgs[0].tool_result.is_error
    assert "denied" in tool_msgs[0].tool_result.output.lower()
