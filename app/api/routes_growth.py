"""Growth Action Primitive API — Registry 只读 + 预算护栏。

执行能力状态是显式的：mutating 原语 BLOCKED_NOT_IMPLEMENTED，
不做任何平台写回。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.growth_primitives import (
    check_budget_guard,
    get_primitive,
    list_primitives,
    primitives_for_segment,
)

router = APIRouter()


@router.get("/growth/primitives")
def get_primitives(
    segment: str = Query("", description="按目标人群筛选"),
) -> list[dict[str, Any]]:
    """列出 Growth Action Primitive（含 execution_capability 状态）。"""
    if segment:
        return [vars(p) | {"execution_status": p.execution_status} for p in primitives_for_segment(segment)]
    return [p | {"execution_status": p.execution_status} for p in list_primitives()]


class BudgetCheckRequest(BaseModel):
    action_type: str
    target_count: int


@router.post("/growth/primitives/budget-check")
def post_budget_check(body: BudgetCheckRequest) -> dict[str, Any]:
    """预算护栏检查（只是 Budget Guard，不是 Profit Gate）。"""
    result = check_budget_guard(body.action_type, body.target_count)
    if not result.get("ok") and result.get("reason") == "unknown primitive":
        raise HTTPException(404, "unknown primitive")
    primitive = get_primitive(body.action_type)
    return {
        **result,
        "execution_status": primitive.execution_status if primitive else "UNKNOWN",
        "note": "budget guard only — profit gate and capability gate still apply",
    }
