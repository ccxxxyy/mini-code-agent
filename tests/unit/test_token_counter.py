"""Tests for token counting accuracy (P43). token 计数精度的测试。"""

from mini_agent.llm.base import TokenUsage, assemble_response
from mini_agent.llm.token_counter import _estimate_tokens, count_tokens, truncate_to_tokens
from mini_agent.memory.context import ContextManager
from mini_agent.models.config import MemoryConfig
from mini_agent.models.message import Conversation, Message, Role

# --- truncate_to_tokens ---


def test_truncate_to_tokens_short_text():
    text = "hello world"
    assert truncate_to_tokens(text, 100) == text


def test_truncate_to_tokens_long_text():
    text = "a" * 40_000  # ~10000 tokens
    result = truncate_to_tokens(text, 100)
    assert count_tokens(result.removesuffix("\n... (truncated)")) <= 100
    assert result.endswith("... (truncated)")


def test_truncate_to_tokens_empty():
    assert truncate_to_tokens("", 100) == ""
    assert truncate_to_tokens("hello", 0) == ""


# --- CJK-aware estimation CJK 感知估算 ---


def test_estimate_english_unchanged():
    # 纯英文仍是 len//4
    text = "a" * 400
    assert _estimate_tokens(text) == 100


def test_estimate_cjk_counts_per_char():
    # 纯中文按 1 token/字，不再是 len//4（低估 4 倍）
    text = "编程" * 50  # 100 个汉字
    assert _estimate_tokens(text) == 100


def test_estimate_mixed_cjk_english():
    # 混合：40 汉字 + 400 英文字符 = 40 + 100
    text = "码" * 40 + "a" * 400
    assert _estimate_tokens(text) == 140


def test_estimate_fullwidth_and_kana():
    # 全角标点和假名也按 CJK 计
    assert _estimate_tokens("，。！") == 3
    assert _estimate_tokens("こんにちは") == 5


def test_count_tokens_cjk_no_tiktoken():
    # 无 tiktoken 环境下 count_tokens 走 CJK 感知估算
    chinese = "这是一段中文测试文本"  # 10 个汉字
    assert count_tokens(chinese) >= 10


# --- API usage anchor API usage 锚点 ---


def make_usage(prompt=1000, completion=50) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def make_conv(n_msgs=3) -> Conversation:
    conv = Conversation(system_prompt="sys")
    for i in range(n_msgs):
        conv.messages.append(Message(role=Role.USER, content=f"msg {i}"))
    return conv


def test_record_api_usage_anchors_total():
    cm = ContextManager(MemoryConfig(context_window=10_000))
    conv = make_conv(3)
    cm.record_api_usage(conv, make_usage(prompt=2000, completion=100))
    total = cm.update_total(conv)
    # 锚点覆盖全部 3 条消息：直接用 API 总量，不做估算
    assert total == 2100


def test_update_total_estimates_after_anchor():
    cm = ContextManager(MemoryConfig(context_window=10_000))
    conv = make_conv(2)
    cm.record_api_usage(conv, make_usage(prompt=2000, completion=100))
    # 锚点后追加一条新消息：API 总量 + 新消息估算
    new_msg = Message(role=Role.USER, content="x" * 400)
    conv.messages.append(new_msg)
    total = cm.update_total(conv)
    assert total == 2100 + cm.count_message(new_msg)
    assert total > 2100


def test_anchor_invalidated_by_compression():
    cm = ContextManager(MemoryConfig(context_window=10_000))
    conv = make_conv(5)
    cm.record_api_usage(conv, make_usage(prompt=50_000, completion=100))
    # 模拟压缩：历史被重排，锚点消息不在原位置
    conv.messages = [Message(role=Role.SYSTEM, content="summary", compressed=True)]
    total = cm.update_total(conv)
    # 锚点失效 → 回到全量估算，不会用过时的 50100
    assert total < 50_000


def test_anchor_ignores_zero_usage():
    cm = ContextManager(MemoryConfig(context_window=10_000))
    conv = make_conv(2)
    cm.record_api_usage(conv, TokenUsage())  # 全 0 usage（供应商没返回）
    total = cm.update_total(conv)
    # 无有效锚点 → 纯估算
    assert 0 < total < 1000


def test_anchor_computes_total_when_missing():
    # Anthropic 风格：只有 prompt/completion，无 total_tokens
    cm = ContextManager(MemoryConfig(context_window=10_000))
    conv = make_conv(2)
    usage = TokenUsage(prompt_tokens=3000, completion_tokens=200, total_tokens=0)
    cm.record_api_usage(conv, usage)
    assert cm.update_total(conv) == 3200


# --- usage field-wise merge usage 按字段合并 ---


def test_assemble_response_merges_split_usage():
    # Anthropic 把 usage 拆在两个事件：message_start 带 prompt，message_delta 带 completion
    from mini_agent.llm.base import StreamChunk

    chunks = [
        StreamChunk(usage=TokenUsage(prompt_tokens=1500, cache_read_input_tokens=800)),
        StreamChunk(delta="hello"),
        StreamChunk(finish_reason="stop", usage=TokenUsage(completion_tokens=42)),
    ]
    resp = assemble_response(chunks)
    assert resp.usage.prompt_tokens == 1500  # 不被第二个 usage 覆盖为 0
    assert resp.usage.completion_tokens == 42
    assert resp.usage.cache_read_input_tokens == 800
