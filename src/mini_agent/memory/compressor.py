"""Compression strategies for managing context window overflow.
用于处理上下文窗口溢出的压缩策略。

Three-stage cascade:
  Stage 1: DropToolResults — abbreviate verbose tool outputs
  Stage 2: SummarizeOldest — LLM-summarize the oldest messages
  Stage 3: SlidingWindow  — keep only the most recent N messages

三级级联：
  第 1 级：DropToolResults——缩略冗长的工具输出
  第 2 级：SummarizeOldest——用 LLM 总结最旧的消息
  第 3 级：SlidingWindow——只保留最近的 N 条消息
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from mini_agent.llm.token_counter import count_tokens
from mini_agent.models.message import Conversation, Message, Role

if TYPE_CHECKING:
    from mini_agent.llm.base import LLMProvider


class CompressionStrategy(ABC):
    @abstractmethod
    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        """Mutate conversation.messages in-place to reduce token count.
        原地修改 conversation.messages 以减少 token 数。"""
        ...


class DropToolResults(CompressionStrategy):
    """Stage 1: Replace verbose tool outputs with short summaries.
    第 1 级：用简短摘要替换冗长的工具输出。"""

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
    第 2 级：把最旧的一批消息总结成一条摘要消息。

    Uses a simple extractive approach (no LLM call in P4 — keeps it fast
    and avoids recursive API calls). A full LLM-based summary can be
    plugged in later.

    使用简单的抽取式方法（P4 阶段不调用 LLM——保持速度快并避免递归 API 调用）。
    以后可以接入完整的基于 LLM 的摘要。
    """

    KEEP_RECENT = 6  # always keep the most recent N messages untouched
    # 始终保持最近的 N 条消息不动

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        msgs = conversation.messages
        if len(msgs) <= self.KEEP_RECENT:
            return

        to_summarize = msgs[: len(msgs) - self.KEEP_RECENT]
        kept = msgs[len(msgs) - self.KEEP_RECENT :]

        summary_text = "[Compressed conversation history]\n" + _extractive_digest(to_summarize)
        conversation.messages = [_make_summary_message(summary_text)] + kept


def _extractive_digest(messages: list[Message]) -> str:
    """Mechanical digest: role + content snippet per message.
    机械式摘要：每条消息取角色 + 内容片段。"""
    parts: list[str] = []
    for msg in messages:
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
    return "\n".join(parts)


def _make_summary_message(summary_text: str) -> Message:
    msg = Message(role=Role.SYSTEM, content=summary_text, compressed=True)
    msg.token_count = count_tokens(summary_text) + 4
    return msg


_SUMMARY_PROMPT = """Summarize this conversation history between a user and a coding agent.
Preserve, in compact form:
1. The task goal(s) the user asked for
2. Steps already completed (files read/modified, commands run, their outcomes)
3. Key files, findings, and decisions
4. Any unresolved issues or pending work

Be factual and dense. Output the summary only, no preamble.

Conversation history:
{history}"""


class LLMSummarizeOldest(CompressionStrategy):
    """Stage 2 (LLM variant): semantically summarize the oldest messages via LLM.
    第 2 级（LLM 变体）：用 LLM 对最旧的消息做语义摘要。

    Falls back to the extractive digest if the LLM call fails -- the
    compression chain must never break on a network error.
    LLM 调用失败时回退到抽取式摘要——压缩链绝不能因网络错误中断。
    """

    KEEP_RECENT = 6
    MAX_HISTORY_CHARS = 24_000  # cap the summarization request size 限制摘要请求的大小

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        msgs = conversation.messages
        if len(msgs) <= self.KEEP_RECENT:
            return

        to_summarize = msgs[: len(msgs) - self.KEEP_RECENT]
        kept = msgs[len(msgs) - self.KEEP_RECENT :]

        digest = _extractive_digest(to_summarize)
        try:
            summary = await self._summarize(digest[: self.MAX_HISTORY_CHARS])
            summary_text = "[Compressed conversation history (LLM summary)]\n" + summary
        except Exception:
            summary_text = "[Compressed conversation history]\n" + digest

        conversation.messages = [_make_summary_message(summary_text)] + kept

    async def _summarize(self, history: str) -> str:
        # One-shot direct LLM call, bypasses AgentLoop -- no recursion risk.
        # 一次性直连 LLM 调用，不经过 AgentLoop——无递归风险。
        messages = [{"role": "user", "content": _SUMMARY_PROMPT.format(history=history)}]
        parts: list[str] = []
        async for chunk in self._llm.stream(messages):
            if chunk.delta:
                parts.append(chunk.delta)
        summary = "".join(parts).strip()
        if not summary:
            raise ValueError("empty summary from LLM")
        return summary


class SlidingWindow(CompressionStrategy):
    """Stage 3: Keep only messages that fit within target_tokens (last resort).
    第 3 级：只保留能放进 target_tokens 预算内的消息（最后手段）。"""

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

        # Task anchor: NEVER drop the latest user message. A long turn (one
        # question + dozens of tool results) can push the question itself out
        # of the window -- the LLM then finishes reading and asks "what did
        # you want?" because the task is gone.
        # 任务锚点：绝不丢弃最近一条用户消息。长轮次（一个提问 + 几十条工具
        # 结果）会把提问本身挤出窗口——LLM 读完文件后反问"你要我做什么"，
        # 因为任务没了。
        if not any(m.role == Role.USER for m in kept):
            for msg in reversed(conversation.messages):
                if msg.role == Role.USER:
                    kept.insert(0, msg)
                    break

        conversation.messages = kept


class Compressor:
    """Runs compression strategies in cascade until target is met.
    级联运行各压缩策略，直到达到目标。"""

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
