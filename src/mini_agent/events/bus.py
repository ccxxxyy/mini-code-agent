"""Async publish-subscribe event bus. 异步发布-订阅事件总线。"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from mini_agent.models.events import Event

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any], Awaitable[None]]


class EventBus:
    """Async publish-subscribe event bus for decoupling components.
    用于组件解耦的异步发布-订阅事件总线。
    """

    def __init__(self) -> None:
        self._handlers: dict[type, list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []

    def on(self, event_type: type, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def on_any(self, handler: EventHandler) -> None:
        self._global_handlers.append(handler)

    def off(self, event_type: type, handler: EventHandler) -> None:
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def off_any(self, handler: EventHandler) -> None:
        if handler in self._global_handlers:
            self._global_handlers.remove(handler)

    async def emit(self, event: Event) -> None:
        event_type: type = type(event)
        handlers = list(self._handlers.get(event_type, []))
        handlers.extend(self._global_handlers)
        if not handlers:
            return
        results = await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                # A broken handler must not break emit; surface it in logs
                # 坏 handler 不能炸掉 emit；但要在日志中暴露
                logger.warning("event handler failed for %s", event_type.__name__, exc_info=result)
