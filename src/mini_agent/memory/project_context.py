"""Project instruction file discovery and loading.
项目指令文件发现与加载——启动时自动注入 system prompt 的上下文感知机制。

File names, priority order, and size cap are configurable via the
[context] section of config.toml; defaults live in ContextConfig.
文件名、优先级和截断长度可通过 config.toml 的 [context] 段配置，
默认值定义在 ContextConfig。
"""

from __future__ import annotations

from pathlib import Path

# Fallback defaults (kept in sync with ContextConfig) 兜底默认值（与 ContextConfig 一致）
DEFAULT_INSTRUCTION_FILES = ["AGENT.md", "CLAUDE.md", ".mini-agent/instructions.md"]
DEFAULT_USER_FILE = "~/.mini-agent/instructions.md"
DEFAULT_MAX_CHARS = 8000


def _read_capped(path: Path, max_chars: int) -> str | None:
    """Read a text file, capped at max_chars. 读取文本文件，超长截断。"""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...(truncated)"
    return text


def load_project_instructions(
    project_dir: Path,
    instruction_files: list[str] | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple[str, str] | None:
    """Find and read the first instruction file in the project.
    在项目中查找并读取第一个指令文件。

    Returns (filename, content) or None.
    """
    for name in instruction_files or DEFAULT_INSTRUCTION_FILES:
        path = project_dir / name
        if path.is_file():
            text = _read_capped(path, max_chars)
            if text:
                return name, text
    return None


def load_user_instructions(
    user_file: str = DEFAULT_USER_FILE,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str | None:
    """Read global user instructions. 读取用户级全局指令。"""
    path = Path(user_file).expanduser()
    if not path.is_file():
        return None
    return _read_capped(path, max_chars)
