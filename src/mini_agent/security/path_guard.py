"""Path restriction enforcement."""

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


class PathGuard:
    """Restricts file system access to allowed paths."""

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
        """
        resolved = path.expanduser().resolve()

        for denied in self._denied_paths:
            if resolved == denied or denied in resolved.parents:
                return PermissionLevel.DENY

        if self.is_sensitive_file(resolved):
            return PermissionLevel.DENY

        if resolved == self._project_dir or self._project_dir in resolved.parents:
            return PermissionLevel.ALLOW

        for allowed in self._allowed_paths:
            if resolved == allowed or allowed in resolved.parents:
                return PermissionLevel.ALLOW

        return PermissionLevel.ASK

    @staticmethod
    def is_sensitive_file(path: Path) -> bool:
        """Check if file matches sensitive patterns (.env, credentials, keys)."""
        name = path.name.lower()
        if name in SENSITIVE_EXCEPTIONS:
            return False
        return any(fnmatch.fnmatch(name, pat) for pat in SENSITIVE_FILE_PATTERNS)
