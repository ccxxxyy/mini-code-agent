"""Tests for the OpenAI Responses API provider (comparison 1.1).
OpenAI Responses API Provider 的测试。"""

from __future__ import annotations

import pytest

from mini_agent.llm.base import StreamChunk, TokenUsage, ToolCallDelta
from mini_agent.llm.openai_responses_provider import OpenAIResponsesProvider
from mini_agent.models.config import LLMConfig

pytestmark = pytest.mark.asyncio


def make_provider() -> OpenAIResponsesProvider:
    return OpenAIResponsesProvider(LLMConfig(api_key="test", model="o1"))


# --- _convert_to_input 消息转换 ---


def test_convert_system_extraction():
    instructions, items = OpenAIResponsesProvider._convert_to_input(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
    )
    assert instructions == "You are helpful."
    assert len(items) == 1
    assert items[0] == {"type": "message", "role": "user", "content": "hi"}


def test_convert_tool_calls_to_function_call():
    _, items = OpenAIResponsesProvider._convert_to_input(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path": "x.py"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "file data"},
        ]
    )
    assert items[0]["type"] == "function_call"
    assert items[0]["call_id"] == "c1"
    assert items[0]["name"] == "read_file"
    assert items[0]["arguments"] == '{"path": "x.py"}'
    assert items[1]["type"] == "function_call_output"
    assert items[1]["call_id"] == "c1"
    assert items[1]["output"] == "file data"


def test_convert_assistant_text_plus_tool_calls():
    _, items = OpenAIResponsesProvider._convert_to_input(
        [
            {
                "role": "assistant",
                "content": "Let me check.",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"command": "ls"}'},
                    }
                ],
            },
        ]
    )
    assert items[0]["type"] == "message"
    assert items[0]["content"] == "Let me check."
    assert items[1]["type"] == "function_call"


def test_convert_no_system():
    instructions, items = OpenAIResponsesProvider._convert_to_input(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
    )
    assert instructions == ""
    assert len(items) == 2


# --- _convert_tools 工具扁平化 ---


def test_convert_tools_flattens():
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }
    ]
    result = OpenAIResponsesProvider._convert_tools(openai_tools)
    assert result[0]["type"] == "function"
    assert result[0]["name"] == "read_file"
    assert result[0]["description"] == "Read a file"
    assert "function" not in result[0]
    assert result[0]["parameters"]["properties"]["path"]["type"] == "string"


# --- _parse_event 事件解析 ---


def test_parse_text_delta():
    p = make_provider()
    chunk = p._parse_event({"type": "response.output_text.delta", "delta": "Hello"}, {}, False)
    assert chunk.delta == "Hello"


def test_parse_thinking_delta():
    p = make_provider()
    chunk = p._parse_event(
        {"type": "response.reasoning_summary_text.delta", "delta": "thinking..."}, {}, False
    )
    assert chunk.thinking == "thinking..."


def test_parse_tool_call_start():
    p = make_provider()
    tool_calls: dict = {}
    chunk = p._parse_event(
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {"type": "function_call", "call_id": "fc_1", "name": "read_file"},
        },
        tool_calls,
        False,
    )
    assert chunk.tool_call_deltas[0].id == "fc_1"
    assert chunk.tool_call_deltas[0].name == "read_file"
    assert chunk.tool_call_deltas[0].index == 0
    assert tool_calls[0] == {"call_id": "fc_1", "name": "read_file"}


def test_parse_tool_call_args_delta():
    p = make_provider()
    chunk = p._parse_event(
        {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '{"fi'},
        {0: {"call_id": "fc_1", "name": "read_file"}},
        False,
    )
    assert chunk.tool_call_deltas[0].arguments_delta == '{"fi'
    assert chunk.tool_call_deltas[0].index == 0


