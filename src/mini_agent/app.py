"""Application orchestrator -- wires all layers together."""

from __future__ import annotations

from mini_agent.events.bus import EventBus
from mini_agent.llm.base import StreamChunk
from mini_agent.llm.openai_provider import assemble_response
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.models.config import AgentConfig
from mini_agent.models.events import (
    LLMStreamChunkEvent,
    SessionEndEvent,
    SessionStartEvent,
    UserMessageEvent,
)
from mini_agent.models.message import Message, Role
from mini_agent.models.session import Session
from mini_agent.ui.terminal import Terminal


class Application:
    """Main application -- simple conversation loop for P1."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.event_bus = EventBus()
        self.terminal = Terminal()
        self.session = Session()
        self.session.conversation.system_prompt = (
            "You are a helpful coding assistant running in a terminal. "
            "Be concise and direct in your responses. "
            "Use markdown formatting when appropriate."
        )
        self.session.metadata.model = config.llm.model

        self._llm = ProviderRegistry.create(config.llm)

    async def run(self) -> None:
        self.terminal.show_welcome()
        await self.event_bus.emit(SessionStartEvent(session_id=self.session.metadata.session_id))

        try:
            while True:
                try:
                    user_input = await self.terminal.get_user_input()
                except EOFError:
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

        user_msg = Message(role=Role.USER, content=user_input)
        self.session.conversation.append(user_msg)
        self.session.metadata.total_turns += 1

        api_messages = self.session.conversation.to_api_messages()

        self.terminal.start_stream()
        chunks: list[StreamChunk] = []

        try:
            async for chunk in self._llm.stream(api_messages):
                chunks.append(chunk)
                if chunk.delta:
                    self.terminal.feed_stream(chunk.delta)
                    await self.event_bus.emit(LLMStreamChunkEvent(delta=chunk.delta))
        except Exception as e:
            self.terminal.finish_stream()
            self.terminal.show_error(str(e))
            return

        self.terminal.finish_stream()

        response = assemble_response(chunks)
        assistant_msg = Message(
            role=Role.ASSISTANT,
            content=response.content,
        )
        if response.usage:
            assistant_msg.token_count = response.usage.total_tokens
            self.session.metadata.total_tokens_used += response.usage.total_tokens

        self.session.conversation.append(assistant_msg)
