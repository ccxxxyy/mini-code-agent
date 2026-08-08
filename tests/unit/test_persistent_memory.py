"""Tests for persistent memory and extraction. 持久化记忆与记忆提取的测试。"""

from pathlib import Path

import pytest

from mini_agent.memory.extraction import MemoryExtractor
from mini_agent.memory.persistent import MemoryEntry, PersistentMemory
from mini_agent.models.message import Conversation, Message, Role

pytestmark = pytest.mark.asyncio

# --- PersistentMemory ---


async def test_user_memory_crud(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "user_mem"))

    entries = await pm.load_user_memory()
    assert entries == []

    entry = MemoryEntry(content="User prefers tabs", tags=["style"])
    await pm.add_user_memory(entry)

    entries = await pm.load_user_memory()
    assert len(entries) == 1
    assert entries[0].content == "User prefers tabs"


async def test_project_memory_crud(tmp_path: Path):
    pm = PersistentMemory(
        user_memory_dir=str(tmp_path / "user_mem"),
        project_memory_file=".mini-agent/memory.json",
    )
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    entry = MemoryEntry(content="Uses pytest", source="project", tags=["testing"])
    await pm.add_project_memory(project_dir, entry)

    entries = await pm.load_project_memory(project_dir)
    assert len(entries) == 1
    assert entries[0].content == "Uses pytest"


