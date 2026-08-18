"""种子客户门店测试 Gate：只读、禁写回、禁 Mock、Day 0 不进 StoreState。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.closed_loop import ClosedLoopItem
from app.models.entities import Merchant, ShopFunnelDaily, Store
from app.models.settings import PlatformConnection
from app.services.data_acquisition_ingest import ingest_reconciliation
from app.services.platform_write import WritePermissionError, execute_confirmed_writeback
from app.services.seed_store import (
    WRITEBACK_DISABLED,
    SeedStoreError,
    assert_writeback_allowed,
    is_seed_store,
    open_seed_store,
    seed_store_readiness,
)
from app.services.store_state import build_store_state
from app.services.test_store_access import open_test_store_access


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _store(db: Session, platform: str = "meituan") -> Store:
    merchant = Merchant(name="种子客户")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="授权测试店", city="北京", platform=platform)
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def test_open_seed_store_is_read_only_and_gates_pass() -> None:
    db = _session()
    store = _store(db)
    ready = open_seed_store(db, store, authorizer="店主王先生", authorization_note="7天只读测试")
    db.commit()

    assert ready["can_start_day0"] is True
    assert ready["day0_verdict"] == "DAY0_READY"
    assert ready["can_promote_truth"] is False
    assert ready["authority"]["status"] == "PASS"
    assert ready["execution"]["status"] == "PASS"
    assert ready["truth"]["status"] == "PASS"
    assert ready["data_as_01"]["connector"] == "UNAVAILABLE"
    assert ready["constraints"]["writeback"] == "DISABLED"
    assert ready["constraints"]["mode"] == "READ_ONLY"
    assert is_seed_store(db, store.id) is True

    row = db.execute(select(PlatformConnection).where(PlatformConnection.store_id == store.id)).scalar_one()
    assert row.connector_mode == "human_paste"
    assert row.status == "seed_ready"


def test_seed_store_blocks_writeback_and_mock_unlock() -> None:
    db = _session()
    store = _store(db)
    open_seed_store(db, store, authorizer="店主王先生")
    db.commit()

    try:
        assert_writeback_allowed(db, store.id)
        raise AssertionError("writeback must be disabled")
    except SeedStoreError as exc:
        assert exc.code == WRITEBACK_DISABLED

    item = ClosedLoopItem(
        store_id=store.id,
        fingerprint="seed-writeback",
        title="改标题",
        status="now",
        action_type="change_title",
        object_name="招牌饭",
        pack_json="{}",
    )
    db.add(item)
    db.flush()
    try:
        execute_confirmed_writeback(db, store.id, item, {"copy_text": "改标题"})
        raise AssertionError("execute writeback must fail")
    except WritePermissionError as exc:
        assert WRITEBACK_DISABLED in str(exc)

    try:
        open_test_store_access(db, store)
        raise AssertionError("mock unlock must fail on seed store")
    except ValueError as exc:
        assert "Mock" in str(exc) or "种子店" in str(exc)


def test_seed_day0_official_report_stays_evidence_only() -> None:
    db = _session()
    store = _store(db)
    open_seed_store(db, store, authorizer="店主王先生")
    db.commit()

    result = ingest_reconciliation(
        db,
        store_id=store.id,
        platform="meituan",
        official_rows=[{"day": date.today().isoformat(), "orders": 42, "gmv": 1680, "merchant_revenue": 1200, "refund": 0}],
        collector_rows=None,
        acquisition_mode="FILE_IMPORT",
        baseline_only=True,
    )
    assert result["entered_storestate"] is False
    assert result["baseline_only"] is True
    assert result["day0_verdict"] == "DAY0_PASS_WITH_LIMITS"
    assert result["day0_audit"]["merchant_revenue"] == 1200
    assert result["day0_audit"]["MetricDefinitionVersion"]["merchant_revenue"] == "UNKNOWN"
    assert result["day0_audit"]["raw_report_hash"]

    row = db.get(ShopFunnelDaily, (store.id, date.today()))
    assert row is None
    state = build_store_state(db, store.id, days=7)
    assert state is not None
    assert (state.kpis["orders"].observed_value or 0) != 42

    again = seed_store_readiness(db, store.id)
    assert again["day0_verdict"] == "DAY0_PASS_WITH_LIMITS"
    assert again["can_promote_truth"] is False
    assert again["data_as_01"]["day0_runs"] >= 1


def test_day0_pass_requires_four_definitions_and_still_not_production() -> None:
    db = _session()
    store = _store(db)
    open_seed_store(db, store, authorizer="店主王先生")
    db.commit()
    day = date.today().isoformat()
    result = ingest_reconciliation(
        db,
        store_id=store.id,
        platform="meituan",
        official_rows=[{"day": day, "orders": 42, "gmv": 1680, "merchant_revenue": 1200, "refund": 0}],
        collector_rows=None,
        acquisition_mode="FILE_IMPORT",
        baseline_only=True,
        report_date=day,
        metric_definitions=[
            {"metric": "order_count", "definition_version": "v1", "time_basis": "order_created_at"},
            {"metric": "gross_gmv", "definition_version": "v1", "time_basis": "order_created_at"},
            {"metric": "merchant_revenue", "definition_version": "v1", "time_basis": "settlement_day", "fee_policy": ["platform_commission"]},
            {"metric": "refund_amount", "definition_version": "v1", "time_basis": "refund_created_at"},
        ],
    )
    assert result["day0_verdict"] == "DAY0_PASS"
    assert result["entered_storestate"] is False
    assert seed_store_readiness(db, store.id)["can_promote_truth"] is False


def test_seed_store_rejects_missing_authorizer_and_non_meituan() -> None:
    db = _session()
    store = _store(db, platform="eleme")
    try:
        open_seed_store(db, store, authorizer="店主")
        raise AssertionError("non-meituan must be rejected")
    except SeedStoreError as exc:
        assert exc.code == "PLATFORM_LOCKED"

    meituan = _store(db)
    try:
        open_seed_store(db, meituan, authorizer="  ")
        raise AssertionError("blank authorizer must be rejected")
    except SeedStoreError as exc:
        assert exc.code == "AUTHORIZATION_REQUIRED"
