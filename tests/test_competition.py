from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.entities import (
    CompetitorMenuItem,
    CompetitorSnapshot,
    CompetitorStore,
    Merchant,
    Store,
    StoreCompetitorWatch,
)
from app.services.agents import _distance_m, _positioning, build_single_agent
from app.services.store_state import build_store_state


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_competitor_distance_and_positioning() -> None:
    distance = _distance_m(39.909, 116.397, 39.912, 116.401)

    assert distance is not None
    assert 400 <= distance <= 600
    assert _positioning("28-35", 20, 25) == "低价快餐"
    assert _positioning("28-35", 27, 36) == "同价格带竞争"
    assert _positioning("28-35", 40, 48) == "品质溢价"


def test_store_state_detects_competitor_menu_changes() -> None:
    db = _session()
    merchant = Merchant(name="测试商户", category="快餐")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="测试门店", area="国贸")
    competitor = CompetitorStore(name="竞品 A", area="国贸", category="快餐")
    db.add_all([store, competitor])
    db.flush()
    db.add(
        StoreCompetitorWatch(
            store_id=store.id,
            c_store_id=competitor.id,
            provider="test",
            active=True,
        )
    )

    now = datetime.now(timezone.utc)
    previous = CompetitorSnapshot(
        c_store_id=competitor.id,
        captured_at=now - timedelta(days=1),
        rating=4.4,
        price_band_min=28,
        price_band_max=38,
    )
    latest = CompetitorSnapshot(
        c_store_id=competitor.id,
        captured_at=now,
        rating=4.7,
        price_band_min=26,
        price_band_max=36,
    )
    db.add_all([previous, latest])
    db.flush()
    db.add_all(
        [
            CompetitorMenuItem(
                snapshot_id=previous.id,
                name="鸡腿饭",
                price=30,
                image_url="old.jpg",
            ),
            CompetitorMenuItem(
                snapshot_id=latest.id,
                name="鸡腿饭",
                price=28,
                image_url="new.jpg",
            ),
            CompetitorMenuItem(
                snapshot_id=latest.id,
                name="午餐套餐",
                price=35,
            ),
        ]
    )
    db.commit()

    state = build_store_state(db, store.id)

    assert state is not None
    change_types = {change.type for change in state.competition_changes}
    assert {"price_down", "rating_up", "product_added"}.issubset(change_types)
    assert "product_price_changed" in change_types or "image_changed" in change_types


def test_competition_agent_returns_actionable_competitor_profile() -> None:
    db = _session()
    seeded = seed_demo(db)

    result = build_single_agent(db, seeded["store_id"], "competition")

    assert result is not None
    assert result["meta"]["confidence"] >= 0.7
    assert result["expected_impact"]
    assert result["actions"]
    competitor = result["top_competitors"][0]
    assert competitor["distance_m"] is not None
    assert competitor["positioning"] == "同价格带竞争"
    assert competitor["featured_products"]
    assert competitor["set_meal_count"] == 2
