"""Tests for the interactive UX pack: collapsible tool blocks, shift+tab
mode cycling, always-save persistence, Esc detach-to-background.
交互 UX 小项包测试：工具块折叠、shift+tab 模式循环、always-save 持久化、Esc 转后台。"""

from __future__ import annotations

import asyncio
from io import StringIO
from types import SimpleNamespace

from rich.console import Console

from mini_agent.models.config import SecurityConfig, ToolConfig
from mini_agent.models.permissions import (
    PermissionDecision,
    PermissionLevel,
    PermissionMode,
    PermissionRequest,
    PermissionScope,
)
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager
from mini_agent.ui.terminal import Terminal

# --- ① Collapsible read-only tool group 工具块折叠 ---


def make_terminal(collapse: bool = True) -> Terminal:
    t = Terminal()
    t.collapse_tool_calls = collapse
    t.console = Console(file=StringIO(), record=True, force_terminal=True, width=120)
    return t


def test_two_readonly_tools_collapse():
    t = make_terminal()
    t.show_tool_call("read_file", {"path": "a.py"})
    t.show_tool_result("read_file", "x\ny")
    t.show_tool_call("grep", {"pattern": "foo"})
    t.show_tool_result("grep", "match line")
    t.flush_tool_group()
    out = t.console.export_text()
    assert "Done (2 tool uses" in out
    # Individual result lines ("N lines, N chars") must be gone
    assert "lines," not in out


def test_single_readonly_tool_prints_full():
    t = make_terminal()
    t.show_tool_call("read_file", {"path": "a.py"})
    t.show_tool_result("read_file", "hello")
    t.flush_tool_group()
    out = t.console.export_text()
    assert "read_file" in out
    assert "1 lines, 5 chars" in out
    assert "Done (" not in out


def test_readonly_error_expands_group():
    t = make_terminal()
    t.show_tool_call("read_file", {"path": "a.py"})
    t.show_tool_result("read_file", "boom: not found", is_error=True)
    out = t.console.export_text()
    assert "read_file" in out  # call line reprinted by flush
    assert "✗ boom: not found" in out
    assert t._ro_live is None


def test_non_readonly_tool_prints_immediately():
    t = make_terminal()
    t.show_tool_call("bash", {"command": "ls"})
    out = t.console.export_text()
    assert "bash" in out
    assert t._ro_live is None


def test_non_readonly_tool_flushes_open_group():
    t = make_terminal()
    t.show_tool_call("read_file", {"path": "a.py"})
    t.show_tool_result("read_file", "data")
    t.show_tool_call("write_file", {"path": "b.py"})
    out = t.console.export_text()
    assert t._ro_live is None
    assert "write_file" in out
    # single-entry group expanded, not collapsed 单条组展开而非折叠
    assert "read_file" in out


def test_flush_without_group_is_noop():
    t = make_terminal()
    t.flush_tool_group()
    assert t.console.export_text() == ""


def test_collapse_off_by_default_prints_full_lines():
    # Default is OFF: collapsing is opt-in via collapse_tool_calls = true
    # 默认关闭：折叠需显式配置 collapse_tool_calls = true
    t = Terminal()
    assert t.collapse_tool_calls is False
    t.console = Console(file=StringIO(), record=True, force_terminal=True, width=120)
    t.show_tool_call("read_file", {"path": "a.py"})
    t.show_tool_result("read_file", "x\ny")
    t.show_tool_call("grep", {"pattern": "foo"})
    t.show_tool_result("grep", "match line")
    out = t.console.export_text()
    assert t._ro_live is None
    assert "Done (" not in out
    assert out.count("lines,") == 2  # both result lines printed 两条结果行都在


# --- ② Permission mode cycling 模式循环 ---


def _fake_app(start: PermissionMode) -> SimpleNamespace:
    ns = SimpleNamespace(
        permission_manager=SimpleNamespace(mode=start),
        agent_loop=SimpleNamespace(plan_mode=False),
        session=SimpleNamespace(conversation=SimpleNamespace(system_prompt="base prompt")),
        event_bus=SimpleNamespace(),
    )
    return ns


def test_cycle_order():
    from mini_agent.app import Application

    ns = _fake_app(PermissionMode.DEFAULT)
    ns.set_permission_mode = lambda m: setattr(ns.permission_manager, "mode", m)
    seen = [Application._cycle_permission_mode(ns) for _ in range(5)]
    assert seen == ["accept-edits", "plan", "bypass", "default", "accept-edits"]


