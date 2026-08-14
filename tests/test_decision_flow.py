from datetime import datetime

from app.schemas.arbiter import DecisionAction, DecisionCard, OpsQueueBrief
from app.schemas.events import EventEngineResult, OperatingEvent
from app.schemas.runtime_api import WorkspaceRuntimeResponse
from app.services.decision_flow import (
    build_decision_flow,
    is_growth_action,
    resolve_operating_phase,
)
from app.services.operating_rhythm import DEFAULT_RHYTHM
from app.services.poie.triggers import trigger_time


def _card(**kwargs) -> DecisionCard:
    data = {
        "id": "nba-1",
        "title": "把黑椒饭主图换成份量特写",
        "arbiter_state": "confirm",
        "interrupt_reason": "time",
        "queue_bucket": "need_you",
        "why_now": "高峰前改完还能赶上这一餐",
        "ai_judgment": "主图点击率连续 3 天低于商圈",
        "actions": [DecisionAction(label="按这个做", kind="adopt")],
    }
    data.update(kwargs)
    return DecisionCard(**data)


def _queue(**kwargs) -> OpsQueueBrief:
    data = {"need_you": [], "working": [], "results": [], "opportunities": []}
    data.update(kwargs)
    return OpsQueueBrief(**data)


def test_resolve_phase_covers_clock_windows() -> None:
    rhythm = DEFAULT_RHYTHM
    assert resolve_operating_phase(rhythm, hour=3) == "night_learn"
    assert resolve_operating_phase(rhythm, hour=7) == "deep_review"
    assert resolve_operating_phase(rhythm, hour=9) == "morning_readiness"
    assert resolve_operating_phase(rhythm, hour=10) == "lunch_nba"
    assert resolve_operating_phase(rhythm, hour=12) == "lunch_protect"
    assert resolve_operating_phase(rhythm, hour=14) == "lunch_review"
    assert resolve_operating_phase(rhythm, hour=15) == "dinner_strategy"
    assert resolve_operating_phase(rhythm, hour=16) == "lunch_nba"
    assert resolve_operating_phase(rhythm, hour=18) == "lunch_protect"
    assert resolve_operating_phase(rhythm, hour=21) == "evening_review"
    assert resolve_operating_phase(rhythm, hour=23) == "quiet"


def test_empty_pre_peak_does_not_fake_an_approval() -> None:
    flow = build_decision_flow(queue=_queue(), hour=10, rhythm=DEFAULT_RHYTHM)
    assert flow["phase"] == "lunch_nba"
    assert flow["now"]["owner"] == "ai"
    assert not flow["now"]["source_card_id"]
    assert flow["interrupt_ok"] is False
    assert flow["guide"]["type"] == "INFO"
    assert flow["guide"]["choices"] == []


def test_pre_peak_projects_single_nba() -> None:
    flow = build_decision_flow(
        queue=_queue(need_you=[_card()]),
        hour=10,
        rhythm=DEFAULT_RHYTHM,
    )
    assert flow["phase"] == "lunch_nba"
    assert flow["interrupt_ok"] is True
    assert flow["protect_mode"] is False
    assert flow["now"]["title"] == "把黑椒饭主图换成份量特写"
    assert flow["now"]["owner"] == "boss"
    assert flow["guide"]["type"] == "APPROVAL"
    assert "如果现在不做" not in flow["now"]["if_skip"]
    assert flow["now"]["if_skip"]
    assert flow["next"]["when"] == "高峰保护"


def test_protect_mode_does_not_push_growth_action() -> None:
    growth = _card(title="加 200 元午餐投流", why_now="想趁高峰放量")
    assert is_growth_action(growth)
    flow = build_decision_flow(
        queue=_queue(need_you=[growth]),
        hour=12,
        rhythm=DEFAULT_RHYTHM,
    )
    assert flow["phase"] == "lunch_protect"
    assert flow["protect_mode"] is True
    assert flow["growth_ok"] is False
    assert flow["now"]["title"] == "高峰保护中，我只盯异常"
    assert flow["now"]["owner"] == "ai"
    assert flow["guide"]["type"] == "INFO"
    assert flow["interrupt_ok"] is False


