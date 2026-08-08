"""ReAct agent loop -- the heart of the system."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

from mini_agent.core.agent_state import AgentPhase, AgentState
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, LLMResponse, StreamChunk
from mini_agent.llm.openai_provider import assemble_response
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
from mini_agent.models.permissions import PermissionDecision
from mini_agent.security.permission import PermissionManager
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.hooks import HookAction, HookContext, HookManager, HookStage

# Callback invoked with each streaming text delta (for UI rendering)
# 每次收到流式文本增量时调用的回调（用于 UI 渲染）
StreamCallback = Callable[[str], None]
# Callbacks invoked when a tool starts / finishes (for UI rendering)
# 工具开始 / 结束时调用的回调（用于 UI 渲染）
ToolStartCallback = Callable[[ToolCall], None]
ToolEndCallback = Callable[[ToolResult], None]


class AgentLoop:
    """Orchestrates the think-act-observe ReAct cycle. 编排“思考-行动-观察”的 ReAct 循环。"""

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

        self.on_stream_delta: StreamCallback | None = None
        self.on_stream_start: Callable[[], None] | None = None
        self.on_stream_end: Callable[[], None] | None = None
        self.on_tool_start: ToolStartCallback | None = None
        self.on_tool_end: ToolEndCallback | None = None
        self.on_tool_call_assembling: Callable[[str], None] | None = None
        self.last_turn_tokens: int = 0
        # Files created/modified during the last run() 上一轮新建/修改的文件
        self.last_turn_file_changes: list[tuple[str, str]] = []
        self._file_changes: dict[str, str] = {}
        # Optional per-turn file snapshots for operation-level undo (app injects)
        # 可选的每轮文件快照——操作级撤销（app.py 注入）
        self.snapshot_store = None
        self.current_turn_id: int = 0
        # Model name for cost attribution (app/subagent manager sets it)
        # 模型名——供成本归属（app/subagent manager 设置）
        self.model_name: str = ""
        # True when the last run() ended via circuit breaker, not a natural answer
        # 上一次 run() 是否因熔断（而非自然回答）结束
        self.stopped_early: bool = False

    @property
    def state(self) -> AgentState:
        return self._state

    def cancel(self) -> None:
        self._cancelled = True

    async def run(self, conversation: Conversation) -> str:
        """Execute the full ReAct loop. Appends messages to the conversation.
        Returns the final assistant text response.
        执行完整的 ReAct 循环，将消息追加到会话中，返回助手最终的文本回复。
        """
        self._cancelled = False
        self._state = AgentState(max_iterations=self._config.max_agent_iterations)
        self.stopped_early = False
        self._file_changes = {}
        if self.snapshot_store:
            self.current_turn_id += 1
            self.snapshot_store.begin_turn(self.current_turn_id)
        tools_called = 0
        tokens_used = 0
        final_content = ""

        while True:
            self._state.iteration += 1

            # THINK
            await self._transition(AgentPhase.THINKING)
            response = await self._think(conversation)

            # Record assistant message
            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=response.content,
                tool_calls=response.tool_calls,
            )
            if response.usage:
                assistant_msg.token_count = response.usage.total_tokens
                tokens_used += response.usage.total_tokens
            conversation.append(assistant_msg)

            # No tool calls -> final answer
            if not response.tool_calls:
                final_content = response.content
                await self._transition(AgentPhase.RESPONDING)
                break

            # ACT
            await self._transition(AgentPhase.TOOL_CALLING)
            results = await self._act(response.tool_calls)
            tools_called += len(results)

            # OBSERVE
            await self._transition(AgentPhase.OBSERVING)
            for result in results:
                conversation.append(Message(role=Role.TOOL, tool_result=result))
            self._state.last_tool_results = results

            # Context compression check
            if self._context:
                await self._context.check_and_compress(conversation)

            if not self._should_continue():
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
        return final_content

    async def _think(self, conversation: Conversation) -> LLMResponse:
        """Call LLM with streaming; assemble the full response.
        以 stream 方式调用 LLM 并组装完整响应。
        """
        api_messages = conversation.to_api_messages()
        tool_schemas = self._tools.get_schemas()

        await self._event_bus.emit(
            LLMRequestEvent(message_count=len(api_messages), tool_count=len(tool_schemas))
        )

        # PRE_LLM hook: can inject memories, block LLM call, etc.
        # PRE_LLM hook：可注入记忆、阻止 LLM 调用等
        pre_llm_ctx = HookContext(
            stage=HookStage.PRE_LLM,
            metadata={"message_count": len(api_messages), "tool_count": len(tool_schemas)},
        )
        pre_llm_result = await self._hooks.run(pre_llm_ctx)
        if pre_llm_result.action == HookAction.BLOCK:
            return LLMResponse(content=pre_llm_result.reason or "(blocked by PRE_LLM hook)")

        # Context overflow guard: force-truncate if still over window
        # 上下文溢出兜底：超窗口时强制截断，防 API 400
        if self._context:
            truncated = await self._context.ensure_fits(conversation, self._llm.context_window)
            if truncated:
                api_messages = conversation.to_api_messages()

        chunks: list[StreamChunk] = []
        stream_started = False

        async for chunk in self._llm.stream(api_messages, tools=tool_schemas or None):
            if self._cancelled:
                break
            chunks.append(chunk)
            if chunk.delta:
                if not stream_started:
                    stream_started = True
                    if self.on_stream_start:
                        self.on_stream_start()
                if self.on_stream_delta:
                    self.on_stream_delta(chunk.delta)
            if chunk.tool_call_deltas and self.on_tool_call_assembling:
                for tcd in chunk.tool_call_deltas:
                    if tcd.name:
                        self.on_tool_call_assembling(tcd.name)

        if stream_started and self.on_stream_end:
            self.on_stream_end()

        response = assemble_response(chunks)
        usage = response.usage
        await self._event_bus.emit(
            LLMResponseEvent(
                content=response.content[:100],
                has_tool_calls=bool(response.tool_calls),
                tokens_used=usage.total_tokens if usage else 0,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                model=self.model_name,
            )
        )
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

        # --- Phase 1: sequential permission pre-check ---
        decisions: list[PermissionDecision | None] = []
        for tc in tool_calls:
            if self._cancelled:
                decisions.append(None)
                continue
            if self._permissions is not None:
                decisions.append(await self._check_permission(tc))
            else:
                decisions.append(PermissionDecision.GRANTED)

        # --- Phase 2: parallel execution ---
        async def _run_one(i: int) -> ToolResult:
            tc = tool_calls[i]
            d = decisions[i]
            if d is None:
                return ToolResult(
                    call_id=tc.id, name=tc.name, output="Cancelled by user", is_error=True
                )
            if d == PermissionDecision.DENIED:
                return ToolResult(
                    call_id=tc.id,
                    name=tc.name,
                    output=f"Permission denied for {tc.name}",
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
            self.on_tool_end(result)
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
                    output=f"Permission denied for {tc.name}",
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

    async def _check_permission(self, tc: ToolCall) -> PermissionDecision:
        """Route permission check by tool type. 按工具类型路由权限检查。"""
        assert self._permissions is not None
        scope = "tool"
        resource = tc.name

        if tc.name == "bash":
            scope = "command"
            resource = str(tc.arguments.get("command", ""))
            decision = await self._permissions.check_command(resource)
        elif tc.name in ("read_file", "glob", "grep"):
            path_arg = tc.arguments.get("file_path") or tc.arguments.get("path")
            if path_arg:
                scope = "path"
                resource = str(path_arg)
                decision = await self._permissions.check_path(Path(resource), "read")
            else:
                decision = PermissionDecision.GRANTED
                self._permissions.last_decision_reason = "no_path_arg"
        elif tc.name in ("write_file", "edit_file"):
            path_arg = tc.arguments.get("file_path")
            if path_arg:
                scope = "path"
                resource = str(path_arg)
                decision = await self._permissions.check_path(Path(resource), "write")
            else:
                decision = PermissionDecision.GRANTED
                self._permissions.last_decision_reason = "no_path_arg"
        else:
            decision = PermissionDecision.GRANTED
            self._permissions.last_decision_reason = "unrestricted_tool"

        await self._event_bus.emit(
            PermissionCheckEvent(
                tool_name=tc.name,
                scope=scope,
                resource=resource[:120],
                decision=decision.value,
                reason=self._permissions.last_decision_reason,
            )
        )
        return decision

    def _should_continue(self) -> bool:
        """Decide whether to continue the ReAct loop. 判断是否继续 ReAct 循环。"""
        if self._state.iteration >= self._state.max_iterations:
            return False
        if self._cancelled:
            return False
        # Infinite loop guard 1: same tool+args called 6+ times in a row
        # 死循环保护 1：同一工具+参数连续调用 6 次及以上
        recent = self._state.recent_tool_names[-6:]
        if len(recent) >= 6 and len(set(recent)) == 1:
            return False
        # Infinite loop guard 2: same tool NAME dominates recent calls
        # (10+ of last 12 calls are the same tool, regardless of args)
        # 死循环保护 2：同名工具占据最近调用的绝对多数（不看参数）
        window = self._state.recent_tool_names[-12:]
        if len(window) >= 12:
            names = [sig.split("(", 1)[0] for sig in window]
            most_common = max(set(names), key=names.count)
            if names.count(most_common) >= 10:
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
