"""平台 OAuth 授权实现。

V1 目标：
1. 设置页录入 client_id/client_secret/redirect_uri
2. 返回正式授权 URL
3. callback/code -> access_token/refresh_token
4. 持久化到 PlatformConnection，后续可用于真实平台拉数
5. SEC-PLATFORM-01：token 进 secret setting，meta/API 只留 credential_status

说明：
- 平台字段仍需使用商家自己的开放平台配置
- 这里按标准 OAuth 2.0 授权码流程实现；若平台字段名有差异，可在设置里覆盖 URL/scope
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.settings import PlatformConnection
from app.services.copy_humanize import humanize_operator_text
from app.services.credential_store import (
    has_oauth_secret,
    migrate_legacy_oauth_tokens,
    public_oauth_fields,
    put_oauth_secret,
)
from app.services.settings_store import get_setting, set_setting


@dataclass
class OAuthConfig:
    """平台 OAuth 配置。"""
    platform: str  # meituan / eleme
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    auth_url: str = ""  # 授权页 URL
    token_url: str = ""  # 换 token 的 URL
    scope: str = ""  # 授权范围


_OAUTH_CONFIGS: dict[str, OAuthConfig] = {
    "meituan": OAuthConfig(
        platform="meituan",
        auth_url="https://open-erp.meituan.com/oauth/authorize",
        token_url="https://open-erp.meituan.com/oauth/token",
        scope="order_manage menu_manage review_manage ads_manage",
    ),
    "eleme": OAuthConfig(
        platform="eleme",
        auth_url="https://open.ele.me/oauth/authorize",
        token_url="https://open.ele.me/oauth/token",
        scope="order menu review",
    ),
}


def _setting_key(platform: str, suffix: str) -> str:
    return f"oauth_{platform}_{suffix}"


def _load_oauth_config(platform: str) -> Optional[OAuthConfig]:
    base = _OAUTH_CONFIGS.get(platform)
    if base is None:
        return None
    return OAuthConfig(
        platform=platform,
        client_id=str(get_setting(_setting_key(platform, "client_id")) or base.client_id or "").strip(),
        client_secret=str(get_setting(_setting_key(platform, "client_secret")) or base.client_secret or "").strip(),
        redirect_uri=str(get_setting(_setting_key(platform, "redirect_uri")) or base.redirect_uri or "").strip(),
        auth_url=str(get_setting(_setting_key(platform, "auth_url")) or base.auth_url or "").strip(),
        token_url=str(get_setting(_setting_key(platform, "token_url")) or base.token_url or "").strip(),
        scope=str(get_setting(_setting_key(platform, "scope")) or base.scope or "").strip(),
    )


_OAUTH_STATE_TTL_SECONDS = 600  # state 10 分钟过期


def _oauth_signing_secret() -> bytes:
    """state 签名密钥：优先 jwt_secret，其次 api_token。两者都没有 → 拒签（fail-closed）。"""
    from app.core.config import settings

    secret = (settings.jwt_secret or settings.api_token or "").strip()
    if not secret:
        raise RuntimeError("OAuth state signing requires JWT_SECRET or API_TOKEN")
    return f"oauth-state:{secret}".encode("utf-8")


def _sign_state_payload(raw: bytes) -> str:
    import hashlib
    import hmac

    return hmac.new(_oauth_signing_secret(), raw, hashlib.sha256).hexdigest()


def build_oauth_state(platform: str, *, store_id: str = "") -> str:
    """构造带 HMAC 签名 + 过期时间的 state（防伪造/防重放）。"""
    payload = {
        "platform": platform,
        "store_id": store_id or "",
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = _sign_state_payload(raw)
    envelope = json.dumps({"payload": base64.urlsafe_b64encode(raw).decode("ascii"), "sig": signature}).encode("utf-8")
    return base64.urlsafe_b64encode(envelope).decode("ascii")


def parse_oauth_state(state: str) -> dict[str, str]:
    """验签 + 过期校验。签名不符或超时 → 空结果（fail-closed）。"""
    empty = {"platform": "", "store_id": ""}
    try:
        envelope = json.loads(base64.urlsafe_b64decode(state.encode("ascii")).decode("utf-8"))
        raw = base64.urlsafe_b64decode(envelope["payload"].encode("ascii"))
        expected_sig = _sign_state_payload(raw)
        import hmac as _hmac

        if not _hmac.compare_digest(envelope.get("sig", ""), expected_sig):
            return empty
        payload = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001 — 含签名密钥缺失: fail-closed 返回空
        return empty
    if not isinstance(payload, dict):
        return empty
    # 过期校验
    try:
        issued = datetime.fromisoformat(payload.get("issued_at", ""))
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - issued).total_seconds() > _OAUTH_STATE_TTL_SECONDS:
            return empty
    except (ValueError, TypeError):
        return empty
    return {
        "platform": str(payload.get("platform") or ""),
        "store_id": str(payload.get("store_id") or ""),
    }


def get_oauth_url(platform: str, state: str = "") -> Optional[str]:
    config = _load_oauth_config(platform)
    if config is None or not config.client_id or not config.redirect_uri or not config.auth_url:
        return None
    params = urlencode({
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": config.scope,
        "state": state or platform,
    })
    return f"{config.auth_url}?{params}"


def exchange_code_for_token(platform: str, code: str) -> Optional[dict]:
    config = _load_oauth_config(platform)
    if config is None or not config.client_id or not config.client_secret or not config.redirect_uri or not config.token_url:
        return None
    payload = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": config.redirect_uri,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        config.token_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="ignore")
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ValueError(f"OAuth 换票失败：{exc.code} {detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"OAuth 换票失败：{exc.reason}") from exc
    data = _parse_oauth_payload(body, content_type)
    if not data.get("access_token"):
        raise ValueError("平台没有返回 access_token。")
    return data


def refresh_token(platform: str, refresh_token: str) -> Optional[dict]:
    config = _load_oauth_config(platform)
    if config is None or not config.client_id or not config.client_secret or not config.token_url:
        return None
    payload = urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        config.token_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="ignore")
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ValueError(f"OAuth 刷新失败：{exc.code} {detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"OAuth 刷新失败：{exc.reason}") from exc
    data = _parse_oauth_payload(body, content_type)
    if not data.get("access_token"):
        raise ValueError("平台没有返回新的 access_token。")
    return data


def is_oauth_configured(platform: str) -> bool:
    config = _load_oauth_config(platform)
    return config is not None and bool(config.client_id and config.client_secret and config.redirect_uri)


def configure_oauth(
    platform: str,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> None:
    config = _OAUTH_CONFIGS.get(platform)
    set_setting(_setting_key(platform, "client_id"), client_id, is_secret=False, description=f"{platform} OAuth Client ID")
    set_setting(_setting_key(platform, "client_secret"), client_secret, is_secret=True, description=f"{platform} OAuth Client Secret")
    set_setting(_setting_key(platform, "redirect_uri"), redirect_uri, is_secret=False, description=f"{platform} OAuth Redirect URI")
    if config is not None:
        set_setting(_setting_key(platform, "auth_url"), config.auth_url, is_secret=False, description=f"{platform} OAuth auth URL")
        set_setting(_setting_key(platform, "token_url"), config.token_url, is_secret=False, description=f"{platform} OAuth token URL")
        set_setting(_setting_key(platform, "scope"), config.scope, is_secret=False, description=f"{platform} OAuth scope")


def persist_oauth_connection(
    db: Session,
    *,
    store_id: str,
    platform: str,
    token_payload: dict,
) -> PlatformConnection:
    row = db.execute(
        select(PlatformConnection).where(
            PlatformConnection.store_id == store_id,
            PlatformConnection.platform == platform,
        )
    ).scalar_one_or_none()
    if row is None:
        row = PlatformConnection(store_id=store_id, platform=platform)
        db.add(row)
        db.flush()
    meta = _load_meta(row.meta_json)
    existing = meta.get("oauth") if isinstance(meta.get("oauth"), dict) else {}
    had_plaintext = bool(existing.get("access_token") or existing.get("refresh_token") or existing.get("raw"))
    merged = {
        "access_token": str(token_payload.get("access_token") or existing.get("access_token") or ""),
        "refresh_token": str(token_payload.get("refresh_token") or existing.get("refresh_token") or ""),
        "token_type": str(token_payload.get("token_type") or existing.get("token_type") or "bearer"),
        "scope": str(token_payload.get("scope") or existing.get("scope") or ""),
    }
    ref = put_oauth_secret(db, store_id, platform, merged)
    meta["oauth"] = {
        "credential_ref": ref,
        "credential_status": "ACTIVE",
        "token_type": merged["token_type"],
        "scope": merged["scope"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "rotate_recommended": had_plaintext,
    }
    row.meta_json = json.dumps(meta, ensure_ascii=False)
    row.status = "connected"
    row.connector_mode = "oauth"
    row.connected_at = row.connected_at or datetime.now(timezone.utc)
    row.last_error = None
    row.external_store_id = _external_store_id(token_payload) or row.external_store_id
    row.auth_expires_at = _expires_at(token_payload)
    db.add(row)
    db.flush()
    return row


def oauth_status(row: PlatformConnection | None, db: Session | None = None) -> dict[str, object]:
    if row is None:
        return {"connected": False}
    if db is not None:
        migrate_legacy_oauth_tokens(db, row)
    meta = _load_meta(row.meta_json)
    oauth = meta.get("oauth") if isinstance(meta.get("oauth"), dict) else {}
    expires = row.auth_expires_at.isoformat() if row.auth_expires_at else None
    public = public_oauth_fields(oauth, expires_at=expires)
    connected = bool(
        oauth.get("credential_status") == "ACTIVE"
        or (db is not None and has_oauth_secret(db, row.store_id, row.platform))
    )
    return {
        "connected": connected,
        "connector_mode": row.connector_mode,
        "status": row.status,
        "external_store_id": row.external_store_id,
        "token_type": oauth.get("token_type") or "bearer",
        "scope": oauth.get("scope") or "",
        "scopes": public["scopes"],
        "expires_at": expires,
        "auth_expires_at": expires,
        "credential_status": public["credential_status"],
        "rotate_recommended": public["rotate_recommended"],
    }


def _load_meta(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _parse_oauth_payload(body: str, content_type: str) -> dict:
    if "application/json" in (content_type or "").lower():
        value = json.loads(body or "{}")
        return value if isinstance(value, dict) else {}
    parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def _expires_at(payload: dict) -> datetime | None:
    raw = payload.get("expires_at")
    if raw:
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError:
            pass
    raw = payload.get("expires_in")
    try:
        seconds = int(raw)
    except Exception:  # noqa: BLE001
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=max(seconds, 0))


def _external_store_id(payload: dict) -> str:
    for key in ("external_store_id", "store_id", "shop_id", "merchant_id", "biz_store_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def oauth_connected_message(platform: str, row: PlatformConnection) -> str:
    label = "平台门店" if not row.external_store_id else f"平台门店 {row.external_store_id}"
    return humanize_operator_text(f"{platform} 已授权完成，当前绑定 {label}。后续可直接走真实平台拉数。")
