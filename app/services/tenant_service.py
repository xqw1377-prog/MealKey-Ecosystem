"""租户凭证与门店作用域。"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import generate_client_secret, hash_client_secret
from app.core.time import utc_now
from app.models.entities import Store
from app.models.tenant import Tenant, TenantStore


def list_tenant_store_ids(db: Session, tenant_id: str) -> list[str]:
    rows = db.execute(
        select(TenantStore.store_id).where(TenantStore.tenant_id == tenant_id)
    ).scalars().all()
    return [str(r) for r in rows]


def get_tenant_by_client_id(db: Session, client_id: str) -> Tenant | None:
    return db.execute(
        select(Tenant)
        .options(selectinload(Tenant.stores))
        .where(Tenant.client_id == client_id, Tenant.status == "active")
    ).scalar_one_or_none()


def verify_tenant_secret(tenant: Tenant, client_secret: str) -> bool:
    return tenant.client_secret_hash == hash_client_secret(client_secret)


def ensure_default_tenant(db: Session, *, name: str = "默认租户") -> tuple[Tenant, str | None]:
    """若无租户则创建默认租户，并挂上全部现有门店。

    Returns: (tenant, plaintext_secret_or_None_if_existing)
    """
    existing = db.execute(select(Tenant).order_by(Tenant.created_at.asc())).scalars().first()
    if existing:
        # 补绑尚未归属的门店
        bound = set(list_tenant_store_ids(db, existing.id))
        stores = db.execute(select(Store)).scalars().all()
        for store in stores:
            if store.id not in bound:
                db.add(TenantStore(tenant_id=existing.id, store_id=store.id, role="operator"))
        db.commit()
        db.refresh(existing)
        return existing, None

    secret = generate_client_secret()
    tenant = Tenant(
        name=name,
        client_id="tenant_default",
        client_secret_hash=hash_client_secret(secret),
        status="active",
        created_at=utc_now(),
    )
    db.add(tenant)
    db.flush()
    for store in db.execute(select(Store)).scalars().all():
        db.add(TenantStore(tenant_id=tenant.id, store_id=store.id, role="operator"))
    db.commit()
    db.refresh(tenant)
    return tenant, secret


def create_tenant(
    db: Session,
    *,
    name: str,
    store_ids: list[str],
    client_id: Optional[str] = None,
) -> tuple[Tenant, str]:
    secret = generate_client_secret()
    cid = client_id or f"tenant_{generate_client_secret()[:10]}"
    tenant = Tenant(
        name=name,
        client_id=cid,
        client_secret_hash=hash_client_secret(secret),
        status="active",
        created_at=utc_now(),
    )
    db.add(tenant)
    db.flush()
    for sid in store_ids:
        db.add(TenantStore(tenant_id=tenant.id, store_id=sid, role="operator"))
    db.commit()
    db.refresh(tenant)
    return tenant, secret
