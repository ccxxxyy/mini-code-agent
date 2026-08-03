"""Memory extraction -- pull learnings from conversations.
记忆提取——从对话中提取学到的内容。

Extracts key facts, preferences, and conventions mentioned in the
conversation and stores them as MemoryEntry objects. Uses simple
heuristic extraction (keyword/pattern-based) in P4 to avoid recursive
LLM calls. A full LLM-based extractor can be plugged in later.

提取对话中提到的关键事实、偏好和约定，并将其存储为 MemoryEntry 对象。
P4 阶段使用简单的启发式提取（基于关键词/模式）以避免递归的 LLM 调用。
以后可以接入完整的基于 LLM 的提取器。
"""

from __future__ import annotations

import re
from pathlib import Path

from mini_agent.memory.persistent import MemoryEntry, PersistentMemory
from mini_agent.models.message import Conversation, Role

# Patterns that suggest extractable facts 暗示存在可提取事实的模式
EXTRACT_PATTERNS = [
    (r"(?:always|prefer|please|make sure|remember)\s+(.{10,80})", "preference"),
    (r"(?:this project|we|our team)\s+(?:uses?|runs?|requires?)\s+(.{10,80})", "convention"),
    (r"(?:don'?t|never|avoid)\s+(.{10,60})", "constraint"),
]

MIN_TURNS_FOR_EXTRACTION = 5


class MemoryExtractor:
    """Extracts learnings from conversations and persists them. 从对话中提取学到的内容并持久化。"""

    def __init__(self, persistent_memory: PersistentMemory) -> None:
        self._memory = persistent_memory

    async def maybe_extract(
        self,
        conversation: Conversation,
        project_dir: Path | None = None,
    ) -> list[MemoryEntry]:
        """Analyze conversation for extractable learnings.
        分析对话中可提取的学习内容。

        Only triggers after MIN_TURNS_FOR_EXTRACTION turns.
        Deduplicates against existing memories.

        仅在达到 MIN_TURNS_FOR_EXTRACTION 轮之后触发。
        会与已有记忆去重。
        """
        user_messages = [m for m in conversation.messages if m.role == Role.USER]
        if len(user_messages) < MIN_TURNS_FOR_EXTRACTION:
            return []

        candidates = self._extract_candidates(conversation)
        if not candidates:
            return []

        existing = await self._memory.load_user_memory()
        if project_dir:
            existing += await self._memory.load_project_memory(project_dir)

        new_entries = self._deduplicate(candidates, existing)

        for entry in new_entries:
            if project_dir:
                await self._memory.add_project_memory(project_dir, entry)
            else:
                await self._memory.add_user_memory(entry)

        return new_entries

    def _extract_candidates(self, conversation: Conversation) -> list[MemoryEntry]:
        """Extract candidate memories from user messages using patterns.
        使用模式从用户消息中提取候选记忆。"""
        candidates: list[MemoryEntry] = []
        seen_content: set[str] = set()

        for msg in conversation.messages:
            if msg.role != Role.USER:
                continue
            text = msg.content
            for pattern, tag in EXTRACT_PATTERNS:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    content = match.group(1).strip().rstrip(".,;:!")
                    content_key = content.lower()
                    if content_key not in seen_content and len(content) > 10:
                        seen_content.add(content_key)
                        candidates.append(
                            MemoryEntry(
                                content=content,
                                source="extracted",
                                tags=[tag],
                            )
                        )
        return candidates

    @staticmethod
    def _deduplicate(
        candidates: list[MemoryEntry],
        existing: list[MemoryEntry],
    ) -> list[MemoryEntry]:
        """Remove candidates that are too similar to existing entries.
        移除与已有条目过于相似的候选项。"""
        existing_contents = {e.content.lower() for e in existing}
        new: list[MemoryEntry] = []
        for c in candidates:
            c_lower = c.content.lower()
            if c_lower not in existing_contents:
                is_substring = any(c_lower in ex for ex in existing_contents)
                if not is_substring:
                    new.append(c)
                    existing_contents.add(c_lower)
        return new
