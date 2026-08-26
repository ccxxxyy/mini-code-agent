"""Condition expression engine for declarative hook matching.
声明式 hook 条件表达式引擎。

Grammar:
  expression = comparison (('and' | 'or') comparison)*
  comparison = field operator value
  field      = identifier ('.' identifier)*
  operator   = '==' | '!=' | '=~' | '~='
  value      = quoted_string | bare_word

Operators:
  ==  exact string match
  !=  not equal
  =~  regex (re.search)
  ~=  glob (fnmatch)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any

log = logging.getLogger(__name__)

_COMPARISON_RE = re.compile(
    r"""^\s*
    (?P<field>[\w][\w.]*)          # field: tool, args.command, etc.
    \s*
    (?P<op>==|!=|=~|~=)           # operator
    \s*
    (?:
        '(?P<sq>[^']*)'           # single-quoted value
      | "(?P<dq>[^"]*)"          # double-quoted value
      | (?P<bare>\S+)            # bare word (no spaces)
    )
    \s*$""",
    re.VERBOSE,
)

_AND_SPLIT = re.compile(r"\s+and\s+", re.IGNORECASE)
_OR_SPLIT = re.compile(r"\s+or\s+", re.IGNORECASE)


@dataclass
class Condition:
    """A single comparison: field operator value."""

    field: str
    operator: str  # "==" | "!=" | "=~" | "~="
    value: str


@dataclass
class ConditionGroup:
    """A group of conditions joined by a single logic combinator."""

    conditions: list[Condition]
    logic: str  # "and" | "or"


def parse_condition(expr: str) -> ConditionGroup | None:
    """Parse a condition expression string into a ConditionGroup.

    Returns None on invalid input (logged as warning, never crashes).
    Mixing 'and' and 'or' in the same expression is rejected.
    """
    if not expr or not expr.strip():
        return None

    expr = expr.strip()
    has_and = bool(_AND_SPLIT.search(expr))
    has_or = bool(_OR_SPLIT.search(expr))

    if has_and and has_or:
        log.warning("condition: mixing 'and'/'or' not supported: %s", expr)
        return None

    if has_and:
        parts = _AND_SPLIT.split(expr)
        logic = "and"
    elif has_or:
        parts = _OR_SPLIT.split(expr)
        logic = "or"
    else:
        parts = [expr]
        logic = "and"

    conditions: list[Condition] = []
    for part in parts:
        m = _COMPARISON_RE.match(part)
        if not m:
            log.warning("condition: invalid comparison '%s'", part)
            return None
        field = m.group("field")
        op = m.group("op")
        value = (
            m.group("sq")
            if m.group("sq") is not None
            else (m.group("dq") if m.group("dq") is not None else m.group("bare"))
        )

        if op == "=~":
            try:
                re.compile(value)
            except re.error as e:
                log.warning("condition: invalid regex '%s': %s", value, e)
                return None

        conditions.append(Condition(field=field, operator=op, value=value))

    return ConditionGroup(conditions=conditions, logic=logic)


def resolve_field(field: str, context: dict[str, Any]) -> str:
    """Resolve a dotted field path against a context dict.

    "tool"         -> str(context["tool"])
    "args.command"  -> str(context["args"]["command"])
    Missing keys   -> ""
    """
    parts = field.split(".")
    current: Any = context
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return ""
        if current is None:
            return ""
    return str(current)


def evaluate_condition(group: ConditionGroup, context: dict[str, Any]) -> bool:
    """Evaluate a parsed condition group against a runtime context.

    Context shape: {"tool": str, "event": str, "args": dict[str, Any]}.
    """

    def _eval_single(cond: Condition) -> bool:
        actual = resolve_field(cond.field, context)
        try:
            if cond.operator == "==":
                return actual == cond.value
            if cond.operator == "!=":
                return actual != cond.value
            if cond.operator == "=~":
                return bool(re.search(cond.value, actual))
            if cond.operator == "~=":
                return fnmatch(actual, cond.value)
        except Exception:
            log.debug("condition eval error: %s %s %s", cond.field, cond.operator, cond.value)
            return False
        return False

    if group.logic == "or":
        return any(_eval_single(c) for c in group.conditions)
    return all(_eval_single(c) for c in group.conditions)
