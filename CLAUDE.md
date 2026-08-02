# Mini-Code-Agent

Python 终端编程 Agent 工具，仿 Claude Code。架构见 `docs/spec.md`，任务清单见 `docs/tasks.md`，验收标准见 `docs/checklist.md`。

## 常用命令

```bash
uv sync --extra dev          # 安装依赖（含开发工具）
uv run mini-agent            # 启动 Agent
uv run pytest tests/         # 运行测试
uv run ruff check src/ tests/    # Lint
uv run ruff format src/ tests/   # 格式化
```

## 架构要点

- 五层架构：交互层(ui/) → 引擎层(core/) → 工具层(tools/) → 记忆层(memory/) → 安全层(security/)，通过 events/bus.py 的 EventBus 解耦
- LLM Provider 抽象在 llm/，直接用 httpx 不依赖供应商 SDK
- 所有 I/O 全异步（asyncio）
- 核心数据模型用 dataclass（models/）
- 配置分层：CLI 参数 > 环境变量 > .env > 项目配置 > 用户配置 > 默认值

## 代码规范

- Python 3.11+，全类型注解
- ruff line-length 100，target py311
- 测试放 tests/unit/ 和 tests/integration/，用 pytest + pytest-asyncio (auto mode)
- 工具类实现 Tool ABC（schema 属性 + execute 方法），注册到 ToolRegistry
