"""Compression strategies for managing context window overflow.

Three-stage cascade:
  Stage 1: DropToolResults — abbreviate verbose tool outputs
  Stage 2: SummarizeOldest — LLM-summarize the oldest messages
  Stage 3: SlidingWindow  — keep only the most recent N messages
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mini_agent.llm.token_counter import count_tokens
from mini_agent.models.message import Conversation, Message, Role


class CompressionStrategy(ABC):
    @abstractmethod
    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        """Mutate conversation.messages in-place to reduce token count."""
        ...


class DropToolResults(CompressionStrategy):
    """Stage 1: Replace verbose tool outputs with short summaries."""

    MAX_TOOL_OUTPUT = 200

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        for msg in conversation.messages:
            if msg.role == Role.TOOL and msg.tool_result and not msg.compressed:
                output = msg.tool_result.output
                if len(output) > self.MAX_TOOL_OUTPUT:
                    lines = output.count("\n") + 1
                    chars = len(output)
                    short = (
                        output[: self.MAX_TOOL_OUTPUT]
                        + f"\n... ({lines} lines, {chars} chars total, truncated)"
                    )
                    msg.tool_result = msg.tool_result.__class__(
                        call_id=msg.tool_result.call_id,
                        name=msg.tool_result.name,
                        output=short,
                        is_error=msg.tool_result.is_error,
                        metadata=msg.tool_result.metadata,
                    )
                    msg.content = short
                    msg.token_count = None  # force recount
                    msg.compressed = True


class SummarizeOldest(CompressionStrategy):
    """Stage 2: Summarize the oldest portion of messages into one summary message.

    Uses a simple extractive approach (no LLM call in P4 — keeps it fast
    and avoids recursive API calls). A full LLM-based summary can be
    plugged in later.
    """

    KEEP_RECENT = 6  # always keep the most recent N messages untouched

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        msgs = conversation.messages
        if len(msgs) <= self.KEEP_RECENT:
            return

        to_summarize = msgs[: len(msgs) - self.KEEP_RECENT]
        kept = msgs[len(msgs) - self.KEEP_RECENT :]

        parts: list[str] = []
        for msg in to_summarize:
            role = msg.role.value
            if msg.content:
                text = msg.content[:300]
                parts.append(f"[{role}] {text}")
            elif msg.tool_calls:
                names = ", ".join(tc.name for tc in msg.tool_calls)
                parts.append(f"[{role}] called tools: {names}")
            elif msg.tool_result:
                status = "error" if msg.tool_result.is_error else "ok"
                parts.append(f"[{role}] {msg.tool_result.name} → {status}")

        summary_text = "[Compressed conversation history]\n" + "\n".join(parts)

        summary_msg = Message(
            role=Role.SYSTEM,
            content=summary_text,
            compressed=True,
        )
        summary_msg.token_count = count_tokens(summary_text) + 4

        conversation.messages = [summary_msg] + kept


class SlidingWindow(CompressionStrategy):
    """Stage 3: Keep only messages that fit within target_tokens (last resort)."""

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        system_cost = count_tokens(conversation.system_prompt) if conversation.system_prompt else 0
        budget = target_tokens - system_cost

        kept: list[Message] = []
        running = 0
        for msg in reversed(conversation.messages):
            cost = msg.token_count or count_tokens(msg.content or "") + 4
            if running + cost > budget:
                break
            kept.append(msg)
            running += cost
        kept.reverse()
        conversation.messages = kept


class Compressor:
    """Runs compression strategies in cascade until target is met."""

    def __init__(
        self,
        strategies: list[CompressionStrategy] | None = None,
    ) -> None:
        self._strategies = strategies or [
            DropToolResults(),
            SummarizeOldest(),
            SlidingWindow(),
        ]

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        for strategy in self._strategies:
            # Recount after each stage
            total = sum(
                m.token_count or count_tokens(m.content or "") + 4 for m in conversation.messages
            )
            if total <= target_tokens:
                break
            await strategy.compress(conversation, target_tokens)
