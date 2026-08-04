"""Tests for the hook lifecycle system."""

import pytest

from mini_agent.tools.hooks import (
    HookAction,
    HookContext,
    HookManager,
    HookResult,
    HookStage,
)

pytestmark = pytest.mark.asyncio


async def test_no_hooks_continues():
    mgr = HookManager()
    result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash"))
    assert result.action == HookAction.CONTINUE


async def test_block_hook():
    mgr = HookManager()

    async def blocker(ctx: HookContext) -> HookResult:
        return HookResult(action=HookAction.BLOCK, reason="not allowed")

    mgr.register(HookStage.PRE_TOOL, blocker)
    result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash"))
    assert result.action == HookAction.BLOCK
    assert result.reason == "not allowed"


async def test_block_short_circuits():
    calls = []

    async def blocker(ctx):
        calls.append("blocker")
        return HookResult(action=HookAction.BLOCK)

    async def later(ctx):
        calls.append("later")
        return HookResult(action=HookAction.CONTINUE)

    mgr = HookManager()
    mgr.register(HookStage.PRE_TOOL, blocker, priority=10)
    mgr.register(HookStage.PRE_TOOL, later, priority=0)
    await mgr.run(HookContext(stage=HookStage.PRE_TOOL))
    assert calls == ["blocker"]


async def test_modify_hook_updates_args():
    async def modifier(ctx: HookContext) -> HookResult:
        new_args = dict(ctx.tool_args or {})
        new_args["timeout"] = 5
        return HookResult(action=HookAction.MODIFY, modified_args=new_args)

    mgr = HookManager()
    mgr.register(HookStage.PRE_TOOL, modifier)
    ctx = HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "ls"})
    await mgr.run(ctx)
    assert ctx.tool_args == {"command": "ls", "timeout": 5}


async def test_priority_order():
    calls = []

    async def high(ctx):
        calls.append("high")
        return HookResult()

    async def low(ctx):
        calls.append("low")
        return HookResult()

    mgr = HookManager()
    mgr.register(HookStage.PRE_TOOL, low, priority=1)
    mgr.register(HookStage.PRE_TOOL, high, priority=10)
    await mgr.run(HookContext(stage=HookStage.PRE_TOOL))
    assert calls == ["high", "low"]


async def test_stage_isolation():
    calls = []

    async def pre_hook(ctx):
        calls.append("pre")
        return HookResult()

    mgr = HookManager()
    mgr.register(HookStage.PRE_TOOL, pre_hook)
    await mgr.run(HookContext(stage=HookStage.POST_TOOL))
    assert calls == []


async def test_unregister():
    calls = []

    async def hook(ctx):
        calls.append(1)
        return HookResult()

    mgr = HookManager()
    mgr.register(HookStage.PRE_TOOL, hook)
    mgr.unregister(HookStage.PRE_TOOL, hook)
    await mgr.run(HookContext(stage=HookStage.PRE_TOOL))
    assert calls == []
