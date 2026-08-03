"""Tests for session persistence."""

from pathlib import Path

from mini_agent.memory.session_store import SessionStore
from mini_agent.models.message import Message, Role, ToolCall, ToolResult
from mini_agent.models.session import Session


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
