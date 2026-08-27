"""Git worktree isolation manager. Git worktree 隔离管理器。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Dependency dirs symlinked into new worktrees so agents skip reinstall
# 创建 worktree 时符号链接的依赖目录——Agent 免重装依赖
_LINK_DIRS = ("node_modules", ".venv", "vendor")


@dataclass
class WorktreeInfo:
    path: Path
    branch: str
    head_commit: str = ""
    is_clean: bool = True


@dataclass
class MergeResult:
    success: bool
    conflicts: list[str] = field(default_factory=list)
    merged_branch: str = ""
    message: str = ""


class WorktreeError(Exception):
    """Git worktree operation failed. Git worktree 操作失败。"""


async def _run_git(*args: str, cwd: Path) -> tuple[int, str, str]:
    """Run a git command, return (exit_code, stdout, stderr).
    运行 git 命令，返回 (exit_code, stdout, stderr)。"""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
    )
    stdout_b, stderr_b = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout_b.decode("utf-8", errors="replace").strip(),
        stderr_b.decode("utf-8", errors="replace").strip(),
    )


class WorktreeManager:
    """Manages git worktree creation, tracking, and cleanup.
    管理 git worktree 的创建、跟踪与清理。"""

    def __init__(self, repo_dir: Path, base_dir: str = ".mini-agent/worktrees") -> None:
        self._repo_dir = repo_dir
        self._base_dir = repo_dir / base_dir

    async def create(self, branch_name: str, base_ref: str = "HEAD") -> Path:
        """Create a new worktree on a new branch. Returns the worktree path.
        在新分支上创建一个新的 worktree。返回 worktree 路径。"""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        worktree_path = self._base_dir / branch_name

        if worktree_path.exists():
            raise WorktreeError(f"Worktree path already exists: {worktree_path}")

        code, _out, err = await _run_git(
            "worktree",
            "add",
            str(worktree_path),
            "-b",
            branch_name,
            base_ref,
            cwd=self._repo_dir,
        )
        if code != 0:
            raise WorktreeError(f"git worktree add failed: {err}")

        self._link_dependency_dirs(worktree_path)
        return worktree_path

    def _link_dependency_dirs(self, worktree_path: Path) -> None:
        """Symlink dependency dirs from the main repo into the worktree.
        把主仓库的依赖目录符号链接到 worktree——免重装依赖。
        Windows without developer mode lacks symlink permission: skip silently.
        Windows 无开发者模式时缺少符号链接权限：静默跳过。"""
        for dep in _LINK_DIRS:
            src = self._repo_dir / dep
            dst = worktree_path / dep
            if src.is_dir() and not dst.exists():
                try:
                    dst.symlink_to(src, target_is_directory=True)
                except OSError:
                    logger.debug("symlink dep failed: %s", dep, exc_info=True)
                    pass

    async def remove(self, worktree_path: Path, force: bool = False) -> None:
        """Remove a worktree. Refuses if it has uncommitted changes unless force.
        移除 worktree。若存在未提交的更改则拒绝，除非 force 为真。"""
        if not force:
            info = await self.status(worktree_path)
            if not info.is_clean:
                raise WorktreeError(
                    f"Worktree has uncommitted changes: {worktree_path}. Use force=True."
                )

        args = ["worktree", "remove", str(worktree_path)]
        if force:
            args.append("--force")
        code, _out, err = await _run_git(*args, cwd=self._repo_dir)
        if code != 0:
            raise WorktreeError(f"git worktree remove failed: {err}")

    async def list(self) -> list[WorktreeInfo]:
        """List all worktrees of the repository. 列出仓库的所有 worktree。"""
        code, out, err = await _run_git("worktree", "list", "--porcelain", cwd=self._repo_dir)
        if code != 0:
            raise WorktreeError(f"git worktree list failed: {err}")

        worktrees: list[WorktreeInfo] = []
        current_path: Path | None = None
        current_branch = ""
        current_head = ""

        for line in out.splitlines():
            if line.startswith("worktree "):
                if current_path:
                    worktrees.append(
                        WorktreeInfo(
                            path=current_path, branch=current_branch, head_commit=current_head
                        )
                    )
                current_path = Path(line[len("worktree ") :])
                current_branch = ""
                current_head = ""
            elif line.startswith("HEAD "):
                current_head = line[len("HEAD ") :]
            elif line.startswith("branch "):
                current_branch = line[len("branch ") :].replace("refs/heads/", "")

        if current_path:
            worktrees.append(
                WorktreeInfo(path=current_path, branch=current_branch, head_commit=current_head)
            )
        return worktrees

    async def status(self, worktree_path: Path) -> WorktreeInfo:
        """Get status of a specific worktree (clean or dirty).
        获取指定 worktree 的状态（干净或有改动）。"""
        code, out, _err = await _run_git("status", "--porcelain", cwd=worktree_path)
        is_clean = code == 0 and not out.strip()

        _code, branch_out, _err = await _run_git(
            "rev-parse", "--abbrev-ref", "HEAD", cwd=worktree_path
        )
        _code, head_out, _err = await _run_git("rev-parse", "HEAD", cwd=worktree_path)

        return WorktreeInfo(
            path=worktree_path,
            branch=branch_out,
            head_commit=head_out[:12],
            is_clean=is_clean,
        )

    async def has_uncommitted_changes(self, worktree_path: Path) -> bool:
        """Check whether a worktree has uncommitted changes.
        检查 worktree 是否有未提交的更改。"""
        info = await self.status(worktree_path)
        return not info.is_clean

    async def cleanup_stale(self, max_age_days: int) -> list[str]:
        """Remove worktrees older than max_age_days. Dirty ones are kept.
        清理超过 max_age_days 的过期 worktree。有未提交更改的保留。

        Returns the list of removed paths. Individual failures are skipped
        so one bad worktree cannot block the rest.
        返回已删除的路径列表。单个失败跳过，不影响其他清理。"""
        if max_age_days <= 0 or not self._base_dir.is_dir():
            return []

        cutoff = time.time() - max_age_days * 86400
        removed: list[str] = []
        for entry in self._base_dir.iterdir():
            if not entry.is_dir():
                continue
            try:
                if entry.stat().st_mtime > cutoff:
                    continue
                info = await self.status(entry)
                if not info.is_clean:
                    continue  # keep uncommitted work 保留未提交的工作
                branch = info.branch
                await self.remove(entry)
                if branch and branch != "HEAD":
                    await _run_git("branch", "-D", branch, cwd=self._repo_dir)
                removed.append(str(entry))
            except (WorktreeError, OSError):
                continue
        return removed

    async def merge_back(self, branch_name: str, target_branch: str = "") -> MergeResult:
        """Merge a worktree branch back into the target branch (default: current).
        把 worktree 分支合并回目标分支（默认：当前分支）。"""
        if target_branch:
            code, _out, err = await _run_git("checkout", target_branch, cwd=self._repo_dir)
            if code != 0:
                return MergeResult(success=False, message=f"checkout {target_branch} failed: {err}")

        code, out, err = await _run_git("merge", "--no-ff", branch_name, cwd=self._repo_dir)
        if code != 0:
            # Detect conflicts 检测冲突
            conflict_code, conflict_out, _e = await _run_git(
                "diff", "--name-only", "--diff-filter=U", cwd=self._repo_dir
            )
            conflicts = conflict_out.splitlines() if conflict_code == 0 else []
            if conflicts:
                # Abort merge to leave repo clean 中止合并以保持仓库干净
                await _run_git("merge", "--abort", cwd=self._repo_dir)
            return MergeResult(
                success=False,
                conflicts=conflicts,
                merged_branch=branch_name,
                message=err or "merge failed",
            )

        return MergeResult(success=True, merged_branch=branch_name, message=out)
