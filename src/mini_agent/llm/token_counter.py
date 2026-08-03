"""Token counting utilities.

Uses tiktoken when available for accurate counts, falls back to a
chars/4 heuristic otherwise (tiktoken is an optional dependency).
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
    """Count tokens in text. Accurate with tiktoken, estimated without."""
    encoder = _get_encoder()
    if encoder is not None:
        return len(encoder.encode(text))
    return max(1, len(text) // 4) if text else 0


def count_message_tokens(message: dict[str, Any]) -> int:
    """Estimate tokens for a single API message.

    Each message has ~4 tokens overhead (role, separators).
    Tool calls add extra for the function schema.
    """
    total = 4  # role + separators overhead
    content = message.get("content")
    if isinstance(content, str):
        total += count_tokens(content)

    tool_calls = message.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            total += 3  # tool call overhead
            func = tc.get("function", {})
            if func.get("name"):
                total += count_tokens(func["name"])
            if func.get("arguments"):
                total += count_tokens(func["arguments"])

    return total


def count_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a list of API messages."""
    return sum(count_message_tokens(m) for m in messages) + 3  # +3 for reply priming
