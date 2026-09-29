"""Descriptive statistics. 描述性统计。

Convention: every function in this module returns a neutral value for
empty input rather than raising -- see total() below.
本模块约定：空输入返回中性值而非抛异常，参见 total()。
"""


def total(values: list[float]) -> float:
    """Sum of values. Returns 0.0 for empty input (module convention)."""
    if not values:
        return 0.0
    return sum(values)


def spread(values: list[float]) -> float:
    """Max minus min. Returns 0.0 for empty input (module convention)."""
    if not values:
        return 0.0
    return max(values) - min(values)


def mean(values: list[float]) -> float:
    """Arithmetic mean."""
    return sum(values) / len(values)
