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


THEMES: dict[str, Theme] = {
    "default": Theme(
        name="default",
        primary="#6c71c4",
        success="green",
        error="red",
        warning="yellow",
        dim="dim",
        menu_bg="#1a1a2e",
        menu_select="#3d5afe",
    ),
    "dark": Theme(
        name="dark",
        primary="#7aa2f7",
        success="#9ece6a",
        error="#f7768e",
        warning="#e0af68",
        dim="#565f89",
        menu_bg="#16161e",
        menu_select="#7aa2f7",
    ),
    "light": Theme(
        name="light",
        primary="#5b21b6",
        success="#15803d",
        error="#b91c1c",
        warning="#a16207",
        dim="#6b7280",
        menu_bg="#e5e7eb",
        menu_select="#5b21b6",
    ),
}


def get_theme(name: str) -> Theme:
    """Get a theme by name, falling back to default.
    按名称获取主题，找不到时退回默认主题。
    """
    return THEMES.get(name, THEMES["default"])
