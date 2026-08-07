"""Memory extraction -- LLM-based structured extraction from conversations.
记忆提取——用 LLM 从对话中结构化提取值得跨会话记住的事实。

P30 upgrade: replaces the P4 regex heuristic with an LLM call that outputs
JSON. Falls back silently on any failure (extraction must never block exit).
P30 升级：用 LLM 调用（JSON 输出）替代 P4 的正则启发式。
失败时静默降级（提取绝不阻断退出）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mini_agent.memory.persistent import MemoryEntry, PersistentMemory
from mini_agent.models.message import Conversation, Role

MIN_TURNS_FOR_EXTRACTION = 5
MAX_RECENT_MESSAGES = 20

EXTRACTION_PROMPT = """\
You are a memory extractor. From the conversation below, extract facts worth
remembering for future sessions. Output ONLY a JSON array (no markdown fences):
[{"content": "...", "category": "preference|convention|fact", "tags": ["..."]}]

Rules:
- Only extract things the USER explicitly stated or confirmed
- Skip greetings, transient questions, and task-specific details
- Each entry must be self-contained (understandable without the conversation)
- Prefer concise entries (1-2 sentences max)
- If nothing worth remembering, return []
"""


class MemoryExtractor:
    """Extracts learnings from conversations via LLM and persists them.
    通过 LLM 从对话中提取学习内容并持久化。"""

    def __init__(self, persistent_memory: PersistentMemory, llm: Any = None) -> None:
        self._memory = persistent_memory
        self._llm = llm

    async def maybe_extract(
        self,
        conversation: Conversation,
        project_dir: Path | None = None,
    ) -> list[MemoryEntry]:
        """Analyze conversation for extractable learnings.
        分析对话中可提取的学习内容。"""
        user_messages = [m for m in conversation.messages if m.role == Role.USER]
        if len(user_messages) < MIN_TURNS_FOR_EXTRACTION:
            return []

        candidates = await self._extract_candidates(conversation)
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

    async def _extract_candidates(self, conversation: Conversation) -> list[MemoryEntry]:
        """Call LLM to extract structured memories from recent messages.
        调 LLM 从最近消息中结构化提取记忆。"""
        if self._llm is None:
            return []

        recent = conversation.messages[-MAX_RECENT_MESSAGES:]
        lines = []
        for msg in recent:
            if msg.role == Role.USER and msg.content:
                lines.append(f"USER: {msg.content}")
            elif msg.role == Role.ASSISTANT and msg.content:
                lines.append(f"ASSISTANT: {msg.content[:200]}")
        if not lines:
            return []

        messages = [
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ]

        try:
            from mini_agent.llm.openai_provider import assemble_response

            chunks = []
            async for chunk in self._llm.stream(messages):
                chunks.append(chunk)
            response = assemble_response(chunks)
            return self._parse_response(response.content)
        except Exception:
            return []

    @staticmethod
    def _parse_response(text: str) -> list[MemoryEntry]:
        """Parse LLM JSON response into MemoryEntry list.
        解析 LLM JSON 响应为 MemoryEntry 列表。"""
        try:
            clean = text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()
            items = json.loads(clean)
            if not isinstance(items, list):
                return []
            entries = []
            for item in items:
                if not isinstance(item, dict) or "content" not in item:
                    continue
                content = str(item["content"]).strip()
                if len(content) < 5:
                    continue
                tags = item.get("tags", [])
                category = item.get("category", "")
                if category and category not in tags:
                    tags = [category] + list(tags)
                entries.append(MemoryEntry(content=content, source="extracted", tags=tags))
            return entries
        except (json.JSONDecodeError, ValueError, TypeError):
            return []

    @staticmethod
    def _is_similar(a: str, b: str, threshold: float = 0.6) -> bool:
        """Word-overlap similarity check. 基于词重叠的相似度检查。"""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return False
        overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
        return overlap >= threshold

    @staticmethod
    def _deduplicate(
        candidates: list[MemoryEntry],
        existing: list[MemoryEntry],
    ) -> list[MemoryEntry]:
        """Remove candidates too similar to existing entries.
        移除与已有条目过于相似的候选项。"""
        existing_contents = [e.content for e in existing]
        existing_lower = {c.lower() for c in existing_contents}
        new: list[MemoryEntry] = []
        for c in candidates:
            c_lower = c.content.lower()
            if c_lower in existing_lower:
                continue
            if any(c_lower in ex for ex in existing_lower):
                continue
            if any(MemoryExtractor._is_similar(c.content, ex) for ex in existing_contents):
                continue
            new.append(c)
            existing_contents.append(c.content)
            existing_lower.add(c_lower)
        return new
