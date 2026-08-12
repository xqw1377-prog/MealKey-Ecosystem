from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.entities import (
    CompetitorMenuItem,
    CompetitorSnapshot,
    CompetitorStore,
    ItemFunnelDaily,
    MenuItem,
    ReviewFact,
    ReviewNLP,
    ShopFunnelDaily,
    Store,
    StoreCompetitorWatch,
)
from app.schemas.store_state import (
    CompetitionChange,
    CoreItem,
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
        )
        .where(ShopFunnelDaily.store_id == store_id)
        .where(ShopFunnelDaily.day >= from_day)
        .where(ShopFunnelDaily.day <= to_day)
    )
    return db.execute(stmt).mappings().one()


def _delta_pct(baseline: Optional[float], observed: Optional[float]) -> Optional[float]:
    if baseline is None or observed is None:
        return None
    if baseline == 0:
        return None
    return (observed - baseline) / baseline * 100.0


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
    return FeedbackInfo(keywords=keywords[:5], scores=scores)


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

    baseline_gmv = float(base["gmv"] or 0)
    observed_gmv = float(obs["gmv"] or 0)
    baseline_orders = float(base["orders"] or 0)
    observed_orders = float(obs["orders"] or 0)
    baseline_impr = float(base["impressions"] or 0)
    observed_impr = float(obs["impressions"] or 0)
    baseline_vis = float(base["visits"] or 0)
    observed_vis = float(obs["visits"] or 0)

    baseline_ctr = (baseline_vis / baseline_impr) if baseline_impr else None
    observed_ctr = (observed_vis / observed_impr) if observed_impr else None

    baseline_cvr = (baseline_orders / baseline_vis) if baseline_vis else None
    observed_cvr = (observed_orders / observed_vis) if observed_vis else None

    kpis = {
        "gmv": DeltaMetric(
            delta_pct=_delta_pct(baseline_gmv, observed_gmv),
            value=observed_gmv,
            baseline_value=baseline_gmv,
            observed_value=observed_gmv,
            confidence=0.9,
        ),
        "orders": DeltaMetric(
            delta_pct=_delta_pct(baseline_orders, observed_orders),
            value=observed_orders,
            baseline_value=baseline_orders,
            observed_value=observed_orders,
            confidence=0.9,
        ),
        "impressions": DeltaMetric(
            delta_pct=_delta_pct(baseline_impr, observed_impr),
            value=observed_impr,
            baseline_value=baseline_impr,
            observed_value=observed_impr,
            confidence=0.7,
        ),
        "ctr": DeltaMetric(
            delta_pct=_delta_pct(baseline_ctr, observed_ctr),
            value=observed_ctr,
            baseline_value=baseline_ctr,
            observed_value=observed_ctr,
            confidence=0.8,
        ),
        "cvr": DeltaMetric(
            delta_pct=_delta_pct(baseline_cvr, observed_cvr),
            value=observed_cvr,
            baseline_value=baseline_cvr,
            observed_value=observed_cvr,
            confidence=0.8,
        ),
    }

    # core items: top by orders in observe window
    stmt = (
        select(ItemFunnelDaily.item_id, func.sum(ItemFunnelDaily.orders).label("orders"))
        .join(MenuItem, MenuItem.id == ItemFunnelDaily.item_id)
        .where(MenuItem.store_id == store_id)
        .where(ItemFunnelDaily.day >= w.observe_from)
        .where(ItemFunnelDaily.day <= w.observe_to)
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
        )
        o_stmt = (
            select(func.avg(ItemFunnelDaily.ctr).label("ctr"))
            .where(ItemFunnelDaily.item_id == item_id)
            .where(ItemFunnelDaily.day >= w.observe_from)
            .where(ItemFunnelDaily.day <= w.observe_to)
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
    platform_health = build_platform_health_state(
        store_rating=float(avg_rating) if avg_rating is not None else None,
        mid_bad_review_rate=mid_bad,
        decoration_completeness=decoration,
        hero_sku_in_stock_rate=1.0,
        activity_valid=True,
        open_status="open",
    )
    profit = build_profit_state(
        gross_gmv=observed_gmv,
        orders=observed_orders,
        baseline_gmv=baseline_gmv,
        baseline_orders=baseline_orders,
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
        generated_at=datetime.now(timezone.utc),
    )
    return state
