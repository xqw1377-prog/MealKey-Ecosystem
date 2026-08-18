from app.db.base import Base
from app.db.session import SessionLocal, engine
import app.models  # noqa: F401

Base.metadata.create_all(bind=engine)

from app.models.entities import Merchant, Store
from app.services.action_registry import build_action_spec
from app.services.authorized_session_connector import AuthorizedSessionConnector
from app.services.data_acquisition_ingest import ingest_reconciliation
from app.services.data_acquisition_loop import declining_series, run_connected_discovery
from app.services.sandbox_golden_path import run_title_golden_path
from app.schemas.data_acquisition import FetchRequest


def _store(db) -> Store:
    merchant = Merchant(name="落地测试店")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="落地测试店", city="北京", platform="meituan")
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def test_authorized_session_fetch_stays_unavailable() -> None:
    result = AuthorizedSessionConnector().fetch(FetchRequest(store_id="any", platform="meituan"))
    assert result.health.status == "UNAVAILABLE"
    assert result.envelopes == []


def test_day0_baseline_does_not_enter_storestate() -> None:
    db = SessionLocal()
    try:
        store = _store(db)
        result = ingest_reconciliation(
            db,
            store_id=store.id,
            platform="meituan",
            official_rows=[{"day": "2026-08-01", "orders": 10, "gmv": 400}],
            baseline_only=True,
        )
        assert result["entered_storestate"] is False
        assert result["baseline_only"] is True
    finally:
        db.close()


def test_discover_real_without_facts_is_no_signal() -> None:
    db = SessionLocal()
    try:
        store = _store(db)
        body = run_connected_discovery(db, store_id=store.id, mode="REAL")
        assert body["status"] == "NO_SIGNAL"
        assert body["reached_candidate_action"] is False
        assert body["executed"] is False
        assert body["production_truth"] is False
    finally:
        db.close()


def test_matched_ingest_then_discover_candidate_without_execute() -> None:
    db = SessionLocal()
    try:
        store = _store(db)
        official, collector = declining_series()
        body = run_connected_discovery(
            db,
            store_id=store.id,
            official_rows=official,
            collector_rows=collector,
            mode="REAL",
        )
        assert body["ingest"]["entered_storestate"] is True
        assert body["orders_delta_pct"] is not None and body["orders_delta_pct"] < -8
        assert any(e["event_type"] == "ORDER_DROP" for e in body["events"])
        assert body["candidate_action"]
        assert body["reached_candidate_action"] is True
        assert body["executed"] is False
        assert body["production_truth"] is True
    finally:
        db.close()


def test_sandbox_golden_path_is_l0() -> None:
    db = SessionLocal()
    try:
        body = run_title_golden_path(db, world_id="landed")
        assert body["read_back_ok"] is True
        assert body["control_unchanged"] is True
        assert body["contrast"]["evidence_grade"] == "L0_RESEARCH"
        assert body["may_authorize"] is False
        assert body["production_truth"] is False
    finally:
        db.close()


def test_growth_primitives_are_registered_but_not_executable() -> None:
    from app.services.action_capability import ActionCapabilityError, assert_action_executable

    spec = build_action_spec("issue_repurchase_coupon", reason="复购下降")
    assert spec["type"] == "COUPON"
    assert spec["execution_method"] == "not_implemented"
    assert spec["execution_capability"] == "NOT_IMPLEMENTED"
    assert spec["profit_guard"] is True
    assert spec["attribution_method"] == "incremental_if_control_else_observed"
    try:
        assert_action_executable("issue_repurchase_coupon")
        raise AssertionError("coupon must be blocked")
    except ActionCapabilityError as exc:
        assert exc.code == "BLOCKED_NOT_IMPLEMENTED"
