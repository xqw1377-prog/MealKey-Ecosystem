from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import ReviewFact, ShopFunnelDaily
from app.services.truth_resolution import production_funnel_clause
from app.schemas.agents import (
    DiagnosisComparison,
    DiagnosisMarketComparison,
    DiagnosisMetricSignal,
    DiagnosisRootCause,
)
from app.schemas.store_state import StoreState


METRIC_LABELS = {
    "gmv": "营业额",
    "orders": "订单量",
    "impressions": "曝光量",
    "ctr": "点击率",
    "cvr": "转化率",
    "aov": "客单价",
    "repurchase_rate": "复购率",
    "rating": "评分",
    "refund_rate": "退款率",
}


def _delta_pct(baseline: Optional[float], observed: Optional[float]) -> Optional[float]:
    if baseline in (None, 0) or observed is None:
        return None
    return (observed - baseline) / baseline * 100.0


def _aggregate_shop(db: Session, store_id: str, from_day: date, to_day: date) -> dict[str, Any] | None:
    row = db.execute(
        select(
            func.count(ShopFunnelDaily.day).label("days"),
            func.sum(ShopFunnelDaily.gmv).label("gmv"),
            func.sum(ShopFunnelDaily.orders).label("orders"),
            func.sum(ShopFunnelDaily.impressions).label("impressions"),
            func.sum(ShopFunnelDaily.visits).label("visits"),
            func.sum(ShopFunnelDaily.repurchase).label("repurchase"),
        )
        .where(ShopFunnelDaily.store_id == store_id)
        .where(ShopFunnelDaily.day >= from_day)
        .where(ShopFunnelDaily.day <= to_day)
        .where(production_funnel_clause(ShopFunnelDaily.data_source))
    ).mappings().one()
    if not row["days"]:
        return None
    orders = float(row["orders"] or 0)
    gmv = float(row["gmv"] or 0)
    impressions = float(row["impressions"] or 0)
    visits = float(row["visits"] or 0)
    repurchase = float(row["repurchase"] or 0)
    return {
        "days": int(row["days"]),
        "gmv": gmv,
        "orders": orders,
        "impressions": impressions,
        "visits": visits,
        "ctr": visits / impressions if impressions else None,
        "cvr": orders / visits if visits else None,
        "aov": gmv / orders if orders else None,
        "repurchase_rate": repurchase / orders if orders else None,
    }


