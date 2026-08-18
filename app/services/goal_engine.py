"""Goal Engine — 长期目标的创建、进度同步、偏差检测。

第 3 类触发（历史事项）+ 第 5 类触发（目标偏差）的核心引擎。
老板设定一次,AI 持续推进 + 定期比对预测。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.goal import Goal
from app.schemas.goal import GoalCreateRequest, GoalSnapshot, GoalView
from app.services.store_state import build_store_state


# metric → StoreState KPI 字段的映射
_METRIC_TO_KPI = {
    "gmv": "gmv",
    "orders": "orders",
    "ctr": "ctr",
    "cvr": "cvr",
    "rating": "rating",
    "take_home_rate": "take_home_rate",
}


def create_goal(
    db: Session,
    store_id: str,
    request: GoalCreateRequest,
) -> Goal:
    """创建一个长期目标。"""
    goal = Goal(
        store_id=store_id,
        raw_text=request.raw_text,
        metric=request.metric,
        target_value=request.target_value,
        deadline=request.deadline,
        status="active",
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def _goal_to_view(goal: Goal) -> GoalView:
    """ORM → View，计算 gap_pct 和 on_track。"""
    gap_pct = None
    on_track = None
    if goal.target_value and goal.gap is not None:
        gap_pct = round(goal.gap / goal.target_value * 100, 1) if goal.target_value else None
    if goal.forecast_value is not None and goal.target_value:
        # rank 类（越小越好）单独处理
        if goal.metric == "rank":
            on_track = goal.forecast_value <= goal.target_value
        else:
            on_track = goal.forecast_value >= goal.target_value * 0.95
    return GoalView(
        id=goal.id,
        store_id=goal.store_id,
        raw_text=goal.raw_text,
        metric=goal.metric,
        target_value=goal.target_value,
        deadline=goal.deadline,
        status=goal.status,
        current_value=goal.current_value,
        forecast_value=goal.forecast_value,
        gap=goal.gap,
        gap_pct=gap_pct,
        on_track=on_track,
        last_synced_at=goal.last_synced_at,
        created_at=goal.created_at,
    )


def _read_metric_from_state(metric: str, store_state) -> Optional[float]:
    """从 StoreState 读取指标当前值。"""
    if metric == "take_home_rate":
        return store_state.profit.take_home_rate
    kpi_name = _METRIC_TO_KPI.get(metric)
    if kpi_name is None:
        return None
    kpi = store_state.kpis.get(kpi_name)
    if kpi is None:
        return None
    return getattr(kpi, "observed_value", None)


def update_goal_progress(db: Session, store_id: str, *, days: int = 7) -> int:
    """同步所有 active 目标的进度。

    从 StoreState 读当前值，简单线性预测（当前值按剩余天数外推），
    算 gap。返回更新的目标数。
    """
    goals = list(
        db.execute(
            select(Goal).where(Goal.store_id == store_id, Goal.status == "active")
        ).scalars()
    )
    if not goals:
        return 0

    store_state = build_store_state(db=db, store_id=store_id, days=days)
    if store_state is None:
        return 0

    today = date.today()
    updated = 0
    for goal in goals:
        current = _read_metric_from_state(goal.metric, store_state)
        goal.current_value = current
        goal.last_synced_at = today

        # 趋势外推：优先日序列回归；否则用窗口 delta_pct
        remaining_days = 30
        if goal.deadline:
            remaining_days = max(1, (goal.deadline - today).days)
        forecast = current
        if current is not None and goal.metric in {"gmv", "orders"}:
            from app.models.entities import ShopFunnelDaily
            from app.services.truth_resolution import production_funnel_clause

            from_day = today.fromordinal(today.toordinal() - 13)
            col = ShopFunnelDaily.gmv if goal.metric == "gmv" else ShopFunnelDaily.orders
            series = [
                float(v or 0)
                for _, v in db.execute(
                    select(ShopFunnelDaily.day, col)
                    .where(
                        ShopFunnelDaily.store_id == store_id,
                        ShopFunnelDaily.day >= from_day,
                        ShopFunnelDaily.day <= today,
                        production_funnel_clause(ShopFunnelDaily.data_source),
                    )
                    .order_by(ShopFunnelDaily.day.asc())
                ).all()
            ]
            if len(series) >= 3:
                n = len(series)
                xs = list(range(n))
                mean_x = sum(xs) / n
                mean_y = sum(series) / n
                denom = sum((x - mean_x) ** 2 for x in xs) or 1.0
                slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, series)) / denom
                daily = max(0.0, mean_y + slope * (n - 1))
                # 保守：当前值 + 0.35 × 外推日贡献
                forecast = round(current + daily * remaining_days * 0.35, 2)
        elif current is not None:
            kpi_name = _METRIC_TO_KPI.get(goal.metric)
            if kpi_name:
                kpi = store_state.kpis.get(kpi_name)
                if kpi and kpi.delta_pct is not None:
                    extrapolation_factor = min(remaining_days / 7.0, 3.0)
                    trend_delta = current * (kpi.delta_pct / 100.0) * extrapolation_factor
                    forecast = current - trend_delta if goal.metric == "rank" else current + trend_delta
                else:
                    # 新店或无 delta_pct：用日均×剩余天数做保守线性外推
                    if goal.metric in {"gmv", "orders"} and current > 0:
                        daily_avg = current / max(1, store_state.window.days or 7)
                        forecast = round(current + daily_avg * remaining_days * 0.3, 2)
                    # 其他指标无趋势数据时 forecast=current（标注低置信度）
                    # gap 仍会算，只是不外推趋势

        if goal.target_value and forecast is not None:
            if goal.metric == "rank":
                # rank 越小越好，gap = forecast - target（正=还差多少名）
                goal.gap = forecast - goal.target_value
            else:
                goal.gap = goal.target_value - forecast
                # 已达成
                if forecast >= goal.target_value:
                    goal.status = "achieved"
        goal.forecast_value = forecast
        db.add(goal)
        updated += 1

    db.commit()
    return updated


def check_goal_deviation(db: Session, store_id: str) -> list[GoalView]:
    """检测目标偏差，返回需要提醒老板的目标（on_track=False 且未达成）。"""
    goals = list(
        db.execute(
            select(Goal).where(Goal.store_id == store_id, Goal.status == "active")
        ).scalars()
    )
    alerts: list[GoalView] = []
    for goal in goals:
        view = _goal_to_view(goal)
        if view.on_track is False and view.forecast_value is not None:
            alerts.append(view)
    return alerts


def load_goal_snapshot(db: Session, store_id: str) -> GoalSnapshot:
    """加载门店所有目标的快照。"""
    goals = list(
        db.execute(
            select(Goal).where(Goal.store_id == store_id).order_by(Goal.created_at.desc())
        ).scalars()
    )
    active: list[GoalView] = []
    achieved: list[GoalView] = []
    deviation: list[GoalView] = []
    for goal in goals:
        view = _goal_to_view(goal)
        if goal.status == "achieved":
            achieved.append(view)
        elif goal.status == "active":
            active.append(view)
            if view.on_track is False:
                deviation.append(view)
    return GoalSnapshot(
        store_id=store_id,
        active_goals=active,
        achieved_goals=achieved,
        deviation_alerts=deviation,
    )
