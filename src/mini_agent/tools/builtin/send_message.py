"""Send message tool -- cross-agent communication via the shared Mailbox.
发消息工具——通过共享 Mailbox 实现跨 Agent 通信。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext


class SendMessageParams(BaseModel):
    """Pydantic model for send_message parameters. Auto-generates ToolSchema."""

    to: str = Field(description="Recipient agent id, or 'main' for the orchestrator agent")
    message: str = Field(description="Message content to deliver")


class SendMessageTool(Tool):
    """Lets an agent send a message to another agent's inbox.
    允许 Agent 向其他 Agent 的收件箱发送消息。"""

    _name = "send_message"
    _description = (
        "Send a message to another agent ('main' is the orchestrator). "
        "The recipient sees it at the start of their next think round. "
        "Use this to share findings, coordinate work, or report progress mid-task."
    )
    params_model = SendMessageParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.mailbox is None:
            return self.error_result("", "send_message is not available: no mailbox configured")

        to: str = kwargs["to"]
        message: str = kwargs["message"]
        if not message.strip():
            return self.error_result("", "Message content is empty")

        if not ctx.mailbox.send(sender=ctx.agent_id, recipient=to, content=message):
            peers = ctx.mailbox.peers(exclude=ctx.agent_id)
            known = ", ".join(peers) if peers else "(none)"
            return self.error_result("", f"Unknown recipient '{to}'. Known agents: {known}")

        return ToolResult(
            call_id="",
            name="send_message",
            output=f"Message delivered to '{to}' ({len(message)} chars)",
        )
