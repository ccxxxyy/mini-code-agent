"""Tests for memory export/import interop. 记忆导出/导入互操作的测试。"""

from pathlib import Path

from mini_agent.memory.interop import export_memories, import_memories
from mini_agent.memory.persistent import MemoryEntry


def make_entries() -> list[MemoryEntry]:
    return [
        MemoryEntry(
            id="mem_aaaa1111",
            content="User prefers tabs over spaces",
            source="user",
            created_at="2026-08-15T10:00:00",
            tags=["style", "编辑器"],
        ),
        MemoryEntry(
            id="mem_bbbb2222",
            content="Project uses pytest\nwith asyncio auto mode",
            source="extracted",
            created_at="2026-08-15T11:00:00",
            tags=[],
        ),
    ]


def scopes() -> dict[str, str]:
    return {"mem_aaaa1111": "user", "mem_bbbb2222": "project"}


def test_export_creates_files_and_index(tmp_path: Path):
    paths = export_memories(make_entries(), tmp_path / "out", scopes())
    names = {p.name for p in paths}
    assert names == {"mem_aaaa1111.md", "mem_bbbb2222.md", "MEMORY.md"}

    md = (tmp_path / "out" / "mem_aaaa1111.md").read_text(encoding="utf-8")
    assert md.startswith("---\n")
    assert "id: mem_aaaa1111" in md
    assert "source: user" in md
    assert "scope: user" in md
    assert "created_at: 2026-08-15T10:00:00" in md
    assert '"style"' in md and '"编辑器"' in md
    assert "User prefers tabs over spaces" in md

    index = (tmp_path / "out" / "MEMORY.md").read_text(encoding="utf-8")
    assert "[mem_aaaa1111](mem_aaaa1111.md)" in index
    # index hook is the first content line only 索引摘要只取内容首行
    assert "Project uses pytest" in index
    assert "asyncio auto mode" not in index


def test_roundtrip_preserves_fields_and_scope(tmp_path: Path):
    original = make_entries()
    export_memories(original, tmp_path, scopes())
    imported = import_memories(tmp_path)

    assert len(imported) == 2
    by_id = {e.id: (e, s) for e, s in imported}
    for orig in original:
        got, scope = by_id[orig.id]
        assert got.content == orig.content.strip()
        assert got.source == orig.source
        assert got.created_at == orig.created_at
        assert got.tags == orig.tags
        assert scope == scopes()[orig.id]


def test_export_without_scopes_omits_scope_line(tmp_path: Path):
    export_memories(make_entries(), tmp_path)
    md = (tmp_path / "mem_aaaa1111.md").read_text(encoding="utf-8")
    assert "scope:" not in md
    imported = import_memories(tmp_path)
    assert all(scope == "" for _, scope in imported)


def test_import_skips_index_file(tmp_path: Path):
    export_memories(make_entries(), tmp_path, scopes())
    imported = import_memories(tmp_path)
    assert len(imported) == 2
    assert all(e.id.startswith("mem_") for e, _ in imported)


def test_import_plain_markdown_without_frontmatter(tmp_path: Path):
    (tmp_path / "note.md").write_text("Just a plain note\nsecond line", encoding="utf-8")
    imported = import_memories(tmp_path)
    assert len(imported) == 1
    entry, scope = imported[0]
    assert entry.content == "Just a plain note\nsecond line"
    assert entry.id.startswith("mem_")  # auto-generated
    assert entry.source == "user"
    assert scope == ""


def test_import_mewcode_style_frontmatter(tmp_path: Path):
    (tmp_path / "feedback_style.md").write_text(
        "---\n"
        "name: feedback-style\n"
        "description: user wants terse responses\n"
        "metadata:\n"
        "  type: feedback\n"
        "---\n"
        "\n"
        "Keep responses short.\n",
        encoding="utf-8",
    )
    imported = import_memories(tmp_path)
    assert len(imported) == 1
    entry, _ = imported[0]
    assert entry.content == "Keep responses short."
    assert entry.id.startswith("mem_")


def test_import_mewcode_empty_body_uses_description(tmp_path: Path):
    (tmp_path / "x.md").write_text(
        "---\ndescription: the gist lives here\n---\n\n",
        encoding="utf-8",
    )
    imported = import_memories(tmp_path)
    assert len(imported) == 1
    assert imported[0][0].content == "the gist lives here"


def test_import_skips_empty_files(tmp_path: Path):
    (tmp_path / "empty.md").write_text("", encoding="utf-8")
    (tmp_path / "fm_only.md").write_text("---\nid: mem_x\n---\n", encoding="utf-8")
    assert import_memories(tmp_path) == []


def test_import_unterminated_frontmatter_as_body(tmp_path: Path):
    (tmp_path / "broken.md").write_text("---\nid: mem_broken\nno closing", encoding="utf-8")
    imported = import_memories(tmp_path)
    assert len(imported) == 1
    entry, _ = imported[0]
    # whole file treated as content, id auto-generated 整个文件视为正文
    assert "no closing" in entry.content
    assert entry.id != "mem_broken"


def test_tags_comma_fallback(tmp_path: Path):
    (tmp_path / "t.md").write_text("---\nid: mem_t1\ntags: a, b\n---\n\nbody\n", encoding="utf-8")
    imported = import_memories(tmp_path)
    assert imported[0][0].tags == ["a", "b"]
