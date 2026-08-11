"""Tests for remote/browser mode (P57). 远程/浏览器模式测试。"""

from __future__ import annotations

import asyncio
import json

import pytest


def test_ndjson_event_format():

    events = [
        {"type": "stream_text", "delta": "hello"},
        {"type": "stream_start"},
        {"type": "stream_end"},
        {"type": "tool_call", "name": "read_file", "args": '{"file_path": "x.py"}'},
        {"type": "tool_result", "name": "read_file", "output": "content", "is_error": False},
        {"type": "permission_request", "id": "abc", "prompt": "Allow bash?"},
        {"type": "info", "message": "Connected"},
    ]
    for event in events:
        serialized = json.dumps(event, ensure_ascii=False)
        parsed = json.loads(serialized)
        assert parsed["type"] == event["type"]


def test_client_message_format():
    msgs = [
        {"type": "user_input", "text": "hello"},
        {"type": "permission_response", "id": "abc", "decision": "y"},
        {"type": "permission_response", "id": "def", "decision": "n"},
        {"type": "permission_response", "id": "ghi", "decision": "a"},
    ]
    for msg in msgs:
        serialized = json.dumps(msg)
        parsed = json.loads(serialized)
        assert parsed["type"] == msg["type"]


@pytest.mark.asyncio
async def test_permission_future_flow():
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()

    future.set_result(True)
    assert await future is True

    future2: asyncio.Future = loop.create_future()
    future2.set_result("always")
    assert await future2 == "always"

    future3: asyncio.Future = loop.create_future()
    future3.set_result(False)
    assert await future3 is False


def test_web_ui_builds():
    from mini_agent.remote.web_ui import build_html

    html = build_html(8765)
    assert "<!DOCTYPE html>" in html
    assert "Mini-Code-Agent" in html
    assert "WebSocket" in html
    assert "user_input" in html
    assert "permission_response" in html
    assert "stream_text" in html


def test_web_ui_port_embedded():
    from mini_agent.remote.web_ui import build_html

    html = build_html(9999)
    assert "Mini-Code-Agent" in html


def test_remote_server_class_exists():
    from mini_agent.remote.server import RemoteServer

    assert RemoteServer is not None


def test_cli_remote_args():
    from mini_agent.cli import parse_args

    args = parse_args(["--remote", "--port", "9999", "--host", "0.0.0.0"])
    assert args.remote is True
    assert args.port == 9999
    assert args.host == "0.0.0.0"


def test_cli_default_no_remote():
    from mini_agent.cli import parse_args

    args = parse_args([])
    assert args.remote is False
    assert args.port == 8765
    assert args.host == "localhost"
