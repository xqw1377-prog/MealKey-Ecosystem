from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.services.truth_resolution import (
    confidence_for_sources,
    production_funnel_clause,
)

from app.models.business_facts import AdSpendDaily, OpsMetricDaily
from app.models.entities import (
    CompetitorMenuItem,
    CompetitorSnapshot,
    CompetitorStore,
    ItemFunnelDaily,
    MenuItem,
    OrderFact,
    OrderItemFact,
    ReviewFact,
    ReviewNLP,
    ShopFunnelDaily,
    Store,
    StoreCompetitorWatch,
)
from app.schemas.store_state import (
    CompetitionChange,
    CoreItem,
    DataCoverage,
    DeltaMetric,
    FeedbackInfo,
    MarketInfo,
    PrimaryProblem,
    StoreInfo,
    StoreState,
    WindowInfo,
)
from app.services.sensing import (
    build_benchmark_state,
    build_business_state,
    build_customer_state,
    build_platform_health_state,
    build_profit_state,
)


@dataclass
class _Window:
    observe_from: date
    observe_to: date
    baseline_from: date
    baseline_to: date


def _calc_window(days: int) -> _Window:
    # V1: observe = last N days (excluding today), baseline = previous N days
    if days < 1:
        raise ValueError("days must be >= 1")
    today = date.today()
    observe_to = today - timedelta(days=1)
    observe_from = observe_to - timedelta(days=days - 1)
    baseline_to = observe_from - timedelta(days=1)
    baseline_from = baseline_to - timedelta(days=days - 1)
    return _Window(observe_from=observe_from, observe_to=observe_to, baseline_from=baseline_from, baseline_to=baseline_to)


def _sum_shop(db: Session, store_id: str, from_day: date, to_day: date):
    stmt = (
        select(
            func.sum(ShopFunnelDaily.gmv).label("gmv"),
            func.sum(ShopFunnelDaily.orders).label("orders"),
            func.sum(ShopFunnelDaily.impressions).label("impressions"),
            func.sum(ShopFunnelDaily.visits).label("visits"),
            func.sum(ShopFunnelDaily.ads_spend).label("ads_spend"),
        )
        .where(ShopFunnelDaily.store_id == store_id)
        .where(ShopFunnelDaily.day >= from_day)
        .where(ShopFunnelDaily.day <= to_day)
        .where(production_funnel_clause(ShopFunnelDaily.data_source))
    )
    return db.execute(stmt).mappings().one()


def _funnel_sources(db: Session, store_id: str, from_day: date, to_day: date) -> list[str]:
    rows = db.execute(
        select(ShopFunnelDaily.data_source)
        .where(ShopFunnelDaily.store_id == store_id)
        .where(ShopFunnelDaily.day >= from_day)
        .where(ShopFunnelDaily.day <= to_day)
        .where(production_funnel_clause(ShopFunnelDaily.data_source))
        .distinct()
    ).scalars().all()
    from app.services.truth_resolution import LEGACY_UNKNOWN_SOURCE, normalize_source

    return [normalize_source(source) if source is not None else LEGACY_UNKNOWN_SOURCE for source in rows]


def _sum_ads(db: Session, store_id: str, from_day: date, to_day: date) -> Optional[float]:
    val = db.execute(
        select(func.sum(AdSpendDaily.cost)).where(
            AdSpendDaily.store_id == store_id,
            AdSpendDaily.day >= from_day,
            AdSpendDaily.day <= to_day,
        )
    ).scalar()
    return float(val) if val is not None else None


