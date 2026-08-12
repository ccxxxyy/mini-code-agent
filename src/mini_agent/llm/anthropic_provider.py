"""Anthropic Claude API provider with tool_use support.
支持 tool_use 的 Anthropic Claude API Provider。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from mini_agent.llm.base import (
    LLMProvider,
    StreamChunk,
    TokenUsage,
    ToolCallDelta,
)
from mini_agent.models.config import LLMConfig

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-20250514": 200_000,
    "claude-haiku-4-20250514": 200_000,
    "claude-opus-4-20250514": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
}


_EPHEMERAL = {"type": "ephemeral"}


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
        system_prompt, api_messages = self._split_system(messages)

        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": api_messages,
            # kwargs override supports max_tokens recovery retries (P44)
            # kwargs 覆盖支持 max_tokens 恢复重试
            "max_tokens": kwargs.get("max_tokens") or self._config.max_tokens,
            "stream": True,
        }
        if system_prompt:
            body["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if tools:
            tools_list = self._convert_tools(tools)
            if tools_list:
                tools_list[-1] = {**tools_list[-1], "cache_control": {"type": "ephemeral"}}
            body["tools"] = tools_list
        _mark_last_user_for_cache(api_messages)

        async with self._client.stream("POST", "/v1/messages", json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue

                chunk = self._parse_event(event)
                if chunk:
                    yield chunk

    def _parse_event(self, event: dict[str, Any]) -> StreamChunk | None:
        event_type = event.get("type", "")

        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                return StreamChunk(delta=delta.get("text", ""))
            if delta_type == "thinking_delta":
                return StreamChunk(thinking=delta.get("thinking", ""))
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
                api_msgs.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id", ""),
                                "content": msg.get("content", ""),
                            }
                        ],
                    }
                )
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
            anthropic_tools.append(
                {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return anthropic_tools

    def count_tokens(self, text: str) -> int:
        from mini_agent.llm.token_counter import count_tokens

        return count_tokens(text)

    @property
    def context_window(self) -> int:
        return MODEL_CONTEXT_WINDOWS.get(self._config.model, 200_000)
