"""E2E verification: two concurrent SubAgents exchange messages mid-run.
端到端验证：两个并行 SubAgent 在运行中互传消息。

Agent B loops on a wait tool until mail arrives; Agent A sends it a message
via the real send_message tool. B's final answer proves it saw the message
mid-run -- the full chain (tool -> Mailbox file -> AgentLoop drain -> conversation)
is exercised without a real LLM.
Agent B 循环等待直到收到消息；Agent A 通过真实的 send_message 工具发消息。
B 的最终回答证明它在运行中看到了消息——完整链路（工具 -> Mailbox 文件 ->
AgentLoop drain -> 会话）全部走通，无需真实 LLM。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic import BaseModel

from mini_agent.core.mailbox import Mailbox
from mini_agent.core.subagent import SubAgent
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk, ToolCallDelta
from mini_agent.models.config import AgentConfig
from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolRegistry
from mini_agent.tools.builtin.send_message import SendMessageTool

pytestmark = pytest.mark.asyncio

MAIL_MARKER = "[Message from agent"


class WaitParams(BaseModel):
    pass


class WaitTool(Tool):
    """No-op tool that yields the event loop briefly. 短暂让出事件循环的空工具。"""

    _name = "wait"
    _description = "Wait briefly"
    params_model = WaitParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        await asyncio.sleep(0.05)
        return ToolResult(call_id="", name="wait", output="waited")


def _tool_call_chunks(name: str, args: dict) -> list[StreamChunk]:
    return [
        StreamChunk(
            tool_call_deltas=[
                ToolCallDelta(index=0, id="call_1", name=name, arguments_delta=json.dumps(args))
            ]
        ),
        StreamChunk(finish_reason="tool_calls"),
    ]


class ReceiverLLM(LLMProvider):
    """Waits (via wait tool) until a mailbox message appears in the
    conversation, then reports it. 循环等待，收到消息后如实上报。"""

    MAX_WAIT_ROUNDS = 30

    def __init__(self) -> None:
        self._rounds = 0

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        mail = [
            m["content"]
            for m in messages
            if m.get("role") == "user" and MAIL_MARKER in str(m.get("content", ""))
        ]
        if mail:
            yield StreamChunk(delta=f"RECEIVED: {mail[0]}")
            yield StreamChunk(finish_reason="stop")
            return
        self._rounds += 1
        if self._rounds >= self.MAX_WAIT_ROUNDS:
            yield StreamChunk(delta="NEVER_RECEIVED")
            yield StreamChunk(finish_reason="stop")
            return
        for chunk in _tool_call_chunks("wait", {}):
            yield chunk

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


class SenderLLM(LLMProvider):
    """Sends one message to the target agent, then finishes.
    给目标 Agent 发一条消息后结束。"""

    def __init__(self, target_id: str) -> None:
        self._target = target_id
        self._sent = False

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        if not self._sent:
            self._sent = True
            args = {"to": self._target, "message": "convention: this project uses pnpm"}
            for chunk in _tool_call_chunks("send_message", args):
                yield chunk
            return
        yield StreamChunk(delta="message sent, done")
        yield StreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


class WaitingReceiverLLM(LLMProvider):
    """Round 1: call wait_message. Round 2: report what the tool returned.
    第一轮调用 wait_message，第二轮上报工具返回的消息。"""

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        received = [
            str(m.get("content", ""))
            for m in messages
            if m.get("role") == "tool" and "[from '" in str(m.get("content", ""))
        ]
        if received:
            yield StreamChunk(delta=f"RECEIVED: {received[0]}")
            yield StreamChunk(finish_reason="stop")
            return
        for chunk in _tool_call_chunks("wait_message", {"timeout_seconds": 15}):
            yield chunk

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


class SlowSenderLLM(LLMProvider):
    """Waits before sending -- reproduces the 'sender slower than receiver'
    timing that killed the naive sleep-loop approach.
    发送前先等待——复现"发送方比接收方慢"的时序。"""

    def __init__(self, target_id: str) -> None:
        self._target = target_id
        self._step = 0

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        self._step += 1
        if self._step == 1:
            for chunk in _tool_call_chunks("wait", {}):  # simulate slow exploration 模拟慢速探索
                yield chunk
            return
        if self._step == 2:
            args = {"to": self._target, "message": "late finding: use pnpm"}
            for chunk in _tool_call_chunks("send_message", args):
                yield chunk
            return
        yield StreamChunk(delta="sent")
        yield StreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


async def test_receiver_survives_slow_sender_via_wait_message(tmp_path):
    from mini_agent.tools.builtin.wait_message import WaitMessageTool

    registry = ToolRegistry()
    registry.register(SendMessageTool())
    registry.register(WaitMessageTool())
    registry.register(WaitTool())
    mailbox = Mailbox(tmp_path / "mailboxes")
    config = AgentConfig()
    config.self_verify = False
    bus = EventBus()

    receiver = SubAgent(
        task="wait for the finding, then summarize it",
        llm=WaitingReceiverLLM(),
        tool_registry=registry,
        config=config,
        event_bus=bus,
        working_dir=tmp_path,
        mailbox=mailbox,
    )
    sender = SubAgent(
        task="explore slowly, then share the finding",
        llm=SlowSenderLLM(target_id=receiver.agent_id),
        tool_registry=registry,
        config=config,
        event_bus=bus,
        working_dir=tmp_path,
        mailbox=mailbox,
    )

    receiver_result, sender_result = await asyncio.gather(receiver.run(), sender.run())

    assert sender_result.success
    assert receiver_result.success
    # wait_message kept the receiver alive until the slow sender delivered
    # wait_message 让接收方存活到慢速发送方投递完成
    assert receiver_result.output.startswith("RECEIVED:")
    assert "late finding: use pnpm" in receiver_result.output
    assert f"[from '{sender.agent_id}'" in receiver_result.output


async def test_worker_to_worker_message_mid_run(tmp_path):
    registry = ToolRegistry()
    registry.register(SendMessageTool())
    registry.register(WaitTool())
    mailbox = Mailbox(tmp_path / "mailboxes")
    config = AgentConfig()
    config.self_verify = False
    bus = EventBus()

    receiver = SubAgent(
        task="wait for instructions",
        llm=ReceiverLLM(),
        tool_registry=registry,
        config=config,
        event_bus=bus,
        working_dir=tmp_path,
        mailbox=mailbox,
    )
    sender = SubAgent(
        task="tell the other agent about the pnpm convention",
        llm=SenderLLM(target_id=receiver.agent_id),
        tool_registry=registry,
        config=config,
        event_bus=bus,
        working_dir=tmp_path,
        mailbox=mailbox,
    )

    receiver_result, sender_result = await asyncio.gather(receiver.run(), sender.run())

    assert sender_result.success
    assert receiver_result.success
    # B saw A's message mid-run, with sender id and full content
    # B 在运行中看到了 A 的消息，含发送者 id 与完整内容
    assert receiver_result.output.startswith("RECEIVED:")
    assert f"[Message from agent '{sender.agent_id}']" in receiver_result.output
    assert "convention: this project uses pnpm" in receiver_result.output
