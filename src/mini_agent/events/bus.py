"""Async publish-subscribe event bus."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from mini_agent.models.events import Event

EventHandler = Callable[[Any], Awaitable[None]]


class EventBus:
    """Async publish-subscribe event bus for decoupling components."""

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

    async def emit(self, event: Event) -> None:
        event_type: type = type(event)
        handlers = list(self._handlers.get(event_type, []))
        handlers.extend(self._global_handlers)
        if handlers:
            await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
