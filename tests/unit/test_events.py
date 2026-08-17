"""Tests for event bus."""

import asyncio

from mini_agent.events.bus import EventBus
from mini_agent.models.events import LLMRequestEvent, UserMessageEvent


def test_event_bus_on_and_emit():
    results = []

    async def handler(event):
        results.append(event)

    bus = EventBus()
    bus.on(UserMessageEvent, handler)
    asyncio.run(bus.emit(UserMessageEvent(content="hello")))

    assert len(results) == 1
    assert results[0].content == "hello"


def test_event_bus_does_not_cross_types():
    results = []

    async def handler(event):
        results.append(event)

    bus = EventBus()
    bus.on(UserMessageEvent, handler)
    asyncio.run(bus.emit(LLMRequestEvent(message_count=1)))

    assert len(results) == 0


def test_event_bus_on_any():
    results = []

    async def handler(event):
        results.append(event)

    bus = EventBus()
    bus.on_any(handler)
    asyncio.run(bus.emit(UserMessageEvent(content="a")))
    asyncio.run(bus.emit(LLMRequestEvent(message_count=2)))

    assert len(results) == 2


def test_event_bus_off():
    results = []

    async def handler(event):
        results.append(event)

    bus = EventBus()
    bus.on(UserMessageEvent, handler)
    bus.off(UserMessageEvent, handler)
    asyncio.run(bus.emit(UserMessageEvent(content="ignored")))

    assert len(results) == 0
