"""Selective memory recall -- LLM picks the most relevant memories.
选择性记忆召回——LLM 挑选与当前消息最相关的记忆。

When memory count exceeds the threshold, a lightweight LLM call selects the
top-k most relevant entries instead of blindly injecting the first N.
Falls back silently to head-truncation on any failure (recall must never
block the main request).
记忆超过阈值时，用轻量 LLM 调用挑选最相关的 top-k 条，而非盲目注入前 N 条。
任何失败静默回退到头部截断（召回绝不阻断主请求）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mini_agent.memory.persistent import MemoryEntry

logger = logging.getLogger(__name__)

FALLBACK_LIMIT = 10

RECALL_PROMPT = """\
You are a memory selector. Given the user's latest message and a list of
memory entries, return a JSON array of the IDs of the at most {top_k} entries
most relevant to the message. Return ONLY the JSON array (no markdown fences),
e.g. ["mem_abc123", "mem_def456"]. If none are relevant, return [].

User message:
{user_message}

Memory entries (id: content preview):
{memory_list}"""


class MemoryRecall:
    """Selects the most relevant memories via a lightweight LLM call.
    通过轻量 LLM 调用挑选最相关的记忆。"""

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    async def select_relevant(
        self,
        entries: list[MemoryEntry],
        user_message: str,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        """Pick at most top_k relevant entries. Falls back to head-truncation.
        挑选最多 top_k 条相关记忆。失败时回退头部截断。"""
        if self._llm is None or not entries:
            return entries[:FALLBACK_LIMIT]

        memory_list = "\n".join(f"{e.id}: {e.content[:50]}" for e in entries)
        prompt = RECALL_PROMPT.format(
            top_k=top_k,
            user_message=user_message[:500],
            memory_list=memory_list,
        )
        messages = [{"role": "user", "content": prompt}]

        try:
            from mini_agent.llm.base import complete

            response = await complete(self._llm, messages)
            ids = self._parse_ids(response.content)
        except Exception:
            logger.warning("LLM recall ranking failed", exc_info=True)
            return entries[:FALLBACK_LIMIT]

        if ids is None:
            return entries[:FALLBACK_LIMIT]

        by_id = {e.id: e for e in entries}
        selected = [by_id[i] for i in ids if i in by_id]
        return selected[:top_k]

    @staticmethod
    def _parse_ids(text: str) -> list[str] | None:
        """Parse the LLM's JSON array of IDs. Returns None on failure.
        解析 LLM 返回的 ID JSON 数组。失败返回 None。"""
        try:
            from mini_agent.memory._utils import strip_json_fence

            clean = strip_json_fence(text)
            ids = json.loads(clean)
            if not isinstance(ids, list):
                return None
            return [str(i) for i in ids]
        except (json.JSONDecodeError, ValueError, TypeError):
            return None


class RecallPrefetcher:
    """Parallel recall prefetch -- selection runs alongside the main LLM call
    (tech-notes §111). 并行召回预取——挑选与主 LLM 调用并行。

    Awaiting select_relevant() inline on the injection path adds a full LLM
    round-trip to first-token latency. Instead, the first poll() starts the
    selection as a background task and returns immediately -- the main LLM
    call proceeds while the selector runs. Later polls await the result,
    which by then has usually completed behind the previous round. Timeout
    or failure degrades to head-truncation (recall must never break the
    main request).
    在注入路径上内联 await 会把一次完整 LLM 往返加进首 token 延迟。
    首次 poll() 把挑选放进后台任务立即返回——主 LLM 调用与挑选并行。
    后续 poll await 结果（通常已藏在上一轮延迟后面完成）。
    超时或失败降级头部截断（召回绝不打断主请求）。"""

    def __init__(self, llm: Any = None, timeout: float = 8.0) -> None:
        self._recall = MemoryRecall(llm)
        self._timeout = timeout
        self._task: asyncio.Task[list[MemoryEntry]] | None = None

    async def poll(
        self,
        entries: list[MemoryEntry],
        user_message: str,
        top_k: int = 5,
    ) -> list[MemoryEntry] | None:
        """First call starts the prefetch and returns None immediately (the
        main LLM call proceeds unblocked); later calls await the selection --
        it usually finished during the previous round, so only the residual
        (bounded by the task's overall timeout) can block. Timeout/failure
        returns head-truncation fallback.
        首次调用启动预取并立即返回 None（主 LLM 调用不受阻）；后续调用
        await 挑选结果——通常已在上一轮期间完成，最多阻塞残余时间（受任务
        整体超时约束）。超时/失败返回头部截断降级。"""
        if self._task is None:
            self._task = asyncio.create_task(
                asyncio.wait_for(
                    self._recall.select_relevant(entries, user_message, top_k),
                    timeout=self._timeout,
                )
            )
            return None
        try:
            return await self._task
        except Exception:
            logger.warning("recall prefetch failed or timed out; falling back")
            return entries[:FALLBACK_LIMIT]

    def cancel(self) -> None:
        """Cancel a pending prefetch and reset. 取消未完成的预取并重置。"""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
