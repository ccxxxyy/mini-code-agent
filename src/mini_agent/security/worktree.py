"""Git worktree isolation manager. Git worktree 隔离管理器。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path


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

        return worktree_path

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
