"""Permission types for the security layer. 安全层的权限类型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PermissionLevel(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionScope(StrEnum):
    TOOL = "tool"
    PATH = "path"
    COMMAND = "command"


class PermissionDecision(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    PENDING = "pending"


@dataclass(frozen=True)
class PermissionRule:
    scope: PermissionScope
    pattern: str
    level: PermissionLevel
    reason: str = ""


@dataclass
class PermissionRequest:
    scope: PermissionScope
    resource: str
    tool_name: str = ""
    context: str = ""
    matched_rule: PermissionRule | None = None
