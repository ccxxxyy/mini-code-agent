"""Permission manager -- evaluates permission requests against rules."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from mini_agent.models.config import SecurityConfig
from mini_agent.models.permissions import (
    PermissionDecision,
    PermissionLevel,
    PermissionRequest,
    PermissionRule,
    PermissionScope,
)
from mini_agent.security.path_guard import PathGuard

# Patterns that flag a command as dangerous (confirm before running)
DANGEROUS_COMMAND_PATTERNS = [
    r"\brm\s+(-[a-z]*[rf][a-z]*\s+)",  # rm -rf / rm -r / rm -f
    r"\bsudo\b",
    r"\bchmod\s+777\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
    r"\bgit\s+push\s+.*--force",
    r"\bgit\s+reset\s+--hard",
    r"\bdel\s+/[sq]",  # Windows del /s /q
    r"\brmdir\s+/s",  # Windows rmdir /s
    r"\bformat\s+[a-z]:",  # Windows format
    r"curl[^|]*\|\s*(ba)?sh",  # curl | sh
    r"wget[^|]*\|\s*(ba)?sh",
]

# Callback to ask the user for confirmation.
# Returns True (allow once), False (deny), or "always" (allow for session).
ConfirmCallback = Callable[[str], Awaitable[bool | str]]


class PermissionManager:
    """Evaluates permission requests. Prompts user when needed."""

    def __init__(
        self,
        config: SecurityConfig,
        path_guard: PathGuard,
        confirm_callback: ConfirmCallback | None = None,
    ) -> None:
        self._config = config
        self._path_guard = path_guard
        self._confirm = confirm_callback
        self._rules: list[PermissionRule] = []
        self._session_grants: set[tuple[PermissionScope, str]] = set()
        self._load_rules_from_config(config)

    def _load_rules_from_config(self, config: SecurityConfig) -> None:
        for pattern in config.denied_commands:
            self._rules.append(
                PermissionRule(
                    scope=PermissionScope.COMMAND,
                    pattern=pattern,
                    level=PermissionLevel.DENY,
                    reason="denied by config",
                )
            )
        for pattern in config.allowed_commands:
            self._rules.append(
                PermissionRule(
                    scope=PermissionScope.COMMAND,
                    pattern=pattern,
                    level=PermissionLevel.ALLOW,
                    reason="allowed by config",
                )
            )

    def add_rule(self, rule: PermissionRule) -> None:
        self._rules.append(rule)

    def grant_session_permission(self, scope: PermissionScope, pattern: str) -> None:
        """User granted permission for the remainder of the session."""
        self._session_grants.add((scope, pattern))

    async def check(self, request: PermissionRequest) -> PermissionDecision:
        """Evaluate a permission request.

        Order: explicit DENY -> explicit ALLOW -> session grants -> default mode.
        """
        # 1. Explicit DENY rules
        for rule in self._rules:
            if rule.scope == request.scope and rule.level == PermissionLevel.DENY:
                if self._matches(rule.pattern, request.resource):
                    request.matched_rule = rule
                    return PermissionDecision.DENIED

        # 2. Explicit ALLOW rules
        for rule in self._rules:
            if rule.scope == request.scope and rule.level == PermissionLevel.ALLOW:
                if self._matches(rule.pattern, request.resource):
                    request.matched_rule = rule
                    return PermissionDecision.GRANTED

        # 3. Session grants
        for scope, pattern in self._session_grants:
            if scope == request.scope and self._matches(pattern, request.resource):
                return PermissionDecision.GRANTED

        # 4. Default mode
        mode = self._config.permission_mode
        if mode == "allow":
            return PermissionDecision.GRANTED
        if mode == "deny":
            return PermissionDecision.DENIED
        return await self._ask_user(request)

    async def check_path(self, path: Path, operation: str = "read") -> PermissionDecision:
        """Check file path access via PathGuard, then rules."""
        level = self._path_guard.check(path, operation)
        if level == PermissionLevel.DENY:
            return PermissionDecision.DENIED
        if level == PermissionLevel.ALLOW:
            return PermissionDecision.GRANTED
        request = PermissionRequest(
            scope=PermissionScope.PATH,
            resource=str(path),
            context=f"{operation} access outside project directory",
        )
        return await self.check(request)

    async def check_command(self, command: str) -> PermissionDecision:
        """Check bash command: dangerous patterns need confirmation."""
        request = PermissionRequest(
            scope=PermissionScope.COMMAND,
            resource=command,
            tool_name="bash",
        )

        # Explicit rules and session grants first
        decision = await self._check_rules_only(request)
        if decision is not None:
            return decision

        # Dangerous pattern -> always confirm (even in allow mode)
        if self.is_dangerous_command(command):
            request.context = "dangerous command detected"
            return await self._ask_user(request)

        # Normal command -> default mode
        mode = self._config.permission_mode
        if mode == "deny":
            return PermissionDecision.DENIED
        # Both "allow" and "ask" mode auto-allow normal commands;
        # only dangerous ones need confirmation
        return PermissionDecision.GRANTED

    async def _check_rules_only(self, request: PermissionRequest) -> PermissionDecision | None:
        """Check explicit rules and session grants. None = no match."""
        for rule in self._rules:
            if rule.scope == request.scope and rule.level == PermissionLevel.DENY:
                if self._matches(rule.pattern, request.resource):
                    request.matched_rule = rule
                    return PermissionDecision.DENIED
        for rule in self._rules:
            if rule.scope == request.scope and rule.level == PermissionLevel.ALLOW:
                if self._matches(rule.pattern, request.resource):
                    request.matched_rule = rule
                    return PermissionDecision.GRANTED
        for scope, pattern in self._session_grants:
            if scope == request.scope and self._matches(pattern, request.resource):
                return PermissionDecision.GRANTED
        return None

    @staticmethod
    def is_dangerous_command(command: str) -> bool:
        return any(re.search(p, command, re.IGNORECASE) for p in DANGEROUS_COMMAND_PATTERNS)

    async def _ask_user(self, request: PermissionRequest) -> PermissionDecision:
        if self._confirm is None:
            # No UI available -> deny by default (safe)
            return PermissionDecision.DENIED
        prompt = f"Allow {request.scope.value} access to: {request.resource}"
        if request.context:
            prompt += f"\n({request.context})"
        answer = await self._confirm(prompt)
        if answer == "always":
            self.grant_session_permission(request.scope, request.resource)
            return PermissionDecision.GRANTED
        return PermissionDecision.GRANTED if answer else PermissionDecision.DENIED

    @staticmethod
    def _matches(pattern: str, resource: str) -> bool:
        """Glob-style matching; 'git *' matches 'git status' but not 'github'."""
        if fnmatch.fnmatch(resource, pattern):
            return True
        # Prefix match: keep the delimiter so 'git *' -> startswith('git ')
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return bool(prefix) and resource.startswith(prefix)
        return resource == pattern
