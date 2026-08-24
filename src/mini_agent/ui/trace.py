"""Trace renderer -- real-time display of agent internals (for /trace).
Trace 渲染器——实时展示 Agent 内部状态（用于 /trace）。

A pure EventBus subscriber: zero intrusion into the ReAct loop.
纯 EventBus 订阅者：对 ReAct 循环零侵入。
"""

from __future__ import annotations

from datetime import datetime

from rich.console import Console

from mini_agent.events.bus import EventBus
from mini_agent.models.events import (
    AgentPhaseChangeEvent,
    ContextSummaryDoneEvent,
    ContextSummaryStartEvent,
    LLMRequestEvent,
    LLMResponseEvent,
    PermissionCheckEvent,
    PermissionModeChangedEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    TurnCompleteEvent,
    UserMessageEvent,
)
from mini_agent.ui.themes import Theme, get_theme


def _ts() -> str:
    """Current time as HH:MM:SS.mmm"""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class TraceRenderer:
    """Renders agent internal events as dim trace lines.
    以暗色 trace 行渲染 Agent 内部事件。
    """

    def __init__(self, console: Console, theme: Theme | None = None) -> None:
        self._console = console
        self.theme = theme or get_theme("default")
        self.enabled: bool = False

    def attach(self, bus: EventBus) -> None:
        """Subscribe to all traceable events. 订阅所有可追踪事件。"""
        bus.on(AgentPhaseChangeEvent, self._on_phase)
        bus.on(PermissionCheckEvent, self._on_permission)
        bus.on(ToolCallStartEvent, self._on_tool_start)
        bus.on(ToolCallEndEvent, self._on_tool_end)
        bus.on(LLMRequestEvent, self._on_llm_request)
        bus.on(LLMResponseEvent, self._on_llm_response)
        bus.on(TurnCompleteEvent, self._on_turn_complete)
        bus.on(UserMessageEvent, self._on_user_message)
        bus.on(ContextSummaryStartEvent, self._on_ctx_summary_start)
        bus.on(ContextSummaryDoneEvent, self._on_ctx_summary_done)
        bus.on(PermissionModeChangedEvent, self._on_mode_changed)

    def detach(self, bus: EventBus) -> None:
        """Unsubscribe all handlers. 取消所有订阅。"""
        bus.off(AgentPhaseChangeEvent, self._on_phase)
        bus.off(PermissionCheckEvent, self._on_permission)
        bus.off(ToolCallStartEvent, self._on_tool_start)
        bus.off(ToolCallEndEvent, self._on_tool_end)
        bus.off(LLMRequestEvent, self._on_llm_request)
        bus.off(LLMResponseEvent, self._on_llm_response)
        bus.off(TurnCompleteEvent, self._on_turn_complete)
        bus.off(UserMessageEvent, self._on_user_message)
        bus.off(ContextSummaryStartEvent, self._on_ctx_summary_start)
        bus.off(ContextSummaryDoneEvent, self._on_ctx_summary_done)
        bus.off(PermissionModeChangedEvent, self._on_mode_changed)

    def _line(self, kind: str, body: str) -> None:
        """Print one trace line. 输出一行 trace。"""
        self._console.print(
            f"  [dim]trace \\[{_ts()}] {kind:5s}[/dim] {body}",
            highlight=False,
        )

    async def _on_phase(self, e: AgentPhaseChangeEvent) -> None:
        if not self.enabled:
            return
        p = self.theme.primary
        self._line(
            "iter",
            f"[dim]{e.iteration}[/dim]  [{p}]{e.old_phase}[/{p}] "
            f"[dim]->[/dim] [{p}]{e.new_phase}[/{p}]",
        )

    async def _on_mode_changed(self, e: PermissionModeChangedEvent) -> None:
        if not self.enabled:
            return
        w = self.theme.warning
        self._line("mode", f"[{w}]{e.old_mode}[/{w}] [dim]->[/dim] [{w}]{e.new_mode}[/{w}]")

    async def _on_permission(self, e: PermissionCheckEvent) -> None:
        if not self.enabled:
            return
        if e.decision == "pending":
            color = self.theme.warning
            label = "PENDING (awaiting user)"
        elif e.decision == "granted":
            color = self.theme.success
            label = "GRANTED"
        else:
            color = self.theme.error
            label = e.decision.upper()
        self._line(
            "perm",
            f"{e.scope} [dim]{e.resource[:60]}[/dim] [dim]->[/dim] "
            f"[{color}]{label}[/{color}] [dim]({e.reason})[/dim]",
        )

    async def _on_tool_start(self, e: ToolCallStartEvent) -> None:
        if not self.enabled:
            return
        p = self.theme.primary
        preview = ", ".join(f"{k}={str(v)[:40]}" for k, v in list(e.arguments.items())[:3])
        self._line("tool", f"[{p}]{e.tool_name}[/{p}] start  [dim]{preview}[/dim]")

    async def _on_tool_end(self, e: ToolCallEndEvent) -> None:
        if not self.enabled:
            return
        p = self.theme.primary
        e_c = self.theme.error
        s_c = self.theme.success
        mark = f"[{e_c}]FAIL[/{e_c}]" if e.is_error else f"[{s_c}]OK[/{s_c}]"
        self._line(
            "tool", f"[{p}]{e.tool_name}[/{p}] done   [dim]{e.duration_ms:.0f}ms[/dim] {mark}"
        )

    async def _on_user_message(self, e: UserMessageEvent) -> None:
        if not self.enabled:
            return
        tag = " [dim]\\[slash][/dim]" if e.is_slash_command else ""
        self._line("user", f'[dim]"{e.content[:60]}"[/dim]{tag}')

    async def _on_llm_request(self, e: LLMRequestEvent) -> None:
        if not self.enabled:
            return
        tok = f", ~{e.estimated_tokens} tok" if e.estimated_tokens else ""
        self._line("llm", f"request  [dim]{e.message_count} msgs, {e.tool_count} tools{tok}[/dim]")

    async def _on_llm_response(self, e: LLMResponseEvent) -> None:
        if not self.enabled:
            return
        tc = str(e.has_tool_calls).lower()
        self._line("llm", f"response [dim]{e.tokens_used} tokens, tool_calls={tc}[/dim]")

    async def _on_ctx_summary_start(self, e: ContextSummaryStartEvent) -> None:
        if not self.enabled:
            return
        self._line("ctx", "summarizing parent conversation for fork...")

    async def _on_ctx_summary_done(self, e: ContextSummaryDoneEvent) -> None:
        if not self.enabled:
            return
        self._line(
            "ctx",
            f"summary ready  [dim]{e.duration_ms:.0f}ms, {e.char_count} chars[/dim]",
        )

    async def _on_turn_complete(self, e: TurnCompleteEvent) -> None:
        if not self.enabled:
            return
        self._line(
            "turn",
            f"complete [dim]{e.iteration_count} iterations, "
            f"{e.tools_called} tools, {e.tokens_used} tokens[/dim]",
        )
