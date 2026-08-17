"""Event listener plugins -- external code observing all bus events.
事件监听插件——外部代码监听总线上的全部事件（统计/调试用）。

Plugin contract (a plain .py file in a listener dir) 插件契约（监听目录下的 .py 文件）:

- ``def register(bus)``: full control -- subscribe to specific event types
  via ``bus.on(EventType, handler)`` or everything via ``bus.on_any(handler)``.
  完全控制——用 ``bus.on`` 订阅特定事件类型，或用 ``bus.on_any`` 订阅全部。
- ``def on_event(event)`` / ``async def on_event(event)``: convenience --
  auto-registered via ``bus.on_any``. 便捷形式——自动注册为全局监听。

``register`` takes precedence when both are defined. Plugin import errors and
handler exceptions are logged and isolated -- they never break the agent.
两者都定义时 ``register`` 优先。插件导入错误与 handler 异常都被隔离并记日志——
绝不影响 Agent 主流程。
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path

from mini_agent.events.bus import EventBus, EventHandler

logger = logging.getLogger(__name__)


def load_event_listeners(listener_dirs: list[str | Path], bus: EventBus) -> list[str]:
    """Load listener plugins from the given directories onto the bus.
    从给定目录加载监听插件并挂到事件总线上。

    Returns the names of successfully loaded plugins (file stem).
    返回成功加载的插件名列表（文件名去后缀）。
    """
    loaded: list[str] = []
    for raw_dir in listener_dirs:
        dir_path = Path(raw_dir).expanduser()
        if not dir_path.is_dir():
            continue
        for py_file in sorted(dir_path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            name = _load_plugin(py_file, bus)
            if name:
                loaded.append(name)
    return loaded


def _load_plugin(path: Path, bus: EventBus) -> str | None:
    """Import a single plugin file and register its handlers.
    导入单个插件文件并注册其 handler。失败返回 None。"""
    plugin_name = path.stem
    module_name = f"mini_agent_listener_{plugin_name}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("listener plugin %s: cannot create import spec", path)
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        logger.warning("listener plugin %s: import failed", path, exc_info=True)
        return None

    register = getattr(module, "register", None)
    on_event = getattr(module, "on_event", None)
    if callable(register):
        try:
            register(bus)
        except Exception:
            logger.warning("listener plugin %s: register() failed", path, exc_info=True)
            return None
        return plugin_name
    if callable(on_event):
        bus.on_any(_wrap_handler(on_event, plugin_name))
        return plugin_name
    logger.warning("listener plugin %s: no register() or on_event() found", path)
    return None


def _wrap_handler(fn, plugin_name: str) -> EventHandler:
    """Adapt sync/async on_event to an isolated async EventHandler.
    将同步/异步 on_event 适配为异常隔离的异步 EventHandler。"""

    async def handler(event) -> None:
        try:
            result = fn(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.warning("listener plugin %s: handler failed", plugin_name, exc_info=True)

    return handler
