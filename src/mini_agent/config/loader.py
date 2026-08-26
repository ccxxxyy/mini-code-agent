"""Layered configuration loading. 分层配置加载。

Priority stack (highest to lowest) 优先级栈（从高到低）:
  CLI arguments > env vars > .env file > project TOML > user TOML > defaults
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mini_agent.config.defaults import get_defaults
from mini_agent.models.config import AgentConfig, MCPServerConfig


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class ConfigLoader:
    """Loads and merges configuration from all layers. 从所有层级加载并合并配置。"""

    @staticmethod
    def load(
        cli_overrides: dict[str, Any] | None = None,
    ) -> AgentConfig:
        config = get_defaults()

        # 1. Merge user TOML (~/.mini-agent/config.toml) 合并用户级 TOML
        user_toml = Path.home() / ".mini-agent" / "config.toml"
        if user_toml.is_file():
            ConfigLoader._merge(config, ConfigLoader._load_toml(user_toml))

        # 2. Merge project TOML (.mini-agent/config.toml) 合并项目级 TOML
        project_toml = Path.cwd() / ".mini-agent" / "config.toml"
        if project_toml.is_file():
            ConfigLoader._merge(config, ConfigLoader._load_toml(project_toml))

        # 3. Load .env file into os.environ (won't overwrite existing vars)
        ConfigLoader._load_dotenv()

        # 4. Apply environment variables 应用环境变量
        config = ConfigLoader._apply_env(config)

        # 5. Load named LLM profiles 加载命名 LLM 档案
        ConfigLoader._load_profiles(config)

        # 6. Strong/weak model mixing 强弱模型混编
        config.planner_profile = os.environ.get("MINI_AGENT_PLANNER_PROFILE", "").strip()
        config.worker_profile = os.environ.get("MINI_AGENT_WORKER_PROFILE", "").strip()

        # 7. Apply CLI overrides (highest priority) 应用 CLI 覆盖（最高优先级）
        if cli_overrides:
            config = ConfigLoader._apply_cli(config, cli_overrides)

        return config

    @staticmethod
    def _load_toml(path: Path) -> dict[str, Any]:
        """Parse a TOML file. 解析 TOML 文件。"""
        import tomllib

        with open(path, "rb") as f:
            return tomllib.load(f)

    @staticmethod
    def _merge(config: AgentConfig, overlay: dict[str, Any]) -> AgentConfig:
        """Deep-merge a TOML dict onto the config dataclass.
        将 TOML 字典深度合并到配置 dataclass。"""
        for section_name, section_data in overlay.items():
            if not isinstance(section_data, dict):
                if hasattr(config, section_name):
                    setattr(config, section_name, section_data)
                continue
            if section_name == "mcp":
                ConfigLoader._merge_mcp(config, section_data)
                continue
            sub = getattr(config, section_name, None)
            if sub is None:
                continue
            for key, value in section_data.items():
                if hasattr(sub, key):
                    setattr(sub, key, value)
        return config

    @staticmethod
    def _merge_mcp(config: AgentConfig, mcp_data: dict[str, Any]) -> None:
        """Merge [mcp.servers.<name>] sections into config.mcp.servers.
        将 [mcp.servers.<名称>] 部分合并到 config.mcp.servers。"""
        servers = mcp_data.get("servers", {})
        for name, srv_data in servers.items():
            if isinstance(srv_data, dict):
                config.mcp.servers[name] = MCPServerConfig(**srv_data)

    @staticmethod
    def _load_profiles(config: AgentConfig) -> None:
        """Parse named switchable models from environment variables.
        从环境变量解析可切换的命名模型。"""
        from dataclasses import replace

        names = os.environ.get("MINI_AGENT_MODELS", "") or os.environ.get("MINI_AGENT_PROFILES", "")
        if not names.strip():
            return

        for raw_name in names.split(","):
            name = raw_name.strip()
            if not name:
                continue
            new_prefix = f"MODEL_{name.upper()}_"
            old_prefix = f"PROFILE_{name.upper()}_"

            def get(field: str, np=new_prefix, op=old_prefix) -> str | None:
                return os.environ.get(np + field) or os.environ.get(op + field)

            model = get("MODEL")
            if not model:
                continue
            thinking_raw = get("THINKING")
            profile = replace(
                config.llm,
                model=model,
                provider=get("PROVIDER") or config.llm.provider,
                api_key=get("API_KEY") or config.llm.api_key,
                base_url=get("BASE_URL") or config.llm.base_url,
                thinking=_parse_bool(thinking_raw) if thinking_raw else config.llm.thinking,
            )
            config.llm_profiles[name] = profile

    @staticmethod
    def _load_dotenv() -> None:
        """Read .env file from current directory and set into os.environ.
        从当前目录读取 .env 文件并写入 os.environ。"""
        env_path = Path.cwd() / ".env"
        if not env_path.is_file():
            return
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if "  #" in value:
                    value = value[: value.index("  #")].strip()
                if key and key not in os.environ:
                    os.environ[key] = value

    @staticmethod
    def _apply_env(config: AgentConfig) -> AgentConfig:
        env_layers = [
            {
                "OPENAI_API_KEY": "llm.api_key",
                "OPENAI_BASE_URL": "llm.base_url",
            },
            {
                "MINI_AGENT_PROVIDER": "llm.provider",
                "MINI_AGENT_MODEL": "llm.model",
                "MINI_AGENT_API_KEY": "llm.api_key",
                "MINI_AGENT_BASE_URL": "llm.base_url",
            },
        ]
        overrides: dict[str, Any] = {}
        for layer in env_layers:
            for env_var, config_key in layer.items():
                value = os.environ.get(env_var)
                if value:
                    overrides[config_key] = value
        if overrides:
            config = ConfigLoader._apply_cli(config, overrides)
        thinking_raw = os.environ.get("MINI_AGENT_THINKING")
        if thinking_raw:
            config.llm.thinking = _parse_bool(thinking_raw)
        return config

    @staticmethod
    def _apply_cli(config: AgentConfig, overrides: dict[str, Any]) -> AgentConfig:
        """Apply dotted-key overrides (e.g. "llm.model", "tools.bash_timeout").
        应用点分键覆盖（如 "llm.model"、"tools.bash_timeout"）。"""
        for key, value in overrides.items():
            parts = key.split(".")
            if len(parts) == 2:
                section = getattr(config, parts[0], None)
                if section and hasattr(section, parts[1]):
                    setattr(section, parts[1], value)
            elif len(parts) == 1 and hasattr(config, key):
                setattr(config, key, value)
        return config
