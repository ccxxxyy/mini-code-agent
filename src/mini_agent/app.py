"""Application orchestrator -- wires all layers together. 应用编排器——将所有层级组装在一起。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mini_agent.core.agent_loop import AgentLoop
from mini_agent.events.bus import EventBus
from mini_agent.extensions.builtin_commands import register_builtin_commands
from mini_agent.extensions.skills import SkillRegistry
from mini_agent.extensions.slash_commands import SlashCommandRegistry
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.memory.compressor import Compressor
from mini_agent.memory.context import ContextManager
from mini_agent.memory.session_store import SessionStore
from mini_agent.models.config import AgentConfig
from mini_agent.models.events import (
    SessionEndEvent,
    SessionStartEvent,
    UserMessageEvent,
)
from mini_agent.models.message import Message, Role
from mini_agent.models.session import Session
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin import ALL_BUILTIN_TOOLS
from mini_agent.tools.hooks import HookManager
from mini_agent.ui.terminal import Terminal

SYSTEM_PROMPT = """You are a helpful coding agent running in a terminal.
Working directory: {working_dir}
Platform: {platform}
Shell: {shell}

You have access to tools for reading/writing/editing files, running shell commands, \
and searching the codebase (glob for file names, grep for file contents).

Guidelines:
- Use tools to accomplish tasks. Don't guess file contents -- read them.
- Break complex tasks into steps: search, read, then modify.
- Be concise in your final answers. Use markdown formatting.
- When editing files, read them first to understand the context.
- Report errors honestly. If a tool fails, explain what went wrong.
- IMPORTANT: Use platform-appropriate shell commands. \
On Windows use dir/type/findstr/where, NOT ls/cat/grep/which."""


class Application:
    """Main application -- agent conversation loop. 主应用——Agent 对话循环。"""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.event_bus = EventBus()
        self.terminal = Terminal()
        self.session = Session()

        working_dir = Path.cwd()
        platform = f"{sys.platform} ({'Windows' if sys.platform == 'win32' else 'Unix'})"
        shell = os.environ.get("SHELL", "cmd.exe" if sys.platform == "win32" else "/bin/bash")
        self.session.conversation.system_prompt = SYSTEM_PROMPT.format(
            working_dir=working_dir,
            platform=platform,
            shell=shell,
        )
        self.session.metadata.model = config.llm.model
        self.session.metadata.project_dir = working_dir

        self._llm = ProviderRegistry.create(config.llm)

        # Tool registry with all builtin tools 包含所有内置工具的工具 registry
        self.tool_registry = ToolRegistry()
        for tool_class in ALL_BUILTIN_TOOLS:
            tool = tool_class()
            if tool.schema.name in config.tools.enabled_tools:
                self.tool_registry.register(tool)

        tool_context = ToolContext(
            working_dir=working_dir,
            session=self.session,
            event_bus=self.event_bus,
            config=config,
        )

        # Security: path guard + permission manager wired to terminal confirm
        # 安全：路径守卫 + 权限管理器接入终端确认
        path_guard = PathGuard(
            tool_config=config.tools,
            security_config=config.security,
            project_dir=working_dir,
        )
        self.permission_manager = PermissionManager(
            config=config.security,
            path_guard=path_guard,
            confirm_callback=self.terminal.confirm,
        )
        self.hook_manager = HookManager()

        # Memory: context manager + compressor + session store
        # 记忆：上下文管理器 + 压缩器 + 会话存储
        self.context_manager = ContextManager(config.memory)
        compressor = Compressor()
        self.context_manager.set_compressor(compressor)
        self.session_store = SessionStore()

        self.agent_loop = AgentLoop(
            llm=self._llm,
            tool_registry=self.tool_registry,
            event_bus=self.event_bus,
            config=config,
            tool_context=tool_context,
            permission_manager=self.permission_manager,
            hook_manager=self.hook_manager,
            context_manager=self.context_manager,
        )

        # Skill system
        self.skill_registry = SkillRegistry(skill_dirs=[Path(d) for d in config.skill_dirs])
        self.skill_registry.load_all()

        # Slash commands
        self.slash_commands = SlashCommandRegistry()
        register_builtin_commands(self)

        # Wire slash command completions to terminal 将斜杠命令补全接入终端
        self.terminal.set_slash_commands(
            [(c.name, c.description) for c in self.slash_commands.list_commands()]
        )

        # Wire agent loop callbacks to terminal rendering 将 Agent 循环回调接入终端渲染
        self.agent_loop.on_stream_start = self.terminal.start_stream
        self.agent_loop.on_stream_delta = self.terminal.feed_stream
        self.agent_loop.on_stream_end = lambda: self.terminal.finish_stream()
        self.agent_loop.on_tool_start = lambda tc: self.terminal.show_tool_call(
            tc.name, tc.arguments
        )
        self.agent_loop.on_tool_end = lambda tr: self.terminal.show_tool_result(
            tr.name, tr.output, tr.is_error
        )

    async def run(self) -> None:
        self.terminal.show_welcome()
        await self.event_bus.emit(SessionStartEvent(session_id=self.session.metadata.session_id))

        try:
            while True:
                try:
                    user_input = await self.terminal.get_user_input()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    break

                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.lower() in ("exit", "quit"):
                    break

                # Slash command dispatch 斜杠命令分发
                if self.slash_commands.is_slash_command(user_input):
                    try:
                        result = await self.slash_commands.execute(user_input, self)
                        if result:
                            self.terminal.console.print()
                            self.terminal.console.print(result)
                            self.terminal.console.print()
                    except SystemExit:
                        break
                    continue

                await self._handle_turn(user_input)
        finally:
            await self.event_bus.emit(SessionEndEvent(session_id=self.session.metadata.session_id))
            self.terminal.show_info("Goodbye!")

    async def _handle_turn(self, user_input: str) -> None:
        await self.event_bus.emit(UserMessageEvent(content=user_input))

        self.session.conversation.append(Message(role=Role.USER, content=user_input))
        self.session.metadata.total_turns += 1

        try:
            await self.agent_loop.run(self.session.conversation)
            turn_tokens = self.agent_loop.last_turn_tokens
            self.session.metadata.total_tokens_used += turn_tokens
            self.terminal.show_info(
                f"tokens: {turn_tokens} this turn / {self.session.metadata.total_tokens_used} total"
            )
            self.terminal.console.print()
        except KeyboardInterrupt:
            self.agent_loop.cancel()
            self.terminal.show_info("Interrupted.")
            self.terminal.console.print()
        except Exception as e:
            self.terminal.show_error(str(e))
