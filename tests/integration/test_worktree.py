"""Integration tests for git worktree management (requires git).
git worktree 管理的集成测试（需要安装 git）。"""

import shutil
from pathlib import Path

import pytest

from mini_agent.security.worktree import WorktreeError, WorktreeManager

pytestmark = [
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
    pytest.mark.asyncio,
]


@pytest.fixture
async def git_repo(tmp_path: Path) -> Path:
    """Create a real git repo with an initial commit. 创建一个带初始提交的真实 git 仓库。"""
    import asyncio

    async def run(*args, cwd):
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(cwd),
        )
        await proc.wait()

    repo = tmp_path / "repo"
    repo.mkdir()
    await run("git", "init", "-b", "main", cwd=repo)
    await run("git", "config", "user.email", "test@test.local", cwd=repo)
    await run("git", "config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("# Test\n", encoding="utf-8")
    await run("git", "add", ".", cwd=repo)
    await run("git", "commit", "-m", "init", cwd=repo)
    return repo


async def test_create_and_list(git_repo):
    mgr = WorktreeManager(git_repo)
    wt_path = await mgr.create("feature-x")

    assert wt_path.is_dir()
    assert (wt_path / "README.md").is_file()

    worktrees = await mgr.list()
    branches = [w.branch for w in worktrees]
    assert "feature-x" in branches


async def test_create_duplicate_fails(git_repo):
    mgr = WorktreeManager(git_repo)
    await mgr.create("dup")
    with pytest.raises(WorktreeError):
        await mgr.create("dup")


async def test_status_clean_and_dirty(git_repo):
    mgr = WorktreeManager(git_repo)
    wt = await mgr.create("status-test")

    info = await mgr.status(wt)
    assert info.is_clean
    assert info.branch == "status-test"

    (wt / "new_file.txt").write_text("dirty", encoding="utf-8")
    info = await mgr.status(wt)
    assert not info.is_clean


async def test_remove_clean(git_repo):
    mgr = WorktreeManager(git_repo)
    wt = await mgr.create("removeme")
    await mgr.remove(wt)
    assert not wt.exists()


async def test_remove_dirty_refuses(git_repo):
    mgr = WorktreeManager(git_repo)
    wt = await mgr.create("dirty-wt")
    (wt / "uncommitted.txt").write_text("data", encoding="utf-8")

    with pytest.raises(WorktreeError, match="uncommitted"):
        await mgr.remove(wt)

    # Force works 使用 force 则可以删除
    await mgr.remove(wt, force=True)
    assert not wt.exists()


async def test_merge_back(git_repo):
    import asyncio

    async def run(*args, cwd):
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(cwd),
        )
        await proc.wait()

    mgr = WorktreeManager(git_repo)
    wt = await mgr.create("feature-merge")

    # Make a commit in the worktree 在 worktree 中创建一次提交
    (wt / "feature.txt").write_text("new feature", encoding="utf-8")
    await run("git", "add", ".", cwd=wt)
    await run("git", "commit", "-m", "add feature", cwd=wt)

    result = await mgr.merge_back("feature-merge")
    assert result.success
    assert (git_repo / "feature.txt").is_file()


# --- P54: lifecycle enhancements ---


async def test_create_symlinks_dependency_dirs(git_repo):
    venv = git_repo / ".venv"
    venv.mkdir()
    (venv / "marker.txt").write_text("deps", encoding="utf-8")

    mgr = WorktreeManager(git_repo)
    wt = await mgr.create("with-deps")

    linked = wt / ".venv"
    if not linked.exists():
        pytest.skip("symlink not permitted (Windows without developer mode)")
    assert (linked / "marker.txt").is_file()


async def test_has_uncommitted_changes(git_repo):
    mgr = WorktreeManager(git_repo)
    wt = await mgr.create("check-changes")

    assert not await mgr.has_uncommitted_changes(wt)
    (wt / "dirty.txt").write_text("x", encoding="utf-8")
    assert await mgr.has_uncommitted_changes(wt)


async def test_cleanup_stale_removes_old_clean(git_repo):
    import os
    import time

    mgr = WorktreeManager(git_repo)
    wt = await mgr.create("old-clean")

    old = time.time() - 30 * 86400
    os.utime(wt, (old, old))

    removed = await mgr.cleanup_stale(max_age_days=7)
    assert str(wt) in removed
    assert not wt.exists()


async def test_cleanup_stale_keeps_dirty(git_repo):
    import os
    import time

    mgr = WorktreeManager(git_repo)
    wt = await mgr.create("old-dirty")
    (wt / "uncommitted.txt").write_text("keep me", encoding="utf-8")

    old = time.time() - 30 * 86400
    os.utime(wt, (old, old))

    removed = await mgr.cleanup_stale(max_age_days=7)
    assert removed == []
    assert wt.exists()


async def test_cleanup_stale_keeps_recent(git_repo):
    mgr = WorktreeManager(git_repo)
    wt = await mgr.create("fresh")

    removed = await mgr.cleanup_stale(max_age_days=7)
    assert removed == []
    assert wt.exists()


async def test_cleanup_stale_disabled(git_repo):
    mgr = WorktreeManager(git_repo)
    await mgr.create("any")
    assert await mgr.cleanup_stale(max_age_days=0) == []
