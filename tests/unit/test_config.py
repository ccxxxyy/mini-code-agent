"""Tests for configuration loading. 配置加载的测试。"""

import pytest

from mini_agent.config.loader import ConfigLoader

ENV_VARS = [
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "MINI_AGENT_PROVIDER",
    "MINI_AGENT_MODEL",
    "MINI_AGENT_API_KEY",
    "MINI_AGENT_BASE_URL",
    "MINI_AGENT_PROFILES",
    "MINI_AGENT_MODELS",
]


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch, tmp_path):
    """Clear relevant env vars and prevent .env auto-loading from project root.
    清除相关环境变量，并防止从项目根目录自动加载 .env。
    """
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


# --- LLM profiles 多 LLM 档案 ---


def test_models_loaded(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-default")
    monkeypatch.setenv("MINI_AGENT_MODELS", "fast,smart")
    monkeypatch.setenv("MODEL_FAST_MODEL", "deepseek-chat")
    monkeypatch.setenv("MODEL_FAST_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("MODEL_SMART_MODEL", "claude-sonnet-4-20250514")
    monkeypatch.setenv("MODEL_SMART_PROVIDER", "anthropic")
    monkeypatch.setenv("MODEL_SMART_API_KEY", "sk-ant-x")

    config = ConfigLoader.load()
    assert set(config.llm_profiles.keys()) == {"fast", "smart"}

    fast = config.llm_profiles["fast"]
    assert fast.model == "deepseek-chat"
    assert fast.base_url == "https://api.deepseek.com/v1"
    assert fast.api_key == "sk-default"  # 继承默认 key

    smart = config.llm_profiles["smart"]
    assert smart.provider == "anthropic"
    assert smart.api_key == "sk-ant-x"  # 独立 key


def test_legacy_profiles_still_work(monkeypatch):
    # 旧命名 MINI_AGENT_PROFILES / PROFILE_X_* 向后兼容
    monkeypatch.setenv("OPENAI_API_KEY", "sk-default")
    monkeypatch.setenv("MINI_AGENT_PROFILES", "old")
    monkeypatch.setenv("PROFILE_OLD_MODEL", "legacy-model")

    config = ConfigLoader.load()
    assert config.llm_profiles["old"].model == "legacy-model"


def test_models_without_model_skipped(monkeypatch):
    monkeypatch.setenv("MINI_AGENT_MODELS", "broken")
    # MODEL_BROKEN_MODEL 未设置 → 该条目被跳过
    config = ConfigLoader.load()
    assert "broken" not in config.llm_profiles


def test_no_profiles_by_default():
    config = ConfigLoader.load()
    assert config.llm_profiles == {}
