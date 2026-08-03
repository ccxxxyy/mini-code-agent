"""Context window manager -- tracks token usage and triggers compression.
上下文窗口管理器——跟踪 token 使用量并触发压缩。"""

from __future__ import annotations

from mini_agent.llm.token_counter import count_tokens
from mini_agent.models.config import MemoryConfig
from mini_agent.models.message import Conversation, Message


class ContextManager:
    """Tracks and manages the conversation context window. 跟踪并管理对话上下文窗口。"""

    def __init__(self, config: MemoryConfig) -> None:
        self._max_tokens = config.context_window
        self._threshold = config.compression_threshold
        self._total_tokens = 0
        self._compressor = None  # set via set_compressor() after init
        # 初始化后通过 set_compressor() 设置

    def set_compressor(self, compressor) -> None:
        """Inject the compressor (avoids circular import at init time).
        注入压缩器（避免初始化时的循环导入）。"""
        self._compressor = compressor

    def count_message(self, message: Message) -> int:
        """Count and cache tokens for a message. 统计并缓存消息的 token 数。"""
        if message.token_count is not None:
            return message.token_count
        parts = []
        if message.content:
            parts.append(message.content)
        if message.tool_result:
            parts.append(message.tool_result.output)
        for tc in message.tool_calls:
            parts.append(tc.name)
            parts.append(str(tc.arguments))
        text = " ".join(parts) if parts else ""
        message.token_count = count_tokens(text) + 4  # +4 overhead
        return message.token_count

    def update_total(self, conversation: Conversation) -> int:
        """Recount total tokens from the conversation. 重新统计对话的总 token 数。"""
        total = count_tokens(conversation.system_prompt) if conversation.system_prompt else 0
        for msg in conversation.messages:
            total += self.count_message(msg)
        self._total_tokens = total
        conversation.total_tokens = total
        return total

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def usage_ratio(self) -> float:
        if self._max_tokens <= 0:
            return 0.0
        return self._total_tokens / self._max_tokens

    @property
    def tokens_remaining(self) -> int:
        return max(0, self._max_tokens - self._total_tokens)

    @property
    def needs_compression(self) -> bool:
        return self.usage_ratio >= self._threshold

    async def check_and_compress(self, conversation: Conversation) -> bool:
        """Check if compression is needed and perform it.
        检查是否需要压缩并执行压缩。

        Returns True if compression was performed.
        若执行了压缩则返回 True。
        """
        self.update_total(conversation)
        if not self.needs_compression:
            return False
        if self._compressor is None:
            return False

        target = int(self._max_tokens * 0.5)
        await self._compressor.compress(conversation, target)
        self.update_total(conversation)
        return True
