"""Runtime environment detection. 运行环境探测。"""

import os
import sys


def detect_shell() -> str:
    return os.environ.get("SHELL", "cmd.exe" if sys.platform == "win32" else "/bin/bash")
