from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.authorized_session_connector import AuthorizedSessionConnector
from app.services.data_acquisition_ingest import connector_status, ingest_reconciliation, list_runs, poc_review
from app.services.data_acquisition_loop import run_connected_discovery
from app.schemas.data_acquisition import FetchRequest

router = APIRouter()


class OfficialReportBody(BaseModel):
    platform: str = "meituan"
    rows: list[dict[str, Any]] = Field(default_factory=list)
    baseline_only: bool = True


class IngestBody(BaseModel):
    platform: str = "meituan"
    official_rows: list[dict[str, Any]] = Field(default_factory=list)
    collector_rows: list[dict[str, Any]] = Field(default_factory=list)
    acquisition_mode: str = "AUTHORIZED_SESSION"
    auth_status: str = "authorized"


class DiscoverBody(BaseModel):
    mode: str = "REAL"
    official_rows: list[dict[str, Any]] = Field(default_factory=list)
    collector_rows: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/data-acquisition/status")
def acquisition_status(store_id: str = "unwired", platform: str = "meituan") -> dict[str, Any]:
    return connector_status(store_id, platform)


@router.post("/stores/{store_id}/data-acquisition/fetch")
def fetch_authorized_session(store_id: str, platform: str = "meituan") -> dict[str, Any]:
    """真实 fetch。未接线必须 UNAVAILABLE，绝不返回伪造经营事实。"""
    result = AuthorizedSessionConnector().fetch(FetchRequest(store_id=store_id, platform=platform))
    return result.model_dump(mode="json")


@router.post("/stores/{store_id}/data-acquisition/official-report")
def day0_official_report(store_id: str, body: OfficialReportBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return ingest_reconciliation(
            db,
            store_id=store_id,
            platform=body.platform,
            official_rows=body.rows,
            collector_rows=None,
            baseline_only=True,
        )
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 422, str(exc)) from exc


@router.post("/stores/{store_id}/data-acquisition/ingest")
def ingest_facts(store_id: str, body: IngestBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return ingest_reconciliation(
            db,
            store_id=store_id,
            platform=body.platform,
            official_rows=body.official_rows,
            collector_rows=body.collector_rows,
            acquisition_mode=body.acquisition_mode,
            auth_status=body.auth_status,
        )
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 422, str(exc)) from exc


@router.get("/stores/{store_id}/data-acquisition/runs")
def get_runs(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"store_id": store_id, "runs": list_runs(db, store_id)}


@router.get("/stores/{store_id}/data-acquisition/review")
def get_review(store_id: str, reached_candidate_action: bool = False, db: Session = Depends(get_db)) -> dict[str, Any]:
    return poc_review(db, store_id, reached_candidate_action=reached_candidate_action)


@router.post("/stores/{store_id}/data-acquisition/discover")
def discover_from_facts(
    store_id: str,
    body: DiscoverBody | None = Body(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """对账后的经营发现：StoreState → ORDER_DROP → Candidate Action。不执行写回。

    默认 REAL：无事实 → NO_SIGNAL，绝不合成下降序列。
    FIXTURE / SANDBOX 仅开发环境，且写入 synthetic，不得晋升生产 Truth。
    """
    payload = body or DiscoverBody()
    mode = str(payload.mode or "REAL").strip().upper()
    if mode in {"FIXTURE", "SANDBOX"} and not settings.is_dev:
        raise HTTPException(status_code=403, detail="FIXTURE/SANDBOX discover 仅开发环境可用")
    official = payload.official_rows or None
    collector = payload.collector_rows or None
    try:
        return run_connected_discovery(
            db,
            store_id=store_id,
            mode=mode,  # type: ignore[arg-type]
            official_rows=official,
            collector_rows=collector,
        )
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 422, str(exc)) from exc
