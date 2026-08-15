"""Context window manager -- tracks token usage and triggers compression.
上下文窗口管理器——跟踪 token 使用量并触发压缩。"""

from __future__ import annotations

import logging

from mini_agent.llm.token_counter import count_tokens
from mini_agent.memory.compressor import SlidingWindow
from mini_agent.models.config import MemoryConfig
from mini_agent.models.message import Conversation, Message, Role

logger = logging.getLogger(__name__)


class ContextManager:
    """Tracks and manages the conversation context window. 跟踪并管理对话上下文窗口。"""

    def __init__(self, config: MemoryConfig) -> None:
        self._max_tokens = config.context_window
        self._threshold = config.compression_threshold
        self._total_tokens = 0
        self._compressor = None  # set via set_compressor() after init
        # 初始化后通过 set_compressor() 设置
        # Circuit breaker: stop retrying compression after N consecutive
        # ineffective attempts (tokens did not decrease)
        # 熔断器：连续 N 次压缩无效后停止重试
        self._compress_failures: int = 0
        self._max_compress_failures: int = config.compress_max_failures
        # Ordered, deduplicated list of files read this session -- re-injected
        # after compression so the LLM does not forget and re-read them
        # 本会话已读文件（保序去重）——压缩后重新注入，防 LLM 忘记后重读
        self._read_files: dict[str, None] = {}
        # API usage anchor: the LLM-reported total is authoritative for the
        # whole conversation up to the anchored message (it even includes
        # tool schemas, which estimation cannot see). Messages after the
        # anchor are estimated. Identity check auto-invalidates on compression.
        # API usage 锚点：LLM 返回的总量是锚点消息之前整个对话的权威计数
        # （连估算看不到的工具 schema 都包含）。锚点之后的消息用估算。
        # 对象身份检查让压缩重排后锚点自动失效。
        self._api_total = 0
        self._api_index = -1
        self._api_anchor: Message | None = None

    def set_compressor(self, compressor) -> None:
        """Inject the compressor (avoids circular import at init time).
        注入压缩器（避免初始化时的循环导入）。"""
        self._compressor = compressor

    def record_file_read(self, path: str) -> None:
        self._read_files[path] = None

    @property
    def read_files(self) -> list[str]:
        return list(self._read_files)

    def record_api_usage(self, conversation: Conversation, usage) -> None:
        """Anchor the authoritative API-reported token total at the newest message.
        将 API 返回的权威 token 总量锚定在最新一条消息上。

        usage.prompt_tokens covers everything the API actually billed for the
        conversation so far (system prompt, all messages, tool schemas);
        adding completion gives the exact total through the last message.
        prompt_tokens 覆盖 API 实际计费的全部内容（系统提示、所有消息、
        工具 schema），加上 completion 即截至最新消息的精确总量。"""
        if usage.prompt_tokens <= 0 or not conversation.messages:
            return
        self._api_total = usage.total_tokens or (usage.prompt_tokens + usage.completion_tokens)
        self._api_index = len(conversation.messages) - 1
        self._api_anchor = conversation.messages[-1]

    def _invalidate_api_anchor(self) -> None:
        self._api_total = 0
        self._api_index = -1
        self._api_anchor = None

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
        """Recount total tokens. Prefers the API-reported total (anchored at
        the message that usage covered) and only estimates messages appended
        after the anchor -- estimation error no longer accumulates over turns.
        重新统计总 token。优先用 API 返回的权威总量（锚定在 usage 覆盖的
        消息上），只对锚点之后追加的消息估算——估算误差不再逐轮累积。"""
        msgs = conversation.messages
        anchor_valid = (
            self._api_anchor is not None
            and 0 <= self._api_index < len(msgs)
            and msgs[self._api_index] is self._api_anchor
        )
        if anchor_valid:
            total = self._api_total
            for msg in msgs[self._api_index + 1 :]:
                total += self.count_message(msg)
        else:
            if self._api_anchor is not None:
                self._invalidate_api_anchor()  # compression/undo reshaped history
            total = count_tokens(conversation.system_prompt) if conversation.system_prompt else 0
            for msg in msgs:
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
        if (
            self._max_compress_failures > 0
            and self._compress_failures >= self._max_compress_failures
        ):
            logger.warning(
                "Compression circuit breaker open: %d consecutive ineffective "
                "attempts, skipping. 压缩熔断器已开启：连续 %d 次无效，跳过",
                self._compress_failures,
                self._compress_failures,
            )
            return False

        old_total = self._total_tokens
        target = int(self._max_tokens * 0.5)
        await self._compressor.compress(conversation, target)
        self._inject_read_files(conversation)
        # Fallback: SlidingWindow alone doesn't create a summary, but
        # _inject_read_files inserts a compressed SYSTEM message we can use.
        # 兜底：纯 SlidingWindow 不产生摘要，但 _inject_read_files 会插入
        # 压缩 SYSTEM 消息可作为边界。
        if conversation.compact_boundary is None:
            from datetime import datetime

            for msg in conversation.messages:
                if msg.compressed and msg.role == Role.SYSTEM and msg.content:
                    conversation.compact_boundary = {
                        "summary": msg.content,
                        "timestamp": datetime.now().isoformat(),
                    }
                    break
        if conversation.compact_boundary is not None:
            conversation.compact_boundary["read_files"] = list(self._read_files)
        self.update_total(conversation)
        if self._total_tokens >= old_total:
            self._compress_failures += 1
            logger.info(
                "Compression ineffective (%d -> %d tokens), failure %d/%d. "
                "压缩无效（%d -> %d），失败 %d/%d",
                old_total,
                self._total_tokens,
                self._compress_failures,
                self._max_compress_failures or -1,
                old_total,
                self._total_tokens,
                self._compress_failures,
                self._max_compress_failures or -1,
            )
        else:
            if self._compress_failures > 0:
                logger.info(
                    "Compression effective (%d -> %d tokens), resetting failure count. "
                    "压缩有效（%d -> %d），重置失败计数",
                    old_total,
                    self._total_tokens,
                    old_total,
                    self._total_tokens,
                )
            self._compress_failures = 0
        return True

    def _inject_read_files(self, conversation: Conversation) -> None:
        """After compression, remind the LLM which files it already read --
        summaries discard file contents AND identities, so without this the
        LLM re-reads the same files and re-triggers compression in a loop.
        压缩后提醒 LLM 已读过哪些文件——摘要连内容带文件名一起丢弃，
        没有这行 LLM 会重读同样的文件并再次触发压缩，形成循环。"""
        if not self._read_files:
            return
        note = (
            "[Files already read this session -- do NOT re-read unless "
            "their content changed: " + ", ".join(self._read_files) + "]"
        )
        marker = "[Files already read this session"
        for msg in reversed(conversation.messages):
            if msg.role == Role.SYSTEM and msg.compressed:
                content = msg.content or ""
                if marker in content:
                    # Replace stale note -- the read list may have grown
                    # 替换旧清单——已读列表可能已增长
                    content = content[: content.index(marker)].rstrip()
                msg.content = (content + "\n" + note) if content else note
                msg.token_count = None
                return
        # No summary message (pure SlidingWindow path): insert a standalone note
        # 没有摘要消息（纯滑窗路径）：插入独立提示
        conversation.messages.insert(0, Message(role=Role.SYSTEM, content=note, compressed=True))

    def adopt_boundary(self, conversation: Conversation) -> None:
        """Restore read-files state from a loaded compact boundary.
        从已加载的压缩边界恢复已读文件状态。"""
        boundary = conversation.compact_boundary
        if not boundary:
            return
        for path in boundary.get("read_files", []):
            self._read_files[path] = None

    async def ensure_fits(self, conversation: Conversation, max_tokens: int) -> bool:
        """Last-resort guard: force-truncate if conversation exceeds max_tokens.
        最终兜底：超窗口时强制截断（SlidingWindow），防 API 400。

        Returns True if truncation was performed.
        """
        self.update_total(conversation)
        if self._total_tokens <= max_tokens:
            return False
        target = int(max_tokens * 0.85)
        await SlidingWindow().compress(conversation, target)
        self.update_total(conversation)
        return True
