"""Shared utilities for memory modules. 记忆模块共享工具函数。"""

from __future__ import annotations


def strip_json_fence(text: str) -> str:
    """Strip markdown code fences (```json ... ```) wrapping JSON content.
    剥离包裹 JSON 内容的 markdown 代码围栏。"""
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
    return clean
