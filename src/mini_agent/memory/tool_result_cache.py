"""Spill oversized tool results to disk -- keep only a preview in conversation.
超大工具结果溢写磁盘——对话中只保留预览。

Root cause fix for the compression-reread inflation problem: large file
contents used to enter the conversation wholesale, trigger compression,
get summarized away, and be re-read by the LLM in a loop.
压缩-重读膨胀问题的根治：大文件内容曾整体进入对话，触发压缩后被摘要
丢弃，LLM 再重读，形成循环。

Two protection layers 两层防护:
1. Per-result threshold (maybe_spill): single results above threshold_chars
   单条阈值——单个结果超过 threshold_chars 即溢写
2. Aggregate budget (spill_batch): many results each under the threshold can
   still blow up the context together; force-spill largest-first until the
   turn's cumulative total fits the budget
   聚合预算——多个结果单条都不超阈值但合计撑爆上下文时，按大小降序
   强制溢写，直到本轮累计总量回到预算内
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

from mini_agent.models.message import ToolResult

PREVIEW_CHARS = 2_000


class ToolResultCache:
    """Spills tool outputs above a size threshold to disk files.
    把超过阈值的工具输出溢写到磁盘文件。"""

    def __init__(
        self,
        cache_dir: Path,
        threshold_chars: int = 50_000,
        aggregate_chars: int = 200_000,
    ) -> None:
        self._cache_dir = cache_dir
        self._threshold = threshold_chars
        self._aggregate = aggregate_chars

    @property
    def enabled(self) -> bool:
        return self._threshold > 0

    @property
    def _preview_chars(self) -> int:
        # Preview never exceeds the threshold (tiny thresholds in tests)
        # 预览不超过阈值（测试中可能设很小的阈值）
        return min(PREVIEW_CHARS, self._threshold)

    def is_spill_readback(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """True when a tool call reads back a file inside the spill directory.
        判断一次工具调用是否在读回溢写目录下的文件。

        Such results are exempt from spilling: re-spilling what the model
        just read back means it never sees the full content and loops
        between read-back and spill forever.
        这类结果豁免溢写——把模型刚读回的内容再溢写，模型永远看不到
        全文，会在「读回、溢写」之间死循环。"""
        if tool_name != "read_file":
            return False
        raw = arguments.get("file_path", "")
        if not isinstance(raw, str) or not raw:
            return False
        abs_path = os.path.abspath(raw)
        return abs_path.startswith(os.path.abspath(str(self._cache_dir)))

    def maybe_spill(self, result: ToolResult, force: bool = False) -> ToolResult:
        """Return the result unchanged if small; otherwise spill to disk and
        return a rebuilt result holding only a preview. With force=True the
        per-result threshold is bypassed (aggregate budget enforcement), but
        results no longer than the preview are still exempt -- spilling them
        cannot reclaim space.
        小结果原样返回；大结果写盘后重建，只保留预览。force=True 绕过
        单条阈值（聚合预算强制溢写），但不长于预览的结果仍豁免——溢写
        换不回空间。"""
        if not self.enabled or result.is_error:
            return result
        output = result.output
        if len(output) <= self._preview_chars:
            return result
        if not force and len(output) <= self._threshold:
            return result

        digest = hashlib.sha1(output.encode("utf-8", errors="replace")).hexdigest()[:12]
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_dir / f"result_{digest}.txt"
        path.write_text(output, encoding="utf-8")

        lines = output.count("\n") + 1
        preview = output[: self._preview_chars]
        spilled_output = (
            f"{preview}\n"
            f"... [output too large for conversation: {len(output):,} chars, "
            f"{lines:,} lines total. Preview above. Full content saved to "
            f"{path} -- use read_file with offset/limit on that path, or "
            f"re-run the tool with narrower parameters.]"
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

    def spill_batch(
        self,
        results: list[ToolResult],
        already_used: int = 0,
        exempt_ids: set[str] | None = None,
    ) -> list[ToolResult]:
        """Aggregate budget: when this batch would push the turn's cumulative
        tool-result chars over the budget, force-spill the largest results
        first until it fits (or nothing spillable remains).
        聚合预算：本批结果会使本轮累计字符超预算时，按大小降序强制溢写，
        直到回到预算内（或没有可溢写的结果）。

        Exempt from spilling 豁免项: error results / already-spilled results /
        spill-readback results (exempt_ids) / results no longer than the
        preview (spilling cannot reclaim space).
        """
        if not self.enabled or self._aggregate <= 0:
            return results
        exempt = exempt_ids or set()
        total = already_used + sum(len(r.output) for r in results)
        if total <= self._aggregate:
            return results

        out = list(results)
        # Largest first: fewest results touched to get back under budget
        # 先溢写最大的——回到预算内需要动的条数最少
        ranked = sorted(range(len(out)), key=lambda i: len(out[i].output), reverse=True)
        for i in ranked:
            if total <= self._aggregate:
                break
            r = out[i]
            if r.call_id in exempt or r.is_error or "spilled_path" in r.metadata:
                continue
            try:
                spilled = self.maybe_spill(r, force=True)
            except OSError:
                # Disk write failed -- keep the original rather than crash
                # the OBSERVE phase 写盘失败保留原文，不炸 OBSERVE 阶段
                continue
            if spilled is r:
                continue  # too small to reclaim space 太小换不回空间
            total -= len(r.output) - len(spilled.output)
            out[i] = spilled
        return out

    def cleanup(self) -> None:
        """Remove the entire cache directory. 删除整个缓存目录。"""
        shutil.rmtree(self._cache_dir, ignore_errors=True)
