"""把 Recommendation.execute 落到系统内真实变更（能改的改，不能改的诚实标记）。

原则：
- 菜单/商品类：写 MenuItem / MenuItemVersion
- 平台禁写类（投流/评价/CRM…）：只建观察窗，标注 awaiting_platform
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Menu, MenuItem, MenuItemVersion
from app.models.ohre import Recommendation

# 系统内可真正落库的动作
IN_SYSTEM_ACTIONS = {
    "change_title",
    "adjust_price_value",
    "add_set_meal",
    "change_main_image",
    "menu_patch",
    "menu_cleanup",
}


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _item_id_from_ref(object_ref: str) -> str | None:
    if object_ref and object_ref.startswith("item:"):
        return object_ref.split(":", 1)[1]
    return None


def _ensure_menu(db: Session, store_id: str) -> Menu:
    menu = db.execute(
        select(Menu)
        .where(Menu.store_id == store_id, Menu.status == "active")
        .order_by(Menu.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if menu:
        return menu
    menu = Menu(store_id=store_id, name="默认菜单", status="active")
    db.add(menu)
    db.flush()
    return menu


def _clone_version(
    item: MenuItem,
    *,
    name: str | None = None,
    price: float | None = None,
    image_url: str | None = None,
    description: str | None = None,
    category: str | None = None,
    source: str,
) -> MenuItemVersion:
    current = item.current_version
    return MenuItemVersion(
        item_id=item.id,
        name=name if name is not None else (current.name if current else "未命名"),
        category=category if category is not None else (current.category if current else None),
        price=price if price is not None else (current.price if current else None),
        description=description if description is not None else (current.description if current else None),
        image_url=image_url if image_url is not None else (current.image_url if current else None),
        source=source,
    )


def _apply_product_domain(db: Session, rec: Recommendation, content: dict[str, Any]) -> dict[str, Any]:
    suggestion = content.get("product_suggestion") or {}
    gen = suggestion.get("generated_content") or {}
    action = rec.action_type
    item_id = _item_id_from_ref(rec.object_ref)
    now = datetime.now(timezone.utc)

    if action == "add_set_meal":
        menu = _ensure_menu(db, rec.store_id)
        new_item = MenuItem(store_id=rec.store_id, menu_id=menu.id, is_active=True)
        db.add(new_item)
        db.flush()
        bundle_name = gen.get("bundle_name") or suggestion.get("title") or "新套餐"
        version = MenuItemVersion(
            item_id=new_item.id,
            name=bundle_name,
            category="套餐",
            price=gen.get("suggested_price"),
            description=suggestion.get("detail"),
            source="executor_set_meal",
        )
        db.add(version)
        db.flush()
        new_item.current_version_id = version.id
        db.add(new_item)
        rec.object_ref = f"item:{new_item.id}"
        return {
            "applied": True,
            "mode": "in_system",
            "action": action,
            "detail": f"已创建套餐「{bundle_name}」",
            "item_id": new_item.id,
            "at": now.isoformat(),
        }

    if not item_id:
        return {"applied": False, "mode": "failed", "reason": "缺少商品 object_ref", "action": action}

    item = db.get(MenuItem, item_id)
    if item is None or item.store_id != rec.store_id:
        return {"applied": False, "mode": "failed", "reason": "商品不存在", "action": action}

    if action == "change_title":
        new_title = gen.get("suggested_title") or gen.get("title_candidate") or suggestion.get("title")
        if not new_title:
            return {"applied": False, "mode": "failed", "reason": "无新标题", "action": action}
        version = _clone_version(item, name=new_title, source="executor_title")
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        db.add(item)
        return {
            "applied": True,
            "mode": "in_system",
            "action": action,
            "detail": f"标题已更新为「{new_title}」",
            "item_id": item.id,
            "at": now.isoformat(),
        }

    if action == "adjust_price_value":
        new_price = gen.get("suggested_price")
        current = item.current_version
        if new_price is None and current and current.price is not None:
            # 价值校准：默认保持原价，但写入 value_points 说明（审计可追溯）
            new_price = current.price
        version = _clone_version(
            item,
            price=float(new_price) if new_price is not None else None,
            description=(
                (current.description or "")
                + " | 价值点："
                + "、".join(gen.get("value_points") or [])
            ).strip(" |"),
            source="executor_price",
        )
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        db.add(item)
        return {
            "applied": True,
            "mode": "in_system",
            "action": action,
            "detail": f"价格/价值表达已更新（¥{new_price:g}）" if new_price is not None else "价值表达已更新",
            "item_id": item.id,
            "at": now.isoformat(),
        }

    if action == "change_main_image":
        # 系统内可落：写入 visual_brief 对应的占位图 URL（或已有 image_url）
        image_url = gen.get("image_url") or gen.get("optimized_image_url")
        if not image_url:
            brief = gen.get("visual_brief") or suggestion.get("detail") or "optimized"
            # 可回滚的系统内占位：标记为 MealKey 优化稿，真实平台替换仍需商家授权
            image_url = f"mealkey://optimized-main-image/{item.id}?v={int(now.timestamp())}"
        version = _clone_version(
            item,
            image_url=image_url,
            description=(item.current_version.description if item.current_version else None)
            or gen.get("visual_brief"),
            source="executor_main_image",
        )
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        db.add(item)
        return {
            "applied": True,
            "mode": "in_system",
            "action": action,
            "detail": "主图优化稿已写入系统（平台侧仍需同步/授权上传）",
            "item_id": item.id,
            "image_url": image_url,
            "at": now.isoformat(),
            "platform_sync_required": True,
        }

    return {"applied": False, "mode": "unsupported", "action": action}


def _apply_menu_cleanup(db: Session, rec: Recommendation, content: dict[str, Any]) -> dict[str, Any]:
    item_id = _item_id_from_ref(rec.object_ref)
    if not item_id:
        cleanup = content.get("menu_cleanup") or {}
        # 尝试从 payload 取
        item_id = cleanup.get("item_id")
    if not item_id:
        return {"applied": False, "mode": "failed", "reason": "cleanup 缺少 item_id", "action": "menu_cleanup"}
    item = db.get(MenuItem, item_id)
    if item is None or item.store_id != rec.store_id:
        return {"applied": False, "mode": "failed", "reason": "商品不存在", "action": "menu_cleanup"}
    item.is_active = False
    db.add(item)
    return {
        "applied": True,
        "mode": "in_system",
        "action": "menu_cleanup",
        "detail": f"已停用商品 {item_id}",
        "item_id": item_id,
        "at": datetime.now(timezone.utc).isoformat(),
    }


def _apply_menu_patch(db: Session, rec: Recommendation, content: dict[str, Any]) -> dict[str, Any]:
    patch = content.get("menu_patch") or {}
    name = patch.get("item_name") or patch.get("name")
    if not name:
        return {"applied": False, "mode": "failed", "reason": "menu_patch 缺少菜名", "action": "menu_patch"}
    menu = _ensure_menu(db, rec.store_id)
    item = MenuItem(store_id=rec.store_id, menu_id=menu.id, is_active=True)
    db.add(item)
    db.flush()
    version = MenuItemVersion(
        item_id=item.id,
        name=name,
        category=patch.get("suggested_category") or patch.get("category"),
        price=patch.get("suggested_price") or patch.get("price"),
        description=patch.get("reason") or patch.get("detail"),
        source="executor_menu_patch",
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    db.add(item)
    rec.object_ref = f"item:{item.id}"
    return {
        "applied": True,
        "mode": "in_system",
        "action": "menu_patch",
        "detail": f"已新建菜品「{name}」",
        "item_id": item.id,
        "at": datetime.now(timezone.utc).isoformat(),
    }


def execute_recommendation_domain(db: Session, rec: Recommendation) -> dict[str, Any]:
    """对已采纳的 Recommendation 做系统内落库；返回执行摘要。"""
    content = _loads(rec.content_json)
    action = rec.action_type or ""

    # 已执行过系统内变更则幂等返回
    if content.get("executed_in_system"):
        return {
            "applied": True,
            "mode": "in_system",
            "action": action,
            "detail": "此前已在系统内执行",
            "idempotent": True,
        }

    result: dict[str, Any]
    if action in {"change_title", "adjust_price_value", "add_set_meal", "change_main_image"} or content.get(
        "source"
    ) == "product_agent":
        # 若 action 空但有 product_suggestion，用 suggestion.action_type
        if action not in IN_SYSTEM_ACTIONS:
            suggestion = content.get("product_suggestion") or {}
            action = suggestion.get("action_type") or action
            rec.action_type = action
        result = _apply_product_domain(db, rec, content)
    elif action == "menu_cleanup" or "menu_cleanup" in content:
        result = _apply_menu_cleanup(db, rec, content)
    elif action == "menu_patch" or "menu_patch" in content:
        result = _apply_menu_patch(db, rec, content)
    elif action == "add_set_meal" and "menu_bundle" in content:
        # menu agent 套餐：转成新建套餐商品
        bundle = content.get("menu_bundle") or {}
        content = {
            **content,
            "product_suggestion": {
                "action_type": "add_set_meal",
                "title": bundle.get("title") or "套餐",
                "detail": bundle.get("reason"),
                "generated_content": {
                    "bundle_name": bundle.get("bundle_name") or bundle.get("title"),
                    "suggested_price": bundle.get("suggested_price"),
                },
            },
        }
        rec.action_type = "add_set_meal"
        result = _apply_product_domain(db, rec, content)
    else:
        result = {
            "applied": False,
            "mode": "awaiting_platform",
            "action": action,
            "detail": "该动作需在外卖平台后台操作，系统已进入观察窗等待你确认执行结果。",
            "at": datetime.now(timezone.utc).isoformat(),
        }

    # 回写 content_json 审计
    content["domain_execution"] = result
    if result.get("applied"):
        content["executed_in_system"] = True
    rec.content_json = json.dumps(content, ensure_ascii=False)
    db.add(rec)
    return result
