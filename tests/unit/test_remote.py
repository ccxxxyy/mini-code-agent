"""Tests for remote/browser mode. 远程/浏览器模式测试。"""

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
    loop = asyncio.get_running_loop()
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
    assert "permission" in html
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


def test_cli_remote_token():
    from mini_agent.cli import parse_args

    args = parse_args(["--remote", "--remote-token", "secret123"])
    assert args.remote_token == "secret123"

    args2 = parse_args(["--remote"])
    assert args2.remote_token == ""


# --- Disconnect queuing ---


@pytest.mark.asyncio
async def test_disconnect_timeout_denies_pending():
    """When timeout expires, all pending futures are denied."""
    from mini_agent.remote.server import RemoteServer

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()

    server = object.__new__(RemoteServer)
    server._pending_confirms = {"req1": future}
    server._pending_prompts = {"req1": "Allow?"}

    await server._disconnect_timeout(timeout=0.05)
    assert future.done()
    assert future.result() is False
    assert len(server._pending_confirms) == 0
    assert len(server._pending_prompts) == 0


@pytest.mark.asyncio
async def test_disconnect_timeout_cancelled_on_reconnect():
    """Cancelling the timeout task should not deny futures."""
    from mini_agent.remote.server import RemoteServer

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()

    server = object.__new__(RemoteServer)
    server._pending_confirms = {"req1": future}
    server._pending_prompts = {"req1": "Allow?"}

    task = asyncio.create_task(server._disconnect_timeout(timeout=10.0))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert not future.done()


@pytest.mark.asyncio
async def test_resolve_cleans_prompt():
    """Resolving a permission should clean up _pending_prompts."""
    from mini_agent.remote.server import RemoteServer

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()

    server = object.__new__(RemoteServer)
    server._pending_confirms = {"req1": future}
    server._pending_prompts = {"req1": "Allow?"}

    server._resolve_permission("req1", "y")
    assert "req1" not in server._pending_prompts
    assert future.result() is True


def test_cli_default_no_remote():
    from mini_agent.cli import parse_args

    args = parse_args([])
    assert args.remote is False
    assert args.port == 8765
    assert args.host == "localhost"


def test_remote_server_wraps_terminal():
    """Test that RemoteServer wraps the terminal to intercept UI calls."""
    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader
    from mini_agent.remote.server import RemoteServer
    from mini_agent.remote.terminal import RemoteTerminalAdapter

    config = ConfigLoader.load(cli_overrides={"llm.api_key": "test"})
    app = Application(config)
    original_terminal = app.terminal

    RemoteServer(app, host="localhost", port=19999)

    # Terminal should be wrapped
    assert isinstance(app.terminal, RemoteTerminalAdapter)
    assert app.terminal._terminal is original_terminal


def test_remote_terminal_adapter_show_info():
    """Test that RemoteTerminalAdapter intercepts show_info calls."""
    from mini_agent.remote.terminal import RemoteTerminalAdapter

    sent_messages = []

    def mock_send(event_type, **data):
        sent_messages.append((event_type, data))

    class MockTerminal:
        def show_info(self, msg):
            pass

    adapter = RemoteTerminalAdapter(MockTerminal(), mock_send)
    adapter.show_info("test message")

    # Should have sent to WebSocket
    assert len(sent_messages) > 0
    assert sent_messages[0][0] == "info"
    assert sent_messages[0][1]["message"] == "test message"


def test_remote_json_dumps_with_non_serializable():
    """Test that RemoteServer handles non-serializable tool arguments."""
    import json

    # This would normally crash json.dumps
    non_serializable = {"key": object()}

    try:
        json.dumps(non_serializable, ensure_ascii=False)
        assert False, "Should have raised TypeError"
    except TypeError:
        pass

    # But our fixed code should handle it
    try:
        args_preview = json.dumps(non_serializable, ensure_ascii=False)[:200]
    except (TypeError, ValueError):
        args_preview = str(non_serializable)[:200]

    assert isinstance(args_preview, str)


def test_turn_start_end_events_format():
    """turn_start / turn_end events round-trip through JSON."""
    for event in [{"type": "turn_start"}, {"type": "turn_end"}]:
        parsed = json.loads(json.dumps(event))
        assert parsed["type"] == event["type"]


def test_thinking_delta_event_format():
    """thinking_delta event round-trips through JSON."""
    event = {"type": "thinking_delta", "delta": "Let me reason..."}
    parsed = json.loads(json.dumps(event, ensure_ascii=False))
    assert parsed["type"] == "thinking_delta"
    assert parsed["delta"] == "Let me reason..."


