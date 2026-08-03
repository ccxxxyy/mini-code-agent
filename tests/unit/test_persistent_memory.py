"""Tests for persistent memory and extraction. 持久化记忆与记忆提取的测试。"""

from pathlib import Path

from mini_agent.memory.extraction import MemoryExtractor
from mini_agent.memory.persistent import MemoryEntry, PersistentMemory
from mini_agent.models.message import Conversation, Message, Role

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


# --- MemoryExtractor ---


async def test_extraction_too_few_turns(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    extractor = MemoryExtractor(pm)

    conv = Conversation()
    conv.append(Message(role=Role.USER, content="always use type hints"))

    entries = await extractor.maybe_extract(conv)
    assert entries == []  # too few turns 轮次太少


async def test_extraction_finds_preferences(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    extractor = MemoryExtractor(pm)

    conv = Conversation()
    for i in range(6):
        conv.append(Message(role=Role.USER, content=f"question {i}"))
        conv.append(Message(role=Role.ASSISTANT, content=f"answer {i}"))
    conv.append(Message(role=Role.USER, content="please always use type hints on all functions"))

    entries = await extractor.maybe_extract(conv)
    assert len(entries) >= 1
    assert any("type hints" in e.content for e in entries)


async def test_extraction_deduplicates(tmp_path: Path):
    pm = PersistentMemory(user_memory_dir=str(tmp_path / "mem"))
    await pm.add_user_memory(MemoryEntry(content="use type hints on all functions"))

    extractor = MemoryExtractor(pm)
    conv = Conversation()
    for i in range(6):
        conv.append(Message(role=Role.USER, content=f"msg {i}"))
        conv.append(Message(role=Role.ASSISTANT, content=f"ans {i}"))
    conv.append(Message(role=Role.USER, content="always use type hints on all functions"))

    entries = await extractor.maybe_extract(conv)
    # Should deduplicate: "use type hints on all functions" already exists
    # 应去重："use type hints on all functions" 已存在
    assert all("type hints" not in e.content for e in entries)


async def test_extraction_stores_to_project(tmp_path: Path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    pm = PersistentMemory(
        user_memory_dir=str(tmp_path / "mem"),
        project_memory_file=".mini-agent/memory.json",
    )
    extractor = MemoryExtractor(pm)

    conv = Conversation()
    for i in range(6):
        conv.append(Message(role=Role.USER, content=f"msg {i}"))
        conv.append(Message(role=Role.ASSISTANT, content=f"ans {i}"))
    conv.append(
        Message(role=Role.USER, content="this project uses pytest with --tb=short for all tests")
    )

    await extractor.maybe_extract(conv, project_dir=project_dir)
    stored = await pm.load_project_memory(project_dir)
    assert len(stored) >= 1
