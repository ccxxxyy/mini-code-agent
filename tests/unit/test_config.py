"""Tests for configuration loading."""

import os

from mini_agent.config.loader import ConfigLoader


def test_default_config():
    config = ConfigLoader.load()
    assert config.llm.provider == "openai"
    assert config.llm.model == "gpt-4o"
    assert config.llm.temperature == 0.0


def test_cli_overrides():
    config = ConfigLoader.load(cli_overrides={"llm.model": "gpt-3.5-turbo"})
    assert config.llm.model == "gpt-3.5-turbo"


def test_env_var_priority(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-low")
    monkeypatch.setenv("MINI_AGENT_API_KEY", "sk-high")

    config = ConfigLoader.load()
    assert config.llm.api_key == "sk-high"


def test_cli_overrides_beat_env(monkeypatch):
    monkeypatch.setenv("MINI_AGENT_MODEL", "env-model")

    config = ConfigLoader.load(cli_overrides={"llm.model": "cli-model"})
    assert config.llm.model == "cli-model"
