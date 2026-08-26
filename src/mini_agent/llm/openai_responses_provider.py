"""OpenAI Responses API provider (/v1/responses, for o1/o3/o4-mini etc.).
OpenAI Responses API Provider（/v1/responses，适用于 o1/o3/o4-mini 等推理模型）。

The Responses API uses typed input items instead of Chat Completions'
role-based messages, a flat tool schema format, and event-typed SSE
streaming (``event:`` + ``data:`` lines). This provider converts from
the internal Chat Completions format, parses the Responses-specific SSE
events into StreamChunk objects, and plugs into the same assemble_response
/ agent_loop pipeline as the existing providers.
Responses API 使用类型化输入项（非 Chat Completions 的角色消息格式），
扁平化工具 schema，以及事件类型化的 SSE 流式传输。本 Provider 从内部
Chat Completions 格式转换、解析 Responses 特有的 SSE 事件为 StreamChunk，
接入与现有 Provider 相同的 assemble_response / agent_loop 管道。
"""

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
from mini_agent.llm.openai_provider import _sanitize_surrogates
from mini_agent.models.config import LLMConfig

logger = logging.getLogger(__name__)


class LLMAuthenticationError(Exception):
    """API key invalid or missing. API key 无效或缺失。"""


class LLMRateLimitError(Exception):
    """Rate limited by the API. 被 API 限流。"""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMNetworkError(Exception):
    """Connection or timeout failure. 连接或超时失败。"""


MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "o1": 200_000,
    "o1-mini": 128_000,
    "o1-pro": 200_000,
    "o3": 200_000,
    "o3-mini": 200_000,
    "o4-mini": 200_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
}

_CONTEXT_WINDOW_KEYS = frozenset(
    {"context_window", "context_length", "max_context_length", "max_model_len", "max_input_tokens"}
)


