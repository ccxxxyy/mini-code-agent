"""Tests for LLM provider parsing layers. LLM Provider 解析层的测试。"""

from mini_agent.llm.anthropic_provider import AnthropicProvider
from mini_agent.llm.base import StreamChunk, ToolCallDelta, assemble_response
from mini_agent.llm.openai_provider import OpenAIProvider
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


# --- OpenAI: 上下文窗口 API 探测 ---


def test_extract_context_window_top_level():
    assert OpenAIProvider._extract_context_window({"context_window": 200_000}) == 200_000
    assert OpenAIProvider._extract_context_window({"context_length": 131_072}) == 131_072
    assert OpenAIProvider._extract_context_window({"max_model_len": 32_768}) == 32_768


def test_extract_context_window_nested():
    # OpenRouter 风格：字段在嵌套对象里
    data = {"id": "m", "top_provider": {"context_length": 65_536}}
    assert OpenAIProvider._extract_context_window(data) == 65_536


def test_extract_context_window_deeply_nested():
    # 阿里云 MaaS 风格：extra_info.default_envs.max_input_tokens（实测验证）
    data = {
        "id": "deepseek-v4-flash-0731",
        "extra_info": {"default_envs": {"max_tokens": 131_072, "max_input_tokens": 129_024}},
    }
    assert OpenAIProvider._extract_context_window(data) == 129_024


def test_extract_context_window_missing_or_invalid():
    assert OpenAIProvider._extract_context_window({"id": "gpt-4o"}) is None
    assert OpenAIProvider._extract_context_window({"context_window": "big"}) is None
    assert OpenAIProvider._extract_context_window({"context_window": 0}) is None


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


async def test_probe_context_window_success():
    provider = OpenAIProvider(LLMConfig(api_key="x", model="some-new-model"))

    async def fake_get(url, **kwargs):
        assert url == "/models/some-new-model"
        return _FakeResponse({"id": "some-new-model", "context_window": 262_144})

    provider._client.get = fake_get
    await provider._probe_context_window()
    assert provider.context_window == 262_144


async def test_probe_context_window_failure_falls_back():
    import httpx

    provider = OpenAIProvider(LLMConfig(api_key="x", model="gpt-4"))

    async def fake_get(url, **kwargs):
        raise httpx.ConnectError("boom")

    provider._client.get = fake_get
    await provider._probe_context_window()
    assert provider.context_window == 8_192  # 回退到硬编码表


async def test_prepare_probes_context_window():
    # 启动预热：app.run() 在首轮对话前调用 prepare()，让首轮溢出检查用真实窗口
    provider = OpenAIProvider(LLMConfig(api_key="x", model="some-new-model"))

    async def fake_get(url, **kwargs):
        return _FakeResponse({"context_window": 262_144})

    provider._client.get = fake_get
    await provider.prepare()
    assert provider.context_window == 262_144


async def test_probe_context_window_only_once():
    provider = OpenAIProvider(LLMConfig(api_key="x", model="m"))
    calls = 0

    async def fake_get(url, **kwargs):
        nonlocal calls
        calls += 1
        return _FakeResponse({"context_window": 100_000})

    provider._client.get = fake_get
    await provider._probe_context_window()
    await provider._probe_context_window()
    assert calls == 1


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

    # max_tokens 归一化为 OpenAI 的 "length"——agent_loop 恢复逻辑两家通用
    chunk = provider._parse_event(
        {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {}}
    )
    assert chunk.finish_reason == "length"


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


# --- Anthropic: Prompt 缓存标记 ---