def test_protect_mode_still_surfaces_sold_out() -> None:
    events = EventEngineResult(
        store_id="s1",
        generated_at=datetime.now(),
        events=[
            OperatingEvent(
                id="e-soldout",
                store_id="s1",
                event_type="HERO_SKU_SOLD_OUT",
                title="黑椒牛肉饭提前售罄",
                detail="高峰还有 40 分钟，主推已经没了。",
                severity="critical",
                detected_at=datetime.now(),
                status="open",
            )
        ],
        open_count=1,
        alert_count=1,
    )
    flow = build_decision_flow(
        queue=_queue(need_you=[_card(title="加午餐广告预算")]),
        events=events,
        hour=12,
        rhythm=DEFAULT_RHYTHM,
    )
    assert flow["protect_mode"] is True
    assert flow["now"]["title"] == "黑椒牛肉饭提前售罄"
    assert flow["now"]["owner"] == "boss"
    assert flow["interrupt_ok"] is True
    assert flow["guide"]["type"] == "APPROVAL"


def test_quiet_hours_do_not_interrupt() -> None:
    flow = build_decision_flow(
        queue=_queue(need_you=[_card()]),
        hour=23,
        rhythm=DEFAULT_RHYTHM,
    )
    assert flow["phase"] == "quiet"
    assert flow["now"]["owner"] == "ai"
    assert flow["interrupt_ok"] is False
    assert flow["guide"]["type"] == "INFO"


def test_morning_readiness_prefers_ops_over_growth() -> None:
    ops = _card(
        id="ops-1",
        title="主推活动今晚过期",
        why_now="开店前先把活动续上",
        interrupt_reason="anomaly",
    )
    growth = _card(id="ads-1", title="加投流预算冲排名", why_now="想冲午高峰曝光")
    flow = build_decision_flow(
        queue=_queue(need_you=[growth, ops]),
        hour=9,
        rhythm=DEFAULT_RHYTHM,
    )
    assert flow["phase"] == "morning_readiness"
    assert flow["now"]["id"] == "ops-1"
    assert flow["growth_ok"] is False


def test_evening_review_holds_new_actions() -> None:
    flow = build_decision_flow(
        queue=_queue(need_you=[_card()]),
        hour=21,
        rhythm=DEFAULT_RHYTHM,
    )
    assert flow["phase"] == "evening_review"
    assert flow["now"]["title"] == "今晚不再新开动作"
    assert flow["guide"]["type"] == "INFO"


def test_trigger_time_respects_peak_protect_hour() -> None:
    from app.schemas.store_state import ManagerHomeBrief, PrimaryExperimentBrief

    brief = ManagerHomeBrief(
        store_name="测试店",
        business_health_score=70,
        business_judgment="平稳",
        primary_experiment=PrimaryExperimentBrief(
            title="主图实验",
            status="proposed",
            recommendation_id="r1",
        ),
    )
    assert trigger_time(brief, None, hour=12) == []
    assert trigger_time(brief, None, hour=10)


def test_now_id_matches_need_you_and_guide() -> None:
    card = _card()
    flow = build_decision_flow(
        queue=_queue(need_you=[card]),
        hour=10,
        rhythm=DEFAULT_RHYTHM,
    )
    assert flow["now"]["id"] == card.id
    assert flow["now"]["source_card_id"] == card.id
    assert flow["guide"]["id"] == card.id
    pack = flow["now"].get("execution_pack") or {}
    assert pack.get("action_type") == "change_main_image"
    assert "CTR" not in (pack.get("copy_text") or "")


def test_attach_decision_flow_forces_now_id() -> None:
    from app.services.decision_flow import attach_decision_flow

    card = _card()
    flow = build_decision_flow(
        queue=_queue(need_you=[card]),
        hour=10,
        rhythm=DEFAULT_RHYTHM,
    )
    merged = attach_decision_flow({"id": "bridge-other", "type": "APPROVAL", "title": "别的卡"}, flow)
    assert merged["id"] == card.id
    assert merged.get("execution_pack", {}).get("action_type") == "change_main_image"


