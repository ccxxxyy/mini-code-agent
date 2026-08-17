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
        ]
    )
    bash_timeout: float = 120.0
    max_file_size: int = 10_000_000
    allowed_paths: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=lambda: ["~/.ssh", "~/.aws", "~/.gnupg"])


@dataclass
class MCPServerConfig:
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"
    loading: str = "eager"


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
    # Sessions older than this many days are auto-removed at startup (0 = off)
    # 超过此天数的旧会话启动时自动清理（0 = 禁用）
    session_cleanup_days: int = 30
    # Circuit breaker: skip compression after N consecutive ineffective attempts
    # 熔断器：连续 N 次压缩无效后跳过（0 = 禁用）
    compress_max_failures: int = 3
    # Use LLM semantic summary for compression (True) or extractive truncation (False)
    # 压缩时用 LLM 语义摘要（True）还是抽取式截断（False）
    llm_summarize: bool = True


@dataclass
class SecurityConfig:
    permission_mode: str = "ask"
    allowed_commands: list[str] = field(default_factory=list)
    denied_commands: list[str] = field(
        default_factory=lambda: ["rm -rf /", "sudo", "curl|sh", "wget|sh"]
    )
    worktree_base_dir: str = ".mini-agent/worktrees"
    # Stale worktrees older than this are auto-removed at startup (0 = off)
    # 超过此天数的过期 worktree 启动时自动清理（0 = 禁用）
    worktree_max_age_days: int = 7
    # OS-level sandbox (Linux bwrap / macOS seatbelt); Windows: no-op
    # OS 级沙箱（Linux bwrap / macOS seatbelt）；Windows 无效
    sandbox: bool = False
    sandbox_auto_allow: bool = False
    sandbox_network: bool = False


@dataclass
class CostConfig:
    """Cost tracking: per-model pricing and session budget (P29).
    成本跟踪：每模型价格与会话预算。"""

    # model name -> {"input": price per 1M tokens, "output": ...} 元/百万 token
    pricing: dict = field(default_factory=dict)
    budget: float = 0.0  # per-session cap; 0 = unlimited 会话预算，0 不限
    total_budget: float = 0.0  # all-time ledger cap; 0 = unlimited 总账预算，0 不限
    currency: str = "¥"


@dataclass
class ContextConfig:
    """Context awareness: project instruction file injection (P25).
    上下文感知：项目指令文件注入。"""

    # Priority order, first match wins 优先级顺序，第一个命中即用
    instruction_files: list[str] = field(
        default_factory=lambda: ["AGENT.md", "CLAUDE.md", ".mini-agent/instructions.md"]
    )
    user_instructions_file: str = "~/.mini-agent/instructions.md"
    max_chars: int = 8000


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
    # Declarative PRE_TOOL rejection rules from `[[hooks]]` TOML (raw dicts,
    # parsed by tools/hooks.parse_hook_rules)
    # `[[hooks]]` TOML 的声明式 PRE_TOOL 拒绝规则（原始字典，注册时解析）
    hooks: list = field(default_factory=list)
    self_verify: bool = False
    # Execute tool calls as they finish assembling during streaming
    # 流式期间工具调用一组装完成就开始执行
    streaming_tool_execution: bool = True
    enable_plan_mode: bool = False
    skill_dirs: list[str] = field(default_factory=lambda: ["./skills", "~/.mini-agent/skills"])
    theme: str = "default"
