"""User Intent Engine：人找 MealKey（Pull）— 目标 + 自然语言设置。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.schemas.goal import GoalCreateRequest


def _month_end() -> date:
    today = date.today()
    if today.month == 12:
        return date(today.year, 12, 31)
    next_month = date(today.year, today.month + 1, 1)
    return date.fromordinal(next_month.toordinal() - 1)


def _parse_goal(question: str) -> GoalCreateRequest | None:
    text = (question or "").strip()
    if not text:
        return None

    m = re.search(r"(?:这个月|本月|月内)?.{0,6}(?:做到|冲到|完成|达到)\s*(\d+(?:\.\d+)?)\s*万", text)
    if m:
        return GoalCreateRequest(
            raw_text=text,
            metric="gmv",
            target_value=float(m.group(1)) * 10000,
            deadline=_month_end(),
        )

    m = re.search(r"利润(?:率)?(?:拉回|拉到|做到|提到|提高到)?\s*(\d+(?:\.\d+)?)\s*%?", text)
    if m and ("利润" in text) and not re.search(r"利润优先|先赚钱", text):
        val = float(m.group(1))
        if val > 1:
            val = val / 100.0
        return GoalCreateRequest(
            raw_text=text,
            metric="take_home_rate",
            target_value=val,
            deadline=_month_end(),
        )

    if re.search(r"(前\s*三|top\s*3|Top\s*3)", text, re.I) and (
        "饭" in text or "菜" in text or "做到" in text or "帮我" in text
    ):
        return GoalCreateRequest(
            raw_text=text,
            metric="rank",
            target_value=3.0,
            deadline=_month_end(),
        )

    m = re.search(r"(?:多|增加|做到)\s*(\d+)\s*单", text)
    if m and ("午餐" in text or "今天" in text or "一天" in text) and "一小时" not in text and "每小时" not in text:
        return GoalCreateRequest(
            raw_text=text,
            metric="orders",
            target_value=float(m.group(1)),
            deadline=date.today(),
        )

    if re.search(r"(做到|帮我|目标|冲到|提升到)", text) and len(text) <= 40:
        if any(k in text for k in ("万", "单", "%", "前", "利润", "GMV", "营业额", "排名")):
            # 偏好类交给 MUE，不当成 Goal
            if re.search(r"利润优先|先赚钱|冲单量|交给你平衡", text):
                return None
            return GoalCreateRequest(
                raw_text=text,
                metric="custom",
                target_value=None,
                deadline=_month_end(),
            )

    return None


def _handle_goal_intent(db: Session, store_id: str, question: str) -> Optional[dict[str, Any]]:
    request = _parse_goal(question)
    if request is None:
        return None

    from app.services.goal_engine import create_goal, update_goal_progress
    from app.services.thread_engine import create_thread, load_active_threads

    goal = create_goal(db, store_id, request)
    try:
        update_goal_progress(db, store_id, days=7)
    except Exception:  # noqa: BLE001
        pass

    existing = [
        t
        for t in load_active_threads(db, store_id)
        if t.goal == goal.raw_text or t.title == goal.raw_text[:100]
    ]
    if not existing:
        create_thread(
            db,
            store_id,
            title=goal.raw_text[:100],
            goal_text=goal.raw_text,
            goal_id=goal.id,
        )

    metric_label = {
        "gmv": "营业额",
        "orders": "订单",
        "take_home_rate": "利润率",
        "rank": "排名",
        "custom": "目标",
    }.get(goal.metric, goal.metric)

    target_txt = ""
    if goal.target_value is not None:
        if goal.metric == "gmv":
            target_txt = f"¥{goal.target_value:,.0f}"
        elif goal.metric == "take_home_rate":
            target_txt = f"{goal.target_value * 100:.0f}%"
        elif goal.metric == "rank":
            target_txt = f"Top {int(goal.target_value)}"
        else:
            target_txt = str(goal.target_value)

    # 方案 A/B/C 对比（V1 §19 补全）：查缺口 → 产候选方案
    gap_text = ""
    candidate_plans: list[dict[str, Any]] = []
    try:
        current = goal.current_value or 0
        target = goal.target_value or 0
        gap_val = target - current
        if gap_val > 0:
            gap_text = f"当前 {current:.0f}，目标 {target:.0f}，缺口 {gap_val:.0f}"
            # 基于缺口生成候选方案
            if goal.metric in ("orders", "gmv"):
                candidate_plans = [
                    {"label": "A", "action": "午餐投流加预算", "expected_gain": f"+{int(gap_val*0.5)}单", "risk": "中", "needs_owner": False},
                    {"label": "B", "action": "放大29元套餐", "expected_gain": f"+{int(gap_val*0.3)}单", "risk": "低", "needs_owner": True},
                    {"label": "C", "action": "高价值老客召回", "expected_gain": f"+{int(gap_val*0.2)}单", "risk": "低", "needs_owner": False},
                ]
            elif goal.metric == "take_home_rate":
                candidate_plans = [
                    {"label": "A", "action": "退出低效补贴活动", "expected_gain": f"+{(gap_val*100):.1f}%", "risk": "低", "needs_owner": True},
                    {"label": "B", "action": "优化套餐结构提客单", "expected_gain": f"+{(gap_val*50):.1f}%", "risk": "中", "needs_owner": False},
                ]
    except Exception:  # noqa: BLE001
        pass

    plan_text = ""
    if candidate_plans:
        plan_lines = [f"缺口分析：{gap_text}", "", "我有几个方案："]
        for p in candidate_plans:
            owner_tag = "（需要你确认）" if p.get("needs_owner") else "（我可以直接做）"
            plan_lines.append(f"  方案{p['label']}：{p['action']}，预计 {p['expected_gain']}，风险{p['risk']}{owner_tag}")
        plan_text = "\n".join(plan_lines)

    actions = [
        f"已建立长期目标（{metric_label}{(' · ' + target_txt) if target_txt else ''}）",
        "已创建经营线程，后续会自动续航，不用你反复交代",
    ]
    if plan_text:
        actions.append(plan_text)
    else:
        actions.append("我会先检查商品、流量、活动和用户，需要你时再找你")

    return {
        "conclusion": f"明白。目标是：{goal.raw_text}",
        "actions": actions,
        "expected": "进入主动经营循环后，偏离计划或需要你拍板时我会出现在「现在需要你」",
        "confidence": "high",
        "candidate_plans": candidate_plans,
        "answer": f"明白。我来处理。\n\n目标：{goal.raw_text}\n\n"
        + "\n".join(f"{i+1}. {a}" for i, a in enumerate(actions)),
        "intent": "goal",
        "goal_id": goal.id,
        "mode": "poie_intent",
        "question": question,
        "question_type": "goal_intent",
    }


def handle_user_intent(db: Session, store_id: str, question: str) -> Optional[dict[str, Any]]:
    """Pull 入口：先自然语言设置（MUE），再目标（Goal）。

    都不是则返回 None → chief_agent。
    """
    from app.services.mue import handle_understanding_intent

    mue_hit = handle_understanding_intent(db, store_id, question)
    if mue_hit is not None:
        return mue_hit

    return _handle_goal_intent(db, store_id, question)
