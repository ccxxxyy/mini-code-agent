"""OS-level command sandboxing -- kernel isolation for bash tool execution.
OS 级命令沙箱——bash 工具执行的内核隔离。

Linux: bubblewrap (bwrap) or unshare fallback -- user-namespace isolation, read-only rootfs
macOS: Seatbelt (sandbox-exec) -- SBPL deny-default profile
Windows: Low Integrity (admin, kernel-enforced) or attrib +R (non-admin, bypassable)
Linux：bubblewrap 或 unshare 后备——用户命名空间隔离，只读根文件系统
macOS：Seatbelt——SBPL 默认拒绝策略
Windows：Low Integrity（管理员，内核级）或 attrib +R（非管理员，可绕过）"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


def resolve_path(path: str) -> str:
    """Resolve a path to its absolute canonical form. 将路径解析为绝对规范形式。"""
    return str(Path(path).resolve())


@dataclass
class SandboxConfig:
    """What the sandbox allows / denies. 沙箱的允许/拒绝配置。"""

    allow_write: list[str] = field(default_factory=list)
    deny_write: list[str] = field(default_factory=list)
    network: bool = False


class Sandbox(ABC):
    """Abstract sandbox backend. 抽象沙箱后端。"""

    @abstractmethod
    def wrap(self, command: str, config: SandboxConfig) -> str:
        """Wrap a command string for sandboxed execution.
        将命令字符串包装为沙箱执行形式。"""
        ...

    @abstractmethod
    def available(self) -> bool:
        """True if the sandbox backend binary is installed.
        沙箱后端二进制文件是否已安装。"""
        ...


def create_sandbox() -> Sandbox | None:
    """Auto-detect and return the appropriate sandbox for the current OS.
    自动检测并返回当前操作系统对应的沙箱实现。"""
    system = platform.system()
    if system == "Linux":
        from mini_agent.security.sandbox.bwrap import BwrapSandbox

        bwrap = BwrapSandbox()
        if bwrap.available():
            return bwrap
        from mini_agent.security.sandbox.unshare import UnshareSandbox

        return UnshareSandbox()
    if system == "Darwin":
        from mini_agent.security.sandbox.seatbelt import SeatbeltSandbox

        return SeatbeltSandbox()
    if system == "Windows":
        from mini_agent.security.sandbox.windows import WindowsSandbox

        return WindowsSandbox()
    return None
