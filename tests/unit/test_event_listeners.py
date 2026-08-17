"""Tests for event listener plugins (global event listening)."""

import asyncio
import logging

from mini_agent.events.bus import EventBus
from mini_agent.extensions.event_listeners import load_event_listeners
from mini_agent.models.events import LLMRequestEvent, UserMessageEvent


def _write(tmp_path, name, code):
    f = tmp_path / name
    f.write_text(code, encoding="utf-8")
    return f


def test_load_on_event_async(tmp_path):
    _write(
        tmp_path,
        "collector.py",
        "events = []\nasync def on_event(event):\n    events.append(type(event).__name__)\n",
    )
    bus = EventBus()
    loaded = load_event_listeners([tmp_path], bus)
    assert loaded == ["collector"]

    asyncio.run(bus.emit(UserMessageEvent(content="hi")))
    asyncio.run(bus.emit(LLMRequestEvent(message_count=1)))

    import sys

    module = sys.modules["mini_agent_listener_collector"]
    assert module.events == ["UserMessageEvent", "LLMRequestEvent"]


def test_load_on_event_sync(tmp_path):
    _write(
        tmp_path,
        "sync_collector.py",
        "count = 0\ndef on_event(event):\n    global count\n    count += 1\n",
    )
    bus = EventBus()
    loaded = load_event_listeners([tmp_path], bus)
    assert loaded == ["sync_collector"]

    asyncio.run(bus.emit(UserMessageEvent(content="a")))

    import sys

    assert sys.modules["mini_agent_listener_sync_collector"].count == 1


def test_load_register_style(tmp_path):
    _write(
        tmp_path,
        "targeted.py",
        "from mini_agent.models.events import UserMessageEvent\n"
        "seen = []\n"
        "def register(bus):\n"
        "    async def handler(event):\n"
        "        seen.append(event.content)\n"
        "    bus.on(UserMessageEvent, handler)\n",
    )
    bus = EventBus()
    loaded = load_event_listeners([tmp_path], bus)
    assert loaded == ["targeted"]

    asyncio.run(bus.emit(UserMessageEvent(content="only-this")))
    asyncio.run(bus.emit(LLMRequestEvent(message_count=1)))

    import sys

    assert sys.modules["mini_agent_listener_targeted"].seen == ["only-this"]


def test_broken_plugin_skipped(tmp_path, caplog):
    _write(tmp_path, "broken.py", "raise RuntimeError('boom at import')\n")
    _write(
        tmp_path,
        "good.py",
        "async def on_event(event):\n    pass\n",
    )
    bus = EventBus()
    with caplog.at_level(logging.WARNING):
        loaded = load_event_listeners([tmp_path], bus)
    assert loaded == ["good"]
    assert any("import failed" in r.message for r in caplog.records)


def test_plugin_without_contract_skipped(tmp_path, caplog):
    _write(tmp_path, "empty.py", "x = 1\n")
    bus = EventBus()
    with caplog.at_level(logging.WARNING):
        loaded = load_event_listeners([tmp_path], bus)
    assert loaded == []
    assert any("no register() or on_event()" in r.message for r in caplog.records)


def test_handler_exception_isolated(tmp_path, caplog):
    _write(
        tmp_path,
        "faulty.py",
        "async def on_event(event):\n    raise ValueError('handler boom')\n",
    )
    bus = EventBus()
    load_event_listeners([tmp_path], bus)

    # Regular handlers still run despite the faulty plugin
    # 坏插件不影响其他 handler
    results = []

    async def ok_handler(event):
        results.append(event)

    bus.on(UserMessageEvent, ok_handler)
    with caplog.at_level(logging.WARNING):
        asyncio.run(bus.emit(UserMessageEvent(content="x")))

    assert len(results) == 1
    assert any("handler failed" in r.message for r in caplog.records)


def test_underscore_files_and_missing_dirs_ignored(tmp_path):
    _write(tmp_path, "_private.py", "async def on_event(event):\n    pass\n")
    bus = EventBus()
    loaded = load_event_listeners([tmp_path, tmp_path / "nonexistent"], bus)
    assert loaded == []


def test_bus_off_any():
    results = []

    async def handler(event):
        results.append(event)

    bus = EventBus()
    bus.on_any(handler)
    bus.off_any(handler)
    asyncio.run(bus.emit(UserMessageEvent(content="ignored")))
    assert results == []


def test_emit_logs_handler_exception(caplog):
    async def bad_handler(event):
        raise RuntimeError("kaboom")

    bus = EventBus()
    bus.on(UserMessageEvent, bad_handler)
    with caplog.at_level(logging.WARNING):
        asyncio.run(bus.emit(UserMessageEvent(content="x")))
    assert any("event handler failed" in r.message for r in caplog.records)
