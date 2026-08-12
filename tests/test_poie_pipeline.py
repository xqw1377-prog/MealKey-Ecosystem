"""POIE 全链路：Trigger 汇流 → 仲裁 → ops_queue。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.schemas.goal import GoalCreateRequest
from app.services.agents import build_store_agents
from app.services.event_decisions import apply_decision_overrides, load_decision_map
from app.services.event_engine import build_operating_events
from app.services.goal_engine import create_goal, update_goal_progress
from app.services.manager_brief import build_manager_home_brief
from app.services.poie import run_poie
from app.services.poie.triggers import collect_candidates
from app.services.strategy_memory import load_strategy_memory


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_collect_candidates_from_demo_store():
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    agents = build_store_agents(db=db, store_id=store_id, days=7)
    assert agents is not None
    events = apply_decision_overrides(
        build_operating_events(agents.store_state),
        load_decision_map(db, store_id),
    )
    memory = load_strategy_memory(db, store_id)
    brief = build_manager_home_brief(
        agents.store_state,
        events=events,
        growth=agents.growth,
        storefront=agents.storefront,
        agents=agents,
        strategy_memory=memory,
        db=db,
        store_id=store_id,
    )
    create_goal(
        db,
        store_id,
        GoalCreateRequest(raw_text="GMV做到100万", metric="gmv", target_value=1_000_000),
    )
    update_goal_progress(db, store_id, days=7)

    cands = collect_candidates(
        brief,
        store_id=store_id,
        events=events,
        agents=agents,
        strategy_memory=memory,
        db=db,
    )
    triggers = {c.trigger for c in cands}
    # demo + 高目标至少应打出 goal / anomaly / result 中若干类
    assert cands
    assert triggers & {"goal", "anomaly", "opportunity", "time", "history", "result"}


def test_run_poie_full_pipeline_merges_queue():
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    agents = build_store_agents(db=db, store_id=store_id, days=7)
    assert agents is not None
    events = apply_decision_overrides(
        build_operating_events(agents.store_state),
        load_decision_map(db, store_id),
    )
    memory = load_strategy_memory(db, store_id)
    brief = build_manager_home_brief(
        agents.store_state,
        events=events,
        growth=agents.growth,
        storefront=agents.storefront,
        agents=agents,
        strategy_memory=memory,
        db=db,
        store_id=store_id,
    )
    create_goal(
        db,
        store_id,
        GoalCreateRequest(raw_text="GMV做到100万", metric="gmv", target_value=1_000_000),
    )

    result = run_poie(
        brief,
        store_id=store_id,
        events=events,
        agents=agents,
        strategy_memory=memory,
        db=db,
    )
    assert result.ops_queue is not None
    assert result.candidates_total >= 1
    assert len(result.ops_queue.need_you) <= 3
    # 高目标偏差应进入 active_goals 或 need_you
    assert result.active_goals or result.ops_queue.need_you or result.ops_queue.working