def test_set_permission_mode_syncs_plan_prompt():
    from mini_agent.app import _PLAN_MODE_PROMPT, Application

    ns = _fake_app(PermissionMode.DEFAULT)
    Application.set_permission_mode(ns, PermissionMode.PLAN)
    assert ns.agent_loop.plan_mode is True
    assert _PLAN_MODE_PROMPT in ns.session.conversation.system_prompt

    Application.set_permission_mode(ns, PermissionMode.DEFAULT)
    assert ns.agent_loop.plan_mode is False
    assert _PLAN_MODE_PROMPT not in ns.session.conversation.system_prompt
    assert ns.session.conversation.system_prompt == "base prompt"


def test_set_permission_mode_no_duplicate_prompt():
    from mini_agent.app import _PLAN_MODE_PROMPT, Application

    ns = _fake_app(PermissionMode.DEFAULT)
    Application.set_permission_mode(ns, PermissionMode.PLAN)
    Application.set_permission_mode(ns, PermissionMode.PLAN)
    assert ns.session.conversation.system_prompt.count(_PLAN_MODE_PROMPT) == 1


# --- Key bindings 按键绑定层 ---


def _find_binding(bindings, keys: tuple):
    from prompt_toolkit.keys import Keys

    name_map = {"s-tab": Keys.BackTab, "escape": Keys.Escape, "enter": Keys.ControlM}
    want = tuple(name_map[k] for k in keys)
    matches = [b for b in bindings.bindings if tuple(b.keys) == want]
    assert matches, f"no binding registered for {keys}"
    return matches[0]


def test_shift_tab_binding_calls_cycler():
    from mini_agent.ui.input_handler import build_key_bindings

    calls: list = []
    bindings = build_key_bindings(mode_cycler=lambda: calls.append("cycled"))
    binding = _find_binding(bindings, ("s-tab",))
    invalidated: list = []
    event = SimpleNamespace(app=SimpleNamespace(invalidate=lambda: invalidated.append(1)))
    binding.handler(event)
    assert calls == ["cycled"]
    assert invalidated == [1]


def test_shift_tab_binding_absent_without_cycler():
    from prompt_toolkit.keys import Keys

    from mini_agent.ui.input_handler import build_key_bindings

    bindings = build_key_bindings(mode_cycler=None)
    assert not [b for b in bindings.bindings if tuple(b.keys) == (Keys.BackTab,)]


def test_escape_binding_submits_provider_command():
    from mini_agent.ui.input_handler import build_key_bindings

    bindings = build_key_bindings(esc_command_provider=lambda: "/spawn wait")
    binding = _find_binding(bindings, ("escape",))
    submitted: list = []
    buf = SimpleNamespace(text="", validate_and_handle=lambda: submitted.append(1))
    binding.handler(SimpleNamespace(current_buffer=buf))
    assert buf.text == "/spawn wait"
    assert submitted == [1]


def test_escape_binding_noop_when_provider_returns_none():
    from mini_agent.ui.input_handler import build_key_bindings

    bindings = build_key_bindings(esc_command_provider=lambda: None)
    binding = _find_binding(bindings, ("escape",))
    submitted: list = []
    buf = SimpleNamespace(text="", validate_and_handle=lambda: submitted.append(1))
    binding.handler(SimpleNamespace(current_buffer=buf))
    assert buf.text == ""
    assert submitted == []


def test_escape_enter_binding_inserts_newline():
    from mini_agent.ui.input_handler import build_key_bindings

    bindings = build_key_bindings()
    binding = _find_binding(bindings, ("escape", "enter"))
    inserted: list = []
    buf = SimpleNamespace(insert_text=lambda t: inserted.append(t))
    binding.handler(SimpleNamespace(current_buffer=buf))
    assert inserted == ["\n"]


# --- Post-command mailbox delivery 命令后收件箱处理 ---


async def test_process_pending_deliveries_drains_mailbox():
    from mini_agent.app import Application

    handled: list = []

    async def fake_handle() -> None:
        handled.append(1)

    ns = SimpleNamespace(
        mailbox=SimpleNamespace(has_pending=lambda who: True),
        _handle_background_delivery=fake_handle,
    )
    await Application._process_pending_deliveries(ns)
    assert handled == [1]

    ns.mailbox = SimpleNamespace(has_pending=lambda who: False)
    await Application._process_pending_deliveries(ns)
    assert handled == [1]  # nothing pending, nothing handled 无投递不处理


# --- ③ always-save persistence 持久化 ---


