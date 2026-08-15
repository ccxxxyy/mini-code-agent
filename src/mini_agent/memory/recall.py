"""Selective memory recall -- LLM picks the most relevant memories (P52).
选择性记忆召回——LLM 挑选与当前消息最相关的记忆。

When memory count exceeds the threshold, a lightweight LLM call selects the
top-k most relevant entries instead of blindly injecting the first N.
Falls back silently to head-truncation on any failure (recall must never
block the main request).
记忆超过阈值时，用轻量 LLM 调用挑选最相关的 top-k 条，而非盲目注入前 N 条。
任何失败静默回退到头部截断（召回绝不阻断主请求）。
"""

from __future__ import annotations

import json
from typing import Any

from mini_agent.memory.persistent import MemoryEntry

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
            from mini_agent.llm.openai_provider import assemble_response

            chunks = []
            async for chunk in self._llm.stream(messages):
                chunks.append(chunk)
            response = assemble_response(chunks)
            ids = self._parse_ids(response.content)
        except Exception:
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
