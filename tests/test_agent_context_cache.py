"""AgentContext 缓存 + 单 agent 独立调用测试（步骤 2）。

验证：
- 缓存命中时不重建 context（性能）；
- 缓存失效后重建；
- build_single_agent_cached 只跑指定 agent（不跑全部 13 个）。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.services import agent_context_cache
from app.services.agents import build_single_agent_cached


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_context_cached_on_second_call() -> None:
    """连续两次 get_context，第二次应命中缓存（同一对象）。"""
    agent_context_cache.clear_all()
    db = _session()
    seeded = seed_demo(db)

    ctx1 = agent_context_cache.get_context(db, seeded["store_id"], days=7)
    assert ctx1 is not None
    ctx2 = agent_context_cache.get_context(db, seeded["store_id"], days=7)
    assert ctx2 is not None
    # 同一对象引用 = 缓存命中
    assert ctx1 is ctx2
    assert agent_context_cache.cache_size() == 1


def test_invalidate_forces_rebuild() -> None:
    """invalidate 后，下次 get_context 应重建（不同对象）。"""
    agent_context_cache.clear_all()
    db = _session()
    seeded = seed_demo(db)

    ctx1 = agent_context_cache.get_context(db, seeded["store_id"], days=7)
    agent_context_cache.invalidate(seeded["store_id"])
    ctx2 = agent_context_cache.get_context(db, seeded["store_id"], days=7)
    assert ctx1 is not ctx2  # 重建了


def test_force_refresh_rebuilds() -> None:
    """force_refresh=True 时强制重建。"""
    agent_context_cache.clear_all()
    db = _session()
    seeded = seed_demo(db)

    ctx1 = agent_context_cache.get_context(db, seeded["store_id"], days=7)
    ctx2 = agent_context_cache.get_context(db, seeded["store_id"], days=7, force_refresh=True)
    assert ctx1 is not ctx2


def test_build_single_agent_cached_returns_one_agent() -> None:
    """build_single_agent_cached 能单独跑一个 agent，返回正确结构。"""
    agent_context_cache.clear_all()
    db = _session()
    seeded = seed_demo(db)

    result = build_single_agent_cached(db, seeded["store_id"], "diagnosis", use_cache=False)
    assert result is not None
    assert result["meta"]["key"] == "diagnosis"
    assert "diagnosis_score" in result
    assert result["diagnosis_score"] > 0


def test_build_single_agent_cached_uses_context() -> None:
    """传入复用的 ctx 时不再重建（同一 ctx 对象）。"""
    agent_context_cache.clear_all()
    db = _session()
    seeded = seed_demo(db)
    from app.services.agents import build_agent_context

    ctx = build_agent_context(db=db, store_id=seeded["store_id"], days=7)
    assert ctx is not None

    # 传入 ctx，不应触发缓存查找
    result = build_single_agent_cached(db, seeded["store_id"], "menu", ctx=ctx, use_cache=False)
    assert result is not None
    assert result["meta"]["key"] == "menu"


def test_matrix_agent_single_call() -> None:
    """矩阵 agent（如 review）也能单跑。"""
    agent_context_cache.clear_all()
    db = _session()
    seeded = seed_demo(db)

    result = build_single_agent_cached(db, seeded["store_id"], "review", use_cache=False)
    assert result is not None
    assert result["meta"]["key"] == "review"
