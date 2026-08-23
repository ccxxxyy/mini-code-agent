"""Windows sandbox -- Low Integrity (admin) or no protection (non-admin).
Windows 沙箱——Low 完整性（管理员）或无文件保护（非管理员）。

Admin mode: child process runs at Low integrity via Mandatory Integrity
Control. The kernel blocks all writes to Medium objects (user files default).
Allowed paths are lowered to Low integrity so the child CAN write there.
Same mechanism as IE Protected Mode / Chrome sandbox. Kernel-enforced,
cannot be bypassed by os.chmod/attrib/shutil.rmtree.
管理员模式：子进程以 Low 完整性运行，内核阻止写入 Medium 对象（用户文件
默认值）。允许写入路径降为 Low 完整性。与 IE/Chrome 沙箱同一机制，
内核级强制，os.chmod/attrib/shutil.rmtree 均无法绕过。

Non-admin mode: NO file protection and NO startup warning -- the limitation is
documented only in config-guide (to avoid noise on every launch). An earlier
attrib +R approach was tried and removed: attrib is bypassable (a command can
clear the read-only flag) AND, being system-wide, it blocked the agent's own
writes to ~/.mini-agent (session/history/memory).
非管理员模式：无文件保护，也不打启动警告——该限制仅在 config-guide 文档
说明（避免每次启动的噪音）。曾尝试 attrib +R 但已移除：可被命令清除，且
系统级只读会阻断 agent 自身对 ~/.mini-agent（会话/历史/记忆）的写入。"""

from __future__ import annotations

import base64
import ctypes
import shutil
import sys
from pathlib import Path

from mini_agent.security.sandbox import Sandbox, SandboxConfig, resolve_path

_HELPER = Path(__file__).parent / "_low_integrity.py"


def is_admin() -> bool:
    """Check if the current process has admin privileges.
    检查当前进程是否有管理员权限。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class WindowsSandbox(Sandbox):
    """Windows sandbox -- Low Integrity (admin) or no protection (non-admin).
    Windows 沙箱——Low 完整性（管理员）或无文件保护（非管理员，不打启动警告）。"""

    def __init__(self) -> None:
        self._admin = is_admin()

    @property
    def mode(self) -> str:
        return "low_integrity" if self._admin else "no_protection"

    def wrap(self, command: str, config: SandboxConfig) -> str:
        # Admin: run at Low integrity (kernel-enforced write protection).
        # Non-admin: no file protection available -> run the command as-is
        # (limitation documented in config-guide, no startup warning).
        # 管理员：Low 完整性运行（内核级写保护）。非管理员：无文件保护，
        # 原样执行（限制在 config-guide 文档说明，不打启动警告）。
        if self._admin:
            return self._wrap_low_integrity(command, config)
        return command

    def available(self) -> bool:
        return sys.platform == "win32" and _powershell_exe() is not None

    def _wrap_low_integrity(self, command: str, config: SandboxConfig) -> str:
        """Admin mode: Low Integrity process + icacls integrity labels.
        管理员模式：Low 完整性进程 + icacls 完整性标签。"""
        allow_paths = _collect_existing_paths(config.allow_write)
        deny_paths = _collect_existing_paths(config.deny_write)
        setup: list[str] = []
        cleanup: list[str] = []

        for p in allow_paths:
            setup.append(
                f'    cmd /c \'icacls "{p}" /setintegritylevel "(OI)(CI)L" /T /C /Q\' >$null 2>&1'
            )
            cleanup.append(
                f'    cmd /c \'icacls "{p}" /setintegritylevel "(OI)(CI)M" /T /C /Q\' >$null 2>&1'
            )
        for p in deny_paths:
            setup.append(
                f'    cmd /c \'icacls "{p}" /setintegritylevel "(OI)(CI)M" /T /C /Q\' >$null 2>&1'
            )

        python = sys.executable
        helper = str(_HELPER)
        escaped = _ps_escape(command)

        return _build_ps_script(
            setup,
            cleanup,
            f'    & "{python}" "{helper}" -- {escaped}',
        )


def _build_ps_script(setup: list[str], cleanup: list[str], run_line: str) -> str:
    s = "\n".join(setup) if setup else "    # no setup"
    c = "\n".join(cleanup) if cleanup else "    # no cleanup"
    script = (
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        "try {\n"
        f"{s}\n"
        f"{run_line}\n"
        "    exit $LASTEXITCODE\n"
        "} finally {\n"
        f"{c}\n"
        "}"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    ps = _powershell_exe()
    return f"{ps} -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}"


def _powershell_exe() -> str | None:
    for name in ("pwsh", "powershell"):
        if shutil.which(name):
            return name
    return None


def _ps_escape(command: str) -> str:
    """Escape a command for embedding in a PowerShell double-quoted string.
    转义命令以嵌入 PowerShell 双引号字符串。"""
    escaped = command.replace("`", "``").replace('"', '`"').replace("$", "`$")
    return f'"{escaped}"'


def _collect_existing_paths(paths: list[str]) -> list[str]:
    out: list[str] = []
    for p in paths:
        rp = Path(resolve_path(p)).resolve()
        if rp.exists():
            out.append(str(rp))
    return out
