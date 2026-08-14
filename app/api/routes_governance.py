"""AI Governance API — 需求 #181-200。

让老板能问 AI "为什么"、"用了什么数据"、"多大把握"、"不做会怎样"、"哪些经验过期了"。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.ai_governance import (
    confidence_display,
    explain_data_provenance,
    explain_judgment,
    worst_case_if_nothing,
)
from app.services.memory_lifecycle import get_active_memories, run_memory_lifecycle

router = APIRouter()


class ExplainRequest(BaseModel):
    recommendation_id: Optional[str] = None
    question: str = ""


@router.post("/stores/{store_id}/ai/explain")
def post_explain(store_id: str, body: ExplainRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """解释 AI 的判断依据。需求 #182。"""
    return explain_judgment(db, store_id, recommendation_id=body.recommendation_id or "", question=body.question)


@router.get("/stores/{store_id}/ai/data-provenance")
def get_provenance(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """这次判断用了哪些数据,缺哪些。需求 #183。"""
    return explain_data_provenance(db, store_id)


@router.get("/stores/{store_id}/ai/confidence")
def get_confidence(
    store_id: str,
    confidence: float = Query(0.7, description="置信度 0-1"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """把置信度转化为人类可读的把握度。需求 #184。"""
    return confidence_display(confidence)


@router.get("/stores/{store_id}/ai/worst-case")
def get_worst_case(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """如果什么都不做,最坏可能损失多少。需求 #185。"""
    return worst_case_if_nothing(store_id, db)


@router.post("/stores/{store_id}/ai/memory-lifecycle")
def post_memory_cleanup(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """执行 Strategy Memory 过期/降权清理。需求 #199。"""
    stats = run_memory_lifecycle(db)
    return stats


@router.get("/stores/{store_id}/ai/active-memories")
def get_memories(store_id: str, limit: int = Query(20, le=50), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """获取有效的 Strategy Memory(排除过期/失效)。"""
    records = get_active_memories(db, store_id, limit)
    return [
        {
            "id": r.id,
            "action_type": r.action_type,
            "result": r.result,
            "lift_pct": r.lift_pct,
            "confidence": r.confidence,
            "lesson": r.lesson,
            "reuse_when": r.reuse_when,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
