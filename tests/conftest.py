"""Shared test fixtures."""

from pathlib import Path

import pytest

from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path_factory, monkeypatch):
    """Redirect every home-dir lookup to a temp dir so tests never touch
    the real ~/.mini-agent (sessions, memory, theme, instructions).
    把所有 home 目录查找重定向到临时目录——测试绝不污染真实 ~/.mini-agent。

    Two entry points must both be patched: Path.home() AND the env vars
    used by os.path.expanduser (USERPROFILE on Windows, HOME on Unix).
    必须同时打两个入口：Path.home() 和 expanduser 读的环境变量。
    """
    fake_home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    return fake_home


@pytest.fixture
def tool_context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
    )
