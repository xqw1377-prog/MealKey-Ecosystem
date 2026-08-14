"""Golden Case API — 经典案例库 + 智能匹配。"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.golden_cases import match_cases, seed_cases

router = APIRouter()


class MatchRequest(BaseModel):
    question: str = ""
    category: str = ""
    signals: Optional[dict[str, Any]] = None
    limit: int = 3


@router.post("/benchmark/seed-cases")
def post_seed_cases(db: Session = Depends(get_db)) -> dict[str, Any]:
    """初始化30个经典案例。"""
    inserted = seed_cases(db)
    return {"inserted": inserted, "total": 30}


@router.post("/cases/match")
def post_match_cases(body: MatchRequest, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """根据问题/信号匹配最相似的经典案例。"""
    return match_cases(
        db,
        signals=body.signals,
        question=body.question,
        category=body.category,
        limit=body.limit,
    )


@router.get("/cases")
def get_cases(
    category: str = Query("", description="按类别筛选"),
    limit: int = Query(30, le=50),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """列出经典案例。"""
    from app.models.golden_case import GoldenCase
    from sqlalchemy import select
    import json

    query = select(GoldenCase)
    if category:
        query = query.where(GoldenCase.category == category)
    rows = list(db.execute(query.order_by(GoldenCase.case_code).limit(limit)).scalars())
    return [
        {
            "case_code": r.case_code,
            "category": r.category,
            "title": r.title,
            "scenario": r.scenario,
            "expected_diagnosis": r.expected_diagnosis,
            "expected_action": r.expected_action,
            "lesson": r.lesson,
            "tags": r.tags,
            "confidence": r.confidence,
        }
        for r in rows
    ]
