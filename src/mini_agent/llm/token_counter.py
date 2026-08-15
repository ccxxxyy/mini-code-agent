"""Token counting utilities.
token 计数工具。

Uses tiktoken when available for accurate counts, falls back to a
chars/4 heuristic otherwise (tiktoken is an optional dependency).
可用时使用 tiktoken 进行精确计数，否则退回到“字符数/4”的启发式估算
（tiktoken 是可选依赖）。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

_encoder = None
_tiktoken_checked = False

# CJK character ranges: these tokenize at ~1 token/char (not 1 token per
# 4 chars like English), so len//4 underestimates Chinese text ~4x and
# delays compression until the context overflows.
# CJK 字符范围：约 1 token/字符（不像英文 4 字符/token），len//4 对
# 中文低估约 4 倍，导致压缩迟迟不触发直到上下文溢出。
_CJK_RANGES = (
    (0x3000, 0x303F),  # CJK punctuation 中日韩标点
    (0x3040, 0x30FF),  # Hiragana/Katakana 平假名/片假名
    (0x3400, 0x4DBF),  # CJK Extension A 扩展 A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs 基本汉字
    (0xAC00, 0xD7AF),  # Hangul syllables 谚文
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs 兼容汉字
    (0xFF00, 0xFFEF),  # Fullwidth forms 全角符号
)


def _estimate_tokens(text: str) -> int:
    """CJK-aware estimation: 1 token per CJK char + 1 per 4 other chars.
    CJK 感知估算：CJK 字符按 1 token/字，其余按 4 字符/token。"""
    cjk = sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in _CJK_RANGES))
    return max(1, cjk + (len(text) - cjk) // 4)


def _get_encoder() -> Any:
    global _encoder, _tiktoken_checked
    if not _tiktoken_checked:
        _tiktoken_checked = True
        try:
            import tiktoken

            _encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            _encoder = None
    return _encoder


@lru_cache(maxsize=4096)
def _count_cached(text: str) -> int:
    encoder = _get_encoder()
    if encoder is not None:
        return len(encoder.encode(text))
    return _estimate_tokens(text)


def count_tokens(text: str) -> int:
    """Count tokens in text. Accurate with tiktoken, estimated without.
    统计文本的 token 数。有 tiktoken 时精确，否则为估算值。

    Results are LRU-cached: system prompts and repeated tool outputs
    are recounted on every compression check, caching avoids rework.
    结果带 LRU 缓存：system prompt 和重复的工具输出在每次压缩检查时
    都会被重新计数，缓存避免重复计算。
    """
    if not text:
        return 0
    # Skip cache for very long texts (memory concern) 超长文本跳过缓存（内存考虑）
    if len(text) > 50_000:
        encoder = _get_encoder()
        if encoder is not None:
            return len(encoder.encode(text))
        return _estimate_tokens(text)
    return _count_cached(text)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to fit within *max_tokens*.
    将文本截断到 max_tokens 以内（二分搜索切割点）。"""
    if not text or max_tokens <= 0:
        return ""
    if count_tokens(text) <= max_tokens:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(text[:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    result = text[:lo]
    if lo < len(text):
        result += "\n... (truncated)"
    return result


def count_message_tokens(message: dict[str, Any]) -> int:
    """Estimate tokens for a single API message.
    估算单条 API 消息的 token 数。

    Each message has ~4 tokens overhead (role, separators).
    Tool calls add extra for the function schema.
    每条消息约有 4 个 token 的额外开销（角色、分隔符）。
    tool_calls 会因函数 schema 增加额外开销。
    """
    total = 4  # role + separators overhead 角色 + 分隔符开销
    content = message.get("content")
    if isinstance(content, str):
        total += count_tokens(content)

    tool_calls = message.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            total += 3  # tool call overhead 工具调用开销
            func = tc.get("function", {})
            if func.get("name"):
                total += count_tokens(func["name"])
            if func.get("arguments"):
                total += count_tokens(func["arguments"])

    return total


def count_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a list of API messages. 估算 API 消息列表的总 token 数。"""
    return sum(count_message_tokens(m) for m in messages) + 3  # +3 for reply priming 回复引导开销