class OpenAIResponsesProvider(LLMProvider):
    """OpenAI Responses API provider.
    OpenAI Responses API Provider。"""

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

    # ── context window probing 上下文窗口探测 ────────────────────

    async def prepare(self) -> None:
        await self._probe_context_window()

    async def _probe_context_window(self) -> None:
        if self._probe_attempted:
            return
        self._probe_attempted = True
        try:
            response = await self._client.get(
                f"/models/{self._config.model}", timeout=httpx.Timeout(10.0)
            )
            response.raise_for_status()
            from mini_agent.llm.openai_provider import OpenAIProvider

            self._probed_window = OpenAIProvider._extract_context_window(response.json())
        except (httpx.HTTPError, ValueError):
            pass

    @property
    def context_window(self) -> int:
        if self._probed_window:
            return self._probed_window
        return MODEL_CONTEXT_WINDOWS.get(self._config.model, 200_000)

    def count_tokens(self, text: str) -> int:
        from mini_agent.llm.token_counter import count_tokens

        return count_tokens(text)

    # ── message conversion 消息转换 ──────────────────────────────

    @staticmethod
    def _convert_to_input(
        messages: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Convert internal Chat Completions messages to Responses API
        input items. Returns (instructions, items). Handles thinking
        round-trip (reasoning items) and tool-result pairing repair.
        将内部 Chat Completions 消息转换为 Responses API 输入项。
        处理 thinking 回传（reasoning 项）和工具结果配对修复。"""
        instructions = ""
        items: list[dict[str, Any]] = []
        # Track tool call ids that have been emitted, for pairing repair
        # 跟踪已发出的 tool call id，用于配对修复
        pending_call_ids: set[str] = set()
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content") or ""
            if role == "system":
                instructions = content
            elif role == "user":
                items.append({"type": "message", "role": "user", "content": content})
            elif role == "assistant":
                # Thinking round-trip: emit reasoning item before text/tools
                # thinking 回传：在文本/工具之前发出 reasoning 项
                thinking = (msg.get("metadata") or {}).get("thinking", "")
                if thinking:
                    items.append(
                        {
                            "type": "reasoning",
                            "id": msg.get("id", ""),
                            "summary": [{"type": "summary_text", "text": thinking}],
                        }
                    )
                if content:
                    items.append({"type": "message", "role": "assistant", "content": content})
                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    call_id = tc.get("id", "")
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": call_id,
                            "name": func.get("name", ""),
                            "arguments": func.get("arguments", "{}"),
                        }
                    )
                    pending_call_ids.add(call_id)
            elif role == "tool":
                call_id = msg.get("tool_call_id", "")
                pending_call_ids.discard(call_id)
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": content,
                    }
                )
        # Tool pairing repair: emit synthetic error results for any
        # function_call that never received a result (interrupted session)
        # 工具配对修复：为未收到结果的 function_call 补合成错误结果（会话中断）
        for orphan_id in pending_call_ids:
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": orphan_id,
                    "output": "Tool execution was interrupted and did not produce a result.",
                }
            )
        return instructions, items

    # ── tool schema conversion 工具 schema 转换 ──────────────────

    @staticmethod
    def _convert_tools(openai_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Flatten Chat Completions tool format to Responses API format.
        将 Chat Completions 工具格式扁平化为 Responses API 格式。"""
        result = []
        for tool in openai_tools:
            func = tool.get("function", tool)
            result.append(
                {
                    "type": "function",
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return result

    # ── streaming 流式请求 ───────────────────────────────────────

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        await self._probe_context_window()
        instructions, input_items = self._convert_to_input(_sanitize_surrogates(messages))

        body: dict[str, Any] = {
            "model": self._config.model,
            "input": input_items,
            "stream": True,
        }
        if instructions:
            body["instructions"] = instructions
        if tools:
            body["tools"] = self._convert_tools(tools)

        # Responses API uses max_output_tokens, not max_tokens.
        # agent_loop sends max_tokens in kwargs for recovery retries (P44).
        # Responses API 用 max_output_tokens 而非 max_tokens。
        # agent_loop 重试时通过 kwargs 传 max_tokens（P44），需映射。
        max_out = kwargs.get("max_tokens") or self._config.max_tokens
        if max_out:
            body["max_output_tokens"] = max_out

        if self._config.temperature is not None:
            body["temperature"] = self._config.temperature

        # Request-side reasoning control; summary makes reasoning stream back
        # as response.reasoning_summary_text.delta events (B12)
        # 发送侧 reasoning 控制；summary 让推理以 reasoning_summary_text 事件流回
        if self._config.thinking:
            effort = self._config.extra.get("reasoning_effort", "medium")
            body["reasoning"] = {"effort": effort, "summary": "auto"}

        has_function_calls = False
        tool_calls: dict[int, dict[str, str]] = {}

        attempt = 0
        try:
            while True:
                async with self._client.stream("POST", "/responses", json=body) as response:
                    if (
                        response.status_code in RETRYABLE_HTTP_STATUSES
                        and attempt < MAX_HTTP_RETRIES
                    ):
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
                        # SSE 规范允许 "data:" 后无空格（部分兼容网关会省略）
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].lstrip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        event_type = data.get("type", "")
                        if event_type == "response.output_item.added":
                            item = data.get("item", {})
                            if item.get("type") == "function_call":
                                has_function_calls = True

                        chunk = self._parse_event(data, tool_calls, has_function_calls)
                        if chunk is not None:
                            yield chunk
                return
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code == 401:
                raise LLMAuthenticationError(str(e)) from e
            if code == 429:
                retry_after = e.response.headers.get("retry-after")
                ra = float(retry_after) if retry_after else None
                raise LLMRateLimitError(str(e), retry_after=ra) from e
            raise
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise LLMNetworkError(str(e)) from e

    # ── event parsing 事件解析 ───────────────────────────────────

    def _parse_event(
        self,
        data: dict[str, Any],
        tool_calls: dict[int, dict[str, str]],
        has_function_calls: bool,
    ) -> StreamChunk | None:
        """Map a Responses API SSE event to a StreamChunk.
        将 Responses API SSE 事件映射为 StreamChunk。"""
        event_type = data.get("type", "")

        if event_type == "response.output_text.delta":
            return StreamChunk(delta=data.get("delta", ""))

        if event_type == "response.reasoning_summary_text.delta":
            return StreamChunk(thinking=data.get("delta", ""))

        if event_type == "response.output_item.added":
            item = data.get("item", {})
            if item.get("type") == "function_call":
                output_index = data.get("output_index", 0)
                call_id = item.get("call_id", "")
                name = item.get("name", "")
                tool_calls[output_index] = {"call_id": call_id, "name": name}
                return StreamChunk(
                    tool_call_deltas=[ToolCallDelta(index=output_index, id=call_id, name=name)]
                )
            return None

        if event_type == "response.function_call_arguments.delta":
            output_index = data.get("output_index", 0)
            return StreamChunk(
                tool_call_deltas=[
                    ToolCallDelta(index=output_index, arguments_delta=data.get("delta", ""))
                ]
            )

        if event_type == "response.completed":
            resp = data.get("response", {})
            usage_data = resp.get("usage", {})
            input_tokens = usage_data.get("input_tokens", 0)
            output_tokens = usage_data.get("output_tokens", 0)
            cached_tokens = 0
            input_details = usage_data.get("input_tokens_details") or {}
            if input_details:
                cached_tokens = input_details.get("cached_tokens", 0)

            output_items = resp.get("output", [])
            has_fc = has_function_calls or any(
                item.get("type") == "function_call" for item in output_items
            )
            finish = "tool_calls" if has_fc else "stop"

            return StreamChunk(
                finish_reason=finish,
                usage=TokenUsage(
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    cache_read_input_tokens=cached_tokens,
                ),
            )

        if event_type == "response.incomplete":
            return StreamChunk(finish_reason="length")

        if event_type == "response.failed":
            error = data.get("response", {}).get("error", {})
            logger.error("Responses API error: %s", error.get("message", "unknown"))
            return None

        return None
