"""Read-before-edit enforcement .
编辑前必须先读的强制机制。

Tracks which files have been read and their mtime, so edit/write tools can
refuse to modify a file that was never read or was changed externally since
the read -- preventing edits based on stale content.
记录已读文件及其 mtime，让编辑/写入工具拒绝修改"从未读过"或"读后被外部
改过"的文件——防止基于陈旧内容的编辑。
"""

from __future__ import annotations

from pathlib import Path


class FileStateCache:
    """Per-session cache of read file mtimes, enforcing read-before-edit.
    会话级已读文件 mtime 缓存，强制 read-before-edit。

    Stores {absolute_path: mtime_ns} after each successful read. edit/write
    check two gates before proceeding:
      - Gate 1: file must have been read (present in cache).
      - Gate 2: file must not have changed since the read (mtime_ns matches).
    每次成功读取后存 {绝对路径: mtime_ns}。编辑/写入前过两道门：
    ① 必须读过（在缓存中）；② 读后未被改动（mtime_ns 一致）。
    """

    def __init__(self) -> None:
        self._cache: dict[str, int] = {}

    @staticmethod
    def _key(path: Path) -> str:
        return str(path.resolve())

    def record(self, path: Path) -> None:
        """Record a file's mtime after a successful read. 读成功后记录 mtime。"""
        try:
            self._cache[self._key(path)] = path.stat().st_mtime_ns
        except OSError:
            pass

    def check(self, path: Path) -> tuple[bool, str]:
        """Check whether the file is safe to edit/write. Returns (ok, error).
        判断文件是否可安全编辑/写入。返回 (是否可以, 错误信息)。"""
        key = self._key(path)
        cached = self._cache.get(key)
        if cached is None:
            return False, (
                "File has not been read yet. Read it first before editing "
                "(read-before-edit safety)."
            )
        try:
            current = path.stat().st_mtime_ns
        except OSError:
            # File vanished or unreadable -- let the tool's own checks handle it
            # 文件消失或不可读——交给工具自身的检查处理
            return True, ""
        if current != cached:
            return False, (
                "File has been modified since it was last read. "
                "Read it again before editing (content may be stale)."
            )
        return True, ""

    def update(self, path: Path) -> None:
        """Refresh the cache entry after a successful edit/write. 编辑/写入后刷新。"""
        self.record(path)
