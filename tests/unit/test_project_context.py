"""Tests for project instruction file loading. 项目指令文件加载测试。"""

from __future__ import annotations

from mini_agent.memory.project_context import (
    DEFAULT_MAX_CHARS,
    _expand_includes,
    load_project_instructions,
    load_user_instructions,
)


def test_load_agent_md(tmp_path):
    (tmp_path / "AGENT.md").write_text("use uv for everything", encoding="utf-8")

    result = load_project_instructions(tmp_path)
    assert result is not None
    name, text = result
    assert name == "AGENT.md"
    assert "use uv" in text


def test_priority_agent_over_claude(tmp_path):
    (tmp_path / "AGENT.md").write_text("agent rules", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("claude rules", encoding="utf-8")

    name, text = load_project_instructions(tmp_path)
    assert name == "AGENT.md"
    assert text == "agent rules"


def test_load_claude_md_fallback(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("claude rules", encoding="utf-8")

    name, text = load_project_instructions(tmp_path)
    assert name == "CLAUDE.md"


def test_load_mini_agent_instructions(tmp_path):
    sub = tmp_path / ".mini-agent"
    sub.mkdir()
    (sub / "instructions.md").write_text("project specific", encoding="utf-8")

    name, text = load_project_instructions(tmp_path)
    assert name == ".mini-agent/instructions.md"


def test_no_files_returns_none(tmp_path):
    assert load_project_instructions(tmp_path) is None


def test_truncation(tmp_path):
    (tmp_path / "AGENT.md").write_text("x" * (DEFAULT_MAX_CHARS + 500), encoding="utf-8")

    _, text = load_project_instructions(tmp_path)
    assert len(text) <= DEFAULT_MAX_CHARS + 20
    assert text.endswith("(truncated)")


def test_empty_file_skipped(tmp_path):
    (tmp_path / "AGENT.md").write_text("   \n  ", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("fallback content", encoding="utf-8")

    name, text = load_project_instructions(tmp_path)
    assert name == "CLAUDE.md"


def test_user_instructions(tmp_path):
    inst = tmp_path / "instructions.md"
    inst.write_text("always answer in Chinese", encoding="utf-8")

    assert load_user_instructions(str(inst)) == "always answer in Chinese"


def test_user_instructions_missing(tmp_path):
    assert load_user_instructions(str(tmp_path / "nope.md")) is None


def test_custom_instruction_files(tmp_path):
    (tmp_path / "MY_RULES.md").write_text("custom rules", encoding="utf-8")
    (tmp_path / "AGENT.md").write_text("agent rules", encoding="utf-8")

    # Custom list overrides defaults 自定义列表覆盖默认
    name, text = load_project_instructions(tmp_path, ["MY_RULES.md"])
    assert name == "MY_RULES.md"
    assert text == "custom rules"


def test_custom_max_chars(tmp_path):
    (tmp_path / "AGENT.md").write_text("x" * 500, encoding="utf-8")

    _, text = load_project_instructions(tmp_path, max_chars=100)
    assert text.endswith("(truncated)")
    assert len(text) <= 120


# --- @-include directive tests @-include 指令测试 ---


def test_include_relative(tmp_path):
    """@./sub/extra.md is expanded to the referenced file's content."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "extra.md").write_text("extra rules", encoding="utf-8")
    (tmp_path / "AGENT.md").write_text("main\n@./sub/extra.md\nend", encoding="utf-8")

    _, text = load_project_instructions(tmp_path)
    assert "main" in text
    assert "extra rules" in text
    assert "end" in text
    assert "@./sub/extra.md" not in text


def test_include_home(tmp_path, monkeypatch):
    """@~/shared.md resolves relative to Path.home()."""
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    (fake_home / "shared.md").write_text("home content", encoding="utf-8")
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    (tmp_path / "AGENT.md").write_text("before\n@~/shared.md\nafter", encoding="utf-8")
    _, text = load_project_instructions(tmp_path)
    assert "home content" in text
    assert "@~/shared.md" not in text


def test_include_nested(tmp_path):
    """Two-level nesting: A includes B, B includes C."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "AGENT.md").write_text("level0\n@./sub/b.md", encoding="utf-8")
    (sub / "b.md").write_text("level1\n@./c.md", encoding="utf-8")
    (sub / "c.md").write_text("level2", encoding="utf-8")

    _, text = load_project_instructions(tmp_path)
    assert "level0" in text
    assert "level1" in text
    assert "level2" in text


def test_include_circular(tmp_path):
    """A includes B, B includes A — produces a comment, no infinite loop."""
    (tmp_path / "a.md").write_text("AAA\n@./b.md", encoding="utf-8")
    (tmp_path / "b.md").write_text("BBB\n@./a.md", encoding="utf-8")

    text = _expand_includes("start\n@./a.md", tmp_path, max_depth=5)
    assert "AAA" in text
    assert "BBB" in text
    assert "<!-- circular include:" in text


def test_include_not_found(tmp_path):
    """@./nonexistent.md produces a comment marker, not an error."""
    (tmp_path / "AGENT.md").write_text("ok\n@./nonexistent.md\nfine", encoding="utf-8")

    _, text = load_project_instructions(tmp_path)
    assert "<!-- include not found: ./nonexistent.md -->" in text
    assert "ok" in text
    assert "fine" in text


def test_include_depth_limit(tmp_path):
    """Beyond max_depth, @-include lines are kept verbatim."""
    (tmp_path / "deep.md").write_text("deep content", encoding="utf-8")

    text = _expand_includes("@./deep.md", tmp_path, max_depth=0)
    assert "@./deep.md" in text
    assert "deep content" not in text


def test_include_disabled(tmp_path):
    """max_include_depth=0 disables expansion entirely."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "extra.md").write_text("should not appear", encoding="utf-8")
    (tmp_path / "AGENT.md").write_text("@./sub/extra.md", encoding="utf-8")

    _, text = load_project_instructions(tmp_path, max_include_depth=0)
    assert "@./sub/extra.md" in text
    assert "should not appear" not in text


def test_include_truncation(tmp_path):
    """Expanded content counts toward max_chars truncation."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "big.md").write_text("X" * 5000, encoding="utf-8")
    (tmp_path / "AGENT.md").write_text("header\n@./sub/big.md", encoding="utf-8")

    _, text = load_project_instructions(tmp_path, max_chars=200)
    assert text.endswith("(truncated)")
    assert len(text) <= 220


def test_include_inline_text_not_expanded(tmp_path):
    """Inline @./foo.md in running text must NOT be expanded."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "foo.md").write_text("SHOULD NOT APPEAR", encoding="utf-8")
    (tmp_path / "AGENT.md").write_text("see @./sub/foo.md for details", encoding="utf-8")

    _, text = load_project_instructions(tmp_path)
    assert "SHOULD NOT APPEAR" not in text
    assert "see @./sub/foo.md for details" in text


def test_include_with_user_instructions(tmp_path):
    """User-level instruction files also support @-include."""
    sub = tmp_path / "shared"
    sub.mkdir()
    (sub / "rules.md").write_text("shared rules", encoding="utf-8")
    inst = tmp_path / "instructions.md"
    inst.write_text("user base\n@./shared/rules.md", encoding="utf-8")

    text = load_user_instructions(str(inst))
    assert "user base" in text
    assert "shared rules" in text
    assert "@./shared/rules.md" not in text


def test_application_injects_instructions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    (tmp_path / "CLAUDE.md").write_text("project uses pytest", encoding="utf-8")

    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    app = Application(ConfigLoader.load())
    sp = app.session.conversation.system_prompt
    assert "--- Project instructions ---" in sp
    assert "project uses pytest" in sp
    assert sp.count("--- Project instructions ---") == 1
    assert app._context_file_loaded == "CLAUDE.md"
