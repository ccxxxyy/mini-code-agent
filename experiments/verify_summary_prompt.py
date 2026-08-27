"""真实 LLM 验证：结构化摘要 prompt（<analysis> + 9 节 <summary>）。

运行：uv run python experiments/verify_summary_prompt.py
验证点：
1. LLMSummarizeOldest 走真实 LLM 产出 9 节结构化摘要（非抽取式回退）
2. <analysis> 草稿不泄漏进对话
3. <summary> 标签本身不泄漏
4. 关键细节（文件名/用户约束/下一步）在摘要中保留
"""

import asyncio

from mini_agent.config.loader import ConfigLoader
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.memory.compressor import LLMSummarizeOldest
from mini_agent.models.message import Conversation, Message, Role


def make_conv() -> Conversation:
    conv = Conversation()
    script = [
        (Role.USER, "帮我修复 login.py 里的认证 bug，用户反馈登录后立即被登出"),
        (Role.ASSISTANT, "我先读取 login.py 检查会话处理逻辑。"),
        (Role.USER, "注意不要改动 session_store.py，那个模块另一个同事在重构"),
        (
            Role.ASSISTANT,
            "发现问题：login.py 第 42 行 `session.expire = time.time()` 应为 "
            "`time.time() + TTL`，过期时间设成了当前时刻导致立即登出。已修复并运行 "
            "pytest tests/test_login.py，8 个测试全部通过。",
        ),
        (Role.USER, "很好，顺便把 TTL 提取成配置项，默认 3600 秒"),
        (
            Role.ASSISTANT,
            "已在 config.py 新增 SESSION_TTL = int(os.getenv('SESSION_TTL', 3600))，"
            "login.py 改为引用该配置。接下来准备补充过期边界的测试用例。",
        ),
    ]
    for role, text in script:
        m = Message(role=role, content=text)
        m.token_count = 3000  # 撑大 token 让 _compute_keep_split 触发切分
        conv.messages.append(m)
    for i in range(14):
        m = Message(role=Role.USER if i % 2 else Role.ASSISTANT, content=f"填充消息 {i}")
        m.token_count = 3000
        conv.messages.append(m)
    return conv


async def main() -> None:
    config = ConfigLoader.load()
    llm = ProviderRegistry.create(config.llm)
    await llm.prepare()
    strategy = LLMSummarizeOldest(llm)
    conv = make_conv()
    n_before = len(conv.messages)
    await strategy.compress(conv, target_tokens=10_000)
    summary_msg = conv.messages[0]
    print(f"messages: {n_before} -> {len(conv.messages)}")
    print("=" * 60)
    print(summary_msg.content)
    print("=" * 60)
    checks = {
        "no <analysis> leak": "<analysis>" not in summary_msg.content,
        "no <summary> tag leak": "<summary>" not in summary_msg.content,
        "LLM summary path (not fallback)": "(LLM summary)" in summary_msg.content,
        "file name preserved": "login.py" in summary_msg.content,
        "user constraint preserved": "session_store" in summary_msg.content,
    }
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}: {name}")


if __name__ == "__main__":
    asyncio.run(main())
