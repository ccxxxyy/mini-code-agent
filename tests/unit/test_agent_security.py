"""Integration tests: security pipeline inside the agent loop.
集成测试：Agent 循环内部的安全管线。
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

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

pytestmark = pytest.mark.asyncio


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


# --- D2: confirm-denial circuit breaker (threshold 1: one denial stops) ---
# Covers dangerous commands, paths outside the project, and hook confirms.


async def test_dangerous_denial_stops_loop_immediately(tool_context):
    """D2: denying one dangerous command stops the goal at once (threshold 1),
    never reaching the LLM's next bypass attempt.
    D2：拒绝一条危险命令立即停止（阈值 1），到不了 LLM 的下一条绕过尝试。"""

    async def deny(prompt):
        return False

    # LLM would keep trying bypasses (rm -> rmdir -> python -c). One denial stops.
    scripts = [
        tool_call("bash", {"command": "rm -rf /tmp/target"}),
        tool_call("bash", {"command": "rmdir /s /q /tmp/target"}),
        tool_call("bash", {"command": "python -c \"import shutil; shutil.rmtree('/tmp/target')\""}),
        text("done"),
    ]
    loop = make_secured_loop(scripts, tool_context, confirm=deny)
    conv = Conversation()
    await loop.run(conv)

    assert loop.stopped_early
    assert loop.stop_reason == "confirm_denied"
    # Stopped after the FIRST denial (1 iteration), bypasses never reached
    assert loop.state.iteration == 1
    # Only one bash tool result (the denied rm), no bypass executed
    bash_results = [m.tool_result.output for m in conv.messages if m.role == Role.TOOL]
    assert len(bash_results) == 1
    assert "Permission denied" in bash_results[0]


async def test_granted_dangerous_command_does_not_stop(tool_context):
    """A granted dangerous command proceeds (counter stays 0, no breaker).
    危险命令被放行时继续（计数器保持 0，不熔断）。"""

    async def allow(prompt):
        return True

    scripts = [
        tool_call("bash", {"command": "rm -rf ./build || echo ok"}),
        text("done"),
    ]
    loop = make_secured_loop(scripts, tool_context, confirm=allow)
    conv = Conversation()
    await loop.run(conv)

    assert loop.stop_reason != "confirm_denied"
    assert loop.state.consecutive_confirm_denials == 0


async def test_path_denial_stops_goal(tool_context):
    """Denying a path-outside-project confirm also stops the goal (threshold 1).
    拒绝项目外路径确认同样停止目标（阈值 1）。"""
    outside = tool_context.working_dir.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    async def deny(prompt):
        return False

    scripts = [
        tool_call("read_file", {"file_path": str(outside)}),
        tool_call("read_file", {"file_path": str(outside)}),
        text("done"),
    ]
    loop = make_secured_loop(scripts, tool_context, confirm=deny)
    conv = Conversation()
    await loop.run(conv)

    assert loop.stopped_early
    assert loop.stop_reason == "confirm_denied"
    assert loop.state.iteration == 1


async def test_hook_confirm_denial_stops_goal(tool_context):
    """Denying a hook confirm also stops the goal (threshold 1).
    拒绝 hook 确认同样停止目标（阈值 1）。"""
    from mini_agent.tools.hooks import HookManager

    hooks = HookManager()

    async def confirm_rule(ctx):
        if ctx.tool_name == "bash":
            return HookResult(action=HookAction.CONFIRM, reason="needs confirm")
        return HookResult(action=HookAction.CONTINUE)

    hooks.register(HookStage.PRE_TOOL, confirm_rule)

    async def deny(prompt):
        return False

    scripts = [
        tool_call("bash", {"command": "echo hello"}),
        tool_call("bash", {"command": "echo world"}),
        text("done"),
    ]
    loop = make_secured_loop(scripts, tool_context, confirm=deny, hooks=hooks)
    loop.confirm_callback = deny
    conv = Conversation()
    await loop.run(conv)

    assert loop.stopped_early
    assert loop.stop_reason == "confirm_denied"
    assert loop.state.iteration == 1


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


async def test_permission_check_event_emitted(tool_context):
    """PermissionCheckEvent fires with decision and reason.
    PermissionCheckEvent 携带判定结果和依据发射。"""
    from mini_agent.models.events import PermissionCheckEvent

    f = tool_context.working_dir / "evt.txt"
    f.write_text("x", encoding="utf-8")

    events = []

    loop = make_secured_loop(
        [tool_call("read_file", {"file_path": str(f)}), text("done")],
        tool_context,
    )

    async def collect(e: PermissionCheckEvent) -> None:
        events.append(e)

    loop._event_bus.on(PermissionCheckEvent, collect)

    conv = Conversation()
    await loop.run(conv)

    assert len(events) == 1
    evt = events[0]
    assert evt.tool_name == "read_file"
    assert evt.scope == "path"
    assert evt.decision == "granted"
    assert evt.reason == "path_guard:project_dir"


# --- Tool-level permission gate (PermissionScope.TOOL, extension point #9) ---
# --- 工具级权限门（PermissionScope.TOOL，拓展点 #9） ---


async def test_tool_deny_rule_blocks_tool(tool_context):
    """A TOOL deny rule blocks the tool outright, even for a harmless command.
    TOOL 拒绝规则直接拦截工具，即使命令本身无害。"""
    from mini_agent.models.permissions import PermissionLevel, PermissionRule, PermissionScope

    loop = make_secured_loop(
        [tool_call("bash", {"command": "echo hi"}), text("done")],
        tool_context,
    )
    loop._permissions.add_rule(
        PermissionRule(scope=PermissionScope.TOOL, pattern="bash", level=PermissionLevel.DENY)
    )
    conv = Conversation()
    await loop.run(conv)

    tool_msg = [m for m in conv.messages if m.role == Role.TOOL][0]
    assert tool_msg.tool_result.is_error
    assert "Permission denied" in tool_msg.tool_result.output


async def test_tool_allow_rule_skips_resource_checks(tool_context):
    """A TOOL allow rule trusts the tool wholesale: dangerous commands run
    without confirmation. TOOL 允许规则整体信任工具：危险命令不确认直接执行。"""
    from mini_agent.models.permissions import PermissionLevel, PermissionRule, PermissionScope

    asked = []

    async def confirm(prompt):
        asked.append(prompt)
        return False

    loop = make_secured_loop(
        [tool_call("bash", {"command": "rm -rf ./nonexistent || echo ran"}), text("done")],
        tool_context,
        confirm=confirm,
    )
    loop._permissions.add_rule(
        PermissionRule(scope=PermissionScope.TOOL, pattern="bash", level=PermissionLevel.ALLOW)
    )
    conv = Conversation()
    await loop.run(conv)

    tool_msg = [m for m in conv.messages if m.role == Role.TOOL][0]
    assert "Permission denied" not in tool_msg.tool_result.output
    assert asked == []  # no confirmation prompt 没有弹确认框


async def test_tool_gate_event_scope(tool_context):
    """The tool gate emits PermissionCheckEvent with scope=tool and the
    matched rule. 工具门发射 scope=tool 且带命中规则的 PermissionCheckEvent。"""
    from mini_agent.models.events import PermissionCheckEvent
    from mini_agent.models.permissions import PermissionLevel, PermissionRule, PermissionScope

    events = []

    loop = make_secured_loop(
        [tool_call("bash", {"command": "echo hi"}), text("done")],
        tool_context,
    )
    loop._permissions.add_rule(
        PermissionRule(scope=PermissionScope.TOOL, pattern="bash", level=PermissionLevel.DENY)
    )

    async def collect(e: PermissionCheckEvent) -> None:
        events.append(e)

    loop._event_bus.on(PermissionCheckEvent, collect)

    conv = Conversation()
    await loop.run(conv)

    assert len(events) == 1
    evt = events[0]
    assert evt.scope == "tool"
    assert evt.resource == "bash"
    assert evt.decision == "denied"
    assert evt.matched_rule == "deny:bash"


async def test_no_tool_rule_falls_through_to_resource_checks(tool_context):
    """Without a TOOL rule, checks fall through to command/path routing.
    无 TOOL 规则时继续走命令/路径路由。"""
    from mini_agent.models.events import PermissionCheckEvent

    f = tool_context.working_dir / "ft.txt"
    f.write_text("x", encoding="utf-8")

    events = []

    loop = make_secured_loop(
        [tool_call("read_file", {"file_path": str(f)}), text("done")],
        tool_context,
    )

    async def collect(e: PermissionCheckEvent) -> None:
        events.append(e)

    loop._event_bus.on(PermissionCheckEvent, collect)

    conv = Conversation()
    await loop.run(conv)

    assert events[0].scope == "path"
    assert events[0].decision == "granted"
