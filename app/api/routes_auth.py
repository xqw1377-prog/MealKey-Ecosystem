"""多租户鉴权：签发 JWT / 查看当前身份。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    AuthPrincipal,
    create_access_token,
    verify_api_token,
)
from app.db.session import get_db
from app.models.entities import Store
from app.services.tenant_service import (
    ensure_default_tenant,
    get_tenant_by_client_id,
    list_tenant_store_ids,
    verify_tenant_secret,
)

router = APIRouter()


class TokenRequest(BaseModel):
    """换取 JWT。

    两种方式：
    1) 主 API token（admin）：body.api_token 或 header x-api-token
    2) 租户凭证：client_id + client_secret
    """

    api_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    store_id: Optional[str] = None
    store_ids: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    tenant_id: Optional[str] = None
    store_ids: list[str] = Field(default_factory=list)


@router.post("/token", response_model=TokenResponse)
def issue_token(payload: TokenRequest, request: Request, db: Session = Depends(get_db)):
    header_token = request.headers.get("x-api-token", "")
    master = payload.api_token or header_token

    # ── 主 token → admin JWT（可限 store） ──
    if master and verify_api_token(master):
        wanted = list(payload.store_ids)
        if payload.store_id:
            wanted.append(payload.store_id)
        wanted = [s for s in dict.fromkeys(wanted) if s]
        if wanted:
            existing = set(
                db.execute(select(Store.id).where(Store.id.in_(wanted))).scalars().all()
            )
            missing = [s for s in wanted if s not in existing]
            if missing:
                raise HTTPException(status_code=404, detail=f"store not found: {missing[0]}")
            store_ids = wanted
        else:
            store_ids = list(db.execute(select(Store.id)).scalars().all())
        token = create_access_token(
            subject="admin",
            tenant_id=None,
            store_ids=store_ids,
            role="admin",
        )
        return TokenResponse(
            access_token=token,
            expires_in=int(settings.jwt_expire_minutes) * 60,
            role="admin",
            tenant_id=None,
            store_ids=store_ids,
        )

    # ── 租户凭证 → operator JWT ──
    if payload.client_id and payload.client_secret:
        tenant = get_tenant_by_client_id(db, payload.client_id)
        if tenant is None or not verify_tenant_secret(tenant, payload.client_secret):
            raise HTTPException(status_code=401, detail="invalid tenant credentials")
        allowed = list_tenant_store_ids(db, tenant.id)
        wanted = list(payload.store_ids)
        if payload.store_id:
            wanted.append(payload.store_id)
        wanted = [s for s in dict.fromkeys(wanted) if s]
        if wanted:
            if any(s not in allowed for s in wanted):
                raise HTTPException(status_code=403, detail="store not in tenant scope")
            store_ids = wanted
        else:
            store_ids = allowed
        token = create_access_token(
            subject=tenant.client_id,
            tenant_id=tenant.id,
            store_ids=store_ids,
            role="operator",
        )
        return TokenResponse(
            access_token=token,
            expires_in=int(settings.jwt_expire_minutes) * 60,
            role="operator",
            tenant_id=tenant.id,
            store_ids=store_ids,
        )

    raise HTTPException(
        status_code=401,
        detail="provide api_token or client_id/client_secret",
    )


@router.get("/me")
def auth_me(request: Request):
    principal: AuthPrincipal | None = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return {
        "subject": principal.subject,
        "role": principal.role,
        "tenant_id": principal.tenant_id,
        "store_ids": list(principal.store_ids),
        "auth_mode": principal.auth_mode,
        "is_admin": principal.is_admin,
    }


@router.post("/bootstrap-tenant")
def bootstrap_tenant(request: Request, db: Session = Depends(get_db)):
    """开发/运维：确保默认租户存在；仅 admin / 主 token 可调用。"""
    principal: AuthPrincipal | None = getattr(request.state, "principal", None)
    if principal is None or not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin required")
    tenant, secret = ensure_default_tenant(db)
    return {
        "tenant_id": tenant.id,
        "client_id": tenant.client_id,
        "client_secret": secret,  # 仅首次创建时返回明文
        "store_ids": list_tenant_store_ids(db, tenant.id),
        "message": (
            "default tenant created; store client_secret securely"
            if secret
            else "default tenant already exists"
        ),
    }