def _sum_orders(db: Session, store_id: str, from_day: date, to_day: date) -> tuple[Optional[float], Optional[float]]:
    start = datetime.combine(from_day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(to_day, time.max, tzinfo=timezone.utc)
    row = db.execute(
        select(
            func.sum(OrderFact.gmv).label("gmv"),
            func.count(OrderFact.id).label("orders"),
        ).where(
            OrderFact.store_id == store_id,
            OrderFact.ordered_at >= start,
            OrderFact.ordered_at <= end,
        )
    ).mappings().one()
    count = int(row["orders"] or 0)
    if count <= 0:
        return None, None
    return float(row["gmv"] or 0), float(count)


def _item_qty_map(db: Session, store_id: str, from_day: date, to_day: date) -> dict[str, float]:
    start = datetime.combine(from_day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(to_day, time.max, tzinfo=timezone.utc)
    rows = db.execute(
        select(OrderItemFact.item_id, func.sum(OrderItemFact.qty).label("qty"))
        .join(OrderFact, OrderItemFact.order_id == OrderFact.id)
        .where(
            OrderFact.store_id == store_id,
            OrderFact.ordered_at >= start,
            OrderFact.ordered_at <= end,
            OrderItemFact.item_id.is_not(None),
        )
        .group_by(OrderItemFact.item_id)
    ).all()
    return {str(item_id): float(qty or 0) for item_id, qty in rows if item_id}


def _avg_rating(db: Session, store_id: str, from_day: date, to_day: date) -> Optional[float]:
    start = datetime.combine(from_day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(to_day, time.max, tzinfo=timezone.utc)
    val = db.execute(
        select(func.avg(ReviewFact.rating)).where(
            ReviewFact.store_id == store_id,
            ReviewFact.reviewed_at >= start,
            ReviewFact.reviewed_at <= end,
            ReviewFact.rating.is_not(None),
        )
    ).scalar()
    return float(val) if val is not None else None


def _avg_ops(db: Session, store_id: str, from_day: date, to_day: date) -> dict[str, Optional[float]]:
    row = db.execute(
        select(
            func.avg(OpsMetricDaily.im_reply_rate).label("im_reply_rate"),
            func.avg(OpsMetricDaily.meal_prep_rate).label("meal_prep_rate"),
            func.avg(OpsMetricDaily.on_time_delivery_rate).label("on_time_delivery_rate"),
            func.avg(OpsMetricDaily.merchant_cancel_rate).label("merchant_cancel_rate"),
        ).where(
            OpsMetricDaily.store_id == store_id,
            OpsMetricDaily.day >= from_day,
            OpsMetricDaily.day <= to_day,
        )
    ).mappings().one()
    return {
        "im_reply_rate": float(row["im_reply_rate"]) if row["im_reply_rate"] is not None else None,
        "meal_prep_rate": float(row["meal_prep_rate"]) if row["meal_prep_rate"] is not None else None,
        "on_time_delivery_rate": float(row["on_time_delivery_rate"]) if row["on_time_delivery_rate"] is not None else None,
        "merchant_cancel_rate": float(row["merchant_cancel_rate"]) if row["merchant_cancel_rate"] is not None else None,
    }


def _has_synthetic_item_funnel(db: Session, item_ids: list[str], from_day: date, to_day: date) -> bool:
    if not item_ids:
        return False
    count = db.execute(
        select(func.count()).select_from(ItemFunnelDaily).where(
            ItemFunnelDaily.item_id.in_(item_ids),
            ItemFunnelDaily.day >= from_day,
            ItemFunnelDaily.day <= to_day,
            ItemFunnelDaily.data_source == "synthetic",
        )
    ).scalar() or 0
    return count > 0


def _delta_pct(baseline: Optional[float], observed: Optional[float]) -> Optional[float]:
    if baseline is None or observed is None:
        return None
    if baseline == 0:
        return None
    return (observed - baseline) / baseline * 100.0


def _aggregate_store_cost(
    menu_items: list[MenuItem],
    orders: Optional[float],
    qty_by_item: Optional[dict[str, float]] = None,
) -> dict:
    """从 MenuItem 缓存列聚合门店级成本。

    有订单明细时按真实销量加权；否则按订单均摊（并标成 allocated）。
    """
    items_with_cost = [
        i for i in menu_items
        if i.food_cost is not None or i.packaging_cost is not None
    ]
    if not items_with_cost:
        return {}

    used_qty = bool(qty_by_item)
    if used_qty:
        total_food = sum((i.food_cost or 0) * float(qty_by_item.get(i.id, 0)) for i in items_with_cost)
        total_pack = sum((i.packaging_cost or 0) * float(qty_by_item.get(i.id, 0)) for i in items_with_cost)
        if total_food <= 0 and total_pack <= 0:
            used_qty = False

    if not used_qty:
        n_items = len(items_with_cost) or 1
        est_orders_per_item = (orders or 0) / n_items if orders else 1.0
        total_food = sum((i.food_cost or 0) * est_orders_per_item for i in items_with_cost)
        total_pack = sum((i.packaging_cost or 0) * est_orders_per_item for i in items_with_cost)

    confidences = [i.cost_confidence for i in items_with_cost if i.cost_confidence]
    min_confidence = min(confidences, key=lambda c: {"high": 0, "medium": 1, "low": 2}.get(c, 9)) if confidences else "medium"
    sources = [i.cost_source for i in items_with_cost if i.cost_source]
    cost_source = sources[0] if sources else "observed"
    if not used_qty:
        cost_source = "allocated"

    return {
        "food_cost": total_food if total_food > 0 else None,
        "packaging_cost": total_pack if total_pack > 0 else None,
        "cost_source": cost_source,
        "cost_confidence": min_confidence,
    }


def _competitor_menu_map(db: Session, snapshot_id: str) -> dict[str, CompetitorMenuItem]:
    stmt = select(CompetitorMenuItem).where(CompetitorMenuItem.snapshot_id == snapshot_id)
    items = db.execute(stmt).scalars().all()
    return {
        "".join(char for char in item.name.strip().lower() if char.isalnum()): item
        for item in items
        if item.name.strip()
    }


def _build_competition_changes(db: Session, store_id: str, store: Store) -> list[CompetitionChange]:
    """
    V1 Competition 变化锚定逻辑：
    对门店商圈内每个竞品，比较最近两次快照（rating / 价格带 / 菜单），
    把真实发生的“改价 / 上新 / 评分变化”转成 CompetitionChange，
    供 Competition Agent 与首页“今日风险”使用。
    没有快照数据时返回空列表（由 Agent fallback 到商圈/价格带保守判断）。
    """
    changes: list[CompetitionChange] = []

    watched_ids = list(
        db.execute(
            select(StoreCompetitorWatch.c_store_id).where(
                StoreCompetitorWatch.store_id == store_id,
                StoreCompetitorWatch.active.is_(True),
            )
        ).scalars()
    )
    c_stmt = (
        select(CompetitorStore)
        .where(CompetitorStore.id.in_(watched_ids))
        .order_by(CompetitorStore.name)
    )
    competitors = db.execute(c_stmt).scalars().all()

    for competitor in competitors:
        snap_stmt = (
            select(CompetitorSnapshot)
            .where(CompetitorSnapshot.c_store_id == competitor.id)
            .order_by(CompetitorSnapshot.captured_at.desc())
            .limit(2)
        )
        snaps = list(db.execute(snap_stmt).scalars().all())
        if not snaps:
            # 没有快照历史，无法发现“变化”，跳过（仍会有基础评分逻辑在 Agent 端兜底）
            continue
        latest = snaps[0]
        prev = snaps[1] if len(snaps) > 1 else None

        # 1) 价格带变化 -> 竞品改价
        if prev is not None and latest.price_band_min is not None and latest.price_band_max is not None:
            prev_min = prev.price_band_min
            prev_max = prev.price_band_max
            if prev_min is not None and prev_max is not None:
                if latest.price_band_min < prev_min or latest.price_band_max < prev_max:
                    changes.append(
                        CompetitionChange(
                            c_store_id=competitor.id,
                            type="price_down",
                            summary=f"{competitor.name} 近期下调了价格带，价格竞争在加剧。",
                            price=latest.price_band_min,
                        )
                    )
                elif latest.price_band_max > prev_max:
                    changes.append(
                        CompetitionChange(
                            c_store_id=competitor.id,
                            type="price_up",
                            summary=f"{competitor.name} 近期上探更高价格带，正在抢中高端心智。",
                            price=latest.price_band_max,
                        )
                    )

        # 2) 评分变化 -> 竞品口碑变化
        if prev is not None and latest.rating is not None and prev.rating is not None:
            rating_gap = latest.rating - prev.rating
            if rating_gap >= 0.2:
                changes.append(
                    CompetitionChange(
                        c_store_id=competitor.id,
                        type="rating_up",
                        summary=f"{competitor.name} 评价回升（近期评分 +{rating_gap:.1f}），转化威胁上升。",
                    )
                )
            elif rating_gap <= -0.2:
                changes.append(
                    CompetitionChange(
                        c_store_id=competitor.id,
                        type="rating_down",
                        summary=f"{competitor.name} 评价回落（近期评分 {rating_gap:.1f}），口碑窗口打开。",
                    )
                )

        # 3) 菜单变化 -> 上新、删品、单品调价、换图
        if prev is not None:
            latest_menu = _competitor_menu_map(db, latest.id)
            previous_menu = _competitor_menu_map(db, prev.id)
            for key in latest_menu.keys() - previous_menu.keys():
                item = latest_menu[key]
                changes.append(
                    CompetitionChange(
                        c_store_id=competitor.id,
                        type="product_added",
                        summary=f"{competitor.name} 新增了「{item.name}」，正在扩充商品供给。",
                        price=item.price,
                    )
                )
            for key in previous_menu.keys() - latest_menu.keys():
                item = previous_menu[key]
                changes.append(
                    CompetitionChange(
                        c_store_id=competitor.id,
                        type="product_removed",
                        summary=f"{competitor.name} 下架了「{item.name}」，菜单结构出现调整。",
                        price=item.price,
                    )
                )
            for key in latest_menu.keys() & previous_menu.keys():
                latest_item = latest_menu[key]
                previous_item = previous_menu[key]
                if (
                    latest_item.price is not None
                    and previous_item.price is not None
                    and abs(latest_item.price - previous_item.price) >= 0.5
                ):
                    direction = "上调" if latest_item.price > previous_item.price else "下调"
                    changes.append(
                        CompetitionChange(
                            c_store_id=competitor.id,
                            type="product_price_changed",
                            summary=(
                                f"{competitor.name} 将「{latest_item.name}」价格"
                                f"{direction}至 ¥{latest_item.price:.1f}。"
                            ),
                            price=latest_item.price,
                        )
                    )
                if (
                    latest_item.image_url
                    and previous_item.image_url
                    and latest_item.image_url != previous_item.image_url
                ):
                    changes.append(
                        CompetitionChange(
                            c_store_id=competitor.id,
                            type="image_changed",
                            summary=f"{competitor.name} 更换了「{latest_item.name}」主图。",
                            price=latest_item.price,
                        )
                    )

    return changes[:6]


def _build_feedback(db: Session, store_id: str) -> FeedbackInfo:
    """
    V1 评价反馈聚合：
    用 ReviewFact.rating 计算情感基线，用 ReviewNLP 主题分（taste/portion/speed/package）
    输出关键词与维度得分，供首页评分还原与对话引用。
    没有评价数据时返回空桶。
    """
    review_stmt = (
        select(ReviewFact)
        .where(ReviewFact.store_id == store_id)
        .order_by(ReviewFact.reviewed_at.desc())
        .limit(200)
    )
    reviews = list(db.execute(review_stmt).scalars().all())

    keywords: list[dict] = []
    scores: dict[str, float] = {}

    if not reviews:
        return FeedbackInfo(keywords=keywords, scores=scores)

    # 情感基线：平均评分映射到 0-1
    ratings = [float(r.rating) for r in reviews if r.rating is not None]
    if ratings:
        avg_rating = sum(ratings) / len(ratings)
        scores["sentiment"] = round(max(0.0, min(1.0, (avg_rating - 1.0) / 4.0)), 3)
        scores["avg_rating"] = round(avg_rating, 2)

    # 主题分：聚合各 Underlying dimension 的平均值
    review_ids = [r.id for r in reviews]
    if review_ids:
        nlp_stmt = select(ReviewNLP).where(ReviewNLP.review_id.in_(review_ids))
        nlps = list(db.execute(nlp_stmt).scalars().all())
        if nlps:
            dims = {"taste": "口味", "portion": "份量", "speed": "出餐速度", "package": "包装"}
            for key, label in dims.items():
                values = [
                    float(getattr(n, key))
                    for n in nlps
                    if getattr(n, key) is not None
                ]
                if values:
                    scores[key] = round(sum(values) / len(values), 3)
                    keywords.append({"key": key, "label": label, "score": round(sum(values) / len(values), 3)})

    # 类型化关键词：按主题分从高到低排前5
    keywords.sort(key=lambda row: row.get("score") or 0, reverse=True)

    # ── 差评闭环信号:近 30 天评价的差评率 ──
    cutoff = date.today() - timedelta(days=30)
    recent_reviews = [r for r in reviews if r.reviewed_at and r.reviewed_at.date() >= cutoff]
    recent_bad = [r for r in recent_reviews if r.rating is not None and float(r.rating) <= 3.0]
    bad_rate = (len(recent_bad) / len(recent_reviews)) if recent_reviews else None
    recent_bad_samples = [
        {"rating": float(r.rating), "content": (r.content or "")[:100], "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None}
        for r in recent_bad[:5]
    ]

    return FeedbackInfo(
        keywords=keywords[:5],
        scores=scores,
        recent_review_count=len(recent_reviews),
        recent_bad_review_count=len(recent_bad),
        bad_review_rate=bad_rate,
        recent_bad_reviews=recent_bad_samples,
    )


def _build_ads_summary(db: Session, store_id: str, from_day: date, to_day: date):
    """从 AdSpendDaily 聚合投流摘要 + 调用 analyze_ads 诊断。"""
    from app.schemas.store_state import AdsSummary

    rows = list(
        db.execute(
            select(AdSpendDaily)
            .where(
                AdSpendDaily.store_id == store_id,
                AdSpendDaily.day >= from_day,
                AdSpendDaily.day <= to_day,
            )
            .order_by(AdSpendDaily.day)
        ).scalars()
    )
    if not rows:
        return AdsSummary()

    total_cost = sum(r.cost or 0 for r in rows)
    total_clicks = sum(r.clicks or 0 for r in rows)
    total_ads_orders = sum(r.orders_from_ads or 0 for r in rows)
    avg_cpc_vals = [r.cpc for r in rows if r.cpc is not None]
    avg_roas_vals = [r.roas for r in rows if r.roas is not None]
    avg_ctr_vals = [r.ctr for r in rows if r.ctr is not None]

    # CPC/ROAS 趋势
    cpc_trend = None
    roas_trend = None
    if len(rows) >= 2:
        first_cpc = rows[0].cpc
        last_cpc = rows[-1].cpc
        if first_cpc and last_cpc and first_cpc > 0:
            cpc_trend = round((last_cpc - first_cpc) / first_cpc * 100, 1)
        first_roas = rows[0].roas
        last_roas = rows[-1].roas
        if first_roas and last_roas and first_roas > 0:
            roas_trend = round((last_roas - first_roas) / first_roas * 100, 1)

    daily_rows = [
        {
            "day": r.day.isoformat() if r.day else "",
            "cost": r.cost,
            "clicks": r.clicks,
            "cpc": r.cpc,
            "roas": r.roas,
            "ctr": r.ctr,
        }
        for r in rows
    ]

    # 调用 analyze_ads 诊断
    from app.services.domain_skills import analyze_ads

    ads_result = analyze_ads(
        ads_daily=daily_rows,
        profit_floor=None,
        product_ready=True,
    )
    findings_text = [f"{f.title}: {f.description}" for f in ads_result.findings]

    return AdsSummary(
        total_cost=round(total_cost, 1),
        avg_daily_cost=round(total_cost / len(rows), 1),
        avg_cpc=round(sum(avg_cpc_vals) / len(avg_cpc_vals), 2) if avg_cpc_vals else None,
        avg_roas=round(sum(avg_roas_vals) / len(avg_roas_vals), 2) if avg_roas_vals else None,
        avg_ctr=round(sum(avg_ctr_vals) / len(avg_ctr_vals), 4) if avg_ctr_vals else None,
        total_clicks=total_clicks,
        total_ads_orders=total_ads_orders,
        cpc_trend_pct=cpc_trend,
        roas_trend_pct=roas_trend,
        days=len(rows),
        daily_rows=daily_rows[-7:],  # 最近7天
        findings=findings_text,
    )


def build_store_state(db: Session, store_id: str, days: int = 7) -> Optional[StoreState]:
    store = db.execute(
        select(Store)
        .options(
            joinedload(Store.merchant),
            joinedload(Store.items).joinedload(MenuItem.current_version),
        )
        .where(Store.id == store_id)
    ).unique().scalar_one_or_none()
    if store is None:
        return None
    item_name_map = {
        item.id: (item.current_version.name if item.current_version else "SKU")
        for item in (store.items or [])
    }

    w = _calc_window(days=days)
    base = _sum_shop(db, store_id, w.baseline_from, w.baseline_to)
    obs = _sum_shop(db, store_id, w.observe_from, w.observe_to)
    funnel_sources = _funnel_sources(db, store_id, w.baseline_from, w.observe_to)
    funnel_confidence = confidence_for_sources(funnel_sources)

    baseline_gmv = float(base["gmv"] or 0)
    observed_gmv = float(obs["gmv"] or 0)
    baseline_orders = float(base["orders"] or 0)
    observed_orders = float(obs["orders"] or 0)
    baseline_impr = float(base["impressions"] or 0)
    observed_impr = float(obs["impressions"] or 0)
    baseline_vis = float(base["visits"] or 0)
    observed_vis = float(obs["visits"] or 0)
    if funnel_confidence <= 0:
        baseline_gmv = observed_gmv = 0.0
        baseline_orders = observed_orders = 0.0
        baseline_impr = observed_impr = 0.0
        baseline_vis = observed_vis = 0.0

    order_obs_gmv, order_obs_count = _sum_orders(db, store_id, w.observe_from, w.observe_to)
    order_base_gmv, order_base_count = _sum_orders(db, store_id, w.baseline_from, w.baseline_to)
    orders_observed = order_obs_count is not None
    if orders_observed:
        observed_gmv = float(order_obs_gmv or 0)
        observed_orders = float(order_obs_count or 0)
        if order_base_count is not None:
            baseline_gmv = float(order_base_gmv or 0)
            baseline_orders = float(order_base_count or 0)
        funnel_confidence = max(funnel_confidence, 0.75)

    ads_from_table = _sum_ads(db, store_id, w.observe_from, w.observe_to)
    ads_base_table = _sum_ads(db, store_id, w.baseline_from, w.baseline_to)
    funnel_ads = float(obs["ads_spend"] or 0) if obs.get("ads_spend") else None
    funnel_ads_base = float(base["ads_spend"] or 0) if base.get("ads_spend") else None
    if ads_from_table is not None:
        observed_ads = ads_from_table
        baseline_ads = ads_base_table
        ads_source = "ad_spend_daily"
    elif funnel_ads is not None:
        observed_ads = funnel_ads
        baseline_ads = funnel_ads_base
        ads_source = "shop_funnel"
    else:
        observed_ads = None
        baseline_ads = None
        ads_source = "missing"

    baseline_ctr = (baseline_vis / baseline_impr) if baseline_impr else None
    observed_ctr = (observed_vis / observed_impr) if observed_impr else None

    baseline_cvr = (baseline_orders / baseline_vis) if baseline_vis else None
    observed_cvr = (observed_orders / observed_vis) if observed_vis else None

    kpi_confidence = funnel_confidence
    kpis = {
        "gmv": DeltaMetric(
            delta_pct=_delta_pct(baseline_gmv, observed_gmv) if kpi_confidence > 0 else None,
            value=observed_gmv,
            baseline_value=baseline_gmv,
            observed_value=observed_gmv,
            confidence=kpi_confidence if kpi_confidence > 0 else 0.0,
        ),
        "orders": DeltaMetric(
            delta_pct=_delta_pct(baseline_orders, observed_orders) if kpi_confidence > 0 else None,
            value=observed_orders,
            baseline_value=baseline_orders,
            observed_value=observed_orders,
            confidence=kpi_confidence if kpi_confidence > 0 else 0.0,
        ),
        "impressions": DeltaMetric(
            delta_pct=_delta_pct(baseline_impr, observed_impr) if kpi_confidence > 0 else None,
            value=observed_impr,
            baseline_value=baseline_impr,
            observed_value=observed_impr,
            confidence=min(0.7, kpi_confidence) if kpi_confidence > 0 else 0.0,
        ),
        "ctr": DeltaMetric(
            delta_pct=_delta_pct(baseline_ctr, observed_ctr) if kpi_confidence > 0 else None,
            value=observed_ctr,
            baseline_value=baseline_ctr,
            observed_value=observed_ctr,
            confidence=min(0.8, kpi_confidence) if kpi_confidence > 0 else 0.0,
        ),
        "cvr": DeltaMetric(
            delta_pct=_delta_pct(baseline_cvr, observed_cvr) if kpi_confidence > 0 else None,
            value=observed_cvr,
            baseline_value=baseline_cvr,
            observed_value=observed_cvr,
            confidence=min(0.8, kpi_confidence) if kpi_confidence > 0 else 0.0,
        ),
    }
    observed_rating = _avg_rating(db, store_id, w.observe_from, w.observe_to)
    baseline_rating = _avg_rating(db, store_id, w.baseline_from, w.baseline_to)
    if observed_rating is not None or baseline_rating is not None:
        kpis["rating"] = DeltaMetric(
            delta_pct=_delta_pct(baseline_rating, observed_rating),
            value=observed_rating,
            baseline_value=baseline_rating,
            observed_value=observed_rating,
            confidence=0.75,
        )

    # core items: top by orders in observe window
    stmt = (
        select(ItemFunnelDaily.item_id, func.sum(ItemFunnelDaily.orders).label("orders"))
        .join(MenuItem, MenuItem.id == ItemFunnelDaily.item_id)
        .where(MenuItem.store_id == store_id)
        .where(ItemFunnelDaily.day >= w.observe_from)
        .where(ItemFunnelDaily.day <= w.observe_to)
        .where(production_funnel_clause(ItemFunnelDaily.data_source))
        .group_by(ItemFunnelDaily.item_id)
        .order_by(func.sum(ItemFunnelDaily.orders).desc())
        .limit(5)
    )
    rows = db.execute(stmt).all()
    total_orders = sum([int(r.orders or 0) for r in rows]) or 0

    core_items: list[CoreItem] = []
    for r in rows:
        item_id = r.item_id
        item_orders = float(r.orders or 0)
        share = (item_orders / total_orders * 100.0) if total_orders else None

        # item ctr delta (baseline vs observe)
        b_stmt = (
            select(func.avg(ItemFunnelDaily.ctr).label("ctr"))
            .where(ItemFunnelDaily.item_id == item_id)
            .where(ItemFunnelDaily.day >= w.baseline_from)
            .where(ItemFunnelDaily.day <= w.baseline_to)
            .where(production_funnel_clause(ItemFunnelDaily.data_source))
        )
        o_stmt = (
            select(func.avg(ItemFunnelDaily.ctr).label("ctr"))
            .where(ItemFunnelDaily.item_id == item_id)
            .where(ItemFunnelDaily.day >= w.observe_from)
            .where(ItemFunnelDaily.day <= w.observe_to)
            .where(production_funnel_clause(ItemFunnelDaily.data_source))
        )
        b_ctr = db.execute(b_stmt).mappings().one()["ctr"]
        o_ctr = db.execute(o_stmt).mappings().one()["ctr"]
        ctr_delta = _delta_pct(float(b_ctr) if b_ctr is not None else None, float(o_ctr) if o_ctr is not None else None)

        name = item_name_map.get(item_id, "SKU")

        flags = []
        if ctr_delta is not None and ctr_delta < -8:
            flags.append("anomaly_ctr_down")
        core_items.append(CoreItem(item_id=item_id, name=name, order_share_pct=share, ctr_delta_pct=ctr_delta, flags=flags))

    # Build real competition changes from competitor snapshots & menu items
    competition_changes = _build_competition_changes(db, store_id, store)

    # Build feedback from reviews (rating themes + sentiment)
    feedback = _build_feedback(db, store_id)

    # primary problem (very rough V1)
    primary_problem = None
    if kpis["ctr"].delta_pct is not None and kpis["ctr"].delta_pct < -5:
        primary_problem = PrimaryProblem(type="store_ctr_down", confidence=0.8)
    elif kpis["cvr"].delta_pct is not None and kpis["cvr"].delta_pct < -5:
        primary_problem = PrimaryProblem(type="store_cvr_down", confidence=0.75)

    # Sensing layer proxies
    menu_items = [item for item in (store.items or []) if item.is_active]
    with_image = sum(1 for item in menu_items if item.current_version and item.current_version.image_url)
    decoration = (with_image / len(menu_items)) if menu_items else None
    avg_rating = feedback.scores.get("avg_rating")
    mid_bad = None
    if avg_rating is not None:
        # proxy: lower rating => higher mid/bad share
        mid_bad = max(0.0, min(0.45, (4.8 - float(avg_rating)) * 0.12))

    business = build_business_state(kpis)
    ops = _avg_ops(db, store_id, w.observe_from, w.observe_to)
    platform_health = build_platform_health_state(
        store_rating=float(avg_rating) if avg_rating is not None else None,
        mid_bad_review_rate=mid_bad,
        decoration_completeness=decoration,
        hero_sku_in_stock_rate=1.0,
        activity_valid=True,
        open_status="open",
        im_reply_rate=ops["im_reply_rate"],
        meal_prep_rate=ops["meal_prep_rate"],
        on_time_delivery_rate=ops["on_time_delivery_rate"],
        merchant_cancel_rate=ops["merchant_cancel_rate"],
    )
    qty_by_item = _item_qty_map(db, store_id, w.observe_from, w.observe_to)
    profit = build_profit_state(
        gross_gmv=observed_gmv,
        orders=observed_orders,
        ads_spend=observed_ads,
        baseline_gmv=baseline_gmv,
        baseline_orders=baseline_orders,
        **_aggregate_store_cost(menu_items, observed_orders, qty_by_item),
    )
    # Peer funnel proxies from watched competitors are limited in V1; leave empty unless we have CTR-like proxies later.
    benchmark = build_benchmark_state(
        store_ctr=observed_ctr,
        store_cvr=observed_cvr,
        peer_ctr_values=[],
        peer_cvr_values=[],
    )
    customer = build_customer_state(
        repurchase_rate=None,
        repurchase_delta_pct=None,
    )

    # Enrich business judgment with benchmark when available
    if benchmark.available and benchmark.judgment:
        business.judgment = f"{business.judgment} {benchmark.judgment}".strip()

    ads_days = db.execute(
        select(func.count()).select_from(AdSpendDaily).where(
            AdSpendDaily.store_id == store_id,
            AdSpendDaily.day >= w.observe_from,
            AdSpendDaily.day <= w.observe_to,
        )
    ).scalar() or 0
    funnel_days = db.execute(
        select(func.count()).select_from(ShopFunnelDaily).where(
            ShopFunnelDaily.store_id == store_id,
            ShopFunnelDaily.day >= w.observe_from,
            ShopFunnelDaily.day <= w.observe_to,
            production_funnel_clause(ShopFunnelDaily.data_source),
        )
    ).scalar() or 0
    review_count = db.execute(
        select(func.count()).select_from(ReviewFact).where(ReviewFact.store_id == store_id)
    ).scalar() or 0
    order_rows = db.execute(
        select(func.count()).select_from(OrderFact).where(OrderFact.store_id == store_id)
    ).scalar() or 0
    coverage = DataCoverage(
        funnel_days=int(funnel_days),
        ads_days=int(ads_days),
        reviews=int(review_count),
        order_rows=int(order_rows),
        items_with_cost=sum(1 for i in menu_items if i.food_cost is not None),
        synthetic_item_funnel=_has_synthetic_item_funnel(
            db, [i.id for i in menu_items], w.observe_from, w.observe_to
        ),
        ads_source=ads_source,
        ads_observed=ads_source != "missing",
        orders_observed=bool(orders_observed),
    )

    ads_summary = _build_ads_summary(db, store_id, w.observe_from, w.observe_to)

    state = StoreState(
        store=StoreInfo(
            store_id=store.id,
            name=store.name,
            category=getattr(store.merchant, "category", None),
            city=store.city,
            lng=store.longitude,
            lat=store.latitude,
        ),
        market=MarketInfo(market_type=[t for t in [store.primary_audience, store.primary_pain] if t], radius_m=store.delivery_radius_m or 1000),
        window=WindowInfo(
            from_day=w.observe_from,
            to_day=w.observe_to,
            compare_from_day=w.baseline_from,
            compare_to_day=w.baseline_to,
        ),
        kpis=kpis,
        core_items=core_items,
        competition_changes=competition_changes,
        feedback=feedback,
        primary_problem=primary_problem,
        business=business,
        platform_health=platform_health,
        profit=profit,
        benchmark=benchmark,
        customer=customer,
        data_coverage=coverage,
        ads_summary=ads_summary,
        generated_at=datetime.now(timezone.utc),
    )
    return state
