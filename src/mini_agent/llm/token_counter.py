"""Token counting utilities.

Uses tiktoken when available for accurate counts, falls back to a
chars/4 heuristic otherwise (tiktoken is an optional dependency).
"""

from __future__ import annotations

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


def count_message_tokens(messages: list[dict]) -> int:
    """Estimate total tokens for a list of API messages."""
    total = 0
    for msg in messages:
        # ~4 tokens per message overhead (role, separators)
        total += 4
        content = msg.get("content")
        if isinstance(content, str):
            total += count_tokens(content)
    return total
