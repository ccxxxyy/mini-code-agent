"""Send message tool -- cross-agent communication via the shared Mailbox.
发消息工具——通过共享 Mailbox 实现跨 Agent 通信。"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from mini_agent.core.mailbox import VALID_MESSAGE_TYPES
from mini_agent.models.message import ToolResult
from mini_agent.models.permissions import ToolCategory
from mini_agent.tools.base import Tool, ToolContext


class SendMessageParams(BaseModel):
    """Pydantic model for send_message parameters. Auto-generates ToolSchema."""

    to: str = Field(
        description=(
            "Recipient: an agent name, an agent id, 'main' (the orchestrator), "
            "or '*' to broadcast to all other agents"
        )
    )
    message: str = Field(description="Message content to deliver")
    type: str = Field(
        default="text",
        description=(
            "'text' (default), 'request' (you expect a reply; a request_id is "
            "auto-assigned and returned), or 'response' (answering a request; "
            "must include its request_id)"
        ),
    )
    request_id: str = Field(
        default="",
        description="For type='response': the request_id you are answering",
    )
    approve: bool | None = Field(
        default=None,
        description="Optional verdict for a response (true=approve, false=reject)",
    )


class SendMessageTool(Tool):
    """Lets an agent send a message to another agent's inbox.
    允许 Agent 向其他 Agent 的收件箱发送消息。"""

    _name = "send_message"

    category = ToolCategory.READ
    _description = (
        "Send a message to another agent by name or id ('main' is the "
        "orchestrator, '*' broadcasts to all). The recipient sees it at the "
        "start of their next think round. Supports a structured protocol: "
        "type='request' expects a reply (request_id auto-assigned), "
        "type='response' answers one (pass the request_id, optionally approve). "
        "Use this to share findings, coordinate work, or report progress mid-task."
    )
    params_model = SendMessageParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.mailbox is None:
            return self.error_result("", "send_message is not available: no mailbox configured")

        to: str = kwargs["to"]
        message: str = kwargs["message"]
        msg_type: str = kwargs.get("type") or "text"
        request_id: str = kwargs.get("request_id") or ""
        approve: bool | None = kwargs.get("approve")

        if not message.strip():
            return self.error_result("", "Message content is empty")
        if msg_type not in VALID_MESSAGE_TYPES:
            valid = ", ".join(sorted(VALID_MESSAGE_TYPES))
            return self.error_result("", f"Invalid type '{msg_type}'. Must be one of: {valid}")
        if msg_type == "response" and not request_id:
            return self.error_result(
                "", "type='response' requires the 'request_id' of the request you are answering"
            )
        if msg_type == "request" and not request_id:
            request_id = uuid.uuid4().hex[:8]

        suffix = f" (request_id={request_id})" if request_id else ""

        if to == "*":
            recipients = ctx.mailbox.broadcast(
                sender=ctx.agent_id,
                content=message,
                type=msg_type,
                request_id=request_id,
                approve=approve,
            )
            if not recipients:
                return self.error_result("", "Broadcast failed: no other agents are registered")
            return ToolResult(
                call_id="",
                name="send_message",
                output=f"Message broadcast to {len(recipients)} agent(s): "
                + ", ".join(recipients)
                + suffix,
            )

        delivered = ctx.mailbox.send(
            sender=ctx.agent_id,
            recipient=to,
            content=message,
            type=msg_type,
            request_id=request_id,
            approve=approve,
        )
        if not delivered:
            known = ctx.mailbox.describe_peers(exclude=ctx.agent_id)
            return self.error_result("", f"Unknown recipient '{to}'. Known agents: {known}")

        return ToolResult(
            call_id="",
            name="send_message",
            output=f"Message delivered to '{to}' ({len(message)} chars){suffix}",
        )
