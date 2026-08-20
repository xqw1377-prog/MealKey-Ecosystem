from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Merchant, Store
from app.models.settings import PlatformConnection
from app.services.daily_report_test_connector import (
    ADAPTER_ID,
    CONNECTOR_KEY,
    DailyReportTestConnector,
    PROVENANCE,
    SOURCE_NAME,
)

_LOCAL_STORE_KEY_PREFIX = "daily_report_test:"
_PREVIEW_FIELDS = (
    "id",
    "store_id",
    "store_code",
    "store_name",
    "platform",
    "record_date",
    "source",
    "promotion_fee",
    "exposure",
    "entry_rate",
    "order_rate",
    "repurchase_rate",
    "store_rating",
    "store_score",
    "region_rank",
    "bad_review_count",
    "bad_review_rate",
    "main_issues",
    "created_at",
    "updated_at",
)


def _loads_meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _record_sort_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("record_date") or ""),
        str(record.get("updated_at") or ""),
        str(record.get("created_at") or ""),
    )


def _trim_record(record: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in _PREVIEW_FIELDS:
        value = record.get(field)
        if value is not None:
            payload[field] = value
    return payload


def _remote_store_id(record: dict[str, Any]) -> str:
    return str(record.get("store_id") or record.get("store_code") or record.get("store_name") or "").strip()


def _normalize_platform(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    return key or "external_test"


def _local_store_key(remote_store_id: str) -> str:
    return f"{_LOCAL_STORE_KEY_PREFIX}{remote_store_id}"


def _ensure_store(
    db: Session,
    *,
    remote_store_id: str,
    store_name: str,
    primary_platform: str,
) -> tuple[Store, bool]:
    local_key = _local_store_key(remote_store_id)
    store = db.execute(
        select(Store).where(Store.platform_store_key == local_key).order_by(Store.created_at.desc())
    ).scalar_one_or_none()
    if store is not None:
        if store_name and store.name != store_name:
            store.name = store_name
        if primary_platform and store.platform != primary_platform:
            store.platform = primary_platform
        if not store.primary_audience:
            store.primary_audience = "测试数据"
        if not store.primary_pain:
            store.primary_pain = "TEST_ONLY 数据预览"
        db.add(store)
        db.flush()
        return store, False

    merchant = Merchant(
        name=store_name or remote_store_id,
        brand_name=store_name or remote_store_id,
        category="测试数据",
    )
    db.add(merchant)
    db.flush()

    store = Store(
        merchant_id=merchant.id,
        name=store_name or remote_store_id,
        platform=primary_platform,
        platform_store_key=local_key,
        primary_audience="测试数据",
        primary_pain="TEST_ONLY 数据预览",
        status="active",
    )
    db.add(store)
    db.flush()
    return store, True


def import_daily_report_test_records(
    db: Session,
    *,
    connector: DailyReportTestConnector | None = None,
    page_size: int = 100,
    page: int = 1,
    remote_store_id: str | None = None,
    max_records_per_platform: int = 12,
) -> dict[str, Any]:
    fixture = connector or DailyReportTestConnector()
    records = fixture.fetch_records(page_size=page_size, store_id=remote_store_id, page=page)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        key = _remote_store_id(row)
        if key:
            grouped[key].append(row)

    now = datetime.now(timezone.utc)
    created_stores = 0
    created_connections = 0
    imported: list[dict[str, Any]] = []

    for remote_id, store_records in sorted(grouped.items()):
        ordered = sorted(store_records, key=_record_sort_key, reverse=True)
        latest = ordered[0]
        store_name = str(latest.get("store_name") or remote_id).strip() or remote_id
        store, created = _ensure_store(
            db,
            remote_store_id=remote_id,
            store_name=store_name,
            primary_platform=_normalize_platform(latest.get("platform")),
        )
        if created:
            created_stores += 1

        platform_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in ordered:
            platform_rows[_normalize_platform(row.get("platform"))].append(row)

        connections_payload: list[dict[str, Any]] = []
        for platform, rows in sorted(platform_rows.items()):
            connection = db.execute(
                select(PlatformConnection).where(
                    PlatformConnection.store_id == store.id,
                    PlatformConnection.platform == platform,
                )
            ).scalar_one_or_none()
            if connection is None:
                connection = PlatformConnection(store_id=store.id, platform=platform)
                db.add(connection)
                db.flush()
                created_connections += 1
            latest_platform = rows[0]
            preview = [_trim_record(row) for row in rows[: max(1, int(max_records_per_platform))]]
            meta = _loads_meta(connection.meta_json)
            meta.update(
                {
                    "source": "daily_report_test_import",
                    "source_connector": SOURCE_NAME,
                    "adapter": ADAPTER_ID,
                    "test_only": True,
                    "truth_eligible": False,
                    "production_truth": False,
                    "writeback": "disabled",
                    "provenance": PROVENANCE,
                    "remote_store_id": remote_id,
                    "remote_store_code": latest_platform.get("store_code"),
                    "remote_store_name": store_name,
                    "record_count": len(rows),
                    "latest_record_date": latest_platform.get("record_date"),
                    "latest_record": preview[0] if preview else {},
                    "records": preview,
                    "imported_at": now.isoformat(),
                }
            )
            connection.status = "connected"
            connection.external_store_id = remote_id
            connection.connector_mode = CONNECTOR_KEY
            connection.last_sync_at = now
            connection.last_error = None
            connection.meta_json = json.dumps(meta, ensure_ascii=False)
            db.add(connection)
            connections_payload.append(
                {
                    "platform": platform,
                    "record_count": len(rows),
                    "latest_record_date": latest_platform.get("record_date"),
                    "latest_record": preview[0] if preview else {},
                }
            )

        db.add(store)
        imported.append(
            {
                "store_id": store.id,
                "store_name": store.name,
                "platform_store_key": store.platform_store_key,
                "remote_store_id": remote_id,
                "connections": connections_payload,
            }
        )

    db.flush()
    return {
        "page": page,
        "page_size": page_size,
        "records_fetched": len(records),
        "stores_imported": len(imported),
        "stores_created": created_stores,
        "connections_created": created_connections,
        "stores": imported,
    }


def list_daily_report_test_stores(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(PlatformConnection, Store)
        .join(Store, Store.id == PlatformConnection.store_id)
        .where(PlatformConnection.connector_mode == CONNECTOR_KEY)
        .order_by(Store.created_at.desc(), PlatformConnection.platform.asc())
    ).all()
    grouped: dict[str, dict[str, Any]] = {}
    for connection, store in rows:
        meta = _loads_meta(connection.meta_json)
        payload = grouped.setdefault(
            store.id,
            {
                "store_id": store.id,
                "store_name": store.name,
                "merchant_id": store.merchant_id,
                "platform_store_key": store.platform_store_key,
                "primary_platform": store.platform,
                "remote_store_id": meta.get("remote_store_id") or connection.external_store_id,
                "remote_store_name": meta.get("remote_store_name") or store.name,
                "connections": [],
            },
        )
        payload["connections"].append(
            {
                "platform": connection.platform,
                "status": connection.status,
                "connector_mode": connection.connector_mode,
                "external_store_id": connection.external_store_id,
                "record_count": meta.get("record_count") or 0,
                "latest_record_date": meta.get("latest_record_date"),
                "latest_record": meta.get("latest_record") or {},
                "records": meta.get("records") or [],
                "truth_eligible": bool(meta.get("truth_eligible")),
                "provenance": meta.get("provenance"),
                "writeback": meta.get("writeback"),
            }
        )
    stores = list(grouped.values())
    for item in stores:
        latest_dates = [str(conn.get("latest_record_date") or "") for conn in item["connections"]]
        item["latest_record_date"] = max(latest_dates) if latest_dates else None
        item["record_count"] = sum(int(conn.get("record_count") or 0) for conn in item["connections"])
        item["platforms"] = [str(conn.get("platform") or "") for conn in item["connections"]]
    stores.sort(key=lambda row: (str(row.get("latest_record_date") or ""), str(row.get("store_name") or "")), reverse=True)
    return stores

