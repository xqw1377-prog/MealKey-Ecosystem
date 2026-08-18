"""SEC-PLATFORM-01：把 OAuth token 从业务 meta 挪到 secret setting。

不是统一 Secrets Platform。只堵住：
- PlatformConnection.meta_json 明文 token
- 普通设置 API 回传 token
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.settings import PlatformConnection
from app.services.settings_store import get_setting, upsert_setting

TOKEN_KEYS = ("access_token", "refresh_token", "id_token", "raw")


def credential_ref_for(store_id: str, platform: str) -> str:
    return f"oauth_secret:{store_id}:{platform}"


def _load_meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _oauth_blob(meta: dict[str, Any]) -> dict[str, Any]:
    oauth = meta.get("oauth")
    return oauth if isinstance(oauth, dict) else {}


def put_oauth_secret(db: Session, store_id: str, platform: str, token_payload: dict[str, Any]) -> str:
    ref = credential_ref_for(store_id, platform)
    payload = {
        "access_token": str(token_payload.get("access_token") or ""),
        "refresh_token": str(token_payload.get("refresh_token") or ""),
        "token_type": str(token_payload.get("token_type") or "bearer"),
        "scope": str(token_payload.get("scope") or ""),
        "id_token": str(token_payload.get("id_token") or ""),
    }
    upsert_setting(
        db,
        ref,
        json.dumps(payload, ensure_ascii=False),
        is_secret=True,
        description="OAuth tokens — never expose via business API",
    )
    return ref


def get_oauth_secret(db: Session | None, store_id: str, platform: str) -> dict[str, Any]:
    raw = get_setting(credential_ref_for(store_id, platform), db)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def has_oauth_secret(db: Session | None, store_id: str, platform: str) -> bool:
    secret = get_oauth_secret(db, store_id, platform)
    return bool(str(secret.get("access_token") or "").strip())


def public_oauth_fields(oauth: dict[str, Any], *, expires_at: Optional[str] = None) -> dict[str, Any]:
    scope = str(oauth.get("scope") or "").strip()
    scopes = [part for part in scope.replace(",", " ").split() if part]
    return {
        "credential_status": oauth.get("credential_status") or None,
        "expires_at": expires_at,
        "scopes": scopes,
        "rotate_recommended": bool(oauth.get("rotate_recommended")),
    }


def migrate_legacy_oauth_tokens(db: Session, row: PlatformConnection) -> bool:
    """把 meta_json 里的明文 token 搬走。已是真实凭据时调用方应 rotate。"""
    meta = _load_meta(row.meta_json)
    oauth = _oauth_blob(meta)
    if not any(oauth.get(key) for key in TOKEN_KEYS):
        return False
    ref = put_oauth_secret(db, row.store_id, row.platform, oauth)
    meta["oauth"] = {
        "credential_ref": ref,
        "credential_status": "ACTIVE",
        "token_type": oauth.get("token_type") or "bearer",
        "scope": oauth.get("scope") or "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "rotate_recommended": True,
    }
    row.meta_json = json.dumps(meta, ensure_ascii=False)
    db.add(row)
    db.flush()
    return True


def load_oauth_credentials(db: Session, store_id: str, platform: str, *, connection: PlatformConnection | None = None) -> dict[str, Any]:
    """仅供服务端 connector 使用。会顺带迁移遗留明文。"""
    row = connection
    if row is not None:
        migrate_legacy_oauth_tokens(db, row)
    secret = get_oauth_secret(db, store_id, platform)
    if secret:
        return secret
    if row is None:
        return {}
    return _oauth_blob(_load_meta(row.meta_json))


def public_platform_link(row: PlatformConnection, *, db: Session | None = None) -> dict[str, Any]:
    if db is not None:
        migrate_legacy_oauth_tokens(db, row)
    meta = _load_meta(row.meta_json)
    oauth = _oauth_blob(meta)
    expires = row.auth_expires_at.isoformat() if row.auth_expires_at else None
    public = public_oauth_fields(oauth, expires_at=expires)
    connected = row.status == "connected" and (
        public["credential_status"] == "ACTIVE"
        or row.connector_mode in {"mock", "http", "mobile"}
        or (db is not None and has_oauth_secret(db, row.store_id, row.platform))
    )
    return {
        "platform": row.platform,
        "status": row.status,
        "connector_mode": row.connector_mode,
        "external_store_id": row.external_store_id,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "last_error": row.last_error,
        "connected": bool(connected),
        "expires_at": expires,
        "scopes": public["scopes"],
        "credential_status": public["credential_status"],
        "rotate_recommended": public["rotate_recommended"],
    }
