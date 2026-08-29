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


# --- Strong/weak model mixing 强弱模型混编 ---


def test_mixing_profiles_loaded(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("MINI_AGENT_MODELS", "fast,smart")
    monkeypatch.setenv("MODEL_FAST_MODEL", "weak-model")
    monkeypatch.setenv("MODEL_SMART_MODEL", "strong-model")
    monkeypatch.setenv("MINI_AGENT_PLANNER_PROFILE", "smart")
    monkeypatch.setenv("MINI_AGENT_WORKER_PROFILE", "fast")

    config = ConfigLoader.load()
    assert config.planner_profile == "smart"
    assert config.worker_profile == "fast"


def test_mixing_empty_by_default():
    config = ConfigLoader.load()
    assert config.planner_profile == ""
    assert config.worker_profile == ""


def test_create_for_role_uses_profile(monkeypatch):
    from mini_agent.llm.registry import ProviderRegistry

    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("MINI_AGENT_MODELS", "fast,smart")
    monkeypatch.setenv("MODEL_FAST_MODEL", "weak-model")
    monkeypatch.setenv("MODEL_SMART_MODEL", "strong-model")
    monkeypatch.setenv("MINI_AGENT_PLANNER_PROFILE", "smart")
    monkeypatch.setenv("MINI_AGENT_WORKER_PROFILE", "fast")

    config = ConfigLoader.load()
    planner_llm = ProviderRegistry.create_for_role(config, "planner")
    worker_llm = ProviderRegistry.create_for_role(config, "worker")
    assert planner_llm._config.model == "strong-model"
    assert worker_llm._config.model == "weak-model"


def test_create_for_role_falls_back_to_main(monkeypatch):
    from mini_agent.llm.registry import ProviderRegistry

    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("MINI_AGENT_MODEL", "main-model")

    config = ConfigLoader.load()
    # No mixing configured -> both roles use the main llm
    # 未配置混编 → 两个角色都用主模型
    planner_llm = ProviderRegistry.create_for_role(config, "planner")
    assert planner_llm._config.model == "main-model"


def test_create_for_role_unknown_profile_falls_back(monkeypatch):
    from mini_agent.llm.registry import ProviderRegistry

    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("MINI_AGENT_MODEL", "main-model")
    monkeypatch.setenv("MINI_AGENT_PLANNER_PROFILE", "nonexistent")

    config = ConfigLoader.load()
    planner_llm = ProviderRegistry.create_for_role(config, "planner")
    assert planner_llm._config.model == "main-model"


# --- TOML configuration TOML 配置 ---


def test_load_user_toml(monkeypatch, tmp_path):
    toml_dir = tmp_path / ".mini-agent"
    toml_dir.mkdir()
    (toml_dir / "config.toml").write_text('[llm]\nmodel = "toml-model"\n', encoding="utf-8")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    config = ConfigLoader.load()
    assert config.llm.model == "toml-model"


def test_project_toml_overrides_user(monkeypatch, tmp_path):
    user_dir = tmp_path / "home" / ".mini-agent"
    user_dir.mkdir(parents=True)
    (user_dir / "config.toml").write_text('[llm]\nmodel = "user-model"\n', encoding="utf-8")

    proj_dir = tmp_path / "project" / ".mini-agent"
    proj_dir.mkdir(parents=True)
    (proj_dir / "config.toml").write_text('[llm]\nmodel = "project-model"\n', encoding="utf-8")

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")
    monkeypatch.chdir(tmp_path / "project")

    config = ConfigLoader.load()
    assert config.llm.model == "project-model"


def test_env_overrides_toml(monkeypatch, tmp_path):
    toml_dir = tmp_path / ".mini-agent"
    toml_dir.mkdir()
    (toml_dir / "config.toml").write_text('[llm]\nmodel = "toml-model"\n', encoding="utf-8")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MINI_AGENT_MODEL", "env-model")

    config = ConfigLoader.load()
    assert config.llm.model == "env-model"


def test_merge_partial(monkeypatch, tmp_path):
    toml_dir = tmp_path / ".mini-agent"
    toml_dir.mkdir()
    (toml_dir / "config.toml").write_text(
        '[llm]\nmodel = "custom"\n\n[memory]\nauto_extract = false\n', encoding="utf-8"
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    config = ConfigLoader.load()
    assert config.llm.model == "custom"
    assert config.llm.provider == "openai"
    assert config.memory.auto_extract is False
    assert config.memory.context_window == 128_000


def test_merge_mcp_servers(monkeypatch, tmp_path):
    toml_dir = tmp_path / ".mini-agent"
    toml_dir.mkdir()
    toml_content = (
        "[mcp.servers.github]\n"
        'command = "npx"\n'
        'args = ["-y", "@mcp/server-github"]\n'
        'transport = "stdio"\n'
    )
    (toml_dir / "config.toml").write_text(toml_content, encoding="utf-8")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    config = ConfigLoader.load()
    assert "github" in config.mcp.servers
    assert config.mcp.servers["github"].command == "npx"
    assert config.mcp.servers["github"].transport == "stdio"


def test_merge_top_level_scalars(monkeypatch, tmp_path):
    toml_dir = tmp_path / ".mini-agent"
    toml_dir.mkdir()
    (toml_dir / "config.toml").write_text(
        'theme = "dark"\nmax_agent_iterations = 30\n', encoding="utf-8"
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    config = ConfigLoader.load()
    assert config.theme == "dark"
    assert config.max_agent_iterations == 30


def test_profile_roles_from_toml_survive_without_env(monkeypatch, tmp_path):
    """TOML-set planner/worker_profile must not be wiped by the unset-env
    default (regression: unconditional env assign cleared TOML values).
    TOML 配置的混编 profile 不能被未设置的环境变量空缺省清掉（回归：
    无条件 env 赋值曾清空 TOML 值）。"""
    toml_dir = tmp_path / ".mini-agent"
    toml_dir.mkdir()
    (toml_dir / "config.toml").write_text(
        'planner_profile = "smart"\nworker_profile = "fast"\n', encoding="utf-8"
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MINI_AGENT_PLANNER_PROFILE", raising=False)
    monkeypatch.delenv("MINI_AGENT_WORKER_PROFILE", raising=False)

    config = ConfigLoader.load()
    assert config.planner_profile == "smart"
    assert config.worker_profile == "fast"


def test_profile_roles_env_overrides_toml(monkeypatch, tmp_path):
    toml_dir = tmp_path / ".mini-agent"
    toml_dir.mkdir()
    (toml_dir / "config.toml").write_text('planner_profile = "smart"\n', encoding="utf-8")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MINI_AGENT_PLANNER_PROFILE", "env-wins")

    config = ConfigLoader.load()
    assert config.planner_profile == "env-wins"
