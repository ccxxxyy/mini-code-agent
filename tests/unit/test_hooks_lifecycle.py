"""Tests for PRE_LLM and SESSION_END lifecycle hooks. 生命周期 hook 测试。"""

from __future__ import annotations

import pytest

from mini_agent.core.agent_loop import AgentLoop
from mini_agent.events.bus import EventBus
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
from tests.mocks import MockLLM

pytestmark = pytest.mark.asyncio


def make_loop(tmp_path, hooks: HookManager | None = None) -> tuple[AgentLoop, MockLLM]:
    llm = MockLLM(text="hello")
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


# --- Extended lifecycle stages ---


def test_all_stages_unique():
    values = [s.value for s in HookStage]
    assert len(values) == len(set(values))
    assert len(values) == 11
    for name in (
        "startup",
        "shutdown",
        "session_start",
        "session_end",
        "user_input",
        "turn_start",
        "turn_end",
        "pre_llm",
        "post_llm",
        "pre_tool",
        "post_tool",
    ):
        assert name in values


async def test_turn_start_and_end_fire(tmp_path):
    fired: list[str] = []

    async def capture(ctx: HookContext) -> HookResult:
        fired.append(ctx.stage.value)
        return HookResult()

    hm = HookManager()
    hm.register(HookStage.TURN_START, capture)
    hm.register(HookStage.TURN_END, capture)
    hm.register(HookStage.PRE_LLM, capture)
    loop, llm = make_loop(tmp_path, hooks=hm)

    conv = Conversation(system_prompt="test")
    conv.append(Message(role=Role.USER, content="hi"))
    await loop.run(conv)

    assert fired == ["turn_start", "pre_llm", "turn_end"]


async def test_turn_end_receives_metadata(tmp_path):
    received: list[dict] = []

    async def capture(ctx: HookContext) -> HookResult:
        received.append(dict(ctx.metadata))
        return HookResult()

    hm = HookManager()
    hm.register(HookStage.TURN_END, capture)
    loop, llm = make_loop(tmp_path, hooks=hm)

    conv = Conversation(system_prompt="test")
    conv.append(Message(role=Role.USER, content="hi"))
    await loop.run(conv)

    assert received[0]["iteration_count"] >= 1
    assert "tools_called" in received[0]
    assert "tokens_used" in received[0]


async def test_post_llm_fires_with_content(tmp_path):
    received: list[dict] = []

    async def capture(ctx: HookContext) -> HookResult:
        received.append(dict(ctx.metadata))
        return HookResult()

    hm = HookManager()
    hm.register(HookStage.POST_LLM, capture)
    loop, llm = make_loop(tmp_path, hooks=hm)

    conv = Conversation(system_prompt="test")
    conv.append(Message(role=Role.USER, content="hi"))
    await loop.run(conv)

    assert len(received) == 1
    assert received[0]["content_preview"] == "hello"
    assert received[0]["has_tool_calls"] is False
    assert received[0]["finish_reason"] == "stop"


async def test_post_llm_block_does_not_affect_flow(tmp_path):
    async def block(ctx: HookContext) -> HookResult:
        return HookResult(action=HookAction.BLOCK, reason="ignored")

    hm = HookManager()
    hm.register(HookStage.POST_LLM, block)
    loop, llm = make_loop(tmp_path, hooks=hm)

    conv = Conversation(system_prompt="test")
    conv.append(Message(role=Role.USER, content="hi"))
    output = await loop.run(conv)

    assert output == "hello"
    assert llm.call_count == 1


async def test_user_input_block_via_manager():
    async def block_bad_input(ctx: HookContext) -> HookResult:
        if "forbidden" in ctx.metadata.get("input_text", ""):
            return HookResult(action=HookAction.BLOCK, reason="input rejected")
        return HookResult()

    hm = HookManager()
    hm.register(HookStage.USER_INPUT, block_bad_input)

    blocked = await hm.run(
        HookContext(stage=HookStage.USER_INPUT, metadata={"input_text": "forbidden text"})
    )
    assert blocked.action == HookAction.BLOCK
    assert blocked.reason == "input rejected"

    allowed = await hm.run(
        HookContext(stage=HookStage.USER_INPUT, metadata={"input_text": "normal text"})
    )
    assert allowed.action == HookAction.CONTINUE


async def test_startup_shutdown_session_start_via_manager():
    fired: list[str] = []

    async def capture(ctx: HookContext) -> HookResult:
        fired.append(ctx.stage.value)
        return HookResult()

    hm = HookManager()
    for stage in (HookStage.STARTUP, HookStage.SESSION_START, HookStage.SHUTDOWN):
        hm.register(stage, capture)

    await hm.run(HookContext(stage=HookStage.STARTUP, metadata={"session_id": "s1"}))
    await hm.run(
        HookContext(stage=HookStage.SESSION_START, metadata={"session_id": "s1", "model": "m"})
    )
    await hm.run(HookContext(stage=HookStage.SHUTDOWN, metadata={"session_id": "s1"}))

    assert fired == ["startup", "session_start", "shutdown"]
