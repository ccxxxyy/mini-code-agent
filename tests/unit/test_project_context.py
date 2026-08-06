"""Tests for project instruction file loading. 项目指令文件加载测试。"""

from __future__ import annotations

from mini_agent.memory.project_context import (
    DEFAULT_MAX_CHARS,
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
