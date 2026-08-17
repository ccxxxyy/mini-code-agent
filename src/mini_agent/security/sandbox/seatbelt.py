"""macOS Seatbelt (sandbox-exec) sandbox -- SBPL deny-default profile.
macOS Seatbelt 沙箱——SBPL 默认拒绝策略。

Generates a Scheme-based sandbox profile (SBPL) that denies all by default,
then selectively allows file reads globally and file writes only to
whitelisted paths. Deny rules placed after allow rules take priority
(Seatbelt uses last-match-wins evaluation).
生成基于 Scheme 的沙箱策略（SBPL），默认拒绝全部，然后选择性地允许全局
文件读取和仅向白名单路径写入。deny 规则放在 allow 之后优先生效
（Seatbelt 使用后匹配优先）。"""

from __future__ import annotations

import shlex
from pathlib import Path

from mini_agent.security.sandbox import Sandbox, SandboxConfig, resolve_path


class SeatbeltSandbox(Sandbox):
    """Seatbelt sandbox for macOS. macOS 的 Seatbelt 沙箱。"""

    def wrap(self, command: str, config: SandboxConfig) -> str:
        profile = _build_profile(config)
        return f"/usr/bin/sandbox-exec -p {shlex.quote(profile)} bash -c {shlex.quote(command)}"

    def available(self) -> bool:
        return Path("/usr/bin/sandbox-exec").is_file()


def _build_profile(config: SandboxConfig) -> str:
    """Build an SBPL profile string. 构建 SBPL 策略字符串。"""
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow sysctl-read)",
        '(allow file-read* (subpath "/"))',
    ]
    for path in config.allow_write:
        resolved = resolve_path(path)
        lines.append(f'(allow file-write* (subpath "{resolved}"))')
    for path in config.deny_write:
        resolved = resolve_path(path)
        if Path(resolved).is_dir() or resolved.endswith("/"):
            lines.append(f'(deny file-write* (subpath "{resolved}"))')
        else:
            lines.append(f'(deny file-write* (literal "{resolved}"))')
    if config.network:
        lines.append("(allow network*)")
    else:
        lines.append("(deny network*)")
    return "\n".join(lines)
