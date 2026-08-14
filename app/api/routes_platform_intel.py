"""平台官网公开政策与促销采集 API。不接商家后台 OAuth。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import Store
from app.services.platform_intel import (
    collect_official_intel,
    latest_run,
    list_intel,
    load_sources,
    project_promos_to_store,
    schedule_label,
    serialize_item,
    serialize_run,
)

router = APIRouter()


@router.get("/platform-intel")
def get_platform_intel(
    kind: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    run = latest_run(db)
    items = list_intel(db, kind=kind, platform=platform, limit=limit)
    return {
        "schedule": schedule_label(),
        "timezone": "Asia/Shanghai",
        "last_run": serialize_run(run) if run else None,
        "sources": [
            {"platform": row["platform"], "name": row["name"], "url": row["url"]}
            for row in load_sources(db)
        ],
        "items": [serialize_item(item) for item in items],
        "counts": {
            "promo": sum(1 for item in items if item.kind == "promo"),
            "policy": sum(1 for item in items if item.kind == "policy"),
            "news": sum(1 for item in items if item.kind == "news"),
        },
    }


@router.post("/platform-intel/collect")
def post_collect_platform_intel(
    store_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if store_id and db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="store not found")
    return collect_official_intel(db, store_id=store_id)


@router.post("/stores/{store_id}/platform-intel/collect")
def post_collect_store_platform_intel(store_id: str, db: Session = Depends(get_db)):
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="store not found")
    return collect_official_intel(db, store_id=store_id)


@router.post("/stores/{store_id}/platform-intel/apply")
def post_apply_platform_intel(store_id: str, db: Session = Depends(get_db)):
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="store not found")
    written = project_promos_to_store(db, store_id)
    db.commit()
    return {"store_id": store_id, "projected_campaigns": written}
