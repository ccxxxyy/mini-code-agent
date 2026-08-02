"""ReAct agent loop -- the heart of the system."""

from __future__ import annotations

import time
from collections.abc import Callable

from mini_agent.core.agent_state import AgentPhase, AgentState
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, LLMResponse, StreamChunk
from mini_agent.llm.openai_provider import assemble_response
from mini_agent.models.config import AgentConfig
from mini_agent.models.events import (
    AgentPhaseChangeEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    TurnCompleteEvent,
)
from mini_agent.models.message import Conversation, Message, Role, ToolCall, ToolResult
from mini_agent.tools.base import ToolContext, ToolRegistry

# Callback invoked with each streaming text delta (for UI rendering)
StreamCallback = Callable[[str], None]
# Callbacks invoked when a tool starts / finishes (for UI rendering)
ToolStartCallback = Callable[[ToolCall], None]
ToolEndCallback = Callable[[ToolResult], None]


class AgentLoop:
    """Orchestrates the think-act-observe ReAct cycle."""

    def __init__(
        self,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        event_bus: EventBus,
        config: AgentConfig,
        tool_context: ToolContext,
    ) -> None:
        self._llm = llm
        self._tools = tool_registry
        self._event_bus = event_bus
        self._config = config
        self._tool_context = tool_context
        self._state = AgentState(max_iterations=config.max_agent_iterations)
        self._cancelled = False

        self.on_stream_delta: StreamCallback | None = None
        self.on_stream_start: Callable[[], None] | None = None
        self.on_stream_end: Callable[[], None] | None = None
        self.on_tool_start: ToolStartCallback | None = None
        self.on_tool_end: ToolEndCallback | None = None
        self.last_turn_tokens: int = 0

    @property
    def state(self) -> AgentState:
        return self._state

    def cancel(self) -> None:
        self._cancelled = True

    async def run(self, conversation: Conversation) -> str:
        """Execute the full ReAct loop. Appends messages to the conversation.
        Returns the final assistant text response."""
        self._cancelled = False
        self._state = AgentState(max_iterations=self._config.max_agent_iterations)
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

            if not self._should_continue():
                final_content = response.content or "(stopped: iteration limit or cancellation)"
                await self._transition(AgentPhase.TERMINATED)
                break

        await self._transition(AgentPhase.IDLE)
        self.last_turn_tokens = tokens_used
        await self._event_bus.emit(
            TurnCompleteEvent(
                iteration_count=self._state.iteration,
                tools_called=tools_called,
                tokens_used=tokens_used,
            )
        )
        return final_content

    async def _think(self, conversation: Conversation) -> LLMResponse:
        """Call LLM with streaming; assemble the full response."""
        api_messages = conversation.to_api_messages()
        tool_schemas = self._tools.get_schemas()

        chunks: list[StreamChunk] = []
        stream_started = False

        async for chunk in self._llm.stream(api_messages, tools=tool_schemas or None):
            chunks.append(chunk)
            if chunk.delta:
                if not stream_started:
                    stream_started = True
                    if self.on_stream_start:
                        self.on_stream_start()
                if self.on_stream_delta:
                    self.on_stream_delta(chunk.delta)

        if stream_started and self.on_stream_end:
            self.on_stream_end()

        return assemble_response(chunks)

    async def _act(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Execute tool calls sequentially, reporting progress via callbacks."""
        results: list[ToolResult] = []
        for tc in tool_calls:
            if self._cancelled:
                results.append(
                    ToolResult(
                        call_id=tc.id,
                        name=tc.name,
                        output="Cancelled by user",
                        is_error=True,
                    )
                )
                continue
            results.append(await self._execute_single_tool(tc))
        return results

    async def _execute_single_tool(self, tc: ToolCall) -> ToolResult:
        self._state.record_tool_call(tc.name)
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
            try:
                validated = tool.validate_args(tc.arguments)
                raw = await tool.execute(self._tool_context, **validated)
                # Re-attach the call_id (tools don't know it)
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

        duration_ms = (time.monotonic() - start) * 1000
        await self._event_bus.emit(
            ToolCallEndEvent(
                tool_name=tc.name,
                call_id=tc.id,
                is_error=result.is_error,
                duration_ms=duration_ms,
            )
        )
        if self.on_tool_end:
            self.on_tool_end(result)
        return result

    def _should_continue(self) -> bool:
        """Decide whether to continue the ReAct loop."""
        if self._state.iteration >= self._state.max_iterations:
            return False
        if self._cancelled:
            return False
        # Infinite loop guard: same tool called 6+ times in a row
        recent = self._state.recent_tool_names[-6:]
        if len(recent) >= 6 and len(set(recent)) == 1:
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
