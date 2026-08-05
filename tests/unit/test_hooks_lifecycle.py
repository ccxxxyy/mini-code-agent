"""Tests for PRE_LLM and SESSION_END lifecycle hooks. 生命周期 hook 测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.agent_loop import AgentLoop
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk
from mini_agent.models.config import AgentConfig
from mini_agent.models.message import Conversation, Message, Role
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.hooks import (
    HookAction,
    HookContext,
    HookManager,
    HookResult,
    HookStage,
)

pytestmark = pytest.mark.asyncio


class MockLLM(LLMProvider):
    def __init__(self):
        self.call_count = 0

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        self.call_count += 1
        yield StreamChunk(delta="hello")
        yield StreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


def make_loop(tmp_path, hooks: HookManager | None = None) -> tuple[AgentLoop, MockLLM]:
    llm = MockLLM()
    hm = hooks or HookManager()
    loop = AgentLoop(
        llm=llm,
        tool_registry=ToolRegistry(),
        event_bus=EventBus(),
        config=AgentConfig(),
        tool_context=ToolContext(
            working_dir=tmp_path, session=Session(), event_bus=EventBus(), config=AgentConfig()
        ),
        hook_manager=hm,
    )
    return loop, llm


# --- PRE_LLM ---


async def test_pre_llm_hook_fires(tmp_path):
    fired: list[str] = []

    async def on_pre_llm(ctx: HookContext) -> HookResult:
        fired.append(ctx.stage.value)
        return HookResult()

    hm = HookManager()
    hm.register(HookStage.PRE_LLM, on_pre_llm)
    loop, llm = make_loop(tmp_path, hooks=hm)

    conv = Conversation(system_prompt="test")
    conv.append(Message(role=Role.USER, content="hi"))
    await loop.run(conv)

    assert "pre_llm" in fired
    assert llm.call_count == 1


async def test_pre_llm_block_prevents_llm_call(tmp_path):
    async def block_llm(ctx: HookContext) -> HookResult:
        return HookResult(action=HookAction.BLOCK, reason="rate limited")

    hm = HookManager()
    hm.register(HookStage.PRE_LLM, block_llm)
    loop, llm = make_loop(tmp_path, hooks=hm)

    conv = Conversation(system_prompt="test")
    conv.append(Message(role=Role.USER, content="hi"))
    output = await loop.run(conv)

    assert llm.call_count == 0
    assert "rate limited" in output


# --- SESSION_END ---


async def test_session_end_hook_fires(tmp_path):
    fired: list[str] = []

    async def on_session_end(ctx: HookContext) -> HookResult:
        fired.append(ctx.stage.value)
        return HookResult()

    hm = HookManager()
    hm.register(HookStage.SESSION_END, on_session_end)

    await hm.run(HookContext(stage=HookStage.SESSION_END, metadata={"session_id": "test123"}))
    assert "session_end" in fired


async def test_session_end_receives_metadata():
    received: list[dict] = []

    async def capture(ctx: HookContext) -> HookResult:
        received.append(ctx.metadata)
        return HookResult()

    hm = HookManager()
    hm.register(HookStage.SESSION_END, capture)

    await hm.run(
        HookContext(stage=HookStage.SESSION_END, metadata={"session_id": "abc", "extra": 42})
    )
    assert received[0]["session_id"] == "abc"
    assert received[0]["extra"] == 42
