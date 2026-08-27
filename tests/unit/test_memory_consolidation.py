"""Tests for memory consolidation. 记忆合并测试。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mini_agent.llm.base import StreamChunk
from mini_agent.memory.consolidation import MemoryConsolidator
from mini_agent.memory.persistent import MemoryEntry

pytestmark = pytest.mark.asyncio


class _MockLLM:
    def __init__(self, response: str):
        self._response = response

    async def stream(self, messages: list[dict], **kwargs: Any):
        yield StreamChunk(delta=self._response)
        yield StreamChunk(finish_reason="stop")


class _ExplodingLLM:
    async def stream(self, messages: list[dict], **kwargs: Any):
        raise RuntimeError("boom")
        yield  # pragma: no cover


def make_entries() -> list[MemoryEntry]:
    return [
        MemoryEntry(
            id="mem_001",
            content="User prefers tabs for indentation",
            source="user",
            created_at="2026-01-01T10:00:00",
            tags=["preference"],
        ),
        MemoryEntry(
            id="mem_002",
            content="User dislikes spaces for indentation",
            source="extracted",
            created_at="2026-02-01T10:00:00",
            tags=["style"],
        ),
        MemoryEntry(
            id="mem_003",
            content="Project uses pytest for testing",
            source="project",
            created_at="2026-03-01T10:00:00",
            tags=["convention"],
        ),
    ]


def merge_response(ids: list[str], content: str) -> str:
    return json.dumps([{"merge_ids": ids, "merged_content": content}])


async def test_consolidate_merges_group():
    entries = make_entries()
    llm = _MockLLM(merge_response(["mem_001", "mem_002"], "User prefers tabs over spaces"))
    result = await MemoryConsolidator(llm).consolidate(entries)
    assert result is not None
    assert len(result) == 2
    contents = [e.content for e in result]
    assert "User prefers tabs over spaces" in contents
    assert "Project uses pytest for testing" in contents


async def test_consolidate_keeps_newest_created_at():
    entries = make_entries()
    llm = _MockLLM(merge_response(["mem_001", "mem_002"], "merged"))
    result = await MemoryConsolidator(llm).consolidate(entries)
    merged = next(e for e in result if e.content == "merged")
    assert merged.created_at == "2026-02-01T10:00:00"


async def test_consolidate_merges_tags():
    entries = make_entries()
    llm = _MockLLM(merge_response(["mem_001", "mem_002"], "merged"))
    result = await MemoryConsolidator(llm).consolidate(entries)
    merged = next(e for e in result if e.content == "merged")
    assert merged.tags == ["preference", "style"]
    assert merged.source == "extracted"


async def test_consolidate_unmerged_preserved():
    entries = make_entries()
    llm = _MockLLM(merge_response(["mem_001", "mem_002"], "merged"))
    result = await MemoryConsolidator(llm).consolidate(entries)
    untouched = next(e for e in result if e.id == "mem_003")
    assert untouched.content == "Project uses pytest for testing"
    assert untouched.created_at == "2026-03-01T10:00:00"


async def test_consolidate_single_id_group_ignored():
    entries = make_entries()
    llm = _MockLLM(merge_response(["mem_001"], "should not merge"))
    result = await MemoryConsolidator(llm).consolidate(entries)
    assert result is None


async def test_consolidate_hallucinated_ids_filtered():
    entries = make_entries()
    llm = _MockLLM(merge_response(["mem_001", "mem_999"], "should not merge"))
    result = await MemoryConsolidator(llm).consolidate(entries)
    assert result is None


async def test_consolidate_duplicate_id_across_groups():
    entries = make_entries()
    response = json.dumps(
        [
            {"merge_ids": ["mem_001", "mem_002"], "merged_content": "first merge"},
            {"merge_ids": ["mem_002", "mem_003"], "merged_content": "second merge"},
        ]
    )
    llm = _MockLLM(response)
    result = await MemoryConsolidator(llm).consolidate(entries)
    assert result is not None
    contents = [e.content for e in result]
    assert "first merge" in contents
    assert "second merge" not in contents  # mem_002 already consumed
    assert "Project uses pytest for testing" in contents


async def test_consolidate_empty_result_returns_none():
    entries = make_entries()
    llm = _MockLLM("[]")
    result = await MemoryConsolidator(llm).consolidate(entries)
    assert result is None


async def test_consolidate_invalid_json_returns_none():
    entries = make_entries()
    llm = _MockLLM("not json")
    result = await MemoryConsolidator(llm).consolidate(entries)
    assert result is None


async def test_consolidate_llm_none_returns_none():
    result = await MemoryConsolidator(None).consolidate(make_entries())
    assert result is None


async def test_consolidate_exception_returns_none():
    result = await MemoryConsolidator(_ExplodingLLM()).consolidate(make_entries())
    assert result is None


async def test_consolidate_fewer_than_two_entries():
    llm = _MockLLM("[]")
    result = await MemoryConsolidator(llm).consolidate([make_entries()[0]])
    assert result is None


async def test_consolidate_markdown_fenced():
    entries = make_entries()
    inner = merge_response(["mem_001", "mem_002"], "fenced merge")
    llm = _MockLLM(f"```json\n{inner}\n```")
    result = await MemoryConsolidator(llm).consolidate(entries)
    assert result is not None
    assert any(e.content == "fenced merge" for e in result)


def test_parse_groups_valid():
    groups = MemoryConsolidator._parse_groups('[{"merge_ids": ["a"], "merged_content": "x"}]')
    assert groups == [{"merge_ids": ["a"], "merged_content": "x"}]


def test_parse_groups_invalid():
    assert MemoryConsolidator._parse_groups("garbage") is None
    assert MemoryConsolidator._parse_groups('{"a": 1}') is None


def test_parse_groups_skips_malformed_items():
    text = json.dumps(
        [
            {"merge_ids": "not-a-list", "merged_content": "x"},
            {"merge_ids": ["a", "b"], "merged_content": ""},
            {"merge_ids": ["a", "b"], "merged_content": "valid"},
            "not-a-dict",
        ]
    )
    groups = MemoryConsolidator._parse_groups(text)
    assert len(groups) == 1
    assert groups[0]["merged_content"] == "valid"
