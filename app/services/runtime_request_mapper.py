"""Map current MealKey runtime objects into Runtime Bridge bridge requests."""

from __future__ import annotations

from datetime import datetime

from app.schemas.content_engine import OperatingObjectRef
from app.schemas.runtime_bridge import RuntimeBridgeRunRequest
from app.schemas.events import OperatingEvent
from app.schemas.runtime_objects import BusinessEventObject, MerchantContextItem, StoreStateSnapshot
from app.schemas.runtime import build_daily_operating_state
from app.schemas.store_state import DeltaMetric, StoreState
from app.services.runtime_engine import determine_runtime_state


_EVENT_DOMAIN_MAP: dict[str, str] = {
    "CTR_DROP": "PRODUCT",
    "CVR_DROP": "PRODUCT",
    "HERO_SKU_SOLD_OUT": "PRODUCT",
    "TAKE_RATE_DROP": "PROFIT",
    "ADS_ROI_DROP": "TRAFFIC",
    "ACTIVITY_EXPIRING": "TRAFFIC",
    "STORE_ABNORMAL_CLOSED": "PLATFORM",
    "RATING_DROP": "REPUTATION",
    "IM_REPLY_DROP": "PLATFORM",
    "COMPETITOR_NEW_PRODUCT": "COMPETITION",
    "COMPETITOR_NEW_PROMOTION": "COMPETITION",
    "COMPETITOR_PRICE_CHANGE": "COMPETITION",
    "OPPORTUNITY_DETECTED": "COMPETITION",
}

_EVENT_TRIGGER_MAP: dict[str, str] = {
    "ACTIVITY_EXPIRING": "TIME",
    "OPPORTUNITY_DETECTED": "OPPORTUNITY",
}

_AGENT_TO_SKILL: dict[str, str] = {
    "product": "product",
    "menu": "product",
    "storefront": "product",
    "ads": "traffic",
    "promo": "traffic",
    "competition": "competition",
    "diagnosis": "profit",
}


def build_store_state_snapshot(state: StoreState) -> StoreStateSnapshot:
    orders = state.kpis.get("orders") or DeltaMetric()
    gmv = state.kpis.get("gmv") or DeltaMetric()
    impressions = state.kpis.get("impressions") or DeltaMetric()
    ctr = state.kpis.get("ctr") or DeltaMetric()
    cvr = state.kpis.get("cvr") or DeltaMetric()
    return StoreStateSnapshot(
        store_id=state.store.store_id,
        snapshot_at=state.generated_at or datetime.now(),
        business={
            "orders_today": orders.observed_value or orders.value,
            "forecast_orders": orders.baseline_value,
            "gmv_today": gmv.observed_value or gmv.value,
            "forecast_gmv": gmv.baseline_value,
        },
        funnel={
            "exposure": impressions.observed_value or impressions.value,
            "ctr": ctr.observed_value or ctr.value,
            "cvr": cvr.observed_value or cvr.value,
        },
        profit={
            "take_home_rate": state.profit.take_home_rate,
            "contribution_margin": state.profit.contribution_margin,
            "ads_spend": state.profit.ads_spend,
        },
        platform={
            "store_open": state.platform_health.open_status == "open",
            "hero_sku_available_rate": state.platform_health.hero_sku_in_stock_rate,
            "im_reply_rate": state.platform_health.im_reply_rate,
            "rating": state.platform_health.store_rating,
        },
        market={
            "competition_level": "high" if state.competition_changes else "normal",
        },
        customer={
            "repeat_rate": state.customer.repurchase_rate,
            "new_customer_ratio": state.customer.new_customer_share_pct,
        },
    )


def build_business_event_object(event: OperatingEvent, state: StoreState) -> BusinessEventObject:
    subject = _guess_subject(event, state)
    competition_changes = [
        {"type": item.type, "summary": item.summary, "price": item.price}
        for item in state.competition_changes[:3]
    ]
    item_snapshots = [
        {
            "item_id": item.item_id,
            "name": item.name,
            "role": "Hero Product" if "hero" in [flag.lower() for flag in item.flags] or (item.order_share_pct or 0) >= 35 else "Product",
            "observe_ctr": item.ctr_delta_pct,
            "baseline_ctr": None,
            "ctr_delta_pct": item.ctr_delta_pct,
            "order_share_pct": item.order_share_pct,
        }
        for item in state.core_items[:3]
    ]
    observation = {
        "metric": event.affected_metric or "",
        "change": _metric_change_from_event(event, state),
        "benchmark": "baseline_window",
        "estimated_loss_orders": event.estimated_impact_amount,
        "competition_changes": competition_changes,
        "item_snapshots": item_snapshots,
    }
    return BusinessEventObject(
        event_id=event.id,
        event_type=event.event_type,
        domain=_EVENT_DOMAIN_MAP.get(event.event_type, "PLATFORM"),  # type: ignore[arg-type]
        store_id=event.store_id,
        subject=subject,
        severity=event.severity,
        observation=observation,
        detected_at=event.detected_at,
        status=event.status.upper(),
    )


def build_runtime_bridge_run_request(
    *,
    state: StoreState,
    event: OperatingEvent,
    merchant_context: list[MerchantContextItem] | None = None,
    goal_text: str = "",
    question: str = "",
) -> RuntimeBridgeRunRequest:
    runtime_state = determine_runtime_state()
    runtime_snapshot = build_daily_operating_state(current_state=runtime_state)
    preferred_skill = _AGENT_TO_SKILL.get(event.recommended_agent or "")
    return RuntimeBridgeRunRequest(
        store_state=build_store_state_snapshot(state),
        business_event=build_business_event_object(event, state),
        merchant_context=merchant_context or [],
        goal_text=goal_text,
        question=question,
        trigger_reason=_EVENT_TRIGGER_MAP.get(event.event_type, "ANOMALY"),  # type: ignore[arg-type]
        runtime_state=runtime_state,
        analysis_node=runtime_snapshot.current_node,
        preferred_skills=[preferred_skill] if preferred_skill else [],
        system_mode="operating",
    )


def pick_primary_event(events: list[OperatingEvent]) -> OperatingEvent | None:
    if not events:
        return None
    severity_rank = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
    ordered = sorted(
        events,
        key=lambda event: (
            severity_rank.get(event.severity, 0),
            float(event.estimated_impact_amount or 0),
            1 if event.manager_decision in {"alert_owner", "handle_today"} else 0,
        ),
        reverse=True,
    )
    return ordered[0]


def _metric_change_from_event(event: OperatingEvent, state: StoreState) -> float | None:
    metric = (event.affected_metric or "").lower()
    delta = state.kpis.get(metric)
    if delta and delta.delta_pct is not None:
        return float(delta.delta_pct)
    return None


def _guess_subject(event: OperatingEvent, state: StoreState) -> OperatingObjectRef:
    if event.event_type in {"CTR_DROP", "CVR_DROP", "HERO_SKU_SOLD_OUT"} and state.core_items:
        hero = max(state.core_items, key=lambda item: item.order_share_pct or 0)
        return OperatingObjectRef(type="sku", id=hero.item_id, name=hero.name)
    return OperatingObjectRef(type="store", id=state.store.store_id, name=state.store.name)
