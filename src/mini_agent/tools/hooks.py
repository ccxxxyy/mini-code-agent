"""Lifecycle hooks around tool execution and LLM calls.
围绕工具执行和 LLM 调用的生命周期 hook。"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatch
from typing import Any

from mini_agent.models.message import ToolResult

log = logging.getLogger(__name__)


class HookStage(StrEnum):
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_INPUT = "user_input"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    PRE_LLM = "pre_llm"
    POST_LLM = "post_llm"
    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"


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


@dataclass
class HookRule:
    """Declarative PRE_TOOL rule from `[[hooks]]` TOML config.
    Users block tools (action="block") or require user confirmation
    (action="confirm") by config instead of writing Python hook code --
    adapted from mewcode's `reject: true` pre_tool_use hooks.
    来自 `[[hooks]]` TOML 配置的声明式 PRE_TOOL 规则——用户通过配置
    而非 Python 代码阻止工具执行（action="block"）或要求用户确认
    （action="confirm"），对标 mewcode 的 reject hook。"""

    tool: str = "*"  # fnmatch pattern on tool name 工具名 fnmatch 模式
    arg: str = ""  # optional: check only this argument 只检查此参数
    contains: str = ""  # optional: substring that triggers 触发子串
    regex: str = ""  # optional: re.search pattern that triggers 触发正则
    reason: str = ""  # message shown to the LLM 回给 LLM 的原因
    action: HookAction = HookAction.BLOCK  # block or confirm 阻止或确认

    def _value_hits(self, text: str) -> bool:
        if self.contains and self.contains not in text:
            return False
        if self.regex and not re.search(self.regex, text):
            return False
        return True

    def matches(self, tool_name: str, args: dict[str, Any] | None) -> bool:
        if not fnmatch(tool_name, self.tool):
            return False
        if not self.contains and not self.regex:
            return True
        values = args or {}
        if self.arg:
            return self._value_hits(str(values.get(self.arg, "")))
        return any(self._value_hits(str(v)) for v in values.values())


def parse_hook_rules(raw_rules: list[Any]) -> list[HookRule]:
    """Parse `[[hooks]]` TOML entries into HookRule objects. Invalid
    entries are skipped with a warning -- config mistakes must not
    break startup. 解析 `[[hooks]]` 配置条目；非法条目告警跳过，
    配置错误不能阻断启动。"""
    rules: list[HookRule] = []
    for i, entry in enumerate(raw_rules or []):
        if not isinstance(entry, dict):
            log.warning("hooks[%d]: not a table, skipped", i)
            continue
        event = entry.get("event", "pre_tool")
        if event != "pre_tool":
            log.warning("hooks[%d]: unsupported event '%s' (only 'pre_tool'), skipped", i, event)
            continue
        if not entry.get("reject", True):
            log.warning("hooks[%d]: only reject=true rules are supported, skipped", i)
            continue
        action_raw = str(entry.get("action", "block")).lower()
        if action_raw not in (HookAction.BLOCK, HookAction.CONFIRM):
            log.warning(
                "hooks[%d]: unsupported action '%s' (only 'block'/'confirm'), skipped",
                i,
                action_raw,
            )
            continue
        regex = str(entry.get("regex", ""))
        if regex:
            try:
                re.compile(regex)
            except re.error as e:
                log.warning("hooks[%d]: invalid regex '%s' (%s), skipped", i, regex, e)
                continue
        rules.append(
            HookRule(
                tool=str(entry.get("tool", "*")) or "*",
                arg=str(entry.get("arg", "")),
                contains=str(entry.get("contains", "")),
                regex=regex,
                reason=str(entry.get("reason", "")),
                action=HookAction(action_raw),
            )
        )
    return rules


class HookManager:
    """Manages registration and execution of lifecycle hooks.
    管理生命周期 hook 的注册与执行。"""

    def __init__(self) -> None:
        self._hooks: dict[HookStage, list[tuple[int, HookFn]]] = {}
        # Declarative confirm rules -- kept for the non-interactive peek
        # would_confirm() (mirrors PermissionManager.would_ask)
        # 声明式确认规则——供非交互预判 would_confirm() 使用
        # （对应 PermissionManager.would_ask）
        self._confirm_rules: list[HookRule] = []

    def register(self, stage: HookStage, hook: HookFn, priority: int = 0) -> None:
        """Register a hook. Higher priority runs first.
        注册一个 hook。优先级越高越先执行。"""
        self._hooks.setdefault(stage, []).append((priority, hook))
        self._hooks[stage].sort(key=lambda x: -x[0])

    def unregister(self, stage: HookStage, hook: HookFn) -> None:
        hooks = self._hooks.get(stage, [])
        self._hooks[stage] = [(p, h) for p, h in hooks if h is not hook]

    def track_confirm_rule(self, rule: HookRule) -> None:
        self._confirm_rules.append(rule)

    def would_confirm(self, tool_name: str, args: dict[str, Any] | None) -> bool:
        """Non-interactive peek: would a declarative rule ask for confirmation?
        Only covers `[[hooks]]` config rules -- programmatic hooks returning
        CONFIRM cannot be predicted without running them.
        非交互预判：声明式规则是否会要求确认？只覆盖 `[[hooks]]` 配置规则——
        代码注册的 hook 返回 CONFIRM 无法在不执行的情况下预测。"""
        return any(r.matches(tool_name, args) for r in self._confirm_rules)

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


def register_hook_rules(manager: HookManager, raw_rules: list[Any]) -> int:
    """Parse config rules and register them as PRE_TOOL blocking or
    confirming hooks. Returns the number of rules registered.
    解析配置规则并注册为 PRE_TOOL 阻止或确认 hook，返回注册数量。"""
    rules = parse_hook_rules(raw_rules)
    for rule in rules:

        async def _rule_hook(ctx: HookContext, _rule: HookRule = rule) -> HookResult:
            if ctx.tool_name and _rule.matches(ctx.tool_name, ctx.tool_args):
                if _rule.action == HookAction.CONFIRM:
                    reason = _rule.reason or (
                        f"tool '{ctx.tool_name}' requires confirmation (project hook rule)"
                    )
                    return HookResult(action=HookAction.CONFIRM, reason=reason)
                reason = _rule.reason or (
                    f"tool '{ctx.tool_name}' is blocked by a project hook rule"
                )
                return HookResult(action=HookAction.BLOCK, reason=reason)
            return HookResult(action=HookAction.CONTINUE)

        manager.register(HookStage.PRE_TOOL, _rule_hook)
        if rule.action == HookAction.CONFIRM:
            manager.track_confirm_rule(rule)
    return len(rules)