async def test_search_keyword(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    await pm.add_user_memory(MemoryEntry(content="Prefers type hints"))
    await pm.add_user_memory(MemoryEntry(content="Uses black formatter"))

    results = await pm.search("type hints")
    assert len(results) == 1
    assert "type hints" in results[0].content


async def test_search_by_tag(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    await pm.add_user_memory(MemoryEntry(content="something", tags=["python", "style"]))
    await pm.add_user_memory(MemoryEntry(content="other", tags=["rust"]))

    results = await pm.search("python")
    assert len(results) == 1


async def test_search_across_project_and_user(tmp_path: Path):
    pm = PersistentMemory(
        user_memory_dir=str(tmp_path / "user"),
        project_memory_file=".mini-agent/memory.json",
    )
    project_dir = tmp_path / "proj"
    project_dir.mkdir()

    await pm.add_user_memory(MemoryEntry(content="User fact: likes vim"))
    await pm.add_project_memory(project_dir, MemoryEntry(content="Project fact: uses vim mode"))

    results = await pm.search("vim", project_dir=project_dir)
    assert len(results) == 2


async def test_delete_user_memory_by_id(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    e1 = MemoryEntry(content="fact one")
    e2 = MemoryEntry(content="fact two")
    await pm.add_user_memory(e1)
    await pm.add_user_memory(e2)

    removed = await pm.delete_user_memory(e1.id)
    assert removed is not None
    assert removed.content == "fact one"
    entries = await pm.load_user_memory()
    assert len(entries) == 1
    assert entries[0].content == "fact two"


async def test_delete_user_memory_by_content(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    await pm.add_user_memory(MemoryEntry(content="prefers tabs"))
    await pm.add_user_memory(MemoryEntry(content="uses vim"))

    removed = await pm.delete_user_memory("tabs")
    assert removed is not None
    assert "tabs" in removed.content
    assert len(await pm.load_user_memory()) == 1


async def test_delete_user_memory_not_found(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    await pm.add_user_memory(MemoryEntry(content="something"))
    removed = await pm.delete_user_memory("nonexistent")
    assert removed is None
    assert len(await pm.load_user_memory()) == 1


async def test_delete_ambiguous_content_returns_first_only(tmp_path: Path):
    """At the storage layer, delete by content picks the first match.
    The command handler adds a multi-match guard on top."""
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    await pm.add_user_memory(MemoryEntry(content="测试一"))
    await pm.add_user_memory(MemoryEntry(content="测试二"))

    removed = await pm.delete_user_memory("测试")
    assert removed is not None
    assert removed.content == "测试一"
    remaining = await pm.load_user_memory()
    assert len(remaining) == 1
    assert remaining[0].content == "测试二"


async def test_delete_project_memory(tmp_path: Path):
    pm = PersistentMemory(
        user_memory_dir=str(tmp_path / "user"),
        project_memory_file=".mini-agent/memory.json",
    )
    proj = tmp_path / "proj"
    proj.mkdir()
    e = MemoryEntry(content="project fact", source="project")
    await pm.add_project_memory(proj, e)

    removed = await pm.delete_project_memory(proj, e.id)
    assert removed is not None
    assert len(await pm.load_project_memory(proj)) == 0


# --- MemoryExtractor (LLM-based, P30) ---


class _MockExtractionLLM:
    """MockLLM that returns a configurable JSON string for extraction.
    返回可配置 JSON 字符串的 MockLLM。"""

    def __init__(self, response_text: str):
        self._response = response_text

    async def stream(self, messages, **kwargs):
        from mini_agent.llm.base import StreamChunk

        yield StreamChunk(delta=self._response)
        yield StreamChunk(finish_reason="stop")


def _make_conv(turns: int = 6) -> Conversation:
    conv = Conversation()
    for i in range(turns):
        conv.append(Message(role=Role.USER, content=f"question {i}"))
        conv.append(Message(role=Role.ASSISTANT, content=f"answer {i}"))
    return conv


async def test_extraction_too_few_turns(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    llm = _MockExtractionLLM("[]")
    extractor = MemoryExtractor(pm, llm)

    conv = Conversation()
    conv.append(Message(role=Role.USER, content="hello"))
    entries = await extractor.maybe_extract(conv)
    assert entries == []


async def test_llm_extraction_parses_json(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    json_resp = (
        '[{"content": "User prefers type hints", "category": "preference", "tags": ["coding"]}]'
    )
    llm = _MockExtractionLLM(json_resp)
    extractor = MemoryExtractor(pm, llm)

    conv = _make_conv()
    entries = await extractor.maybe_extract(conv)
    assert len(entries) == 1
    assert "type hints" in entries[0].content
    assert "preference" in entries[0].tags


async def test_llm_extraction_empty_response(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    llm = _MockExtractionLLM("[]")
    extractor = MemoryExtractor(pm, llm)

    conv = _make_conv()
    entries = await extractor.maybe_extract(conv)
    assert entries == []


async def test_llm_extraction_malformed_json(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    llm = _MockExtractionLLM("this is not json at all {{{")
    extractor = MemoryExtractor(pm, llm)

    conv = _make_conv()
    entries = await extractor.maybe_extract(conv)
    assert entries == []


async def test_llm_extraction_markdown_fenced(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    fenced = '```json\n[{"content": "uses uv", "category": "convention"}]\n```'
    llm = _MockExtractionLLM(fenced)
    extractor = MemoryExtractor(pm, llm)

    conv = _make_conv()
    entries = await extractor.maybe_extract(conv)
    assert len(entries) == 1
    assert "uv" in entries[0].content


async def test_exact_dedup_still_works(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    await pm.add_user_memory(MemoryEntry(content="User prefers type hints"))

    json_resp = '[{"content": "User prefers type hints", "category": "preference"}]'
    llm = _MockExtractionLLM(json_resp)
    extractor = MemoryExtractor(pm, llm)

    conv = _make_conv()
    entries = await extractor.maybe_extract(conv)
    assert entries == []


async def test_similarity_dedup(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    await pm.add_user_memory(MemoryEntry(content="always use type hints on functions"))

    json_resp = '[{"content": "use type hints on all functions always"}]'
    llm = _MockExtractionLLM(json_resp)
    extractor = MemoryExtractor(pm, llm)

    conv = _make_conv()
    entries = await extractor.maybe_extract(conv)
    assert entries == []


async def test_extraction_stores_to_project(tmp_path: Path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    pm = PersistentMemory(
        user_memory_dir=str(tmp_path / "mem"),
        project_memory_file=".mini-agent/memory.json",
    )
    json_resp = '[{"content": "project uses pytest", "category": "convention"}]'
    llm = _MockExtractionLLM(json_resp)
    extractor = MemoryExtractor(pm, llm)

    conv = _make_conv()
    await extractor.maybe_extract(conv, project_dir=project_dir)
    stored = await pm.load_project_memory(project_dir)
    assert len(stored) >= 1


async def test_no_llm_returns_empty(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    extractor = MemoryExtractor(pm, llm=None)

    conv = _make_conv()
    entries = await extractor.maybe_extract(conv)
    assert entries == []
