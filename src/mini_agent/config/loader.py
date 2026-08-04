"""Layered configuration loading. 分层配置加载。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mini_agent.config.defaults import get_defaults
from mini_agent.models.config import AgentConfig


class ConfigLoader:
    """Loads and merges configuration from all layers. 从所有层级加载并合并配置。"""

    @staticmethod
    def load(
        cli_overrides: dict[str, Any] | None = None,
    ) -> AgentConfig:
        config = get_defaults()

        # Load .env file into os.environ (won't overwrite existing vars)
        # 将 .env 文件加载到 os.environ（不会覆盖已存在的变量）
        ConfigLoader._load_dotenv()

        # Apply environment variables
        config = ConfigLoader._apply_env(config)

        # Load named LLM profiles 加载命名 LLM 档案
        ConfigLoader._load_profiles(config)

        # Strong/weak model mixing 强弱模型混编
        config.planner_profile = os.environ.get("MINI_AGENT_PLANNER_PROFILE", "").strip()
        config.worker_profile = os.environ.get("MINI_AGENT_WORKER_PROFILE", "").strip()

        # Apply CLI overrides (highest priority)
        if cli_overrides:
            config = ConfigLoader._apply_cli(config, cli_overrides)

        return config

    @staticmethod
    def _load_profiles(config: AgentConfig) -> None:
        """Parse named switchable models from environment variables.
        从环境变量解析可切换的命名模型。

        Format 格式:
          MINI_AGENT_MODELS=fast,smart
          MODEL_FAST_MODEL=deepseek-chat
          MODEL_FAST_API_KEY=sk-xxx        (可省略, 继承默认)
          MODEL_FAST_BASE_URL=https://...   (可省略, 继承默认)
          MODEL_FAST_PROVIDER=openai        (可省略, 继承默认)

        Legacy MINI_AGENT_PROFILES / PROFILE_X_* names still work.
        旧的 MINI_AGENT_PROFILES / PROFILE_X_* 命名仍然兼容。
        """
        from dataclasses import replace

        names = os.environ.get("MINI_AGENT_MODELS", "") or os.environ.get("MINI_AGENT_PROFILES", "")
        if not names.strip():
            return

        for raw_name in names.split(","):
            name = raw_name.strip()
            if not name:
                continue
            # New MODEL_X_* prefix first, legacy PROFILE_X_* as fallback
            # 优先新的 MODEL_X_* 前缀，旧的 PROFILE_X_* 兜底
            new_prefix = f"MODEL_{name.upper()}_"
            old_prefix = f"PROFILE_{name.upper()}_"

            def get(field: str, np=new_prefix, op=old_prefix) -> str | None:
                return os.environ.get(np + field) or os.environ.get(op + field)

            model = get("MODEL")
            if not model:
                continue  # An entry must at least define a model 至少要定义模型名
            profile = replace(
                config.llm,
                model=model,
                provider=get("PROVIDER") or config.llm.provider,
                api_key=get("API_KEY") or config.llm.api_key,
                base_url=get("BASE_URL") or config.llm.base_url,
            )
            config.llm_profiles[name] = profile

    @staticmethod
    def _load_dotenv() -> None:
        """Read .env file from current directory and set into os.environ.
        Won't overwrite variables that are already set.
        从当前目录读取 .env 文件并写入 os.environ。
        不会覆盖已设置的变量。"""
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
                # Inline comment removal
                if "  #" in value:
                    value = value[: value.index("  #")].strip()
                if key and key not in os.environ:
                    os.environ[key] = value

    @staticmethod
    def _apply_env(config: AgentConfig) -> AgentConfig:
        # Lower priority first, higher priority later (overwrites)
        env_layers = [
            # Low priority: OPENAI_* vars
            {
                "OPENAI_API_KEY": "llm.api_key",
                "OPENAI_BASE_URL": "llm.base_url",
            },
            # High priority: MINI_AGENT_* vars
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
        return config

    @staticmethod
    def _apply_cli(config: AgentConfig, overrides: dict[str, Any]) -> AgentConfig:
        for key, value in overrides.items():
            parts = key.split(".")
            if len(parts) == 2 and parts[0] == "llm":
                attr = parts[1]
                if hasattr(config.llm, attr):
                    setattr(config.llm, attr, value)
        return config
