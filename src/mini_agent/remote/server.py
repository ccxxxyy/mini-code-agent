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
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mini_agent.app import Application


def _get_html(port: int, version: str = "", model: str = "") -> str:
    from mini_agent.remote.web_ui import build_html

    return build_html(port, version=version, model=model)


class RemoteServer:
    """WebSocket server bridging the agent to a browser UI.
    连接 Agent 和浏览器 UI 的 WebSocket 服务器。"""

    def __init__(
        self,
        app: Application,
        host: str = "localhost",
        port: int = 8765,
        token: str = "",
    ) -> None:
        self._app = app
        self._host = host
        self._port = port
        self._token = token
        self._clients: set[Any] = set()
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

        version = getattr(self._app, "version", "") or "1.0.0"
        model = self._app.agent_loop.model_name or "unknown"
        self._html_bytes = _get_html(self._port, version=version, model=model).encode("utf-8")

        print("Mini-Code-Agent remote mode")
        if self._token:
            print(f"  Browser:   http://{self._host}:{self._port}?token={self._token}")
            print("  Auth:      token required")
        else:
            print(f"  Browser:   http://{self._host}:{self._port}")
        print("  Waiting for browser connection...")

        async with websockets.serve(
            self._handler,
            self._host,
            self._port,
            process_request=self._process_http,
        ):
            asyncio.create_task(self._ping_loop())
            await asyncio.Future()

    def _process_http(self, connection: Any, request: Any) -> Any:
        """Serve HTML for GET /, let /ws proceed to WebSocket upgrade."""
        import websockets as _ws
        from websockets.http11 import Response

        if request.path == "/":
            return Response(
                200,
                "OK",
                _ws.Headers(
                    {
                        "Content-Type": "text/html; charset=utf-8",
                        "Cache-Control": "no-cache, no-store",
                    }
                ),
                self._html_bytes,
            )
        if not request.path.startswith("/ws"):
            return Response(404, "Not Found", _ws.Headers(), b"Not Found")
        return None

    async def _ping_loop(self) -> None:
        """Send application-level ping every 10 seconds."""
        while True:
            await asyncio.sleep(10)
            if self._clients:
                await self._ws_send("ping")

    async def _ws_send(self, event_type: str, **data: Any) -> None:
        """Broadcast to all connected clients.
        广播给所有已连接的客户端。"""
        if not self._clients:
            return
        payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
        dead: list[Any] = []
        for ws in list(self._clients):
            try:
                await ws.send(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def _handler(self, websocket: Any) -> None:
        """Handle a single WebSocket connection.
        处理单个 WebSocket 连接。"""
        if self._token:
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=10)
                msg = json.loads(raw)
                if msg.get("type") != "auth" or msg.get("token") != self._token:
                    await websocket.send(
                        json.dumps({"type": "error", "message": "Authentication failed"})
                    )
                    await websocket.close()
                    return
            except Exception:
                await websocket.close()
                return

        self._clients.add(websocket)
        self._wire_callbacks()

        model = self._app.agent_loop.model_name or "unknown"
        provider = self._app.config.llm.provider or "openai"
        profiles = self._app.config.llm_profiles
        model_count = max(1, len(profiles))
        switch_hint = f"  |  {model_count} models, /model to switch" if model_count > 1 else ""
        try:
            await websocket.send(
                json.dumps(
                    {
                        "type": "info",
                        "message": f"Welcome! Type a message to start.\n"
                        f"LLM: {model} ({provider}){switch_hint}",
                    },
                    ensure_ascii=False,
                )
            )
        except Exception:
            pass
        await self._replay_history(websocket)
        await self._send_commands(websocket)

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
                                from mini_agent.extensions.slash_commands import (
                                    MARKDOWN_RESULT,
                                )

                                await self._ws_send(
                                    "info", message=result.removeprefix(MARKDOWN_RESULT)
                                )
                            parts = text.strip().split(maxsplit=1)
                            if parts[0].lower() == "/theme" and len(parts) > 1:
                                t = parts[1].strip().lower()
                                if t in ("light", "dark"):
                                    await self._ws_send("theme", theme=t)
                        except SystemExit:
                            break
                        continue
                    await self._ws_send("user_message", text=text)
                    await self._ws_send("turn_start")
                    _turn_t0 = time.monotonic()
                    try:
                        await self._app._handle_turn(text)
                    except Exception as e:
                        await self._ws_send("error", message=f"Error: {str(e)}")
                    finally:
                        al = self._app.agent_loop
                        elapsed = time.monotonic() - _turn_t0
                        await self._ws_send(
                            "turn_end",
                            tokens=al.last_turn_tokens,
                            iterations=al._state.iteration,
                            elapsed=elapsed,
                        )

                elif msg_type == "cancel":
                    self._app.agent_loop.cancel()

                elif msg_type == "permission":
                    req_id = msg.get("id", "")
                    decision = msg.get("decision", "n")
                    self._resolve_permission(req_id, decision)
        except Exception:
            pass
        finally:
            self._clients.discard(websocket)

    async def _replay_history(self, websocket: Any) -> None:
        """Send existing conversation history to a single newly connected client."""
        from mini_agent.models.message import Role

        messages = self._app.session.conversation.messages
        if not messages:
            return

        async def _send(event_type: str, **data: Any) -> None:
            try:
                await websocket.send(json.dumps({"type": event_type, **data}, ensure_ascii=False))
            except Exception:
                pass

        for msg in messages:
            if msg.role == Role.USER:
                await _send("history_user", text=msg.content)
            elif msg.role == Role.ASSISTANT:
                if msg.content:
                    await _send("history_assistant", text=msg.content)
                for tc in msg.tool_calls:
                    try:
                        args = json.dumps(tc.arguments, ensure_ascii=False)[:200]
                    except (TypeError, ValueError):
                        args = str(tc.arguments)[:200]
                    await _send("history_tool_call", name=tc.name, args=args)
            elif msg.role == Role.TOOL and msg.tool_result:
                tr = msg.tool_result
                await _send(
                    "history_tool_result",
                    name=tr.name,
                    output=tr.output[:500],
                    is_error=tr.is_error,
                )

    async def _send_commands(self, websocket: Any) -> None:
        """Send the full slash command list to a newly connected client."""
        cmds = sorted(
            [[f"/{c.name}", c.description] for c in self._app.slash_commands.list_commands()],
            key=lambda c: c[0],
        )
        try:
            await websocket.send(
                json.dumps({"type": "commands", "commands": cmds}, ensure_ascii=False)
            )
        except Exception:
            pass

    def _wire_callbacks(self) -> None:
        """Replace AgentLoop and PermissionManager callbacks.
        回调通过 self._ws_send 发送，始终用最新连接。"""
        al = self._app.agent_loop

        def fire(coro: Any) -> None:
            asyncio.get_running_loop().create_task(coro)

        al.on_stream_start = lambda: fire(self._ws_send("stream_start"))
        al.on_stream_delta = lambda d: fire(self._ws_send("stream_text", delta=d))
        al.on_stream_end = lambda ft: fire(self._ws_send("stream_end", full_text=ft))
        al.on_thinking_delta = lambda d: fire(self._ws_send("thinking_delta", delta=d))

        def on_tool_start(tc: Any) -> None:
            try:
                ap = json.dumps(tc.arguments, ensure_ascii=False)[:200]
            except (TypeError, ValueError):
                ap = str(tc.arguments)[:200]
            fire(self._ws_send("tool_call", name=tc.name, args=ap))

        def on_tool_end(tr: Any, duration_ms: float = 0.0) -> None:
            elapsed = ""
            if duration_ms >= 1000:
                elapsed = f"{duration_ms / 1000:.1f}s"
            elif duration_ms > 0:
                elapsed = f"{duration_ms:.0f}ms"
            fire(
                self._ws_send(
                    "tool_result",
                    name=tr.name,
                    output=tr.output[:500],
                    is_error=tr.is_error,
                    elapsed=elapsed,
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
        await self._ws_send("permission_request", id=req_id, prompt=prompt)
        return await future

    def _resolve_permission(self, req_id: str, decision: str) -> None:
        """Resolve a permission Future (called from WS handler)."""
        future = self._pending_confirms.pop(req_id, None)
        if not future or future.done():
            return
        if decision == "y":
            future.set_result(True)
        elif decision == "a":
            future.set_result("always")
        else:
            future.set_result(False)

    def _safe_send(self, event_type: str, **data: Any) -> None:
        """Non-async wrapper used by RemoteTerminalAdapter.
        RemoteTerminalAdapter 用的非异步包装器。"""
        asyncio.get_running_loop().create_task(self._ws_send(event_type, **data))
