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


class ToolCategory(StrEnum):
    """Side-effect class of a tool, the second axis of the permission mode
    matrix (mode × category). Declared on each Tool class; unknown/plugin
    tools default to EXTERNAL (conservative: plan mode denies them).
    工具的副作用类别——权限模式矩阵的第二根轴（模式 × 类别）。每个 Tool 类
    自行声明；未声明的插件工具默认 EXTERNAL（保守：plan 模式拒绝）。

    READ     -- no user-visible side effects (file reads, searches, task
                board, messaging, interaction). 无用户可见副作用。
    WRITE    -- mutates files (write/edit/delete, skill install). 改文件。
    EXECUTE  -- runs gated sub-systems (bash via the command pipeline,
                spawn_agents via propagated permission stacks). 经受门控
                子系统执行（bash 走命令管道，spawn 走传播的权限栈）。
    EXTERNAL -- side effects outside this process (MCP tools): cannot be
                verified read-only. 进程外副作用（MCP），无法验证只读。
    """

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    EXTERNAL = "external"


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
