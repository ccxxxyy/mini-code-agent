"""Tests for the plugin ecosystem loader."""

import logging
import types

from mini_agent.events.bus import EventBus
from mini_agent.extensions import plugin_loader
from mini_agent.extensions.plugin_loader import PluginContext, load_plugins
from mini_agent.extensions.skills import SkillRegistry
from mini_agent.extensions.slash_commands import SlashCommandRegistry
from mini_agent.models.config import AgentConfig
from mini_agent.tools.base import ToolRegistry


def _ctx() -> PluginContext:
    return PluginContext(
        tool_registry=ToolRegistry(),
        slash_commands=SlashCommandRegistry(),
        skill_registry=SkillRegistry(),
        event_bus=EventBus(),
        config=AgentConfig(),
    )


def _write(tmp_path, name, code):
    f = tmp_path / name
    f.write_text(code, encoding="utf-8")
    return f


_TOOL_PLUGIN = """
from typing import Any
from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolSchema

class PingTool(Tool):
    @property
    def schema(self):
        return ToolSchema(name="ping", description="ping", parameters=[])
    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return ToolResult(call_id="", name="ping", output="pong")

def register_tools(registry):
    registry.register(PingTool())
"""

_CMD_SKILL_PLUGIN = """
from mini_agent.extensions.skills import Skill
from mini_agent.extensions.slash_commands import SlashCommand

def register_commands(registry):
    async def hello(args, ctx):
        return "hi"
    registry.register(SlashCommand(name="hello", description="say hi", handler=hello))

def register_skills(registry):
    registry.register(Skill(name="demo-skill", description="d", prompt="p"))
"""


def test_register_tools_hook(tmp_path):
    _write(tmp_path, "pinger.py", _TOOL_PLUGIN)
    ctx = _ctx()
    loaded = load_plugins([tmp_path], ctx)
    assert len(loaded) == 1
    assert loaded[0].name == "pinger"
    assert loaded[0].source == str(tmp_path / "pinger.py")
    assert loaded[0].tools == ["ping"]
    assert loaded[0].commands == []
    assert ctx.tool_registry.get("ping") is not None


def test_register_commands_and_skills_hooks(tmp_path):
    _write(tmp_path, "combo.py", _CMD_SKILL_PLUGIN)
    ctx = _ctx()
    loaded = load_plugins([tmp_path], ctx)
    assert len(loaded) == 1
    assert loaded[0].commands == ["hello"]
    assert loaded[0].skills == ["demo-skill"]
    assert ctx.slash_commands.get("hello") is not None
    assert ctx.skill_registry.get("demo-skill") is not None


def test_register_ctx_takes_precedence(tmp_path):
    _write(
        tmp_path,
        "full.py",
        "calls = []\n"
        "def register(ctx):\n"
        "    calls.append('register')\n"
        "def register_tools(registry):\n"
        "    calls.append('register_tools')\n",
    )
    ctx = _ctx()
    loaded = load_plugins([tmp_path], ctx)
    assert len(loaded) == 1

    import sys

    assert sys.modules["mini_agent_plugin_full"].calls == ["register"]


def test_import_failure_isolated(tmp_path, caplog):
    _write(tmp_path, "broken.py", "raise RuntimeError('boom at import')\n")
    _write(tmp_path, "combo.py", _CMD_SKILL_PLUGIN)
    ctx = _ctx()
    with caplog.at_level(logging.WARNING):
        loaded = load_plugins([tmp_path], ctx)
    assert [p.name for p in loaded] == ["combo"]
    assert any("import failed" in r.message for r in caplog.records)


def test_hook_exception_isolated(tmp_path, caplog):
    _write(
        tmp_path,
        "faulty.py",
        "def register_tools(registry):\n    raise ValueError('hook boom')\n",
    )
    _write(tmp_path, "zcombo.py", _CMD_SKILL_PLUGIN)
    ctx = _ctx()
    with caplog.at_level(logging.WARNING):
        loaded = load_plugins([tmp_path], ctx)
    assert [p.name for p in loaded] == ["zcombo"]
    assert any("register_tools() failed" in r.message for r in caplog.records)


def test_no_hooks_warning(tmp_path, caplog):
    _write(tmp_path, "empty.py", "x = 1\n")
    ctx = _ctx()
    with caplog.at_level(logging.WARNING):
        loaded = load_plugins([tmp_path], ctx)
    assert loaded == []
    assert any("no register hooks" in r.message for r in caplog.records)


