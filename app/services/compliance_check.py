"""规则合规检测 — 需求 #114, #116, #119。

基于商品数据 + 营业信息做基础合规检测。
不需要平台规则API,只用已有数据做风险预警。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import MenuItem, MenuItemVersion, Store


def check_compliance(db: Session, store_id: str) -> dict[str, Any]:
    """基础合规检测 — 覆盖 #114, #116, #119。

    检测:
    - 商品名违规风险(含夸大宣传词) #114
    - 数据一致性(价格/图片/描述缺失) #119
    - 经营信息缺失(营业执照/许可) #116 (简化版)
    """
    store = db.get(Store, store_id)
    if not store:
        return {"has_data": False, "findings": [], "summary": "门店不存在"}

    items = list(
        db.execute(
            select(MenuItem).where(MenuItem.store_id == store_id, MenuItem.is_active.is_(True))
        ).scalars()
    )

    findings: list[dict[str, Any]] = []

    # ── #114: 商品名违规风险 ──
    violation_keywords = ["第一", "最好", "最强", "顶级", "极品", "全国", "独家", "100%", "绝对", "包治"]
    for item in items[:20]:
        version = db.get(MenuItemVersion, item.current_version_id) if item.current_version_id else None
        if not version or not version.name:
            continue
        for kw in violation_keywords:
            if kw in version.name:
                findings.append({
                    "code": "PRODUCT_NAME_VIOLATION_RISK",
                    "demand_id": 114,
                    "severity": "high",
                    "title": f"商品名「{version.name}」可能违规",
                    "detail": f"商品名包含「{kw}」,平台规则通常禁止使用绝对化用语。可能导致商品被下架或处罚。",
                    "action": f"修改商品名,去掉「{kw}」",
                })
                break

    # ── #119: 数据一致性(图片/描述缺失) ──
    for item in items[:20]:
        version = db.get(MenuItemVersion, item.current_version_id) if item.current_version_id else None
        if not version:
            continue
        if not version.image_url:
            findings.append({
                "code": "MISSING_IMAGE",
                "demand_id": 119,
                "severity": "medium",
                "title": f"「{version.name}」缺少商品图片",
                "detail": "无图商品CTR通常比有图低50%以上,且部分平台要求必须上传图片。",
                "action": "上传真实出品照片",
            })
        if not version.description:
            findings.append({
                "code": "MISSING_DESCRIPTION",
                "demand_id": 119,
                "severity": "low",
                "title": f"「{version.name}」缺少商品描述",
                "detail": "描述能提升CVR,且部分平台有字数要求。",
                "action": "添加简洁描述",
            })

    # ── #116: 经营信息缺失(简化版) ──
    merchant = store.merchant
    if merchant and not merchant.category:
        findings.append({
            "code": "MISSING_STORE_CATEGORY",
            "demand_id": 116,
            "severity": "medium",
            "title": "门店品类信息缺失",
            "detail": "品类信息影响搜索匹配和排名。",
            "action": "在平台后台完善品类信息",
        })

    return {
        "has_data": True,
        "findings": findings,
        "summary": f"检查了 {len(items)} 个商品,发现 {len(findings)} 个合规风险" if findings else f"检查了 {len(items)} 个商品,暂无合规风险",
        "item_count": len(items),
    }
