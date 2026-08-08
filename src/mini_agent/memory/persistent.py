"""Cross-session memory -- project-level and user-level persistent storage.
跨 session 记忆——项目级与用户级的持久化存储。"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class MemoryEntry:
    id: str = ""
    content: str = ""
    source: str = "user"  # "project" | "user" | "extracted"
    created_at: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"mem_{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


def _find_and_remove(entries: list[MemoryEntry], query: str) -> MemoryEntry | None:
    """Find an entry by ID prefix or content substring and remove it.
    按 ID 前缀或内容子串匹配，找到并移除条目。"""
    q = query.lower()
    for i, e in enumerate(entries):
        if e.id == query or e.id.startswith(query):
            return entries.pop(i)
    for i, e in enumerate(entries):
        if q in e.content.lower():
            return entries.pop(i)
    return None


class PersistentMemory:
    """Stores and retrieves long-term memory across sessions. 跨 session 存储和检索长期记忆。"""

    def __init__(
        self,
        user_memory_dir: str = "~/.mini-agent/memory",
        project_memory_file: str = ".mini-agent/memory.json",
    ) -> None:
        self._user_dir = Path(user_memory_dir).expanduser()
        self._project_file = project_memory_file

    # --- Project-level memory ---

    def _project_path(self, project_dir: Path) -> Path:
        return project_dir / self._project_file

    async def load_project_memory(self, project_dir: Path) -> list[MemoryEntry]:
        path = self._project_path(project_dir)
        return self._load_file(path)

    async def save_project_memory(self, project_dir: Path, entries: list[MemoryEntry]) -> None:
        path = self._project_path(project_dir)
        self._save_file(path, entries)

    async def add_project_memory(self, project_dir: Path, entry: MemoryEntry) -> None:
        entries = await self.load_project_memory(project_dir)
        entries.append(entry)
        await self.save_project_memory(project_dir, entries)

    async def delete_project_memory(self, project_dir: Path, query: str) -> MemoryEntry | None:
        entries = await self.load_project_memory(project_dir)
        removed = _find_and_remove(entries, query)
        if removed:
            await self.save_project_memory(project_dir, entries)
        return removed

    # --- User-level memory ---

    def _user_path(self) -> Path:
        return self._user_dir / "user_memory.json"

    async def load_user_memory(self) -> list[MemoryEntry]:
        return self._load_file(self._user_path())

    async def save_user_memory(self, entries: list[MemoryEntry]) -> None:
        self._save_file(self._user_path(), entries)

    async def add_user_memory(self, entry: MemoryEntry) -> None:
        entries = await self.load_user_memory()
        entries.append(entry)
        await self.save_user_memory(entries)

    async def delete_user_memory(self, query: str) -> MemoryEntry | None:
        entries = await self.load_user_memory()
        removed = _find_and_remove(entries, query)
        if removed:
            await self.save_user_memory(entries)
        return removed

    # --- Search ---

    async def search(self, query: str, project_dir: Path | None = None) -> list[MemoryEntry]:
        """Simple keyword search across all memory entries. 对所有记忆条目做简单的关键词搜索。"""
        results: list[MemoryEntry] = []
        query_lower = query.lower()

        user_entries = await self.load_user_memory()
        if project_dir:
            project_entries = await self.load_project_memory(project_dir)
            all_entries = project_entries + user_entries
        else:
            all_entries = user_entries

        for entry in all_entries:
            if query_lower in entry.content.lower():
                results.append(entry)
            elif any(query_lower in tag.lower() for tag in entry.tags):
                results.append(entry)

        return results

    # --- File I/O ---

    @staticmethod
    def _load_file(path: Path) -> list[MemoryEntry]:
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [
                MemoryEntry(
                    id=e.get("id", ""),
                    content=e.get("content", ""),
                    source=e.get("source", "user"),
                    created_at=e.get("created_at", ""),
                    tags=e.get("tags", []),
                )
                for e in data.get("entries", [])
            ]
        except (json.JSONDecodeError, KeyError):
            return []

    @staticmethod
    def _save_file(path: Path, entries: list[MemoryEntry]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"entries": [asdict(e) for e in entries]}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
