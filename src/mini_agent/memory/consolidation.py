"""Memory consolidation -- LLM merges semantically related memories.
记忆合并——LLM 语义合并相关记忆。

Word-overlap dedup only catches surface similarity; semantically related
entries with different wording accumulate as redundancy. When entry count
exceeds the threshold, an LLM identifies mergeable groups and consolidates
each into a single entry. Falls back silently to no-op on any failure.
词重叠去重只能捕捉表面相似性；用词不同但语义相关的条目会冗余累积。
条目超过阈值时，LLM 识别可合并的组并各合并为一条。任何失败静默 no-op。
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mini_agent.memory.persistent import MemoryEntry, PersistentMemory

logger = logging.getLogger(__name__)

CONSOLIDATION_PROMPT = """\
You are a memory consolidator. Below is a list of memory entries. Identify
groups of entries that are semantically related and can be merged into one.
Output ONLY a JSON array (no markdown fences) of merge groups. Each group:
{{"merge_ids": ["id1", "id2"], "merged_content": "..."}}
Rules:
- Only merge entries that are clearly about the same topic
- merged_content must preserve ALL information from the merged entries
- A group needs at least 2 entries
- If nothing should be merged, return []

Memory entries (id: content):
{memory_list}"""


class MemoryConsolidator:
    """Merges semantically related memories via a lightweight LLM call.
    通过轻量 LLM 调用合并语义相关的记忆。"""

    def __init__(self, llm: Any = None) -> None:
        self._llm = llm

    async def consolidate(self, entries: list[MemoryEntry]) -> list[MemoryEntry] | None:
        """Merge related entries. Returns the new list, or None when nothing
        was merged (or on any failure) -- caller should no-op on None.
        合并相关条目。返回新列表；无合并或失败返回 None（调用方 no-op）。"""
        if self._llm is None or len(entries) < 2:
            return None

        memory_list = "\n".join(f"{e.id}: {e.content}" for e in entries)
        prompt = CONSOLIDATION_PROMPT.format(memory_list=memory_list)
        messages = [{"role": "user", "content": prompt}]

        try:
            from mini_agent.llm.base import complete

            response = await complete(self._llm, messages)
            groups = self._parse_groups(response.content)
        except Exception:
            logger.warning("LLM consolidation failed", exc_info=True)
            return None

        if not groups:
            return None

        by_id = {e.id: e for e in entries}
        consumed: set[str] = set()
        merged_entries: list[MemoryEntry] = []

        for group in groups:
            valid_ids = [i for i in group["merge_ids"] if i in by_id and i not in consumed]
            if len(valid_ids) < 2:
                continue
            members = [by_id[i] for i in valid_ids]
            newest = max(m.created_at for m in members)
            tags: list[str] = []
            for m in members:
                for t in m.tags:
                    if t not in tags:
                        tags.append(t)
            merged_entries.append(
                MemoryEntry(
                    content=group["merged_content"],
                    source="extracted",
                    created_at=newest,
                    tags=tags,
                )
            )
            consumed.update(valid_ids)

        if not merged_entries:
            return None

        result = [e for e in entries if e.id not in consumed]
        result.extend(merged_entries)
        return result

    @staticmethod
    def _parse_groups(text: str) -> list[dict[str, Any]] | None:
        """Parse the LLM's JSON array of merge groups. None on failure.
        解析 LLM 返回的合并组 JSON 数组。失败返回 None。"""
        try:
            from mini_agent.memory._utils import strip_json_fence

            clean = strip_json_fence(text)
            items = json.loads(clean)
            if not isinstance(items, list):
                return None
            groups = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                ids = item.get("merge_ids")
                content = item.get("merged_content")
                if not isinstance(ids, list) or not isinstance(content, str):
                    continue
                if not content.strip():
                    continue
                groups.append({"merge_ids": [str(i) for i in ids], "merged_content": content})
            return groups
        except (json.JSONDecodeError, ValueError, TypeError):
            return None


class ConsolidationScheduler:
    """Background consolidation cadence -- time + session-count gated (tech-notes §111).
    后台整固节律——时间 + 会话数双门槛。

    Threshold-triggered consolidation only fires when a scope exceeds
    N entries; small-but-stale memory sets never get merged. This scheduler
    runs at startup as a background task: when >= *min_hours* have passed
    AND >= *min_sessions* new sessions were active since the last run, it
    consolidates user + project memories -- invisible to the user. A lock
    file guards against concurrent instances; saves are backed up first and
    rolled back on failure.
    阈值触发的整固只在条目超阈值时发生；小而陈旧的记忆集永远合不到。
    本调度器在启动时作为后台任务运行：距上次整固 >= min_hours 且期间有
    >= min_sessions 个新会话活跃时，整固用户级 + 项目级记忆——用户无感。
    锁文件防多实例并发；保存前备份、失败回滚。"""

    STATE_FILE = "consolidation_state.json"
    LOCK_FILE = "consolidation.lock"
    # A consolidation run takes minutes at most; a crashed holder's lock
    # should not block the cadence for long (real-run: a leftover lock
    # silently gates every startup until it ages out)
    # 一次整固至多分钟级；崩溃残锁不应长时间挡住节律
    # （实测：残锁会让之后每次启动静默 gated 直到超龄）
    LOCK_MAX_AGE_SECONDS = 600.0  # stale lock takeover 过期锁接管

    def __init__(
        self,
        memory: PersistentMemory,
        session_store: Any,
        llm: Any = None,
        *,
        min_hours: float = 24.0,
        min_sessions: int = 5,
    ) -> None:
        self._memory = memory
        self._sessions = session_store
        self._consolidator = MemoryConsolidator(llm)
        self._min_hours = min_hours
        self._min_sessions = min_sessions

    # --- Public entry ---

    async def run_once(self, project_dir: Path | None = None) -> dict[str, str]:
        """Gate-check and consolidate both scopes. Returns scope -> outcome
        ("gated" / "too_few" / "no_merge" / "merged" / "rolled_back"),
        or {"lock": "held"} when another instance is consolidating.
        门槛检查并整固两个作用域。返回各作用域结果；锁被占时返回 lock held。"""
        if not self._acquire_lock():
            return {"lock": "held"}
        try:
            sessions = await self._sessions.list_sessions()
            state = self._load_state()
            outcomes = {"user": await self._run_scope("user", None, sessions, state)}
            if project_dir:
                key = f"project:{project_dir.resolve().as_posix()}"
                outcomes[key] = await self._run_scope(key, project_dir, sessions, state)
            self._save_state(state)
            return outcomes
        finally:
            self._release_lock()

    # --- Scope runner ---

    async def _run_scope(
        self,
        key: str,
        project_dir: Path | None,
        sessions: list[dict[str, Any]],
        state: dict[str, str],
    ) -> str:
        if not self._gate_passes(key, project_dir, sessions, state):
            return "gated"
        # Record the attempt even when nothing merges -- otherwise a memory
        # set with nothing mergeable would burn an LLM call every startup.
        # 无可合并也记录本次尝试——否则无可合并的记忆集每次启动都烧一次 LLM 调用。
        state[key] = datetime.now().isoformat()
        if project_dir:
            entries = await self._memory.load_project_memory(project_dir)
            path = self._memory.project_memory_path(project_dir)
        else:
            entries = await self._memory.load_user_memory()
            path = self._memory.user_memory_path()
        if len(entries) < 2:
            return "too_few"
        merged = await self._consolidator.consolidate(entries)
        if merged is None:
            return "no_merge"
        return await self._save_with_rollback(project_dir, path, merged)

    async def _save_with_rollback(
        self, project_dir: Path | None, path: Path, merged: list[MemoryEntry]
    ) -> str:
        backup: Path | None = None
        if path.is_file():
            backup = path.with_name(path.name + ".bak")
            shutil.copy2(path, backup)
        try:
            if project_dir:
                await self._memory.save_project_memory(project_dir, merged)
            else:
                await self._memory.save_user_memory(merged)
        except Exception:
            logger.warning("consolidation save failed; rolling back", exc_info=True)
            if backup is not None and backup.is_file():
                shutil.copy2(backup, path)
            return "rolled_back"
        else:
            if backup is not None:
                backup.unlink(missing_ok=True)
            return "merged"

    # --- Gates ---

    def _gate_passes(
        self,
        key: str,
        project_dir: Path | None,
        sessions: list[dict[str, Any]],
        state: dict[str, str],
    ) -> bool:
        last_run: datetime | None = None
        raw = state.get(key)
        if raw:
            try:
                last_run = datetime.fromisoformat(raw)
            except ValueError:
                last_run = None
        if last_run is not None:
            if datetime.now() - last_run < timedelta(hours=self._min_hours):
                return False
        count = 0
        for s in sessions:
            if project_dir is not None and s.get("project_dir") != str(project_dir):
                continue
            if last_run is not None:
                try:
                    if datetime.fromisoformat(s.get("last_active", "")) <= last_run:
                        continue
                except ValueError:
                    continue
            count += 1
            if count >= self._min_sessions:
                return True
        return False

    # --- State & lock files ---

    def _state_path(self) -> Path:
        return self._memory.user_dir / self.STATE_FILE

    def _load_state(self) -> dict[str, str]:
        path = self._state_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_state(self, state: dict[str, str]) -> None:
        path = self._state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            logger.warning("failed to persist consolidation state", exc_info=True)

    def _lock_path(self) -> Path:
        return self._memory.user_dir / self.LOCK_FILE

    def _acquire_lock(self) -> bool:
        lock = self._lock_path()
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
            with open(lock, "x", encoding="utf-8") as f:
                f.write(datetime.now().isoformat())
            return True
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > self.LOCK_MAX_AGE_SECONDS:
                    # Stale lock (crashed instance) -- take over 过期锁（实例崩溃）——接管
                    lock.write_text(datetime.now().isoformat(), encoding="utf-8")
                    return True
            except OSError:
                pass
            return False
        except OSError:
            return False

    def _release_lock(self) -> None:
        try:
            self._lock_path().unlink(missing_ok=True)
        except OSError:
            pass
