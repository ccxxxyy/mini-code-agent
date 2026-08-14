"""LLM provider registry and factory."""

from __future__ import annotations

from mini_agent.llm.base import LLMProvider
from mini_agent.models.config import AgentConfig, LLMConfig


class ProviderRegistry:
    """Factory for LLM providers."""

    _providers: dict[str, type[LLMProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_class: type[LLMProvider]) -> None:
        cls._providers[name] = provider_class

    @classmethod
    def create(cls, config: LLMConfig) -> LLMProvider:
        provider_class = cls._providers.get(config.provider)
        if not provider_class:
            available = ", ".join(cls._providers.keys()) or "(none)"
            raise ValueError(f"Unknown LLM provider '{config.provider}'. Available: {available}")
        return provider_class(config)

    @classmethod
    def list_providers(cls) -> list[str]:
        return list(cls._providers.keys())

    @classmethod
    def create_for_role(cls, config: AgentConfig, role: str) -> LLMProvider:
        """Create a provider for a mixing role ("planner" / "worker").
        Falls back to the main llm when the profile is unset or unknown.
        为混编角色（planner/worker）创建 Provider。
        profile 未配置或不存在时回退主模型。
        """
        profile_name = getattr(config, f"{role}_profile", "")
        profile = config.llm_profiles.get(profile_name) if profile_name else None
        return cls.create(profile or config.llm)


def _register_builtins() -> None:
    from mini_agent.llm.anthropic_provider import AnthropicProvider
    from mini_agent.llm.openai_provider import OpenAIProvider
    from mini_agent.llm.openai_responses_provider import OpenAIResponsesProvider

    ProviderRegistry.register("openai", OpenAIProvider)
    ProviderRegistry.register("anthropic", AnthropicProvider)
    ProviderRegistry.register("openai-responses", OpenAIResponsesProvider)


_register_builtins()
