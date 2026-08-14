from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.commercial import StoreLicense
from app.models.entities import Merchant, Store
from app.models.settings import PlatformConnection
from app.services.mue import ensure_understanding, load_understanding
from app.services.platform_write import PLATFORM_WRITE_ALLOWLIST
from app.services.seed_launch import profit_honesty
from app.services.test_store_access import open_all_test_stores, open_test_store_access


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _store(db: Session, name: str = "测试牛肉饭") -> Store:
    merchant = Merchant(name=name)
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name=name, platform="meituan")
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def test_open_test_store_access_satisfies_mos_and_paid_license() -> None:
    db = _session()
    store = _store(db)
    result = open_test_store_access(db, store)

    assert result["mos_satisfied"] is True
    assert result["system_mode"] == "operating"
    assert result["blocking"] == []
    assert result["license"] == "paid"
    assert result["wallet_cny"] == 500
    assert result["low_risk_auto_ok"] is True
    assert result["writeback_allowlist_unchanged"] is True

    u = load_understanding(db, store.id)
    assert u.mos_satisfied is True
    assert u.system_mode == "operating"
    assert u.onboarding_stage == "operating"
    assert u.open_gaps == []
    assert u.permissions.auto_reply_good_reviews is True
    assert u.permissions.ads_auto_daily_limit_cny == 500
    assert u.preferences.priority_style == "balanced"
    assert u.platform_connected is True

    refreshed = ensure_understanding(db, store.id)
    assert refreshed.open_gaps == []
    assert refreshed.mos_satisfied is True

    conn = db.execute(
        select(PlatformConnection).where(PlatformConnection.store_id == store.id)
    ).scalar_one()
    assert conn.status == "connected"
    assert conn.connector_mode == "mock"

    license_row = db.execute(select(StoreLicense).where(StoreLicense.store_id == store.id)).scalar_one()
    assert license_row.status == "paid"

    honesty = profit_honesty(db, store.id)
    assert honesty["precise_profit"] is False
    assert PLATFORM_WRITE_ALLOWLIST == {
        "change_title",
        "change_main_image",
        "reply_ordinary_reviews",
        "appeal_pack",
    }


def test_open_all_test_stores_unlocks_every_active_store() -> None:
    db = _session()
    first = _store(db, "一店")
    second = _store(db, "二店")
    payload = open_all_test_stores(db)
    assert payload["count"] == 2
    ids = {row["store_id"] for row in payload["stores"]}
    assert ids == {first.id, second.id}
    assert all(row["mos_satisfied"] for row in payload["stores"])
    assert all(row["license"] == "paid" for row in payload["stores"])
