"""PRE-PROD-GATE-01 P0-5: OAuth token 永远不出现在普通 API 响应里。

锁定 Invariant #2：Secret 永远不通过普通业务 API 返回。
即便 DB 里曾有明文 token，迁移后 public_platform_link 也只能返回状态布尔值/credential_ref，
不得泄露 access_token / refresh_token / id_token / client_secret 原文。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.models.settings import PlatformConnection
from app.services.credential_store import (
    public_platform_link,
    public_oauth_fields,
    migrate_legacy_oauth_tokens,
)

# 原始 token 值的识别标记——若任何一个出现在 public 响应里即判定泄露
_SECRET_KEYS = ("access_token", "refresh_token", "id_token", "client_secret")
_LEAK_MARKERS = {
    "access_token": "ak_live_leak_canary_123",
    "refresh_token": "rt_live_leak_canary_456",
    "id_token": "id_live_leak_canary_789",
    "client_secret": "cs_live_leak_canary_000",
}


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _legacy_connection(db: Session) -> PlatformConnection:
    """构造一个 meta_json 里残留明文 OAuth token 的旧连接。"""
    row = PlatformConnection(
        store_id="s1",
        platform="meituan",
        status="connected",
        connector_mode="http",
        external_store_id="mt_123",
        auth_expires_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
        meta_json=json.dumps({
            "oauth": {
                "access_token": _LEAK_MARKERS["access_token"],
                "refresh_token": _LEAK_MARKERS["refresh_token"],
                "id_token": _LEAK_MARKERS["id_token"],
                "token_type": "bearer",
                "scope": "order.read shop.read",
                "credential_status": "ACTIVE",
            },
            "oauth_meituan_client_secret": _LEAK_MARKERS["client_secret"],
        }),
    )
    db.add(row)
    db.commit()
    return row


def test_public_platform_link_strips_all_token_fields_after_migration():
    db = _session()
    row = _legacy_connection(db)
    # 迁移把明文 token 搬到 credential_ref
    migrated = migrate_legacy_oauth_tokens(db, row)
    assert migrated is True
    public = public_platform_link(row, db=db)
    # public 只能含状态字段
    assert set(public.keys()) == {
        "platform", "status", "connector_mode", "external_store_id",
        "last_sync_at", "last_error", "connected", "expires_at",
        "scopes", "credential_status", "rotate_recommended",
    }
    # 任何原始 token 值不得出现在响应里
    blob = json.dumps(public, ensure_ascii=False)
    for marker in _LEAK_MARKERS.values():
        assert marker not in blob, f"token leaked into public response: {marker}"


def test_public_oauth_fields_never_exposes_token_keys():
    oauth = {
        "access_token": _LEAK_MARKERS["access_token"],
        "refresh_token": _LEAK_MARKERS["refresh_token"],
        "id_token": _LEAK_MARKERS["id_token"],
        "scope": "order.read",
        "credential_status": "ACTIVE",
        "rotate_recommended": False,
    }
    public = public_oauth_fields(oauth, expires_at="2026-12-31T00:00:00+00:00")
    # 不得含任何 _SECRET_KEYS
    for key in _SECRET_KEYS:
        assert key not in public, f"public_oauth_fields leaked key: {key}"
    assert public["credential_status"] == "ACTIVE"
    assert public["scopes"] == ["order.read"]


def test_legacy_plaintoken_not_in_public_even_without_migration_call():
    """即便调用方忘记显式迁移，public_platform_link(db=...) 内部也会迁移。"""
    db = _session()
    row = _legacy_connection(db)
    public = public_platform_link(row, db=db)
    blob = json.dumps(public, ensure_ascii=False)
    for marker in _LEAK_MARKERS.values():
        assert marker not in blob, f"token leaked when migration was implicit: {marker}"
