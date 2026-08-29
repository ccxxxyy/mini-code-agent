"""WebSocket server for remote/browser mode.
远程/浏览器模式的 WebSocket 服务器。

Starts a WebSocket server that replaces the terminal UI with NDJSON events
over the wire. The browser connects, sends user_input messages, and receives
streaming text, tool calls, and permission requests.
启动 WebSocket 服务器替代终端 UI，通过 NDJSON 事件进行通信。浏览器连接后
发送 user_input 消息，接收流式文本、工具调用和权限请求。
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mini_agent.app import Application

logger = logging.getLogger(__name__)


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
        self._pending_prompts: dict[str, str] = {}
        self._disconnect_timeout_task: asyncio.Task | None = None
        self._running_turn: asyncio.Task | None = None

        # Wrap terminal to intercept UI calls and send to WebSocket
        from mini_agent.remote.terminal import RemoteTerminalAdapter

        self._original_terminal = app.terminal
        app.terminal = RemoteTerminalAdapter(app.terminal, self._safe_send)  # type: ignore[assignment]

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
            print("  Auth:      token required (constant-time comparison)")
            print("  Warning:   token appears in the URL -- it may be saved in browser")
            print("             history, server logs, or proxy logs. Use --remote-token")
            print("             only on trusted networks; for public exposure, add a")
            print("             reverse proxy with TLS (e.g. nginx + Let's Encrypt).")
        else:
            print(f"  Browser:   http://{self._host}:{self._port}")
        print("  Waiting for browser connection...")

        await self._restore_last_session()
        # Background memory consolidation: same gated task as terminal mode
        # (tech-notes §111) 后台记忆整固：与终端模式共用同一门槛化任务
        self._app.start_background_consolidation()

        async with websockets.serve(
            self._handler,
            self._host,
            self._port,
            process_request=self._process_http,
        ):
            asyncio.create_task(self._ping_loop())
            try:
                await asyncio.Future()
            finally:
                await self._app.stop_background_consolidation()
                await self._save_on_shutdown()

    async def _restore_last_session(self) -> None:
        """Auto-restore the newest crashed session of this project. No prompt:
        the server starts with no client to ask (terminal mode asks instead).
        Unwanted restore: /session load <id> switches away losslessly;
        /fork + /clear starts fresh keeping the history (a bare /clear would
        let autosave overwrite the old history under the same session id).
        自动恢复本项目最新未正常关闭的会话。不询问：服务器启动时无客户端
        可问（终端模式是询问式）。误恢复：/session load 无损切走；
        /fork + /clear 保留历史另起（裸 /clear 会让自动保存以同会话 ID
        覆盖旧历史）。"""
        app = self._app
        mem = app.config.memory
        if mem.session_cleanup_days > 0 or mem.crashed_session_cleanup_days > 0:
            try:
                await app.session_store.cleanup_stale(
                    mem.session_cleanup_days, mem.crashed_session_cleanup_days
                )
            except Exception:
                logger.debug("stale session cleanup failed", exc_info=True)
        latest = await app._find_crashed_session()
        if latest is None:
            return
        loaded = await app.session_store.load(latest["session_id"])
        if loaded is None:
            return
        loaded.metadata.closed_cleanly = False  # live again 恢复后重新算进行中
        app._adopt_session(loaded)
        print(
            f"  Restored session {latest['session_id'][:12]}... "
            f"({len(loaded.conversation.messages)} messages)",
            flush=True,
        )

    async def _save_on_shutdown(self) -> None:
        """Mark the session cleanly closed and persist it (mirrors the
        terminal path in Application.run()'s finally).
        标记会话正常关闭并持久化（镜像 Application.run() finally 的终端路径）。"""
        self._app.session.metadata.closed_cleanly = True
        try:
            await self._app._autosave(force=True)
        except Exception:
            logger.debug("shutdown session save failed", exc_info=True)

    def _process_http(self, connection: Any, request: Any) -> Any:
        """Serve HTML for GET /, let /ws proceed to WebSocket upgrade."""
        import websockets as _ws
        from websockets.http11 import Response

        # request.path includes query string (e.g. "/?token=xxx"), so
        # split on "?" and compare only the path component.
        # request.path 含查询字符串（如 "/?token=xxx"），只取路径部分比较。
        raw_path = request.path.split("?", 1)[0]
        if raw_path == "/":
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
        if not raw_path.startswith("/ws"):
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
                if msg.get("type") != "auth" or not hmac.compare_digest(
                    msg.get("token", ""), self._token
                ):
                    await websocket.send(
                        json.dumps({"type": "error", "message": "Authentication failed"})
                    )
                    await websocket.close()
                    return
            except Exception:
                logger.warning("WS auth failed", exc_info=True)
                await websocket.close()
                return

        self._clients.add(websocket)
        if self._disconnect_timeout_task and not self._disconnect_timeout_task.done():
            self._disconnect_timeout_task.cancel()
            self._disconnect_timeout_task = None
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
            logger.debug("WS welcome send failed", exc_info=True)
            pass
        await self._replay_history(websocket)
        await self._send_commands(websocket)
        await self._replay_pending_confirms(websocket)

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
                        session_before = self._app.session
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
                        await self._app._autosave()
                        # /session load or /fork swapped the session: reset the
                        # browser chat area and replay the adopted history
                        # (connect-time replay never reruns on its own).
                        # /session load 或 /fork 换了会话：重置浏览器聊天区并
                        # 重放采用的历史（连接时的重放不会自己重跑）。
                        if self._app.session is not session_before:
                            await self._ws_send("history_reset")
                            for ws in list(self._clients):
                                await self._replay_history(ws)
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
                        # Mirror the terminal path: force-save after every
                        # turn so a hard kill never loses the last exchange
                        # 镜像终端路径：每轮强制保存，硬杀不丢最后一轮
                        await self._app._autosave(force=True)

                elif msg_type == "cancel":
                    self._app.agent_loop.cancel()

                elif msg_type == "permission":
                    req_id = msg.get("id", "")
                    decision = msg.get("decision", "n")
                    self._resolve_permission(req_id, decision)
        except Exception:
            logger.debug("WS main loop error", exc_info=True)
            pass
        finally:
            self._clients.discard(websocket)
            if not self._clients and self._pending_confirms:
                self._disconnect_timeout_task = asyncio.create_task(self._disconnect_timeout())

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
                logger.debug("WS replay send failed", exc_info=True)
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
            logger.debug("WS commands send failed", exc_info=True)
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
        self._pending_prompts[req_id] = prompt
        self._event_loop = loop
        await self._ws_send("permission_request", id=req_id, prompt=prompt)
        return await future

    def _resolve_permission(self, req_id: str, decision: str) -> None:
        """Resolve a permission Future (called from WS handler)."""
        future = self._pending_confirms.pop(req_id, None)
        self._pending_prompts.pop(req_id, None)
        if not future or future.done():
            return
        if decision == "y":
            future.set_result(True)
        elif decision == "a":
            future.set_result("always")
        else:
            future.set_result(False)

    async def _disconnect_timeout(self, timeout: float = 120.0) -> None:
        """Deny all pending permissions if no client reconnects within timeout.
        若超时内无客户端重连，拒绝所有待处理权限请求。"""
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return
        for req_id, future in list(self._pending_confirms.items()):
            if not future.done():
                future.set_result(False)
        self._pending_confirms.clear()
        self._pending_prompts.clear()

    async def _replay_pending_confirms(self, websocket: Any) -> None:
        """Re-send pending permission requests to a newly connected client.
        向新连接的客户端重发待处理的权限请求。"""
        for req_id, prompt in list(self._pending_prompts.items()):
            if req_id in self._pending_confirms and not self._pending_confirms[req_id].done():
                try:
                    await websocket.send(
                        json.dumps(
                            {"type": "permission_request", "id": req_id, "prompt": prompt},
                            ensure_ascii=False,
                        )
                    )
                except Exception:
                    logger.debug("WS replay pending confirm failed", exc_info=True)

    def _safe_send(self, event_type: str, **data: Any) -> None:
        """Non-async wrapper used by RemoteTerminalAdapter.
        RemoteTerminalAdapter 用的非异步包装器。"""
        asyncio.get_running_loop().create_task(self._ws_send(event_type, **data))
