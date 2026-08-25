"""Remote mode SessionStore integration tests. 远程模式会话持久化测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mini_agent.memory.session_store import SessionStore
from mini_agent.models.message import Message, Role
from mini_agent.models.session import Session

pytestmark = pytest.mark.asyncio


def make_session(closed: bool = False, project_dir: Path | None = None) -> Session:
    s = Session()
    s.metadata.closed_cleanly = closed
    s.metadata.project_dir = str(project_dir) if project_dir else str(Path.cwd())
    s.conversation.append(Message(role=Role.USER, content="hello"))
    return s


class FakeApp:
    """Minimal stand-in borrowing the real Application methods under test.
    借用被测真实方法的最小替身。"""

    def __init__(self, tmp_path: Path):
        from mini_agent.app import Application

        self.session_store = SessionStore(session_dir=str(tmp_path))
        self.session = Session()
        self._last_autosave = 0.0
        self.adopted: list[Session] = []
        self._autosave = Application._autosave.__get__(self)
        self._find_crashed_session = Application._find_crashed_session.__get__(self)

    def _adopt_session(self, loaded: Session) -> None:
        self.adopted.append(loaded)
        self.session = loaded


def make_server(app: FakeApp):
    """Bare RemoteServer with only the attributes the tested methods touch.
    只带被测方法所需属性的裸 RemoteServer。"""
    from mini_agent.remote.server import RemoteServer

    server = object.__new__(RemoteServer)
    server._app = app
    server._clients = set()
    server._pending_confirms = {}
    server._pending_prompts = {}
    server._disconnect_timeout_task = None
    server._token = ""
    return server


# --- _find_crashed_session helper 崩溃会话查找助手 ---


async def test_find_crashed_session_filters(tmp_path):
    app = FakeApp(tmp_path)
    crashed_here = make_session(closed=False, project_dir=Path.cwd())
    clean_here = make_session(closed=True, project_dir=Path.cwd())
    crashed_elsewhere = make_session(closed=False, project_dir=tmp_path)
    for s in (crashed_here, clean_here, crashed_elsewhere):
        await app.session_store.save(s)

    found = await app._find_crashed_session()
    assert found is not None
    assert found["session_id"] == crashed_here.metadata.session_id


async def test_find_crashed_session_empty_store(tmp_path):
    app = FakeApp(tmp_path)
    assert await app._find_crashed_session() is None


async def test_find_crashed_session_excludes_current(tmp_path):
    app = FakeApp(tmp_path)
    crashed = make_session(closed=False, project_dir=Path.cwd())
    await app.session_store.save(crashed)
    app.session = crashed  # the crashed one IS the current session 崩溃的就是当前会话
    assert await app._find_crashed_session() is None


# --- server startup auto-restore 服务器启动自动恢复 ---


async def test_restore_last_session_adopts(tmp_path):
    app = FakeApp(tmp_path)
    app.config = SimpleNamespace(memory=SimpleNamespace(session_cleanup_days=0))
    crashed = make_session(closed=False, project_dir=Path.cwd())
    await app.session_store.save(crashed)

    server = make_server(app)
    await server._restore_last_session()

    assert len(app.adopted) == 1
    assert app.adopted[0].metadata.session_id == crashed.metadata.session_id
    # Restored session is live again 恢复后重新算进行中
    assert app.adopted[0].metadata.closed_cleanly is False


async def test_restore_last_session_no_candidate(tmp_path):
    app = FakeApp(tmp_path)
    app.config = SimpleNamespace(memory=SimpleNamespace(session_cleanup_days=0))
    clean = make_session(closed=True, project_dir=Path.cwd())
    await app.session_store.save(clean)

    server = make_server(app)
    await server._restore_last_session()
    assert app.adopted == []


# --- graceful shutdown save 优雅退出保存 ---


async def test_save_on_shutdown_marks_clean(tmp_path):
    app = FakeApp(tmp_path)
    app.session = make_session(closed=False)

    server = make_server(app)
    await server._save_on_shutdown()

    path = tmp_path / f"{app.session.metadata.session_id}.json"
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["metadata"]["closed_cleanly"] is True


# --- WS handler wiring 消息循环接线 ---


class FakeWS:
    def __init__(self, messages: list[str]):
        self._messages = list(messages)
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


def make_handler_server(app: FakeApp):
    """Server with handler collaborators stubbed for message-loop tests.
    为消息循环测试打桩协作方法的 server。"""
    server = make_server(app)
    server.ws_events: list[tuple] = []
    server.replayed: list = []

    async def _ws_send(event_type, **data):
        server.ws_events.append((event_type, data))

    async def _noop(ws):
        pass

    async def _replay(ws):
        server.replayed.append(ws)

    server._ws_send = _ws_send
    server._wire_callbacks = lambda: None
    server._replay_history = _replay
    server._send_commands = _noop
    server._replay_pending_confirms = _noop

    app.agent_loop = SimpleNamespace(
        model_name="m", last_turn_tokens=5, _state=SimpleNamespace(iteration=1)
    )
    app.config = SimpleNamespace(
        llm=SimpleNamespace(provider="openai"),
        llm_profiles={},
        memory=SimpleNamespace(session_cleanup_days=0),
    )
    return server


async def test_turn_end_autosaves(tmp_path):
    app = FakeApp(tmp_path)
    saves: list[bool] = []

    async def record_autosave(force=False):
        saves.append(force)

    app._autosave = record_autosave
    app.slash_commands = SimpleNamespace(is_slash_command=lambda t: False)

    async def handle_turn(text):
        pass

    app._handle_turn = handle_turn

    server = make_handler_server(app)
    ws = FakeWS([json.dumps({"type": "user_input", "text": "hi"})])
    await server._handler(ws)

    # Mirror of the terminal path: force save after the turn 镜像终端路径
    assert saves == [True]


async def test_session_swap_broadcasts_history_reset(tmp_path):
    app = FakeApp(tmp_path)
    saves: list[bool] = []

    async def record_autosave(force=False):
        saves.append(force)

    app._autosave = record_autosave

    new_session = Session()

    async def execute(text, ctx):
        app.session = new_session  # /session load swaps the session 换会话
        return "loaded"

    app.slash_commands = SimpleNamespace(is_slash_command=lambda t: True, execute=execute)

    server = make_handler_server(app)
    ws = FakeWS([json.dumps({"type": "user_input", "text": "/session load abc"})])
    await server._handler(ws)

    events = [e[0] for e in server.ws_events]
    assert "history_reset" in events
    assert ws in server.replayed[1:]  # replayed again after the swap 换会话后重放
    assert saves == [False]  # throttled autosave after slash 斜杠后节流保存


async def test_slash_without_swap_no_reset(tmp_path):
    app = FakeApp(tmp_path)

    async def record_autosave(force=False):
        pass

    app._autosave = record_autosave

    async def execute(text, ctx):
        return "ok"  # session unchanged 会话未变

    app.slash_commands = SimpleNamespace(is_slash_command=lambda t: True, execute=execute)

    server = make_handler_server(app)
    ws = FakeWS([json.dumps({"type": "user_input", "text": "/status"})])
    await server._handler(ws)

    events = [e[0] for e in server.ws_events]
    assert "history_reset" not in events


# --- terminal-mode regression 终端模式回归 ---


async def test_maybe_restore_session_still_prompts(tmp_path):
    from mini_agent.app import Application

    app = FakeApp(tmp_path)
    app._maybe_restore_session = Application._maybe_restore_session.__get__(app)
    crashed = make_session(closed=False, project_dir=Path.cwd())
    await app.session_store.save(crashed)

    asked: list[str] = []

    class FakeTerminal:
        async def ask_yes_no(self, prompt):
            asked.append(prompt)
            return True

        def show_info(self, msg):
            pass

        def show_error(self, msg):
            pass

    app.terminal = FakeTerminal()
    await app._maybe_restore_session()

    assert len(asked) == 1  # still prompt-based in terminal mode 终端仍询问式
    assert len(app.adopted) == 1
    assert app.adopted[0].metadata.session_id == crashed.metadata.session_id


# --- /session new (safe fresh start) 安全另起新会话 ---


async def test_session_new_saves_old_and_starts_fresh(tmp_path):
    from mini_agent.extensions.builtin_commands import _make_session

    app = FakeApp(tmp_path)
    app.session = make_session(closed=False)
    app.session.conversation.system_prompt = "SYSTEM"
    old_id = app.session.metadata.session_id

    handler = _make_session(app)
    result = await handler("new", None)

    # Old session saved intact and cleanly closed 旧会话完整存盘并标记正常关闭
    old_path = tmp_path / f"{old_id}.json"
    assert old_path.is_file()
    data = json.loads(old_path.read_text(encoding="utf-8"))
    assert data["metadata"]["closed_cleanly"] is True
    assert len(data["conversation"]["messages"]) == 1

    # Fresh session adopted: new id, empty, system prompt kept
    # 新会话已采用：新 ID、空历史、保留 system prompt
    assert len(app.adopted) == 1
    fresh = app.adopted[0]
    assert fresh.metadata.session_id != old_id
    assert fresh.conversation.messages == []
    assert fresh.conversation.system_prompt == "SYSTEM"
    assert fresh.metadata.project_dir == str(Path.cwd())
    assert old_id[:8] in result  # return hint 提示可 load 回来


async def test_session_new_empty_session_skips_save(tmp_path):
    from mini_agent.extensions.builtin_commands import _make_session

    app = FakeApp(tmp_path)  # empty conversation 空对话
    handler = _make_session(app)
    await handler("new", None)

    assert list(tmp_path.glob("*.json")) == []  # nothing saved 不落盘
    assert len(app.adopted) == 1  # but still starts fresh 但仍另起


# --- stale context state across adoption 采用会话时的陈旧状态复位 ---


async def test_adopt_resets_stale_context_state():
    from mini_agent.memory.context import ContextManager
    from mini_agent.models.config import MemoryConfig

    cm = ContextManager(MemoryConfig(context_window=1000))
    cm.record_file_read("a.py", "content")
    cm._adopted_skills = (["skill-x"], ["skill-x"])
    assert cm.read_files == ["a.py"]

    # Adopting a boundary-less session must NOT inherit the previous
    # session's caches 采用无边界会话不得继承上一会话的缓存
    cm.reset_state()
    assert cm.read_files == []
    assert cm.adopted_skills is None
    assert cm._last_user_request == ""
