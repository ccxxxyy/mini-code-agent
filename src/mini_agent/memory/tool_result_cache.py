"""Spill oversized tool results to disk -- keep only a preview in conversation.
超大工具结果溢写磁盘——对话中只保留预览。

Root cause fix for the compression-reread inflation problem: large file
contents used to enter the conversation wholesale, trigger compression,
get summarized away, and be re-read by the LLM in a loop.
压缩-重读膨胀问题的根治：大文件内容曾整体进入对话，触发压缩后被摘要
丢弃，LLM 再重读，形成循环。"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from mini_agent.models.message import ToolResult

PREVIEW_CHARS = 500


class ToolResultCache:
    """Spills tool outputs above a size threshold to disk files.
    把超过阈值的工具输出溢写到磁盘文件。"""

    def __init__(self, cache_dir: Path, threshold_chars: int = 50_000) -> None:
        self._cache_dir = cache_dir
        self._threshold = threshold_chars

    @property
    def enabled(self) -> bool:
        return self._threshold > 0

    def maybe_spill(self, result: ToolResult) -> ToolResult:
        """Return the result unchanged if small; otherwise spill to disk and
        return a rebuilt result holding only a preview.
        小结果原样返回；大结果写盘后重建，只保留预览。"""
        if not self.enabled or result.is_error:
            return result
        output = result.output
        if len(output) <= self._threshold:
            return result

        digest = hashlib.sha1(output.encode("utf-8", errors="replace")).hexdigest()[:12]
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_dir / f"result_{digest}.txt"
        path.write_text(output, encoding="utf-8")

        lines = output.count("\n") + 1
        # Preview never exceeds the threshold (tiny thresholds in tests)
        # 预览不超过阈值（测试中可能设很小的阈值）
        preview = output[: min(PREVIEW_CHARS, self._threshold)]
        spilled_output = (
            f"{preview}\n"
            f"... [output too large for conversation: {len(output):,} chars, "
            f"{lines:,} lines total. Preview above. Re-run the tool with "
            f"offset/limit parameters to view specific sections.]"
        )
        metadata = dict(result.metadata)
        metadata["spilled_path"] = str(path)
        metadata["full_chars"] = len(output)
        return ToolResult(
            call_id=result.call_id,
            name=result.name,
            output=spilled_output,
            is_error=result.is_error,
            metadata=metadata,
        )

    def cleanup(self) -> None:
        """Remove the entire cache directory. 删除整个缓存目录。"""
        shutil.rmtree(self._cache_dir, ignore_errors=True)
