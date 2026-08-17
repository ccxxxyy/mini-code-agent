"""OpenAI-compatible LLM provider. 兼容 OpenAI 的 LLM Provider。"""

from __future__ import annotations

import asyncio
import json
import logging
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
            # kwargs override supports max_tokens recovery retries (P44)
            # kwargs 覆盖支持 max_tokens 恢复重试
            "max_tokens": kwargs.get("max_tokens") or self._config.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        # Retry rate limits / transient 5xx with backoff -- but ONLY when the
        # failure happens before any chunk was yielded (a clean re-request).
        # Mid-stream failures propagate: retrying would duplicate output.
        # 限流/瞬时 5xx 带退避重试——仅限任何 chunk 产出之前的失败（可干净重发）。
        # 流中途失败原样抛出：重试会产生重复输出。
        attempt = 0
        while True:
            async with self._client.stream("POST", "/chat/completions", json=body) as response:
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
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break

                    chunk_data = json.loads(data)
                    yield self._parse_chunk(chunk_data)
            return

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

        if "reasoning_content" in delta and delta["reasoning_content"]:
            chunk.thinking = delta["reasoning_content"]

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
        from mini_agent.llm.token_counter import count_tokens

        return count_tokens(text)

    @property
    def context_window(self) -> int:
        if self._probed_window:
            return self._probed_window
        return MODEL_CONTEXT_WINDOWS.get(self._config.model, 128_000)
