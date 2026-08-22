"""Windows sandbox -- dual mode: Low Integrity (admin) or attrib (non-admin).
Windows 沙箱——双模式：Low 完整性（管理员）或 attrib（非管理员）。

Admin mode: child process runs at Low integrity via Mandatory Integrity
Control. The kernel blocks all writes to Medium objects (user files default).
Allowed paths are lowered to Low integrity so the child CAN write there.
Same mechanism as IE Protected Mode / Chrome sandbox. Kernel-enforced,
cannot be bypassed by os.chmod/attrib/shutil.rmtree.
管理员模式：子进程以 Low 完整性运行，内核阻止写入 Medium 对象（用户文件
默认值）。允许写入路径降为 Low 完整性。与 IE/Chrome 沙箱同一机制，
内核级强制，os.chmod/attrib/shutil.rmtree 均无法绕过。

Non-admin mode: attrib +R on sensitive paths. A speed bump only -- the child
process can clear read-only flags and write anyway. A startup warning tells
the user to run as admin for real protection.
非管理员模式：对敏感路径 attrib +R。仅减速带——子进程可清除只读标志。
启动时提示用户以管理员运行以获得真正保护。"""

from __future__ import annotations

import base64
import ctypes
import shutil
import sys
from pathlib import Path

from mini_agent.security.sandbox import Sandbox, SandboxConfig, resolve_path

_HELPER = Path(__file__).parent / "_low_integrity.py"
_FIREWALL_RULE_NAME = "MiniAgentSandboxDenyNet"


def is_admin() -> bool:
    """Check if the current process has admin privileges.
    检查当前进程是否有管理员权限。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class WindowsSandbox(Sandbox):
    """Windows sandbox -- Low Integrity (admin) or attrib (non-admin).
    Windows 沙箱——Low 完整性（管理员）或 attrib（非管理员）。"""

    def __init__(self) -> None:
        self._admin = is_admin()

    @property
    def mode(self) -> str:
        return "low_integrity" if self._admin else "attrib"

    def wrap(self, command: str, config: SandboxConfig) -> str:
        if self._admin:
            return self._wrap_low_integrity(command, config)
        return self._wrap_attrib(command, config)

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

        if not config.network:
            setup.append(_firewall_add())
            cleanup.append(_firewall_del())

        python = sys.executable
        helper = str(_HELPER)
        escaped = _ps_escape(command)

        return _build_ps_script(
            setup,
            cleanup,
            f'    & "{python}" "{helper}" -- {escaped}',
        )

    def _wrap_attrib(self, command: str, config: SandboxConfig) -> str:
        """Non-admin mode: attrib +R on sensitive paths.
        非管理员模式：敏感路径 attrib +R。"""
        deny_paths = _collect_deny_paths(config)
        needs_net = not config.network
        if not deny_paths and not needs_net:
            return command

        setup: list[str] = []
        cleanup: list[str] = []

        for p in deny_paths:
            setup.append(f'    attrib +R /S /D "{p}\\*" >$null 2>&1')
            setup.append(f'    attrib +R "{p}" >$null 2>&1')
            cleanup.append(f'    attrib -R /S /D "{p}\\*" >$null 2>&1')
            cleanup.append(f'    attrib -R "{p}" >$null 2>&1')

        if needs_net:
            setup.append(_firewall_add())
            cleanup.append(_firewall_del())

        return _build_ps_script(
            setup,
            cleanup,
            f"    cmd /c {_ps_escape(command)}",
        )

    def startup_warning(self) -> str | None:
        """Return a warning if running without admin. None if admin.
        非管理员时返回警告。管理员时返回 None。"""
        if self._admin:
            return None
        return (
            "[sandbox] Running without admin -- sandbox uses attrib (bypassable). "
            "Run as administrator for kernel-level Low Integrity protection."
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
    return '"' + command.replace('"', '`"') + '"'


def _firewall_add() -> str:
    return (
        f"    netsh advfirewall firewall add rule"
        f' name="{_FIREWALL_RULE_NAME}"'
        f" dir=out action=block program=$env:ComSpec"
        f" enable=yes >$null 2>&1"
    )


def _firewall_del() -> str:
    return f'    netsh advfirewall firewall delete rule name="{_FIREWALL_RULE_NAME}" >$null 2>&1'


def _collect_existing_paths(paths: list[str]) -> list[str]:
    out: list[str] = []
    for p in paths:
        rp = Path(resolve_path(p)).resolve()
        if rp.exists():
            out.append(str(rp))
    return out


def _collect_deny_paths(config: SandboxConfig) -> list[str]:
    """Attrib mode: collect paths to protect (home subdirs minus allow_write).
    Attrib 模式：收集需保护的路径（主目录子目录减去 allow_write）。"""
    allow_resolved = {Path(resolve_path(p)).resolve() for p in config.allow_write}
    deny_set: set[str] = set()

    for p in config.deny_write:
        rp = Path(resolve_path(p)).resolve()
        if not _is_under(rp, allow_resolved) and rp.exists():
            deny_set.add(str(rp))

    home = Path.home().resolve()
    try:
        for child in home.iterdir():
            if child.is_dir() and not _is_under(child, allow_resolved):
                deny_set.add(str(child))
    except PermissionError:
        pass

    return sorted(deny_set)


def _is_under(path: Path, allow_set: set[Path]) -> bool:
    for allowed in allow_set:
        try:
            path.relative_to(allowed)
            return True
        except ValueError:
            pass
        try:
            allowed.relative_to(path)
            return True
        except ValueError:
            pass
    return False
