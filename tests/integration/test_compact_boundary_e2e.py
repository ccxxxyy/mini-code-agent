"""E2E: compression → save → load → boundary restores read-files state.
端到端：压缩 → 保存 → 加载 → 边界恢复已读文件状态。

Exercises the full chain without a real LLM:
  ContextManager tracks read files → Compressor records boundary →
  SessionStore persists boundary → load skips compressed SYSTEM →
  adopt_boundary restores read-files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mini_agent.memory.compressor import Compressor
from mini_agent.memory.context import ContextManager
from mini_agent.memory.session_store import SessionStore
from mini_agent.models.config import MemoryConfig
from mini_agent.models.message import Conversation, Message, Role
from mini_agent.models.session import Session

pytestmark = pytest.mark.asyncio


def _build_long_conversation(n_messages: int = 20) -> Conversation:
    conv = Conversation(system_prompt="You are helpful.")
    for i in range(n_messages):
        if i % 2 == 0:
            conv.append(Message(role=Role.USER, content=f"Question {i} " + "x" * 200))
        else:
            conv.append(Message(role=Role.ASSISTANT, content=f"Answer {i} " + "y" * 200))
    return conv


async def test_compress_save_load_boundary(tmp_path: Path):
    """Full chain: compress with read-files → save → load → boundary present,
    compressed SYSTEM skipped, read-files recoverable."""
    config = MemoryConfig(context_window=600, compression_threshold=0.3)
    ctx = ContextManager(config)
    compressor = Compressor()
    ctx.set_compressor(compressor)

    ctx.record_file_read("src/main.py")
    ctx.record_file_read("README.md")

    conv = _build_long_conversation(20)
    session = Session()
    session.conversation = conv

    compressed = await ctx.check_and_compress(conv)
    assert compressed, "compression should have fired"
    assert conv.compact_boundary is not None
    assert conv.compact_boundary["read_files"] == ["src/main.py", "README.md"]
    assert "summary" in conv.compact_boundary

    summary_msgs_before = [
        m for m in conv.messages if m.compressed and m.role == Role.SYSTEM
    ]
    assert len(summary_msgs_before) >= 1

    store = SessionStore(session_dir=str(tmp_path))
    await store.save(session)
    loaded = await store.load(session.metadata.session_id)

    assert loaded is not None
    assert loaded.conversation.compact_boundary is not None
    assert loaded.conversation.compact_boundary["read_files"] == [
        "src/main.py",
        "README.md",
    ]

    loaded_msgs = loaded.conversation.messages
    assert loaded_msgs[0].role == Role.SYSTEM
    assert loaded_msgs[0].compressed is True
    assert loaded_msgs[0].content == conv.compact_boundary["summary"]

    non_system_compressed = [
        m
        for m in loaded_msgs[1:]
        if m.compressed and m.role == Role.SYSTEM
    ]
    assert len(non_system_compressed) == 0, "duplicate compressed SYSTEM should be skipped"

    ctx2 = ContextManager(MemoryConfig())
    assert ctx2.read_files == []
    ctx2.adopt_boundary(loaded.conversation)
    assert ctx2.read_files == ["src/main.py", "README.md"]


async def test_legacy_session_no_boundary(tmp_path: Path):
    """Sessions saved before this feature load identically (backward compat)."""
    store = SessionStore(session_dir=str(tmp_path))
    session = Session()
    session.conversation.append(
        Message(role=Role.SYSTEM, content="[old summary]", compressed=True)
    )
    session.conversation.append(Message(role=Role.USER, content="hi"))
    session.conversation.append(Message(role=Role.ASSISTANT, content="hello"))

    await store.save(session)
    loaded = await store.load(session.metadata.session_id)

    assert loaded is not None
    assert loaded.conversation.compact_boundary is None
    assert len(loaded.conversation.messages) == 3
    assert loaded.conversation.messages[0].content == "[old summary]"
    assert loaded.conversation.messages[0].compressed is True
