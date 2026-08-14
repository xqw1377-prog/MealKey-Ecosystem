"""竞品能力短板契约：真数据进得来、真动作写得出、真结果收得回。"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.business_facts import AdSpendDaily, OpsMetricDaily
from app.models.entities import (
    ItemFunnelDaily,
    MenuItem,
    Merchant,
    OrderFact,
    OrderItemFact,
    ReviewFact,
    Store,
)
from app.models.ohre import Experiment, Recommendation
from app.models.settings import PlatformConnection
from app.services.action_feedback import find_recent_action_feedback
from app.services.business_import import (
    get_data_coverage,
    import_ops_metrics,
    import_orders,
)
from app.services.closed_loop import ensure_now_loop, mark_loop_executed
from app.services.execution_pack import build_execution_pack
from app.services.execution_policy import AUTO_EXECUTABLE_ACTIONS
from app.services.experiment_attribution import evaluate_experiment
from app.services.matrix_agents.builders import build_ads_agent
from app.services.matrix_agents.common import MatrixAgentInput
from app.services.platform_connectors import fetch_mock_snapshot, reset_mock_platform_state
from app.services.platform_sync import apply_platform_snapshot, merge_multi_platform_snapshots, sync_all_platforms
from app.services.platform_write import is_platform_writeable
from app.services.store_state import build_store_state


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _title_flow(name: str) -> dict:
    pack = build_execution_pack("change_title", object_name=name, title=f"改{name}标题")
    return {
        "now": {
            "id": "nba-title",
            "source_card_id": "nba-title",
            "title": f"改{name}标题",
            "object_name": name,
            "execution_pack": pack,
        }
    }


def test_import_orders_weights_real_cost() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    item = db.get(MenuItem, seeded["item_id"])
    assert item is not None
    item.food_cost = 10.0
    item.packaging_cost = 1.0
    item.cost_source = "owner_cost_sheet"
    db.add(item)
    db.commit()

    day = (date.today() - timedelta(days=2)).isoformat()
    csv = (
        "订单号,下单时间,营业额,商品名,数量,单价\n"
        f"A1,{day} 12:00:00,32,招牌牛肉盖饭,3,32\n"
    ).encode("utf-8")
    # seed_demo item name may not be 招牌牛肉盖饭 — use actual name
    name = item.current_version.name if item.current_version else "SKU"
    csv = (
        "订单号,下单时间,营业额,商品名,数量,单价\n"
        f"A1,{day} 12:00:00,96,{name},3,32\n"
    ).encode("utf-8")
    report = import_orders(db, store_id, csv, "orders.csv")
    assert report["imported"] == 1
    assert report["imported_items"] == 1
    assert db.execute(select(OrderFact).where(OrderFact.store_id == store_id)).scalars().first() is not None
    line = db.execute(select(OrderItemFact)).scalars().first()
    assert line is not None
    assert line.item_id == item.id
    assert line.qty == 3

    state = build_store_state(db, store_id, days=7)
    assert state is not None
    assert state.data_coverage.orders_observed is True
    assert state.profit.food_cost == 30.0
    assert state.profit.packaging_cost == 3.0


def test_ads_spend_from_ad_spend_daily_and_ads_fail_closed() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    state = build_store_state(db, store_id, days=7)
    assert state is not None
    assert state.data_coverage.ads_observed is False
    assert state.profit.ads_spend in {None, 0}

    store = db.get(Store, store_id)
    data = MatrixAgentInput(
        store=store,
        menu_items=[],
        item_snapshots=[],
        competition_changes=[],
        kpis=state.kpis,
        document_alignment={},
        primary_problem_type=None,
        hypothesis_id=None,
        generated_at=datetime.now(timezone.utc),
        ads_observed=False,
    )
    ads = build_ads_agent(db, data, [])
    assert ads.unlock_ready is False
    assert any(a.action_type != "boost_hero_item_ads" for a in ads.priority_actions) or not ads.priority_actions
    assert all(a.action_type != "boost_hero_item_ads" for a in ads.priority_actions)

    observe_day = date.today() - timedelta(days=2)
    db.add(AdSpendDaily(store_id=store_id, day=observe_day, cost=188.0, source="platform_export"))
    db.commit()
    state2 = build_store_state(db, store_id, days=7)
    assert state2 is not None
    assert state2.data_coverage.ads_source == "ad_spend_daily"
    assert state2.profit.ads_spend == 188.0


def test_ops_metrics_fill_im_reply_without_inventing() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    state = build_store_state(db, store_id, days=7)
    assert state is not None
    im = next(s for s in state.platform_health.signals if s.key == "im_reply_rate")
    assert im.status == "unknown"
    assert state.platform_health.im_reply_rate is None

    day = (date.today() - timedelta(days=2)).isoformat()
    csv = f"日期,IM回复率,配送准时率\n{day},92%,88%\n".encode("utf-8")
    report = import_ops_metrics(db, store_id, csv, "ops.csv")
    assert report["imported"] == 1
    assert db.execute(select(OpsMetricDaily).where(OpsMetricDaily.store_id == store_id)).scalars().first() is not None
    state2 = build_store_state(db, store_id, days=7)
    assert state2 is not None
    assert state2.platform_health.im_reply_rate == 0.92
    assert state2.platform_health.on_time_delivery_rate == 0.88
    assert state2.platform_health.meal_prep_rate is None


def test_snapshot_reviews_and_multi_platform_merge() -> None:
    reset_mock_platform_state()
    db = _session()
    merchant = Merchant(name="多平台商户")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="双平台店")
    db.add(store)
    db.commit()
    db.refresh(store)

    meituan = fetch_mock_snapshot("meituan", store_name=store.name)
    eleme = fetch_mock_snapshot("eleme", store_name=store.name)
    assert meituan.reviews
    merged = merge_multi_platform_snapshots([meituan, eleme])
    assert merged.platform == "multi"
    assert len(merged.menu_items) >= len(meituan.menu_items)
    result = apply_platform_snapshot(db, store, merged)
    assert result["reviews_upserted"] >= 1
    reviews = db.execute(select(ReviewFact).where(ReviewFact.store_id == store.id)).scalars().all()
    assert reviews
    synthetic = db.execute(
        select(ItemFunnelDaily).where(ItemFunnelDaily.data_source == "synthetic")
    ).scalars().first()
    assert synthetic is not None

    db.add(PlatformConnection(store_id=store.id, platform="meituan", status="connected", connector_mode="mock"))
    db.add(PlatformConnection(store_id=store.id, platform="eleme", status="connected", connector_mode="mock"))
    db.commit()
    synced = sync_all_platforms(db, store, mode="mock")
    assert "meituan" in synced["platforms"] or synced["platform"] == "multi"


def test_writeback_allowlist_and_execution_policy() -> None:
    assert is_platform_writeable("change_title") is True
    assert is_platform_writeable("change_main_image") is True
    assert is_platform_writeable("reply_ordinary_reviews") is True
    assert is_platform_writeable("appeal_pack") is True
    assert is_platform_writeable("adjust_price_value") is False
    assert is_platform_writeable("boost_hero_item_ads") is False
    assert "adjust_price_value" not in AUTO_EXECUTABLE_ACTIONS
    assert AUTO_EXECUTABLE_ACTIONS <= {"change_title", "change_main_image", "reply_ordinary_reviews"}


def test_experiment_binds_sku_and_skips_without_funnel() -> None:
    db = _session()
    merchant = Merchant(name="归因商户")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="归因店")
    db.add(store)
    db.flush()
    item = MenuItem(store_id=store.id, is_active=True)
    db.add(item)
    db.flush()
    from app.models.entities import MenuItemVersion

    version = MenuItemVersion(item_id=item.id, name="黑椒牛肉饭", price=28)
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    db.commit()

    loop = ensure_now_loop(db, store.id, decision_flow=_title_flow("黑椒牛肉饭"), events=None)
    assert loop is not None
    marked = mark_loop_executed(db, store.id, loop.id)
    exp = db.get(Experiment, marked.experiment_id)
    assert exp is not None
    assert exp.item_id == item.id

    rec = db.get(Recommendation, exp.recommendation_id)
    rec.expected_metric = "ctr"
    rec.status = "executed"
    rec.executed_at = datetime.now(timezone.utc) - timedelta(days=3)
    db.add(rec)
    db.commit()
    outcome = evaluate_experiment(db, exp, days=7)
    assert outcome.skipped is True
    assert outcome.reason == "funnel_missing"
    assert outcome.result == "unknown"
    assert exp.result == "unknown"


def test_feedback_fuzzy_matches_loop_ref() -> None:
    db = _session()
    seeded = seed_demo(db)
    rec = Recommendation(
        store_id=seeded["store_id"],
        scope="item",
        object_ref=f"item:{seeded['item_id']}",
        action_type="change_title",
        expected_metric="ctr",
        status="executed",
        executed_at=datetime.now(timezone.utc) - timedelta(days=3),
        content_json='{"object_name":"招牌牛肉盖饭"}',
    )
    db.add(rec)
    db.flush()
    exp = Experiment(
        recommendation_id=rec.id,
        store_id=seeded["store_id"],
        item_id=seeded["item_id"],
        result="positive",
        lift_pct=8.0,
    )
    db.add(exp)
    db.commit()
    feedback = find_recent_action_feedback(
        [rec],
        [exp],
        action_type="change_title",
        object_ref=f"loop:{rec.id}",
    )
    assert feedback is not None
    assert feedback.result == "positive"


def test_coverage_includes_orders_and_ads() -> None:
    db = _session()
    seeded = seed_demo(db)
    coverage = get_data_coverage(db, seeded["store_id"])
    assert "order_rows" in coverage
    assert "ads_observed" in coverage
    assert coverage["ads_observed"] is False
