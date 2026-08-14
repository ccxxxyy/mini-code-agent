"""Tests for session persistence. session 持久化的测试。"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mini_agent.memory.session_store import SessionStore
from mini_agent.models.message import Message, Role, ToolCall, ToolResult
from mini_agent.models.session import Session

pytestmark = pytest.mark.asyncio


async def test_save_and_load(tmp_path: Path):
    store = SessionStore(session_dir=str(tmp_path))
    session = Session()
    session.metadata.model = "test-model"
    session.conversation.system_prompt = "You are helpful."
    session.conversation.append(Message(role=Role.USER, content="hello"))
    session.conversation.append(Message(role=Role.ASSISTANT, content="hi there"))

    await store.save(session)
    loaded = await store.load(session.metadata.session_id)

    assert loaded is not None
    assert loaded.metadata.session_id == session.metadata.session_id
    assert loaded.metadata.model == "test-model"
    assert loaded.conversation.system_prompt == "You are helpful."
    assert len(loaded.conversation.messages) == 2
    assert loaded.conversation.messages[0].content == "hello"
    assert loaded.conversation.messages[1].content == "hi there"


async def test_save_with_tool_calls(tmp_path: Path):
    store = SessionStore(session_dir=str(tmp_path))
    session = Session()

    tc = ToolCall(id="tc1", name="read_file", arguments={"path": "/tmp/a"})
    session.conversation.append(Message(role=Role.ASSISTANT, content="", tool_calls=[tc]))

    tr = ToolResult(call_id="tc1", name="read_file", output="file content")
    session.conversation.append(Message(role=Role.TOOL, tool_result=tr))

    await store.save(session)
    loaded = await store.load(session.metadata.session_id)

    assert loaded is not None
    assert len(loaded.conversation.messages) == 2
    assert loaded.conversation.messages[0].tool_calls[0].name == "read_file"
    assert loaded.conversation.messages[1].tool_result.output == "file content"


async def test_list_sessions(tmp_path: Path):
    store = SessionStore(session_dir=str(tmp_path))

    s1 = Session()
    s1.metadata.model = "model-a"
    s1.metadata.total_turns = 5
    await store.save(s1)

    s2 = Session()
    s2.metadata.model = "model-b"
    s2.metadata.total_turns = 10
    await store.save(s2)

    sessions = await store.list_sessions()
    assert len(sessions) == 2
    ids = {s["session_id"] for s in sessions}
    assert s1.metadata.session_id in ids
    assert s2.metadata.session_id in ids


async def test_delete_session(tmp_path: Path):
    store = SessionStore(session_dir=str(tmp_path))
    session = Session()
    await store.save(session)

    deleted = await store.delete(session.metadata.session_id)
    assert deleted

    loaded = await store.load(session.metadata.session_id)
    assert loaded is None


async def test_delete_nonexistent(tmp_path: Path):
    store = SessionStore(session_dir=str(tmp_path))
    assert not await store.delete("nonexistent_id")


async def test_load_nonexistent(tmp_path: Path):
    store = SessionStore(session_dir=str(tmp_path))
    assert await store.load("nonexistent") is None


# --- cleanup_stale ---


def _backdate_session(store: SessionStore, session: Session, days_ago: int) -> None:
    """Save a session then overwrite its last_active to simulate age.
    保存 session 后改写 last_active 模拟过期。"""
    import json as _json

    path = store._path_for(session.metadata.session_id)
    data = _json.loads(path.read_text(encoding="utf-8"))
    data["metadata"]["last_active"] = (datetime.now() - timedelta(days=days_ago)).isoformat()
    path.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")


async def test_cleanup_stale_removes_old_sessions(tmp_path: Path):
    store = SessionStore(session_dir=str(tmp_path))
    old = Session()
    old.metadata.closed_cleanly = True
    await store.save(old)
    _backdate_session(store, old, days_ago=45)

    recent = Session()
    recent.metadata.closed_cleanly = True
    await store.save(recent)
    _backdate_session(store, recent, days_ago=5)

    removed = await store.cleanup_stale(max_age_days=30)
    assert removed == 1
    assert await store.load(old.metadata.session_id) is None
    assert await store.load(recent.metadata.session_id) is not None


async def test_cleanup_stale_skips_unclean_sessions(tmp_path: Path):
    store = SessionStore(session_dir=str(tmp_path))
    crashed = Session()
    crashed.metadata.closed_cleanly = False
    await store.save(crashed)
    _backdate_session(store, crashed, days_ago=60)

    removed = await store.cleanup_stale(max_age_days=30)
    assert removed == 0
    assert await store.load(crashed.metadata.session_id) is not None


async def test_cleanup_stale_disabled_with_zero(tmp_path: Path):
    store = SessionStore(session_dir=str(tmp_path))
    old = Session()
    old.metadata.closed_cleanly = True
    await store.save(old)
    _backdate_session(store, old, days_ago=999)

    removed = await store.cleanup_stale(max_age_days=0)
    assert removed == 0
    assert await store.load(old.metadata.session_id) is not None


async def test_cleanup_stale_empty_dir(tmp_path: Path):
    store = SessionStore(session_dir=str(tmp_path))
    removed = await store.cleanup_stale(max_age_days=30)
    assert removed == 0


# --- compact_boundary ---


async def test_compact_boundary_round_trip(tmp_path: Path):
    """Boundary is serialized and deserialized correctly."""
    store = SessionStore(session_dir=str(tmp_path))
    session = Session()
    session.conversation.system_prompt = "sys"
    session.conversation.append(
        Message(role=Role.SYSTEM, content="[summary]", compressed=True)
    )
    session.conversation.append(Message(role=Role.USER, content="hi"))
    session.conversation.compact_boundary = {
        "summary": "[summary]",
        "timestamp": "2025-01-01T00:00:00",
        "read_files": ["a.py", "b.py"],
    }

    await store.save(session)
    loaded = await store.load(session.metadata.session_id)

    assert loaded is not None
    assert loaded.conversation.compact_boundary is not None
    assert loaded.conversation.compact_boundary["summary"] == "[summary]"
    assert loaded.conversation.compact_boundary["read_files"] == ["a.py", "b.py"]


async def test_compact_boundary_skips_compressed_system(tmp_path: Path):
    """With a boundary, compressed SYSTEM messages are skipped on load;
    the boundary summary is used instead."""
    store = SessionStore(session_dir=str(tmp_path))
    session = Session()
    session.conversation.append(
        Message(role=Role.SYSTEM, content="old summary", compressed=True)
    )
    session.conversation.append(Message(role=Role.USER, content="q"))
    session.conversation.append(Message(role=Role.ASSISTANT, content="a"))
    session.conversation.compact_boundary = {
        "summary": "boundary summary",
        "timestamp": "2025-01-01T00:00:00",
    }

    await store.save(session)
    loaded = await store.load(session.metadata.session_id)

    assert loaded is not None
    msgs = loaded.conversation.messages
    assert msgs[0].role == Role.SYSTEM
    assert msgs[0].content == "boundary summary"
    assert msgs[0].compressed is True
    assert msgs[1].content == "q"
    assert msgs[2].content == "a"
    assert len(msgs) == 3


async def test_compact_boundary_preserves_non_compressed(tmp_path: Path):
    """Non-compressed messages are loaded normally even with boundary."""
    store = SessionStore(session_dir=str(tmp_path))
    session = Session()
    # Compressed tool result (from DropToolResults) should NOT be skipped
    tr = ToolResult(call_id="tc1", name="read_file", output="truncated...")
    session.conversation.append(
        Message(role=Role.TOOL, tool_result=tr, compressed=True)
    )
    session.conversation.append(Message(role=Role.USER, content="next"))
    session.conversation.compact_boundary = {
        "summary": "summary",
        "timestamp": "2025-01-01T00:00:00",
    }

    await store.save(session)
    loaded = await store.load(session.metadata.session_id)

    assert loaded is not None
    # summary from boundary + tool msg + user msg
    assert len(loaded.conversation.messages) == 3
    assert loaded.conversation.messages[0].content == "summary"
    assert loaded.conversation.messages[1].role == Role.TOOL
    assert loaded.conversation.messages[2].content == "next"


async def test_compact_boundary_absent_loads_all(tmp_path: Path):
    """Legacy sessions without boundary load all messages as before."""
    store = SessionStore(session_dir=str(tmp_path))
    session = Session()
    session.conversation.append(
        Message(role=Role.SYSTEM, content="old summary", compressed=True)
    )
    session.conversation.append(Message(role=Role.USER, content="hello"))
    # No compact_boundary set

    await store.save(session)
    loaded = await store.load(session.metadata.session_id)

    assert loaded is not None
    assert loaded.conversation.compact_boundary is None
    assert len(loaded.conversation.messages) == 2
    assert loaded.conversation.messages[0].content == "old summary"
    assert loaded.conversation.messages[0].compressed is True