def test_left_panel_does_not_split_finding_from_now() -> None:
    from app.api.routes_runtime import _build_left_panel

    nba = _card(id="nba-1", title="先换主图，抢回第一眼点击")
    working = _card(id="nba-1", title="先换主图，抢回第一眼点击")
    events = EventEngineResult(
        store_id="s1",
        generated_at=datetime.now(),
        events=[
            OperatingEvent(
                id="ev-ctr",
                store_id="s1",
                event_type="CTR_DROP",
                title="点击率下降",
                detail="ctr 较baseline_window 下降 15.4%",
                severity="high",
                detected_at=datetime.now(),
                estimated_impact="CTR 较基线-15.4%，预计今日损失约5单",
            )
        ],
        open_count=1,
        alert_count=1,
    )
    left = _build_left_panel(
        _queue(need_you=[nba], working=[working]),
        None,
        now_id="nba-1",
        now_title=nba.title,
        events=events,
    )
    need_ids = [item["id"] for item in left["need_you"]]
    active_ids = [item["id"] for item in left["active"]]
    assert "nba-1" not in need_ids
    assert "nba-1" not in active_ids
    assert "ev-ctr" not in need_ids
    workspace = WorkspaceRuntimeResponse.model_validate(
        {
            "store": {
                "store_id": "store_1",
                "store_name": "老王牛肉饭",
                "runtime_state": "pre_peak_decision",
                "operating_phase": "lunch_nba",
                "phase_label": "高峰前 · 今天只拍这一板",
            },
            "left": {
                "need_you": [],
                "active": [],
                "waiting": [],
                "completed": [],
                "opportunities": [],
                "active_goal": None,
                "threads": [],
            },
            "center": {
                "active_thread_id": None,
                "guide": {"type": "APPROVAL", "title": "今天只拍这一板"},
                "principle": "系统负责发现所有事情",
                "decision_flow": {"phase": "lunch_nba", "now": {"title": "改主图"}},
            },
            "right": {"proactive_feed": [], "filtered_count": 0},
            "meta": {
                "candidates_total": 0,
                "filtered_noop_count": 0,
                "mealkey_score": None,
                "operation_score": None,
            },
        }
    )
    assert workspace.center.decision_flow["phase"] == "lunch_nba"
    assert workspace.store.operating_phase == "lunch_nba"
    assert workspace.center.loop is None


def _memory_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import app.models  # noqa: F401
    from app.db.base import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_nba_pin_keeps_same_card_through_the_phase() -> None:
    from app.services.operating_clock import save_nba_pin

    db = _memory_db()
    save_nba_pin(db, "s1", "lunch_nba", "nba-1")
    db.commit()
    first = _card(id="nba-1", title="把黑椒饭主图换成份量特写")
    later = _card(id="nba-2", title="加投流冲排名", why_now="想加预算")
    flow = build_decision_flow(
        queue=_queue(need_you=[later, first]),
        hour=10,
        rhythm=DEFAULT_RHYTHM,
        db=db,
        store_id="s1",
    )
    assert flow["now"]["id"] == "nba-1"


def test_light_tick_does_not_auto_execute_in_protect() -> None:
    from app.services.operating_clock import apply_light_tick

    db = _memory_db()
    flow = build_decision_flow(
        queue=_queue(need_you=[_card(title="加 200 元午餐投流")]),
        hour=12,
        rhythm=DEFAULT_RHYTHM,
    )
    result = apply_light_tick(db, "s1", flow=flow)
    assert flow["protect_mode"] is True
    assert result["auto_executed"] == []
    assert result["notified"] is False
    assert result["pinned"] is None


def test_light_tick_pins_and_notifies_pre_peak_nba() -> None:
    from app.services.operating_clock import apply_light_tick, load_nba_pin
    from app.services.notification_service import notify_store_owner

    db = _memory_db()
    flow = build_decision_flow(
        queue=_queue(need_you=[_card()]),
        hour=10,
        rhythm=DEFAULT_RHYTHM,
    )
    result = apply_light_tick(db, "s1", flow=flow)
    assert result["pinned"] == "nba-1"
    assert load_nba_pin(db, "s1", "lunch_nba") == "nba-1"
    assert result["notified"] is True
    # 同一 NBA 当天不重复叫
    again = apply_light_tick(db, "s1", flow=flow)
    assert again["notified"] is False
    assert notify_store_owner(
        db,
        store_id="s1",
        notification_type="need_you",
        title="重复",
        related_decision_id="nba-1",
    ) is None


def test_inprocess_clock_disabled_in_pytest() -> None:
    from app.services.operating_clock import clock_disabled, start_inprocess_clock

    assert clock_disabled() is True
    assert start_inprocess_clock() is None