def make_pm(tmp_path, answer) -> PermissionManager:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    guard = PathGuard(
        tool_config=ToolConfig(), security_config=SecurityConfig(), project_dir=project
    )

    async def confirm(prompt: str):
        return answer

    pm = PermissionManager(config=SecurityConfig(), path_guard=guard, confirm_callback=confirm)
    pm.working_dir = project
    return pm


async def test_always_save_writes_rule_file(tmp_path):
    pm = make_pm(tmp_path, "always-save")
    req = PermissionRequest(
        scope=PermissionScope.COMMAND, resource="rm -rf build", tool_name="bash"
    )
    decision = await pm._ask_user(req)
    assert decision is PermissionDecision.GRANTED
    assert pm.last_decision_reason == "user_confirm:always-save"
    assert any(
        r.pattern == "rm -rf build" and r.level == PermissionLevel.ALLOW for r in pm.list_rules()
    )
    toml_file = pm.working_dir / ".mini-agent" / "permissions.toml"
    assert toml_file.is_file()
    assert "rm -rf build" in toml_file.read_text(encoding="utf-8")


async def test_always_does_not_write_file(tmp_path):
    pm = make_pm(tmp_path, "always")
    req = PermissionRequest(
        scope=PermissionScope.COMMAND, resource="rm -rf build", tool_name="bash"
    )
    decision = await pm._ask_user(req)
    assert decision is PermissionDecision.GRANTED
    assert not (pm.working_dir / ".mini-agent" / "permissions.toml").exists()
    # Session grant still applies 会话授权仍生效
    again = await pm._check_rules_only(req)
    assert again is PermissionDecision.GRANTED


# --- ④ Esc detach-to-background 转后台 ---


class FakeEscWatcher:
    def __init__(self, double: bool = True) -> None:
        self.triggered = True

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _KeyClock:
    """Fake clock + timed key source for EscWatcher poll tests.
    EscWatcher 轮询测试用的假时钟 + 定时按键源。"""

    def __init__(self, watcher, arrivals: list[tuple[float, str]], stop_at: float = 5.0):
        self.t = 0.0
        self._watcher = watcher
        self._pending = sorted(arrivals)
        self._stop_at = stop_at

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def kbhit(self) -> bool:
        if self._pending and self._pending[0][0] <= self.t:
            return True
        if self.t >= self._stop_at:
            self._watcher._running = False  # end the loop 结束轮询循环
        return False

    def getch(self) -> str:
        return self._pending.pop(0)[1]

    def install(self, monkeypatch) -> None:
        from mini_agent.ui import esc_watcher as ew

        monkeypatch.setattr(ew, "_kbhit", self.kbhit)
        monkeypatch.setattr(ew, "_getch", self.getch)
        monkeypatch.setattr(ew.time, "monotonic", self.monotonic)
        monkeypatch.setattr(ew.time, "sleep", self.sleep)


def _run_poll(monkeypatch, watcher, arrivals):
    clock = _KeyClock(watcher, arrivals)
    clock.install(monkeypatch)
    watcher._running = True
    watcher._poll()
    return watcher


def test_single_esc_after_grace_triggers(monkeypatch):
    from mini_agent.ui.esc_watcher import EscWatcher

    # Lone Esc arriving after the 0.3s arming grace 观察窗后到达的孤立 Esc
    w = _run_poll(monkeypatch, EscWatcher(double=False), [(0.5, "\x1b")])
    assert w.triggered is True


def test_double_esc_still_needs_two(monkeypatch):
    from mini_agent.ui.esc_watcher import EscWatcher

    w = _run_poll(monkeypatch, EscWatcher(), [(0.5, "\x1b"), (0.8, "\x1b")])
    assert w.triggered is True


def test_stale_buffered_esc_does_not_trigger(monkeypatch):
    """Keys buffered before/at startup are drained by the arming grace
    window, never treated as a detach (real-run: stray \\x1b at board start
    caused an instant false detach on every run).
    启动时缓冲区里的按键由观察窗排空，绝不当成转后台
    （实测：面板启动瞬间的杂散 \\x1b 曾导致每次秒误转后台）。"""
    from mini_agent.ui.esc_watcher import EscWatcher

    w = _run_poll(monkeypatch, EscWatcher(double=False), [(0.0, "\x1b"), (0.1, "\x1b")])
    assert w.triggered is False


