"""Wait message tool -- block until a cross-agent message arrives.
等消息工具——阻塞等待跨 Agent 消息到达。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext

MAX_WAIT_SECONDS = 600.0
POLL_INTERVAL = 0.5


class WaitMessageParams(BaseModel):
    """Pydantic model for wait_message parameters. Auto-generates ToolSchema."""

    timeout_seconds: float = Field(
        default=120.0,
        description="Max seconds to wait before giving up (capped at 600)",
    )


class WaitMessageTool(Tool):
    """Blocks until a message from another agent arrives in this agent's inbox.
    阻塞直到本 Agent 收件箱收到其他 Agent 的消息。"""

    _name = "wait_message"
    _description = (
        "Wait (block) until a message from another agent arrives in your inbox, "
        "then return it. Use this when your task says to wait for information "
        "from a peer agent -- it keeps you alive while waiting, unlike finishing "
        "early. Returns immediately if messages are already waiting."
    )
    params_model = WaitMessageParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.mailbox is None:
            return self.error_result("", "wait_message is not available: no mailbox configured")

        timeout = min(float(kwargs.get("timeout_seconds", 120.0)), MAX_WAIT_SECONDS)
        deadline = time.monotonic() + timeout
        while True:
            messages = ctx.mailbox.drain(ctx.agent_id)
            if messages:
                lines = [f"[from '{m.sender}' at {m.timestamp}] {m.content}" for m in messages]
                return ToolResult(
                    call_id="",
                    name="wait_message",
                    output=f"Received {len(messages)} message(s):\n" + "\n".join(lines),
                )
            if time.monotonic() >= deadline:
                return ToolResult(
                    call_id="",
                    name="wait_message",
                    output=(
                        f"No message arrived within {timeout:.0f}s. "
                        "The sender may have finished or failed -- decide how to "
                        "proceed with the information you have."
                    ),
                )
            await asyncio.sleep(POLL_INTERVAL)
