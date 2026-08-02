"""LLM provider registry and factory."""

from __future__ import annotations

from mini_agent.llm.base import LLMProvider
from mini_agent.models.config import LLMConfig


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


def _register_builtins() -> None:
    from mini_agent.llm.openai_provider import OpenAIProvider

    ProviderRegistry.register("openai", OpenAIProvider)


_register_builtins()