def test_parse_completed_stop():
    p = make_provider()
    chunk = p._parse_event(
        {
            "type": "response.completed",
            "response": {
                "output": [{"type": "message"}],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        },
        {},
        False,
    )
    assert chunk.finish_reason == "stop"
    assert chunk.usage.prompt_tokens == 100
    assert chunk.usage.completion_tokens == 50
    assert chunk.usage.total_tokens == 150


def test_parse_completed_tool_calls():
    p = make_provider()
    chunk = p._parse_event(
        {
            "type": "response.completed",
            "response": {
                "output": [{"type": "function_call", "name": "read_file"}],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        },
        {},
        True,
    )
    assert chunk.finish_reason == "tool_calls"


def test_parse_incomplete_is_length():
    p = make_provider()
    chunk = p._parse_event(
        {
            "type": "response.incomplete",
            "response": {"incomplete_details": {"reason": "max_output_tokens"}},
        },
        {},
        False,
    )
    assert chunk.finish_reason == "length"


def test_parse_cached_tokens():
    p = make_provider()
    chunk = p._parse_event(
        {
            "type": "response.completed",
            "response": {
                "output": [],
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "input_tokens_details": {"cached_tokens": 800},
                },
            },
        },
        {},
        False,
    )
    assert chunk.usage.cache_read_input_tokens == 800
    assert chunk.usage.prompt_tokens == 1000


def test_parse_unknown_event_ignored():
    p = make_provider()
    assert p._parse_event({"type": "response.created"}, {}, False) is None
    assert p._parse_event({"type": "response.in_progress"}, {}, False) is None


def test_parse_non_function_output_item_ignored():
    p = make_provider()
    assert (
        p._parse_event(
            {"type": "response.output_item.added", "item": {"type": "message"}}, {}, False
        )
        is None
    )


# --- assemble_response 集成 ---


def test_assemble_with_responses_chunks():
    from mini_agent.llm.base import assemble_response

    chunks = [
        StreamChunk(delta="Hello "),
        StreamChunk(delta="world"),
        StreamChunk(tool_call_deltas=[ToolCallDelta(index=0, id="fc_1", name="read_file")]),
        StreamChunk(tool_call_deltas=[ToolCallDelta(index=0, arguments_delta='{"path": "x.py"}')]),
        StreamChunk(
            finish_reason="tool_calls",
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        ),
    ]
    resp = assemble_response(chunks)
    assert resp.content == "Hello world"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "read_file"
    assert resp.tool_calls[0].arguments == {"path": "x.py"}
    assert resp.finish_reason == "tool_calls"
    assert resp.usage.prompt_tokens == 100


# --- context window ---


def test_context_window_o1():
    p = OpenAIResponsesProvider(LLMConfig(api_key="x", model="o1"))
    assert p.context_window == 200_000


def test_context_window_unknown_defaults_200k():
    p = OpenAIResponsesProvider(LLMConfig(api_key="x", model="future-model"))
    assert p.context_window == 200_000


# --- registry ---


def test_registry_has_openai_responses():
    from mini_agent.llm.registry import ProviderRegistry

    assert "openai-responses" in ProviderRegistry.list_providers()
    provider = ProviderRegistry.create(
        LLMConfig(provider="openai-responses", api_key="test", model="o1")
    )
    assert isinstance(provider, OpenAIResponsesProvider)


# --- Thinking round-trip 思维回传 ---


def test_convert_thinking_round_trip():
    """Assistant messages with thinking metadata emit reasoning items
    before text/tool_calls. 带 thinking 的助手消息在文本/工具前发出 reasoning 项。"""
    _, items = OpenAIResponsesProvider._convert_to_input(
        [
            {
                "role": "assistant",
                "content": "The answer is 42.",
                "id": "msg_123",
                "metadata": {"thinking": "I need to reason about this..."},
            },
        ]
    )
    assert items[0]["type"] == "reasoning"
    assert items[0]["id"] == "msg_123"
    assert items[0]["summary"][0]["text"] == "I need to reason about this..."
    assert items[1]["type"] == "message"
    assert items[1]["content"] == "The answer is 42."


def test_convert_no_thinking_no_reasoning_item():
    _, items = OpenAIResponsesProvider._convert_to_input(
        [{"role": "assistant", "content": "no thinking here"}]
    )
    assert all(item["type"] != "reasoning" for item in items)


def test_assemble_accumulates_thinking():
    from mini_agent.llm.base import assemble_response

    chunks = [
        StreamChunk(thinking="step 1, "),
        StreamChunk(thinking="step 2"),
        StreamChunk(delta="result"),
        StreamChunk(finish_reason="stop"),
    ]
    resp = assemble_response(chunks)
    assert resp.thinking == "step 1, step 2"
    assert resp.content == "result"


# --- Tool pairing repair 工具配对修复 ---


def test_convert_orphan_tool_call_gets_synthetic_result():
    """function_call without a matching function_call_output gets a
    synthetic error result (interrupted session repair).
    无匹配结果的 function_call 补合成错误结果（中断会话修复）。"""
    _, items = OpenAIResponsesProvider._convert_to_input(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "orphan_1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": '{"command": "ls"}'},
                    }
                ],
            },
            # No tool result for orphan_1 没有对应结果
        ]
    )
    outputs = [i for i in items if i["type"] == "function_call_output"]
    assert len(outputs) == 1
    assert outputs[0]["call_id"] == "orphan_1"
    assert "interrupted" in outputs[0]["output"]


def test_convert_paired_tool_call_no_synthetic():
    _, items = OpenAIResponsesProvider._convert_to_input(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        ]
    )
    outputs = [i for i in items if i["type"] == "function_call_output"]
    assert len(outputs) == 1  # Only the real result, no synthetic 只有真结果
    assert outputs[0]["output"] == "ok"


# --- Error classification 错误分类 ---


async def test_error_classification_401():
    import httpx as _httpx

    from mini_agent.llm.openai_responses_provider import LLMAuthenticationError

    provider = make_provider()
    provider._probe_attempted = True

    def handler(request: _httpx.Request) -> _httpx.Response:
        return _httpx.Response(401)

    provider._client = _httpx.AsyncClient(
        base_url="http://test/v1", transport=_httpx.MockTransport(handler)
    )
    with pytest.raises(LLMAuthenticationError):
        async for _ in provider.stream([{"role": "user", "content": "hi"}]):
            pass


async def test_error_classification_network():
    import httpx as _httpx

    from mini_agent.llm.openai_responses_provider import LLMNetworkError

    provider = make_provider()
    provider._probe_attempted = True

    def handler(request: _httpx.Request) -> _httpx.Response:
        raise _httpx.ConnectError("refused")

    provider._client = _httpx.AsyncClient(
        base_url="http://test/v1", transport=_httpx.MockTransport(handler)
    )
    with pytest.raises(LLMNetworkError):
        async for _ in provider.stream([{"role": "user", "content": "hi"}]):
            pass
