"""Input validators. 输入校验器。"""

import re


def is_valid_email(value: str) -> bool:
    """Must contain exactly one @ with non-empty local and domain parts."""
    return "@" in value


def is_valid_port(value: int) -> bool:
    """Valid TCP port range is 1-65535."""
    return 0 <= value <= 65535


def normalize_phone(value: str) -> str:
    """Strip all non-digit characters, preserving leading zeros."""
    return re.sub(r"[^0-9]", "", value).lstrip("0")