def test_interrupt_input_skips_idle_prompt():
    """interrupt_input between prompts must NOT save the buffer: it still
    holds the LAST SUBMITTED text, which would pre-fill the next prompt
    (real-run: "/spawn wait" reappeared in the input line after re-attach).
    两次 prompt 之间 interrupt_input 不得保存缓冲——里面是上一次提交的
    文本，会预填进下一次输入行（实测：re-attach 后输入行残留 /spawn wait）。"""
    t = Terminal()
    buf = SimpleNamespace(text="/spawn wait")
    calls: list = []
    app = SimpleNamespace(is_running=False, current_buffer=buf, exit=lambda **kw: calls.append(kw))
    t._prompt_session = SimpleNamespace(app=app)

    t.interrupt_input()
    assert t._saved_buffer_text == ""  # stale text NOT saved 残留未被保存
    assert calls == []  # no exit on an idle app 未运行的 app 不 exit

    app.is_running = True
    buf.text = "half-typed messa"
    t.interrupt_input()
    assert t._saved_buffer_text == "half-typed messa"  # live typing preserved 打了一半的输入保留
    assert len(calls) == 1


def test_escape_sequence_does_not_trigger(monkeypatch):
    """\\x1b immediately followed by more bytes is a terminal-generated
    escape sequence (e.g. a CSI reply), not a human Esc press.
    \\x1b 后紧跟其他字节是终端产生的转义序列（如 CSI 应答），不是人按的键。"""
    from mini_agent.ui.esc_watcher import EscWatcher

    w = _run_poll(
        monkeypatch,
        EscWatcher(double=False),
        [(0.5, "\x1b"), (0.51, "["), (0.52, "1"), (0.53, "R")],
    )
    assert w.triggered is False


async def test_board_detach_keeps_agent_running(tmp_path, monkeypatch):
    from mini_agent.ui import esc_watcher as ew
    from mini_agent.ui.board import BOARD_DETACHED, SubAgentBoard
    from tests.unit.test_board import make_manager

    monkeypatch.setattr(ew, "EscWatcher", FakeEscWatcher)
    mgr = make_manager(tmp_path, delay=0.4)
    console = Console(record=True, width=100, force_terminal=False)
    board = SubAgentBoard(console, mgr)
    aid = await mgr.spawn("some background task")

    outcome = await board.run_while(mgr.wait(aid, timeout=5), detachable=True)
    assert outcome is BOARD_DETACHED
    assert board.pending_task is not None
    assert not board.pending_task.cancelled()
    # The agent was NOT killed: awaiting the stashed task yields its result
    # agent 未被杀死：await 暂存任务能拿到真实结果
    result = await board.pending_task
    assert result.success


async def test_adopt_pending_wait_delivers_to_mailbox(tmp_path):
    from mini_agent.models.events import SubAgentCompleteEvent
    from tests.unit.test_board import make_manager

    mgr = make_manager(tmp_path, delay=0.2)
    mgr.mailbox.register("main")
    events: list[SubAgentCompleteEvent] = []

    async def on_complete(event: SubAgentCompleteEvent) -> None:
        events.append(event)

    mgr._event_bus.on(SubAgentCompleteEvent, on_complete)

    aid = await mgr.spawn("adopted task")
    wait_task = asyncio.ensure_future(mgr.wait(aid, timeout=5))
    mgr.adopt_pending_wait([aid], wait_task)

    result = await wait_task
    assert result.success
    await asyncio.sleep(0.05)  # let the deliver task run 让投递任务跑完
    assert mgr.mailbox.has_pending("main")
    assert events and events[0].background is True
    # Delivery done: the adopted group is deregistered 投递完成后组已注销
    assert mgr.find_adopted_wait(aid) is None


async def test_reattach_reclaims_foreground_result(tmp_path):
    from tests.unit.test_board import make_manager

    mgr = make_manager(tmp_path, delay=0.3)
    mgr.mailbox.register("main")
    aid = await mgr.spawn("reattach me")
    wait_task = asyncio.ensure_future(mgr.wait(aid, timeout=5))
    mgr.adopt_pending_wait([aid], wait_task)

    entry = mgr.find_adopted_wait(aid)
    assert entry is not None
    assert mgr.find_adopted_wait("") is entry  # empty id = first group 空 id 取首组
    assert mgr.has_adopted_waits is True

    result = await entry["wait_task"]
    assert result.success
    reclaimed = mgr.reclaim_adopted_wait(entry)
    if reclaimed:
        # Foreground took the result: no mailbox delivery, marking dropped
        # 前台拿到结果：无收件箱投递、后台标记撤销
        await asyncio.sleep(0.05)
        assert not mgr.mailbox.has_pending("main")
        assert aid not in mgr._background_ids
        assert mgr.find_adopted_wait(aid) is None
    else:
        # Rare race: deliver fired first -- result must be in the mailbox
        # 罕见竞态：投递先到——结果必须在收件箱里
        assert mgr.mailbox.has_pending("main")