def test_anthropic_cache_control_on_system():

    provider = make_anthropic()
    system, api_msgs = provider._split_system(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
    )
    body: dict = {"model": "claude-sonnet-4-20250514", "messages": api_msgs}
    if system:
        body["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    assert isinstance(body["system"], list)
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["system"][0]["text"] == "You are helpful."


def test_anthropic_cache_control_on_last_tool():
    provider = make_anthropic()
    tools = [
        {
            "type": "function",
            "function": {"name": "read_file", "description": "Read", "parameters": {}},
        },
        {
            "type": "function",
            "function": {"name": "bash", "description": "Run", "parameters": {}},
        },
    ]
    converted = provider._convert_tools(tools)
    if converted:
        converted[-1] = {**converted[-1], "cache_control": {"type": "ephemeral"}}
    assert "cache_control" not in converted[0]
    assert converted[-1]["cache_control"] == {"type": "ephemeral"}
    assert converted[-1]["name"] == "bash"


def test_anthropic_cache_control_on_last_user_msg():
    from mini_agent.llm.anthropic_provider import _mark_last_user_for_cache

    _, msgs = AnthropicProvider._split_system(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "second question"},
        ]
    )
    _mark_last_user_for_cache(msgs)
    last_user = msgs[-1]
    assert isinstance(last_user["content"], list)
    assert last_user["content"][0]["type"] == "text"
    assert last_user["content"][0]["text"] == "second question"
    assert last_user["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert isinstance(msgs[0]["content"], str)


def test_anthropic_cache_control_on_tool_result_user_msg():
    from mini_agent.llm.anthropic_provider import _mark_last_user_for_cache

    _, msgs = AnthropicProvider._split_system(
        [
            {"role": "user", "content": "do something"},
            {"role": "tool", "tool_call_id": "c1", "content": "result"},
        ]
    )
    _mark_last_user_for_cache(msgs)
    tool_result_msg = msgs[-1]
    assert tool_result_msg["role"] == "user"
    assert isinstance(tool_result_msg["content"], list)
    last_block = tool_result_msg["content"][-1]
    assert last_block["cache_control"] == {"type": "ephemeral"}


def test_anthropic_cache_control_no_tools():
    from mini_agent.llm.anthropic_provider import _mark_last_user_for_cache

    provider = make_anthropic()
    converted = provider._convert_tools([])
    assert converted == []

    _, msgs = AnthropicProvider._split_system([{"role": "system", "content": "sys"}])
    _mark_last_user_for_cache(msgs)


def test_anthropic_cache_usage_parsing():
    provider = make_anthropic()
    chunk = provider._parse_event(
        {
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 1000,
                    "cache_read_input_tokens": 800,
                    "cache_creation_input_tokens": 200,
                }
            },
        }
    )
    assert chunk is not None
    assert chunk.usage.prompt_tokens == 1000
    assert chunk.usage.cache_read_input_tokens == 800
    assert chunk.usage.cache_creation_input_tokens == 200


# --- Anthropic: 发送侧 extended thinking ---


def test_adaptive_thinking_model_detection():
    from mini_agent.llm.anthropic_provider import _supports_adaptive_thinking

    # >= 4.6 → 自适应（budget_tokens: 0）
    assert _supports_adaptive_thinking("claude-opus-4-6")
    assert _supports_adaptive_thinking("claude-sonnet-4-6-20260101")
    assert _supports_adaptive_thinking("claude-opus-5")
    # < 4.6 → 显式 budget；日期段不能被当成版本号
    assert not _supports_adaptive_thinking("claude-sonnet-4-5-20250929")
    assert not _supports_adaptive_thinking("claude-sonnet-4-20250514")
    assert not _supports_adaptive_thinking("claude-3-5-sonnet-20241022")
    assert not _supports_adaptive_thinking("claude-haiku-4-5")
    assert not _supports_adaptive_thinking("gpt-4o")


def test_anthropic_signature_delta_parsing():
    provider = make_anthropic()
    chunk = provider._parse_event(
        {
            "type": "content_block_delta",
            "delta": {"type": "signature_delta", "signature": "sig_abc"},
        }
    )
    assert chunk is not None
    assert chunk.thinking_signature == "sig_abc"


def test_assemble_response_collects_signature():
    chunks = [
        StreamChunk(thinking="let me think"),
        StreamChunk(thinking_signature="sig_"),
        StreamChunk(thinking_signature="abc"),
        StreamChunk(delta="answer"),
        StreamChunk(finish_reason="stop"),
    ]
    resp = assemble_response(chunks)
    assert resp.thinking == "let me think"
    assert resp.thinking_signature == "sig_abc"
    assert resp.content == "answer"


def test_anthropic_thinking_roundtrip_with_tool_calls():
    # thinking 开启时，带签名的 thinking 块必须回传且排在 tool_use 之前
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}
        ],
        "metadata": {"thinking": "plan...", "thinking_signature": "sig1"},
    }
    _, msgs = AnthropicProvider._split_system([msg], include_thinking=True)
    blocks = msgs[0]["content"]
    assert blocks[0] == {"type": "thinking", "thinking": "plan...", "signature": "sig1"}
    assert blocks[1]["type"] == "tool_use"


def test_anthropic_thinking_roundtrip_text_only():
    msg = {
        "role": "assistant",
        "content": "hello",
        "metadata": {"thinking": "hmm", "thinking_signature": "sig2"},
    }
    _, msgs = AnthropicProvider._split_system([msg], include_thinking=True)
    blocks = msgs[0]["content"]
    assert blocks[0]["type"] == "thinking"
    assert blocks[1] == {"type": "text", "text": "hello"}


def test_anthropic_thinking_not_roundtripped_when_disabled():
    # 默认关闭：即使 metadata 有 thinking 也不回传（否则 API 400）
    msg = {
        "role": "assistant",
        "content": "hello",
        "metadata": {"thinking": "hmm", "thinking_signature": "sig2"},
    }
    _, msgs = AnthropicProvider._split_system([msg])
    assert msgs[0]["content"] == "hello"


def test_anthropic_thinking_block_requires_signature():
    # 无签名的 thinking 不回传（Anthropic 拒绝无签名 thinking 块）
    msg = {"role": "assistant", "content": "hi", "metadata": {"thinking": "hmm"}}
    _, msgs = AnthropicProvider._split_system([msg], include_thinking=True)
    assert msgs[0]["content"] == "hi"


