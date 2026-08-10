"""Tests for selective memory recall (P52). 选择性记忆召回测试。"""

from __future__ import annotations

from typing import Any

import pytest

from mini_agent.llm.base import StreamChunk
from mini_agent.memory.persistent import MemoryEntry
from mini_agent.memory.recall import MemoryRecall

pytestmark = pytest.mark.asyncio


class _MockRecallLLM:
    """Yields a fixed response text. 返回固定响应文本。"""

    def __init__(self, response: str):
        self._response = response

    async def stream(self, messages: list[dict], **kwargs: Any):
        yield StreamChunk(delta=self._response)
        yield StreamChunk(finish_reason="stop")


class _ExplodingLLM:
    async def stream(self, messages: list[dict], **kwargs: Any):
        raise RuntimeError("boom")
        yield  # pragma: no cover


def make_entries(n: int) -> list[MemoryEntry]:
    return [
        MemoryEntry(id=f"mem_{i:03d}", content=f"memory content number {i}", source="user")
        for i in range(n)
    ]


async def test_recall_selects_by_ids():
    entries = make_entries(15)
    llm = _MockRecallLLM('["mem_003", "mem_007"]')
    recall = MemoryRecall(llm)
    result = await recall.select_relevant(entries, "some question", top_k=5)
    assert [e.id for e in result] == ["mem_003", "mem_007"]


async def test_recall_preserves_llm_order():
    entries = make_entries(15)
    llm = _MockRecallLLM('["mem_010", "mem_002", "mem_005"]')
    recall = MemoryRecall(llm)
    result = await recall.select_relevant(entries, "q", top_k=5)
    assert [e.id for e in result] == ["mem_010", "mem_002", "mem_005"]


async def test_recall_caps_at_top_k():
    entries = make_entries(15)
    ids = [f'"mem_{i:03d}"' for i in range(8)]
    llm = _MockRecallLLM(f"[{', '.join(ids)}]")
    recall = MemoryRecall(llm)
    result = await recall.select_relevant(entries, "q", top_k=5)
    assert len(result) == 5


async def test_recall_invalid_json_fallback():
    entries = make_entries(15)
    llm = _MockRecallLLM("this is not json at all")
    recall = MemoryRecall(llm)
    result = await recall.select_relevant(entries, "q", top_k=5)
    assert len(result) == 10
    assert result[0].id == "mem_000"


async def test_recall_llm_none_fallback():
    entries = make_entries(15)
    recall = MemoryRecall(None)
    result = await recall.select_relevant(entries, "q", top_k=5)
    assert len(result) == 10
    assert result[0].id == "mem_000"


async def test_recall_unknown_ids_ignored():
    entries = make_entries(5)
    llm = _MockRecallLLM('["mem_002", "mem_999", "hallucinated"]')
    recall = MemoryRecall(llm)
    result = await recall.select_relevant(entries, "q", top_k=5)
    assert [e.id for e in result] == ["mem_002"]


async def test_recall_empty_result():
    entries = make_entries(15)
    llm = _MockRecallLLM("[]")
    recall = MemoryRecall(llm)
    result = await recall.select_relevant(entries, "q", top_k=5)
    assert result == []


async def test_recall_markdown_fenced_json():
    entries = make_entries(15)
    llm = _MockRecallLLM('```json\n["mem_001", "mem_004"]\n```')
    recall = MemoryRecall(llm)
    result = await recall.select_relevant(entries, "q", top_k=5)
    assert [e.id for e in result] == ["mem_001", "mem_004"]


async def test_recall_llm_exception_fallback():
    entries = make_entries(15)
    recall = MemoryRecall(_ExplodingLLM())
    result = await recall.select_relevant(entries, "q", top_k=5)
    assert len(result) == 10


async def test_recall_non_list_json_fallback():
    entries = make_entries(15)
    llm = _MockRecallLLM('{"ids": ["mem_001"]}')
    recall = MemoryRecall(llm)
    result = await recall.select_relevant(entries, "q", top_k=5)
    assert len(result) == 10


async def test_recall_empty_entries():
    recall = MemoryRecall(_MockRecallLLM("[]"))
    result = await recall.select_relevant([], "q", top_k=5)
    assert result == []


def test_parse_ids_valid():
    assert MemoryRecall._parse_ids('["a", "b"]') == ["a", "b"]


def test_parse_ids_invalid():
    assert MemoryRecall._parse_ids("garbage") is None
    assert MemoryRecall._parse_ids('{"a": 1}') is None