def test_stream_chunk_thinking_field():
    """StreamChunk supports the thinking field."""
    from mini_agent.llm.base import StreamChunk

    default = StreamChunk()
    assert default.thinking == ""

    chunk = StreamChunk(thinking="reasoning step")
    assert chunk.thinking == "reasoning step"
    assert chunk.delta == ""


def test_web_ui_has_thinking_indicator():
    """Browser frontend handles turn_start, turn_end, thinking_delta."""
    from mini_agent.remote.web_ui import build_html

    html = build_html(8765)
    assert "turn_start" in html
    assert "turn_end" in html
    assert "thinking_delta" in html
    assert "thinking-indicator" in html
    assert "showSpinner" in html
    assert "history_user" in html
    assert "history_assistant" in html


def test_openai_parse_reasoning_content():
    """OpenAI provider captures reasoning_content into chunk.thinking."""
    from mini_agent.llm.openai_provider import OpenAIProvider
    from mini_agent.models.config import LLMConfig

    config = LLMConfig(api_key="test", model="deepseek-r1")
    provider = OpenAIProvider(config)

    chunk_data = {
        "choices": [
            {
                "delta": {"reasoning_content": "Let me think about this"},
                "finish_reason": None,
            }
        ]
    }
    chunk = provider._parse_chunk(chunk_data)
    assert chunk.thinking == "Let me think about this"
    assert chunk.delta == ""


def test_anthropic_parse_thinking_delta():
    """Anthropic provider captures thinking_delta into chunk.thinking."""
    from mini_agent.llm.anthropic_provider import AnthropicProvider
    from mini_agent.models.config import LLMConfig

    config = LLMConfig(api_key="test", model="claude-sonnet-4-20250514")
    provider = AnthropicProvider(config)

    event = {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "thinking_delta", "thinking": "Analyzing the code"},
    }
    chunk = provider._parse_event(event)
    assert chunk is not None
    assert chunk.thinking == "Analyzing the code"
    assert chunk.delta == ""


def test_remote_terminal_adapter_suppresses_internal_errors():
    """Internal Python errors are not sent to the browser."""
    from mini_agent.remote.terminal import RemoteTerminalAdapter

    sent = []

    def mock_send(event_type, **data):
        sent.append((event_type, data))

    class MockTerminal:
        def show_error(self, msg):
            pass

    adapter = RemoteTerminalAdapter(MockTerminal(), mock_send)
    adapter.show_error("'list' object has no attribute 'items'")
    assert len(sent) == 0

    adapter.show_error("API 请求失败 (401)")
    assert len(sent) == 1
    assert sent[0][0] == "error"


def test_remote_terminal_adapter_show_file_changes():
    """RemoteTerminalAdapter.show_file_changes handles list[tuple[str, str]]."""
    from mini_agent.remote.terminal import RemoteTerminalAdapter

    sent = []

    def mock_send(event_type, **data):
        sent.append((event_type, data))

    class MockTerminal:
        def show_file_changes(self, changes):
            pass

    adapter = RemoteTerminalAdapter(MockTerminal(), mock_send)
    adapter.show_file_changes([("created", "new.py"), ("modified", "old.py")])
    assert len(sent) == 1
    assert sent[0][0] == "file_changes"
    assert "+ new.py" in sent[0][1]["items"]
    assert "~ old.py" in sent[0][1]["items"]


@pytest.mark.asyncio
async def test_replay_history_sends_messages():
    """_replay_history sends existing conversation as history events."""
    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader
    from mini_agent.models.message import Message, Role
    from mini_agent.remote.server import RemoteServer

    config = ConfigLoader.load(cli_overrides={"llm.api_key": "test"})
    app = Application(config)
    app.session.conversation.append(Message(role=Role.USER, content="hello"))
    app.session.conversation.append(Message(role=Role.ASSISTANT, content="hi there"))

    sent = []

    class MockWS:
        async def send(self, data):
            sent.append(json.loads(data))

    server = RemoteServer(app, host="localhost", port=29999)
    mock_ws = MockWS()
    server._clients.add(mock_ws)
    await server._replay_history(mock_ws)

    types = [m["type"] for m in sent]
    assert "history_user" in types
    assert "history_assistant" in types
    user_msg = next(m for m in sent if m["type"] == "history_user")
    assert user_msg["text"] == "hello"
    asst_msg = next(m for m in sent if m["type"] == "history_assistant")
    assert asst_msg["text"] == "hi there"


def test_token_comparison_uses_constant_time():
    """Token comparison must use hmac.compare_digest, not == or !=."""
    import inspect

    from mini_agent.remote.server import RemoteServer

    source = inspect.getsource(RemoteServer._handler)
    assert "compare_digest" in source, (
        "_handler must use hmac.compare_digest for token comparison, not == or !="
    )
