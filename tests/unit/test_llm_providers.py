"""Tests for LLM provider parsing layers. LLM Provider 解析层的测试。"""

from mini_agent.llm.anthropic_provider import AnthropicProvider
from mini_agent.llm.base import StreamChunk, ToolCallDelta
from mini_agent.llm.openai_provider import OpenAIProvider, assemble_response
from mini_agent.models.config import LLMConfig

# --- OpenAI: _parse_chunk ---


def make_openai() -> OpenAIProvider:
    return OpenAIProvider(LLMConfig(provider="openai", api_key="test"))


def test_openai_parse_text_delta():
    provider = make_openai()
    chunk = provider._parse_chunk(
        {"choices": [{"delta": {"content": "hello"}, "finish_reason": None}]}
    )
    assert chunk.delta == "hello"
    assert chunk.finish_reason is None


def test_openai_parse_finish_reason():
    provider = make_openai()
    chunk = provider._parse_chunk({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    assert chunk.finish_reason == "stop"


def test_openai_parse_tool_call_delta():
    provider = make_openai()
    chunk = provider._parse_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read_file", "arguments": '{"fi'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
    )
    assert len(chunk.tool_call_deltas) == 1
    tcd = chunk.tool_call_deltas[0]
    assert tcd.id == "call_1"
    assert tcd.name == "read_file"
    assert tcd.arguments_delta == '{"fi'


def test_openai_parse_usage():
    provider = make_openai()
    chunk = provider._parse_chunk(
        {
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )
    assert chunk.usage is not None
    assert chunk.usage.total_tokens == 15


def test_openai_context_window_lookup():
    provider = OpenAIProvider(LLMConfig(api_key="x", model="gpt-4"))
    assert provider.context_window == 8_192
    provider = OpenAIProvider(LLMConfig(api_key="x", model="unknown-model"))
    assert provider.context_window == 128_000  # fallback 兜底值


# --- assemble_response: 碎片组装 ---


def test_assemble_text_only():
    chunks = [
        StreamChunk(delta="Hello "),
        StreamChunk(delta="world"),
        StreamChunk(finish_reason="stop"),
    ]
    resp = assemble_response(chunks)
    assert resp.content == "Hello world"
    assert resp.finish_reason == "stop"
    assert resp.tool_calls == []


def test_assemble_fragmented_tool_call():
    # Tool call arguments split across 3 chunks 工具调用参数分散在 3 个 chunk 中
    chunks = [
        StreamChunk(tool_call_deltas=[ToolCallDelta(index=0, id="c1", name="read_file")]),
        StreamChunk(tool_call_deltas=[ToolCallDelta(index=0, arguments_delta='{"file_')]),
        StreamChunk(tool_call_deltas=[ToolCallDelta(index=0, arguments_delta='path": "a.py"}')]),
        StreamChunk(finish_reason="tool_calls"),
    ]
    resp = assemble_response(chunks)
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.id == "c1"
    assert tc.name == "read_file"
    assert tc.arguments == {"file_path": "a.py"}


def test_assemble_multiple_tool_calls():
    chunks = [
        StreamChunk(
            tool_call_deltas=[
                ToolCallDelta(index=0, id="c1", name="glob", arguments_delta='{"pattern": "*.py"}'),
                ToolCallDelta(index=1, id="c2", name="grep", arguments_delta='{"pattern": "TODO"}'),
            ]
        ),
        StreamChunk(finish_reason="tool_calls"),
    ]
    resp = assemble_response(chunks)
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0].name == "glob"
    assert resp.tool_calls[1].name == "grep"


def test_assemble_invalid_json_fallback():
    # Truncated JSON should not crash 截断的 JSON 不应导致崩溃
    chunks = [
        StreamChunk(
            tool_call_deltas=[
                ToolCallDelta(index=0, id="c1", name="bash", arguments_delta='{"comman')
            ]
        ),
        StreamChunk(finish_reason="tool_calls"),
    ]
    resp = assemble_response(chunks)
    assert resp.tool_calls[0].arguments == {}  # fallback 兜底为空字典
    assert resp.tool_calls[0].raw_arguments == '{"comman'


# --- Anthropic: _parse_event ---


def make_anthropic() -> AnthropicProvider:
    return AnthropicProvider(LLMConfig(provider="anthropic", api_key="test"))


def test_anthropic_text_delta():
    provider = make_anthropic()
    chunk = provider._parse_event(
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}
    )
    assert chunk is not None
    assert chunk.delta == "hi"


def test_anthropic_tool_use_start():
    provider = make_anthropic()
    chunk = provider._parse_event(
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "tu_1", "name": "read_file"},
        }
    )
    assert chunk is not None
    tcd = chunk.tool_call_deltas[0]
    assert tcd.id == "tu_1"
    assert tcd.name == "read_file"
    assert tcd.index == 1


def test_anthropic_input_json_delta():
    provider = make_anthropic()
    chunk = provider._parse_event(
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"a":'},
        }
    )
    assert chunk is not None
    assert chunk.tool_call_deltas[0].arguments_delta == '{"a":'


def test_anthropic_stop_reason_mapping():
    provider = make_anthropic()
    chunk = provider._parse_event(
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {}}
    )
    assert chunk is not None
    assert chunk.finish_reason == "stop"

    chunk = provider._parse_event(
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {}}
    )
    assert chunk.finish_reason == "tool_calls"


def test_anthropic_unknown_event_ignored():
    provider = make_anthropic()
    assert provider._parse_event({"type": "ping"}) is None


# --- Anthropic: 消息格式转换 ---


def test_anthropic_split_system():
    system, msgs = AnthropicProvider._split_system(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
    )
    assert system == "You are helpful."
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


def test_anthropic_tool_call_conversion():
    _, msgs = AnthropicProvider._split_system(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path": "x"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "file data"},
        ]
    )
    # assistant tool_calls → content 里的 tool_use 块
    assert msgs[0]["role"] == "assistant"
    tool_use = msgs[0]["content"][0]
    assert tool_use["type"] == "tool_use"
    assert tool_use["id"] == "c1"
    assert tool_use["input"] == {"path": "x"}
    # tool 消息 → user 角色的 tool_result 块
    assert msgs[1]["role"] == "user"
    tool_result = msgs[1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "c1"


def test_anthropic_tools_format_conversion():
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    result = AnthropicProvider._convert_tools(openai_tools)
    assert result[0]["name"] == "read_file"
    assert result[0]["description"] == "Read a file"
    assert "input_schema" in result[0]
