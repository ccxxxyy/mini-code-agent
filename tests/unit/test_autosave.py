"""Tests for session auto-save and crash recovery. 会话自动保存与崩溃恢复测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mini_agent.memory.session_store import SessionStore
from mini_agent.models.message import Message, Role
from mini_agent.models.session import Session

pytestmark = pytest.mark.asyncio


def make_session(closed: bool = False, project_dir: Path | None = None) -> Session:
    s = Session()
    s.metadata.closed_cleanly = closed
    s.metadata.project_dir = project_dir
    s.conversation.append(Message(role=Role.USER, content="hello"))
    return s


# --- closed_cleanly persistence ---


async def test_closed_cleanly_roundtrip(tmp_path):
    store = SessionStore(session_dir=str(tmp_path))
    s = make_session(closed=False)
    await store.save(s)
    loaded = await store.load(s.metadata.session_id)
    assert loaded is not None
    assert loaded.metadata.closed_cleanly is False

    s.metadata.closed_cleanly = True
    await store.save(s)
    loaded2 = await store.load(s.metadata.session_id)
    assert loaded2.metadata.closed_cleanly is True


async def test_old_files_default_closed(tmp_path):
    """Legacy session files without the flag must not trigger crash prompts.
    无 closed_cleanly 字段的旧文件不得误报崩溃。"""
    store = SessionStore(session_dir=str(tmp_path))
    s = make_session()
    await store.save(s)
    # Strip the flag to simulate a legacy file 删除字段模拟旧文件
    path = tmp_path / f"{s.metadata.session_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["metadata"]["closed_cleanly"]
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = await store.load(s.metadata.session_id)
    assert loaded.metadata.closed_cleanly is True

    sessions = await store.list_sessions()
    assert sessions[0]["closed_cleanly"] is True


async def test_list_sessions_includes_flag(tmp_path):
    store = SessionStore(session_dir=str(tmp_path))
    await store.save(make_session(closed=False))
    sessions = await store.list_sessions()
    assert sessions[0]["closed_cleanly"] is False


# --- Application autosave/restore logic (tested via a minimal harness) ---


class FakeApp:
    """Minimal stand-in exposing the real Application methods under test.
    暴露被测真实方法的最小替身。"""

    def __init__(self, tmp_path: Path):
        from mini_agent.app import Application

        self.session_store = SessionStore(session_dir=str(tmp_path))
        self.session = make_session()
        self._last_autosave = 0.0
        # Borrow the real methods 借用真实方法
        self._autosave = Application._autosave.__get__(self)


async def test_autosave_throttle(tmp_path):
    app = FakeApp(tmp_path)
    await app._autosave()
    path = tmp_path / f"{app.session.metadata.session_id}.json"
    assert path.is_file()

    app.session.conversation.append(Message(role=Role.USER, content="more"))
    await app._autosave()  # within 30s -> throttled 30 秒内被节流
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["conversation"]["messages"]) == 1  # not rewritten 未重写

    await app._autosave(force=True)  # force bypasses throttle 强制绕过节流
    data2 = json.loads(path.read_text(encoding="utf-8"))
    assert len(data2["conversation"]["messages"]) == 2


async def test_autosave_skips_empty_session(tmp_path):
    app = FakeApp(tmp_path)
    app.session = Session()  # no messages 无消息
    await app._autosave(force=True)
    assert list(tmp_path.glob("*.json")) == []


async def test_autosave_swallows_oserror(tmp_path):
    app = FakeApp(tmp_path)

    async def broken_save(session):
        raise OSError("disk full")

    app.session_store.save = broken_save
    await app._autosave(force=True)  # must not raise 不得抛异常


# --- Crash detection filter 崩溃检测过滤 ---


async def test_crash_detection_filter(tmp_path):
    store = SessionStore(session_dir=str(tmp_path))
    cwd = Path.cwd()

    crashed_here = make_session(closed=False, project_dir=cwd)
    clean_here = make_session(closed=True, project_dir=cwd)
    crashed_elsewhere = make_session(closed=False, project_dir=tmp_path)
    for s in (crashed_here, clean_here, crashed_elsewhere):
        await store.save(s)

    sessions = await store.list_sessions()
    current_id = "not-any-of-them"
    matches = [
        s
        for s in sessions
        if not s.get("closed_cleanly", True)
        and str(s.get("project_dir", "")) == str(cwd)
        and s["session_id"] != current_id
    ]
    assert len(matches) == 1
    assert matches[0]["session_id"] == crashed_here.metadata.session_id
