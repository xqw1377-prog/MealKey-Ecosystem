"""MealKey Score + 晨报升级测试（步骤 4+5）。

覆盖：
- MealKey Score 5 维加权计算正确；
- 总分 = sum(score * weight)；
- judgment 定性合理；
- ManagerHomeBrief 的 problems（3条）和 tasks（3条）结构。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.services.agents import build_store_agents
from app.services.manager_brief import build_manager_home_brief
from app.services.mealkey_score import compute_mealkey_score


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_mealkey_score_5_dimensions() -> None:
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None

    score = compute_mealkey_score(agents)
    assert len(score.dimensions) == 5
    keys = {d.key for d in score.dimensions}
    assert keys == {"product", "menu", "competition", "trend", "review"}

    # 权重之和 = 1.0
    total_weight = sum(d.weight for d in score.dimensions)
    assert abs(total_weight - 1.0) < 0.01

    # 每个维度有分值和加权分
    for d in score.dimensions:
        assert 20 <= d.score <= 98
        assert d.weighted_score == round(d.score * d.weight, 1)


def test_mealkey_score_total_is_weighted_sum() -> None:
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None

    score = compute_mealkey_score(agents)
    expected_total = round(sum(d.weighted_score for d in score.dimensions))
    assert score.total == expected_total
    assert 20 <= score.total <= 98


def test_mealkey_score_judgment_present() -> None:
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None

    score = compute_mealkey_score(agents)
    assert score.judgment
    assert len(score.judgment) > 5  # 有实质内容


def test_manager_brief_v2_has_problems_and_tasks() -> None:
    """传入完整 agents 时，brief 应包含 3 条 problems + tasks。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None

    brief = build_manager_home_brief(
        agents.store_state,
        growth=agents.growth,
        storefront=agents.storefront,
        agents=agents,
    )

    # MealKey Score 存在
    assert brief.mealkey_score is not None
    assert brief.mealkey_score.total > 0

    # problems 最多 3 条
    assert 1 <= len(brief.problems) <= 3
    for p in brief.problems:
        assert p.title
        assert p.source_agent

    # tasks 最多 3 条
    assert 1 <= len(brief.tasks) <= 3
    for t in brief.tasks:
        assert t.title
        assert t.agent_key
        assert t.expected_metric  # 每条任务都有观察指标


def test_manager_brief_v2_backward_compatible_without_agents() -> None:
    """不传 agents 时（V1 兼容），brief 不崩溃，新字段为空。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None

    brief = build_manager_home_brief(
        agents.store_state,
        growth=agents.growth,
        storefront=agents.storefront,
        # 不传 agents
    )
    # V1 字段正常
    assert brief.store_name
    assert brief.business_health_score > 0
    # V2 字段为空（兼容）
    assert brief.mealkey_score is None
    assert brief.problems == []
    assert brief.tasks == []


def test_manager_brief_business_health_score_uses_mealkey() -> None:
    """传 agents 时，business_health_score 应等于 MealKey Score 总分。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None

    brief = build_manager_home_brief(
        agents.store_state,
        growth=agents.growth,
        storefront=agents.storefront,
        agents=agents,
    )
    assert brief.mealkey_score is not None
    assert brief.business_health_score == brief.mealkey_score.total
