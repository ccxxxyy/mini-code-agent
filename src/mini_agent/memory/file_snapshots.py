"""Per-turn file snapshots for operation-level undo.
每轮文件快照——支持操作级撤销（/undo 连文件一起恢复）。

Snapshots live on disk under <project>/.mini-agent/undo_snapshots/ and are
cleared when the session ends. Only the last KEEP_TURNS turns are retained;
files over MAX_SNAPSHOT_BYTES are skipped (reported for manual recovery).
快照存放在项目的 .mini-agent/undo_snapshots/ 下，会话结束时清空。
只保留最近 KEEP_TURNS 轮；超过 MAX_SNAPSHOT_BYTES 的文件跳过（提示手动恢复）。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_SNAPSHOT_BYTES = 30 * 1024 * 1024  # 30MB per file 单文件上限
KEEP_TURNS = 5  # keep snapshots for the last N turns 保留最近 N 轮


class FileSnapshotStore:
    """Stores pre-modification file contents, one directory per turn.
    按轮存储文件修改前的内容，每轮一个目录。"""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    def _turn_dir(self, turn_id: int) -> Path:
        return self._base / f"turn_{turn_id}"

    def _manifest_path(self, turn_id: int) -> Path:
        return self._turn_dir(turn_id) / "manifest.json"

    def _load_manifest(self, turn_id: int) -> list[dict]:
        path = self._manifest_path(turn_id)
        if not path.is_file():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save_manifest(self, turn_id: int, manifest: list[dict]) -> None:
        self._manifest_path(turn_id).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def begin_turn(self, turn_id: int) -> None:
        """Start a new turn: prune old snapshots beyond KEEP_TURNS.
        开始新轮：清理超出保留范围的旧快照。"""
        try:
            self._base.mkdir(parents=True, exist_ok=True)
            cutoff = turn_id - KEEP_TURNS
            for d in self._base.glob("turn_*"):
                try:
                    tid = int(d.name.split("_", 1)[1])
                except (ValueError, IndexError):
                    continue
                if tid <= cutoff:
                    shutil.rmtree(d, ignore_errors=True)
        except OSError:
            logger.debug("snapshot prune failed", exc_info=True)
            pass

    def snapshot(self, turn_id: int, file_path: Path) -> None:
        """Save the pre-modification state of file_path (first touch per turn wins).
        保存文件修改前的状态（同轮同文件只存第一次）。"""
        try:
            key = str(file_path.resolve())
        except OSError:
            key = str(file_path)
        manifest = self._load_manifest(turn_id)
        if any(entry["path"] == key for entry in manifest):
            return  # first snapshot this turn wins 本轮首次快照优先

        turn_dir = self._turn_dir(turn_id)
        files_dir = turn_dir / "files"
        try:
            files_dir.mkdir(parents=True, exist_ok=True)

            if not file_path.is_file():
                manifest.append({"path": key, "state": "missing"})
            elif file_path.stat().st_size > MAX_SNAPSHOT_BYTES:
                manifest.append({"path": key, "state": "too_large"})
            else:
                snap_name = f"{len(manifest)}.snap"
                shutil.copyfile(file_path, files_dir / snap_name)
                manifest.append({"path": key, "state": "saved", "snap": snap_name})
            self._save_manifest(turn_id, manifest)
        except OSError:
            logger.debug("snapshot save failed", exc_info=True)
            pass  # snapshot failure must never break the tool call 快照失败绝不阻断工具

    def restore_turns(self, turn_ids: list[int]) -> list[str]:
        """Restore snapshots for the given turns, newest first.
        按最新在前的顺序恢复给定轮次的快照，返回恢复报告行。"""
        report: list[str] = []
        for turn_id in sorted(turn_ids, reverse=True):
            manifest = self._load_manifest(turn_id)
            files_dir = self._turn_dir(turn_id) / "files"
            for entry in manifest:
                path = Path(entry["path"])
                try:
                    if entry["state"] == "saved":
                        shutil.copyfile(files_dir / entry["snap"], path)
                        report.append(f"{path.name} (restored)")
                    elif entry["state"] == "missing":
                        if path.is_file():
                            path.unlink()
                        report.append(f"{path.name} (deleted -- did not exist before)")
                    elif entry["state"] == "too_large":
                        report.append(f"{path.name} (NOT restored -- exceeded 30MB, manual fix)")
                except OSError as e:
                    report.append(f"{path.name} (restore failed: {e})")
            shutil.rmtree(self._turn_dir(turn_id), ignore_errors=True)
        return report

    def clear(self) -> None:
        """Remove all snapshots (session end). 清空全部快照（会话结束）。"""
        shutil.rmtree(self._base, ignore_errors=True)