def test_underscore_and_missing_dirs_skipped(tmp_path):
    _write(tmp_path, "_private.py", _CMD_SKILL_PLUGIN)
    ctx = _ctx()
    loaded = load_plugins([tmp_path, tmp_path / "nonexistent"], ctx)
    assert loaded == []


def test_disabled_file_plugin_skipped(tmp_path):
    _write(tmp_path, "combo.py", _CMD_SKILL_PLUGIN)
    ctx = _ctx()
    loaded = load_plugins([tmp_path], ctx, disabled=["combo"])
    assert loaded == []
    assert ctx.slash_commands.get("hello") is None


class _FakeEntryPoint:
    def __init__(self, name, module=None, error=None):
        self.name = name
        self._module = module
        self._error = error

    def load(self):
        if self._error:
            raise self._error
        return self._module


def test_entry_point_discovery(monkeypatch):
    def fake_register_commands(registry):
        async def ep_cmd(args, ctx):
            return "ep"

        from mini_agent.extensions.slash_commands import SlashCommand

        registry.register(SlashCommand(name="ep-cmd", description="", handler=ep_cmd))

    module = types.SimpleNamespace(register_commands=fake_register_commands)
    monkeypatch.setattr(
        plugin_loader, "entry_points", lambda group: [_FakeEntryPoint("my_ep", module)]
    )
    ctx = _ctx()
    loaded = load_plugins([], ctx)
    assert len(loaded) == 1
    assert loaded[0].name == "my_ep"
    assert loaded[0].source == "entry_point"
    assert loaded[0].commands == ["ep-cmd"]


def test_entry_point_load_failure_isolated(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(
        plugin_loader,
        "entry_points",
        lambda group: [_FakeEntryPoint("bad_ep", error=ImportError("nope"))],
    )
    _write(tmp_path, "combo.py", _CMD_SKILL_PLUGIN)
    ctx = _ctx()
    with caplog.at_level(logging.WARNING):
        loaded = load_plugins([tmp_path], ctx)
    assert [p.name for p in loaded] == ["combo"]
    assert any("entry point load failed" in r.message for r in caplog.records)


def test_entry_point_disabled(monkeypatch):
    module = types.SimpleNamespace(register_tools=lambda registry: None)
    monkeypatch.setattr(
        plugin_loader, "entry_points", lambda group: [_FakeEntryPoint("my_ep", module)]
    )
    ctx = _ctx()
    loaded = load_plugins([], ctx, disabled=["my_ep"])
    assert loaded == []


def test_duplicate_name_warns(tmp_path, monkeypatch, caplog):
    def ep_hook(registry):
        pass

    module = types.SimpleNamespace(register_tools=ep_hook)
    monkeypatch.setattr(
        plugin_loader, "entry_points", lambda group: [_FakeEntryPoint("combo", module)]
    )
    _write(tmp_path, "combo.py", _CMD_SKILL_PLUGIN)
    ctx = _ctx()
    with caplog.at_level(logging.WARNING):
        loaded = load_plugins([tmp_path], ctx)
    assert len(loaded) == 1
    assert loaded[0].source == "entry_point"
    assert any("already loaded from entry point" in r.message for r in caplog.records)
    # File plugin's hooks never ran 文件插件的钩子未执行
    assert ctx.slash_commands.get("hello") is None


async def test_plugins_command_empty():
    from mini_agent.extensions.builtin_commands import _make_plugins

    app = types.SimpleNamespace(loaded_plugins=[])
    handler = _make_plugins(app)
    result = await handler("", None)
    assert "No plugins loaded" in result


async def test_plugins_command_populated():
    from mini_agent.extensions.builtin_commands import _make_plugins
    from mini_agent.extensions.plugin_loader import LoadedPlugin
    from mini_agent.extensions.slash_commands import MARKDOWN_RESULT

    app = types.SimpleNamespace(
        loaded_plugins=[
            LoadedPlugin(
                name="demo",
                source="entry_point",
                tools=["word_count"],
                commands=["greet"],
                skills=[],
            )
        ]
    )
    handler = _make_plugins(app)
    result = await handler("", None)
    assert result.startswith(MARKDOWN_RESULT)
    assert "demo" in result
    assert "word_count" in result
