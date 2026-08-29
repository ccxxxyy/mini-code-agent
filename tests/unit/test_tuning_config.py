"""Tests for configurable tuning knobs (formerly hard-coded magic numbers).
可调参数（原硬编码魔法数字）配置化测试。"""

from __future__ import annotations

from pathlib import Path

from mini_agent.config.loader import ConfigLoader
from mini_agent.core.mailbox import Mailbox
from mini_agent.core.subagent import SubAgentManager, SubAgentResult
from mini_agent.events.bus import EventBus
from mini_agent.memory.compressor import _compute_keep_split
from mini_agent.models.config import AgentConfig
from mini_agent.models.message import Message, Role
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin import BashTool, GrepTool
from mini_agent.ui.board import SubAgentBoard
from tests.mocks import MockLLM

# --- defaults match the former constants 默认值与原常量一致 ---


def test_defaults_match_former_constants():
    cfg = AgentConfig()
    assert cfg.tools.bash_max_output_chars == 30_000
    assert cfg.tools.grep_max_matches == 200
    assert cfg.memory.autosave_interval == 30.0
    assert cfg.memory.keep_recent_tokens == 10_000
    assert cfg.memory.keep_max_tokens == 40_000
    assert cfg.notify_max_chars == 4000
    assert cfg.board_refresh_interval == 0.25


# --- TOML loading TOML 加载 ---


def test_tuning_fields_load_from_toml(monkeypatch, tmp_path):
    toml_dir = tmp_path / ".mini-agent"
    toml_dir.mkdir()
    (toml_dir / "config.toml").write_text(
        "notify_max_chars = 123\n"
        "board_refresh_interval = 0.5\n"
        "[tools]\n"
        "bash_max_output_chars = 1000\n"
        "grep_max_matches = 7\n"
        "[memory]\n"
        "autosave_interval = 5.0\n"
        "keep_recent_tokens = 2000\n"
        "keep_max_tokens = 8000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    config = ConfigLoader.load()
    assert config.tools.bash_max_output_chars == 1000
    assert config.tools.grep_max_matches == 7
    assert config.memory.autosave_interval == 5.0
    assert config.memory.keep_recent_tokens == 2000
    assert config.memory.keep_max_tokens == 8000
    assert config.notify_max_chars == 123
    assert config.board_refresh_interval == 0.5


# --- wiring 接线 ---


def _ctx(tmp_path: Path, config: AgentConfig) -> ToolContext:
    return ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=config,
    )


async def test_bash_output_truncation_respects_config(tmp_path):
    config = AgentConfig()
    config.tools.bash_max_output_chars = 50
    result = await BashTool().execute(
        _ctx(tmp_path, config), command="python -c \"print('x' * 500)\""
    )
    assert "truncated" in result.output
    # 50 chars kept + truncation marker line 保留 50 字符 + 截断标记行
    assert result.output.startswith("x" * 50 + "\n... (truncated")


async def test_grep_max_matches_respects_config(tmp_path):
    (tmp_path / "data.txt").write_text("hit\n" * 10, encoding="utf-8")
    config = AgentConfig()
    config.tools.grep_max_matches = 3
    result = await GrepTool().execute(_ctx(tmp_path, config), pattern="hit")
    assert result.metadata["matches"] == 3
    assert "truncated to 3 matches" in result.output


async def test_notify_truncation_respects_config(tmp_path):
    config = AgentConfig()
    config.notify_max_chars = 10
    mailbox = Mailbox(tmp_path / "mailboxes")
    mailbox.register("main")
    mgr = SubAgentManager(
        llm=MockLLM(),
        tool_registry=ToolRegistry(),
        config=config,
        event_bus=EventBus(),
        working_dir=tmp_path,
        mailbox=mailbox,
    )
    mgr._deliver_result(SubAgentResult(agent_id="a1", task="t", success=True, output="y" * 100))
    messages = mailbox.drain("main")
    assert len(messages) == 1
    assert "y" * 10 + "\n... (truncated)" in messages[0].content
    assert "y" * 11 not in messages[0].content


def test_keep_split_respects_custom_window():
    # 10 msgs x 1000 tokens; default floor (10K) would keep everything
    # reachable, a 2K floor stops after MIN_KEEP_MESSAGES (5)
    # 10 条 x 1000 token；默认下限 10K 会尽量多留，2K 下限满足最少 5 条后即停
    msgs = [Message(role=Role.USER, content=f"m{i}", token_count=1000) for i in range(10)]
    default_split = _compute_keep_split(msgs, target_tokens=100_000)
    custom_split = _compute_keep_split(
        msgs, target_tokens=100_000, keep_recent_tokens=2000, keep_max_tokens=6000
    )
    assert default_split == 0  # all 10K tokens fit under the default floor
    assert custom_split == 5  # floor 2K + min 5 messages -> keep 5, split 5


def test_board_refresh_interval_param(tmp_path):
    config = AgentConfig()
    mgr = SubAgentManager(
        llm=MockLLM(),
        tool_registry=ToolRegistry(),
        config=config,
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    from rich.console import Console

    board = SubAgentBoard(Console(), mgr, refresh_interval=0.05)
    assert board._refresh_interval == 0.05
    # default falls back to the module constant 缺省回退模块常量
    assert SubAgentBoard(Console(), mgr)._refresh_interval == 0.25
