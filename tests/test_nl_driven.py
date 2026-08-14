"""NL 驱动 + 经营线程持久化测试。

覆盖 thread_engine 的 4 个核心函数:
- create_thread
- update_thread_progress
- load_active_threads
- sync_threads_from_agents
"""
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import Merchant, Store
from app.models.goal import Goal
from app.models.thread import OperatingThread
from app.services.thread_engine import (
    create_thread,
    ensure_thread_for_action,
    load_active_threads,
    sync_threads_from_agents,
    update_thread_progress,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_store(db: Session) -> str:
    m = Merchant(name="测试商户")
    db.add(m)
    db.flush()
    s = Store(merchant_id=m.id, name="测试店")
    db.add(s)
    db.flush()
    return s.id


def test_create_thread() -> None:
    """创建经营线程。"""
    db = _session()
    store_id = _seed_store(db)

    thread = create_thread(db, store_id, "午餐增长计划", "午餐订单 +20%")
    assert thread.id
    assert thread.title == "午餐增长计划"
    assert thread.goal_text == "午餐订单 +20%"
    assert thread.status == "active"
    db.close()


def test_update_thread_progress() -> None:
    """更新线程进度。"""
    db = _session()
    store_id = _seed_store(db)
    thread = create_thread(db, store_id, "主图优化", "CTR +15%")

    updated = update_thread_progress(
        db,
        thread.id,
        done=["旧主图已备份"],
        doing=["新主图实验中 剩余31h"],
        next_step="CVR≥18% → 放大",
        current_result="CTR +8.7%",
        ai_judgment="进度正常",
        needs_owner=False,
    )
    assert updated is not None
    assert "旧主图已备份" in (updated.done_json or "")
    assert "新主图实验中" in (updated.doing_json or "")
    assert updated.next_step == "CVR≥18% → 放大"
    db.close()


def test_load_active_threads() -> None:
    """加载活跃线程。"""
    db = _session()
    store_id = _seed_store(db)

    create_thread(db, store_id, "线程1", "目标1")
    create_thread(db, store_id, "线程2", "目标2")

    # 一个完成的线程不应出现
    t3 = create_thread(db, store_id, "线程3", "目标3")
    t3.status = "completed"
    db.add(t3)
    db.commit()

    active = load_active_threads(db, store_id)
    assert len(active) == 2
    titles = [t.title for t in active]
    assert "线程1" in titles
    assert "线程2" in titles
    assert "线程3" not in titles
    db.close()


def test_sync_threads_from_agents() -> None:
    """从 agents 同步线程——有活跃 Goal 时自动创建线程。"""
    db = _session()
    store_id = _seed_store(db)

    # 创建一个活跃 Goal
    goal = Goal(
        store_id=store_id,
        raw_text="本月GMV做到20万",
        metric="gmv",
        target_value=200000,
        status="active",
    )
    db.add(goal)
    db.commit()

    # agents mock (sync 需要 agents.growth 带特定属性)
    class MockGrowth:
        current_action = None
        experiments_summary = {"positive": 2, "negative": 0}
        selected_opportunity = None
        learning_summary = "增长势头良好"

    class MockAgents:
        def __init__(self, sid):
            self.store_id = sid
            self.growth = MockGrowth()

    threads = sync_threads_from_agents(db, store_id, MockAgents(store_id))
    assert len(threads) >= 1
    # 应该为 Goal 创建了对应线程
    has_goal_thread = any(
        "20万" in (t.title or "") or "GMV" in (t.title or "") or "增长" in (t.title or "")
        for t in threads
    )
    assert has_goal_thread
    db.close()


def test_ensure_thread_for_action_reuses_existing() -> None:
    """ensure_thread_for_action: 有活跃线程时复用,没有时创建。"""
    db = _session()
    store_id = _seed_store(db)

    # 第一次调用 → 创建
    t1 = ensure_thread_for_action(db, store_id, "主图优化")
    assert t1.title == "主图优化"

    # 第二次调用 → 复用同一个
    t2 = ensure_thread_for_action(db, store_id, "标题优化")
    assert t2.id == t1.id  # 复用,不新建

    threads = load_active_threads(db, store_id)
    assert len(threads) == 1  # 只有一个线程
    db.close()


def test_ensure_thread_for_action_creates_when_none() -> None:
    """没有活跃线程时创建新的。"""
    db = _session()
    store_id = _seed_store(db)

    thread = ensure_thread_for_action(db, store_id, "午餐增长")
    assert thread.id
    assert thread.status == "active"
    assert "午餐增长" in thread.title
    db.close()
