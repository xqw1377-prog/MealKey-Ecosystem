"""Truth Contract 边界回归（PRE-PROD-GATE-01 / P0-7：Synthetic 永远不是 Truth）。

核心断言：**只有满足生产 Truth 条件的 funnel 数据，才能被 attribution 看见。**

`production_funnel_clause(data_source)` 排除：NULL（历史未知来源）、空串、
以及 `NEVER_PRODUCTION_TRUTH`（synthetic / mock / fixture / sandbox / legacy_unknown_source / test_only / external_daily_report_test）。
`seed_demo` 的 funnel 现显式标 `synthetic` —— 不进 Truth，永不伪装真实来源。

四个场景把「No Provenance = No Truth」从代码层锁死为回归：
1. data_source=None        → _item_funnel_observed=False，归因 funnel_missing
2. data_source=synthetic   → _item_funnel_observed=False，归因 funnel_missing
3. data_source=authorized_session → observed available（_item_funnel_observed=True 且 metric 有值）
4. valid production provenance     → evaluate_experiment 执行，落终态 result
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import (
    ItemFunnelDaily,
    Menu,
    MenuItem,
    MenuItemVersion,
    Merchant,
    ShopFunnelDaily,
    Store,
)
from app.models.ohre import Experiment, Recommendation
from app.services.experiment_attribution import (
    _item_funnel_observed,
    _item_metric_value,
    evaluate_experiment,
)
from app.services.store_state import _calc_window


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _build_store_with_funnel(db: Session, *, data_source):
    """最小 store + item + 14d funnel，全部行打同一个 `data_source` 标签。

    data_source=None 表示显式 NULL（历史未知来源）。
    observe 窗（最近 7 天）ctr=0.040，baseline 窗（更早 7 天）ctr=0.048。
    """
    merchant = Merchant(name="边界测试商户")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="边界测试店")
    db.add(store)
    db.flush()
    menu = Menu(store_id=store.id, name="默认", version=1, status="active")
    db.add(menu)
    db.flush()
    item = MenuItem(store_id=store.id, menu_id=menu.id, is_active=True)
    db.add(item)
    db.flush()
    v1 = MenuItemVersion(item_id=item.id, name="黑椒牛肉饭", category="主食", price=32.0, source="seed")
    db.add(v1)
    db.flush()
    item.current_version_id = v1.id

    today = date.today()
    for i in range(14):
        d = today - timedelta(days=i + 1)
        in_observe = i < 7
        ctr = 0.040 if in_observe else 0.048
        imp = 1200
        visits = int(imp * ctr)
        orders = int(visits * 0.18)
        gmv = float(orders * 32.0)
        db.add(
            ItemFunnelDaily(
                item_id=item.id,
                day=d,
                impressions=imp,
                visits=visits,
                orders=orders,
                payments=orders,
                gmv=gmv,
                ctr=ctr,
                cvr=(orders / visits) if visits else None,
                data_source=data_source,
            )
        )
        db.add(
            ShopFunnelDaily(
                store_id=store.id,
                day=d,
                impressions=imp,
                visits=visits,
                payments=orders,
                orders=orders,
                gmv=gmv,
                aov=32.0,
                data_source=data_source,
            )
        )
    db.commit()
    return store.id, item.id


def _pending_ctr_experiment(db: Session, store_id: str, item_id: str) -> Experiment:
    rec = Recommendation(
        store_id=store_id,
        scope="item",
        object_ref=f"item:{item_id}",
        action_type="change_main_image",
        expected_metric="ctr",
        expected_lift_pct_low=6,
        expected_lift_pct_high=12,
        window_hours=24,
        confidence=0.7,
        status="executed",
        executed_at=datetime.now(timezone.utc) - timedelta(days=3),
    )
    db.add(rec)
    db.flush()
    exp = Experiment(
        recommendation_id=rec.id,
        store_id=store_id,
        item_id=item_id,
        baseline_value=0.048,
        result="pending",
        attribution_quality="medium",
        control_desc="Truth 边界测试",
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return exp


# ── 场景 1：data_source=None（历史未知来源）→ 排除 ──

def test_truth_none_provenance_excluded() -> None:
    db = _session()
    store_id, item_id = _build_store_with_funnel(db, data_source=None)
    w = _calc_window(7)

    assert _item_funnel_observed(db, item_id, w.observe_from, w.observe_to) is False

    exp = _pending_ctr_experiment(db, store_id, item_id)
    outcome = evaluate_experiment(db, exp, days=7)
    assert outcome.skipped
    assert outcome.reason == "funnel_missing"
    assert outcome.result == "unknown"
    # evaluate 自身不 commit（caller 控制事务）；commit 后落库 unknown
    db.commit()
    db.refresh(exp)
    assert exp.result == "unknown"


# ── 场景 2：data_source=synthetic（明确假数据）→ 排除 ──

def test_truth_synthetic_provenance_excluded() -> None:
    db = _session()
    store_id, item_id = _build_store_with_funnel(db, data_source="synthetic")
    w = _calc_window(7)

    assert _item_funnel_observed(db, item_id, w.observe_from, w.observe_to) is False

    exp = _pending_ctr_experiment(db, store_id, item_id)
    outcome = evaluate_experiment(db, exp, days=7)
    assert outcome.skipped
    assert outcome.reason == "funnel_missing"
    assert outcome.result == "unknown"
    db.commit()
    db.refresh(exp)
    assert exp.result == "unknown"


# ── 场景 2b：TEST-ADAPTER-01 provenance 与 synthetic 同类，生产不可见 ──

def test_truth_test_only_provenance_excluded() -> None:
    db = _session()
    store_id, item_id = _build_store_with_funnel(db, data_source="test_only")
    w = _calc_window(7)

    assert _item_funnel_observed(db, item_id, w.observe_from, w.observe_to) is False

    exp = _pending_ctr_experiment(db, store_id, item_id)
    outcome = evaluate_experiment(db, exp, days=7)
    assert outcome.skipped
    assert outcome.reason == "funnel_missing"
    assert outcome.result == "unknown"


# ── 场景 3：data_source=authorized_session → observed available ──

def test_truth_authorized_session_observed_available() -> None:
    db = _session()
    store_id, item_id = _build_store_with_funnel(db, data_source="authorized_session")
    w = _calc_window(7)

    # 闸门放行：production_funnel_clause 接受 authorized_session
    assert _item_funnel_observed(db, item_id, w.observe_from, w.observe_to) is True
    # metric 聚合可见：返回真实数值（observe 窗 ctr≈0.040）
    observed = _item_metric_value(db, item_id, "ctr", w.observe_from, w.observe_to)
    assert observed is not None
    assert abs(observed - 0.040) < 0.005


# ── 场景 4：valid production provenance → attribution 执行，落终态 ──

def test_truth_production_provenance_attribution_executes() -> None:
    db = _session()
    store_id, item_id = _build_store_with_funnel(db, data_source="authorized_session")

    exp = _pending_ctr_experiment(db, store_id, item_id)
    outcome = evaluate_experiment(db, exp, days=7)
    assert not outcome.skipped, f"满足 Truth 条件的数据不应被跳过：{outcome.reason}"
    db.refresh(exp)
    # observe ctr 0.040 < baseline 0.048 → negative；终态，非 pending/unknown-funnel_missing
    assert exp.result in {"positive", "negative", "neutral", "unknown"}
    assert exp.result != "pending"
    assert outcome.result == exp.result