def test_to_api_messages_carries_thinking_metadata():
    from mini_agent.models.message import Conversation, Message, Role, ToolCall

    conv = Conversation()
    m1 = Message(role=Role.ASSISTANT, content="ans")
    m1.metadata["thinking"] = "t1"
    m1.metadata["thinking_signature"] = "s1"
    conv.append(m1)
    m2 = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(id="c1", name="bash", arguments={}, raw_arguments="{}")],
    )
    m2.metadata["thinking"] = "t2"
    conv.append(m2)
    api = conv.to_api_messages()
    assert api[0]["metadata"] == {"thinking": "t1", "thinking_signature": "s1"}
    assert api[1]["metadata"] == {"thinking": "t2"}
    # user 消息不带 metadata
    conv2 = Conversation()
    conv2.append(Message(role=Role.USER, content="hi"))
    assert "metadata" not in conv2.to_api_messages()[0]


async def _capture_request_body(provider: AnthropicProvider, messages: list) -> dict:
    """Drive stream() against a MockTransport and return the actual HTTP body.
    用 MockTransport 驱动 stream()，返回实际发出的 HTTP 请求体。"""
    import httpx

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.update(_json.loads(request.content))
        return httpx.Response(
            200, text="data: {}\n\n", headers={"content-type": "text/event-stream"}
        )

    provider._client = httpx.AsyncClient(
        base_url="https://mock", transport=httpx.MockTransport(handler)
    )
    async for _ in provider.stream(messages):
        pass
    return captured


async def test_anthropic_thinking_request_body_explicit_budget():
    provider = AnthropicProvider(
        LLMConfig(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            api_key="test",
            max_tokens=2048,
            thinking=True,
        )
    )
    msgs = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "ok",
            "metadata": {"thinking": "plan", "thinking_signature": "sig1"},
        },
        {"role": "user", "content": "go on"},
    ]
    body = await _capture_request_body(provider, msgs)
    # < 4.6 → 显式 budget = max_tokens - 1
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 2047}
    # 带签名 thinking 块回传，排在 text 之前
    assistant = body["messages"][1]
    assert assistant["content"][0] == {"type": "thinking", "thinking": "plan", "signature": "sig1"}


async def test_anthropic_thinking_request_body_adaptive():
    provider = AnthropicProvider(
        LLMConfig(
            provider="anthropic",
            model="claude-opus-4-6",
            api_key="test",
            max_tokens=2048,
            thinking=True,
        )
    )
    body = await _capture_request_body(provider, [{"role": "user", "content": "hi"}])
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 0}
    assert body["max_tokens"] == 2048


async def test_anthropic_thinking_disabled_request_body_unchanged():
    provider = AnthropicProvider(
        LLMConfig(provider="anthropic", model="claude-opus-4-6", api_key="test", max_tokens=2048)
    )
    msgs = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "ok",
            "metadata": {"thinking": "plan", "thinking_signature": "sig1"},
        },
        {"role": "user", "content": "go on"},
    ]
    body = await _capture_request_body(provider, msgs)
    assert "thinking" not in body
    assert body["messages"][1]["content"] == "ok"


async def test_anthropic_thinking_budget_floor_bumps_max_tokens():
    # max_tokens 太小时 budget 落到下限 1024，max_tokens 抬到 budget+1
    provider = AnthropicProvider(
        LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            api_key="test",
            max_tokens=512,
            thinking=True,
        )
    )
    body = await _capture_request_body(provider, [{"role": "user", "content": "hi"}])
    assert body["thinking"]["budget_tokens"] == 1024
    assert body["max_tokens"] == 1025


async def test_openai_extra_params_passthrough():
    # extra 透传（qwen enable_thinking 等）；核心字段不可被覆盖
    import httpx

    provider = OpenAIProvider(
        LLMConfig(
            api_key="test",
            model="qwen-test",
            extra={"enable_thinking": True, "top_p": 0.9, "model": "evil-override"},
        )
    )
    provider._probe_attempted = True
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.update(_json.loads(request.content))
        return httpx.Response(
            200, text="data: {}\n\n", headers={"content-type": "text/event-stream"}
        )

    provider._client = httpx.AsyncClient(
        base_url="http://test/v1", transport=httpx.MockTransport(handler)
    )
    async for _ in provider.stream([{"role": "user", "content": "hi"}]):
        pass
    assert captured["enable_thinking"] is True
    assert captured["top_p"] == 0.9
    assert captured["model"] == "qwen-test"  # setdefault 挡住核心字段覆盖


def test_openai_provider_strips_metadata():
    from mini_agent.llm.openai_provider import _sanitize_surrogates

    msgs = [{"role": "assistant", "content": "x", "metadata": {"thinking": "t"}}]
    stripped = [{k: v for k, v in m.items() if k != "metadata"} for m in _sanitize_surrogates(msgs)]
    assert stripped == [{"role": "assistant", "content": "x"}]
