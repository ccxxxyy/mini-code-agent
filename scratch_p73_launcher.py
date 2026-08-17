"""P73 终端验证启动器：其余全真，只做一件事——
把第一次摘要请求真实垫大到超过端点限制（交互会话手动够不到 6M 字符），
让真实端点返回真 400，然后现场观看收缩重试。

用法：uv run python scratch_p73_launcher.py   （代替 uv run mini-agent）
"""

import sys

from mini_agent.memory import compressor
from mini_agent.memory.compressor import LLMSummarizeOldest

# 放开 cap，让垫大的 digest 不被 24K 截断（实测 6.1M 字符必触发模型层 400）
LLMSummarizeOldest.MAX_HISTORY_CHARS = 6_500_000

_orig_digest = compressor._extractive_digest
_PAD = ("[user] filler: " + "alpha bravo charlie delta " * 10 + "\n") * 24_000  # ~6.6M 字符
_state = {"padded": False}


def _inflated_digest(messages):
    digest = _orig_digest(messages)
    if not _state["padded"]:
        _state["padded"] = True  # 只垫首次——收缩重试重建 digest 时恢复正常尺寸
        print(
            ">>> [P73] 首次摘要 digest 已垫大到 ~6.5M 字符，预期端点返回真 400",
            file=sys.stderr,
        )
        return _PAD + digest
    return digest


compressor._extractive_digest = _inflated_digest

from mini_agent.cli import main

main()
