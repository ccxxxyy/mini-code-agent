"""Permission manager -- evaluates permission requests against rules.
权限管理器——根据规则评估权限请求。"""

from __future__ import annotations

import asyncio
import fnmatch
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
    PermissionRequest,
    PermissionRule,
    PermissionScope,
)
from mini_agent.security.path_guard import (
    SENSITIVE_EXCEPTIONS,
    SENSITIVE_FILE_PATTERNS,
    PathGuard,
)

if TYPE_CHECKING:
    from mini_agent.events.bus import EventBus

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
    # command-signature matching (D3: proven by real A2 bypass twice).
    # 内联解释器——引号内任意代码绕过命令签名匹配（D3：A2 实测两次绕过证实）。
    r"\bpython[23]?\s+-(c\b|(\s|<|$))",  # python -c "..." / python - / python - < file
    r"\bnode\s+-(e|p)\b",  # node -e "..." / node --eval / node -p
    r"\bperl\s+-e\b",  # perl -e '...'
    r"\bruby\s+-e\b",  # ruby -e '...'
    r"\b(ba)?sh\s+-c\b",  # sh -c "..." / bash -c "..."
    r"\bpowershell\s+-(Command|c)\b",  # powershell -Command "..."
    r"\bpwsh\s+-(Command|c)\b",  # pwsh -c "..."
]

