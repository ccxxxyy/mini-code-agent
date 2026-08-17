"""Linux bubblewrap (bwrap) sandbox -- user-namespace isolation.
Linux bubblewrap 沙箱——用户命名空间隔离。

The child process sees the entire root filesystem as read-only, with
explicit writable bind-mounts for the working directory and /tmp.
子进程看到整个根文件系统为只读，工作目录和 /tmp 通过绑定挂载显式可写。"""

from __future__ import annotations

import shlex
import shutil

from mini_agent.security.sandbox import Sandbox, SandboxConfig, resolve_path


class BwrapSandbox(Sandbox):
    """Bubblewrap sandbox for Linux. Linux 的 bubblewrap 沙箱。"""

    def wrap(self, command: str, config: SandboxConfig) -> str:
        args = [
            "bwrap",
            "--unshare-user",
            "--unshare-pid",
            "--ro-bind",
            "/",
            "/",
        ]
        for path in config.allow_write:
            resolved = resolve_path(path)
            args += ["--bind", resolved, resolved]
        for path in config.deny_write:
            resolved = resolve_path(path)
            args += ["--ro-bind", resolved, resolved]
        if not config.network:
            args.append("--unshare-net")
        args += ["--proc", "/proc", "--dev", "/dev", "--"]
        args += ["bash", "-c", command]
        return " ".join(shlex.quote(a) for a in args)

    def available(self) -> bool:
        return shutil.which("bwrap") is not None
