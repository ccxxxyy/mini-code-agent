"""Headless -p mode tests. -p 非交互一次性模式测试。"""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.cli import parse_args
from mini_agent.llm.base import LLMProvider, StreamChunk, ToolCallDelta

pytestmark = pytest.mark.asyncio


# --- CLI parsing 参数解析 ---


async def test_parse_args_prompt_and_format():
    args = parse_args(["-p", "hello world", "--output-format", "stream-json"])
    assert args.prompt == "hello world"
    assert args.output_format == "stream-json"


async def test_parse_args_prompt_defaults():
    args = parse_args([])
    assert args.prompt is None
    assert args.output_format == "text"


# --- Runner harness 运行器测试替身 ---


class MockLLM(LLMProvider):
    """Yields a fixed answer; optionally a tool call first or an error.
    固定回答；可选先产出一个工具调用或抛错。"""

    def __init__(self, text: str = "Done.", tool_call: dict | None = None, error: bool = False):
        self._text = text
        self._tool_call = tool_call
        self._calls = 0
        self._error = error

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        if self._error:
            raise RuntimeError("boom")
        self._calls += 1
        if self._tool_call and self._calls == 1:
            yield StreamChunk(
                tool_call_deltas=[
                    ToolCallDelta(
                        index=0,
                        id="tc1",
                        name=self._tool_call["name"],
                        arguments_delta=json.dumps(self._tool_call["args"]),
                    )
                ]
            )
            yield StreamChunk(finish_reason="tool_calls")
            return
        yield StreamChunk(delta=self._text)
        yield StreamChunk(finish_reason="stop")

    async def prepare(self) -> None:
        pass

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


def make_app(tmp_path, llm: MockLLM):
    """Real Application with the LLM swapped for a mock.
    真实 Application，仅替换 LLM。"""
    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    config = ConfigLoader.load(cli_overrides={"llm.api_key": "test"})
    app = Application(config)
    app._llm = llm
    app.agent_loop._llm = llm
    return app


async def run_headless_captured(app, prompt: str, fmt: str, monkeypatch) -> tuple[int, str]:
    """Run with sys.__stdout__ captured. 捕获真 stdout 运行。"""
    import sys

    import mini_agent.headless as headless_mod

    buf = io.StringIO()
    monkeypatch.setattr(sys, "__stdout__", buf)
    code = await headless_mod.run_headless(app, prompt, fmt)
    return code, buf.getvalue()


# --- text mode ---


async def test_text_mode_prints_final_answer(tmp_path, monkeypatch, capsys):
    app = make_app(tmp_path, MockLLM(text="The answer is 42."))
    code, out = await run_headless_captured(app, "what is the answer?", "text", monkeypatch)
    assert code == 0
    assert out.strip() == "The answer is 42."


# --- stream-json mode ---


async def test_stream_json_valid_ndjson_and_order(tmp_path, monkeypatch):
    app = make_app(tmp_path, MockLLM(text="hi there"))
    code, out = await run_headless_captured(app, "say hi", "stream-json", monkeypatch)
    assert code == 0

    lines = [ln for ln in out.splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]  # every line is valid JSON 每行合法
    types = [e["type"] for e in events]

    assert types[0] == "user_message"
    assert types[1] == "turn_start"
    assert types[-1] == "turn_end"
    assert "stream_end" in types
    assert types.index("turn_start") < types.index("stream_end")
    full = next(e for e in events if e["type"] == "stream_end")
    assert full["full_text"] == "hi there"
    end = events[-1]
    assert "tokens" in end and "iterations" in end and "elapsed" in end


async def test_stream_json_tool_events(tmp_path, monkeypatch):
    app = make_app(
        tmp_path,
        MockLLM(text="done", tool_call={"name": "glob", "args": {"pattern": "*.md"}}),
    )
    code, out = await run_headless_captured(app, "list md files", "stream-json", monkeypatch)
    assert code == 0
    types = [json.loads(ln)["type"] for ln in out.splitlines() if ln.strip()]
    assert "tool_call" in types
    assert "tool_result" in types


# --- permission fail-safe 权限失败安全 ---


async def test_dangerous_command_denied_not_hung(tmp_path, monkeypatch):
    """A command that would prompt for confirmation is denied fail-safe
    (no confirm UI) instead of hanging. 需确认的命令被拒不挂起。"""
    app = make_app(
        tmp_path,
        MockLLM(text="ok", tool_call={"name": "bash", "args": {"command": "rm -rf /tmp/x"}}),
    )
    code, out = await run_headless_captured(app, "delete it", "stream-json", monkeypatch)
    assert code == 0  # denial is a normal outcome, not a crash 拒绝是正常结局
    events = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
    assert events[-1]["type"] == "turn_end"  # completed, did not hang 收尾未挂起
    # Denied at the permission layer via the no-UI fail-safe, and the
    # confirm-denial breaker stopped the loop 权限层失败安全拒绝+熔断早停
    assert app.permission_manager.last_decision_reason == "no_ui:default_deny"
    assert app.agent_loop.stopped_early
    assert app.agent_loop.stop_reason == "confirm_denied"


# --- error path 异常路径 ---


async def test_llm_error_exits_1_with_error_event(tmp_path, monkeypatch):
    app = make_app(tmp_path, MockLLM(error=True))
    code, out = await run_headless_captured(app, "hi", "stream-json", monkeypatch)
    assert code == 1
    events = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
    assert any(e["type"] == "error" and "boom" in e["message"] for e in events)
    assert events[-1]["type"] == "turn_end"  # turn_end still emitted 仍收尾


# --- no session persistence 会话不落盘 ---


async def test_headless_does_not_persist_session(tmp_path, monkeypatch):
    from mini_agent.memory.session_store import SessionStore

    app = make_app(tmp_path, MockLLM(text="ok"))
    app.session_store = SessionStore(session_dir=str(tmp_path / "sessions"))
    code, _ = await run_headless_captured(app, "hi", "text", monkeypatch)
    assert code == 0
    assert (
        not list((tmp_path / "sessions").glob("*.json"))
        if (tmp_path / "sessions").exists()
        else True
    )
