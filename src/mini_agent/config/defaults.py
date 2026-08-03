"""Built-in default configuration values. 内置默认配置值。"""

from mini_agent.models.config import AgentConfig


def get_defaults() -> AgentConfig:
    return AgentConfig()
