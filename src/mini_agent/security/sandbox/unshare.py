"""Linux unshare sandbox -- fallback when bubblewrap is not installed.
Linux unshare 沙箱——bubblewrap 未安装时的后备方案。

Uses `unshare --mount` (part of util-linux, pre-installed on nearly all
Linux distros) to create a mount namespace, then remounts the root
filesystem as read-only with explicit writable bind-mounts.
使用 `unshare --mount`（util-linux 组件，几乎所有 Linux 发行版预装）
创建挂载命名空间，然后将根文件系统重挂载为只读并显式绑定挂载可写路径。"""

from __future__ import annotations

import shlex
import shutil

from mini_agent.security.sandbox import Sandbox, SandboxConfig, resolve_path


class UnshareSandbox(Sandbox):
    """Linux unshare-based sandbox (fallback for bwrap).
    基于 unshare 的 Linux 沙箱（bwrap 的后备）。"""

    def wrap(self, command: str, config: SandboxConfig) -> str:
        writable_mounts = ""
        for path in config.allow_write:
            resolved = resolve_path(path)
            writable_mounts += f"mount --bind {shlex.quote(resolved)} {shlex.quote(resolved)} && "

        deny_remounts = ""
        for path in config.deny_write:
            resolved = resolve_path(path)
            deny_remounts += (
                f"mount --bind {shlex.quote(resolved)} {shlex.quote(resolved)} && "
                f"mount -o remount,ro,bind {shlex.quote(resolved)} && "
            )

        net_flag = "" if config.network else "--net "

        inner = (
            f"mount --make-rprivate / && "
            f"mount -o remount,ro / 2>/dev/null; "
            f"{writable_mounts}"
            f"{deny_remounts}"
            f"{command}"
        )

        return f"unshare --mount --map-root-user {net_flag}sh -c {shlex.quote(inner)}"

    def available(self) -> bool:
        return shutil.which("unshare") is not None
