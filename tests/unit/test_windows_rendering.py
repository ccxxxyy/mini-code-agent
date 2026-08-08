"""Windows terminal adaptation tests (P34). Windows 终端适配测试。

Simulates legacy Windows console conditions (16 colors, GBK codepage)
without needing a real CMD window.
在不需要真实 CMD 窗口的情况下模拟 legacy 控制台条件（16 色、GBK 代码页）。
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

pytestmark = pytest.mark.asyncio


def legacy_console(**kwargs) -> Console:
    """A console configured like legacy Windows CMD. 模拟 legacy CMD 的 Console。"""
    return Console(
        color_system="windows",
        legacy_windows=True,
        force_terminal=True,
        width=80,
        record=True,
        **kwargs,
    )


# --- diff rendering on legacy console legacy 控制台的 diff 渲染 ---


async def test_diff_renders_on_legacy_console():
    from mini_agent.ui.terminal import Terminal

    t = Terminal()
    t.console = legacy_console()
    diff = "--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-old line\n+new line\n"
    t._render_diff(diff)  # must not raise 不抛异常

    out = t.console.export_text()
    assert "old line" in out
    assert "new line" in out


# --- cost dashboard on legacy console ---


async def test_cost_summary_renders_on_legacy():
    from mini_agent.core.cost_tracker import CostTracker
    from mini_agent.models.config import CostConfig
    from mini_agent.models.events import LLMResponseEvent

    tracker = CostTracker(CostConfig(pricing={"m": {"input": 1.0, "output": 1.0}}, budget=5.0))
    await tracker._on_response(
        LLMResponseEvent(tokens_used=1000, prompt_tokens=800, completion_tokens=200, model="m")
    )
    console = legacy_console()
    for line in tracker.summary_lines():
        console.print(line)  # must not raise

    assert "m" in console.export_text()


# --- GBK encoding stream GBK 编码流 ---


def test_special_chars_survive_gbk_replace():
    """All special glyphs must not crash a GBK-encoded stream with errors=replace.
    含特殊字符的输出在 GBK+replace 流下不崩溃。"""
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="gbk", errors="replace")
    console = Console(file=stream, width=80, force_terminal=False)

    console.print("╭─ tool ─╮ ╰─ ✓ ✗ ⚠ ■ ⏳ 🔄 ✅ ❌ ─")
    stream.flush()
    assert buf.getvalue()  # something was written without raising


# --- CLI stdio hardening CLI 入口加固 ---


def test_harden_windows_stdio_noop_on_unix(monkeypatch):
    from mini_agent import cli

    monkeypatch.setattr("sys.platform", "linux")
    cli._harden_windows_stdio()  # must be a silent no-op


def test_harden_windows_stdio_win(monkeypatch):
    from mini_agent import cli

    monkeypatch.setattr("sys.platform", "win32")
    cli._harden_windows_stdio()  # must not raise even if reconfigure unavailable


# --- EscWatcher stop joins thread ---


def test_esc_watcher_stop_joins(monkeypatch):
    from mini_agent.ui import esc_watcher
    from mini_agent.ui.esc_watcher import EscWatcher

    monkeypatch.setattr(esc_watcher, "_is_tty", lambda: True)
    monkeypatch.setattr(esc_watcher, "_kbhit", lambda: False)

    w = EscWatcher()
    w.start()
    assert w._thread is not None
    thread = w._thread
    w.stop()
    assert w._thread is None
    assert not thread.is_alive()  # join worked 线程确实退出了


# --- ask_yes_no fallback ---


async def test_ask_yes_no_falls_back_to_input(monkeypatch):
    from mini_agent.ui.terminal import Terminal

    def boom(*a, **k):
        raise RuntimeError("NoConsoleScreenBufferError simulated")

    monkeypatch.setattr("prompt_toolkit.PromptSession.__init__", boom)
    monkeypatch.setattr("builtins.input", lambda _: "y")

    t = Terminal()
    assert await t.ask_yes_no("continue?") is True


# --- todo emoji fallback on legacy ---


async def test_todo_labels_ascii_on_legacy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    app = Application(ConfigLoader.load())
    app.terminal.console = legacy_console()

    await app.slash_commands.execute("/todo add test task")
    result = await app.slash_commands.execute("/todo")
    assert "[ ] pending" in result
    assert "⏳" not in result


# --- stream renderer tail budget 流式尾段预算 ---


def test_tail_budget_shrinks_for_long_lines():
    from mini_agent.ui.renderer import StreamRenderer

    console = Console(width=40, force_terminal=False, record=True)
    r = StreamRenderer(console)
    # 15 lines each 200 chars -> wraps to 5 physical rows each on width-40
    # 15 行每行 200 字符 -> 40 宽下各占 5 物理行
    r._buffer = "\n".join("x" * 200 for _ in range(15))
    budget = r._tail_budget()
    assert budget < 15  # shrunk 收缩了
    assert budget >= 4


def test_tail_budget_full_for_short_lines():
    from mini_agent.ui.renderer import StreamRenderer

    console = Console(width=80, force_terminal=False, record=True)
    r = StreamRenderer(console)
    r._buffer = "\n".join("short" for _ in range(15))
    assert r._tail_budget() == 15