# Matches script execution to detect write-then-execute bypass:
#   python script.py / node app.js / perl x.pl / ruby x.rb
#   ./script.py / .\script.bat (direct execution)
#   cmd /c script.bat
# 匹配脚本执行以检测写后执行绕过。
_SCRIPT_EXEC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:python[23]?|node|perl|ruby)\s+(?!-\S)(?P<path>\S+)", re.IGNORECASE),
    re.compile(r"^\.[\\/](?P<path>\S+)", re.IGNORECASE),
    re.compile(r"\bcmd\s+/c\s+(?P<path>\S+)", re.IGNORECASE),
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
    (.env / *.pem / id_rsa / credentials / *secret*). A speed bump, not a wall:
    obfuscated paths (env vars, wildcards) can still slip through.
    命令中任一 token 命中敏感文件名则为真。减速带而非围墙：变量/通配等混淆仍可能逃逸。"""
    for raw in _TOKEN_SPLIT_RE.split(command):
        tok = raw.strip().strip("'\"")
        if not tok:
            continue
        name = tok.replace("\\", "/").rsplit("/", 1)[-1]
        if name in SENSITIVE_EXCEPTIONS:
            continue
        if any(fnmatch.fnmatch(name, pat) for pat in SENSITIVE_FILE_PATTERNS):
            return True
    return False


# Callback to ask the user for confirmation.
# Returns True (allow once), False (deny), or "always" (allow for session).
# 向用户请求确认的回调。
# 返回 True（允许一次）、False（拒绝）或 "always"（本会话内始终允许）。
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
        # Why the last decision was made (for /trace) 最近一次判定的依据（用于 /trace）
        self.last_decision_reason: str = ""
        self.last_matched_rule: str = ""
        self._load_rules_from_config(config)

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
        level = self._path_guard.check(path, operation)
        if level == PermissionLevel.DENY:
            self.last_decision_reason = "path_guard:sensitive"
            return PermissionDecision.DENIED
        if level == PermissionLevel.ALLOW:
            self.last_decision_reason = "path_guard:project_dir"
            return PermissionDecision.GRANTED
        return await self._check_generic(request)

    def _deny_rule_matches(self, scope: PermissionScope, resource: str) -> bool:
        for rule in self._rules:
            if (
                rule.scope == scope
                and rule.level == PermissionLevel.DENY
                and self._matches(rule.pattern, resource)
            ):
                self.last_decision_reason = f"rule:{rule.pattern}"
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

        # Dangerous pattern or executing a script written this session -> confirm
        # 危险模式 或 执行本会话写过的脚本 -> 确认
        is_dangerous = self.is_dangerous_command(command)
        is_written_script = self.is_executing_written_script(command, self.working_dir)
        is_sensitive_file = command_references_sensitive_file(command)
        if is_dangerous or is_written_script or is_sensitive_file:
            if self.sandbox_auto_allow:
                self.last_decision_reason = "sandbox_auto_allow"
                return PermissionDecision.GRANTED
            if is_written_script:
                request.context = "executing script written by agent this session"
                self.last_decision_reason = "written_script_execution"
            elif is_sensitive_file:
                request.context = "command references a sensitive file (.env / key / credentials)"
                self.last_decision_reason = "sensitive_file_command"
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
                if self._matches(rule.pattern, request.resource):
                    request.matched_rule = rule
                    self.last_matched_rule = f"{rule.level}:{rule.pattern}"
                    self.last_decision_reason = f"rule:{rule.pattern}"
                    return PermissionDecision.DENIED
        for rule in self._rules:
            if rule.scope == request.scope and rule.level == PermissionLevel.ALLOW:
                if self._matches(rule.pattern, request.resource):
                    request.matched_rule = rule
                    self.last_matched_rule = f"{rule.level}:{rule.pattern}"
                    self.last_decision_reason = f"rule:{rule.pattern}"
                    return PermissionDecision.GRANTED
        for scope, pattern in self._session_grants:
            if scope == request.scope and self._matches(pattern, request.resource):
                self.last_decision_reason = "session_grant"
                return PermissionDecision.GRANTED
        return None

    @staticmethod
    def is_dangerous_command(command: str) -> bool:
        return any(re.search(p, command, re.IGNORECASE) for p in DANGEROUS_COMMAND_PATTERNS)

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
        for pattern in _SCRIPT_EXEC_PATTERNS:
            m = pattern.search(cmd)
            if m:
                script_path = m.group("path").strip().strip("'\"")
                try:
                    p = Path(script_path)
                    if not p.is_absolute() and working_dir:
                        p = working_dir / p
                    # resolve() on 3.11+ does not stat for non-existent paths
                    if str(p.resolve()) in all_written:
                        return True
                except (ValueError, OSError):
                    continue
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

    def would_ask(self, tool_name: str, arguments: dict) -> bool:
        # Explicit tool-level rule resolves without prompting
        # 显式工具级规则直接判定，不弹窗
        tool_request = PermissionRequest(
            scope=PermissionScope.TOOL, resource=tool_name, tool_name=tool_name
        )
        if self._rules_would_resolve(tool_request):
            return False
        if tool_name == "bash":
            return self._would_ask_command(str(arguments.get("command", "")))
        if tool_name in ("read_file", "glob", "grep", "write_file", "edit_file", "delete_file"):
            path = arguments.get("file_path") or arguments.get("path")
            if not path:
                return False
            return self._would_ask_path(Path(str(path)))
        return False  # unrestricted tools never prompt 非受限工具永不弹窗

    def _would_ask_command(self, command: str) -> bool:
        request = PermissionRequest(scope=PermissionScope.COMMAND, resource=command)
        if self._rules_would_resolve(request):
            return False
        if self.is_dangerous_command(command) or self.is_executing_written_script(
            command, self.working_dir
        ):
            return True
        return False

    def _would_ask_path(self, path: Path) -> bool:
        if self._deny_rule_matches(PermissionScope.PATH, str(path)):
            return False  # explicit deny resolves without prompting 显式拒绝不弹窗
        level = self._path_guard.check(path)
        if level != PermissionLevel.ASK:
            return False  # ALLOW / DENY resolve without prompting
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
        if answer == "always":
            self.grant_session_permission(request.scope, request.resource)
            self.last_decision_reason = "user_confirm:always"
            return PermissionDecision.GRANTED
        self.last_decision_reason = f"user_confirm:{'yes' if answer else 'no'}"
        return PermissionDecision.GRANTED if answer else PermissionDecision.DENIED

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
