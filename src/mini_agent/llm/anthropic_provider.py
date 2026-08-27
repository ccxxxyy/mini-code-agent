"""Anthropic Claude API provider with tool_use support.
支持 tool_use 的 Anthropic Claude API Provider。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from mini_agent.llm.base import (
    MAX_HTTP_RETRIES,
    RETRYABLE_HTTP_STATUSES,
    LLMProvider,
    StreamChunk,
    TokenUsage,
    ToolCallDelta,
    compute_retry_delay,
)
from mini_agent.models.config import LLMConfig

logger = logging.getLogger(__name__)

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-20250514": 200_000,
    "claude-haiku-4-20250514": 200_000,
    "claude-opus-4-20250514": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
}


_EPHEMERAL = {"type": "ephemeral"}

NATIVE_TOOL_SEARCH_BETA = "advanced-tool-use-2025-11-20"

# Matches family + version in e.g. "claude-opus-4-6" / "claude-sonnet-4-5-20250929";
# negative lookaheads keep date segments out of the version groups.
# 匹配模型家族+版本号；负向前瞻避免把日期段当版本号。
_ADAPTIVE_THINKING_RE = re.compile(r"claude-(?:opus|sonnet)-(\d{1,2})(?!\d)(?:-(\d{1,2})(?!\d))?")


def _supports_adaptive_thinking(model: str) -> bool:
    """Opus/Sonnet >= 4.6 accept budget_tokens=0 (model decides its own budget).
    Opus/Sonnet >= 4.6 接受 budget_tokens=0（模型自行决定思考预算）。"""
    m = _ADAPTIVE_THINKING_RE.search(model)
    if not m:
        return False
    return (int(m.group(1)), int(m.group(2) or 0)) >= (4, 6)


def _thinking_block(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Rebuild a signed thinking block from message metadata for round-trip.
    Anthropic requires assistant turns (esp. with tool_use) to carry back
    their thinking blocks with signatures when thinking is enabled.
    从消息 metadata 重建带签名的 thinking 块用于回传——thinking 开启时
    Anthropic 要求 assistant 消息（尤其含 tool_use 的）带回 thinking 块。"""
    meta = msg.get("metadata") or {}
    thinking = meta.get("thinking")
    signature = meta.get("thinking_signature")
    if thinking and signature:
        return {"type": "thinking", "thinking": thinking, "signature": signature}
    return None


def _mark_last_user_for_cache(messages: list[dict[str, Any]]) -> None:
    """Add cache_control to the last user message's content.
    给最后一条用户消息的内容加 cache_control——Anthropic 会缓存到此标记
    为止的所有前缀内容，后续请求命中缓存后输入 token 成本降约 90%。"""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = [{"type": "text", "text": content, "cache_control": _EPHEMERAL}]
        elif isinstance(content, list) and content:
            last = {**content[-1], "cache_control": _EPHEMERAL}
            msg["content"] = content[:-1] + [last]
        break


