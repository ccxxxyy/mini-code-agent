"""Lifecycle hooks around tool execution and LLM calls.
围绕工具执行和 LLM 调用的生命周期 hook。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from mini_agent.models.message import ToolResult


class HookStage(StrEnum):
    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"
    PRE_LLM = "pre_llm"
    POST_LLM = "post_llm"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_INPUT = "user_input"


class HookAction(StrEnum):
    CONTINUE = "continue"
    BLOCK = "block"
    MODIFY = "modify"
    CONFIRM = "confirm"


@dataclass
class HookContext:
    stage: HookStage
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: ToolResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    action: HookAction = HookAction.CONTINUE
    modified_args: dict[str, Any] | None = None
    reason: str = ""


HookFn = Callable[[HookContext], Awaitable[HookResult]]


class HookManager:
    """Manages registration and execution of lifecycle hooks.
    管理生命周期 hook 的注册与执行。"""

    def __init__(self) -> None:
        self._hooks: dict[HookStage, list[tuple[int, HookFn]]] = {}

    def register(self, stage: HookStage, hook: HookFn, priority: int = 0) -> None:
        """Register a hook. Higher priority runs first.
        注册一个 hook。优先级越高越先执行。"""
        self._hooks.setdefault(stage, []).append((priority, hook))
        self._hooks[stage].sort(key=lambda x: -x[0])

    def unregister(self, stage: HookStage, hook: HookFn) -> None:
        hooks = self._hooks.get(stage, [])
        self._hooks[stage] = [(p, h) for p, h in hooks if h is not hook]

    async def run(self, ctx: HookContext) -> HookResult:
        """Run all hooks for the stage in priority order.

        Short-circuits on BLOCK and CONFIRM. MODIFY updates ctx.tool_args
        and continues down the chain.

        按优先级顺序运行该阶段的所有 hook。
        遇到 BLOCK 和 CONFIRM 时短路返回。MODIFY 会更新 ctx.tool_args
        并继续执行链上后续 hook。
        """
        final = HookResult(action=HookAction.CONTINUE)
        for _priority, hook in self._hooks.get(ctx.stage, []):
            result = await hook(ctx)
            if result.action == HookAction.BLOCK:
                return result
            if result.action == HookAction.CONFIRM:
                return result
            if result.action == HookAction.MODIFY and result.modified_args is not None:
                ctx.tool_args = result.modified_args
                final = result
        return final
