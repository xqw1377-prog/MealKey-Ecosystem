"""Business Data Import API — 统一业务数据导入端点。

补足"平台真实数据"短板的第一阶段路径:
    平台导出 Excel/CSV → 上传 → 自动解析 → 写入事实表

4 种导入: 经营数据 / 投流数据 / 评价数据 / 活动数据
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.business_import import (
    get_data_coverage,
    import_ads_data,
    import_campaigns,
    import_funnel_data,
    import_ops_metrics,
    import_orders,
    import_reviews,
)

router = APIRouter()


async def _read_upload(file: UploadFile) -> bytes:
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")
    content = await file.read()
    if not content:
        raise HTTPException(400, "文件内容为空")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "文件过大,请上传 10MB 以内")
    return content


@router.post("/stores/{store_id}/import/funnel")
async def import_funnel(
    store_id: str,
    file: UploadFile = File(...),
    source: str = Query("platform_export"),
    confidence: str = Query("high"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """导入每日经营数据(曝光/访问/订单/GMV/推广费)。

    兼容美团/饿了么等平台导出的 CSV/Excel/JSON。
    """
    content = await _read_upload(file)
    try:
        return import_funnel_data(db, store_id, content, file.filename, source=source, confidence=confidence)
    except Exception as exc:
        raise HTTPException(422, f"解析失败: {exc}") from exc


@router.post("/stores/{store_id}/import/ads")
async def import_ads(
    store_id: str,
    file: UploadFile = File(...),
    source: str = Query("platform_export"),
    confidence: str = Query("high"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """导入推广投流数据(花费/点击/CPC/ROAS)。"""
    content = await _read_upload(file)
    try:
        return import_ads_data(db, store_id, content, file.filename, source=source, confidence=confidence)
    except Exception as exc:
        raise HTTPException(422, f"解析失败: {exc}") from exc


@router.post("/stores/{store_id}/import/reviews")
async def import_reviews_endpoint(
    store_id: str,
    file: UploadFile = File(...),
    source: str = Query("platform_export"),
    confidence: str = Query("high"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """导入评价数据(评分/内容/回复),同步写入诊断层。"""
    content = await _read_upload(file)
    try:
        return import_reviews(db, store_id, content, file.filename, source=source, confidence=confidence)
    except Exception as exc:
        raise HTTPException(422, f"解析失败: {exc}") from exc


@router.post("/stores/{store_id}/import/campaigns")
async def import_campaigns_endpoint(
    store_id: str,
    file: UploadFile = File(...),
    source: str = Query("manual_input"),
    confidence: str = Query("medium"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """导入活动数据(活动规则/补贴/时间)。"""
    content = await _read_upload(file)
    try:
        return import_campaigns(db, store_id, content, file.filename, source=source, confidence=confidence)
    except Exception as exc:
        raise HTTPException(422, f"解析失败: {exc}") from exc


@router.post("/stores/{store_id}/import/orders")
async def import_orders_endpoint(
    store_id: str,
    file: UploadFile = File(...),
    source: str = Query("platform_export"),
    confidence: str = Query("high"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """导入订单明细(订单号/时间/GMV/商品/数量)，利润按真实销量加权。"""
    content = await _read_upload(file)
    try:
        return import_orders(db, store_id, content, file.filename, source=source, confidence=confidence)
    except Exception as exc:
        raise HTTPException(422, f"解析失败: {exc}") from exc


@router.post("/stores/{store_id}/import/ops")
async def import_ops_endpoint(
    store_id: str,
    file: UploadFile = File(...),
    source: str = Query("platform_export"),
    confidence: str = Query("medium"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """导入运营指标(IM回复率/出餐率/准时率/商责取消率)。缺列不编造。"""
    content = await _read_upload(file)
    try:
        return import_ops_metrics(db, store_id, content, file.filename, source=source, confidence=confidence)
    except Exception as exc:
        raise HTTPException(422, f"解析失败: {exc}") from exc


@router.get("/stores/{store_id}/import/coverage")
def import_coverage(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """门店各维度数据覆盖度概览。"""
    return get_data_coverage(db, store_id)


@router.get("/stores/{store_id}/seed-launch")
def seed_launch_board(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """上线前 6 块能力的店长侧事实，不是 6 个老板按钮。"""
    from app.services.seed_launch import load_store, seed_launch_status

    if load_store(db, store_id) is None:
        raise HTTPException(404, "store not found")
    return seed_launch_status(db, store_id)
