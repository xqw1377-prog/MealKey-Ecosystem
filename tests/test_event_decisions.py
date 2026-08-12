from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.services.event_decisions import (
    apply_decision_overrides,
    event_fingerprint,
    load_decision_map,
    upsert_event_decision,
)
from app.services.event_engine import build_operating_events
from app.services.store_state import build_store_state


def test_event_decision_persists_and_filters() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    seeded = seed_demo(db)
    store_id = seeded["store_id"]

    state = build_store_state(db, store_id)
    assert state is not None
    if state.kpis.get("ctr"):
        state.kpis["ctr"].delta_pct = -12
    events = build_operating_events(state)
    assert events.events
    target = events.events[0]
    fp = event_fingerprint(target)
    upsert_event_decision(db, store_id=store_id, fingerprint=fp, decision="ignore")
    updated = apply_decision_overrides(events, load_decision_map(db, store_id))
    matched = next(e for e in updated.events if event_fingerprint(e) == fp)
    assert matched.manager_decision == "ignore"
    assert matched.status == "ignored"
