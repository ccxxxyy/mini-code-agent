"""Context window manager -- tracks token usage and triggers compression.
上下文窗口管理器——跟踪 token 使用量并触发压缩。"""

from __future__ import annotations

import logging

from mini_agent.llm.token_counter import count_tokens, truncate_to_tokens
from mini_agent.memory.compressor import SlidingWindow
from mini_agent.models.config import MemoryConfig
from mini_agent.models.message import Conversation, Message, Role

_MAX_RECOVERY_FILES = 5
_RECOVERY_TOKENS_PER_FILE = 5000
_MAX_TASK_CHARS = 2000

logger = logging.getLogger(__name__)


class ContextManager:
    """Tracks and manages the conversation context window. 跟踪并管理对话上下文窗口。"""

    def __init__(self, config: MemoryConfig) -> None:
        self._max_tokens = config.context_window
        self._threshold = config.compression_threshold
        self._hard_threshold = config.hard_compression_threshold
        self._total_tokens = 0
        self._compressor = None  # set via set_compressor() after init
        # 初始化后通过 set_compressor() 设置
        # Circuit breaker: stop retrying compression after N consecutive
        # ineffective attempts (tokens did not decrease)
        # 熔断器：连续 N 次压缩无效后停止重试
        self._compress_failures: int = 0
        self._max_compress_failures: int = config.compress_max_failures
        # Warn only once when the breaker opens -- check_and_compress runs
        # twice per iteration, repeating the warning floods the console
        # 熔断器开启只警告一次——每轮迭代检查两次，重复警告会刷屏
        self._breaker_warned: bool = False
        # Ordered, deduplicated list of files read this session -- re-injected
        # after compression so the LLM does not forget and re-read them
        # 本会话已读文件（保序去重）——压缩后重新注入，防 LLM 忘记后重读
        self._read_files: dict[str, str | None] = {}
        self._last_user_request: str = ""
        # Skill state provider: returns (invoked_names, active_names).
        # A callback keeps the dependency direction clean -- the memory
        # layer must not import the extensions layer.
        # 技能状态提供者：返回（调用历史, 当前激活）。用回调保持依赖方向
        # 干净——记忆层不 import 扩展层。
        self._skill_provider = None
        # Skill state read from an adopted boundary, for the app layer to
        # push back into SkillRegistry (this class never touches the registry)
        # 从边界恢复的技能状态，供 app 层写回 SkillRegistry
        # （本类不反向操作 registry）
        self._adopted_skills: tuple[list[str], list[str]] | None = None
        # API usage anchor: the LLM-reported total is authoritative for the
        # whole conversation up to the anchored message (it even includes
        # tool schemas, which estimation cannot see). Messages after the
        # anchor are estimated. Identity check auto-invalidates on compression.
        # API usage 锚点：LLM 返回的总量是锚点消息之前整个对话的权威计数
        # （连估算看不到的工具 schema 都包含）。锚点之后的消息用估算。
        # 对象身份检查让压缩重排后锚点自动失效。
        self._api_total = 0
        self._api_index = -1
        self._api_anchor: Message | None = None

    def set_compressor(self, compressor) -> None:
        """Inject the compressor (avoids circular import at init time).
        注入压缩器（避免初始化时的循环导入）。"""
        self._compressor = compressor

    def set_skill_provider(self, provider) -> None:
        """Inject a callable returning (invoked_names, active_names).
        注入返回（技能调用历史, 当前激活技能）的可调用对象。"""
        self._skill_provider = provider

    def _skill_state(self) -> tuple[list[str], list[str]]:
        if self._skill_provider is None:
            return [], []
        try:
            invoked, active = self._skill_provider()
            return list(invoked), list(active)
        except Exception:
            return [], []

    @property
    def adopted_skills(self) -> tuple[list[str], list[str]] | None:
        """Skill state restored from a compact boundary, or None.
        从压缩边界恢复的技能状态（调用历史, 激活集合），无则 None。"""
        return self._adopted_skills

    def reset_state(self) -> None:
        """Clear per-session state before adopting another session. Without
        this, a session adopted WITHOUT a compact boundary inherits the
        previous session's read-file cache and skill state (stale-state bug).
        采用另一会话前清空会话级状态。不清空的话，无压缩边界的被采用
        会话会继承上一会话的已读文件缓存与技能状态（陈旧状态 bug）。"""
        self._read_files.clear()
        self._last_user_request = ""
        self._adopted_skills = None

    def record_file_read(self, path: str, content: str = "") -> None:
        if content:
            self._read_files[path] = truncate_to_tokens(content, _RECOVERY_TOKENS_PER_FILE)
        elif path not in self._read_files:
            self._read_files[path] = None

    @property
    def read_files(self) -> list[str]:
        return list(self._read_files)

    def record_api_usage(self, conversation: Conversation, usage) -> None:
        """Anchor the authoritative API-reported token total at the newest message.
        将 API 返回的权威 token 总量锚定在最新一条消息上。

        usage.prompt_tokens covers everything the API actually billed for the
        conversation so far (system prompt, all messages, tool schemas);
        adding completion gives the exact total through the last message.
        prompt_tokens 覆盖 API 实际计费的全部内容（系统提示、所有消息、
        工具 schema），加上 completion 即截至最新消息的精确总量。"""
        if usage.prompt_tokens <= 0 or not conversation.messages:
            return
        self._api_total = usage.total_tokens or (usage.prompt_tokens + usage.completion_tokens)
        self._api_index = len(conversation.messages) - 1
        self._api_anchor = conversation.messages[-1]

    def _invalidate_api_anchor(self) -> None:
        self._api_total = 0
        self._api_index = -1
        self._api_anchor = None

    def count_message(self, message: Message) -> int:
        """Count and cache tokens for a message. 统计并缓存消息的 token 数。

        Accounts for per-role separators (+4) and per-tool-call overhead (+3 each,
        for function name/arguments structure).
        计入每条消息的角色分隔开销（+4）和每个工具调用的结构开销（每个 +3，
        包含函数名/参数结构）。
        """
        if message.token_count is not None:
            return message.token_count
        total = 4  # role + separators overhead 角色 + 分隔符开销
        if message.content:
            total += count_tokens(message.content)
        if message.tool_result:
            total += count_tokens(message.tool_result.output)
        for tc in message.tool_calls:
            total += 3  # per-tool-call overhead 每个工具调用的结构开销
            total += count_tokens(tc.name)
            total += count_tokens(str(tc.arguments))
        message.token_count = total
        return message.token_count

    def update_total(self, conversation: Conversation) -> int:
        """Recount total tokens. Prefers the API-reported total (anchored at
        the message that usage covered) and only estimates messages appended
        after the anchor -- estimation error no longer accumulates over turns.
        重新统计总 token。优先用 API 返回的权威总量（锚定在 usage 覆盖的
        消息上），只对锚点之后追加的消息估算——估算误差不再逐轮累积。"""
        msgs = conversation.messages
        anchor_valid = (
            self._api_anchor is not None
            and 0 <= self._api_index < len(msgs)
            and msgs[self._api_index] is self._api_anchor
        )
        if anchor_valid:
            total = self._api_total
            for msg in msgs[self._api_index + 1 :]:
                total += self.count_message(msg)
        else:
            if self._api_anchor is not None:
                self._invalidate_api_anchor()  # compression/undo reshaped history
            total = count_tokens(conversation.system_prompt) if conversation.system_prompt else 0
            for msg in msgs:
                total += self.count_message(msg)
        self._total_tokens = total
        conversation.total_tokens = total
        return total

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def usage_ratio(self) -> float:
        if self._max_tokens <= 0:
            return 0.0
        return self._total_tokens / self._max_tokens

    @property
    def tokens_remaining(self) -> int:
        return max(0, self._max_tokens - self._total_tokens)

    @property
    def needs_compression(self) -> bool:
        return self.usage_ratio >= self._threshold

    @property
    def needs_hard_compression(self) -> bool:
        return self.usage_ratio >= self._hard_threshold

    async def check_and_compress(self, conversation: Conversation, force: bool = False) -> bool:
        """Check if compression is needed and perform it.
        检查是否需要压缩并执行压缩。

        force=True skips the threshold and breaker checks (manual /compact) --
        the manual path must still go through THIS pipeline: calling the
        compressor directly skips the recovery attachment and every boundary
        field (read files / last user request / skill state), real-run:
        a manually compacted then saved session restored with no skill state.
        force=True 跳过阈值与熔断检查（手动 /compact）——手动路径也必须走
        本管道：直接调 compressor 会跳过恢复附件和全部边界字段（已读文件/
        用户请求/技能状态），实测手动压缩后保存的会话恢复时技能状态全丢。

        Returns True if compression was performed.
        若执行了压缩则返回 True。
        """
        self.update_total(conversation)
        if not force and not self.needs_compression:
            return False
        if self._compressor is None:
            return False
        if (
            not force
            and self._max_compress_failures > 0
            and self._compress_failures >= self._max_compress_failures
            and not self.needs_hard_compression
        ):
            if not self._breaker_warned:
                self._breaker_warned = True
                logger.warning(
                    "Compression circuit breaker open: %d consecutive ineffective "
                    "attempts, skipping further compression this session. "
                    "压缩熔断器已开启：连续 %d 次无效，本会话跳过后续压缩",
                    self._compress_failures,
                    self._compress_failures,
                )
            return False

        if (
            self._compress_failures >= self._max_compress_failures > 0
            and self.needs_hard_compression
        ):
            logger.warning(
                "Hard compression threshold reached (%.0f%%), bypassing circuit breaker. "
                "硬阈值触发（%.0f%%），绕过熔断器强制压缩",
                self.usage_ratio * 100,
                self.usage_ratio * 100,
            )

        # Capture the latest user request before compression discards it
        # 压缩前捕获最近的用户请求，防止被摘要吞掉
        for msg in reversed(conversation.messages):
            if msg.role == Role.USER and msg.content:
                self._last_user_request = msg.content[:_MAX_TASK_CHARS]
                break

        old_total = self._total_tokens
        target = int(self._max_tokens * 0.5)
        await self._compressor.compress(conversation, target)
        self._inject_read_files(conversation)
        # Fallback: SlidingWindow alone doesn't create a summary, but
        # _inject_read_files inserts a compressed SYSTEM message we can use.
        # 兜底：纯 SlidingWindow 不产生摘要，但 _inject_read_files 会插入
        # 压缩 SYSTEM 消息可作为边界。
        if conversation.compact_boundary is None:
            from datetime import datetime

            for msg in conversation.messages:
                if msg.compressed and msg.role == Role.SYSTEM and msg.content:
                    conversation.compact_boundary = {
                        "summary": msg.content,
                        "timestamp": datetime.now().isoformat(),
                    }
                    break
        if conversation.compact_boundary is not None:
            conversation.compact_boundary["read_files"] = list(self._read_files)
            file_contents = {
                p: c
                for p, c in list(self._read_files.items())[-_MAX_RECOVERY_FILES:]
                if c is not None
            }
            if file_contents:
                conversation.compact_boundary["file_contents"] = file_contents
            if self._last_user_request:
                conversation.compact_boundary["last_user_request"] = self._last_user_request
            invoked, active = self._skill_state()
            if invoked:
                conversation.compact_boundary["skill_invocations"] = invoked
            if active:
                conversation.compact_boundary["active_skills"] = active
        self.update_total(conversation)
        if self._total_tokens >= old_total:
            self._compress_failures += 1
            logger.info(
                "Compression ineffective (%d -> %d tokens), failure %d/%d. "
                "压缩无效（%d -> %d），失败 %d/%d",
                old_total,
                self._total_tokens,
                self._compress_failures,
                self._max_compress_failures or -1,
                old_total,
                self._total_tokens,
                self._compress_failures,
                self._max_compress_failures or -1,
            )
        else:
            if self._compress_failures > 0:
                logger.info(
                    "Compression effective (%d -> %d tokens), resetting failure count. "
                    "压缩有效（%d -> %d），重置失败计数",
                    old_total,
                    self._total_tokens,
                    old_total,
                    self._total_tokens,
                )
            self._compress_failures = 0
            self._breaker_warned = False
        return True

    def _inject_read_files(self, conversation: Conversation) -> None:
        """After compression, inject recovery context: user's last request,
        read-file paths, and recent file contents.
        压缩后注入恢复上下文：用户最近请求、已读文件路径、近期文件内容。"""
        parts: list[str] = []
        # 1. Last user request -- prevents "I don't know what you asked" after compression
        # 最近用户请求——防止压缩后 agent 忘记任务
        if self._last_user_request:
            parts.append(
                "[User's most recent request before compression:\n" + self._last_user_request + "]"
            )
        # 2. Read-file path list
        if self._read_files:
            parts.append(
                "[Files already read this session -- do NOT re-read unless "
                "their content changed: " + ", ".join(self._read_files) + "]"
            )
        # 2b. Skill state -- same anti-repeat pattern as read files: active
        # skill prompts survive in the system prompt (it is never compressed),
        # but the ACTIVATION history lives in messages that the summary just
        # swallowed -- without this line the LLM re-activates or forgets.
        # 技能状态——与已读文件同一防重复模式：激活的 skill prompt 在
        # system prompt 里存活（不被压缩），但激活历史在刚被摘要吞掉的
        # 消息里——没有这行 LLM 会重复激活或遗忘。
        invoked, active = self._skill_state()
        if active:
            parts.append(
                "[Skills active (their prompts remain in the system prompt "
                "-- do NOT re-activate): " + ", ".join(active) + "]"
            )
        used_only = [n for n in invoked if n not in active]
        if used_only:
            parts.append(
                "[Skills previously used this session (now deactivated): "
                + ", ".join(used_only)
                + "]"
            )
        # 3. Truncated contents of the most recent files (up to 5).
        # Total budget scales with the window: the absolute 5x5000-token
        # attachment exceeds a small window entirely (observed at window=20K:
        # a 54K-char summary message pinned context at 112% -- compression
        # could never win). Same constant-vs-target class of bug as the
        # keep-window scaling fix.
        # 附加最近文件的截断内容（最多 5 个）。总预算随窗口缩放：绝对值
        # 5x5000 token 的附件在小窗口下超过整个窗口（实测 window=20K 时
        # 54K 字符的摘要消息把上下文钉死在 112%——压缩永远赢不了）。与保留
        # 窗口缩放修复同类问题。
        recent = [(p, c) for p, c in self._read_files.items() if c is not None][
            -_MAX_RECOVERY_FILES:
        ]
        if recent:
            total_budget = min(
                _MAX_RECOVERY_FILES * _RECOVERY_TOKENS_PER_FILE, self._max_tokens // 4
            )
            per_file = max(total_budget // len(recent), 200)
            parts.append("[File contents from before compression:]\n")
            for path, content in recent:
                parts.append(f"--- {path} ---\n{truncate_to_tokens(content, per_file)}")
        if not parts:
            return
        note = "\n\n".join(parts)
        marker = "[Files already read this session"
        user_marker = "[User's most recent request"
        skill_marker = "[Skills active ("
        used_marker = "[Skills previously used this session"
        for msg in reversed(conversation.messages):
            if msg.role == Role.SYSTEM and msg.compressed:
                content = msg.content or ""
                # Strip old recovery block (any marker may come first)
                # 剥离旧恢复块（任一标记可能在前）
                for m in (user_marker, marker, skill_marker, used_marker):
                    if m in content:
                        content = content[: content.index(m)].rstrip()
                msg.content = (content + "\n" + note) if content else note
                msg.token_count = None
                return
        conversation.messages.insert(0, Message(role=Role.SYSTEM, content=note, compressed=True))

    def adopt_boundary(self, conversation: Conversation) -> None:
        """Restore read-files and task state from a loaded compact boundary.
        从已加载的压缩边界恢复已读文件和任务状态。"""
        boundary = conversation.compact_boundary
        if not boundary:
            return
        file_contents = boundary.get("file_contents", {})
        for path in boundary.get("read_files", []):
            self._read_files[path] = file_contents.get(path)
        self._last_user_request = boundary.get("last_user_request", "")
        invoked = boundary.get("skill_invocations", [])
        active = boundary.get("active_skills", [])
        if invoked or active:
            self._adopted_skills = (list(invoked), list(active))

    async def ensure_fits(self, conversation: Conversation, max_tokens: int) -> bool:
        """Last-resort guard: force-truncate if conversation exceeds max_tokens.
        最终兜底：超窗口时强制截断（SlidingWindow），防 API 400。

        Returns True if truncation was performed.
        """
        self.update_total(conversation)
        if self._total_tokens <= max_tokens:
            return False
        target = int(max_tokens * 0.85)
        await SlidingWindow().compress(conversation, target)
        self.update_total(conversation)
        return True
