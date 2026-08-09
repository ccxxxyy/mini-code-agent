"""Tests for @file inline references (P39).
@文件内联引用的测试。"""

from pathlib import Path

import pytest

from mini_agent.ui.input_handler import (
    FileRefCompleter,
    expand_at_refs,
)

pytestmark = pytest.mark.asyncio


# --- expand_at_refs ---


async def test_expand_existing_file(tmp_path: Path):
    (tmp_path / "hello.txt").write_text("world", encoding="utf-8")
    result = expand_at_refs("see @hello.txt please", tmp_path)
    assert "[File: hello.txt]" in result
    assert "world" in result
    assert "@hello.txt" not in result


async def test_expand_nonexistent_file_unchanged(tmp_path: Path):
    result = expand_at_refs("see @nope.txt please", tmp_path)
    assert result == "see @nope.txt please"


async def test_expand_multiple_refs(tmp_path: Path):
    (tmp_path / "a.py").write_text("aaa", encoding="utf-8")
    (tmp_path / "b.py").write_text("bbb", encoding="utf-8")
    result = expand_at_refs("compare @a.py and @b.py", tmp_path)
    assert "[File: a.py]" in result
    assert "[File: b.py]" in result
    assert "aaa" in result
    assert "bbb" in result


async def test_expand_truncates_large_file(tmp_path: Path):
    big = tmp_path / "big.txt"
    big.write_text("x" * 20_000, encoding="utf-8")
    result = expand_at_refs("@big.txt", tmp_path)
    assert "truncated" in result
    assert len(result) < 15_000


async def test_expand_no_at_sign_noop(tmp_path: Path):
    result = expand_at_refs("no refs here", tmp_path)
    assert result == "no refs here"


async def test_expand_subdirectory_path(tmp_path: Path):
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "main.py").write_text("import sys", encoding="utf-8")
    result = expand_at_refs("read @src/main.py", tmp_path)
    assert "[File: src/main.py]" in result
    assert "import sys" in result


# --- FileRefCompleter ---


def _complete(completer, text):
    from prompt_toolkit.document import Document

    doc = Document(text, cursor_position=len(text))
    return list(completer.get_completions(doc, None))


async def test_completer_matches_files(tmp_path: Path):
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / "setup.py").write_text("x", encoding="utf-8")
    c = FileRefCompleter(tmp_path)
    results = _complete(c, "@READ")
    assert any("README.md" in r.text for r in results)
    assert not any("setup.py" in r.text for r in results)


async def test_completer_shows_dir_with_slash(tmp_path: Path):
    (tmp_path / "src").mkdir()
    c = FileRefCompleter(tmp_path)
    results = _complete(c, "@sr")
    assert any("src/" in r.text for r in results)


async def test_completer_skips_hidden(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "visible.py").write_text("x", encoding="utf-8")
    c = FileRefCompleter(tmp_path)
    results = _complete(c, "@")
    texts = [r.text for r in results]
    assert not any(".git" in t for t in texts)
    assert any("visible.py" in t for t in texts)


async def test_completer_subdirectory(tmp_path: Path):
    sub = tmp_path / "docs"
    sub.mkdir()
    (sub / "spec.md").write_text("x", encoding="utf-8")
    (sub / "tasks.md").write_text("x", encoding="utf-8")
    c = FileRefCompleter(tmp_path)
    results = _complete(c, "@docs/sp")
    assert any("spec.md" in r.text for r in results)
    assert not any("tasks.md" in r.text for r in results)


async def test_completer_no_trigger_without_at(tmp_path: Path):
    c = FileRefCompleter(tmp_path)
    assert _complete(c, "hello") == []


async def test_completer_stops_after_space(tmp_path: Path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    c = FileRefCompleter(tmp_path)
    assert _complete(c, "@a.txt then") == []
