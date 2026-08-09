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

# Field names that OpenAI-compatible servers use for context window size
# (vLLM: max_model_len, OpenRouter: context_length, Aliyun MaaS: max_input_tokens...)
# 各兼容服务返回上下文窗口大小时使用的字段名
_CONTEXT_WINDOW_KEYS = (
    "context_window",
    "context_length",
    "max_context_length",
    "max_model_len",
    "max_input_tokens",
)


def _sanitize_surrogates(value: Any) -> Any:
    """Strip lone UTF-16 surrogates that cannot be UTF-8 encoded.
    On Windows, paths/usernames decoded via surrogateescape (e.g. mintty,
    GBK filenames) can carry \\udc80-\\udcff chars -- httpx's JSON encoding
    then raises 'surrogates not allowed'. Replace them so requests never crash.
    清除无法 UTF-8 编码的孤立代理字符。Windows 上经 surrogateescape 解码的
    路径/用户名（mintty、GBK 文件名）可能携带 \\udc80-\\udcff——httpx 的
    JSON 编码会抛 'surrogates not allowed'。替换掉保证请求不崩。"""
    if isinstance(value, str):
        try:
            value.encode("utf-8")
            return value
        except UnicodeEncodeError:
            return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, dict):
        return {k: _sanitize_surrogates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_surrogates(v) for v in value]
    return value


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
        self._probed_window: int | None = None
        self._probe_attempted = False

    @staticmethod
    def _extract_context_window(data: dict[str, Any]) -> int | None:
        """Find a context window field anywhere in a /models response (recursive).
        递归查找 /models 响应中的上下文窗口字段（如阿里云 MaaS 嵌套在
        extra_info.default_envs.max_input_tokens）。"""
        for key in _CONTEXT_WINDOW_KEYS:
            value = data.get(key)
            if isinstance(value, int) and value > 0:
                return value
        for value in data.values():
            if isinstance(value, dict):
                found = OpenAIProvider._extract_context_window(value)
                if found:
                    return found
        return None

    async def prepare(self) -> None:
        await self._probe_context_window()

    async def _probe_context_window(self) -> None:
        """Query GET /models/{model} for the context window, once per instance.
        通过 GET /models/{model} 探测上下文窗口，每实例只尝试一次，失败静默回退。"""
        if self._probe_attempted:
            return
        self._probe_attempted = True
        try:
            response = await self._client.get(
                f"/models/{self._config.model}", timeout=httpx.Timeout(10.0)
            )
            response.raise_for_status()
            self._probed_window = self._extract_context_window(response.json())
        except (httpx.HTTPError, ValueError):
            pass

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        await self._probe_context_window()
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": _sanitize_surrogates(messages),
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
        if self._probed_window:
            return self._probed_window
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
            # Field-wise merge: Anthropic splits usage across two events
            # (message_start has prompt tokens, message_delta has completion)
            # -- overwriting would lose the prompt count.
            # 按字段合并：Anthropic 的 usage 分散在两个事件中（message_start
            # 带 prompt，message_delta 带 completion）——覆盖会丢掉 prompt 计数。
            u = chunk.usage
            usage = TokenUsage(
                prompt_tokens=max(usage.prompt_tokens, u.prompt_tokens),
                completion_tokens=max(usage.completion_tokens, u.completion_tokens),
                total_tokens=max(usage.total_tokens, u.total_tokens),
                cache_read_input_tokens=max(
                    usage.cache_read_input_tokens, u.cache_read_input_tokens
                ),
                cache_creation_input_tokens=max(
                    usage.cache_creation_input_tokens, u.cache_creation_input_tokens
                ),
            )

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
