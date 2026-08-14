from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.services.mue import (
    ensure_understanding,
    handle_understanding_intent,
    load_understanding,
)
from app.services.mue.nl_update import apply_nl_update
from app.services.poie import handle_user_intent


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_bootstrap_knows_store_and_keeps_gaps():
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    from app.services.agents import build_store_agents

    agents = build_store_agents(db=db, store_id=store_id, days=7)
    u = ensure_understanding(db, store_id, agents=agents)
    assert u.known_count >= 1
    assert "priority_style" in u.open_gaps
    assert u.principle.startswith("Ask Only")


def test_nl_chip_labels_update_priority_without_interview_key():
    from app.schemas.merchant_understanding import MerchantUnderstanding

    u = MerchantUnderstanding(store_id="s1", open_gaps=["priority_style", "lunch_capacity"])
    result = apply_nl_update(u, "提高利润")
    assert result is not None
    assert result.understanding.preferences.priority_style == "profit"
    assert "priority_style" not in result.understanding.open_gaps


def test_nl_profit_priority_updates_preferences():
    from app.schemas.merchant_understanding import MerchantUnderstanding

    u = MerchantUnderstanding(store_id="s1", open_gaps=["priority_style", "lunch_capacity"])
    result = apply_nl_update(u, "先赚钱，别瞎冲单量")
    assert result is not None
    assert result.understanding.preferences.priority_style == "profit"
    assert "priority_style" not in result.understanding.open_gaps


def test_nl_ads_limit_and_capacity():
    from app.schemas.merchant_understanding import MerchantUnderstanding

    u = MerchantUnderstanding(store_id="s1", open_gaps=["lunch_capacity"])
    r1 = apply_nl_update(u, "以后广告每天200以内你自己决定")
    assert r1 is not None
    assert r1.understanding.permissions.ads_auto_daily_limit_cny == 200

    r2 = apply_nl_update(u, "午餐一小时大概100单，再多就顶不住")
    assert r2 is not None
    assert r2.understanding.constraints.lunch_capacity_per_hour == 100
    assert "lunch_capacity" not in r2.understanding.open_gaps


def test_ask_path_routes_setting_before_goal():
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    hit = handle_user_intent(db, store_id, "利润优先，少点优惠")
    assert hit is not None
    assert hit["mode"] == "mue_update"
    u = load_understanding(db, store_id)
    assert u.preferences.priority_style == "profit"


def test_handle_understanding_persists():
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    hit = handle_understanding_intent(db, store_id, "可以，普通好评你直接回")
    assert hit is not None
    u = load_understanding(db, store_id)
    assert u.permissions.auto_reply_good_reviews is True
    assert u.permissions.low_risk_auto_ok is True
    assert "low_risk_auto" not in u.open_gaps
    assert "risk_boundary" not in u.mos_blocking_fields


def test_handle_understanding_uses_explicit_key():
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    hit = handle_understanding_intent(db, store_id, "提高排名", key="priority_style")
    assert hit is not None
    assert hit.get("accepted") is True
    u = load_understanding(db, store_id)
    assert u.preferences.priority_style == "rank"
    assert "priority_style" not in u.open_gaps
    assert u.mos_satisfied is False
    assert "priority_style" not in u.mos_blocking_fields


def test_interview_nl_miss_returns_none():
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    hit = handle_understanding_intent(db, store_id, "今天天气真好", key="priority_style")
    assert hit is None


def test_handle_user_intent_compiles_action():
    db = _session()
    seeded = seed_demo(db)
    hit = handle_user_intent(db, seeded["store_id"], "换牛肉饭主图")
    assert hit is not None
    assert hit["intent"] == "action"
    assert hit["decision"]["action_type"] == "change_main_image"
    assert hit["decision"]["execution_tier"] == "draft"


def test_ingest_attachment_knowledge_writes_profile():
    from types import SimpleNamespace

    from app.services.mue.engine import ingest_attachment_knowledge

    db = _session()
    seeded = seed_demo(db)
    files = [SimpleNamespace(name="菜单.png", extracted_text="牛肉饭 28元 套餐 39元")]
    view = ingest_attachment_knowledge(db, seeded["store_id"], files)
    assert view is not None
    assert "牛肉饭" in view.store_profile.get("from_files", "")
    assert view.store_profile.get("has_menu_snapshot") is True
