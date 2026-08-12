"""实验归因闭环测试（P0-1）。

验证：
- 已过观察窗的 pending 实验会被自动评估并落库 result；
- strategy_memory 被同步沉淀；
- 未过观察窗的不处理；
- 已有终态的不被覆盖。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.entities import MenuItem
from app.models.ohre import Experiment, Recommendation
from app.services.experiment_attribution import (
    attribute_store_experiments,
    evaluate_experiment,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_executed_recommendation(db: Session, store_id: str, item_id: str) -> Recommendation:
    """构造一条已执行、实验 pending 的动作，时间设在观察窗之外。"""
    rec = Recommendation(
        store_id=store_id,
        scope="item",
        object_ref=f"item:{item_id}",
        action_type="change_main_image",
        expected_metric="ctr",
        expected_lift_pct_low=6,
        expected_lift_pct_high=12,
        window_hours=24,  # 24 小时观察窗
        confidence=0.7,
        status="executed",
        executed_at=datetime.now(timezone.utc) - timedelta(days=3),  # 3天前，已过观察窗
    )
    db.add(rec)
    db.flush()
    exp = Experiment(
        recommendation_id=rec.id,
        store_id=store_id,
        item_id=item_id,
        baseline_value=0.048,
        observed_value=None,
        lift_pct=None,
        result="pending",
        attribution_quality="medium",
        control_desc="测试",
    )
    db.add(exp)
    db.commit()
    db.refresh(rec)
    db.refresh(exp)
    return rec


def test_pending_experiment_past_window_gets_evaluated() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    item_id = seeded["item_id"]

    rec = _create_executed_recommendation(db, store_id, item_id)
    exp = db.execute(
        select(Experiment).where(Experiment.recommendation_id == rec.id)
    ).scalar_one()

    assert exp.result == "pending"
    outcomes = attribute_store_experiments(db, store_id, days=7, only_observed=True)
    evaluated = [o for o in outcomes if not o.skipped]
    assert len(evaluated) == 1
    # result 必须被落库为终态之一
    assert evaluated[0].result in {"positive", "negative", "neutral", "unknown"}
    assert evaluated[0].result != "pending"

    db.refresh(exp)
    assert exp.result == evaluated[0].result
    assert exp.result != "pending"


def test_experiment_within_window_not_evaluated() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    item_id = seeded["item_id"]

    # 构造一条刚刚执行（观察窗未结束）的动作
    rec = Recommendation(
        store_id=store_id,
        scope="item",
        object_ref=f"item:{item_id}",
        action_type="change_main_image",
        expected_metric="ctr",
        window_hours=168,
        confidence=0.7,
        status="executed",
        executed_at=datetime.now(timezone.utc) - timedelta(hours=2),  # 2小时前，观察窗未结束
    )
    db.add(rec)
    db.flush()
    db.add(Experiment(
        recommendation_id=rec.id,
        store_id=store_id,
        item_id=item_id,
        result="pending",
    ))
    db.commit()

    outcomes = attribute_store_experiments(db, store_id, days=7, only_observed=True)
    # 没有实验被评估（观察窗未结束）
    assert all(o.skipped for o in outcomes) or not outcomes


def test_already_resulted_experiment_not_overwritten() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    item_id = seeded["item_id"]

    rec = _create_executed_recommendation(db, store_id, item_id)
    exp = db.execute(
        select(Experiment).where(Experiment.recommendation_id == rec.id)
    ).scalar_one()
    # 模拟商家已手动标注为 positive
    exp.result = "positive"
    exp.lift_pct = 8.0
    db.add(exp)
    db.commit()

    outcomes = attribute_store_experiments(db, store_id, days=7, only_observed=True)
    matching = [o for o in outcomes if o.experiment_id == exp.id]
    if matching:
        assert matching[0].skipped
        assert matching[0].result == "positive"
        assert matching[0].lift_pct == 8.0  # 没被覆盖


def test_strategy_memory_upserted_after_attribution() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    item_id = seeded["item_id"]

    rec = _create_executed_recommendation(db, store_id, item_id)
    exp = db.execute(
        select(Experiment).where(Experiment.recommendation_id == rec.id)
    ).scalar_one()

    evaluate_experiment(db, exp, days=7)
    db.commit()

    # strategy_memory 应该被沉淀
    from app.models.strategy_memory import StrategyMemoryRecord
    records = db.execute(
        select(StrategyMemoryRecord).where(StrategyMemoryRecord.store_id == store_id)
    ).scalars().all()
    assert len(records) >= 1
    assert records[0].action_type == "change_main_image"
    assert records[0].result in {"positive", "negative", "neutral", "unknown"}


def test_force_revaluate_overwrites_terminal_state() -> None:
    """force=True 时，已有终态的实验也会被重算（手动 evaluate API 用）。"""
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    item_id = seeded["item_id"]

    rec = _create_executed_recommendation(db, store_id, item_id)
    exp = db.execute(
        select(Experiment).where(Experiment.recommendation_id == rec.id)
    ).scalar_one()
    # 先手动标成 neutral
    exp.result = "neutral"
    exp.lift_pct = 0.0
    db.add(exp)
    db.commit()

    # 不带 force：应该 skip
    outcome_no_force = evaluate_experiment(db, exp, days=7)
    assert outcome_no_force.skipped
    assert outcome_no_force.reason == "already_neutral"

    # 带 force：应该重算
    outcome_force = evaluate_experiment(db, exp, days=7, force=True)
    assert not outcome_force.skipped
    db.refresh(exp)
    # 重算后 result 可能变化（基于真实数据）
    assert exp.result in {"positive", "negative", "neutral", "unknown"}


def test_attribute_all_stores_aggregates_summary() -> None:
    """全店归因返回汇总结构正确。"""
    from app.services.experiment_attribution import attribute_all_stores_experiments

    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    item_id = seeded["item_id"]
    _create_executed_recommendation(db, store_id, item_id)

    summary = attribute_all_stores_experiments(db, days=7)
    assert summary["store_count"] >= 1
    assert "evaluated" in summary
    assert "positive" in summary
    assert "negative" in summary
    assert "skipped" in summary
    assert isinstance(summary["stores"], list)
