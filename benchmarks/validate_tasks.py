"""Validate benchmark tasks: unfixed must FAIL, intended fix must PASS.
校验评测任务：未修改必须失败，打上预期修复必须通过。

Must run under the project venv so `python -m pytest` resolves to a
pytest-bearing interpreter:  uv run python benchmarks/validate_tasks.py
必须在项目 venv 下运行，否则 `python -m pytest` 会落到无 pytest 的系统
解释器上：uv run python benchmarks/validate_tasks.py
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

BENCH = pathlib.Path(__file__).resolve().parent
TASKS = BENCH / "tasks"
WORKSPACES = BENCH / "workspaces"

NEW_TASKS = [
    "hidden_dependency_bug",
    "conflicting_constraints",
    "large_file_navigation",
    "infer_convention",
    "three_bugs",
    "create_from_tests",
]

# Substring replacements that constitute the intended fix
# 构成预期修复的字符串替换
REPLACE: dict[str, list[tuple[str, str, str]]] = {
    "hidden_dependency_bug": [("parser.py", 'split(";")', 'split(",")')],
    "large_file_navigation": [("bigmodule.py", "% 255", "% 256")],
    "infer_convention": [
        (
            "stats.py",
            '    """Arithmetic mean."""\n    return sum(values) / len(values)',
            '    """Arithmetic mean. Returns 0.0 for empty input."""\n'
            "    if not values:\n        return 0.0\n"
            "    return sum(values) / len(values)",
        )
    ],
}

# Whole-file rewrites that constitute the intended fix 整文件重写型修复
REWRITE: dict[str, tuple[str, str]] = {
    "conflicting_constraints": (
        "discount.py",
        '"""Order pricing."""\n\n\n'
        "def final_price(unit_price: float, quantity: int, is_member: bool) -> float:\n"
        '    """Additive discounts."""\n'
        "    rate = 0.0\n"
        "    if quantity >= 10:\n"
        "        rate += 0.10\n"
        "    if is_member:\n"
        "        rate += 0.05\n"
        "    return unit_price * quantity * (1 - rate)\n",
    ),
    "three_bugs": (
        "validators.py",
        '"""Input validators."""\n\nimport re\n\n\n'
        "def is_valid_email(value: str) -> bool:\n"
        '    parts = value.split("@")\n'
        "    return len(parts) == 2 and all(parts)\n\n\n"
        "def is_valid_port(value: int) -> bool:\n"
        "    return 1 <= value <= 65535\n\n\n"
        "def normalize_phone(value: str) -> str:\n"
        '    return re.sub(r"[^0-9]", "", value)\n',
    ),
    "create_from_tests": (
        "geometry.py",
        '"""Shapes."""\n\nimport math\n\n\n'
        "class Circle:\n"
        "    def __init__(self, radius: float) -> None:\n"
        "        if radius < 0:\n"
        '            raise ValueError("radius must be non-negative")\n'
        "        self.radius = radius\n\n"
        "    def area(self) -> float:\n"
        "        return math.pi * self.radius**2\n\n\n"
        "class Rectangle:\n"
        "    def __init__(self, width: float, height: float) -> None:\n"
        "        if width < 0 or height < 0:\n"
        '            raise ValueError("dimensions must be non-negative")\n'
        "        self.width = width\n"
        "        self.height = height\n\n"
        "    def area(self) -> float:\n"
        "        return self.width * self.height\n\n\n"
        "def total_area(shapes) -> float:\n"
        "    return sum(s.area() for s in shapes)\n",
    ),
}


def verify_command(task: str) -> str:
    text = (TASKS / f"{task}.yaml").read_text(encoding="utf-8")
    m = re.search(r'verify_command:\s*"(.+?)"', text)
    if not m:
        raise ValueError(f"{task}: no verify_command")
    return m.group(1)


def run(task: str, apply_fix: bool) -> tuple[int, str]:
    cmd = verify_command(task)
    with tempfile.TemporaryDirectory(prefix=f"vt_{task}_") as tmp:
        root = pathlib.Path(tmp)
        shutil.copytree(WORKSPACES / task, root, dirs_exist_ok=True)
        if apply_fix:
            for fname, old, new in REPLACE.get(task, []):
                p = root / fname
                s = p.read_text(encoding="utf-8")
                if old not in s:
                    return -99, f"fix snippet not found in {fname}"
                p.write_text(s.replace(old, new), encoding="utf-8")
            if task in REWRITE:
                fname, content = REWRITE[task]
                (root / fname).write_text(content, encoding="utf-8")
        proc = subprocess.run(
            cmd, shell=True, cwd=str(root), capture_output=True, text=True, timeout=120
        )
    tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-160:].replace("\n", " ")
    return proc.returncode, tail


def main() -> int:
    print(f"interpreter: {sys.executable}")
    try:
        import pytest  # noqa: F401

        print(f"pytest: {pytest.__version__}\n")
    except ImportError:
        print("FATAL: pytest missing -- run under `uv run`\n")
        return 2

    failures: list[str] = []
    print(f"{'task':26s} {'unfixed':>9s} {'fixed':>7s}  verdict")
    for task in NEW_TASKS:
        rc_unfixed, tail_u = run(task, apply_fix=False)
        rc_fixed, tail_f = run(task, apply_fix=True)
        good = rc_unfixed != 0 and rc_fixed == 0
        if not good:
            failures.append(task)
        verdict = "OK" if good else "BAD"
        if rc_unfixed == 0:
            verdict += " (passes unfixed -- task is free points)"
        if rc_fixed != 0:
            verdict += " (unsolvable)"
        print(f"{task:26s} {rc_unfixed:>9d} {rc_fixed:>7d}  {verdict}")
        if rc_unfixed == 0:
            print(f"    unfixed tail: {tail_u}")
        if rc_fixed != 0:
            print(f"    fixed   tail: {tail_f}")

    print()
    if failures:
        print(f"INVALID TASKS: {failures}")
        return 1
    print(f"ALL {len(NEW_TASKS)} NEW TASKS VALID (fail unfixed, pass when fixed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
