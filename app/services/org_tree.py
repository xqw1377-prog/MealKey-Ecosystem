"""企业主体 → 多品牌 → 多门店。Merchant 仍是计费主体。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Brand, Menu, Merchant, Store
from app.models.tenant import Tenant, TenantStore


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def ensure_org_tree(db: Session, store: Store) -> bool:
    """把旧的 1 商户 1 门店数据回填成默认品牌。有写入则返回 True。"""
    merchant = store.merchant
    if merchant is None:
        return False

    dirty = False
    brands = list(db.execute(select(Brand).where(Brand.merchant_id == merchant.id)).scalars().all())
    if not brands:
        brand = Brand(
            merchant_id=merchant.id,
            name=_clean(merchant.brand_name) or _clean(merchant.name) or store.name,
            category=merchant.category,
            cuisine_type=merchant.cuisine_type,
            business_hours=merchant.business_hours,
            status="active",
        )
        db.add(brand)
        db.flush()
        brands = [brand]
        dirty = True

    default_brand = brands[0]
    sibling_stores = list(db.execute(select(Store).where(Store.merchant_id == merchant.id)).scalars().all())
    for row in sibling_stores:
        if row.brand_id:
            continue
        row.brand_id = default_brand.id
        db.add(row)
        dirty = True
        if row.id == store.id:
            store.brand_id = default_brand.id

    if dirty:
        db.flush()
        db.expire(merchant, ["brands", "stores"])
        if store.brand_id and store.brand is None:
            store.brand = next((item for item in brands if item.id == store.brand_id), default_brand)
    return dirty


def org_tree_payload(db: Session, store: Store) -> dict[str, Any]:
    merchant = store.merchant
    if merchant is None and store.merchant_id:
        merchant = db.execute(select(Merchant).where(Merchant.id == store.merchant_id)).scalar_one_or_none()
    if merchant is None:
        return {
            "merchant_id": store.merchant_id,
            "name": "",
            "location": "",
            "brand_count": 0,
            "store_count": 0,
            "brands": [],
        }

    brands = list(
        db.execute(
            select(Brand).where(Brand.merchant_id == merchant.id).order_by(Brand.created_at.asc(), Brand.name.asc())
        ).scalars().all()
    )
    stores = list(
        db.execute(
            select(Store).where(Store.merchant_id == merchant.id).order_by(Store.created_at.asc(), Store.name.asc())
        ).scalars().all()
    )
    stores_by_brand: dict[str, list[Store]] = {}
    for row in stores:
        if not row.brand_id:
            continue
        stores_by_brand.setdefault(row.brand_id, []).append(row)

    brand_rows = []
    for brand in brands:
        brand_stores = stores_by_brand.get(brand.id, [])
        brand_rows.append(
            {
                "brand_id": brand.id,
                "name": brand.name,
                "category": brand.category or "",
                "cuisine_type": brand.cuisine_type or "",
                "business_hours": brand.business_hours or "",
                "status": brand.status,
                "store_count": len(brand_stores),
                "stores": [
                    {
                        "store_id": row.id,
                        "name": row.name,
                        "city": row.city or "",
                        "area": row.area or "",
                        "address": row.address or "",
                        "status": row.status,
                        "current": row.id == store.id,
                    }
                    for row in brand_stores
                ],
            }
        )
    return {
        "merchant_id": merchant.id,
        "name": merchant.name or "",
        "location": merchant.location or "",
        "brand_count": len(brand_rows),
        "store_count": sum(item["store_count"] for item in brand_rows),
        "brands": brand_rows,
    }


def current_brand(store: Store) -> Brand | None:
    if store.brand is not None:
        return store.brand
    if store.brand_id and store.merchant:
        for brand in store.merchant.brands or []:
            if brand.id == store.brand_id:
                return brand
    return None


def enterprise_payload(db: Session, store: Store) -> dict[str, Any]:
    merchant = store.merchant
    brand = current_brand(store)
    org = org_tree_payload(db, store)
    return {
        "store_id": store.id,
        "merchant_id": getattr(merchant, "id", None),
        "brand_id": getattr(brand, "id", None) or store.brand_id,
        "name": getattr(merchant, "name", None) or "",
        "location": getattr(merchant, "location", None) or "",
        "brand_name": getattr(brand, "name", None) or getattr(merchant, "brand_name", None) or "",
        "category": getattr(brand, "category", None) or getattr(merchant, "category", None) or "",
        "cuisine_type": getattr(brand, "cuisine_type", None)
        or getattr(merchant, "cuisine_type", None)
        or "",
        "business_hours": getattr(brand, "business_hours", None)
        or getattr(merchant, "business_hours", None)
        or "",
        "org": org,
    }


def update_enterprise(db: Session, store: Store, data: dict[str, Any]) -> dict[str, Any]:
    merchant = store.merchant
    if merchant is None:
        raise ValueError("enterprise not found")
    ensure_org_tree(db, store)
    brand = current_brand(store)

    if "name" in data:
        name = _clean(data.get("name"))
        if name:
            merchant.name = name
    if "location" in data:
        merchant.location = _clean(data.get("location"))

    brand_fields = ("brand_name", "category", "cuisine_type", "business_hours")
    if brand is not None:
        if "brand_name" in data:
            brand_name = _clean(data.get("brand_name"))
            if brand_name:
                brand.name = brand_name
            merchant.brand_name = brand_name
        if "category" in data:
            brand.category = _clean(data.get("category"))
            merchant.category = brand.category
        if "cuisine_type" in data:
            brand.cuisine_type = _clean(data.get("cuisine_type"))
            merchant.cuisine_type = brand.cuisine_type
        if "business_hours" in data:
            brand.business_hours = _clean(data.get("business_hours"))
            merchant.business_hours = brand.business_hours
        db.add(brand)
    else:
        for field in brand_fields:
            if field not in data:
                continue
            value = _clean(data.get(field))
            attr = "brand_name" if field == "brand_name" else field
            setattr(merchant, attr, value)

    db.add(merchant)
    db.flush()
    return enterprise_payload(db, store)


def create_brand(db: Session, store: Store, data: dict[str, Any]) -> dict[str, Any]:
    merchant = store.merchant
    if merchant is None:
        raise ValueError("enterprise not found")
    ensure_org_tree(db, store)
    name = _clean(data.get("name"))
    if not name:
        raise ValueError("品牌名不能为空")
    brand = Brand(
        merchant_id=merchant.id,
        name=name,
        category=_clean(data.get("category")),
        cuisine_type=_clean(data.get("cuisine_type")),
        business_hours=_clean(data.get("business_hours")),
        status="active",
    )
    db.add(brand)
    db.flush()
    return enterprise_payload(db, store)


def update_brand(db: Session, store: Store, brand_id: str, data: dict[str, Any]) -> dict[str, Any]:
    merchant = store.merchant
    if merchant is None:
        raise ValueError("enterprise not found")
    brand = db.execute(
        select(Brand).where(Brand.id == brand_id, Brand.merchant_id == merchant.id)
    ).scalar_one_or_none()
    if brand is None:
        raise ValueError("brand not found")
    if "name" in data:
        name = _clean(data.get("name"))
        if name:
            brand.name = name
    for field in ("category", "cuisine_type", "business_hours"):
        if field in data:
            setattr(brand, field, _clean(data.get(field)))
    db.add(brand)
    if store.brand_id == brand.id or (store.brand and store.brand.id == brand.id):
        merchant.brand_name = brand.name
        merchant.category = brand.category
        merchant.cuisine_type = brand.cuisine_type
        merchant.business_hours = brand.business_hours
        db.add(merchant)
    db.flush()
    return enterprise_payload(db, store)


def bind_store_to_merchant_tenants(db: Session, store: Store) -> None:
    sibling_ids = db.execute(
        select(Store.id).where(Store.merchant_id == store.merchant_id, Store.id != store.id)
    ).scalars().all()
    tenant_ids: list[str] = []
    if sibling_ids:
        tenant_ids = list(
            db.execute(
                select(TenantStore.tenant_id).where(TenantStore.store_id.in_(sibling_ids)).distinct()
            ).scalars().all()
        )
    if not tenant_ids:
        default = db.execute(select(Tenant).order_by(Tenant.created_at.asc())).scalars().first()
        if default is not None:
            tenant_ids = [default.id]
    bound = set(
        db.execute(select(TenantStore.tenant_id).where(TenantStore.store_id == store.id)).scalars().all()
    )
    for tenant_id in tenant_ids:
        if tenant_id in bound:
            continue
        db.add(TenantStore(tenant_id=tenant_id, store_id=store.id, role="operator"))


def create_store_under_brand(db: Session, context_store: Store, brand_id: str, data: dict[str, Any]) -> dict[str, Any]:
    merchant = context_store.merchant
    if merchant is None:
        raise ValueError("enterprise not found")
    brand = db.execute(
        select(Brand).where(Brand.id == brand_id, Brand.merchant_id == merchant.id)
    ).scalar_one_or_none()
    if brand is None:
        raise ValueError("brand not found")
    name = _clean(data.get("name"))
    if not name:
        raise ValueError("门店名不能为空")
    store = Store(
        merchant_id=merchant.id,
        brand_id=brand.id,
        name=name,
        city=_clean(data.get("city")),
        area=_clean(data.get("area")),
        address=_clean(data.get("address")),
        status="active",
    )
    db.add(store)
    db.flush()
    db.add(Menu(store_id=store.id, name="默认菜单", type="delivery", version=1, status="active"))
    bind_store_to_merchant_tenants(db, store)
    db.flush()
    return enterprise_payload(db, context_store)
