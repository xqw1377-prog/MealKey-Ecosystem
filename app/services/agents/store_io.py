from __future__ import annotations
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.models.entities import MenuItem, Store

def _store_query():
    return select(Store).options(
        selectinload(Store.merchant),
        selectinload(Store.items).selectinload(MenuItem.current_version),
    )

def _load_store(db: Session, store_id: str) -> Store | None:
    return db.execute(_store_query().where(Store.id == store_id)).scalar_one_or_none()

def _menu_items(store: Store) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in store.items:
        if not item.is_active:
            continue
        current = item.current_version
        items.append(
            {
                "item_id": item.id,
                "name": current.name if current else "未命名商品",
                "category": current.category if current else None,
                "price": current.price if current else None,
                "description": current.description if current else None,
                "image_url": current.image_url if current else None,
                "is_active": item.is_active,
            }
        )
    return items
