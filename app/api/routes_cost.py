"""Cost API — 成本导入 + 查询 + 单品录入。

Track B (Business Truth) 的入口:
    老板上传成本表 / 手动填一个商品成本 → 系统获得真实经营事实。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.cost_import import (
    get_item_costs,
    get_store_cost_coverage,
    import_cost_sheet,
    update_single_item_cost,
)

router = APIRouter()


# ── 上传成本表 ────────────────────────────────────────────────


@router.post("/stores/{store_id}/cost/import")
async def import_cost(
    store_id: str,
    file: UploadFile = File(...),
    source: str = Query("owner_cost_sheet", description="数据来源"),
    confidence: str = Query("high", description="置信度 high/medium/low"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """上传成本表(Excel/CSV/JSON),自动解析 + 匹配 + 写入。

    返回导入报告,包括未匹配商品列表(需人工确认)。
    """
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    content = await file.read()
    if not content:
        raise HTTPException(400, "文件内容为空")

    # 限制文件大小 5MB
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "文件过大,请上传 5MB 以内的成本表")

    try:
        report = import_cost_sheet(
            db,
            store_id=store_id,
            content=content,
            filename=file.filename,
            source=source,
            confidence=confidence,
        )
    except Exception as exc:
        raise HTTPException(422, f"解析失败: {exc}") from exc

    return report


# ── 查询商品成本列表 ──────────────────────────────────────────


@router.get("/stores/{store_id}/cost/items")
def list_item_costs(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """列出门店所有商品的成本状态。"""
    return {
        "items": get_item_costs(db, store_id),
        "coverage": get_store_cost_coverage(db, store_id),
    }


# ── 查询成本覆盖度 ────────────────────────────────────────────


@router.get("/stores/{store_id}/cost/coverage")
def cost_coverage(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """门店成本覆盖度:有多少 SKU 有真实成本,多少还 UNKNOWN。"""
    return get_store_cost_coverage(db, store_id)


# ── 手动更新单品成本 ──────────────────────────────────────────


class SingleCostUpdate(BaseModel):
    """单品成本录入(用于中栏 [填写成本] 按钮)。"""

    food_cost: Optional[float] = None
    packaging_cost: Optional[float] = None
    source: str = "manual_input"
    confidence: str = "high"


@router.put("/stores/{store_id}/cost/items/{item_id}")
def update_item_cost(
    store_id: str,
    item_id: str,
    body: SingleCostUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """手动更新单个商品成本。

    场景:系统算到最后一步发现缺成本 → 中栏出现 [填写成本] → 老板填 → 继续。
    """
    result = update_single_item_cost(
        db,
        store_id=store_id,
        item_id=item_id,
        food_cost=body.food_cost,
        packaging_cost=body.packaging_cost,
        source=body.source,
        confidence=body.confidence,
    )
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result
