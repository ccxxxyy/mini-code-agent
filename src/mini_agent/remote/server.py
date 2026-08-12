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


def _get_html(port: int, version: str = "", model: str = "") -> str:
    from mini_agent.remote.web_ui import build_html

    return build_html(port, version=version, model=model)


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
        version = getattr(self._app, "version", "") or "1.0.0"
        model = self._app.agent_loop.model_name or "unknown"
        html = _get_html(self._port, version=version, model=model)
        self._start_http_server(html, self._host, http_port)

        print("Mini-Code-Agent remote mode")
        print(f"  WebSocket: ws://{self._host}:{self._port}")
        print(f"  Browser:   http://{self._host}:{http_port}")
        print("  Waiting for browser connection...")

        async with websockets.serve(self._handler, self._host, self._port):
            await asyncio.Future()

    def _start_http_server(self, html: str, host: str, port: int) -> None:
        """Start a background HTTP server to serve the browser UI.
        启动后台 HTTP 服务器提供浏览器 UI。"""
        html_bytes = html.encode("utf-8")
        remote_server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store")
                self.end_headers()
                self.wfile.write(html_bytes)

            def do_POST(self) -> None:
                if self.path == "/cancel":
                    remote_server._app.agent_loop.cancel()
                    self._ok()
                elif self.path.startswith("/permission"):
                    import urllib.parse as up

                    qs = up.parse_qs(up.urlparse(self.path).query)
                    req_id = qs.get("id", [""])[0]
                    decision = qs.get("decision", ["n"])[0]
                    remote_server._resolve_permission(req_id, decision)
                    self._ok()
                else:
                    self.send_response(404)
                    self.end_headers()

            def _ok(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"ok")

            def do_OPTIONS(self) -> None:
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST")
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:
                pass

        server = HTTPServer((host, port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

    async def _ws_send(self, event_type: str, **data: Any) -> None:
        """Send via the latest active WebSocket connection.
        通过最新的活跃 WebSocket 连接发送。"""
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps({"type": event_type, **data}, ensure_ascii=False))
        except Exception:
            pass

    async def _handler(self, websocket: Any) -> None:
        """Handle a single WebSocket connection.
        处理单个 WebSocket 连接。"""
        self._ws = websocket
        self._wire_callbacks()

        model = self._app.agent_loop.model_name or "unknown"
        provider = self._app.config.llm.provider or "openai"
        profiles = self._app.config.llm_profiles
        model_count = max(1, len(profiles))
        switch_hint = f"  |  {model_count} models, /model to switch" if model_count > 1 else ""
        await self._ws_send(
            "info",
            message=(f"Welcome! Type a message to start.\nLLM: {model} ({provider}){switch_hint}"),
        )
        await self._replay_history()

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
                        await self._ws_send("info", message="Goodbye!")
                        break
                    if self._app.slash_commands.is_slash_command(text):
                        try:
                            result = await self._app.slash_commands.execute(text, self._app)
                            if result:
                                await self._ws_send("info", message=result)
                        except SystemExit:
                            break
                        continue
                    await self._ws_send("turn_start")
                    try:
                        await self._app._handle_turn(text)
                    except Exception as e:
                        await self._ws_send("error", message=f"Error: {str(e)}")
                    finally:
                        await self._ws_send("turn_end")

                elif msg_type == "cancel":
                    self._app.agent_loop.cancel()
        except Exception:
            pass

    async def _replay_history(self) -> None:
        """Send existing conversation history to a newly connected browser.
        向新连接的浏览器发送已有的对话历史。"""
        from mini_agent.models.message import Role

        messages = self._app.session.conversation.messages
        if not messages:
            return
        for msg in messages:
            if msg.role == Role.USER:
                await self._ws_send("history_user", text=msg.content)
            elif msg.role == Role.ASSISTANT:
                if msg.content:
                    await self._ws_send("history_assistant", text=msg.content)
                for tc in msg.tool_calls:
                    try:
                        args = json.dumps(tc.arguments, ensure_ascii=False)[:200]
                    except (TypeError, ValueError):
                        args = str(tc.arguments)[:200]
                    await self._ws_send("history_tool_call", name=tc.name, args=args)
            elif msg.role == Role.TOOL and msg.tool_result:
                tr = msg.tool_result
                await self._ws_send(
                    "history_tool_result",
                    name=tr.name,
                    output=tr.output[:500],
                    is_error=tr.is_error,
                )

    def _wire_callbacks(self) -> None:
        """Replace AgentLoop and PermissionManager callbacks.
        回调通过 self._ws_send 发送，始终用最新连接。"""
        al = self._app.agent_loop

        def fire(coro: Any) -> None:
            asyncio.get_running_loop().create_task(coro)

        al.on_stream_start = lambda: fire(self._ws_send("stream_start"))
        al.on_stream_delta = lambda d: fire(self._ws_send("stream_text", delta=d))
        al.on_stream_end = lambda: fire(self._ws_send("stream_end"))
        al.on_thinking_delta = lambda d: fire(self._ws_send("thinking_delta", delta=d))

        def on_tool_start(tc: Any) -> None:
            try:
                ap = json.dumps(tc.arguments, ensure_ascii=False)[:200]
            except (TypeError, ValueError):
                ap = str(tc.arguments)[:200]
            fire(self._ws_send("tool_call", name=tc.name, args=ap))

        def on_tool_end(tr: Any) -> None:
            fire(
                self._ws_send(
                    "tool_result",
                    name=tr.name,
                    output=tr.output[:500],
                    is_error=tr.is_error,
                )
            )

        al.on_tool_start = on_tool_start
        al.on_tool_end = on_tool_end
        self._app.permission_manager._confirm = self._confirm_via_ws

    async def _confirm_via_ws(self, prompt: str) -> bool | str:
        """Send a permission request and await the browser's response.
        发送权限请求并等待浏览器的响应。"""
        req_id = uuid.uuid4().hex[:8]
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_confirms[req_id] = future
        self._event_loop = loop
        ws = self._ws
        if ws:
            try:
                event = json.dumps(
                    {
                        "type": "permission_request",
                        "id": req_id,
                        "prompt": prompt,
                    },
                    ensure_ascii=False,
                )
                await ws.send(event)
            except Exception:
                pass
        return await future

    def _resolve_permission(self, req_id: str, decision: str) -> None:
        """Called from HTTP thread to resolve a permission Future.
        从 HTTP 线程调用，解析权限 Future。"""
        future = self._pending_confirms.pop(req_id, None)
        if not future or future.done():
            return
        loop = getattr(self, "_event_loop", None)
        if not loop:
            return
        if decision == "y":
            loop.call_soon_threadsafe(future.set_result, True)
        elif decision == "a":
            loop.call_soon_threadsafe(future.set_result, "always")
        else:
            loop.call_soon_threadsafe(future.set_result, False)

    def _safe_send(self, event_type: str, **data: Any) -> None:
        """Non-async wrapper used by RemoteTerminalAdapter.
        RemoteTerminalAdapter 用的非异步包装器。"""
        asyncio.get_running_loop().create_task(self._ws_send(event_type, **data))
