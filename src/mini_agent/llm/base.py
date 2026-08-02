"""LLM Provider abstraction layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from mini_agent.models.message import ToolCall


@dataclass
class ToolCallDelta:
    """Incremental tool call data from streaming."""

    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response."""

    delta: str = ""
    tool_call_deltas: list[ToolCallDelta] = field(default_factory=list)
    finish_reason: str | None = None
    usage: TokenUsage | None = None


@dataclass
class LLMResponse:
    """Completed LLM response."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str = "stop"
    model: str = ""


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming completion -- yields chunks as they arrive."""
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Estimate token count for the given text."""
        ...

    @property
    @abstractmethod
    def context_window(self) -> int:
        """Maximum context window size for the configured model."""
        ...
