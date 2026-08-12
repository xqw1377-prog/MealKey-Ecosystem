from datetime import date, datetime

from app.schemas.events import OperatingEvent
from app.schemas.store_state import (
    CompetitionChange,
    CoreItem,
    DeltaMetric,
    MarketInfo,
    PlatformHealthState,
    ProfitState,
    StoreInfo,
    StoreState,
    WindowInfo,
)
from app.services.runtime_request_mapper import (
    build_business_event_object,
    build_runtime_bridge_run_request,
    build_store_state_snapshot,
    pick_primary_event,
)


def _store_state() -> StoreState:
    return StoreState(
        store=StoreInfo(store_id="store_1", name="老王牛肉饭"),
        market=MarketInfo(),
        window=WindowInfo(
            from_day=date(2026, 8, 11),
            to_day=date(2026, 8, 12),
            compare_from_day=date(2026, 8, 4),
            compare_to_day=date(2026, 8, 5),
        ),
        kpis={
            "orders": DeltaMetric(observed_value=83, baseline_value=96, delta_pct=-13.5),
            "gmv": DeltaMetric(observed_value=2460, baseline_value=2780),
            "impressions": DeltaMetric(observed_value=18200),
            "ctr": DeltaMetric(observed_value=0.0291, baseline_value=0.0342, delta_pct=-14.8),
            "cvr": DeltaMetric(observed_value=0.172, baseline_value=0.168, delta_pct=2.4),
        },
        core_items=[
            CoreItem(item_id="sku_888", name="黑椒牛肉饭", order_share_pct=38, ctr_delta_pct=-14.8, flags=["hero"])
        ],
        competition_changes=[
            CompetitionChange(c_store_id="c1", type="image_upgrade", summary="竞品更换主图", price=29.9)
        ],
        platform_health=PlatformHealthState(open_status="open", hero_sku_in_stock_rate=1.0, im_reply_rate=0.98, store_rating=4.7),
        profit=ProfitState(take_home_rate=0.634, contribution_margin=0.181, ads_spend=180),
        generated_at=datetime(2026, 8, 12, 10, 20),
    )


def test_build_store_state_snapshot_maps_runtime_fields() -> None:
    snapshot = build_store_state_snapshot(_store_state())
    assert snapshot.store_id == "store_1"
    assert snapshot.business["orders_today"] == 83
    assert snapshot.funnel["ctr"] == 0.0291
    assert snapshot.platform["rating"] == 4.7
    assert snapshot.profit["contribution_margin"] == 0.181


def test_build_business_event_object_and_request() -> None:
    state = _store_state()
    event = OperatingEvent(
        id="evt_1",
        store_id="store_1",
        event_type="CTR_DROP",
        title="点击率下降",
        detail="CTR 较基线 -14.8%",
        severity="high",
        detected_at=datetime(2026, 8, 12, 10, 21),
        affected_metric="ctr",
        estimated_impact_amount=25,
        recommended_agent="storefront",
        manager_decision="handle_today",
    )
    business_event = build_business_event_object(event, state)
    request = build_runtime_bridge_run_request(state=state, event=event)

    assert business_event.domain == "PRODUCT"
    assert business_event.subject.type == "sku"
    assert business_event.subject.id == "sku_888"
    assert request.business_event.event_type == "CTR_DROP"
    assert request.trigger_reason == "ANOMALY"
    assert request.preferred_skills == ["product"]
    assert request.analysis_node


def test_pick_primary_event_prefers_severity_then_impact() -> None:
    events = [
        OperatingEvent(
            id="evt_low",
            store_id="store_1",
            event_type="CTR_DROP",
            title="点击率下降",
            detail="",
            severity="medium",
            detected_at=datetime(2026, 8, 12, 10, 21),
            estimated_impact_amount=35,
        ),
        OperatingEvent(
            id="evt_high",
            store_id="store_1",
            event_type="STORE_ABNORMAL_CLOSED",
            title="门店异常闭店",
            detail="",
            severity="critical",
            detected_at=datetime(2026, 8, 12, 10, 22),
            estimated_impact_amount=20,
        ),
    ]
    chosen = pick_primary_event(events)
    assert chosen is not None
    assert chosen.id == "evt_high"
