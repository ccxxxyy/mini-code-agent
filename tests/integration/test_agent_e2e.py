"""End-to-end smoke tests: full Application assembly. 端到端冒烟测试：完整 Application 装配。"""

import pytest

from mini_agent.app import Application
from mini_agent.config.loader import ConfigLoader

pytestmark = pytest.mark.asyncio


def test_application_assembles(monkeypatch, tmp_path):
    """The full app wires all layers without errors. 完整应用装配所有层级且无错误。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    config = ConfigLoader.load()
    app = Application(config)

    # All layers present 所有层级就位
    assert app.event_bus is not None
    assert app.terminal is not None
    assert app.tool_registry is not None
    assert app.permission_manager is not None
    assert app.hook_manager is not None
    assert app.context_manager is not None
    assert app.session_store is not None
    assert app.agent_loop is not None
    assert app.skill_registry is not None
    assert app.slash_commands is not None


def test_application_tools_registered(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    app = Application(ConfigLoader.load())
    tool_names = {t.schema.name for t in app.tool_registry.list_tools()}
    assert tool_names == {
        "read_file",
        "write_file",
        "edit_file",
        "delete_file",
        "bash",
        "glob",
        "grep",
        "spawn_agents",
        "tool_search",
        "mcp_call",
    }


def test_application_slash_commands_registered(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    app = Application(ConfigLoader.load())
    names = {c.name for c in app.slash_commands.list_commands()}
    # Visible commands 可见命令
    for expected in (
        "help",
        "clear",
        "status",
        "model",
        "compact",
        "memory",
        "session",
        "tools",
        "skill",
        "exit",
    ):
        assert expected in names


def test_application_system_prompt_has_platform(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    app = Application(ConfigLoader.load())
    sp = app.session.conversation.system_prompt
    assert "Platform:" in sp
    assert "Working directory:" in sp


async def test_slash_help_executes(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    app = Application(ConfigLoader.load())
    result = await app.slash_commands.execute("/help", app)
    assert result is not None
    assert "/status" in result


async def test_slash_status_executes(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    app = Application(ConfigLoader.load())
    result = await app.slash_commands.execute("/status", app)
    assert result is not None
    assert "Model:" in result
