"""Tests for the cross-agent Mailbox and SendMessageTool (6.2).
跨 Agent Mailbox 与 SendMessageTool 测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.mailbox import Mailbox
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk
from mini_agent.models.config import AgentConfig
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin.send_message import SendMessageTool

pytestmark = pytest.mark.asyncio


# --- Mailbox core ---


def make_mailbox(tmp_path) -> Mailbox:
    return Mailbox(tmp_path / "mailboxes")


async def test_send_and_drain(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")

    assert mb.send(sender="agent_a", recipient="main", content="found the bug")
    messages = mb.drain("main")
    assert len(messages) == 1
    assert messages[0].sender == "agent_a"
    assert messages[0].content == "found the bug"
    assert messages[0].timestamp

    # Drain clears the inbox 清空后再 drain 为空
    assert mb.drain("main") == []


async def test_send_to_unknown_recipient(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    assert not mb.send(sender="main", recipient="ghost", content="hi")


async def test_drain_unregistered_agent(tmp_path):
    mb = make_mailbox(tmp_path)
    assert mb.drain("nobody") == []


async def test_messages_persist_to_file(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("agent_b")
    mb.send(sender="main", recipient="agent_b", content="第一条")
    mb.send(sender="main", recipient="agent_b", content="第二条")

    inbox = tmp_path / "mailboxes" / "agent_b.json"
    assert inbox.is_file()
    messages = mb.drain("agent_b")
    assert [m.content for m in messages] == ["第一条", "第二条"]


async def test_register_resets_stale_inbox(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.send(sender="main", recipient="main", content="stale")
    # New session re-registers -> old messages are dropped
    # 新会话重新注册 -> 旧消息被丢弃
    mb2 = make_mailbox(tmp_path)
    mb2.register("main")
    assert mb2.drain("main") == []


async def test_peers(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    mb.register("agent_b")
    assert mb.peers(exclude="agent_a") == ["agent_b", "main"]
    mb.unregister("agent_b")
    assert mb.peers() == ["agent_a", "main"]


async def test_unregister_drops_inbox_file(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("agent_a")
    mb.unregister("agent_a")
    assert not (tmp_path / "mailboxes" / "agent_a.json").is_file()
    assert not mb.send(sender="main", recipient="agent_a", content="late")


# --- SendMessageTool ---


def make_ctx(tmp_path, mailbox: Mailbox | None, agent_id: str = "agent_a") -> ToolContext:
    return ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
        mailbox=mailbox,
        agent_id=agent_id,
    )


async def test_send_message_tool_delivers(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    tool = SendMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), to="main", message="progress: 50%")
    assert not result.is_error
    assert "delivered to 'main'" in result.output
    messages = mb.drain("main")
    assert messages[0].sender == "agent_a"
    assert messages[0].content == "progress: 50%"


async def test_send_message_tool_unknown_recipient(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    tool = SendMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), to="ghost", message="hi")
    assert result.is_error
    assert "Unknown recipient" in result.output
    assert "main" in result.output  # lists known agents 列出已知 Agent


async def test_send_message_tool_no_mailbox(tmp_path):
    tool = SendMessageTool()
    result = await tool.execute(make_ctx(tmp_path, None), to="main", message="hi")
    assert result.is_error
    assert "not available" in result.output


async def test_send_message_tool_empty_message(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    tool = SendMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), to="main", message="   ")
    assert result.is_error


# --- WaitMessageTool ---


async def test_wait_message_returns_immediately_when_mail_waiting(tmp_path):
    from mini_agent.tools.builtin.wait_message import WaitMessageTool

    mb = make_mailbox(tmp_path)
    mb.register("agent_a")
    mb.send(sender="main", recipient="agent_a", content="here you go")
    tool = WaitMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), timeout_seconds=5)
    assert not result.is_error
    assert "Received 1 message(s)" in result.output
    assert "[from 'main'" in result.output
    assert "here you go" in result.output


async def test_wait_message_blocks_until_mail_arrives(tmp_path):
    import asyncio

    from mini_agent.tools.builtin.wait_message import WaitMessageTool

    mb = make_mailbox(tmp_path)
    mb.register("agent_a")
    mb.register("agent_b")
    tool = WaitMessageTool()

    async def send_later() -> None:
        await asyncio.sleep(0.7)
        mb.send(sender="agent_b", recipient="agent_a", content="delayed news")

    result, _ = await asyncio.gather(
        tool.execute(make_ctx(tmp_path, mb), timeout_seconds=10),
        send_later(),
    )
    assert not result.is_error
    assert "delayed news" in result.output


async def test_wait_message_timeout(tmp_path):
    from mini_agent.tools.builtin.wait_message import WaitMessageTool

    mb = make_mailbox(tmp_path)
    mb.register("agent_a")
    tool = WaitMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), timeout_seconds=0.1)
    assert not result.is_error  # timeout is information, not an error 超时是信息不是错误
    assert "No message arrived" in result.output


async def test_wait_message_no_mailbox(tmp_path):
    from mini_agent.tools.builtin.wait_message import WaitMessageTool

    tool = WaitMessageTool()
    result = await tool.execute(make_ctx(tmp_path, None), timeout_seconds=1)
    assert result.is_error


# --- AgentLoop inbox delivery ---


class MockLLM(LLMProvider):
    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="Done.")
        yield StreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


async def test_agent_loop_delivers_inbox_messages(tmp_path):
    from mini_agent.core.agent_loop import AgentLoop
    from mini_agent.models.message import Conversation, Message, Role

    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    mb.send(sender="agent_a", recipient="main", content="worker finding")

    bus = EventBus()
    config = AgentConfig()
    config.self_verify = False
    loop = AgentLoop(
        llm=MockLLM(),
        tool_registry=ToolRegistry(),
        event_bus=bus,
        config=config,
        tool_context=make_ctx(tmp_path, mb, agent_id="main"),
    )
    loop.mailbox = mb
    loop.agent_id = "main"

    conversation = Conversation(system_prompt="test")
    conversation.append(Message(role=Role.USER, content="hello"))
    await loop.run(conversation)

    delivered = [
        m
        for m in conversation.messages
        if m.role == Role.USER and "[Message from agent 'agent_a']" in (m.content or "")
    ]
    assert len(delivered) == 1
    assert "worker finding" in delivered[0].content
    assert mb.drain("main") == []  # inbox drained 收件箱已清空


async def test_subagent_registers_and_gets_mailbox_prompt(tmp_path):
    from mini_agent.core.subagent import SubAgent

    registry = ToolRegistry()
    registry.register(SendMessageTool())
    mb = make_mailbox(tmp_path)
    mb.register("main")

    agent = SubAgent(
        task="test task",
        llm=MockLLM(),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        mailbox=mb,
    )
    assert agent.agent_id in mb.peers()
    assert agent.agent_id in agent._conversation.system_prompt
    assert "send_message" in agent._conversation.system_prompt
    assert agent._loop.agent_id == agent.agent_id

    # After run() completes, the inbox is unregistered
    # run() 结束后收件箱注销
    await agent.run()
    assert agent.agent_id not in mb.peers()


async def test_spawn_parallel_siblings_know_each_other(tmp_path):
    from mini_agent.core.subagent import SubAgentManager

    registry = ToolRegistry()
    registry.register(SendMessageTool())
    mgr = SubAgentManager(
        llm=MockLLM(),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    tasks = ["count unit tests", "count core files", "wait and sum the numbers"]
    ids = await mgr.spawn_parallel(tasks)
    assert len(set(ids)) == 3
    # Each agent's system prompt names its own id, and each peer id WITH its
    # task snippet -- so agents know which peer plays which role
    # 每个 Agent 的 prompt 含自身 id，同伴 id 均带任务摘要——知道谁是什么角色
    for i, agent_id in enumerate(ids):
        prompt = mgr._active[agent_id].agent._conversation.system_prompt
        assert f"agent '{agent_id}'" in prompt
        for j, peer in enumerate(ids):
            if peer != agent_id:
                assert f"'{peer}' (task: {tasks[j]}" in prompt
    await mgr.wait_all(ids)
