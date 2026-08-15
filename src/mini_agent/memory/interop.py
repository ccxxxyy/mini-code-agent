"""Memory export/import -- mewcode-compatible Markdown interop (4.6/P61).
记忆导出/导入——与 mewcode 兼容的 Markdown 互操作格式。

Export format: one .md file per entry with YAML-style frontmatter, plus a
MEMORY.md index. Import parses the same format tolerantly -- files without
frontmatter (or with foreign keys like mewcode's name/description) still
import with sensible defaults.

导出格式：每条记忆一个 .md 文件（YAML 风格前置元数据）+ MEMORY.md 索引。
导入按同一格式容错解析——无前置元数据的文件（或含 mewcode 的
name/description 等外来键）也能以合理默认值导入。
"""

from __future__ import annotations

import json
from pathlib import Path

from mini_agent.memory.persistent import MemoryEntry

INDEX_FILE = "MEMORY.md"


def export_memories(
    entries: list[MemoryEntry],
    dest_dir: Path,
    scopes: dict[str, str] | None = None,
) -> list[Path]:
    """Write one .md per entry plus a MEMORY.md index. Returns written paths.
    每条记忆写一个 .md 文件，外加 MEMORY.md 索引。返回写入的路径列表。

    `scopes` maps entry id -> storage scope ("project" | "user"). The scope is
    recorded in frontmatter so import can restore entries to the right store --
    MemoryEntry.source ("user"/"extracted") tracks WHO created it, not WHERE
    it lives, so scope must travel separately.
    `scopes` 是 条目 id -> 存储作用域（"project" | "user"）的映射。作用域记入
    前置元数据，导入时才能还原到正确的存储——MemoryEntry.source
    （"user"/"extracted"）记录的是谁创建的，不是存在哪里，所以作用域要单独携带。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    scopes = scopes or {}
    written: list[Path] = []
    index_lines = ["# Memory Index", ""]

    for entry in entries:
        path = dest_dir / f"{entry.id}.md"
        path.write_text(_render_entry(entry, scopes.get(entry.id, "")), encoding="utf-8")
        written.append(path)
        hook = entry.content.strip().splitlines()[0][:80] if entry.content.strip() else ""
        index_lines.append(f"- [{entry.id}]({entry.id}.md) — {hook}")

    index_path = dest_dir / INDEX_FILE
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    written.append(index_path)
    return written


def import_memories(src_dir: Path) -> list[tuple[MemoryEntry, str]]:
    """Parse all .md files (except MEMORY.md) into (entry, scope) pairs.
    Scope is "project"/"user" when the file recorded one, else "".
    解析目录下除 MEMORY.md 外的所有 .md 文件为 (条目, 作用域) 对。
    文件记录了作用域时为 "project"/"user"，否则为空串。"""
    results: list[tuple[MemoryEntry, str]] = []
    for path in sorted(src_dir.glob("*.md")):
        if path.name == INDEX_FILE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parsed = _parse_entry(text)
        if parsed is not None:
            results.append(parsed)
    return results


def _render_entry(entry: MemoryEntry, scope: str = "") -> str:
    lines = [
        "---",
        f"id: {entry.id}",
        f"source: {entry.source}",
    ]
    if scope:
        lines.append(f"scope: {scope}")
    lines += [
        f"created_at: {entry.created_at}",
        f"tags: {json.dumps(entry.tags, ensure_ascii=False)}",
        "---",
        "",
        entry.content.strip(),
        "",
    ]
    return "\n".join(lines)


def _parse_entry(text: str) -> tuple[MemoryEntry, str] | None:
    frontmatter, body = _split_frontmatter(text)
    content = body.strip()
    if not content:
        # Foreign formats (e.g. mewcode) may carry the gist in `description`.
        # 外来格式（如 mewcode）可能把要点放在 description 里。
        content = frontmatter.get("description", "").strip()
    if not content:
        return None
    entry = MemoryEntry(
        id=frontmatter.get("id", ""),  # empty -> auto-generated 为空则自动生成
        content=content,
        source=frontmatter.get("source", "user"),
        created_at=frontmatter.get("created_at", ""),
        tags=_parse_tags(frontmatter.get("tags", "")),
    )
    return entry, frontmatter.get("scope", "")


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split '---'-delimited frontmatter from the body. Tolerates absence.
    切分 '---' 包围的前置元数据与正文。无前置元数据时容错返回。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    fm: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return fm, "\n".join(lines[i + 1 :])
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()
        # indented lines (nested YAML like mewcode's metadata) are skipped
        # 缩进行（如 mewcode 的 metadata 嵌套 YAML）跳过
    return {}, text  # unterminated frontmatter -> treat whole file as body


def _parse_tags(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(t) for t in parsed]
    except json.JSONDecodeError:
        pass
    return [t.strip() for t in raw.strip("[]").split(",") if t.strip()]
