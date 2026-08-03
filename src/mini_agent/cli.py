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
    from mini_agent import __version__

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

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

    app = Application(config)

    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass
    finally:
        sys.exit(0)