class AnthropicProvider(LLMProvider):
    """Claude API provider via Messages API with SSE streaming.
    通过 Messages API 和 SSE 流式传输的 Claude API Provider。
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._base_url = (config.base_url or "https://api.anthropic.com").rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "x-api-key": config.api_key,
                # Third-party Anthropic-compatible gateways (DashScope etc.)
                # auth via Bearer; the official API only reads x-api-key
                # 第三方 Anthropic 兼容网关（DashScope 等）用 Bearer 认证，
                # 官方 API 只读 x-api-key、忽略多余头
                "Authorization": f"Bearer {config.api_key}",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=httpx.Timeout(config.timeout, connect=10.0),
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        system_prompt, api_messages = self._split_system(
            messages, include_thinking=self._config.thinking
        )

        max_tokens = kwargs.get("max_tokens") or self._config.max_tokens
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": api_messages,
            # kwargs override supports max_tokens recovery retries
            # kwargs 覆盖支持 max_tokens 恢复重试
            "max_tokens": max_tokens,
            "stream": True,
        }
        if self._config.thinking:
            if _supports_adaptive_thinking(self._config.model):
                budget = 0
            else:
                budget = max(1024, max_tokens - 1)
                if budget >= max_tokens:
                    # Anthropic requires max_tokens > budget_tokens
                    # Anthropic 要求 max_tokens > budget_tokens
                    body["max_tokens"] = budget + 1
            body["thinking"] = {"type": "enabled", "budget_tokens": budget}
        if system_prompt:
            body["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        extra_headers: dict[str, str] = {}
        if tools:
            tools_list = self._convert_tools(tools)
            if tools_list:
                tools_list[-1] = {**tools_list[-1], "cache_control": {"type": "ephemeral"}}
            body["tools"] = tools_list
            if any(t.get("defer_loading") for t in tools_list):
                extra_headers["anthropic-beta"] = NATIVE_TOOL_SEARCH_BETA
        _mark_last_user_for_cache(api_messages)

        # Retry rate limits / transient 5xx with backoff, only before any
        # chunk was yielded (see openai_provider for rationale).
        # 限流/瞬时 5xx 带退避重试，仅限任何 chunk 产出之前（理由同 openai_provider）。
        attempt = 0
        while True:
            async with self._client.stream(
                "POST", "/v1/messages", json=body, headers=extra_headers or None
            ) as response:
                if response.status_code in RETRYABLE_HTTP_STATUSES and attempt < MAX_HTTP_RETRIES:
                    delay = compute_retry_delay(attempt, response.headers.get("retry-after"))
                    attempt += 1
                    logger.warning(
                        "LLM request got %d, retry %d/%d in %.1fs",
                        response.status_code,
                        attempt,
                        MAX_HTTP_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                async for line in response.aiter_lines():
                    # SSE allows "data:" without a trailing space (some
                    # Anthropic-compatible gateways omit it)
                    # SSE 规范允许 "data:" 后无空格（部分兼容网关会省略）
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].lstrip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    chunk = self._parse_event(event)
                    if chunk:
                        yield chunk
            return

    def _parse_event(self, event: dict[str, Any]) -> StreamChunk | None:
        event_type = event.get("type", "")

        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                return StreamChunk(delta=delta.get("text", ""))
            if delta_type == "thinking_delta":
                return StreamChunk(thinking=delta.get("thinking", ""))
            if delta_type == "signature_delta":
                return StreamChunk(thinking_signature=delta.get("signature", ""))
            if delta_type == "input_json_delta":
                index = event.get("index", 0)
                return StreamChunk(
                    tool_call_deltas=[
                        ToolCallDelta(
                            index=index,
                            arguments_delta=delta.get("partial_json", ""),
                        )
                    ]
                )

        if event_type == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                index = event.get("index", 0)
                return StreamChunk(
                    tool_call_deltas=[
                        ToolCallDelta(
                            index=index,
                            id=block.get("id"),
                            name=block.get("name"),
                        )
                    ]
                )

        if event_type == "message_delta":
            delta = event.get("delta", {})
            stop_reason = delta.get("stop_reason")
            usage = event.get("usage", {})
            finish = None
            if stop_reason == "end_turn":
                finish = "stop"
            elif stop_reason == "tool_use":
                finish = "tool_calls"
            elif stop_reason == "max_tokens":
                # Normalize to OpenAI's "length" so the recovery logic in
                # agent_loop works for both providers.
                # 归一化为 OpenAI 的 "length"，让 agent_loop 的恢复逻辑对两家通用。
                finish = "length"
            if finish or usage:
                return StreamChunk(
                    finish_reason=finish,
                    usage=TokenUsage(
                        completion_tokens=usage.get("output_tokens", 0),
                    )
                    if usage
                    else None,
                )

        if event_type == "message_start":
            msg = event.get("message", {})
            usage = msg.get("usage", {})
            if usage:
                return StreamChunk(
                    usage=TokenUsage(
                        prompt_tokens=usage.get("input_tokens", 0),
                        cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
                        cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
                    )
                )

        return None

    @staticmethod
    def _split_system(
        messages: list[dict[str, Any]],
        include_thinking: bool = False,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Extract system prompt and convert to Anthropic format.
        提取系统 prompt 并转换为 Anthropic 格式。
        """
        system = ""
        api_msgs: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")
            if role == "system":
                system = msg.get("content", "")
            elif role == "assistant" and msg.get("tool_calls"):
                content: list[dict[str, Any]] = []
                block = _thinking_block(msg) if include_thinking else None
                if block:
                    content.append(block)
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    func = tc.get("function", {})
                    try:
                        input_data = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        input_data = {}
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": func.get("name", ""),
                            "input": input_data,
                        }
                    )
                api_msgs.append({"role": "assistant", "content": content})
            elif role == "tool":
                content_blocks = msg.get("content_blocks")
                tool_content: Any = content_blocks if content_blocks else msg.get("content", "")
                api_msgs.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id", ""),
                                "content": tool_content,
                            }
                        ],
                    }
                )
            elif role == "assistant":
                block = _thinking_block(msg) if include_thinking else None
                if block:
                    blocks: list[dict[str, Any]] = [block]
                    if msg.get("content"):
                        blocks.append({"type": "text", "text": msg["content"]})
                    api_msgs.append({"role": "assistant", "content": blocks})
                else:
                    api_msgs.append({"role": "assistant", "content": msg.get("content", "")})
            else:
                api_msgs.append({"role": role, "content": msg.get("content", "")})

        return system, api_msgs

    @staticmethod
    def _convert_tools(openai_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI function calling format to Anthropic tool format.
        将 OpenAI 函数调用格式转换为 Anthropic 工具格式。
        """
        anthropic_tools = []
        for tool in openai_tools:
            func = tool.get("function", tool)
            entry: dict[str, Any] = {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            }
            if tool.get("defer_loading"):
                entry["defer_loading"] = True
            anthropic_tools.append(entry)
        return anthropic_tools

    def count_tokens(self, text: str) -> int:
        from mini_agent.llm.token_counter import count_tokens

        return count_tokens(text)

    @property
    def context_window(self) -> int:
        return MODEL_CONTEXT_WINDOWS.get(self._config.model, 200_000)
