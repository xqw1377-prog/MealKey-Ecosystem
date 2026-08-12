from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import CompetitionCollectionRun, Store
from app.schemas.competition import (
    CompetitionCollectionResult,
    CompetitionMapResponse,
    CompetitorSnapshotInput,
)
from app.services.competition_collection import (
    build_competition_map,
    collect_store_competitors,
    get_competition_source,
    ingest_competitor_snapshot,
)

router = APIRouter()


@router.post(
    "/{store_id}/competition/collect",
    response_model=CompetitionCollectionResult,
)
def collect_competition(
    store_id: str,
    provider: str = Query(default="amap", pattern="^(amap|licensed_partner)$"),
    db: Session = Depends(get_db),
):
    try:
        return collect_store_competitors(
            db=db,
            store_id=store_id,
            source=get_competition_source(provider),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{store_id}/competition/snapshots", status_code=201)
def import_competitor_snapshot(
    store_id: str,
    payload: CompetitorSnapshotInput,
    db: Session = Depends(get_db),
):
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    competitor = ingest_competitor_snapshot(db=db, store=store, payload=payload)
    db.commit()
    return {
        "status": "created",
        "competitor_id": competitor.id,
        "provider": payload.provider,
        "menu_item_count": len(payload.menu_items),
    }


@router.get(
    "/{store_id}/competition/map",
    response_model=CompetitionMapResponse,
)
def get_competition_map(
    store_id: str,
    db: Session = Depends(get_db),
):
    payload = build_competition_map(db=db, store_id=store_id)
    if payload is None:
        raise HTTPException(
            status_code=422,
            detail="门店不存在或缺少经纬度，无法生成竞争地图",
        )
    return payload


@router.get("/{store_id}/competition/collection-runs")
def get_collection_runs(
    store_id: str,
    db: Session = Depends(get_db),
):
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="store not found")
    rows = list(
        db.execute(
            select(CompetitionCollectionRun)
            .where(CompetitionCollectionRun.store_id == store_id)
            .order_by(CompetitionCollectionRun.started_at.desc())
            .limit(20)
        ).scalars()
    )
    return {
        "store_id": store_id,
        "runs": [
            {
                "run_id": row.id,
                "provider": row.provider,
                "status": row.status,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
                "discovered_count": row.discovered_count,
                "snapshot_count": row.snapshot_count,
                "error": row.error,
            }
            for row in rows
        ],
    }
