"""Tests for persistent task system (S12). 持久化任务系统测试。"""

from __future__ import annotations

import pytest

from mini_agent.core.task_store import AmbiguousTaskError, TaskRecord, TaskStore

pytestmark = pytest.mark.asyncio


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path)


# --- TaskStore CRUD ---


def test_add_and_load(store):
    t = TaskRecord(description="first task")
    store.add(t)

    tasks = store.load()
    assert len(tasks) == 1
    assert tasks[0].description == "first task"
    assert tasks[0].id.startswith("task_")
    assert tasks[0].status == "pending"


def test_get_by_id(store):
    t = TaskRecord(description="find me")
    store.add(t)

    found = store.get(t.id)
    assert found is not None
    assert found.description == "find me"


def test_get_by_prefix(store):
    t = TaskRecord(description="prefix match")
    store.add(t)

    found = store.get(t.id[:8])
    assert found is not None
    assert found.id == t.id


def test_get_ambiguous_prefix(store):
    t1 = TaskRecord(id="task_aaa11111", description="first")
    t2 = TaskRecord(id="task_aaa22222", description="second")
    store.add(t1)
    store.add(t2)

    with pytest.raises(AmbiguousTaskError) as exc_info:
        store.get("task_aaa")
    assert len(exc_info.value.matches) == 2


def test_get_exact_id_not_ambiguous(store):
    t1 = TaskRecord(id="task_aaa11111", description="first")
    t2 = TaskRecord(id="task_aaa1111100", description="second")
    store.add(t1)
    store.add(t2)

    found = store.get("task_aaa11111")
    assert found is not None
    assert found.id == "task_aaa11111"


def test_get_not_found(store):
    assert store.get("nonexistent") is None


def test_update(store):
    t = TaskRecord(description="update me")
    store.add(t)

    updated = store.update(t.id, status="in_progress")
    assert updated is not None
    assert updated.status == "in_progress"

    reloaded = store.get(t.id)
    assert reloaded.status == "in_progress"


def test_update_not_found(store):
    assert store.update("nope", status="done") is None


def test_remove(store):
    t = TaskRecord(description="remove me")
    store.add(t)

    assert store.remove(t.id) is True
    assert store.get(t.id) is None
    assert store.remove(t.id) is False


def test_clear_done(store):
    store.add(TaskRecord(description="pending one"))
    store.add(TaskRecord(description="done one", status="completed"))
    store.add(TaskRecord(description="failed one", status="failed"))

    removed = store.clear_done()
    assert removed == 2
    assert len(store.load()) == 1


# --- min_unique_prefix 最小唯一前缀 ---


def test_min_unique_prefix_single_task(store):
    t = TaskRecord(id="task_abcdefgh", description="only one")
    store.add(t)
    assert store.min_unique_prefix(t.id) == "task_"


def test_min_unique_prefix_shared_prefix(store):
    t1 = TaskRecord(id="task_aaa11111", description="first")
    t2 = TaskRecord(id="task_aaa22222", description="second")
    store.add(t1)
    store.add(t2)
    p1 = store.min_unique_prefix(t1.id)
    p2 = store.min_unique_prefix(t2.id)
    assert t1.id.startswith(p1)
    assert t2.id.startswith(p2)
    assert p1 != p2
    assert len(p1) >= 5
    assert len(p2) >= 5


# --- persistence 持久化 ---


def test_persistence_roundtrip(store):
    store.add(TaskRecord(description="survive restart", tags=["important"]))

    store2 = TaskStore(store._path.parent.parent)
    tasks = store2.load()
    assert len(tasks) == 1
    assert tasks[0].tags == ["important"]


# --- dependencies 依赖 ---


def test_find_unblocked_by(store):
    t1 = TaskRecord(description="first")
    t2 = TaskRecord(description="second", blocked_by=[t1.id])
    t3 = TaskRecord(description="third", blocked_by=[t1.id, "other_id"])
    store.add(t1)
    store.add(t2)
    store.add(t3)

    unblocked = store.find_unblocked_by(t1.id)
    # t2 is unblocked (only dependency is t1), t3 still blocked by "other_id"
    # t2 解除阻塞（唯一依赖是 t1），t3 仍被 other_id 阻塞
    assert len(unblocked) == 1
    assert unblocked[0].id == t2.id


# --- /todo command 命令 ---


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    return Application(ConfigLoader.load())


async def test_todo_add(app):
    result = await app.slash_commands.execute("/todo add implement feature X")
    assert "Added:" in result
    assert "feature X" in result


async def test_todo_list(app):
    await app.slash_commands.execute("/todo add task one")
    await app.slash_commands.execute("/todo add task two")

    result = await app.slash_commands.execute("/todo")
    assert "task one" in result
    assert "task two" in result
    assert "pending" in result


async def test_todo_done_shows_unblocked(app):
    await app.slash_commands.execute("/todo add first task")
    tid = app.task_store.load()[0].id

    await app.slash_commands.execute(f"/todo add second task --after {tid}")

    result = await app.slash_commands.execute(f"/todo done {tid}")
    assert "completed" in result
    assert "unblocked" in result


async def test_todo_start_warns_blocked(app):
    await app.slash_commands.execute("/todo add blocker")
    tid1 = app.task_store.load()[0].id

    await app.slash_commands.execute(f"/todo add dependent --after {tid1}")
    tid2 = app.task_store.load()[1].id

    result = await app.slash_commands.execute(f"/todo start {tid2}")
    assert "still blocked by" in result


async def test_todo_multi_dependency(app):
    await app.slash_commands.execute("/todo add 设计")
    tid1 = app.task_store.load()[0].id
    await app.slash_commands.execute("/todo add 实现")
    tid2 = app.task_store.load()[1].id

    # Depends on BOTH design AND implement 同时依赖两个
    r3 = await app.slash_commands.execute(f"/todo add 测试 --after {tid1},{tid2}")
    assert "blocked by" in r3
    store = app.task_store
    all_tasks = store.load()
    assert store.min_unique_prefix(tid1, all_tasks) in r3
    assert store.min_unique_prefix(tid2, all_tasks) in r3

    # Complete one — still blocked 完成一个——仍被阻塞
    await app.slash_commands.execute(f"/todo done {tid1}")
    tid3 = app.task_store.load()[2].id
    r_start = await app.slash_commands.execute(f"/todo start {tid3}")
    assert "still blocked" in r_start

    # Complete both — unblocked 全部完成——解锁
    result = await app.slash_commands.execute(f"/todo done {tid2}")
    assert "unblocked" in result


async def test_todo_empty_list(app):
    result = await app.slash_commands.execute("/todo")
    assert "No tasks" in result


async def test_todo_done_by_description(app):
    await app.slash_commands.execute("/todo add 设计模块")

    result = await app.slash_commands.execute("/todo done 设计")
    assert "completed" in result


async def test_get_by_description(store):
    t = TaskRecord(description="重构配置层")
    store.add(t)

    found = store.get("重构")
    assert found is not None
    assert found.id == t.id


async def test_todo_ambiguous_prefix(app):
    from mini_agent.core.task_store import TaskRecord

    store = app.task_store
    store.add(TaskRecord(id="task_aaa11111", description="alpha"))
    store.add(TaskRecord(id="task_aaa22222", description="beta"))

    result = await app.slash_commands.execute("/todo done task_aaa")
    assert "Ambiguous" in result
    assert "alpha" in result or "task_aaa" in result


async def test_todo_delete(app):
    r = await app.slash_commands.execute("/todo add deletable")
    tid = r.split()[1]

    result = await app.slash_commands.execute(f"/todo delete {tid}")
    assert "Deleted" in result
