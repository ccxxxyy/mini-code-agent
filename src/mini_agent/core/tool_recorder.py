"""Toolchain recording for deterministic replay.
工具链录制——供 /replay 零 LLM 确定性重放。

An EventBus subscriber (same pattern as AuditLogger): captures tool name and
arguments on ToolCallStartEvent, confirms success on ToolCallEndEvent, and
saves the successful sequence as a replayable JSON file.
EventBus 订阅者（与 AuditLogger 同模式）：ToolCallStartEvent 捕获工具名和参数，
ToolCallEndEvent 确认成功，把成功序列存为可重放的 JSON 文件。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mini_agent.models.events import ToolCallEndEvent, ToolCallStartEvent


class ToolRecorder:
    """Records successful tool calls for later replay.
    录制成功的工具调用供之后回放。"""

    def __init__(self, recordings_dir: Path) -> None:
        self._dir = recordings_dir
        self.recording_name: str | None = None
        self._pending: dict[str, dict[str, Any]] = {}
        self._steps: list[dict[str, Any]] = []
        # True while /replay runs -- prevents re-recording the replay itself
        # /replay 期间为 True——防止回放被再次录进去
        self.suspended = False

    # --- EventBus wiring 事件总线接线 ---

    def attach(self, bus) -> None:
        bus.on(ToolCallStartEvent, self._on_start)
        bus.on(ToolCallEndEvent, self._on_end)

    def detach(self, bus) -> None:
        bus.off(ToolCallStartEvent, self._on_start)
        bus.off(ToolCallEndEvent, self._on_end)

    async def _on_start(self, event: ToolCallStartEvent) -> None:
        if self.suspended or self.recording_name is None:
            return
        self._pending[event.call_id] = {
            "tool": event.tool_name,
            "args": dict(event.arguments),
        }

    async def _on_end(self, event: ToolCallEndEvent) -> None:
        if self.suspended or self.recording_name is None:
            return
        step = self._pending.pop(event.call_id, None)
        if step is not None and not event.is_error:
            self._steps.append(step)

    # --- recording lifecycle 录制生命周期 ---

    @property
    def is_recording(self) -> bool:
        return self.recording_name is not None

    def start(self, name: str) -> None:
        self.recording_name = name
        self._pending.clear()
        self._steps.clear()

    def stop(self) -> tuple[int, Path]:
        """Stop and save. Returns (step_count, path). 停止并保存。"""
        count = len(self._steps)
        path = self.save()
        self.recording_name = None
        self._pending.clear()
        self._steps.clear()
        return count, path

    def cancel(self) -> None:
        self.recording_name = None
        self._pending.clear()
        self._steps.clear()

    def save(self) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{self.recording_name}.json"
        data = {
            "name": self.recording_name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "steps": self._steps,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    # --- stored recordings 已存录制 ---

    def list_recordings(self) -> list[dict[str, Any]]:
        if not self._dir.is_dir():
            return []
        out = []
        for f in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                out.append(
                    {
                        "name": data.get("name", f.stem),
                        "steps": len(data.get("steps", [])),
                        "created_at": data.get("created_at", ""),
                    }
                )
            except (OSError, ValueError):
                continue
        return out

    def load(self, name: str) -> dict[str, Any] | None:
        path = self._dir / f"{name}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def delete(self, name: str) -> bool:
        path = self._dir / f"{name}.json"
        if path.is_file():
            path.unlink()
            return True
        return False


def render_template(value: Any, variables: dict[str, str]) -> Any:
    """Recursively substitute {{var}} placeholders in strings.
    递归替换字符串中的 {{变量}} 占位符。

    Built-in variables (auto-provided): {{date}} -> YYYY-MM-DD,
    {{time}} -> HH:MM:SS, {{datetime}} -> full ISO timestamp.
    内置变量（自动提供）：{{date}} 日期、{{time}} 时间、{{datetime}} 完整时间戳。
    """
    if isinstance(value, str):
        for key, val in variables.items():
            value = value.replace("{{" + key + "}}", val)
        return value
    if isinstance(value, dict):
        return {k: render_template(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [render_template(v, variables) for v in value]
    return value


def builtin_variables() -> dict[str, str]:
    """Auto-provided template variables. 自动提供的模板变量。"""
    now = datetime.now()
    return {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "datetime": now.isoformat(timespec="seconds"),
    }


def find_placeholders(steps: list[dict[str, Any]]) -> set[str]:
    """Collect all {{var}} names used in a recording's steps.
    收集录制步骤中用到的全部 {{变量}} 名。"""
    import re

    names: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            names.update(re.findall(r"\{\{(\w+)\}\}", value))
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(steps)
    return names
