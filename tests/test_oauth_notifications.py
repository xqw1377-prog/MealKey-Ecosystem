from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.entities import Merchant, Store
from app.models.notification import Notification
from app.services.notification_service import flush_queued_notifications, notify_store_owner
from app.services.platform_oauth import build_oauth_state, parse_oauth_state, persist_oauth_connection


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _store(db: Session) -> Store:
    merchant = Merchant(name="通知测试商户")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="测试店")
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def test_oauth_state_roundtrip_and_persist_connection() -> None:
    db = _session()
    store = _store(db)
    state = build_oauth_state("meituan", store_id=store.id)
    parsed = parse_oauth_state(state)
    assert parsed["platform"] == "meituan"
    assert parsed["store_id"] == store.id

    row = persist_oauth_connection(
        db,
        store_id=store.id,
        platform="meituan",
        token_payload={
            "access_token": "at-demo",
            "refresh_token": "rt-demo",
            "token_type": "bearer",
            "scope": "order menu",
            "expires_in": 3600,
            "shop_id": "mt-shop-1",
        },
    )
    db.commit()
    assert row.connector_mode == "oauth"
    assert row.status == "connected"
    assert row.external_store_id == "mt-shop-1"
    meta = json.loads(row.meta_json or "{}")
    assert "access_token" not in meta.get("oauth", {})
    assert "refresh_token" not in meta.get("oauth", {})
    assert meta["oauth"]["credential_status"] == "ACTIVE"
    from app.services.credential_store import get_oauth_secret, public_platform_link

    secret = get_oauth_secret(db, store.id, "meituan")
    assert secret["access_token"] == "at-demo"
    public = public_platform_link(row, db=db)
    assert "access_token" not in json.dumps(public)
    assert public["connected"] is True


def test_notifications_queue_in_quiet_hours_and_merge_digest(monkeypatch) -> None:
    db = _session()
    store = _store(db)

    monkeypatch.setattr("app.services.notification_service.resolve_store_rhythm", lambda db, store_id: object())
    monkeypatch.setattr("app.services.notification_service.is_in_quiet_hours", lambda rhythm, hour: True)

    first = notify_store_owner(
        db,
        store_id=store.id,
        notification_type="need_you",
        title="先看午高峰",
        body="第一条",
        clock_phase="lunch_nba",
    )
    second = notify_store_owner(
        db,
        store_id=store.id,
        notification_type="need_you",
        title="再看评价",
        body="第二条",
        clock_phase="lunch_nba",
    )
    assert first == second

    row = db.query(Notification).filter(Notification.store_id == store.id).one()
    assert row.push_status == "queued"
    assert "第一条" in (row.body or "")
    assert "第二条" in (row.body or "")

    monkeypatch.setattr("app.services.notification_service.is_in_quiet_hours", lambda rhythm, hour: False)
    released = flush_queued_notifications(db, store.id)
    assert released == 1
    db.refresh(row)
    assert row.push_status == "delivered"
