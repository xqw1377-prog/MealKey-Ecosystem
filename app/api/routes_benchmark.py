"""Operating Benchmark API — 经营需求基准覆盖率。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.operating_benchmark import (
    benchmark_report,
    get_demands_by_status,
    seed_demands,
)

router = APIRouter()


@router.get("/benchmark/report")
def get_benchmark_report(db: Session = Depends(get_db)) -> dict[str, Any]:
    """200 个经营需求的覆盖率报告。"""
    return benchmark_report(db)


@router.post("/benchmark/seed")
def post_benchmark_seed(db: Session = Depends(get_db)) -> dict[str, Any]:
    """初始化/更新 200 个需求。幂等。"""
    inserted = seed_demands(db)
    return {"inserted": inserted, "total": len(__import__("app.services.operating_benchmark", fromlist=["DEMANDS"]).DEMANDS)}


@router.get("/benchmark/demands")
def get_demands(
    status: str = Query("not_covered", description="covered/partial/not_covered"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """按覆盖率状态查需求列表。"""
    return get_demands_by_status(db, status, limit)
