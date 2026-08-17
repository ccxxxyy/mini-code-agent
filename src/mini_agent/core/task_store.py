"""Persistent task system with dependency tracking (S12).
持久化任务系统——带依赖追踪（S12）。

Tasks persist to <project>/.mini-agent/tasks.json and survive restarts.
Users manage tasks via the /todo command; LLM does not touch them directly.
任务持久化到项目的 .mini-agent/tasks.json，跨重启保留。
用户通过 /todo 命令管理；LLM 不直接操作。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

MIN_PREFIX = 5


class AmbiguousTaskError(Exception):
    """Raised when a prefix matches more than one task."""

    def __init__(self, query: str, matches: list[TaskRecord]) -> None:
        self.query = query
        self.matches = matches
        ids = ", ".join(t.id[:12] for t in matches)
        super().__init__(f"Ambiguous prefix '{query}' matches: {ids}")


@dataclass
class TaskRecord:
    """A single task with optional dependency tracking.
    一条任务——可选的依赖追踪。"""

    id: str = ""
    description: str = ""
    status: str = "pending"  # pending | in_progress | completed | failed
    blocked_by: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"task_{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = datetime.now().isoformat(timespec="seconds")
        if not self.updated_at:
            self.updated_at = self.created_at


class TaskStore:
    """Manages a per-project task list on disk.
    管理项目级磁盘任务列表。"""

    def __init__(self, project_dir: Path) -> None:
        self._path = project_dir / ".mini-agent" / "tasks.json"

    def load(self) -> list[TaskRecord]:
        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [TaskRecord(**t) for t in data.get("tasks", [])]
        except (OSError, ValueError, TypeError):
            return []

    def save(self, tasks: list[TaskRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"tasks": [asdict(t) for t in tasks]}
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def add(self, task: TaskRecord) -> None:
        tasks = self.load()
        tasks.append(task)
        self.save(tasks)

    def get(self, query: str) -> TaskRecord | None:
        """Find task by ID, ID prefix, or description substring.
        按 ID、ID 前缀或描述子串查找任务。
        Raises AmbiguousTaskError when a prefix matches more than one task.
        当前缀匹配多个任务时抛出 AmbiguousTaskError。"""
        tasks = self.load()
        # Exact match first
        for t in tasks:
            if t.id == query:
                return t
        # Prefix match — collect all candidates
        candidates = [t for t in tasks if t.id.startswith(query)]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise AmbiguousTaskError(query, candidates)
        # Fallback: search by description 兜底：按描述搜索
        query_lower = query.lower()
        for t in tasks:
            if query_lower in t.description.lower():
                return t
        return None

    def _resolve_id(self, query: str) -> str | None:
        """Resolve a query (ID, prefix, or description) to a full task ID.
        将查询（ID/前缀/描述）解析为完整任务 ID。"""
        match = self.get(query)
        return match.id if match else None

    def update(self, query: str, **fields) -> TaskRecord | None:
        resolved = self._resolve_id(query)
        if not resolved:
            return None
        tasks = self.load()
        for t in tasks:
            if t.id == resolved:
                for k, v in fields.items():
                    if hasattr(t, k):
                        setattr(t, k, v)
                t.updated_at = datetime.now().isoformat(timespec="seconds")
                self.save(tasks)
                return t
        return None

    def remove(self, query: str) -> bool:
        resolved = self._resolve_id(query)
        if not resolved:
            return False
        tasks = self.load()
        tasks = [t for t in tasks if t.id != resolved]
        self.save(tasks)
        return True

    def clear_done(self) -> int:
        """Remove completed and failed tasks. 清除已完成和失败的任务。"""
        tasks = self.load()
        remaining = [t for t in tasks if t.status not in ("completed", "failed")]
        removed = len(tasks) - len(remaining)
        if removed:
            self.save(remaining)
        return removed

    def min_unique_prefix(self, task_id: str, tasks: list[TaskRecord] | None = None) -> str:
        """Return the shortest prefix of *task_id* that uniquely identifies it.
        返回能唯一标识该任务的最短 ID 前缀。"""
        if tasks is None:
            tasks = self.load()
        others = [t.id for t in tasks if t.id != task_id]
        for length in range(MIN_PREFIX, len(task_id) + 1):
            prefix = task_id[:length]
            if not any(o.startswith(prefix) for o in others):
                return prefix
        return task_id

    def find_unblocked_by(self, task_id: str) -> list[TaskRecord]:
        """Find pending tasks that were blocked only by the given task.
        查找仅被指定任务阻塞的待办任务（完成后将解除阻塞）。"""
        tasks = self.load()
        done_ids = {t.id for t in tasks if t.status in ("completed", "failed")}
        done_ids.add(task_id)
        result = []
        for t in tasks:
            if t.status not in ("pending", "in_progress") or not t.blocked_by:
                continue
            if task_id in t.blocked_by and all(b in done_ids for b in t.blocked_by):
                result.append(t)
        return result
