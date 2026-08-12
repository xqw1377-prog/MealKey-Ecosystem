"""Execution Plan — 把执行逻辑拆成「计划 + 应用」两层（P0-B 三段式）。

build_change_plan 只读不写，产出 ChangePlan（含 diff）。
_apply_plan 只做机械写入，记录回滚锚点。
preview 端点调 build_change_plan，execute 调 _apply_plan。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Menu, MenuItem, MenuItemVersion
from app.models.ohre import Recommendation


@dataclass
class FieldChange:
    field: str
    before: Any
    after: Any


@dataclass
class ChangePlan:
    action: str
    mode: str  # in_system / awaiting_platform / failed
    target_item_id: str | None = None
    creates_item: bool = False
    changes: list[FieldChange] = field(default_factory=list)
    detail: str = ""
    reason: str = ""
    platform_sync_required: bool = False
    expected: dict[str, Any] = field(default_factory=dict)
    reversible: bool = True


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _item_id_from_ref(object_ref: str) -> str | None:
    if object_ref and object_ref.startswith("item:"):
        return object_ref.split(":", 1)[1]
    return None


def build_change_plan(db: Session, rec: Recommendation) -> ChangePlan:
    """只读不写——决定要改什么，产出 diff。"""
    content = _loads(rec.content_json)
    action = rec.action_type or ""
    suggestion = content.get("product_suggestion") or {}
    gen = suggestion.get("generated_content") or {}
    cleanup = content.get("menu_cleanup") or {}
    patch = content.get("menu_patch") or {}
    bundle = content.get("menu_bundle") or {}
    expected = {
        "metric": rec.expected_metric or "orders",
        "estimated_lift_pct_low": rec.expected_lift_pct_low,
        "estimated_lift_pct_high": rec.expected_lift_pct_high,
        "window_hours": rec.window_hours,
    }

    # add_set_meal / menu_patch: 创建新商品
    if action in ("add_set_meal", "menu_patch") or (bundle and action == "add_set_meal"):
        if action == "menu_patch":
            name = patch.get("item_name") or patch.get("name", "")
            price = patch.get("suggested_price") or patch.get("price")
            category = patch.get("suggested_category") or patch.get("category")
        else:
            name = gen.get("bundle_name") or bundle.get("bundle_name") or suggestion.get("title") or "新套餐"
            price = gen.get("suggested_price") or bundle.get("suggested_price")
            category = "套餐"

        changes = [
            FieldChange("name", "(新建)", name),
            FieldChange("price", "(新建)", price),
            FieldChange("category", "(新建)", category or "未分类"),
            FieldChange("is_active", "(新建)", True),
        ]
        return ChangePlan(
            action=action or "add_set_meal",
            mode="in_system",
            creates_item=True,
            changes=changes,
            detail=f"将创建新商品「{name}」",
            expected=expected,
            reversible=True,
        )

    # menu_cleanup: 停用
    if action == "menu_cleanup":
        item_id = cleanup.get("item_id") or _item_id_from_ref(rec.object_ref)
        item = db.get(MenuItem, item_id) if item_id else None
        if not item or item.store_id != rec.store_id:
            return ChangePlan(action=action, mode="failed", reason="商品不存在", expected=expected)
        name = (item.current_version.name if item.current_version else item_id) or item_id
        return ChangePlan(
            action=action,
            mode="in_system",
            target_item_id=item_id,
            changes=[FieldChange("is_active", True, False)],
            detail=f"将停用商品「{name}」",
            expected=expected,
            reversible=True,
        )

    # 非系统内动作（投流/活动/评价等）：进观察窗，不算失败
    if action not in ("change_title", "adjust_price_value", "change_main_image"):
        return ChangePlan(
            action=action,
            mode="awaiting_platform",
            detail="该动作需在外卖平台后台操作，系统已进入观察窗。",
            expected=expected,
            reversible=False,
            platform_sync_required=True,
        )

    # change_title / adjust_price_value / change_main_image: 版本化变更
    item_id = _item_id_from_ref(rec.object_ref)
    if not item_id:
        return ChangePlan(action=action, mode="failed", reason="缺少商品 object_ref", expected=expected)

    item = db.get(MenuItem, item_id)
    if not item or item.store_id != rec.store_id:
        return ChangePlan(action=action, mode="failed", reason="商品不存在", expected=expected)

    current = item.current_version
    cur_name = current.name if current else ""
    cur_price = current.price if current else None
    cur_image = current.image_url if current else None
    cur_desc = current.description if current else ""

    changes: list[FieldChange] = []
    detail = ""
    platform_sync = False

    if action == "change_title":
        new_title = gen.get("suggested_title") or gen.get("title_candidate") or suggestion.get("title")
        if not new_title:
            return ChangePlan(action=action, mode="failed", reason="无新标题", expected=expected)
        changes.append(FieldChange("name", cur_name, new_title))
        detail = f"标题「{cur_name}」→「{new_title}」"

    elif action == "adjust_price_value":
        new_price = gen.get("suggested_price")
        if new_price is None and cur_price is not None:
            new_price = cur_price  # 价值校准保持原价
        changes.append(FieldChange("price", cur_price, new_price))
        detail = f"价格 ¥{cur_price} → ¥{new_price}" if cur_price != new_price else "价值表达更新（价格不变）"

    elif action == "change_main_image":
        new_image = gen.get("image_url") or gen.get("optimized_image_url")
        if not new_image:
            new_image = f"mealkey://optimized-main-image/{item_id}?v={int(datetime.now(timezone.utc).timestamp())}"
            platform_sync = True
        changes.append(FieldChange("image_url", cur_image or "(无图)", new_image))
        detail = "主图优化稿"
        if platform_sync:
            detail += "（平台侧仍需同步上传）"

    else:
        # 非系统内动作
        return ChangePlan(
            action=action,
            mode="awaiting_platform",
            detail="该动作需在外卖平台后台操作，系统已进入观察窗。",
            expected=expected,
            reversible=False,
            platform_sync_required=True,
        )

    return ChangePlan(
        action=action,
        mode="in_system",
        target_item_id=item_id,
        changes=changes,
        detail=detail,
        expected=expected,
        reversible=True,
        platform_sync_required=platform_sync,
    )


def apply_plan(db: Session, rec: Recommendation, plan: ChangePlan) -> dict[str, Any]:
    """机械写入——根据 plan 执行，记录回滚锚点。"""
    now = datetime.now(timezone.utc)
    content = _loads(rec.content_json)

    if plan.mode == "failed":
        return {"applied": False, "mode": "failed", "reason": plan.reason, "action": plan.action}
    if plan.mode == "awaiting_platform":
        return {
            "applied": False,
            "mode": "awaiting_platform",
            "action": plan.action,
            "detail": plan.detail,
            "at": now.isoformat(),
        }

    # 创建新商品
    if plan.creates_item:
        name = next((c.after for c in plan.changes if c.field == "name"), "新商品")
        price = next((c.after for c in plan.changes if c.field == "price"), None)
        category = next((c.after for c in plan.changes if c.field == "category"), None)
        # ensure menu
        menu = db.execute(
            select(Menu).where(Menu.store_id == rec.store_id, Menu.status == "active").limit(1)
        ).scalar_one_or_none()
        if not menu:
            menu = Menu(store_id=rec.store_id, name="默认菜单", status="active")
            db.add(menu)
            db.flush()
        item = MenuItem(store_id=rec.store_id, menu_id=menu.id, is_active=True)
        db.add(item)
        db.flush()
        version = MenuItemVersion(
            item_id=item.id, name=name, category=category, price=float(price) if price else None,
            source="executor_plan",
        )
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        db.add(item)
        rec.object_ref = f"item:{item.id}"
        result = {
            "applied": True, "mode": "in_system", "action": plan.action,
            "detail": plan.detail, "item_id": item.id,
            "created_item_id": item.id, "at": now.isoformat(),
        }
        content["domain_execution"] = result
        content["executed_in_system"] = True
        rec.content_json = json.dumps(content, ensure_ascii=False)
        db.add(rec)
        return result

    # 变更已有商品
    item_id = plan.target_item_id
    if not item_id:
        return {"applied": False, "mode": "failed", "reason": "无 target_item_id"}
    item = db.get(MenuItem, item_id)
    if not item:
        return {"applied": False, "mode": "failed", "reason": "商品不存在"}

    old_version_id = item.current_version_id

    # menu_cleanup: 停用
    if plan.action == "menu_cleanup":
        item.is_active = False
        db.add(item)
        result = {
            "applied": True, "mode": "in_system", "action": plan.action,
            "detail": plan.detail, "item_id": item_id,
            "previous_version_id": old_version_id, "at": now.isoformat(),
        }
        content["domain_execution"] = result
        content["executed_in_system"] = True
        rec.content_json = json.dumps(content, ensure_ascii=False)
        db.add(rec)
        return result

    # 版本化变更
    current = item.current_version
    new_name = next((c.after for c in plan.changes if c.field == "name"), None)
    new_price = next((c.after for c in plan.changes if c.field == "price"), None)
    new_image = next((c.after for c in plan.changes if c.field == "image_url"), None)

    version = MenuItemVersion(
        item_id=item.id,
        name=new_name if new_name is not None else (current.name if current else "未命名"),
        category=current.category if current else None,
        price=float(new_price) if new_price is not None else (current.price if current else None),
        description=current.description if current else None,
        image_url=new_image if new_image is not None else (current.image_url if current else None),
        source="executor_plan",
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    db.add(item)

    result = {
        "applied": True, "mode": "in_system", "action": plan.action,
        "detail": plan.detail, "item_id": item_id,
        "previous_version_id": old_version_id,
        "new_version_id": version.id,
        "at": now.isoformat(),
        "platform_sync_required": plan.platform_sync_required,
    }
    content["domain_execution"] = result
    content["executed_in_system"] = True
    rec.content_json = json.dumps(content, ensure_ascii=False)
    db.add(rec)
    return result


def rollback_recommendation(db: Session, rec: Recommendation) -> dict[str, Any]:
    """回滚已执行的系统内动作。"""
    content = _loads(rec.content_json)
    execution = content.get("domain_execution") or {}

    if content.get("rolled_back"):
        return {"applied": False, "mode": "idempotent", "reason": "已回滚过"}

    if not execution.get("applied"):
        return {"applied": False, "mode": "noop", "reason": "从未执行"}

    now = datetime.now(timezone.utc)

    # 创建类回滚：停用新商品
    created_id = execution.get("created_item_id")
    if created_id:
        item = db.get(MenuItem, created_id)
        if item:
            item.is_active = False
            db.add(item)
        content["rolled_back"] = True
        content["domain_execution"]["rolled_back_at"] = now.isoformat()
        rec.content_json = json.dumps(content, ensure_ascii=False)
        db.add(rec)
        return {"applied": True, "mode": "rolled_back", "detail": f"已停用回滚创建的商品 {created_id}", "at": now.isoformat()}

    # 版本类回滚：恢复 previous_version_id
    prev_id = execution.get("previous_version_id")
    item_id = execution.get("item_id")
    if prev_id and item_id:
        item = db.get(MenuItem, item_id)
        if item:
            item.current_version_id = prev_id
            db.add(item)
            content["rolled_back"] = True
            content["domain_execution"]["rolled_back_at"] = now.isoformat()
            rec.content_json = json.dumps(content, ensure_ascii=False)
            db.add(rec)
            return {"applied": True, "mode": "rolled_back", "detail": f"已恢复到版本 {prev_id}", "at": now.isoformat()}

    # cleanup 回滚：重新激活
    if execution.get("action") == "menu_cleanup" and item_id:
        item = db.get(MenuItem, item_id)
        if item:
            item.is_active = True
            db.add(item)
            content["rolled_back"] = True
            content["domain_execution"]["rolled_back_at"] = now.isoformat()
            rec.content_json = json.dumps(content, ensure_ascii=False)
            db.add(rec)
            return {"applied": True, "mode": "rolled_back", "detail": f"已重新激活商品 {item_id}", "at": now.isoformat()}

    return {"applied": False, "mode": "unsupported", "reason": "无法回滚此类型动作"}
