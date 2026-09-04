"""ReAct agent loop -- the heart of the system."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mini_agent.core.mailbox import Mailbox
    from mini_agent.memory.file_snapshots import FileSnapshotStore
    from mini_agent.memory.tool_result_cache import ToolResultCache

from mini_agent.core.agent_state import AgentPhase, AgentState
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, LLMResponse, StreamChunk, assemble_response
from mini_agent.memory.context import ContextManager
from mini_agent.models.config import AgentConfig
from mini_agent.models.events import (
    AgentPhaseChangeEvent,
    LLMRequestEvent,
    LLMResponseEvent,
    PermissionCheckEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    TurnCompleteEvent,
)
from mini_agent.models.message import Conversation, Message, Role, ToolCall, ToolResult
from mini_agent.models.permissions import PermissionDecision, PermissionMode, ToolCategory
from mini_agent.security.permission import PermissionManager
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.hooks import HookAction, HookContext, HookManager, HookStage

logger = logging.getLogger(__name__)

# Callback invoked with each streaming text delta (for UI rendering)
# 每次收到流式文本增量时调用的回调（用于 UI 渲染）
StreamCallback = Callable[[str], None]
# Callbacks invoked when a tool starts / finishes (for UI rendering)
# 工具开始 / 结束时调用的回调（用于 UI 渲染）
ToolStartCallback = Callable[[ToolCall], None]
ToolEndCallback = Callable[[ToolResult, float], None]


# Human/LLM-readable hints per denial reason: without the WHY the LLM burns
# tokens investigating configs instead of adapting (real-run: 50K tokens
# spent hunting a nonexistent rule after a bare "Permission denied").
# 拒绝原因的可读提示：不带原因 LLM 会烧 token 排查配置而不是调整策略
# （实测：光秃秃的 Permission denied 后烧了 5 万 token 找不存在的规则）。
_DENY_REASON_HINTS = {
    "mode:plan": "read-only plan mode — ask the user to approve exiting plan mode first",
    "path_guard:sensitive": "sensitive path (keys/credentials), protected in every mode",
    "user_confirm:no": "the user denied the confirmation",
    "no_ui:default_deny": (
        "confirmation required but no interactive user is available — "
        "denied fail-safe, do NOT retry via alternative routes"
    ),
}


def _denied_message(tool_name: str, reason: str) -> str:
    """Denial message carrying the reason so the LLM can adapt instead of
    guessing. 带原因的拒绝消息——LLM 能据此调整而不是瞎猜。"""
    if not reason:
        return f"Permission denied for {tool_name}"
    hint = _DENY_REASON_HINTS.get(reason.split(" — ")[0], "")
    suffix = f" — {hint}" if hint and "—" not in reason else ""
    return f"Permission denied for {tool_name} (reason: {reason}{suffix})"


def _mail_prefix(mail) -> str:
    """Format the injection prefix by message type (structured protocol).
    按消息类型格式化注入前缀（结构化协议）。"""
    if mail.type == "request":
        return f"[Request from agent '{mail.sender}' request_id={mail.request_id}]"
    if mail.type == "response":
        approve = "" if mail.approve is None else f" approve={str(mail.approve).lower()}"
        return f"[Response from agent '{mail.sender}' request_id={mail.request_id}{approve}]"
    return f"[Message from agent '{mail.sender}']"


VERIFY_NUDGE = (
    "Spot-check 2-3 key numbers or claims in your response using tools. "
    "If all correct, reply with one sentence: 'Verified, no corrections.' "
    "If any are wrong, reply with ONLY the corrections (e.g., "
    "'Correction: X is actually Y'). Do NOT rewrite or repeat the full answer."
)


class IncrementalAssembler:
    """Detects completed tool calls mid-stream.
    在流式过程中检测已组装完成的工具调用。

    Chat Completions streams tool calls sequentially: a delta with a NEW
    (higher) index means all lower indexes are complete; finish_reason
    closes the last open index. This mirrors assemble_response's builder
    logic, but flushes ToolCalls as soon as they are known complete.
    Chat Completions 按顺序流式传输工具调用：出现更高 index 的 delta
    意味着所有更低的 index 已完成；finish_reason 关闭最后一个未完成的
    index。与 assemble_response 的 builder 逻辑一致，但一旦确定完成就
    立刻产出 ToolCall。
    """

    def __init__(self) -> None:
        self._builders: dict[int, dict[str, str]] = {}
        self._flushed: set[int] = set()

    def feed(self, chunk: StreamChunk) -> list[ToolCall]:
        """Feed one chunk; return tool calls that just became complete.
        喂入一个 chunk；返回本次新确定完成的工具调用。"""
        completed: list[ToolCall] = []
        for tcd in chunk.tool_call_deltas:
            if tcd.index not in self._builders:
                # New index opens -> all lower indexes are complete
                # 新 index 开启 -> 所有更低的 index 已完成
                for idx in sorted(self._builders):
                    if idx < tcd.index and idx not in self._flushed:
                        completed.append(self._flush(idx))
                self._builders[tcd.index] = {"id": "", "name": "", "arguments": ""}
            b = self._builders[tcd.index]
            if tcd.id:
                b["id"] = tcd.id
            if tcd.name:
                b["name"] = tcd.name
            if tcd.arguments_delta:
                b["arguments"] += tcd.arguments_delta
        if chunk.finish_reason:
            for idx in sorted(self._builders):
                if idx not in self._flushed:
                    completed.append(self._flush(idx))
        return completed

    def _flush(self, idx: int) -> ToolCall:
        import json as _json

        self._flushed.add(idx)
        b = self._builders[idx]
        raw = b["arguments"]
        try:
            parsed = _json.loads(raw) if raw else {}
        except _json.JSONDecodeError:
            parsed = {}
        return ToolCall(id=b["id"], name=b["name"], arguments=parsed, raw_arguments=raw)


class AgentLoop:
    """Orchestrates the think-act-observe ReAct cycle. 编排“思考-行动-观察”的 ReAct 循环。"""

    MAX_TOKENS_RETRIES = 3

    def __init__(
        self,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        event_bus: EventBus,
        config: AgentConfig,
        tool_context: ToolContext,
        permission_manager: PermissionManager | None = None,
        hook_manager: HookManager | None = None,
        context_manager: ContextManager | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tool_registry
        self._event_bus = event_bus
        self._config = config
        self._tool_context = tool_context
        self._permissions = permission_manager
        self._hooks = hook_manager or HookManager()
        self._context = context_manager
        self._state = AgentState(max_iterations=config.max_agent_iterations)
        self._cancelled = False
        # CONFIRM hook resolution: UI callback injected by app.py -- hooks
        # themselves hold no UI reference (tool layer must not depend on the
        # interaction layer), so the loop resolves CONFIRM verdicts.
        # CONFIRM hook 裁决：app.py 注入 UI 回调——hook 本身不持有 UI 引用
        # （工具层不依赖交互层），由循环负责执行确认。
        self.confirm_callback: Callable[[str], Awaitable[bool | str]] | None = None
        # "always" grants for this session, keyed by (tool_name, reason)
        # 本会话内 "always" 授权，按 (工具名, 原因) 记录
        self._hook_confirm_grants: set[tuple[str, str]] = set()
        # Confirm dialogs must not interleave (parallel tool execution)
        # 确认弹窗不可交错（工具并行执行时）
        self._confirm_lock = asyncio.Lock()

        self.on_stream_delta: StreamCallback | None = None
        self.on_stream_start: Callable[[], None] | None = None
        self.on_stream_end: Callable[[str], None] | None = None
        self.on_thinking_delta: Callable[[str], None] | None = None
        self.on_tool_start: ToolStartCallback | None = None
        self.on_tool_end: ToolEndCallback | None = None
        self.on_tool_call_assembling: Callable[[str], None] | None = None
        self.last_turn_tokens: int = 0
        # Files created/modified during the last run() 上一轮新建/修改的文件
        self.last_turn_file_changes: list[tuple[str, str]] = []
        self._file_changes: dict[str, str] = {}
        # Optional per-turn file snapshots for operation-level undo (app injects)
        # 可选的每轮文件快照——操作级撤销（app.py 注入）
        self.snapshot_store: FileSnapshotStore | None = None
        # Optional spill-to-disk cache for oversized tool results (app injects)
        # 可选的超大工具结果溢写缓存（app.py 注入）
        self.result_cache: ToolResultCache | None = None
        # Tasks submitted mid-stream (streaming tool execution), keyed by call id
        # 流式期间提交的执行任务（按 call id 索引）
        self._streaming_tasks: dict[str, asyncio.Task[Any] | asyncio.Future[ToolResult]] = {}
        self.current_turn_id: int = 0
        # Model name for cost attribution (app/subagent manager sets it)
        # 模型名——供成本归属（app/subagent manager 设置）
        self.model_name: str = ""
        # True when the last run() ended via circuit breaker, not a natural answer
        # 上一次 run() 是否因熔断（而非自然回答）结束
        self.stopped_early: bool = False
        # Which circuit breaker fired ("" = none / iteration / loop guard).
        # "confirm_denied" = user denied a confirm (dangerous command / path
        # outside project / hook) -> stop the goal (default threshold 1).
        # 哪个熔断触发（""=无/迭代/死循环守卫）；"confirm_denied"=用户拒绝了
        # 确认框（危险命令/项目外路径/hook）（默认阈值 1，拒一次即停）。
        self.stop_reason: str = ""
        self.plan_mode: bool = False
        # Cross-agent mailbox: drained at the start of each iteration (app/subagent injects)
        # 跨 Agent 收件箱——每轮开始前 drain（app/subagent 注入）
        self.mailbox: Mailbox | None = None
        self.agent_id: str = "main"

    @property
    def state(self) -> AgentState:
        return self._state

    def cancel(self) -> None:
        self._cancelled = True
        for task in self._streaming_tasks.values():
            task.cancel()
        self._streaming_tasks = {}

    async def run(self, conversation: Conversation) -> str:
        """Execute the full ReAct loop. Appends messages to the conversation.
        Returns the final assistant text response.
        执行完整的 ReAct 循环，将消息追加到会话中，返回助手最终的文本回复。
        """
        self._cancelled = False
        self._state = AgentState(max_iterations=self._config.max_agent_iterations)
        self.stopped_early = False
        self.stop_reason = ""
        self._file_changes = {}
        self._streaming_tasks = {}
        if self.snapshot_store:
            self.current_turn_id += 1
            self.snapshot_store.begin_turn(self.current_turn_id)
        tools_called = 0
        tokens_used = 0
        final_content = ""
        verified = False
        # Aggregate spill budget: cumulative tool-result chars this turn --
        # per-batch checks miss many small batches adding up across iterations
        # 聚合溢写预算：本轮累计工具结果字符——只看单批会漏掉多次迭代累加
        turn_result_chars = 0

        try:
            await self._hooks.run(
                HookContext(
                    stage=HookStage.TURN_START,
                    metadata={"turn_id": self.current_turn_id},
                )
            )
        except Exception:
            logger.warning("hook fire failed: turn-start", exc_info=True)
            pass

        while True:
            self._state.iteration += 1

            # Deliver incoming cross-agent messages before thinking
            # 思考前投递跨 Agent 消息
            self._deliver_mail(conversation)

            # THINK
            await self._transition(AgentPhase.THINKING)
            response = await self._think(conversation)

            # Record assistant message (store thinking in metadata for
            # round-trip -- Responses API sends it back as reasoning items)
            # 记录助手消息（thinking 存 metadata 供 round-trip——Responses
            # API 将其作为 reasoning 项回传）
            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=response.content,
                tool_calls=response.tool_calls,
            )
            if response.thinking:
                assistant_msg.metadata["thinking"] = response.thinking
                if response.thinking_signature:
                    assistant_msg.metadata["thinking_signature"] = response.thinking_signature
            if response.usage:
                # completion_tokens (this message's own size), NOT total_tokens:
                # total includes the whole prompt, so summing it per message
                # would count the conversation N times over.
                # 用 completion_tokens（本消息自身大小）而非 total_tokens：
                # total 含整个 prompt，按消息累加会把对话重复算 N 遍。
                assistant_msg.token_count = response.usage.completion_tokens or None
                tokens_used += response.usage.total_tokens
            conversation.append(assistant_msg)
            if response.usage and self._context:
                self._context.record_api_usage(conversation, response.usage)

            # No tool calls -> final answer
            if not response.tool_calls:
                # Self-verify: one chance to check unverified claims
                # 自检：给 LLM 一次机会检查未验证的断言
                if self._config.self_verify and not verified and self._state.iteration > 1:
                    verified = True
                    conversation.append(Message(role=Role.USER, content=VERIFY_NUDGE))
                    continue

                # Cancel orphan streaming tasks (partial stream after cancel)
                # 取消孤儿流式任务（中断后流不完整时可能残留）
                for task in self._streaming_tasks.values():
                    task.cancel()
                self._streaming_tasks = {}
                # Clean up verify nudge from conversation history
                # 从会话历史中清理自检消息
                if verified:
                    conversation.messages = [
                        m
                        for m in conversation.messages
                        if not (m.role == Role.USER and m.content == VERIFY_NUDGE)
                    ]
                final_content = response.content
                await self._transition(AgentPhase.RESPONDING)
                break

            # ACT
            await self._transition(AgentPhase.TOOL_CALLING)
            results = await self._act(response.tool_calls)
            tools_called += len(results)
            self._state.record_iteration_tools({tc.name for tc in response.tool_calls})

            # OBSERVE
            await self._transition(AgentPhase.OBSERVING)
            # Aggregate budget: single-result threshold cannot catch many
            # results that are each under it but together blow the context
            # 聚合预算：单条阈值管不住"每条都不超、合计撑爆"的场景
            if self.result_cache is not None:
                exempt_ids = {
                    tc.id
                    for tc in response.tool_calls
                    if self.result_cache.is_spill_readback(tc.name, tc.arguments)
                }
                results = self.result_cache.spill_batch(
                    results, already_used=turn_result_chars, exempt_ids=exempt_ids
                )
            turn_result_chars += sum(len(r.output) for r in results)
            for result in results:
                conversation.append(Message(role=Role.TOOL, tool_result=result))
            self._state.last_tool_results = results

            # Context compression check
            if self._context:
                await self._context.check_and_compress(conversation)

            if not self._should_continue():
                if self.stop_reason == "confirm_denied":
                    final_content = (
                        "已停止对这个目标的尝试——你拒绝了一个需要确认的操作。"
                        "请告诉我你希望如何处理，或者确认是否放弃。"
                    )
                else:
                    final_content = response.content or "(stopped: iteration limit or cancellation)"
                self.stopped_early = True
                await self._transition(AgentPhase.TERMINATED)
                break

        await self._transition(AgentPhase.IDLE)
        self.last_turn_tokens = tokens_used
        self.last_turn_file_changes = [(t, p) for p, t in self._file_changes.items()]
        await self._event_bus.emit(
            TurnCompleteEvent(
                iteration_count=self._state.iteration,
                tools_called=tools_called,
                tokens_used=tokens_used,
            )
        )
        try:
            await self._hooks.run(
                HookContext(
                    stage=HookStage.TURN_END,
                    metadata={
                        "turn_id": self.current_turn_id,
                        "iteration_count": self._state.iteration,
                        "tools_called": tools_called,
                        "tokens_used": tokens_used,
                    },
                )
            )
        except Exception:
            logger.warning("hook fire failed: turn-end", exc_info=True)
            pass
        return final_content

    def _deliver_mail(self, conversation: Conversation) -> None:
        """Drain this agent's inbox and append messages to the conversation.
        清空本 Agent 收件箱，将消息追加进会话。"""
        if self.mailbox is None:
            return
        try:
            incoming = self.mailbox.drain(self.agent_id)
        except Exception:
            logger.debug("mailbox drain failed", exc_info=True)
            return
        for mail in incoming:
            conversation.append(
                Message(role=Role.USER, content=f"{_mail_prefix(mail)}: {mail.content}")
            )

    async def _think(self, conversation: Conversation) -> LLMResponse:
        """Call LLM with streaming; assemble the full response.
        以 stream 方式调用 LLM 并组装完整响应。
        """
        api_messages = conversation.to_api_messages()
        tool_schemas = self._tools.get_schemas()
        if self.plan_mode:
            tool_schemas = [
                s
                for s in tool_schemas
                if self._category(s["function"]["name"]) is not ToolCategory.WRITE
            ]

        estimated = self._context.total_tokens if self._context else 0
        await self._event_bus.emit(
            LLMRequestEvent(
                message_count=len(api_messages),
                tool_count=len(tool_schemas),
                estimated_tokens=estimated,
            )
        )

        # PRE_LLM hook: can inject memories, block LLM call, etc.
        # PRE_LLM hook：可注入记忆、阻止 LLM 调用等
        pre_llm_ctx = HookContext(
            stage=HookStage.PRE_LLM,
            metadata={"message_count": len(api_messages), "tool_count": len(tool_schemas)},
        )
        sp_before_hook = conversation.system_prompt
        pre_llm_result = await self._hooks.run(pre_llm_ctx)
        if pre_llm_result.action == HookAction.BLOCK:
            return LLMResponse(content=pre_llm_result.reason or "(blocked by PRE_LLM hook)")
        # api_messages was snapshotted above -- without a rebuild, a hook's
        # system_prompt edit (memory injection) would only reach the NEXT
        # LLM call, one round late (latent since selective recall landed,
        # exposed by real-run)
        # api_messages 在上方已快照——不重建的话 hook 对 system_prompt 的
        # 修改（记忆注入）只能进下一次 LLM 调用，晚一轮生效
        if conversation.system_prompt != sp_before_hook:
            api_messages = conversation.to_api_messages()

        # Context compression: check BEFORE every LLM call (not just after
        # tool results) so pure-conversation turns also get compressed.
        # 上下文压缩：每次 LLM 调用前检查（不仅在工具结果后），
        # 纯对话轮次也能触发压缩。
        if self._context:
            compressed = await self._context.check_and_compress(conversation)
            if compressed:
                api_messages = conversation.to_api_messages()

        # Context overflow guard: force-truncate if still over window
        # 上下文溢出兜底：超窗口时强制截断，防 API 400
        if self._context:
            truncated = await self._context.ensure_fits(conversation, self._llm.context_window)
            if truncated:
                api_messages = conversation.to_api_messages()

        # max_tokens recovery: if the response was cut off (finish_reason
        # "length"), retry with a doubled limit -- up to 3 retries, keeping
        # the last result if still truncated.
        # max_tokens 恢复：回答被截断（finish_reason "length"）时翻倍限制
        # 重试——最多 3 次，仍截断则保留最后一次结果。

        retry_max_tokens = 0  # 0 = provider uses its configured default
        # Cross-attempt cache: eagerly completed tasks whose results must not
        # be re-executed on retry. Key = "name\0args_json". Lives only within
        # this _think() call -- no cross-iteration or cross-turn leakage.
        # 跨 attempt 缓存：已 eager 完成的任务结果在重试时复用，不重跑。
        # Key = "name\0args_json"。仅存活于本次 _think() 调用内。
        self._eager_completed: dict[str, ToolResult] = {}
        self._eager_keys: dict[str, str] = {}  # tc.id -> cache key

        for _attempt in range(1 + self.MAX_TOKENS_RETRIES):
            response = await self._stream_once(
                api_messages, tool_schemas, max_tokens=retry_max_tokens
            )
            if response.finish_reason != "length" or self._cancelled:
                break
            # Salvage results from eagerly completed tasks before cancelling
            # the rest -- an already-finished side-effecting command (mkdir,
            # npm install, ...) cannot be rolled back; re-executing it on
            # retry would be a double side effect. Incomplete tasks get
            # cancelled as before (their args may be cut mid-JSON anyway).
            # 取消前抢救已完成的 eager 任务结果——已结束的副作用命令
            # （mkdir / npm install 等）无法回滚，重试时重跑会产生双副作用。
            # 未完成任务照旧取消（参数可能被 JSON 截断）。
            for tc_id, task in self._streaming_tasks.items():
                if task.done() and not task.cancelled():
                    try:
                        key = self._eager_keys.get(tc_id)
                        if key:
                            self._eager_completed[key] = task.result()
                    except Exception:
                        pass
                else:
                    task.cancel()
            self._streaming_tasks = {}
            self._eager_keys = {}
            retry_max_tokens = (retry_max_tokens or self._config.llm.max_tokens) * 2
        return response

    async def _stream_once(
        self,
        api_messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        max_tokens: int = 0,
    ) -> LLMResponse:
        """Single streaming LLM call; assembles chunks into a response.
        单次流式 LLM 调用，将 chunk 组装为完整响应。"""
        chunks: list[StreamChunk] = []
        stream_started = False
        _stream_text_parts: list[str] = []
        _thinking_parts: list[str] = []
        assembler = IncrementalAssembler()
        streaming_enabled = self._config.streaming_tool_execution
        extra: dict[str, Any] = {"max_tokens": max_tokens} if max_tokens else {}

        async for chunk in self._llm.stream(api_messages, tools=tool_schemas or None, **extra):
            if self._cancelled:
                break
            chunks.append(chunk)
            if chunk.thinking:
                _thinking_parts.append(chunk.thinking)
                if not stream_started:
                    stream_started = True
                    if self.on_stream_start:
                        self.on_stream_start()
                if self.on_thinking_delta:
                    self.on_thinking_delta(chunk.thinking)
            if chunk.delta:
                if not stream_started:
                    stream_started = True
                    if self.on_stream_start:
                        self.on_stream_start()
                _stream_text_parts.append(chunk.delta)
                if self.on_stream_delta:
                    self.on_stream_delta(chunk.delta)
            if chunk.tool_call_deltas and self.on_tool_call_assembling:
                for tcd in chunk.tool_call_deltas:
                    if tcd.name:
                        self.on_tool_call_assembling(tcd.name)
            # Streaming tool execution: submit each tool call the moment it
            # finishes assembling -- tool #1 runs while tool #2 still streams.
            # Tools that would pop a confirm dialog are deferred to _act()
            # (dialogs cannot interleave with live stream rendering).
            # 流式工具执行：工具调用一组装完成就提交——工具 #1 执行时
            # 工具 #2 还在流式传输。会弹确认框的延迟到 _act()（弹窗不能
            # 和流式渲染交错）。
            if streaming_enabled:
                for tc in assembler.feed(chunk):
                    if not tc.name or not tc.id:
                        continue
                    if self._category(tc.name) is ToolCategory.WRITE:
                        # Never eager-execute write tools mid-stream: a
                        # truncated response (finish_reason="length") triggers
                        # a retry, but an already-completed side-effecting task
                        # cannot be rolled back -- task.cancel() is a no-op on a
                        # done task -> double write/delete. Defer to _act, which
                        # runs only after max_tokens recovery settles on a final
                        # non-truncated response. (Also covers plan-mode denial,
                        # handled in _act.)
                        # 写工具绝不在流式期间抢先执行：截断响应会触发重试，
                        # 但已完成的副作用任务无法回滚（task.cancel() 对已完成
                        # 任务是空操作）→ 重复写/删。延迟到 _act——它只在
                        # max_tokens 恢复确定最终非截断响应后才执行。
                        # （同时覆盖 plan 模式拒绝，由 _act 处理。）
                        continue
                    tool_obj = self._tools.get(tc.name)
                    if tool_obj is not None and tool_obj.opens_dialog:
                        # Dialog tools (ask_user, exit_plan_mode) cannot
                        # interleave with live rendering -> defer to _act.
                        # 对话框工具不能和流式渲染交错 -> 延迟到 _act。
                        continue
                    if self._permissions is not None and self._permissions.would_ask(
                        tc.name, tc.arguments, category=self._category(tc.name)
                    ):
                        continue  # deferred to _act 延迟到 _act
                    if self._hooks.would_confirm(tc.name, tc.arguments):
                        continue  # confirm dialog -> deferred to _act 确认弹窗延迟到 _act
                    # Cross-attempt dedup: if a prior truncated attempt
                    # already completed this exact (name, args) command,
                    # reuse the cached result instead of re-executing --
                    # an already-committed side effect cannot be undone.
                    # 跨 attempt 去重：若上一次截断 attempt 已完成同一
                    # (name, args) 命令，复用缓存结果而非重跑——已提交
                    # 的副作用无法撤销。
                    import json as _json

                    _cache_key = (
                        tc.name
                        + "\0"
                        + _json.dumps(tc.arguments, sort_keys=True, ensure_ascii=False)
                    )
                    cached = self._eager_completed.get(_cache_key)
                    if cached is not None:
                        fut: asyncio.Future[ToolResult] = asyncio.get_running_loop().create_future()
                        fut.set_result(
                            ToolResult(
                                call_id=tc.id,
                                name=cached.name,
                                output=cached.output,
                                is_error=cached.is_error,
                            )
                        )
                        self._streaming_tasks[tc.id] = fut
                    else:
                        self._streaming_tasks[tc.id] = asyncio.create_task(
                            self._execute_single_tool(tc)
                        )
                    self._eager_keys[tc.id] = _cache_key

        if stream_started and self.on_stream_end:
            self.on_stream_end("".join(_stream_text_parts))

        response = assemble_response(chunks)
        response.model = self.model_name
        usage = response.usage
        await self._event_bus.emit(
            LLMResponseEvent(
                content=response.content[:100],
                has_tool_calls=bool(response.tool_calls),
                tokens_used=usage.total_tokens if usage else 0,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                model=self.model_name,
                cache_read_input_tokens=usage.cache_read_input_tokens if usage else 0,
                cache_creation_input_tokens=usage.cache_creation_input_tokens if usage else 0,
            )
        )
        # POST_LLM hook: observe-only (mirrors POST_TOOL)
        # POST_LLM hook：仅观察（与 POST_TOOL 一致）
        try:
            await self._hooks.run(
                HookContext(
                    stage=HookStage.POST_LLM,
                    metadata={
                        "content_preview": response.content[:200],
                        "has_tool_calls": bool(response.tool_calls),
                        "finish_reason": response.finish_reason,
                    },
                )
            )
        except Exception:
            logger.warning("hook fire failed: post-LLM", exc_info=True)
            pass
        return response

    async def _act(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Execute tool calls with parallel optimization.
        并行优化的工具调用执行。

        Phase 1: sequential permission pre-check (confirmations must not
        interleave). Phase 2: all GRANTED tools execute in parallel via
        asyncio.gather.
        阶段 1：串行权限预检（确认弹窗不可交错）。
        阶段 2：所有 GRANTED 的工具通过 asyncio.gather 并行执行。
        """
        n = len(tool_calls)
        # Tasks already submitted mid-stream (streaming tool execution)
        # 流式期间已提交的任务
        streaming = self._streaming_tasks
        self._streaming_tasks = {}

        # --- Phase 1: sequential permission pre-check (skip streamed ones) ---
        # Capture the denial reason per tool: last_decision_reason is shared
        # manager state and would be stale by result-build time.
        # 逐工具捕获拒绝原因：last_decision_reason 是共享状态，结果构建时会过期。
        decisions: list[PermissionDecision | None] = []
        deny_reasons: list[str] = []
        for tc in tool_calls:
            if tc.id in streaming:
                decisions.append(PermissionDecision.GRANTED)  # already running 已在执行
                deny_reasons.append("")
                continue
            if self.plan_mode and self._category(tc.name) is ToolCategory.WRITE:
                decisions.append(PermissionDecision.DENIED)
                deny_reasons.append("mode:plan — read-only plan mode blocks write tools")
                continue
            if self._cancelled:
                decisions.append(None)
                deny_reasons.append("")
                continue
            if self._permissions is not None:
                decisions.append(await self._check_permission(tc))
                deny_reasons.append(self._permissions.last_decision_reason)
            else:
                decisions.append(PermissionDecision.GRANTED)
                deny_reasons.append("")

        # --- Phase 2: parallel execution / collect streamed results ---
        async def _run_one(i: int) -> ToolResult:
            tc = tool_calls[i]
            if tc.id in streaming:
                return await streaming[tc.id]
            d = decisions[i]
            if d is None:
                return ToolResult(
                    call_id=tc.id, name=tc.name, output="Cancelled by user", is_error=True
                )
            if d == PermissionDecision.DENIED:
                return ToolResult(
                    call_id=tc.id,
                    name=tc.name,
                    output=_denied_message(tc.name, deny_reasons[i]),
                    is_error=True,
                )
            return await self._execute_single_tool(tc, skip_permission=True)

        if n == 1:
            return [await _run_one(0)]
        return list(await asyncio.gather(*(_run_one(i) for i in range(n))))

    async def _execute_single_tool(self, tc: ToolCall, skip_permission: bool = False) -> ToolResult:
        import json as _json

        try:
            args_key = _json.dumps(tc.arguments, sort_keys=True, ensure_ascii=False)[:200]
        except (TypeError, ValueError):
            args_key = str(tc.arguments)[:200]
        self._state.record_tool_call(tc.name, args_key)
        await self._event_bus.emit(
            ToolCallStartEvent(tool_name=tc.name, arguments=tc.arguments, call_id=tc.id)
        )
        if self.on_tool_start:
            self.on_tool_start(tc)

        start = time.monotonic()
        tool = self._tools.get(tc.name)
        if tool is None:
            result = ToolResult(
                call_id=tc.id,
                name=tc.name,
                output=f"Unknown tool: {tc.name}",
                is_error=True,
            )
        else:
            # Snapshot pre-modification state for /undo file restore
            # 快照修改前状态——供 /undo 恢复文件
            if self.snapshot_store and tc.name in ("write_file", "edit_file", "delete_file"):
                raw_path = tc.arguments.get("file_path")
                if raw_path:
                    p = Path(raw_path)
                    if not p.is_absolute():
                        p = self._tool_context.working_dir / p
                    self.snapshot_store.snapshot(self.current_turn_id, p)
            result = await self._run_tool_pipeline(tc, tool, skip_permission=skip_permission)

        duration_ms = (time.monotonic() - start) * 1000
        await self._event_bus.emit(
            ToolCallEndEvent(
                tool_name=tc.name,
                call_id=tc.id,
                is_error=result.is_error,
                duration_ms=duration_ms,
            )
        )
        if not result.is_error:
            self._record_file_change(tc.name, tc.arguments, result)
        if self.on_tool_end:
            self.on_tool_end(result, duration_ms)
        return result

    def _record_file_change(self, tool_name: str, args: dict, result: ToolResult) -> None:
        """Track files created/modified/deleted by file tools.
        跟踪文件工具的新建/修改/删除。"""
        if tool_name not in ("write_file", "edit_file", "delete_file"):
            return
        path = str(args.get("file_path", ""))
        if not path:
            return
        if tool_name == "delete_file":
            # delete wins: whatever happened before, the file is gone now
            # 删除覆盖一切——不管之前怎么改，文件现在没了
            self._file_changes[path] = "deleted"
            return
        if tool_name == "write_file" and not result.metadata.get("existed", True):
            change = "created"
        else:
            change = "modified"
        # created sticks: create-then-edit still counts as created
        # 先建后改仍算新建
        if self._file_changes.get(path) != "created":
            self._file_changes[path] = change

    async def _run_tool_pipeline(
        self, tc: ToolCall, tool, skip_permission: bool = False
    ) -> ToolResult:
        """Full security pipeline: permission -> PRE_TOOL hook -> execute -> POST_TOOL hook.
        完整安全流水线：权限检查 -> PRE_TOOL hook -> 执行 -> POST_TOOL hook。
        """
        # 1. Permission check 权限检查（skip when pre-checked in _act 预检过时跳过）
        if not skip_permission and self._permissions is not None:
            decision = await self._check_permission(tc)
            if decision == PermissionDecision.DENIED:
                return ToolResult(
                    call_id=tc.id,
                    name=tc.name,
                    output=_denied_message(tc.name, self._permissions.last_decision_reason),
                    is_error=True,
                )

        # 2. PRE_TOOL hooks (can block or modify args)
        args = dict(tc.arguments)
        hook_ctx = HookContext(stage=HookStage.PRE_TOOL, tool_name=tc.name, tool_args=args)
        hook_result = await self._hooks.run(hook_ctx)
        if hook_result.action == HookAction.BLOCK:
            return ToolResult(
                call_id=tc.id,
                name=tc.name,
                output=f"Blocked by hook: {hook_result.reason}",
                is_error=True,
            )
        if hook_result.action == HookAction.CONFIRM:
            approved = await self._resolve_hook_confirm(tc.name, hook_result.reason)
            if not approved:
                # Hook confirm denied -> count toward the confirm-denial breaker
                # so the goal stops (same as a denied dangerous command / path).
                # hook 确认被拒 -> 计入确认拒绝熔断，停止目标（同危险命令/路径）。
                self._state.consecutive_confirm_denials += 1
                return ToolResult(
                    call_id=tc.id,
                    name=tc.name,
                    output=f"Denied by user: {hook_result.reason}",
                    is_error=True,
                )
        if hook_ctx.tool_args is not None:
            args = hook_ctx.tool_args

        # 3. Execute
        try:
            validated = tool.validate_args(args)
            raw = await tool.execute(self._tool_context, **validated)
            result = ToolResult(
                call_id=tc.id,
                name=raw.name,
                output=raw.output,
                is_error=raw.is_error,
                metadata=raw.metadata,
            )
            if self._permissions and tc.name in ("write_file", "edit_file") and not result.is_error:
                path = args.get("file_path")
                if path:
                    self._permissions.record_written_file(path)
            # Record file content BEFORE spill -- spill replaces output
            # with a placeholder, but recovery needs the real content
            # 在溢写前记录文件内容——溢写会替换为占位符，恢复需要真实内容
            if self._context is not None and tc.name == "read_file" and not result.is_error:
                path = args.get("file_path")
                if path:
                    self._context.record_file_read(str(path), result.output)
            # Spill oversized outputs to disk -- large file contents entering
            # the conversation wholesale is the root cause of the
            # compression-reread inflation loop. Read-backs of spill files
            # are exempt: re-spilling them would loop forever.
            # 超大输出溢写磁盘——大文件内容整体进对话是压缩-重读膨胀的根源。
            # 溢写文件的读回结果豁免——再溢写会死循环。
            if self.result_cache is not None and not self.result_cache.is_spill_readback(
                tc.name, args
            ):
                result = self.result_cache.maybe_spill(result)
        except ValueError as e:
            result = ToolResult(call_id=tc.id, name=tc.name, output=str(e), is_error=True)
        except Exception as e:
            result = ToolResult(
                call_id=tc.id,
                name=tc.name,
                output=f"Tool execution error: {e}",
                is_error=True,
            )

        # 4. POST_TOOL hooks (observe)
        await self._hooks.run(
            HookContext(
                stage=HookStage.POST_TOOL,
                tool_name=tc.name,
                tool_args=args,
                tool_result=result,
            )
        )
        return result

    async def _resolve_hook_confirm(self, tool_name: str, reason: str) -> bool:
        """Resolve a CONFIRM hook verdict by asking the user.

        Returns True to proceed. No UI callback -> deny (safe default,
        mirrors PermissionManager). "always" grants skip the prompt for the
        same (tool, reason) for the rest of the session. The lock keeps
        dialogs from interleaving when tools execute in parallel.

        通过询问用户裁决 CONFIRM hook。返回 True 表示放行。无 UI 回调时
        拒绝（安全默认，与 PermissionManager 一致）。"always" 使同一
        (工具, 原因) 本会话内不再询问。锁防止并行执行时弹窗交错。
        """
        key = (tool_name, reason)
        if key in self._hook_confirm_grants:
            return True
        if self.confirm_callback is None:
            logger.warning("CONFIRM hook for '%s' but no UI callback: denied", tool_name)
            return False
        async with self._confirm_lock:
            # Re-check: a parallel call may have granted "always" while
            # this one waited on the lock.
            # 重查：等锁期间并行调用可能已授予 "always"。
            if key in self._hook_confirm_grants:
                return True
            prompt = f"Hook requires confirmation for tool '{tool_name}'"
            if reason:
                prompt += f"\n({reason})"
            answer = await self.confirm_callback(prompt)
        # "always-save" degrades to "always" here: hook grants have no
        # persistence semantics. "always-save" 在此降级为 "always"——
        # hook 授权无持久化语义。
        if answer in ("always", "always-save"):
            self._hook_confirm_grants.add(key)
            return True
        return bool(answer)

    def _category(self, name: str) -> ToolCategory:
        """Category of a tool by name; unknown names (hallucinated or
        unregistered plugin tools) are treated as EXTERNAL (conservative).
        按名字查工具类别；未知名字（幻觉/未注册插件）保守视为 EXTERNAL。"""
        tool = self._tools.get(name)
        return tool.category if tool is not None else ToolCategory.EXTERNAL

    async def _check_permission(self, tc: ToolCall) -> PermissionDecision:
        """Route permission check by tool category (mode × category matrix).
        按工具类别路由权限检查（模式 × 类别矩阵）。"""
        assert self._permissions is not None
        scope = "tool"
        resource = tc.name
        category = self._category(tc.name)
        # Mode from the permission manager, NOT self.plan_mode: a sub-agent's
        # loop flag is False but its propagated permission stack still carries
        # the parent's mode -- this is what makes propagation bite.
        # 模式取自权限管理器而非 self.plan_mode：子 agent 的 loop 标志是
        # False，但传播来的权限栈仍带着父级模式——传播正是在这里生效。
        mode = self._permissions.mode

        # 0. Tool-level gate: explicit TOOL rules decide outright.
        # DENY blocks the tool; ALLOW trusts it wholesale (skips resource
        # checks); no rule falls through to category/command/path routing.
        # 工具级门：显式 TOOL 规则直接判定。DENY 拦截工具；ALLOW 整体信任
        # （跳过资源检查）；无规则则继续走类别/命令/路径路由。
        tool_decision = await self._permissions.check_tool(tc.name)
        if tool_decision is not None:
            decision = tool_decision
        elif tc.name == "bash":
            scope = "command"
            resource = str(tc.arguments.get("command", ""))
            decision = await self._permissions.check_command(resource)
        # Category-level mode gate: covers tools WITHOUT path args too
        # (install_skill writes skill dirs, MCP tools mutate external state).
        # 类别级模式门：覆盖无路径参数的工具（install_skill 写技能目录，
        # MCP 工具改外部状态）。
        elif category is ToolCategory.WRITE and mode is PermissionMode.PLAN:
            decision = PermissionDecision.DENIED
            self._permissions.last_decision_reason = "mode:plan"
        elif category is ToolCategory.EXTERNAL and mode is PermissionMode.PLAN:
            decision = PermissionDecision.DENIED
            self._permissions.last_decision_reason = "mode:plan"
        elif category is ToolCategory.EXTERNAL and mode is PermissionMode.BYPASS:
            decision = PermissionDecision.GRANTED
            self._permissions.last_decision_reason = "mode:bypass"
        elif category in (ToolCategory.READ, ToolCategory.WRITE) and (
            path_arg := tc.arguments.get("file_path") or tc.arguments.get("path")
        ):
            scope = "path"
            resource = str(path_arg)
            operation = "write" if category is ToolCategory.WRITE else "read"
            decision = await self._permissions.check_path(
                Path(resource), operation, tool_name=tc.name
            )
        elif category in (ToolCategory.READ, ToolCategory.WRITE):
            decision = PermissionDecision.GRANTED
            self._permissions.last_decision_reason = "no_path_arg"
        else:
            decision = PermissionDecision.GRANTED
            self._permissions.last_decision_reason = "unrestricted_tool"

        # A user-denied confirm (dangerous command OR path outside project)
        # stops the goal -- the loop breaker reads consecutive_confirm_denials.
        # "no_ui:default_deny" counts too: it is the same confirm-denial
        # semantic translated to headless loops (gated sub-agents) -- without
        # it a child hunts bypass routes forever (real-run: 9 tools across 10
        # iterations retrying a denied ping). Policy denials (rule:/mode:/
        # sensitive-path) stay neutral everywhere: they skip and continue.
        # 用户拒绝确认框时停止目标——熔断读 consecutive_confirm_denials。
        # "no_ui:default_deny" 同样计数：它是确认拒绝语义在无头循环（有门
        # 子 agent）中的对应物——不计数时子 agent 会无限找绕路（实测：被拒
        # ping 后连试 9 个工具 10 轮）。策略拒绝（规则/模式/敏感路径）在
        # 任何地方都中性：跳过继续。
        if decision == PermissionDecision.DENIED:
            reason = self._permissions.last_decision_reason
            if reason and reason not in self._state.denial_reasons:
                self._state.denial_reasons.append(reason)
        if self._permissions.last_decision_reason in ("user_confirm:no", "no_ui:default_deny"):
            self._state.consecutive_confirm_denials += 1
        elif decision == PermissionDecision.GRANTED:
            self._state.consecutive_confirm_denials = 0

        await self._event_bus.emit(
            PermissionCheckEvent(
                tool_name=tc.name,
                scope=scope,
                resource=resource[:120],
                decision=decision.value,
                reason=self._permissions.last_decision_reason,
                matched_rule=self._permissions.last_matched_rule,
            )
        )
        return decision

    def _should_continue(self) -> bool:
        """Decide whether to continue the ReAct loop. 判断是否继续 ReAct 循环。"""
        if self._state.iteration >= self._state.max_iterations:
            return False
        if self._cancelled:
            return False
        # A denied confirm stops the goal (default threshold 1: one denial
        # stops). Covers dangerous commands, paths outside the project, and
        # hook confirms -- denying any of them means "don't do this", so the
        # agent stops and asks instead of hunting for a workaround.
        # 确认框被拒即停（默认阈值 1，拒一次就停）。涵盖危险命令、项目外路径、
        # hook 确认——拒绝任一个都是"别做这个"，agent 停下回问而非找绕过。
        if self._state.consecutive_confirm_denials >= self._config.max_consecutive_denials:
            self.stop_reason = "confirm_denied"
            return False
        # Infinite loop guard 1: same tool+args called 6+ times in a row
        # 死循环保护 1：同一工具+参数连续调用 6 次及以上
        recent = self._state.recent_tool_names[-6:]
        if len(recent) >= 6 and len(set(recent)) == 1:
            return False
        # Infinite loop guard 2: same tool in every one of the last 15
        # iterations. Generous threshold allows multi-file analysis while
        # still catching real loops.
        # 死循环保护 2：连续 15 轮每轮都有同一工具。
        # 宽松阈值允许多文件分析，仍能捕获真死循环。
        window = self._state.iteration_tools[-15:]
        if len(window) >= 15:
            common = frozenset.intersection(*window)
            if common:
                return False
        return True

    async def _transition(self, new_phase: AgentPhase) -> None:
        old = self._state.transition(new_phase)
        await self._event_bus.emit(
            AgentPhaseChangeEvent(
                old_phase=str(old),
                new_phase=str(new_phase),
                iteration=self._state.iteration,
            )
        )
