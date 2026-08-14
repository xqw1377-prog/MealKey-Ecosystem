from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.services.poie.intent import handle_user_intent, _parse_goal
from app.services.thread_engine import load_active_threads


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_parse_gmv_goal():
    req = _parse_goal("这个月做到20万")
    assert req is not None
    assert req.metric == "gmv"
    assert req.target_value == 200000


def test_parse_rank_goal():
    req = _parse_goal("帮我把牛肉饭做到前三")
    assert req is not None
    assert req.metric == "rank"
    assert req.target_value == 3.0


def test_non_goal_returns_none():
    assert _parse_goal("今天天气怎么样") is None
    assert handle_user_intent(_session(), "s1", "今天天气怎么样") is None


def test_review_question_hits_operating_demand():
    result = handle_user_intent(_session(), "s1", "帮我看看评价")
    assert result is not None
    assert result["mode"] == "operating_demand"
    assert result["demand"]["id"] == 51


def test_handle_user_intent_creates_goal_and_thread():
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]

    result = handle_user_intent(db, store_id, "这个月做到20万")
    assert result is not None
    assert result["intent"] == "goal"
    assert result["mode"] == "poie_intent"
    assert result["goal_id"]
    threads = load_active_threads(db, store_id)
    assert any("20万" in t.title or "20万" in t.goal for t in threads)
