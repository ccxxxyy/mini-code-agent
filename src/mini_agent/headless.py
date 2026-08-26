"""Headless one-shot runner for `-p` mode. `-p` 非交互一次性运行器。

Runs a single prompt through the agent loop and exits -- for scripts, CI
and pipelines. Two output formats on the REAL stdout (all other output is
expected to be redirected to stderr by the CLI entry):

- text: only the final assistant answer
- stream-json: NDJSON event stream, one JSON object per line, event names
  and payload shapes shared with the remote-mode WebSocket protocol

执行单个 prompt 后退出——服务脚本/CI/管道场景。真 stdout 上两种输出格式
（其余输出由 CLI 入口整体重定向到 stderr）：text 只出最终回答；
stream-json 逐行 NDJSON，事件命名与远程模式 WS 协议一致。

Honest boundaries 诚实边界：
- No confirm UI: anything that would prompt is DENIED fail-safe
  (permission reason `no_ui:default_deny`). 无确认 UI，需确认的操作
  一律失败安全拒绝。
- The one-shot session is NOT persisted (no autosave) -- a CI job must
  not leave a session file per run. 一次性会话不落盘。
- SESSION_START/END hooks and memory extraction are skipped. 不跑
  SESSION hooks 与记忆提取。
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TextIO

from mini_agent.models.message import Message, Role

if TYPE_CHECKING:
    from mini_agent.app import Application


class _NdjsonEmitter:
    """One JSON object per line on the given stream, flushed immediately.
    逐行 JSON 输出并立即 flush。"""

    def __init__(self, out: TextIO) -> None:
        self._out = out

    def emit(self, event_type: str, **data: Any) -> None:
        self._out.write(json.dumps({"type": event_type, **data}, ensure_ascii=False) + "\n")
        self._out.flush()


class _QuietTerminal:
    """Terminal adapter for stream-json: show_* calls become NDJSON events,
    everything else forwards to the wrapped terminal (whose console output
    lands on the redirected stderr).
    stream-json 模式的终端适配：show_* 转 NDJSON 事件，其余转发原终端
    （其 console 输出落在被重定向的 stderr 上）。"""

    def __init__(self, inner: Any, emit: Callable[..., None]) -> None:
        self._inner = inner
        self._emit = emit

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def show_info(self, message: str) -> None:
        self._emit("info", message=message)

    def show_error(self, error: str) -> None:
        self._emit("error", message=error)

    def show_file_changes(self, items: list[str]) -> None:
        self._emit("file_changes", items=items)


def _wire_silent(al: Any, capture: list[str]) -> None:
    """text mode: silence all callbacks, only capture the final answer.
    text 模式：全部回调静默，只捕获最终回答。"""

    def _cap(full_text: str) -> None:
        capture[0] = full_text

    al.on_stream_start = None
    al.on_stream_delta = None
    al.on_stream_end = _cap
    al.on_thinking_delta = None
    al.on_tool_call_assembling = None
    al.on_tool_start = None
    al.on_tool_end = None


def _wire_ndjson(al: Any, emitter: _NdjsonEmitter, capture: list[str]) -> None:
    """stream-json mode: map callbacks to remote-protocol events.
    stream-json 模式：回调映射为远程协议同名事件。"""

    def _on_end(full_text: str) -> None:
        capture[0] = full_text
        emitter.emit("stream_end", full_text=full_text)

    def _on_tool_start(tc: Any) -> None:
        try:
            args = json.dumps(tc.arguments, ensure_ascii=False)[:200]
        except (TypeError, ValueError):
            args = str(tc.arguments)[:200]
        emitter.emit("tool_call", name=tc.name, args=args)

    def _on_tool_end(tr: Any, duration_ms: float) -> None:
        emitter.emit(
            "tool_result",
            name=tr.name,
            output=tr.output[:500],
            is_error=tr.is_error,
            elapsed=f"{duration_ms / 1000:.1f}s",
        )

    al.on_stream_start = lambda: emitter.emit("stream_start")
    al.on_stream_delta = lambda d: emitter.emit("stream_text", delta=d)
    al.on_stream_end = _on_end
    al.on_thinking_delta = lambda d: emitter.emit("thinking_delta", delta=d)
    al.on_tool_call_assembling = None
    al.on_tool_start = _on_tool_start
    al.on_tool_end = _on_tool_end


async def run_headless(app: Application, prompt: str, output_format: str = "text") -> int:
    """Execute one prompt and return the process exit code (0 ok / 1 error).
    执行单个 prompt，返回进程退出码（0 正常 / 1 异常）。"""
    out = sys.__stdout__ or sys.stdout
    emitter = _NdjsonEmitter(out) if output_format == "stream-json" else None
    al = app.agent_loop
    final_text = [""]

    # No confirm UI: fail-safe deny for anything that would prompt
    # 无确认 UI：需确认的操作一律失败安全拒绝
    app.permission_manager._confirm = None
    al.confirm_callback = None
    app._tool_context.ask_user_callback = None

    if emitter:
        _wire_ndjson(al, emitter, final_text)
        app.terminal = _QuietTerminal(app.terminal, emitter.emit)
    else:
        _wire_silent(al, final_text)

    await app._llm.prepare()
    await app._connect_mcp_servers()

    # Build the turn (mirrors _handle_turn without terminal reporting,
    # with our own try/except for exit-code semantics)
    # 手工构造回合（镜像 _handle_turn 但不经终端报告，自持异常拿退出码）
    from mini_agent.models.events import UserMessageEvent
    from mini_agent.ui.input_handler import expand_at_refs

    text = prompt
    if "@" in text:
        text = expand_at_refs(text, app._tool_context.working_dir)
    if emitter:
        emitter.emit("user_message", text=text)
    await app.event_bus.emit(UserMessageEvent(content=text))
    app.session.conversation.append(Message(role=Role.USER, content=text))
    app.session.metadata.total_turns += 1

    if emitter:
        emitter.emit("turn_start")
    t0 = time.monotonic()
    exit_code = 0
    try:
        await al.run(app.session.conversation)
    except Exception as e:
        exit_code = 1
        if emitter:
            emitter.emit("error", message=f"{type(e).__name__}: {e}")
        else:
            print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
    finally:
        if emitter:
            emitter.emit(
                "turn_end",
                tokens=al.last_turn_tokens,
                iterations=al._state.iteration,
                elapsed=time.monotonic() - t0,
            )
        try:
            await app.mcp_manager.disconnect_all()
        except Exception:  # noqa: BLE001 - shutdown must not mask the exit code
            pass

    if emitter is None and exit_code == 0:
        out.write(final_text[0] + "\n")
        out.flush()
    return exit_code
