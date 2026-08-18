"""End-to-end verification of PermissionDecision.PENDING cross-process protocol.
全管道无污染验证：跨进程权限审批协议。

Runs TWO concurrent coroutines in one process to simulate worker + parent:
  - worker_side: builds the REAL permission stack (PathGuard + PermissionManager
    + RemoteConfirm) and calls check_command("git push origin main")
  - parent_side: polls for .perm-request.json, reads it, prints it, writes
    .perm-decision.json with "y"

Every step prints a timestamped checkpoint so we can audit the full chain.
每一步打印带时间戳的检查点，供审计完整链路。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from mini_agent.events.bus import EventBus
from mini_agent.models.config import SecurityConfig, ToolConfig
from mini_agent.models.events import PermissionCheckEvent
from mini_agent.models.permissions import PermissionDecision
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager
from mini_agent.security.remote_confirm import RemoteConfirm, read_request, write_decision

AGENT_ID = "verify-001"


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


async def worker_side(workers_dir: Path, events: list[dict]) -> PermissionDecision:
    """Simulate the worker process: build real permission stack, check a
    dangerous command. This is the EXACT code path that worker.py now runs.
    模拟 worker 进程：搭建真实权限栈，检查危险命令。"""
    print(f"[{ts()}] WORKER: building permission stack...")

    event_bus = EventBus()
    collected_events: list[PermissionCheckEvent] = []

    async def on_perm(e: PermissionCheckEvent) -> None:
        collected_events.append(e)
        events.append({
            "ts": ts(),
            "side": "worker",
            "event": "PermissionCheckEvent",
            "decision": e.decision,
            "reason": e.reason,
            "scope": e.scope,
            "resource": e.resource[:80],
        })
        print(f"[{ts()}] WORKER EVENT: decision={e.decision}, reason={e.reason}")

    event_bus.on(PermissionCheckEvent, on_perm)

    path_guard = PathGuard(
        tool_config=ToolConfig(),
        security_config=SecurityConfig(),
        project_dir=Path.cwd(),
    )
    remote_confirm = RemoteConfirm(
        workers_dir, AGENT_ID, poll_interval=0.1, timeout=10.0
    )
    pm = PermissionManager(
        config=SecurityConfig(permission_mode="ask"),
        path_guard=path_guard,
        confirm_callback=remote_confirm,
        event_bus=event_bus,
    )

    print(f"[{ts()}] WORKER: calling check_command('git push origin main')...")
    print(f"[{ts()}] WORKER: is_dangerous_command = {pm.is_dangerous_command('git push origin main')}")

    decision = await pm.check_command("git push origin main")

    print(f"[{ts()}] WORKER: decision = {decision}")
    print(f"[{ts()}] WORKER: last_decision_reason = {pm.last_decision_reason}")
    print(f"[{ts()}] WORKER: events collected = {len(collected_events)}")
    for i, e in enumerate(collected_events):
        print(f"  event[{i}]: decision={e.decision}, reason={e.reason}")

    return decision


async def parent_side(workers_dir: Path, answer: str, events: list[dict]) -> None:
    """Simulate the parent process: poll for .perm-request.json, read it,
    write .perm-decision.json. This is the EXACT code path that
    _collect_pane_result() now runs.
    模拟父进程：轮询 .perm-request.json，读取后写 .perm-decision.json。"""
    print(f"[{ts()}] PARENT: polling for permission request...")

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        req = read_request(workers_dir, AGENT_ID)
        if req and req.get("status") == "pending":
            print(f"[{ts()}] PARENT: found permission request!")
            print(f"  request_id = {req['request_id']}")
            print(f"  agent_id   = {req['agent_id']}")
            print(f"  prompt     = {req['prompt'][:100]}")
            print(f"  status     = {req['status']}")

            events.append({
                "ts": ts(),
                "side": "parent",
                "event": "read_request",
                "request_id": req["request_id"],
                "prompt": req["prompt"][:100],
            })

            # Verify file actually exists on disk
            req_path = workers_dir / f"{AGENT_ID}.perm-request.json"
            raw = req_path.read_text(encoding="utf-8")
            print(f"[{ts()}] PARENT: raw file content = {raw}")

            print(f"[{ts()}] PARENT: writing decision '{answer}'...")
            write_decision(workers_dir, AGENT_ID, req["request_id"], answer)

            # Verify decision file exists
            dec_path = workers_dir / f"{AGENT_ID}.perm-decision.json"
            dec_raw = dec_path.read_text(encoding="utf-8")
            print(f"[{ts()}] PARENT: decision file content = {dec_raw}")

            events.append({
                "ts": ts(),
                "side": "parent",
                "event": "write_decision",
                "decision": answer,
            })
            return

        await asyncio.sleep(0.05)

    print(f"[{ts()}] PARENT: TIMEOUT - no permission request found!")
    events.append({"ts": ts(), "side": "parent", "event": "timeout"})


async def run_test(answer: str, expected: PermissionDecision) -> dict:
    """Run one test case with a given answer and expected decision."""
    import tempfile
    workers_dir = Path(tempfile.mkdtemp(prefix="perm-verify-"))
    events: list[dict] = []

    print(f"\n{'='*70}")
    print(f"TEST: answer='{answer}', expected={expected}")
    print(f"workers_dir = {workers_dir}")
    print(f"{'='*70}")

    worker_task = asyncio.create_task(worker_side(workers_dir, events))
    parent_task = asyncio.create_task(parent_side(workers_dir, answer, events))

    decision = await worker_task
    await parent_task

    # Verify files are cleaned up by RemoteConfirm
    req_exists = (workers_dir / f"{AGENT_ID}.perm-request.json").exists()
    dec_exists = (workers_dir / f"{AGENT_ID}.perm-decision.json").exists()
    print(f"\n[{ts()}] CLEANUP: request file exists = {req_exists}")
    print(f"[{ts()}] CLEANUP: decision file exists = {dec_exists}")

    passed = decision == expected and not req_exists and not dec_exists
    print(f"\n[{ts()}] RESULT: decision={decision}, expected={expected}, "
          f"files_cleaned={not req_exists and not dec_exists}")
    print(f"[{ts()}] {'PASS ✅' if passed else 'FAIL ❌'}")

    return {
        "answer": answer,
        "expected": expected.value,
        "actual": decision.value,
        "files_cleaned": not req_exists and not dec_exists,
        "passed": passed,
        "events": events,
    }


async def run_timeout_test() -> dict:
    """Test that RemoteConfirm times out and denies when no parent responds."""
    import tempfile
    workers_dir = Path(tempfile.mkdtemp(prefix="perm-verify-timeout-"))
    events: list[dict] = []

    print(f"\n{'='*70}")
    print(f"TEST: timeout (no parent responds), expected=DENIED")
    print(f"{'='*70}")

    event_bus = EventBus()
    collected: list[PermissionCheckEvent] = []

    async def on_perm(e: PermissionCheckEvent) -> None:
        collected.append(e)
        print(f"[{ts()}] WORKER EVENT: decision={e.decision}, reason={e.reason}")

    event_bus.on(PermissionCheckEvent, on_perm)

    path_guard = PathGuard(
        tool_config=ToolConfig(),
        security_config=SecurityConfig(),
        project_dir=Path.cwd(),
    )
    rc = RemoteConfirm(workers_dir, AGENT_ID, poll_interval=0.05, timeout=0.5)
    pm = PermissionManager(
        config=SecurityConfig(permission_mode="ask"),
        path_guard=path_guard,
        confirm_callback=rc,
        event_bus=event_bus,
    )

    print(f"[{ts()}] WORKER: checking dangerous command with NO parent...")
    decision = await pm.check_command("sudo rm -rf /")
    print(f"[{ts()}] WORKER: decision = {decision}")

    passed = decision == PermissionDecision.DENIED
    print(f"[{ts()}] {'PASS ✅' if passed else 'FAIL ❌'}")

    pending_events = [e for e in collected if e.decision == "pending"]
    denied_events = [e for e in collected if e.decision == "denied"]

    return {
        "answer": "none (timeout)",
        "expected": "denied",
        "actual": decision.value,
        "pending_events": len(pending_events),
        "denied_events": len(denied_events),
        "passed": passed,
        "events": events,
    }


async def main():
    print(f"PermissionDecision.PENDING E2E Verification")
    print(f"Started at {ts()}")
    print()

    results = []

    # Test 1: parent answers "y" -> GRANTED
    results.append(await run_test("y", PermissionDecision.GRANTED))

    # Test 2: parent answers "n" -> DENIED
    results.append(await run_test("n", PermissionDecision.DENIED))

    # Test 3: parent answers "a" (always) -> GRANTED
    results.append(await run_test("a", PermissionDecision.GRANTED))

    # Test 4: timeout (no parent) -> DENIED
    results.append(await run_timeout_test())

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    all_passed = True
    for r in results:
        status = "✅" if r["passed"] else "❌"
        print(f"  {status} answer={r['answer']}: "
              f"expected={r['expected']}, actual={r['actual']}")
        if not r["passed"]:
            all_passed = False

    print(f"\n{'PASS' if all_passed else 'FAIL'}: "
          f"{sum(1 for r in results if r['passed'])}/{len(results)} tests passed")

    # Write forensic JSON
    out = Path(__file__).parent / "results" / "verify_pending.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nForensic JSON: {out}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
