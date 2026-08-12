from datetime import datetime

from app.schemas.content_engine import OperatingObjectRef
from app.schemas.runtime_bridge import RuntimeBridgeRunRequest
from app.schemas.runtime_objects import BusinessEventObject, MerchantContextItem, StoreStateSnapshot
from app.services.runtime_bridge import run_runtime_bridge_poc


def _base_store_state() -> StoreStateSnapshot:
    return StoreStateSnapshot(
        store_id="store_1",
        snapshot_at=datetime.now(),
        business={"orders_today": 83, "forecast_orders": 382},
        funnel={"ctr": 0.0291, "cvr": 0.172},
        profit={"take_home_rate": 0.64, "contribution_margin": 0.181, "ads_spend": 180},
        platform={"store_open": True, "rating": 4.7},
        market={"competition_level": "high"},
    )


def test_runtime_bridge_generates_candidate_odo_for_hero_ctr_drop() -> None:
    request = RuntimeBridgeRunRequest(
        store_state=_base_store_state(),
        business_event=BusinessEventObject(
            event_id="evt_hero_ctr",
            event_type="HERO_SKU_CTR_DROP",
            domain="PRODUCT",
            store_id="store_1",
            subject=OperatingObjectRef(type="sku", id="sku_888", name="黑椒牛肉饭"),
            severity="high",
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
                "competition_changes": [
                    {"type": "menu_added", "summary": "核心竞品新上 29.9 套餐"},
                    {"type": "price_down", "summary": "竞品工作餐套餐降价到 27.9"},
                ],
            },
        ),
        merchant_context=[
            MerchantContextItem(
                key="profit_floor_rate",
                value_json={"rate": 0.58},
                source="user",
                confidence=1.0,
            )
        ],
        goal_text="稳定午餐订单",
        trigger_reason="ANOMALY",
        runtime_state="pre_peak_decision",
        analysis_node="pre_lunch_nba",
    )

    result = run_runtime_bridge_poc(request)

    assert result.lead_agent == "mealkey_lead_agent"
    assert result.selected_skills[:3] == ["product", "competition", "profit"]
    assert any(item.skill_key == "product" for item in result.skill_executions)
    assert any(candidate.domain == "PRODUCT" for candidate in result.candidate_odos)

    product_candidate = next(candidate for candidate in result.candidate_odos if candidate.domain == "PRODUCT")
    assert product_candidate.odo.reason == "ANOMALY"
    assert product_candidate.odo.object.id == "sku_888"
    assert product_candidate.odo.recommended_action.type == "CHANGE_PRODUCT_IMAGE"
    assert product_candidate.odo.execution_mode in {"ASK_APPROVAL", "AUTO_AND_REPORT", "OBSERVE"}


def test_runtime_bridge_blocks_traffic_amplification_when_product_not_ready() -> None:
    request = RuntimeBridgeRunRequest(
        store_state=_base_store_state(),
        business_event=BusinessEventObject(
            event_id="evt_under_spend",
            event_type="HIGH_ROI_UNDERSPEND",
            domain="TRAFFIC",
            store_id="store_1",
            subject=OperatingObjectRef(type="sku", id="sku_888", name="黑椒牛肉饭"),
            severity="medium",
            observation={
                "metric": "roi",
                "change": 0.0,
                "estimated_roi": 3.6,
                "cvr": 0.11,
                "cvr_baseline": 0.16,
                "item_snapshots": [
                    {
                        "item_id": "sku_888",
                        "name": "黑椒牛肉饭",
                        "role": "Hero Product",
                        "observe_ctr": 0.018,
                        "baseline_ctr": 0.0342,
                        "ctr_delta_pct": -47.4,
                        "observe_cvr": 0.11,
                        "baseline_cvr": 0.16,
                        "price": 29.9,
                        "observe_orders": 35,
                        "order_share_pct": 20,
                    }
                ],
            },
        ),
        trigger_reason="TIME",
        runtime_state="pre_peak_decision",
        analysis_node="pre_lunch_nba",
    )

    result = run_runtime_bridge_poc(request)

    assert result.selected_skills[:3] == ["traffic", "product", "profit"]
    traffic_execution = next(item for item in result.skill_executions if item.skill_key == "traffic")
    assert traffic_execution.candidate_actions_count == 0
    assert "先调用 Product Domain 解决商品问题" in traffic_execution.recommended_next_step

    traffic_candidate = next(candidate for candidate in result.candidate_odos if candidate.domain == "TRAFFIC")
    assert traffic_candidate.odo.execution_mode == "OBSERVE"
    assert traffic_candidate.odo.recommended_action.type == ""
