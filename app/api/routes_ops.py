"""运营诊断 — 店长内部判断用，不给老板另开 12 个入口。

覆盖履约/SKU/体验/对账/排班/内容/新店/设备/合规。
老板只问店长；本路由给问诊闭环和内部复盘。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.ops_diagnosis import (
    diagnose_content_health,
    diagnose_device_health,
    diagnose_financial_reconciliation,
    diagnose_fulfillment,
    diagnose_new_store_setup,
    diagnose_order_detail,
    diagnose_order_experience,
    diagnose_settlement_detail,
    diagnose_sku_lifecycle,
    diagnose_sku_strategy,
    diagnose_staffing,
)
from app.services.compliance_check import check_compliance

router = APIRouter()


@router.get("/stores/{store_id}/diagnosis/fulfillment")
def get_fulfillment_diagnosis(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """履约产能诊断 — #84-89 (出餐/取消/包装/漏餐/产能/原料)。"""
    return diagnose_fulfillment(db, store_id)


@router.get("/stores/{store_id}/diagnosis/sku-lifecycle")
def get_sku_diagnosis(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """SKU生命周期诊断 — #141-149 (共用率/损耗/互斥/换季/套餐)。"""
    return diagnose_sku_lifecycle(db, store_id)


@router.get("/stores/{store_id}/diagnosis/order-experience")
def get_experience_diagnosis(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """下单体验诊断 — #164-169 (距离衰减/包装/预期差异/质量不稳定)。"""
    return diagnose_order_experience(db, store_id)


@router.get("/stores/{store_id}/diagnosis/financial")
def get_financial_diagnosis(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """基础财务对账 — #101-106 (GMV合理性/推广对账)。"""
    return diagnose_financial_reconciliation(db, store_id)


@router.get("/stores/{store_id}/diagnosis/all")
def get_all_diagnosis(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """全部诊断 — 一次性返回所有引擎的结果。"""
    return {
        "fulfillment": diagnose_fulfillment(db, store_id),
        "sku_lifecycle": diagnose_sku_lifecycle(db, store_id),
        "sku_strategy": diagnose_sku_strategy(db, store_id),
        "order_experience": diagnose_order_experience(db, store_id),
        "order_detail": diagnose_order_detail(db, store_id),
        "financial": diagnose_financial_reconciliation(db, store_id),
        "settlement": diagnose_settlement_detail(db, store_id),
        "staffing": diagnose_staffing(db, store_id),
        "content": diagnose_content_health(db, store_id),
        "store_setup": diagnose_new_store_setup(db, store_id),
        "device": diagnose_device_health(db, store_id),
        "compliance": check_compliance(db, store_id),
    }


@router.get("/stores/{store_id}/diagnosis/compliance")
def get_compliance_check(store_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """规则合规检测 — #114, #116, #119。"""
    return check_compliance(db, store_id)
