from datetime import datetime

from app.schemas.content_engine import OperatingObjectRef
from app.schemas.runtime_bridge import RuntimeBridgeRunRequest
from app.schemas.runtime_objects import BusinessEventObject, StoreStateSnapshot
from app.services.runtime_bridge_adapter import (
    runtime_bridge_result_to_runtime_feed,
    runtime_bridge_result_to_runtime_queue,
    run_runtime_bridge_runtime,
)


def _request() -> RuntimeBridgeRunRequest:
    return RuntimeBridgeRunRequest(
        store_state=StoreStateSnapshot(
            store_id="store_1",
            snapshot_at=datetime.now(),
            funnel={"ctr": 0.0291, "cvr": 0.172},
            profit={"take_home_rate": 0.64, "contribution_margin": 0.181, "ads_spend": 180},
            platform={"rating": 4.7},
        ),
        business_event=BusinessEventObject(
            event_id="evt_hero_ctr",
            event_type="HERO_SKU_CTR_DROP",
            domain="PRODUCT",
            store_id="store_1",
            subject=OperatingObjectRef(type="sku", id="sku_888", name="黑椒牛肉饭"),
            observation={
                "metric": "ctr",
                "change": -0.148,
                "benchmark": "7d_same_meal_period",
                "estimated_loss_orders": 25,
                "item_snapshots": [
                    {
                        "item_id": "sku_888",
                        "name": "黑椒牛肉饭",
                        "role": "Hero Product",
                        "observe_ctr": 0.0291,
                        "baseline_ctr": 0.0342,
                        "ctr_delta_pct": -14.8,
                        "observe_cvr": 0.172,
                        "baseline_cvr": 0.168,
                        "price": 29.9,
                        "observe_orders": 82,
                        "order_share_pct": 38,
                    }
                ],
            },
        ),
        goal_text="稳定午餐订单",
        trigger_reason="ANOMALY",
        runtime_state="pre_peak_decision",
        analysis_node="pre_lunch_nba",
    )


def test_runtime_adapter_returns_local_poc_result_by_default() -> None:
    result = run_runtime_bridge_runtime(_request())
    assert result.lead_agent == "mealkey_lead_agent"
    assert any(candidate.domain == "PRODUCT" for candidate in result.candidate_odos)


def test_runtime_adapter_projects_queue_and_feed() -> None:
    result = run_runtime_bridge_runtime(_request())
    queue = runtime_bridge_result_to_runtime_queue(
        store_id="store_1",
        runtime_state="pre_peak_decision",
        result=result,
        source_event_id="evt_hero_ctr",
    )
    feed = runtime_bridge_result_to_runtime_feed(
        store_id="store_1",
        runtime_state="pre_peak_decision",
        result=result,
        source_event_id="evt_hero_ctr",
    )

    assert queue.runtime_state == "pre_peak_decision"
    assert len(queue.items) >= 1
    assert queue.items[0].candidate_odo_id.startswith("evt_hero_ctr:")
    assert feed.runtime_state == "pre_peak_decision"
    assert len(feed.events) >= 1
    assert feed.events[0].source_odo_id.startswith("evt_hero_ctr:")
