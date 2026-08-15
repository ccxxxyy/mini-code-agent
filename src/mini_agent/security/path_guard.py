"""Path restriction enforcement. 路径访问限制的强制执行。"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from mini_agent.models.config import SecurityConfig, ToolConfig
from mini_agent.models.permissions import PermissionLevel

SENSITIVE_FILE_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    "credentials*",
    "*secret*",
    "*.p12",
    "*.pfx",
]

# .env.example is a template, not a secret
SENSITIVE_EXCEPTIONS = [".env.example", ".env.sample", ".env.template"]


def _result_cache_root() -> Path:
    """The agent's own spill cache: oversized tool results land here and the
    placeholder text invites the LLM to read them back -- prompting for
    permission on every read-back defeats the mechanism. Computed per call:
    Path.home() is patched in tests.
    Agent 自己的溢写缓存：超大工具结果落在这里，占位文案会引导 LLM 读回——
    每次读回都弹权限框会废掉这个机制。每次调用时计算——测试会替换 Path.home()。"""
    return Path.home() / ".mini-agent" / "cache" / "results"


class PathGuard:
    """Restricts file system access to allowed paths.
    将文件系统访问限制在允许的路径内。"""

    def __init__(
        self,
        tool_config: ToolConfig,
        security_config: SecurityConfig,
        project_dir: Path,
    ) -> None:
        self._project_dir = project_dir.resolve()
        self._denied_paths = [Path(p).expanduser().resolve() for p in tool_config.denied_paths]
        self._allowed_paths = [Path(p).expanduser().resolve() for p in tool_config.allowed_paths]

    def check(self, path: Path, operation: str = "read") -> PermissionLevel:
        """Check if a path is allowed for the given operation.

        operation: 'read' | 'write'
        Order: denied dirs -> sensitive files -> project dir -> allowed paths -> ask

        检查给定操作是否允许访问该路径。
        operation: 'read' | 'write'
        顺序：拒绝目录 -> 敏感文件 -> 项目目录 -> 允许路径 -> 询问
        """
        resolved = path.expanduser().resolve()

        for denied in self._denied_paths:
            if resolved == denied or denied in resolved.parents:
                return PermissionLevel.DENY

        if self.is_sensitive_file(resolved):
            return PermissionLevel.DENY

        if resolved == self._project_dir or self._project_dir in resolved.parents:
            return PermissionLevel.ALLOW

        # Read-only auto-allow for the agent's own spill cache (writes still ask)
        # 溢写缓存只读自动放行（写入仍询问）
        if operation == "read":
            cache_root = _result_cache_root().resolve()
            if resolved == cache_root or cache_root in resolved.parents:
                return PermissionLevel.ALLOW

        for allowed in self._allowed_paths:
            if resolved == allowed or allowed in resolved.parents:
                return PermissionLevel.ALLOW

        return PermissionLevel.ASK

    @staticmethod
    def is_sensitive_file(path: Path) -> bool:
        """Check if file matches sensitive patterns (.env, credentials, keys).
        检查文件是否匹配敏感模式（.env、凭据、密钥）。"""
        name = path.name.lower()
        if name in SENSITIVE_EXCEPTIONS:
            return False
        return any(fnmatch.fnmatch(name, pat) for pat in SENSITIVE_FILE_PATTERNS)
