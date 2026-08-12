"""手机连接码：落库，支持多 worker。"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.settings import ConnectCode, PlatformConnection

logger = logging.getLogger(__name__)

_EXPIRE_SECONDS = 900


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_payload(row: ConnectCode) -> dict[str, Any]:
    now = _utcnow()
    expires_at = row.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    status = row.status
    remaining = 0
    if status == "pending" and expires_at is not None:
        remaining = max(0, int((expires_at - now).total_seconds()))
        if remaining <= 0:
            status = "expired"
    return {
        "code": row.code,
        "store_id": row.store_id,
        "platform": row.platform,
        "status": status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "connected_at": row.connected_at.isoformat() if row.connected_at else None,
        "expires_in_seconds": remaining,
    }


def get_connect_code(db: Session, store_id: str, code: str) -> dict[str, Any] | None:
    row = db.execute(
        select(ConnectCode).where(ConnectCode.code == code, ConnectCode.store_id == store_id)
    ).scalar_one_or_none()
    if row is None:
        return None
    return _to_payload(row)


def create_connect_code(db: Session, store_id: str, platform: str) -> dict[str, Any]:
    now = _utcnow()
    code = secrets.token_hex(3).upper()
    while db.execute(select(ConnectCode.id).where(ConnectCode.code == code)).scalar_one_or_none():
        code = secrets.token_hex(3).upper()
    row = ConnectCode(
        code=code,
        store_id=store_id,
        platform=platform,
        status="pending",
        expires_at=now + timedelta(seconds=_EXPIRE_SECONDS),
    )
    db.add(row)

    connection = db.execute(
        select(PlatformConnection).where(
            PlatformConnection.store_id == store_id,
            PlatformConnection.platform == platform,
        )
    ).scalar_one_or_none()
    if connection is None:
        connection = PlatformConnection(
            store_id=store_id,
            platform=platform,
            status="pending",
            connector_mode="mobile",
        )
        db.add(connection)
    else:
        connection.status = "pending"
        connection.connector_mode = "mobile"
        db.add(connection)
    db.commit()
    db.refresh(row)
    return _to_payload(row)


def confirm_connect_code(db: Session, store_id: str, code: str, store) -> dict[str, Any]:
    row = db.execute(
        select(ConnectCode).where(ConnectCode.code == code, ConnectCode.store_id == store_id)
    ).scalar_one_or_none()
    if row is None:
        return {"error": "not_found"}
    live = _to_payload(row)
    if live.get("status") == "expired":
        return {"error": "expired"}

    now = _utcnow()
    row.status = "connected"
    row.connected_at = now
    platform = row.platform or "外卖平台"
    connection = db.execute(
        select(PlatformConnection).where(
            PlatformConnection.store_id == store_id,
            PlatformConnection.platform == platform,
        )
    ).scalar_one_or_none()
    if connection is None:
        connection = PlatformConnection(store_id=store_id, platform=platform)
        db.add(connection)
    connection.status = "connected"
    connection.connector_mode = connection.connector_mode or "mobile"
    connection.connected_at = now
    connection.last_error = None
    db.add(connection)
    db.add(row)
    db.commit()

    try:
        from app.services.platform_sync import sync_store_platform

        mode = connection.connector_mode if connection.connector_mode in {"mock", "http"} else "mock"
        sync_store_platform(db, store, platform, mode=mode)
        connection.status = "connected"
        connection.last_sync_at = _utcnow()
        db.add(connection)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("platform sync after connect confirm failed: %s", exc)
        db.rollback()
        connection = db.execute(
            select(PlatformConnection).where(
                PlatformConnection.store_id == store_id,
                PlatformConnection.platform == platform,
            )
        ).scalar_one_or_none()
        if connection is not None:
            connection.status = "connected"
            connection.last_error = str(exc)[:500]
            db.add(connection)
            db.commit()

    db.refresh(row)
    return {"ok": True, "link": _to_payload(row)}
