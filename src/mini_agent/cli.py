"""CLI argument parsing and application launch. CLI 参数解析与应用启动。"""

from __future__ import annotations

import argparse
import asyncio
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mini-agent",
        description="A terminal-based coding agent tool",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model name (e.g. gpt-4o, claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        choices=["openai", "anthropic"],
        help="LLM provider to use",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for the LLM provider",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Custom API base URL (for OpenAI-compatible endpoints)",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Start in remote/browser mode (WebSocket server)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="WebSocket server port (default: 8765)",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="WebSocket server host (default: localhost)",
    )
    parser.add_argument(
        "--remote-token",
        default="",
        help="Token for remote mode authentication (optional)",
    )
    parser.add_argument(
        "--worker",
        default=None,
        metavar="SPEC_JSON",
        help="Run as a headless pane worker: execute the task described in "
        "SPEC_JSON and exit (used by /spawn --pane, not meant for manual use)",
    )
    parser.add_argument(
        "-p",
        "--prompt",
        default=None,
        metavar="PROMPT",
        help="Run one prompt non-interactively and exit (for scripts/CI/pipes); "
        "actions that would need confirmation are denied fail-safe",
    )
    parser.add_argument(
        "--output-format",
        choices=["text", "stream-json"],
        default="text",
        help="Output format for -p mode: 'text' (default) prints only the final "
        "answer; 'stream-json' emits an NDJSON event stream (one JSON per line, "
        "same event names as remote mode)",
    )
    from mini_agent import __version__

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args(argv)


def _harden_windows_stdio() -> None:
    """Windows consoles default to legacy codepages (cp936/cp437) that cannot
    encode box-drawing chars -- reconfigure stdio to UTF-8 with replacement.
    stdin matters too: mintty (Git Bash) pipes may surface lone surrogates
    via surrogateescape, which later crash httpx's UTF-8 JSON encoding.
    Windows 控制台默认旧代码页编码不了制表符——入口统一切 UTF-8 并容错替换。
    stdin 同样要处理：mintty 管道可能经 surrogateescape 产生孤立代理字符，
    后续 httpx 的 UTF-8 JSON 编码会因此崩溃。"""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> None:
    _harden_windows_stdio()
    args = parse_args(argv)

    if args.worker:
        from mini_agent.core.worker import run_worker

        sys.exit(asyncio.run(run_worker(args.worker)))

    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    cli_overrides: dict = {}
    if args.model:
        cli_overrides["llm.model"] = args.model
    if args.provider:
        cli_overrides["llm.provider"] = args.provider
    if args.api_key:
        cli_overrides["llm.api_key"] = args.api_key
    if args.base_url:
        cli_overrides["llm.base_url"] = args.base_url

    config = ConfigLoader.load(cli_overrides=cli_overrides)

    if not config.llm.api_key:
        print("错误: 未配置 API key。请通过以下任一方式设置:")
        print("  1. 复制 .env.example 为 .env 并填入 OPENAI_API_KEY")
        print("  2. 设置环境变量: OPENAI_API_KEY 或 MINI_AGENT_API_KEY")
        print("  3. CLI 参数: mini --api-key sk-xxx")
        sys.exit(1)

    if args.prompt:
        # Headless one-shot: ALL terminal/rich output goes to stderr so the
        # real stdout carries only the result (final text or NDJSON lines).
        # 一次性无头模式：终端输出整体转 stderr，真 stdout 只承载结果。
        import contextlib

        from mini_agent.headless import run_headless

        with contextlib.redirect_stdout(sys.stderr):
            app = Application(config)
            code = asyncio.run(run_headless(app, args.prompt, args.output_format))
        sys.exit(code)

    app = Application(config)

    # NOTE: no `finally: sys.exit(0)` here -- that would swallow the
    # traceback of ANY crash and turn it into a silent clean exit
    # (a pane-board AttributeError once hid exactly this way).
    # 不能用 finally: sys.exit(0)——它会吞掉一切崩溃的 traceback，
    # 把异常变成无声的正常退出（进度面板的 AttributeError 曾被这样掩盖）。
    try:
        if args.remote:
            from mini_agent.remote.server import RemoteServer

            server = RemoteServer(
                app,
                host=args.host,
                port=args.port,
                token=args.remote_token,
            )
            asyncio.run(server.start())
        else:
            asyncio.run(app.run())
    except KeyboardInterrupt:
        pass
    sys.exit(0)
