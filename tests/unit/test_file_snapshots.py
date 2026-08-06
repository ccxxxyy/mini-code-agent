"""Tests for per-turn file snapshots and operation-level undo.
每轮文件快照与操作级撤销测试。"""

from __future__ import annotations

import pytest

from mini_agent.memory.file_snapshots import KEEP_TURNS, FileSnapshotStore
from mini_agent.models.message import Message, Role

pytestmark = pytest.mark.asyncio


@pytest.fixture
def store(tmp_path):
    return FileSnapshotStore(tmp_path / "snaps")


# --- FileSnapshotStore unit tests ---


async def test_snapshot_saves_content(store, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("original", encoding="utf-8")
    store.begin_turn(1)
    store.snapshot(1, f)

    f.write_text("modified", encoding="utf-8")
    report = store.restore_turns([1])

    assert f.read_text(encoding="utf-8") == "original"
    assert any("restored" in r for r in report)


async def test_snapshot_missing_file_restores_by_deleting(store, tmp_path):
    f = tmp_path / "new.txt"
    store.begin_turn(1)
    store.snapshot(1, f)  # does not exist yet 尚不存在

    f.write_text("created this turn", encoding="utf-8")
    report = store.restore_turns([1])

    assert not f.exists()
    assert any("did not exist" in r for r in report)


async def test_snapshot_too_large_skipped(store, tmp_path, monkeypatch):
    monkeypatch.setattr("mini_agent.memory.file_snapshots.MAX_SNAPSHOT_BYTES", 10)
    f = tmp_path / "big.txt"
    f.write_text("x" * 100, encoding="utf-8")
    store.begin_turn(1)
    store.snapshot(1, f)

    f.write_text("changed", encoding="utf-8")
    report = store.restore_turns([1])

    assert f.read_text(encoding="utf-8") == "changed"  # NOT restored 未恢复
    assert any("NOT restored" in r for r in report)


async def test_first_snapshot_per_turn_wins(store, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("v1", encoding="utf-8")
    store.begin_turn(1)
    store.snapshot(1, f)
    f.write_text("v2", encoding="utf-8")
    store.snapshot(1, f)  # second touch ignored 第二次忽略
    f.write_text("v3", encoding="utf-8")

    store.restore_turns([1])
    assert f.read_text(encoding="utf-8") == "v1"


async def test_begin_turn_prunes_old(store, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    for turn in range(1, KEEP_TURNS + 3):
        store.begin_turn(turn)
        store.snapshot(turn, f)

    dirs = sorted(p.name for p in (tmp_path / "snaps").glob("turn_*"))
    assert len(dirs) <= KEEP_TURNS + 1  # old ones pruned 旧的已清理
    assert "turn_1" not in dirs
    assert "turn_2" not in dirs


async def test_restore_multiple_turns_newest_first(store, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("start", encoding="utf-8")
    store.begin_turn(1)
    store.snapshot(1, f)
    f.write_text("after turn1", encoding="utf-8")
    store.begin_turn(2)
    store.snapshot(2, f)
    f.write_text("after turn2", encoding="utf-8")

    store.restore_turns([1, 2])
    # Newest restored first, then older overwrites -> back to start
    # 先恢复最新轮再恢复更早轮 -> 回到最初状态
    assert f.read_text(encoding="utf-8") == "start"


async def test_clear_removes_everything(store, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    store.begin_turn(1)
    store.snapshot(1, f)

    store.clear()
    assert not (tmp_path / "snaps").exists()


# --- /undo integration: files restored 集成——undo 恢复文件 ---


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    return Application(ConfigLoader.load())


def fake_turn(app, user_text: str):
    """Simulate a turn: user message + snapshot turn begin.
    模拟一轮：用户消息 + 快照开轮。"""
    app.session.conversation.append(Message(role=Role.USER, content=user_text))
    app.agent_loop.current_turn_id += 1
    app.agent_loop.snapshot_store.begin_turn(app.agent_loop.current_turn_id)


def end_turn(app, assistant_text: str = "done"):
    app.session.conversation.append(Message(role=Role.ASSISTANT, content=assistant_text))
    app.session.metadata.total_turns += 1


async def test_undo_restores_written_file(app, tmp_path):
    from mini_agent.models.message import ToolCall

    fake_turn(app, "create t.txt")
    target = tmp_path / "t.txt"
    await app.agent_loop._act(
        [
            ToolCall(
                id="c1", name="write_file", arguments={"file_path": str(target), "content": "hi"}
            )
        ]
    )
    end_turn(app)
    assert target.exists()

    result = await app.slash_commands.execute("/undo")
    assert "Files restored" in result
    assert not target.exists()  # created file removed 新建的文件被删


async def test_undo_restores_edited_file(app, tmp_path):
    from mini_agent.models.message import ToolCall

    target = tmp_path / "e.txt"
    target.write_text("original", encoding="utf-8")

    fake_turn(app, "edit e.txt")
    await app.agent_loop._act(
        [
            ToolCall(
                id="c1",
                name="edit_file",
                arguments={"file_path": str(target), "old_text": "original", "new_text": "changed"},
            )
        ]
    )
    end_turn(app)
    assert target.read_text(encoding="utf-8") == "changed"

    result = await app.slash_commands.execute("/undo")
    assert "Files restored" in result
    assert target.read_text(encoding="utf-8") == "original"


async def test_undo_restores_deleted_file(app, tmp_path):
    from mini_agent.models.message import ToolCall

    target = tmp_path / "d.txt"
    target.write_text("precious data", encoding="utf-8")

    fake_turn(app, "delete d.txt")
    await app.agent_loop._act(
        [ToolCall(id="c1", name="delete_file", arguments={"file_path": str(target)})]
    )
    end_turn(app)
    assert not target.exists()

    result = await app.slash_commands.execute("/undo")
    assert "Files restored" in result
    assert target.read_text(encoding="utf-8") == "precious data"
