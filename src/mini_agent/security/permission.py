"""Permission manager -- evaluates permission requests against rules.
权限管理器——根据规则评估权限请求。"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from mini_agent.models.config import SecurityConfig
from mini_agent.models.events import (
    PermissionCheckEvent,
    PermissionRuleAddedEvent,
    PermissionRuleRemovedEvent,
)
from mini_agent.models.permissions import (
    PermissionDecision,
    PermissionLevel,
    PermissionMode,
    PermissionRequest,
    PermissionRule,
    PermissionScope,
    ToolCategory,
)
from mini_agent.security.path_guard import (
    PathGuard,
    matches_sensitive_name,
)

if TYPE_CHECKING:
    from mini_agent.events.bus import EventBus

logger = logging.getLogger(__name__)

# Git global-option prefix: tolerates options inserted between `git` and the
# subcommand (e.g. `git -C /repo push`, `git -c user.name=x commit`). The
# value-taking flags (-c/-C) are listed first so alternation consumes their
# argument; `--?\S+\s+` then absorbs standalone flags and attached forms
# (-C/repo). Order matters -- see tests for bypass corpus.
# Git 全局选项前缀：容忍 git 与子命令之间插入的选项（如 git -C /repo push）。
# 带独立值的 -c/-C 列在前以便 alternation 吞掉其参数；--?\S+\s+ 兜底单标志
# 与 attached 形式（-C/repo）。顺序重要——绕过语料见测试。
_GIT_PREFIX = r"git\s+(?:-c\s+\S+\s+|-C\s+\S+\s+|--?\S+\s+)*"

# Patterns that flag a command as dangerous (confirm before running).
# NOTE: a regex blacklist can never be exhaustive -- a determined LLM can
# always reshape a command to evade signature matching (proven by this
# project's deadlock experiment). These patterns block the common, obvious
# forms; they are a speed bump, not a wall. The iteration limit and
# human-in-the-loop confirm on matched commands are the real safeguards.
# 用于标记危险命令的模式（执行前需要确认）。
# 注意：正则黑名单本质不可能穷尽——LLM 总能变形绕过签名（本项目死循环实验
# 已证）。这些模式只堵常见明显形态，是减速带而非围墙；迭代上限与命中后的
# 人工确认才是真正的护栏。
DANGEROUS_COMMAND_PATTERNS = [
    # Any rm targeting something (bare `rm file` deletes too -- not just -rf).
    # Excludes bare `rm` with no argument and rm --help/-h.
    # 任何删文件的 rm（裸 `rm file` 也删，不只是 -rf）。排除无参 rm 和 --help。
    r"\brm\s+(?!--help\b|-h\b)\S",
    r"\bsudo\b",
    # chmod 777/0777, tolerating leading option flags (chmod -R 777)
    # chmod 777/0777，容忍前置选项（chmod -R 777）
    r"\bchmod\s+(?:-[a-zA-Z]+\s+)*[0-7]*777\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
    r"\b" + _GIT_PREFIX + r"push\b",  # any push touches the remote 任何 push 都影响远程
    r"\b" + _GIT_PREFIX + r"commit\b",  # commits must be user-initiated 提交须用户主动
    r"\b" + _GIT_PREFIX + r"reset\b",
    r"\b" + _GIT_PREFIX + r"stash\b",  # can silently shelve in-progress work 静默搁置未完成工作
    r"\b" + _GIT_PREFIX + r"rebase\b",
    # switching/restoring can discard changes; -b (new branch) is safe
    # 切换/还原可能丢弃改动；-b（新建分支）安全
    r"\b" + _GIT_PREFIX + r"checkout\s+(?!-b\b)",
    r"\b" + _GIT_PREFIX + r"restore\b",
    r"\b" + _GIT_PREFIX + r"clean\b",
    r"\bdel\s+\S",  # Windows del (any form -- deletes files) Windows 删文件
    r"\brmdir\s+\S",  # Windows rmdir (any form, incl. empty dir) Windows 删目录
    r"\brd\s+\S",  # Windows rd (rmdir alias) Windows rmdir 别名
    r"\bformat\s+[a-z]:",  # Windows format Windows 的格式化磁盘
    r"curl[^|]*\|\s*(ba)?sh",  # curl | sh 下载并直接执行脚本
    r"wget[^|]*\|\s*(ba)?sh",
    # Inline interpreter execution -- arbitrary code inside quotes bypasses
    # command-signature matching (proven by real bypass twice).
    # 内联解释器——引号内任意代码绕过命令签名匹配（实测两次绕过证实）。
    r"\bpython[23]?\s+-(c\b|(\s|<|$))",  # python -c "..." / python - / python - < file
    r"\bnode\s+-(e|p)\b",  # node -e "..." / node --eval / node -p
    r"\bperl\s+-e\b",  # perl -e '...'
    r"\bruby\s+-e\b",  # ruby -e '...'
    r"\b(ba)?sh\s+-c\b",  # sh -c "..." / bash -c "..."
    r"\bpowershell\s+-(Command|c)\b",  # powershell -Command "..."
    r"\bpwsh\s+-(Command|c)\b",  # pwsh -c "..."
    # cmd /c "..." is the Windows equivalent of sh -c: arbitrary inline
    # command inside quotes bypasses signature matching (incl. quoted
    # redirects that quote-stripping in is_write_command would miss).
    # cmd /c 是 Windows 版 sh -c：引号内任意内联命令绕过签名匹配
    # （含 is_write_command 引号剥离会漏掉的引号内重定向）。
    r"\bcmd(\.exe)?\s+/c\b",
]

# Write-form commands, used by plan mode's read-only guarantee: file
# redirects and file-mutating commands must not slip through the bash
# channel while write TOOLS are locked. A speed bump, not a wall (same
# honest boundary as the dangerous list): obfuscation can escape.
# 写形态命令——plan 模式只读保证使用：写工具被锁时，文件重定向和改文件
# 命令不能从 bash 通道溜走。与危险清单同为减速带而非围墙：混淆仍可逃逸。
WRITE_COMMAND_PATTERNS = [
    # Redirect to a real file; >nul / >/dev/null / >&fd discard, not writes
    # 重定向到真实文件；>nul / >/dev/null / >&fd 是丢弃输出不算写
    r">\s*(?!nul\b|/dev/null\b|&)",
    # File-mutating command at start or after a separator (; & |)
    # 位于开头或分隔符（; & |）之后的改文件命令
    r"(?:^|[;&|]\s*)\s*(mkdir|md|copy|xcopy|robocopy|move|ren|rename"
    r"|del|erase|rd|rmdir|rm|mv|cp|touch|tee|truncate|dd)\s",
]

# Balanced quoted segments, stripped before write-pattern matching
# 成对引号段——写形态匹配前剥离
_QUOTED_SEGMENT_RE = re.compile(r"\"[^\"]*\"|'[^']*'")

# Shell wrapper prefixes that embed an inner command. DENY rules must match
# the inner command too: `cmd /c "ping x"` sailed past a `ping*` deny rule
# and was only caught by the dangerous-command confirm layer (real-run) --
# in an interactive session the user could approve that confirm without
# noticing it wraps a denied command.
# 内嵌命令的 shell 包装前缀。deny 规则必须同时匹配内层命令：实测
# `cmd /c "ping x"` 绕过了 `ping*` deny 规则，仅靠危险命令确认层兜底——
# 交互会话里用户可能没注意到确认框里包着一条被拒命令就点了同意。
_WRAPPER_COMMAND_RE = re.compile(
    r"^\s*(?:cmd(?:\.exe)?\s+/[ck]\s+"
    r"|(?:powershell|pwsh)(?:\.exe)?\s+(?:-\w+\s+)*-c(?:ommand)?\s+"
    r"|(?:ba)?sh\s+-c\s+)(?P<inner>.+)$",
    re.IGNORECASE,
)

# Matches script execution to detect write-then-execute bypass:
#   python script.py / node app.js / perl x.pl / ruby x.rb
#   ./script.py / .\script.bat (direct execution)
#   cmd /c script.bat / call script.bat / start script.bat
# 匹配脚本执行以检测写后执行绕过。
_SCRIPT_EXEC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:python[23]?|node|perl|ruby)\s+(?!-\S)(?P<path>\S+)", re.IGNORECASE),
    re.compile(r"^\.[\\/](?P<path>\S+)", re.IGNORECASE),
    re.compile(r"\bcmd\s+/c\s+(?P<path>\S+)", re.IGNORECASE),
    re.compile(r"\b(?:call|start)\s+(?P<path>\S+)", re.IGNORECASE),
]
_PYTHON_M_RE = re.compile(r"\bpython[23]?\s+-m\s+(?P<module>\S+)", re.IGNORECASE)

# Splits a shell command into path-like tokens (whitespace, =, and shell
# operators). Used to spot a sensitive filename referenced anywhere in a bash
# command -- `type .env`, `cat ~/.ssh/id_rsa`, `Get-Content creds.json` all
# bypass the read_file tool's sensitive-file DENY because they run via bash.
# 把 shell 命令切成类路径 token（空白、=、shell 操作符）。用于发现 bash 命令里
# 任意位置引用的敏感文件名——type/cat/Get-Content 读 .env 等会绕过 read_file
# 工具的敏感文件拦截，因为它们走 bash 通道。
_TOKEN_SPLIT_RE = re.compile(r"[\s=]+|[|;&<>()]+")


def command_references_sensitive_file(command: str) -> bool:
    """True if any token in a shell command names a sensitive file
    (.env / *.pem / id_rsa / credentials / *secret* / .npmrc / .docker/config.json).
    A speed bump, not a wall: obfuscated paths (env vars, wildcards) can still
    slip through.
    命令中任一 token 命中敏感文件名则为真。减速带而非围墙：变量/通配等混淆仍可能逃逸。"""
    for raw in _TOKEN_SPLIT_RE.split(command):
        tok = raw.strip().strip("'\"")
        if not tok:
            continue
        parts = tok.replace("\\", "/").split("/")
        parent = parts[-2] if len(parts) >= 2 else ""
        if matches_sensitive_name(parts[-1], parent):
            return True
    return False


# Callback to ask the user for confirmation.
# Returns True (allow once), False (deny), "always" (allow for session),
# or "always-save" (allow for session + persist a rule to permissions.toml).
# 向用户请求确认的回调。
# 返回 True（允许一次）、False（拒绝）、"always"（本会话内始终允许）
# 或 "always-save"（会话允许并持久化规则到 permissions.toml）。
ConfirmCallback = Callable[[str], Awaitable[bool | str]]

# TOML section name per scope (permissions.toml) 各 scope 对应的 TOML 节名
_SCOPE_SECTIONS: dict[PermissionScope, str] = {
    PermissionScope.COMMAND: "commands",
    PermissionScope.PATH: "paths",
    PermissionScope.TOOL: "tools",
}


class PermissionManager:
    """Evaluates permission requests. Prompts user when needed.
    评估权限请求。必要时提示用户确认。"""

    def __init__(
        self,
        config: SecurityConfig,
        path_guard: PathGuard,
        confirm_callback: ConfirmCallback | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._config = config
        self._path_guard = path_guard
        self._confirm = confirm_callback
        self._event_bus = event_bus
        self._rules: list[PermissionRule] = []
        self._session_grants: set[tuple[PermissionScope, str]] = set()
        self._session_written_files: set[str] = set()
        self.shared_written_files: set[str] | None = None
        self.working_dir: Path | None = None
        # OS sandbox auto-allows normal commands (kernel provides isolation)
        # OS 沙箱自动放行普通命令（内核提供隔离）
        self.sandbox_auto_allow: bool = False
        # Session permission mode (matrix): relaxes/tightens what would
        # otherwise prompt. Deny rules and sensitive paths hold in every mode.
        # 会话权限模式（矩阵）：放宽/收紧原本要询问的部分。deny 规则和
        # 敏感路径在所有模式下有效。
        self.mode: PermissionMode = PermissionMode.DEFAULT
        # Why the last decision was made (for /trace) 最近一次判定的依据（用于 /trace）
        self.last_decision_reason: str = ""
        self.last_matched_rule: str = ""
        self._load_rules_from_config(config)

    def child_view(self) -> ChildPermissionManager:
        """A view of this manager for in-process sub-agents: shares rules,
        session grants, written-file tracking and (live) the mode, but never
        prompts -- anything that would ask the user is denied fail-safe.
        给 in-process 子 agent 的视图：共享规则/会话授权/写文件追踪/模式
        （实时），但绝不弹窗——需要询问用户的一律安全拒绝。"""
        return ChildPermissionManager(self)

    def _load_rules_from_config(self, config: SecurityConfig) -> None:
        for pattern in config.denied_commands:
            self.add_rule(
                PermissionRule(
                    scope=PermissionScope.COMMAND,
                    pattern=pattern,
                    level=PermissionLevel.DENY,
                    reason="denied by config",
                ),
                _silent=True,
            )
        for pattern in config.allowed_commands:
            self.add_rule(
                PermissionRule(
                    scope=PermissionScope.COMMAND,
                    pattern=pattern,
                    level=PermissionLevel.ALLOW,
                    reason="allowed by config",
                ),
                _silent=True,
            )

    def add_rule(self, rule: PermissionRule, *, _silent: bool = False) -> bool:
        """Add a permission rule at runtime. Returns False if duplicate.
        运行时添加权限规则。重复则返回 False。"""
        if not rule.pattern or not rule.pattern.strip():
            raise ValueError("Permission rule pattern must not be empty")
        if any(
            r.scope == rule.scope and r.pattern == rule.pattern and r.level == rule.level
            for r in self._rules
        ):
            return False
        self._rules.append(rule)
        if not _silent and self._event_bus is not None:
            asyncio.get_event_loop().create_task(
                self._event_bus.emit(
                    PermissionRuleAddedEvent(
                        scope=rule.scope.value,
                        pattern=rule.pattern,
                        level=rule.level.value,
                        reason=rule.reason,
                    )
                )
            )
        return True

    def remove_rule(self, scope: PermissionScope, pattern: str, level: PermissionLevel) -> bool:
        """Remove a rule by scope+pattern+level. Returns True if found and removed.
        按 scope+pattern+level 移除规则。找到并移除返回 True。"""
        for i, rule in enumerate(self._rules):
            if rule.scope == scope and rule.pattern == pattern and rule.level == level:
                self._rules.pop(i)
                if self._event_bus is not None:
                    asyncio.get_event_loop().create_task(
                        self._event_bus.emit(
                            PermissionRuleRemovedEvent(
                                scope=scope.value,
                                pattern=pattern,
                                level=level.value,
                            )
                        )
                    )
                return True
        return False

    def list_rules(self) -> list[PermissionRule]:
        """Return a copy of the current rule list for introspection.
        返回当前规则列表的副本，供外部查看。"""
        return list(self._rules)

    @staticmethod
    def save_rule_to_file(path: Path, rule: PermissionRule) -> None:
        """Append a rule to a TOML permission file, creating it if needed.
        将规则追加到 TOML 权限文件，不存在则创建。"""
        import tomllib

        section = _SCOPE_SECTIONS[rule.scope]
        level_key = rule.level.value  # "allow" or "deny"

        data: dict = {}
        if path.is_file():
            with open(path, "rb") as f:
                data = tomllib.load(f)

        table = data.setdefault(section, {})
        entries = table.setdefault(level_key, [])
        if rule.pattern not in entries:
            entries.append(rule.pattern)

        path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for sec in ("commands", "paths", "tools"):
            sec_data = data.get(sec)
            if not sec_data:
                continue
            lines.append(f"[{sec}]")
            for lk in ("allow", "deny"):
                vals = sec_data.get(lk, [])
                if vals:
                    formatted = ", ".join(f'"{v}"' for v in vals)
                    lines.append(f"{lk} = [{formatted}]")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")

    def load_rule_files(
        self,
        user_file: Path | None = None,
        project_file: Path | None = None,
    ) -> int:
        """Load user-defined permission rules from TOML files.
        从 TOML 文件加载用户自定义权限规则。

        Format 格式:
            [commands]
            allow = ["docker build *"]
            deny = ["docker rm *"]
            [paths]
            allow = ["D:/shared/*"]
            deny = ["*/secrets/*"]
            [tools]
            allow = ["glob"]
            deny = ["delete_file"]

        Returns the number of rules loaded. Missing files are skipped;
        malformed files are skipped with a warning (startup must not crash).
        返回加载的规则数。文件缺失跳过；格式错误警告后跳过（启动不能崩）。
        """
        count = 0
        for path, source in ((user_file, "user"), (project_file, "project")):
            if path is None or not path.is_file():
                continue
            try:
                import tomllib

                with open(path, "rb") as f:
                    data = tomllib.load(f)
            except Exception as e:
                import sys

                print(f"Warning: skipping {path}: {e}", file=sys.stderr)
                continue
            reason = f"permissions.toml({source})"
            for section, scope in (
                ("commands", PermissionScope.COMMAND),
                ("paths", PermissionScope.PATH),
                ("tools", PermissionScope.TOOL),
            ):
                table = data.get(section, {})
                if not isinstance(table, dict):
                    continue
                levels = (("deny", PermissionLevel.DENY), ("allow", PermissionLevel.ALLOW))
                for level_key, level in levels:
                    for pattern in table.get(level_key, []):
                        if isinstance(pattern, str) and pattern:
                            added = self.add_rule(
                                PermissionRule(
                                    scope=scope, pattern=pattern, level=level, reason=reason
                                ),
                                _silent=True,
                            )
                            if added:
                                count += 1
        return count

    def grant_session_permission(self, scope: PermissionScope, pattern: str) -> None:
        """User granted permission for the remainder of the session.
        用户在本会话剩余时间内授予了该权限。"""
        self._session_grants.add((scope, pattern))

    async def check(self, request: PermissionRequest) -> PermissionDecision:
        """Universal permission check entry -- dispatches by scope so any
        consumer can evaluate any request with a single call.

        COMMAND -> full command pipeline (dangerous-pattern confirmation).
        PATH    -> full path pipeline (DENY rules -> PathGuard -> generic).
        TOOL    -> generic pipeline (rules -> session grants -> default mode).

        通用权限检查入口——按 scope 分发，任意消费者一次调用即可评估任意请求。
        COMMAND -> 完整命令管道（危险模式确认）。
        PATH    -> 完整路径管道（DENY 规则 -> PathGuard -> 通用）。
        TOOL    -> 通用管道（规则 -> 会话授权 -> 默认模式）。
        """
        if request.scope == PermissionScope.COMMAND:
            return await self._check_command_request(request)
        if request.scope == PermissionScope.PATH:
            operation = "write" if request.context.startswith("write") else "read"
            return await self._check_path_request(request, operation)
        return await self._check_generic(request)

    async def _check_generic(self, request: PermissionRequest) -> PermissionDecision:
        """Generic pipeline: explicit rules -> session grants -> default mode.
        通用管道：显式规则 -> 会话授权 -> 默认模式。"""
        decision = await self._check_rules_only(request)
        if decision is not None:
            return decision

        # Default mode 默认模式
        mode = self._config.permission_mode
        self.last_decision_reason = f"mode:{mode}"
        if mode == "allow":
            return PermissionDecision.GRANTED
        if mode == "deny":
            return PermissionDecision.DENIED
        return await self._ask_user(request)

    async def check_tool(self, tool_name: str) -> PermissionDecision | None:
        """Tool-level gate: explicit TOOL rules and session grants only.

        Returns None when nothing matches -- callers fall through to
        resource-level checks (command/path). An ALLOW rule here means the
        user trusts the tool wholesale (skips resource checks); default
        mode deliberately does NOT apply, or deny mode would block even
        project-dir reads at the tool level.

        工具级门：只看显式 TOOL 规则和会话授权。无匹配返回 None——调用方
        继续做资源级检查（命令/路径）。ALLOW 表示用户整体信任该工具
        （跳过资源检查）；默认模式刻意不参与，否则 deny 模式会在工具层
        拦掉项目内读取。"""
        request = PermissionRequest(
            scope=PermissionScope.TOOL,
            resource=tool_name,
            tool_name=tool_name,
        )
        return await self._check_rules_only(request)

    async def check_path(
        self, path: Path, operation: str = "read", tool_name: str = ""
    ) -> PermissionDecision:
        """Check file path access: explicit DENY rules -> PathGuard -> rules.
        检查文件路径访问：显式 DENY 规则 -> PathGuard -> 其余规则。"""
        request = PermissionRequest(
            scope=PermissionScope.PATH,
            resource=str(path),
            tool_name=tool_name,
            context=f"{operation} access outside project directory",
        )
        return await self._check_path_request(request, operation)

    async def _check_path_request(
        self, request: PermissionRequest, operation: str
    ) -> PermissionDecision:
        """Path pipeline. Explicit DENY rules come FIRST -- otherwise
        PathGuard's project-dir ALLOW short-circuits them, and a user's
        `deny = ["*/secrets/*"]` for an in-project path would silently
        never apply.
        路径管道。显式 DENY 规则最优先——否则 PathGuard 的项目内 ALLOW
        会短路它们，用户对项目内路径写的 deny 规则会静默失效。"""
        path = Path(request.resource)
        if self._deny_rule_matches(PermissionScope.PATH, str(path)):
            return PermissionDecision.DENIED
        # Plan mode: writes denied outright, BEFORE PathGuard's project-dir
        # ALLOW would grant them (third lock behind schema filtering and the
        # act-phase intercept in the loop).
        # plan 模式：写操作直接拒绝——须在 PathGuard 项目内 ALLOW 放行前判定
        # （loop 的 schema 过滤和 act 拦截之外的第三重锁）。
        if self.mode is PermissionMode.PLAN and operation == "write":
            self.last_decision_reason = "mode:plan"
            return PermissionDecision.DENIED
        level = self._path_guard.check(path, operation)
        if level == PermissionLevel.DENY:
            self.last_decision_reason = "path_guard:sensitive"
            return PermissionDecision.DENIED
        if level == PermissionLevel.ALLOW:
            self.last_decision_reason = "path_guard:project_dir"
            return PermissionDecision.GRANTED
        # Out-of-project path (PathGuard ASK). Sensitive paths were already
        # denied above -- bypass/accept-edits never open those.
        # 项目外路径（PathGuard ASK）。敏感路径已在上方拒绝——
        # bypass/accept-edits 不会打开它们。
        if self.mode is PermissionMode.BYPASS:
            self.last_decision_reason = "mode:bypass"
            return PermissionDecision.GRANTED
        if self.mode is PermissionMode.ACCEPT_EDITS and operation == "write":
            self.last_decision_reason = "mode:accept-edits"
            return PermissionDecision.GRANTED
        return await self._check_generic(request)

    @staticmethod
    def _rule_reason(rule: PermissionRule) -> str:
        """Decision reason carrying the rule's SOURCE -- without it the LLM
        hunts config files for session rules that live only in memory
        (real-run: 347K tokens spent tracing a /deny rule's origin).
        Parentheses, NOT square brackets: reasons flow into Rich-rendered
        trace lines where `[/...]` parses as a closing markup tag (real-run:
        MarkupError traceback dumped to the terminal).
        带规则来源的判定理由——不带来源时 LLM 会翻遍配置文件找只存在于
        内存的会话规则（实测：为溯源一条 /deny 规则烧了 34 万 token）。
        用圆括号而非方括号：理由会进入 Rich 渲染的 trace 行，`[/...]` 会被
        解析为闭合标记（实测 MarkupError 崩溃刷屏）。"""
        if rule.reason:
            return f"rule:{rule.scope.value}:{rule.pattern} ({rule.reason})"
        return f"rule:{rule.scope.value}:{rule.pattern}"

    @staticmethod
    def _deny_command_variants(command: str) -> list[str]:
        """Command + unwrapped inner commands + unquoted segments, for DENY
        matching only. ALLOW rules stay on the plain command: expanding what
        a deny catches fails closed, expanding what an allow grants does not.
        命令本体 + 解包后的内层命令 + 去引号分段，仅用于 deny 匹配。
        allow 规则只看命令本体：扩大 deny 命中面是收紧，扩大 allow 是放松。"""
        variants = [command]
        inner = command
        for _ in range(3):
            m = _WRAPPER_COMMAND_RE.match(inner)
            if not m:
                break
            inner = m.group("inner").strip().strip("\"'")
            if inner not in variants:
                variants.append(inner)
        # Quoted spans blanked before splitting: `echo "a & ping x"` must not
        # produce a `ping x` segment (data, not a command).
        # 分段前先抹掉引号段：`echo "a & ping x"` 不能拆出 `ping x` 段
        # （那是数据不是命令）。
        for v in list(variants):
            blanked = _QUOTED_SEGMENT_RE.sub('""', v)
            for seg in re.split(r"[|;&]+", blanked):
                seg = seg.strip()
                if seg and seg not in variants:
                    variants.append(seg)
        return variants

    def _matches_deny(self, pattern: str, scope: PermissionScope, resource: str) -> bool:
        if scope is PermissionScope.COMMAND:
            return any(self._matches(pattern, v) for v in self._deny_command_variants(resource))
        return self._matches(pattern, resource)

    def _deny_rule_matches(self, scope: PermissionScope, resource: str) -> bool:
        for rule in self._rules:
            if (
                rule.scope == scope
                and rule.level == PermissionLevel.DENY
                and self._matches_deny(rule.pattern, scope, resource)
            ):
                self.last_decision_reason = self._rule_reason(rule)
                return True
        return False

    async def check_command(self, command: str) -> PermissionDecision:
        """Check bash command: dangerous patterns need confirmation.
        检查 bash 命令：危险模式需要确认。"""
        request = PermissionRequest(
            scope=PermissionScope.COMMAND,
            resource=command,
            tool_name="bash",
        )
        return await self._check_command_request(request)

    async def _check_command_request(self, request: PermissionRequest) -> PermissionDecision:
        """Command pipeline: rules -> dangerous-pattern confirm -> default mode.
        命令管道：规则 -> 危险模式确认 -> 默认模式。"""
        command = request.resource

        # Explicit rules and session grants first 先检查显式规则和会话授权
        decision = await self._check_rules_only(request)
        if decision is not None:
            return decision

        # Plan mode: write-form commands denied outright -- the read-only
        # guarantee must cover the bash channel too (real-run verified: the
        # LLM planned `echo HELLO> a.txt` to write around the locked tools).
        # plan 模式：写形态命令直接拒绝——只读保证必须覆盖 bash 通道
        # （真实运行实测：LLM 计划用 `echo HELLO> a.txt` 绕开被锁的写工具）。
        if self.mode is PermissionMode.PLAN and self.is_write_command(command):
            self.last_decision_reason = "mode:plan"
            return PermissionDecision.DENIED

        # Sensitive-file commands hold in EVERY mode, bypass included --
        # a mode switch must never silently open `type .env` / `cat id_rsa`
        # (real-run verified: bypass leaked an API key via this channel
        # before this check was ordered ahead of the mode short-circuit).
        # 敏感文件命令在所有模式下有效（含 bypass）——模式切换绝不能静默
        # 放行 `type .env` 这类读取（真实运行实测：此检查排在模式短路
        # 之前的排序修正前，bypass 曾经此通道泄漏 API key）。
        if command_references_sensitive_file(command):
            if self.sandbox_auto_allow:
                self.last_decision_reason = "sandbox_auto_allow"
                return PermissionDecision.GRANTED
            request.context = "command references a sensitive file (.env / key / credentials)"
            self.last_decision_reason = "sensitive_file_command"
            return await self._ask_user(request)

        # Bypass mode: everything else not caught by a deny rule is
        # auto-granted. bypass 模式：其余未被 deny 规则拦下的命令自动放行。
        if self.mode is PermissionMode.BYPASS:
            self.last_decision_reason = "mode:bypass"
            return PermissionDecision.GRANTED

        # Dangerous pattern or executing a script written this session -> confirm
        # 危险模式 或 执行本会话写过的脚本 -> 确认
        is_dangerous = self.is_dangerous_command(command)
        is_written_script = self.is_executing_written_script(command, self.working_dir)
        if is_dangerous or is_written_script:
            if self.sandbox_auto_allow:
                self.last_decision_reason = "sandbox_auto_allow"
                return PermissionDecision.GRANTED
            if is_written_script:
                request.context = "executing script written by agent this session"
                self.last_decision_reason = "written_script_execution"
            else:
                request.context = "dangerous command detected"
                self.last_decision_reason = "dangerous_command"
            return await self._ask_user(request)

        # Normal command -> default mode 普通命令 -> 走默认模式
        mode = self._config.permission_mode
        self.last_decision_reason = f"mode:{mode}"
        if mode == "deny":
            return PermissionDecision.DENIED
        # Both "allow" and "ask" mode auto-allow normal commands;
        # only dangerous ones need confirmation
        # "allow" 和 "ask" 模式都会自动放行普通命令；
        # 只有危险命令才需要确认
        return PermissionDecision.GRANTED

    async def _check_rules_only(self, request: PermissionRequest) -> PermissionDecision | None:
        """Check explicit rules and session grants. None = no match.
        检查显式规则和会话授权。None 表示无匹配。"""
        self.last_matched_rule = ""
        for rule in self._rules:
            if rule.scope == request.scope and rule.level == PermissionLevel.DENY:
                if self._matches_deny(rule.pattern, request.scope, request.resource):
                    request.matched_rule = rule
                    self.last_matched_rule = f"{rule.level}:{rule.pattern}"
                    self.last_decision_reason = self._rule_reason(rule)
                    return PermissionDecision.DENIED
        for rule in self._rules:
            if rule.scope == request.scope and rule.level == PermissionLevel.ALLOW:
                if self._matches(rule.pattern, request.resource):
                    request.matched_rule = rule
                    self.last_matched_rule = f"{rule.level}:{rule.pattern}"
                    self.last_decision_reason = self._rule_reason(rule)
                    return PermissionDecision.GRANTED
        for scope, pattern in self._session_grants:
            if scope == request.scope and self._matches(pattern, request.resource):
                self.last_decision_reason = "session_grant"
                return PermissionDecision.GRANTED
        return None

    @staticmethod
    def is_dangerous_command(command: str) -> bool:
        return any(re.search(p, command, re.IGNORECASE) for p in DANGEROUS_COMMAND_PATTERNS)

    @staticmethod
    def is_write_command(command: str) -> bool:
        """Write-form bash command (file redirect / file-mutating command).
        Quoted segments are stripped first: a `>` inside quotes is data, not
        a redirect (`findstr ">" f` / `git log --pretty="a>b"` are reads).
        Safe because every inline executor that could smuggle a quoted
        redirect (sh -c / powershell -Command / cmd /c) is in the dangerous
        list and prompts regardless. Unbalanced quotes are left in place,
        erring toward deny.
        写形态 bash 命令（文件重定向 / 改文件命令）。先剥离引号段：引号内
        的 `>` 是数据不是重定向（findstr/git pretty 等只读用法）。安全性由
        危险清单兜底——能把引号内重定向真正执行起来的内联执行器
        （sh -c / powershell -Command / cmd /c）全部在清单内必弹确认。
        不成对引号不剥离，宁可误拦。"""
        stripped = _QUOTED_SEGMENT_RE.sub("", command)
        return any(re.search(p, stripped, re.IGNORECASE) for p in WRITE_COMMAND_PATTERNS)

    def record_written_file(self, path: str) -> None:
        """Track a file written by the agent this session.
        记录本会话 agent 写过的文件。"""
        resolved = str(Path(path).resolve())
        self._session_written_files.add(resolved)
        if self.shared_written_files is not None:
            self.shared_written_files.add(resolved)

    def is_executing_written_script(self, command: str, working_dir: Path | None = None) -> bool:
        """Check if a command runs a script the agent wrote this session.
        检测命令是否在执行本会话 agent 写过的脚本文件。
        working_dir: bash 工具的工作目录，用于解析相对路径。"""
        all_written = self._session_written_files
        if self.shared_written_files:
            all_written = all_written | self.shared_written_files
        if not all_written:
            return False
        cmd = command.strip()

        def _is_written(script_path: str) -> bool:
            try:
                p = Path(script_path.strip().strip("'\""))
                if not p.is_absolute() and working_dir:
                    p = working_dir / p
                # resolve() on 3.11+ does not stat for non-existent paths
                return str(p.resolve()) in all_written
            except (ValueError, OSError):
                return False

        # Bare invocation: the FIRST token of any command segment names a
        # written file (`run_ping.bat` runs directly on Windows -- real-run:
        # a sub-agent bypassed a deny rule this way; the regex patterns only
        # caught ./x, cmd /c x and interpreter forms). First-token-only so
        # reading a written file (`type run_ping.bat`) does not trigger.
        # 裸调用：命令段首 token 是写过的文件（Windows 下 `run_ping.bat`
        # 直接执行——实测子 agent 借此绕过 deny 规则；原正则只认 ./x、
        # cmd /c x 和解释器形态）。只查首 token——读取写过的文件
        # （type run_ping.bat）不误触发。
        for segment in re.split(r"[|;&]+", cmd):
            parts = segment.strip().split()
            if parts and _is_written(parts[0]):
                return True

        for pattern in _SCRIPT_EXEC_PATTERNS:
            m = pattern.search(cmd)
            if m and _is_written(m.group("path")):
                return True
        m_mod = _PYTHON_M_RE.search(cmd)
        if m_mod and working_dir:
            mod_name = m_mod.group("module").strip()
            mod_path = working_dir / f"{mod_name.replace('.', '/')}.py"
            try:
                if str(mod_path.resolve()) in all_written:
                    return True
            except (ValueError, OSError):
                pass
        return False

    # --- Non-interactive peek: "would this call pop a confirm dialog?"
    # --- 非交互预判："这次调用会不会弹确认框？"
    # Used by streaming tool execution: tools that would NOT prompt can be
    # submitted while the LLM response is still streaming; tools that would
    # prompt are deferred until after the stream (dialogs cannot interleave
    # with live rendering). Never prompts, never mutates state.
    # 供流式工具执行使用：不会弹窗的工具可以在流式期间提前提交执行，
    # 会弹窗的延迟到流结束后（弹窗不能和流式渲染交错）。不弹窗、无副作用。

    def would_ask(
        self, tool_name: str, arguments: dict, category: ToolCategory | None = None
    ) -> bool:
        """category routes the check (mode × category matrix); None falls back
        to EXTERNAL, which never prompts -- callers that know the tool should
        always pass its category. category 决定路由（模式 × 类别矩阵）；None
        回退 EXTERNAL（永不弹窗）——知道工具的调用方应总是传类别。"""
        # Explicit tool-level rule resolves without prompting
        # 显式工具级规则直接判定，不弹窗
        tool_request = PermissionRequest(
            scope=PermissionScope.TOOL, resource=tool_name, tool_name=tool_name
        )
        if self._rules_would_resolve(tool_request):
            return False
        if tool_name == "bash":
            return self._would_ask_command(str(arguments.get("command", "")))
        if category in (ToolCategory.READ, ToolCategory.WRITE):
            path = arguments.get("file_path") or arguments.get("path")
            if not path:
                return False
            operation = "write" if category is ToolCategory.WRITE else "read"
            return self._would_ask_path(Path(str(path)), operation)
        # EXECUTE / EXTERNAL / unknown: category-gate denies or grants,
        # never prompts. EXECUTE/EXTERNAL/未知：类别门拒绝或放行，不弹窗。
        return False

    def _would_ask_command(self, command: str) -> bool:
        request = PermissionRequest(scope=PermissionScope.COMMAND, resource=command)
        if self._rules_would_resolve(request):
            return False
        if self.mode is PermissionMode.PLAN and self.is_write_command(command):
            return False  # denied outright, no prompt plan 直接拒绝不弹窗
        if command_references_sensitive_file(command):
            # Prompts in every mode (bypass included) unless the sandbox
            # auto-allows. 所有模式下都弹窗（含 bypass），除非沙箱自动放行。
            return not self.sandbox_auto_allow
        if self.mode is PermissionMode.BYPASS:
            return False  # bypass auto-grants, never prompts bypass 自动放行不弹窗
        if self.is_dangerous_command(command) or self.is_executing_written_script(
            command, self.working_dir
        ):
            return True
        return False

    def _would_ask_path(self, path: Path, operation: str = "read") -> bool:
        if self._deny_rule_matches(PermissionScope.PATH, str(path)):
            return False  # explicit deny resolves without prompting 显式拒绝不弹窗
        if self.mode is PermissionMode.PLAN and operation == "write":
            return False  # plan denies writes outright plan 直接拒绝写，不弹窗
        level = self._path_guard.check(path)
        if level != PermissionLevel.ASK:
            return False  # ALLOW / DENY resolve without prompting
        if self.mode is PermissionMode.BYPASS:
            return False
        if self.mode is PermissionMode.ACCEPT_EDITS and operation == "write":
            return False
        request = PermissionRequest(scope=PermissionScope.PATH, resource=str(path))
        if self._rules_would_resolve(request):
            return False
        return self._config.permission_mode == "ask"

    def _rules_would_resolve(self, request: PermissionRequest) -> bool:
        """True if explicit rules or session grants decide this request.
        显式规则或会话授权能直接判定则返回 True。"""
        for rule in self._rules:
            if rule.scope == request.scope and self._matches(rule.pattern, request.resource):
                return True
        for scope, pattern in self._session_grants:
            if scope == request.scope and self._matches(pattern, request.resource):
                return True
        return False

    async def _ask_user(self, request: PermissionRequest) -> PermissionDecision:
        if self._confirm is None:
            # No UI available -> deny by default (safe)
            # 无可用 UI -> 默认拒绝（安全起见）
            self.last_decision_reason = "no_ui:default_deny"
            return PermissionDecision.DENIED
        # Emit PENDING event before awaiting user response
        # 等待用户响应前发射 PENDING 事件
        if self._event_bus is not None:
            await self._event_bus.emit(
                PermissionCheckEvent(
                    tool_name=request.tool_name,
                    scope=request.scope.value,
                    resource=request.resource[:120],
                    decision=PermissionDecision.PENDING.value,
                    reason="awaiting_user",
                )
            )
        prompt = f"Allow {request.scope.value} access to: {request.resource}"
        if request.context:
            prompt += f"\n({request.context})"
        answer = await self._confirm(prompt)
        if answer in ("always", "always-save"):
            self.grant_session_permission(request.scope, request.resource)
            if answer == "always-save":
                self._persist_confirmed_rule(request)
                self.last_decision_reason = "user_confirm:always-save"
            else:
                self.last_decision_reason = "user_confirm:always"
            return PermissionDecision.GRANTED
        self.last_decision_reason = f"user_confirm:{'yes' if answer else 'no'}"
        return PermissionDecision.GRANTED if answer else PermissionDecision.DENIED

    def _persist_confirmed_rule(self, request: PermissionRequest) -> None:
        """Persist an ALLOW rule from the confirm dialog to the project's
        permissions.toml (same file and format as /allow --save). Failure
        must not break the grant -- the session permission already holds.
        把确认弹窗授予的 ALLOW 规则持久化到项目 permissions.toml
        （与 /allow --save 同一文件与格式）。写盘失败不影响本次授权
        ——会话级授权已生效。"""
        rule = PermissionRule(
            scope=request.scope,
            pattern=request.resource,
            level=PermissionLevel.ALLOW,
            reason="saved from confirm dialog",
        )
        self.add_rule(rule)
        base = self.working_dir or Path.cwd()
        try:
            self.save_rule_to_file(base / ".mini-agent" / "permissions.toml", rule)
        except OSError:
            logger.warning("failed to persist confirmed rule", exc_info=True)

    @staticmethod
    def _matches(pattern: str, resource: str) -> bool:
        """Glob-style matching; 'git *' matches 'git status' but not 'github'.
        glob 风格匹配；'git *' 匹配 'git status' 但不匹配 'github'。"""
        if fnmatch.fnmatch(resource, pattern):
            return True
        # Prefix match: keep the delimiter so 'git *' -> startswith('git ')
        # 前缀匹配：保留分隔符，使 'git *' -> startswith('git ')
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return bool(prefix) and resource.startswith(prefix)
        return resource == pattern


class ChildPermissionManager(PermissionManager):
    """Permission view for in-process sub-agents: the FULL parent gate
    (deny rules, sensitive paths, dangerous commands, mode matrix) with one
    difference -- no confirm callback, so anything that would prompt the
    user is denied fail-safe instead. Mutable state is SHARED by reference
    (rules list, session grants, written-file sets), and ``mode`` delegates
    to the parent live -- /deny and /mode in the main session affect running
    sub-agents immediately. ``last_decision_reason`` is per-child (parallel
    agents must not clobber each other's trace context).
    in-process 子 agent 的权限视图：父级完整门禁（deny 规则/敏感路径/危险
    命令/模式矩阵），唯一区别是无确认回调——需要弹窗的一律安全拒绝。可变
    状态按引用共享（规则表/会话授权/写文件集合），``mode`` 实时委托父级——
    主会话的 /deny 和 /mode 即时影响运行中的子 agent。``last_decision_reason``
    每个子实例独立（并行 agent 不互相覆盖 trace 上下文）。"""

    def __init__(self, parent: PermissionManager) -> None:
        # Deliberately NOT calling super().__init__: state is bound to the
        # parent's objects, not rebuilt from config (which would duplicate
        # config-declared rules into the shared list).
        # 刻意不调 super().__init__：状态绑定父级对象而非从配置重建
        # （重建会把配置声明的规则重复灌进共享列表）。
        self._parent = parent
        self._config = parent._config
        self._path_guard = parent._path_guard
        self._confirm = None  # never prompts 绝不弹窗
        self._event_bus = parent._event_bus
        self._rules = parent._rules  # shared list 共享列表（/allow /deny 实时生效）
        self._session_grants = parent._session_grants
        self._session_written_files = parent._session_written_files
        self.shared_written_files = parent.shared_written_files
        self.working_dir = parent.working_dir
        self.sandbox_auto_allow = parent.sandbox_auto_allow
        self.last_decision_reason = ""
        self.last_matched_rule = ""

    @property
    def mode(self) -> PermissionMode:
        return self._parent.mode

    @mode.setter
    def mode(self, value: PermissionMode) -> None:
        # Single source of truth: a child never diverges from the parent.
        # 单一事实源：子视图不允许与父级分叉。
        self._parent.mode = value
