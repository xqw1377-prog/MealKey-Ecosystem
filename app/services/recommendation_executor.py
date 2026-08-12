"""把 Recommendation.execute 落到系统内真实变更（能改的改，不能改的诚实标记）。

原则：
- 菜单/商品类：写 MenuItem / MenuItemVersion
- 平台禁写类（投流/评价/CRM…）：只建观察窗，标注 awaiting_platform
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

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


def _normalize_action(rec: Recommendation, content: dict[str, Any]) -> str:
    """action 为空/非系统内时，从 content 结构推断真实动作类型。"""
    action = rec.action_type or ""
    if action in IN_SYSTEM_ACTIONS:
        return action
    suggestion = content.get("product_suggestion") or {}
    if suggestion.get("action_type"):
        rec.action_type = suggestion["action_type"]
    elif "menu_cleanup" in content:
        rec.action_type = "menu_cleanup"
    elif "menu_patch" in content:
        rec.action_type = "menu_patch"
    elif "menu_bundle" in content:
        rec.action_type = "add_set_meal"
    return rec.action_type or action


def execute_recommendation_domain(db: Session, rec: Recommendation) -> dict[str, Any]:
    """对已采纳的 Recommendation 做系统内落库；返回执行摘要。

    P0-B 单一逻辑源：预览（build_change_plan）与执行（apply_plan）
    共用同一份计划，杜绝「预览的 ≠ 执行的」漂移。
    """
    from app.services.execution_plan import apply_plan, build_change_plan

    content = _loads(rec.content_json)

    # 已执行过系统内变更则幂等返回
    if content.get("executed_in_system"):
        return {
            "applied": True,
            "mode": "in_system",
            "action": rec.action_type or "",
            "detail": "此前已在系统内执行",
            "idempotent": True,
        }

    _normalize_action(rec, content)
    plan = build_change_plan(db, rec)
    result = apply_plan(db, rec, plan)

    # apply_plan 只在 applied 时回写审计；失败/awaiting 也要落审计
    if not result.get("applied"):
        result.setdefault("at", datetime.now(timezone.utc).isoformat())
        content = _loads(rec.content_json)
        content["domain_execution"] = result
        rec.content_json = json.dumps(content, ensure_ascii=False)
        db.add(rec)
    return result
