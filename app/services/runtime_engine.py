"""MealKey Runtime Engine — AI 店长 24h 状态机（Runtime V1）。

核心：根据当前时间 + 门店营业节奏，确定 AI 该做什么。
不写死时间——围绕餐段节点 + 实时事件运转。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.schemas.runtime import (
    DailyOperatingPlan,
    build_daily_operating_state,
    OperatingBudget,
    RuntimeState,
)


def _hour_local() -> int:
    """当前小时（本地时区）。"""
    return datetime.now().astimezone().hour


def determine_runtime_state(
    *,
    hour: int | None = None,
    store_open_hour: int = 10,
    lunch_start: int = 11,
    lunch_end: int = 13,
    dinner_start: int = 17,
    dinner_end: int = 20,
    store_close_hour: int = 22,
) -> RuntimeState:
    """根据当前时间 + 门店营业节奏，确定 Runtime 状态。

    不是写死时间——参数化门店营业时间。
    """
    h = hour if hour is not None else _hour_local()

    # 凌晨 2-6: 数据结算后，Night Learn
    if 2 <= h < 6:
        return "night_learn"
    # 6-9: 昨日数据完整，Deep Review
    if 6 <= h < store_open_hour - 1:
        return "daily_deep_review"
    # 开店前 1 小时: Pre-Open Check
    if store_open_hour - 1 <= h < store_open_hour:
        return "pre_open_check"
    # 高峰前 1 小时: Pre-Peak Decision
    if lunch_start - 1 <= h < lunch_start:
        return "pre_peak_decision"
    # 午高峰: Peak Protect
    if lunch_start <= h < lunch_end:
        return "peak_protect"
    # 午餐后到晚餐前: Inter-Peak Strategy（含 Post-Peak Review）
    if lunch_end <= h < dinner_start - 1:
        return "inter_peak_strategy"
    # 晚餐高峰前 1 小时: Pre-Peak Decision
    if dinner_start - 1 <= h < dinner_start:
        return "pre_peak_decision"
    # 晚高峰: Peak Protect
    if dinner_start <= h < dinner_end:
        return "peak_protect"
    # 晚餐后到关店: Post-Peak Review → Day Close
    if dinner_end <= h < store_close_hour:
        return "post_peak_review"
    # 关店后: Day Close → Night Learn
    return "day_close"


def build_daily_operating_plan(
    db: Session,
    store_id: str,
    *,
    days: int = 7,
) -> DailyOperatingPlan:
    """生成今日 AI 店长工作计划（材料 §12）。

    Deep Review 完成后调用，不需要完整展示给老板。
    """
    from app.services.agents import build_agent_context
    from app.services.goal_engine import load_goal_snapshot
    from app.services.thread_engine import load_active_threads

    plan = DailyOperatingPlan(date=datetime.now().astimezone().strftime("%Y-%m-%d"))
    current_state = determine_runtime_state()
    runtime_snapshot = build_daily_operating_state(current_state=current_state)
    plan.current_runtime_state = current_state
    plan.current_meal_period = runtime_snapshot.current_meal_period

    # 核心目标
    try:
        goals = load_goal_snapshot(db, store_id)
        if goals.active_goals:
            plan.core_goal = goals.active_goals[0].raw_text
        elif goals.deviation_alerts:
            plan.core_goal = f"追回偏差：{goals.deviation_alerts[0].raw_text}"
    except Exception:  # noqa: BLE001
        pass

    # 重点餐段
    plan.focus_meal_period = "lunch"  # V1 默认午餐

    # 当前主实验
    try:
        ctx = build_agent_context(db=db, store_id=store_id, days=days)
        if ctx:
            active_exps = [e for e in ctx.experiments if e.result == "pending"]
            if active_exps:
                rec = next((r for r in ctx.recommendations if r.id == active_exps[0].recommendation_id), None)
                plan.active_experiment = rec.action_type if rec else "实验进行中"
    except Exception:  # noqa: BLE001
        pass

    # 需要保护的指标
    plan.protected_metrics = ["贡献利润率", "到手率"]

    # 自主执行预算
    try:
        from app.services.mue import ensure_understanding

        mu = ensure_understanding(db, store_id=store_id, agents=None)
        budget = build_operating_budget(mu)
        plan.auto_exec_budget = {
            "ads_daily_limit": budget.ads_daily_limit_cny,
            "review_auto": budget.review_auto_reply,
            "price_range": budget.price_auto_adjust_range,
        }
    except Exception:  # noqa: BLE001
        pass

    # 需要继续的 WorkThread
    try:
        threads = load_active_threads(db, store_id)
        plan.active_threads = [t.title for t in threads[:3]]
    except Exception:  # noqa: BLE001
        pass

    # 检查节点
    plan.check_points = ["10:30", "14:00", "17:00", "数据结算后"]

    return plan


def build_operating_budget(mu: Any) -> OperatingBudget:
    """从 MerchantUnderstanding 构建 OperatingBudget。"""
    from app.schemas.runtime import OperatingBudget

    budget = OperatingBudget()
    try:
        budget.ads_daily_limit_cny = mu.permissions.ads_auto_daily_limit_cny
        budget.review_auto_reply = mu.permissions.auto_reply_good_reviews or mu.permissions.low_risk_auto_ok
        if mu.constraints.profit_floor_rate:
            budget.activity_profit_floor_pct = mu.constraints.profit_floor_rate
    except Exception:  # noqa: BLE001
        pass
    return budget


def run_night_learn(db: Session, store_id: str) -> dict:
    """Night Learn 状态：数据结算后回收实验 + 更新画像 + Strategy Memory。

    材料定义：回收实验、更新用户画像、竞品变化、Strategy Memory。
    原则上不打扰老板。
    """
    results = {"status": "completed", "actions": []}

    # 1. 回收实验（调实验归因）
    try:
        from app.services.experiment_attribution import attribute_store_experiments

        outcomes = attribute_store_experiments(db, store_id, days=7, only_observed=True)
        evaluated = [o for o in outcomes if not o.skipped]
        if evaluated:
            results["actions"].append(f"回收了 {len(evaluated)} 个实验")
    except Exception:  # noqa: BLE001
        pass

    # 2. 更新 Goal 进度
    try:
        from app.services.goal_engine import update_goal_progress

        updated = update_goal_progress(db, store_id, days=7)
        if updated:
            results["actions"].append(f"更新了 {updated} 个目标的进度")
    except Exception:  # noqa: BLE001
        pass

    # 3. 更新经营线程状态
    try:
        from app.services.agents import build_store_agents
        from app.services.thread_engine import sync_threads_from_agents

        agents = build_store_agents(db=db, store_id=store_id, days=7)
        if agents:
            threads = sync_threads_from_agents(db, store_id, agents)
            results["actions"].append(f"同步了 {len(threads)} 个经营线程")
    except Exception:  # noqa: BLE001
        pass

    results["summary"] = "；".join(results["actions"]) if results["actions"] else "今晚无需特别处理。"
    return results
