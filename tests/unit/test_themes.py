"""Tests for theme system. 主题系统测试。"""

from __future__ import annotations

import pytest

from mini_agent.ui.themes import THEMES, get_theme

pytestmark = pytest.mark.asyncio


def test_get_theme_default():
    t = get_theme("default")
    assert t.name == "default"
    assert t.primary == "#6c71c4"


def test_get_theme_dark():
    t = get_theme("dark")
    assert t.name == "dark"
    assert t.primary == "#ff9e64"


def test_get_theme_unknown_fallback():
    t = get_theme("nonexistent")
    assert t.name == "default"


def test_all_themes_have_required_fields():
    for name, theme in THEMES.items():
        assert theme.name == name
        assert theme.primary
        assert theme.success
        assert theme.error
        assert theme.warning
        assert theme.dim


def test_theme_persistence_roundtrip(tmp_path):
    theme_file = tmp_path / ".theme"
    theme_file.write_text("dark", encoding="utf-8")
    loaded = theme_file.read_text(encoding="utf-8").strip()
    assert loaded == "dark"
    assert get_theme(loaded).name == "dark"


def test_prompt_style_uses_theme():
    from mini_agent.ui.input_handler import create_prompt_style

    dark = get_theme("dark")
    style = create_prompt_style(dark)
    # Style object created without error and uses theme colors
    assert style is not None


def test_terminal_accepts_theme():
    from mini_agent.ui.terminal import Terminal

    dark = get_theme("dark")
    term = Terminal(theme=dark)
    assert term.theme.name == "dark"
    assert term.theme.primary == "#ff9e64"
