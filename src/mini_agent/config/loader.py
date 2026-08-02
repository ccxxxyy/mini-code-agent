"""Layered configuration loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mini_agent.config.defaults import get_defaults
from mini_agent.models.config import AgentConfig


class ConfigLoader:
    """Loads and merges configuration from all layers."""

    @staticmethod
    def load(
        cli_overrides: dict[str, Any] | None = None,
    ) -> AgentConfig:
        config = get_defaults()

        # Load .env file into os.environ (won't overwrite existing vars)
        ConfigLoader._load_dotenv()

        # Apply environment variables
        config = ConfigLoader._apply_env(config)

        # Apply CLI overrides (highest priority)
        if cli_overrides:
            config = ConfigLoader._apply_cli(config, cli_overrides)

        return config

    @staticmethod
    def _load_dotenv() -> None:
        """Read .env file from current directory and set into os.environ.
        Won't overwrite variables that are already set."""
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
