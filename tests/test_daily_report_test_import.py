from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal
from app.main import app
from app.models.entities import ShopFunnelDaily, Store
from app.models.settings import PlatformConnection
from app.services.daily_report_test_connector import DailyReportTestConnector
from app.services.daily_report_test_import import (
    import_daily_report_test_records,
    list_daily_report_test_stores,
)


RECORDS = [
    {
        "id": 449,
        "store_id": "scm8_import_store",
        "store_name": "米熊（高新店）",
        "store_code": "0001",
        "platform": "eleme",
        "record_date": "2026-08-19",
        "promotion_fee": 0,
        "store_rating": 4.7,
        "exposure": 2466,
        "entry_rate": 7.6,
        "order_rate": 30.9,
        "repurchase_rate": 12.7,
        "bad_review_count": 0,
        "source": "mobile",
        "updated_at": "2026-08-19 21:07:37",
    },
    {
        "id": 446,
        "store_id": "scm8_import_store",
        "store_name": "米熊（高新店）",
        "store_code": "0001",
        "platform": "meituan",
        "record_date": "2026-08-19",
        "promotion_fee": 0,
        "store_rating": 4.6,
        "exposure": 5128,
        "entry_rate": 6.9,
        "order_rate": 34.8,
        "repurchase_rate": 14.2,
        "bad_review_count": 0,
        "source": "mobile",
        "updated_at": "2026-08-19 21:05:20",
    },
    {
        "id": 437,
        "store_id": "scm8_import_store",
        "store_name": "米熊（高新店）",
        "store_code": "0001",
        "platform": "eleme",
        "record_date": "2026-08-18",
        "promotion_fee": 0,
        "store_rating": 4.2,
        "exposure": 2611,
        "entry_rate": 8.4,
        "order_rate": 27.4,
        "repurchase_rate": 12.2,
        "bad_review_count": 3,
        "source": "mobile",
        "updated_at": "2026-08-18 21:07:37",
    },
]


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _enable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "daily_report_test_enabled", True)
    monkeypatch.setattr(settings, "daily_report_test_base_url", "http://daily-report-test.local")


def _connector(monkeypatch, records=None) -> DailyReportTestConnector:
    _enable(monkeypatch)
    payload = {"records": records if records is not None else RECORDS, "total": 3, "page": 1, "page_size": 100}

    def http_get(_url: str) -> dict:
        return payload

    return DailyReportTestConnector(http_get=http_get, base_url="http://daily-report-test.local")


def test_import_creates_local_store_and_connections_without_funnel(monkeypatch) -> None:
    db = _session()
    result = import_daily_report_test_records(db, connector=_connector(monkeypatch), page_size=100)
    db.commit()

    assert result["records_fetched"] == 3
    assert result["stores_imported"] == 1
    assert result["stores_created"] == 1
    assert result["connections_created"] == 2

    store = db.execute(select(Store)).scalar_one()
    assert store.name == "米熊（高新店）"
    assert store.platform_store_key == "daily_report_test:scm8_import_store"
    assert store.primary_pain == "TEST_ONLY 数据预览"

    connections = db.execute(select(PlatformConnection).order_by(PlatformConnection.platform.asc())).scalars().all()
    assert [row.platform for row in connections] == ["eleme", "meituan"]
    assert all(row.connector_mode == "daily_report_test" for row in connections)
    assert all(row.status == "connected" for row in connections)
    assert db.execute(select(ShopFunnelDaily)).scalars().all() == []

    preview = list_daily_report_test_stores(db)
    assert len(preview) == 1
    assert preview[0]["record_count"] == 3
    assert preview[0]["latest_record_date"] == "2026-08-19"
    assert preview[0]["platforms"] == ["eleme", "meituan"]


def test_dev_routes_show_imported_test_store(monkeypatch) -> None:
    _enable(monkeypatch)
    with SessionLocal() as db:
        import_daily_report_test_records(db, connector=_connector(monkeypatch), page_size=100)
        db.commit()

    client = TestClient(app)
    response = client.get("/dev/daily-report-test/stores")
    assert response.status_code == 200
    payload = response.json()
    assert payload["stores"]
    first = payload["stores"][0]
    assert first["store_name"] == "米熊（高新店）"
    assert first["remote_store_id"] == "scm8_import_store"
    assert first["record_count"] >= 3

    links = client.get(f"/workspace/stores/{first['store_id']}/platform-links")
    assert links.status_code == 200
    link_payload = links.json()
    test_links = [row for row in link_payload["links"] if row["connector_mode"] == "daily_report_test"]
    assert test_links
    assert test_links[0]["test_preview"]["remote_store_id"] == "scm8_import_store"
    assert test_links[0]["test_preview"]["latest_record"]["store_name"] == "米熊（高新店）"

    html = client.get("/dev/daily-report-test/view")
    assert html.status_code == 200
    assert "日报测试源调试页" in html.text
    assert "米熊（高新店）" in html.text
