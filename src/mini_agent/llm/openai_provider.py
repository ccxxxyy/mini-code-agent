"""OpenAI-compatible LLM provider. 兼容 OpenAI 的 LLM Provider。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from mini_agent.llm.base import (
    LLMProvider,
    LLMResponse,
    StreamChunk,
    TokenUsage,
    ToolCallDelta,
)
from mini_agent.models.config import LLMConfig
from mini_agent.models.message import ToolCall

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
}


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider (GPT, local servers, Azure, etc.).
    兼容 OpenAI 的 Provider（GPT、本地服务、Azure 等）。
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(config.timeout, connect=10.0),
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        async with self._client.stream("POST", "/chat/completions", json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break

                chunk_data = json.loads(data)
                yield self._parse_chunk(chunk_data)

    def _parse_chunk(self, data: dict[str, Any]) -> StreamChunk:
        chunk = StreamChunk()

        if "usage" in data and data["usage"]:
            u = data["usage"]
            chunk.usage = TokenUsage(
                prompt_tokens=u.get("prompt_tokens", 0),
                completion_tokens=u.get("completion_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
            )

        choices = data.get("choices", [])
        if not choices:
            return chunk

        choice = choices[0]
        delta = choice.get("delta", {})
        chunk.finish_reason = choice.get("finish_reason")

        if "content" in delta and delta["content"]:
            chunk.delta = delta["content"]

        if "tool_calls" in delta:
            for tc_delta in delta["tool_calls"]:
                tcd = ToolCallDelta(index=tc_delta.get("index", 0))
                if "id" in tc_delta:
                    tcd.id = tc_delta["id"]
                func = tc_delta.get("function", {})
                if "name" in func:
                    tcd.name = func["name"]
                if "arguments" in func:
                    tcd.arguments_delta = func["arguments"]
                chunk.tool_call_deltas.append(tcd)

        return chunk

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return MODEL_CONTEXT_WINDOWS.get(self._config.model, 128_000)


def assemble_response(chunks: list[StreamChunk]) -> LLMResponse:
    """Assemble a list of stream chunks into a complete LLMResponse.
    将 stream chunk 列表组装为完整的 LLMResponse。
    """
    content_parts: list[str] = []
    tool_call_builders: dict[int, dict[str, Any]] = {}
    usage = TokenUsage()
    finish_reason = "stop"

    for chunk in chunks:
        if chunk.delta:
            content_parts.append(chunk.delta)
        if chunk.finish_reason:
            finish_reason = chunk.finish_reason
        if chunk.usage:
            usage = chunk.usage

        for tcd in chunk.tool_call_deltas:
            if tcd.index not in tool_call_builders:
                tool_call_builders[tcd.index] = {
                    "id": "",
                    "name": "",
                    "arguments": "",
                }
            builder = tool_call_builders[tcd.index]
            if tcd.id:
                builder["id"] = tcd.id
            if tcd.name:
                builder["name"] = tcd.name
            if tcd.arguments_delta:
                builder["arguments"] += tcd.arguments_delta

    tool_calls: list[ToolCall] = []
    for _idx in sorted(tool_call_builders):
        b = tool_call_builders[_idx]
        raw_args = b["arguments"]
        try:
            parsed = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            parsed = {}
        tool_calls.append(
            ToolCall(
                id=b["id"],
                name=b["name"],
                arguments=parsed,
                raw_arguments=raw_args,
            )
        )

    return LLMResponse(
        content="".join(content_parts),
        tool_calls=tool_calls,
        usage=usage,
        finish_reason=finish_reason,
    )
