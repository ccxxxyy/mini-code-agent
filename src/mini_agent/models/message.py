"""Core message types for the conversation system. 对话系统的核心消息类型。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool invocation requested by the LLM. LLM 请求的一次工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Result returned after executing a tool. 执行工具后返回的结果。"""

    call_id: str
    name: str
    output: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Message:
    """A single message in a conversation. 对话中的一条消息。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    role: Role = Role.USER
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_result: ToolResult | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    token_count: int | None = None
    compressed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Conversation:
    """An ordered sequence of messages with system prompt. 带有 system prompt 的有序消息序列。"""

    system_prompt: str = ""
    messages: list[Message] = field(default_factory=list)
    total_tokens: int = 0
    # Set by Compressor after compression; persisted with the session so that
    # loading can skip archived messages and restore read-files state.
    # 压缩后由 Compressor 设置；随会话持久化，加载时跳过已归档消息并恢复已读文件状态。
    compact_boundary: dict[str, Any] | None = None

    def append(self, message: Message) -> None:
        self.messages.append(message)
        if message.token_count:
            self.total_tokens += message.token_count

    def to_api_messages(self) -> list[dict[str, Any]]:
        """Convert to the format expected by LLM APIs. 转换为 LLM API 期望的格式。"""
        result: list[dict[str, Any]] = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        for msg in self.messages:
            if msg.role == Role.ASSISTANT and msg.tool_calls:
                api_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": tc.raw_arguments or json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
                _attach_thinking(api_msg, msg)
                result.append(api_msg)
            elif msg.role == Role.TOOL and msg.tool_result:
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_result.call_id,
                        "content": msg.tool_result.output,
                    }
                )
            else:
                api_msg = {"role": msg.role.value, "content": msg.content}
                if msg.role == Role.ASSISTANT:
                    _attach_thinking(api_msg, msg)
                result.append(api_msg)
        return result


def _attach_thinking(api_msg: dict[str, Any], msg: Message) -> None:
    """Carry thinking (+ signature) in metadata for provider round-trip:
    Anthropic rebuilds signed thinking blocks, Responses API rebuilds
    reasoning items. Providers strip metadata before sending otherwise.
    thinking（含签名）放 metadata 供 Provider 回传：Anthropic 重建带签名
    thinking 块，Responses API 重建 reasoning 项，其余 Provider 发送前剥除。"""
    thinking = msg.metadata.get("thinking")
    if not thinking:
        return
    api_msg["metadata"] = {"thinking": thinking}
    signature = msg.metadata.get("thinking_signature")
    if signature:
        api_msg["metadata"]["thinking_signature"] = signature