def _average_rating(db: Session, store_id: str, from_day: date, to_day: date) -> Optional[float]:
    from_dt = datetime.combine(from_day, time.min, tzinfo=timezone.utc)
    to_dt = datetime.combine(to_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return db.execute(
        select(func.avg(ReviewFact.rating))
        .where(ReviewFact.store_id == store_id)
        .where(ReviewFact.reviewed_at >= from_dt)
        .where(ReviewFact.reviewed_at < to_dt)
    ).scalar_one_or_none()


def _comparison(
    db: Session,
    store_id: str,
    key: str,
    label: str,
    current_from: date,
    current_to: date,
    baseline_from: date,
    baseline_to: date,
) -> DiagnosisComparison:
    current = _aggregate_shop(db, store_id, current_from, current_to)
    baseline = _aggregate_shop(db, store_id, baseline_from, baseline_to)
    if current is None or baseline is None:
        return DiagnosisComparison(
            key=key,
            label=label,
            current_from=current_from.isoformat(),
            current_to=current_to.isoformat(),
            baseline_from=baseline_from.isoformat(),
            baseline_to=baseline_to.isoformat(),
            status="unavailable",
            note="当前历史数据不足，无法完成该周期对比。",
        )
    orders_delta = _delta_pct(baseline["orders"], current["orders"])
    gmv_delta = _delta_pct(baseline["gmv"], current["gmv"])
    available_deltas = [value for value in (orders_delta, gmv_delta) if value is not None]
    weakest = min(available_deltas) if available_deltas else None
    status = (
        "unavailable"
        if weakest is None
        else "down"
        if weakest <= -5
        else "up"
        if weakest >= 5
        else "stable"
    )
    return DiagnosisComparison(
        key=key,
        label=label,
        current_from=current_from.isoformat(),
        current_to=current_to.isoformat(),
        baseline_from=baseline_from.isoformat(),
        baseline_to=baseline_to.isoformat(),
        orders_delta_pct=orders_delta,
        gmv_delta_pct=gmv_delta,
        status=status,
        note=(
            f"订单 {orders_delta:+.1f}%｜营业额 {gmv_delta:+.1f}%"
            if orders_delta is not None and gmv_delta is not None
            else "当前周期存在零基线，无法计算可靠变化率。"
        ),
    )


def build_diagnosis_comparisons(db: Session, store_id: str) -> list[DiagnosisComparison]:
    yesterday = date.today() - timedelta(days=1)
    return [
        _comparison(
            db,
            store_id,
            "same_weekday",
            "昨日 vs 上周同日",
            yesterday,
            yesterday,
            yesterday - timedelta(days=7),
            yesterday - timedelta(days=7),
        ),
        _comparison(
            db,
            store_id,
            "week_over_week",
            "近 7 日 vs 前 7 日",
            yesterday - timedelta(days=6),
            yesterday,
            yesterday - timedelta(days=13),
            yesterday - timedelta(days=7),
        ),
        _comparison(
            db,
            store_id,
            "month_over_month",
            "近 30 日 vs 前 30 日",
            yesterday - timedelta(days=29),
            yesterday,
            yesterday - timedelta(days=59),
            yesterday - timedelta(days=30),
        ),
    ]


def _signal(metric: str, observed: Optional[float], baseline: Optional[float], confidence: float) -> DiagnosisMetricSignal:
    delta = _delta_pct(baseline, observed)
    if delta is None:
        severity = "unavailable"
        direction = "unknown"
    elif delta <= -12:
        severity = "critical"
        direction = "down"
    elif delta <= -5:
        severity = "warning"
        direction = "down"
    elif delta >= 5:
        severity = "positive"
        direction = "up"
    else:
        severity = "stable"
        direction = "flat"
    return DiagnosisMetricSignal(
        metric=metric,
        label=METRIC_LABELS[metric],
        observed_value=observed,
        baseline_value=baseline,
        delta_pct=delta,
        severity=severity,
        direction=direction,
        confidence=confidence,
    )


def build_diagnosis_signals(
    db: Session,
    store_state: StoreState,
) -> tuple[list[DiagnosisMetricSignal], list[str]]:
    signals = [
        _signal(
            key,
            store_state.kpis[key].observed_value,
            store_state.kpis[key].baseline_value,
            store_state.kpis[key].confidence,
        )
        for key in ("gmv", "orders", "impressions", "ctr", "cvr")
        if key in store_state.kpis
    ]
    observed = _aggregate_shop(db, store_state.store.store_id, store_state.window.from_day, store_state.window.to_day)
    baseline = _aggregate_shop(
        db,
        store_state.store.store_id,
        store_state.window.compare_from_day,
        store_state.window.compare_to_day,
    )
    for key in ("aov", "repurchase_rate"):
        signals.append(
            _signal(
                key,
                observed.get(key) if observed else None,
                baseline.get(key) if baseline else None,
                0.75 if key == "aov" else 0.6,
            )
        )
    observed_rating = _average_rating(
        db,
        store_state.store.store_id,
        store_state.window.from_day,
        store_state.window.to_day,
    )
    baseline_rating = _average_rating(
        db,
        store_state.store.store_id,
        store_state.window.compare_from_day,
        store_state.window.compare_to_day,
    )
    signals.append(_signal("rating", observed_rating, baseline_rating, 0.68))
    signals.append(_signal("refund_rate", None, None, 0.0))
    data_gaps = []
    if signals[-1].severity == "unavailable":
        data_gaps.append("当前数据模型没有退款字段，退款率明确标记为不可用。")
    if observed_rating is None or baseline_rating is None:
        data_gaps.append("评价历史不足，无法完成评分周期对比。")
    if not observed or observed.get("repurchase_rate") is None:
        data_gaps.append("复购数据不足，暂不对复购变化做强判断。")
    return signals, data_gaps


def build_diagnosis_root_causes(
    store_state: StoreState,
    signals: list[DiagnosisMetricSignal],
) -> list[DiagnosisRootCause]:
    signal_map = {row.metric: row for row in signals}
    roots: list[DiagnosisRootCause] = []
    orders = signal_map.get("orders")
    impressions = signal_map.get("impressions")
    ctr = signal_map.get("ctr")
    cvr = signal_map.get("cvr")
    aov = signal_map.get("aov")
    rating = signal_map.get("rating")

    if orders and orders.direction == "down":
        if impressions and impressions.direction == "down":
            roots.append(
                DiagnosisRootCause(
                    rank=1,
                    code="traffic_decline",
                    title="流量入口下降",
                    explanation="订单下滑同时伴随曝光下降，问题首先发生在流量和排序入口。",
                    confidence=0.86,
                    evidence=[
                        f"订单变化 {orders.delta_pct:.1f}%",
                        f"曝光变化 {impressions.delta_pct:.1f}%",
                    ],
                    affected_metrics=["orders", "impressions"],
                )
            )
        elif ctr and ctr.direction == "down":
            roots.append(
                DiagnosisRootCause(
                    rank=1,
                    code="first_impression",
                    title="第一眼点击竞争力下降",
                    explanation="曝光没有先下滑，但 CTR 明显下降，优先检查主推商品图文与价格感知。",
                    confidence=0.84,
                    evidence=[f"订单变化 {orders.delta_pct:.1f}%", f"CTR 变化 {ctr.delta_pct:.1f}%"],
                    affected_metrics=["orders", "ctr"],
                )
            )
        elif cvr and cvr.direction == "down":
            roots.append(
                DiagnosisRootCause(
                    rank=1,
                    code="conversion_weakness",
                    title="下单承接能力下降",
                    explanation="用户仍能看到并点击门店，但进入商品页后没有完成下单。",
                    confidence=0.82,
                    evidence=[f"订单变化 {orders.delta_pct:.1f}%", f"CVR 变化 {cvr.delta_pct:.1f}%"],
                    affected_metrics=["orders", "cvr"],
                )
            )
    if aov and aov.direction == "down":
        roots.append(
            DiagnosisRootCause(
                rank=len(roots) + 1,
                code="aov_decline",
                title="客单价与连带购买走弱",
                explanation="营业额承压的一部分来自客单下降，需要检查套餐和搭配品承接。",
                confidence=0.74,
                evidence=[f"客单价变化 {aov.delta_pct:.1f}%"],
                affected_metrics=["gmv", "aov"],
            )
        )
    if rating and rating.direction == "down":
        roots.append(
            DiagnosisRootCause(
                rank=len(roots) + 1,
                code="rating_decline",
                title="评价口碑走弱",
                explanation="评分下降会放大转化阻力，需要结合差评主题确认。",
                confidence=0.67,
                evidence=[f"评分变化 {rating.delta_pct:.1f}%"],
                affected_metrics=["rating", "cvr"],
            )
        )
    if store_state.competition_changes:
        roots.append(
            DiagnosisRootCause(
                rank=len(roots) + 1,
                code="competition_pressure",
                title="商圈竞争压力上升",
                explanation="竞品近期发生价格、商品或图片变化，可能造成相对分流，但缺少市场订单数据时仅作为辅助证据。",
                confidence=0.58,
                evidence=[row.summary for row in store_state.competition_changes[:2]],
                affected_metrics=["orders", "ctr", "cvr"],
            )
        )
    if not roots:
        roots.append(
            DiagnosisRootCause(
                rank=1,
                code="no_strong_anomaly",
                title="暂未发现单一强异常",
                explanation="核心指标没有形成一致的异常链路，继续观察并补齐缺失数据。",
                confidence=0.56,
                evidence=["当前指标变化未达到强异常阈值。"],
                affected_metrics=[],
            )
        )
    roots.sort(key=lambda row: row.confidence, reverse=True)
    return [row.model_copy(update={"rank": index + 1}) for index, row in enumerate(roots[:3])]


def build_market_comparison(store_state: StoreState) -> DiagnosisMarketComparison:
    own_delta = store_state.kpis.get("orders").delta_pct if "orders" in store_state.kpis else None
    if store_state.competition_changes:
        return DiagnosisMarketComparison(
            availability="partial",
            data_type="proxy",
            own_orders_delta_pct=own_delta,
            market_orders_delta_pct=None,
            relative_status="market_pressure_rising",
            note="当前只有竞品价格、商品和评分变化代理信号，没有商圈真实订单趋势，不能宣称市场份额变化。",
        )
    return DiagnosisMarketComparison(
        availability="unavailable",
        data_type="unavailable",
        own_orders_delta_pct=own_delta,
        market_orders_delta_pct=None,
        relative_status="unknown",
        note="尚未接入商圈订单趋势；本店与商圈份额判断暂不可用。",
    )


def diagnosis_score(signals: list[DiagnosisMetricSignal], data_gaps: list[str]) -> int:
    score = 88
    for signal in signals:
        score -= {"critical": 13, "warning": 7, "unavailable": 2}.get(signal.severity, 0)
        if signal.severity == "positive":
            score += 2
    score -= min(8, len(data_gaps) * 2)
    return max(28, min(96, score))
