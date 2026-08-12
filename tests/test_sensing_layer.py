from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.schemas.store_state import ProfitState
from app.services.event_engine import build_operating_events
from app.services.manager_brief import build_manager_home_brief
from app.services.profit_gate import evaluate_profit_gate
from app.services.store_state import build_store_state


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_store_state_includes_sensing_layers() -> None:
    db = _session()
    seeded = seed_demo(db)
    state = build_store_state(db, seeded["store_id"])
    assert state is not None
    assert state.business.health_score >= 20
    assert state.platform_health.score >= 20
    assert state.platform_health.judgment
    assert state.profit.data_quality in {"proxy", "missing", "observed"}
    assert state.benchmark is not None
    assert state.customer is not None


def test_event_engine_emits_manager_decisions() -> None:
    db = _session()
    seeded = seed_demo(db)
    state = build_store_state(db, seeded["store_id"])
    assert state is not None
    # Force a CTR drop signal for event emission
    if state.kpis.get("ctr"):
        state.kpis["ctr"].delta_pct = -12
    events = build_operating_events(state)
    assert events.summary
    assert any(e.event_type == "CTR_DROP" for e in events.events)
    assert any(e.manager_decision in {"handle_today", "alert_owner", "record"} for e in events.events)


def test_profit_gate_rejects_buy_gmv_promo() -> None:
    profit = ProfitState(
        gross_gmv=10000,
        customer_paid=10000,
        merchant_revenue=6400,
        take_home_rate=0.64,
        contribution_profit_per_order=8.2,
        data_quality="proxy",
    )
    decision = evaluate_profit_gate(
        profit,
        action_type="join_lunch_campaign",
        expected_order_lift_pct=18,
        expected_take_home_rate_after=0.57,
    )
    assert decision.allowed is False
    assert "买流水" in decision.reason or "不建议" in decision.reason


def test_manager_brief_is_judgment_first() -> None:
    db = _session()
    seeded = seed_demo(db)
    state = build_store_state(db, seeded["store_id"])
    assert state is not None
    events = build_operating_events(state)
    brief = build_manager_home_brief(state, events=events, parallel_service_notes=["AI 已准备评价草稿"])
    assert brief.store_name
    assert brief.business_health_score >= 20
    assert brief.business_judgment
