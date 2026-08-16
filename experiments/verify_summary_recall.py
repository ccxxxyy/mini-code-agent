"""P67 无污染摘要召回验证：证明 LLM 能从压缩摘要（而非残留历史）恢复信息。

运行：uv run python experiments/verify_summary_recall.py

设计要点（排除巧合与历史污染）：
1. 埋点是虚构事实（代码库/常识中不存在），且覆盖五种难度递增的类型：
   - 因果链（决策 + 原因，不是名词记忆）
   - 中途反转（先说 30 后改 45——只抓首次提及的摘要会答错）
   - 否定约束（"不要用 pandas"——禁止性信息最易被摘要丢弃）
   - 英文标识符（精确字符串，错一字符即 FAIL）
   - 陷阱题（问从未埋过的事实，答"没有"才过——暴露幻觉/巧合）
2. 对话含工具调用对，模拟真实会话结构
3. 压缩后程序化验证所有埋点不在保留消息中——答案唯一可能来源是摘要
4. 每题独立 LLM 调用，互不提示
"""

import asyncio

from mini_agent.config.loader import ConfigLoader
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.memory.compressor import LLMSummarizeOldest
from mini_agent.models.message import Conversation, Message, Role, ToolCall, ToolResult

PLANT_MARKS = ["45 秒", "SQLite", "pandas", "MX_GATEWAY_TOKEN_v3", "离线内网", "30 秒"]

QUESTIONS = [
    ("反转", "请求超时阈值最终定的是多少秒？", lambda a: "45" in a),
    (
        "因果",
        "我们为什么放弃了 Redis 方案？",
        lambda a: ("离线" in a or "内网" in a) and "SQLite" in a,
    ),
    (
        "否定约束",
        "处理 CSV 应该用什么库？有什么禁止事项？",
        lambda a: "csv" in a.lower() and "pandas" in a.lower(),
    ),
    ("标识符", "网关鉴权的环境变量名是什么？", lambda a: "MX_GATEWAY_TOKEN_v3" in a),
    (
        "陷阱",
        "我们之前定过数据库的连接密码吗？是多少？",
        lambda a: any(k in a for k in ["没有", "未", "不曾", "没提", "无"]),
    ),
]


def make_conv() -> Conversation:
    conv = Conversation()

    def add(role: Role, text: str, tokens: int = 500) -> None:
        m = Message(role=role, content=text)
        m.token_count = tokens
        conv.messages.append(m)

    add(
        Role.USER,
        "架构决定：放弃 Redis 缓存方案，改用本地 SQLite，"
        "原因是部署环境是离线内网，没法起 Redis 服务",
    )
    add(Role.ASSISTANT, "明白，缓存层用本地 SQLite，因为离线内网环境无法部署 Redis。")
    add(Role.USER, "请求超时阈值先设 30 秒")
    add(Role.ASSISTANT, "好的，超时 30 秒。")
    tc = Message(
        role=Role.ASSISTANT,
        tool_calls=[ToolCall(id="t1", name="read_file", arguments={"file_path": "config.py"})],
    )
    tc.token_count = 300
    conv.messages.append(tc)
    tr = Message(
        role=Role.TOOL,
        tool_result=ToolResult(call_id="t1", name="read_file", output="TIMEOUT = 30"),
    )
    tr.token_count = 300
    conv.messages.append(tr)
    add(Role.USER, "改一下，刚才的超时阈值不要 30 了，最终定为 45 秒")
    add(Role.ASSISTANT, "收到，超时阈值最终值是 45 秒（覆盖之前的 30 秒）。")
    add(Role.USER, "处理 CSV 的时候不要引入 pandas，就用标准库的 csv 模块")
    add(Role.ASSISTANT, "明白，CSV 处理只用标准库 csv，不引入 pandas。")
    add(Role.USER, "网关鉴权的环境变量名叫 MX_GATEWAY_TOKEN_v3，别拼错")
    add(Role.ASSISTANT, "记住了：MX_GATEWAY_TOKEN_v3。")
    for i in range(10):  # 填充轮次把埋点推出保留窗口
        add(Role.USER if i % 2 else Role.ASSISTANT, f"关于界面配色的闲聊第 {i} 轮", 3000)
    return conv


async def ask(llm, base_messages: list[dict], q: str) -> str:
    msgs = base_messages + [{"role": "user", "content": q}]
    parts: list[str] = []
    async for chunk in llm.stream(msgs):
        if chunk.delta:
            parts.append(chunk.delta)
    return "".join(parts).strip()


async def main() -> None:
    config = ConfigLoader.load()
    llm = ProviderRegistry.create(config.llm)
    await llm.prepare()
    conv = make_conv()
    n0 = len(conv.messages)
    await LLMSummarizeOldest(llm).compress(conv, target_tokens=7500)
    kept = conv.messages[1:]
    kept_text = "\n".join(m.content or "" for m in kept)
    dirty = [x for x in PLANT_MARKS if x in kept_text]
    print(f"压缩: {n0} -> 1 摘要 + {len(kept)} 保留")
    print("污染检查:", dirty or "无 —— 答案只能来自摘要")
    if dirty:
        print("测试无效：埋点仍在历史里，需增加填充轮次")
        return

    base = [{"role": "system", "content": conv.messages[0].content}]
    base += [{"role": m.role.value, "content": m.content or ""} for m in kept]
    passed = 0
    for name, q, check in QUESTIONS:
        a = await ask(llm, base, q)
        ok = check(a)
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {q}")
        print(f"    答: {a[:150]}")
    print("=" * 40)
    print(f"总分: {passed}/{len(QUESTIONS)}")


if __name__ == "__main__":
    asyncio.run(main())
