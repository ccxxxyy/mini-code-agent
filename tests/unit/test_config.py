"""Tests for configuration loading."""

import pytest

from mini_agent.config.loader import ConfigLoader

ENV_VARS = [
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "MINI_AGENT_PROVIDER",
    "MINI_AGENT_MODEL",
    "MINI_AGENT_API_KEY",
    "MINI_AGENT_BASE_URL",
]


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch, tmp_path):
    """Clear relevant env vars and prevent .env auto-loading from project root."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)


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


def test_dotenv_loading(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=sk-from-dotenv\n# comment line\n\nMINI_AGENT_MODEL=dotenv-model\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = ConfigLoader.load()
    assert config.llm.api_key == "sk-from-dotenv"
    assert config.llm.model == "dotenv-model"


def test_real_env_beats_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-real-env")

    config = ConfigLoader.load()
    assert config.llm.api_key == "sk-from-real-env"
