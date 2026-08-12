"""WebSocket server for remote/browser mode (P57).
远程/浏览器模式的 WebSocket 服务器。

Starts a WebSocket server that replaces the terminal UI with NDJSON events
over the wire. The browser connects, sends user_input messages, and receives
streaming text, tool calls, and permission requests.
启动 WebSocket 服务器替代终端 UI，通过 NDJSON 事件进行通信。浏览器连接后
发送 user_input 消息，接收流式文本、工具调用和权限请求。
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mini_agent.app import Application


_WEB_UI_HTML: str | None = None


def _get_html(port: int) -> str:
    global _WEB_UI_HTML
    if _WEB_UI_HTML is None:
        from mini_agent.remote.web_ui import build_html

        _WEB_UI_HTML = build_html(port)
    return _WEB_UI_HTML


class RemoteServer:
    """WebSocket server bridging the agent to a browser UI.
    连接 Agent 和浏览器 UI 的 WebSocket 服务器。"""

    def __init__(self, app: Application, host: str = "localhost", port: int = 8765) -> None:
        self._app = app
        self._host = host
        self._port = port
        self._ws: Any = None
        self._pending_confirms: dict[str, asyncio.Future] = {}
        self._running_turn: asyncio.Task | None = None

        # Wrap terminal to intercept UI calls and send to WebSocket
        from mini_agent.remote.terminal import RemoteTerminalAdapter
        self._original_terminal = app.terminal
        app.terminal = RemoteTerminalAdapter(app.terminal, self._safe_send)

    async def start(self) -> None:
        """Start the WebSocket server and block until stopped.
        启动 WebSocket 服务器并阻塞直到停止。"""
        try:
            import websockets
        except ImportError:
            raise SystemExit(
                "Remote mode requires the 'websockets' package.\n"
                "Install with: uv sync --extra remote  or  pip install websockets"
            )

        http_port = self._port + 1
        html = _get_html(self._port)
        self._start_http_server(html, self._host, http_port)

        print("Mini-Code-Agent remote mode")
        print(f"  WebSocket: ws://{self._host}:{self._port}")
        print(f"  Browser:   http://{self._host}:{http_port}")
        print("  Waiting for browser connection...")

        async with websockets.serve(self._handler, self._host, self._port):
            await asyncio.Future()

    @staticmethod
    def _start_http_server(html: str, host: str, port: int) -> None:
        """Start a background HTTP server to serve the browser UI.
        启动后台 HTTP 服务器提供浏览器 UI。"""
        html_bytes = html.encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_bytes)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        server = HTTPServer((host, port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

    async def _handler(self, websocket: Any) -> None:
        """Handle a single WebSocket connection.
        处理单个 WebSocket 连接。"""
        self._ws = websocket
        self._wire_callbacks()
        await self._send("info", message="Connected to Mini-Code-Agent")

        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "user_input":
                    text = msg.get("text", "").strip()
                    if not text:
                        continue
                    if text.lower() in ("exit", "quit"):
                        await self._send("info", message="Goodbye!")
                        break
                    if self._app.slash_commands.is_slash_command(text):
                        try:
                            result = await self._app.slash_commands.execute(text, self._app)
                            if result:
                                await self._send("info", message=result)
                        except SystemExit:
                            break
                        continue
                    await self._send("turn_start")
                    self._running_turn = asyncio.create_task(self._app._handle_turn(text))
                    try:
                        await self._running_turn
                    except asyncio.CancelledError:
                        await self._send("info", message="(cancelled)")
                    except Exception as e:
                        await self._send("error", message=f"Error: {str(e)}")
                    finally:
                        self._running_turn = None
                        await self._send("turn_end")

                elif msg_type == "cancel":
                    if self._running_turn and not self._running_turn.done():
                        self._app.agent_loop.cancel()
                        self._running_turn.cancel()

                elif msg_type == "permission_response":
                    req_id = msg.get("id", "")
                    decision = msg.get("decision", "n")
                    future = self._pending_confirms.pop(req_id, None)
                    if future and not future.done():
                        if decision == "y":
                            future.set_result(True)
                        elif decision == "a":
                            future.set_result("always")
                        else:
                            future.set_result(False)
        except Exception:
            pass
        finally:
            self._ws = None

    def _wire_callbacks(self) -> None:
        """Replace AgentLoop and PermissionManager callbacks to send over WS.
        替换 AgentLoop 和 PermissionManager 的回调为 WS 发送。"""
        loop = self._app.agent_loop

        def on_stream_start() -> None:
            asyncio.ensure_future(self._send("stream_start"))

        def on_stream_delta(delta: str) -> None:
            asyncio.ensure_future(self._send("stream_text", delta=delta))

        def on_stream_end() -> None:
            asyncio.ensure_future(self._send("stream_end"))

        def on_tool_start(tc: Any) -> None:
            try:
                args_preview = json.dumps(tc.arguments, ensure_ascii=False)[:200]
            except (TypeError, ValueError):
                args_preview = str(tc.arguments)[:200]
            asyncio.ensure_future(self._send("tool_call", name=tc.name, args=args_preview))

        def on_tool_end(tr: Any) -> None:
            asyncio.ensure_future(
                self._send(
                    "tool_result",
                    name=tr.name,
                    output=tr.output[:500],
                    is_error=tr.is_error,
                )
            )

        def on_thinking_delta(delta: str) -> None:
            asyncio.ensure_future(self._send("thinking_delta", delta=delta))

        loop.on_stream_start = on_stream_start
        loop.on_stream_delta = on_stream_delta
        loop.on_stream_end = on_stream_end
        loop.on_thinking_delta = on_thinking_delta
        loop.on_tool_start = on_tool_start
        loop.on_tool_end = on_tool_end

        self._app.permission_manager.confirm_callback = self._confirm_via_ws

    async def _confirm_via_ws(self, prompt: str) -> bool | str:
        """Send a permission request and await the browser's response.
        发送权限请求并等待浏览器的响应。"""
        req_id = uuid.uuid4().hex[:8]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_confirms[req_id] = future
        await self._send("permission_request", id=req_id, prompt=prompt)
        return await future

    def _safe_send(self, event_type: str, **data: Any) -> None:
        """Non-async wrapper for _send, used by RemoteTerminalAdapter.
        用于 RemoteTerminalAdapter 的非异步包装器。"""
        asyncio.ensure_future(self._send(event_type, **data))

    async def _send(self, event_type: str, **data: Any) -> None:
        """Send a NDJSON event to the connected browser.
        发送 NDJSON 事件到浏览器。"""
        if self._ws is None:
            return
        event = {"type": event_type, **data}
        try:
            await self._ws.send(json.dumps(event, ensure_ascii=False))
        except Exception:
            pass
