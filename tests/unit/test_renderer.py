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
    from rich.console import Console

    r = StreamRenderer(Console(width=200, force_terminal=False, record=True))
    lines = ["```python"] + [f"line {i}" for i in range(30)]
    r._buffer = "\n".join(lines)
    md = r._render_tail(r._buffer)
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


# --- feed_thinking fragmented-line fix 思考流碎行修复 ---


async def test_feed_thinking_no_fragment_wrapping():
    """A thinking delta wider than console.width must NOT be word-wrapped by
    Rich: Rich wraps each print as an independent render unit starting from
    column 0, but the REAL cursor may be mid-line from prior deltas -- its
    inserted newlines land in wrong places, littering broken fragments.
    soft_wrap leaves line-breaking to the terminal (which tracks the real
    cursor column). Regression-verified: without soft_wrap this exact input
    renders as 'this is a \\nlong \\nthinking \\nfragment'.
    超过 console.width 的思考增量不能被 Rich 折行：Rich 把每次 print 当
    从 0 列起算的独立渲染单元，而真实光标可能在行中——插入的换行位置
    全错，产生碎行。soft_wrap 把折行交给终端。反向验证：无 soft_wrap 时
    此输入渲染为 'this is a \\nlong \\nthinking \\nfragment'。"""
    from io import StringIO

    from mini_agent.ui.terminal import Terminal

    term = Terminal()
    buf = StringIO()
    term.console = Console(file=buf, width=10, force_terminal=False)

    # One wide fragment + trailing small fragments (real streams mix both)
    # 一个超宽片段 + 若干小片段（真实流两者混合）
    term.feed_thinking("this is a long thinking fragment")
    term.feed_thinking(".txt")
    term.feed_thinking(").")

    out = buf.getvalue()
    assert "\n" not in out, f"Rich inserted line breaks: {out!r}"
    assert out == "this is a long thinking fragment.txt)."


async def test_feed_thinking_preserves_real_newlines():
    """Newlines that ARE in the reasoning content must pass through.
    reasoning 内容里本来就有的换行必须原样保留。"""
    from io import StringIO

    from mini_agent.ui.terminal import Terminal

    term = Terminal()
    buf = StringIO()
    term.console = Console(file=buf, width=40, force_terminal=False)

    term.feed_thinking("step one\n")
    term.feed_thinking("step two")

    assert buf.getvalue() == "step one\nstep two"


async def test_thinking_deltas_do_not_run_under_live():
    """The REAL fragmentation mechanism in a live terminal: agent_loop fires
    on_stream_start on the FIRST thinking chunk, and console.print during an
    active Live is intercepted -- each fragment is followed by Live's refresh
    control codes (\\r + erase-line), so fragments get erased/broken and only
    scattered pieces survive on their own lines. Fix: Live start is deferred
    to the first answer delta (feed_stream); thinking writes go directly to
    the terminal with no Live active. force_terminal=True exercises the real
    ANSI path (Live interception is a no-op on file consoles).
    真实终端碎行主机制：agent_loop 在第一个 thinking chunk 就触发
    on_stream_start，而 Live 活跃期间 console.print 被拦截——每个碎片后
    跟 Live 刷新控制码（\\r+整行擦除），碎片被擦除/打断，只剩零星碎片
    各自成行。修复：Live 延迟到第一个正文 delta 才启动，思考期间直连
    写入无 Live。force_terminal=True 走真实 ANSI 路径（文件控制台下
    Live 拦截不生效，测不到）。"""
    import re
    from io import StringIO

    from mini_agent.ui.renderer import StreamRenderer
    from mini_agent.ui.terminal import Terminal

    term = Terminal()
    buf = StringIO()
    term.console = Console(file=buf, width=80, force_terminal=True)
    term.renderer = StreamRenderer(term.console)

    term.start_stream()
    for d in ["9", ".", "11", " vs ", "9", ".", "9", ", think", "ing..."]:
        term.feed_thinking(d)
    # No Live while thinking streams -- deltas are direct sequential writes
    # 思考流期间无 Live——增量直连顺序写入
    assert term.renderer._live is None
    thinking_out = buf.getvalue()
    # No carriage-return/erase-line between fragments (Live's erasure signature)
    # 碎片之间无回车/整行擦除（Live 擦除特征码）
    assert "\r" not in thinking_out, f"Live erasure codes present: {thinking_out!r}"
    stripped = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", thinking_out)
    assert "9.11 vs 9.9, thinking..." in stripped

    # First answer delta lazily starts the Live (after ending the thinking line)
    # 第一个正文 delta 才延迟启动 Live（先收尾思考行）
    term.feed_stream("answer text")
    assert term.renderer._live is not None
    assert term.finish_stream() == "answer text"


async def test_thinking_only_turn_finishes_cleanly():
    """Thinking followed by tool calls (no answer text) must not crash
    finish_stream: the renderer's Live was never started.
    只有思考没有正文（后接工具调用）时 finish_stream 不能崩溃：
    renderer 的 Live 从未启动。"""
    from io import StringIO

    from mini_agent.ui.renderer import StreamRenderer
    from mini_agent.ui.terminal import Terminal

    term = Terminal()
    buf = StringIO()
    term.console = Console(file=buf, width=80, force_terminal=False)
    term.renderer = StreamRenderer(term.console)

    term.start_stream()
    term.feed_thinking("reasoning only")
    assert term.finish_stream() == ""
    assert "reasoning only" in buf.getvalue()
