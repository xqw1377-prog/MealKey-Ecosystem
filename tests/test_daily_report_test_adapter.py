"""TEST-ADAPTER-01 acceptance: partial daily-report fixture, never Production Truth."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.models.entities import Merchant, ShopFunnelDaily, Store
from app.models.settings import PlatformConnection
from app.services.action_capability import BLOCKED_NOT_IMPLEMENTED
from app.services.authorized_session_connector import AuthorizedSessionConnector
from app.services.connector_mode import CONFIGURATION_ERROR, ConnectorModeError, assert_mode_allowed
from app.services.daily_report_test_connector import (
    ADAPTER_ID,
    CONNECTOR_KEY,
    DailyReportTestConnector,
    DailyReportTestError,
    PROVENANCE,
    SOURCE_NAME,
    UNAVAILABLE,
    UNKNOWN,
    assert_daily_report_test_allowed,
    is_registered_production_connector,
    snapshot_source_is_production_truth,
)
from app.services.platform_connectors import SUPPORTED_PLATFORMS, post_platform_write
from app.services.platform_sync import apply_platform_snapshot
from app.services.platform_write import WritePermissionError, resolve_connector
from app.services.truth_resolution import (
    excluded_from_production_truth,
    is_production_truth_source,
    may_write_funnel_truth,
    production_funnel_clause,
)


RATIO_ONLY_RECORD = {
    "id": 437,
    "store_id": "scm8_test_store",
    "store_name": "测试店（高新店）",
    "platform": "meituan",
    "record_date": "2026-08-18",
    "promotion_fee": 0,
    "region_rank": 30,
    "store_rating": 4.2,
    "store_score": 99.2,
    "exposure": 2611,
    "entry_rate": 8.4,
    "order_rate": 27.4,
    "bad_review_count": 3,
    "bad_review_rate": 12.5,
    "repurchase_rate": 12.2,
    "source": "mobile",
}


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _store(db: Session) -> Store:
    merchant = Merchant(name="日报夹具商户")
    db.add(merchant)
    db.flush()
    store = Store(merchant_id=merchant.id, name="日报夹具店", city="成都", platform="meituan")
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def _enable(monkeypatch, *, env: str = "test") -> None:
    monkeypatch.setattr(settings, "app_env", env)
    monkeypatch.setattr(settings, "daily_report_test_enabled", True)
    monkeypatch.setattr(settings, "daily_report_test_base_url", "http://daily-report-test.local")


def _connector(monkeypatch, records=None) -> DailyReportTestConnector:
    _enable(monkeypatch)
    payload = {"records": records if records is not None else [RATIO_ONLY_RECORD], "total": 1, "page": 1, "page_size": 1}

    def http_get(url: str) -> dict:
        assert "49.234" not in url
        return payload

    return DailyReportTestConnector(http_get=http_get, base_url="http://daily-report-test.local")


def test_canonical_facts_stay_unknown_and_unavailable(monkeypatch) -> None:
    connector = _connector(monkeypatch)
    snapshot = connector.normalize([RATIO_ONLY_RECORD])

    assert snapshot.source == SOURCE_NAME
    assert snapshot.environment == "test"
    assert snapshot.truth_eligible is False
    assert snapshot.writeback == "disabled"
    assert snapshot.provenance == PROVENANCE
    assert snapshot.platform == "meituan_like"

    for name in ("impressions", "visits", "orders", "gmv"):
        assert snapshot.fact_status(name) == UNKNOWN
        assert snapshot.fact_value(name) is None
    for name in ("menu_items", "reviews", "competitors"):
        assert snapshot.fact_status(name) == UNAVAILABLE
        assert snapshot.fact_value(name) is None

    platform = snapshot.to_platform_snapshot()
    assert platform.daily_metrics == []
    assert platform.menu_items == []
    assert platform.reviews == []
    assert platform.synthetic is True


def test_ratio_only_input_does_not_invent_absolutes(monkeypatch) -> None:
    connector = _connector(monkeypatch)
    snapshot = connector.normalize([RATIO_ONLY_RECORD])

    invented_visits = 2611 * 8.4 / 100.0
    invented_orders = invented_visits * 27.4 / 100.0
    invented_gmv = invented_orders * 38.5

    assert snapshot.fact_value("impressions") != 2611
    assert snapshot.fact_value("impressions") is None
    assert snapshot.fact_value("visits") not in {invented_visits, round(invented_visits), int(invented_visits)}
    assert snapshot.fact_value("orders") not in {invented_orders, round(invented_orders), int(invented_orders)}
    assert snapshot.fact_value("gmv") not in {invented_gmv, round(invented_gmv, 2)}

    extras = snapshot.extras
    assert extras["exposure"] == 2611
    assert extras["entry_rate"] == 8.4
    assert extras["order_rate"] == 27.4
    assert extras["store_rating"] == 4.2
    assert extras["bad_review_count"] == 3

    state = connector.project_store_state(snapshot, store_id="s-test")
    for key in ("orders", "gmv", "impressions"):
        metric = state.kpis[key]
        assert metric.value is None
        assert metric.observed_value is None
        assert metric.delta_pct is None
        assert (metric.confidence or 0) == 0
    assert state.data_coverage.orders_observed is False
    assert state.profit.data_quality == "missing"


def test_explicit_orders_stay_source_extra_not_canonical(monkeypatch) -> None:
    record = dict(RATIO_ONLY_RECORD)
    record["orders"] = 88
    record["gmv"] = 3200.0
    record["visits"] = 210
    connector = _connector(monkeypatch)
    snapshot = connector.normalize([record])
    assert snapshot.extras["orders"] == 88
    assert snapshot.extras["gmv"] == 3200.0
    assert snapshot.fact_status("orders") == UNKNOWN
    assert snapshot.fact_status("gmv") == UNKNOWN
    assert snapshot.fact_status("impressions") == UNKNOWN
    assert snapshot.fact_status("visits") == "OBSERVED"
    assert snapshot.fact_value("visits") == 210.0


def test_partial_state_runs_poie_without_treating_unknown_as_zero(monkeypatch) -> None:
    connector = _connector(monkeypatch)
    result = connector.run(store_id="s-test", records=[RATIO_ONLY_RECORD])

    assert result["truth_eligible"] is False
    assert result["production_truth"] is False
    assert result["provenance"] == PROVENANCE
    assert result["writeback"] == "disabled"

    events = result["events"]
    types = {e.event_type for e in events.events}
    assert "RATING_DROP" in types
    assert "ORDER_DROP" not in types
    assert "CVR_DROP" not in types
    for event in events.events:
        if event.affected_metric in {"orders", "gmv"}:
            assert event.estimated_impact_amount is None

    poie = result["poie"]
    assert poie.candidates_total >= 1
    surfaced = list(poie.ops_queue.need_you) + list(poie.ops_queue.working)
    assert surfaced or poie.candidates_total >= 1

    odo_facts = result["odo_facts"]
    assert "orders" not in odo_facts
    assert odo_facts.get("orders") not in {0, 0.0}
    assert odo_facts.get("recent_bad_review_count") == 3
    assert result["odo"] is not None
    assert result["odo"]["code"] == "URGENT_REVIEWS"


def test_prod_rejects_unauthenticated_connector(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "daily_report_test_enabled", True)
    monkeypatch.setattr(settings, "daily_report_test_base_url", "http://daily-report-test.local")

    try:
        assert_daily_report_test_allowed()
        raise AssertionError("prod must reject TEST-ADAPTER-01")
    except ConnectorModeError as exc:
        assert exc.code == CONFIGURATION_ERROR
        assert "生产" in str(exc)

    try:
        assert_mode_allowed("daily_report_test", explicit=True)
        raise AssertionError("prod must reject daily_report_test mode")
    except ConnectorModeError as exc:
        assert exc.code == CONFIGURATION_ERROR

    connector = DailyReportTestConnector(http_get=lambda url: {"records": [RATIO_ONLY_RECORD]})
    try:
        connector.fetch_records()
        raise AssertionError("prod fetch must fail closed")
    except DailyReportTestError as exc:
        assert exc.code == CONFIGURATION_ERROR


def test_default_off_even_in_dev(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "daily_report_test_enabled", False)
    try:
        assert_daily_report_test_allowed()
        raise AssertionError("must stay disabled by default")
    except DailyReportTestError as exc:
        assert exc.code == CONFIGURATION_ERROR


def test_naming_registry_and_writeback_disabled(monkeypatch) -> None:
    connector = _connector(monkeypatch)
    assert connector.__class__.__name__ == "DailyReportTestConnector"
    assert connector.source_connector == "daily_report_test"
    assert connector.acquisition_mode == PROVENANCE
    assert connector.acquisition_mode != "AUTHORIZED_SESSION"
    assert not isinstance(connector, AuthorizedSessionConnector)
    assert is_registered_production_connector() is False
    assert CONNECTOR_KEY not in {row["key"] for row in SUPPORTED_PLATFORMS}
    assert "meituan" not in {connector.source_connector, connector.connector_key}

    snapshot = connector.normalize([RATIO_ONLY_RECORD])
    assert snapshot.platform != "meituan"
    assert snapshot_source_is_production_truth(snapshot) is False
    assert is_production_truth_source(snapshot.source) is False
    assert excluded_from_production_truth("test_only") is True
    assert excluded_from_production_truth("external_daily_report_test") is True
    assert may_write_funnel_truth("authorized_session", "test_only") is False

    blocked = connector.writeback(op="update_product_title")
    assert blocked["ok"] is False
    assert blocked["writeback"] == "disabled"
    assert blocked["code"] == BLOCKED_NOT_IMPLEMENTED
    assert blocked.get("executed") is False

    try:
        post_platform_write(
            "update_product_title",
            platform="meituan_like",
            store_id="s-test",
            payload={"object_name": "盖饭", "new_title": "新标题"},
            mode="daily_report_test",
        )
        raise AssertionError("writeback must be blocked")
    except (ValueError, ConnectorModeError) as exc:
        assert "disabled" in str(exc).lower() or BLOCKED_NOT_IMPLEMENTED in str(exc)

    db = _session()
    store = _store(db)
    db.add(
        PlatformConnection(
            store_id=store.id,
            platform="meituan_like",
            status="connected",
            connector_mode="daily_report_test",
        )
    )
    db.commit()
    try:
        resolve_connector(db, store.id)
        raise AssertionError("resolve_connector must refuse test-adapter writeback")
    except WritePermissionError as exc:
        assert "TEST-ADAPTER-01" in str(exc)


def test_apply_snapshot_does_not_write_invented_funnel(monkeypatch) -> None:
    connector = _connector(monkeypatch)
    snapshot = connector.normalize([RATIO_ONLY_RECORD])
    db = _session()
    store = _store(db)
    result = apply_platform_snapshot(db, store, snapshot.to_platform_snapshot())
    db.commit()
    assert result["metric_days"] == 0
    assert result["menu_upserted"] == 0
    assert result["reviews_upserted"] == 0
    rows = db.execute(select(ShopFunnelDaily).where(ShopFunnelDaily.store_id == store.id)).scalars().all()
    assert rows == []


def test_test_only_funnel_is_query_invisible(monkeypatch) -> None:
    db = _session()
    store = _store(db)
    day = date.today() - timedelta(days=1)
    db.add(
        ShopFunnelDaily(
            store_id=store.id,
            day=day,
            orders=99,
            gmv=9900,
            impressions=2611,
            data_source="external_daily_report_test",
        )
    )
    db.commit()
    visible = db.execute(
        select(ShopFunnelDaily).where(
            ShopFunnelDaily.store_id == store.id,
            production_funnel_clause(ShopFunnelDaily.data_source),
        )
    ).scalars().all()
    assert visible == []

    from app.services.store_state import build_store_state

    state = build_store_state(db, store.id, days=7)
    assert state is not None
    assert (state.kpis["orders"].observed_value or 0) != 99
    assert (state.kpis["orders"].confidence or 0) == 0


def test_fetch_records_uses_injected_http_not_live_host(monkeypatch) -> None:
    seen: list[str] = []

    def http_get(url: str) -> dict:
        seen.append(url)
        assert "49.234.54.78" not in url
        return {"records": [RATIO_ONLY_RECORD], "total": 1, "page": 1, "page_size": 1}

    _enable(monkeypatch)
    connector = DailyReportTestConnector(http_get=http_get, base_url="http://daily-report-test.local")
    rows = connector.fetch_records(page_size=3)
    assert len(rows) == 1
    assert rows[0]["store_id"] == "scm8_test_store"
    assert seen
    assert seen[0].startswith("http://daily-report-test.local/api/records")
    assert ADAPTER_ID == "TEST-ADAPTER-01"
