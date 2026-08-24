"""Project instruction file discovery and loading.
项目指令文件发现与加载——启动时自动注入 system prompt 的上下文感知机制。

File names, priority order, and size cap are configurable via the
[context] section of config.toml; defaults live in ContextConfig.
文件名、优先级和截断长度可通过 config.toml 的 [context] 段配置，
默认值定义在 ContextConfig。

Supports @-include directives: a line containing only `@./path` or
`@~/path` is replaced with the referenced file's content, resolved
relative to the including file's directory (not the project root).
Recursive up to `max_depth` (default 5); circular includes produce a
comment marker and stop.
支持 @-include 指令：仅含 `@./path` 或 `@~/path` 的行被替换为引用
文件的内容，相对于引用方所在目录解析。递归展开至 max_depth（默认 5），
循环引用生成注释标记并停止。
"""

from __future__ import annotations

import re
from pathlib import Path

# Fallback defaults (kept in sync with ContextConfig) 兜底默认值（与 ContextConfig 一致）
DEFAULT_INSTRUCTION_FILES = ["AGENT.md", "CLAUDE.md", ".mini-agent/instructions.md"]
DEFAULT_USER_FILE = "~/.mini-agent/instructions.md"
DEFAULT_MAX_CHARS = 8000
DEFAULT_MAX_INCLUDE_DEPTH = 5

_INCLUDE_RE = re.compile(r"^\s*@(\./[^\s]+|~/[^\s]+)\s*$")


def _expand_includes(
    text: str,
    base_dir: Path,
    max_depth: int,
    _seen: set[Path] | None = None,
) -> str:
    """Recursively expand @-include directives.
    递归展开 @-include 指令。"""
    if max_depth <= 0:
        return text
    if _seen is None:
        _seen = set()

    lines: list[str] = []
    for line in text.splitlines():
        m = _INCLUDE_RE.match(line)
        if not m:
            lines.append(line)
            continue

        raw_path = m.group(1)
        if raw_path.startswith("~/"):
            target = Path.home() / raw_path[2:]
        else:
            target = base_dir / raw_path

        try:
            resolved = target.resolve()
        except OSError:
            lines.append(f"<!-- include not found: {raw_path} -->")
            continue

        if resolved in _seen:
            lines.append(f"<!-- circular include: {raw_path} -->")
            continue

        try:
            content = resolved.read_text(encoding="utf-8").strip()
        except OSError:
            lines.append(f"<!-- include not found: {raw_path} -->")
            continue

        if not content:
            continue

        _seen.add(resolved)
        content = _expand_includes(content, resolved.parent, max_depth - 1, _seen)
        lines.append(content)

    return "\n".join(lines)


def _read_capped(
    path: Path,
    max_chars: int,
    max_include_depth: int = DEFAULT_MAX_INCLUDE_DEPTH,
) -> str | None:
    """Read a text file, expand @-includes, cap at max_chars.
    读取文本文件，展开 @-include，超长截断。"""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None

    if max_include_depth > 0:
        seen: set[Path] = {path.resolve()}
        text = _expand_includes(text, path.parent, max_include_depth, seen)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n...(truncated)"
    return text


def load_project_instructions(
    project_dir: Path,
    instruction_files: list[str] | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_include_depth: int = DEFAULT_MAX_INCLUDE_DEPTH,
) -> tuple[str, str] | None:
    """Find and read the first instruction file in the project.
    在项目中查找并读取第一个指令文件。

    Returns (filename, content) or None.
    """
    for name in instruction_files or DEFAULT_INSTRUCTION_FILES:
        path = project_dir / name
        if path.is_file():
            text = _read_capped(path, max_chars, max_include_depth)
            if text:
                return name, text
    return None


def load_user_instructions(
    user_file: str = DEFAULT_USER_FILE,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_include_depth: int = DEFAULT_MAX_INCLUDE_DEPTH,
) -> str | None:
    """Read global user instructions. 读取用户级全局指令。"""
    path = Path(user_file).expanduser()
    if not path.is_file():
        return None
    return _read_capped(path, max_chars, max_include_depth)
