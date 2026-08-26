"""Lifecycle hooks around tool execution and LLM calls.
围绕工具执行和 LLM 调用的生命周期 hook。"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatch
from typing import Any

from mini_agent.models.message import ToolResult
from mini_agent.tools.hook_conditions import (
    ConditionGroup,
    evaluate_condition,
    parse_condition,
)

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
    COMMAND = "command"
    NOTIFY = "notify"


STAGE_MAP: dict[str, HookStage] = {
    "pre_tool": HookStage.PRE_TOOL,
    "post_tool": HookStage.POST_TOOL,
}


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

CommandRunner = Callable[[str, float], Awaitable[tuple[int, str]]]


@dataclass
class HookRule:
    """Declarative rule from `[[hooks]]` TOML config.
    来自 `[[hooks]]` TOML 配置的声明式规则。

    Supports four actions:
      block   — reject tool execution (default)
      confirm — require user confirmation
      command — execute a shell command
      notify  — display a terminal notification
    """

    tool: str = "*"
    arg: str = ""
    contains: str = ""
    regex: str = ""
    reason: str = ""
    action: HookAction = HookAction.BLOCK
    condition: str = ""
    _parsed_condition: ConditionGroup | None = field(default=None, repr=False)
    command: str = ""
    command_timeout: float = 30.0
    message: str = ""
    event: str = "pre_tool"

    def _value_hits(self, text: str) -> bool:
        if self.contains and self.contains not in text:
            return False
        if self.regex and not re.search(self.regex, text):
            return False
        return True

    def matches(self, tool_name: str, args: dict[str, Any] | None, event: str = "pre_tool") -> bool:
        if self._parsed_condition is not None:
            ctx = {"tool": tool_name, "event": event, "args": args or {}}
            return evaluate_condition(self._parsed_condition, ctx)
        if not fnmatch(tool_name, self.tool):
            return False
        if not self.contains and not self.regex:
            return True
        values = args or {}
        if self.arg:
            return self._value_hits(str(values.get(self.arg, "")))
        return any(self._value_hits(str(v)) for v in values.values())


def expand_template(
    template: str,
    tool_name: str | None,
    tool_args: dict[str, Any] | None,
    stage: str = "",
    tool_result: ToolResult | None = None,
) -> str:
    """Expand $TOOL_NAME, $TOOL_ARGS.<key>, $EVENT, $RESULT in a template.
    Unknown variables are left as-is.
    """

    def _replace(m: re.Match[str]) -> str:
        full = m.group(0)
        if full == "$TOOL_NAME":
            return tool_name or ""
        if full == "$EVENT":
            return stage
        if full == "$RESULT":
            if tool_result:
                return tool_result.output or ""
            return ""
        if full == "$RESULT_ERROR":
            if tool_result:
                return "true" if tool_result.is_error else "false"
            return ""
        if full == "$TOOL_ARGS":
            return json.dumps(tool_args or {}, ensure_ascii=False)
        if full.startswith("$TOOL_ARGS."):
            key = full[len("$TOOL_ARGS.") :]
            if tool_args and key in tool_args:
                return str(tool_args[key])
            return ""
        return full

    return re.sub(r"\$TOOL_ARGS\.\w+|\$\w+", _replace, template)


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
        if event not in STAGE_MAP:
            log.warning("hooks[%d]: unsupported event '%s', skipped", i, event)
            continue
        if not entry.get("reject", True):
            log.warning("hooks[%d]: only reject=true rules are supported, skipped", i)
            continue
        action_raw = str(entry.get("action", "block")).lower()
        valid_actions = (
            HookAction.BLOCK,
            HookAction.CONFIRM,
            HookAction.COMMAND,
            HookAction.NOTIFY,
        )
        if action_raw not in valid_actions:
            log.warning(
                "hooks[%d]: unsupported action '%s', skipped",
                i,
                action_raw,
            )
            continue

        cmd = str(entry.get("command", ""))
        if action_raw == HookAction.COMMAND and not cmd:
            log.warning("hooks[%d]: action='command' requires 'command' field, skipped", i)
            continue
        msg = str(entry.get("message", ""))
        if action_raw == HookAction.NOTIFY and not msg:
            log.warning("hooks[%d]: action='notify' requires 'message' field, skipped", i)
            continue

        regex = str(entry.get("regex", ""))
        if regex:
            try:
                re.compile(regex)
            except re.error as e:
                log.warning("hooks[%d]: invalid regex '%s' (%s), skipped", i, regex, e)
                continue

        condition_str = str(entry.get("condition", ""))
        parsed_cond: ConditionGroup | None = None
        if condition_str:
            parsed_cond = parse_condition(condition_str)
            if parsed_cond is None:
                log.warning("hooks[%d]: invalid condition '%s', skipped", i, condition_str)
                continue

        rules.append(
            HookRule(
                tool=str(entry.get("tool", "*")) or "*",
                arg=str(entry.get("arg", "")),
                contains=str(entry.get("contains", "")),
                regex=regex,
                reason=str(entry.get("reason", "")),
                action=HookAction(action_raw),
                condition=condition_str,
                _parsed_condition=parsed_cond,
                command=cmd,
                command_timeout=float(entry.get("command_timeout", 30.0)),
                message=msg,
                event=event,
            )
        )
    return rules


class HookManager:
    """Manages registration and execution of lifecycle hooks.
    管理生命周期 hook 的注册与执行。"""

    def __init__(self) -> None:
        self._hooks: dict[HookStage, list[tuple[int, HookFn]]] = {}
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
        非交互预判：声明式规则是否会要求确认？"""
        return any(r.matches(tool_name, args) for r in self._confirm_rules)

    async def run(self, ctx: HookContext) -> HookResult:
        """Run all hooks for the stage in priority order.

        Short-circuits on BLOCK and CONFIRM. MODIFY updates ctx.tool_args
        and continues down the chain.
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


def register_hook_rules(
    manager: HookManager,
    raw_rules: list[Any],
    *,
    command_runner: CommandRunner | None = None,
    notify_callback: Callable[[str], None] | None = None,
) -> int:
    """Parse config rules and register them as lifecycle hooks.
    Returns the number of rules registered.
    解析配置规则并注册为生命周期 hook，返回注册数量。"""
    rules = parse_hook_rules(raw_rules)
    for rule in rules:
        stage = STAGE_MAP.get(rule.event, HookStage.PRE_TOOL)

        if rule.action == HookAction.COMMAND:
            _register_command_rule(manager, rule, stage, command_runner, notify_callback)
        elif rule.action == HookAction.NOTIFY:
            _register_notify_rule(manager, rule, stage, notify_callback)
        elif rule.action == HookAction.CONFIRM:
            _register_confirm_rule(manager, rule, stage)
        else:
            _register_block_rule(manager, rule, stage)

    return len(rules)


def _register_block_rule(manager: HookManager, rule: HookRule, stage: HookStage) -> None:
    async def _rule_hook(ctx: HookContext, _rule: HookRule = rule) -> HookResult:
        if ctx.tool_name and _rule.matches(ctx.tool_name, ctx.tool_args, _rule.event):
            reason = _rule.reason or (f"tool '{ctx.tool_name}' is blocked by a project hook rule")
            return HookResult(action=HookAction.BLOCK, reason=reason)
        return HookResult(action=HookAction.CONTINUE)

    manager.register(stage, _rule_hook)


def _register_confirm_rule(manager: HookManager, rule: HookRule, stage: HookStage) -> None:
    async def _rule_hook(ctx: HookContext, _rule: HookRule = rule) -> HookResult:
        if ctx.tool_name and _rule.matches(ctx.tool_name, ctx.tool_args, _rule.event):
            reason = _rule.reason or (
                f"tool '{ctx.tool_name}' requires confirmation (project hook rule)"
            )
            return HookResult(action=HookAction.CONFIRM, reason=reason)
        return HookResult(action=HookAction.CONTINUE)

    manager.register(stage, _rule_hook)
    manager.track_confirm_rule(rule)


def _register_command_rule(
    manager: HookManager,
    rule: HookRule,
    stage: HookStage,
    runner: CommandRunner | None,
    notify_callback: Callable[[str], None] | None = None,
) -> None:
    async def _rule_hook(
        ctx: HookContext,
        _rule: HookRule = rule,
        _runner: CommandRunner | None = runner,
        _notify: Callable[[str], None] | None = notify_callback,
    ) -> HookResult:
        if not ctx.tool_name or not _rule.matches(ctx.tool_name, ctx.tool_args, _rule.event):
            return HookResult(action=HookAction.CONTINUE)

        expanded = expand_template(
            _rule.command,
            ctx.tool_name,
            ctx.tool_args,
            stage=_rule.event,
            tool_result=ctx.tool_result,
        )

        if not _runner:
            log.warning("hook command skipped (no runner): %s", expanded)
            return HookResult(action=HookAction.CONTINUE)

        try:
            returncode, output = await _runner(expanded, _rule.command_timeout)
        except Exception:
            log.warning("hook command failed: %s", expanded, exc_info=True)
            return HookResult(action=HookAction.CONTINUE)

        if output and _notify:
            _notify(output)

        if stage == HookStage.PRE_TOOL and returncode != 0:
            reason = output or _rule.reason or "command hook rejected tool execution"
            return HookResult(action=HookAction.BLOCK, reason=reason)

        return HookResult(action=HookAction.CONTINUE)

    manager.register(stage, _rule_hook)


def _register_notify_rule(
    manager: HookManager,
    rule: HookRule,
    stage: HookStage,
    callback: Callable[[str], None] | None,
) -> None:
    async def _rule_hook(
        ctx: HookContext,
        _rule: HookRule = rule,
        _cb: Callable[[str], None] | None = callback,
    ) -> HookResult:
        if not ctx.tool_name or not _rule.matches(ctx.tool_name, ctx.tool_args, _rule.event):
            return HookResult(action=HookAction.CONTINUE)

        expanded = expand_template(
            _rule.message,
            ctx.tool_name,
            ctx.tool_args,
            stage=_rule.event,
            tool_result=ctx.tool_result,
        )

        if _cb:
            try:
                _cb(expanded)
            except Exception:
                log.warning("hook notify callback failed", exc_info=True)
        else:
            log.info("hook notify: %s", expanded)

        return HookResult(action=HookAction.CONTINUE)

    manager.register(stage, _rule_hook)
