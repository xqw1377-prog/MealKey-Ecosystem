from datetime import date

from app.schemas.decision_core import CampaignRule
from app.schemas.store_state import (
    BusinessState,
    CoreItem,
    DeltaMetric,
    MarketInfo,
    ProfitState,
    StoreInfo,
    StoreState,
    WindowInfo,
)
from app.services.action_ranker import apply_memory_to_scores, memory_from_result
from app.services.decision_skills import campaign_skill_candidates, profit_skill_candidates


def _memory(action_type: str, result: str, lift: float) -> StrategyMemorySnapshot:
    return memory_from_result(action_type=action_type, result=result, lift_pct=lift, metric="ctr")


def test_positive_image_result_reranks_next_actions() -> None:
    before = [
        {"action_type": "change_main_image", "score": 0.62, "label": "换图"},
        {"action_type": "adjust_price_value", "score": 0.58, "label": "降价"},
        {"action_type": "boost_hero_item_ads", "score": 0.51, "label": "加投"},
        {"action_type": "change_title", "score": 0.48, "label": "换标题"},
    ]
    assert [row["label"] for row in before] == ["换图", "降价", "加投", "换标题"]

    after = apply_memory_to_scores(before, _memory("change_main_image", "positive", 14.6))
    labels = [row["label"] for row in after]
    scores = {row["action_type"]: row["score"] for row in after}

    assert labels[0] == "换图"
    assert labels[1] == "换标题"
    assert "降价" in labels[2:]
    assert scores["change_main_image"] == 0.84
    assert scores["change_title"] == 0.55
    assert scores["adjust_price_value"] == 0.41
    assert scores["boost_hero_item_ads"] == 0.38
    assert scores["change_main_image"] > scores["change_title"] > scores["adjust_price_value"]


def test_negative_image_result_demotes_creative() -> None:
    before = [
        {"action_type": "change_main_image", "score": 0.62},
        {"action_type": "adjust_price_value", "score": 0.58},
        {"action_type": "change_title", "score": 0.48},
    ]
    after = apply_memory_to_scores(before, _memory("change_main_image", "negative", 8.0))
    scores = {row["action_type"]: row["score"] for row in after}
    assert scores["change_main_image"] < 0.62
    assert after[0]["action_type"] != "change_main_image"


def test_evaluate_experiment_memory_changes_growth_order() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import app.models  # noqa: F401
    from app.api.routes_dev import seed_demo
    from app.db.base import Base
    from app.models.ohre import Experiment, Recommendation
    from app.services.agents import build_single_agent
    from app.services.strategy_memory import load_strategy_memory, upsert_strategy_memory_from_experiment

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    seeded = seed_demo(db)
    store_id = seeded["store_id"]

    rec = db.query(Recommendation).filter(
        Recommendation.store_id == store_id,
        Recommendation.action_type == "change_main_image",
    ).first()
    if rec is None:
        rec = Recommendation(
            store_id=store_id,
            scope="item",
            object_ref="item:hero",
            action_type="change_main_image",
            expected_metric="ctr",
            confidence=0.7,
            status="executed",
        )
        db.add(rec)
        db.flush()
    exp = Experiment(
        store_id=store_id,
        recommendation_id=rec.id,
        result="positive",
        lift_pct=14.6,
        attribution_quality="high",
        notes="CTR +14.6%，转化率无下降。",
    )
    db.add(exp)
    db.commit()
    upsert_strategy_memory_from_experiment(db, exp)
    memory = load_strategy_memory(db, store_id)
    assert memory.items
    assert memory.items[0].action_type == "change_main_image"

    result = build_single_agent(db, store_id, "growth")
    assert result is not None
    pool = result["opportunity_pool"]
    image_rows = [row for row in pool if row["action_type"] == "change_main_image"]
    assert image_rows
    selected = result["selected_opportunity"]
    assert selected["action_type"] in {"change_main_image", "change_title", "refresh_hero_image", "refresh_signature_card"}


def test_profit_skill_enters_candidate_not_ui_box() -> None:
    state = StoreState(
        store=StoreInfo(store_id="s1", name="老王牛肉饭"),
        market=MarketInfo(),
        window=WindowInfo(from_day=date.today(), to_day=date.today(), compare_from_day=date.today(), compare_to_day=date.today()),
        kpis={},
        core_items=[CoreItem(item_id="i1", name="黑椒牛肉饭")],
        business=BusinessState(orders=DeltaMetric(observed_value=80, baseline_value=90, delta_pct=-11.0)),
        profit=ProfitState(
            customer_paid=28.0,
            merchant_subsidy=6.0,
            food_cost=12.0,
            packaging_cost=2.0,
            ads_spend=4.0,
            contribution_profit_delta_pct=-12.0,
            judgment="利润下滑",
        ),
    )
    candidates = profit_skill_candidates(state)
    assert candidates
    assert "主图" in candidates[0].title or "利润" in candidates[0].title
    assert candidates[0].trigger == "anomaly"


def test_campaign_black_without_cost_does_not_become_now() -> None:
    state = StoreState(
        store=StoreInfo(store_id="s1", name="老王牛肉饭"),
        market=MarketInfo(),
        window=WindowInfo(from_day=date.today(), to_day=date.today(), compare_from_day=date.today(), compare_to_day=date.today()),
        kpis={},
        profit=ProfitState(customer_paid=29.9, food_cost=None, packaging_cost=None),
    )
    candidates = campaign_skill_candidates(state, rule=CampaignRule(campaign_name="午餐满减", discount_value=5))
    assert candidates
    assert candidates[0].title == "这次活动先别参加"
    assert candidates[0].suggested_state == "auto_do"


def test_funnel_csv_writes_store_state_rows() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import app.models  # noqa: F401
    from app.db.base import Base
    from app.models.entities import Merchant, ShopFunnelDaily, Store
    from app.services.metrics_ingest import ingest_funnel_csv

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    merchant = Merchant(name="m")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="店")
    db.add(store)
    db.commit()
    text = "日期,曝光,访问,订单,GMV\n2026-08-10,1000,80,12,360\n2026-08-11,1100,90,14,420\n"
    result = ingest_funnel_csv(db, store.id, text)
    assert result["rows"] == 2
    rows = db.query(ShopFunnelDaily).filter(ShopFunnelDaily.store_id == store.id).all()
    assert len(rows) == 2
    assert rows[0].orders in {12, 14}
