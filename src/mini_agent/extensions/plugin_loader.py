"""Plugin ecosystem -- third-party packages/files registering tools, commands, skills.
插件生态——第三方 pip 包 / 本地文件注册工具、命令、技能。

Discovery runs on two channels 发现走双通道:

1. **pip packages** via the ``mini_agent.plugins`` entry-point group. A plugin
   package declares in its ``pyproject.toml``:
   pip 包通过 ``mini_agent.plugins`` entry-point 群组声明::

       [project.entry-points."mini_agent.plugins"]
       my_plugin = "my_pkg.plugin"

2. **Local files**: plain ``.py`` files dropped into a ``plugin_dirs`` directory
   (default ``./.mini-agent/plugins`` and ``~/.mini-agent/plugins``) -- no
   packaging needed, same trust boundary as ``listener_dirs``/``config.toml``.
   本地文件：放进 ``plugin_dirs`` 目录的 ``.py`` 文件——免打包，
   信任边界与 ``listener_dirs``/``config.toml`` 相同。

Plugin contract (module-level optional hooks) 插件契约（模块级可选钩子）:

- ``def register(ctx: PluginContext)``: full control -- takes precedence; when
  defined, ONLY it runs. 全控钩子——定义时优先且只运行它。
- ``def register_tools(registry: ToolRegistry)``
- ``def register_commands(registry: SlashCommandRegistry)``
- ``def register_skills(registry: SkillRegistry)``

Plugin tools deliberately bypass ``config.tools.enabled_tools`` -- that
whitelist enumerates builtins; installing a plugin IS the opt-in act, and
``disabled_plugins`` is the kill switch. Import errors and hook exceptions are
logged and isolated -- they never break the agent (event_listeners precedent).
插件工具有意不受 ``enabled_tools`` 白名单约束——白名单只枚举内置工具；
安装插件即 opt-in，``disabled_plugins`` 是关闭开关。导入错误与钩子异常
都被隔离并记日志——绝不影响 Agent 主流程（沿袭 event_listeners 先例）。
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mini_agent.events.bus import EventBus
    from mini_agent.extensions.skills import SkillRegistry
    from mini_agent.extensions.slash_commands import SlashCommandRegistry
    from mini_agent.models.config import AgentConfig
    from mini_agent.tools.base import ToolRegistry

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "mini_agent.plugins"

_HOOK_NAMES = ("register_tools", "register_commands", "register_skills")


@dataclass
class PluginContext:
    """Everything a full-control ``register(ctx)`` hook may touch.
    全控钩子 ``register(ctx)`` 可触达的全部对象。"""

    tool_registry: ToolRegistry
    slash_commands: SlashCommandRegistry
    skill_registry: SkillRegistry
    event_bus: EventBus
    config: AgentConfig


@dataclass
class LoadedPlugin:
    """Record of one successfully loaded plugin (feeds ``/plugins``).
    单个成功加载插件的记录（供 ``/plugins`` 展示）。"""

    name: str
    source: str  # "entry_point" or the plugin file path 来源："entry_point" 或插件文件路径
    tools: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


def load_plugins(
    plugin_dirs: list[str | Path],
    ctx: PluginContext,
    disabled: list[str] | None = None,
) -> list[LoadedPlugin]:
    """Discover and load plugins from entry points, then from plugin dirs.
    先从 entry points、再从插件目录发现并加载插件。

    ``disabled`` matches entry-point names or file stems. Returns records of
    successfully loaded plugins. ``disabled`` 按 entry-point 名或文件名去后缀
    匹配。返回成功加载的插件记录。
    """
    disabled_set = set(disabled or [])
    loaded: list[LoadedPlugin] = []
    seen: set[str] = set()

    for name, module in _discover_entry_points(disabled_set):
        record = _run_hooks(module, name, "entry_point", ctx)
        if record:
            loaded.append(record)
            seen.add(name)

    for py_file in _discover_dir_files(plugin_dirs):
        name = py_file.stem
        if name in disabled_set:
            continue
        if name in seen:
            logger.warning("plugin %s: name already loaded from entry point, skipping", py_file)
            continue
        module = _import_file(py_file)
        if module is None:
            continue
        record = _run_hooks(module, name, str(py_file), ctx)
        if record:
            loaded.append(record)
            seen.add(name)

    return loaded


def _discover_entry_points(disabled: set[str]) -> list[tuple[str, Any]]:
    """Resolve ``mini_agent.plugins`` entry points into (name, module) pairs.
    将 ``mini_agent.plugins`` entry points 解析为 (名称, 模块) 对。"""
    resolved: list[tuple[str, Any]] = []
    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:
        logger.warning("plugin entry point discovery failed", exc_info=True)
        return resolved
    for ep in eps:
        if ep.name in disabled:
            continue
        try:
            resolved.append((ep.name, ep.load()))
        except Exception:
            logger.warning("plugin %s: entry point load failed", ep.name, exc_info=True)
    return resolved


def _discover_dir_files(plugin_dirs: list[str | Path]) -> list[Path]:
    """List candidate plugin files across dirs (sorted, ``_``-prefixed skipped).
    列出各目录下的候选插件文件（排序，跳过 ``_`` 前缀）。"""
    files: list[Path] = []
    for raw_dir in plugin_dirs:
        dir_path = Path(raw_dir).expanduser()
        if not dir_path.is_dir():
            continue
        for py_file in sorted(dir_path.glob("*.py")):
            if not py_file.name.startswith("_"):
                files.append(py_file)
    return files


def _import_file(path: Path) -> Any | None:
    """Import a single plugin file. Failure returns None.
    导入单个插件文件。失败返回 None。"""
    module_name = f"mini_agent_plugin_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("plugin %s: cannot create import spec", path)
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(module_name, None)
        logger.warning("plugin %s: import failed", path, exc_info=True)
        return None


def _run_hooks(module: Any, name: str, source: str, ctx: PluginContext) -> LoadedPlugin | None:
    """Run the plugin's hooks; diff registry snapshots into a LoadedPlugin.
    运行插件钩子；差分注册表快照生成 LoadedPlugin。失败返回 None。"""
    before_tools, before_cmds, before_skills = _snapshot(ctx)

    register = getattr(module, "register", None)
    hooks: list[tuple[str, Any, Any]]
    if callable(register):
        hooks = [("register", register, ctx)]
    else:
        hooks = [
            ("register_tools", getattr(module, "register_tools", None), ctx.tool_registry),
            ("register_commands", getattr(module, "register_commands", None), ctx.slash_commands),
            ("register_skills", getattr(module, "register_skills", None), ctx.skill_registry),
        ]
        hooks = [(h, fn, arg) for h, fn, arg in hooks if callable(fn)]
        if not hooks:
            logger.warning("plugin %s: no register hooks found", name)
            return None

    for hook_name, fn, arg in hooks:
        try:
            fn(arg)
        except Exception:
            logger.warning("plugin %s: %s() failed", name, hook_name, exc_info=True)
            return None

    after_tools, after_cmds, after_skills = _snapshot(ctx)
    return LoadedPlugin(
        name=name,
        source=source,
        tools=sorted(after_tools - before_tools),
        commands=sorted(after_cmds - before_cmds),
        skills=sorted(after_skills - before_skills),
    )


def _snapshot(ctx: PluginContext) -> tuple[set[str], set[str], set[str]]:
    """Key-sets of the three registries (tool/command/skill names).
    三个注册表的名称集合快照（工具/命令/技能名）。"""
    return (
        {t.schema.name for t in ctx.tool_registry.list_tools()},
        ctx.slash_commands.names(),
        {s.name for s in ctx.skill_registry.list_skills()},
    )
