"""Pane spawn backends -- run sub-agents in visible terminal panes (6.4).
窗格 spawn 后端——把 SubAgent 跑进可见的终端窗格。

In-process sub-agents are invisible while running; pane backends give each
worker its own terminal pane so the user watches it think and act live.
Backends: tmux (Unix, split-window) and Windows Terminal (wt split-pane).
Only used when the current session ALREADY runs inside tmux / Windows
Terminal (env detection, mirroring mewcode) -- otherwise callers fall back
to in-process. Note: mewcode guards win32 to in-process only; the wt
backend makes panes work on Windows too.
仅当当前会话本就跑在 tmux / Windows Terminal 里（环境变量探测）才启用
窗格；否则调用方回退进程内。mewcode 在 win32 一律回退进程内，wt 后端
让 Windows 也能用窗格。

The worker protocol: parent writes a WorkerSpec JSON, the pane runs
``mini-agent --worker <spec>``, the worker writes its result JSON, the
parent polls for that file (see SubAgentManager.spawn_pane).
协议：父进程写任务描述 JSON → 窗格跑 worker → worker 写结果 JSON →
父进程轮询结果文件。
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

BACKEND_TMUX = "tmux"
BACKEND_WT = "wt"
# Fallback when wt.exe exists but we are NOT inside a WT session: wt can
# still be invoked from any terminal (cmd/PowerShell/IDE) to open a brand
# new Windows Terminal window. wt.exe 存在但不在 WT 会话内时的降级：从任意
# 终端调用 wt 都能弹出全新 WT 窗口。
BACKEND_WT_WINDOW = "wt-window"


class SpawnBackendError(Exception):
    """Raised when a pane could not be created. 窗格创建失败。"""


def detect_pane_backend() -> str:
    """Return the usable pane backend, or '' when none is available.
    Inside tmux / Windows Terminal -> split a pane (mewcode's philosophy);
    on Windows with wt installed but launched from another terminal
    (cmd/PowerShell/IDE) -> degrade to opening a new WT window.
    在 tmux / WT 会话内 -> 分屏；Windows 装了 wt 但从其他终端启动 ->
    降级为弹新 WT 窗口。"""
    if os.environ.get("TMUX") and shutil.which("tmux"):
        return BACKEND_TMUX
    if sys.platform == "win32" and shutil.which("wt"):
        return BACKEND_WT if os.environ.get("WT_SESSION") else BACKEND_WT_WINDOW
    return ""


def build_worker_argv(spec_path: str) -> list[str]:
    """Command line that runs the worker with the parent's interpreter
    (inherits the venv). 用父进程解释器运行 worker（继承虚拟环境）。"""
    return [sys.executable, "-m", "mini_agent", "--worker", spec_path]


def spawn_pane(backend: str, title: str, argv: list[str], cwd: str) -> None:
    """Open a new pane running *argv*. Raises SpawnBackendError on failure.
    打开运行 argv 的新窗格，失败抛 SpawnBackendError。"""
    if backend == BACKEND_TMUX:
        _spawn_tmux(title, argv, cwd)
    elif backend == BACKEND_WT:
        _spawn_wt(title, argv, cwd)
    elif backend == BACKEND_WT_WINDOW:
        _spawn_wt_window(title, argv, cwd)
    else:
        raise SpawnBackendError(f"Unknown pane backend: {backend!r}")


def _spawn_tmux(title: str, argv: list[str], cwd: str) -> None:
    # -d: don't steal focus, the user keeps their current pane
    # -d 不抢焦点，用户停留在当前窗格
    cmd = ["tmux", "split-window", "-d", "-c", cwd, shlex.join(argv)]
    _run(cmd)
    try:
        _run(["tmux", "select-pane", "-T", title])
    except SpawnBackendError:
        pass  # pane titles are cosmetic 标题失败不致命


def _spawn_wt(title: str, argv: list[str], cwd: str) -> None:
    # -w 0: target the current window; split-pane opens beside the user
    # -w 0 定位当前窗口；split-pane 在旁边开新窗格
    cmd = ["wt", "-w", "0", "split-pane", "--title", title, "-d", cwd, *argv]
    _run(cmd)


def _spawn_wt_window(title: str, argv: list[str], cwd: str) -> None:
    # -w mini-agents: target a NAMED window -- first spawn creates it,
    # later spawns land as TABS in the same window instead of spamming
    # one new window per worker. Works from any terminal (cmd/IDE).
    # -w mini-agents 按名字定位窗口——首次派发创建，后续派发进同一窗口
    # 的新标签页，不再每个 worker 轰炸一个独立窗口。任意终端可用。
    cmd = ["wt", "-w", "mini-agents", "new-tab", "--title", title, "-d", cwd, *argv]
    _run(cmd)


def _run(cmd: list[str]) -> None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SpawnBackendError(f"{cmd[0]} failed: {e}") from e
    if result.returncode != 0:
        raise SpawnBackendError(f"{' '.join(cmd[:2])} failed: {result.stderr.strip()}")
