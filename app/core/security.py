"""多租户 JWT 与凭证校验。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

import jwt

from app.core.config import settings
from app.core.time import utc_now

ALGORITHM = "HS256"


@dataclass(frozen=True)
class AuthPrincipal:
    """请求身份：legacy 主 token 或门店作用域 JWT。"""

    subject: str
    role: str  # admin | operator
    tenant_id: Optional[str]
    store_ids: tuple[str, ...]  # 空元组 = 不限（仅 admin/legacy）
    auth_mode: str  # api_token | jwt

    @property
    def is_admin(self) -> bool:
        return self.role == "admin" or self.auth_mode == "api_token"

    def can_access_store(self, store_id: str) -> bool:
        if self.is_admin:
            return True
        if not self.store_ids:
            return True
        return store_id in self.store_ids


def jwt_secret() -> str:
    secret = (settings.jwt_secret or "").strip()
    if secret:
        return secret
    # 开发回退：派生自 api_token，避免未配置时完全不可用
    base = (settings.api_token or "mealky-dev").encode("utf-8")
    return hashlib.sha256(b"mealky-jwt|" + base).hexdigest()


def hash_client_secret(secret: str) -> str:
    return hashlib.sha256(f"mealky-tenant|{secret}".encode("utf-8")).hexdigest()


def generate_client_secret() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(
    *,
    subject: str,
    tenant_id: Optional[str],
    store_ids: list[str] | tuple[str, ...],
    role: str = "operator",
    expires_minutes: int | None = None,
) -> str:
    ttl = expires_minutes if expires_minutes is not None else int(settings.jwt_expire_minutes)
    now = utc_now()
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "tenant_id": tenant_id,
        "store_ids": list(store_ids),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
        "iss": "mealky",
    }
    return jwt.encode(payload, jwt_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> AuthPrincipal:
    try:
        payload = jwt.decode(
            token,
            jwt_secret(),
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise ValueError("invalid or expired token") from exc
    store_ids = payload.get("store_ids") or []
    if not isinstance(store_ids, list):
        store_ids = []
    return AuthPrincipal(
        subject=str(payload.get("sub") or ""),
        role=str(payload.get("role") or "operator"),
        tenant_id=payload.get("tenant_id"),
        store_ids=tuple(str(s) for s in store_ids if s),
        auth_mode="jwt",
    )


def extract_bearer(authorization: str | None) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def verify_api_token(token: str) -> bool:
    expected = settings.api_token or ""
    if not expected or not token:
        return False
    return hmac.compare_digest(token, expected)
