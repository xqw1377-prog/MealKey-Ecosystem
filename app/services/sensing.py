"""Sensing layer builders: Platform Health / Profit / Benchmark / Customer / Business."""

from __future__ import annotations

from typing import Any, Optional

from app.schemas.store_state import (
    BenchmarkMetric,
    BenchmarkState,
    BusinessState,
    CustomerState,
    DeltaMetric,
    HealthSignal,
    PlatformHealthState,
    ProfitState,
)


def _status_from_threshold(
    value: Optional[float],
    *,
    good_above: Optional[float] = None,
    good_below: Optional[float] = None,
) -> str:
    if value is None:
        return "unknown"
    if good_above is not None:
        if value >= good_above:
            return "ok"
        if value >= good_above * 0.9:
            return "watch"
        return "risk"
    if good_below is not None:
        if value <= good_below:
            return "ok"
        if value <= good_below * 1.15:
            return "watch"
        return "risk"
    return "unknown"


def build_business_state(kpis: dict[str, DeltaMetric]) -> BusinessState:
    orders = kpis.get("orders")
    gmv = kpis.get("gmv")
    score = 72
    if orders and orders.delta_pct is not None:
        score += max(-20, min(18, orders.delta_pct))
    if gmv and gmv.delta_pct is not None:
        score += max(-10, min(10, gmv.delta_pct / 2))
    score = int(max(20, min(98, round(score))))

    judgment = "经营基本盘稳定。"
    if orders and orders.delta_pct is not None and orders.delta_pct < -5:
        judgment = f"订单较基线 {orders.delta_pct:.1f}%，需要先定位是流量、点击还是转化问题。"
    elif orders and orders.delta_pct is not None and orders.delta_pct > 5:
        judgment = f"订单较基线 +{orders.delta_pct:.1f}%，重点看增长是否健康（到手率/毛利）。"

    return BusinessState(
        health_score=score,
        orders=orders,
        gmv=gmv,
        impressions=kpis.get("impressions"),
        ctr=kpis.get("ctr"),
        cvr=kpis.get("cvr"),
        aov=kpis.get("aov"),
        judgment=judgment,
    )


def build_platform_health_state(
    *,
    store_rating: Optional[float],
    mid_bad_review_rate: Optional[float],
    decoration_completeness: Optional[float],
    hero_sku_in_stock_rate: Optional[float] = 1.0,
    activity_valid: Optional[bool] = True,
    open_status: str = "open",
) -> PlatformHealthState:
    """V1 uses available proxies; missing platform ops metrics stay unknown."""

    signals = [
        HealthSignal(
            key="store_rating",
            label="店铺评分",
            value=store_rating,
            unit="score",
            status=_status_from_threshold(store_rating, good_above=4.5),
            threshold=4.5,
        ),
        HealthSignal(
            key="mid_bad_review_rate",
            label="中差评率",
            value=mid_bad_review_rate,
            unit="pct",
            status=_status_from_threshold(
                (mid_bad_review_rate * 100) if mid_bad_review_rate is not None else None,
                good_below=12,
            ),
            threshold=0.12,
        ),
        HealthSignal(
            key="decoration_completeness",
            label="装修完整度",
            value=decoration_completeness,
            unit="pct",
            status=_status_from_threshold(
                (decoration_completeness * 100) if decoration_completeness is not None else None,
                good_above=70,
            ),
            threshold=0.7,
        ),
        HealthSignal(
            key="hero_sku_in_stock_rate",
            label="核心商品在售率",
            value=hero_sku_in_stock_rate,
            unit="pct",
            status=_status_from_threshold(
                (hero_sku_in_stock_rate * 100) if hero_sku_in_stock_rate is not None else None,
                good_above=95,
            ),
            threshold=0.95,
        ),
        HealthSignal(
            key="meal_prep_rate",
            label="出餐率",
            value=None,
            status="unknown",
            note="待平台运营指标接入",
        ),
        HealthSignal(
            key="im_reply_rate",
            label="IM回复率",
            value=None,
            status="unknown",
            note="待平台运营指标接入",
        ),
        HealthSignal(
            key="on_time_delivery_rate",
            label="配送准时率",
            value=None,
            status="unknown",
            note="待平台运营指标接入",
        ),
        HealthSignal(
            key="merchant_cancel_rate",
            label="商责取消率",
            value=None,
            status="unknown",
            note="待平台运营指标接入",
        ),
    ]

    risk_signals = [s for s in signals if s.status == "risk"]
    watch_signals = [s for s in signals if s.status == "watch"]
    known = [s for s in signals if s.status != "unknown"]
    score = 78
    score -= 12 * len(risk_signals)
    score -= 5 * len(watch_signals)
    if open_status == "closed":
        score -= 25
        risk_signals.append(
            HealthSignal(key="open_status", label="营业状态", status="risk", note="异常闭店")
        )
    if activity_valid is False:
        score -= 8
        watch_signals.append(
            HealthSignal(key="activity_valid", label="活动有效状态", status="watch", note="活动失效/将过期")
        )
    score = int(max(20, min(98, score)))

    if risk_signals:
        status = "risk"
        top = risk_signals[0]
        judgment = f"平台健康 {score}/100。当前最大风险：{top.label}{(' · ' + top.note) if top.note else ''}。"
    elif watch_signals:
        status = "watch"
        top = watch_signals[0]
        judgment = f"平台健康 {score}/100。需关注：{top.label}，暂未构成主风险。"
    elif not known:
        status = "unknown"
        top = None
        judgment = f"平台健康 {score}/100。关键运营指标尚未接入，先用评分/装修/在售代理判断。"
    else:
        status = "healthy"
        top = None
        judgment = f"平台健康 {score}/100。当前未见高风险平台项。"

    return PlatformHealthState(
        score=score,
        status=status,
        top_risk=top.label if top else None,
        judgment=judgment,
        open_status=open_status if open_status in {"open", "closed", "unknown"} else "unknown",
        store_rating=store_rating,
        mid_bad_review_rate=mid_bad_review_rate,
        hero_sku_in_stock_rate=hero_sku_in_stock_rate,
        decoration_completeness=decoration_completeness,
        activity_valid=activity_valid,
        signals=signals,
    )


