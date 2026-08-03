"""Integration tests: security pipeline inside the agent loop.
集成测试：Agent 循环内部的安全管线。
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from mini_agent.core.agent_loop import AgentLoop
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk, ToolCallDelta
from mini_agent.models.config import AgentConfig, SecurityConfig, ToolConfig
from mini_agent.models.message import Conversation, Role
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.builtin import BashTool, ReadFileTool
from mini_agent.tools.hooks import (
    HookAction,
    HookContext,
    HookManager,
    HookResult,
    HookStage,
)


class ScriptedLLM(LLMProvider):
    def __init__(self, scripts):
        self._scripts = scripts
        self._i = 0

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        script = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        for chunk in script:
            yield chunk

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


def tool_call(name: str, args: dict) -> list[StreamChunk]:
    return [
        StreamChunk(
            tool_call_deltas=[
                ToolCallDelta(index=0, id="c1", name=name, arguments_delta=json.dumps(args))
            ]
        ),
        StreamChunk(finish_reason="tool_calls"),
    ]


def text(t: str) -> list[StreamChunk]:
    return [StreamChunk(delta=t), StreamChunk(finish_reason="stop")]


def make_secured_loop(scripts, tool_context, confirm=None, hooks=None):
    config = AgentConfig()
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(BashTool())

    path_guard = PathGuard(
        tool_config=ToolConfig(),
        security_config=SecurityConfig(),
        project_dir=tool_context.working_dir,
    )
    pm = PermissionManager(
        config=SecurityConfig(),
        path_guard=path_guard,
        confirm_callback=confirm,
    )
    return AgentLoop(
        llm=ScriptedLLM(scripts),
        tool_registry=registry,
        event_bus=EventBus(),
        config=config,
        tool_context=tool_context,
        permission_manager=pm,
        hook_manager=hooks or HookManager(),
    )


async def test_project_file_read_allowed(tool_context):
    f = tool_context.working_dir / "ok.txt"
    f.write_text("fine", encoding="utf-8")

    loop = make_secured_loop(
        [tool_call("read_file", {"file_path": str(f)}), text("done")],
        tool_context,
    )
    conv = Conversation()
    await loop.run(conv)

    tool_msg = [m for m in conv.messages if m.role == Role.TOOL][0]
    assert not tool_msg.tool_result.is_error
    assert "fine" in tool_msg.tool_result.output


async def test_dangerous_bash_denied_without_ui(tool_context):
    loop = make_secured_loop(
        [tool_call("bash", {"command": "rm -rf /tmp/x"}), text("done")],
        tool_context,
        confirm=None,  # no UI -> dangerous commands denied
    )
    conv = Conversation()
    await loop.run(conv)

    tool_msg = [m for m in conv.messages if m.role == Role.TOOL][0]
    assert tool_msg.tool_result.is_error
    assert "Permission denied" in tool_msg.tool_result.output


async def test_dangerous_bash_approved_by_user(tool_context):
    async def approve(prompt):
        return True

    loop = make_secured_loop(
        [tool_call("bash", {"command": "rm -rf ./build && echo cleaned"}), text("done")],
        tool_context,
        confirm=approve,
    )
    conv = Conversation()
    await loop.run(conv)

    tool_msg = [m for m in conv.messages if m.role == Role.TOOL][0]
    # Approved -> command actually ran (echo works even if rm target missing)
    # 已批准 -> 命令实际执行了（即使 rm 的目标不存在，echo 也能正常工作）
    assert "Permission denied" not in tool_msg.tool_result.output


async def test_sensitive_file_blocked(tool_context):
    env_file = tool_context.working_dir / ".env"
    env_file.write_text("SECRET=x", encoding="utf-8")

    loop = make_secured_loop(
        [tool_call("read_file", {"file_path": str(env_file)}), text("done")],
        tool_context,
    )
    conv = Conversation()
    await loop.run(conv)

    tool_msg = [m for m in conv.messages if m.role == Role.TOOL][0]
    assert tool_msg.tool_result.is_error
    assert "Permission denied" in tool_msg.tool_result.output


async def test_pre_tool_hook_blocks(tool_context):
    f = tool_context.working_dir / "x.txt"
    f.write_text("data", encoding="utf-8")

    async def block_reads(ctx: HookContext) -> HookResult:
        if ctx.tool_name == "read_file":
            return HookResult(action=HookAction.BLOCK, reason="reads disabled")
        return HookResult()

    hooks = HookManager()
    hooks.register(HookStage.PRE_TOOL, block_reads)

    loop = make_secured_loop(
        [tool_call("read_file", {"file_path": str(f)}), text("done")],
        tool_context,
        hooks=hooks,
    )
    conv = Conversation()
    await loop.run(conv)

    tool_msg = [m for m in conv.messages if m.role == Role.TOOL][0]
    assert tool_msg.tool_result.is_error
    assert "reads disabled" in tool_msg.tool_result.output


async def test_post_tool_hook_observes(tool_context):
    f = tool_context.working_dir / "y.txt"
    f.write_text("data", encoding="utf-8")

    observed = []

    async def observer(ctx: HookContext) -> HookResult:
        observed.append((ctx.tool_name, ctx.tool_result.is_error))
        return HookResult()

    hooks = HookManager()
    hooks.register(HookStage.POST_TOOL, observer)

    loop = make_secured_loop(
        [tool_call("read_file", {"file_path": str(f)}), text("done")],
        tool_context,
        hooks=hooks,
    )
    conv = Conversation()
    await loop.run(conv)

    assert observed == [("read_file", False)]
