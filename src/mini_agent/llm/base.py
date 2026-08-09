"""LLM Provider abstraction layer. LLM Provider 抽象层。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from mini_agent.models.message import ToolCall


@dataclass
class ToolCallDelta:
    """Incremental tool call data from streaming. 来自 stream 的增量工具调用数据。"""

    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response. 流式 LLM 响应中的单个 chunk。"""

    delta: str = ""
    tool_call_deltas: list[ToolCallDelta] = field(default_factory=list)
    finish_reason: str | None = None
    usage: TokenUsage | None = None


@dataclass
class LLMResponse:
    """Completed LLM response. 完整的 LLM 响应。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str = "stop"
    model: str = ""


class LLMProvider(ABC):
    """Abstract base for all LLM providers. 所有 LLM Provider 的抽象基类。"""

    async def prepare(self) -> None:
        """Optional warmup before first use (e.g. context window probing).
        首次使用前的可选预热（如上下文窗口探测），默认无操作。"""

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming completion -- yields chunks as they arrive. 流式补全——chunk 到达时逐个产出。"""
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Estimate token count for the given text. 估算给定文本的 token 数。"""
        ...

    @property
    @abstractmethod
    def context_window(self) -> int:
        """Maximum context window size for the configured model. 所配置模型的最大上下文窗口大小。"""
        ...
