"""Merchant Understanding 路由 — 非 Settings 表单，供调试与 Escape Hatch。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.merchant_understanding import MerchantUnderstanding
from app.services.mue import begin_interview_turn, ensure_understanding, load_understanding
from app.services.mue.engine import light_agents_for_store

router = APIRouter()


class InterviewAnswerRequest(BaseModel):
    """老板回答访谈问题的请求。"""

    key: Optional[str] = None  # 问题 key
    answer: str = ""  # 老板的自然语言回答


def _agents_or_404(db: Session, store_id: str):
    agents = light_agents_for_store(db, store_id)
    if agents is None:
        raise HTTPException(status_code=404, detail="store not found")
    return agents


@router.get("/stores/{store_id}/understanding", response_model=MerchantUnderstanding)
def get_understanding(store_id: str, db: Session = Depends(get_db)):
    agents = _agents_or_404(db, store_id)
    return ensure_understanding(db, store_id, agents=agents)


@router.post("/stores/{store_id}/understanding/interview")
def post_interview_turn(
    store_id: str,
    payload: InterviewAnswerRequest | None = None,
    db: Session = Depends(get_db),
):
    """访谈端点：可回答问题（带 payload）或仅取下一题（无 payload）。

    - 带 {key, answer}：先写回答案，再返回下一题 + 更新后的理解快照
    - 无 payload：仅取下一道「只问 AI 不能知道」的问题
    - NL 未命中：422，保留当前题，不静默换题
    """
    agents = _agents_or_404(db, store_id)

    if payload and payload.answer:
        from app.services.mue import handle_understanding_intent

        result = handle_understanding_intent(
            db,
            store_id,
            payload.answer,
            agents=agents,
            key=payload.key,
        )
        if result:
            return result
        current = begin_interview_turn(db, store_id, agents=agents)
        current["accepted"] = False
        current["detail"] = "确认没有对上当前问题，请再选一次"
        return JSONResponse(status_code=422, content=current)

    return begin_interview_turn(db, store_id, agents=agents)


@router.get("/stores/{store_id}/understanding/raw", response_model=MerchantUnderstanding)
def get_understanding_raw(store_id: str, db: Session = Depends(get_db)):
    """不触发 bootstrap 刷新，仅读库（高级设置用）。"""
    return load_understanding(db, store_id)
