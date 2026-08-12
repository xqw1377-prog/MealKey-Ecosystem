"""Experiment Attribution Service.

把已过观察窗的 pending 实验自动归因：计算 lift_pct → 落库 result → 沉淀 strategy_memory。

闭环修复点（审计 P0）：
- 之前 experiment.result 只能靠商家手动调用 /evaluate 接口写入；
- growth/menu 等 30+ 处读取 experiment.result 来调整优先级、抑制重复动作；
- 结果 plan_progress_pct 永远卡 0%、learning_summary 永远显示"还没完成实验"。
本服务提供单店 / 全量两种调用方式，并被 celery beat 与 dev 路由复用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import ItemFunnelDaily
from app.models.ohre import Experiment, Recommendation
from app.services.store_state import build_store_state
from app.services.strategy_memory import upsert_strategy_memory_from_experiment

logger = logging.getLogger(__name__)

# 归因阈值（与 routes_workspace._evaluate_experiment_record 保持一致）
LIFT_POSITIVE_THRESHOLD = 2.0
LIFT_NEGATIVE_THRESHOLD = -2.0


@dataclass
class AttributionOutcome:
    experiment_id: str
    store_id: str
    result: str
    lift_pct: Optional[float]
    skipped: bool = False
    reason: str = ""


def _item_metric_value(
    db: Session, item_id: str, metric: str, from_day, to_day
) -> Optional[float]:
    """商品级窗口聚合。与 routes_workspace._item_metric_value 同口径，避免分叉。"""
    stmt = (
        select(
            func.coalesce(func.sum(ItemFunnelDaily.orders), 0).label("orders"),
            func.coalesce(func.sum(ItemFunnelDaily.impressions), 0).label("impressions"),
            func.coalesce(func.sum(ItemFunnelDaily.visits), 0).label("visits"),
            func.coalesce(func.sum(ItemFunnelDaily.gmv), 0).label("gmv"),
        )
        .where(ItemFunnelDaily.item_id == item_id)
        .where(ItemFunnelDaily.day >= from_day)
        .where(ItemFunnelDaily.day <= to_day)
    )
    row = db.execute(stmt).mappings().one()
    orders = float(row["orders"] or 0)
    impressions = float(row["impressions"] or 0)
    visits = float(row["visits"] or 0)
    gmv = float(row["gmv"] or 0)
    if metric == "orders":
        return orders
    if metric == "gmv":
        return gmv
    if metric == "impressions":
        return impressions
    if metric == "ctr":
        return (visits / impressions) if impressions else None
    if metric == "cvr":
        return (orders / visits) if visits else None
    return None


def _classify(lift_pct: Optional[float]) -> tuple[str, str]:
    """返回 (result, notes 模板占位说明)。"""
    if lift_pct is None:
        return "unknown", "缺少足够口径，暂时无法判断动作结果。"
    if lift_pct >= LIFT_POSITIVE_THRESHOLD:
        return "positive", f"相比基线提升 {lift_pct:.1f}%，建议继续当前动作。"
    if lift_pct <= LIFT_NEGATIVE_THRESHOLD:
        return "negative", f"相比基线下降 {lift_pct:.1f}%，建议按回滚条件处理。"
    return "neutral", f"相比基线变化 {lift_pct:.1f}%，还不足以支持放大动作。"


def evaluate_experiment(
    db: Session, experiment: Experiment, *, days: int = 7, force: bool = False
) -> AttributionOutcome:
    """对单条实验计算 lift 并落库 result。不 commit，由调用方控制事务。

    force=True 时即使已有终态也重算（供手动 evaluate API 强制刷新用）。
    """
    rec = db.get(Recommendation, experiment.recommendation_id)
    if rec is None:
        return AttributionOutcome(
            experiment_id=experiment.id,
            store_id=experiment.store_id,
            result=experiment.result,
            lift_pct=experiment.lift_pct,
            skipped=True,
            reason="recommendation_missing",
        )

    # 已有终态（非 pending）的不重复计算，避免覆盖商家手动标注（force 除外）
    if not force and experiment.result not in {None, "pending"}:
        return AttributionOutcome(
            experiment_id=experiment.id,
            store_id=experiment.store_id,
            result=experiment.result,
            lift_pct=experiment.lift_pct,
            skipped=True,
            reason=f"already_{experiment.result}",
        )

    state = build_store_state(db=db, store_id=experiment.store_id, days=days)
    if state is None:
        return AttributionOutcome(
            experiment_id=experiment.id,
            store_id=experiment.store_id,
            result=experiment.result,
            lift_pct=experiment.lift_pct,
            skipped=True,
            reason="store_state_unavailable",
        )

    metric_name = rec.expected_metric
    baseline = experiment.baseline_value
    observed: Optional[float] = None
    attribution_scope = "store"

    if experiment.item_id:
        attribution_scope = "item"
        observed = _item_metric_value(
            db, experiment.item_id, metric_name, state.window.from_day, state.window.to_day
        )
        if baseline is None:
            baseline = _item_metric_value(
                db,
                experiment.item_id,
                metric_name,
                state.window.compare_from_day,
                state.window.compare_to_day,
            )
    else:
        metric = state.kpis.get(metric_name)
        if baseline is None:
            baseline = metric.baseline_value if metric else None
        observed = metric.observed_value if metric else None

    lift_pct: Optional[float] = None
    if baseline not in (None, 0) and observed is not None:
        lift_pct = (observed - baseline) / baseline * 100.0

    # 归因质量：item 单变量执行时可信度最高
    executed_count = db.execute(
        select(func.count(Recommendation.id)).where(
            Recommendation.store_id == experiment.store_id,
            Recommendation.status == "executed",
        )
    ).scalar_one()
    if attribution_scope == "item" and executed_count <= 1:
        attribution_quality = "high"
    elif attribution_scope == "item":
        attribution_quality = "medium"
    else:
        attribution_quality = "medium" if executed_count <= 1 else "low"

    result, note = _classify(lift_pct)
    scope_label = "商品漏斗" if attribution_scope == "item" else "门店 KPI"

    experiment.baseline_value = baseline
    experiment.observed_value = observed
    experiment.observe_from = state.window.from_day
    experiment.observe_to = state.window.to_day
    experiment.lift_pct = lift_pct
    experiment.attribution_quality = attribution_quality
    experiment.result = result
    experiment.notes = f"{metric_name}（{scope_label}）{note}"
    db.add(experiment)

    # P1-A: 回写预估-实际对账数据到 recommendation
    try:
        rec = db.get(Recommendation, experiment.recommendation_id)
        if rec:
            import json as _json
            content = _loads_dict(rec.content_json)
            expected_high = float(rec.expected_lift_pct_high or 0)
            actual_lift = float(lift_pct) if lift_pct is not None else 0.0
            if expected_high > 0 and actual_lift >= expected_high * 0.8:
                verdict = "beat" if actual_lift >= expected_high else "met"
            elif actual_lift > 0:
                verdict = "partial"
            else:
                verdict = "missed"
            content["verification"] = {
                "expected_lift_pct": expected_high,
                "actual_lift_pct": round(actual_lift, 1),
                "verdict": verdict,
                "attribution_quality": attribution_quality,
                "metric": metric_name,
            }
            rec.content_json = _json.dumps(content, ensure_ascii=False)
            db.add(rec)
    except Exception:  # noqa: BLE001
        pass

    # 同步沉淀策略记忆（upsert 内部会 commit，这里保持原行为）
    try:
        upsert_strategy_memory_from_experiment(db, experiment)
    except Exception as exc:  # noqa: BLE001
        logger.warning("strategy_memory upsert failed for %s: %s", experiment.id, exc)

    return AttributionOutcome(
        experiment_id=experiment.id,
        store_id=experiment.store_id,
        result=result,
        lift_pct=lift_pct,
        reason="evaluated",
    )


def attribute_store_experiments(
    db: Session,
    store_id: str,
    *,
    days: int = 7,
    only_observed: bool = True,
) -> list[AttributionOutcome]:
    """归因单店所有 pending 实验。

    only_observed=True（默认）：只处理观察窗已结束的实验。
        观察窗 = executed_at + window_hours（回退 168h / 7 天）。
    only_observed=False：处理该店所有 pending 实验（供手动强制触发）。
    """
    stmt = (
        select(Experiment)
        .where(Experiment.store_id == store_id, Experiment.result.in_((None, "pending")))
        .order_by(Experiment.created_at.desc())
    )
    experiments = list(db.execute(stmt).scalars().all())
    outcomes: list[AttributionOutcome] = []
    now = datetime.now(timezone.utc)

    for experiment in experiments:
        if only_observed:
            rec = db.get(Recommendation, experiment.recommendation_id)
            event_at = None
            if rec is not None:
                event_at = rec.executed_at or rec.adopted_at or rec.created_at
            if event_at is None:
                continue
            if event_at.tzinfo is None:
                event_at = event_at.replace(tzinfo=timezone.utc)
            window_hours = (rec.window_hours if rec else 168) or 168
            observe_until = event_at + timedelta(hours=window_hours)
            if observe_until > now:
                # 观察窗未结束，跳过
                continue
        try:
            outcome = evaluate_experiment(db, experiment, days=days)
            outcomes.append(outcome)
        except Exception as exc:  # noqa: BLE001
            logger.warning("evaluate_experiment failed for %s: %s", experiment.id, exc)
            outcomes.append(
                AttributionOutcome(
                    experiment_id=experiment.id,
                    store_id=store_id,
                    result=experiment.result,
                    lift_pct=experiment.lift_pct,
                    skipped=True,
                    reason=f"error:{type(exc).__name__}",
                )
            )
    db.commit()
    return outcomes


def attribute_all_stores_experiments(db: Session, *, days: int = 7) -> dict:
    """归因全店（供 celery beat 调用）。返回汇总。"""
    store_ids = list(
        db.execute(
            select(Experiment.store_id)
            .where(Experiment.result.in_((None, "pending")))
            .distinct()
        ).scalars()
    )
    summary = {
        "store_count": len(store_ids),
        "evaluated": 0,
        "skipped": 0,
        "positive": 0,
        "negative": 0,
        "neutral": 0,
        "unknown": 0,
        "stores": [],
    }
    for store_id in store_ids:
        outcomes = attribute_store_experiments(db, store_id, days=days, only_observed=True)
        if not outcomes:
            continue
        store_summary = {
            "store_id": store_id,
            "total": len(outcomes),
            "positive": sum(1 for o in outcomes if o.result == "positive"),
            "negative": sum(1 for o in outcomes if o.result == "negative"),
            "neutral": sum(1 for o in outcomes if o.result == "neutral"),
            "unknown": sum(1 for o in outcomes if o.result == "unknown"),
            "skipped": sum(1 for o in outcomes if o.skipped),
        }
        summary["stores"].append(store_summary)
        summary["evaluated"] += store_summary["total"] - store_summary["skipped"]
        summary["skipped"] += store_summary["skipped"]
        summary["positive"] += store_summary["positive"]
        summary["negative"] += store_summary["negative"]
        summary["neutral"] += store_summary["neutral"]
        summary["unknown"] += store_summary["unknown"]
    return summary
