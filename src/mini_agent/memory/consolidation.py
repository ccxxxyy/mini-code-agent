"""Memory consolidation -- LLM merges semantically related memories (P53).
记忆合并——LLM 语义合并相关记忆。

Word-overlap dedup only catches surface similarity; semantically related
entries with different wording accumulate as redundancy. When entry count
exceeds the threshold, an LLM identifies mergeable groups and consolidates
each into a single entry. Falls back silently to no-op on any failure.
词重叠去重只能捕捉表面相似性；用词不同但语义相关的条目会冗余累积。
条目超过阈值时，LLM 识别可合并的组并各合并为一条。任何失败静默 no-op。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mini_agent.memory.persistent import MemoryEntry

logger = logging.getLogger(__name__)

CONSOLIDATION_PROMPT = """\
You are a memory consolidator. Below is a list of memory entries. Identify
groups of entries that are semantically related and can be merged into one.
Output ONLY a JSON array (no markdown fences) of merge groups. Each group:
{{"merge_ids": ["id1", "id2"], "merged_content": "..."}}
Rules:
- Only merge entries that are clearly about the same topic
- merged_content must preserve ALL information from the merged entries
- A group needs at least 2 entries
- If nothing should be merged, return []

Memory entries (id: content):
{memory_list}"""


class MemoryConsolidator:
    """Merges semantically related memories via a lightweight LLM call.
    通过轻量 LLM 调用合并语义相关的记忆。"""

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    async def consolidate(self, entries: list[MemoryEntry]) -> list[MemoryEntry] | None:
        """Merge related entries. Returns the new list, or None when nothing
        was merged (or on any failure) -- caller should no-op on None.
        合并相关条目。返回新列表；无合并或失败返回 None（调用方 no-op）。"""
        if self._llm is None or len(entries) < 2:
            return None

        memory_list = "\n".join(f"{e.id}: {e.content}" for e in entries)
        prompt = CONSOLIDATION_PROMPT.format(memory_list=memory_list)
        messages = [{"role": "user", "content": prompt}]

        try:
            from mini_agent.llm.base import complete

            response = await complete(self._llm, messages)
            groups = self._parse_groups(response.content)
        except Exception:
            logger.warning("LLM consolidation failed", exc_info=True)
            return None

        if not groups:
            return None

        by_id = {e.id: e for e in entries}
        consumed: set[str] = set()
        merged_entries: list[MemoryEntry] = []

        for group in groups:
            valid_ids = [i for i in group["merge_ids"] if i in by_id and i not in consumed]
            if len(valid_ids) < 2:
                continue
            members = [by_id[i] for i in valid_ids]
            newest = max(m.created_at for m in members)
            tags: list[str] = []
            for m in members:
                for t in m.tags:
                    if t not in tags:
                        tags.append(t)
            merged_entries.append(
                MemoryEntry(
                    content=group["merged_content"],
                    source="extracted",
                    created_at=newest,
                    tags=tags,
                )
            )
            consumed.update(valid_ids)

        if not merged_entries:
            return None

        result = [e for e in entries if e.id not in consumed]
        result.extend(merged_entries)
        return result

    @staticmethod
    def _parse_groups(text: str) -> list[dict[str, Any]] | None:
        """Parse the LLM's JSON array of merge groups. None on failure.
        解析 LLM 返回的合并组 JSON 数组。失败返回 None。"""
        try:
            from mini_agent.memory._utils import strip_json_fence

            clean = strip_json_fence(text)
            items = json.loads(clean)
            if not isinstance(items, list):
                return None
            groups = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                ids = item.get("merge_ids")
                content = item.get("merged_content")
                if not isinstance(ids, list) or not isinstance(content, str):
                    continue
                if not content.strip():
                    continue
                groups.append({"merge_ids": [str(i) for i in ids], "merged_content": content})
            return groups
        except (json.JSONDecodeError, ValueError, TypeError):
            return None