def _proxy_contribution(
    *,
    gross_gmv: float,
    orders: Optional[float],
    ads_spend: float = 0.0,
    merchant_subsidy_proxy_rate: float = 0.08,
    commission_proxy_rate: float = 0.22,
) -> tuple[float, Optional[float], Optional[float]]:
    customer_paid = gross_gmv
    platform_commission = gross_gmv * commission_proxy_rate
    merchant_subsidy = gross_gmv * merchant_subsidy_proxy_rate
    merchant_revenue = max(0.0, customer_paid - platform_commission - merchant_subsidy - ads_spend)
    take_home = merchant_revenue / customer_paid if customer_paid else None
    per_order = (merchant_revenue / orders) if orders else None
    return merchant_revenue, take_home, per_order


def build_profit_state(
    *,
    gross_gmv: Optional[float],
    orders: Optional[float],
    ads_spend: Optional[float] = None,
    baseline_gmv: Optional[float] = None,
    baseline_orders: Optional[float] = None,
    merchant_subsidy_proxy_rate: float = 0.08,
    commission_proxy_rate: float = 0.22,
) -> ProfitState:
    if gross_gmv is None:
        return ProfitState(data_quality="missing", judgment="利润数据不足，活动/投流建议将更保守。")

    ads = float(ads_spend or 0)
    contribution_profit, take_home, per_order = _proxy_contribution(
        gross_gmv=gross_gmv,
        orders=orders,
        ads_spend=ads,
        merchant_subsidy_proxy_rate=merchant_subsidy_proxy_rate,
        commission_proxy_rate=commission_proxy_rate,
    )
    customer_paid = gross_gmv
    platform_commission = gross_gmv * commission_proxy_rate
    merchant_subsidy = gross_gmv * merchant_subsidy_proxy_rate

    take_home_delta = None
    contribution_delta = None
    if baseline_gmv is not None and baseline_gmv > 0:
        baseline_profit, baseline_thr, _ = _proxy_contribution(
            gross_gmv=baseline_gmv,
            orders=baseline_orders,
            ads_spend=ads,
            merchant_subsidy_proxy_rate=merchant_subsidy_proxy_rate,
            commission_proxy_rate=commission_proxy_rate,
        )
        if baseline_profit > 0:
            contribution_delta = ((contribution_profit - baseline_profit) / baseline_profit) * 100.0
        if baseline_thr and take_home is not None and baseline_thr > 0:
            take_home_delta = ((take_home - baseline_thr) / baseline_thr) * 100.0

    judgment = "利润口径目前为代理估算（佣金/补贴），接入真实账单后会更准。"
    if take_home is not None and take_home < 0.55:
        judgment = f"到手率约 {take_home:.0%}，活动与投流必须过利润门禁，避免买流水。"
    elif take_home is not None and take_home >= 0.65:
        judgment = f"到手率约 {take_home:.0%}，增长动作空间相对更健康。"
    if contribution_delta is not None and take_home_delta is not None:
        if contribution_delta > take_home_delta + 3:
            judgment = (
                f"贡献利润 {contribution_delta:+.1f}% ，到手率 {take_home_delta:+.1f}%。"
                " 利润跌幅小于流水时，不建议为冲单量重开大额优惠。"
            )

    return ProfitState(
        gross_gmv=gross_gmv,
        customer_paid=customer_paid,
        merchant_revenue=contribution_profit,
        platform_commission=platform_commission,
        merchant_subsidy=merchant_subsidy,
        ads_spend=ads,
        take_home_rate=take_home,
        take_home_rate_delta_pct=take_home_delta,
        contribution_margin=take_home,
        contribution_profit=contribution_profit,
        contribution_profit_delta_pct=contribution_delta,
        contribution_profit_per_order=per_order,
        data_quality="proxy",
        judgment=judgment,
    )


