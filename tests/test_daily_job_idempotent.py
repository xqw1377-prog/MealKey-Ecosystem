from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.ohre import Observation, Recommendation
from app.services.daily_job import run_daily_job
from app.services.store_state import build_store_state


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_daily_job_is_idempotent_for_same_observe_window() -> None:
    db = _session()
    seeded = seed_demo(db)

    first = run_daily_job(db, seeded["store_id"], days=7)
    second = run_daily_job(db, seeded["store_id"], days=7)

    assert first is not None and second is not None
    observation_count = db.execute(
        select(func.count()).select_from(Observation).where(Observation.store_id == seeded["store_id"])
    ).scalar_one()
    recommendation_count = db.execute(
        select(func.count())
        .select_from(Recommendation)
        .where(
            Recommendation.store_id == seeded["store_id"],
            Recommendation.status.in_(("proposed", "adopted", "executed")),
        )
    ).scalar_one()

    assert observation_count == len(first.observations)
    assert recommendation_count == len(first.top_actions)
    assert len(second.observations) == len(first.observations)


def test_core_item_uses_real_menu_name() -> None:
    db = _session()
    seeded = seed_demo(db)
    state = build_store_state(db, seeded["store_id"], days=7)
    assert state is not None
    assert state.core_items
    assert state.core_items[0].name != "SKU"
