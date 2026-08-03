"""Token counting utilities.
token 计数工具。

Uses tiktoken when available for accurate counts, falls back to a
chars/4 heuristic otherwise (tiktoken is an optional dependency).
可用时使用 tiktoken 进行精确计数，否则退回到“字符数/4”的启发式估算
（tiktoken 是可选依赖）。
"""

from __future__ import annotations

from typing import Any

_encoder = None
_tiktoken_checked = False


def _get_encoder():
    global _encoder, _tiktoken_checked
    if not _tiktoken_checked:
        _tiktoken_checked = True
        try:
            import tiktoken

            _encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            _encoder = None
    return _encoder


def count_tokens(text: str) -> int:
    """Count tokens in text. Accurate with tiktoken, estimated without.
    统计文本的 token 数。有 tiktoken 时精确，否则为估算值。
    """
    encoder = _get_encoder()
    if encoder is not None:
        return len(encoder.encode(text))
    return max(1, len(text) // 4) if text else 0


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
