"""Configuration dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.0
    timeout: float = 120.0
    # Request-side extended thinking: Anthropic `thinking` param / OpenAI
    # Responses `reasoning` param. Providers that always emit
    # reasoning_content (DeepSeek-style) don't need this.
    # 发送侧 extended thinking：Anthropic thinking 参数 / OpenAI Responses
    # reasoning 参数。自动吐 reasoning_content 的 Provider（DeepSeek 类）无需开启。
    thinking: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class ToolConfig:
    enabled_tools: list[str] = field(
        default_factory=lambda: [
            "read_file",
            "write_file",
            "edit_file",
            "delete_file",
            "bash",
            "glob",
            "grep",
            "spawn_agents",
            "send_message",
            "wait_message",
            "tool_search",
            "mcp_call",
            "ask_user",
            "exit_plan_mode",
            "task_create",
            "task_get",
            "task_list",
            "task_update",
            "load_skill",
            "install_skill",
            "synthetic_output",
        ]
    )
    bash_timeout: float = 120.0
    max_file_size: int = 10_000_000
    allowed_paths: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=lambda: ["~/.ssh", "~/.aws", "~/.gnupg"])
    # Read-before-edit gate : set False to allow editing files without reading first
    # 编辑前必读门：设为 False 可关闭（编辑前无需先读）
    enforce_read_before_edit: bool = True


@dataclass
class MCPServerConfig:
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"  # "stdio" | "http" | "sse"
    loading: str = "eager"  # "eager" | "native" | "dispatch"


@dataclass
class MCPConfig:
    servers: dict[str, MCPServerConfig] = field(default_factory=dict)


@dataclass
class MemoryConfig:
    context_window: int = 128_000
    compression_threshold: float = 0.75
    hard_compression_threshold: float = 0.90
    persistent_memory_dir: str = "~/.mini-agent/memory"
    project_memory_file: str = ".mini-agent/memory.json"
    auto_extract: bool = True
    # Tool results above this size are spilled to disk (0 = disabled)
    # 超过此字符数的工具结果溢写磁盘（0 = 禁用）
    spill_threshold_chars: int = 50_000
    # Aggregate budget: when a turn's cumulative tool-result chars exceed
    # this, largest results are force-spilled until back under (0 = disabled)
    # 聚合预算：单轮工具结果累计字符超此值时按大小降序强制溢写（0 = 禁用）
    aggregate_spill_chars: int = 200_000
    # Selective recall: above this many memories, an LLM picks the most
    # relevant ones instead of injecting the first N
    # 选择性召回：记忆超过此数量时用 LLM 挑选最相关的，而非注入前 N 条
    recall_threshold: int = 10
    recall_top_k: int = 5
    # Memory consolidation: above this many entries, an LLM merges
    # semantically related memories into one
    # 记忆合并：条目超过此数量时用 LLM 语义合并相关记忆
    consolidation_threshold: int = 20
    # Background consolidation cadence: at startup, when both gates pass
    # (>= min hours since last run AND >= min new sessions), memories are
    # consolidated in a background task -- invisible to the user
    # 后台整固节律：启动时双门槛（距上次 >= 小时数 且 新会话 >= 个数）
    # 满足则后台任务整固记忆——用户无感
    auto_consolidate: bool = True
    consolidate_min_hours: float = 24.0
    consolidate_min_sessions: int = 5
    # Recall prefetch runs in parallel with the main LLM call; past this many
    # seconds the selection is abandoned and head-truncation is injected
    # recall 预取与主 LLM 调用并行；超过此秒数放弃挑选、注入头部截断
    recall_timeout: float = 8.0
    # Sessions older than this many days are auto-removed at startup (0 = off)
    # 超过此天数的旧会话启动时自动清理（0 = 禁用）
    session_cleanup_days: int = 30
    # Crashed sessions (closed_cleanly=False) older than this are also removed
    # (longer than session_cleanup_days because crash sessions have recovery value)
    # 崩溃会话（closed_cleanly=False）超过此天数也清理（比正常会话更宽松，因有恢复价值）
    crashed_session_cleanup_days: int = 40
    # Circuit breaker: skip compression after N consecutive ineffective attempts
    # 熔断器：连续 N 次压缩无效后跳过（0 = 禁用）
    compress_max_failures: int = 3
    # Use LLM semantic summary for compression (True) or extractive truncation (False)
    # 压缩时用 LLM 语义摘要（True）还是抽取式截断（False）
    llm_summarize: bool = True
    # /undo file snapshots: keep the last N turns (raise for deeper rollback)
    # /undo 文件快照：保留最近 N 轮（调大可回滚更早的改动）
    undo_keep_turns: int = 5


@dataclass
class SecurityConfig:
    permission_mode: str = "ask"
    # Startup permission mode (matrix): default / accept-edits / plan / bypass.
    # Runtime switch via /mode. Deny rules and sensitive paths hold in every
    # mode. 启动权限模式（矩阵）：default / accept-edits / plan / bypass，
    # 运行时用 /mode 切换。deny 规则和敏感路径在所有模式下有效。
    approval_mode: str = "default"
    allowed_commands: list[str] = field(default_factory=list)
    denied_commands: list[str] = field(
        default_factory=lambda: ["rm -rf /", "sudo", "curl|sh", "wget|sh"]
    )
    worktree_base_dir: str = ".mini-agent/worktrees"
    # Stale worktrees older than this are auto-removed at startup (0 = off)
    # 超过此天数的过期 worktree 启动时自动清理（0 = 禁用）
    worktree_max_age_days: int = 7
    # OS-level sandbox (Linux bwrap/unshare / macOS seatbelt / Windows admin
    # Low Integrity; Windows non-admin = no file protection, no startup warning)
    # OS 级沙箱（Linux bwrap/unshare / macOS seatbelt / Windows 管理员 Low
    # Integrity；非管理员无文件保护、不打启动警告）
    sandbox: bool = True
    sandbox_auto_allow: bool = False
    sandbox_network: bool = False


@dataclass
class CostConfig:
    """Cost tracking: per-model pricing and session budget.
    成本跟踪：每模型价格与会话预算。"""

    # model name -> {"input": price per 1M tokens, "output": ...} 元/百万 token
    pricing: dict = field(default_factory=dict)
    budget: float = 0.0  # per-session cap; 0 = unlimited 会话预算，0 不限
    total_budget: float = 0.0  # all-time ledger cap; 0 = unlimited 总账预算，0 不限
    currency: str = "¥"


@dataclass
class ContextConfig:
    """Context awareness: project instruction file injection.
    上下文感知：项目指令文件注入。"""

    # Priority order, first match wins 优先级顺序，第一个命中即用
    instruction_files: list[str] = field(
        default_factory=lambda: ["AGENT.md", "CLAUDE.md", ".mini-agent/instructions.md"]
    )
    user_instructions_file: str = "~/.mini-agent/instructions.md"
    max_chars: int = 8000
    max_include_depth: int = 5  # @-include recursive expansion depth; 0 disables


@dataclass
class AgentConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    # Named LLM profiles for /model switching 用于 /model 切换的命名 LLM 档案
    llm_profiles: dict[str, LLMConfig] = field(default_factory=dict)
    # Strong/weak model mixing: profile names for Planner and SubAgent workers.
    # Empty = use the main llm. Validated by experiments/model_mix.py: strong
    # planner + weak workers is Pareto-optimal (all pass, lowest cost).
    # 强弱模型混编：Planner 和 SubAgent worker 的 profile 名。
    # 空 = 使用主模型。实验验证 strong-weak 编排是帕累托最优。
    planner_profile: str = ""
    worker_profile: str = ""
    tools: ToolConfig = field(default_factory=ToolConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    max_agent_iterations: int = 80
    # Stop and ask the user after this many confirm-dialog denials (dangerous
    # command / path outside project / hook confirm). Default 1: one denial
    # stops the goal (denying a confirm means "don't do this"; the agent asks
    # instead of hunting for a bypass). Raise to give the agent room to retry
    # with a corrected command after a denial.
    # 确认框被拒达到这个次数就停下回问用户（危险命令/项目外路径/hook 确认）。
    # 默认 1：拒一次即停（拒绝确认框 = "别做这个"，agent 停下问你而非找绕过）。
    # 调大可给 agent 被拒后用修正命令重试的空间。
    max_consecutive_denials: int = 1
    # Declarative hook rules from `[[hooks]]` TOML (raw dicts, parsed by
    # tools/hooks.parse_hook_rules). Supports PRE_TOOL/POST_TOOL events,
    # 4 actions (block/confirm/command/notify), and condition expressions.
    # `[[hooks]]` TOML 声明式规则（block/confirm/command/notify + 条件表达式）
    hooks: list = field(default_factory=list)
    self_verify: bool = False
    # Execute tool calls as they finish assembling during streaming
    # 流式期间工具调用一组装完成就开始执行
    streaming_tool_execution: bool = True
    enable_plan_mode: bool = False
    skill_dirs: list[str] = field(default_factory=lambda: ["./skills", "~/.mini-agent/skills"])
    # Event listener plugin dirs: *.py files observing all bus events
    # 事件监听插件目录：*.py 文件监听总线全部事件（统计/调试）
    listener_dirs: list[str] = field(
        default_factory=lambda: ["./.mini-agent/listeners", "~/.mini-agent/listeners"]
    )
    # Plugin dirs: *.py files registering tools/commands/skills.
    # pip packages register via the mini_agent.plugins entry-point group instead.
    # 插件目录：*.py 文件注册工具/命令/技能；pip 包走 mini_agent.plugins entry point。
    plugin_dirs: list[str] = field(
        default_factory=lambda: ["./.mini-agent/plugins", "~/.mini-agent/plugins"]
    )
    # Plugins to skip, by entry-point name or file stem 按 entry-point 名或文件名禁用插件
    disabled_plugins: list[str] = field(default_factory=list)
    # Custom agent type dirs: *.md files declaring agent types
    # 自定义 Agent 类型目录：*.md 文件声明 agent 类型
    agent_dirs: list[str] = field(
        default_factory=lambda: ["~/.mini-agent/agents", "./.mini-agent/agents"]
    )
    theme: str = "default"
    # Collapse read-only tool calls (read_file/glob/grep) into a one-line
    # summary when >=2 run in the same round. Default OFF: full per-call
    # lines; opt in with true.
    # 只读工具同轮 >=2 次时折叠为一行摘要。默认关闭（逐条完整显示），
    # 设 true 才折叠。
    collapse_tool_calls: bool = False
