"""Theme system -- color palettes for the terminal UI.
主题系统——终端 UI 的配色方案。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    """A color theme for the terminal UI. 终端 UI 的配色主题。"""

    name: str
    primary: str  # Brand color: prompt, tool names 品牌色：提示符、工具名
    success: str  # Success indicators 成功标识
    error: str  # Error indicators 错误标识
    warning: str  # Warnings and confirmations 警告和确认
    dim: str  # Secondary text 次要文本
    menu_bg: str  # Completion menu background 补全菜单背景
    menu_select: str  # Completion menu selection 补全菜单选中项
    heading: str = ""  # Markdown headings (empty = use success) 标题色（空 = 用 success）
    # User input line: typed text + framing rules. Bright so the line is
    # instantly findable in scrollback. 用户输入行：文字 + 上下横线。
    # 亮色确保滚动历史中一眼可辨。
    user_input: str = "#ffaf00"


THEMES: dict[str, Theme] = {
    "default": Theme(
        name="default",
        primary="#6c71c4",
        success="#2ecc71",
        error="#e74c3c",
        warning="#f39c12",
        dim="#666666",
        menu_bg="#1a1a2e",
        menu_select="#3d5afe",
        heading="#2ecc71",
        user_input="#ffaf00",
    ),
    "dark": Theme(
        name="dark",
        primary="#ff9e64",
        success="#9ece6a",
        error="#f7768e",
        warning="#e0af68",
        dim="#565f89",
        menu_bg="#16161e",
        menu_select="#ff9e64",
        heading="#ff9e64",  # same as prompt 与提示符同色（橙）
        user_input="#ff9e64",
    ),
    "light": Theme(
        name="light",
        primary="#0550ae",
        success="#116329",
        error="#cf222e",
        warning="#9a6700",
        dim="#57606a",
        menu_bg="#f6f8fa",
        menu_select="#0550ae",
        heading="#9ece6a",  # dark theme's yellow-green 用 dark 的黄绿
        user_input="#b35900",
    ),
}


def get_theme(name: str) -> Theme:
    """Get a theme by name, falling back to default.
    按名称获取主题，找不到时退回默认主题。
    """
    return THEMES.get(name, THEMES["default"])