def build_benchmark_state(
    *,
    store_ctr: Optional[float],
    store_cvr: Optional[float],
    peer_ctr_values: list[float],
    peer_cvr_values: list[float],
) -> BenchmarkState:
    def _metric(key: str, label: str, store_value: Optional[float], peers: list[float]) -> BenchmarkMetric:
        if store_value is None or not peers:
            return BenchmarkMetric(key=key, label=label, store_value=store_value)
        ordered = sorted(peers)
        avg = sum(ordered) / len(ordered)
        top25_idx = max(0, int(len(ordered) * 0.75) - 1)
        top10_idx = max(0, int(len(ordered) * 0.90) - 1)
        top25 = ordered[top25_idx]
        top10 = ordered[top10_idx]
        gap_avg = ((store_value - avg) / avg * 100.0) if avg else None
        gap_top = ((store_value - top25) / top25 * 100.0) if top25 else None
        return BenchmarkMetric(
            key=key,
            label=label,
            store_value=round(store_value * 100, 2) if store_value <= 1 else round(store_value, 2),
            area_avg=round(avg * 100, 2) if avg <= 1 else round(avg, 2),
            top_25_pct=round(top25 * 100, 2) if top25 <= 1 else round(top25, 2),
            top_10_pct=round(top10 * 100, 2) if top10 <= 1 else round(top10, 2),
            gap_vs_avg_pct=round(gap_avg, 1) if gap_avg is not None else None,
            gap_vs_top25_pct=round(gap_top, 1) if gap_top is not None else None,
            unit="pct",
        )

    metrics = [
        _metric("ctr", "进店率(CTR)", store_ctr, peer_ctr_values),
        _metric("cvr", "下单率(CVR)", store_cvr, peer_cvr_values),
    ]
    available = bool(peer_ctr_values or peer_cvr_values)
    judgment = "商圈对标样本不足。"
    if available:
        ctr = metrics[0]
        cvr = metrics[1]
        parts = []
        if ctr.gap_vs_avg_pct is not None and ctr.gap_vs_avg_pct < -5:
            parts.append("进店率低于商圈均值，优先看首图/第一屏，而不是先降价。")
        if cvr.gap_vs_avg_pct is not None and cvr.gap_vs_avg_pct > 0 and ctr.gap_vs_avg_pct is not None and ctr.gap_vs_avg_pct < 0:
            parts.append("进店后购买能力不弱，问题更可能在第一眼吸引力。")
        if cvr.gap_vs_avg_pct is not None and cvr.gap_vs_avg_pct < -5:
            parts.append("下单转化低于商圈，应检查套餐/价格带/评价信任。")
        judgment = " ".join(parts) if parts else "关键漏斗指标接近商圈均值。"

    return BenchmarkState(
        available=available,
        peer_count=max(len(peer_ctr_values), len(peer_cvr_values)),
        metrics=metrics,
        judgment=judgment,
    )


def build_customer_state(
    *,
    repurchase_rate: Optional[float],
    repurchase_delta_pct: Optional[float],
) -> CustomerState:
    churn = "unknown"
    if repurchase_delta_pct is not None:
        if repurchase_delta_pct <= -10:
            churn = "high"
        elif repurchase_delta_pct <= -5:
            churn = "medium"
        else:
            churn = "low"
    judgment = "用户侧信号有限，暂用复购代理。"
    if repurchase_delta_pct is not None and repurchase_delta_pct < -5:
        judgment = f"复购较基线 {repurchase_delta_pct:.1f}%，应启动召回而非只做拉新。"
    return CustomerState(
        repurchase_rate=repurchase_rate,
        repurchase_delta_pct=repurchase_delta_pct,
        churn_risk_level=churn,
        judgment=judgment,
    )
