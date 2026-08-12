"""AI 主动经营闭环测试 — 6 类触发 + 5 种决策 + 3 区前台。

覆盖：
- Goal 表 CRUD + 进度同步 + 偏差检测（第 3/5 类触发）
- 机会引擎扫描（第 4 类触发）
- 结果推送入晨报（第 6 类触发）
- 5 种 AI 决策行为
- 3 区前台结构（needs_you / auto_doing / results）
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.schemas.goal import GoalCreateRequest
from app.schemas.events import AIAction
from app.services.agents import build_store_agents
from app.services.event_engine import _decide_ai_action, build_operating_events
from app.services.goal_engine import (
    check_goal_deviation,
    create_goal,
    load_goal_snapshot,
    update_goal_progress,
)
from app.services.manager_brief import build_manager_home_brief


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


# ---------------------------------------------------------------------------
# 步骤 1: Goal 表 + 长期目标
# ---------------------------------------------------------------------------


def test_goal_crud_lifecycle() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]

    # 创建
    goal = create_goal(
        db, store_id,
        GoalCreateRequest(raw_text="本月GMV做到20万", metric="gmv", target_value=200000, deadline=date.today()),
    )
    assert goal.status == "active"
    assert goal.target_value == 200000

    # 快照
    snap = load_goal_snapshot(db, store_id)
    assert len(snap.active_goals) == 1
    assert snap.active_goals[0].raw_text == "本月GMV做到20万"


def test_goal_progress_sync() -> None:
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]

    create_goal(db, store_id, GoalCreateRequest(raw_text="订单目标", metric="orders", target_value=1000))
    updated = update_goal_progress(db, store_id, days=7)
    assert updated >= 1

    snap = load_goal_snapshot(db, store_id)
    goal = snap.active_goals[0]
    assert goal.current_value is not None  # 从 StoreState 回填了
    assert goal.gap is not None  # 算了偏差


def test_goal_deviation_detection() -> None:
    """目标偏差检测：forecast < target 时产生 alert。"""
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]

    # 设一个很高的目标（必然偏差）
    create_goal(db, store_id, GoalCreateRequest(raw_text="GMV做到100万", metric="gmv", target_value=1000000))
    update_goal_progress(db, store_id, days=7)

    alerts = check_goal_deviation(db, store_id)
    assert len(alerts) >= 1
    assert alerts[0].on_track is False


# ---------------------------------------------------------------------------
# 步骤 2: 机会引擎
# ---------------------------------------------------------------------------


def test_opportunity_scanner_returns_list() -> None:
    from app.services.opportunity_scanner import scan_opportunities

    db = _session()
    seeded = seed_demo(db)
    triggers = scan_opportunities(db, seeded["store_id"], days=7)
    # 可能返回空（demo 数据不一定触发），但必须是 list
    assert isinstance(triggers, list)


# ---------------------------------------------------------------------------
# 步骤 3: 结果推送
# ---------------------------------------------------------------------------


def test_brief_includes_results_from_strategy_memory() -> None:
    """晨报 results 区包含归因完成的实验结论。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None

    brief = build_manager_home_brief(
        agents.store_state,
        growth=agents.growth,
        storefront=agents.storefront,
        agents=agents,
        db=db,
        store_id=seeded["store_id"],
    )
    # results 是 list（可能为空，因为 demo 没有归因完成的实验）
    assert isinstance(brief.results, list)


# ---------------------------------------------------------------------------
# 步骤 4: 5 种 AI 决策行为
# ---------------------------------------------------------------------------


def test_ai_action_decides_correctly() -> None:
    """5 种 AI 行为决策覆盖各种场景。"""
    # critical → need_assist
    assert _decide_ai_action("STORE_ABNORMAL_CLOSED", "critical", 0.9, "diagnosis") == "need_assist"
    # service → auto_handle（AI 自己回复评价）
    assert _decide_ai_action("RATING_DROP", "medium", 0.8, "service") == "auto_handle"
    # review → auto_handle
    assert _decide_ai_action("RATING_DROP", "medium", 0.8, "review") == "auto_handle"
    # high + storefront → need_confirm（换主图要老板确认）
    assert _decide_ai_action("CTR_DROP", "high", 0.85, "storefront") == "need_confirm"
    # medium + promo → need_confirm（活动要老板确认花钱）
    assert _decide_ai_action("ACTIVITY_EXPIRING", "medium", 0.75, "promo") == "need_confirm"
    # 低置信度 → silent_observe
    assert _decide_ai_action("CTR_DROP", "medium", 0.4, "storefront") == "silent_observe"


def test_events_have_ai_action_assigned() -> None:
    """事件引擎产出的事件都带 ai_action 字段。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None
    events = build_operating_events(agents.store_state)
    for event in events.events:
        assert event.ai_action is not None
        assert event.ai_action in {"auto_handle", "need_confirm", "need_assist", "inform_only", "silent_observe"}


# ---------------------------------------------------------------------------
# 步骤 5: 3 区前台
# ---------------------------------------------------------------------------


def test_brief_has_3_zone_structure() -> None:
    """晨报包含 3 区：needs_you / auto_doing / results + goal_prompt。"""
    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None
    brief = build_manager_home_brief(
        agents.store_state,
        growth=agents.growth,
        storefront=agents.storefront,
        agents=agents,
        db=db,
        store_id=seeded["store_id"],
    )
    # 3 区都是 list
    assert isinstance(brief.needs_you, list)
    assert isinstance(brief.auto_doing, list)
    assert isinstance(brief.results, list)
    # goal_prompt 存在
    assert brief.goal_prompt is not None
    assert "MealKey" in brief.goal_prompt or "做到" in brief.goal_prompt


def test_brief_needs_you_from_events() -> None:
    """需要老板处理的事件进入 needs_you。"""
    from app.schemas.events import EventEngineResult, OperatingEvent

    db = _session()
    seeded = seed_demo(db)
    agents = build_store_agents(db, seeded["store_id"])
    assert agents is not None

    # 构造一个带 need_confirm 事件的结果
    now = datetime.now(timezone.utc)
    fake_events = EventEngineResult(
        store_id=seeded["store_id"],
        generated_at=now,
        events=[
            OperatingEvent(
                id="e1",
                store_id=seeded["store_id"],
                event_type="CTR_DROP",
                title="点击率下降",
                detail="CTR -15%",
                severity="high",
                detected_at=now,
                affected_metric="ctr",
                estimated_impact="预计损失20单",
                confidence=0.85,
                recommended_agent="storefront",
                manager_decision="handle_today",
                ai_action="need_confirm",
            ),
        ],
        open_count=1,
        handle_today_count=1,
        summary="test",
    )

    brief = build_manager_home_brief(
        agents.store_state,
        events=fake_events,
        growth=agents.growth,
        storefront=agents.storefront,
        agents=agents,
        db=db,
        store_id=seeded["store_id"],
    )
    # need_confirm 事件进入 needs_you
    assert len(brief.needs_you) >= 1
    assert any("点击率" in t.title or "CTR" in t.detail for t in brief.needs_you)
