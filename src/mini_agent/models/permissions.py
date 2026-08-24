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


class PermissionMode(StrEnum):
    """Session-level permission mode: how eagerly tool calls are approved.
    Explicit deny rules and sensitive-path denials hold in EVERY mode --
    modes only relax (or tighten) what would otherwise prompt the user.
    会话级权限模式：决定工具调用的放行积极程度。显式 deny 规则和敏感路径
    拒绝在所有模式下有效——模式只放宽（或收紧）原本要询问用户的部分。

    DEFAULT      -- current behavior: dangerous commands / out-of-project
                    paths prompt. 默认：危险命令/项目外路径询问。
    ACCEPT_EDITS -- file writes auto-approved (in AND out of project);
                    dangerous commands still prompt. 写文件免确认，
                    危险命令仍询问。
    PLAN         -- read-only: write operations denied outright.
                    只读：写操作直接拒绝。
    BYPASS       -- everything auto-approved except deny rules and
                    sensitive paths. 除 deny 规则和敏感路径外全部免确认。
    """

    DEFAULT = "default"
    ACCEPT_EDITS = "accept-edits"
    PLAN = "plan"
    BYPASS = "bypass"


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
