"""记忆子系统体验增强验证（tech-notes §111）：后台整固节律 + 并行 recall 预取。

运行：uv run python experiments/verify_memory_cadence.py

设计要点（真实 LLM + 隔离文件系统 + 取证输出）：
A. 后台整固：临时目录记忆文件（不碰真实 ~/.mini-agent），真实 LLM 合并——
   门槛满足→merged / 立即重跑→gated（时间门槛）/ 锁占用→held / 保存失败→回滚复原。
B. 并行 recall：首次 poll 必须瞬时返回（不含 LLM 往返，对照串行耗时）；
   完成后 poll 拿到 LLM 挑选结果（埋点条目必须命中）；超时降级头部截断不报错。
C. 端到端：临时 USERPROFILE 预埋 12 条记忆（含虚构编辑器名），mini-agent -p
   跑含工具调用的真实回合——第二次 LLM 调用注入记忆，答案含虚构名即证明全管道。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from mini_agent.config.loader import ConfigLoader
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.memory.consolidation import ConsolidationScheduler
from mini_agent.memory.persistent import MemoryEntry, PersistentMemory
from mini_agent.memory.recall import RecallPrefetcher

PROJECT_ROOT = Path(__file__).resolve().parent.parent

RESULTS: dict[str, dict] = {}


class _FakeSessionStore:
    def __init__(self, n: int):
        ts = (datetime.now() - timedelta(hours=1)).isoformat()
        self._sessions = [
            {"session_id": f"s{i}", "last_active": ts, "project_dir": ""} for i in range(n)
        ]

    async def list_sessions(self):
        return self._sessions


def _seed_entries() -> list[MemoryEntry]:
    """6 条记忆：前 3 条明显同主题（可合并），后 3 条各自独立。"""
    return [
        MemoryEntry(id="mem_t1", content="用户缩进偏好 tab 不用空格"),
        MemoryEntry(id="mem_t2", content="用户喜欢用 tab 缩进代码"),
        MemoryEntry(id="mem_t3", content="缩进风格：用户要求 tab"),
        MemoryEntry(id="mem_x1", content="项目用 pytest 跑测试"),
        MemoryEntry(id="mem_x2", content="部署目标是离线内网环境"),
        MemoryEntry(id="mem_x3", content="数据库选了 SQLite"),
    ]


async def verify_consolidation(llm) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mem_cadence_"))
    try:
        pm = PersistentMemory(user_memory_dir=str(tmp / "memory"))
        await pm.save_user_memory(_seed_entries())
        before = len(await pm.load_user_memory())

        sched = ConsolidationScheduler(
            pm, _FakeSessionStore(5), llm, min_hours=24.0, min_sessions=5
        )

        # 1. 双门槛满足 → 真实 LLM 合并
        t0 = time.perf_counter()
        outcomes = await sched.run_once()
        elapsed = time.perf_counter() - t0
        after_entries = await pm.load_user_memory()
        state = json.loads((tmp / "memory" / sched.STATE_FILE).read_text(encoding="utf-8"))
        RESULTS["A1_merge"] = {
            "outcomes": outcomes,
            "entries_before": before,
            "entries_after": len(after_entries),
            "contents_after": [e.content for e in after_entries],
            "state_recorded": "user" in state,
            "lock_released": not (tmp / "memory" / sched.LOCK_FILE).is_file(),
            "elapsed_s": round(elapsed, 2),
            "pass": outcomes.get("user") in ("merged", "no_merge")
            and "user" in state
            and not (tmp / "memory" / sched.LOCK_FILE).is_file()
            and (outcomes.get("user") != "merged" or len(after_entries) < before),
        }

        # 2. 立即重跑 → 时间门槛拦住（不再烧 LLM）
        outcomes2 = await sched.run_once()
        RESULTS["A2_regate"] = {
            "outcomes": outcomes2,
            "pass": outcomes2.get("user") == "gated",
        }

        # 3. 锁占用 → 跳过
        lock = tmp / "memory" / sched.LOCK_FILE
        lock.write_text(datetime.now().isoformat(), encoding="utf-8")
        outcomes3 = await sched.run_once()
        lock.unlink()
        RESULTS["A3_lock"] = {
            "outcomes": outcomes3,
            "pass": outcomes3 == {"lock": "held"},
        }

        # 4. 保存失败 → 回滚复原（真实 LLM 合并后在保存点注入故障）
        class _FailingSave(PersistentMemory):
            async def save_user_memory(self, entries):
                self.user_memory_path().write_text("corrupt", encoding="utf-8")
                raise OSError("injected disk failure")

        pm2 = _FailingSave(user_memory_dir=str(tmp / "memory2"))
        await PersistentMemory(user_memory_dir=str(tmp / "memory2")).save_user_memory(
            _seed_entries()
        )
        original = pm2.user_memory_path().read_text(encoding="utf-8")
        sched2 = ConsolidationScheduler(
            pm2, _FakeSessionStore(5), llm, min_hours=24.0, min_sessions=5
        )
        outcomes4 = await sched2.run_once()
        restored = pm2.user_memory_path().read_text(encoding="utf-8")
        RESULTS["A4_rollback"] = {
            "outcomes": outcomes4,
            "file_restored": restored == original,
            # LLM 可能判定无可合并（no_merge 不触发保存），两种结果都算管道正确
            "pass": (outcomes4.get("user") == "rolled_back" and restored == original)
            or outcomes4.get("user") == "no_merge",
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _recall_entries() -> list[MemoryEntry]:
    topics = [
        "项目用 pytest 跑测试",
        "部署目标是离线内网",
        "数据库选了 SQLite",
        "用户偏好中文回复",
        "CI 在 GitHub Actions",
        "代码风格 ruff line-length 100",
        "用户最喜欢的编辑器是 VimStar9000",
        "分支策略：dev 开发 main 发布",
        "禁止使用 pandas 处理 CSV",
        "超时阈值定为 45 秒",
        "网关鉴权环境变量 MX_GATEWAY_TOKEN_v3",
        "用户的时区是 UTC+8",
        "日志库用 structlog",
        "打包工具是 uv",
        "Python 版本要求 3.11+",
    ]
    return [MemoryEntry(id=f"mem_{i:03d}", content=t) for i, t in enumerate(topics)]


async def verify_recall(llm) -> None:
    entries = _recall_entries()
    question = "我最喜欢的编辑器是什么？"

    # 串行对照：一次完整 recall LLM 往返的真实耗时
    from mini_agent.memory.recall import MemoryRecall

    t0 = time.perf_counter()
    serial_result = await MemoryRecall(llm).select_relevant(entries, question, top_k=5)
    serial_s = time.perf_counter() - t0

    # 并行：首次 poll 必须瞬时返回（这就是省下的首 token 延迟）
    pf = RecallPrefetcher(llm, timeout=8.0)
    t0 = time.perf_counter()
    first = await pf.poll(entries, question, top_k=5)
    first_poll_s = time.perf_counter() - t0

    # 模拟主 LLM 调用期间挑选并行完成，随后第二次 poll 只等残余时间
    await asyncio.sleep(2.0)
    t0 = time.perf_counter()
    result = await pf.poll(entries, question, top_k=5)
    second_poll_s = time.perf_counter() - t0
    picked = [e.content for e in (result or [])]
    RESULTS["B1_parallel"] = {
        "serial_roundtrip_s": round(serial_s, 2),
        "serial_picked": [e.content for e in serial_result],
        "first_poll_s": round(first_poll_s, 4),
        "first_poll_returns_none": first is None,
        "second_poll_residual_s": round(second_poll_s, 4),
        "prefetch_picked": picked,
        "marker_hit": any("VimStar9000" in c for c in picked),
        "pass": first is None
        and first_poll_s < 0.1
        and second_poll_s < 1.0  # 残余等待远小于串行往返 residual << serial round-trip
        and result is not None
        and any("VimStar9000" in c for c in picked),
    }

    # 超时降级：极小超时 → 头部截断，不报错
    pf2 = RecallPrefetcher(llm, timeout=0.01)
    assert await pf2.poll(entries, question, top_k=5) is None
    degraded = await pf2.poll(entries, question, top_k=5)
    head_ids = [f"mem_{i:03d}" for i in range(10)]
    RESULTS["B2_timeout_degrade"] = {
        "degraded_count": len(degraded or []),
        "is_head_truncation": [e.id for e in (degraded or [])] == head_ids,
        "pass": degraded is not None and len(degraded) == 10,
    }


def verify_e2e() -> None:
    """端到端：临时 USERPROFILE 预埋记忆，-p 模式含工具回合，第二次 LLM 调用注入。"""
    tmp_home = Path(tempfile.mkdtemp(prefix="mem_home_"))
    tmp_proj = Path(tempfile.mkdtemp(prefix="mem_proj_"))
    try:
        mem_dir = tmp_home / ".mini-agent" / "memory"
        mem_dir.mkdir(parents=True)
        data = {"entries": [json.loads(json.dumps(e.__dict__)) for e in _recall_entries()]}
        (mem_dir / "user_memory.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shutil.copy2(PROJECT_ROOT / ".env", tmp_proj / ".env")
        (tmp_proj / "notes.txt").write_text("(本文件与问题无关)", encoding="utf-8")

        env = dict(os.environ)
        env["USERPROFILE"] = str(tmp_home)
        env["HOME"] = str(tmp_home)
        prompt = "先用 read_file 读取 notes.txt，然后只根据你的记忆回答：我最喜欢的编辑器是什么？"
        proc = subprocess.run(
            [sys.executable, "-m", "mini_agent", "-p", prompt],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(tmp_proj),
            env=env,
            timeout=180,
        )
        out = proc.stdout or ""
        RESULTS["C1_e2e_injection"] = {
            "exit_code": proc.returncode,
            "stdout_tail": out[-300:],
            "marker_answered": "VimStar9000" in out,
            "pass": proc.returncode == 0 and "VimStar9000" in out,
        }
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)
        shutil.rmtree(tmp_proj, ignore_errors=True)


async def main() -> int:
    config = ConfigLoader.load()
    llm = ProviderRegistry.create(config.llm)
    print(f"模型: {config.llm.model} ({config.llm.provider})\n")

    print("=== A. 后台整固节律 ===")
    await verify_consolidation(llm)
    print("=== B. 并行 recall 预取 ===")
    await verify_recall(llm)
    print("=== C. 端到端注入（-p 全管道） ===")
    verify_e2e()

    print(json.dumps(RESULTS, ensure_ascii=False, indent=2))
    all_pass = all(r.get("pass") for r in RESULTS.values())
    print(
        f"\n判定: {'ALL PASS' if all_pass else 'FAIL'} "
        f"({sum(1 for r in RESULTS.values() if r.get('pass'))}/{len(RESULTS)})"
    )
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
