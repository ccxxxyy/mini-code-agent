"""StreamRenderer 逐段提交式流式渲染测试。"""

from __future__ import annotations

import pytest
from rich.console import Console

from mini_agent.ui.renderer import StreamRenderer

pytestmark = pytest.mark.asyncio


def make_renderer() -> tuple[StreamRenderer, Console]:
    console = Console(record=True, width=80, force_terminal=False)
    return StreamRenderer(console), console


async def test_finish_returns_full_text():
    r, _ = make_renderer()
    r.start()
    r.feed("Hello ")
    r.feed("world")
    assert r.finish() == "Hello world"


async def test_full_text_across_paragraph_commits():
    r, _ = make_renderer()
    r.start()
    text = "para one\n\npara two\n\npara three"
    for ch in text:
        r.feed(ch)
    assert r.finish() == text


async def test_committed_content_printed_once():
    r, console = make_renderer()
    r.start()
    long_text = "\n\n".join(f"paragraph number {i}" for i in range(20))
    for i in range(0, len(long_text), 7):
        r.feed(long_text[i : i + 7])
    r.finish()
    output = console.export_text()
    assert output.count("paragraph number 5") == 1
    assert output.count("paragraph number 19") == 1


def test_split_committed_keeps_fence_intact():
    text = "before\n\n```python\ncode line\n\nstill in fence\n```\nafter"
    committed, tail = StreamRenderer._split_committed(text)
    assert "```" not in committed or committed.count("```") % 2 == 0
    assert "still in fence" in tail or "still in fence" in committed


def test_split_committed_no_blank_line():
    committed, tail = StreamRenderer._split_committed("single line no break")
    assert committed == ""
    assert tail == "single line no break"


def test_split_committed_blank_line_inside_fence_not_split():
    text = "```bash\n# Windows\npwsh -c x\n\n# macOS / Linux\ncurl ...\n```\n\nnext para\nmore"
    committed, tail = StreamRenderer._split_committed(text)
    if committed:
        assert committed.count("```") % 2 == 0
        assert "# macOS / Linux" in committed
    else:
        assert tail == text


async def test_streaming_matches_full_render():
    text = "intro\n\n```bash\n# A\ncmd-a\n\n# B\ncmd-b\n```\n\noutro paragraph\n\nfinal"
    r, console = make_renderer()
    r.start()
    for i in range(0, len(text), 3):
        r.feed(text[i : i + 3])
    r.finish()
    streamed = console.export_text()

    from rich.markdown import Markdown

    full_console = Console(record=True, width=80, force_terminal=False)
    full_console.print(Markdown(text))
    full = full_console.export_text()

    def norm(s: str) -> list[str]:
        return [line.rstrip() for line in s.splitlines() if line.strip()]

    assert norm(streamed) == norm(full)


def test_render_tail_reopens_fence():
    lines = ["```python"] + [f"line {i}" for i in range(30)]
    md = StreamRenderer._render_tail("\n".join(lines))
    assert md.markup.startswith("```python\n")


def test_normalize_upgrades_illegal_nested_fence():
    # LLM 常见非法输出：外层 ``` 包住内层 ```bash（同长度嵌套）
    text = "intro\n\n```\n# Title\n\n```bash\ncurl ...\n```\n\n### 2. next\n```\ndone"
    fixed = StreamRenderer._normalize(text)
    lines = fixed.split("\n")
    assert lines[2] == "````"  # 外层升级为 4 反引号
    assert lines[-2] == "````"
    assert "```bash" in fixed  # 内层保持不变


def test_normalize_legal_markdown_unchanged():
    text = "para\n\n```python\ncode\n```\n\nafter"
    assert StreamRenderer._normalize(text) == text


def test_split_committed_nested_fence_not_split_at_inner_close():
    # 外层围栏内含 bash 块，bash 块关闭后的空行仍在外层围栏内，不能切分
    text = "```\n# README\n\n```bash\ncmd\n```\n\n### 2. section\nline\nline2"
    committed, tail = StreamRenderer._split_committed(text)
    assert committed == ""
    assert tail == text


async def test_streaming_nested_fence_stays_in_one_block():
    inner = "\n".join(f"content line {i}" for i in range(5))
    text = (
        f"quote:\n\n```\n# Title\n\n```bash\ncmd-x\n```\n\n{inner}\n\n### 2. next\n```\n\ntail para"
    )
    r, console = make_renderer()
    r.start()
    for i in range(0, len(text), 4):
        r.feed(text[i : i + 4])
    r.finish()
    out = console.export_text()
    # 非法嵌套被修复后，"### 2. next" 应作为代码块内容渲染（保留 ### 前缀），
    # 而不是被断开当成真标题（真标题渲染会去掉 ### 标记）
    assert "### 2. next" in out
