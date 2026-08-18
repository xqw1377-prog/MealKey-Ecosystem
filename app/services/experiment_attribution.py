"""Experiment Attribution Service.

把已过观察窗的 pending 实验自动归因：计算 lift_pct → 落库 result → 沉淀 strategy_memory。

闭环修复点（审计 P0）：
- 之前 experiment.result 只能靠商家手动调用 /evaluate 接口写入；
- growth/menu 等 30+ 处读取 experiment.result 来调整优先级、抑制重复动作；
- 结果 plan_progress_pct 永远卡 0%、learning_summary 永远显示"还没完成实验"。
本服务提供单店 / 全量两种调用方式，并被 celery beat 与 dev 路由复用。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import ItemFunnelDaily, ReviewFact
from app.models.ohre import Experiment, Recommendation
from app.services.store_state import build_store_state
from app.services.strategy_memory import upsert_strategy_memory_from_experiment
from app.services.truth_resolution import production_funnel_clause

logger = logging.getLogger(__name__)

# 归因阈值（与 routes_workspace._evaluate_experiment_record 保持一致）
LIFT_POSITIVE_THRESHOLD = 2.0
LIFT_NEGATIVE_THRESHOLD = -2.0
FAILED_VERIFICATION = "FAILED_VERIFICATION"


def _loads_dict(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _emit_verification_failure(db: Session, experiment: Experiment, exc: BaseException) -> None:
    logger.error("FAILED_VERIFICATION experiment=%s: %s", experiment.id, exc)
    try:
        from app.services.agent_event_log import AgentEventLog

        AgentEventLog(db, store_id=experiment.store_id, session_id=f"verify:{experiment.id}").error(
            message=FAILED_VERIFICATION,
            context={"experiment_id": experiment.id, "error": str(exc), "type": type(exc).__name__},
        )
    except Exception:  # noqa: BLE001 — 事件日志失败不能再次吞掉归因失败本身
        logger.exception("failed to emit FAILED_VERIFICATION event for %s", experiment.id)


def _mark_failed_verification(db: Session, experiment: Experiment, exc: BaseException) -> None:
    experiment.result = "unknown"
    note = (experiment.notes or "").strip()
    marker = FAILED_VERIFICATION
    experiment.notes = f"{note} {marker}".strip() if note else marker
    db.add(experiment)
    _emit_verification_failure(db, experiment, exc)


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
    if metric == "rating":
        return _item_rating(db, item_id, from_day, to_day)
    return None


def _item_rating(db: Session, item_id: str, from_day, to_day) -> Optional[float]:
    start = datetime.combine(from_day, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(to_day, datetime.max.time(), tzinfo=timezone.utc)
    val = db.execute(
        select(func.avg(ReviewFact.rating)).where(
            ReviewFact.item_id == item_id,
            ReviewFact.reviewed_at >= start,
            ReviewFact.reviewed_at <= end,
            ReviewFact.rating.is_not(None),
        )
    ).scalar()
    return float(val) if val is not None else None


def _item_funnel_observed(db: Session, item_id: str, from_day, to_day) -> bool:
    count = db.execute(
        select(func.count()).select_from(ItemFunnelDaily).where(
            ItemFunnelDaily.item_id == item_id,
            ItemFunnelDaily.day >= from_day,
            ItemFunnelDaily.day <= to_day,
            production_funnel_clause(ItemFunnelDaily.data_source),
        )
    ).scalar() or 0
    return count > 0


def _mark_unknown(experiment: Experiment, reason: str, note: str) -> AttributionOutcome:
    experiment.result = "unknown"
    experiment.attribution_quality = "low"
    experiment.notes = note
    experiment.lift_pct = None
    return AttributionOutcome(
        experiment_id=experiment.id,
        store_id=experiment.store_id,
        result="unknown",
        lift_pct=None,
        skipped=True,
        reason=reason,
    )


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
    funnel_metrics = {"ctr", "cvr", "impressions"}

    if experiment.item_id:
        attribution_scope = "item"
        if metric_name in funnel_metrics and not _item_funnel_observed(
            db, experiment.item_id, state.window.from_day, state.window.to_day
        ):
            return _mark_unknown(
                experiment,
                "funnel_missing",
                "缺少真实商品漏斗，无法自动判定这次动作的结果。",
            )
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
        if metric_name in funnel_metrics:
            metric = state.kpis.get(metric_name)
            if metric is None or metric.observed_value is None:
                return _mark_unknown(
                    experiment,
                    "funnel_missing",
                    "缺少门店漏斗读数，无法自动判定这次动作的结果。",
                )
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

    # ── 护栏检查:不只看主指标,还要检查利润/投流是否恶化 ──
    guardrail_warnings: list[str] = []
    try:
        # 检查利润护栏:到手率是否下降
        profit_now = state.profit
        if profit_now and profit_now.take_home_rate is not None:
            # 如果到手率低于 50%,即使主指标涨了也可能在买流水
            if profit_now.take_home_rate < 0.5:
                guardrail_warnings.append(
                    f"到手率仅 {profit_now.take_home_rate:.0%},可能为了冲量牺牲了利润"
                )
                if result == "positive":
                    note += "(但到手率偏低,注意利润)"
    except Exception as exc:  # noqa: BLE001 — P0-8: 护栏自身故障不能静默
        # 不能让本该降级 neutral 的 positive 在护栏自身故障时漏网保留 positive。
        # 记 warning + 追加告警，交由下面的统一降级逻辑处理。
        logger.warning("profit guardrail check failed for experiment=%s: %s", experiment.id, exc)
        guardrail_warnings.append("利润护栏检查失败，无法确认到手率安全")

    # 检查投流护栏:CPC 是否在实验期间上涨
    try:
        from app.models.business_facts import AdSpendDaily

        ads_rows = list(
            db.execute(
                select(AdSpendDaily)
                .where(
                    AdSpendDaily.store_id == experiment.store_id,
                    AdSpendDaily.day >= state.window.from_day,
                    AdSpendDaily.day <= state.window.to_day,
                )
                .order_by(AdSpendDaily.day)
            ).scalars()
        )
        if len(ads_rows) >= 2:
            cpc_first = ads_rows[0].cpc
            cpc_last = ads_rows[-1].cpc
            if cpc_first and cpc_last and cpc_first > 0:
                cpc_change = (cpc_last - cpc_first) / cpc_first * 100
                if cpc_change > 15:
                    guardrail_warnings.append(
                        f"实验期间 CPC 上涨 {cpc_change:.0f}%,投流成本在恶化"
                    )
    except Exception as exc:  # noqa: BLE001 — P0-8: 护栏自身故障不能静默
        logger.warning("cpc guardrail check failed for experiment=%s: %s", experiment.id, exc)
        guardrail_warnings.append("投流护栏检查失败，无法确认 CPC 安全")

    # 如果护栏告警,降级 positive → neutral
    if guardrail_warnings and result == "positive":
        result = "neutral"
        note = note + "。" + ";".join(guardrail_warnings)

    experiment.baseline_value = baseline
    experiment.observed_value = observed
    experiment.observe_from = state.window.from_day
    experiment.observe_to = state.window.to_day
    experiment.lift_pct = lift_pct
    experiment.attribution_quality = attribution_quality
    experiment.result = result
    experiment.notes = f"{metric_name}（{scope_label}）{note}"
    db.add(experiment)

    # P1-A: 回写预估-实际对账数据到 recommendation。失败必须显式 FAILED_VERIFICATION。
    try:
        rec = db.get(Recommendation, experiment.recommendation_id)
        if rec:
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
            rec.content_json = json.dumps(content, ensure_ascii=False)
            db.add(rec)
    except Exception as exc:  # noqa: BLE001
        _mark_failed_verification(db, experiment, exc)
        return AttributionOutcome(
            experiment_id=experiment.id,
            store_id=experiment.store_id,
            result="unknown",
            lift_pct=lift_pct,
            reason=FAILED_VERIFICATION,
        )

    # 同步沉淀策略记忆（upsert 内部会 commit，这里保持原行为）
    try:
        upsert_strategy_memory_from_experiment(db, experiment)
    except Exception as exc:  # noqa: BLE001
        logger.error("strategy_memory upsert failed for %s: %s", experiment.id, exc)
        _mark_failed_verification(db, experiment, exc)
        return AttributionOutcome(
            experiment_id=experiment.id,
            store_id=experiment.store_id,
            result="unknown",
            lift_pct=lift_pct,
            reason=FAILED_VERIFICATION,
        )

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
            _mark_failed_verification(db, experiment, exc)
            outcomes.append(
                AttributionOutcome(
                    experiment_id=experiment.id,
                    store_id=store_id,
                    result="unknown",
                    lift_pct=experiment.lift_pct,
                    skipped=True,
                    reason=f"{FAILED_VERIFICATION}:{type(exc).__name__}",
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
