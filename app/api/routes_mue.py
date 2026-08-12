"""Merchant Understanding 路由 — 非 Settings 表单，供调试与 Escape Hatch。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.merchant_understanding import MerchantUnderstanding
from app.services.agents import build_store_agents
from app.services.mue import begin_interview_turn, ensure_understanding, load_understanding

router = APIRouter()


class InterviewAnswerRequest(BaseModel):
    """老板回答访谈问题的请求。"""
    key: Optional[str] = None  # 问题 key
    answer: str = ""  # 老板的自然语言回答


@router.get("/stores/{store_id}/understanding", response_model=MerchantUnderstanding)
def get_understanding(store_id: str, db: Session = Depends(get_db)):
    agents = build_store_agents(db=db, store_id=store_id, days=7)
    if agents is None:
        raise HTTPException(status_code=404, detail="store not found")
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
    """
    agents = build_store_agents(db=db, store_id=store_id, days=7)
    if agents is None:
        raise HTTPException(status_code=404, detail="store not found")

    if payload and payload.answer:
        # 写回答案
        from app.services.mue import handle_understanding_intent

        result = handle_understanding_intent(db, store_id, payload.answer)
        if result:
            return result
        # 如果 NL 解析没命中，仍然继续取下一题

    return begin_interview_turn(db, store_id, agents=agents)


@router.get("/stores/{store_id}/understanding/raw", response_model=MerchantUnderstanding)
def get_understanding_raw(store_id: str, db: Session = Depends(get_db)):
    """不触发 bootstrap 刷新，仅读库（高级设置用）。"""
    return load_understanding(db, store_id)
