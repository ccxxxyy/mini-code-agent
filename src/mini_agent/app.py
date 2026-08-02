"""Application orchestrator -- wires all layers together."""

from __future__ import annotations

from pathlib import Path

from mini_agent.core.agent_loop import AgentLoop
from mini_agent.events.bus import EventBus
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.models.config import AgentConfig
from mini_agent.models.events import (
    SessionEndEvent,
    SessionStartEvent,
    UserMessageEvent,
)
from mini_agent.models.message import Message, Role
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin import ALL_BUILTIN_TOOLS
from mini_agent.ui.terminal import Terminal

SYSTEM_PROMPT = """You are a helpful coding agent running in a terminal, working in {working_dir}.

You have access to tools for reading/writing/editing files, running shell commands, \
and searching the codebase (glob for file names, grep for file contents).

Guidelines:
- Use tools to accomplish tasks. Don't guess file contents -- read them.
- Break complex tasks into steps: search, read, then modify.
- Be concise in your final answers. Use markdown formatting.
- When editing files, read them first to understand the context.
- Report errors honestly. If a tool fails, explain what went wrong."""


class Application:
    """Main application -- agent conversation loop."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.event_bus = EventBus()
        self.terminal = Terminal()
        self.session = Session()

        working_dir = Path.cwd()
        self.session.conversation.system_prompt = SYSTEM_PROMPT.format(working_dir=working_dir)
        self.session.metadata.model = config.llm.model
        self.session.metadata.project_dir = working_dir

        self._llm = ProviderRegistry.create(config.llm)

        # Tool registry with all builtin tools
        self.tool_registry = ToolRegistry()
        for tool_class in ALL_BUILTIN_TOOLS:
            tool = tool_class()
            if tool.schema.name in config.tools.enabled_tools:
                self.tool_registry.register(tool)

        tool_context = ToolContext(
            working_dir=working_dir,
            session=self.session,
            event_bus=self.event_bus,
            config=config,
        )

        self.agent_loop = AgentLoop(
            llm=self._llm,
            tool_registry=self.tool_registry,
            event_bus=self.event_bus,
            config=config,
            tool_context=tool_context,
        )

        # Wire agent loop callbacks to terminal rendering
        self.agent_loop.on_stream_start = self.terminal.start_stream
        self.agent_loop.on_stream_delta = self.terminal.feed_stream
        self.agent_loop.on_stream_end = lambda: self.terminal.finish_stream()
        self.agent_loop.on_tool_start = lambda tc: self.terminal.show_tool_call(
            tc.name, tc.arguments
        )
        self.agent_loop.on_tool_end = lambda tr: self.terminal.show_tool_result(
            tr.name, tr.output, tr.is_error
        )

    async def run(self) -> None:
        self.terminal.show_welcome()
        await self.event_bus.emit(SessionStartEvent(session_id=self.session.metadata.session_id))

        try:
            while True:
                try:
                    user_input = await self.terminal.get_user_input()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    break

                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.lower() in ("/quit", "/exit", "exit", "quit"):
                    break

                await self._handle_turn(user_input)
        finally:
            await self.event_bus.emit(SessionEndEvent(session_id=self.session.metadata.session_id))
            self.terminal.show_info("Goodbye!")

    async def _handle_turn(self, user_input: str) -> None:
        await self.event_bus.emit(UserMessageEvent(content=user_input))

        self.session.conversation.append(Message(role=Role.USER, content=user_input))
        self.session.metadata.total_turns += 1

        try:
            await self.agent_loop.run(self.session.conversation)
            turn_tokens = self.agent_loop.last_turn_tokens
            self.session.metadata.total_tokens_used += turn_tokens
            self.terminal.show_info(
                f"tokens: {turn_tokens} this turn / {self.session.metadata.total_tokens_used} total"
            )
        except KeyboardInterrupt:
            self.agent_loop.cancel()
            self.terminal.show_info("Interrupted.")
        except Exception as e:
            self.terminal.show_error(str(e))
