"""Tests for SubAgent dispatch with mock LLM. 使用 mock LLM 测试 SubAgent 调度。"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.agent_types import get_agent_type
from mini_agent.core.subagent import SubAgent, SubAgentManager
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk, ToolCallDelta
from mini_agent.models.config import AgentConfig
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.builtin import ReadFileTool, WriteFileTool

pytestmark = pytest.mark.asyncio


class MockLLM(LLMProvider):
    """Replays a fixed script for every sub-agent. 为每个 SubAgent 重放固定脚本。"""

    def __init__(self, scripts: list[list[StreamChunk]], delay: float = 0.0):
        self._scripts = scripts
        self._delay = delay
        self._call_count = 0

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        if self._delay:
            await asyncio.sleep(self._delay)
        script = self._scripts[min(self._call_count, len(self._scripts) - 1)]
        self._call_count += 1
        for chunk in script:
            yield chunk

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


def text_response(text: str) -> list[StreamChunk]:
    return [StreamChunk(delta=text), StreamChunk(finish_reason="stop")]


def tool_call_response(name: str, args: dict) -> list[StreamChunk]:
    return [
        StreamChunk(
            tool_call_deltas=[
                ToolCallDelta(index=0, id="c1", name=name, arguments_delta=json.dumps(args))
            ]
        ),
        StreamChunk(finish_reason="tool_calls"),
    ]


def make_manager(scripts, tmp_path, delay=0.0):
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    return SubAgentManager(
        llm=MockLLM(scripts, delay=delay),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )


async def test_subagent_completes_task(tmp_path):
    mgr = make_manager([text_response("Task done: created the file")], tmp_path)
    agent_id = await mgr.spawn("do something simple")
    result = await mgr.wait(agent_id)

    assert result.success
    assert "Task done" in result.output
    assert result.agent_id == agent_id


async def test_subagent_uses_tools(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("hello", encoding="utf-8")

    scripts = [
        tool_call_response("read_file", {"file_path": str(f)}),
        text_response("File contains: hello"),
    ]
    mgr = make_manager(scripts, tmp_path)
    agent_id = await mgr.spawn("read the data file")
    result = await mgr.wait(agent_id)

    assert result.success
    assert result.tool_calls_made == 1


async def test_spawn_parallel(tmp_path):
    mgr = make_manager([text_response("done")], tmp_path, delay=0.05)
    ids = await mgr.spawn_parallel(["task 1", "task 2", "task 3"])
    assert len(ids) == 3
    assert len(mgr.list_active()) == 3

    results = await mgr.wait_all(ids)
    assert len(results) == 3
    assert all(r.success for r in results)
    assert len(mgr.list_active()) == 0


async def test_parallel_faster_than_serial(tmp_path):
    """3 agents with 0.1s LLM delay should finish in ~0.1s, not ~0.3s.
    3 个带 0.1 秒 LLM 延迟的 Agent 应在约 0.1 秒内完成，而不是约 0.3 秒。"""
    import time

    mgr = make_manager([text_response("ok")], tmp_path, delay=0.1)
    start = time.monotonic()
    ids = await mgr.spawn_parallel(["a", "b", "c"])
    await mgr.wait_all(ids)
    elapsed = time.monotonic() - start

    # parallel: ~0.1s; serial would be ~0.3s+ 并行约 0.1 秒；串行则需约 0.3 秒以上
    assert elapsed < 0.35


async def test_wait_unknown_agent(tmp_path):
    mgr = make_manager([text_response("x")], tmp_path)
    result = await mgr.wait("nonexistent")
    assert not result.success
    assert "Unknown agent" in result.error


async def test_timeout(tmp_path):
    mgr = make_manager([text_response("slow")], tmp_path, delay=5.0)
    agent_id = await mgr.spawn("slow task")
    result = await mgr.wait(agent_id, timeout=0.2)
    assert not result.success
    assert "Timed out" in result.error


async def test_allowed_tools_filter(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())

    agent = SubAgent(
        task="test",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        allowed_tools=["read_file"],
    )
    # The sub-agent's internal registry should only have read_file
    # SubAgent 的内部注册表应只包含 read_file
    assert agent._loop._tools.get("read_file") is not None
    assert agent._loop._tools.get("write_file") is None


async def test_subagent_isolated_registry(tmp_path):
    """Sub-agent's registry is a clone -- modifications don't affect parent.
    SubAgent 的注册表是克隆的——修改不会影响父级。"""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())

    SubAgent(
        task="t",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        allowed_tools=["read_file"],
    )
    # Parent registry untouched 父级注册表未受影响
    assert registry.get("write_file") is not None


# --- Agent type integration (P48) ---


async def test_subagent_with_explore_type(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())

    agent = SubAgent(
        task="explore the codebase",
        llm=MockLLM([text_response("found it")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        agent_type=get_agent_type("explore"),
    )
    assert agent._loop._tools.get("read_file") is not None
    assert agent._loop._tools.get("write_file") is None
    assert "read-only" in agent._conversation.system_prompt.lower()


async def test_subagent_type_intersects_with_caller_tools(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())

    agent = SubAgent(
        task="test",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        allowed_tools=["read_file"],
        agent_type=get_agent_type("explore"),
    )
    assert agent._loop._tools.get("read_file") is not None
    assert agent._loop._tools.get("glob") is None


async def test_subagent_type_overrides_max_iterations(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    agent = SubAgent(
        task="verify something",
        llm=MockLLM([text_response("PASS")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        agent_type=get_agent_type("verify"),
    )
    assert "20" in agent._conversation.system_prompt


async def test_spawn_parallel_with_agent_type(tmp_path):
    mgr = make_manager([text_response("found it")], tmp_path)
    ids = await mgr.spawn_parallel(["search A", "search B"], agent_type="explore")
    assert len(ids) == 2
    results = await mgr.wait_all(ids)
    assert all(r.success for r in results)


# --- DEFAULT_AGENT_TYPE fallback (extension point #10) ---
# --- 默认 Agent 类型回退（拓展点 #10） ---


async def test_untyped_subagent_uses_default_type(tmp_path):
    """No agent_type -> the DEFAULT_AGENT_TYPE (worker) profile applies.
    未指定类型 -> 采用 DEFAULT_AGENT_TYPE（worker）档案。"""
    from mini_agent.core.agent_types import DEFAULT_AGENT_TYPE

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())

    agent = SubAgent(
        task="do something",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    worker = get_agent_type(DEFAULT_AGENT_TYPE)
    # Same prompt template as the default type (formatted with runtime values)
    # 与默认类型同一提示词模板（用运行时值格式化）
    head = worker.system_prompt.split("{", 1)[0]
    assert agent._conversation.system_prompt.startswith(head)
    # worker keeps all tools 保留全部工具
    assert agent._loop._tools.get("write_file") is not None


async def test_untyped_subagent_keeps_config_iterations(tmp_path):
    """Untyped spawn keeps config.max_agent_iterations, NOT the worker
    type's 50 -- the config is user-tunable and must win when no type is
    explicitly requested. 未指定类型时保留 config 的迭代预算而非 worker 的
    50——用户可配值优先。"""
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    config = AgentConfig()
    config.max_agent_iterations = 7
    agent = SubAgent(
        task="do something",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=config,
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    assert agent._loop._config.max_agent_iterations == 7
    assert "7" in agent._conversation.system_prompt  # iteration_budget 注入


async def test_typed_subagent_still_overrides_iterations(tmp_path):
    """Explicit type opt-in adopts the type's budget (worker = 50).
    显式选类型仍采纳类型预算（worker = 50）。"""
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    config = AgentConfig()
    config.max_agent_iterations = 7
    agent = SubAgent(
        task="do something",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=config,
        event_bus=EventBus(),
        working_dir=tmp_path,
        agent_type=get_agent_type("worker"),
    )
    assert agent._loop._config.max_agent_iterations == 50


# --- background spawn + completion notification 后台派生 + 完成通知 ---


async def test_spawn_background_returns_immediately(tmp_path):
    """spawn_background returns ids without waiting for completion.
    spawn_background 立即返回 id，不等完成。"""
    mgr = make_manager([text_response("slow work")], tmp_path, delay=0.2)
    mgr.mailbox.register("main")
    ids = await mgr.spawn_background(["a slow task"])
    assert len(ids) == 1
    # Agent still running right after return 返回时 agent 仍在运行
    assert ids[0] in mgr.list_active()
    await asyncio.sleep(0.4)  # let it finish 等它完成


async def test_background_completion_notifies_main(tmp_path):
    """On completion, 'main' receives a mailbox message with the result.
    完成后 main 收件箱收到含结果的通知。"""
    mgr = make_manager([text_response("the answer is 42")], tmp_path)
    mgr.mailbox.register("main")
    ids = await mgr.spawn_background(["compute the answer"])
    await asyncio.sleep(0.3)  # notifier runs after completion 等通知任务跑完

    mails = mgr.mailbox.drain("main")
    assert len(mails) == 1
    assert f"[Background agent '{ids[0]}' completed successfully]" in mails[0].content
    assert "the answer is 42" in mails[0].content
    assert mails[0].sender == ids[0]


async def test_background_failure_notifies_failed(tmp_path):
    """A cancelled background agent delivers a FAILED notification.
    被取消的后台 agent 投递 FAILED 通知。"""
    mgr = make_manager([text_response("never finishes")], tmp_path, delay=5.0)
    mgr.mailbox.register("main")
    ids = await mgr.spawn_background(["doomed task"])
    await asyncio.sleep(0.05)
    mgr.cancel(ids[0])
    await asyncio.sleep(0.3)

    mails = mgr.mailbox.drain("main")
    assert len(mails) == 1
    assert "FAILED" in mails[0].content


async def test_background_event_flag(tmp_path):
    """SubAgentCompleteEvent.background is True for background spawns,
    False for normal spawn+wait. 后台派生事件 background=True，普通为 False。"""
    from mini_agent.models.events import SubAgentCompleteEvent

    events: list[SubAgentCompleteEvent] = []

    async def _collect(event: SubAgentCompleteEvent) -> None:
        events.append(event)

    mgr = make_manager([text_response("ok")], tmp_path)
    mgr.mailbox.register("main")
    mgr._event_bus.on(SubAgentCompleteEvent, _collect)

    await mgr.spawn_background(["bg task"])
    await asyncio.sleep(0.3)
    assert len(events) == 1
    assert events[0].background is True

    agent_id = await mgr.spawn("fg task")
    await mgr.wait(agent_id)
    assert len(events) == 2
    assert events[1].background is False


async def test_spawn_agents_tool_background_mode(tmp_path):
    """The spawn_agents tool with background=true returns immediately.
    spawn_agents 工具 background=true 时立即返回。"""
    from mini_agent.events.bus import EventBus as _Bus
    from mini_agent.models.session import Session
    from mini_agent.tools.base import ToolContext
    from mini_agent.tools.builtin.spawn_agents import SpawnAgentsTool

    mgr = make_manager([text_response("bg result")], tmp_path, delay=0.2)
    mgr.mailbox.register("main")
    ctx = ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=_Bus(),
        config=AgentConfig(),
        subagent_manager=mgr,
    )
    result = await SpawnAgentsTool().execute(ctx, tasks=["bg work"], background=True)
    assert not result.is_error
    assert "background agent(s)" in result.output
    # Returned before completion (agent still active) 返回时 agent 仍在运行
    assert len(mgr.list_active()) == 1
    await asyncio.sleep(0.5)  # drain 等完成


# --- fork-style context inheritance 摘要式上下文继承 ---


async def test_summarize_conversation_llm_success(tmp_path):
    """LLM summary is returned when the call succeeds. LLM 成功时返回其摘要。"""
    from mini_agent.memory.compressor import summarize_conversation
    from mini_agent.models.message import Message, Role

    llm = MockLLM([text_response("<summary>We discussed renaming X to Y.</summary>")])
    msgs = [
        Message(role=Role.USER, content="let's rename X to Y"),
        Message(role=Role.ASSISTANT, content="agreed, X becomes Y"),
    ]
    summary = await summarize_conversation(llm, msgs)
    assert "renaming X to Y" in summary


async def test_summarize_conversation_falls_back_on_llm_error(tmp_path):
    """A failing LLM falls back to the extractive digest. LLM 失败回退 digest。"""
    from mini_agent.memory.compressor import summarize_conversation
    from mini_agent.models.message import Message, Role

    class BoomLLM(MockLLM):
        async def stream(self, messages, tools=None, **kwargs):
            raise RuntimeError("api down")
            yield  # pragma: no cover

    msgs = [Message(role=Role.USER, content="rename X to Y please")]
    summary = await summarize_conversation(BoomLLM([]), msgs)
    assert "rename X to Y" in summary  # digest contains the original text


async def test_subagent_context_summary_injected(tmp_path):
    """context_summary lands in the sub-agent's system prompt.
    context_summary 注入子 agent 的 system prompt。"""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    agent = SubAgent(
        task="do the thing we discussed",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        context_summary="We agreed to rename X to Y.",
    )
    sp = agent._conversation.system_prompt
    assert "[Inherited context" in sp
    assert "rename X to Y" in sp


async def test_subagent_no_summary_no_marker(tmp_path):
    """Default (empty summary) leaves the system prompt unchanged.
    默认空摘要不注入标记（行为不变）。"""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    agent = SubAgent(
        task="plain task",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    assert "[Inherited context" not in agent._conversation.system_prompt


async def test_spawn_background_passes_context_summary(tmp_path):
    """context_summary flows through spawn_background to the sub-agent.
    context_summary 经 spawn_background 透传到子 agent。"""
    mgr = make_manager([text_response("done")], tmp_path)
    mgr.mailbox.register("main")
    ids = await mgr.spawn_background(
        ["continue the discussed work"], context_summary="Discussion: use plan B."
    )
    entry = mgr._active[ids[0]]
    assert "use plan B" in entry.agent._conversation.system_prompt
    await asyncio.sleep(0.3)


async def test_spawn_agents_tool_inherit_context(tmp_path):
    """inherit_context=true summarizes the main conversation and injects it.
    inherit_context=true 摘要主对话并注入。"""
    from mini_agent.models.message import Message, Role
    from mini_agent.models.session import Session
    from mini_agent.tools.base import ToolContext
    from mini_agent.tools.builtin.spawn_agents import SpawnAgentsTool

    # Script: first call = summary generation, second = sub-agent reply
    # 脚本：第一次调用是摘要生成，第二次是子 agent 回复
    mgr = make_manager(
        [
            text_response("<summary>Parent discussed plan Z.</summary>"),
            text_response("executed per plan Z"),
        ],
        tmp_path,
    )
    mgr.mailbox.register("main")
    session = Session()
    session.conversation.append(Message(role=Role.USER, content="let's go with plan Z"))
    ctx = ToolContext(
        working_dir=tmp_path,
        session=session,
        event_bus=EventBus(),
        config=AgentConfig(),
        subagent_manager=mgr,
    )
    result = await SpawnAgentsTool().execute(
        ctx, tasks=["do what we discussed"], inherit_context=True
    )
    assert not result.is_error
    assert "1/1 succeeded" in result.output
