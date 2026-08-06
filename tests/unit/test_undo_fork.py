"""Tests for /undo and /fork commands. 对话回滚与分叉命令测试。"""

from __future__ import annotations

import pytest

from mini_agent.models.message import Message, Role, ToolResult

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")

    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    return Application(ConfigLoader.load())


def add_turn(app, user_text: str, assistant_text: str, with_tool: bool = False):
    conv = app.session.conversation
    conv.append(Message(role=Role.USER, content=user_text))
    if with_tool:
        conv.append(Message(role=Role.ASSISTANT, content="", tool_calls=[]))
        conv.append(
            Message(
                role=Role.TOOL,
                tool_result=ToolResult(call_id="c1", name="bash", output="result"),
            )
        )
    conv.append(Message(role=Role.ASSISTANT, content=assistant_text))
    app.session.metadata.total_turns += 1


async def run_cmd(app, line: str) -> str:
    return await app.slash_commands.execute(line)


# --- /undo ---


async def test_undo_single_turn(app):
    add_turn(app, "q1", "a1")
    add_turn(app, "q2", "a2")
    add_turn(app, "q3", "a3")

    result = await run_cmd(app, "/undo")
    assert "Rolled back 1 turn" in result
    assert "q3" in result
    msgs = app.session.conversation.messages
    assert len(msgs) == 4
    assert msgs[-1].content == "a2"
    assert app.session.metadata.total_turns == 2


async def test_undo_multiple_turns(app):
    add_turn(app, "q1", "a1")
    add_turn(app, "q2", "a2")
    add_turn(app, "q3", "a3")

    result = await run_cmd(app, "/undo 2")
    assert "Rolled back 2 turn" in result
    msgs = app.session.conversation.messages
    assert len(msgs) == 2
    assert msgs[-1].content == "a1"


async def test_undo_too_many(app):
    add_turn(app, "q1", "a1")

    result = await run_cmd(app, "/undo 5")
    assert "Cannot undo" in result
    assert len(app.session.conversation.messages) == 2  # untouched


async def test_undo_empty(app):
    result = await run_cmd(app, "/undo")
    assert "Nothing to undo" in result


async def test_undo_removes_tool_messages(app):
    add_turn(app, "q1", "a1")
    add_turn(app, "q2", "a2", with_tool=True)

    await run_cmd(app, "/undo")
    msgs = app.session.conversation.messages
    assert len(msgs) == 2
    assert all(m.role != Role.TOOL for m in msgs)


async def test_undo_updates_tokens(app):
    add_turn(app, "hello world this is a question", "the answer is here")
    app.context_manager.update_total(app.session.conversation)
    before = app.context_manager.total_tokens
    assert before > 0

    await run_cmd(app, "/undo")
    assert app.context_manager.total_tokens < before


# --- /fork ---


async def test_fork_creates_new_session(app):
    add_turn(app, "q1", "a1")
    old_id = app.session.metadata.session_id

    result = await run_cmd(app, "/fork")
    new_id = app.session.metadata.session_id
    assert new_id != old_id
    assert old_id[:8] in result
    assert new_id in result
    assert len(app.session.conversation.messages) == 2  # copy intact


async def test_fork_preserves_original(app):
    add_turn(app, "q1", "a1")
    old_id = app.session.metadata.session_id

    await run_cmd(app, "/fork")
    # Mutate the fork 修改分支
    app.session.conversation.messages.clear()

    # Original on disk is untouched 磁盘上的原线不受影响
    original = await app.session_store.load(old_id)
    assert original is not None
    assert len(original.conversation.messages) == 2


async def test_fork_with_rollback(app):
    add_turn(app, "q1", "a1")
    add_turn(app, "q2", "a2")
    old_id = app.session.metadata.session_id

    result = await run_cmd(app, "/fork 1")
    assert "rolled back 1 turn" in result
    assert len(app.session.conversation.messages) == 2  # q1+a1 only
    assert app.session.metadata.total_turns == 1

    original = await app.session_store.load(old_id)
    assert len(original.conversation.messages) == 4  # original keeps both turns


async def test_fork_rollback_too_many(app):
    add_turn(app, "q1", "a1")
    old_id = app.session.metadata.session_id

    result = await run_cmd(app, "/fork 5")
    assert "Cannot fork" in result
    assert app.session.metadata.session_id == old_id  # no switch happened


async def test_fork_inherits_token_spend(app):
    add_turn(app, "q1", "a1")
    app.session.metadata.total_tokens_used = 5000

    await run_cmd(app, "/fork")
    # Branch carries the cumulative bill 分支继承累计账单
    assert app.session.metadata.total_tokens_used == 5000


async def test_fork_marks_original_cleanly_closed(app):
    add_turn(app, "q1", "a1")
    old_id = app.session.metadata.session_id

    await run_cmd(app, "/fork")
    # Original on disk must not look crashed 磁盘上的原线不能像崩溃会话
    original = await app.session_store.load(old_id)
    assert original.metadata.closed_cleanly is True


async def test_session_load_marks_old_cleanly_closed(app):
    add_turn(app, "q1", "a1")
    first_id = app.session.metadata.session_id
    await run_cmd(app, "/fork")
    second_id = app.session.metadata.session_id
    add_turn(app, "q2", "a2")

    # Switching away must save the branch as cleanly closed
    # 切走时分支必须存为正常关闭
    await run_cmd(app, f"/session load {first_id[:8]}")
    branch = await app.session_store.load(second_id)
    assert branch.metadata.closed_cleanly is True
    assert app.session.metadata.session_id == first_id
